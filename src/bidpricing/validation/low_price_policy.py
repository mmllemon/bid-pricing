"""H-004 低价确认与废标风险留痕（LC-01～LC-05 + 运行时确认记录构造）。

背景：报价比率低于 50%（报价/限价）时，当前 ``NEEDS_CONFIRMATION`` 只是**产品
安全闸门**（低于阈值未确认就不计算），不是法律裁定。H-004 验收标准要求：
结果记录**用户、时间、条款依据**；**区分「低价确认」与「废标判定」**；**不替
用户作法律判断**。本模块把这些承诺做成可机器校验的配置声明 + 运行时留痕契约：

* **低价确认（CONFIRM_ONLY）**：系统只负责把『谁在什么时间依据哪条招标文件
  条款确认了允许低于阈值报价』记进结果；确认记录缺字段时**标注留痕缺口**
  （ADR-0013：留痕缺失不阻断计算，但不得伪造）。
* **废标判定**：系统**永不**作出。结果恒附 `disposition_note`：
  『是否构成废标以招标文件为准』。任何声明系统可判定废标的配置都是 FAIL。

六态语义沿用校验层（ADR-0008 五态 + ADR-0013 INFO）：

* **BLOCKED**：声明了 DECLARED（条款依据已登记）却内容为空——确认记录无法引用
  具体条款，留痕不可追溯（H-004 验收红线）。
* **FAIL**：说了但说错了——disposition 不在词表（含『系统可判定废标』）、
  阈值越界、阈值与 tol_lo 不一致、mode=NONE 与启用条款冲突、字段契约不全。
* **WARN**：未登记（UNKNOWN/缺字段）——闸门仍生效，但结果只能泛称
  『招标文件低价条款』并注明以招标文件为准，不得声称已完成条款级合规复核。
* **SKIP**：判据所需制品缺失（策略文件/不平衡条款缺失）——显式记录。
"""

from __future__ import annotations

from typing import Any, Mapping

from .cost_basis import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    CostBasisReport,
    _bad,
    _ok,
    _read,
)
from .unbalanced import SETTLEMENT_ADJUSTMENT

#: 判定边界词表——**唯一合法值 CONFIRM_ONLY**：系统只记录低价确认，
#: 废标判定以招标文件为准（H-004：不替用户作法律判断）。
DISPOSITION_VOCABULARY: tuple[str, ...] = ("CONFIRM_ONLY",)
DISPOSITION_CONFIRM_ONLY = "CONFIRM_ONLY"

#: 结果必须携带的确认留痕字段（H-004 验收：用户、时间、条款依据）。
REQUIRED_CONFIRMATION_FIELDS: tuple[str, ...] = (
    "confirmed_by", "confirmed_at", "clause_basis",
)

#: 声明模式词表（与 hidden_cost 保持一致）。
MODE_VOCABULARY: tuple[str, ...] = ("NONE", "DECLARED", "UNKNOWN")

#: 恒附在低价确认记录上的判定边界声明。
DISPOSITION_NOTE = (
    "系统仅记录低价确认，不作出废标判定；是否构成废标以招标文件为准（H-004）。"
)


class LowPricePolicyError(ValueError):
    """低价确认声明缺失或不足以支撑 H-004 留痕契约。"""


def check_low_price_policy(config_dir) -> CostBasisReport:
    """H-004：低价确认与废标风险留痕声明校验（LC-01～LC-05）。

    判据基准（ADR-0013）：条款依据声明为已登记（DECLARED）却无内容 → BLOCKED
    （留痕不可追溯）；判定边界/阈值/字段契约说错 → FAIL；未登记 → WARN
    （闸门仍生效，结果须注明『以招标文件为准』）；制品缺失 → SKIP。
    任一项 BLOCKED/FAIL → 不输出『已完成低价合规复核』类结论。
    """
    rep = CostBasisReport()
    policy = _read(config_dir, "project_quote_policy.json")
    if policy is None:
        rep.results.append(_bad(
            "LC-01", STATUS_SKIP,
            "项目报价策略缺失（project_quote_policy.json）——低价确认声明无从校验"))
        return rep

    clause = policy.get("unbalanced_clause")
    sec = policy.get("low_price_policy") or {}
    if not clause:
        rep.results.append(_bad(
            "LC-01", STATUS_SKIP,
            "不平衡报价条款未声明（unbalanced_clause 缺失）——低价确认声明无从关联，挂起"))
        return rep
    if not sec:
        rep.results.append(_bad(
            "LC-01", STATUS_WARN,
            "低价确认与废标风险留痕未声明（low_price_policy 缺失）——"
            "NEEDS_CONFIRMATION 产品闸门仍生效，但条款依据与判定边界未登记，"
            "结果只能提示『以招标文件为准』（H-004）"))
        return rep
    rep.results.append(_ok(
        "LC-01", "低价确认声明节存在（H-004），按阈值 / 判定边界 / 条款依据 / "
                 "字段契约分项校验"))

    # ---- LC-02 判定边界：区分「低价确认」与「废标判定」----
    disposition = sec.get("disposition")
    if disposition is None:
        rep.results.append(_bad(
            "LC-02", STATUS_WARN,
            "判定边界未显式声明——默认按 CONFIRM_ONLY 解释：系统只记录低价确认，"
            "不作出废标判定；结果须标注『以招标文件为准』（H-004）"))
    elif disposition not in DISPOSITION_VOCABULARY:
        rep.results.append(_bad(
            "LC-02", STATUS_FAIL,
            f"disposition={disposition!r} 不在词表 {list(DISPOSITION_VOCABULARY)}"
            "——声明系统可判定废标违反 H-004 红线：不替用户作法律判断"))
    else:
        rep.results.append(_ok(
            "LC-02", "判定边界：CONFIRM_ONLY——系统只记录低价确认，"
                     "废标判定以招标文件为准"))

    # ---- LC-03 低价阈值：合法性 + 与 C13 条款 tol_lo 一致性 ----
    threshold = sec.get("low_price_threshold")
    if threshold is None:
        rep.results.append(_bad(
            "LC-03", STATUS_WARN,
            "低价阈值未声明——按默认 0.5（报价/限价）解释，触发 NEEDS_CONFIRMATION 闸门"))
    elif not (isinstance(threshold, (int, float)) and 0 < float(threshold) < 1):
        rep.results.append(_bad(
            "LC-03", STATUS_FAIL,
            f"low_price_threshold={threshold!r} 须在 (0,1) 内"))
    else:
        tol_lo = clause.get("tol_lo") if isinstance(clause, Mapping) else None
        mechanism = clause.get("mechanism") if isinstance(clause, Mapping) else None
        threshold = float(threshold)
        if mechanism == SETTLEMENT_ADJUSTMENT and tol_lo is not None \
                and abs(threshold - float(tol_lo)) > 1e-9:
            rep.results.append(_bad(
                "LC-03", STATUS_FAIL,
                f"低价阈值 {threshold} 与 unbalanced_clause.tol_lo {tol_lo} 不一致"
                "——同一低价条款两个读数，确认记录引用会失真"))
        elif mechanism != SETTLEMENT_ADJUSTMENT:
            rep.results.append(_bad(
                "LC-03", STATUS_SKIP,
                f"mechanism={mechanism!r} 非 SETTLEMENT_ADJUSTMENT——"
                "tol_lo 语义不同，一致性校验挂起"))
        else:
            rep.results.append(_ok(
                "LC-03", f"低价阈值 {threshold} 与 C13 条款 tol_lo={tol_lo} 一致"))

    # ---- LC-04 条款依据留痕 ----
    mode = sec.get("mode")
    clause_basis = sec.get("clause_basis")
    if mode not in MODE_VOCABULARY:
        rep.results.append(_bad(
            "LC-04", STATUS_FAIL,
            f"low_price_policy.mode={mode!r} 不在词表 {list(MODE_VOCABULARY)}"))
    elif mode == "NONE":
        rep.results.append(_bad(
            "LC-04", STATUS_FAIL,
            "mode=NONE（无低价确认义务）与 unbalanced_clause.enabled 冲突——"
            "存在 C13 条款却声明无确认义务，H-004 留痕义务被绕过"))
    elif mode == "DECLARED":
        if not clause_basis:
            rep.results.append(_bad(
                "LC-04", STATUS_BLOCKED,
                "已声明条款依据已登记（DECLARED）但 clause_basis 为空——"
                "确认记录无法引用具体条款，H-004 留痕不可追溯"))
        else:
            rep.results.append(_ok(
                "LC-04", f"条款依据已登记：{clause_basis}"))
    else:  # UNKNOWN / 缺失
        rep.results.append(_bad(
            "LC-04", STATUS_WARN,
            "条款依据未登记（UNKNOWN）——确认记录只能泛指『招标文件低价条款』，"
            "结果须注明以招标文件为准，不得声称已完成条款级合规复核"))

    # ---- LC-05 确认记录字段契约（H-004 验收：记录用户、时间、条款依据）----
    fields = sec.get("confirmation_fields")
    if fields is None:
        rep.results.append(_bad(
            "LC-05", STATUS_WARN,
            "确认记录字段契约未声明（confirmation_fields 缺失）——运行时仍输出"
            "确认记录，但『用户/时间/条款依据』三字段未冻结，留痕口径无据"))
    elif not isinstance(fields, list) or not set(REQUIRED_CONFIRMATION_FIELDS) \
            .issubset(set(fields)):
        rep.results.append(_bad(
            "LC-05", STATUS_FAIL,
            f"confirmation_fields={fields!r} 未覆盖必填字段 "
            f"{list(REQUIRED_CONFIRMATION_FIELDS)}——H-004 要求结果记录"
            "用户、时间、条款依据"))
    else:
        rep.results.append(_ok(
            "LC-05", f"确认记录字段契约齐备：{list(REQUIRED_CONFIRMATION_FIELDS)}"))

    return rep


def build_low_price_confirmation(
    *,
    confirmed: bool,
    threshold: float,
    has_low_items: bool,
    confirmed_by: str | None = None,
    confirmed_at: str | None = None,
    clause_basis: str | None = None,
) -> dict[str, Any]:
    """构造低价确认留痕记录（H-004 运行时契约，供 API/结果层调用）。

    * ``confirmed=False`` 且存在低价项 → ``review_required=True``（必须人工复核，
      结果须显著标注，不能静默通过）；
    * ``confirmed=True`` 时缺确认人/确认时间/条款依据 → 不伪造、不阻断，把缺口
      写进 ``trace_gaps``（ADR-0013：留痕缺失不阻断，但必须显式标注）；
    * ``disposition`` 恒为 CONFIRM_ONLY——系统只记录确认，不作出废标判定。

    参数类型/阈值非法属程序或输入错误 → ``LowPricePolicyError``。
    """
    if not isinstance(confirmed, bool):
        raise LowPricePolicyError("confirmed 必须为布尔值")
    if not isinstance(threshold, (int, float)) or not 0 < float(threshold) < 1:
        raise LowPricePolicyError(
            f"low_price_threshold={threshold!r} 须在 (0,1) 内")
    review_required = bool(has_low_items) and not confirmed
    trace_gaps: list[str] = []
    if confirmed:
        if not confirmed_by:
            trace_gaps.append("未记录确认人（confirmed_by）")
        if not confirmed_at:
            trace_gaps.append("未记录确认时间（confirmed_at）")
    if confirmed and not clause_basis:
        trace_gaps.append(
            "条款依据未登记（clause_basis）——确认记录只能泛指招标文件低价条款")
    return {
        "confirmed": confirmed,
        "confirmed_by": confirmed_by,
        "confirmed_at": confirmed_at,
        "clause_basis": clause_basis,
        "threshold": float(threshold),
        "review_required": review_required,
        "disposition": DISPOSITION_CONFIRM_ONLY,
        "disposition_note": DISPOSITION_NOTE,
        "trace_gaps": trace_gaps,
    }
