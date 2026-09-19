"""H-003 固定/隐形成本模型分列声明（HC-*）测试。

主线（ADR-0013 分档）：隐形成本**未声明** = WARN（利润解释力受限，报告层须标注
「清单贡献利润」——算式仍可算，只是口径不完整）；**声明了 DECLARED 却缺算式前提**
（载体/基数/费率/金额/桶归属）= BLOCKED（算式算错）；**说了但说错了**（词表外、
费率越界、桶合计与构成不符）= FAIL。
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
from bidpricing.validation.hidden_cost import (
    ALLOCATION_BASIS_VOCABULARY,
    COLUMN_MODE_VOCABULARY,
    check_hidden_cost_policy,
)

CONFIG = Path(__file__).resolve().parents[1] / "config"

_FIXED = {
    "mode": "FIXED_CURRENT_VALUES",
    "measure_fee": 15853.12,
    "regulatory_fee": 6528.62,
    "fixed_pretax": 22381.74,
}


def _policy(hidden: dict | None = None,
            fixed_pretax: dict | None = None,
            *,
            has_fixed_pretax: bool = True) -> dict:
    policy: dict = {}
    if has_fixed_pretax:
        policy["fixed_pretax_policy"] = fixed_pretax or dict(_FIXED)
    if hidden is not None:
        policy["hidden_cost_policy"] = hidden
    return policy


def _unknown_all() -> dict:
    return {
        "direct": {"mode": "UNKNOWN", "carrier": None},
        "allocable": {"mode": "UNKNOWN", "basis": None, "rate": None},
        "project_fixed": {"mode": "UNKNOWN", "amount": None,
                          "enters_fixed_pretax": None},
    }


def _declared_all() -> dict:
    return {
        "direct": {"mode": "DECLARED", "carrier": "COST_LISTING_ITEM_ENTRIES"},
        "allocable": {"mode": "DECLARED", "basis": "LABOR", "rate": 0.05},
        "project_fixed": {"mode": "DECLARED", "amount": 3000.0,
                          "enters_fixed_pretax": False},
    }


class RealRepoTest(unittest.TestCase):
    def test_undeclared_is_warn_not_block(self):
        """真实仓库当前三类均 UNKNOWN → WARN（不阻断计算），结构 PASS。"""
        rep = check_hidden_cost_policy(CONFIG)
        self.assertEqual(rep.by_rule("HC-01").status, STATUS_PASS)
        self.assertEqual(rep.by_rule("HC-02").status, STATUS_PASS)
        self.assertEqual(rep.by_rule("HC-03").status, STATUS_WARN)
        self.assertEqual(rep.by_rule("HC-04").status, STATUS_WARN)
        self.assertEqual(rep.by_rule("HC-05").status, STATUS_WARN)
        self.assertEqual(rep.by_rule("HC-06").status, STATUS_SKIP)
        # 隐形成本未声明不阻断计算（区别于 CT-* 的 BLOCKED）：利润按清单贡献口径解释
        self.assertEqual(rep.status, "PASS")
        self.assertEqual(rep.blocking, [])
        self.assertIn("H-003", rep.by_rule("HC-01").detail)

    def test_vocabularies(self):
        self.assertEqual(COLUMN_MODE_VOCABULARY, ("NONE", "DECLARED", "UNKNOWN"))
        self.assertIn("DIRECT", ALLOCATION_BASIS_VOCABULARY)
        self.assertNotIn("FIXED_PROJECT", ALLOCATION_BASIS_VOCABULARY)


class SyntheticCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cdir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _write(self, policy: dict):
        (self.cdir / "project_quote_policy.json").write_text(
            json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    # ---- HC-01 声明节存在性 ----
    def test_missing_policy_skips(self):
        self._write({})  # 无 project_quote_policy.json
        (self.cdir / "project_quote_policy.json").unlink()
        rep = check_hidden_cost_policy(self.cdir)
        self.assertEqual(rep.by_rule("HC-01").status, STATUS_SKIP)

    def test_missing_section_is_warn(self):
        self._write(_policy(hidden=None))
        rep = check_hidden_cost_policy(self.cdir)
        self.assertEqual(rep.by_rule("HC-01").status, STATUS_WARN)
        self.assertIn("未纳入成本的风险", rep.by_rule("HC-01").detail)

    # ---- HC-02 分列结构 ----
    def test_missing_column_is_fail(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "NONE"},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-02").status, STATUS_FAIL)

    def test_all_columns_present_passes(self):
        rep = check_hidden_cost_policy(CONFIG)
        self.assertEqual(rep.by_rule("HC-02").status, STATUS_PASS)

    # ---- HC-03 可直接归属 ----
    def test_direct_declared_missing_carrier_blocks(self):
        self._write(_policy(hidden={
            "direct": {"mode": "DECLARED"},
            "allocable": {"mode": "NONE"},
            "project_fixed": {"mode": "NONE"},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-03").status, STATUS_BLOCKED)

    def test_direct_declared_with_carrier_passes(self):
        self._write(_policy(hidden={
            "direct": {"mode": "DECLARED", "carrier": "COST_LISTING_ITEM_ENTRIES"},
            "allocable": {"mode": "NONE"},
            "project_fixed": {"mode": "NONE"},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-03").status, STATUS_PASS)

    def test_direct_none_passes(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "NONE"},
            "project_fixed": {"mode": "NONE"},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-03").status, STATUS_PASS)

    def test_direct_mode_out_of_vocab_is_fail(self):
        self._write(_policy(hidden={
            "direct": {"mode": "HALF"},
            "allocable": {"mode": "NONE"},
            "project_fixed": {"mode": "NONE"},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-03").status, STATUS_FAIL)

    # ---- HC-04 可分摊 ----
    def test_allocable_declared_missing_basis_blocks(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "DECLARED", "rate": 0.05},
            "project_fixed": {"mode": "NONE"},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-04").status, STATUS_BLOCKED)

    def test_allocable_declared_basis_out_of_vocab_is_fail(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "DECLARED", "basis": "FIXED_PROJECT",
                          "rate": 0.05},
            "project_fixed": {"mode": "NONE"},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-04").status, STATUS_FAIL)

    def test_allocable_declared_missing_rate_blocks(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "DECLARED", "basis": "LABOR"},
            "project_fixed": {"mode": "NONE"},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-04").status, STATUS_BLOCKED)

    def test_allocable_declared_rate_out_of_range_is_fail(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "DECLARED", "basis": "LABOR", "rate": 1.5},
            "project_fixed": {"mode": "NONE"},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-04").status, STATUS_FAIL)

    def test_allocable_declared_complete_passes(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "DECLARED", "basis": "DIRECT_COST", "rate": 0.03},
            "project_fixed": {"mode": "NONE"},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-04").status, STATUS_PASS)

    # ---- HC-05 项目固定 ----
    def test_project_fixed_declared_missing_amount_blocks(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "NONE"},
            "project_fixed": {"mode": "DECLARED", "enters_fixed_pretax": False},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-05").status, STATUS_BLOCKED)

    def test_project_fixed_declared_missing_enters_blocks(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "NONE"},
            "project_fixed": {"mode": "DECLARED", "amount": 3000.0},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-05").status, STATUS_BLOCKED)
        self.assertIn("FIXED_PRETAX", check_hidden_cost_policy(self.cdir)
                      .by_rule("HC-05").detail)

    def test_project_fixed_negative_amount_is_fail(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "NONE"},
            "project_fixed": {"mode": "DECLARED", "amount": -1.0,
                              "enters_fixed_pretax": False},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-05").status, STATUS_FAIL)

    def test_project_fixed_enters_not_bool_is_fail(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "NONE"},
            "project_fixed": {"mode": "DECLARED", "amount": 3000.0,
                              "enters_fixed_pretax": "yes"},
        }))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-05").status, STATUS_FAIL)

    def test_project_fixed_profit_only_passes(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "NONE"},
            "project_fixed": {"mode": "DECLARED", "amount": 3000.0,
                              "enters_fixed_pretax": False},
        }))
        rep = check_hidden_cost_policy(self.cdir)
        self.assertEqual(rep.by_rule("HC-05").status, STATUS_PASS)
        self.assertIn("只影响利润", rep.by_rule("HC-05").detail)

    # ---- HC-06 桶联动（影响总竞争预算的可追溯）----
    def test_enters_bucket_consistent_passes(self):
        fp = dict(_FIXED)
        fp["fixed_pretax"] = 25381.74  # 22381.74 + 3000.00
        self._write(_policy(
            hidden={
                "direct": {"mode": "NONE"},
                "allocable": {"mode": "NONE"},
                "project_fixed": {"mode": "DECLARED", "amount": 3000.0,
                                  "enters_fixed_pretax": True},
            },
            fixed_pretax=fp,
        ))
        rep = check_hidden_cost_policy(self.cdir)
        self.assertEqual(rep.by_rule("HC-06").status, STATUS_PASS)
        self.assertEqual(rep.status, "PASS")

    def test_enters_bucket_inconsistent_is_fail(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "NONE"},
            "project_fixed": {"mode": "DECLARED", "amount": 3000.0,
                              "enters_fixed_pretax": True},
        }))  # fixed_pretax 仍是 22381.74，未含 3000
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-06").status, STATUS_FAIL)

    def test_enters_bucket_missing_fixed_policy_skips(self):
        self._write(_policy(hidden={
            "direct": {"mode": "NONE"},
            "allocable": {"mode": "NONE"},
            "project_fixed": {"mode": "DECLARED", "amount": 3000.0,
                              "enters_fixed_pretax": True},
        }, has_fixed_pretax=False))
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-06").status, STATUS_SKIP)

    def test_profit_only_no_bucket_check_skips(self):
        self._write(_policy(hidden=_declared_all()))  # enters_fixed_pretax=False
        self.assertEqual(check_hidden_cost_policy(self.cdir)
                         .by_rule("HC-06").status, STATUS_SKIP)

    # ---- 全量声明通过 ----
    def test_all_declared_passes(self):
        self._write(_policy(hidden=_declared_all()))
        rep = check_hidden_cost_policy(self.cdir)
        self.assertEqual(rep.status, "PASS")
        self.assertEqual(rep.blocking, [])

    def test_partial_unknown_is_warn_but_passes(self):
        self._write(_policy(hidden=_unknown_all()))
        rep = check_hidden_cost_policy(self.cdir)
        self.assertEqual(rep.status, "PASS")
        self.assertEqual(
            [r.status for r in rep.results].count(STATUS_WARN), 3)


if __name__ == "__main__":
    unittest.main()
