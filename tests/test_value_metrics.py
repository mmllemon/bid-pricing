import unittest

from bidpricing.value_metrics import evaluate_value_metrics


class ValueMetricsTest(unittest.TestCase):
    def test_metrics_formula(self):
        result = evaluate_value_metrics(150, 100, 10, 20)
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.optimization_gain, 50)
        self.assertEqual(result.prediction_risk, 10)
        self.assertEqual(result.robustness_ratio, 5)

    def test_unproven_optimality_is_lower_bound(self):
        result = evaluate_value_metrics(150, 100, 10, 20, optimality_proven=False)
        self.assertEqual(result.status, "WARN")
        self.assertTrue(result.gain_is_lower_bound)

    def test_missing_is_blocked(self):
        self.assertEqual(evaluate_value_metrics(None, 100, 10, 20).status, "BLOCKED")

    def test_bad_quantile_order_fails(self):
        self.assertEqual(evaluate_value_metrics(150, 100, 20, 10).status, "FAIL")

    def test_zero_risk_ratio_is_blocked(self):
        result = evaluate_value_metrics(150, 100, 10, 10)
        self.assertEqual(result.status, "BLOCKED")
        self.assertIsNone(result.robustness_ratio)


if __name__ == "__main__":
    unittest.main()
