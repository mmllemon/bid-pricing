"""鲁棒性三指标（T05-02）。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SPEC_FILENAME = "value_metrics_spec.json"


@dataclass(frozen=True)
class ValueMetrics:
    optimization_gain: float
    prediction_risk: float
    robustness_ratio: float | None
    status: str
    gain_is_lower_bound: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "optimization_gain": self.optimization_gain,
            "prediction_risk": self.prediction_risk,
            "robustness_ratio": self.robustness_ratio,
            "status": self.status,
            "gain_is_lower_bound": self.gain_is_lower_bound,
            "reason": self.reason,
        }


def load_value_metrics_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def evaluate_value_metrics(
    z_opt: float | None,
    z_baseline: float | None,
    q5: float | None,
    q95: float | None,
    *,
    optimality_proven: bool = True,
) -> ValueMetrics:
    values = {"z_opt": z_opt, "z_baseline": z_baseline, "q5": q5, "q95": q95}
    missing = [name for name, value in values.items() if value is None]
    if missing:
        return ValueMetrics(0.0, 0.0, None, "BLOCKED", False, "缺少输入: " + ", ".join(missing))
    gain = float(z_opt) - float(z_baseline)
    risk = float(q95) - float(q5)
    if risk < 0:
        return ValueMetrics(gain, risk, None, "FAIL", not optimality_proven, "Q95 小于 Q5，分位数顺序非法")
    if risk == 0:
        return ValueMetrics(gain, risk, None, "BLOCKED", not optimality_proven, "Prediction Risk 为零，Robustness Ratio 未定义")
    ratio = gain / risk
    if not optimality_proven:
        return ValueMetrics(gain, risk, ratio, "WARN", True, "最优性未证：Optimization Gain 仅为下界")
    return ValueMetrics(gain, risk, ratio, "PASS", False, "三指标可复算")
