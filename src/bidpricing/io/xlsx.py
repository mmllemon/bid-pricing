"""零依赖 xlsx 读取器（stdlib only）。

本项目约束：环境无 openpyxl / pandas，一切 IO 只用标准库。
xlsx 本质是 zip + XML（OOXML），直接解析 ``xl/workbook.xml`` /
``xl/sharedStrings.xml`` / 各 sheet XML 即可；**只读**，不改文件。

设计口径（与 ``config/input_protocol_schema.json::listing_structure`` 对齐）：

* 返回**稀疏无关**的矩形行矩阵——空单元格补 ``""``，保证列对齐不漂移；
* 只读缓存值（``<v>``），公式默认不取——投标期拿到的清单是**值**不是公式，
  需要看公式时用 ``want_formula=True``（调试用途，不进解析主链路）；
* 单元格一律以**字符串**返回，数值语义由上层解析器判定——
  读取器不知道哪个列是工程量，也就不该替上层做类型决定。
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"


class XlsxError(Exception):
    """xlsx 打不开 / 结构不符合预期。"""


@dataclass
class Sheet:
    """一张工作表：名称 + 矩形行矩阵（行列均从 0 计）。"""

    name: str
    rows: list[list[str]] = field(default_factory=list)

    def cell(self, row: int, col: int) -> str:
        """取单元格（越界返回空串，**不抛错**——清单里空行/短行是常态）。"""
        if 0 <= row < len(self.rows) and 0 <= col < len(self.rows[row]):
            return self.rows[row][col]
        return ""

    def n_rows(self) -> int:
        return len(self.rows)


@dataclass
class Workbook:
    path: Path
    sheets: list[Sheet] = field(default_factory=list)

    def sheet(self, name_or_prefix: str) -> Sheet | None:
        for s in self.sheets:
            if s.name == name_or_prefix or s.name.startswith(name_or_prefix):
                return s
        return None


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out: list[str] = []
    for si in root.findall(f"{NS}si"):
        out.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    return out


def _sheet_entries(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """返回 [(sheet_name, xml_path)]，按 workbook 声明顺序。"""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid2target = {
        rel.get("Id"): rel.get("Target") for rel in rels.findall(PKG_REL_NS)
    }
    entries: list[tuple[str, str]] = []
    for sh in wb.iter(f"{NS}sheet"):
        target = rid2target.get(sh.get(f"{RNS}id", ""), "")
        if target.startswith("/"):
            target = target[1:]
        elif not target.startswith("xl/"):
            target = "xl/" + target
        entries.append((sh.get("name", "?"), target))
    return entries


def _col_index(ref: str) -> int:
    """把 OOXML 单元格列引用（如 ``A`` / ``AA`` / ``BC``）转成 0-based 列号。

    非法 ref（如空字符串、纯数字、开头就非字母）直接 raise——静默返 0 会把值
    归位到 A 列，下游看不出数据错乱。xlsx 标准保证 ref 形如 ``A1`` / ``BC12``，
    非法 ref 本身意味着文件损坏。
    """
    m = re.match(r"([A-Z]+)", ref)
    if not m:
        raise ValueError(
            f"非法单元格引用 {ref!r}（应为 'A1'、'BC12' 等 OOXML 格式）"
        )
    idx = 0
    for ch in m.group(1):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _read_sheet_xml(zf: zipfile.ZipFile, target: str, sst: list[str]) -> list[list[str]]:
    root = ET.fromstring(zf.read(target))
    rows: list[list[str]] = []
    for r in root.iter(f"{NS}row"):
        cells: dict[int, str] = {}
        for c in r.findall(f"{NS}c"):
            ci = _col_index(c.get("r", ""))
            t = c.get("t")
            v = c.find(f"{NS}v")
            is_ = c.find(f"{NS}is")
            if t == "s" and v is not None and v.text:
                val = sst[int(v.text)]
            elif t == "inlineStr" and is_ is not None:
                val = "".join(x.text or "" for x in is_.iter(f"{NS}t"))
            elif v is not None:
                val = v.text or ""
            else:
                val = ""
            cells[ci] = val
        width = max(cells) + 1 if cells else 0
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


def load_workbook(path: str | Path) -> Workbook:
    """打开 xlsx 并读出全部工作表。任何 IO/XML 错误都归一为 :class:`XlsxError`。"""
    p = Path(path)
    if not p.exists():
        raise XlsxError(f"文件不存在：{p}")
    try:
        with zipfile.ZipFile(p) as zf:
            sst = _shared_strings(zf)
            wb = Workbook(path=p)
            for name, target in _sheet_entries(zf):
                wb.sheets.append(Sheet(name=name, rows=_read_sheet_xml(zf, target, sst)))
            return wb
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise XlsxError(f"无法解析 xlsx（{p.name}）: {exc}") from exc
