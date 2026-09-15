"""RuleSet 两版实现与 T00-08 机械指纹的测试。"""

from __future__ import annotations

import unittest

from bidpricing.contracts.rule_sets import (
    BRANCH_DECREASE,
    BRANCH_IN_RANGE,
    BRANCH_INCREASE,
    GB50500_2013_RuleSet,
    GBT50500_2024_RuleSet,
    AdjustmentScopeNotFrozen,
)
from bidpricing.contracts.selector import ruleset_self_test

RS13 = GB50500_2013_RuleSet()
RS24 = GBT50500_2024_RuleSet()


class BoundaryTest(unittest.TestCase):
    """判据 J2：Q1=0.85Q0 / Q1=1.15Q0 均判为「不触发调价」（严格不等式）。"""

    def test_decrease_boundary_is_inclusive_in_range(self):
        self.assertEqual(RS13.classify_branch(0.85), BRANCH_IN_RANGE)
        self.assertEqual(RS13.classify_branch(0.8499), BRANCH_DECREASE)

    def test_increase_boundary_is_inclusive_in_range(self):
        self.assertEqual(RS13.classify_branch(1.15), BRANCH_IN_RANGE)
        self.assertEqual(RS13.classify_branch(1.1501), BRANCH_INCREASE)


class MechanismDifferenceTest(unittest.TestCase):
    """路线 §8.3 机制差异 2：2024 版在 15% 阈值处由连续变为不连续。"""

    def test_2013_is_continuous_across_threshold(self):
        eps = 1e-7
        lo = RS13.effective_revenue_multiple(1.0, 1.15 - eps, 1.0, rho_plus=0.05)
        hi = RS13.effective_revenue_multiple(1.0, 1.15 + eps, 1.0, rho_plus=0.05)
        self.assertLess(abs(hi - lo), 1e-6)

    def test_2024_full_jumps_down_at_threshold(self):
        eps = 1e-7
        rho = 0.05
        lo = RS24.effective_revenue_multiple(
            1.0, 1.15 - eps, 1.0, rho_plus=rho, scope="FULL"
        )
        hi = RS24.effective_revenue_multiple(
            1.0, 1.15 + eps, 1.0, rho_plus=rho, scope="FULL"
        )
        jump = hi - lo
        self.assertLess(jump, 0, "2024 FULL 口径在阈值处必须跳降")
        self.assertAlmostEqual(jump, -1.15 * rho, places=6)

    def test_2024_segment_matches_2013_on_increase_side(self):
        """SEGMENT 口径与 2013 同形——这正是 4.5 倍利润差的来源。"""
        a = RS13.settlement_amount(100.0, 130.0, 10.0, rho_plus=0.05)
        b = RS24.settlement_amount(100.0, 130.0, 10.0, rho_plus=0.05, scope="SEGMENT")
        self.assertAlmostEqual(a, b, places=9)

    def test_2024_full_differs_materially_from_segment(self):
        full = RS24.settlement_amount(100.0, 130.0, 10.0, rho_plus=0.05, scope="FULL")
        seg = RS24.settlement_amount(100.0, 130.0, 10.0, rho_plus=0.05, scope="SEGMENT")
        self.assertLess(full, seg)

    def test_decrease_side_scope_is_irrelevant(self):
        """2024 减量侧 FULL 与 SEGMENT 等价：减少后剩余部分本就是全部 q1。"""
        full = RS24.settlement_amount(100.0, 70.0, 10.0, rho_minus=0.05, scope="FULL")
        seg = RS24.settlement_amount(100.0, 70.0, 10.0, rho_minus=0.05, scope="SEGMENT")
        self.assertAlmostEqual(full, seg, places=9)


class UnfrozenScopeTest(unittest.TestCase):
    """§7.1.1 断言 2 在求解层面的落地：未冻结不得求解。"""

    def test_2024_raises_without_scope(self):
        with self.assertRaises(AdjustmentScopeNotFrozen):
            RS24.settlement_amount(100.0, 130.0, 10.0, rho_plus=0.05)

    def test_2024_raises_on_illegal_scope(self):
        for bad in ("未定", None, "FULL_SEGMENT"):
            with self.assertRaises(AdjustmentScopeNotFrozen, msg=repr(bad)):
                RS24.settlement_amount(100.0, 130.0, 10.0, rho_plus=0.05, scope=bad)

    def test_2013_ignores_scope(self):
        """2013 §9.6.2 明文分段，作用域非歧义。"""
        self.assertAlmostEqual(
            RS13.settlement_amount(100.0, 130.0, 10.0, rho_plus=0.05),
            RS13.settlement_amount(100.0, 130.0, 10.0, rho_plus=0.05, scope="FULL"),
            places=9,
        )


class FingerprintTest(unittest.TestCase):
    """T00-08 机械判据：r_eff 在 1.15±δ 处的跳变量。"""

    def test_self_test_passes(self):
        result = ruleset_self_test()
        self.assertTrue(result["passed"], result)

    def test_2013_fingerprint_is_near_zero(self):
        self.assertLess(abs(RS13.fingerprint(rho_probe=0.01)), 1e-6)

    def test_2024_fingerprint_matches_expected_magnitude(self):
        self.assertAlmostEqual(
            RS24.fingerprint(rho_probe=0.01), -1.15 * 0.01, places=6
        )

    def test_two_implementations_are_separable(self):
        """「不得仅因条文号不同而输出相同」。"""
        gap = abs(RS24.fingerprint(rho_probe=0.01) - RS13.fingerprint(rho_probe=0.01))
        self.assertGreater(gap, 0.5 * 1.15 * 0.01)

    def test_fingerprint_degenerates_at_zero_probe(self):
        """已知退化条件：rho_probe=0 时两版指纹重合——已在规格中显式登记。"""
        self.assertAlmostEqual(RS13.fingerprint(rho_probe=0.0), 0.0, places=6)
        self.assertAlmostEqual(RS24.fingerprint(rho_probe=0.0), 0.0, places=6)

    def test_2024_fingerprint_is_scope_dependent(self):
        """指纹随作用域变化：FULL 跳降、SEGMENT 连续。"""
        self.assertAlmostEqual(
            RS24.fingerprint(rho_probe=0.01, scope="FULL"), -1.15 * 0.01, places=6
        )
        self.assertLess(abs(RS24.fingerprint(rho_probe=0.01, scope="SEGMENT")), 1e-6)

    def test_self_test_exposes_segment_degeneracy(self):
        """选择 SEGMENT 会让数值指纹失去鉴别力——必须登记为遗留项而非静默通过。"""
        result = ruleset_self_test()
        self.assertIn("rs_2024_fingerprint_SEGMENT", result["checks"])
        self.assertTrue(result["checks"]["rs_2024_fingerprint_SEGMENT"]["degenerate"])
        self.assertTrue(
            any("退化" in a for a in result["advisories"]), result["advisories"]
        )

    def test_supported_scopes_are_declared_per_rule_set(self):
        self.assertEqual(RS13.supported_scopes, ("SEGMENT",))
        self.assertEqual(set(RS24.supported_scopes), {"FULL", "SEGMENT"})


if __name__ == "__main__":
    unittest.main()
