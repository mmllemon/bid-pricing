import unittest

from bidpricing.cost_scenarios import run_cost_scenarios


class CostScenarioTest(unittest.TestCase):
    def test_material_scenarios_and_delta(self):
        report = run_cost_scenarios({"a": 10, "b": 20, "other": 5}, lambda c: sum(c.values()), material_ids=["a", "b"])
        self.assertEqual(report.status, "PASS")
        self.assertEqual([s.factor for s in report.scenarios], [0.8, 1.0, 1.2])
        self.assertEqual(report.scenarios[1].delta_vs_base, 0.0)
        self.assertAlmostEqual(report.scenarios[2].objective, 41.0)

    def test_missing_material_cost_blocks(self):
        report = run_cost_scenarios({"a": 10}, lambda c: 1, material_ids=["b"])
        self.assertEqual(report.status, "BLOCKED")

    def test_negative_cost_blocks(self):
        report = run_cost_scenarios({"a": -1}, lambda c: 1, material_ids=["a"])
        self.assertEqual(report.status, "BLOCKED")

    def test_non_material_rows_remain_unchanged(self):
        seen = []
        report = run_cost_scenarios({"a": 10, "other": 5}, lambda c: seen.append(c) or sum(c.values()), material_ids=["a"], factors=(1.0, 1.2))
        self.assertEqual(report.status, "PASS")
        self.assertTrue(all(c["other"] == 5 for c in seen))


if __name__ == "__main__":
    unittest.main()
