"""T00-12 利润口径桥接表的验收用例。

重点在三处**失效模式**，它们都不是「算错」而是「口径错层」：

1. **算税前、报含税**——目标层级不唯一或差额项缺失时，PB-02/PB-03 必须报错；
2. **同源不同值**——桥接表与 T00-06B 的总价分解对不上时，PB-03 必须失败；
3. **空真通过**——没给划分就跳过数值对账时，判据必须是 SKIP 而**不是 PASS**
   （否则「没检查」会被读成「检查过且通过」）。
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bidpricing.paths import config_dir, repo_root
from bidpricing.total_price import load_fixture, partition_from_fixture
from bidpricing.validation.cost_basis import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_INFO,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
)
from bidpricing.validation.profit_bridge import (
    LEVEL_KINDS,
    LOSS_POLICY_VOCABULARY,
    check_profit_bridge,
)

FIXTURE = repo_root() / "tests" / "data" / "xiyong_l_district" / "pair.json"
SPEC = "profit_bridge_spec.json"
BASIS = "basis_declarations.json"


class BridgeCase(unittest.TestCase):
    """公共夹具：把真实制品复制到临时 config 目录，再按需改一处。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for fname in (SPEC, BASIS):
            shutil.copyfile(config_dir() / fname, self.tmp / fname)
        self._reset_freeze()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _reset_freeze(self):
        """**合成基线必须显式设定**：真实制品已冻结，若照抄会让
        「未冻结 → WARN」这类断言随项目进度翻转而失败——那样测的是
        「项目当前状态」而不是「判据行为」（本轮 q1 侧已踩过一次）。"""
        d = json.loads((self.tmp / SPEC).read_text(encoding="utf-8"))
        d.pop("frozen_at", None)
        d.pop("frozen_by", None)
        (self.tmp / SPEC).write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    def spec(self) -> dict:
        return json.loads((self.tmp / SPEC).read_text(encoding="utf-8"))

    def write_spec(self, spec: dict):
        (self.tmp / SPEC).write_text(
            json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    def mutate(self, fn):
        d = self.spec()
        fn(d)
        self.write_spec(d)

    def run_check(self, partition=None):
        return check_profit_bridge(self.tmp, partition=partition)

    def status(self, rule: str, partition=None) -> str:
        return self.run_check(partition).by_rule(rule).status


class RealRepoTest(unittest.TestCase):
    """真实仓库：桥接表自身必须无阻断，且与真实样本数值对账通过。"""

    @classmethod
    def setUpClass(cls):
        fx = load_fixture(FIXTURE)
        cls.partition = partition_from_fixture(fx, "bid")

    def test_real_spec_is_consistent(self):
        rep = check_profit_bridge(config_dir(), partition=self.partition)
        self.assertEqual(rep.blocking, [], [r.detail for r in rep.blocking])

    def test_real_spec_passes_core_rules(self):
        rep = check_profit_bridge(config_dir(), partition=self.partition)
        for rule in ("PB-01", "PB-02", "PB-03", "PB-04", "PB-05"):
            self.assertEqual(rep.by_rule(rule).status, STATUS_PASS,
                             rep.by_rule(rule).detail)

    def test_numeric_reconciliation_uses_real_partition(self):
        rep = check_profit_bridge(config_dir(), partition=self.partition)
        detail = rep.by_rule("PB-03").detail
        self.assertIn("同源同值", detail)
        self.assertIn("残差 0.0000", detail)

    def test_level_kind_vocabulary_is_closed(self):
        spec = json.loads((config_dir() / SPEC).read_text(encoding="utf-8"))
        for lv in spec["levels"]:
            self.assertIn(lv["kind"], LEVEL_KINDS)


class EmptyTruthTest(unittest.TestCase):
    """最危险的一类通过：没检查被读成检查过。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for fname in (SPEC, BASIS):
            shutil.copyfile(config_dir() / fname, self.tmp / fname)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_missing_partition_is_skip_not_pass(self):
        rep = check_profit_bridge(self.tmp, partition=None)
        self.assertEqual(rep.by_rule("PB-03").status, STATUS_SKIP)
        self.assertIn("不视为通过", rep.by_rule("PB-03").detail)

    def test_missing_spec_is_skip_not_pass(self):
        (self.tmp / SPEC).unlink()
        rep = check_profit_bridge(self.tmp)
        self.assertEqual(rep.by_rule("PB-01").status, STATUS_SKIP)
        self.assertEqual(rep.status, "PASS")  # SKIP 不阻断，但记录在案
        self.assertIn("T00-12 未冻结", rep.by_rule("PB-01").detail)


class ObjectiveUniquenessTest(BridgeCase):
    """PB-02：目标函数必须恰好一个，且两处说法一致。"""

    def test_two_objective_rows_is_blocked(self):
        def mut(d):
            for lv in d["levels"]:
                if lv["key"] == "Z_REPORTED":
                    lv["is_objective"] = True
        self.mutate(mut)
        self.assertEqual(self.status("PB-02"), STATUS_BLOCKED)

    def test_objective_level_mismatch_is_blocked(self):
        self.mutate(lambda d: d["objective"].__setitem__("level", "Z_REPORTED"))
        r = self.run_check().by_rule("PB-02")
        self.assertEqual(r.status, STATUS_BLOCKED)
        self.assertIn("各说各话", r.detail)

    def test_objective_kind_without_flag_is_blocked(self):
        """漏标 is_objective 会让目标静默变成派生量——必须报错而不是默认 false。"""
        def mut(d):
            for lv in d["levels"]:
                if lv["key"] == "Z_OBJECTIVE":
                    lv["is_objective"] = False
        self.mutate(mut)
        r = self.run_check().by_rule("PB-02")
        self.assertEqual(r.status, STATUS_BLOCKED)
        self.assertIn("Z_OBJECTIVE", r.detail)

    def test_operand_set_must_match_flags(self):
        """多标一个常数项进目标 = 把外生常量当决策项。"""
        def mut(d):
            for lv in d["levels"]:
                if lv["key"] == "TAX":
                    lv["enters_objective"] = True
        self.mutate(mut)
        r = self.run_check().by_rule("PB-02")
        self.assertEqual(r.status, STATUS_BLOCKED)
        self.assertIn("参与目标函数", r.detail)

    def test_missing_operand_is_blocked(self):
        self.mutate(lambda d: d["objective"]["operands"].remove("C_SETTLEMENT"))
        self.assertEqual(self.status("PB-02"), STATUS_BLOCKED)

    def test_bad_sense_is_blocked(self):
        self.mutate(lambda d: d["objective"].__setitem__("sense", "max"))
        self.assertEqual(self.status("PB-02"), STATUS_BLOCKED)


class SameSourceTest(BridgeCase):
    """PB-03：与 T00-06B 同源同值。"""

    def test_missing_identity_is_fail(self):
        def mut(d):
            d["identities"] = [i for i in d["identities"] if i["id"] != "B2"]
        self.mutate(mut)
        r = self.run_check().by_rule("PB-03")
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertIn("B2", str(r.evidence))

    def test_empty_difference_terms_is_fail(self):
        """差额项为空 = 「算税前、报含税」这个失效模式失去显式化。"""
        self.mutate(lambda d: d["reported_vs_objective"].__setitem__(
            "difference_terms", []))
        r = self.run_check().by_rule("PB-03")
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertIn("算税前", r.detail)

    def test_difference_term_referencing_unknown_level_is_fail(self):
        self.mutate(lambda d: d["reported_vs_objective"]["difference_terms"].append("VAT_EXTRA"))
        r = self.run_check().by_rule("PB-03")
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertIn("未声明层级", r.detail)

    def test_partition_that_breaks_identity_is_fail(self):
        """造一个 B1 不成立的划分：多出一行税金，但总价没跟着变。"""
        from bidpricing.total_price import TAX, Term

        part = partition_from_fixture(load_fixture(FIXTURE), "bid")
        part.terms.append(Term("T-X", "多出来的项", 123.45, TAX))
        r = self.run_check(partition=part).by_rule("PB-03")
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertIn("不符", r.detail)


class TaxCaliberTest(BridgeCase):
    """PB-04：目标口径与既有税口径声明必须一致。"""

    def test_incl_vat_caliber_is_fail(self):
        self.mutate(lambda d: d.__setitem__("tax_caliber_of_objective", "INCL_VAT"))
        self.assertEqual(self.status("PB-04"), STATUS_FAIL)

    def test_missing_caliber_is_blocked(self):
        self.mutate(lambda d: d.pop("tax_caliber_of_objective"))
        self.assertEqual(self.status("PB-04"), STATUS_BLOCKED)

    def test_undeclared_basis_side_is_blocked(self):
        """未定态 = key 完全缺失，不得用默认值填。"""
        basis = json.loads((self.tmp / BASIS).read_text(encoding="utf-8"))
        basis.pop("cost_tax_scope")
        (self.tmp / BASIS).write_text(json.dumps(basis, ensure_ascii=False),
                                      encoding="utf-8")
        r = self.run_check().by_rule("PB-04")
        self.assertEqual(r.status, STATUS_BLOCKED)
        self.assertIn("cost_tax_scope", r.detail)

    def test_conflicting_basis_side_is_fail(self):
        basis = json.loads((self.tmp / BASIS).read_text(encoding="utf-8"))
        basis["cost_tax_scope"] = "INCL_VAT"
        (self.tmp / BASIS).write_text(json.dumps(basis, ensure_ascii=False),
                                      encoding="utf-8")
        self.assertEqual(self.status("PB-04"), STATUS_FAIL)


class LossPolicyTest(BridgeCase):
    """PB-05：单项亏损政策未声明则可行域无定义。"""

    def test_missing_policy_is_blocked(self):
        self.mutate(lambda d: d.pop("single_item_loss_policy"))
        self.assertEqual(self.status("PB-05"), STATUS_BLOCKED)

    def test_out_of_vocabulary_is_fail(self):
        self.mutate(lambda d: d["single_item_loss_policy"].__setitem__(
            "declared", "WHATEVER"))
        self.assertEqual(self.status("PB-05"), STATUS_FAIL)

    def test_declared_without_basis_is_warn(self):
        self.mutate(lambda d: d["single_item_loss_policy"].pop("basis"))
        self.assertEqual(self.status("PB-05"), STATUS_WARN)

    def test_total_profit_only_is_the_declared_value(self):
        spec = self.spec()
        self.assertEqual(spec["single_item_loss_policy"]["declared"],
                         "TOTAL_PROFIT_ONLY")
        self.assertIn("TOTAL_PROFIT_ONLY", LOSS_POLICY_VOCABULARY)


class LevelFieldTest(BridgeCase):
    """PB-01：层级行的字段齐备与取值域。"""

    def test_missing_field_is_fail(self):
        def mut(d):
            d["levels"][0].pop("source_of_truth")
        self.mutate(mut)
        r = self.run_check().by_rule("PB-01")
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertIn("source_of_truth", r.detail)

    def test_bad_kind_is_fail(self):
        self.mutate(lambda d: d["levels"][0].__setitem__("kind", "WHATEVER"))
        self.assertEqual(self.status("PB-01"), STATUS_FAIL)

    def test_string_flag_is_fail(self):
        """字符串 "true" 在这一层必须被拒绝——它读起来像真值但不是。"""
        self.mutate(lambda d: d["levels"][0].__setitem__("enters_objective", "true"))
        self.assertEqual(self.status("PB-01"), STATUS_FAIL)

    def test_duplicate_key_is_fail(self):
        def mut(d):
            d["levels"].append(dict(d["levels"][0]))
        self.mutate(mut)
        r = self.run_check().by_rule("PB-01")
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertIn("重复", r.detail)


class FreezeTest(BridgeCase):
    def test_unfrozen_is_warn_and_frozen_passes(self):
        self.assertEqual(self.status("PB-06"), STATUS_WARN)
        self.mutate(lambda d: d.__setitem__("frozen_at", "2026-09-17"))
        self.assertEqual(self.status("PB-06"), STATUS_PASS)


class OpenItemsTest(BridgeCase):
    def test_open_items_are_info_not_blocking(self):
        rep = self.run_check()
        info = [r for r in rep.results if r.status == STATUS_INFO]
        self.assertTrue(info)
        self.assertEqual(rep.blocking, [])


class ObjectiveCaliberCrossLayerTest(BridgeCase):
    """PB-07：目标口径「声明（报告层）↔ 实现（求解层）」跨层对账（ADR-0035）。

    为什么不是冗余判据：PB-04 只判**声明自身**自洽（spec ↔ basis_declarations）。
    声明说 EXCL_VAT、而求解层偷偷把收入折算成含税，PB-04 依然全绿。PB-07 是唯一
    把两层具名量拉到一起的判据——它对应的是「同约束多层各判 ⇒ 须跨层对账」。
    """

    def test_real_repo_passes(self):
        self.assertEqual(self.status("PB-07"), STATUS_PASS)

    def test_declared_caliber_mismatch_with_implementation_is_fail(self):
        self.mutate(lambda d: d.__setitem__("tax_caliber_of_objective", "INCL_VAT"))
        self.assertEqual(self.status("PB-07"), STATUS_FAIL)

    def test_missing_declared_caliber_skips_not_passes(self):
        # 声明缺失时 PB-04 阻断；PB-07 挂起——同一缺失不报两次，且绝不记 PASS
        self.mutate(lambda d: d.pop("tax_caliber_of_objective", None))
        self.assertEqual(self.status("PB-04"), STATUS_BLOCKED)
        self.assertEqual(self.status("PB-07"), STATUS_SKIP)

    def test_implementation_caliber_mismatch_is_fail(self):
        from bidpricing.solver import settlement_milp as sm
        with mock.patch.object(sm, "OBJECTIVE_CALIBER", "INCL_VAT"):
            self.assertEqual(self.status("PB-07"), STATUS_FAIL)

    def test_grossed_revenue_is_caught(self):
        """★ 对 ADR-0035 的真实缺陷有区分度：常量标 EXCL_VAT 但收入侧仍乘 (1+v)。"""
        from bidpricing.solver import settlement_milp as sm
        with mock.patch.object(sm, "objective_revenue_factor",
                               lambda v: 1.0 + float(v)):
            self.assertEqual(self.status("PB-07"), STATUS_FAIL)

    def test_unprobeable_implementation_is_blocked(self):
        from bidpricing.solver import settlement_milp as sm
        with mock.patch.object(sm, "objective_revenue_factor",
                               mock.Mock(side_effect=RuntimeError("no impl"))):
            self.assertEqual(self.status("PB-07"), STATUS_BLOCKED)


if __name__ == "__main__":
    unittest.main()
