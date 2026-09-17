"""独立参考实现（T04-08）——**第二条计算路径**。

存在意义
--------
路线 §5.3 判据 S0：**solver objective 正确 ≠ 业务利润正确**。若复核层与生产层
共用同一份 ``R_i`` / constraint / objective 实现，则「两条路径一致」只是同一错误
的两次复现（共因错误），对拍恒绿而无信息量。本模块因此：

* **不 import 任何生产模块**（连数据结构也不 import，靠冻结快照 + 取属性），
  使「文件不重叠」成为可机械审计的事实而非纪律声明；
* 公式来源写进 ``config/reference_impl_spec.json`` 与路线 §5.3 S0、
  ``config/profit_bridge_spec.json``、``config/pricing_rule_card.json``——
  **由制品推导，不由生产代码抄录**；
* 只做「给定 p 的重算」：不构造 LP/MILP、不调求解器。

计算范围
--------
* ``R_i(p)``：三分支（DECREASE / IN_RANGE / INCREASE）× 作用域（FULL / SEGMENT）；
* ``Z_total = Σ_all [R_i − c_i·q1]``（§5.3 S0 原文）；
  ``Z_competitive = Σ_{i∈X_opt}``（利润桥接表的目标**层**）；
  二者之差 ``constant_part`` 显式给出——差是常数，不影响最优分配但影响目标值；
* 约束残差：C1（Σ_{opt} q0·p − B）、盒式 L/U（仅可优化项）、C5（p > 0）。

★ 两个口径必须**两个名字**（与 DV-02 同族）：混用即把同一个量算两遍，
不报错而静默偏掉一个常数。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCOPE = "RI"

STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_WARN = "WARN"
STATUS_SKIP = "SKIP"
STATUS_PASS = "PASS"

#: 聚合序（制品 verdict_aggregation.order 的镜像；★ 不得与 FAIL 合并）
_STATUS_ORDER = (STATUS_FAIL, STATUS_BLOCKED, STATUS_WARN, STATUS_SKIP, STATUS_PASS)

BRANCH_DECREASE = "DECREASE"
BRANCH_IN_RANGE = "IN_RANGE"
BRANCH_INCREASE = "INCREASE"
BRANCHES = (BRANCH_DECREASE, BRANCH_IN_RANGE, BRANCH_INCREASE)
SCOPES = ("FULL", "SEGMENT")

SPEC_FILENAME = "reference_impl_spec.json"

#: 参与计算的参数名——RI-03 要求它们**具名且带来源**，不得是凭空出现的数值。
PARAM_NAMES = (
    "rho_plus",
    "rho_minus",
    "decrease_threshold",
    "increase_threshold",
    "adjustment_scope",
)

#: 本层实际读取的输入名——RI-10（声明↔实现对账）用它做双向比对。
INPUT_NAMES = (
    "instance.items",
    "instance.B",
    "instance.params",
    "p_by_id",
    "resolved",
    "tolerances",
)

_UNSET = object()


# ---------------------------------------------------------------------------
# 冻结快照（ISO-2：不共享可变状态）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RefParams:
    """参考实现使用的参数——**只有数值与名字**，不含任何生产侧对象。"""

    rho_plus: float
    rho_minus: float
    decrease_threshold: float
    increase_threshold: float
    adjustment_scope: str
    #: ``((name, source), ...)``——RI-03：每个数值都要有名字与出处。
    sources: tuple[tuple[str, str], ...] = ()

    @property
    def named(self) -> tuple[str, ...]:
        return tuple(n for n, _ in self.sources)


@dataclass(frozen=True)
class RefItem:
    """单项的冻结快照。``None`` 一律表示**数据缺失**（不是 0）。"""

    item_id: str
    q0: float | None
    q1: float | None
    c_i: float | None
    alpha: float
    L: float | None
    U: float | None
    is_optimizable: bool
    in_c1_scope: bool


@dataclass(frozen=True)
class RefSnapshot:
    """入场即冻结：之后调用方怎么改输入，都不影响已产结果（ISO-2）。"""

    items: tuple[RefItem, ...]
    params: RefParams
    B: float | None

    def item_ids(self) -> tuple[str, ...]:
        return tuple(i.item_id for i in self.items)


@dataclass(frozen=True)
class RefLine:
    """逐项可核对的一行（RI-06 的自洽项）。"""

    item_id: str
    branch: str
    r: float | None
    p: float | None
    revenue: float | None
    cost: float | None
    contribution: float | None
    optimizable: bool

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class RefResidual:
    """一条约束残差。``actual/expected`` 均具名，便于跨来源对账。"""

    constraint: str
    item_id: str | None
    actual: float
    expected: float
    residual: float
    tolerance: float | None
    tolerance_name: str | None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class RefObjective:
    """目标函数的两个口径 + 常数差（★ 两个名字，不得混用）。"""

    Z_total: float
    Z_competitive: float
    constant_part: float
    lines: tuple[RefLine, ...]
    blocked: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "Z_total": self.Z_total,
            "Z_competitive": self.Z_competitive,
            "constant_part": self.constant_part,
            "blocked": list(self.blocked),
            "lines": [l.to_dict() for l in self.lines],
        }


@dataclass(frozen=True)
class RefCheck:
    scope: str
    item: str
    status: str
    reason: str
    actual: Any = None
    expected: Any = None
    delta: float | None = None

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


@dataclass(frozen=True)
class RefReport:
    objective: RefObjective | None
    residuals: tuple[RefResidual, ...]
    checks: tuple[RefCheck, ...]
    inputs_used: tuple[str, ...]
    isolation: Mapping[str, Any] = field(default_factory=dict)

    def verdict(self) -> str:
        if not self.checks:
            return STATUS_BLOCKED  # 空判据集不是 PASS
        for st in _STATUS_ORDER:
            if any(c.status == st for c in self.checks):
                return st
        return STATUS_PASS

    def blocking(self) -> tuple[RefCheck, ...]:
        return tuple(c for c in self.checks if c.blocks_progress)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective.to_dict() if self.objective else None,
            "residuals": [r.to_dict() for r in self.residuals],
            "checks": [c.to_dict() for c in self.checks],
            "inputs_used": list(self.inputs_used),
            "isolation": dict(self.isolation),
            "verdict": self.verdict(),
        }


# ---------------------------------------------------------------------------
# 制品装载
# ---------------------------------------------------------------------------


def load_reference_spec(config_dir: Path) -> dict[str, Any]:
    path = Path(config_dir) / SPEC_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"参考实现制品缺失：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def declared_input_names(spec: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(i.get("field", "")) for i in spec.get("inputs", []))


# ---------------------------------------------------------------------------
# 快照：把生产侧对象**抄成冻结数据**（ISO-2 的第一道闸）
# ---------------------------------------------------------------------------


def params_from(instance: Any, resolved: Any = None) -> RefParams:
    """从实例（可带规则卡解析结果）取出参数并**具名**。

    缺失项按 ADR-0004 处理：**不静默取 0**，而是记为 ``None`` 并由 RI-01/RI-03
    判 BLOCKED。``resolved`` 提供缺省（数据层，非计算层）。
    """

    def _get(obj: Any, name: str) -> Any:
        return getattr(obj, name, None) if obj is not None else None

    p = _get(instance, "params")
    src: list[tuple[str, str]] = []

    def _pick(name: str, attr: str | None = None) -> Any:
        """实例层优先，缺失则继承规则卡解析值；来源**逐项记录**（RI-03）。"""
        attr = attr or name
        v = _get(p, attr)
        if v is not None:
            src.append((name, "instance.params"))
            return v
        v = _get(resolved, attr)
        if v is not None:
            src.append((name, "resolved(规则卡)"))
        return v

    rho_plus = _pick("rho_plus")
    rho_minus = _pick("rho_minus")
    theta_dev = _get(p, "theta_dev")
    if theta_dev is not None:
        # ★ 阈值本身已是 (1 ± θ_dev)：不得再写成 1 + increase_threshold。
        increase_threshold = 1.0 + float(theta_dev)
        decrease_threshold = 1.0 - float(theta_dev)
        src.append(("increase_threshold", "instance.params.theta_dev"))
        src.append(("decrease_threshold", "instance.params.theta_dev"))
    else:
        increase_threshold = _pick("increase_threshold")
        decrease_threshold = _pick("decrease_threshold")
    scope = _pick("adjustment_scope")

    def _f(v: Any) -> float:
        return float(v) if v is not None else float("nan")

    return RefParams(
        rho_plus=_f(rho_plus),
        rho_minus=_f(rho_minus),
        decrease_threshold=_f(decrease_threshold),
        increase_threshold=_f(increase_threshold),
        adjustment_scope=str(scope) if scope is not None else "",
        sources=tuple(src),
    )


def snapshot(instance: Any, resolved: Any = None) -> RefSnapshot:
    """把实例抄成**冻结快照**。

    取属性而非 import 类型——这样本模块与生产侧**零文件重叠**（ISO-1 最强形态）。
    """
    items: list[RefItem] = []
    for raw in getattr(instance, "items", ()) or ():
        role = getattr(raw, "role", "OPTIMIZABLE")
        items.append(
            RefItem(
                item_id=str(getattr(raw, "item_id")),
                q0=getattr(raw, "q0", None),
                q1=getattr(raw, "q1_point", None),
                c_i=getattr(raw, "c_i", None),
                alpha=float(getattr(raw, "alpha", 0.0) or 0.0),
                L=getattr(raw, "L", None),
                U=getattr(raw, "U", None),
                is_optimizable=bool(role == "OPTIMIZABLE"),
                in_c1_scope=bool(getattr(raw, "in_c1_scope", True)),
            )
        )
    return RefSnapshot(
        items=tuple(items),
        params=params_from(instance, resolved),
        B=getattr(instance, "B", None),
    )


# ---------------------------------------------------------------------------
# 核心计算（★ 由制品推导，不调生产函数）
# ---------------------------------------------------------------------------


def ref_branch(r: float, params: RefParams) -> str:
    """按 ``r = q1/q0`` 判分支。阈值来自**具名参数**（RI-03）。"""
    if r < params.decrease_threshold:
        return BRANCH_DECREASE
    if r > params.increase_threshold:
        return BRANCH_INCREASE
    return BRANCH_IN_RANGE


def ref_revenue(item: RefItem, p: float, params: RefParams) -> float:
    """``R_i(p)``——单项结算收入。

    三分支 × 作用域，口径见制品 ``formula_source_of_truth``（源自规则卡 P1 公式
    与 ADR-0010）。★ ``increase_threshold`` **本身已是** ``(1+θ_dev)``：
    写成 ``1 + increase_threshold`` 会把越界段系统性高估（历史真实坑，
    ``tests/test_phase1_exactness.py`` 例 2R 抓到过）。
    """
    r = item.q1 / item.q0  # type: ignore[operator]
    branch = ref_branch(r, params)
    if branch == BRANCH_DECREASE:
        # 减量侧：「减少后剩余部分」本就是全部 Q1 ⇒ FULL 与 SEGMENT 等价
        return item.q1 * p * (1.0 + params.rho_minus)  # type: ignore[operator]
    if branch == BRANCH_INCREASE:
        p1 = p * (1.0 - params.rho_plus)
        if params.adjustment_scope == "FULL":
            return item.q1 * p1  # type: ignore[operator]
        in_range = params.increase_threshold * item.q0 * p  # type: ignore[operator]
        excess = (item.q1 - params.increase_threshold * item.q0) * p1  # type: ignore[operator]
        return in_range + excess
    # 区间内：协商调整率 α **只作用于 FULL 分支**（SEGMENT 下未越界部分按原单价）
    if params.adjustment_scope == "FULL":
        return item.q1 * p * (1.0 + item.alpha)  # type: ignore[operator]
    return item.q1 * p  # type: ignore[operator]


def ref_objective(snap: RefSnapshot, p_by_id: Mapping[str, float]) -> RefObjective:
    """``Z = Σ [R_i − c_i·q1]``（§5.3 S0），同时给出可竞争口径与常数差。"""
    lines: list[RefLine] = []
    blocked: list[str] = []
    z_total = 0.0
    z_comp = 0.0
    for item in snap.items:
        p = p_by_id.get(item.item_id)
        if p is None:
            blocked.append(f"{item.item_id}: 解中缺该变量")
            lines.append(RefLine(item.item_id, "N/A", None, None, None, None, None,
                                 item.is_optimizable))
            continue
        if item.q0 is None or item.q1 is None:
            blocked.append(f"{item.item_id}: q0/q1 缺失，R_i 不可计算")
            lines.append(RefLine(item.item_id, "N/A", None, p, None, None, None,
                                 item.is_optimizable))
            continue
        if item.q0 <= 0:
            blocked.append(f"{item.item_id}: q0 ≤ 0，r 无定义")
            lines.append(RefLine(item.item_id, "N/A", None, p, None, None, None,
                                 item.is_optimizable))
            continue
        r = item.q1 / item.q0
        revenue = ref_revenue(item, float(p), snap.params)
        cost = (item.c_i or 0.0) * item.q1
        contrib = revenue - cost
        z_total += contrib
        if item.is_optimizable:
            z_comp += contrib
        lines.append(
            RefLine(item.item_id, ref_branch(r, snap.params), r, float(p),
                    revenue, cost, contrib, item.is_optimizable)
        )
    return RefObjective(
        Z_total=z_total,
        Z_competitive=z_comp,
        constant_part=z_total - z_comp,
        lines=tuple(lines),
        blocked=tuple(blocked),
    )


def ref_residuals(
    snap: RefSnapshot,
    p_by_id: Mapping[str, float],
    *,
    eps_box: float = 0.0,
    eps_box_name: str | None = None,
    eps_total: float | None = None,
    eps_total_name: str | None = None,
) -> tuple[RefResidual, ...]:
    """重算三类约束残差：C1 总价锁定 / 盒式 L·U / C5 单价为正。"""
    out: list[RefResidual] = []
    competitive_total = 0.0
    for item in snap.items:
        p = p_by_id.get(item.item_id)
        if p is None or not item.is_optimizable:
            if item.in_c1_scope and p is not None:
                competitive_total += item.q0 * p  # type: ignore[operator]
            continue
        competitive_total += item.q0 * p  # type: ignore[operator]
        if item.L is not None:
            out.append(RefResidual(
                "C_low", item.item_id, float(p), float(item.L),
                float(p) - float(item.L), eps_box, eps_box_name))
        if item.U is not None:
            out.append(RefResidual(
                "C_high", item.item_id, float(p), float(item.U),
                float(p) - float(item.U), eps_box, eps_box_name))
        out.append(RefResidual(
            "C5_positive", item.item_id, float(p), 0.0, float(p), None, None))

    if snap.B is not None:
        out.append(RefResidual(
            "C1_total", None, competitive_total, float(snap.B),
            competitive_total - float(snap.B), eps_total, eps_total_name))
    return tuple(out)


# ---------------------------------------------------------------------------
# 判据层（只吃数据 ⇒ 可注入验证）
# ---------------------------------------------------------------------------


def judge_reference(
    objective: RefObjective | None,
    residuals: Sequence[RefResidual],
    *,
    params: RefParams | None,
    spec: Mapping[str, Any] | None = None,
    declared_inputs: Iterable[str] = (),
    inputs_used: Iterable[str] = (),
    z_solver: float | None = None,
    tolerances: Mapping[str, float] | None = None,
    isolation: Mapping[str, Any] | None = None,
) -> tuple[RefCheck, ...]:
    """RI-01..RI-11。**只吃数据**：不读实例、不读配置、不调生产函数。"""
    checks: list[RefCheck] = []
    spec = spec or {}
    used = tuple(inputs_used)
    declared = tuple(declared_inputs)

    def add(item: str, status: str, reason: str, **kw: Any) -> None:
        checks.append(RefCheck(SCOPE, item, status, reason, **kw))

    # ---- RI-01 就绪性 -----------------------------------------------------
    if objective is None:
        add("RI-01 就绪性", STATUS_BLOCKED, "无目标重算结果（快照或解缺失）⇒ 查不成。")
        return tuple(checks)
    if params is None:
        add("RI-01 就绪性", STATUS_BLOCKED, "参数缺失 ⇒ 分支与系数不可定（不静默取 0）。")
        return tuple(checks)
    nan = [n for n in PARAM_NAMES if getattr(params, n, None) != getattr(params, n, None)]
    if nan:
        add("RI-01 就绪性", STATUS_BLOCKED,
            "参数具名但无值：" + "、".join(nan) +
            "（★ 键缺失与值为 null 是两种未定态，均不得降级）")
        return tuple(checks)
    if not params.adjustment_scope:
        add("RI-01 就绪性", STATUS_BLOCKED, "adjustment_scope 未落值 ⇒ 作用域不可定。")
        return tuple(checks)
    add("RI-01 就绪性", STATUS_PASS, "实例/解/参数齐备。")

    # ---- RI-02 分支覆盖（制品声明 ↔ 实现分支集） --------------------------
    domain = spec.get("branch_domain") or {}
    spec_branches = tuple(domain.get("branches", ()))
    spec_scopes = tuple(domain.get("scopes", ()))
    if spec_branches and tuple(spec_branches) != BRANCHES:
        add("RI-02 分支覆盖", STATUS_BLOCKED,
            f"制品声明分支 {spec_branches} 与实现 {BRANCHES} 不一致——"
            "任一侧多一个即漏算一类项（不报错而静默偏小）。")
    elif spec_scopes and tuple(spec_scopes) != SCOPES:
        add("RI-02 分支覆盖", STATUS_BLOCKED,
            f"制品声明作用域 {spec_scopes} 与实现 {SCOPES} 不一致。")
    else:
        add("RI-02 分支覆盖", STATUS_PASS,
            f"分支 {BRANCHES} × 作用域 {SCOPES} 与制品一致。")

    # ---- RI-03 参数具名 ---------------------------------------------------
    named = set(params.named)
    unnamed = [n for n in PARAM_NAMES if n not in named]
    if unnamed:
        add("RI-03 参数具名", STATUS_BLOCKED,
            "参与计算却无名字/来源：" + "、".join(unnamed) +
            "（CC-12 同族：无名数值 ⇒ 不得参与判定）")
    else:
        add("RI-03 参数具名", STATUS_PASS,
            "、".join(f"{n}←{s}" for n, s in params.sources))

    # ---- RI-04 空值不降级 -------------------------------------------------
    if objective.blocked:
        add("RI-04 空值不降级", STATUS_BLOCKED,
            "；".join(objective.blocked) +
            "（★ 不许跳过该项静默累加，也不许按 0 计入）")
    else:
        add("RI-04 空值不降级", STATUS_PASS, "无 q0/q1 缺失或 q0 ≤ 0 的项。")

    # ---- RI-06 逐项自洽（同源：只证加总没错，不证公式对） ------------------
    total = sum(l.contribution for l in objective.lines if l.contribution is not None)
    if abs(total - objective.Z_total) > 1e-9 * max(1.0, abs(objective.Z_total)):
        add("RI-06 逐项自洽", STATUS_FAIL,
            f"逐项贡献 Σ={total:g} ≠ Z_total={objective.Z_total:g}")
    else:
        add("RI-06 逐项自洽", STATUS_PASS,
            f"逐项贡献 Σ 与 Z_total 一致（{len(objective.lines)} 项，"
            "★ 同源自洽不代替 RI-05 的跨来源对照）")

    # ---- RI-05 目标值对照（跨来源：真正的判据） ----------------------------
    if z_solver is None:
        add("RI-05 目标值对照 |Z_solver−Z_ref|≤ε_Z", STATUS_SKIP,
            "未提供 Z_solver ⇒ 本轮没对照。**SKIP ≠ PASS**。")
    elif tolerances is None:
        add("RI-05 目标值对照 |Z_solver−Z_ref|≤ε_Z", STATUS_BLOCKED,
            "未提供容差表 ⇒ ε_Z 不可定（不得按 0 放行）。")
    else:
        eps_abs = tolerances.get("eps_abs")
        eps_rel = tolerances.get("eps_rel_price")
        if eps_abs is None or eps_rel is None:
            add("RI-05 目标值对照 |Z_solver−Z_ref|≤ε_Z", STATUS_BLOCKED,
                "ε_Z 的组成项解析不出：eps_abs / eps_rel_price 缺一 ⇒ 不比。"
                "★ 两者是**两个名字**（绝对 vs 相对），不得互相顶替。")
        else:
            eps_z = float(eps_abs) + float(eps_rel) * max(
                abs(float(z_solver)), abs(objective.Z_total))
            delta = float(z_solver) - objective.Z_total
            ok = abs(delta) <= eps_z
            add("RI-05 目标值对照 |Z_solver−Z_ref|≤ε_Z",
                STATUS_PASS if ok else STATUS_FAIL,
                (f"Z_solver {z_solver:g} vs Z_ref {objective.Z_total:g}"
                 f"（Δ={delta:g} ≤ ε_Z={eps_z:g}）" if ok else
                 f"Δ={delta:g} > ε_Z={eps_z:g} ⇒ 两条路径目标值不一致，"
                 "须查共因错误或实现走样"),
                actual=objective.Z_total, expected=float(z_solver), delta=delta)

    # ---- RI-07 / RI-09 隔离（由 isolation 模块给出） ----------------------
    iso = dict(isolation or {})
    for key, item in (("ISO-1", "RI-07 隔离①源码不重叠"),
                      ("ISO-2", "RI-08 隔离②不共享可变状态"),
                      ("ISO-3", "RI-09 隔离③作者分离已签署")):
        st = iso.get(key)
        if st is None:
            add(item, STATUS_BLOCKED, "未提供该层隔离证明 ⇒ 不得当作已成立。")
        else:
            add(item, str(st.get("status", STATUS_BLOCKED)),
                str(st.get("reason", "")))

    # ---- RI-10 声明↔实现对账 ---------------------------------------------
    if declared:
        extra = [u for u in used if u not in declared]
        if extra:
            add("RI-10 声明↔实现对账", STATUS_FAIL,
                "实现读了制品未声明的输入：" + "、".join(extra) +
                "——制品漏写一条时实现多读一项**不报错**，判据整体变严却没信号。")
        else:
            add("RI-10 声明↔实现对账", STATUS_PASS,
                f"实现读取的 {len(used)} 项输入均在制品声明内。")
    else:
        add("RI-10 声明↔实现对账", STATUS_SKIP,
            "制品未声明输入集 ⇒ 无从对账（不判 PASS）。")

    return tuple(checks)


def reference_report(
    instance: Any,
    p_by_id: Mapping[str, float],
    *,
    resolved: Any = None,
    spec: Mapping[str, Any] | None = None,
    tolerances: Mapping[str, float] | None = None,
    z_solver: float | None = None,
    isolation: Mapping[str, Any] | None = None,
) -> RefReport:
    """一次完整的参考重算 + 判据聚合。"""
    snap = snapshot(instance, resolved)
    objective = ref_objective(snap, p_by_id) if snap.items else None
    residuals = (
        ref_residuals(snap, p_by_id) if objective is not None else ()
    )
    checks = judge_reference(
        objective, residuals,
        params=snap.params, spec=spec,
        declared_inputs=INPUT_NAMES,
        inputs_used=INPUT_NAMES,
        z_solver=z_solver, tolerances=tolerances, isolation=isolation,
    )
    return RefReport(
        objective=objective,
        residuals=residuals,
        checks=checks,
        inputs_used=INPUT_NAMES,
        isolation=dict(isolation or {}),
    )
