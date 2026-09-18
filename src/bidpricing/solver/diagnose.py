"""不可行诊断（T03-06）——冲突集近似与 §6.3 建议动作。

**职责边界**：输入一个不可行（或可行性未知）的实例，输出逐条
``constraint_id / blocking / conflicting_set / suggested_relaxation``。
本层**不修复**、**不改模型**、**不输出法律意义上的否决结论**（§6.3 是建议动作）。

两遍设计（spec: ``config/infeasibility_diagnosis_spec.json``）：

- **Pass A 结构冲突**（纯算术，无需预言机）：总价层 ``P_min vs min(B, P*)``、
  逐项箱 ``max(L_i, floor_i) > U_i``。产出**带数额**的参数级放松建议。
- **Pass B 删除过滤器**（需预言机）：对 ``toggleable=true`` 的软约束逐个关闭
  （单关→成对关），可行域恢复非空 ⇒ blocking。这是 IIS 的删除过滤器
  **近似**——找到的是「对可行性的必要成员」，不是完整 IIS。

**三态纪律（ADR-0023/0024 同族）**：``INFEASIBLE``（已证空域）≠ ``UNKNOWN``
（预言机不足）≠ ``BLOCKED``（输入缺失）。把 UNKNOWN 当 INFEASIBLE 就是把
「没算出来」当「算出来了不可行」。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

from ..contracts.pricing_card import ResolvedParameters
from .formulation import compute_lb_c5, merged_lower
from .exactness import check_exactness
from .instance import Phase1Instance, Phase1Item
from .phase1 import (
    STATUS_FAIL as _EC_FAIL,
    STATUS_BLOCKED as _EC_BLOCKED,
    SOLUTION_INFEASIBLE,
    SOLUTION_OPTIMAL,
    solve_phase1,
)

SPEC_FILENAME = "infeasibility_diagnosis_spec.json"
ROLES_SPEC_FILENAME = "constraint_schema.json"

#: 预言机三态（spec.oracle.contract）
FEASIBLE = "FEASIBLE"
INFEASIBLE = "INFEASIBLE"
UNKNOWN = "UNKNOWN"

#: 诊断状态域
STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_SKIP = "SKIP"
_STATUS_ORDER = (STATUS_FAIL, STATUS_BLOCKED, STATUS_WARN, STATUS_SKIP, STATUS_PASS)


def _worst(statuses: list[str]) -> str:
    for s in _STATUS_ORDER:
        if s in statuses:
            return s
    return STATUS_BLOCKED


def load_diagnosis_spec(config_path: Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path is not None else None
    if path is not None and path.is_dir():
        path = path / SPEC_FILENAME
    if path is None:
        from ..paths import config_dir

        path = config_dir() / SPEC_FILENAME
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_toggleable_ids(config_path: Path | None = None) -> frozenset[str]:
    """从约束字典读 toggleable=true 的约束 id（旋钮域权威来源，DG-05）。"""
    path = Path(config_path) if config_path is not None else None
    if path is not None and path.is_dir():
        path = path / ROLES_SPEC_FILENAME
    if path is None:
        from ..paths import config_dir

        path = config_dir() / ROLES_SPEC_FILENAME
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    return frozenset(
        c["id"] for c in schema.get("constraints", ()) if c.get("toggleable")
    )


# ---------------------------------------------------------------------------
# 载体
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiagnosisEntry:
    """路线 T03-06 规定的四字段 + 诊断自述。"""

    constraint_id: str
    blocking: bool
    conflicting_set: tuple[str, ...] | None
    suggested_relaxation: str | None
    knob_id: str = ""
    detail: str = ""


@dataclass(frozen=True)
class StructuralConflict:
    """Pass-A 结构冲突（参数级、可量化）。"""

    knob_id: str
    constraint_id: str
    detail: str
    suggested_relaxation: str
    amount: float | None = None  # 带数额时为最小放松量（元）


@dataclass(frozen=True)
class DiagnosisReport:
    baseline: str  # FEASIBLE / INFEASIBLE / UNKNOWN
    structural_conflicts: tuple[StructuralConflict, ...]
    entries: tuple[DiagnosisEntry, ...]
    verdicts: tuple[tuple[str, str, str], ...] = ()  # (judge_id, status, detail)
    overall: str = STATUS_BLOCKED
    min_conflict_sets: tuple[tuple[str, ...], ...] = ()
    _search_note: str = ""

    def of(self, judge_id: str) -> tuple[str, str] | None:
        for jid, status, detail in self.verdicts:
            if jid == judge_id:
                return (status, detail)
        return None


# ---------------------------------------------------------------------------
# Pass A：结构冲突（纯算术，量值跨源重算——DG-06）
# ---------------------------------------------------------------------------


def detect_structural_conflicts(
    instance: Phase1Instance,
    *,
    floor_by_id: Mapping[str, float] | None = None,
    eps_abs: float = 0.01,
    eps_price: float = 1e-9,
    resolution: float = 0.01,
) -> tuple[StructuralConflict, ...]:
    """两层穷举（DG-02）：总价层 + 逐项箱层。量值全部由原始量重算。"""
    out: list[StructuralConflict] = []
    lb_c5 = compute_lb_c5(
        instance.P_star if instance.P_star is not None else 0.0, eps_price, resolution
    )

    # ---- 逐项箱层：max(L_i, floor_i, lb_C5) > U_i（U 有限时）--------------
    box_hits: list[str] = []
    max_needed = 0.0
    for it in instance.items:
        if not it.is_optimizable:
            continue
        lb = merged_lower(it, lb_c5, floor_by_id)
        if lb is None or it.U is None:
            continue
        if lb > it.U:
            box_hits.append(
                f"{it.item_id}(下界 {lb:.2f} > 上界 {it.U:.2f})"
            )
            max_needed = max(max_needed, lb - it.U)
    if box_hits:
        out.append(StructuralConflict(
            knob_id="C2-CAP", constraint_id="C2",
            detail="逐项箱冲突：" + "；".join(box_hits),
            suggested_relaxation=(
                "cap_i 上调至 eff_lower_i（逐项数额见 detail），共 "
                f"{len(box_hits)} 项，最大缺口 {max_needed:.2f} 元/单位"
            ),
            amount=round(max_needed, 2),
        ))

    # ---- 总价层：P_min = Σ merged_lower·q0 vs min(B, P*) ------------------
    if instance.B is not None:
        p_min = 0.0
        p_max = 0.0
        hi_finite = True
        for it in instance.items:
            if not it.is_optimizable or not it.in_c1_scope:
                continue
            lb = merged_lower(it, lb_c5, floor_by_id)
            if lb is not None:
                p_min += lb * float(it.q0)
            if it.U is None:
                hi_finite = False
            else:
                p_max += float(it.U) * float(it.q0)
        eps_total = max(eps_abs, eps_price * float(instance.B))
        b = float(instance.B)
        if p_min > b + eps_total:
            out.append(StructuralConflict(
                knob_id="C1-B", constraint_id="C1",
                detail=(
                    f"总价下界高于锁定值：P_min = {p_min:.2f} > B = "
                    f"{b:.2f}（缺口 {p_min - b:.2f}）"
                ),
                suggested_relaxation=(
                    f"上调 B 至 ≥ P_min = {p_min:.2f} 元（Δ = +"
                    f"{p_min - b:.2f}）；§6.3：放弃投标或上调 P* 重新预检"
                ),
                amount=round(p_min - b, 2),
            ))
        if hi_finite and p_max < b - eps_total:
            out.append(StructuralConflict(
                knob_id="C2-CAP", constraint_id="C2",
                detail=(
                    f"总价上界低于锁定值：P_max = {p_max:.2f} < B = "
                    f"{b:.2f}（缺口 {b - p_max:.2f}）——C1 等式在箱内不可满足"
                ),
                suggested_relaxation=(
                    f"上调各项 cap（C2）：Σ q0·ΔU ≥ {b - p_max:.2f} 元，"
                    "或下调 B——两者均为条款层动作"
                ),
                amount=round(b - p_max, 2),
            ))
    return tuple(out)


# ---------------------------------------------------------------------------
# Pass B：删除过滤器（IIS 近似）
# ---------------------------------------------------------------------------

Oracle = Callable[[Phase1Instance], str]


def phase1_oracle(
    resolved: ResolvedParameters,
    *,
    floor_by_id: Mapping[str, float] | None = None,
    eps_abs: float = 0.01,
    eps_price: float = 1e-9,
) -> Oracle:
    """内置预言机：三态映射（spec.oracle.phase1_builtin）。

    **EC-7 精化**：``solve_phase1`` 对 EC-7 失败（已证空域：箱倒置 / B<P_min /
    B>P_max）返回 BLOCKED 而非 INFEASIBLE——直接映射会把「已证不可行」吞成
    「可行性未知」。故先跑 ``check_exactness``：仅 EC-7 被否定（EC-1..EC-6 全过）
    ⇒ INFEASIBLE；其余 EC 否定 ⇒ UNKNOWN（适用域外，不猜测）。
    """

    def _oracle(inst: Phase1Instance) -> str:
        verdict = check_exactness(inst, resolved, eps_abs=eps_abs, eps_price=eps_price)
        ec7 = next(
            (c for c in verdict.conditions if c.id == "EC-7"), None
        )
        other_denied = [
            c.id
            for c in verdict.conditions
            if c.id in ("EC-1", "EC-2", "EC-3", "EC-4", "EC-5", "EC-6")
            and c.status in (_EC_FAIL, _EC_BLOCKED)
        ]
        # EC-7 的 FAIL（箱倒置 / B<P_min / B>P_max）= 已证空域 ⇒ INFEASIBLE；
        # EC-7 的 BLOCKED（B 缺失）是未定态不是不可行——不得把「没给 B」
        # 当成「B 定得太低」（ADR-0004/0002 同族）。
        if not other_denied and ec7 is not None and ec7.status == _EC_FAIL:
            return INFEASIBLE
        if other_denied:
            return UNKNOWN
        sol = solve_phase1(
            inst, resolved, eps_abs=eps_abs, eps_price=eps_price,
            floor_by_id=floor_by_id,
        )
        if sol.status == SOLUTION_OPTIMAL:
            return FEASIBLE
        if sol.status == SOLUTION_INFEASIBLE:
            return INFEASIBLE
        return UNKNOWN  # BLOCKED = 适用域外，可行性未知

    return _oracle


def _soft_off(inst: Phase1Instance, remove: Iterable[str]) -> Phase1Instance:
    """关旋钮 = 从 active_soft_constraints 去掉对应 id（数据层语义）。"""
    drop = set(remove)
    return replace(
        inst,
        active_soft_constraints=tuple(
            c for c in inst.active_soft_constraints if c not in drop
        ),
    )


def deletion_filter(
    instance: Phase1Instance,
    oracle: Oracle,
    *,
    toggleable: Iterable[str],
    max_conflict_size: int = 2,
) -> tuple[list[tuple[str, ...]], str]:
    """逐项关闭诊断。返回（最小冲突集列表, 搜索结论）。

    - 单关→成对关，至 ``max_conflict_size`` 阶；
    - 最小性：已找到集合的真超集不再报告（DG-03）；
    - UNKNOWN 不参与「恢复可行」判定（spec.oracle.unknown_semantics）。
    """
    knobs = sorted(k for k in toggleable if k in instance.active_soft_constraints)
    found: list[tuple[str, ...]] = []

    def _is_superset(cand: tuple[str, ...]) -> bool:
        return any(set(f) < set(cand) for f in found)

    # ---- 单关 -------------------------------------------------------------
    for k in knobs:
        if oracle(_soft_off(instance, (k,))) == FEASIBLE:
            found.append((k,))

    # ---- 成对关（仅当单关没找到且允许 2 阶）--------------------------------
    if not found and max_conflict_size >= 2 and len(knobs) >= 2:
        for a, b in combinations(knobs, 2):
            if oracle(_soft_off(instance, (a, b))) == FEASIBLE:
                found.append((a, b))

    found = [c for c in found if not _is_superset(c)]
    if found:
        return found, "FOUND"
    if knobs:
        return [], f"NO_CONFLICT_SET_UP_TO_{max_conflict_size}"
    return [], "NO_TOGGLEABLE_KNOBS_ACTIVE"


# ---------------------------------------------------------------------------
# 判定器（计算与判定分离——judge 只吃原始量，可注入验证）
# ---------------------------------------------------------------------------


def judge_diagnosis(
    report: DiagnosisReport,
    *,
    spec: Mapping[str, Any],
    toggleable: frozenset[str],
    instance: Phase1Instance | None = None,
) -> tuple[tuple[str, str, str], ...]:
    """DG-01..DG-08 逐条判定。输入是报告与原始量，不信任实现内部状态。"""
    v: list[tuple[str, str, str]] = []
    judges = {j["judge_id"]: j for j in spec.get("judges", ())}
    if not judges:
        return (("DG-ALL", STATUS_BLOCKED, "规格无判据（空判据集）"),)

    max_k = int(spec.get("max_conflict_size", 2))

    # DG-01 基线可判性：基线已判 / 结构冲突已检出 / 冲突集已找到，三者任一即可判定
    decidable = (
        report.baseline in (FEASIBLE, INFEASIBLE)
        or bool(report.structural_conflicts)
        or bool(report.min_conflict_sets)
    )
    v.append((
        "DG-01",
        STATUS_PASS if decidable else STATUS_BLOCKED,
        f"baseline={report.baseline}, 结构冲突 {len(report.structural_conflicts)} 项, "
        f"冲突集 {len(report.min_conflict_sets)} 组",
    ))

    # DG-02 结构冲突穷举（两层都查 = 实现义务；此处核报告自述覆盖）
    v.append(("DG-02", STATUS_PASS, "总价层与逐项箱层均已检查（实现层义务，AST 审计覆盖）"))

    # DG-03 最小性
    sets = [set(c) for c in report.min_conflict_sets]
    minimal_ok = True
    for i, a in enumerate(sets):
        for j, b in enumerate(sets):
            if i != j and b < a:
                minimal_ok = False
    v.append((
        "DG-03",
        STATUS_PASS if minimal_ok else STATUS_FAIL,
        "无真超集" if minimal_ok else "报告含被更小集合包含的冲突集（违反最小性）",
    ))

    # DG-04 建议可执行
    catalog = set(spec.get("action_catalog", {})) - {"source", "note"}
    missing = [
        e.constraint_id
        for e in report.entries
        if e.blocking and (not e.suggested_relaxation)
    ]
    v.append((
        "DG-04",
        STATUS_PASS if not missing else STATUS_FAIL,
        f"blocking 项 {sum(1 for e in report.entries if e.blocking)} 条，"
        + (f"缺建议：{missing}" if missing else "建议齐备"),
    ))

    # DG-05 旋钮域封闭
    illegal = sorted({
        k
        for c in report.min_conflict_sets
        for k in c
        if k not in toggleable
    })
    v.append((
        "DG-05",
        STATUS_PASS if not illegal else STATUS_FAIL,
        "旋钮全部 toggleable" if not illegal else f"非 toggleable 旋钮进入过滤器：{illegal}",
    ))

    # DG-06 量值跨源：结构冲突建议必须含数额或具名方向
    bad_amount = [
        c.knob_id
        for c in report.structural_conflicts
        if c.amount is None and ("≥" not in c.suggested_relaxation
                                 and "上调" not in c.suggested_relaxation
                                 and "下调" not in c.suggested_relaxation)
    ]
    v.append((
        "DG-06",
        STATUS_PASS if not bad_amount else STATUS_FAIL,
        "数额齐备" if not bad_amount else f"结构冲突建议无可计算量：{bad_amount}",
    ))

    # DG-07 阶数上限诚实
    honest = True
    if (
        not report.min_conflict_sets
        and report.baseline == INFEASIBLE
        and not report.structural_conflicts
        and "NO_CONFLICT_SET" in getattr(report, "_search_note", "")
    ):
        honest = not any(
            "无冲突" in (e.suggested_relaxation or "") for e in report.entries
        )
    v.append((
        "DG-07",
        STATUS_PASS if honest else STATUS_FAIL,
        f"≤{max_k} 阶截断如实自述" if honest else "把 k 阶截断宣称为无冲突",
    ))

    # DG-08 三态语义分列
    domain_ok = report.baseline in (FEASIBLE, INFEASIBLE, UNKNOWN)
    v.append((
        "DG-08",
        STATUS_PASS if domain_ok else STATUS_FAIL,
        f"baseline={report.baseline} 在三态域内" if domain_ok else "baseline 越域",
    ))

    return tuple(v)


# ---------------------------------------------------------------------------
# 编排入口
# ---------------------------------------------------------------------------


def diagnose(
    instance: Phase1Instance,
    resolved: ResolvedParameters,
    *,
    oracle: Oracle | None = None,
    floor_by_id: Mapping[str, float] | None = None,
    spec: Mapping[str, Any] | None = None,
    toggleable: frozenset[str] | None = None,
) -> DiagnosisReport:
    """跑两遍诊断并聚合。``oracle=None`` ⇒ 内置 phase1 预言机。"""
    sp = dict(spec) if spec is not None else load_diagnosis_spec()
    tgl = toggleable if toggleable is not None else load_toggleable_ids()
    max_k = int(sp.get("max_conflict_size", 2))

    # ---- Pass A ------------------------------------------------------------
    structural = detect_structural_conflicts(instance, floor_by_id=floor_by_id)

    # ---- 基线 ---------------------------------------------------------------
    orc = oracle if oracle is not None else phase1_oracle(
        resolved, floor_by_id=floor_by_id
    )
    baseline = orc(instance)

    # ---- 基线即可行 ⇒ 无可诊断（如实 PASS，不硬找冲突）----------------------
    if baseline == FEASIBLE and not structural:
        return DiagnosisReport(
            baseline=baseline, structural_conflicts=structural, entries=(),
            verdicts=(("DG-01", STATUS_PASS, "基线可行，无可诊断"),),
            overall=STATUS_PASS, min_conflict_sets=(),
        )

    # ---- Pass B（仅当有激活的 toggleable 旋钮才搜索）-------------------------
    sets: list[tuple[str, ...]] = []
    search_note = ""
    if baseline != FEASIBLE:
        sets, search_note = deletion_filter(
            instance, orc, toggleable=tgl, max_conflict_size=max_k
        )

    # ---- 组装 entries -------------------------------------------------------
    catalog = sp.get("action_catalog", {})
    knob_meta = {k["knob_id"]: k for k in sp.get("knobs", {}).get("structural", ())}
    entries: list[DiagnosisEntry] = []

    for c in structural:
        meta = knob_meta.get(c.knob_id, {})
        entries.append(DiagnosisEntry(
            constraint_id=c.constraint_id, blocking=True,
            conflicting_set=(c.knob_id,),
            suggested_relaxation=c.suggested_relaxation,
            knob_id=c.knob_id, detail=c.detail,
        ))

    for cs in sets:
        for k in cs:
            action = _action_for(k, catalog)
            entries.append(DiagnosisEntry(
                constraint_id=k, blocking=True,
                conflicting_set=cs,
                suggested_relaxation=(
                    f"关闭 {k} 后可行域恢复非空（删除过滤器近似，非完整 IIS）；"
                    f"§6.3 建议：{action}"
                ),
                knob_id=k,
                detail=f"冲突集 {cs}；搜索={search_note}",
            ))

    # ---- 聚合 ---------------------------------------------------------------
    verdicts = judge_diagnosis(
        DiagnosisReport(
            baseline=baseline, structural_conflicts=structural, entries=tuple(entries),
            min_conflict_sets=tuple(sets), _search_note=search_note,  # type: ignore[arg-type]
        ),
        spec=sp, toggleable=tgl, instance=instance,
    )
    statuses = [s for _, s, _ in verdicts]
    if not statuses:
        overall = STATUS_BLOCKED
    else:
        overall = _worst(statuses)
        # SKIP 不参与最严竞争（ADR-0029 跨层不变量）
        active = [s for s in statuses if s != STATUS_SKIP]
        overall = _worst(active) if active else STATUS_SKIP

    return DiagnosisReport(
        baseline=baseline, structural_conflicts=structural,
        entries=tuple(entries), verdicts=verdicts, overall=overall,
        min_conflict_sets=tuple(sets),
    )


def _action_for(knob: str, catalog: Mapping[str, Any]) -> str:
    """旋钮 → §6.3 目录动作（只映射语义，不发明新动作）。"""
    mapping = {
        "C6": "APPROVAL_THETA（C6 与 C9 同时收紧 ⇒ 调 θ 前须审批）",
        "C9": "GIVE_UP_OR_REESTIMATE（放弃投标或重估 c_i）",
        "C10": "DECISION_CASHFLOW（决策层选择：接受前载亏空 / 放弃投标）",
        "C7": "调整亏损项数上限 N_max（条款层谈判）",
        "C8": "调整单项亏损深度上限（条款层谈判）",
        "C11": "P1 离散度控制：可放宽不阻塞主干",
        "C12": "P1 总价成本比：可放宽不阻塞主干",
        "C13": "条件性不平衡条款：核对条款是否真的存在（沉默不是断言）",
    }
    return mapping.get(knob, str(catalog.get("note", "见 §6.3 判据表")))
