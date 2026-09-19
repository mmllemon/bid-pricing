"""成本 c_i 区间情景复算（T05-03）。"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

SPEC_FILENAME = "cost_interval_spec.json"


@dataclass(frozen=True)
class CostScenario:
    name: str
    factor: float
    objective: float
    delta_vs_base: float | None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "factor": self.factor, "objective": self.objective, "delta_vs_base": self.delta_vs_base}


@dataclass(frozen=True)
class CostScenarioReport:
    status: str
    scenarios: tuple[CostScenario, ...]
    material_ids: tuple[str, ...]
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "scenarios": [s.to_dict() for s in self.scenarios], "material_ids": list(self.material_ids), "reason": self.reason}


def load_cost_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def run_cost_scenarios(
    c_by_id: Mapping[str, float],
    evaluator: Callable[[Mapping[str, float]], float],
    *,
    material_ids: Sequence[str],
    factors: Sequence[float] = (0.8, 1.0, 1.2),
) -> CostScenarioReport:
    if not c_by_id or not material_ids or not factors:
        return CostScenarioReport("BLOCKED", (), tuple(material_ids), "缺少 c_i、material_ids 或 factors")
    try:
        costs = {str(k): float(v) for k, v in c_by_id.items()}
    except (TypeError, ValueError):
        return CostScenarioReport("BLOCKED", (), tuple(material_ids), "c_i 含非数值")
    if any(not math.isfinite(v) or v < 0 for v in costs.values()):
        return CostScenarioReport("BLOCKED", (), tuple(material_ids), "c_i 必须为有限非负数")
    ids = tuple(sorted(set(str(k) for k in material_ids)))
    missing = [k for k in ids if k not in costs]
    if missing:
        return CostScenarioReport("BLOCKED", (), ids, "物资项缺少 c_i: " + ", ".join(missing))
    if any(float(f) < 0 for f in factors):
        return CostScenarioReport("BLOCKED", (), ids, "情景因子不得为负")
    base_factor = 1.0
    values: list[tuple[str, float, float]] = []
    for factor in factors:
        f = float(factor)
        scenario = dict(costs)
        for item_id in ids:
            scenario[item_id] = costs[item_id] * f
        values.append((f"x{f:g}", f, float(evaluator(scenario))))
    base_candidates = [value for name, factor, value in values if abs(factor - base_factor) <= 1e-12]
    base = base_candidates[0] if base_candidates else None
    report = tuple(CostScenario(name, factor, objective, None if base is None else objective - base) for name, factor, objective in values)
    return CostScenarioReport("PASS", report, ids, "c_i 区间情景复算完成")
