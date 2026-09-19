"""WP6 风险体检单（T06-02）。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SPEC_FILENAME = "risk_check_spec.json"
CHECK_IDS = ("solution_status", "phase3_verdict", "budget_residual", "cap_compliance", "cost_evidence", "loss_items", "low_price_review", "reference_parity", "rounding_reconciliation")


@dataclass(frozen=True)
class RiskCheck:
    check_id: str
    status: str
    actual: Any
    threshold: Any
    delta: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"check_id": self.check_id, "status": self.status, "actual": self.actual, "threshold": self.threshold, "delta": self.delta, "reason": self.reason}


@dataclass(frozen=True)
class RiskChecklist:
    verdict: str
    checks: tuple[RiskCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "checks": [c.to_dict() for c in self.checks]}


def load_risk_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def _one(check_id: str, raw: Mapping[str, Any] | None) -> RiskCheck:
    if raw is None or "actual" not in raw or "threshold" not in raw:
        return RiskCheck(check_id, "BLOCKED", None if raw is None else raw.get("actual"), None if raw is None else raw.get("threshold"), None, "缺少 actual 或 threshold")
    actual, threshold = raw["actual"], raw["threshold"]
    operator = str(raw.get("operator", "eq"))
    if operator == "lte":
        ok = float(actual) <= float(threshold)
        delta = float(threshold) - float(actual)
    elif operator == "gte":
        ok = float(actual) >= float(threshold)
        delta = float(actual) - float(threshold)
    elif operator == "domain":
        ok = actual in threshold
        delta = None
    elif operator == "ready":
        ok = actual is True
        delta = None
    else:
        ok = actual == threshold
        delta = actual - threshold if isinstance(actual, (int, float)) and isinstance(threshold, (int, float)) else None
    status = "PASS" if ok else str(raw.get("failure_status", "FAIL"))
    return RiskCheck(check_id, status, actual, threshold, delta, str(raw.get("reason", "机械阈值检查")))


def build_risk_checklist(inputs: Mapping[str, Mapping[str, Any]]) -> RiskChecklist:
    checks = tuple(_one(check_id, inputs.get(check_id)) for check_id in CHECK_IDS)
    statuses = [c.status for c in checks]
    verdict = "BLOCKED" if "BLOCKED" in statuses else ("FAIL" if "FAIL" in statuses else ("WARN" if "WARN" in statuses else "PASS"))
    return RiskChecklist(verdict, checks)
