"""T04-01 Phase 1 解析解：排序 + 二分 + 贪心定容。

**为什么需要这一层**：Phase 2（LP/MILP）能给出 P_A 的最优解，但它给不出
「**为什么**是这个解」。T04-01 把 P_A 的**闭式结构**显式化——输出阈值 λ 与
层归属（顶格 / 内点 / 触底），于是「解为什么长这样」变成可读的一句话。
同时它是 T04-04 对拍的两方之一：解析路径与 LP 路径必须**独立**，任何一方
的 bug 都不会同时出现在另一方（见 ADR-0019 的证明路径选择）。

**三条最容易静默出错的地方，本层都用判据守住**：

1. **适用范围必须由 T04-00 的 verdict 决定**（PS-01）。在 EC-1..EC-7 之外，
   阈值分割解**不是** P_A 的最优解——此时「给一个解」比「拒绝」更危险：
   T04-04 会把它与 Phase 2 的解判成不一致，而不一致是**正确行为**，
   于是真正的 bug 被噪声淹没。
2. **排序键是 ``r_eff`` 而不是 ``r``**（PS-04/PS-05）。按 ``r`` 排序会得到
   满足全部约束但**次优**的解，不触发任何可行性检查（T04-00 CE-02；
   历史 bug ``∂Z/∂p = q1·r_eff`` 同族）。
3. **空 cap（不限价）不是 0、也不是一个大 M**（PS-07）。本层把它交给前缀和
   里的 ``+inf`` 自然处理：不限价项只可能是**临界项或触底项**，永远推不到上界。
   折成 0 会让 C2 变成 ``p ≤ 0``（与 C5 冲突）；写成一个 1e9 会在 B 较大时
   把该项「推满」，解不再是 P_A 的解。

设计纪律（与仓内其余模块同源）：

* **求解域与判据域分域**：本层只产出 ``OPTIMAL / INFEASIBLE / BLOCKED``；
  判据用 ``PASS / WARN / FAIL / BLOCKED / SKIP``（见 phase1_solver_spec.json）。
  ``INFEASIBLE`` **不是** ``BLOCKED``：前者是「算出来了，可行域为空」，
  后者是「算不出」，混同会让「B 定得太低」以「数据没齐」的样子长期留档。
* **不重实现既有口径**：``R_i`` / ``r_eff`` 的唯一实现在
  ``contracts.pricing_card``；箱型合并的唯一实现在 ``formulation.merged_lower``；
  目标值一律由 ``instance.check_solution``（独立裁判）给出——本层**不自报 Z**。
* **判据只吃「实例 + 解向量 + 制品声明」**，不读求解过程的中间量，
  因此可以用注入错解的方式验证判据本身在干活。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..contracts.pricing_card import ResolvedParameters
from .exactness import (
    VERDICT_EXACT,
    ExactnessVerdict,
    check_exactness,
)
from .formulation import compute_lb_c5, merged_lower, probe_instance
from .instance import (
    PRICE_RESOLUTION,
    ROLE_OPTIMIZABLE,
    Phase1Instance,
    Phase1Item,
    Phase1Params,
    SolutionCheck,
    check_solution,
)

SPEC_FILENAME = "phase1_solver_spec.json"

#: 判据范围前缀（与 EC / CC / BB / SV / DQ 并列）。
SCOPE = "PS"

# ---- 求解域（不是判据域）---------------------------------------------------
SOLUTION_OPTIMAL = "OPTIMAL"
SOLUTION_INFEASIBLE = "INFEASIBLE"
SOLUTION_BLOCKED = "BLOCKED"
_SOLUTION_DOMAIN = (SOLUTION_OPTIMAL, SOLUTION_INFEASIBLE, SOLUTION_BLOCKED)

# ---- 判据域 -----------------------------------------------------------------
from ..states import STATUS_PASS, STATUS_WARN, STATUS_FAIL, STATUS_BLOCKED, STATUS_SKIP, _STATUS_ORDER

# ---- 解的定位 ---------------------------------------------------------------
ROLE_CANDIDATE = "candidate"
RELATION_TO_FULL_PROBLEM = (
    "P_A 是完整模型（含 C6..C12）关闭「会改变 LP 结构的软约束」后的松弛 "
    "⇒ 本层目标值是完整问题最优值的上界"
)

# ---- tie-break --------------------------------------------------------------
TIE_BREAK_CANONICAL_ITEM_ID = "CANONICAL_ITEM_ID"
#: 本层**已实现**的 tie-break 策略。实例声明了其它策略 ⇒ BLOCKED（机制缺失），
#: 不得静默改用它没声明过的次序（那就等于替被复核对象选了一个解）。
SUPPORTED_TIE_BREAKS: tuple[str, ...] = (TIE_BREAK_CANONICAL_ITEM_ID,)

# ---- 层域（impl_plan_v321 §4.2）--------------------------------------------
LAYER_LOW = "BOUNDARY_LOW"
LAYER_INTERIOR = "INTERIOR"
LAYER_HIGH = "BOUNDARY_HIGH"
LAYER_FIXED = "FIXED"
LAYER_INFEASIBLE = "INFEASIBLE"
LAYER_VALUES: tuple[str, ...] = (
    LAYER_LOW, LAYER_INTERIOR, LAYER_HIGH, LAYER_FIXED, LAYER_INFEASIBLE,
)

# ---- λ 的种类 ---------------------------------------------------------------
LAMBDA_INTERIOR = "INTERIOR"
LAMBDA_BOUNDARY_EXACT = "BOUNDARY_EXACT"
LAMBDA_PLATFORM = "PLATFORM"
LAMBDA_ALL_AT_UPPER = "ALL_AT_UPPER"
LAMBDA_NONE = "NONE"

# ---- 精度缺省（仅作函数签名完整之用，**不构成项目口径**）---------------------
DEFAULT_EPS_ABS = 0.01
DEFAULT_EPS_PRICE = 1e-9

#: 排序键比较容差（与 T04-00 的 ``EPS_R`` 同源同值）。
EPS_R = 1e-6

#: PS-06 的交换见证最多试多少对（防止 O(n²) 在大实例上失控）。被截断时
#: ``tested`` 仍如实计数，判据只要求「至少走到一个」。
MAX_EXCHANGE_PROBES = 200


class Phase1Error(ValueError):
    """本层的不合法调用（结构错误，非数据问题）。"""


# ---------------------------------------------------------------------------
# 载体
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Phase1Check:
    """一条具名判据结果（与 ``DerivedCheck`` 同构，便于统一渲染）。"""

    scope: str
    item: str
    status: str
    reason: str
    actual: Any = None
    expected: Any = None

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
            "blocks_progress": self.blocks_progress,
        }


@dataclass(frozen=True)
class TierAssignment:
    """一个可优化项的解与层归属。"""

    item_id: str
    r_eff: float | None
    p: float | None
    lower: float | None
    upper: float | None
    layer: str
    reason: str = ""
    #: 排序位次（0 = 最高 r_eff）。便于与 λ 对照读。
    rank: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "r_eff": self.r_eff,
            "p": self.p,
            "lower": self.lower,
            "upper": self.upper,
            "layer": self.layer,
            "reason": self.reason,
            "rank": self.rank,
        }


@dataclass(frozen=True)
class LambdaInfo:
    """C1 的对偶乘子 = 排序键阈值。"""

    value: float | None
    kind: str
    interval: tuple[float, float] | None = None
    critical_item: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "kind": self.kind,
            "interval": list(self.interval) if self.interval else None,
            "critical_item": self.critical_item,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Phase1Solution:
    """本层的输出。

    **刻意不自报 Z**：目标值一律由 ``check_solution``（独立裁判）给出，
    本层再算一遍 R_i 就等于自造第二个事实源（PS-10）。
    """

    status: str
    role: str = ROLE_CANDIDATE
    is_final: bool = False
    relates_to_full_problem: str = RELATION_TO_FULL_PROBLEM
    applicability: str = ""
    #: 逐项解与层归属（只含可优化项，按 rank 排列）。
    assignments: tuple[TierAssignment, ...] = ()
    #: **完整**报价向量（可优化项 = 算法值；非可优化项 = 其给定基准 p0）。
    p_by_id: Mapping[str, float] = field(default_factory=dict)
    lam: LambdaInfo = field(
        default_factory=lambda: LambdaInfo(None, LAMBDA_NONE)
    )
    notes: tuple[str, ...] = ()
    reason: str = ""

    # ---- 便捷视图 -------------------------------------------------------
    @property
    def optimal(self) -> bool:
        return self.status == SOLUTION_OPTIMAL

    def p_opt_by_id(self) -> dict[str, float]:
        """只含可优化项的报价向量（与 LP 的变量表同域）。"""
        ids = {a.item_id for a in self.assignments}
        return {k: v for k, v in self.p_by_id.items() if k in ids}

    def layer_of(self, item_id: str) -> str | None:
        for a in self.assignments:
            if a.item_id == item_id:
                return a.layer
        return None

    def layers(self) -> dict[str, str]:
        return {a.item_id: a.layer for a in self.assignments}

    def of(self, item_id: str) -> TierAssignment | None:
        for a in self.assignments:
            if a.item_id == item_id:
                return a
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "role": self.role,
            "is_final": self.is_final,
            "relates_to_full_problem": self.relates_to_full_problem,
            "applicability": self.applicability,
            "lambda": self.lam.to_dict(),
            "layers": self.layers(),
            "assignments": [a.to_dict() for a in self.assignments],
            "p_by_id": {k: self.p_by_id[k] for k in sorted(self.p_by_id)},
            "notes": list(self.notes),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Phase1Report:
    """解 + 判据 + 独立裁判结论。"""

    solution: Phase1Solution
    checks: tuple[Phase1Check, ...]
    exactness: ExactnessVerdict | None = None
    referee: SolutionCheck | None = None

    def verdict(self) -> str:
        """聚合判定：取最严；**空判据集 ⇒ BLOCKED**（「没判过」不是 PASS）。"""
        if not self.checks:
            return STATUS_BLOCKED
        seen = {c.status for c in self.checks}
        for s in _STATUS_ORDER:
            if s in seen:
                return s
        return STATUS_BLOCKED  # pragma: no cover - 状态域封闭，兜底

    def of(self, judge_id: str) -> Phase1Check | None:
        for c in self.checks:
            if c.item == judge_id:
                return c
        return None

    def blocking(self) -> tuple[Phase1Check, ...]:
        return tuple(c for c in self.checks if c.blocks_progress)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict(),
            "exactness": self.exactness.to_dict() if self.exactness else None,
            "solution": self.solution.to_dict(),
            "referee": self.referee.to_dict() if self.referee else None,
            "checks": [c.to_dict() for c in self.checks],
        }


# ---------------------------------------------------------------------------
# 规格加载
# ---------------------------------------------------------------------------


def load_phase1_spec(config_dir: Path) -> dict[str, Any]:
    """读取受控制品 ``config/phase1_solver_spec.json``。"""
    path = Path(config_dir) / SPEC_FILENAME
    if not path.exists():
        raise Phase1Error(f"Phase 1 解析解规格不存在：{path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# 行构造（与 LP **共用**箱型口径）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Row:
    item: Phase1Item
    q0: float | None
    r_eff: float | None
    lower: float | None
    upper: float | None
    problem: str = ""

    @property
    def usable(self) -> bool:
        return (
            not self.problem
            and self.q0 is not None
            and self.q0 > 0
            and self.r_eff is not None
            and self.lower is not None
        )


def _reference_price(instance: Phase1Instance) -> float | None:
    """C5 与 lb_C5 的参考价：优先 P*，缺失时退回 B（与 formulation 同口径）。"""
    if instance.P_star is not None:
        return float(instance.P_star)
    if instance.B is not None:
        return float(instance.B)
    return None


def _rows(
    instance: Phase1Instance,
    resolved: ResolvedParameters,
    *,
    eps_price: float,
    resolution: float,
    floor_by_id: Mapping[str, float] | None,
) -> list[_Row]:
    """逐项构造求解行。``lower`` 走 ``formulation.merged_lower``（唯一实现）。"""
    P_ref = _reference_price(instance)
    lb_c5 = 0.0 if P_ref is None else compute_lb_c5(P_ref, eps_price, resolution)
    out: list[_Row] = []
    for item in instance.opt_items:
        q0 = item.q0
        r_eff = instance.r_eff(item, resolved)
        lower = merged_lower(item, lb_c5, floor_by_id)
        problem = ""
        if q0 is None:
            problem = "q0 缺失（EC-3）"
        elif q0 <= 0:
            problem = "q0 ≤ 0，r 无定义（EC-3）"
        elif r_eff is None:
            problem = "r_eff 算不出（q1_point 或 q0 缺失）"
        elif lower is None:
            problem = "下界算不出（L / floor / lb_C5 全缺）"
        out.append(
            _Row(item=item, q0=q0, r_eff=r_eff, lower=lower,
                 upper=item.U, problem=problem)
        )
    return out


def _sort_key(row: _Row) -> tuple[float, str]:
    """排序：先按 **r_eff 降序**，再按 item_id 升序（确定性 = canonical tie-break）。

    次键必须写死：platform（多个项 r_eff 相同）下，不同的次序给出**不同的
    最优解**，而 §4.1 的三级变量一致性判定要求一个确定的代表元。
    """
    eff = row.r_eff if row.r_eff is not None else float("-inf")
    return (-eff, row.item.item_id)


# ---------------------------------------------------------------------------
# 求解
# ---------------------------------------------------------------------------


def solve_phase1(
    instance: Phase1Instance,
    resolved: ResolvedParameters,
    *,
    eps_abs: float = DEFAULT_EPS_ABS,
    eps_price: float = DEFAULT_EPS_PRICE,
    resolution: float = PRICE_RESOLUTION,
    floor_by_id: Mapping[str, float] | None = None,
) -> Phase1Solution:
    """求 P_A 的解析候选解（排序 + 二分 + 贪心定容）。

    **不做可行性复核**（交 ``check_solution`` / T04-02D）、**不做数值稳定化**
    （交 T04-06）、**不做对拍**（交 T04-04）。只回答「按阈值分割结构，各项该
    取什么值」。
    """
    verdict = check_exactness(
        instance, resolved, eps_abs=eps_abs, eps_price=eps_price
    )

    # ---- 适用范围守卫（PS-01）------------------------------------------
    if verdict.verdict != VERDICT_EXACT:
        name = {
            "EC-1": "C1 作用域完备性", "EC-2": "排序键正确性", "EC-3": "权重正性",
            "EC-4": "系数非负性", "EC-5": "非退化", "EC-6": "软约束不激活",
            "EC-7": "可行域非空且边界自洽",
        }
        denied = [
            f"{c.id}({name.get(c.id, c.name)})={c.status}"
            for c in verdict.conditions
            if c.id in ("EC-1", "EC-2", "EC-3", "EC-4", "EC-5", "EC-6", "EC-7")
            and c.status in (STATUS_FAIL, STATUS_BLOCKED)
        ]
        return Phase1Solution(
            status=SOLUTION_BLOCKED,
            applicability=verdict.verdict,
            notes=verdict.implementation_notes,
            reason=(
                f"不在 T04-00 证明的适用子集内（verdict={verdict.verdict}）——"
                "阈值分割解在此实例上不保证是 P_A 的最优解，本层拒绝给解。"
                "被否定的 A 组条件：" + ("、".join(denied) if denied else "（无）")
                + "。**两条路径不一致在此处是正确行为**，不得据此判模型有 bug"
                "（impl_plan_v321 §4.1）。"
            ),
        )

    # ---- tie-break 政策（平台下才需要）-----------------------------------
    policy = instance.tie_break_policy
    if policy is not None and policy not in SUPPORTED_TIE_BREAKS:
        return Phase1Solution(
            status=SOLUTION_BLOCKED,
            applicability=verdict.verdict,
            notes=verdict.implementation_notes,
            reason=(
                f"实例声明 tie_break_policy={policy!r}，不在本层支持集 "
                f"{list(SUPPORTED_TIE_BREAKS)} 内 ⇒ BLOCKED（机制缺失，"
                "never_downgrade）。**不得**静默改用默认次序——那等于替被复核"
                "对象选了一个它没声明过的解。"
            ),
        )

    rows = _rows(
        instance, resolved, eps_price=eps_price,
        resolution=resolution, floor_by_id=floor_by_id,
    )
    if not rows:
        return Phase1Solution(
            status=SOLUTION_BLOCKED, applicability=verdict.verdict,
            reason="实例没有可优化项——EC-1 本应拦下（无变量可优化）。",
        )
    bad = [r for r in rows if not r.usable]
    if bad:
        detail = "、".join(f"{r.item.item_id}({r.problem})" for r in bad)
        return Phase1Solution(
            status=SOLUTION_BLOCKED, applicability=verdict.verdict,
            reason=f"以下可优化项的求解输入算不出：{detail}——不得降级为 0。",
        )

    # ---- 非可优化项必须有给定基准价，否则向量不完整 ----------------------
    fixed: dict[str, float] = {}
    missing_fixed: list[str] = []
    for item in instance.items:
        if item.role == ROLE_OPTIMIZABLE:
            continue
        if item.p0 is None:
            missing_fixed.append(item.item_id)
        else:
            fixed[item.item_id] = float(item.p0)
    if missing_fixed:
        return Phase1Solution(
            status=SOLUTION_BLOCKED, applicability=verdict.verdict,
            reason=(
                "非可优化项缺基准单价 p0：" + "、".join(missing_fixed)
                + "——报价向量会不完整，check_solution 将逐项报「解中缺该变量」。"
                "非可优化项的单价由招标给定，不是决策变量，故**不得**由本层推测。"
            ),
        )

    B = float(instance.B)  # EC-7 已保证非 None
    eps_total = max(float(eps_abs), float(eps_price) * B)

    # ---- 排序 + 前缀和 + 二分 -------------------------------------------
    ordered = sorted(rows, key=_sort_key)
    n = len(ordered)
    prefix = [0.0] * (n + 1)
    prefix[0] = sum(float(r.q0) * float(r.lower) for r in ordered)
    for k in range(1, n + 1):
        r = ordered[k - 1]
        prev = prefix[k - 1]
        if prev == float("inf") or r.upper is None:
            prefix[k] = float("inf")
        else:
            prefix[k] = prev + float(r.q0) * (float(r.upper) - float(r.lower))

    if prefix[0] > B + eps_total:
        return Phase1Solution(
            status=SOLUTION_INFEASIBLE, applicability=verdict.verdict,
            notes=verdict.implementation_notes,
            reason=(
                f"P_A 可行域为空：B = {B:g} < P_min = Σ lb_i·q0_i = {prefix[0]:g}。"
                "按 §6.3 应走「放弃投标 / 上调 P* 重新预检」判据表，"
                "**不得**借不平衡报价把不可行变成「可行」（EC-7 / CE-07）。"
            ),
        )

    k_star = 0
    for k in range(1, n + 1):
        if prefix[k] <= B + eps_total:
            k_star = k
        else:
            break
    if k_star == n and prefix[n] != float("inf") and B > prefix[n] + eps_total:
        return Phase1Solution(
            status=SOLUTION_INFEASIBLE, applicability=verdict.verdict,
            notes=verdict.implementation_notes,
            reason=(
                f"P_A 可行域为空：B = {B:g} > P_max = Σ ub_i·q0_i = {prefix[n]:g}。"
                "（EC-7 在全部上界有限时本应拦下；此处兜底。）"
            ),
        )

    p_by_id: dict[str, float] = dict(fixed)
    assignments: list[TierAssignment] = []
    for idx, row in enumerate(ordered):
        iid = row.item.item_id
        lo = float(row.lower)
        hi = None if row.upper is None else float(row.upper)
        if idx < k_star:
            p = hi  # 顶格（k* 以内必为有限上界，见 spec.algorithm.null_cap_branch）
            layer = _layer_for(p, lo, hi)
            reason = "位于阈值上方 ⇒ 顶格取 cap"
        elif idx > k_star:
            p = lo
            layer = _layer_for(p, lo, hi)
            reason = "位于阈值下方 ⇒ 触底取下界"
        else:
            residual = B - prefix[k_star]
            p = lo + residual / float(row.q0)
            layer = _layer_for(p, lo, hi)
            reason = (
                f"临界项：承载残差 {residual:g} ⇒ p = lb + 残差/q0"
            )
        p_by_id[iid] = p
        assignments.append(
            TierAssignment(
                item_id=iid, r_eff=row.r_eff, p=p, lower=lo, upper=hi,
                layer=layer, reason=reason, rank=idx,
            )
        )

    lam = _lambda_info(ordered, k_star, prefix, B, assignments, eps_total)

    return Phase1Solution(
        status=SOLUTION_OPTIMAL,
        applicability=verdict.verdict,
        assignments=tuple(assignments),
        p_by_id=p_by_id,
        lam=lam,
        notes=verdict.implementation_notes,
        reason=(
            f"适用子集内（verdict=EXACT）；排序位次 k* = {k_star}（前 {k_star} 项"
            f"顶格、后 {n - k_star - 1} 项触底、第 {k_star + 1} 项为临界项）；"
            f"λ = {lam.value}（{lam.kind}）。"
        ),
    )


def _layer_for(p: float, lo: float, hi: float | None) -> str:
    """由数值反推层归属（判定次序写死：FIXED → LOW/HIGH → INTERIOR）。

    容差用 ``PRICE_RESOLUTION`` 的一半以外的**极紧**口径（1e-9 元相对量级）
    是危险的——那会让「p 与 ub 差 1e-10」被判成内点。此处用**具名**的
    分辨率半宽 ``PRICE_RESOLUTION / 2``，与 EC-8 的舍入半宽同源。
    """
    tol = PRICE_RESOLUTION / 2.0
    if hi is not None and abs(hi - lo) <= tol:
        return LAYER_FIXED
    if hi is not None and p >= hi - tol:
        return LAYER_HIGH
    if p <= lo + tol:
        return LAYER_LOW
    return LAYER_INTERIOR


def _lambda_info(
    ordered: Sequence[_Row],
    k_star: int,
    prefix: Sequence[float],
    B: float,
    assignments: Sequence[TierAssignment],
    eps_total: float,
) -> LambdaInfo:
    """λ = 临界项的 ``r_eff``（**不是** r、不是 1+alpha）。"""
    n = len(ordered)
    if k_star >= n:
        return LambdaInfo(
            value=None, kind=LAMBDA_ALL_AT_UPPER,
            reason=(
                "全部可优化项顶格（k* = n，上界全有限）⇒ 无临界项，"
                "λ 只满足 λ ≤ min r_eff，取值不唯一。"
            ),
        )
    crit = ordered[k_star]
    a = assignments[k_star]
    eff = float(crit.r_eff)
    residual = B - prefix[k_star]
    same = [
        r.item.item_id for r in ordered[k_star + 1:]
        if r.r_eff is not None and abs(float(r.r_eff) - eff) <= EPS_R
    ]
    if same:
        return LambdaInfo(
            value=eff, kind=LAMBDA_PLATFORM, critical_item=a.item_id,
            interval=(eff, eff),
            reason=(
                "临界项与 " + "、".join(same) + " 的 r_eff 相同（EC-5 平台）"
                "⇒ λ 唯一，但临界组内部的取值由 tie_break 决定。"
            ),
        )
    if residual <= eps_total:
        lo_eff = (
            float(ordered[k_star + 1].r_eff)
            if k_star + 1 < n and ordered[k_star + 1].r_eff is not None
            else eff
        )
        return LambdaInfo(
            value=eff, kind=LAMBDA_BOUNDARY_EXACT, critical_item=a.item_id,
            interval=(min(lo_eff, eff), max(lo_eff, eff)),
            reason=(
                f"残差 {residual:g} ≈ 0 ⇒ S(k*) 恰等于 B，临界项落在其下界；"
                "合法 λ 是闭区间（对偶有一段平台），报下端。"
            ),
        )
    return LambdaInfo(
        value=eff, kind=LAMBDA_INTERIOR, critical_item=a.item_id,
        interval=(eff, eff),
        reason=f"残差 {residual:g} > 0 ⇒ 临界项严格落在箱内，λ 唯一确定。",
    )


# ---------------------------------------------------------------------------
# 判据：PS-01..PS-11
# ---------------------------------------------------------------------------


def judge_phase1(
    instance: Phase1Instance,
    resolved: ResolvedParameters,
    solution: Phase1Solution,
    *,
    eps_abs: float = DEFAULT_EPS_ABS,
    eps_price: float = DEFAULT_EPS_PRICE,
    resolution: float = PRICE_RESOLUTION,
    floor_by_id: Mapping[str, float] | None = None,
    tolerances: Mapping[str, float] | None = None,
    declared_inputs: Iterable[str] | None = None,
    exactness: ExactnessVerdict | None = None,
) -> tuple[Phase1Check, ...]:
    """对 ``solution`` 跑 PS-01..PS-11。

    **判据只吃「实例 + 解向量 + 制品声明」**——不读求解过程的中间量。
    因此它可以用**注入错解**的方式被验证：把 ``solution`` 换成篡改过的对象，
    对应判据必须翻成 FAIL。做不到这一点的判据等于没有。
    """
    checks: list[Phase1Check] = []
    checks.append(_ps01(instance, resolved, solution, exactness,
                        eps_abs=eps_abs, eps_price=eps_price))

    if not solution.optimal:
        # 没产出解 ⇒ 需要解向量的判据**无样本**，判 SKIP（不是 PASS，也不是 FAIL）。
        for jid, claim in (
            ("PS-02", "C1 等式满足"),
            ("PS-03", "箱型满足"),
            ("PS-04", "λ / 层 / 数值三者一致"),
            ("PS-05", "阈值结构存在"),
            ("PS-06", "无有利成对交换"),
            ("PS-07", "不限价项处置正确"),
            ("PS-08", "层划分完备且数值一致"),
        ):
            checks.append(Phase1Check(
                SCOPE, jid, STATUS_SKIP,
                f"本轮没产出解（status={solution.status}）⇒ {claim}无样本可判。"
                "**SKIP 不是 PASS**：这不是「已成立」，也不是「已违反」。",
            ))
        checks.append(_ps09(solution))
        checks.append(Phase1Check(
            SCOPE, "PS-10", STATUS_SKIP,
            "无解 ⇒ 无独立裁判可跑（check_solution 需要完整报价向量）。",
        ))
        checks.append(_ps11(declared_inputs, sample=False))
        return tuple(checks)

    rows = _rows(
        instance, resolved, eps_price=eps_price,
        resolution=resolution, floor_by_id=floor_by_id,
    )
    lb_c5 = 0.0
    P_ref = _reference_price(instance)
    if P_ref is not None:
        lb_c5 = compute_lb_c5(P_ref, eps_price, resolution)
    eps_total = (
        None if instance.B is None
        else max(float(eps_abs), float(eps_price) * float(instance.B))
    )

    referee = check_solution(
        instance, dict(solution.p_by_id), resolved,
        eps_total=eps_total, tolerances=tolerances,
    )

    checks.append(_ps02(referee, eps_total))
    checks.append(_ps03(rows, solution, tolerances))
    checks.append(_ps04(solution, rows))
    checks.append(_ps05(solution, rows))
    checks.append(_ps06(instance, resolved, solution, referee, eps_total))
    checks.append(_ps07(instance, rows, solution))
    checks.append(_ps08(rows, solution))
    checks.append(_ps09(solution))
    checks.append(_ps10(solution))
    checks.append(_ps11(declared_inputs, sample=True))
    return tuple(checks)


def _ps01(
    instance: Phase1Instance,
    resolved: ResolvedParameters,
    solution: Phase1Solution,
    exactness: ExactnessVerdict | None,
    *,
    eps_abs: float,
    eps_price: float,
) -> Phase1Check:
    """适用范围守卫：只在 EXACT 上给解。"""
    verdict = exactness or check_exactness(
        instance, resolved, eps_abs=eps_abs, eps_price=eps_price
    )
    if verdict.verdict == VERDICT_EXACT and solution.optimal:
        return Phase1Check(
            SCOPE, "PS-01", STATUS_PASS,
            f"verdict=EXACT ⇒ 适用子集内，已给解（{len(solution.assignments)} 项）。",
            actual=verdict.verdict, expected=VERDICT_EXACT,
        )
    if verdict.verdict != VERDICT_EXACT and not solution.optimal:
        return Phase1Check(
            SCOPE, "PS-01", STATUS_PASS,
            f"verdict={verdict.verdict} ⇒ 正确地拒绝了给解（status={solution.status}）。"
            "**在适用子集之外给解才是缺陷**：那会让 T04-04 把「不一致」（正确行为）"
            "误读成 bug。",
            actual=(verdict.verdict, solution.status), expected="拒绝给解",
        )
    if verdict.verdict != VERDICT_EXACT and solution.optimal:
        return Phase1Check(
            SCOPE, "PS-01", STATUS_BLOCKED,
            f"verdict={verdict.verdict} 却给出了解 —— 越界给解。",
            actual=verdict.verdict, expected="非 EXACT 时不得给解",
        )
    return Phase1Check(
        SCOPE, "PS-01", STATUS_BLOCKED,
        "verdict=EXACT 但未产出解（status=" + solution.status + "）——"
        "守卫放过了，求解却又退回了。",
        actual=solution.status, expected=SOLUTION_OPTIMAL,
    )


def _ps02(referee: SolutionCheck, eps_total: float | None) -> Phase1Check:
    """C1 等式满足——由 check_solution **跨来源**代回。"""
    if eps_total is None:
        return Phase1Check(
            SCOPE, "PS-02", STATUS_BLOCKED,
            "实例未给出 B ⇒ eps_total 算不出 ⇒ **口径不可比不是 PASS 也不是 FAIL**"
            "（ADR-0013）。",
        )
    if referee.c1_residual is None:
        return Phase1Check(
            SCOPE, "PS-02", STATUS_BLOCKED,
            "裁判未给出 C1 残差（实例缺 B）⇒ 本轮没查成。",
        )
    ok = abs(referee.c1_residual) <= eps_total
    return Phase1Check(
        SCOPE, "PS-02", STATUS_PASS if ok else STATUS_FAIL,
        (f"C1 残差 {referee.c1_residual:g} ≤ eps_total {eps_total:g}"
         if ok else
         f"C1 残差 {referee.c1_residual:g} > eps_total {eps_total:g}"
         "——解不满足总价锁定（或实现把 ub/lb 用反、临界项没承载残差）。"),
        actual=referee.c1_residual, expected=f"|残差| <= {eps_total:g}",
    )


def _ps03(
    rows: Sequence[_Row],
    solution: Phase1Solution,
    tolerances: Mapping[str, float] | None,
) -> Phase1Check:
    """箱型满足——具名容差；不限价项不判上界。"""
    if tolerances is None:
        return Phase1Check(
            SCOPE, "PS-03", STATUS_BLOCKED,
            "未给**具名**容差表 ⇒ 盒式约束两侧口径不可比 ⇒ BLOCKED。"
            "不得按严格算术冒充一个可行性结论（DV-01 的直接教训）。",
        )
    eps_box = tolerances.get("eps_price")
    if eps_box is None:
        return Phase1Check(
            SCOPE, "PS-03", STATUS_BLOCKED,
            "容差表里没有 eps_price ⇒ 该名解析不出数值 ⇒ BLOCKED"
            "（**不得**静默按 0）。",
        )
    eps_box = float(eps_box)
    bad: list[str] = []
    for row in rows:
        a = solution.of(row.item.item_id)
        if a is None or a.p is None:
            bad.append(f"{row.item.item_id}: 解中缺该变量")
            continue
        if a.p < float(row.lower) - eps_box:
            bad.append(f"{row.item.item_id}: p={a.p:g} < lb={row.lower:g}")
        if row.upper is not None and a.p > float(row.upper) + eps_box:
            bad.append(f"{row.item.item_id}: p={a.p:g} > ub={row.upper:g}")
        if a.p <= 0:
            bad.append(f"{row.item.item_id}: p={a.p:g} ≤ 0（C5）")
    return Phase1Check(
        SCOPE, "PS-03", STATUS_PASS if not bad else STATUS_FAIL,
        ("全部可优化项落在箱型内（不限价项不判上界）" if not bad
         else "箱型违反：" + "；".join(bad)),
        actual=bad or None, expected="逐项 lb ≤ p ≤ ub（具名容差 eps_price）",
    )


def _ps04(solution: Phase1Solution, rows: Sequence[_Row]) -> Phase1Check:
    """λ / 层 / 数值三者一致（读自报，不重算阈值）。"""
    lam = solution.lam
    if lam.value is None:
        # ALL_AT_UPPER 是合法的「λ 不唯一」，不算缺陷；但层必须全是顶格。
        act = {a.layer for a in solution.assignments}
        if lam.kind != LAMBDA_ALL_AT_UPPER:
            return Phase1Check(
                SCOPE, "PS-04", STATUS_BLOCKED,
                f"λ 未定（kind={lam.kind}）而解已产出 ⇒ 未定态被降级。",
            )
        ok = act <= {LAYER_HIGH, LAYER_FIXED}
        return Phase1Check(
            SCOPE, "PS-04", STATUS_PASS if ok else STATUS_FAIL,
            ("k* = n：全部顶格且 λ 如实未定" if ok
             else f"λ 报 ALL_AT_UPPER 却有非顶格项：{sorted(act)}"),
            actual=sorted(act), expected=sorted({LAYER_HIGH, LAYER_FIXED}),
        )
    crit = solution.of(lam.critical_item or "")
    if crit is None or crit.r_eff is None:
        return Phase1Check(
            SCOPE, "PS-04", STATUS_FAIL,
            f"自报临界项 {lam.critical_item!r} 不在解里（或 r_eff 缺失）。",
        )
    # ★ λ 必须等于临界项的 **r_eff**。若实现误用 r（或 1+alpha），此处即分岔。
    if abs(float(crit.r_eff) - float(lam.value)) > EPS_R:
        return Phase1Check(
            SCOPE, "PS-04", STATUS_FAIL,
            f"自报 λ={lam.value:g} ≠ 临界项 r_eff={crit.r_eff:g}——"
            "排序键被误用（写成 r 或 1+alpha 即 EC-2/CE-02 的失效模式）。",
            actual=lam.value, expected=crit.r_eff,
        )
    # 层必须与 λ 单调一致：r_eff > λ ⇒ 只能顶格；r_eff < λ ⇒ 只能触底。
    bad: list[str] = []
    for row in rows:
        a = solution.of(row.item.item_id)
        if a is None or a.r_eff is None:
            continue
        if float(a.r_eff) > float(lam.value) + EPS_R and a.layer == LAYER_LOW:
            bad.append(f"{a.item_id}(r_eff={a.r_eff:g} > λ 却触底)")
        if float(a.r_eff) < float(lam.value) - EPS_R and a.layer == LAYER_HIGH:
            bad.append(f"{a.item_id}(r_eff={a.r_eff:g} < λ 却顶格)")
    return Phase1Check(
        SCOPE, "PS-04", STATUS_PASS if not bad else STATUS_FAIL,
        (f"λ={lam.value:g}（{lam.kind}，临界项 {lam.critical_item}）与层归属单调一致"
         if not bad else "层与 λ 不一致：" + "；".join(bad)),
        actual=bad or None, expected="r_eff>λ ⇒ 顶格；r_eff<λ ⇒ 触底",
    )


def _ps05(solution: Phase1Solution, rows: Sequence[_Row]) -> Phase1Check:
    """阈值结构存在——**不引用自报 λ**，直接从 (p, r_eff) 的成对蕴含重判。"""
    pairs = [
        (solution.of(r.item.item_id), r) for r in rows
    ]
    pairs = [(a, r) for a, r in pairs if a is not None and a.r_eff is not None]
    if len(pairs) < 2:
        return Phase1Check(
            SCOPE, "PS-05", STATUS_PASS,
            f"可比较项仅 {len(pairs)} 个 ⇒ 无成对蕴含可查。",
        )
    tol = PRICE_RESOLUTION / 2.0
    bad: list[str] = []
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            ai, ri = pairs[i]
            aj, rj = pairs[j]
            if float(ri.r_eff) <= float(rj.r_eff) + EPS_R:
                continue
            # r_eff_i 严格更高 ⇒ i 必须「已顶格」或 j 「已触底」。
            i_sat = ri.upper is not None and ai.p >= float(ri.upper) - tol
            j_floored = aj.p <= float(rj.lower) + tol
            if not i_sat and not j_floored:
                bad.append(
                    f"{ri.item.item_id}(r_eff={ri.r_eff:g}) 未顶格而 "
                    f"{rj.item.item_id}(r_eff={rj.r_eff:g}) 未触底"
                )
    return Phase1Check(
        SCOPE, "PS-05", STATUS_PASS if not bad else STATUS_FAIL,
        ("存在阈值 λ 使顶格集/触底集与 r_eff 单调一致" if not bad
         else "不存在这样的阈值：" + "；".join(bad[:5])),
        actual=bad or None,
        expected="r_eff 更高的项必须已顶格，或对手项已触底",
    )


def _ps06(
    instance: Phase1Instance,
    resolved: ResolvedParameters,
    solution: Phase1Solution,
    referee: SolutionCheck,
    eps_total: float | None,
) -> Phase1Check:
    """数值交换见证——用 ``check_solution`` 复算 Z'，要求无有利交换。"""
    if eps_total is None:
        return Phase1Check(
            SCOPE, "PS-06", STATUS_BLOCKED,
            "缺 B ⇒ eps_Z 与 C1 都不可比 ⇒ BLOCKED。",
        )
    base = dict(solution.p_by_id)
    rows = [
        (a.item_id, a.p, a.lower, a.upper)
        for a in solution.assignments
        if a.p is not None and a.lower is not None
    ]
    z0 = referee.Z
    tol = PRICE_RESOLUTION / 2.0
    tested = 0
    improving: list[str] = []
    # ★ 必须遍历**有序**对：交换是定向的（i 下调、j 上调）。只扫 i<j 会漏掉
    #   一半方向——而「让高 r_eff 项上调、低 r_eff 项下调」这一半恰恰是次优解
    #   的常见形态（首版即因此漏判，被本文件的用例照出）。
    for i in range(len(rows)):
        if tested >= MAX_EXCHANGE_PROBES:
            break
        for j in range(len(rows)):
            if tested >= MAX_EXCHANGE_PROBES:
                break
            if i == j:
                continue
            id_i, p_i, lb_i, _ub_i = rows[i]
            id_j, p_j, lb_j, ub_j = rows[j]
            qi = _q0_of(instance, id_i)
            qj = _q0_of(instance, id_j)
            if qi is None or qj is None or qi <= 0 or qj <= 0:
                continue
            room_i = qi * (p_i - lb_i)
            room_j = float("inf") if ub_j is None else qj * (ub_j - p_j)
            delta = min(room_i, room_j)
            if delta <= tol:
                continue
            tested += 1
            trial = dict(base)
            trial[id_i] = p_i - delta / qi
            trial[id_j] = p_j + delta / qj
            got = check_solution(instance, trial, resolved, eps_total=eps_total)
            if got.Z > z0 + eps_total:
                improving.append(
                    f"{id_i}↓{delta:g} / {id_j}↑：Z'={got.Z:g} > Z={z0:g}"
                )
    if tested == 0:
        return Phase1Check(
            SCOPE, "PS-06", STATUS_SKIP,
            "本轮没有任何「可下调项 × 可上调项」的对 ⇒ **容差/交换根本没被走到**"
            "（典型：所有项都贴在边界上）。这是「这一轮没走到」，不是「已成立」，"
            "也不是「已违反」。",
        )
    return Phase1Check(
        SCOPE, "PS-06", STATUS_PASS if not improving else STATUS_FAIL,
        (f"{tested} 对交换全部无利（Z 单调不增）⇒ 局部最优（交换论证）成立"
         if not improving else
         "存在有利交换 ⇒ 解**满足全部约束但次优**："
         + "；".join(improving[:3])
         + "（这类错误不触发任何可行性检查——只有换一条求值路径才照得出来）"),
        actual=improving or None, expected="全部交换 ΔZ ≤ eps_Z",
    )


def _q0_of(instance: Phase1Instance, item_id: str) -> float | None:
    for item in instance.items:
        if item.item_id == item_id:
            return None if item.q0 is None else float(item.q0)
    return None


def _ps07(
    instance: Phase1Instance,
    rows: Sequence[_Row],
    solution: Phase1Solution,
) -> Phase1Check:
    """不限价项（cap 空）的处置：不得折 0、不得用大 M 推满。"""
    free = [r for r in rows if r.upper is None]
    if not free:
        return Phase1Check(
            SCOPE, "PS-07", STATUS_PASS,
            "本实例没有不限价项（cap 全非空）⇒ 该分支不适用。",
        )
    B = instance.B
    if B is None:
        return Phase1Check(
            SCOPE, "PS-07", STATUS_BLOCKED,
            "含不限价项但缺 B ⇒ C1 给出的隐式上界算不出 ⇒ 本轮没查成。",
        )
    lb_load_others = sum(
        float(r.q0) * float(r.lower)
        for r in rows
        if r.upper is not None
    )
    bad: list[str] = []
    for r in free:
        a = solution.of(r.item.item_id)
        if a is None or a.p is None:
            bad.append(f"{r.item.item_id}: 解中缺该变量")
            continue
        if a.p <= 0:
            bad.append(f"{r.item.item_id}: p={a.p:g} ≤ 0（把空 cap 折成了 0）")
        if a.p < float(r.lower) - PRICE_RESOLUTION / 2.0:
            bad.append(f"{r.item.item_id}: p={a.p:g} < lb={r.lower:g}")
        # C1 给出的隐式上界：p_i·q0_i ≤ B − Σ_{其它项} lb_j·q0_j
        ub_c1 = (float(B) - lb_load_others) / float(r.q0)
        if a.p > ub_c1 + 1e-6:
            bad.append(
                f"{r.item.item_id}: p={a.p:g} > C1 隐式上界 {ub_c1:g}"
                "（把不限价当成了一个大 M）"
            )
    return Phase1Check(
        SCOPE, "PS-07", STATUS_PASS if not bad else STATUS_FAIL,
        (f"{len(free)} 项不限价：均为临界项或触底项，且未超出 C1 隐式上界"
         if not bad else "不限价项处置错误：" + "；".join(bad)),
        actual=bad or None,
        expected="不折 0、不用大 M；p ∈ [lb, C1 隐式上界]",
    )


def _ps08(rows: Sequence[_Row], solution: Phase1Solution) -> Phase1Check:
    """层划分完备：每项恰一层、INFEASIBLE 为空、层与数值一致。"""
    tol = PRICE_RESOLUTION / 2.0
    bad: list[str] = []
    seen: set[str] = set()
    for row in rows:
        iid = row.item.item_id
        a = solution.of(iid)
        if a is None or a.p is None:
            bad.append(f"{iid}: 解中缺该变量")
            continue
        if iid in seen:
            bad.append(f"{iid}: 重复出现")
        seen.add(iid)
        if a.layer not in LAYER_VALUES:
            bad.append(f"{iid}: 层取值 {a.layer!r} 不在层域内")
            continue
        if a.layer == LAYER_INFEASIBLE:
            bad.append(f"{iid}: 落入 INFEASIBLE（出现即实现错误）")
        lo, hi, p = float(row.lower), row.upper, float(a.p)
        if p < lo - tol or (hi is not None and p > float(hi) + tol):
            bad.append(f"{iid}: p={p:g} 越界（lb={lo:g}, ub={hi}）")
        expected = _layer_for(p, lo, None if hi is None else float(hi))
        if a.layer != expected:
            bad.append(f"{iid}: 层标签 {a.layer} 与数值不符（应为 {expected}）")
    return Phase1Check(
        SCOPE, "PS-08", STATUS_PASS if not bad else STATUS_FAIL,
        (f"{len(rows)} 项各归一层，INFEASIBLE 为空，层与数值一致" if not bad
         else "层划分有问题：" + "；".join(bad[:6])),
        actual=bad or None, expected="恰一层 / INFEASIBLE 空 / 层与数值一致",
    )


def _ps09(solution: Phase1Solution) -> Phase1Check:
    """定位：candidate / 非最终解 / 声明与完整问题的关系。"""
    bad: list[str] = []
    if solution.role != ROLE_CANDIDATE:
        bad.append(f"role={solution.role!r}（应 candidate）")
    if solution.is_final:
        bad.append("is_final=True（不得自称最终解）")
    if not solution.relates_to_full_problem:
        bad.append("未声明与完整问题的关系（松弛 ⇒ 上界）")
    return Phase1Check(
        SCOPE, "PS-09", STATUS_PASS if not bad else STATUS_FAIL,
        ("自述 role=candidate、is_final=false，并声明「P_A 是松弛 ⇒ 上界」"
         if not bad else "定位自述错误：" + "；".join(bad)),
        actual=bad or None, expected="candidate / 非最终 / 声明上界关系",
    )


def _ps10(solution: Phase1Solution) -> Phase1Check:
    """目标值只允许来自独立裁判，不允许本层自报。"""
    payload = solution.to_dict()
    extra = [k for k in payload if k in ("Z", "objective", "objective_value")]
    if extra:
        return Phase1Check(
            SCOPE, "PS-10", STATUS_FAIL,
            f"解对象自报了目标值字段 {extra}——那等于重实现 R_i，"
            "与 check_solution 构成第二个事实源。目标值一律由裁判给出。",
            actual=extra, expected="解对象不含 Z",
        )
    return Phase1Check(
        SCOPE, "PS-10", STATUS_PASS,
        "解对象不含自报目标值；Z 与可行性一律由 check_solution（独立裁判）给出。",
    )


def _ps11(declared_inputs: Iterable[str] | None, *, sample: bool) -> Phase1Check:
    """声明 ↔ 实现对账：实现读的输入必须都在制品里声明过。

    ★ 「无样本」⇒ SKIP，**既不是 PASS 也不是 FAIL**（T03-02 DQ-10 首版
    把无样本判成 FAIL，即「把正常实现报成违规」的镜像翻版）。
    """
    if declared_inputs is None:
        return Phase1Check(
            SCOPE, "PS-11", STATUS_BLOCKED,
            "未给制品声明的输入集 ⇒ 无从对账（口径不可比）。",
        )
    declared = {str(x) for x in declared_inputs}
    used = {"instance", "resolved", "floor_by_id", "eps_abs", "eps_price",
            "resolution"}
    undeclared = sorted(used - declared)
    if undeclared:
        return Phase1Check(
            SCOPE, "PS-11", STATUS_FAIL,
            "实现读了制品未声明的输入：" + "、".join(undeclared)
            + "——制品漏写一条时，实现多读一项**不报错**，判据整体变严却没信号。",
            actual=undeclared, expected=sorted(declared),
        )
    if not sample:
        return Phase1Check(
            SCOPE, "PS-11", STATUS_SKIP,
            "本轮没产出解 ⇒ 输入使用集为空，无从对账。**没走到 ≠ 已违反 ≠ 已通过**。",
        )
    return Phase1Check(
        SCOPE, "PS-11", STATUS_PASS,
        "实现读取的输入集 ⊆ 制品 inputs 的声明集。",
        actual=sorted(used), expected=sorted(declared),
    )


def declared_input_names(spec: Mapping[str, Any]) -> set[str]:
    """制品 ``inputs[].field`` 的声明集（PS-11 的右侧）。"""
    out: set[str] = set()
    for entry in spec.get("inputs") or ():
        if isinstance(entry, Mapping) and entry.get("field"):
            out.add(str(entry["field"]))
    return out


# ---------------------------------------------------------------------------
# 报告（求解 + 判据）
# ---------------------------------------------------------------------------


def phase1_report(
    instance: Phase1Instance,
    resolved: ResolvedParameters,
    *,
    eps_abs: float = DEFAULT_EPS_ABS,
    eps_price: float = DEFAULT_EPS_PRICE,
    resolution: float = PRICE_RESOLUTION,
    floor_by_id: Mapping[str, float] | None = None,
    tolerances: Mapping[str, float] | None = None,
    spec: Mapping[str, Any] | None = None,
) -> Phase1Report:
    """一站式：适用守卫 → 求解 → 判据。

    ``tolerances`` 是**行声明的容差名 → 数值**的解析表（来源：
    ``verifier.resolve_tolerances``）。不给 ⇒ PS-03 判 BLOCKED（口径不可比时
    不得按严格算术冒充可行性结论）。
    """
    solution = solve_phase1(
        instance, resolved, eps_abs=eps_abs, eps_price=eps_price,
        resolution=resolution, floor_by_id=floor_by_id,
    )
    declared = declared_input_names(spec) if spec is not None else None
    checks = judge_phase1(
        instance, resolved, solution,
        eps_abs=eps_abs, eps_price=eps_price, resolution=resolution,
        floor_by_id=floor_by_id, tolerances=tolerances,
        declared_inputs=declared,
    )
    referee = None
    if solution.optimal:
        eps_total = (
            None if instance.B is None
            else max(float(eps_abs), float(eps_price) * float(instance.B))
        )
        referee = check_solution(
            instance, dict(solution.p_by_id), resolved,
            eps_total=eps_total, tolerances=tolerances,
        )
    return Phase1Report(
        solution=solution,
        checks=checks,
        exactness=check_exactness(
            instance, resolved, eps_abs=eps_abs, eps_price=eps_price
        ),
        referee=referee,
    )


# ---------------------------------------------------------------------------
# 探针实例
# ---------------------------------------------------------------------------


def phase1_probe_instance(**kwargs: Any) -> Phase1Instance:
    """内置探针：**落在适用子集内**，且覆盖不限价分支。

    复用 ``formulation.probe_instance``（四项：DECREASE / IN_RANGE / INCREASE /
    不限价），只补一样东西：``tie_break_policy = CANONICAL_ITEM_ID``。

    为什么必须补：探针的 ``P-IN`` 与 ``P-FREE`` 的 ``r_eff`` 都是 1.0，且
    ``P-FREE`` 上界无限 ⇒ 存在可容纳总价分配的重复平台 ⇒ EC-5 判 **FAIL**
    ⇒ 实例 INAPPLICABLE（**这正是 T04-00 设计的行为**）。T04-01 的探针要
    验证「给解」这一侧，故必须显式声明 canonical tie-break——这既是 EC-5
    的通过条件，也正是本层 tie-break 机制的用武之地。
    """
    base = probe_instance(**kwargs)
    return replace(
        base,
        tie_break_policy=TIE_BREAK_CANONICAL_ITEM_ID,
        source="solver/phase1.phase1_probe_instance（T04-01 内置探针）",
    )


def phase1_simple_probe_instance() -> Phase1Instance:
    """第二个探针：**无平台、上界全有限、λ 内点唯一**这一格。

    与 :func:`phase1_probe_instance` 互补——后者覆盖不限价与平台，本函数覆盖
    「所有 ub 有限 + 排序键互不相同 + 临界项严格在箱内」。两条探针合起来
    覆盖本层算法在 EC 子集中的两条主要分叉。

    参数是**构造出来**的，逐项可复算：r_eff 依 SEGMENT 口径取
    ``r``（``0.85 ≤ r ≤ 1.15`` 时不调整），故
    ``S-MID(1.1) > S-HI(1.0) > S-LO(0.8)``；``S(1) = 1.9e6``、``S(2) = 2.3e6``，
    取 ``B = 2.1e6`` ⇒ ``k* = 1``、临界项 ``S-HI`` 落在 ``p = 600 ∈ (400, 800)``。
    """
    items = (
        Phase1Item(item_id="S-MID", q0=2000.0, q1_point=2200.0, c_i=600.0,
                   p0=650.0, cap=700.0, L=400.0, U=700.0),
        Phase1Item(item_id="S-HI", q0=1000.0, q1_point=1000.0, c_i=400.0,
                   p0=500.0, cap=800.0, L=400.0, U=800.0),
        Phase1Item(item_id="S-LO", q0=500.0, q1_point=400.0, c_i=300.0,
                   p0=400.0, cap=500.0, L=200.0, U=500.0),
    )
    return Phase1Instance(
        items=items,
        B=2_100_000.0,
        P_star=2_400_000.0,
        params=Phase1Params(
            theta_dev=0.15, rho_plus=0.0, rho_minus=0.0,
            adjustment_scope="SEGMENT", theta=0.05,
        ),
        active_soft_constraints=(),
        rounding_reconciliation_present=True,
        source="solver/phase1.phase1_simple_probe_instance（T04-01 内置探针）",
    )
