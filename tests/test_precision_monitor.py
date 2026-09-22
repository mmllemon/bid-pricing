import unittest
from pathlib import Path

from bidpricing.precision_monitor import (
    BOOTSTRAP_LEVEL,
    BOOTSTRAP_METHOD,
    BOOTSTRAP_N_RESAMPLES,
    BOOTSTRAP_SEED,
    bootstrap_error_ci,
    load_precision_monitor_spec,
    monitor_precision,
)


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


class BootstrapCiTest(unittest.TestCase):
    def test_constants_track_spec(self):
        spec = load_precision_monitor_spec(ROOT / "config")
        bs = spec["bootstrap_ci"]
        self.assertEqual(BOOTSTRAP_METHOD, bs["method"])
        self.assertEqual(BOOTSTRAP_N_RESAMPLES, bs["n_resamples"])
        self.assertEqual(BOOTSTRAP_SEED, bs["seed"])
        self.assertEqual(BOOTSTRAP_LEVEL, bs["level"])
        self.assertEqual(len(spec["promotion_input_sources"]), 4)

    def test_deterministic_and_bounded(self):
        errors = [0.1, 0.2, 0.3, None, 0.15]
        ci1 = bootstrap_error_ci(errors)
        ci2 = bootstrap_error_ci(errors)
        self.assertEqual(ci1, ci2)
        self.assertEqual(ci1["method"], "percentile_bootstrap")
        self.assertEqual(ci1["n_observations"], 4)
        self.assertGreaterEqual(ci1["low"], 0.0)
        self.assertLessEqual(ci1["low"], ci1["high"])
        self.assertLessEqual(ci1["high"], 0.3)

    def test_fewer_than_two_observations_returns_none(self):
        self.assertIsNone(bootstrap_error_ci([]))
        self.assertIsNone(bootstrap_error_ci([0.5]))
        self.assertIsNone(bootstrap_error_ci([None, None]))


if __name__ == "__main__":
    unittest.main()
