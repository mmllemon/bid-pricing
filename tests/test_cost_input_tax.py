"""H-002 成本含税 → 有效成本转换声明（CT-*）测试。

主线：**进项税率/抵扣模式缺失 = BLOCKED（阻断『最优利润』结论）**——
这是 H-002 的验收标准，与 AS-01 的 INFO 降级（台账不是关卡）不同：
这里缺的是**算式前提**，缺了利润就**算错**，不是「说不清出处」。
"""

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.validation.cost_basis import (
    CREDIT_MODE_VOCABULARY,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    check_cost_input_tax,
    effective_cost,
    effective_cost_multiplier,
)

CONFIG = Path(__file__).resolve().parents[1] / "config"


def _policy(**mut) -> dict:
    sec = {
        "mode": "UNKNOWN",
        "cost_input_vat_rate": None,
        "input_vat_credit_mode": "UNKNOWN",
        "credit_ratio": None,
    }
    sec.update(mut)
    return {"cost_input_tax_policy": sec}


class MultiplierTest(unittest.TestCase):
    def test_full_is_incl_over_one_plus_rate(self):
        k = effective_cost_multiplier(0.09, "FULL")
        self.assertAlmostEqual(k, 1.0 / 1.09)

    def test_none_keeps_incl_cost_without_rate(self):
        # NONE 不需要税率：含税即有效成本
        self.assertEqual(effective_cost_multiplier(None, "NONE"), 1.0)

    def test_partial_uses_credit_ratio(self):
        k = effective_cost_multiplier(0.09, "PARTIAL", 0.5)
        self.assertAlmostEqual(k, 1.0 - 0.09 * 0.5 / 1.09)

    def test_unknown_returns_none(self):
        self.assertIsNone(effective_cost_multiplier(None, "UNKNOWN"))

    def test_invalid_mode_is_program_error(self):
        with self.assertRaises(ValueError):
            effective_cost_multiplier(0.09, "HALF")

    def test_missing_rate_or_ratio_returns_none(self):
        self.assertIsNone(effective_cost_multiplier(None, "FULL"))
        self.assertIsNone(effective_cost_multiplier(0.09, "PARTIAL"))

    def test_effective_cost_rounds_to_cents(self):
        self.assertAlmostEqual(effective_cost(109.0, 0.09, "FULL"), 100.0)
        self.assertIsNone(effective_cost(None, 0.09, "FULL"))
        self.assertIsNone(effective_cost(109.0, 0.09, "PARTIAL"))  # 比例缺失


class RealRepoTest(unittest.TestCase):
    def test_undeclared_blocks_profit_conclusion(self):
        """真实仓库当前未声明进项税率/抵扣模式 → CT-03 BLOCKED（H-002）。"""
        rep = check_cost_input_tax(CONFIG)
        self.assertEqual(rep.by_rule("CT-03").status, STATUS_BLOCKED)
        self.assertIn("H-002", rep.by_rule("CT-03").detail)
        self.assertEqual(rep.status, "BLOCKED")
        self.assertTrue(rep.blocking)

    def test_mechanism_passes_and_pending_is_skip_not_fail(self):
        rep = check_cost_input_tax(CONFIG)
        self.assertEqual(rep.by_rule("CT-01").status, STATUS_PASS)
        self.assertEqual(rep.by_rule("CT-02").status, STATUS_SKIP)  # 模式未定，率挂起
        self.assertEqual(rep.by_rule("CT-04").status, STATUS_SKIP)
        self.assertEqual(rep.by_rule("CT-05").status, STATUS_SKIP)


class SyntheticCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cdir = Path(self.tmp.name)
        self._write()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, **mut):
        (self.cdir / "project_quote_policy.json").write_text(
            json.dumps(_policy(**mut), ensure_ascii=False), encoding="utf-8")

    def test_full_declared_passes(self):
        self._write(mode="FULL", cost_input_vat_rate=0.09,
                    input_vat_credit_mode="FULL")
        rep = check_cost_input_tax(self.cdir)
        self.assertEqual(rep.status, "PASS")
        self.assertEqual(rep.blocking, [])

    def test_full_missing_rate_blocks(self):
        self._write(mode="FULL", input_vat_credit_mode="FULL")
        rep = check_cost_input_tax(self.cdir)
        self.assertEqual(rep.by_rule("CT-02").status, STATUS_BLOCKED)
        self.assertEqual(rep.by_rule("CT-05").status, STATUS_BLOCKED)

    def test_partial_missing_ratio_blocks(self):
        self._write(mode="PARTIAL", cost_input_vat_rate=0.09,
                    input_vat_credit_mode="PARTIAL")
        self.assertEqual(check_cost_input_tax(self.cdir)
                         .by_rule("CT-04").status, STATUS_BLOCKED)

    def test_none_mode_no_rate_required(self):
        self._write(mode="NONE", input_vat_credit_mode="NONE")
        rep = check_cost_input_tax(self.cdir)
        self.assertEqual(rep.status, "PASS")

    def test_rate_out_of_range_is_fail(self):
        self._write(mode="FULL", cost_input_vat_rate=1.5,
                    input_vat_credit_mode="FULL")
        self.assertEqual(check_cost_input_tax(self.cdir)
                         .by_rule("CT-02").status, STATUS_FAIL)

    def test_mode_out_of_vocabulary_is_fail(self):
        self._write(mode="FULL", cost_input_vat_rate=0.09,
                    input_vat_credit_mode="HALF")
        self.assertEqual(check_cost_input_tax(self.cdir)
                         .by_rule("CT-03").status, STATUS_FAIL)

    def test_missing_policy_skips(self):
        (self.cdir / "project_quote_policy.json").unlink()
        rep = check_cost_input_tax(self.cdir)
        self.assertEqual(rep.by_rule("CT-01").status, STATUS_SKIP)


if __name__ == "__main__":
    unittest.main()
