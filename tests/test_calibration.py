import unittest
from pathlib import Path

from bidpricing.calibration import build_calibration_record, load_calibration_spec


ROOT = Path(__file__).resolve().parents[1]


class CalibrationTest(unittest.TestCase):
    def test_spec_declares_prerequisites(self):
        spec = load_calibration_spec(ROOT / "config")
        self.assertEqual(len(spec["prerequisites"]), 3)

    def test_missing_evidence_blocks_without_mutation(self):
        record = build_calibration_record(base_config_version="c1", evidence={}, current_config={"alpha": 1}, proposed_changes=[{"key": "alpha", "new_value": 2, "reason": "误差"}])
        self.assertEqual(record.status, "BLOCKED")
        self.assertFalse(record.applied)
        self.assertIsNone(record.proposed_config_version)

    def test_ready_evidence_creates_pending_proposal(self):
        record = build_calibration_record(
            base_config_version="c1",
            proposed_config_version="c2",
            evidence={"replay_status": "PASS", "quantity_comparison_status": "PASS", "precision_promotion_status": "READY"},
            current_config={"alpha": 1},
            proposed_changes=[{"key": "alpha", "new_value": 2, "reason": "置信区间内稳定偏差"}],
        )
        self.assertEqual(record.status, "PASS")
        self.assertEqual(record.approval_status, "PENDING")
        self.assertFalse(record.applied)
        self.assertEqual(record.changes[0].old_value, 1)

    def test_malformed_change_blocks(self):
        record = build_calibration_record(base_config_version="c1", evidence={"replay_status": "PASS", "quantity_comparison_status": "PASS", "precision_promotion_status": "READY"}, current_config={}, proposed_changes=[{"key": "alpha"}])
        self.assertEqual(record.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
