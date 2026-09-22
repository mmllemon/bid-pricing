"""T07-03 Q1 精度监控：MAE/WAPE/sMAPE 与可审计升级判据。"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SPEC_FILENAME = "precision_monitor_spec.json"

# bootstrap 置信区间的声明参数——与 config/precision_monitor_spec.json 的
# bootstrap_ci 段由测试双向锁定（N/seed 沿用 T05-01 约定）。
BOOTSTRAP_METHOD = "percentile_bootstrap"
BOOTSTRAP_N_RESAMPLES = 1000
BOOTSTRAP_SEED = 20260915
BOOTSTRAP_LEVEL = 0.95
BOOTSTRAP_MIN_OBSERVATIONS = 2


def load_precision_monitor_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def bootstrap_error_ci(
    errors: Sequence[float | None],
    n_resamples: int = BOOTSTRAP_N_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    level: float = BOOTSTRAP_LEVEL,
) -> Mapping[str, Any] | None:
    """逐项绝对相对误差均值的 bootstrap 百分位置信区间（spec.bootstrap_ci 的可执行形式）。

    固定 N/seed ⇒ 同一误差序列重放结果逐位一致（可复算）；
    观测不足 BOOTSTRAP_MIN_OBSERVATIONS 时返回 None——不得伪造区间。
    """
    values = [abs(float(e)) for e in errors if e is not None]
    if len(values) < BOOTSTRAP_MIN_OBSERVATIONS:
        return None
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(n_resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    tail = (1.0 - level) / 2.0
    low = means[int(tail * (n_resamples - 1))]
    high = means[int((1.0 - tail) * (n_resamples - 1))]
    return {
        "method": BOOTSTRAP_METHOD,
        "target": "逐项绝对相对误差均值",
        "n_observations": n,
        "n_resamples": n_resamples,
        "seed": seed,
        "level": level,
        "low": round(low, 6),
        "high": round(high, 6),
    }


@dataclass(frozen=True)
class PrecisionMetrics:
    sample_size: int
    mae: float
    wape: float | None
    smape: float
    low_quantity: bool

    def to_dict(self) -> dict[str, Any]:
        return {"sample_size": self.sample_size, "MAE": self.mae, "WAPE": self.wape, "sMAPE": self.smape, "low_quantity": self.low_quantity}


@dataclass(frozen=True)
class PrecisionMonitorReport:
    status: str
    promotion_status: str
    metrics: tuple[PrecisionMetrics, ...]
    sample_size: int
    confidence_interval: Mapping[str, Any] | None
    segment: str | None
    project_type: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "promotion_status": self.promotion_status, "metrics": [m.to_dict() for m in self.metrics], "sample_size": self.sample_size, "confidence_interval": self.confidence_interval, "segment": self.segment, "project_type": self.project_type, "reason": self.reason}


def _metrics(records: Sequence[Mapping[str, Any]], *, low_quantity: bool, q_min: float) -> PrecisionMetrics:
    selected = [record for record in records if (float(record["actual_q1"]) < q_min) == low_quantity]
    if not selected:
        return PrecisionMetrics(0, 0.0, None, 0.0, low_quantity)
    errors = [abs(float(r["predicted_q1"]) - float(r["actual_q1"])) for r in selected]
    actual_sum = sum(abs(float(r["actual_q1"])) for r in selected)
    smape_terms = []
    for record in selected:
        actual, predicted = float(record["actual_q1"]), float(record["predicted_q1"])
        denominator = abs(actual) + abs(predicted)
        smape_terms.append(0.0 if denominator == 0 else 2.0 * abs(predicted - actual) / denominator)
    return PrecisionMetrics(len(selected), sum(errors) / len(errors), None if actual_sum == 0 else sum(errors) / actual_sum, sum(smape_terms) / len(smape_terms), low_quantity)


def monitor_precision(
    records: Sequence[Mapping[str, Any]],
    *,
    q_min: float = 1.0,
    confidence_interval: Mapping[str, Any] | None = None,
    segment: str | None = None,
    project_type: str | None = None,
    min_sample_size: int = 30,
) -> PrecisionMonitorReport:
    required = ("predicted_q1", "actual_q1")
    missing = [field for record in records for field in required if record.get(field) is None]
    if not records or missing:
        return PrecisionMonitorReport("BLOCKED", "BLOCKED", (), 0, confidence_interval, segment, project_type, "无记录或缺少 predicted_q1/actual_q1")
    metrics = (_metrics(records, low_quantity=False, q_min=q_min), _metrics(records, low_quantity=True, q_min=q_min))
    sample_size = len(records)
    promotion_inputs_ready = sample_size >= min_sample_size and confidence_interval is not None and bool(segment) and bool(project_type)
    promotion_status = "READY" if promotion_inputs_ready else "HOLD"
    status = "PASS" if promotion_inputs_ready else "WARN"
    reason = "样本量、置信区间、segment 与 project_type 齐备" if promotion_inputs_ready else "升级/降级暂缓：必须同时满足样本量、置信区间、segment、project_type"
    return PrecisionMonitorReport(status, promotion_status, metrics, sample_size, confidence_interval, segment, project_type, reason)
