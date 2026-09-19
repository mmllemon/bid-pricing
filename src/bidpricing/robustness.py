"""q¹ 扰动实验与风险分位数报告（T05-01）。"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

SPEC_FILENAME = "q1_perturbation_spec.json"
MODES = ("INDEPENDENT", "GROUP_CONSERVING", "GLOBAL比例", "HISTORICAL_RESAMPLE")


@dataclass(frozen=True)
class ScenarioSummary:
    mode: str
    kind: str
    n: int
    seed: int
    metrics: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "kind": self.kind, "n": self.n, "seed": self.seed, "metrics": dict(self.metrics)}


def load_q1_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        raise ValueError("empty sample")
    index = min(len(ordered) - 1, max(0, math.ceil(probability * len(ordered)) - 1))
    return ordered[index]


def summarize_samples(values: Sequence[float], *, confidence: float = 0.95) -> dict[str, float]:
    if not values or not 0 < confidence < 1:
        raise ValueError("samples must be non-empty and confidence in (0,1)")
    var = _quantile(values, confidence)
    tail = [float(v) for v in values if float(v) >= var]
    return {"P5": _quantile(values, 0.05), "P50": _quantile(values, 0.5), "P95": _quantile(values, 0.95), "VaR95": var, "CVaR95": sum(tail) / len(tail)}


def _validate_q1(q1_by_id: Mapping[str, float]) -> dict[str, float]:
    if not q1_by_id:
        raise ValueError("q1_by_id 不能为空")
    try:
        out = {str(k): float(v) for k, v in q1_by_id.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError("q1 必须是有限非负数") from exc
    if any(not math.isfinite(v) or v < 0 for v in out.values()):
        raise ValueError("q1 必须是有限非负数")
    return out


def run_q1_experiment(
    q1_by_id: Mapping[str, float],
    evaluator: Callable[[Mapping[str, float]], float],
    *,
    mode: str,
    n: int = 1000,
    seed: int = 20260915,
    confidence: float = 0.95,
    relative_sigma: float = 0.1,
    groups: Mapping[str, Sequence[str]] | None = None,
    historical_errors: Sequence[float] | None = None,
) -> ScenarioSummary:
    base = _validate_q1(q1_by_id)
    if mode not in MODES or n <= 0 or relative_sigma < 0:
        raise ValueError("mode/n/relative_sigma 不合法")
    if mode == "HISTORICAL_RESAMPLE" and not historical_errors:
        raise ValueError("HISTORICAL_RESAMPLE 缺少 historical_errors")
    rng = random.Random(seed)
    results: list[float] = []
    for _ in range(n):
        if mode == "GLOBAL比例":
            factor = max(0.0, 1.0 + rng.gauss(0.0, relative_sigma))
            scenario = {k: v * factor for k, v in base.items()}
        elif mode == "HISTORICAL_RESAMPLE":
            errors = [float(x) for x in historical_errors or ()]
            if any(not math.isfinite(x) for x in errors):
                raise ValueError("historical_errors 含非有限值")
            scenario = {k: max(0.0, v * (1.0 + rng.choice(errors))) for k, v in base.items()}
        else:
            scenario = {k: max(0.0, v * (1.0 + rng.gauss(0.0, relative_sigma))) for k, v in base.items()}
            if mode == "GROUP_CONSERVING":
                if not groups:
                    raise ValueError("GROUP_CONSERVING 缺少 groups")
                for members in groups.values():
                    valid = [k for k in members if k in base]
                    target = sum(base[k] for k in valid)
                    current = sum(scenario[k] for k in valid)
                    if valid and current > 0:
                        for k in valid:
                            scenario[k] *= target / current
        results.append(float(evaluator(scenario)))
    kind = "empirical_simulation" if mode == "HISTORICAL_RESAMPLE" else "stress_test"
    return ScenarioSummary(mode, kind, n, seed, summarize_samples(results, confidence=confidence))
