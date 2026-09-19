"""k⁺/k⁻ 合同调整情景（T05-04）。"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

SPEC_FILENAME = "k_scenario_spec.json"


@dataclass(frozen=True)
class KScenario:
    name: str
    k_plus: float
    k_minus: float
    objective: float
    ranking: tuple[str, ...]
    ranking_change_vs_base: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "k_plus": self.k_plus, "k_minus": self.k_minus, "objective": self.objective, "ranking": list(self.ranking), "ranking_change_vs_base": self.ranking_change_vs_base}


@dataclass(frozen=True)
class KScenarioReport:
    status: str
    scenarios: tuple[KScenario, ...]
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "scenarios": [s.to_dict() for s in self.scenarios], "reason": self.reason}


def load_k_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def run_k_scenarios(
    rho_plus: float,
    rho_minus: float,
    evaluator: Callable[[Mapping[str, float]], tuple[float, Sequence[str]]],
    *,
    pairs: Sequence[tuple[float, float]] = ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0)),
) -> KScenarioReport:
    try:
        rp, rm = float(rho_plus), float(rho_minus)
    except (TypeError, ValueError):
        return KScenarioReport("BLOCKED", (), "rho_plus/rho_minus 非数值")
    if any(not math.isfinite(x) or x < 0 for x in (rp, rm)):
        return KScenarioReport("BLOCKED", (), "rho_plus/rho_minus 必须为有限非负数")
    if not pairs:
        return KScenarioReport("BLOCKED", (), "情景 pairs 为空")
    results: list[tuple[float, float, float, tuple[str, ...]]] = []
    for kp, km in pairs:
        kp, km = float(kp), float(km)
        if not math.isfinite(kp) or not math.isfinite(km) or kp < 0 or km < 0:
            return KScenarioReport("BLOCKED", (), "k_plus/k_minus 必须为有限非负数")
        objective, ranking = evaluator({"rho_plus": rp * kp, "rho_minus": rm * km, "k_plus": kp, "k_minus": km})
        results.append((kp, km, float(objective), tuple(str(x) for x in ranking)))
    base = next((ranking for kp, km, _obj, ranking in results if kp == 0.0 and km == 0.0), None)
    scenarios = tuple(KScenario(f"k+={kp:g},k-={km:g}", kp, km, obj, ranking, None if base is None else ranking != base) for kp, km, obj, ranking in results)
    return KScenarioReport("PASS", scenarios, "k⁺/k⁻ 三档情景复算完成")
