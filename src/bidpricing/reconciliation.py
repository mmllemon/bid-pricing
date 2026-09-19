"""T06-06 总价重算、舍入调和与约束复验。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .money import money, money_dec, money_sum

SPEC_FILENAME = "reconciliation_spec.json"


class ReconciliationError(ValueError):
    pass


def load_reconciliation_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class ReconciliationLine:
    item: str
    quantity: float
    unit_price: float
    raw_amount: float
    rounded_amount: float

    def to_dict(self) -> dict[str, Any]:
        return {"item": self.item, "quantity": self.quantity, "unit_price": self.unit_price, "raw_amount": self.raw_amount, "rounded_amount": self.rounded_amount}


@dataclass(frozen=True)
class ReconciliationReport:
    status: str
    target_total: float | None
    raw_total: float | None
    rounded_total_before: float | None
    rounded_total_after: float | None
    delta_before: float | None
    adjustment: float
    adjusted_item: str | None
    constraints_revalidated: bool
    lines: tuple[ReconciliationLine, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "target_total": self.target_total, "raw_total": self.raw_total,
            "rounded_total_before": self.rounded_total_before, "rounded_total_after": self.rounded_total_after,
            "delta_before": self.delta_before, "adjustment": self.adjustment, "adjusted_item": self.adjusted_item,
            "constraints_revalidated": self.constraints_revalidated,
            "lines": [line.to_dict() for line in self.lines], "reason": self.reason,
        }


def _line(raw: Mapping[str, Any]) -> ReconciliationLine:
    for field in ("item", "quantity", "unit_price"):
        if field not in raw:
            raise ReconciliationError(f"报价项缺少字段: {field}")
    item = str(raw["item"])
    quantity = float(raw["quantity"])
    unit_price = float(raw["unit_price"])
    if not item or quantity < 0 or unit_price < 0:
        raise ReconciliationError(f"报价项 {item!r} 的数量/单价不得为负")
    raw_amount = quantity * unit_price
    return ReconciliationLine(item, quantity, unit_price, raw_amount, money(raw_amount))


def reconcile_total(
    items: Sequence[Mapping[str, Any]],
    *,
    declared_total: float | None = None,
    adjust_item: str | None = None,
    constraint_validator: Callable[[Sequence[Mapping[str, Any]], float], bool] | None = None,
) -> ReconciliationReport:
    """将展示行与目标总价调和；任何安全复验失败均不返回可提交状态。"""
    try:
        lines = list(map(_line, items))
    except (TypeError, ValueError, ReconciliationError) as exc:
        return ReconciliationReport("BLOCKED", None, None, None, None, None, 0.0, None, False, (), str(exc))
    if not lines:
        return ReconciliationReport("BLOCKED", None, 0.0, 0.0, None, None, 0.0, None, False, (), "报价项为空")
    raw_total = money_sum(line.raw_amount for line in lines)
    target = raw_total if declared_total is None else money(declared_total)
    rounded_before = money_sum(line.rounded_amount for line in lines)
    delta = money(target - rounded_before)
    cents = (money_dec(delta) / Decimal("0.01"))
    if cents != cents.to_integral_value():
        return ReconciliationReport("BLOCKED", target, raw_total, rounded_before, rounded_before, delta, 0.0, None, False, tuple(lines), "差额不是 0.01 元整数倍")
    candidate = adjust_item or max(lines, key=lambda line: abs(line.rounded_amount)).item
    index = next((i for i, line in enumerate(lines) if line.item == candidate), None)
    if index is None:
        return ReconciliationReport("BLOCKED", target, raw_total, rounded_before, rounded_before, delta, 0.0, None, False, tuple(lines), f"修正项不存在: {candidate}")
    adjusted_amount = money(lines[index].rounded_amount + delta)
    if adjusted_amount < 0:
        return ReconciliationReport("BLOCKED", target, raw_total, rounded_before, rounded_before, delta, 0.0, candidate, False, tuple(lines), "差额修正会产生负合价")
    adjusted = list(lines)
    old = adjusted[index]
    adjusted[index] = ReconciliationLine(old.item, old.quantity, old.unit_price, old.raw_amount, adjusted_amount)
    rounded_after = money_sum(line.rounded_amount for line in adjusted)
    validator_ok = True if constraint_validator is None else bool(constraint_validator([line.to_dict() for line in adjusted], rounded_after))
    if not validator_ok:
        return ReconciliationReport("BLOCKED", target, raw_total, rounded_before, rounded_after, delta, delta, candidate, False, tuple(adjusted), "差额修正后约束复验失败")
    status = "PASS" if rounded_after == target else "FAIL"
    return ReconciliationReport(status, target, raw_total, rounded_before, rounded_after, delta, delta, candidate, True, tuple(adjusted), "舍入调和并完成约束复验" if status == "PASS" else "调和后总价仍不一致")
