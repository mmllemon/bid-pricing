"""T01-05 源文件版本锁定与完整性的测试。

判据（任务板原文）：
* 每次导入记录 file_name / file_hash / file_version / sheet_hash /
  import_timestamp / source_owner；
* 源文件被替换后必须**能识别并拒绝**复用旧复算结果。

xlsx 是 zip 包——测试里用标准库 zipfile 现场构造最小合法工作簿，
再字节级改写内容模拟「文件被替换」。
"""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from bidpricing.io.import_registry import (
    compute_sheet_hashes,
    file_sha256,
    load_registry,
    register_import,
    registry_path_for,
    verify_import,
)
from bidpricing.io.xlsx import load_workbook

_SST_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<si><t>编码</t></si><si><t>100</t></si><si><t>999</t></si></sst>'
)
_SHEET_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c>'
    '<c r="B1" t="s"><v>1</v></c></row></sheetData></worksheet>'
)
_SHEET_XML_REPLACED = _SHEET_XML.replace("<v>1</v>", "<v>2</v>")
_WB_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="表-09" sheetId="1" r:id="rId1"/></sheets></workbook>'
)
_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1"'
    ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
    ' Target="worksheets/sheet1.xml"/></Relationships>'
)
_CT_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/></Types>'
)


def _make_xlsx(path: Path, sheet_xml: str = _SHEET_XML) -> Path:
    """现场构造最小合法 xlsx（zip 结构，供零依赖读取器打开）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CT_XML)
        zf.writestr("xl/workbook.xml", _WB_XML)
        zf.writestr("xl/_rels/workbook.xml.rels", _RELS_XML)
        zf.writestr("xl/sharedStrings.xml", _SST_XML)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return path


class FingerprintTest(unittest.TestCase):
    def test_file_hash_changes_on_any_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _make_xlsx(Path(tmp) / "a.xlsx")
            h1 = file_sha256(p)
            _make_xlsx(p, _SHEET_XML_REPLACED)      # 内容替换（zip 时间戳也在变）
            self.assertNotEqual(file_sha256(p), h1)

    def test_sheet_hash_tracks_value_matrix_not_zip_metadata(self):
        """sheet_hash 基于**值矩阵**：同样的数据（重打包）哈希必须一致。"""
        with tempfile.TemporaryDirectory() as tmp:
            p1 = _make_xlsx(Path(tmp) / "a.xlsx")
            p2 = _make_xlsx(Path(tmp) / "b.xlsx")   # 两个独立 zip，数据相同
            h1 = compute_sheet_hashes(load_workbook(p1))
            h2 = compute_sheet_hashes(load_workbook(p2))
            self.assertEqual(h1, h2)
            # 内容替换 → 哈希变化
            _make_xlsx(p2, _SHEET_XML_REPLACED)
            h3 = compute_sheet_hashes(load_workbook(p2))
            self.assertNotEqual(h1, h3)
            # 变化定位：sheet 名一致、哈希不同
            self.assertEqual(set(h1), set(h3))


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.xlsx = _make_xlsx(self.base / "src" / "listing.xlsx")

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_fields_complete(self):
        """任务判据的六个字段一个不能少。"""
        rec = register_import(self.xlsx, "p1", "cap", self.base,
                              source_owner="招标人")
        for f in ("file_name", "file_hash", "file_version", "sheet_hash",
                  "import_timestamp", "source_owner"):
            self.assertTrue(getattr(rec, f), f)
        self.assertEqual(rec.import_seq, 1)
        self.assertEqual(rec.file_version, rec.file_hash[:12])

    def test_verify_pass_on_same_file(self):
        register_import(self.xlsx, "p1", "cap", self.base)
        r = verify_import(self.xlsx, "p1", "cap", self.base)
        self.assertEqual(r.status, "PASS")
        self.assertIsNotNone(r.record)

    def test_verify_blocked_when_not_registered(self):
        """未登记 = 无比对基准 = BLOCKED（不是空真通过）。"""
        r = verify_import(self.xlsx, "p9", "cap", self.base)
        self.assertEqual(r.status, "BLOCKED")
        self.assertIn("未登记", r.reason)

    def test_verify_blocked_on_replaced_file_and_locates_changes(self):
        """核心判据：文件被替换 → 识别 + 拒绝复用 + 定位变化 sheet。"""
        register_import(self.xlsx, "p1", "cap", self.base)
        old = load_registry(registry_path_for(self.base, "p1", "cap"))[-1]
        _make_xlsx(self.xlsx, _SHEET_XML_REPLACED)      # 同路径替换内容
        r = verify_import(self.xlsx, "p1", "cap", self.base)
        self.assertEqual(r.status, "BLOCKED")
        self.assertIn("拒绝复用", r.reason)
        self.assertEqual(r.record.file_hash, old.file_hash)   # 旧登记留痕
        self.assertEqual(r.changed_sheets, ["表-09"])

    def test_registry_is_append_only_with_seq(self):
        """登记表不可变追加：旧记录保留、序号递增、verify 取最新。"""
        register_import(self.xlsx, "p1", "cap", self.base)
        _make_xlsx(self.xlsx, _SHEET_XML_REPLACED)
        register_import(self.xlsx, "p1", "cap", self.base)
        recs = load_registry(registry_path_for(self.base, "p1", "cap"))
        self.assertEqual([r.import_seq for r in recs], [1, 2])
        self.assertNotEqual(recs[0].file_hash, recs[1].file_hash)
        # 当前文件 = 第 2 次导入的文件 → PASS
        self.assertEqual(verify_import(self.xlsx, "p1", "cap", self.base).status, "PASS")

    def test_sides_and_projects_isolated(self):
        register_import(self.xlsx, "p1", "cap", self.base)
        # 同文件登记到 cost 侧 / 另一项目：互不影响
        r = verify_import(self.xlsx, "p1", "cost", self.base)
        self.assertEqual(r.status, "BLOCKED")
        r = verify_import(self.xlsx, "p2", "cap", self.base)
        self.assertEqual(r.status, "BLOCKED")

    def test_registry_payload_is_plain_json(self):
        register_import(self.xlsx, "p1", "cap", self.base)
        payload = json.loads(
            registry_path_for(self.base, "p1", "cap").read_text(encoding="utf-8"))
        self.assertIn("records", payload)
        self.assertEqual(len(payload["records"]), 1)


if __name__ == "__main__":
    unittest.main()
