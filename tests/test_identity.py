"""真实样本（西永L分区限价/报价配对）与总价恒等式的验收用例。

这些用例的立场与其它测试不同：它们**不是在验证我的实现符合我的设计**，
而是在验证设计**符合一份真实的、已经发生的招标—投标数据**。
因此断言值全部取自源工作簿的实测数字，不取自我推导的公式。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from bidpricing.identity import (
    Totals,
    check_component_sum,
    check_identity,
    decompose,
    eps_total,
    load_pair_fixture,
    rates_from_fixture,
    stated_from_fixture,
    totals_from_fixture,
)
from bidpricing.paths import repo_root
from bidpricing.states import Status

FIXTURE = repo_root() / "tests" / "data" / "xiyong_l_district" / "pair.json"

# ---- 源工作簿实测值（勿改成"重算出来的值"，否则用例失去外部锚点） ----
STATED_DIVISION = 1264184.26
STATED_DIVISION_C = 1256580.19
STATED_DIVISION_B3 = 7604.07
STATED_MEASURES = 15853.12
STATED_FEES = 6528.62
STATED_VAT = 115790.94
STATED_SURTAX = 13894.91
STATED_TAX = 129685.85
STATED_TOTAL = 1416251.85
STATED_CAP_SUM = 1374238.77
STATED_SAFETY_FEE = 7834.06


def _fx() -> dict:
    if not FIXTURE.exists():
        raise unittest.SkipTest(f"真实样本不存在：{FIXTURE}")
    return load_pair_fixture(FIXTURE)


class FixtureIntegrityTest(unittest.TestCase):
    """样本本身的结构事实——解析器将来要满足的就是这些。"""

    def test_item_count_and_unique_key(self):
        items = _fx()["items"]
        self.assertEqual(len(items), 81)
        codes = [i["item_id"] for i in items]
        self.assertEqual(len(set(codes)), 81, "编码在单位工程内必须唯一")

    def test_two_sections_with_seq_restarting(self):
        """序号在分节内各自从 1 重算 —— 这是"不得用序号作主键"的实证。"""
        items = _fx()["items"]
        by_sec: dict[str, list[int]] = {}
        for i in items:
            by_sec.setdefault(i["section"], []).append(i["seq_in_section"])
        self.assertEqual(set(by_sec), {"安装工程", "准备运行费"})
        self.assertEqual(len(by_sec["安装工程"]), 52)
        self.assertEqual(len(by_sec["准备运行费"]), 29)
        for sec, seqs in by_sec.items():
            self.assertEqual(min(seqs), 1, f"{sec} 应从 1 开始")
            self.assertEqual(max(seqs), len(seqs), f"{sec} 序号应连续")

    def test_code_length_distribution(self):
        """12 位 67 条 + 6 位 14 条，无 13/15 位。"""
        codes = [i["item_id"] for i in _fx()["items"]]
        lengths: dict[int, int] = {}
        for c in codes:
            lengths[len(c)] = lengths.get(len(c), 0) + 1
        self.assertEqual(lengths, {12: 67, 6: 14})

    def test_supplementary_codes_are_the_6_digit_ones(self):
        sup = sorted(i["item_id"] for i in _fx()["items"] if len(i["item_id"]) == 6)
        self.assertEqual(sup, [f"03B{n:03d}" for n in range(1, 15)])

    def test_groups_by_unit_and_multi_unit(self):
        items = _fx()["items"]
        counts: dict[str, int] = {}
        for i in items:
            counts[i["unit"]] = counts.get(i["unit"], 0) + 1
        self.assertEqual(counts["台"], 26)
        self.assertEqual(counts["块"], 20)
        self.assertEqual(sum(counts.values()), 81)

    def test_no_provisional_price_recorded(self):
        """「其中:暂估价」列在两份文件里都是空的——这是数据事实，不是缺陷。"""
        self.assertTrue(all(i["provisional_price"] is None for i in _fx()["items"]))


class LineSumFaithfulnessTest(unittest.TestCase):
    """逐项明细求和 == 表列小计。对不上说明解析漏行或重复计入。"""

    def test_bid_amount_sums_to_table_04_division(self):
        items = _fx()["items"]
        got = round(sum(i["amount_bid"] for i in items if i["amount_bid"]), 2)
        self.assertAlmostEqual(got, STATED_DIVISION, places=2)

    def test_bid_amount_splits_match_table_04_subitems(self):
        items = _fx()["items"]
        c = round(sum(i["amount_bid"] for i in items if i["section"] == "安装工程"), 2)
        b3 = round(sum(i["amount_bid"] for i in items if i["section"] == "准备运行费"), 2)
        self.assertAlmostEqual(c, STATED_DIVISION_C, places=2)
        self.assertAlmostEqual(b3, STATED_DIVISION_B3, places=2)

    def test_cap_unit_price_times_quantity(self):
        items = _fx()["items"]
        got = round(sum(i["p_cap"] * i["q0"] for i in items if i["p_cap"]), 2)
        self.assertAlmostEqual(got, STATED_CAP_SUM, places=2)

    def test_component_sum_judge_passes_on_real_data(self):
        item = check_component_sum(
            {"分部分项": STATED_DIVISION}, STATED_DIVISION, "分部分项工程费"
        )
        self.assertIs(item.status, Status.PASS)


class IdentityClosureTest(unittest.TestCase):
    """总价恒等式在真实样本上必须闭合。"""

    def setUp(self):
        self.fx = _fx()
        self.totals = totals_from_fixture(self.fx, "bid")
        vat, sur = rates_from_fixture(self.fx, "bid")
        self.dec = decompose(self.totals, vat, sur)
        self.stated = stated_from_fixture(self.fx, "bid")

    def test_rates_read_from_data_not_hardcoded(self):
        vat, sur = rates_from_fixture(self.fx, "bid")
        self.assertAlmostEqual(vat, 0.09, places=10)
        self.assertAlmostEqual(sur, 0.12, places=10)

    def test_taxable_base_excludes_supplied_material_only(self):
        t = Totals(division=100.0, measures=10.0, other=5.0, fees=2.0, supplied_material=7.0)
        self.assertAlmostEqual(t.pre_tax, 117.0, places=10)
        self.assertAlmostEqual(t.taxable_base, 110.0, places=10)

    def test_vat_equals_base_times_rate(self):
        self.assertAlmostEqual(self.dec.vat, STATED_VAT, places=2)

    def test_surtax_equals_vat_times_rate(self):
        self.assertAlmostEqual(self.dec.surtax, STATED_SURTAX, places=2)

    def test_tax_total(self):
        self.assertAlmostEqual(self.dec.tax, STATED_TAX, places=2)

    def test_grand_total_exact(self):
        self.assertAlmostEqual(self.dec.total, STATED_TOTAL, places=2)

    def test_all_identity_checks_pass_with_zero_residual(self):
        items = check_identity(
            self.dec, self.stated["总价"], self.stated["增值税"], self.stated["税金"]
        )
        self.assertEqual([i.status for i in items], [Status.PASS] * 3)
        for i in items:
            self.assertEqual(i.delta, 0.0, f"{i.item} 残差应为 0，实测 {i.delta}")

    def test_identity_fails_when_base_is_perturbed(self):
        """反向用例：把分部分项抬高 1 元，总价判据必须 FAIL。

        这条比正向用例更重要——正向用例能通过可能只是因为容差太宽。
        """
        bad = Totals(
            division=self.totals.division + 1.0,
            measures=self.totals.measures,
            other=self.totals.other,
            fees=self.totals.fees,
        )
        vat, sur = rates_from_fixture(self.fx, "bid")
        dec = decompose(bad, vat, sur)
        items = check_identity(
            dec, self.stated["总价"], self.stated["增值税"], self.stated["税金"]
        )
        self.assertTrue(all(i.status is Status.FAIL for i in items))


class NonCompetitiveConstantTest(unittest.TestCase):
    """D3 建模口径的实测背书：安全文明施工费在两份文件里是**同一个值**。"""

    def test_safety_fee_identical_in_cap_and_bid(self):
        fx = _fx()
        cap = {r["item_name"]: r for r in fx["measures_org_cap"]}
        bid = {r["item_name"]: r for r in fx["measures_org_bid"]}
        name = "安全文明施工费"
        cap_amt = float(cap[name]["amount"])
        bid_amt = float(bid[name]["amount"])
        self.assertAlmostEqual(cap_amt, STATED_SAFETY_FEE, places=2)
        self.assertAlmostEqual(bid_amt, STATED_SAFETY_FEE, places=2)
        self.assertEqual(cap_amt, bid_amt, "投标人未改动不可竞争费")

    def test_competitive_measure_items_are_unpriced_in_cap(self):
        """限价侧未给出组织措施费/竣档费金额，报价侧给出了——它们是可竞争的。"""
        fx = _fx()
        cap = {r["item_name"]: r for r in fx["measures_org_cap"]}
        bid = {r["item_name"]: r for r in fx["measures_org_bid"]}
        for name in ("组织措施费", "建设工程竣工档案编制费"):
            self.assertIsNone(cap[name]["amount"], f"{name} 限价侧应为空")
            self.assertIsNotNone(bid[name]["amount"], f"{name} 报价侧应有值")


class EpsPolicyTest(unittest.TestCase):
    def test_eps_total_is_abs_floor_for_this_project(self):
        """总价 1.4e6 × eps_price(1e-9) ≈ 1.4e-3 < eps_abs(0.01) → 取 0.01。"""
        self.assertAlmostEqual(eps_total(STATED_TOTAL), 0.01, places=10)

    def test_eps_total_grows_with_total(self):
        self.assertGreater(eps_total(1e9), eps_total(1e6))


class RatesAreMandatoryTest(unittest.TestCase):
    def test_missing_rate_raises(self):
        """税率是项目级外生数据，不得有默认值。"""
        t = Totals(division=100.0)
        with self.assertRaises(ValueError):
            decompose(t, None, 0.12)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            decompose(t, 0.09, None)  # type: ignore[arg-type]


class ClosureIsNotCompletenessTest(unittest.TestCase):
    """**恒等式闭合 ≠ 数据完整** —— 本样本自带的真实反例。

    限价文件的表-04/表-12 内部**完全自洽**：分部分项=0、规费=0，
    于是 7,834.06 × 9% = 705.07、税金 789.68、合计 8,623.74，残差为 0。
    可它逐项单价合计其实是 1,374,238.77 元。

    因此恒等式**不能**用来判断"数据是否齐备"——它只能判断
    "已声明的分项之间是否自洽"。若把闭合当作完整性证据，
    一个漏了大部分分项的汇总表会顺利通过全部检查。
    """

    def test_cap_side_closes_despite_missing_division(self):
        fx = _fx()
        dec = decompose(totals_from_fixture(fx, "cap"), *rates_from_fixture(fx, "cap"))
        stated = stated_from_fixture(fx, "cap")
        items = check_identity(
            dec, stated["总价"], stated["增值税"], stated["税金"]
        )
        self.assertEqual([i.status for i in items], [Status.PASS] * 3,
                         "限价侧内部自洽，判据应当全部通过")

    def test_but_cap_side_division_is_zero_while_items_sum_nonzero(self):
        """自洽的表-04 里分部分项为 0，而逐项单价合计 1,374,238.77。"""
        fx = _fx()
        self.assertEqual(float(fx["summary_table_04"]["cap"]["分部分项工程费"] or 0), 0.0)
        item_sum = round(sum(i["p_cap"] * i["q0"] for i in fx["items"] if i["p_cap"]), 2)
        self.assertAlmostEqual(item_sum, STATED_CAP_SUM, places=2)
        self.assertGreater(item_sum, 1_000_000)

    def test_its_total_must_not_be_read_as_the_control_price(self):
        """限价文件合计 8,623.74 元不是该项目的招标控制价。"""
        fx = _fx()
        self.assertAlmostEqual(float(fx["summary_table_04"]["cap"]["合计"]), 8623.74, places=2)


class FixtureIsSelfDescribingTest(unittest.TestCase):
    def test_provenance_file_present(self):
        self.assertTrue((FIXTURE.parent / "PROVENANCE.md").exists())

    def test_fixture_records_source_paths(self):
        src = _fx()["source"]
        self.assertIn("中标限价", src["cap_file"])
        self.assertIn("报价", src["bid_file"])

    def test_column_map_documents_price_column_name_drift(self):
        """限价文件把单价列叫「最高限价」，报价文件叫「综合单价」——解析器必须做别名。"""
        cm = _fx()["column_map"]["分部分项(表-09)"]
        self.assertIn("最高限价", cm["G"])

    def test_json_roundtrip(self):
        p = Path(FIXTURE)
        self.assertEqual(json.loads(p.read_text(encoding="utf-8")), _fx())


if __name__ == "__main__":
    unittest.main()
