"""T00-08 规则集选择器测试。

重点是两条**禁止默认取任一侧**的判据，以及未定态在输出中的表示法。
"""

from __future__ import annotations

import unittest

from bidpricing.contracts.selector import select_rule_set
from bidpricing.states import Status


class DefaultRuleTest(unittest.TestCase):
    def test_post_cutover_defaults_to_2024(self):
        sel = select_rule_set(contract_date="2026-03-01")
        self.assertEqual(sel.rule_set_id, "GB/T50500-2024")
        self.assertEqual(sel.effective_date, "2025-09-01")

    def test_adjustment_scope_key_is_absent_when_undetermined(self):
        """§7.1.1 断言 1：未定态 = key 完全缺失，而非 '未定' 字符串。"""
        sel = select_rule_set(contract_date="2026-03-01")
        payload = sel.to_dict()
        self.assertNotIn("adjustment_scope", payload)
        self.assertIs(sel.status, Status.BLOCKED)
        self.assertTrue(any("adjustment_scope 未定" in b for b in sel.blockers))

    def test_scope_key_present_when_t00_01_freezes_it(self):
        sel = select_rule_set(contract_date="2026-03-01", adjustment_scope_declared="FULL")
        payload = sel.to_dict()
        self.assertEqual(payload["adjustment_scope"], "FULL")
        self.assertIs(sel.status, Status.PASS)


class TransitionProjectTest(unittest.TestCase):
    def test_2013_via_contract_override_with_pre_cutover_contract(self):
        sel = select_rule_set(
            contract_override="GB50500-2013", contract_date="2024-03-01"
        )
        self.assertEqual(sel.rule_set_id, "GB50500-2013")
        self.assertIs(sel.status, Status.PASS)
        # 2013 §9.6.2 明文分段，作用域非歧义
        self.assertEqual(sel.adjustment_scope, "SEGMENT")

    def test_2013_declaration_without_pre_cutover_dates_is_blocked(self):
        """§8.3 校正一：两个条件须同时成立，矛盾时交人裁定而非默认。"""
        sel = select_rule_set(
            standard_version_declared="GB50500-2013",
            tender_document_date="2026-01-01",
            contract_date="2026-02-01",
        )
        self.assertIs(sel.status, Status.BLOCKED)
        self.assertTrue(any("矛盾" in b for b in sel.blockers))

    def test_pre_cutover_dates_without_declaration_is_blocked(self):
        """仅命中日期条件不足以回落 2013——这就是「禁止默认取任一侧」。"""
        sel = select_rule_set(contract_date="2024-06-01")
        self.assertIsNone(sel.rule_set_id)
        self.assertIs(sel.status, Status.BLOCKED)
        self.assertTrue(any("过渡项目窗口" in b for b in sel.blockers))

    def test_2013_declaration_without_any_date_is_blocked(self):
        sel = select_rule_set(standard_version_declared="GB 50500-2013")
        self.assertIs(sel.status, Status.BLOCKED)
        self.assertTrue(any("未提供招标文件发布日期" in b for b in sel.blockers))

    def test_2013_scope_declaration_is_overridden_by_standard(self):
        sel = select_rule_set(
            contract_override="GB50500-2013",
            contract_date="2024-03-01",
            adjustment_scope_declared="FULL",
        )
        self.assertEqual(sel.adjustment_scope, "SEGMENT")
        self.assertTrue(any("被规范明文覆盖" in d for d in sel.decisions))


class UnrecognizedStandardTest(unittest.TestCase):
    def test_unknown_declaration_is_blocked(self):
        sel = select_rule_set(standard_version_declared="GB50500-99", contract_date="2020-01-01")
        self.assertIs(sel.status, Status.BLOCKED)
        self.assertIsNone(sel.rule_set_id)


class PrecedenceTest(unittest.TestCase):
    def test_contract_beats_tender(self):
        sel = select_rule_set(
            contract_override="GB/T50500-2024",
            tender_document_override="GB50500-2013",
            contract_date="2026-01-01",
        )
        self.assertEqual(sel.rule_set_id, "GB/T50500-2024")
        self.assertTrue(any("contract_override" in d for d in sel.decisions))

    def test_precedence_chain_is_frozen(self):
        sel = select_rule_set(contract_date="2026-01-01")
        self.assertEqual(list(sel.precedence_chain), ["Contract", "Tender", "Regional", "Standard"])

    def test_audit_chain_is_preserved(self):
        sel = select_rule_set(contract_date="2026-03-01")
        self.assertTrue(sel.decisions, "判定链必须留痕")
        self.assertTrue(sel.legal_basis)


if __name__ == "__main__":
    unittest.main()
