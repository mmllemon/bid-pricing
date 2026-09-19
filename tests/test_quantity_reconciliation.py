import unittest
from pathlib import Path

from bidpricing.quantity_reconciliation import build_settlement_records, compare_quantities, load_quantity_reconciliation_spec


ROOT = Path(__file__).resolve().parents[1]


class QuantityReconciliationTest(unittest.TestCase):
    def test_spec_declares_actual_field(self):
        spec = load_quantity_reconciliation_spec(ROOT / "config")
        self.assertIn("actual_q1", spec["required_fields"])
        self.assertEqual(spec["actual_settlement_binding"]["actual_q1"], "cost.q1_point")

    def test_build_actual_settlement_from_cost_and_bid(self):
        records, errors = build_settlement_records(
            [{"item_id": "A", "q1_point": 2}],
            [{"item_id": "A", "p_bid": 10}],
        )
        self.assertFalse(errors)
        self.assertEqual(records[0]["actual_q1"], 2)
        self.assertEqual(records[0]["settlement_amount"], 20)
        self.assertEqual(records[0]["source_refs"]["unit_price"], "bid:A")

    def test_complete_comparison_passes(self):
        report = compare_quantities([{"item": "A", "q0": 10, "predicted_q1": 12, "actual_q1": 11}])
        self.assertEqual(report.status, "PASS")
        self.assertEqual(report.comparisons[0].signed_error, -1)
        self.assertAlmostEqual(report.comparisons[0].relative_error, 1 / 11)

    def test_missing_actual_is_blocked(self):
        report = compare_quantities([{"item": "A", "q0": 10, "predicted_q1": 12}])
        self.assertEqual(report.status, "BLOCKED")
        self.assertIsNone(report.comparisons[0].absolute_error)

    def test_zero_actual_has_undefined_relative_error(self):
        report = compare_quantities([{"item": "A", "q0": 0, "predicted_q1": 0, "actual_q1": 0}])
        self.assertEqual(report.status, "PASS")
        self.assertIsNone(report.comparisons[0].relative_error)


if __name__ == "__main__":
    unittest.main()
