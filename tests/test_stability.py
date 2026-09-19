import unittest

from bidpricing.solver.stability import (
    detect_platform,
    p95_latency,
    relative_tolerance,
    restore_values,
    scale_coefficients,
    truncate_epsilon,
)


class StabilityTest(unittest.TestCase):
    def test_truncation_and_relative_tolerance(self):
        self.assertEqual(truncate_epsilon({"a": 1e-10, "b": 2.0}, eps_abs=1e-9), {"a": 0.0, "b": 2.0})
        self.assertEqual(relative_tolerance(100.0, eps_abs=0.01, eps_r=1e-6), 0.01)

    def test_scale_and_restore(self):
        scaled = scale_coefficients({"a": 2.0, "b": -4.0})
        self.assertEqual(scaled.factor, 4.0)
        self.assertEqual(restore_values(scaled.values, factor=scaled.factor), {"a": 2.0, "b": -4.0})

    def test_all_zero_blocks(self):
        self.assertEqual(scale_coefficients({"a": 1e-10}, eps_abs=1e-9).issue.status, "BLOCKED")

    def test_platform_excludes_zero_quantity(self):
        issue = detect_platform({"a": 1.0, "b": 1.0, "z": 1.0}, q0={"a": 1, "b": 1, "z": 0})
        self.assertEqual(issue.status, "WARN")
        self.assertEqual(issue.actual, [["a", "b"]])

    def test_no_platform_passes(self):
        self.assertEqual(detect_platform({"a": 1.0, "b": 2.0}).status, "PASS")

    def test_p95_empty_is_unknown(self):
        self.assertIsNone(p95_latency([]))
        self.assertEqual(p95_latency([10, 20, 30, 40]), 40.0)


if __name__ == "__main__":
    unittest.main()
