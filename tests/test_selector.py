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
        """§7.1.1 断言 1：未定态 = key 完全缺失，而非 '未定' 字符串。

        显式关闭项目落值文件：该用例断言的是"未选择"这一状态本身，
        不得受开发者本机 config/project_selection.json 的内容影响。
        """
        sel = select_rule_set(contract_date="2026-03-01", use_project_selection=False)
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
            contract_override="GB50500-2013", contract_date="2024-03-01",
            use_project_selection=False,
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

    def test_2013_with_full_scope_declaration_is_conflict(self):
        """2013 下 adjustment_scope 非可选项：落值 FULL 是配置冲突，不再静默覆盖。

        静默覆盖会让"系统的建议值"与"人工落值"的差异从审计链上消失，
        因此改为显式 BLOCKED 并给出合法取值集合。
        """
        sel = select_rule_set(
            contract_override="GB50500-2013",
            contract_date="2024-03-01",
            adjustment_scope_declared="FULL",
            use_project_selection=False,
        )
        self.assertIs(sel.status, Status.BLOCKED)
        self.assertIsNone(sel.adjustment_scope)
        self.assertNotIn("adjustment_scope", sel.to_dict())
        self.assertTrue(any("不可选" in b for b in sel.blockers), sel.blockers)

    def test_2013_with_segment_declaration_is_consistent(self):
        sel = select_rule_set(
            contract_override="GB50500-2013",
            contract_date="2024-03-01",
            adjustment_scope_declared="SEGMENT",
            use_project_selection=False,
        )
        self.assertIs(sel.status, Status.PASS)
        self.assertEqual(sel.adjustment_scope, "SEGMENT")

    def test_2013_scope_source_is_rule_set_not_operator(self):
        """2013 的口径由规范明文确定，来源必须与"人工选择"区分。"""
        sel = select_rule_set(
            contract_override="GB50500-2013", contract_date="2024-03-01",
            use_project_selection=False,
        )
        self.assertEqual(sel.adjustment_scope_source, "RULE_SET_DETERMINED")
        self.assertEqual(
            sel.to_dict()["adjustment_scope_source"], "RULE_SET_DETERMINED"
        )

    def test_stale_selection_file_for_other_rule_set_is_flagged(self):
        """落值记录属于另一个规则集时不得被沿用（防止口径错配）。"""
        import json as _json
        import tempfile as _tempfile
        from pathlib import Path as _Path

        with _tempfile.TemporaryDirectory() as tmp:
            path = _Path(tmp) / "sel.json"
            path.write_text(
                _json.dumps(
                    {"options": {"adjustment_scope": {
                        "value": "FULL", "rule_set_id": "GB/T50500-2024"}}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            sel = select_rule_set(
                contract_override="GB50500-2013", contract_date="2024-03-01",
                selection_file=path,
            )
            self.assertIs(sel.status, Status.BLOCKED)
            self.assertTrue(any("不匹配" in b for b in sel.blockers), sel.blockers)


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
