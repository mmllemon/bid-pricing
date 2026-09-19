"""T07-04 参数校准记录：证据不足时只阻断，不静默改配置。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SPEC_FILENAME = "calibration_spec.json"
PREREQUISITES = ("replay_status", "quantity_comparison_status", "precision_promotion_status")


def load_calibration_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class CalibrationChange:
    key: str
    old_value: Any
    new_value: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "old_value": self.old_value, "new_value": self.new_value, "reason": self.reason}


@dataclass(frozen=True)
class CalibrationRecord:
    status: str
    approval_status: str
    base_config_version: str
    proposed_config_version: str | None
    prerequisites: Mapping[str, str]
    changes: tuple[CalibrationChange, ...]
    applied: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "approval_status": self.approval_status, "base_config_version": self.base_config_version, "proposed_config_version": self.proposed_config_version, "prerequisites": dict(self.prerequisites), "changes": [c.to_dict() for c in self.changes], "applied": self.applied, "reason": self.reason}


def build_calibration_record(
    *,
    base_config_version: str,
    evidence: Mapping[str, str],
    current_config: Mapping[str, Any],
    proposed_changes: Sequence[Mapping[str, Any]],
    proposed_config_version: str | None = None,
) -> CalibrationRecord:
    prereqs = {key: str(evidence.get(key, "BLOCKED")) for key in PREREQUISITES}
    missing = [key for key in PREREQUISITES if key not in evidence]
    ready = not missing and prereqs["replay_status"] == "PASS" and prereqs["quantity_comparison_status"] == "PASS" and prereqs["precision_promotion_status"] == "READY"
    changes: list[CalibrationChange] = []
    errors: list[str] = []
    for raw in proposed_changes:
        if not all(field in raw for field in ("key", "new_value", "reason")):
            errors.append("校准建议缺少 key/new_value/reason")
            continue
        key = str(raw["key"])
        changes.append(CalibrationChange(key, current_config.get(key), raw["new_value"], str(raw["reason"])))
    if not ready:
        reason = "校准前置证据未齐备: " + ", ".join(missing or [key for key, value in prereqs.items() if value not in {"PASS", "READY"}])
        return CalibrationRecord("BLOCKED", "PENDING", str(base_config_version), None, prereqs, tuple(changes), False, reason)
    if errors:
        return CalibrationRecord("BLOCKED", "PENDING", str(base_config_version), None, prereqs, tuple(changes), False, "; ".join(errors))
    if not changes:
        return CalibrationRecord("BLOCKED", "PENDING", str(base_config_version), None, prereqs, (), False, "没有可审计的参数变更建议")
    return CalibrationRecord("PASS", "PENDING", str(base_config_version), proposed_config_version, prereqs, tuple(changes), False, "已生成校准建议，等待人工审批和新版本冻结")
