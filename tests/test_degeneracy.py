import unittest

from bidpricing.solver.degeneracy import canonical_allocate, detect_degeneracy, weighted_l1


class DegeneracyTest(unittest.TestCase):
    def test_platform_warns_and_reports_interval(self):
        rep = detect_degeneracy({"a": 1.0, "b": 1.0}, {"a": 1, "b": 1}, {"a": 3, "b": 3}, 4.0, {"a": 1, "b": 1})
        self.assertEqual(rep.status, "WARN")
        self.assertEqual(rep.platforms, (("a", "b"),))
        self.assertEqual(rep.dual_intervals, ((1.0, 1.0),))

    def test_zero_quantity_is_excluded(self):
        rep = detect_degeneracy({"a": 1.0, "z": 1.0}, {"a": 1, "z": 1}, {"a": 3, "z": 3}, 2.0, {"a": 1, "z": 0})
        self.assertEqual(rep.status, "PASS")

    def test_canonical_allocate_is_deterministic(self):
        prices = canonical_allocate({"b": {"q0": 1, "lower": 1, "upper": 3}, "a": {"q0": 1, "lower": 1, "upper": 3}}, 4)
        self.assertEqual(prices, {"a": 3.0, "b": 1.0})

    def test_weighted_l1_rejects_missing_key(self):
        with self.assertRaises(ValueError):
            weighted_l1({"a": 1}, {"b": 1})

    def test_weighted_l1(self):
        self.assertEqual(weighted_l1({"a": 3, "b": 1}, {"a": 1, "b": 2}, {"a": 2, "b": 1}), 5.0)


if __name__ == "__main__":
    unittest.main()
