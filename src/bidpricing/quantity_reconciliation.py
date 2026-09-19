"""T07-02 Q0→Q1 预测与实际结算量对照。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SPEC_FILENAME = "quantity_reconciliation_spec.json"


def build_settlement_records(cost_rows: Sequence[Mapping[str, Any]], bid_rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """按项目编码把成本清单工程量与报价综合单价拼成实际结算记录。

    这是项目当前采用的实际口径：成本侧数量是 actual_q1，报价侧综合单价
    只用于计算结算金额，不会被误写成预测数量。
    """
    cost_by_id = {str(row.get("item_id")): row for row in cost_rows if row.get("item_id")}
    bid_by_id = {str(row.get("item_id")): row for row in bid_rows if row.get("item_id")}
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    for item_id in sorted(set(cost_by_id) | set(bid_by_id)):
        cost, bid = cost_by_id.get(item_id), bid_by_id.get(item_id)
        if cost is None or bid is None:
            errors.append(f"{item_id}: 成本清单或报价行缺失")
            continue
        quantity = cost.get("q1_point", cost.get("quantity"))
        unit_price = bid.get("p_bid", bid.get("p", bid.get("unit_price")))
        if quantity is None or unit_price is None:
            errors.append(f"{item_id}: 工程量或综合单价缺失")
            continue
        quantity = float(quantity)
        unit_price = float(unit_price)
        records.append({
            "item": item_id,
            "actual_q1": quantity,
            "settlement_unit_price": unit_price,
            "settlement_amount": quantity * unit_price,
            "source_refs": {"quantity": f"cost:{item_id}", "unit_price": f"bid:{item_id}"},
        })
    return records, tuple(errors)


def load_quantity_reconciliation_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class QuantityComparison:
    item: str
    q0: float | None
    predicted_q1: float | None
    actual_q1: float | None
    signed_error: float | None
    absolute_error: float | None
    relative_error: float | None
    status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"item": self.item, "q0": self.q0, "predicted_q1": self.predicted_q1, "actual_q1": self.actual_q1, "signed_error": self.signed_error, "absolute_error": self.absolute_error, "relative_error": self.relative_error, "status": self.status, "reason": self.reason}


@dataclass(frozen=True)
class QuantityReconciliationReport:
    status: str
    comparisons: tuple[QuantityComparison, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "comparisons": [item.to_dict() for item in self.comparisons], "reason": self.reason}


def compare_quantities(records: Sequence[Mapping[str, Any]]) -> QuantityReconciliationReport:
    comparisons: list[QuantityComparison] = []
    for raw in records:
        item = str(raw.get("item", "<missing>"))
        missing = [key for key in ("q0", "predicted_q1", "actual_q1") if raw.get(key) is None]
        if missing:
            comparisons.append(QuantityComparison(item, raw.get("q0"), raw.get("predicted_q1"), raw.get("actual_q1"), None, None, None, "BLOCKED", "缺少实际或预测数量: " + ", ".join(missing)))
            continue
        q0, predicted, actual = float(raw["q0"]), float(raw["predicted_q1"]), float(raw["actual_q1"])
        signed = actual - predicted
        absolute = abs(signed)
        relative = None if actual == 0 else absolute / abs(actual)
        comparisons.append(QuantityComparison(item, q0, predicted, actual, signed, absolute, relative, "PASS", "实际结算量已提供，可计算误差"))
    status = "PASS" if comparisons and all(item.status == "PASS" for item in comparisons) else "BLOCKED"
    reason = "所有项目均有实际结算量" if status == "PASS" else "存在缺少实际结算量的项目，不能形成完整对照表"
    return QuantityReconciliationReport(status, tuple(comparisons), reason)
