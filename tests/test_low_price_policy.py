"""H-004 低价确认与废标风险留痕声明（LC-*）+ 运行时确认记录构造测试。

主线（ADR-0013 分档 + H-004 验收）：条款依据**未登记** = WARN（闸门仍生效，
结果注明『以招标文件为准』）；声明**已登记却内容为空** = BLOCKED（留痕不可追溯）；
**说了但说错了**（判定边界词表外、阈值越界/不一致、mode=NONE 冲突、字段契约不全）
= FAIL；运行时确认记录缺用户/时间/条款依据 → **标注 trace_gaps，不伪造不阻断**。
"""

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.validation.cost_basis import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
)
from bidpricing.validation.low_price_policy import (
    DISPOSITION_CONFIRM_ONLY,
    DISPOSITION_NOTE,
    DISPOSITION_VOCABULARY,
    MODE_VOCABULARY,
    REQUIRED_CONFIRMATION_FIELDS,
    LowPricePolicyError,
    build_low_price_confirmation,
    check_low_price_policy,
)

CONFIG = Path(__file__).resolve().parents[1] / "config"

_CLAUSE = {
    "enabled": True,
    "reference": "CAP",
    "tol_lo": 0.5,
    "tol_hi": 0.5,
    "mechanism": "SETTLEMENT_ADJUSTMENT",
}

_FULL_LOW = {
    "mode": "DECLARED",
    "low_price_threshold": 0.5,
    "disposition": "CONFIRM_ONLY",
    "clause_basis": "招标文件第三章 2.4 条：报价低于最高限价50%须澄清",
    "confirmation_fields": ["confirmed_by", "confirmed_at", "clause_basis"],
}


def _policy(low: dict | None = None,
            clause: dict | None = None,
            *,
            has_clause: bool = True) -> dict:
    policy: dict = {}
    if has_clause:
        policy["unbalanced_clause"] = clause or dict(_CLAUSE)
    if low is not None:
        policy["low_price_policy"] = low
    return policy


class RealRepoTest(unittest.TestCase):
    def test_real_repo_undeclared_basis_is_warn_not_block(self):
        """真实仓库：条款依据 UNKNOWN → LC-04 WARN；整体 PASS（不阻断）。"""
        rep = check_low_price_policy(CONFIG)
        self.assertEqual(rep.by_rule("LC-01").status, STATUS_PASS)
        self.assertEqual(rep.by_rule("LC-02").status, STATUS_PASS)
        self.assertEqual(rep.by_rule("LC-03").status, STATUS_PASS)
        self.assertEqual(rep.by_rule("LC-04").status, STATUS_WARN)
        self.assertEqual(rep.by_rule("LC-05").status, STATUS_PASS)
        # 留痕未登记只 WARN，不阻断计算（区别于算式前提缺失的 BLOCKED）
        self.assertEqual(rep.status, "PASS")
        self.assertEqual(rep.blocking, [])
        self.assertIn("H-004", rep.by_rule("LC-01").detail)

    def test_vocabularies(self):
        self.assertEqual(DISPOSITION_VOCABULARY, ("CONFIRM_ONLY",))
        self.assertEqual(REQUIRED_CONFIRMATION_FIELDS,
                         ("confirmed_by", "confirmed_at", "clause_basis"))
        self.assertIn("UNKNOWN", MODE_VOCABULARY)


class SyntheticCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cdir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _write(self, policy: dict):
        (self.cdir / "project_quote_policy.json").write_text(
            json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    # ---- LC-01 声明节存在性 ----
    def test_missing_policy_skips(self):
        self._write({})
        (self.cdir / "project_quote_policy.json").unlink()
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-01").status, STATUS_SKIP)

    def test_missing_clause_skips(self):
        self._write(_policy(low=_FULL_LOW, has_clause=False))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-01").status, STATUS_SKIP)

    def test_missing_section_is_warn(self):
        self._write(_policy(low=None))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-01").status, STATUS_WARN)

    # ---- LC-02 判定边界 ----
    def test_disposition_missing_is_warn(self):
        low = dict(_FULL_LOW)
        del low["disposition"]
        self._write(_policy(low=low))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-02").status, STATUS_WARN)

    def test_disposition_out_of_vocab_is_fail(self):
        low = dict(_FULL_LOW, disposition="SYSTEM_DISQUALIFIES")
        self._write(_policy(low=low))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-02").status, STATUS_FAIL)

    def test_disposition_confirm_only_passes(self):
        self._write(_policy(low=_FULL_LOW))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-02").status, STATUS_PASS)

    # ---- LC-03 低价阈值 ----
    def test_threshold_missing_is_warn(self):
        low = dict(_FULL_LOW)
        del low["low_price_threshold"]
        self._write(_policy(low=low))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-03").status, STATUS_WARN)

    def test_threshold_out_of_range_is_fail(self):
        self._write(_policy(low=dict(_FULL_LOW, low_price_threshold=1.5)))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-03").status, STATUS_FAIL)

    def test_threshold_zero_is_fail(self):
        self._write(_policy(low=dict(_FULL_LOW, low_price_threshold=0.0)))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-03").status, STATUS_FAIL)

    def test_threshold_consistent_with_tol_lo_passes(self):
        self._write(_policy(low=_FULL_LOW))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-03").status, STATUS_PASS)

    def test_threshold_inconsistent_with_tol_lo_is_fail(self):
        self._write(_policy(low=dict(_FULL_LOW, low_price_threshold=0.45)))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-03").status, STATUS_FAIL)

    def test_non_settlement_mechanism_skips_consistency(self):
        self._write(_policy(
            low=_FULL_LOW,
            clause=dict(_CLAUSE, mechanism="BID_VALIDITY")))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-03").status, STATUS_SKIP)

    # ---- LC-04 条款依据 ----
    def test_basis_declared_missing_blocks(self):
        low = dict(_FULL_LOW, clause_basis=None)
        self._write(_policy(low=low))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-04").status, STATUS_BLOCKED)

    def test_basis_declared_present_passes(self):
        self._write(_policy(low=_FULL_LOW))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-04").status, STATUS_PASS)

    def test_basis_unknown_is_warn(self):
        low = dict(_FULL_LOW, mode="UNKNOWN", clause_basis=None)
        self._write(_policy(low=low))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-04").status, STATUS_WARN)

    def test_mode_none_with_enabled_clause_is_fail(self):
        low = dict(_FULL_LOW, mode="NONE")
        self._write(_policy(low=low))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-04").status, STATUS_FAIL)

    def test_mode_out_of_vocab_is_fail(self):
        low = dict(_FULL_LOW, mode="MAYBE")
        self._write(_policy(low=low))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-04").status, STATUS_FAIL)

    # ---- LC-05 字段契约 ----
    def test_fields_missing_is_warn(self):
        low = dict(_FULL_LOW)
        del low["confirmation_fields"]
        self._write(_policy(low=low))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-05").status, STATUS_WARN)

    def test_fields_incomplete_is_fail(self):
        low = dict(_FULL_LOW, confirmation_fields=["confirmed_by"])
        self._write(_policy(low=low))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-05").status, STATUS_FAIL)

    def test_fields_complete_passes(self):
        self._write(_policy(low=_FULL_LOW))
        self.assertEqual(check_low_price_policy(self.cdir)
                         .by_rule("LC-05").status, STATUS_PASS)

    # ---- 全量声明通过 ----
    def test_all_declared_passes(self):
        self._write(_policy(low=_FULL_LOW))
        rep = check_low_price_policy(self.cdir)
        self.assertEqual(rep.status, "PASS")
        self.assertEqual(rep.blocking, [])


class ConfirmationRecordTest(unittest.TestCase):
    def test_confirmed_with_full_trace(self):
        rec = build_low_price_confirmation(
            confirmed=True, threshold=0.5, has_low_items=True,
            confirmed_by="张三", confirmed_at="2026-09-19T15:00:00+08:00",
            clause_basis="招标文件第三章 2.4 条")
        self.assertTrue(rec["confirmed"])
        self.assertFalse(rec["review_required"])
        self.assertEqual(rec["confirmed_by"], "张三")
        self.assertEqual(rec["disposition"], DISPOSITION_CONFIRM_ONLY)
        self.assertEqual(rec["trace_gaps"], [])
        self.assertIn("以招标文件为准", rec["disposition_note"])

    def test_not_confirmed_with_low_items_requires_review(self):
        rec = build_low_price_confirmation(
            confirmed=False, threshold=0.5, has_low_items=True)
        self.assertTrue(rec["review_required"])
        self.assertFalse(rec["confirmed"])

    def test_no_low_items_no_review_required(self):
        rec = build_low_price_confirmation(
            confirmed=False, threshold=0.5, has_low_items=False)
        self.assertFalse(rec["review_required"])

    def test_confirmed_missing_user_marks_trace_gap(self):
        rec = build_low_price_confirmation(
            confirmed=True, threshold=0.5, has_low_items=True,
            confirmed_at="2026-09-19T15:00:00+08:00", clause_basis="某条款")
        self.assertTrue(any("未记录确认人" in g for g in rec["trace_gaps"]))
        self.assertIsNone(rec["confirmed_by"])  # 不伪造确认人

    def test_confirmed_missing_basis_marks_trace_gap(self):
        rec = build_low_price_confirmation(
            confirmed=True, threshold=0.5, has_low_items=True,
            confirmed_by="张三", confirmed_at="2026-09-19T15:00:00+08:00",
            clause_basis=None)
        self.assertTrue(any("条款依据未登记" in g for g in rec["trace_gaps"]))

    def test_invalid_threshold_raises(self):
        with self.assertRaises(LowPricePolicyError):
            build_low_price_confirmation(
                confirmed=True, threshold=1.5, has_low_items=False)

    def test_non_bool_confirmed_raises(self):
        with self.assertRaises(LowPricePolicyError):
            build_low_price_confirmation(
                confirmed="yes", threshold=0.5, has_low_items=False)

    def test_disposition_note_never_judges(self):
        self.assertIn("不作出废标判定", DISPOSITION_NOTE)
        self.assertIn("以招标文件为准", DISPOSITION_NOTE)


if __name__ == "__main__":
    unittest.main()
