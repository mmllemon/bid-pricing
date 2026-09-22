"""T01-00B 解析器测试。

合成用例用**内存构造的最小 xlsx**（zip + inlineStr XML，零第三方依赖），
覆盖双行表头 / 分节标题 / 别名歧义 / 数据缺口四类机制；
真实文件用例在文件缺失时自动跳过（测试不得耦合项目实时状态的同源原则）。
"""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from bidpricing.io.boq import (
    COLUMN_ALIASES,
    ParseReport,
    classify_code_kind,
    parse_listing,
)
from bidpricing.io.xlsx import XlsxError, load_workbook

REPO = Path(__file__).resolve().parents[1]
REAL_CAP = REPO.parent / "真实案件示例" / "中标限价" / (
    "西永L分区公立学校（暂定名）一期工程等项目配电工程.xlsx"
)
REAL_BID = REPO.parent / "真实案件示例" / "报价" / (
    "西永L分区公立学校（暂定名）一期工程等项目配电工程.xlsx"
)


# ------------------------------------------------------------------ fixture


def build_xlsx(path: Path, sheets: list[tuple[str, list[list[str]]]]) -> None:
    """构造一个足够让读取器工作的最小 xlsx（inlineStr，无样式无共享串）。"""
    sheet_xml: list[str] = []
    sheet_entries: list[str] = []
    rel_entries: list[str] = []
    for i, (name, rows) in enumerate(sheets, start=1):
        body: list[str] = []
        for ri, row in enumerate(rows, start=1):
            cells: list[str] = []
            for ci, val in enumerate(row):
                if val == "":
                    continue
                cells.append(
                    f'<c r="{chr(65 + ci)}{ri}" t="inlineStr">'
                    f"<is><t>{val}</t></is></c>"
                )
            body.append(f'<row r="{ri}">{"".join(cells)}</row>')
        sheet_xml.append(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(body)}</sheetData></worksheet>'
        )
        rel_entries.append(
            f'<Relationship Id="rId{i}" '
            f'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        )
        sheet_entries.append(
            f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
        )

    wb_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{''.join(sheet_entries)}</sheets></workbook>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(rel_entries)}</Relationships>"
    )

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", wb_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        for i, xml in enumerate(sheet_xml, start=1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", xml)


#: 与真实文件同构的最小分部分项表（双行表头 + 分节标题 + 一条数据缺口行）。
BOQ_ROWS = [
    ["表-09", "", "", "", "", "", "", "", "", "", "", ""],
    ["分部分项工程项目清单计价表", "", "", "", "", "", "", "", "", "", "", ""],
    ["工程名称：测试单位工程", "", "", "", "", "", "", "", "", "", "", ""],
    ["序号", "项目编码", "", "项目名称", "", "项目特征", "", "计量单位", "工程量", "", "金额（元）", ""],
    ["", "", "", "", "", "", "", "", "", "综合单价", "合价", "其中:暂估价"],
    ["", "C", "", "安装工程", "", "", "", "", "", "", "", ""],
    ["1", "030402017001", "", "高压柜", "", "[项目特征]…", "", "台", "1", "", "100", ""],
    ["2", "030402017002", "", "变压器", "", "[项目特征]…", "", "台", "2", "", "200.5", ""],
    ["3", "031301017001", "", "脚手架搭拆", "", "[项目特征]…", "", "项", "1", "", "", ""],
    ["", "B.3", "", "准备运行费", "", "", "", "", "", "", "", ""],
    ["合   计", "", "", "", "", "", "", "", "", "", "", ""],
]

SUMMARY_ROWS = [
    ["表-04", "", "", "", "", "", "", ""],
    ["单位工程投标报价汇总表"],
    ["序号", "", "汇总内容", "", "", "", "金额(元)"],
    ["1", "", "分部分项工程费", "", "", "", ""],
    ["2", "", "措施项目费", "", "", "", "7834.06"],
]


class CodeKindTest(unittest.TestCase):
    def test_standard_12(self):
        self.assertEqual(classify_code_kind("030402017001"), "STANDARD")
        # 12 位但含字母段（实测 041109B24001 形态）仍属 STANDARD
        self.assertEqual(classify_code_kind("041109B24001"), "STANDARD")

    def test_supplementary_6B(self):
        self.assertEqual(classify_code_kind("03B001"), "SUPPLEMENTARY")

    def test_unknown_not_blocked(self):
        self.assertEqual(classify_code_kind("X1"), "UNKNOWN")
        self.assertEqual(classify_code_kind("12345678"), "UNKNOWN")  # 位数不判合法性


class ParserMechanismTest(unittest.TestCase):
    def _parse(self, tmp: Path, sheets) -> ParseReport:
        xlsx = tmp / "sample.xlsx"
        build_xlsx(xlsx, sheets)
        return parse_listing(xlsx, "TEST-P1")

    def test_two_row_header_maps_amount_group(self):
        """综合单价/合价/暂估价落在子表头行——映射必须跨行合并。"""
        with tempfile.TemporaryDirectory() as tmp:
            rep = self._parse(Path(tmp), [("表-09 分部分项工程项目清单计价表【测试单位工程】", BOQ_ROWS)])
            m = rep.column_mapping["表-09 分部分项工程项目清单计价表【测试单位工程】"]
            self.assertEqual(m["unit_price"]["header"], "综合单价")
            self.assertEqual(m["amount"]["header"], "合价")
            self.assertEqual(m["temporary_valuation"]["header"], "其中:暂估价")
            self.assertEqual(m["unit_price"]["column"], "J")

    def test_section_title_rows_skipped_with_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = self._parse(Path(tmp), [("表-09 分部分项工程项目清单计价表【测试单位工程】", BOQ_ROWS)])
            # 分节标题（C / B.3）与合计行都不能进规范行
            ids = [r.item_id for r in rep.rows]
            self.assertNotIn("C", ids)
            self.assertNotIn("B.3", ids)
            self.assertTrue(any("分节标题行" in n for n in rep.notes))

    def test_row_order_preserves_file_sequence(self):
        """回归：输出行序必须保持源文件逐行顺序，绝不按项目编码重新排序。

        触发源：早期在匹配层用 sorted(set(...)) 曾把清单重新排序，导致网页/导出表
        与用户原清单「难以逐行对齐」（观测附言）。本用例数据编码刻意乱序（B/A/C 且
        跨分节标题），若解析或后续清匹配层任何一处按编码排序都会必现失败。
        """
        ordered = [
            ["表-09", "", "", "", "", "", "", "", "", "", "", ""],
            ["分部分项工程项目清单计价表", "", "", "", "", "", "", "", "", "", "", ""],
            ["序号", "项目编码", "", "项目名称", "", "项目特征", "", "计量单位", "工程量", "", "金额（元）", ""],
            ["", "", "", "", "", "", "", "", "", "综合单价", "合价", ""],
            ["1", "030402017002", "", "变压器A", "", "…", "", "台", "2", "", "200", ""],
            ["", "C", "", "安装工程", "", "", "", "", "", "", "", ""],
            ["2", "030402017001", "", "高压柜B", "", "…", "", "台", "1", "", "100", ""],
            ["3", "03B001", "", "补项C", "", "…", "", "个", "1", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            rep = self._parse(Path(tmp), [("表-09 分部分项工程项目清单计价表【测试单位工程】", ordered)])
            ids = [r.item_id for r in rep.rows]
            # 文件顺序 = 变压器A → 高压柜B → 补项C；若按编码字典序则会被排成
            # 030402017001 / 030402017002 / 03B001（'0'<...<'B'），二者不同 → 必现失败。
            self.assertEqual(ids, ["030402017002", "030402017001", "03B001"])
            self.assertEqual(len(rep.rows), 3)

    def test_quantity_gap_is_failure_not_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = self._parse(Path(tmp), [("表-09 分部分项工程项目清单计价表【测试单位工程】", BOQ_ROWS)])
            # 脚手架搭拆：工程量在、单价空 → 正常行（空值≠缺行）；
            # 反向用例：单价在、工程量空 → 失败样本
            rows = [r for r in rep.rows if r.item_id == "031301017001"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].unit_price, "")

    def test_quantity_empty_real_row_fails(self):
        bad = [row[:] for row in BOQ_ROWS]
        bad[7] = ["2", "030402017002", "", "变压器", "", "[项目特征]…", "", "台", "", "", "200.5", ""]
        with tempfile.TemporaryDirectory() as tmp:
            rep = self._parse(Path(tmp), [("表-09 分部分项工程项目清单计价表【测试单位工程】", bad)])
            self.assertEqual(len(rep.failures), 1)
            self.assertIn("工程量为空", rep.failures[0].reason)
            self.assertFalse(any(r.item_id == "030402017002" for r in rep.rows))

    def test_alias_ambiguity_blocks_not_guesses(self):
        """同一表头行命中两个「项目编码」→ 结构不可判定，整表失败。"""
        bad = [row[:] for row in BOQ_ROWS]
        bad[3] = ["序号", "项目编码", "项目编码", "项目名称", "", "项目特征", "",
                  "计量单位", "工程量", "", "金额（元）", ""]
        with tempfile.TemporaryDirectory() as tmp:
            rep = self._parse(Path(tmp), [("表-09 分部分项工程项目清单计价表【测试单位工程】", bad)])
            self.assertEqual(rep.rows, [])
            self.assertTrue(any("定位不到表头" in f.reason for f in rep.failures))

    def test_summary_sheet_yields_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = self._parse(Path(tmp), [
                ("表-04 单位工程投标报价汇总表【测试单位工程】", SUMMARY_ROWS),
                ("表-09 分部分项工程项目清单计价表【测试单位工程】", BOQ_ROWS),
            ])
            self.assertEqual(len(rep.rows), 3)
            states = {s["sheet_name"]: s["state"] for s in rep.sheets}
            self.assertIn("no_detail_header", states["表-04 单位工程投标报价汇总表【测试单位工程】"])

    def test_unknown_sheet_prefix_noted(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = self._parse(Path(tmp), [("封面", [["Hello"]])])
            self.assertEqual(rep.rows, [])
            self.assertTrue(any("无表号前缀" in n for n in rep.notes))

    def test_unit_work_from_bracket(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = self._parse(Path(tmp), [("表-09 分部分项工程项目清单计价表【测试单位工程】", BOQ_ROWS)])
            self.assertEqual({r.unit_work for r in rep.rows}, {"测试单位工程"})


class ReaderTest(unittest.TestCase):
    def test_missing_file_raises_xlsxerror(self):
        with self.assertRaises(XlsxError):
            load_workbook(Path("Z:/definitely/not/here.xlsx"))

    def test_bad_zip_raises_xlsxerror(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.xlsx"
            p.write_bytes(b"not a zip")
            with self.assertRaises(XlsxError):
                load_workbook(p)


@unittest.skipUnless(REAL_CAP.exists(), "真实样本不在本机（跳过，不视为失败）")
class RealFileSmokeTest(unittest.TestCase):
    """真实配对样本冒烟：数量与对账口径与已固化的 pair.json 交叉印证。"""

    @classmethod
    def setUpClass(cls):
        cls.cap = parse_listing(REAL_CAP, "XIYONG-L")
        cls.bid = parse_listing(REAL_BID, "XIYONG-L")

    def test_no_failures(self):
        self.assertEqual(self.cap.failures, [])
        self.assertEqual(self.bid.failures, [])

    def test_row_count_and_key_agreement(self):
        # 84/82 行业务依据（H-001，本地真实样本 84 行版）：
        # 限价清单 84 行、报价清单 82 行。限价侧独有项：03B015 运行准备（单价空）与
        # 03B016（单价非空），报价侧均未列项——「限价侧独有」≠「无最高限价」，分列不合并。
        # 报价侧没有限价侧缺失的项。两份源文件 sha256 不同。
        self.assertEqual(len(self.cap.rows), 84)
        self.assertEqual(len(self.bid.rows), 82)
        ck = {(r.unit_work, r.item_id) for r in self.cap.rows}
        bk = {(r.unit_work, r.item_id) for r in self.bid.rows}
        self.assertEqual(
            ck - bk, {("电气设备安装工程", "03B015"), ("电气设备安装工程", "03B016")})
        self.assertEqual(bk - ck, set())

    def test_code_kind_distribution(self):
        kinds = [r.code_kind for r in self.cap.rows]
        self.assertEqual(kinds.count("STANDARD"), 68)
        self.assertEqual(kinds.count("SUPPLEMENTARY"), 16)  # 含限价独有 03B015 / 03B016

    def test_weighted_discount_reproduces_pair_json(self):
        """与 T01-02C 固化样本独立复算：加权下浮 8.0084% 应重现。"""

        def f(s: str):
            try:
                return float(s.replace(",", ""))
            except ValueError:
                return None

        num = den = 0.0
        cm = {(r.unit_work, r.item_id): r for r in self.cap.rows}
        bm = {(r.unit_work, r.item_id): r for r in self.bid.rows}
        for k, c in cm.items():
            b = bm.get(k)
            if b is None:
                continue  # 限价独有 no_cap 项（03B015 / 03B016）无报价侧，不参与加权下浮
            q, pc = f(c.quantity), f(c.unit_price)
            pb = f(b.unit_price)
            if q is None or pc is None or pb is None:
                continue
            den += q * pc
            num += (1 - pb / pc) * q * pc
        self.assertAlmostEqual(num / den, 0.080084, places=4)

    def test_cap_side_known_gap_is_scaffold_item(self):
        """已知数据缺口：限价侧单价为空的项（空值≠缺行，ADR-0006）。

        仅 031301017001 脚手架搭拆（标准码）与 03B015 运行准备（补充码）单价为空；
        03B016 单价非空、不属「单价空缺口」。注：「限价侧独有」与「无最高限价」分列——
        限价独有项为 03B015 / 03B016，其中 03B015 单价空。
        """
        gaps = [r for r in self.cap.rows if not r.unit_price]
        self.assertEqual(sorted(r.item_id for r in gaps), ["031301017001", "03B015"])
        cap_only = {(r.unit_work, r.item_id) for r in self.cap.rows} - {(r.unit_work, r.item_id) for r in self.bid.rows}
        self.assertIn(("电气设备安装工程", "03B015"), cap_only)


class AliasMirrorTest(unittest.TestCase):
    def test_alias_mirror_probe(self):
        """contract-check 的镜像判据用的就是本常量——此处探针防「常量被删空」。"""
        self.assertIn("综合单价", COLUMN_ALIASES["unit_price"])
        self.assertIn("最高限价", COLUMN_ALIASES["unit_price"])
        self.assertIn("项目编码", COLUMN_ALIASES["item_id"])


if __name__ == "__main__":
    unittest.main()
