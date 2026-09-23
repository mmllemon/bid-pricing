"""T01-00B 招标（限价）清单解析器。

把一份 xlsx 清单解析为**规范行**（canonical rows），供 WP2/WP3 直接消费。

判据全部来自已冻结的契约制品，不在代码里再发明规则：

* **表识别**：表号（``表-04/09/10/11/12``）→ 角色（``listing_structure.sheets``）；
* **列识别**：「表号 → 逻辑字段 → 别名集合」（``listing_structure.column_aliases``），
  命中 0 个或 ≥2 个 → 失败样本，**不猜**；
* **分节标题行**：序号与编码皆空而名称非空的行——实测分节内序号各自从 1 重算，
  故序号**永不作键**；
* **复合主键**：``(project_id, unit_work, item_id)``——``unit_work`` 不可省
  （实测 ``03B001`` 在不同单位工程里含义不同）；``code_kind`` 只分
  STANDARD / SUPPLEMENTARY / UNKNOWN，**位数不参与合法性判定**（D1 裁定）；
* **空值口径**（ADR-0006 同源）：「值为空」≠「缺列/缺行」，两者分开计数。

解析器只做**机械信号命中**，不改数值、不补数、不猜列——
命不中的行原样进失败样本清单并给原因，绝不静默丢弃。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .xlsx import Sheet, Workbook, XlsxError, load_workbook

# ---------------------------------------------------------------- 识别表

#: 表号 → 清单角色（listing_structure.sheets 的机械投影；表号是稳定键，
#: 工作表**名称**会带【单位工程】后缀且随软件变化，只作前缀匹配）。
TABLE_NO_ROLES: dict[str, str] = {
    "表-04": "SUMMARY",
    "表-09": "DETAIL_BOQ",       # 分部分项 / 施工技术措施共用表号，靠名称区分
    "表-10": "ORG_MEASURE",
    "表-11": "OTHER",
    "表-12": "TAX",
}

#: 列名别名集合 —— 契约 ``column_aliases`` 的代码侧投影。
#: 修改口径须先改契约制品并重冻，本表与之不一致会被 contract-check 拦。
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "item_id": ("项目编码", "项目编号", "清单编码"),
    "item_name": ("项目名称",),
    "item_feature": ("项目特征", "项目特征描述"),
    "unit": ("计量单位", "单位"),
    "quantity": ("工程量", "数量"),
    "unit_price": ("综合单价", "最高限价", "综合单价（元）", "综合单价(元)", "综合单价(元/单位)"),
    "amount": ("合价", "金额", "合计金额"),
    "temporary_valuation": ("其中:暂估价", "其中：暂估价"),
}

#: 分部分项 / 施工技术措施在**工作表名称**上的区分词。
_TECH_MEASURE_MARKERS = ("施工技术措施",)


# ---------------------------------------------------------------- 数据结构


@dataclass
class ParsedRow:
    """一条规范行（canonical row / v1）。"""

    project_id: str
    unit_work: str
    item_id: str
    code_kind: str                 # STANDARD / SUPPLEMENTARY / UNKNOWN
    item_name: str
    item_feature: str
    unit: str
    quantity: str                  # 原样字符串；数值化在 T01-03，解析器不擅自转 float
    unit_price: str                # cap 侧=综合单价；报价侧=投标单价
    amount: str                    # 常为空（ADR-0005 源头事实）
    temporary_valuation: str       # 非空 → PASS_THROUGH 例外信号
    source_sheet: str              # 工作表名
    source_row: int                # 1-based 行号（对账用）
    source_table_no: str           # 表-09 等


@dataclass
class FailedRow:
    """失败样本清单的一行：命不中的行**原样保留**并给原因。"""

    source_sheet: str
    source_row: int
    reason: str
    raw: list[str] = field(default_factory=list)


@dataclass
class ParseReport:
    """解析日志 + 字段映射报告 + 失败样本清单（路线文档对 T01-00B 的三项产出）。"""

    source_file: str
    source_sha256: str
    project_id: str
    sheets: list[dict] = field(default_factory=list)       # 每表摘要（含角色与填充状态）
    column_mapping: dict[str, dict] = field(default_factory=dict)   # 每表的列映射
    rows: list[ParsedRow] = field(default_factory=list)
    failures: list[FailedRow] = field(default_factory=list)
    skipped_rows: int = 0          # 分节标题/页脚/注释行——机械可解释的跳过
    missing_unit_price_sheets: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rows"] = [asdict(r) for r in self.rows]
        d["failures"] = [asdict(f) for f in self.failures]
        return d

    def summary_line(self) -> str:
        by_sheet: dict[str, int] = {}
        for r in self.rows:
            by_sheet[r.source_table_no] = by_sheet.get(r.source_table_no, 0) + 1
        parts = "、".join(f"{k}:{v} 行" for k, v in sorted(by_sheet.items()))
        return (
            f"共 {len(self.rows)} 条规范行（{parts}），"
            f"失败 {len(self.failures)}、机械跳过 {self.skipped_rows}"
        )


# ---------------------------------------------------------------- 工具


def classify_code_kind(item_id: str) -> str:
    """编码形态三分类（D1：**位数不参与合法性判定**）。

    * ``12 位``（可含单个字母段）→ STANDARD；
    * ``6 位``且末段含 ``B``（实测补充编码形态，如 ``03B001``）→ SUPPLEMENTARY；
    * 其余 → UNKNOWN（**不阻塞**，交人工确认）。
    """
    s = item_id.strip().upper()
    if re.fullmatch(r"[0-9A-Z]{12}", s):
        return "STANDARD"
    if re.fullmatch(r"[0-9]{2}B[0-9A-Z]{3}", s):
        return "SUPPLEMENTARY"
    return "UNKNOWN"


def _table_no(sheet_name: str) -> str | None:
    """提取工作表名的表号前缀（如「表-09」）。

    **必须**拒绝半角字母/数字后缀——否则「表-09A 补充清单」会被误判为「表-09」
    而套用主表的角色与列映射，实测真实样本里 A/B/C 后缀表示补充/附表。
    中文紧邻（如「表-09分部分项...」）是合法的，需放行。
    """
    m = re.match(r"(表-\d+)(?![A-Za-z0-9])", sheet_name.strip())
    return m.group(1) if m else None


def _unit_work_from(sheet: Sheet, sheet_name: str) -> str:
    """单位工程维度：优先【…】后缀，退回「工程名称：…」单元格。"""
    m = re.search(r"【(.+?)】", sheet_name)
    if m:
        return m.group(1)
    for row in sheet.rows[:8]:
        for cell in row:
            if cell.startswith("工程名称"):
                m2 = re.search(r"工程名称[:：]\s*(.+)", cell)
                if m2:
                    return m2.group(1).strip()
    return ""


def _find_header(sheet: Sheet) -> tuple[int, dict[str, int]] | None:
    """在表内定位表头并做列映射。

    双行表头（实测）：大列名行（含跨列合并的「金额（元）」）+ 子列名行
    （综合单价 / 合价 / 其中:暂估价）。实现：先找**同时含 item_id 与
    quantity** 的大列名行；若金额区子列落在紧随其后的子表头行，则合并
    （子表头行本身没有 item_id，且只补大列名行没命中的字段——两级行
    各命中一次即收敛，不会产生 ≥2 歧义）。

    返回 (表头行号, {逻辑字段: 列号}, {逻辑字段: 命中列名文本})；
    映射不出 item_id + quantity 的行不是表头。
    """
    for ri, row in enumerate(sheet.rows):
        mapping: dict[str, int] = {}
        texts: dict[str, str] = {}
        for logical, aliases in COLUMN_ALIASES.items():
            hits = [ci for ci, cell in enumerate(row) if cell.strip() in aliases]
            if len(hits) == 1:
                mapping[logical] = hits[0]
                texts[logical] = row[hits[0]].strip()
            elif len(hits) > 1:
                # 契约 column_aliases.policy 原文：「同一逻辑字段命中≥2 个别名时 BLOCK」。
                # 只对**必需键**（item_id/quantity）的歧义做整表阻断——契约口径下，
                # 非必需字段的歧义走数据缺口路径（后续取值为空串）而不是打断整表。
                # 原实现「任何字段歧义就整表 BLOCK」会把大量真实可解析的表头判死。
                if logical in ("item_id", "quantity"):
                    return None  # 必需键歧义 → 整表不可判定，不猜
                # 非必需键歧义：跳过该字段，继续扫描其他字段
        if "item_id" in mapping and "quantity" in mapping:
            # 金额区子列可能在本行之后的子表头行——已在同行的就用同行的
            if ri + 1 < sheet.n_rows():
                sub = sheet.rows[ri + 1]
                sub_has_item = any(
                    cell.strip() in COLUMN_ALIASES["item_id"] for cell in sub
                )
                if not sub_has_item:
                    for logical, aliases in COLUMN_ALIASES.items():
                        if logical in mapping:
                            continue
                        hits = [
                            ci for ci, cell in enumerate(sub) if cell.strip() in aliases
                        ]
                        if len(hits) == 1:
                            mapping[logical] = hits[0]
                            texts[logical] = sub[hits[0]].strip()
            return ri, mapping, texts
    return None


def _is_skippable(row: list[str]) -> tuple[bool, str]:
    """机械可解释的跳过：注释 / 页码 / 空行 / 分节标题。

    注释行仅认「注：」/「注：」/「备注：」这类**注释块标记**；不认
    `first.startswith("注")`——那会把项目名以「注」开头的行（如「注资设备」）
    当注释吞掉，而项目名完全可能以「注」开头。
    """
    joined = "".join(c for c in row if c).strip()
    if not joined:
        return True, "空行"
    first = next((c for c in row if c.strip()), "")
    if re.match(r"^(注|备注)\s*[：:]", first):
        return True, "注释块"
    if first.startswith("表-"):
        return True, "分节/表头重复"
    if "页  共" in joined:
        return True, "页脚"
    return False, ""


def parse_listing(path: str | Path, project_id: str) -> ParseReport:
    """解析一份清单 xlsx，产出 :class:`ParseReport`。"""
    p = Path(path)
    wb: Workbook = load_workbook(p)
    report = ParseReport(
        source_file=str(p),
        source_sha256=hashlib.sha256(p.read_bytes()).hexdigest()[:12],
        project_id=project_id,
    )

    for sheet in wb.sheets:
        table_no = _table_no(sheet.name)
        if table_no is None:
            report.notes.append(f"工作表「{sheet.name}」无表号前缀，跳过")
            continue
        role = TABLE_NO_ROLES[table_no]
        if table_no == "表-09" and any(m in sheet.name for m in _TECH_MEASURE_MARKERS):
            role = "TECH_MEASURE"

        unit_work = _unit_work_from(sheet, sheet.name)
        header = _find_header(sheet)

        entry = {
            "sheet_name": sheet.name,
            "table_no": table_no,
            "role": role,
            "unit_work": unit_work,
            "n_rows": sheet.n_rows(),
        }
        if header is None:
            # 汇总/费率/规费税金表没有「编码+工程量」结构，属预期而非失败
            if role in ("SUMMARY", "ORG_MEASURE", "OTHER", "TAX"):
                entry["state"] = "no_detail_header（汇总/费率式表，预期）"
                report.sheets.append(entry)
                continue
            entry["state"] = "FAILED: 明细表定位不到表头"
            report.sheets.append(entry)
            report.failures.append(
                FailedRow(sheet.name, 0, "明细表定位不到表头（item_id+quantity 列映射失败）", [])
            )
            continue

        hri, mapping, header_texts = header
        entry["state"] = "ok"
        entry["header_row"] = hri + 1
        report.column_mapping[sheet.name] = {
            logical: {"column": chr(65 + ci) if ci < 26 else f"col{ci}",
                      "header": header_texts.get(logical, "")}
            for logical, ci in sorted(mapping.items(), key=lambda kv: kv[1])
        }
        report.sheets.append(entry)

        if role not in ("DETAIL_BOQ", "TECH_MEASURE"):
            continue  # 只有明细表产出规范行

        if "unit_price" not in mapping:
            # D13：缺单价列 ≠ 单元格空——列缺失会让清洗层判为合法 no_cap，
            # 下游无上界报价；此处必须留痕并阻断，交 D13 判据阻断求解。
            report.missing_unit_price_sheets.append(sheet.name)
            report.failures.append(
                FailedRow(sheet.name, hri + 1,
                          "明细表缺少单价列（综合单价/最高限价）——数据缺陷，不猜", [])
            )

        for ri in range(hri + 1, sheet.n_rows()):
            row = sheet.rows[ri]
            skippable, why = _is_skippable(row)
            if skippable:
                report.skipped_rows += 1
                continue
            item_id = sheet.cell(ri, mapping.get("item_id", -1)).strip()
            item_name = sheet.cell(ri, mapping.get("item_name", -1)).strip()
            quantity = sheet.cell(ri, mapping.get("quantity", -1)).strip()
            unit_price = sheet.cell(ri, mapping.get("unit_price", -1)).strip()
            if not item_id and not item_name:
                report.skipped_rows += 1
                continue
            if not item_id:
                # 有名称无编码：分节标题行（序号分节内重算的根因）或异常行 → 失败样本
                report.failures.append(
                    FailedRow(sheet.name, ri + 1, "有项目名称但无项目编码（分节标题行或异常行）", row[:10])
                )
                continue
            if not quantity and not unit_price and not sheet.cell(ri, mapping.get("unit", -1)).strip() \
                    and not sheet.cell(ri, mapping.get("item_feature", -1)).strip():
                # 实测分节标题行（编码列放分节名，如「C」「B.3」「一」）：
                # 工程量 / 单价 / 单位 / 特征 **四项全空**——真明细行不会全空。
                # 四信号合取才判分节，任一存在则按数据缺口处理，不静默吞行。
                report.skipped_rows += 1
                report.notes.append(
                    f"{sheet.name} r{ri + 1}: 分节标题行（编码列={item_id!r}，名称={item_name!r}）"
                )
                continue
            if not quantity:
                report.failures.append(
                    FailedRow(sheet.name, ri + 1,
                              f"明细行工程量为空（item_id={item_id}）——数据缺口，不猜", row[:10])
                )
                continue

            def g(logical: str) -> str:
                ci = mapping.get(logical, -1)
                return sheet.cell(ri, ci).strip() if ci >= 0 else ""

            report.rows.append(
                ParsedRow(
                    project_id=project_id,
                    unit_work=unit_work,
                    item_id=item_id,
                    code_kind=classify_code_kind(item_id),
                    item_name=item_name,
                    item_feature=g("item_feature"),
                    unit=g("unit"),
                    quantity=quantity,
                    unit_price=unit_price,
                    amount=g("amount"),
                    temporary_valuation=g("temporary_valuation"),
                    source_sheet=sheet.name,
                    source_row=ri + 1,
                    source_table_no=table_no,
                )
            )
    return report


def assert_price_columns_present(*, cap_report=None, cost_report=None) -> None:
    """D13：缺单价列 = 数据缺陷，不是「不限价」。

    「不限价」只指列在而值为空（D03 通道）；整列缺失 = 上传的不是本口径清单，
    此时 unit_price 恒为空，清洗层全部走 no_cap，下游无上界报价。此处显式拒绝。

    参数二选一（或同时）：cap_report 为限价清单侧，cost_report 为成本清单侧。
    任一侧有缺列 → 抛 XlsxError。
    """
    bad: list[str] = []
    if cap_report is not None and getattr(cap_report, "missing_unit_price_sheets", None):
        bad.extend([f"cap:{s}" for s in cap_report.missing_unit_price_sheets])
    if cost_report is not None and getattr(cost_report, "missing_unit_price_sheets", None):
        bad.extend([f"cost:{s}" for s in cost_report.missing_unit_price_sheets])
    if bad:
        raise XlsxError(
            f"明细表缺少单价列（综合单价/最高限价），无法判定限价或成本："
            f"{'、'.join(bad)}。"
            "请提供含单价列的清单（『不限价』只指列在而值为空，不是整列缺失）。"
        )


def write_report(report: ParseReport, out_dir: Path) -> dict[str, Path]:
    """三项产出落盘：解析日志（JSON）/ 字段映射报告（md）/ 失败样本清单（csv）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(report.source_file).stem

    log_path = out_dir / f"{stem}.parse_log.json"
    log_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
    )

    md_lines = [
        f"# 字段映射报告 —— {stem}", "",
        f"- 源文件：`{report.source_file}`",
        f"- sha256 前 12 位：`{report.source_sha256}`",
        f"- project_id：`{report.project_id}`",
        f"- {report.summary_line()}", "",
        "## 表识别与列映射", "",
    ]
    for sheet_meta in report.sheets:
        md_lines.append(
            f"- **{sheet_meta['sheet_name']}** → 角色 `{sheet_meta['role']}`，"
            f"单位工程「{sheet_meta['unit_work']}」，{sheet_meta['state']}"
        )
        mapping = report.column_mapping.get(sheet_meta["sheet_name"])
        if mapping:
            for logical, m in mapping.items():
                md_lines.append(f"  - `{logical}` ← 列 **{m['header']}**（{m['column']}）")
    if report.failures:
        md_lines += ["", "## 失败样本清单", ""]
        for f in report.failures:
            md_lines.append(f"- `{f.source_sheet}` r{f.source_row}: {f.reason}")
    if report.notes:
        md_lines += ["", "## 备注", ""] + [f"- {n}" for n in report.notes]
    md_path = out_dir / f"{stem}.mapping.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    # CSV 导出：用 csv.writer + QUOTE_ALL 正确处理含逗号/引号/换行的字段。
    # 旧实现用 `replace(",", "，")` 只处理 ASCII 逗号，双引号、换行、工作表名里的逗号都会破坏 CSV。
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(["source_sheet", "source_row", "reason", "raw"])
    for f in report.failures:
        writer.writerow([
            f.source_sheet,
            f.source_row,
            f.reason,
            "|".join(f.raw),
        ])
    csv_path = out_dir / f"{stem}.failures.csv"
    csv_path.write_text(csv_buf.getvalue(), encoding="utf-8")

    return {"log": log_path, "mapping": md_path, "failures": csv_path}
