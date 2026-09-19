"""数值稳定性预处理与后处理（T04-06）。"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SPEC_FILENAME = "numerical_stability_spec.json"


@dataclass(frozen=True)
class StabilityIssue:
    status: str
    code: str
    reason: str
    actual: Any = None
    expected: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "code": self.code, "reason": self.reason, "actual": self.actual, "expected": self.expected}


@dataclass(frozen=True)
class ScaledCoefficients:
    values: Mapping[str, float]
    factor: float
    issue: StabilityIssue | None = None


def load_stability_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def truncate_epsilon(values: Mapping[str, float], *, eps_abs: float) -> dict[str, float]:
    """将绝对值低于 eps_abs 的数截为 0；NaN/Inf 保留，由上层判阻断。"""
    if eps_abs < 0:
        raise ValueError("eps_abs must be non-negative")
    return {str(k): (0.0 if math.isfinite(float(v)) and abs(float(v)) < eps_abs else float(v)) for k, v in values.items()}


def relative_tolerance(value: float, *, eps_abs: float, eps_r: float) -> float:
    if eps_abs < 0 or eps_r < 0:
        raise ValueError("tolerances must be non-negative")
    return max(float(eps_abs), float(eps_r) * max(1.0, abs(float(value))))


def scale_coefficients(coefficients: Mapping[str, float], *, eps_abs: float = 0.0) -> ScaledCoefficients:
    """按最大绝对系数归一；返回因子以便后处理恢复原尺度。"""
    vals = {str(k): float(v) for k, v in coefficients.items()}
    if not vals or any(not math.isfinite(v) for v in vals.values()):
        return ScaledCoefficients({}, 1.0, StabilityIssue("BLOCKED", "INVALID_COEFFICIENT", "系数为空或含非有限值"))
    vals = truncate_epsilon(vals, eps_abs=eps_abs)
    factor = max(abs(v) for v in vals.values())
    if factor == 0.0:
        return ScaledCoefficients(vals, 1.0, StabilityIssue("BLOCKED", "ALL_ZERO", "系数全部被截为零，无法归一化"))
    return ScaledCoefficients({k: v / factor for k, v in vals.items()}, factor)


def restore_values(values: Mapping[str, float], *, factor: float) -> dict[str, float]:
    if not math.isfinite(float(factor)) or factor == 0:
        raise ValueError("factor must be finite and non-zero")
    return {str(k): float(v) * float(factor) for k, v in values.items()}


def detect_platform(values: Mapping[str, float], *, q0: Mapping[str, float] | None = None, eps_r: float = 1e-9) -> StabilityIssue:
    """识别相同有效排序键的平台；q0=0 项明确排除。"""
    groups: dict[float, list[str]] = {}
    for key, raw in values.items():
        if q0 is not None and q0.get(key) == 0:
            continue
        value = float(raw)
        if not math.isfinite(value):
            continue
        bucket = round(value / max(eps_r, 1e-15))
        groups.setdefault(bucket, []).append(str(key))
    platforms = [ids for ids in groups.values() if len(ids) > 1]
    if platforms:
        return StabilityIssue("WARN", "PLATFORM", "检测到相同或近似排序键", platforms)
    return StabilityIssue("PASS", "NO_PLATFORM", "未检测到平台效应")


def p95_latency(samples_ms: Sequence[float]) -> float | None:
    """P95 基线；空样本返回 None，禁止伪造性能结论。"""
    vals = sorted(float(v) for v in samples_ms)
    if not vals or any(not math.isfinite(v) or v < 0 for v in vals):
        return None
    rank = max(0, math.ceil(0.95 * len(vals)) - 1)
    return vals[rank]
