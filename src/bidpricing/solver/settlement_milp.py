"""严重不平衡报价结算调整的 Phase 2 MILP。

当前项目条款：基准=最高限价、严重低价阈值=50%、工程量偏差阈值=15%。
仅对 ``q1 < 0.85*q0`` 的项目引入二元变量：

* y=0：报价不低于 50% cap，收入为 q1*p；
* y=1：报价低于 50% cap，收入为
  ``0.85*q0*p - (0.85*q0-q1)*cap``。

通过 w=y*p 的 McCormick 线性化得到 MILP。增加量项在本条款下仍为 q1*p，
不需要额外二元变量。无最高限价项无法以 CAP 判断严重低价，保留普通收入并输出警告。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..contracts.pricing_card import ResolvedParameters, resolve_parameters
from ..validation.unbalanced import (
    VALIDITY,
    UnbalancedPolicyError,
    parse_unbalanced_policy,
    settlement_revenue_adjusted,
)
from .compiler import compile_model
from .formulation import (
    Column,
    ConstantCheck,
    DeferredConstraint,
    Formulation,
    Row,
    compute_lb_c5,
    merged_lower,
)
from .instance import Phase1Instance, ROLE_OPTIMIZABLE


@dataclass(frozen=True)
class SettlementMilpBuild:
    formulation: Formulation
    warnings: tuple[str, ...] = ()


def low_price_big_m(upper: float, lower: float, threshold: float) -> float:
    """严重低价二元变量 y 的收紧大 M（pa06 内核优化）。

    y=1 ⟺ ``p <= threshold`` 的约束对是：``p + M·y <= threshold + M``
    （y=1 时 p<=threshold）与 ``p + M·y >= threshold``（y=0 时 p>=threshold）。
    两条约束同时成立的最小安全 M 是：

    * 约束 1 要求 ``M >= upper - threshold``（y=0 时不得切掉高价可行域）；
    * 约束 2 要求 ``M >= threshold - lower``（y=1 时不得切掉低价可行域）。

    二者取大即为最紧合法值（pa06 前取 ``max(upper-lower, upper, 1.0)`` 过松：
    默认 0.5~1.0·cap 区间下收紧前 M≈cap，收紧后 M≈0.5·cap，数值病态风险更低）。
    加极小量防止退化 ``upper==lower==threshold`` 时 M=0 把两个分支压成单点。
    """
    return max(float(upper) - threshold, threshold - float(lower), 1e-9)


#: 目标函数的税口径（实现侧常量）。**必须**等于 ``config/profit_bridge_spec.json``
#: 的 ``tax_caliber_of_objective``；由 PB-07 跨层对账钉住（声明 ↔ 实现，禁各写一份）。
OBJECTIVE_CALIBER = "EXCL_VAT"


def objective_revenue_factor(vat_rate: float) -> float:
    """目标函数**收入侧**的税口径折算系数——本口径的**唯一提供者**。

    ``config/profit_bridge_spec.json`` 声明 ``tax_caliber_of_objective = EXCL_VAT``，
    其 binding 原文：*「报价 p 与成本 c 两侧同为**不含增值税**口径……故目标函数本身
    不含增值税」*。因此收入侧**不得**再乘 ``(1+vat_rate)`` 折算为含税口径——恒返回 1.0。

    ★ 为什么单列一个函数而不是内联 ``1.0``：这样「声明口径（报告层）↔ 实现口径
    （求解层）」才能被 PB-07 机械对账。内联常量无处可查，口径错层只能靠读代码发现。

    ★ 历史缺陷（ADR-0035）：本函数返回 ``1.0 + vat_rate`` 的旧实现把结算收入折算为
    含税，与 H-002 换算后的**不含税**成本相减 ⇒ 目标函数成为混合口径，报告利润
    虚增 ``vat_rate × Σ结算收入``（= 应交增值税）。因收入侧 P 依赖项被同一正常数
    因子缩放、而 ``c_i·q1`` 与 p 无关，**最优解（报价分配）不受影响**，只有报告值错。
    """
    return 1.0


def build_settlement_adjustment_formulation(
    instance: Phase1Instance,
    *,
    clause: Mapping[str, Any],
    vat_rate: float,
    eps_price: float = 1e-9,
    resolution: float = 0.01,
    floor_by_id: Mapping[str, float] | None = None,
) -> SettlementMilpBuild:
    """构造结算调整 MILP。当前只接受 VALIDITY 之外的结算调整条款。

    目标口径为**不含增值税（EXCL_VAT）**，与 ``config/profit_bridge_spec.json``
    的 ``tax_caliber_of_objective`` 声明一致：求解器单价 ``p_i``、最高限价 ``cap``
    与成本 ``c_i`` **三者同为不含税口径**，收入与成本直接相减，不再做含税折算。
    成本侧的不含税口径由 H-002（``validation.cost_basis``）在入口完成换算。
    """
    policy = parse_unbalanced_policy(clause)
    if policy is None or not policy.enabled:
        raise UnbalancedPolicyError("结算调整 MILP 要求 enabled=true")
    if policy.mechanism != "SETTLEMENT_ADJUSTMENT":
        raise UnbalancedPolicyError("该构造器只处理 SETTLEMENT_ADJUSTMENT")
    if policy.reference != "CAP":
        raise UnbalancedPolicyError("当前 MILP 只支持 reference=CAP")
    if instance.B is None:
        raise UnbalancedPolicyError("实例缺少竞争预算 B")

    P_ref = float(instance.P_star) if instance.P_star is not None else float(instance.B)
    lb_c5 = compute_lb_c5(P_ref, eps_price, resolution)
    if vat_rate < 0:
        raise UnbalancedPolicyError("结算调整 MILP 增值税率不得为负")
    # 收入侧税口径折算系数（唯一提供者，见 objective_revenue_factor 的说明）
    revenue_factor = objective_revenue_factor(vat_rate)
    items = tuple(i for i in instance.items if i.role == ROLE_OPTIMIZABLE)
    variables: list[Column] = []
    rows: list[Row] = []
    c1: list[tuple[str, float]] = []
    warnings: list[str] = []
    objective_constant = 0.0

    for item in items:
        if item.q0 is None or item.q1_point is None or item.q0 <= 0:
            raise UnbalancedPolicyError(f"{item.item_id}: q0/q1 缺失或 q0<=0")
        lower = merged_lower(item, lb_c5, floor_by_id)
        if lower is None:
            raise UnbalancedPolicyError(f"{item.item_id}: 单价下界不可计算")
        upper = item.U
        q0, q1 = float(item.q0), float(item.q1_point)
        cap = None if item.cap is None else float(item.cap)
        if cap is None:
            warnings.append(f"{item.item_id}:无最高限价，无法按 CAP 判断严重低价，按普通结算收入处理")
        if upper is None and cap is not None:
            upper = cap

        # 基准收入系数：当前条款在非严重低价区间为 q1*p。
        variables.append(Column("p", item.item_id, "CONTINUOUS", lower, upper, q1 * revenue_factor,
                                ("LP", "MILP"),
                                note="结算调整 MILP 单价变量（收入侧税口径系数见 objective_revenue_factor）"))
        c1.append((f"p_{item.item_id}", q0))
        rows.append(Row("C3/C4/C5", "BOX_LOWER", ">=", lower,
                        ((f"p_{item.item_id}", 1.0),), "eps_price",
                        ("L", "eps_price", "P*"), scope="merged"))
        if upper is not None:
            rows.append(Row("C2", "BOX_UPPER", "<=", upper,
                            ((f"p_{item.item_id}", 1.0),), "eps_price",
                            ("U", "cap"), scope="N_cap"))

        # 只有减量超过15%的项目，严重低价时才改变 p 的斜率和常量。
        lower_q = 0.85 * q0
        delta = lower_q - q1
        if cap is None or delta <= 0:
            continue
        if upper is None:
            raise UnbalancedPolicyError(f"{item.item_id}: 需要 CAP 判定但无有限上界")
        threshold = 0.5 * cap
        M = low_price_big_m(upper, lower, threshold)
        y = f"y_{item.item_id}"
        w = f"w_{item.item_id}"
        variables.append(Column("y", item.item_id, "BINARY", 0.0, 1.0, -delta * cap * revenue_factor,
                                ("MILP",), note="严重低价状态：1=报价低于50%最高限价"))
        variables.append(Column("w", item.item_id, "CONTINUOUS", 0.0, float(upper),
                                delta * revenue_factor, ("MILP",), note="w=y*p 线性化变量（收入侧税口径系数同上）"))
        # y=1 => p <= 0.5 cap；y=0 => p >= 0.5 cap。
        rows.append(Row("C13", "MILP_BINARY", "<=", threshold + M,
                        ((f"p_{item.item_id}", 1.0), (y, M)), "0（整数）",
                        ("cap", "unbalanced_tolerance", "y"),
                        detail="p <= 0.5·cap + M(1-y)"))
        rows.append(Row("C13", "MILP_BINARY", ">=", threshold,
                        ((f"p_{item.item_id}", 1.0), (y, M)), "0（整数）",
                        ("cap", "unbalanced_tolerance", "y"),
                        detail="p >= 0.5·cap·(1-y)（等价移项形式）"))
        rows.append(Row("C13.w1", "LINEAR_INEQ", "<=", 0.0,
                        ((w, 1.0), (y, -float(upper))), "0（整数）",
                        ("p", "y", "U"), detail="w <= U·y"))
        rows.append(Row("C13.w2", "LINEAR_INEQ", "<=", 0.0,
                        ((w, 1.0), (f"p_{item.item_id}", -1.0)), "eps_price",
                        ("p", "w"), detail="w <= p"))
        rows.append(Row("C13.w3", "LINEAR_INEQ", ">=", -float(upper),
                        ((w, 1.0), (f"p_{item.item_id}", -1.0), (y, float(upper))), "eps_price",
                        ("p", "y", "w", "U"), detail="w >= p-U(1-y)"))

    rows.insert(0, Row("C1", "EQUALITY", "==", float(instance.B), tuple(c1),
                       "eps_solver", ("q0", "P*_competitive"), scope="C1_scope"))
    objective_constant -= sum(
        float(i.c_i) * float(i.q1_point)
        for i in items if i.c_i is not None and i.q1_point is not None
    )
    return SettlementMilpBuild(
        formulation=Formulation(
            variables=tuple(variables), rows=tuple(rows), constant_checks=(),
            deferred=(DeferredConstraint("C13", "MILP_BINARY", "T04-05",
                                         "结算调整条款已进入 Phase 2 MILP"),),
            objective_sense="MAXIMIZE", objective_constant=objective_constant,
            objective_expr="Z = Σ settlement_revenue_adjusted(p_i) − Σ c_i·q1_i （EXCL_VAT：p_i/cap/c_i 三者同口径，不含增值税）",
            solver_form="MILP", lb_c5=lb_c5, active=("C13",),
            box_notes=tuple(warnings), source=instance.source,
            objective_caliber=OBJECTIVE_CALIBER,
        ),
        warnings=tuple(warnings),
    )


def settlement_adjusted_profit(
    instance: Phase1Instance,
    prices: Mapping[str, float],
    *,
    clause: Mapping[str, Any],
    vat_rate: float,
) -> float:
    """独立复算结算调整后的利润（**不含增值税 / EXCL_VAT**）。

    求解器单价 ``p_i``、最高限价 ``cap`` 与成本单价 ``c_i`` **三者同口径为不含税**：
    ``cap``/``p`` 由 ``compute_P_competitive`` 剔税得到（GB/T 50500-2024 2.0.8），
    ``c_i`` 由 H-002（``validation.cost_basis``）在入口换算为不含税有效成本。
    收入与成本直接相减，不再乘 ``(1+vat_rate)``——见 ``objective_revenue_factor``。

    本函数是 MILP 目标函数的**独立复算**（T04-08 纪律）：必须与构建器得到同一
    口径与同一数值，否则 ``check_solution`` 的闭合检查会立刻暴露。
    """
    policy = parse_unbalanced_policy(clause)
    if policy is None or policy.mechanism != "SETTLEMENT_ADJUSTMENT" or policy.reference != "CAP":
        raise UnbalancedPolicyError("结算利润复算只支持 CAP + SETTLEMENT_ADJUSTMENT")
    if vat_rate < 0:
        raise UnbalancedPolicyError("结算利润复算的增值税率不得为负")
    revenue_factor = objective_revenue_factor(vat_rate)
    total = 0.0
    for item in instance.items:
        if item.role != ROLE_OPTIMIZABLE:
            continue
        if item.q0 is None or item.q1_point is None or item.c_i is None or item.cap is None:
            raise UnbalancedPolicyError(f"{item.item_id}: 结算利润复算字段缺失")
        revenue = settlement_revenue_adjusted(item.q0, item.q1_point,
                                               float(prices[item.item_id]),
                                               item.cap)
        total += revenue * revenue_factor - float(item.c_i) * float(item.q1_point)
    return total

