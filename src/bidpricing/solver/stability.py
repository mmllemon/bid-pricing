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


def same_bucket(a: float, b: float, eps: float) -> bool:
    """两个数值是否落在同一「平台」内——**直接两两比较**语义 ``|a−b| ≤ eps``。

    **为什么收拢成一个函数（2026-09-28）**：「两个 r_eff 是否近似相等」这一
    性质此前有三份手写实现——本模块 ``detect_platform`` 的 ``round(v/eps)``
    分桶、exactness._ec5 的同型分桶、phase1._lambda_info 的直接
    ``abs(diff) ≤ eps``。三份口径在边界上并不一致（分桶对 ``round`` 的
    half-to-even 与进位敏感，直接比较不受影响），一旦调整 eps 语义就得同步
    三处，漏一处就是同一性质在两层口径分叉。本函数只保证「比较式只有一份」；
    分组语义（锚点链式合并）由各消费方在它之上实现。

    NaN 按不可比较处理（返回 False）——平台检测把非有限值排除在外，这里
    不代为裁决。
    """
    a = float(a)
    b = float(b)
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    return abs(a - b) <= float(eps)


def group_by_platform(
    items: Sequence[Any],
    value_of: Any,
    *,
    eps: float,
) -> list[list[Any]]:
    """按「排序键近似相等」把 items 分组（锚点链式合并）。

    先按值升序，再从每组**第一个成员（锚点）**出发链式合并：后续元素只要
    与锚点满足 :func:`same_bucket` 就留在本组，否则开启新组。选锚点而非
    「与前一元素比较」，是为了保住组内两两近似的不变量——链式漂移会让
    ``a≈b、b≈c`` 传递出 ``a 与 c 差 3ε`` 的组，那不是「平台」而是「坡」。

    这是 ``round(v/eps)`` 分桶的替代：分桶以桶中心为锚，边界值可能被
    half-to-even 拆进相邻两桶；锚点链式合并以真实值为锚，边界行为可解释
    （第一个到达的值为锚）。对「完全相等」的测试场景两者分组一致。
    """
    ordered = sorted(items, key=value_of)
    groups: list[list[Any]] = []
    anchor: float | None = None
    for it in ordered:
        v = float(value_of(it))
        if anchor is None or not same_bucket(v, anchor, eps):
            groups.append([it])
            anchor = v
        else:
            groups[-1].append(it)
    return groups


def detect_platform(values: Mapping[str, float], *, q0: Mapping[str, float] | None = None, eps_r: float = 1e-9) -> StabilityIssue:
    """识别相同有效排序键的平台；q0=0 项明确排除。

    分组经由 :func:`group_by_platform`（比较式唯一实现在
    :func:`same_bucket`）——此前这里手写 ``round(v/eps)`` 分桶，与
    exactness/_ec5、phase1/_lambda_info 三处口径各自为政。
    """
    eligible = [
        (str(key), float(raw)) for key, raw in values.items()
        if not (q0 is not None and q0.get(key) == 0)
        and math.isfinite(float(raw))
    ]
    groups = group_by_platform(eligible, lambda kv: kv[1], eps=eps_r)
    platforms = [[key for key, _v in g] for g in groups if len(g) > 1]
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
