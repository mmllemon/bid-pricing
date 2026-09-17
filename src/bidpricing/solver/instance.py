"""Phase 1 论域的实例结构与解校验（T04-00 的输入/输出载体）。

**为什么需要独立的实例结构，而不直接吃 master 表**：T04-00 的反例集要能被
逐条复算，必须把「实例」表达为*自足*的对象——含全部数值与规则集参数，
不依赖任何项目级落值文件。因此本模块提供 ``from_dict``（供反例集与测试
构造）与 ``from_master``（供真实项目跑）两条入口，且**两者产出的类型相同**，
保证「反例上验证过的结论」可以原样用到真实数据上。

解的校验（``check_solution``）刻意不复用求解路径：它只做「代回原式」，
即拿给定的 p 直接算 C1 残差、箱型违反量、结算收入与目标值。这样它才能
作为 T04-01 解析解与 T04-08 参考实现的**共同裁判**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..contracts.pricing_card import (
    ResolvedParameters,
    compute_r_eff,
    settlement_revenue,
)

#: 项目级角色取值——与 config/competitiveness_classification.json 同域。
ROLE_OPTIMIZABLE = "OPTIMIZABLE"
ROLE_NON_COMPETITIVE = "NON_COMPETITIVE"
ROLE_PASS_THROUGH = "PASS_THROUGH"

#: 判定状态取值——与闸门层/校验层同构（config/constraint_schema.status_domain）
STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"

#: 单价舍入分辨率（元）——与 precision_profile.rounding.resolution 同源。
PRICE_RESOLUTION = 0.01


class Phase1InstanceError(ValueError):
    """实例结构不合法（缺必填键、类型不符）。"""


@dataclass(frozen=True)
class Phase1Item:
    """一个报价项的求解层视图。

    ``U`` 为 ``None`` 表示**不限价**（cap 空，合法语义 ``ALLOW_EMPTY_NO_CAP``），
    不是数据缺口。数值字段为 ``None`` 才是缺数据，两者必须机器可区分（ADR-0004）。
    """

    item_id: str
    role: str = ROLE_OPTIMIZABLE
    in_c1_scope: bool = True
    q0: float | None = None
    q1_point: float | None = None
    c_i: float | None = None
    p0: float | None = None
    cap: float | None = None
    L: float | None = None
    U: float | None = None
    alpha: float = 0.0

    @property
    def is_optimizable(self) -> bool:
        return self.role == ROLE_OPTIMIZABLE

    def r(self) -> float | None:
        """结算量比 ``q1/q0``；``q0`` 缺失或为 0 时返回 ``None``。"""
        if self.q0 is None or self.q1_point is None or self.q0 == 0:
            return None
        return self.q1_point / self.q0


@dataclass(frozen=True)
class Phase1Params:
    """规则集层参数——**取自 rule_set_id，不得硬编码**（§3.7）。

    本结构只是 ``ResolvedParameters`` 的求解层副本；``to_resolved()``
    保证两条路径走同一份分母，避免求解层自造一套阈值。
    """

    theta_dev: float | None = None
    rho_plus: float | None = None
    rho_minus: float | None = None
    adjustment_scope: str | None = None
    theta: float | None = None

    def to_resolved(self, defaults: ResolvedParameters) -> ResolvedParameters:
        """用规则卡解析出的参数补齐未显式给出的项。

        **缺失即继承规则卡**，不得静默取 0——ρ± 的来源必须在输出中可见。
        """
        return ResolvedParameters(
            rho_plus=defaults.rho_plus if self.rho_plus is None else self.rho_plus,
            rho_minus=defaults.rho_minus if self.rho_minus is None else self.rho_minus,
            increase_threshold=(
                defaults.increase_threshold
                if self.theta_dev is None
                else 1.0 + float(self.theta_dev)
            ),
            decrease_threshold=(
                defaults.decrease_threshold
                if self.theta_dev is None
                else 1.0 - float(self.theta_dev)
            ),
            adjustment_scope=(
                defaults.adjustment_scope
                if self.adjustment_scope is None
                else str(self.adjustment_scope)
            ),
            sources={k: "phase1_instance" for k in
                     ("rho_plus", "rho_minus", "increase_threshold",
                      "decrease_threshold", "adjustment_scope")},
        )


@dataclass(frozen=True)
class Phase1Instance:
    """Phase 1 的完整实例。"""

    items: tuple[Phase1Item, ...]
    B: float | None = None
    P_star: float | None = None
    params: Phase1Params = field(default_factory=Phase1Params)
    active_soft_constraints: tuple[str, ...] = ()
    rounding_reconciliation_present: bool = False
    tie_break_policy: str | None = None
    source: str = ""

    # ---- 便捷视图 -------------------------------------------------------
    @property
    def opt_items(self) -> tuple[Phase1Item, ...]:
        return tuple(i for i in self.items if i.is_optimizable)

    @property
    def c1_scope_items(self) -> tuple[Phase1Item, ...]:
        return tuple(i for i in self.items if i.in_c1_scope)

    def r_eff(self, item: Phase1Item, defaults: ResolvedParameters) -> float | None:
        """该项的排序键；``r`` 算不出时返回 ``None``（**不得降级为 0**）。"""
        r = item.r()
        if r is None:
            return None
        return compute_r_eff(r, self.params.to_resolved(defaults), item.alpha)

    # ---- 构造 -----------------------------------------------------------
    @classmethod
    def from_dict(cls, d: Mapping[str, Any], *, source: str = "") -> "Phase1Instance":
        try:
            raw_items = d["items"]
        except KeyError as exc:  # pragma: no cover - 结构错误应当立刻暴露
            raise Phase1InstanceError("实例缺 items 键") from exc
        items = tuple(_item_from_dict(raw) for raw in raw_items)
        p = d.get("params") or {}
        params = Phase1Params(
            theta_dev=p.get("theta_dev"),
            rho_plus=p.get("rho_plus"),
            rho_minus=p.get("rho_minus"),
            adjustment_scope=p.get("adjustment_scope"),
            theta=p.get("theta"),
        )
        return cls(
            items=items,
            B=d.get("B"),
            P_star=d.get("P_star"),
            params=params,
            active_soft_constraints=tuple(d.get("active_soft_constraints") or ()),
            rounding_reconciliation_present=bool(
                d.get("rounding_reconciliation_present", False)
            ),
            tie_break_policy=d.get("tie_break_policy"),
            source=source or str(d.get("synthetic_note", "")),
        )

    @classmethod
    def from_master(
        cls,
        rows: Iterable[Mapping[str, Any]],
        *,
        price_column: str,
        B: float | None,
        P_star: float | None,
        params: Phase1Params | None = None,
        active_soft_constraints: Iterable[str] = (),
        rounding_reconciliation_present: bool = True,
        source: str = "",
    ) -> "Phase1Instance":
        """从 master 表行构造。

        ``price_column`` 指定哪一列作为 ``p0``（基准）：真实项目里成本清单的
        单价是 ``c_i``，限价清单的综合单价是 ``cap_i``（T01-04 的 master 表两侧
        分别落在 ``c_i`` 与 ``cap``）。把选择权交给调用方而不是在这里猜，
        是因为「拿成本单价当基准」与「拿限价当基准」会给出不同的 L/U——
        猜错不会报错，只会算错。
        """
        items: list[Phase1Item] = []
        for row in rows:
            items.append(
                Phase1Item(
                    item_id=str(row.get("item_id", "")),
                    role=str(row.get("pricing_role") or ROLE_OPTIMIZABLE),
                    in_c1_scope=bool(row.get("in_c1_scope", True)),
                    q0=_as_float(row.get("q0")),
                    q1_point=_as_float(row.get("q1_point")),
                    c_i=_as_float(row.get("c_i")),
                    p0=_as_float(row.get(price_column)),
                    cap=_as_float(row.get("cap")),
                    L=_as_float(row.get("L")),
                    U=_as_float(row.get("U")),
                    alpha=float(row.get("alpha") or 0.0),
                )
            )
        return cls(
            items=tuple(items),
            B=B,
            P_star=P_star,
            params=params or Phase1Params(),
            active_soft_constraints=tuple(active_soft_constraints),
            rounding_reconciliation_present=rounding_reconciliation_present,
            source=source,
        )


@dataclass(frozen=True)
class SolutionCheck:
    """把解代回原式的复核结果。

    ``competitive_total`` 按**正确作用域**（``role == OPTIMIZABLE``）求和，
    ``declared_total`` 按实例声明的 ``in_c1_scope`` 求和。两者分开是刻意的：
    C1 的右端 ``B`` 定义在可竞争部分上，而「声明的作用域是否等于可竞争部分」
    是 EC-1 的职责。若这里也用声明作用域求和，CE-01 的**正确解**会被误判
    不可行（因为它把不可竞争项按固定值报出，声明求和自然大于 B）。
    """

    feasible: bool
    Z: float
    competitive_total: float
    declared_total: float
    c1_residual: float | None
    violations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "feasible": self.feasible,
            "Z": self.Z,
            "competitive_total": self.competitive_total,
            "declared_total": self.declared_total,
            "c1_residual": self.c1_residual,
            "violations": list(self.violations),
        }


def check_solution(
    instance: Phase1Instance,
    p_by_id: Mapping[str, float],
    resolved: ResolvedParameters,
    *,
    eps_total: float | None = None,
) -> SolutionCheck:
    """把 ``p_by_id`` 代回 ``R_i`` 与 C1/C2/C3/C5 复核。

    这是**独立于求解路径**的裁判：不做任何优化、不假设任何结构，
    只回答「这个解可行吗、目标值多少」。因此同一函数可用于
    T04-01 解析解的复核、T04-02D 解校验器，以及反例集里
    「误用解 vs 正确解」的对照。

    缺数值（``q0`` / ``q1_point`` 为空）→ 进 ``violations`` 并整体判不可行，
    不得跳过该项静默累加。
    """
    violations: list[str] = []
    Z = 0.0
    competitive_total = 0.0
    declared_total = 0.0
    c1_residual: float | None = None

    for item in instance.items:
        p = p_by_id.get(item.item_id)
        if p is None:
            violations.append(f"{item.item_id}: 解中缺该变量")
            continue
        if item.q0 is None or item.q1_point is None:
            violations.append(f"{item.item_id}: q0/q1 缺失，R_i 不可计算")
            continue
        if item.q0 <= 0:
            violations.append(f"{item.item_id}: q0 <= 0，r 无定义")
            continue

        revenue = settlement_revenue(
            item.q0, item.q1_point, p, instance.params.to_resolved(resolved), item.alpha
        )
        cost = (item.c_i or 0.0) * item.q1_point
        Z += revenue - cost

        if item.is_optimizable:
            competitive_total += item.q0 * p
        if item.in_c1_scope:
            declared_total += item.q0 * p

        # 箱型与 C5 只对可优化项生效——不可竞争项/透传项的单价由招标给定，
        # 其上下界不是本模型的决策约束。
        if not item.is_optimizable:
            continue
        if item.L is not None and p < item.L:
            violations.append(f"{item.item_id}: p={p} < L={item.L}")
        if item.U is not None and p > item.U:
            violations.append(f"{item.item_id}: p={p} > U={item.U}")
        if p <= 0:
            violations.append(f"{item.item_id}: p={p} <= 0（C5 单项报价不得为零）")

    if instance.B is None:
        violations.append("实例未给出 B，C1 不可复核")
    else:
        c1_residual = competitive_total - instance.B
        if eps_total is not None and abs(c1_residual) > eps_total:
            violations.append(
                f"C1 残差 {c1_residual:g} 超出容差 {eps_total:g}"
                f"（可竞争部分 {competitive_total:g} vs B {instance.B:g}）"
            )

    return SolutionCheck(
        feasible=not violations,
        Z=Z,
        competitive_total=competitive_total,
        declared_total=declared_total,
        c1_residual=c1_residual,
        violations=tuple(violations),
    )


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _item_from_dict(d: Mapping[str, Any]) -> Phase1Item:
    return Phase1Item(
        item_id=str(d.get("item_id", "")),
        role=str(d.get("role") or ROLE_OPTIMIZABLE),
        in_c1_scope=bool(d.get("in_c1_scope", True)),
        q0=_as_float(d.get("q0")),
        q1_point=_as_float(d.get("q1_point")),
        c_i=_as_float(d.get("c_i")),
        p0=_as_float(d.get("p0")),
        cap=_as_float(d.get("cap")),
        L=_as_float(d.get("L")),
        U=_as_float(d.get("U")),
        alpha=float(d.get("alpha") or 0.0),
    )
