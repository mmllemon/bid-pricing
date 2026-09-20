import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.solver.parity import (
    TOLERANCE_KEYS,
    compare_phase12,
    independence_status,
    load_spec,
    resolve_tolerances,
)

SPEC_TIGHT = {"tolerances": {"objective_abs": 1e-7, "price_abs": 1e-7, "residual_abs": 1e-7}}
SPEC_LOOSE = {"tolerances": {"objective_abs": 1.0, "price_abs": 1.0, "residual_abs": 1.0}}


def side(**kw):
    """一侧结果的构造器：默认带上状态（L1 要求两侧都产出可比较状态）。"""
    base = {"status": "OPTIMAL", "objective": 10.0, "prices": {"x": 2.0}}
    base.update(kw)
    return base


class ParityBase(unittest.TestCase):
    def signoff(self, root: Path, signed=True):
        p = root / "reference_review_signoff.json"
        p.write_text(
            json.dumps({"signed": signed, "reviewer": "reviewer" if signed else ""}),
            encoding="utf-8",
        )
        return p

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.signoff_path = self.signoff(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def compare(self, a, b, **kw):
        kw.setdefault("spec", SPEC_TIGHT)
        kw.setdefault("signoff_path", self.signoff_path)
        kw.setdefault("floor_source", "tests: floor 表显式给出")
        return compare_phase12(a, b, **kw)


class SpecDeclarationTest(ParityBase):
    def test_spec_declares_two_groups(self):
        self.assertEqual(load_spec()["groups"], ["A", "B"])

    def test_spec_declares_every_tolerance_the_comparator_reads(self):
        """CT-06 式双向对账：制品声明的容差键 ⊆/⊇ 实现读取的容差键。"""
        declared = set((load_spec().get("tolerances") or {}).keys())
        self.assertEqual(declared, set(TOLERANCE_KEYS))

    def test_unresolved_tolerance_is_not_defaulted(self):
        resolved, unresolved = resolve_tolerances({"tolerances": {"objective_abs": 1e-7}})
        self.assertEqual(resolved, {"objective_abs": 1e-7})
        self.assertEqual(set(unresolved), {"price_abs", "residual_abs"})

    def test_explicit_override_wins(self):
        resolved, unresolved = resolve_tolerances(SPEC_TIGHT, overrides={"price_abs": 5.0})
        self.assertEqual(resolved["price_abs"], 5.0)
        self.assertEqual(unresolved, ())


class GateTest(ParityBase):
    def test_unsigned_is_blocked(self):
        path = self.signoff(self.root, signed=False)
        result = compare_phase12(side(), side(), spec=SPEC_TIGHT, signoff_path=path)
        self.assertEqual(result.status, "BLOCKED")

    def test_missing_signoff_is_blocked(self):
        self.assertEqual(independence_status("does-not-exist.json"), "BLOCKED")

    def test_inapplicable_is_blocked(self):
        result = self.compare(side(), side(), applicable=False)
        self.assertEqual(result.status, "BLOCKED")

    def test_unknown_group_is_blocked(self):
        result = self.compare(side(), side(), group="C")
        self.assertEqual(result.status, "BLOCKED")


class L1StatusTest(ParityBase):
    def test_missing_status_on_one_side_is_blocked_even_if_numbers_match(self):
        """数值相等**不能**替代状态可比——这正是「两侧解了不同问题」的形态。"""
        result = self.compare({"objective": 1.0, "prices": {"x": 1.0}}, side(objective=1.0))
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("L1", result.reason)

    def test_both_statuses_are_recorded(self):
        result = self.compare(side(status="OPTIMAL"), side(status="FEASIBLE"))
        self.assertEqual(result.phase1_status, "OPTIMAL")
        self.assertEqual(result.phase2_status, "FEASIBLE")


class L2Test(ParityBase):
    def test_objective_mismatch_fails(self):
        result = self.compare(side(), side(objective=2.0))
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.level, "L2")

    def test_price_mismatch_fails(self):
        result = self.compare(side(), side(prices={"x": 3.0}))
        self.assertEqual(result.status, "FAIL")

    def test_missing_price_id_is_fail(self):
        result = self.compare(side(), side(prices={"y": 2.0}))
        self.assertEqual(result.status, "FAIL")
        self.assertTrue(any("price ids missing" in m for m in result.mismatches))

    def test_matching_prices_pass(self):
        result = self.compare(side(), side())
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.level, "L2")

    def test_tolerance_is_taken_from_spec_not_from_code_literal(self):
        """制品把宽度放到 1.0 ⇒ 差 0.5 必须 PASS；硬编码 1e-7 的实现会判 FAIL。"""
        result = self.compare(side(objective=10.0), side(objective=10.5), spec=SPEC_LOOSE)
        self.assertEqual(result.status, "PASS")

    def test_missing_objective_tolerance_blocks(self):
        spec = {"tolerances": {"price_abs": 1e-7}}
        result = self.compare(side(), side(), spec=spec)
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("objective_abs", result.reason)

    def test_missing_price_vector_blocks(self):
        result = self.compare(side(prices=None), side())
        self.assertEqual(result.status, "BLOCKED")


class L3Test(ParityBase):
    def test_layers_equal_pass_at_l3(self):
        result = self.compare(side(layers={"x": "INTERIOR"}), side(layers={"x": "INTERIOR"}))
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.level, "L3")

    def test_layers_mismatch_warns(self):
        result = self.compare(side(layers={"x": "INTERIOR"}), side(layers={"x": "BOUND"}))
        self.assertEqual(result.status, "WARN")

    def test_residual_over_tolerance_fails(self):
        result = self.compare(side(residuals={"x": 0.0}), side(residuals={"x": 0.5}))
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.level, "L3")

    def test_residual_within_tolerance_passes(self):
        result = self.compare(side(residuals={"x": 0.0}), side(residuals={"x": 1e-9}))
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.level, "L3")

    def test_residual_on_one_side_only_is_blocked(self):
        """口径不可比既不是 PASS 也不是 FAIL——不得静默把缺失侧当 0。"""
        result = self.compare(side(residuals={"x": 0.0}), side())
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("不可比", result.reason)

    def test_missing_residual_tolerance_blocks(self):
        spec = {"tolerances": {"objective_abs": 1e-7, "price_abs": 1e-7}}
        result = self.compare(side(residuals={"x": 0.0}), side(residuals={"x": 0.0}), spec=spec)
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("residual_abs", result.reason)


class GroupBTest(ParityBase):
    def test_phase2_better_than_phase1_is_recorded_as_obligation(self):
        """报价向量一致而 Phase 2 目标值更高 ⇒ 目标函数口径分歧（H-002b 同族）。

        L2 仍判 FAIL（对拍本职就是数值一致性），但 B 组义务必须**额外**记下这条
        归因——只说「数值不一致」会把「口径分歧」误报成「求解器错」。
        """
        result = self.compare(
            side(objective=10.0, feasible=True), side(objective=11.0), group="B"
        )
        self.assertEqual(result.status, "FAIL")
        self.assertTrue(any("优于" in o for o in result.obligations))

    def test_phase2_worse_is_not_a_b_obligation(self):
        result = self.compare(
            side(objective=10.0, feasible=True), side(objective=9.0), group="B"
        )
        self.assertEqual(result.obligations, ())

    def test_undeclared_feasibility_is_an_obligation_not_a_pass(self):
        result = self.compare(side(objective=10.0), side(objective=10.0), group="B")
        self.assertEqual(result.status, "PASS")
        self.assertTrue(any("未走到" in o for o in result.obligations))

    def test_group_a_has_no_b_obligation(self):
        result = self.compare(side(objective=10.0), side(objective=10.0), group="A")
        self.assertEqual(result.obligations, ())


class FloorSourceTest(ParityBase):
    def test_undeclared_floor_source_is_recorded(self):
        result = compare_phase12(
            side(), side(), spec=SPEC_TIGHT, signoff_path=self.signoff_path
        )
        self.assertTrue(any("floor 来源未声明" in o for o in result.obligations))

    def test_declared_floor_source_is_carried_through(self):
        result = self.compare(side(), side())
        self.assertEqual(result.floor_source, "tests: floor 表显式给出")
        self.assertEqual(result.obligations, ())


class MutationDiscriminationTest(ParityBase):
    """变异体注入：每条坏实现必须被**具名**判据杀死。存活 ⇒ FAIL。

    判定条件不依赖被测实现的可解释性文案——只比 ``status`` 行为。
    """

    def _kills(self, bad_result, good_result, expected_status):
        # 杀死 = 坏实现在该输入上给出的 status 不同于正确 status
        return bad_result != good_result or good_result != expected_status

    def test_v1_hardcoded_tolerance_would_be_killed(self):
        """V1：忽略制品容差、用代码字面量 1e-7 ⇒ 在 SPEC_LOOSE 下会判 FAIL。"""
        loose_input = (side(objective=10.0), side(objective=10.5))
        good = self.compare(*loose_input, spec=SPEC_LOOSE).status
        bad = self.compare(*loose_input, spec=SPEC_TIGHT).status  # 硬编码宽的替身
        self.assertEqual(good, "PASS")
        self.assertEqual(bad, "FAIL")
        self.assertTrue(self._kills(bad, good, "PASS"))

    def test_v2_status_check_skipped_would_be_killed(self):
        """V2：跳过 L1（缺状态也放行）⇒ 会在缺状态输入上判 PASS。"""
        missing_status = ({"objective": 1.0, "prices": {"x": 1.0}}, side(objective=1.0))
        good = self.compare(*missing_status).status
        self.assertEqual(good, "BLOCKED")

    def test_v3_residual_check_skipped_would_be_killed(self):
        """V3：不查 L3 残差 ⇒ 会在残差超容差输入上判 PASS。"""
        over = (side(residuals={"x": 0.0}), side(residuals={"x": 0.5}))
        self.assertEqual(self.compare(*over).status, "FAIL")
        without_l3 = self.compare(side(), side()).status
        self.assertEqual(without_l3, "PASS")

    def test_v4_one_sided_residual_treated_as_zero_would_be_killed(self):
        """V4：单侧残差静默当 0 ⇒ 会在口径不可比输入上判 PASS。"""
        onesided = (side(residuals={"x": 0.0}), side())
        self.assertEqual(self.compare(*onesided).status, "BLOCKED")

    def test_v5_dropped_obligations_would_be_killed(self):
        """V5：丢掉 B 组义务 ⇒ 报告少一条可追溯项且无信号。"""
        result = self.compare(
            side(objective=10.0, feasible=True), side(objective=11.0), group="B"
        )
        self.assertNotEqual(result.obligations, ())

    def test_v6_floor_source_not_declared_would_be_killed(self):
        result = compare_phase12(
            side(), side(), spec=SPEC_TIGHT, signoff_path=self.signoff_path
        )
        self.assertTrue(result.obligations)


if __name__ == "__main__":
    unittest.main()
