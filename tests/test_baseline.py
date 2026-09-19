import unittest

from bidpricing.baseline import BaselineError, build_baseline, compute_z_baseline, verify_frozen


class BaselineTest(unittest.TestCase):
    def test_uniform_discount_is_reproducible(self):
        result = build_baseline({"method": "UNIFORM_DISCOUNT", "discount": 0.1, "version": "v1", "frozen": True}, cap_by_id={"b": 200, "a": 100})
        self.assertEqual(result.prices, {"a": 90.0, "b": 180.0})
        self.assertTrue(verify_frozen(result))
        self.assertEqual(compute_z_baseline(result, lambda _i, p: p), 270.0)

    def test_manual_and_convention_are_explicit(self):
        result = build_baseline({"method": "PREVIOUS_MANUAL", "price_by_id": {"a": 10}, "version": "2025", "frozen": True})
        self.assertEqual(result.method, "PREVIOUS_MANUAL")

    def test_unfrozen_or_unknown_is_rejected(self):
        with self.assertRaises(BaselineError):
            build_baseline({"method": "PREVIOUS_MANUAL", "price_by_id": {"a": 1}, "version": "v1", "frozen": False})
        with self.assertRaises(BaselineError):
            build_baseline({"method": "AUTO", "version": "v1", "frozen": True})

    def test_missing_input_is_rejected(self):
        with self.assertRaises(BaselineError):
            build_baseline({"method": "UNIFORM_DISCOUNT", "discount": 0.1, "version": "v1", "frozen": True})

    def test_fingerprint_detects_change(self):
        result = build_baseline({"method": "COMPANY_CONVENTION", "price_by_id": {"a": 1}, "version": "v1", "frozen": True})
        altered = type(result)(result.method, result.version, {"a": 2}, result.fingerprint, True)
        self.assertFalse(verify_frozen(altered))


if __name__ == "__main__":
    unittest.main()
