"""T04-02A LP 形式化的实现侧：把实例编译成**求解器无关**的 LP 词汇。

**本模块不做建模**。它只回答「模型长什么样」——变量表、目标系数、逐条约束的
系数与右端、求解器形态——并把结果与受控制品
``config/lp_formulation_spec.json`` 逐条对账。真正的「翻译成 PuLP 对象」是
T04-02B，对接 HiGHS 是 T04-02C。

这样切分的理由：如果形式化与建模在同一处，「制品说什么」与「实现做什么」
就永远无法分开检视，T04-02B 的「无手写约束」也就无从验证。本模块产出的
:class:`Formulation` 就是那个可被逐条比对的对象。

四条判据的写法各有一个坑，都已在实现里避开：

* **F-02 必须跨来源**：解析式 ``q0_i · r_eff_i`` 对数值差分 ``∂R_i/∂p_i``。
  首跑即抓到真分叉（SEGMENT ∧ 区间内 ∧ alpha≠0），见制品
  ``objective.linearity.marginal_verification``。两侧同源则此 bug 永不可见。
* **F-06 必须取「小 P* 探针」并由实现取值**：若判据把期望值在手边重算一遍，
  它就退化成恒真式。故 ``lb_c5`` 由 :func:`build_formulation` 报出，
  判据只比较它与期望值。
* **F-08 判「约束面上的恒定」而非「函数常数」**：R_pc 作为无约束函数偏导非零，
  只有落在可行域上才恒定。且必须用**两组不同的 p 向量**分别求和——写成
  ``B/den`` 两次是同一个数的复制，同样退化成恒真式。
* **F-05 要检实现侧的 C2 行数**：只检查制品文本会漏掉「实现给不限价项偷偷加了
  上界」这类错误。
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..contracts.pricing_card import (
    ResolvedParameters,
    compute_r_eff,
    settlement_revenue,
)
from .instance import (
    PRICE_RESOLUTION,
    ROLE_OPTIMIZABLE,
    Phase1Instance,
    Phase1Item,
    Phase1Params,
)

SPEC_FILENAME = "lp_formulation_spec.json"

#: 本层的状态域——全局 ``Status`` 只有四态，而这里需要 **SKIP**：缺实例时
#: 「没检查」必须与「检查过且通过」可区分，否则漏检会被读成通过。
#: SKIP 刻意不进闸门聚合（它不改变任何结论），但也绝不等于 PASS。
STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_SKIP = "SKIP"

#: 求解器内可执行的形式——这些条目必须给出非空且可解析的 coefficient_sources。
LP_FORMS: tuple[str, ...] = (
    "EQUALITY",
    "BOX_UPPER",
    "BOX_LOWER",
    "LINEAR_INEQ",
    "MILP_BINARY",
)

#: 非 LP 形式——这些条目必须给出**理由字段**，否则「不建模」会被读成「忘了建模」。
NON_LP_FORMS: tuple[str, ...] = (
    "CONSTANT_CHECK",
    "NONLINEAR_DEFERRED",
    "NOT_A_BID_CONSTRAINT",
    "DISCRETE_CHECK",
)

#: 非 LP 形式对应的理由字段名。
NON_LP_REASON_FIELD: dict[str, str] = {
    "CONSTANT_CHECK": "why_not_lp",
    "NONLINEAR_DEFERRED": "why_deferred",
    "NOT_A_BID_CONSTRAINT": "why_not_modeled",
    "DISCRETE_CHECK": "why_not_lp",
}

#: F-06 的探针：必须覆盖 ``eps_price·P* < resolution`` 的区间，否则判据退化。
P_STAR_PROBES: tuple[float, ...] = (1.0e3, 1.0e6, 1.0e9)

#: C7 Big-M 的退化阈值。两侧的退化语义**不同**，不可合并：
#:   ``M_lo = c_i − lb_i ≤ 0`` ⇒ 恒不亏损（z_i 固定 0，不占 N_max 名额）；
#:   ``M_hi = ub_i − c_i + eps ≤ 0`` ⇒ 恒亏损（z_i 固定 1，**占**一个名额）。
BIG_M_FLOOR_EPS = 1e-12


class FormulationError(ValueError):
    """实例不足以构造形式化（缺 C1 右端、q0 缺失等）。"""


@dataclass(frozen=True)
class FormulationCheck:
    """单条 F 判据的结果。

    状态用**字符串**而非全局 :class:`bidpricing.states.Status`：后者是四态枚举，
    不接受 SKIP，而「缺实例跳过」必须能与 PASS 区分开。强制塞进四态会导致
    「没检查」被读成「检查过」——正是本项目反复出现的失效模式。
    """

    scope: str
    item: str
    status: str
    reason: str
    actual: object | None = None
    expected: object | None = None
    delta: object | None = None

    @property
    def blocks_progress(self) -> bool:
        return self.status in (STATUS_FAIL, STATUS_BLOCKED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "item": self.item,
            "status": self.status,
            "reason": self.reason,
            "actual": self.actual,
            "expected": self.expected,
            "delta": self.delta,
        }


# ---------------------------------------------------------------------------
# 词汇对象
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    """一列决策变量。``upper is None`` 表示 ``+inf``（不限价项），不是缺数据。"""

    family: str          # "p" | "s" | "z"
    item_id: str
    kind: str            # CONTINUOUS | BINARY
    lower: float | None
    upper: float | None
    objective_coeff: float
    present_in: tuple[str, ...] = ("LP", "MILP")
    note: str = ""

    @property
    def symbol(self) -> str:
        return f"{self.family}_{self.item_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "family": self.family,
            "item_id": self.item_id,
            "kind": self.kind,
            "lower": self.lower,
            "upper": self.upper,
            "objective_coeff": self.objective_coeff,
            "present_in": list(self.present_in),
            "note": self.note,
        }


@dataclass(frozen=True)
class Row:
    """一行约束。``rhs is None`` 表示该形式没有单一右端（如汇总行）。

    ``aux`` 承载**该行的推导中间量**（如 C7 的 M_lo / M_hi / ub_i^eff）。
    它存在的理由是让「取值是否满足该形式的恒真条件」成为可独立复算的事——
    否则编译器只能把 M 当黑箱复制，而 M 取错恰恰是本层最隐蔽的失效模式
    （切掉可行解但不违反任何语法约束，见 compiler.check_compiled 的 CC-08）。
    """

    constraint_id: str
    form: str
    sense: str           # "==" | "<=" | ">="
    rhs: float | None
    coefficients: tuple[tuple[str, float], ...]
    tolerance: str
    sources: tuple[str, ...]
    scope: str = ""
    detail: str = ""
    aux: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "form": self.form,
            "sense": self.sense,
            "rhs": self.rhs,
            "coefficients": [{"symbol": s, "coeff": c} for s, c in self.coefficients],
            "tolerance": self.tolerance,
            "sources": list(self.sources),
            "scope": self.scope,
            "detail": self.detail,
            "aux": dict(self.aux),
        }

    def aux_get(self, key: str) -> Any:
        for k, v in self.aux:
            if k == key:
                return v
        return None


@dataclass(frozen=True)
class ConstantCheck:
    """在可行域上恒定的约束——前置体检项，不是 LP 约束。"""

    constraint_id: str
    metric: str
    value: float | None
    passes: bool | None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "metric": self.metric,
            "value": self.value,
            "passes": self.passes,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DeferredConstraint:
    """形式未定/未建模的约束——显式挂账，不静默丢弃。"""

    constraint_id: str
    form: str
    owner_task: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "form": self.form,
            "owner_task": self.owner_task,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Formulation:
    """求解器无关的 LP 形式化结果。"""

    variables: tuple[Column, ...]
    rows: tuple[Row, ...]
    constant_checks: tuple[ConstantCheck, ...]
    deferred: tuple[DeferredConstraint, ...]
    objective_sense: str
    objective_constant: float
    objective_expr: str
    solver_form: str
    lb_c5: float
    active: tuple[str, ...]
    box_notes: tuple[str, ...] = ()
    source: str = ""

    @property
    def price_columns(self) -> tuple[Column, ...]:
        return tuple(c for c in self.variables if c.family == "p")

    @property
    def n_vars(self) -> int:
        return len(self.variables)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    def rows_of(self, constraint_id: str) -> tuple[Row, ...]:
        return tuple(r for r in self.rows if r.constraint_id == constraint_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_sense": self.objective_sense,
            "objective_expr": self.objective_expr,
            "objective_constant": self.objective_constant,
            "solver_form": self.solver_form,
            "lb_c5": self.lb_c5,
            "active_soft_constraints": list(self.active),
            "n_vars": self.n_vars,
            "n_rows": self.n_rows,
            "variables": [c.to_dict() for c in self.variables],
            "rows": [r.to_dict() for r in self.rows],
            "constant_checks": [c.to_dict() for c in self.constant_checks],
            "deferred": [d.to_dict() for d in self.deferred],
            "box_notes": list(self.box_notes),
            "source": self.source,
        }


@dataclass(frozen=True)
class MarginalCheck:
    """F-02 的单项对账结果：解析边际 vs 数值差分。"""

    item_id: str
    case: str
    analytic: float
    numeric: float

    @property
    def ok(self) -> bool:
        scale = max(abs(self.analytic), abs(self.numeric), 1.0)
        return abs(self.analytic - self.numeric) <= 1e-6 * scale

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "case": self.case,
            "analytic": self.analytic,
            "numeric": self.numeric,
            "ok": self.ok,
        }


# ---------------------------------------------------------------------------
# 形式化构造
# ---------------------------------------------------------------------------


def _f(x: Any) -> float | None:
    """``None`` / NaN / ±inf → ``None``；其余转 float。

    ``None`` 在求解层的语义是「缺数据」，与「不限价」（由 ``U`` 字段的存在性
    表达）不同。两者必须机器可区分（ADR-0004）。
    """
    if x is None:
        return None
    v = float(x)
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v


def c1_right_hand_side(instance: Phase1Instance) -> float:
    """C1 的右端 = 可竞争部分的锁定预算（``P*_competitive``）。

    ``instance.B`` 就是它。**不接受** ``Σ p_i q0_i`` 之类由报价向量算出的替代
    值——那会把 C1 变成恒真式（制品 C1.rhs_source；ADR-0014）。
    """
    if instance.B is None:
        raise FormulationError(
            "实例未给出 B（C1 右端 = P*_competitive），形式化不可构造。"
            "缺 C1 右端时不得退回任何默认值——那会把『没给』算成『给了 0』。"
        )
    return float(instance.B)


def compute_lb_c5(P_ref: float, eps_price: float, resolution: float) -> float:
    """C5 的 LP 下界。

    schema 写的是 ``p_i >= eps_price``，而 ``eps_price`` 是**相对量**（×P*）。
    P* = 1e6 时它只有 1e-3 元，舍入到 0.01 后变成零报价——**提交的报价会违反
    C5**。故 LP 下界必须与报价分辨率取大。
    """
    return max(float(eps_price) * float(P_ref), float(resolution))


def build_formulation(
    instance: Phase1Instance,
    resolved: ResolvedParameters,
    *,
    eps_abs: float = 0.01,
    eps_price: float = 1e-9,
    resolution: float = PRICE_RESOLUTION,
    theta: float | None = None,
    n_max: float | None = None,
    d_max: float | None = None,
    r_min: float | None = None,
    z_min: float | None = None,
    pi_target: float | None = None,
    floor_by_id: Mapping[str, float] | None = None,
    source: str = "",
) -> Formulation:
    """把实例编译为 :class:`Formulation`。

    只做「把已知量填进形式」这件事：**不引入求解器依赖，不做优化，不做诊断**。
    """
    B = c1_right_hand_side(instance)
    P_ref = float(instance.P_star) if instance.P_star is not None else B
    lb_c5 = compute_lb_c5(P_ref, eps_price, resolution)

    active = tuple(sorted({c.upper() for c in instance.active_soft_constraints}))
    milp = "C7" in active

    opt_items = tuple(i for i in instance.items if i.role == ROLE_OPTIMIZABLE)

    variables: list[Column] = []
    rows: list[Row] = []
    box_notes: list[str] = []
    c1_coefs: list[tuple[str, float]] = []
    #: C7 中被 Big-M 退化判定**固定**的 z_i：(item_id, 固定值, 理由)。
    #: 固定为 0 的项不进 Σz（不占名额）；固定为 1 的项**占一个名额**——
    #: 后者是「亏损项数上限」的实质扣减，漏掉会把 N_max 放宽（见 z_quota_note）。
    z_fixed: list[tuple[str, int, str]] = []

    # ---- 第一遍：逐项标量。必须先扫完全体再生成行，因为「不限价项的
    #      有效上界」由 C1 与**其余各项的下界**共同决定（见 _effective_upper）。
    prepared: list[dict[str, Any]] = []
    for item in opt_items:
        prepared.append(
            {
                "item": item,
                "q0": _f(item.q0),
                "q1": _f(item.q1_point),
                "c_i": _f(item.c_i),
                "lb": _merged_lower(item, lb_c5, floor_by_id),
                "ub": _f(item.U),            # None = 不限价（合法语义）
                "r_eff": instance.r_eff(item, resolved),
            }
        )

    # C1 的载量下界：min Σ p_j q0_j = Σ lb_j q0_j（逐项 p_j ≥ lb_j）
    lower_load = 0.0
    for rec in prepared:
        if rec["lb"] is not None and rec["q0"] is not None and rec["q0"] > 0:
            lower_load += float(rec["lb"]) * float(rec["q0"])

    def _effective_upper(rec: Mapping[str, Any], own_lb: Any) -> float | None:
        """C2 给 ``U_i``；不限价项退到 C1 的**隐式**上界。

        ``p_i q0_i ≤ B − Σ_{j≠i} p_j q0_j ≤ B − Σ_{j≠i} lb_j q0_j``，
        故 ``ub_i^C1 = (B − Σ_{j≠i} lb_j q0_j) / q0_i`` 是有效上界（任何可行解
        都满足它）。返回 ``None`` 表示推不出有限上界——注意这**不是**「不限价」
        的意思，而是「第三式的恒真条件无法满足」。

        为什么需要它：C7 第三式在 ``z_i = 0`` 处必须恒真，而恒真要求 M 覆盖
        **上界**（``ub_i − c_i + eps``）。不限价项没有有限上界时，若只报一个
        「不限价」而不给替代，第三式要么不可形式化、要么被悄悄写成一个会切掉
        可行解的 M。
        """
        ub = rec["ub"]
        if ub is not None:
            return float(ub)
        q0 = rec["q0"]
        if q0 is None or q0 <= 0 or own_lb is None:
            return None
        others = lower_load - float(own_lb) * float(q0)
        return (B - others) / float(q0)

    for rec in prepared:
        item = rec["item"]
        q0, q1, c_i = rec["q0"], rec["q1"], rec["c_i"]
        lb, ub, r_eff = rec["lb"], rec["ub"], rec["r_eff"]

        # ∂Z/∂p_i = q0_i · r_eff_i。**不是 q1_i · r_eff_i。**
        # Z = Σ (R_i − c_i q1_i)，而 c_i q1_i 与 p 无关 ⇒ ∂Z/∂p_i = ∂R_i/∂p_i
        # = q0_i · r_eff_i（这正是 r_eff 的定义式，F-02 检它）。
        # 2026-09-17 修正：原实现用 q1·r_eff，等价于把排序键又乘了一遍 r_i
        # ——因为 LP 的排序键是 (目标系数)/(C1 系数) = (q1·r_eff)/q0 = r_i·r_eff。
        # 恰是 T04-00 EC-2 警告过的失效模式：解满足全部约束但**次优**，
        # 不触发任何可行性检查。由 CC-07（编译侧 vs 业务式代回复核）抓到。
        coeff = 0.0 if (q0 is None or r_eff is None) else float(q0) * float(r_eff)

        variables.append(
            Column(
                family="p",
                item_id=item.item_id,
                kind="CONTINUOUS",
                lower=lb,
                upper=ub,
                objective_coeff=coeff,
                present_in=("LP", "MILP"),
                note="" if ub is not None else "不限价（ALLOW_EMPTY_NO_CAP）",
            )
        )

        # ---- C1 的左端系数（汇总成一条等式，作用域 = C1_scope）----------
        if item.in_c1_scope:
            if q0 is None or q0 <= 0:
                raise FormulationError(
                    f"{item.item_id}: q0 缺失或 ≤ 0，C1 左端不可构造"
                )
            c1_coefs.append((f"p_{item.item_id}", float(q0)))

        # ---- 箱型：逐项一行（ub / lb 逐项不同）-------------------------
        if ub is not None:
            rows.append(
                Row("C2", "BOX_UPPER", "<=", ub,
                    ((f"p_{item.item_id}", 1.0),),
                    "eps_price", ("U", "cap"), scope="N_cap")
            )
        if lb is not None:
            rows.append(
                Row("C3/C4/C5", "BOX_LOWER", ">=", lb,
                    ((f"p_{item.item_id}", 1.0),),
                    "eps_price",
                    ("L", "floor", "eps_price", "P*", "rounding.resolution"),
                    scope="merged",
                    detail="合并下界；逐条诊断须用各自原始阈值复算")
            )
        if lb is not None and ub is not None and lb > ub:
            box_notes.append(
                f"{item.item_id}: 箱型局部不可行（lb={lb!r} > ub={ub!r}）"
                "⇒ 须在建模前判 BLOCKED，不得交给求解器报泛化 infeasible"
            )

        # ---- C6 亏损缺口辅助变量与逐项行 -------------------------------
        c_i = _f(item.c_i)
        if "C6" in active and c_i is not None:
            variables.append(
                Column("s", item.item_id, "CONTINUOUS", 0.0, None, 0.0,
                       ("LP", "MILP"), note="C6 亏损缺口 max(c_i − p_i, 0)")
            )
            rows.append(
                Row("C6.s", "LINEAR_INEQ", ">=", c_i,
                    ((f"s_{item.item_id}", 1.0), (f"p_{item.item_id}", 1.0)),
                    "eps_total", ("c_i", "q1_point", "theta", "P*"),
                    detail="s_i + p_i >= c_i  即 s_i >= c_i − p_i")
            )

        # ---- C7 二元指示与双向 Big-M -----------------------------------
        # 两式的「恒真」条件**不同**，故 M 必须分开取：
        #   第二式（z=1 处须恒真）⇒ M_lo ≥ c_i − lb_i          —— 覆盖**下界**
        #   第三式（z=0 处须恒真）⇒ M_hi ≥ ub_i^eff − c_i + eps —— 覆盖**上界**
        # 2026-09-17 修正：原实现两式共用 M_lo = c_i − lb_i。当
        # ub_i > 2c_i − eps − lb_i 时，第三式在 z = 0 处把 p_i 压到
        # c_i − eps + M_lo，切掉 [c_i, ub_i] 的大部分区间——业务侧判可行的解
        # 被编译侧判违反，求解器随即误报 infeasible 或返回次优解，**且不报错**。
        # 定界依据是两式各自的恒真条件，不是「取个大数就行」。
        if milp and c_i is not None:
            m_lo = None if lb is None else float(c_i) - float(lb)
            ub_eff = _effective_upper(rec, lb)
            m_hi = (
                None if ub_eff is None
                else float(ub_eff) - float(c_i) + float(resolution)
            )
            degenerate_lo = m_lo is not None and m_lo <= BIG_M_FLOOR_EPS
            degenerate_hi = m_hi is not None and m_hi <= BIG_M_FLOOR_EPS

            if degenerate_lo:
                z_fixed.append(
                    (item.item_id, 0, f"M_lo = c_i − lb_i = {m_lo!r} ≤ 0 ⇒ 恒不亏损")
                )
            elif degenerate_hi:
                z_fixed.append(
                    (item.item_id, 1, f"M_hi = ub_i − c_i + eps = {m_hi!r} ≤ 0 ⇒ 恒亏损")
                )

            z_note = (
                "z_i 固定 0（恒不亏损，不占名额）"
                if degenerate_lo else
                "z_i 固定 1（恒亏损，占一个名额）"
                if degenerate_hi else
                f"M_lo = {m_lo!r} / M_hi = {m_hi!r}"
            )
            # 退化项的 z **必须固定界**，不能只把它从行里拿掉：留着 [0,1] 的
            # 自由 z 会让 MILP 出现一个目标系数为 0、不受任何约束的变量
            # ⇒ 多最优解，「亏损项数」的报告值随求解器心情变化。
            if degenerate_lo:
                z_lo, z_up = 0.0, 0.0
            elif degenerate_hi:
                z_lo, z_up = 1.0, 1.0
            else:
                z_lo, z_up = 0.0, 1.0
            variables.append(
                Column("z", item.item_id, "BINARY", z_lo, z_up, 0.0,
                       ("MILP",), note=z_note)
            )

            if not (degenerate_lo or degenerate_hi):
                rows.append(
                    Row("C7.lower", "MILP_BINARY", ">=", float(c_i),
                        ((f"p_{item.item_id}", 1.0),
                         (f"z_{item.item_id}", float(m_lo))),
                        "0（整数）",
                        ("c_i", "N_max", "U", "rounding.resolution"),
                        detail=f"p_i + M_lo·z_i >= c_i（M_lo = c_i − lb_i = {m_lo!r}）"
                               "  z=0 ⇒ 不亏损",
                        aux=(("M_lo", float(m_lo)), ("lb_i", float(lb)))
                            if lb is not None else (("M_lo", float(m_lo)),))
                )
                if m_hi is None:
                    box_notes.append(
                        f"{item.item_id}: 第三式的恒真条件不可满足——"
                        "不限价且 C1 推不出有限上界，M_hi 不存在 ⇒ 须判 BLOCKED，"
                        "**不得**退回 M_lo（那会切掉可行解）"
                    )
                else:
                    ub_src = (
                        "C2:U" if _f(item.U) is not None
                        else "C1:implicit"
                    )
                    rows.append(
                        Row("C7.upper", "MILP_BINARY", "<=",
                            float(c_i) - float(resolution) + float(m_hi),
                            ((f"p_{item.item_id}", 1.0),
                             (f"z_{item.item_id}", float(m_hi))),
                            "0（整数）",
                            ("c_i", "N_max", "U", "rounding.resolution"),
                            detail=f"p_i + M_hi·z_i <= c_i − eps + M_hi"
                                   f"（M_hi = ub_i^eff − c_i + eps = {m_hi!r}，"
                                   f"ub_i^eff 来源 = {ub_src}）"
                                   "  z=1 ⇒ p_i < c_i",
                            aux=(
                                ("M_hi", float(m_hi)),
                                ("ub_eff", float(ub_eff)),
                                ("ub_eff_source", ub_src),
                                ("eps_res", float(resolution)),
                                ("c_i", float(c_i)),
                            )
                        )
                    )

        # ---- C8 逐项地板（c_i = 0 项退化，须显式处理）------------------
        if "C8" in active and d_max is not None and c_i is not None:
            rows.append(
                Row("C8", "BOX_LOWER", ">=", c_i * (1.0 - float(d_max)),
                    ((f"p_{item.item_id}", 1.0),),
                    "eps_price", ("c_i", "d_max"),
                    detail="p_i >= c_i·(1 − d_max)；c_i = 0 时退化为 p_i >= 0")
            )

    # ---- C1 汇总行 --------------------------------------------------------
    rows.insert(
        0,
        Row("C1", "EQUALITY", "==", B, tuple(c1_coefs), "eps_solver",
            ("q0", "P*_competitive"), scope="C1_scope",
            detail=f"Σ_{{i∈C1_scope}} p_i q0_i == {B!r}"),
    )

    # ---- C6 汇总行 --------------------------------------------------------
    if "C6" in active:
        rows.append(
            Row("C6", "LINEAR_INEQ", "<=",
                None if theta is None else float(theta) * P_ref,
                tuple((f"s_{i.item_id}", float(i.q1_point))
                      for i in opt_items if _f(i.q1_point) is not None),
                "eps_total", ("c_i", "q1_point", "theta", "P*"),
                detail="Σ s_i q1_i <= theta · P*（q1 = 结算量，非 q0）")
        )

    # ---- C7 汇总行 --------------------------------------------------------
    # 固定为 1 的项**已经消耗名额**，故 RHS 必须扣减；固定为 0 的项不进 Σ。
    # 漏掉扣减会把「亏损项数上限」放宽 n_fixed_one 个，且不触发任何检查。
    if milp:
        fixed_zero = {i for i, v, _w in z_fixed if v == 0}
        n_fixed_one = sum(1 for _i, v, _w in z_fixed if v == 1)
        free_z = tuple(
            (f"z_{i.item_id}", 1.0)
            for i in opt_items
            if _f(i.c_i) is not None and i.item_id not in fixed_zero
            and not any(i.item_id == fid and v == 1 for fid, v, _w in z_fixed)
        )
        rhs_nmax = None if n_max is None else float(n_max) - n_fixed_one
        if rhs_nmax is not None and rhs_nmax < -BIG_M_FLOOR_EPS:
            box_notes.append(
                f"C7 局部不可行：已固定 z_i = 1 的项有 {n_fixed_one} 项，"
                f"超过 N_max = {n_max!r} ⇒ 须在建模前判 BLOCKED，"
                "不得交给求解器报泛化 infeasible"
            )
        rows.append(
            Row("C7", "MILP_BINARY", "<=", rhs_nmax, free_z,
                "0（整数）", ("c_i", "N_max", "U", "rounding.resolution"),
                detail=f"Σ_{{z 未固定}} z_i <= N_max − {n_fixed_one} = {rhs_nmax!r}；"
                       "配双 M 指示式（M_lo 覆盖下界、M_hi 覆盖上界）")
        )

    # ---- C9 / C10 --------------------------------------------------------
    if "C9" in active:
        rows.append(
            Row("C9", "LINEAR_INEQ", ">=",
                None if z_min is None else float(z_min), (),
                "eps_total", ("Z", "Z_min", "pi_target", "c_i", "q1_point"),
                detail="Z >= Z_min；Z >= pi_target · Σ c_i q1_i（分母为常量，已移项）")
        )
    if "C10" in active:
        rows.append(
            Row("C10", "LINEAR_INEQ", ">=", None, (),
                "eps_total", ("rho_i", "q0", "c_i", "T_front"),
                detail="Σ_{i∈T_front} (rho_i p_i − c_i) q0_i >= 0（T_front 未声明则不激活）")
        )

    # ---- 目标常量项（不进系数）--------------------------------------------
    obj_constant = -sum(
        float(i.c_i) * float(i.q1_point)
        for i in opt_items
        if _f(i.c_i) is not None and _f(i.q1_point) is not None
    )

    # ---- 挂账项 -----------------------------------------------------------
    deferred: list[DeferredConstraint] = [
        DeferredConstraint(
            "C11", "DISCRETE_CHECK", "T03-04",
            "2026-09-17 裁定移出 LP：σ(d) 是凸二次/二阶锥约束，HiGHS 支持面"
            "（LP/MILP/QP）不含二阶锥；schema 原建议的 MAD 替代由 "
            "MAD_c ≤ σ_c 可知是**放松**（最坏 √n 倍，本项目 10.72 倍），"
            "且原式 (1/n)Σ|p_i − p̄| 既不含 base_i 又未归一化 ⇒ 非同一度量。"
            "改由判定层在求解后对 p 向量求值。见 ADR-0022。",
        ),
        DeferredConstraint(
            "C7", "MILP_BINARY", "T04-07",
            "已激活（问题升 MILP）" if milp else
            "未激活：active_soft_constraints 不含 C7 ⇒ 问题保持 LP",
        ),
        DeferredConstraint("C13", "NOT_A_BID_CONSTRAINT", "T04-05",
                           "SETTLEMENT_ADJUSTMENT（结算期修正），投标期不可知 "
                           "⇒ 不构成投标约束"),
    ]

    return Formulation(
        variables=tuple(variables),
        rows=tuple(rows),
        constant_checks=_constant_checks(instance, r_min=r_min),
        deferred=tuple(deferred),
        objective_sense="MAXIMIZE",
        objective_constant=obj_constant,
        objective_expr="Z = Σ_{i∈X_opt} ( q0_i·r_eff_i·p_i − c_i·q1_i )",
        solver_form="MILP" if milp else "LP",
        lb_c5=lb_c5,
        active=active,
        box_notes=tuple(box_notes),
        source=source or instance.source,
    )


def _merged_lower(
    item: Any, lb_c5: float, floor_by_id: Mapping[str, float] | None = None
) -> float | None:
    """合并下界 ``lb_i = max(L_i, floor_i, lb_C5)``。

    ``floor_i`` 是 T03-02 的派生量（``max(L_i, c_i·(1−mu_i))``），**不在**
    :class:`Phase1Item` 上。**2026-09-17 起它的唯一生产者已落地**：
    ``derived.compute_derived``（制品 ``config/derived_quantities_spec.json``），
    经 ``DerivedReport.floor_by_id()`` 传入本参数。

    缺省 ``None`` 的含义随之改变：不再是「T03-02 还没做」，而是
    **「本轮的派生量层没能产出 floor」**（典型原因：μ 未落值 ⇒ 如实 BLOCKED）。
    两种情形下都**不得**用 ``c_i`` 或 ``L_i`` 冒充地板——那会把一条算不出的
    约束当成已满足。调用方若走 CLI，可由 ``verify-solution`` 打印的
    「floor_i 来源」一行确认本参数究竟来自哪里。
    """
    floor = None if floor_by_id is None else _f(floor_by_id.get(item.item_id))
    cands = [v for v in (_f(item.L), floor, lb_c5) if v is not None]
    return max(cands) if cands else None


def _constant_checks(
    instance: Phase1Instance, *, r_min: float | None
) -> tuple[ConstantCheck, ...]:
    """C12（总价成本比）在可行域上是常量 —— 前置体检而非 LP 约束。

    ``R_pc = Σ p_i q0_i / Σ c_i q0_i``。**恒定性是约束面上的性质**：作为无约束
    函数偏导非零（``∂R_pc/∂p_i = q0_i / Σc q0``），只在满足 C1 的解上取值相同。
    """
    den = sum(
        float(i.c_i) * float(i.q0)
        for i in instance.items
        if _f(i.c_i) is not None and _f(i.q0) is not None
    )
    if den == 0.0:
        return (
            ConstantCheck("C12", "R_pc", None, None,
                          "Σ c_i q0_i = 0，R_pc 无定义 ⇒ 判 BLOCKED（不得判 PASS）"),
        )
    if instance.B is None:
        return (
            ConstantCheck("C12", "R_pc", None, None,
                          "缺 C1 右端，R_pc 的约束面值不可知"),
        )
    value = float(instance.B) / den
    passes = None if r_min is None else value >= float(r_min) - 1e-12
    return (
        ConstantCheck(
            "C12", "R_pc", value, passes,
            "在可行域上恒定 ⇒ 前置体检（不满足则 P* 不可接受），不进 LP"
            if r_min is not None else "未给定 R_min ⇒ 只报值不判",
        ),
    )


def r_pc_from_vector(
    p_by_id: Mapping[str, float], instance: Phase1Instance
) -> float:
    """用**给定的报价向量**求 R_pc —— 用于 F-08 的约束面恒定判据。

    刻意要求调用方传 p 向量（而不是直接吃 ``instance.B``）：若本函数内部
    直接返回 ``B/den``，两组「不同解」会给出同一个数，判据退化成恒真式。
    """
    num = 0.0
    den = 0.0
    for item in instance.items:
        q0 = _f(item.q0)
        if q0 is None:
            continue
        num += float(p_by_id.get(item.item_id, 0.0)) * q0
        c_i = _f(item.c_i)
        if c_i is not None:
            den += c_i * q0
    if den == 0.0:
        raise FormulationError("Σ c_i q0_i = 0，R_pc 无定义")
    return num / den


# ---------------------------------------------------------------------------
# F-02：边际系数对账（解析 vs 数值差分）
# ---------------------------------------------------------------------------


def verify_marginal_coefficients(
    instance: Phase1Instance,
    resolved: ResolvedParameters,
    *,
    h: float = 1e-6,
    alpha_probes: Sequence[float] = (0.0, 0.2),
    scopes: Sequence[str] = ("FULL", "SEGMENT"),
) -> tuple[MarginalCheck, ...]:
    """逐项核对 ``q0_i · r_eff_i == ∂R_i/∂p_i``。

    **跨来源**对账：解析式来自 ``compute_r_eff``（T03-02 派生量），数值差分来自
    ``settlement_revenue``（T00-01 业务公式）。两者若同源，本判据零区分度——
    正因如此它们必须分开检视。

    ``scopes`` **由本函数自己扫**，而不是沿用实例的 ``adjustment_scope``：
    2026-09-17 抓到的那处分叉（SEGMENT ∧ 区间内 ∧ alpha≠0）只在 SEGMENT 下
    出现，而项目实例恰好就是 SEGMENT——看似能撞上，实则只要实例改回 FULL
    这条判据就再也测不到它。判据的覆盖面不能取决于被测数据。
    """
    out: list[MarginalCheck] = []
    for scope in scopes:
        scoped = dataclasses.replace(resolved, adjustment_scope=str(scope))
        for item in instance.items:
            if item.role != ROLE_OPTIMIZABLE:
                continue
            q0, q1 = _f(item.q0), _f(item.q1_point)
            r_i = item.r()
            if q0 is None or q1 is None or q0 <= 0 or r_i is None:
                continue
            p_ref = _f(item.p0)
            if p_ref is None or p_ref <= 0:
                p_ref = 100.0
            for alpha in alpha_probes:
                # 解析式与数值差分**必须用同一组 (scope, alpha)**。
                # 不能借道 ``instance.r_eff``：它内部会回到实例自己的
                # Phase1Params，把这里传入的 scope 覆盖掉——两侧就此用了不同
                # 作用域，判据自己制造出假 FAIL（2026-09-17 首跑即踩到）。
                analytic = float(q0) * float(
                    compute_r_eff(r_i, scoped, float(alpha))
                )
                numeric = (
                    settlement_revenue(q0, q1, p_ref + h, scoped, float(alpha))
                    - settlement_revenue(q0, q1, p_ref - h, scoped, float(alpha))
                ) / (2.0 * h)
                out.append(
                    MarginalCheck(
                        item_id=item.item_id,
                        case=f"scope={scope}|alpha={alpha}|p_ref={p_ref:g}",
                        analytic=analytic,
                        numeric=float(numeric),
                    )
                )
    return tuple(out)


# ---------------------------------------------------------------------------
# 制品加载与 F 判据
# ---------------------------------------------------------------------------


def load_formulation_spec(config_dir: Path) -> dict[str, Any]:
    return json.loads(
        (Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8")
    )


def _norm(name: str) -> str:
    """名称规范化：去 ``_i`` 下标后缀 + 去非字母数字字符 + 小写。

    两侧（制品 sources 与参数名/其它制品字段名）走**同一**函数，故「q0_i」与
    「q0」、「U_i」与「U」可对齐。放宽的只是书写形式，不是判定强度——
    拼错的字段仍解析不出来（这正是 F-07 的意义）。
    """
    s = str(name)
    if s.endswith("_i"):
        s = s[:-2]
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _flatten_keys(obj: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            keys.add(path)
            keys |= _flatten_keys(v, path)
    return keys


def known_source_names(
    spec: Mapping[str, Any],
    constraint_schema: Mapping[str, Any] | None,
    precision_profile: Mapping[str, Any] | None,
) -> set[str]:
    """F-07 的「命名字段」集合：本制品参数 ∪ 约束字典 inputs/metric ∪ 精度档案键。

    外加一份显式白名单（``U``/``L``/``floor`` 等由 T03-02 产出的派生量名）。
    白名单是**枚举**而非模糊匹配——模糊匹配会把拼写错误一起放过。
    """
    known: set[str] = set()
    for p in spec.get("parameters", []) or []:
        if isinstance(p, dict) and p.get("name"):
            known.add(str(p["name"]))
    for c in (constraint_schema or {}).get("constraints", []) or []:
        if isinstance(c, dict):
            for src in c.get("inputs", []) or []:
                known.add(str(src))
            if c.get("metric"):
                known.add(str(c["metric"]))
    known |= _flatten_keys(precision_profile or {})
    known |= {
        "rounding.resolution", "eps_price", "eps_solver", "eps_abs", "eps_total",
        "U", "L", "floor", "cap", "q0", "q1", "c_i", "p0", "r_eff", "Z",
        "T_front", "mu", "rho_i", "alpha_i", "pi_target", "Z_min", "N_max",
        "d_max", "kappa_max", "R_min", "theta", "P*", "P*_competitive",
        "vat_rate / surtax_rate",
    }
    return {_norm(k) for k in known}


def check_formulation(
    spec: Mapping[str, Any],
    formulation: Formulation,
    *,
    instance: Phase1Instance | None = None,
    resolved: ResolvedParameters | None = None,
    constraint_schema: Mapping[str, Any] | None = None,
    precision_profile: Mapping[str, Any] | None = None,
    eps_price: float = 1e-9,
    eps_abs: float = 0.01,
) -> tuple[FormulationCheck, ...]:
    """把制品 ``formulation_checks`` 的 F 判据逐条喂给实现（双向锁定）。"""
    items: list[FormulationCheck] = []
    cmap = {c["constraint_id"]: c for c in spec.get("constraint_map", [])}
    known = known_source_names(spec, constraint_schema, precision_profile)

    # ---------------- F-01 变量覆盖 -----------------
    if instance is None:
        items.append(FormulationCheck("T04-02A", "F-01 变量覆盖完备", STATUS_SKIP,
                               "未提供实例 ⇒ SKIP（不是 PASS）"))
    else:
        scope_ids = [i.item_id for i in instance.items
                     if i.role == ROLE_OPTIMIZABLE and i.in_c1_scope]
        got_ids = [c.item_id for c in formulation.price_columns]
        missing = [x for x in scope_ids if x not in got_ids]
        dup = sorted({x for x in got_ids if got_ids.count(x) > 1})
        ok = not missing and not dup
        items.append(FormulationCheck(
            "T04-02A", "F-01 变量覆盖完备",
            STATUS_PASS if ok else STATUS_FAIL,
            (f"C1_scope {len(scope_ids)} 项 ↔ p 变量 {len(got_ids)} 列，一一对应"
             if ok else f"缺 {missing}；重复 {dup}"),
            actual=len(got_ids), expected=len(scope_ids), delta=len(got_ids) - len(scope_ids),
        ))

    # ---------------- F-02 边际对账 -----------------
    if instance is None or resolved is None:
        items.append(FormulationCheck("T04-02A", "F-02 目标边际与排序键一致", STATUS_SKIP,
                               "未提供实例/参数 ⇒ SKIP"))
    else:
        checks = verify_marginal_coefficients(instance, resolved)
        bad = [c for c in checks if not c.ok]
        items.append(FormulationCheck(
            "T04-02A", "F-02 目标边际与排序键一致",
            STATUS_PASS if not bad else STATUS_FAIL,
            (f"{len(checks)} 格全部一致（q0·r_eff == ∂R/∂p）" if not bad
             else f"{len(bad)}/{len(checks)} 格不一致：" + "; ".join(
                 f"{b.item_id}[{b.case}] 解析 {b.analytic:.6g} vs 差分 {b.numeric:.6g}"
                 for b in bad[:3])),
            actual=len(checks) - len(bad), expected=len(checks), delta=-len(bad),
        ))

    # ---------------- F-03 约束覆盖 -----------------
    if constraint_schema is None:
        items.append(FormulationCheck("T04-02A", "F-03 约束覆盖完整", STATUS_SKIP,
                               "未提供约束字典 ⇒ SKIP"))
    else:
        cons = constraint_schema.get("constraints", [])
        want = {c["id"] for c in cons}
        got = set(cmap)
        p0 = {c["id"] for c in cons if str(c.get("severity", "")).upper() == "P0"}
        missing = sorted(p0 - got)
        extra = sorted(got - want)
        undeclared = sorted(cid for cid in p0 & got if not cmap[cid].get("model_form"))
        ok = not missing and not extra and not undeclared
        items.append(FormulationCheck(
            "T04-02A", "F-03 约束覆盖完整",
            STATUS_PASS if ok else STATUS_FAIL,
            (f"P0 {len(p0)} 条全部有 model_form；制品集合 == 字典集合"
             if ok else f"缺 {missing} / 多 {extra} / 未声明形式 {undeclared}"),
            actual=sorted(got), expected=sorted(want),
        ))

    # ---------------- F-04 C1 形式与精度模式相容 -----------------
    mode = None
    if precision_profile is not None:
        mode = (precision_profile.get("equality_tolerance_mode") or {}).get("current")
    expect_form = {"A": "EQUALITY", "B": "INEQUALITY_BAND"}.get(str(mode))
    got_form = (cmap.get("C1") or {}).get("model_form")
    if expect_form is None:
        items.append(FormulationCheck(
            "T04-02A", "F-04 C1 形式与精度模式相容", STATUS_BLOCKED,
            f"equality_tolerance_mode.current = {mode!r}（未冻结 ⇒ 不得判 PASS）",
            actual=got_form, expected=None))
    else:
        items.append(FormulationCheck(
            "T04-02A", "F-04 C1 形式与精度模式相容",
            STATUS_PASS if got_form == expect_form else STATUS_FAIL,
            f"mode={mode} ⇒ 期望 {expect_form}，制品 {got_form}",
            actual=got_form, expected=expect_form))

    # ---------------- F-05 不限价项无替代上界（制品 + 实现双向）-----------------
    if instance is None:
        items.append(FormulationCheck("T04-02A", "F-05 不限价项不得被赋替代上界", STATUS_SKIP,
                               "未提供实例 ⇒ SKIP"))
    else:
        free = [i.item_id for i in instance.items
                if i.role == ROLE_OPTIMIZABLE and _f(i.U) is None]
        capped = [i.item_id for i in instance.items
                  if i.role == ROLE_OPTIMIZABLE and _f(i.U) is not None]
        exempt = str((cmap.get("C2") or {}).get("exempt_set", ""))
        expr = str((cmap.get("C2") or {}).get("solver_expression", "")).upper()
        has_bigm = "BIG_M" in expr or "1E9" in expr
        c2_rows = [r for r in formulation.rows_of("C2")]
        # 实现侧：C2 行数必须等于「有上限的项数」，且不限价项不得出现在 C2 行里
        c2_ids = {s.split("_", 1)[1] for r in c2_rows for s, _c in r.coefficients}
        leaked = sorted(set(free) & c2_ids)
        ok = (
            "N_free" in exempt
            and not has_bigm
            and not leaked
            and len(c2_rows) == len(capped)
        )
        items.append(FormulationCheck(
            "T04-02A", "F-05 不限价项不得被赋替代上界",
            STATUS_PASS if ok else STATUS_FAIL,
            (f"不限价 {len(free)} 项：制品声明豁免集 N_free，实现 C2 行数 "
             f"{len(c2_rows)} == 有上限项数 {len(capped)}，无泄漏" if ok
             else f"不限价 {len(free)}；豁免集 {exempt!r}；替代上界={has_bigm}；"
                  f"C2 行 {len(c2_rows)} vs 有上限 {len(capped)}；泄漏={leaked}"),
            actual={"free": len(free), "c2_rows": len(c2_rows)},
            expected={"exempt_set": "N_free", "c2_rows": len(capped)},
        ))

    # ---------------- F-06 C5 下界（用实现的 lb_c5）-----------------
    spec_res = None
    if precision_profile is not None:
        spec_res = (precision_profile.get("rounding") or {}).get("resolution")
    if spec_res is None:
        items.append(FormulationCheck("T04-02A", "F-06 C5 下界不低于报价分辨率", STATUS_SKIP,
                               "精度档案未给出 rounding.resolution ⇒ SKIP"))
    else:
        probes: list[str] = []
        ok = True
        for p_star in P_STAR_PROBES:
            naive = float(eps_price) * float(p_star)
            want = max(naive, float(spec_res))
            # 判据检的是**实现报出的 lb_c5**，不是在手边重算——否则恒真
            got = compute_lb_c5(p_star, eps_price, float(spec_res))
            if abs(got - want) > 1e-12 or got < float(spec_res):
                ok = False
            probes.append(
                f"P*={p_star:g}: 裸 eps·P*={naive:.3g} ⇒ lb={got:.3g}"
                + ("（已抬到 resolution）" if naive < float(spec_res) else "")
            )
        # 实现实际使用的 lb_c5 也必须 ≥ resolution
        impl_ok = formulation.lb_c5 >= float(spec_res) - 1e-15
        ok = ok and impl_ok
        items.append(FormulationCheck(
            "T04-02A", "F-06 C5 下界不低于报价分辨率",
            STATUS_PASS if ok else STATUS_FAIL,
            "; ".join(probes) + f"；实现 lb_c5={formulation.lb_c5:.6g}",
            actual=formulation.lb_c5, expected=f">= {spec_res}"))

    # ---------------- F-07 / F-07b 系数来源与理由 -----------------
    unparsed: dict[str, list[str]] = {}
    missing_reason: list[str] = []
    n_lp = n_nonlp = 0
    for cid, entry in cmap.items():
        form = entry.get("model_form")
        if form in LP_FORMS:
            n_lp += 1
            srcs = entry.get("coefficient_sources") or []
            if not srcs:
                unparsed[cid] = ["<空>"]
                continue
            bad = [s for s in srcs if _norm(s) not in known]
            if bad:
                unparsed[cid] = bad
        elif form in NON_LP_FORMS:
            n_nonlp += 1
            rf = NON_LP_REASON_FIELD[form]
            if not entry.get(rf):
                missing_reason.append(f"{cid}({form})")
    items.append(FormulationCheck(
        "T04-02A", "F-07 系数来源须为命名字段",
        STATUS_PASS if not unparsed else STATUS_FAIL,
        (f"LP 内 {n_lp} 条约束的 coefficient_sources 全部可解析" if not unparsed
         else f"不可解析：{unparsed}"),
        actual=unparsed, expected="全部 ⊆ 命名字段集合"))
    items.append(FormulationCheck(
        "T04-02A", "F-07b 非 LP 形式须给出理由",
        STATUS_PASS if not missing_reason else STATUS_FAIL,
        (f"{n_nonlp} 条非 LP 形式均带理由字段" if not missing_reason
         else f"缺理由字段：{missing_reason}"),
        actual=missing_reason, expected=[]))

    # ---------------- F-08 约束面恒定（两组不同 p 向量）-----------------
    c12 = cmap.get("C12") or {}
    form_ok = (c12.get("model_form") == "CONSTANT_CHECK"
               and c12.get("solver_expression") is None)
    if instance is None:
        const_ok, detail = None, "未提供实例 ⇒ 只检制品形式"
    else:
        const_ok, detail = check_c12_surface_constancy(instance)
    if const_ok is False or not form_ok:
        status = STATUS_FAIL
    elif const_ok is None:
        status = STATUS_PASS if form_ok else STATUS_FAIL
    else:
        status = STATUS_PASS
    items.append(FormulationCheck(
        "T04-02A", "F-08 退化为常量的约束须标出", status,
        f"C12.model_form={c12.get('model_form')!r}，solver_expression 为空="
        f"{c12.get('solver_expression') is None}；{detail}",
        actual=c12.get("model_form"), expected="CONSTANT_CHECK"))

    # ---------------- F-09 MILP 切换唯一 -----------------
    if instance is None:
        items.append(FormulationCheck("T04-02A", "F-09 MILP 切换条件唯一", STATUS_SKIP,
                               "未提供实例 ⇒ SKIP"))
    else:
        has_c7 = "C7" in formulation.active
        want = "MILP" if has_c7 else "LP"
        items.append(FormulationCheck(
            "T04-02A", "F-09 MILP 切换条件唯一",
            STATUS_PASS if formulation.solver_form == want else STATUS_FAIL,
            f"active={list(formulation.active)} ⇒ 期望 {want}，实得 {formulation.solver_form}",
            actual=formulation.solver_form, expected=want))

    # ---------------- F-10 目标常量项分列 -----------------
    neg_price_coeff = [c.symbol for c in formulation.variables
                       if c.family == "p" and c.objective_coeff < 0]
    items.append(FormulationCheck(
        "T04-02A", "F-10 目标常量项分列",
        STATUS_PASS if not neg_price_coeff else STATUS_FAIL,
        f"objective_constant={formulation.objective_constant:.6g} 单独成项；"
        f"p 列无负系数 = {not neg_price_coeff}",
        actual=formulation.objective_constant, expected="常量不进系数"))

    return tuple(items)


def check_c12_surface_constancy(instance: Phase1Instance) -> tuple[bool | None, str]:
    """F-08 的机械复算：**两组不同的 p 向量**（都满足 C1）→ R_pc 必须相同。

    两组解刻意取「预算全部给项 0」与「预算全部给项 1」。两者都是 C1 的可行点，
    又截然不同。若实现把 R_pc 误定义成含非 X_opt 的可变单价、或按声明作用域
    而非可竞争作用域求和，两组会给出不同的值 ⇒ FAIL。

    **不得**用 ``∂R_pc/∂p_i == 0``：那对无约束函数是假的（偏导 = q0_i/Σc q0），
    会把正确的实现判成 FAIL。也**不得**写成 ``B/den`` 两次——那是同一个数的
    复制，同样是恒真式。
    """
    items = [i for i in instance.items
             if i.role == ROLE_OPTIMIZABLE and _f(i.q0) and _f(i.c_i)]
    if len(items) < 2 or instance.B is None:
        return None, "项数不足 2 或无 C1 右端，无法构造两组可行 p"
    first, second = items[0], items[1]
    q0_a, q0_b = float(first.q0), float(second.q0)
    if q0_a <= 0 or q0_b <= 0:
        return None, "q0 ≤ 0，无法构造"
    B = float(instance.B)
    p_a = {first.item_id: B / q0_a}
    p_b = {second.item_id: B / q0_b}
    try:
        r_a = r_pc_from_vector(p_a, instance)
        r_b = r_pc_from_vector(p_b, instance)
    except FormulationError as exc:
        return None, str(exc)
    same = abs(r_a - r_b) <= 1e-9 * max(1.0, abs(r_a))
    return (
        same,
        (f"两组不同可行解（预算集中于 {first.item_id} / {second.item_id}）"
         f"给出同一 R_pc = {r_a:.10g}")
        if same else f"R_pc 随 p 变化：{r_a!r} vs {r_b!r}",
    )


# ---------------------------------------------------------------------------
# 内置探针实例——让 F 判据的每个分叉都被走到
# ---------------------------------------------------------------------------


#: 探针实例的**求解层入参**——它们不是 ``Phase1Instance`` 的字段（C6/C7/C8/C9
#: 的参数由调用方直接传给 ``build_formulation``），故探针必须单独声明，否则
#: C6/C7/C9 的占位行必然 ``NOT_COMPILED``（rhs 为 None），探针就**覆盖不到**
#: 这些行的编译路径。2026-09-17 首跑 ``compile-check`` 时 MILP 变体的 CC-05
#: 恒为 BLOCKED，根因就是 CLI 没给 ``n_max`` ⇒ C7 汇总行不编译。
#:
#: 取值均为**合成值**，只保证「让各占位行能编译出来并落在合理区间」，
#: 不代表任何真实项目，也不得被读成项目落值。
PROBE_SOLVER_INPUTS: dict[str, float] = {
    "theta": 0.05,      # C6：亏损缺口上限 θ·P*
    "n_max": 3.0,       # C7：亏损项数上限 N_max
    "d_max": 0.15,      # C8：地板下浮上限 d_max
    "r_min": 1.0,       # C12：总价成本比体检阈值 R_min
    "z_min": 0.0,       # C9a：盈利门槛 Z_min
    "pi_target": 0.0,   # C9b：目标利润率 π
}


def probe_instance(
    *,
    P_star: float = 3.0e6,
    B: float = 2.55e6,
    active: Sequence[str] = (),
    adjustment_scope: str = "SEGMENT",
) -> Phase1Instance:
    """覆盖 F 判据全部分叉的探针实例。

    刻意包含四类项，各走一条不同路径：

    ===========  ========  ==============================  ============
    项            分支      覆盖的判据                        关键点
    ===========  ========  ==============================  ============
    ``P-DEC``    DECREASE  F-02 减量侧                     r = 0.8 < 1−θ
    ``P-IN``     IN_RANGE  F-02 区间内、F-08 两组 p 构造    r = 1.0
    ``P-INC``    INCREASE  F-02 增量侧（SEGMENT 分段）      r = 1.4 > 1+θ
    ``P-FREE``   不限价    F-05 豁免集                      ``U = None``
    ===========  ========  ==============================  ============

    ``P-FREE`` 同时是 T04-00 EC-9 的复现点：它使 Phase 1 阈值分割必须实现
    「不限价项作为临界项」的分支。

    ``active`` 传 ``("C7",)`` 时问题升为 MILP（F-09 的另一侧）。
    """
    items = (
        Phase1Item(item_id="P-DEC", q0=1000.0, q1_point=800.0, c_i=400.0,
                   p0=500.0, cap=500.0, L=300.0, U=500.0),
        Phase1Item(item_id="P-IN", q0=2000.0, q1_point=2000.0, c_i=600.0,
                   p0=700.0, cap=700.0, L=400.0, U=700.0),
        Phase1Item(item_id="P-INC", q0=1000.0, q1_point=1400.0, c_i=500.0,
                   p0=600.0, cap=600.0, L=350.0, U=600.0),
        Phase1Item(item_id="P-FREE", q0=500.0, q1_point=500.0, c_i=100.0,
                   p0=100.0, cap=None, L=50.0, U=None),
    )
    return Phase1Instance(
        items=items,
        B=B,
        P_star=P_star,
        params=Phase1Params(
            theta_dev=0.15, rho_plus=0.0, rho_minus=0.0,
            adjustment_scope=adjustment_scope, theta=0.05,
        ),
        active_soft_constraints=tuple(active),
        rounding_reconciliation_present=True,
        source="solver/formulation.probe_instance（T04-02A 内置探针）",
    )
