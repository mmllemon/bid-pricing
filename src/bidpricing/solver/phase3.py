"""Phase 3 解验证（T04-05）。

只消费求解器输出的原始诊断量，不把缺失诊断量当作零；LP 与 MILP 的验收条件
分开，MILP 不使用 KKT 伪证最优性。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SPEC_FILENAME = "phase3_verification_spec.json"


@dataclass(frozen=True)
class Phase3Check:
    name: str
    status: str
    reason: str
    actual: Any = None
    expected: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "reason": self.reason, "actual": self.actual, "expected": self.expected}


@dataclass(frozen=True)
class Phase3Report:
    form: str
    verdict: str
    checks: tuple[Phase3Check, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"form": self.form, "verdict": self.verdict, "checks": [c.to_dict() for c in self.checks]}


def load_phase3_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def _report(form: str, checks: list[Phase3Check]) -> Phase3Report:
    statuses = [c.status for c in checks]
    if "BLOCKED" in statuses:
        verdict = "BLOCKED"
    elif "FAIL" in statuses:
        verdict = "FAIL"
    elif "WARN" in statuses:
        verdict = "WARN"
    elif statuses and all(s == "SKIP" for s in statuses):
        verdict = "SKIP"
    else:
        verdict = "PASS"
    return Phase3Report(form, verdict, tuple(checks))


def verify_phase3(facts: Mapping[str, Any], *, form: str) -> Phase3Report:
    """验证 LP 或 MILP 事实字典；不接受未知形态，也不静默降级。"""
    form = str(form).upper()
    if form not in {"LP", "MILP"}:
        return _report(form, [Phase3Check("form", "BLOCKED", f"未知求解形态 {form!r}")])

    def require(name: str) -> Any:
        value = facts.get(name)
        return value

    if form == "LP":
        required = ("primal_feasible", "dual_feasible", "stationarity_residual", "complementarity_residual", "objective_reported", "objective_recomputed")
        missing = [name for name in required if require(name) is None]
        if missing:
            return _report("LP", [Phase3Check("inputs", "BLOCKED", "缺少 LP 验证输入: " + ", ".join(missing))])
        tol = float(facts.get("tolerance", 1e-7))
        checks = [
            Phase3Check("primal_feasibility", "PASS" if facts["primal_feasible"] is True else "FAIL", "原始可行性"),
            Phase3Check("dual_feasibility", "PASS" if facts["dual_feasible"] is True else "FAIL", "对偶可行性"),
            Phase3Check("stationarity", "PASS" if abs(float(facts["stationarity_residual"])) <= tol else "FAIL", "驻点残差", facts["stationarity_residual"], tol),
            Phase3Check("complementary_slackness", "PASS" if abs(float(facts["complementarity_residual"])) <= tol else "FAIL", "互补松弛残差", facts["complementarity_residual"], tol),
            Phase3Check("objective_recomputation", "PASS" if abs(float(facts["objective_reported"]) - float(facts["objective_recomputed"])) <= tol else "FAIL", "目标值复算", abs(float(facts["objective_reported"]) - float(facts["objective_recomputed"])), tol),
        ]
        return _report("LP", checks)

    required = ("primal_feasible", "objective_reported", "objective_recomputed", "mip_gap", "mip_gap_tolerance")
    missing = [name for name in required if require(name) is None]
    if missing:
        return _report("MILP", [Phase3Check("inputs", "BLOCKED", "缺少 MILP 验证输入: " + ", ".join(missing))])
    checks = [
        Phase3Check("primal_feasibility", "PASS" if facts["primal_feasible"] is True else "FAIL", "原始可行性"),
        Phase3Check("objective_recomputation", "PASS" if abs(float(facts["objective_reported"]) - float(facts["objective_recomputed"])) <= float(facts.get("objective_tolerance", 1e-7)) else "FAIL", "目标值复算"),
        Phase3Check("mip_gap", "PASS" if float(facts["mip_gap"]) <= float(facts["mip_gap_tolerance"]) else "WARN", "MIP gap", facts["mip_gap"], facts["mip_gap_tolerance"]),
    ]
    return _report("MILP", checks)
