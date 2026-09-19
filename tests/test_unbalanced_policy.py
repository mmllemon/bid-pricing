import unittest

from bidpricing.validation.unbalanced import (
    SETTLEMENT_ADJUSTMENT,
    UnbalancedPolicyError,
    apply_validity_lower_bounds,
    parse_unbalanced_policy,
    settlement_revenue_adjusted,
)


class UnbalancedPolicyTest(unittest.TestCase):
    def test_cap_validity_adds_lower_bound(self):
        policy = parse_unbalanced_policy({
            "enabled": True, "reference": "CAP", "tol_lo": 0.5,
            "tol_hi": 0.5, "mechanism": "BID_VALIDITY",
        })
        rows, notes = apply_validity_lower_bounds(
            [{"item_id": "A", "cap": 100, "L": 0.01}], policy
        )
        self.assertEqual(rows[0]["L"], 50.0)
        self.assertEqual(notes, ())

    def test_no_cap_is_not_treated_as_zero(self):
        policy = parse_unbalanced_policy({
            "enabled": True, "reference": "CAP", "tol_lo": 0.5,
            "tol_hi": 0.5, "mechanism": "BID_VALIDITY",
        })
        rows, notes = apply_validity_lower_bounds([{"item_id": "A", "cap": None}], policy)
        self.assertIsNone(rows[0].get("unbalanced_lower_bound"))
        self.assertIn("无最高限价", notes[0])

    def test_settlement_adjustment_blocks_until_revenue_is_wired(self):
        policy = parse_unbalanced_policy({
            "enabled": True, "reference": "CAP", "tol_lo": 0.5,
            "tol_hi": 0.5, "mechanism": SETTLEMENT_ADJUSTMENT,
        })
        with self.assertRaises(UnbalancedPolicyError):
            apply_validity_lower_bounds([{"item_id": "A", "cap": 100}], policy)

    def test_settlement_piecewise_formula(self):
        # q0=100, bid=40 (<50% cap=100)
        self.assertEqual(settlement_revenue_adjusted(100, 100, 40, 100), 4000)
        # 增量超过15%：超出部分仍取较低单价 bid
        self.assertEqual(settlement_revenue_adjusted(100, 130, 40, 100), 5200)
        # 减量超过15%：仅超出15%的减少部分承担 cap-bid 修正
        self.assertEqual(settlement_revenue_adjusted(100, 80, 40, 100), 2900)

    def test_exact_fifty_percent_is_not_severe_low_bid(self):
        self.assertEqual(settlement_revenue_adjusted(100, 50, 50, 100), 2500)


if __name__ == "__main__":
    unittest.main()
