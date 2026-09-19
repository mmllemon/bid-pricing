"""Phase 1/2 对拍器（T04-04）。

本模块只比较两条路径已经产出的结果，不替任一路径求解；独立性签署未通过时
结论强制 BLOCKED，避免把同一作者的双重实现包装成“对拍通过”。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

SPEC_FILENAME = "phase12_parity_spec.json"
SIGNOFF_FILENAME = "reference_review_signoff.json"


@dataclass(frozen=True)
class ParityResult:
    status: str
    level: str | None
    reason: str
    objective_delta: float | None = None
    max_price_delta: float | None = None
    mismatches: tuple[str, ...] = ()
    independence: str = "UNKNOWN"
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.status == "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "level": self.level,
            "reason": self.reason,
            "objective_delta": self.objective_delta,
            "max_price_delta": self.max_price_delta,
            "mismatches": list(self.mismatches),
            "independence": self.independence,
            "details": dict(self.details),
        }


def load_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def independence_status(
    signoff_path: Path | str = "docs/reference_review_signoff.json",
) -> str:
    path = Path(signoff_path)
    if not path.exists():
        return "BLOCKED"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "BLOCKED"
    return "PASS" if data.get("signed") is True and data.get("reviewer") else "BLOCKED"


def compare_phase12(
    phase1: Mapping[str, Any] | None,
    phase2: Mapping[str, Any] | None,
    *,
    applicable: bool = True,
    group: str = "A",
    signoff_path: Path | str = "docs/reference_review_signoff.json",
    objective_abs: float = 1e-7,
    price_abs: float = 1e-7,
) -> ParityResult:
    """比较 Phase 1/2 的结果字典。

    结果可用 ``objective``/``Z`` 表示目标值、``prices``/``p_by_id`` 表示报价向量，
    ``layers`` 可选用于 L3；缺失值不静默当作 0。
    """
    independence = independence_status(signoff_path)
    if independence != "PASS":
        return ParityResult("BLOCKED", None, "T04-08 独立性签署状态非 PASS", independence=independence)
    if not applicable:
        return ParityResult("BLOCKED", None, "实例不在 T04-00 适用子集", independence=independence)
    if group not in {"A", "B"}:
        return ParityResult("BLOCKED", None, f"未知对拍组 {group!r}", independence=independence)
    if not phase1 or not phase2:
        return ParityResult("BLOCKED", None, "任一路径缺少可比较结果", independence=independence)

    def value(data: Mapping[str, Any], *names: str) -> Any:
        for name in names:
            if name in data:
                return data[name]
        return None

    z1, z2 = value(phase1, "objective", "Z", "Z_competitive"), value(phase2, "objective", "Z", "Z_competitive")
    if z1 is None or z2 is None:
        return ParityResult("BLOCKED", None, "目标值缺失，无法进行 L2 对拍", independence=independence)
    objective_delta = abs(float(z1) - float(z2))
    mismatches: list[str] = []
    if objective_delta > objective_abs:
        mismatches.append(f"objective delta {objective_delta} > {objective_abs}")

    p1, p2 = value(phase1, "prices", "p_by_id"), value(phase2, "prices", "p_by_id")
    if not isinstance(p1, Mapping) or not isinstance(p2, Mapping):
        return ParityResult("BLOCKED", None, "报价向量缺失，无法进行 L2 对拍", objective_delta, None, tuple(mismatches), independence)
    ids = sorted(set(p1) | set(p2))
    deltas = [abs(float(p1[k]) - float(p2[k])) for k in ids if k in p1 and k in p2]
    missing = [k for k in ids if k not in p1 or k not in p2]
    max_delta = max(deltas, default=0.0)
    if missing:
        mismatches.append("price ids missing: " + ",".join(missing))
    if max_delta > price_abs:
        mismatches.append(f"price delta {max_delta} > {price_abs}")

    if mismatches:
        return ParityResult("FAIL", "L2", "Phase 1/2 数值不一致", objective_delta, max_delta, tuple(mismatches), independence)

    l1, l2 = value(phase1, "layers"), value(phase2, "layers")
    if l1 is not None or l2 is not None:
        if l1 != l2:
            return ParityResult("WARN", "L3", "报价一致但层归属不一致", objective_delta, max_delta, ("layers mismatch",), independence)
        return ParityResult("PASS", "L3", "三层对拍一致", objective_delta, max_delta, independence=independence)
    return ParityResult("PASS", "L2", "目标值与报价向量一致", objective_delta, max_delta, independence=independence)
