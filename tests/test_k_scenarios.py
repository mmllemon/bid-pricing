import unittest

from bidpricing.k_scenarios import run_k_scenarios


class KScenarioTest(unittest.TestCase):
    def test_three_levels_and_ranking_change(self):
        def evaluator(params):
            k = params["k_plus"]
            ranking = ("a", "b") if k < 1 else ("b", "a")
            return 100 + k, ranking
        report = run_k_scenarios(0.2, 0.1, evaluator)
        self.assertEqual(report.status, "PASS")
        self.assertEqual(len(report.scenarios), 3)
        self.assertTrue(report.scenarios[-1].ranking_change_vs_base)

    def test_invalid_rho_blocks(self):
        self.assertEqual(run_k_scenarios(-1, 0, lambda p: (1, ())).status, "BLOCKED")

    def test_invalid_k_blocks(self):
        self.assertEqual(run_k_scenarios(0, 0, lambda p: (1, ()), pairs=[(-0.1, 0)]).status, "BLOCKED")

    def test_empty_pairs_blocks(self):
        self.assertEqual(run_k_scenarios(0, 0, lambda p: (1, ()), pairs=[]).status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
