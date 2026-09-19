"""T01-03 规范化清洗的测试（stdlib unittest，零第三方依赖）。

覆盖：数值归一（千分位/全角/空白）、编码标准化（**不做位数补零**——D1）、
cap 空值语义（不限价，**禁止按 cap=0**——2026-09-16 用户裁定）、
C5 零价信号、透传信号、数值解析失败进报告不猜、精度归一。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.io.boq import ParsedRow
from bidpricing.io.clean import (
    _normalize_code,
    _to_number,
    clean_listing_rows,
)


def _row(**over) -> ParsedRow:
    base = dict(
        project_id="P1", unit_work="电气设备安装工程", item_id="030404017001",
        code_kind="STANDARD", item_name="配电箱", item_feature=" 型号 XX ",
        unit=" 台 ", quantity=" 1,234.567891 ", unit_price="１,２３４．５６",
        amount="", temporary_valuation="", source_sheet="表-09",
        source_row=5, source_table_no="表-09",
    )
    base.update(over)
    return ParsedRow(**base)


class NumericNormalizeTest(unittest.TestCase):
    def test_thousands_and_spaces(self):
        v, err = _to_number(" 1,234.567891 ")
        self.assertIsNone(err)
        self.assertAlmostEqual(v, 1234.567891)

    def test_fullwidth(self):
        v, err = _to_number("１,２３４．５")
        self.assertIsNone(err)
        self.assertAlmostEqual(v, 1234.5)

    def test_empty_is_none_not_zero(self):
        v, err = _to_number("   ")
        self.assertIsNone(v)
        self.assertIsNone(err)          # 空 = 缺测/语义，不是 0

    def test_garbage_reports_not_guesses(self):
        v, err = _to_number("12..34")
        self.assertIsNone(v)
        self.assertIn("无法解析", err)


class CodeNormalizeTest(unittest.TestCase):
    def test_fullwidth_and_case(self):
        self.assertEqual(_normalize_code(" ０３Ｂ００１ "), "03B001")

    def test_no_zero_padding(self):
        """D1：位数不参与合法性判定——补零等于改主键，禁止。"""
        self.assertEqual(_normalize_code("03B001"), "03B001")
        self.assertNotEqual(_normalize_code("03B001"), "00000003B001")


class CleanListingTest(unittest.TestCase):
    def test_cap_side_types_and_flags(self):
        rows, rep = clean_listing_rows([_row()], "cap")
        self.assertEqual(rep.n_rows_out, 1)
        r = rows[0]
        self.assertAlmostEqual(r.q0, 1234.567891)
        self.assertAlmostEqual(r.cap, 1234.56)
        self.assertIs(r.q1_point, None)
        self.assertIs(r.c_i, None)
        self.assertFalse(r.no_cap)
        self.assertEqual(r.unit, "台")           # 全角/空白归一
        self.assertEqual(r.item_feature, "型号 XX")

    def test_empty_cap_means_no_cap_not_zero(self):
        """★ 2026-09-16 裁定：cap 空 = 不限价但不得为 0。"""
        rows, rep = clean_listing_rows([_row(item_id="031301017001", unit_price="")], "cap")
        self.assertTrue(rows[0].no_cap)
        self.assertIsNone(rows[0].cap)           # 绝不是 0
        self.assertIn("031301017001", rep.no_cap_items)

    def test_cost_side_maps_q1_and_c(self):
        rows, _ = clean_listing_rows([_row(quantity="2", unit_price="980.5")], "cost")
        r = rows[0]
        self.assertAlmostEqual(r.q1_point, 2.0)
        self.assertAlmostEqual(r.c_i, 980.5)
        self.assertIsNone(r.q0)
        self.assertIsNone(r.cap)
        self.assertFalse(r.no_cap)

    def test_zero_price_flag(self):
        rows, rep = clean_listing_rows([_row(unit_price="0")], "cap")
        self.assertTrue(rows[0].zero_price)
        self.assertEqual(len(rep.zero_price_items), 1)

    def test_pass_through_signal(self):
        rows, rep = clean_listing_rows([_row(temporary_valuation="500")], "cap")
        self.assertTrue(rows[0].pass_through)
        self.assertEqual(rep.pass_through_items, ["030404017001"])

    def test_numeric_error_kept_in_report(self):
        rows, rep = clean_listing_rows([_row(quantity="abc")], "cap")
        self.assertIsNone(rows[0].q0)            # 不猜
        self.assertEqual(len(rep.numeric_errors), 1)
        self.assertEqual(rep.numeric_errors[0]["column"], "quantity")

    def test_invalid_side_rejected(self):
        with self.assertRaises(ValueError):
            clean_listing_rows([], "bid")

    def test_real_file_smoke(self):
        """真实文件冒烟：83 行全通过（含限价独有 no_cap 项 03B015），脚手架搭拆 cap 空 → no_cap。"""
        src = Path(r"d:/Lee-proj/TRAE/bid-pricing-build/真实案件示例/中标限价/"
                   "西永L分区公立学校（暂定名）一期工程等项目配电工程.xlsx")
        if not src.exists():
            self.skipTest("真实样本文件不在本机")
        from bidpricing.io.boq import parse_listing
        report = parse_listing(str(src), "XIYONG-L")
        rows, rep = clean_listing_rows(report.rows, "cap")
        self.assertEqual(rep.n_rows_out, 83)
        self.assertEqual(len(rep.numeric_errors), 0)
        self.assertIn("031301017001", rep.no_cap_items)
        self.assertIn("03B015", rep.no_cap_items)
        scaffold = next(r for r in rows if r.item_id == "031301017001")
        self.assertTrue(scaffold.no_cap)
        self.assertIsNone(scaffold.cap)


class CanonicalSchemaArtifactTest(unittest.TestCase):
    """canonical_schema 制品：结构完整、字段集与 CleanRow 对齐。"""

    def test_artifact_structure(self):
        p = Path(__file__).resolve().parents[1] / "config" / "canonical_schema.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(d["row_key"], "(project_id, unit_work, item_id)")
        names = {f["name"] for f in d["fields"]}
        required = {"project_id", "unit_work", "item_id", "code_kind", "item_name",
                    "item_feature", "unit", "q0", "q1_point", "cap", "c_i",
                    "no_cap", "zero_price", "pass_through", "attribution", "provenance"}
        self.assertEqual(names, required)
        # 空值语义必须写明 cap 裁定
        self.assertIn("不限价", d["null_semantics"]["cap"])
        # 标准化必须写明不做位数补零
        self.assertIn("不做位数补零", d["normalization"]["item_id"])

    def test_registry_declaration(self):
        p = Path(__file__).resolve().parents[1] / "config" / "gate0_registry.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        entry = d["gate_0a"].get("canonical_schema_version")
        self.assertIsNotNone(entry, "canonical_schema 未注册进 Gate 0a")
        self.assertEqual(entry["artifact_path"], "canonical_schema.json")
        self.assertTrue(entry["hash"], "canonical_schema 未冻结")


if __name__ == "__main__":
    unittest.main()
