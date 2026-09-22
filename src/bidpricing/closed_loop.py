"""T07-03/T07-04 闭环编排：对照（T07-02）→ 精度监控（T07-03）→ 参数校准（T07-04）。

闭环契约的事实源是 config/closed_loop_spec.json：

- predicted_q1 须为独立来源：只能取 spec.predicted_q1_sources 里已登记的
  来源（historical_replay / model / manual），且不得与 actual_q1 的绑定源
  cost.q1_point 同源；
- 缺 predicted_q1 或其来源未登记时，精度/校准两级如实判 BLOCKED，
  不得用 q0 或 actual 顶替；
- 校准只在三门前置（replay=PASS + 实际对照=PASS + 精度升级=READY）齐备时
  生成版本化建议（审批 PENDING），永不直接覆盖当前 config。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .calibration import CalibrationRecord, PREREQUISITES, build_calibration_record
from .precision_monitor import PrecisionMonitorReport, monitor_precision
from .predicted_q1 import PredictionDeclarationError, load_declaration, verify_and_merge
from .quantity_reconciliation import QuantityReconciliationReport, compare_quantities

SPEC_FILENAME = "closed_loop_spec.json"

DEFAULT_PREDICTED_Q1_SOURCES = ("historical_replay", "model", "manual")
DEFAULT_ACTUAL_Q1_SOURCE = "cost.q1_point"
DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_Q_MIN = 1.0
STAGES = ("T07-02 reconcile", "T07-03 precision", "T07-04 calibrate")
STATUS_DOMAIN = ("READY", "BLOCKED")


class ClosedLoopError(ValueError):
    """闭环输入束（bundle）结构非法。"""


def load_closed_loop_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class ClosedLoopBundle:
    """闭环输入束：records + 闭环级证据字段（均可由 JSON 文件承载）。"""

    records: tuple[Mapping[str, Any], ...]
    replay_status: str | None
    base_config_version: str
    proposed_config_version: str | None
    proposed_changes: tuple[Mapping[str, Any], ...]
    current_config: Mapping[str, Any]
    predicted_q1_source: str | None
    predicted_q1_source_ref: str | None
    predicted_q1_declaration: str | None
    actual_q1_source: str | None
    segment: str | None
    project_type: str | None
    confidence_interval: Mapping[str, Any] | None
    min_sample_size: int | None
    q_min: float | None
    source: str | None

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any], source: str | None = None) -> "ClosedLoopBundle":
        """从 JSON 文档构造输入束；纯数组视为 {"records": [...]}。

        结构非法时抛 ClosedLoopError——静默吞掉非法输入等价于放行未声明的来源。
        """
        if isinstance(doc, list):
            doc = {"records": doc}
        records = doc.get("records")
        if records is None:
            records = []
        if not isinstance(records, list) or not all(isinstance(r, Mapping) for r in records):
            raise ClosedLoopError("records 必须是对象数组（缺省 [] 合法，非空时每项须为对象）")
        changes = doc.get("proposed_changes") or []
        if not isinstance(changes, list) or not all(isinstance(c, Mapping) for c in changes):
            raise ClosedLoopError("proposed_changes 必须是对象数组")
        current = doc.get("current_config") or {}
        if not isinstance(current, Mapping):
            raise ClosedLoopError("current_config 必须是对象")
        min_sample_size = doc.get("min_sample_size")
        if min_sample_size is not None and (not isinstance(min_sample_size, int) or min_sample_size < 1):
            raise ClosedLoopError("min_sample_size 必须是正整数")
        q_min = doc.get("q_min")
        if q_min is not None and (not isinstance(q_min, (int, float)) or isinstance(q_min, bool) or q_min < 0):
            raise ClosedLoopError("q_min 必须是非负数值")
        ci = doc.get("confidence_interval")
        if ci is not None and not isinstance(ci, Mapping):
            raise ClosedLoopError("confidence_interval 必须是对象")
        base_version = doc.get("base_config_version", "unversioned")
        if not isinstance(base_version, str):
            raise ClosedLoopError("base_config_version 必须是字符串")

        def _opt_str(key: str) -> str | None:
            value = doc.get(key)
            if value is not None and not isinstance(value, str):
                raise ClosedLoopError(f"{key} 必须是字符串")
            return value

        return cls(
            records=tuple(records),
            replay_status=_opt_str("replay_status"),
            base_config_version=base_version,
            proposed_config_version=_opt_str("proposed_config_version"),
            proposed_changes=tuple(changes),
            current_config=current,
            predicted_q1_source=_opt_str("predicted_q1_source"),
            predicted_q1_source_ref=_opt_str("predicted_q1_source_ref"),
            predicted_q1_declaration=_opt_str("predicted_q1_declaration"),
            actual_q1_source=_opt_str("actual_q1_source"),
            segment=_opt_str("segment"),
            project_type=_opt_str("project_type"),
            confidence_interval=ci,
            min_sample_size=min_sample_size,
            q_min=None if q_min is None else float(q_min),
            source=source,
        )


@dataclass(frozen=True)
class ClosedLoopStage:
    stage: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class ClosedLoopReport:
    status: str
    stages: tuple[ClosedLoopStage, ...]
    evidence: Mapping[str, str]
    predicted_q1_source: str | None
    predicted_source_note: str
    quantity_comparison: QuantityReconciliationReport
    precision: PrecisionMonitorReport | None
    calibration: CalibrationRecord
    source: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stages": [s.to_dict() for s in self.stages],
            "evidence": dict(self.evidence),
            "predicted_q1_source": self.predicted_q1_source,
            "predicted_source_note": self.predicted_source_note,
            "quantity_comparison": self.quantity_comparison.to_dict(),
            "precision": self.precision.to_dict() if self.precision is not None else None,
            "calibration": self.calibration.to_dict(),
            "source": self.source,
            "reason": self.reason,
        }


def check_predicted_source(bundle: ClosedLoopBundle, spec: Mapping[str, Any]) -> tuple[bool, str]:
    """predicted_q1 来源独立性判据（spec.independence_rule 的可执行形式）。

    返回 (ok, 判据说明)。任何一条不成立都不得静默降级——算出来的指标
    只能标注 BLOCKED，不能当作精度证据。
    """
    registered = tuple(spec.get("predicted_q1_sources", DEFAULT_PREDICTED_Q1_SOURCES))
    actual_source = bundle.actual_q1_source or str(spec.get("actual_q1_source", DEFAULT_ACTUAL_Q1_SOURCE))
    src = bundle.predicted_q1_source
    if src is None:
        return False, "predicted_q1 来源未登记：精度/校准级判 BLOCKED，不得用 q0 或 actual 顶替"
    if src == actual_source:
        return False, f"predicted_q1 来源与 actual_q1 绑定源同源 {src!r}，违反独立性规则"
    if src not in registered:
        return False, f"predicted_q1 来源 {src!r} 未登记（已登记：{list(registered)}）"
    note = f"predicted_q1 来源 {src!r} 已登记且独立于 actual 源 {actual_source!r}"
    if bundle.predicted_q1_source_ref:
        note += f"（出处：{bundle.predicted_q1_source_ref}）"
    return True, note


def resolve_precision_inputs(
    bundle: ClosedLoopBundle, spec: Mapping[str, Any]
) -> tuple[list[dict[str, Any]] | None, str]:
    """来源判据 + 声明书交叉校验（run_closed_loop 与 CLI 单级命令共用同一处实现）。

    返回 (合并后的 records, 判据说明)；None = 该级 BLOCKED，说明具名原因。
    """
    ok, note = check_predicted_source(bundle, spec)
    if not ok:
        return None, note
    merged: list[dict[str, Any]] = [dict(r) for r in bundle.records]
    if bundle.predicted_q1_declaration:
        try:
            declaration = load_declaration(bundle.predicted_q1_declaration)
        except PredictionDeclarationError as exc:
            return None, f"声明书校验失败：{exc}"
        if declaration.source != bundle.predicted_q1_source:
            return None, (
                f"声明书 source {declaration.source!r} 与 bundle 声明的 "
                f"{bundle.predicted_q1_source!r} 不一致"
            )
        merged, decl_errors = verify_and_merge(merged, declaration)
        if decl_errors:
            return None, "声明书交叉校验失败：" + "；".join(decl_errors)
        note += (
            f"；声明书 {declaration.path} 交叉校验通过"
            f"（{len(declaration.records)} 项，declared_by={declaration.declared_by}）"
        )
    return merged, note


def run_closed_loop(
    records: Sequence[Mapping[str, Any]],
    *,
    replay_status: str | None = None,
    base_config_version: str = "unversioned",
    proposed_config_version: str | None = None,
    proposed_changes: Sequence[Mapping[str, Any]] = (),
    current_config: Mapping[str, Any] | None = None,
    predicted_q1_source: str | None = None,
    predicted_q1_source_ref: str | None = None,
    predicted_q1_declaration: str | None = None,
    actual_q1_source: str | None = None,
    segment: str | None = None,
    project_type: str | None = None,
    confidence_interval: Mapping[str, Any] | None = None,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    q_min: float = DEFAULT_Q_MIN,
    spec: Mapping[str, Any] | None = None,
    source: str | None = None,
) -> ClosedLoopReport:
    """三级编排：对照 → 精度监控 → 参数校准。

    各级判据与状态域：

    - T07-02 reconcile：{PASS, BLOCKED}（全部记录有实际结算量才 PASS）
    - T07-03 precision：{PASS, WARN, BLOCKED}；升级闸门 {READY, HOLD, BLOCKED}
    - T07-04 calibrate：{PASS, BLOCKED}（PASS = 已生成版本化建议，审批 PENDING）

    整体状态取 spec.status_domain：只有 spec.closed_when 三条全部成立才 READY，
    其余一律如实 BLOCKED（缺哪条由 reason 具名，不静默放行）。

    bundle 引用声明书（predicted_q1_declaration）时，声明书是 predicted_q1 的
    唯一事实源：缺值由声明书补齐（来源已登记，不是顶替）、异值判篡改、
    未覆盖项判无登记来源——一律如实 BLOCKED。
    """
    if spec is None:
        spec = load_closed_loop_spec()
    bundle = ClosedLoopBundle(
        records=tuple(records),
        replay_status=replay_status,
        base_config_version=base_config_version,
        proposed_config_version=proposed_config_version,
        proposed_changes=tuple(proposed_changes),
        current_config=current_config or {},
        predicted_q1_source=predicted_q1_source,
        predicted_q1_source_ref=predicted_q1_source_ref,
        predicted_q1_declaration=predicted_q1_declaration,
        actual_q1_source=actual_q1_source,
        segment=segment,
        project_type=project_type,
        confidence_interval=confidence_interval,
        min_sample_size=min_sample_size,
        q_min=q_min,
        source=source,
    )

    merged_records, source_note = resolve_precision_inputs(bundle, spec)

    comparison = compare_quantities(merged_records or bundle.records)

    if merged_records is not None:
        precision = monitor_precision(
            merged_records,
            q_min=q_min,
            confidence_interval=confidence_interval,
            segment=segment,
            project_type=project_type,
            min_sample_size=min_sample_size,
        )
        promotion = precision.promotion_status
        precision_stage = ClosedLoopStage(STAGES[1], precision.status, precision.reason)
    else:
        precision = None
        promotion = "BLOCKED"
        precision_stage = ClosedLoopStage(STAGES[1], "BLOCKED", source_note)

    evidence = {
        "replay_status": replay_status or "BLOCKED",
        "quantity_comparison_status": comparison.status,
        "precision_promotion_status": promotion,
    }
    calibration = build_calibration_record(
        base_config_version=base_config_version,
        proposed_config_version=proposed_config_version,
        evidence=evidence,
        current_config=current_config or {},
        proposed_changes=proposed_changes,
    )

    stages = (
        ClosedLoopStage(STAGES[0], comparison.status, comparison.reason),
        precision_stage,
        ClosedLoopStage(STAGES[2], calibration.status, calibration.reason),
    )
    closed = (
        comparison.status == "PASS"
        and promotion == "READY"
        and calibration.status == "PASS"
    )
    if closed:
        status, reason = "READY", "闭环成立：reconcile PASS + 精度升级 READY + 校准已生成版本化建议（审批 PENDING）"
    else:
        gaps: list[str] = []
        if comparison.status != "PASS":
            gaps.append(f"reconcile {comparison.status}")
        if promotion != "READY":
            gaps.append(f"精度升级 {promotion}")
        if calibration.status != "PASS":
            gaps.append(f"calibrate {calibration.status}（{calibration.reason}）")
        status, reason = "BLOCKED", "闭环未成立：" + "；".join(gaps)

    return ClosedLoopReport(
        status=status,
        stages=stages,
        evidence=evidence,
        predicted_q1_source=predicted_q1_source,
        predicted_source_note=source_note,
        quantity_comparison=comparison,
        precision=precision,
        calibration=calibration,
        source=source,
        reason=reason,
    )


def load_closed_loop_bundle(path: Path | str) -> ClosedLoopBundle:
    """从磁盘加载闭环输入束（JSON 数组或含 records 键的对象）。"""
    p = Path(path)
    if not p.exists():
        raise ClosedLoopError(f"输入束不存在：{p}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ClosedLoopError(f"输入束不是合法 JSON：{exc}") from exc
    return ClosedLoopBundle.from_dict(doc, source=str(p))
