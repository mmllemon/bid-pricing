"""T03-07 全局状态与低价处置状态机。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .states import Status, aggregate


class LowPriceState(str, Enum):
    LOW_PRICE_REVIEW_REQUIRED = "LOW_PRICE_REVIEW_REQUIRED"
    COST_EVIDENCE_REQUIRED = "COST_EVIDENCE_REQUIRED"
    POTENTIAL_INFEASIBILITY = "POTENTIAL_INFEASIBILITY"


@dataclass(frozen=True)
class LowPriceDecision:
    state: LowPriceState | None
    reason: str
    triggered: bool

    def to_dict(self) -> dict:
        return {"state": self.state.value if self.state else None, "reason": self.reason, "triggered": self.triggered}


def aggregate_global(statuses: Iterable[Status | str]) -> Status:
    """统一全局四态聚合，保持 BLOCKED > FAIL > WARN > PASS。"""
    normalized = [s if isinstance(s, Status) else Status(str(s)) for s in statuses]
    return aggregate(normalized)


def decide_low_price(
    *,
    feasibility_status: Status | str,
    cost_evidence_status: str,
    p_star: float | None,
    p_star_min: float | None,
) -> LowPriceDecision:
    """按已声明输入判定低价处置状态；未触发时返回 state=None。"""
    feasibility = feasibility_status if isinstance(feasibility_status, Status) else Status(str(feasibility_status))
    if feasibility in (Status.FAIL, Status.BLOCKED):
        return LowPriceDecision(LowPriceState.POTENTIAL_INFEASIBILITY, "可行性/约束状态为 FAIL 或 BLOCKED", True)
    if str(cost_evidence_status).upper() in {"BLOCKED", "MISSING", "UNKNOWN"}:
        return LowPriceDecision(LowPriceState.COST_EVIDENCE_REQUIRED, "成本证据未齐备，不能确认低价风险", True)
    if p_star is not None and p_star_min is not None and p_star < p_star_min:
        return LowPriceDecision(LowPriceState.LOW_PRICE_REVIEW_REQUIRED, "报价总价低于显式低价审查下限", True)
    return LowPriceDecision(None, "未触发低价处置条件", False)
