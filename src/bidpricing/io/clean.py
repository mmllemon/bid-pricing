"""T01-03 规范化与清洗 —— 字符串规范行 → 类型化 canonical 行。

口径全部来自已冻结制品，**不在代码里发明规则**：

* 字段集与空值语义 —— ``config/canonical_schema.json``（T01-01，Gate 0a 冻结）；
* ``cap`` 空 = 不限价（``ALLOW_EMPTY_NO_CAP``，用户 2026-09-16 裁定）——
  **禁止按 cap=0 处理**（``p_i ≤ 0`` 直接不可行，数值实现最危险的静默错误）；
* 编码标准化**不做位数补零**（D1：位数不参与合法性判定，补零等于改主键）；
* 数值精度：工程量 6 位、金额 2 位（与 ``field_schema`` 一致）。

清洗器只做机械归一：命不中的数值原样保留并计入报告，**不猜、不补、不静默丢弃**。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .boq import ParsedRow

__all__ = [
    "CleanRow",
    "CleanReport",
    "clean_listing_rows",
    "_to_number",
    "_normalize_code",
    "_normalize_unit",
]

# 全角 → 半角（数字、字母、常用符号）
_FULLWIDTH = {ord(f): ord(t) for f, t in zip(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ，．（）：；",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz,.():;")}


def _halfwidth(s: str) -> str:
    return s.translate(_FULLWIDTH)


def _to_number(raw: str) -> tuple[float | None, str | None]:
    """字符串 → float。返回 (值, 错误)。空 → (None, None)；解析失败 → (None, 原因)。

    口径：去千分位逗号与空白、全角→半角。**不做**四舍五入（精度归一由输出层按
    field_schema 的 precision 执行）。
    """
    s = _halfwidth((raw or "").strip()).replace(",", "").replace(" ", "")
    if not s:
        return None, None
    try:
        return float(s), None
    except ValueError:
        return None, f"无法解析为数值：{raw!r}"


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _normalize_code(raw: str) -> str:
    """编码标准化：空白/全角/大小写归一。**不做位数补零**（D1）。"""
    return _halfwidth((raw or "").strip()).upper()


def _normalize_unit(raw: str) -> str:
    return _halfwidth((raw or "").strip())


@dataclass
class CleanRow:
    """canonical 行（T01-01 统一字段集）。字符串 → 类型化，语义标志齐备。"""

    project_id: str
    unit_work: str
    item_id: str
    code_kind: str
    item_name: str
    item_feature: str
    unit: str
    q0: float | None
    q1_point: float | None
    cap: float | None
    c_i: float | None
    no_cap: bool
    zero_price: bool
    pass_through: bool
    attribution: str | None          # DRAWING_DIFF / CHANGE_ORDER / BOTH / UNKNOWN
    provenance: dict

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CleanReport:
    """清洗报告：每一步归一都可解释，异常行进清单不丢弃。"""

    side: str                        # cap / cost
    n_rows_in: int = 0
    n_rows_out: int = 0
    numeric_errors: list[dict] = field(default_factory=list)   # 解析失败的数值原文
    no_cap_items: list[str] = field(default_factory=list)      # cap 空 → 不限价（裁定语义）
    zero_price_items: list[dict] = field(default_factory=list) # 单价为 0（C5 信号）
    pass_through_items: list[str] = field(default_factory=list)
    q_mismatch_items: int = 0        # q0 与 q1_point 不一致项数（对账阶段细查）

    def to_dict(self) -> dict:
        return asdict(self)


def clean_listing_rows(
    rows: list[ParsedRow],
    side: str,
    attribution: str | None = None,
) -> tuple[list[CleanRow], CleanReport]:
    """把一个清单侧的 ParsedRow 清洗为 canonical 行。

    side = "cap"：quantity→q0、unit_price→cap（空 → no_cap=true）；
    side = "cost"：quantity→q1_point、unit_price→c_i。
    其余字段机械归一（编码/单位/数值），异常进报告。
    """
    if side not in ("cap", "cost"):
        raise ValueError(f"side 须为 cap|cost，收到 {side!r}")
    rep = CleanReport(side=side)
    out: list[CleanRow] = []

    for r in rows:
        rep.n_rows_in += 1
        item_id = _normalize_code(r.item_id)
        unit = _normalize_unit(r.unit)

        q_raw, p_raw = r.quantity, r.unit_price
        q, q_err = _to_number(q_raw)
        p, p_err = _to_number(p_raw)
        for col, err in (("quantity", q_err), ("unit_price", p_err)):
            if err:
                rep.numeric_errors.append(
                    {"item_id": item_id, "column": col,
                     "source_sheet": r.source_sheet, "source_row": r.source_row,
                     "error": err})

        if side == "cap":
            q0, cap = _round(q, 6), _round(p, 2)
            q1_point, c_i = None, None
            no_cap = p_raw is None or not p_raw.strip()
            if no_cap:
                rep.no_cap_items.append(item_id)
        else:
            q1_point, c_i = _round(q, 6), _round(p, 2)
            q0, cap = None, None
            no_cap = False

        zero_price = p == 0.0
        if zero_price:
            rep.zero_price_items.append(
                {"item_id": item_id, "side": side,
                 "source_sheet": r.source_sheet, "source_row": r.source_row})
        pass_through = bool((r.temporary_valuation or "").strip())
        if pass_through:
            rep.pass_through_items.append(item_id)

        out.append(CleanRow(
            project_id=r.project_id,
            unit_work=r.unit_work,
            item_id=item_id,
            code_kind=r.code_kind,
            item_name=r.item_name.strip(),
            item_feature=r.item_feature.strip(),
            unit=unit,
            q0=q0, q1_point=q1_point, cap=cap, c_i=c_i,
            no_cap=no_cap,
            zero_price=zero_price,
            pass_through=pass_through,
            attribution=attribution,
            provenance={
                "source_sheet": r.source_sheet,
                "source_row": r.source_row,
                "source_table_no": r.source_table_no,
                "side": side,
            },
        ))
        rep.n_rows_out += 1

    return out, rep
