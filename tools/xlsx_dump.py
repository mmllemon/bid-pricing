#!/usr/bin/env python
"""零依赖 xlsx 读取器（stdlib only）——用于核对用户实际提供的清单结构。

用法:
    python tools/xlsx_dump.py <file.xlsx> [--sheet N] [--max-rows N] [--formulas]

设计取向与 bid-pricing 一致：不引入第三方依赖（本机无 openpyxl / pandas）。
xlsx 本质是 zip + XML，直接解析即可；本工具只读，不改文件。
"""
from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out: list[str] = []
    for si in root.findall(f"{NS}si"):
        out.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    return out


def _sheet_names(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """返回 [(sheet_name, target_path)]，按 workbook 顺序。"""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid2target = {
        rel.get("Id"): rel.get("Target")
        for rel in rels.findall(
            "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
        )
    }
    out = []
    for sh in wb.iter(f"{NS}sheet"):
        rid = sh.get(f"{RNS}id")
        target = rid2target.get(rid, "")
        if target.startswith("/"):
            target = target[1:]
        elif not target.startswith("xl/"):
            target = "xl/" + target
        out.append((sh.get("name", "?"), target))
    return out


def _col_index(ref: str) -> int:
    letters = re.match(r"([A-Z]+)", ref)
    if not letters:
        return 0
    idx = 0
    for ch in letters.group(1):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def read_sheet(zf: zipfile.ZipFile, path: str, sst: list[str], want_formula: bool) -> list[list[str]]:
    root = ET.fromstring(zf.read(path))
    rows: list[list[str]] = []
    for r in root.iter(f"{NS}row"):
        cells: dict[int, str] = {}
        for c in r.findall(f"{NS}c"):
            ref = c.get("r", "")
            ci = _col_index(ref)
            t = c.get("t")
            f = c.find(f"{NS}f")
            v = c.find(f"{NS}v")
            is_ = c.find(f"{NS}is")
            if t == "s" and v is not None:
                val = sst[int(v.text)] if v.text else ""
            elif t == "inlineStr" and is_ is not None:
                val = "".join(x.text or "" for x in is_.iter(f"{NS}t"))
            elif v is not None:
                val = v.text or ""
            else:
                val = ""
            if f is not None and want_formula:
                ftxt = f.text or ""
                val = f"={ftxt}" if not val else f"{val} [={ftxt}]"
            cells[ci] = val
        width = max(cells) + 1 if cells else 0
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--sheet", type=int, default=None, help="只打印第 N 张表（从 1 开始）")
    ap.add_argument("--max-rows", type=int, default=0, help="每表最多打印多少行（0=全部）")
    ap.add_argument("--formulas", action="store_true", help="显示公式")
    args = ap.parse_args()

    path = Path(args.xlsx)
    with zipfile.ZipFile(path) as zf:
        sst = _shared_strings(zf)
        sheets = _sheet_names(zf)
        print(f"# {path.name}")
        print(f"# 共 {len(sheets)} 张表: " + " | ".join(n for n, _ in sheets))
        for i, (name, target) in enumerate(sheets, start=1):
            if args.sheet and i != args.sheet:
                continue
            rows = read_sheet(zf, target, sst, args.formulas)
            print(f"\n{'=' * 78}\n## [{i}] {name}  （{len(rows)} 行）\n{'=' * 78}")
            limit = args.max_rows or len(rows)
            for ri, row in enumerate(rows[:limit], start=1):
                cells = " | ".join(row)
                if cells.strip(" |"):
                    print(f"r{ri:>3}: {cells}")
            if limit < len(rows):
                print(f"  … 余 {len(rows) - limit} 行省略")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
