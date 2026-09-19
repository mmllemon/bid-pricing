import unittest
from pathlib import Path

from bidpricing.precision_monitor import load_precision_monitor_spec, monitor_precision


ROOT = Path(__file__).resolve().parents[1]


class PrecisionMonitorTest(unittest.TestCase):
    def test_spec_declares_metrics_and_promotion_inputs(self):
        spec = load_precision_monitor_spec(ROOT / "config")
        self.assertEqual(spec["metrics"], ["MAE", "WAPE", "sMAPE"])
        self.assertEqual(len(spec["promotion_inputs"]), 4)

    def test_metrics_and_low_quantity_split(self):
        report = monitor_precision([
            {"predicted_q1": 12, "actual_q1": 10},
            {"predicted_q1": 0.5, "actual_q1": 0.25},
        ], q_min=1, min_sample_size=1, confidence_interval={"low": 0, "high": 1}, segment="x", project_type="y")
        self.assertEqual(report.status, "PASS")
        self.assertEqual(report.metrics[0].sample_size, 1)
        self.assertEqual(report.metrics[1].sample_size, 1)
        self.assertAlmostEqual(report.metrics[0].mae, 2)

    def test_missing_promotion_inputs_warns_not_promotes(self):
        report = monitor_precision([{"predicted_q1": 2, "actual_q1": 1}], min_sample_size=1)
        self.assertEqual(report.status, "WARN")
        self.assertEqual(report.promotion_status, "HOLD")

    def test_missing_actual_blocks(self):
        report = monitor_precision([{"predicted_q1": 2}], min_sample_size=1)
        self.assertEqual(report.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
