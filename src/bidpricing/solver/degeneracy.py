"""退化、多最优解与 canonical tie-break（T04-06B）。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SPEC_FILENAME = "degeneracy_spec.json"


@dataclass(frozen=True)
class DegeneracyReport:
    status: str
    platforms: tuple[tuple[str, ...], ...]
    dual_intervals: tuple[tuple[float, float], ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "platforms": [list(x) for x in self.platforms], "dual_intervals": [list(x) for x in self.dual_intervals], "reason": self.reason}


def load_degeneracy_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def weighted_l1(prices: Mapping[str, float], canonical: Mapping[str, float], weights: Mapping[str, float] | None = None) -> float:
    """计算 canonical tie-break 的次级目标，不把缺项当作零。"""
    weights = weights or {}
    if set(prices) != set(canonical):
        raise ValueError("prices 与 canonical 必须覆盖同一组变量")
    return sum(float(weights.get(k, 1.0)) * abs(float(prices[k]) - float(canonical[k])) for k in prices)


def canonical_allocate(
    items: Mapping[str, Mapping[str, float | None]],
    budget: float,
    *,
    order: Sequence[str] | None = None,
) -> dict[str, float]:
    """按 item_id 的确定性次序，把预算分配到平台组的可行区间。

    items 每项包含 q0、lower、upper；upper=None 表示不限价。q0=0 项不参与分配。
    这是 tie-break 的确定性见证，不替代主问题可行性检查。
    """
    active = [
        (str(k), v) for k, v in items.items()
        if v.get("q0") is not None and float(v["q0"]) > 0
    ]
    keys = list(order) if order is not None else sorted(k for k, _ in active)
    by_id = dict(active)
    if set(keys) != set(by_id):
        raise ValueError("order 必须覆盖全部有效项且不含 q0=0 项")
    result: dict[str, float] = {}
    remaining = float(budget) - sum(float(v.get("q0")) * float(v.get("lower") or 0.0) for _, v in active)
    if remaining < -1e-9:
        raise ValueError("budget 低于下界")
    for key in keys:
        row = by_id[key]
        q0 = float(row["q0"])
        lo = float(row.get("lower") or 0.0)
        upper = row.get("upper")
        capacity = float("inf") if upper is None else max(0.0, q0 * (float(upper) - lo))
        used = min(remaining, capacity)
        result[key] = lo + used / q0
        remaining -= used
    if remaining > 1e-8:
        raise ValueError("budget 超出所有上界")
    return result


def detect_degeneracy(
    r_eff: Mapping[str, float],
    lower: Mapping[str, float],
    upper: Mapping[str, float | None],
    budget: float,
    q0: Mapping[str, float] | None = None,
    *,
    eps_r: float = 1e-9,
) -> DegeneracyReport:
    groups: dict[int, list[str]] = {}
    for key, raw in r_eff.items():
        if q0 is not None and q0.get(key) == 0:
            continue
        bucket = round(float(raw) / max(eps_r, 1e-15))
        groups.setdefault(bucket, []).append(str(key))
    platforms = [tuple(sorted(ids)) for ids in groups.values() if len(ids) > 1]
    intervals: list[tuple[float, float]] = []
    for ids in platforms:
        minimum = sum(float(q0.get(k, 1.0) if q0 else 1.0) * float(lower[k]) for k in ids)
        maximum = sum(float(q0.get(k, 1.0) if q0 else 1.0) * float(upper[k]) for k in ids if upper.get(k) is not None)
        if any(upper.get(k) is None for k in ids):
            maximum = float("inf")
        if minimum <= budget <= maximum:
            value = r_eff[ids[0]]
            intervals.append((float(value), float(value)))
    if intervals:
        return DegeneracyReport("WARN", tuple(platforms), tuple(intervals), "平台组可容纳预算，存在多最优解")
    return DegeneracyReport("PASS", tuple(platforms), (), "未发现可分配平台退化")
