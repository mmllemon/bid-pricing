"""T00-01《计价规则卡》测试。

两条主线：

1. **规范 ↔ 实现双向锁定** —— 规则卡 JSON 声明的阈值必须等于
   ``rule_sets.base`` 的代码常量；P1 计算结果必须与 ``rule_sets``
   的 ``settlement_amount`` 逐值对拍（防「同一规则两处实现」）。
2. **未定态必须阻断** —— 输入缺失 / 未知 override 一律 BLOCKED，
   不得降级为默认值（ADR-0004/0005/0007）。
"""

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.contracts.pricing_card import (
    CARD_FILENAME,
    REGISTERED_OVERRIDES,
    STATUS_BLOCKED,
    STATUS_PASS,
    PricingCardError,
    classify_branch,
    compute_p1,
    load_pricing_card,
    resolve_parameters,
)
from bidpricing.contracts.rule_sets import base as rs_base
from bidpricing.contracts.rule_sets.gbt50500_2024 import GBT50500_2024_RuleSet

CARD_PATH = Path(__file__).resolve().parents[1] / "config" / CARD_FILENAME


def _card() -> dict:
    return json.loads(CARD_PATH.read_text(encoding="utf-8"))


class TestCardArtifact(unittest.TestCase):
    """制品结构：必填键与五项澄清齐备。"""

    def setUp(self):
        self.card = _card()

    def test_required_keys_present(self):
        for key in ("card_id", "rule_set_id", "adjustment_scope", "contract_type",
                    "symbols", "parameters", "p1_clarifications", "p1_formula",
                    "precedence_chain", "override_policy", "binding"):
            self.assertIn(key, self.card, f"规则卡缺 {key}")

    def test_five_clarifications_all_resolved(self):
        """T00-01 要求：P1 计算规则的 5 项澄清必须全部有结论。"""
        clar = self.card["p1_clarifications"]
        self.assertEqual(len(clar), 5)
        self.assertEqual([c["id"] for c in clar],
                         ["P1-A", "P1-B", "P1-C", "P1-D", "P1-E"])
        for c in clar:
            self.assertEqual(c["status"], "RESOLVED", c["id"])
            self.assertTrue(c["resolution"].strip(), c["id"])
            self.assertTrue(c["basis"].strip(), c["id"])

    def test_symbols_bind_to_canonical_fields(self):
        """符号绑定必须是字段字典里真实存在的字段名。

        2026-09-17 实测：P0 曾误绑 ``p_i``（字段字典无此字段）。决策变量实为
        ``p_bid``；``p0`` 是控制价/合同价，本项目取值等于 cap_i。字段名的事实源
        在字段字典，规则卡只应引用——此处与 contract-check 第 13 判据双保险。
        """
        sym = self.card["symbols"]
        self.assertEqual(sym["Q0"]["binding"], "q0")
        self.assertEqual(sym["Q1"]["binding"], "q1_point")
        self.assertEqual(sym["P0"]["binding"], "p_bid")
        self.assertEqual(sym["P1"]["binding"], "p1")
        self.assertEqual(sym["S"]["binding"], "settlement_amount")

    def test_rho_default_is_declared_as_mechanism(self):
        """ρ=0 必须被显式说明为机制层默认，而非项目数据缺省。"""
        p = self.card["parameters"]
        self.assertEqual(p["rho_plus"], 0.0)
        self.assertEqual(p["rho_minus"], 0.0)
        self.assertTrue(p.get("rho_default_is_mechanism_not_data", "").strip())

    def test_missing_card_is_blocked_not_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PricingCardError) as ctx:
                load_pricing_card(Path(tmp))
        self.assertIn("未定态", str(ctx.exception))

    def test_incomplete_card_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / CARD_FILENAME).write_text(
                json.dumps({"card_id": "broken"}), encoding="utf-8")
            with self.assertRaises(PricingCardError) as ctx:
                load_pricing_card(Path(tmp))
        self.assertIn("缺必填键", str(ctx.exception))


class TestConstantLock(unittest.TestCase):
    """规则卡声明值 ↔ 代码常量互锁。"""

    def setUp(self):
        self.card = _card()
        self.params = resolve_parameters(self.card)

    def test_thresholds_equal_code_constants(self):
        self.assertEqual(self.params.increase_threshold, rs_base.INCREASE_THRESHOLD)
        self.assertEqual(self.params.decrease_threshold, rs_base.DECREASE_THRESHOLD)

    def test_card_declared_thresholds_match_constants(self):
        p = self.card["parameters"]
        self.assertEqual(p["increase_threshold"], rs_base.INCREASE_THRESHOLD)
        self.assertEqual(p["decrease_threshold"], rs_base.DECREASE_THRESHOLD)

    def test_branch_classification_matches_rule_set(self):
        rs = GBT50500_2024_RuleSet()
        for r in (0.5, 0.849, 0.85, 1.0, 1.15, 1.151, 3.0):
            with self.subTest(r=r):
                self.assertEqual(classify_branch(r, self.params),
                                 rs.classify_branch(r))

    def test_threshold_override_conflicting_with_constant_is_blocked(self):
        with self.assertRaises(PricingCardError) as ctx:
            resolve_parameters(self.card, {"increase_threshold": 1.2})
        self.assertIn("两处说法", str(ctx.exception))

    def test_registered_overrides_match_card_policy(self):
        self.assertEqual(set(self.card["override_policy"]["registered_overrides"]),
                         set(REGISTERED_OVERRIDES))


class TestP1Computation(unittest.TestCase):
    """P1 与结算金额：逐分支 + 与 rule_sets 跨模块对拍。"""

    def setUp(self):
        self.card = _card()

    def _cross_check(self, q0, q1, p0, override=None):
        res = compute_p1(q0, q1, p0, self.card, override)
        self.assertEqual(res.status, STATUS_PASS)
        params = res.parameters
        rs = GBT50500_2024_RuleSet()
        expected = rs.settlement_amount(
            q0, q1, p0,
            rho_plus=params["rho_plus"], rho_minus=params["rho_minus"],
            scope=params["adjustment_scope"],
        )
        self.assertAlmostEqual(res.settlement, expected, places=9)
        return res

    def test_in_range_no_adjustment(self):
        res = self._cross_check(100.0, 105.0, 50.0)
        self.assertEqual(res.branch, rs_base.BRANCH_IN_RANGE)
        self.assertAlmostEqual(res.p1, 50.0)
        self.assertAlmostEqual(res.settlement, 105.0 * 50.0)

    def test_decrease_branch_raises_unit_price(self):
        res = self._cross_check(100.0, 70.0, 50.0)
        self.assertEqual(res.branch, rs_base.BRANCH_DECREASE)
        self.assertAlmostEqual(res.p1, 50.0)      # ρ⁻=0 时等于 P0
        self.assertAlmostEqual(res.settlement, 70.0 * 50.0)

    def test_increase_segment_keeps_contract_part(self):
        res = self._cross_check(100.0, 150.0, 50.0)
        self.assertEqual(res.branch, rs_base.BRANCH_INCREASE)
        self.assertAlmostEqual(res.settlement, 1.15 * 100 * 50 + (150 - 115) * 50)

    def test_increase_full_differs_from_segment_when_rho_nonzero(self):
        """SEGMENT 与 FULL 的差异只在 ρ⁺≠0 时显现——两者必须可比。"""
        seg = compute_p1(100.0, 150.0, 50.0, self.card,
                         {"adjustment_scope": "SEGMENT", "rho_plus": 0.1})
        full = compute_p1(100.0, 150.0, 50.0, self.card,
                          {"adjustment_scope": "FULL", "rho_plus": 0.1})
        self.assertAlmostEqual(full.settlement, 150 * 45)
        self.assertAlmostEqual(seg.settlement, 115 * 50 + 35 * 45)
        self.assertGreater(seg.settlement, full.settlement)

    def test_rho_override_changes_p1_and_is_recorded(self):
        res = compute_p1(100.0, 150.0, 50.0, self.card, {"rho_plus": 0.1})
        self.assertAlmostEqual(res.p1, 45.0)
        self.assertEqual(res.parameters["sources"]["rho_plus"], "override")
        self.assertTrue(any("ρ±" in b for b in res.basis))

    def test_decrease_side_full_equals_segment(self):
        """减量侧 FULL 与 SEGMENT 等价（剩余部分本就是全部 Q1）。"""
        a = compute_p1(100.0, 70.0, 50.0, self.card,
                       {"adjustment_scope": "FULL", "rho_minus": 0.2})
        b = compute_p1(100.0, 70.0, 50.0, self.card,
                       {"adjustment_scope": "SEGMENT", "rho_minus": 0.2})
        self.assertAlmostEqual(a.settlement, b.settlement)
        self.assertAlmostEqual(a.p1, 60.0)


class TestUndeterminedIsBlocked(unittest.TestCase):
    """未定态一律 BLOCKED，不降级为默认值。"""

    def setUp(self):
        self.card = _card()

    def test_missing_q0(self):
        r = compute_p1(None, 100.0, 50.0, self.card)
        self.assertEqual(r.status, STATUS_BLOCKED)
        self.assertIn("Q0", r.blocked_reason)

    def test_missing_q1(self):
        r = compute_p1(100.0, None, 50.0, self.card)
        self.assertEqual(r.status, STATUS_BLOCKED)
        self.assertIn("Q1", r.blocked_reason)

    def test_missing_p0(self):
        r = compute_p1(100.0, 110.0, None, self.card)
        self.assertEqual(r.status, STATUS_BLOCKED)
        self.assertIn("P0", r.blocked_reason)

    def test_zero_q0(self):
        r = compute_p1(0.0, 100.0, 50.0, self.card)
        self.assertEqual(r.status, STATUS_BLOCKED)
        self.assertIn("Q0 <= 0", r.blocked_reason)

    def test_unknown_override_key_is_blocked(self):
        with self.assertRaises(PricingCardError) as ctx:
            compute_p1(100.0, 110.0, 50.0, self.card, {"vip_discount": 0.9})
        self.assertIn("未登记", str(ctx.exception))

    def test_unknown_override_is_not_silently_ignored(self):
        """已知键 + 未知键混用：整体阻断，不是「用已知的那部分」。"""
        with self.assertRaises(PricingCardError):
            compute_p1(100.0, 110.0, 50.0, self.card,
                       {"rho_plus": 0.1, "mystery": 1})

    def test_none_valued_override_is_ignored_not_blocked(self):
        """显式 None = 未声明（非未知键），按未定态处理而非阻断。"""
        res = compute_p1(100.0, 110.0, 50.0, self.card, {"rho_plus": None})
        self.assertEqual(res.status, STATUS_PASS)
        self.assertEqual(res.parameters["sources"]["rho_plus"],
                         "pricing_rule_card")


class TestUnbalancedClause(unittest.TestCase):
    """不平衡报价条款口径（OI-05/OI-06）在规则卡中留痕。"""

    def setUp(self):
        self.clause = _card()["unbalanced_price_clause"]

    def test_benchmark_is_cap_bidirectional(self):
        self.assertIn("cap_i", self.clause["benchmark"])
        self.assertIn("50%", self.clause["high_side"])
        self.assertIn("50%", self.clause["low_side"])

    def test_consequence_is_settlement_adjustment(self):
        """后果=结算修正（SETTLEMENT_ADJUSTMENT），**不是**投标有效性。"""
        self.assertTrue(
            self.clause["consequence"].startswith("SETTLEMENT_ADJUSTMENT"))
        self.assertIn("非投标有效性", self.clause["consequence"])

    def test_high_side_dead_branch_is_derived(self):
        """偏高侧死分支是 C2 的推导结论，须在卡内留痕而非口头约定。"""
        self.assertIn("C2", self.clause["high_side_dead_branch"])
        self.assertIn("死分支", self.clause["high_side_dead_branch"])

    def test_p_rev_nominal_value_is_cap(self):
        self.assertIn("cap_i", self.clause["p_rev_handling"])
        self.assertIn("敏感性", self.clause["p_rev_handling"])


if __name__ == "__main__":
    unittest.main()
