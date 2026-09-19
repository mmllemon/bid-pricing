import unittest
from pathlib import Path

from bidpricing.reconciliation import load_reconciliation_spec, reconcile_total


ROOT = Path(__file__).resolve().parents[1]


class ReconciliationTest(unittest.TestCase):
    def test_spec_declares_safe_steps(self):
        spec = load_reconciliation_spec(ROOT / "config")
        self.assertEqual(spec["steps"][0], "round_line_items")
        self.assertIn("revalidate_constraints", spec["steps"])

    def test_rounding_delta_is_reconciled(self):
        report = reconcile_total([
            {"item": "A", "quantity": 1, "unit_price": 0.005},
            {"item": "B", "quantity": 1, "unit_price": 0.005},
        ], declared_total=0.01)
        self.assertEqual(report.status, "PASS")
        self.assertEqual(report.rounded_total_after, report.target_total)
        self.assertEqual(report.adjustment, report.delta_before)

    def test_constraint_failure_blocks_submission(self):
        report = reconcile_total(
            [{"item": "A", "quantity": 1, "unit_price": 10}],
            declared_total=10.01,
            constraint_validator=lambda lines, total: False,
        )
        self.assertEqual(report.status, "BLOCKED")
        self.assertFalse(report.constraints_revalidated)

    def test_negative_adjustment_cannot_make_line_negative(self):
        report = reconcile_total(
            [{"item": "A", "quantity": 1, "unit_price": 0.01}],
            declared_total=-0.01,
        )
        self.assertEqual(report.status, "BLOCKED")
        self.assertIn("负合价", report.reason)


if __name__ == "__main__":
    unittest.main()
