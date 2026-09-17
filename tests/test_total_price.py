"""T00-06B 总价分解与 P_competitive 联动函数的验收用例。

两类锚点分开：
* **真实样本**（西永L分区限价/报价配对）——断言值取自源工作簿实测数字，
  用来验证「实现符合一份已发生的数据」；
* **合成算例**——用来暴露**真实样本无法区分**的缺陷（本样本暂列金额与
  甲供材料费均为 0，故「甲供材当加项」「重复计暂列」这类错误在真实数据上
  数值不可观测）。合成算例的立场是「让判据可被错误的值否定」。
"""

from __future__ import annotations

import unittest

from bidpricing.money import money
from bidpricing.paths import repo_root
from bidpricing.states import Status
from bidpricing.total_price import (
    COMPETITIVE,
    DISCLOSURE_PROVISIONAL,
    FIXED_PRETAX,
    TAX,
    Partition,
    Term,
    TotalPriceError,
    check_partition,
    check_tax_base_document,
    check_tax_response,
    compute_P_competitive,
    compute_tax,
    load_fixture,
    partition_from_fixture,
    tax_basis_text_from_fixture,
    total_from_competitive,
)

FIXTURE = repo_root() / "tests" / "data" / "xiyong_l_district" / "pair.json"

# 真实样本表-04 报价侧实测值（勿改成"重算出来的值"）
BID_TOTAL = 1_416_251.85
BID_TAX = 129_685.85
BID_VAT = 115_790.94
BID_SURTAX = 13_894.91
BID_DIVISION = 1_264_184.26
BID_PRETAX = 1_286_566.00


def synth(
    competitive: float = 1_000_000.0,
    measures: float = 20_000.0,
    other: float = 50_000.0,
    provisional: float = 30_000.0,
    fees: float = 6_000.0,
    supplied: float = 0.0,
    vat: float = 0.09,
    sur: float = 0.12,
    declared_total: float | None = None,
) -> Partition:
    """合成划分。``other`` **已含** ``provisional``（它就是「其中：」列）。"""
    terms = [
        Term("T-DIVISION", "分部分项工程费", competitive, COMPETITIVE,
             source_list="BOQ"),
        Term("T-MEASURE", "措施项目费", measures, FIXED_PRETAX,
             source_list="TECH_MEASURE"),
        Term("T-OTHER", "其他项目费", other, FIXED_PRETAX, source_list="OTHER",
             disclosure={DISCLOSURE_PROVISIONAL: provisional}),
        Term("T-FEE", "规费", fees, FIXED_PRETAX, source_list="FEE_TAX"),
    ]
    part = Partition(terms=terms, vat_rate=vat, surtax_rate=sur,
                     supplied_material=supplied)
    terms.append(Term("T-TAX", "税金", part.tax, TAX, source_list="FEE_TAX",
                      in_tax_base=False))
    part.declared_total = part.total if declared_total is None else declared_total
    return part


def status_of(items, rule: str) -> Status:
    hits = [i for i in items if i.item == rule]
    assert hits, f"未产生判据 {rule}"
    return hits[0].status


class RealSampleTest(unittest.TestCase):
    """真实样本：总价链条必须与源工作簿逐项一致。"""

    @classmethod
    def setUpClass(cls):
        cls.fx = load_fixture(FIXTURE)

    def test_bid_partition_closes_on_stated_total(self):
        part = partition_from_fixture(self.fx, "bid")
        items = check_partition(part, part.declared_total)
        for it in items:
            self.assertEqual(it.status, Status.PASS, f"{it.item}: {it.reason}")

    def test_decomposition_matches_table_04(self):
        part = partition_from_fixture(self.fx, "bid")
        self.assertEqual(part.competitive, BID_DIVISION)
        self.assertEqual(part.pre_tax, BID_PRETAX)
        self.assertEqual(part.tax, BID_TAX)
        self.assertEqual(part.total, BID_TOTAL)

    def test_tax_decomposes_into_vat_and_surtax(self):
        part = partition_from_fixture(self.fx, "bid")
        vat, sur, tax = compute_tax(part.tax_base, part.vat_rate, part.surtax_rate)
        self.assertEqual((vat, sur), (BID_VAT, BID_SURTAX))
        self.assertEqual(tax, BID_TAX)

    def test_tax_matches_table_anchor(self):
        """外部锚点：重算税金必须等于表-12 列示金额。

        这条同时是「甲供材缺失按 0」这一假设的反证——若实际甲供材不为 0，
        重算税金会小于表列值，此处即失败。
        """
        part = partition_from_fixture(self.fx, "bid")
        rows = {r["item_name"]: r for r in self.fx["fee_and_tax"]["bid"]}
        self.assertEqual(part.tax, float(rows["税金"]["amount"]))
        self.assertEqual(part.total, float(self.fx["summary_table_04"]["bid"]["合计"]))

    def test_P_competitive_round_trips_to_locked_total(self):
        """C1 右端由本函数提供；用它正算必须回到锁定的总价。"""
        part = partition_from_fixture(self.fx, "bid")
        c = compute_P_competitive(
            part.declared_total, part.fixed_pretax, part.vat_rate,
            part.surtax_rate, part.supplied_material,
        )
        self.assertAlmostEqual(c, BID_DIVISION, delta=0.05)
        self.assertEqual(
            total_from_competitive(
                c, part.fixed_pretax, part.vat_rate, part.surtax_rate,
                part.supplied_material,
            ),
            BID_TOTAL,
        )

    def test_five_price_levels_reproduce_by_hand(self):
        part = partition_from_fixture(self.fx, "bid")
        items = check_tax_response(part)
        for it in items:
            self.assertEqual(it.status, Status.PASS, it.reason)

    def test_tax_base_text_is_taken_from_tender_document(self):
        text = tax_basis_text_from_fixture(self.fx, "bid")
        self.assertEqual(
            check_tax_base_document(text).status, Status.PASS, text
        )

    def test_cap_side_is_refused_not_read_as_zero(self):
        """限价侧表-04 的「分部分项工程费」为空（ADR-0005 实证）。

        空 ≠ 0：读成 0 会造出「可竞争部分为零」的假划分。
        """
        with self.assertRaises(TotalPriceError) as ctx:
            partition_from_fixture(self.fx, "cap")
        self.assertIn("分部分项工程费", str(ctx.exception))
        self.assertIn("ADR-0005", str(ctx.exception))


class SuppliedMaterialTest(unittest.TestCase):
    """甲供材料费：只减计税基数，不进总价划分（路线 ①/② 原式在此处须更正）。"""

    def test_closed_form_matches_reference_formula(self):
        part = synth(supplied=200_000.0)
        c = compute_P_competitive(
            part.declared_total, part.fixed_pretax, part.vat_rate,
            part.surtax_rate, part.supplied_material,
        )
        k = part.vat_rate * (1 + part.surtax_rate)
        reference = (part.declared_total + 200_000.0 * k) / (1 + k) - part.fixed_pretax
        self.assertAlmostEqual(c, reference, delta=0.5)

    def test_ignoring_supplied_material_is_detectable(self):
        """把甲供材漏掉会差多少——差值必须远大于 0.01 元容差，否则判据无区分度。"""
        part = synth(supplied=200_000.0)
        wrong = compute_P_competitive(
            part.declared_total, part.fixed_pretax, part.vat_rate,
            part.surtax_rate, 0.0,
        )
        right = compute_P_competitive(
            part.declared_total, part.fixed_pretax, part.vat_rate,
            part.surtax_rate, part.supplied_material,
        )
        self.assertGreater(abs(wrong - right), 0.01)
        # 漏掉甲供材 ⇒ 税基被高估 ⇒ 反解出的可竞争部分偏小
        self.assertLess(wrong, right)

    def test_supplied_material_is_not_an_addend(self):
        part = synth(supplied=200_000.0)
        part.terms.append(
            Term("T-SUPPLIED", "甲供材料费", 200_000.0, FIXED_PRETAX)
        )
        items = check_partition(part, part.declared_total)
        self.assertEqual(status_of(items, "TP-02"), Status.FAIL)
        self.assertIn("甲供材料费", "".join(str(i.actual) for i in items if i.item == "TP-02"))

    def test_total_has_no_supplied_material_addend(self):
        """甲供材不是总价加项——它只经税基影响总价（实测恒等式口径）。

        正确陈述有三条，缺一不可：
        ① 税前合计不受甲供材影响；
        ② 总价 = 税前合计 + 税金，**没有第四项**；
        ③ 总价之差 == 税金之差（差异全部来自税基）。
        """
        a = synth(supplied=0.0)
        b = synth(supplied=200_000.0)
        self.assertEqual(a.pre_tax, b.pre_tax)                       # ①
        self.assertEqual(b.total, money(b.pre_tax + b.tax))          # ②
        self.assertEqual(money(a.total - b.total), money(a.tax - b.tax))  # ③
        self.assertNotEqual(a.total, b.total)


class DoubleCountTest(unittest.TestCase):
    """暂列金额：披露列活在父项金额内部，重复计必须被抓住。"""

    def test_disclosure_is_inside_parent_not_extra_addend(self):
        part = synth()
        self.assertEqual(part.provisional, 30_000.0)
        # 父项金额里已经含它：总价不会因为披露而增加
        self.assertEqual(part.fixed_pretax, 20_000.0 + 50_000.0 + 6_000.0)

    def test_extra_addend_breaks_closure(self):
        part = synth()
        part.terms.append(Term("T-PROV", "暂列金额", 30_000.0, FIXED_PRETAX))
        items = check_partition(part, part.declared_total)
        self.assertEqual(status_of(items, "TP-03"), Status.FAIL)
        tp03 = [i for i in items if i.item == "TP-03"][0]
        self.assertAlmostEqual(tp03.actual["delta"], 30_000.0, delta=0.01)

    def test_disclosure_exceeding_parent_is_rejected(self):
        part = synth(other=50_000.0, provisional=60_000.0)
        items = check_partition(part, part.declared_total)
        self.assertEqual(status_of(items, "TP-02"), Status.FAIL)

    def test_negative_disclosure_is_rejected(self):
        part = synth(provisional=-1.0)
        items = check_partition(part, part.declared_total)
        self.assertEqual(status_of(items, "TP-02"), Status.FAIL)

    def test_duplicate_term_id_is_rejected(self):
        part = synth()
        part.terms.append(Term("T-FEE", "规费（重复）", 1.0, FIXED_PRETAX))
        items = check_partition(part, part.declared_total)
        self.assertEqual(status_of(items, "TP-02"), Status.FAIL)

    def test_multiple_tax_rows_are_rejected(self):
        part = synth()
        part.terms.append(Term("T-TAX-2", "税金（第二行）", 0.0, TAX))
        items = check_partition(part, part.declared_total)
        self.assertEqual(status_of(items, "TP-02"), Status.FAIL)


class StructureTest(unittest.TestCase):
    """TP-01 / TP-04：取值域与计税基数自洽。"""

    def test_unknown_bucket_is_fail(self):
        part = synth()
        part.terms.append(Term("T-X", "未知项", 1.0, "SOMETHING_ELSE"))
        self.assertEqual(status_of(check_partition(part, part.declared_total), "TP-01"),
                         Status.FAIL)

    def test_unknown_disclosure_key_is_fail(self):
        part = synth()
        part.terms.append(
            Term("T-Y", "其他", 10.0, FIXED_PRETAX, disclosure={"其中:瞎写": 1.0})
        )
        self.assertEqual(status_of(check_partition(part, part.declared_total), "TP-01"),
                         Status.FAIL)

    def test_in_tax_base_flag_must_be_consistent(self):
        """把规费标成不进税基 → 与「税前合计−甲供材」口径矛盾 → TP-04 FAIL。"""
        part = synth()
        part.terms[3] = Term("T-FEE", "规费", 6_000.0, FIXED_PRETAX,
                             source_list="FEE_TAX", in_tax_base=False)
        self.assertEqual(status_of(check_partition(part, part.declared_total), "TP-04"),
                         Status.FAIL)

    def test_clean_partition_reports_all_rules(self):
        part = synth()
        ids = {i.item for i in check_partition(part, part.declared_total)}
        self.assertEqual(ids, {"TP-01", "TP-02", "TP-03", "TP-04", "TP-05"})


class TaxResponseTest(unittest.TestCase):
    """TP-06：税金随报价联动——这是「五组报价」测试的存在理由。"""

    def test_tax_is_constant_under_reallocation_but_not_under_rescaling(self):
        part = synth()
        # 报价水平变化 ⇒ 税金变化
        t_base = compute_tax(part.tax_base, part.vat_rate, part.surtax_rate)[2]
        t_up = compute_tax(money(part.tax_base * 1.2), part.vat_rate,
                           part.surtax_rate)[2]
        self.assertNotEqual(t_base, t_up)
        # 总价锁定下怎么分配不影响税金：税金只依赖可竞争部分之和
        same = synth(competitive=500_000.0, measures=20_000.0,
                     other=50_000.0, provisional=30_000.0, fees=6_000.0)
        explicitly = synth(competitive=500_000.0, measures=20_000.0,
                           other=50_000.0, provisional=30_000.0, fees=6_000.0)
        self.assertEqual(same.tax, explicitly.tax)

    def test_five_levels_hand_calculated(self):
        part = synth(competitive=1_000_000.0, supplied=150_000.0)
        base = part.competitive
        for k in (1.0, 1.1, 0.9, 1.2, 0.8):
            pre = money(base * k + part.fixed_pretax)
            vat = money((pre - part.supplied_material) * part.vat_rate)
            sur = money(vat * part.surtax_rate)
            expected = money(pre + vat + sur)
            got = total_from_competitive(
                base * k, part.fixed_pretax, part.vat_rate,
                part.surtax_rate, part.supplied_material,
            )
            self.assertEqual(got, expected, f"level {k}")

    def test_constant_tax_implementation_is_discriminating(self):
        """把税金当固定值搬进总价，在 +20% 报价下偏差必须可观测。

        这就是路线要求五组报价而非一组报价的原因：只在控制价上测，
        两种实现给出同一个数。
        """
        part = synth(competitive=1_000_000.0, supplied=150_000.0)
        k = 1.2
        pre = money(part.competitive * k + part.fixed_pretax)
        constant_tax_total = money(pre + part.tax)          # 错误实现
        formula_total = total_from_competitive(
            part.competitive * k, part.fixed_pretax, part.vat_rate,
            part.surtax_rate, part.supplied_material,
        )
        self.assertGreater(abs(constant_tax_total - formula_total), 0.01)
        # 只在控制价（k=1）上，两种实现一致 —— 故一组报价测不出缺陷
        self.assertEqual(
            money(part.competitive + part.fixed_pretax + part.tax), part.total
        )

    def test_check_tax_response_passes_on_clean_partition(self):
        for it in check_tax_response(synth()):
            self.assertEqual(it.status, Status.PASS, it.reason)

    def test_tax_response_reports_rows_for_audit(self):
        items = check_tax_response(synth())
        rows = [i for i in items if i.actual and isinstance(i.actual, list)][0].actual
        self.assertEqual([r["level"] for r in rows], [1.0, 1.1, 0.9, 1.2, 0.8])


class TaxBaseDocumentTest(unittest.TestCase):
    """TP-07：税基以招标文件原文为准，不先归一化再比对。"""

    REAL = "分部分项工程费+措施项目费+其他项目费+规费-甲供材料费"

    def test_real_text_passes(self):
        self.assertEqual(check_tax_base_document(self.REAL).status, Status.PASS)

    def test_whitespace_is_tolerated(self):
        padded = " 分部分项工程费 + 措施项目费 + 其他项目费 + 规费 - 甲供材料费 "
        self.assertEqual(check_tax_base_document(padded).status, Status.PASS)

    def test_empty_text_is_fail_not_defaulted(self):
        self.assertEqual(check_tax_base_document("").status, Status.FAIL)
        self.assertEqual(check_tax_base_document("   ").status, Status.FAIL)

    def test_missing_addend_is_fail(self):
        text = "分部分项工程费+措施项目费+其他项目费-甲供材料费"  # 丢规费
        item = check_tax_base_document(text)
        self.assertEqual(item.status, Status.FAIL)
        self.assertIn("规费", str(item.actual["missing"]))

    def test_missing_supplied_material_deduction_is_fail(self):
        text = "分部分项工程费+措施项目费+其他项目费+规费"
        self.assertEqual(check_tax_base_document(text).status, Status.FAIL)


class RoundingOrderTest(unittest.TestCase):
    """舍入口径：分项先舍、汇总再舍一次；附加税以舍入后的增值税为基数。"""

    def test_surtax_uses_rounded_vat(self):
        # 基数额刻意使增值税落在半厘上
        base = 1_111_111.11
        vat = money(base * 0.09)
        self.assertEqual(compute_tax(base, 0.09, 0.12)[0], vat)
        self.assertEqual(compute_tax(base, 0.09, 0.12)[1], money(vat * 0.12))

    def test_missing_rate_raises(self):
        with self.assertRaises(TotalPriceError):
            compute_tax(1000.0, None, 0.12)

    def test_negative_fixed_part_is_rejected(self):
        with self.assertRaises(TotalPriceError):
            compute_P_competitive(1000.0, -1.0, 0.09, 0.12)


if __name__ == "__main__":
    unittest.main()
