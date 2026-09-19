import unittest

from bidpricing.robustness import run_q1_experiment, summarize_samples


class RobustnessTest(unittest.TestCase):
    def test_metrics_are_reported(self):
        self.assertEqual(set(summarize_samples([1, 2, 3, 4])), {"P5", "P50", "P95", "VaR95", "CVaR95"})

    def test_independent_is_reproducible(self):
        fn = lambda q: sum(q.values())
        a = run_q1_experiment({"a": 10, "b": 20}, fn, mode="INDEPENDENT", n=20, seed=7)
        b = run_q1_experiment({"a": 10, "b": 20}, fn, mode="INDEPENDENT", n=20, seed=7)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_group_conserving_preserves_sum(self):
        seen = []
        def fn(q):
            seen.append(sum(q.values()))
            return sum(q.values())
        run_q1_experiment({"a": 10, "b": 20}, fn, mode="GROUP_CONSERVING", groups={"g": ["a", "b"]}, n=5)
        self.assertTrue(all(abs(value - 30) < 1e-8 for value in seen))

    def test_historical_requires_errors(self):
        with self.assertRaises(ValueError):
            run_q1_experiment({"a": 10}, lambda q: q["a"], mode="HISTORICAL_RESAMPLE", n=2)

    def test_historical_is_empirical(self):
        result = run_q1_experiment({"a": 10}, lambda q: q["a"], mode="HISTORICAL_RESAMPLE", historical_errors=[-0.1, 0.1], n=10)
        self.assertEqual(result.kind, "empirical_simulation")
        self.assertEqual(result.n, 10)

    def test_invalid_q1_is_rejected(self):
        with self.assertRaises(ValueError):
            run_q1_experiment({"a": None}, lambda q: 1, mode="INDEPENDENT", n=1)
