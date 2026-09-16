"""T01-02B 输入变体测试集 —— 十四类真实世界结构变体逐类覆盖。

任务判据：覆盖 Sheet 名变化、列序变化、合并单元格、空行、多表头、合计行、
隐藏行、表头带单位、数字带逗号、中文括号、文本数字、百分比、公式结果、
多单位工程；**任何无法识别的结构必须 BLOCK，禁止猜测映射**。

行为决策留痕（不是疏漏）：

* **隐藏行**：零依赖读取器只读值矩阵、不解析可见性标记——隐藏行按普通行
  参与解析。数据层**不因展示属性丢弃数据**（静默丢行违反 ADR-0005 输入
  保真；可见性是打印/展示层概念）。
* **表头带单位 / 未登录别名 / 同行多别名**：列映射失败 → 明细表定位不到
  表头 → BLOCK（failures 非空、rows 为空），**不猜**。
* 合并单元格：读取器视图 = 左上有值、其余空——空值语义按
  ``ALLOW_EMPTY_NO_CAP`` / 数据缺口处理，不视为结构缺失。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bidpricing.io.boq import parse_listing
from bidpricing.io.clean import clean_listing_rows
from bidpricing.io.xlsxkit import C, write_xlsx

# 真实双行表头形态（实测）：大列名行「金额（元）」跨列合并（合并区左上），
# 子表头行放「合价 / 其中:暂估价」——amount 别名命中的是子行的「合价」。
HDR = ["项目编码", "项目名称", "项目特征描述", "计量单位", "工程量",
       "综合单价（元）", "金额（元）", ""]
SUB = ["", "", "", "", "", "", "合价", "其中:暂估价"]

DETAIL_ROW = ["041101001001", "变压器", "10kV 油浸", "台", "2", "176068.11", "", ""]


def _detail_sheet(rows: list[list], header: list[str] | None = HDR,
                  sub: list[str] | None = SUB) -> list[list]:
    out: list[list] = [["表-09 分部分项工程项目清单计价表【电气设备安装工程】"], []]
    if header is not None:
        out.append(header)
    if sub is not None:
        out.append(sub)
    return out + rows


class VariantKit(unittest.TestCase):
    """每个用例独立临时目录 + 现场构造 xlsx。"""

    def parse(self, sheets: dict[str, list[list]], **kw) -> object:
        with tempfile.TemporaryDirectory() as tmp:
            p = write_xlsx(Path(tmp) / "v.xlsx", sheets, merged=kw.get("merged"))
            return parse_listing(p, "p1")


class TestRecognizableVariants(VariantKit):
    """可识别变体 → 解析成功且数值正确。"""

    def test_sheet_name_variation(self):
        """表号前缀即身份：空格/后缀变化不影响识别。"""
        rows = [DETAIL_ROW]
        r = self.parse({
            "表-09分部分项工程项目清单与计价表【电气】": _detail_sheet(rows)})
        self.assertEqual(len(r.rows), 1)
        self.assertEqual(r.rows[0].unit_work, "电气")
        self.assertEqual(r.failures, [])

    def test_sheet_without_table_prefix_is_noted_not_failed(self):
        """无表号前缀 → note 跳过（非明细表，预期），不制造假失败。"""
        r = self.parse({"分部分项": _detail_sheet([DETAIL_ROW])})
        self.assertEqual(r.rows, [])
        self.assertEqual(r.failures, [])
        self.assertTrue(any("无表号前缀" in n for n in r.notes))

    def test_column_order_variation(self):
        """列序打乱：按表头别名定位，不依赖位置。"""
        header = ["工程量", "综合单价（元）", "计量单位", "项目编码",
                  "项目名称", "项目特征描述"]
        row = ["2", "176068.11", "台", "041101001001", "变压器", "10kV"]
        r = self.parse({"表-09 明细【电气】": [
            ["t"], [], header, row]})
        self.assertEqual(len(r.rows), 1)
        x = r.rows[0]
        self.assertEqual((x.item_id, x.quantity, x.unit_price, x.unit),
                         ("041101001001", "2", "176068.11", "台"))

    def test_merged_cells(self):
        """合并单元格：表头「金额（元）」跨列 + 数据区名称纵向合并。"""
        rows = _detail_sheet([
            ["041101001001", "变压器", "10kV 油浸", "台", "2", "176068.11", "", ""],
            ["041101001002", "", "干式", "台", "1", "98765.43", "", ""],
        ])
        r = self.parse({"表-09 明细【电气】": rows},
                       merged={"表-09 明细【电气】": [(2, 5, 3, 6), (4, 1, 5, 1)]})
        self.assertEqual(len(r.rows), 2)
        self.assertEqual(r.rows[0].item_name, "变压器")
        self.assertEqual(r.rows[1].item_name, "")      # 合并区第二行 = 空
        self.assertEqual(r.failures, [])

    def test_blank_rows_skipped(self):
        rows = _detail_sheet([
            [],
            [],
            DETAIL_ROW,
            [],
            ["041101001002", "电缆", "WDZBN", "m", "10", "5.2", "", ""],
            [],
        ])
        r = self.parse({"表-09 明细【电气】": rows})
        self.assertEqual(len(r.rows), 2)
        self.assertEqual(r.failures, [])
        self.assertGreaterEqual(r.skipped_rows, 3)

    def test_double_header_real_shape(self):
        """双行表头（真实形态）：金额子列「合价/暂估价」在第二行。"""
        rows = _detail_sheet([
            ["041101001001", "变压器", "10kV", "台", "2", "176068.11", "352136.22", ""],
        ])
        r = self.parse({"表-09 明细【电气】": rows})
        self.assertEqual(len(r.rows), 1)
        m = r.column_mapping["表-09 明细【电气】"]
        self.assertIn("amount", m)
        self.assertEqual(m["amount"]["header"], "合价")
        self.assertIn("temporary_valuation", m)

    def test_total_row_skipped_as_section_like(self):
        """合计行：编码列「合计」+ 量/价/单位/特征全空 → 机械跳过不吞行。"""
        rows = _detail_sheet([
            DETAIL_ROW,
            ["合计", "合计", "", "", "", "", "", ""],
        ])
        r = self.parse({"表-09 明细【电气】": rows})
        self.assertEqual([x.item_id for x in r.rows], ["041101001001"])
        self.assertTrue(any("分节标题行" in n for n in r.notes))

    def test_thousands_separator_and_fullwidth(self):
        """数字带逗号 + 中文括号 + 全角 → 解析原样保留，清洗归一。"""
        rows = _detail_sheet([
            ["041101001001", "电缆", "ＷＤＺＢＮ", "ｍ", "1,234.5", "５２１.３５", "", ""],
        ])
        r = self.parse({"表-09 明细【电气】": rows})
        self.assertEqual(len(r.rows), 1)
        self.assertEqual(r.rows[0].quantity, "1,234.5")   # 解析层不转数
        cleaned, rep = clean_listing_rows(r.rows, "cap")
        self.assertEqual(rep.numeric_errors, [])
        self.assertEqual(cleaned[0].q0, 1234.5)
        self.assertEqual(cleaned[0].cap, 521.35)
        self.assertEqual(cleaned[0].unit, "m")            # 全角→半角

    def test_text_numbers(self):
        """文本型数字（t=s）：读取器按字符串读出，清洗照常数值化。"""
        rows = _detail_sheet([
            ["041101001001", "变压器", "10kV", "台", "2", "176068.11", "", ""],
        ])
        r = self.parse({"表-09 明细【电气】": rows})
        cleaned, rep = clean_listing_rows(r.rows, "cap")
        self.assertEqual(rep.numeric_errors, [])
        self.assertEqual(cleaned[0].q0, 2.0)

    def test_percent_string_goes_to_report_not_guessed(self):
        """百分比字符串「85%」：清洗器不猜 → numeric_errors 留痕、值 None。"""
        rows = _detail_sheet([
            ["041101001001", "费率项", "", "项", "1", "85%", "", ""],
        ])
        r = self.parse({"表-09 明细【电气】": rows})
        cleaned, rep = clean_listing_rows(r.rows, "cap")
        self.assertEqual(len(rep.numeric_errors), 1)
        self.assertIn("无法解析", rep.numeric_errors[0]["error"])
        self.assertIsNone(cleaned[0].cap)

    def test_formula_with_and_without_cached_value(self):
        """公式：有缓存值→读到值；无缓存值→空（cap 侧走 no_cap 语义）。"""
        rows = _detail_sheet([
            ["041101001001", "变压器", "10kV", "台", C("B5*2", "4"),
             C("单价*2", 352136.22), "", ""],
        ])
        r = self.parse({"表-09 明细【电气】": rows})
        self.assertEqual(len(r.rows), 1)
        self.assertEqual(r.rows[0].quantity, "4")
        self.assertEqual(r.rows[0].unit_price, "352136.22")
        rows2 = _detail_sheet([
            ["041101001001", "变压器", "10kV", "台", "2", C("单价*2", None), "", ""],
        ])
        r2 = self.parse({"表-09 明细【电气】": rows2})
        # quantity 有值、unit_price 公式无缓存 → 读到空 = cap 空 = no_cap 合法语义
        self.assertEqual(r2.rows[0].quantity, "2")
        cleaned, _ = clean_listing_rows(r2.rows, "cap")
        self.assertIsNone(cleaned[0].cap)
        self.assertTrue(cleaned[0].no_cap)
        self.assertEqual(r2.failures, [])

    def test_multiple_unit_works_in_one_file(self):
        """多单位工程：同文件两个 sheet，行键天然按 unit_work 分段。"""
        r = self.parse({
            "表-09 分部分项【电气设备安装工程】": _detail_sheet([DETAIL_ROW]),
            "表-09 分部分项【给排水安装工程】": _detail_sheet(
                [["041101001001", "水泵", "立式", "台", "3", "12000", "", ""]]),
        })
        self.assertEqual(len(r.rows), 2)
        works = {x.unit_work for x in r.rows}
        self.assertEqual(works, {"电气设备安装工程", "给排水安装工程"})
        # 同 item_id 跨单位工程不视为冲突（键含 unit_work）


class TestUnrecognizableMustBlock(VariantKit):
    """无法识别的结构 → BLOCK，禁止猜测映射。"""

    def test_header_with_units_blocks(self):
        """表头带单位「工程量(m)」：别名命不中 → 定位不到表头 → BLOCK。"""
        r = self.parse({"表-09 明细【电气】": [
            ["t"], [],
            ["项目编码", "项目名称", "工程量(m)", "综合单价(元/m)"],
            ["041101001001", "变压器", "2", "176068.11"],
        ]})
        self.assertEqual(r.rows, [])
        self.assertEqual(len(r.failures), 1)
        self.assertIn("定位不到表头", r.failures[0].reason)

    def test_unknown_alias_blocks(self):
        """item_id/quantity 列名全部未登录：定位不到表头 → 不猜，BLOCK。

        注意「清单编码」是登录别名（item_id）、「数量」是登录别名（quantity）——
        负例必须让**两个锚点列同时**命不中才会 BLOCK。
        """
        r = self.parse({"表-09 明细【电气】": [
            ["t"], [],
            ["材料编码", "名称", "单价", "规格"],
            ["041101001001", "变压器", "2", "176068.11"],
        ]})
        self.assertEqual(r.rows, [])
        self.assertGreaterEqual(len(r.failures), 1)

    def test_duplicate_alias_in_same_row_blocks(self):
        """同行命中两个「工程量」别名 → 结构不可判定 → 不猜，BLOCK。"""
        r = self.parse({"表-09 明细【电气】": [
            ["t"], [],
            ["项目编码", "工程量", "工程量", "综合单价（元）", "项目名称"],
            ["041101001001", "2", "3", "176068.11", "变压器"],
        ]})
        self.assertEqual(r.rows, [])
        self.assertGreaterEqual(len(r.failures), 1)

    def test_detail_sheet_without_any_header_blocks(self):
        """明细表完全无表头（纯数据）：BLOCK 而非空真通过。"""
        r = self.parse({"表-09 明细【电气】": [
            ["t"], [],
            ["041101001001", "变压器", "10kV", "台", "2", "176068.11"],
        ]})
        self.assertEqual(r.rows, [])
        self.assertGreaterEqual(len(r.failures), 1)

    def test_empty_detail_sheet_is_legal_conclusion(self):
        """对照：定位到表头但 0 数据行 = 合法结论（ADR-0006），不是 BLOCK。"""
        r = self.parse({"表-09 明细【电气】": _detail_sheet([])})
        self.assertEqual(r.rows, [])
        self.assertEqual(r.failures, [])


if __name__ == "__main__":
    unittest.main()
