"""测试用 xlsx 构造器 —— 零依赖生成**最小合法工作簿**。

用途：T01-02B 输入变体测试集与 T01-02C Golden Dataset 的生成底座。
**只服务测试与数据集制造，不进解析主链路**；与 ``io/xlsx.py``（读）配对：
这里写出的文件必须能被读取器按值矩阵原样读回。

设计口径：

* 单元格自动分型：int/float → 数字单元格（裸 ``<v>``）；str → 共享字符串；
  ``C(value, formula)`` → 公式单元格（``<f>`` + 可选缓存 ``<v>``——
  模拟「有/无缓存值公式」两种真实形态）；
* ``merged`` 声明合并区（0-based 行列），写出 ``<mergeCells>``——合并区
  左上角有值、其余为空，这正是零依赖读取器面对合并单元格的真实视图；
* 行矩阵允许**短行**（右侧缺单元格）与**稀疏跳行**——真实清单常态。
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

__all__ = ["C", "write_xlsx"]

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


@dataclass
class C:
    """公式单元格：formula 必填；cached=None 模拟「无缓存值」（读取器见空）。"""

    formula: str
    cached: str | float | None = None


def _col_letter(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def _cell_xml(row0: int, col0: int, value) -> str:
    ref = f"{_col_letter(col0)}{row0 + 1}"
    if isinstance(value, C):
        f = f"<f>{escape(value.formula)}</f>"
        v = "" if value.cached is None else f"<v>{value.cached}</v>"
        return f'<c r="{ref}">{f}{v}</c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"><v>{value}</v></c>'
    s = "" if value is None else str(value)
    if not s:
        return ""
    return f'<c r="{ref}" t="s"><v>{_sst_index(s)}</v></c>'


_SST: list[str] = []


def _sst_index(s: str) -> int:
    if s in _SST:
        return _SST.index(s)
    _SST.append(s)
    return len(_SST) - 1


def write_xlsx(
    path: str | Path,
    sheets: dict[str, list[list]],
    merged: dict[str, list[tuple[int, int, int, int]]] | None = None,
) -> Path:
    """写出最小合法 xlsx。sheets = {sheet_name: 行矩阵}。

    merged = {sheet_name: [(r1, c1, r2, c2), …]}（0-based，含端点）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _SST.clear()

    sheet_names = list(sheets)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument'
            '.spreadsheetml.worksheet+xml"/>' for i in range(len(sheet_names)))
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            f"{overrides}</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_R}"><sheets>'
            + "".join(
                f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                for i, n in enumerate(sheet_names))
            + "</sheets></workbook>",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                for i in range(len(sheet_names)))
            + "</Relationships>",
        )
        # 注意顺序：先写各 worksheet（累积共享字符串），最后写 sharedStrings
        for i, name in enumerate(sheet_names):
            rows_xml = []
            for r0, row in enumerate(sheets[name]):
                cells = "".join(
                    _cell_xml(r0, c0, v)
                    for c0, v in enumerate(row)
                )
                rows_xml.append(f'<row r="{r0 + 1}">{cells}</row>')
            merge_xml = ""
            if merged and name in merged:
                refs = "".join(
                    f'<mergeCell ref="{_col_letter(c1)}{r1 + 1}:{_col_letter(c2)}{r2 + 1}"/>'
                    for r1, c1, r2, c2 in merged[name])
                merge_xml = f'<mergeCells count="{len(merged[name])}">{refs}</mergeCells>'
            zf.writestr(
                f"xl/worksheets/sheet{i + 1}.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<worksheet xmlns="{NS_MAIN}"><sheetData>'
                + "".join(rows_xml)
                + f"</sheetData>{merge_xml}</worksheet>",
            )
        zf.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<sst xmlns="{NS_MAIN}" count="{len(_SST)}" uniqueCount="{len(_SST)}">'
            + "".join(f"<si><t>{escape(s)}</t></si>" for s in _SST)
            + "</sst>",
        )
    _SST.clear()
    return path
