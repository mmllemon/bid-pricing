import json
import unittest
from pathlib import Path

from bidpricing.decision_support import build_decision_support, load_decision_support_spec
from bidpricing.state_machine import LowPriceState
from bidpricing.states import Status


ROOT = Path(__file__).resolve().parents[1]


class DecisionSupportTest(unittest.TestCase):
    def test_spec_and_required_sections(self):
        spec = load_decision_support_spec(ROOT / "config")
        self.assertEqual(spec["task"], "T06-03")
        self.assertEqual(len(spec["low_price_material_fields"]), 7)

    def test_machine_support_never_decides_bid_or_no_bid(self):
        result = build_decision_support(
            structure_rationality={"status": "PASS", "actual": 1, "threshold": 1},
            pricing_benchmark_risk={"status": "PASS", "actual": 0.1, "threshold": 0.2},
            feasibility_status=Status.PASS,
            cost_evidence_status="PASS",
        )
        self.assertEqual(result.machine_conclusion, "PROCEED_TO_HUMAN_REVIEW")
        self.assertEqual(result.human_approval.approval_status, "PENDING")
        self.assertNotIn(result.machine_conclusion, {"投", "不投"})

    def test_low_price_material_maps_three_state(self):
        result = build_decision_support(
            structure_rationality={"status": "PASS"},
            pricing_benchmark_risk={"status": "WARN", "reason": "基准版本未签署"},
            feasibility_status=Status.PASS,
            cost_evidence_status="PASS",
            p_star=80,
            p_star_min=100,
            low_price_items=[{
                "item": "A-01", "bid_price": 80, "estimated_individual_cost": 75,
                "margin": 5, "reason": "低于审查下限", "supporting_data": {"source": "cost-ledger"}
            }],
        )
        self.assertEqual(result.low_price_materials[0].low_price_state, LowPriceState.LOW_PRICE_REVIEW_REQUIRED.value)
        self.assertEqual(result.machine_conclusion, "HOLD_FOR_REVIEW")

    def test_missing_structure_blocks_and_bad_material_rejected(self):
        result = build_decision_support(structure_rationality=None, pricing_benchmark_risk={"status": "PASS"})
        self.assertEqual(result.machine_conclusion, "BLOCKED")
        with self.assertRaises(ValueError):
            build_decision_support(structure_rationality={"status": "PASS"}, pricing_benchmark_risk={"status": "PASS"}, low_price_items=[{"item": "A"}])


if __name__ == "__main__":
    unittest.main()
