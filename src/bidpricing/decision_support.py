"""T06-03 机器决策支持结论页。

该模块只汇总已存在的机械判定，不产生“投/不投”建议。结论页的最后
一步永远是人工审批，低价项必须携带可解释材料包并映射 T03-07 状态。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .state_machine import LowPriceState, decide_low_price
from .states import Status, aggregate

SPEC_FILENAME = "decision_support_spec.json"
MACHINE_CONCLUSIONS = ("PROCEED_TO_HUMAN_REVIEW", "HOLD_FOR_REVIEW", "BLOCKED")
APPROVAL_FIELDS = ("approval_status", "approver", "approved_at", "decision", "comment")
MATERIAL_FIELDS = ("item", "bid_price", "estimated_individual_cost", "margin", "reason", "supporting_data", "low_price_state")


def load_decision_support_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def _status(value: Status | str) -> Status:
    return value if isinstance(value, Status) else Status(str(value).upper())


def _metric_status(raw: Mapping[str, Any] | None, *, label: str) -> tuple[Status, str]:
    """读取一个已经计算好的结构/基准检查结果，缺输入时阻断。"""
    if raw is None or "status" not in raw:
        return Status.BLOCKED, f"{label} 缺少 status"
    try:
        status = _status(raw["status"])
    except (ValueError, TypeError):
        return Status.BLOCKED, f"{label} status 不在四态域内"
    reason = str(raw.get("reason", f"{label} 机械结果"))
    return status, reason


@dataclass(frozen=True)
class LowPriceMaterial:
    item: str
    bid_price: float | None
    estimated_individual_cost: float | None
    margin: float | None
    reason: str
    supporting_data: Any
    low_price_state: str

    def to_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in MATERIAL_FIELDS}


@dataclass(frozen=True)
class HumanApproval:
    approval_status: str = "PENDING"
    approver: str | None = None
    approved_at: str | None = None
    decision: str | None = None
    comment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in APPROVAL_FIELDS}


@dataclass(frozen=True)
class DecisionSupport:
    machine_conclusion: str
    overall_status: str
    structure_rationality: dict[str, Any]
    pricing_benchmark_risk: dict[str, Any]
    low_price_materials: tuple[LowPriceMaterial, ...]
    human_approval: HumanApproval
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "machine_conclusion": self.machine_conclusion,
            "overall_status": self.overall_status,
            "structure_rationality": self.structure_rationality,
            "pricing_benchmark_risk": self.pricing_benchmark_risk,
            "low_price_materials": [item.to_dict() for item in self.low_price_materials],
            "human_approval": self.human_approval.to_dict(),
            "reasons": list(self.reasons),
        }


def _material(raw: Mapping[str, Any], default_state: LowPriceState | None) -> LowPriceMaterial:
    missing = [field for field in MATERIAL_FIELDS[:-1] if field not in raw]
    if missing:
        raise ValueError("低价材料包缺少字段: " + ", ".join(missing))
    state = raw.get("low_price_state")
    if state is None and default_state is not None:
        state = default_state.value
    if state not in {item.value for item in LowPriceState}:
        raise ValueError("low_price_state 必须映射 T03-07 三态")
    return LowPriceMaterial(
        item=str(raw["item"]),
        bid_price=None if raw["bid_price"] is None else float(raw["bid_price"]),
        estimated_individual_cost=None if raw["estimated_individual_cost"] is None else float(raw["estimated_individual_cost"]),
        margin=None if raw["margin"] is None else float(raw["margin"]),
        reason=str(raw["reason"]),
        supporting_data=raw["supporting_data"],
        low_price_state=str(state),
    )


def build_decision_support(
    *,
    structure_rationality: Mapping[str, Any] | None,
    pricing_benchmark_risk: Mapping[str, Any] | None,
    low_price_items: Sequence[Mapping[str, Any]] = (),
    feasibility_status: Status | str = Status.BLOCKED,
    cost_evidence_status: str = "UNKNOWN",
    p_star: float | None = None,
    p_star_min: float | None = None,
    human_approval: Mapping[str, Any] | None = None,
) -> DecisionSupport:
    """构建机器决策支持页；不把机器结论冒充最终人工决策。"""
    structure_status, structure_reason = _metric_status(structure_rationality, label="结构合理性")
    benchmark_status, benchmark_reason = _metric_status(pricing_benchmark_risk, label="定价基准风险")
    low_price = decide_low_price(
        feasibility_status=feasibility_status,
        cost_evidence_status=cost_evidence_status,
        p_star=p_star,
        p_star_min=p_star_min,
    )
    materials = tuple(_material(raw, low_price.state) for raw in low_price_items)
    statuses = [structure_status, benchmark_status]
    if low_price.triggered:
        statuses.append(Status.WARN)
    overall = aggregate(statuses)
    reasons = [structure_reason, benchmark_reason]
    if low_price.triggered:
        reasons.append(low_price.reason)
    if overall is Status.BLOCKED:
        conclusion = "BLOCKED"
    elif overall in (Status.FAIL, Status.WARN):
        conclusion = "HOLD_FOR_REVIEW"
    else:
        conclusion = "PROCEED_TO_HUMAN_REVIEW"
    approval_values = dict(human_approval or {})
    approval = HumanApproval(**{field: approval_values.get(field, getattr(HumanApproval(), field)) for field in APPROVAL_FIELDS})
    return DecisionSupport(conclusion, overall.value, dict(structure_rationality or {}), dict(pricing_benchmark_risk or {}), materials, approval, tuple(reasons))
