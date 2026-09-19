"""H-003 固定/隐形成本模型分列校验（HC-01～HC-06）。

隐形成本（业务费、公司管理费、融资费等）必须**显式建模**，不得默认为 0：
不纳入则高估利润，全部重复摊入每个清单则低估利润。按既有裁定（
CODE_REVIEW §2.4、PRODUCT_ROADMAP §5）分为三类，**一列一判据**：

* ``direct`` 可直接归属某清单 → 加入该清单有效成本 ``c_i`` → **影响单项最优分配**；
* ``allocable`` 可按规则分摊到清单 → 按**明确基数 + 费率**分摊进 ``c_i`` →
  **影响单项最优分配**；
* ``project_fixed`` 项目整体固定费用 → ``enters_fixed_pretax=true`` 计入
  **FIXED_PRETAX 桶**（减少总竞争预算）；``=false`` 单列扣减（**只影响利润**，
  不改变清单间排序）。

六态语义沿用校验层（ADR-0008 五态 + ADR-0013 INFO）：

* **BLOCKED**：缺失会让**算式算错**——已声明 DECLARED 但缺分摊基数/费率/
  金额/载体/桶归属。任一缺，相应算式（``c_i``、固定税前、利润扣减）算不出或算错。
* **FAIL**：写了但与词表或恒等式冲突——模式不在词表、基数不在词表、
  费率越界、FIXED_PRETAX 合计与构成之和不等。
* **WARN**：列未声明（UNKNOWN）——算式可算，但利润是**清单贡献利润**
  （不含隐形成本），报告层必须列为「未纳入成本的风险」，不得称为项目净利润
  （CODE_REVIEW §2.4：不能默认为 0 后不提示）。
* **SKIP**：判据所需制品不存在——显式记录，不静默通过。
"""

from __future__ import annotations

import json
from pathlib import Path

from .cost_basis import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    CostBasisReport,
    CostCheckItem,
    _bad,
    _ok,
    _read,
)

#: 每列的声明模式词表。NONE=明确无此列成本；DECLARED=存在且声明完整；
#: UNKNOWN=未声明（按「未纳入」口径解释，配 WARN）。
COLUMN_MODE_VOCABULARY: tuple[str, ...] = ("NONE", "DECLARED", "UNKNOWN")

#: 可分摊成本的分摊基数词表（CODE_REVIEW §2.4 allocation_basis）。
#: FIXED_PROJECT 不属于分摊基数——项目整体固定走 project_fixed 列，不在此表。
ALLOCATION_BASIS_VOCABULARY: tuple[str, ...] = (
    "DIRECT", "LABOR", "DIRECT_COST", "OUTPUT",
)

#: H-003 要求的三类分列——**键序即规范顺序**，缺一即违反「分列可追溯」。
REQUIRED_COLUMNS: tuple[str, ...] = ("direct", "allocable", "project_fixed")


def _mode_of(col: dict | None) -> str | None:
    return (col or {}).get("mode")


def check_hidden_cost_policy(config_dir: Path) -> CostBasisReport:
    """H-003：固定/隐形成本三类分列声明校验（HC-01～HC-06）。

    判据基准（ADR-0013）：声明了 DECLARED 却缺算式前提 → BLOCKED
    （算式算错）；说了但说错了 → FAIL；整列未声明 → WARN（利润解释力受限，
    报告层必须标注「清单贡献利润」，不阻断计算——与 CT-* 的 BLOCKED 不同：
    进项税率缺失是**算式本身**无定义，隐形成本未声明是**口径不完整**）。
    """
    rep = CostBasisReport()
    policy = _read(config_dir, "project_quote_policy.json")
    if policy is None:
        rep.results.append(_bad(
            "HC-01", STATUS_SKIP,
            "项目报价策略缺失（project_quote_policy.json）——隐形成本声明无从校验"))
        return rep

    sec = policy.get("hidden_cost_policy") or {}
    if not sec:
        rep.results.append(_bad(
            "HC-01", STATUS_WARN,
            "隐形成本未声明（hidden_cost_policy 缺失）——当前利润为清单贡献利润"
            "（不含隐形成本），报告层必须列为『未纳入成本的风险』，不得称为项目"
            "净利润（H-003；CODE_REVIEW §2.4 不得默认为 0 后不提示）"))
        return rep

    rep.results.append(_ok(
        "HC-01", "隐形成本声明节存在（H-003），按 direct / allocable / "
                 "project_fixed 分列校验"))

    # ---- HC-02 分列结构（H-003 验收：三类分列可追溯）----
    missing_cols = [k for k in REQUIRED_COLUMNS if k not in sec]
    if missing_cols:
        rep.results.append(_bad(
            "HC-02", STATUS_FAIL,
            f"隐形成本未按三类分列：缺 {missing_cols}——"
            "违反 H-003『直接成本、分摊成本、项目固定成本分列可追溯』",
            [f"实为 {sorted(sec)}"]))
    else:
        rep.results.append(_ok("HC-02", f"三类分列齐备（{', '.join(REQUIRED_COLUMNS)}）"))

    # ---- HC-03 可直接归属成本（direct）----
    direct = sec.get("direct") or {}
    mode = _mode_of(direct)
    if mode in (None, "UNKNOWN"):
        rep.results.append(_bad(
            "HC-03", STATUS_WARN,
            "可直接归属成本未声明（UNKNOWN）——若存在可归属清单的隐形成本而未计入，"
            "c_i 将低估、最优分配会偏离；声明前利润按『未纳入』口径解释"))
    elif mode not in COLUMN_MODE_VOCABULARY:
        rep.results.append(_bad(
            "HC-03", STATUS_FAIL,
            f"direct.mode={mode!r} 不在词表 {list(COLUMN_MODE_VOCABULARY)}"))
    elif mode == "DECLARED":
        carrier = direct.get("carrier")
        if not carrier:
            rep.results.append(_bad(
                "HC-03", STATUS_BLOCKED,
                "已声明存在可直接归属成本但未声明归属载体（carrier）——"
                "c_i 无法计入该部分成本，最优分配算错"))
        else:
            rep.results.append(_ok(
                "HC-03", f"可直接归属成本已声明，归属载体：{carrier}"))
    else:  # NONE
        rep.results.append(_ok("HC-03", "无可直接归属成本（NONE）"))

    # ---- HC-04 可分摊成本（allocable）----
    alloc = sec.get("allocable") or {}
    mode = _mode_of(alloc)
    if mode in (None, "UNKNOWN"):
        rep.results.append(_bad(
            "HC-04", STATUS_WARN,
            "可分摊成本未声明（UNKNOWN）——若存在按基数分摊的隐形成本而未计入，"
            "c_i 将低估；声明前利润按『未纳入』口径解释"))
    elif mode not in COLUMN_MODE_VOCABULARY:
        rep.results.append(_bad(
            "HC-04", STATUS_FAIL,
            f"allocable.mode={mode!r} 不在词表 {list(COLUMN_MODE_VOCABULARY)}"))
    elif mode == "DECLARED":
        basis = alloc.get("basis")
        rate = alloc.get("rate")
        if basis is None:
            rep.results.append(_bad(
                "HC-04", STATUS_BLOCKED,
                "已声明可分摊成本但未声明分摊基数（basis）——分摊额 = 基数 × 费率，"
                "基数缺失算式算不出"))
        elif basis not in ALLOCATION_BASIS_VOCABULARY:
            rep.results.append(_bad(
                "HC-04", STATUS_FAIL,
                f"allocable.basis={basis!r} 不在词表 "
                f"{list(ALLOCATION_BASIS_VOCABULARY)}（FIXED_PROJECT 属项目固定列）"))
        elif rate is None:
            rep.results.append(_bad(
                "HC-04", STATUS_BLOCKED,
                "已声明可分摊成本但未声明分摊费率（rate）——分摊额算不出"))
        elif not (0 < rate <= 1):
            rep.results.append(_bad(
                "HC-04", STATUS_FAIL,
                f"allocable.rate={rate!r} 须在 (0,1] 内"))
        else:
            rep.results.append(_ok(
                "HC-04", f"可分摊成本已声明：基数 {basis}、费率 {rate}"))
    else:  # NONE
        rep.results.append(_ok("HC-04", "无可分摊成本（NONE）"))

    # ---- HC-05 项目固定成本（project_fixed）----
    pf = sec.get("project_fixed") or {}
    mode = _mode_of(pf)
    if mode in (None, "UNKNOWN"):
        rep.results.append(_bad(
            "HC-05", STATUS_WARN,
            "项目固定成本未声明（UNKNOWN）——若存在业务费/公司管理费等而未计入，"
            "利润将高估；声明前利润按『清单贡献利润』口径解释"))
    elif mode not in COLUMN_MODE_VOCABULARY:
        rep.results.append(_bad(
            "HC-05", STATUS_FAIL,
            f"project_fixed.mode={mode!r} 不在词表 {list(COLUMN_MODE_VOCABULARY)}"))
    elif mode == "DECLARED":
        amount = pf.get("amount")
        enters = pf.get("enters_fixed_pretax")
        if amount is None:
            rep.results.append(_bad(
                "HC-05", STATUS_BLOCKED,
                "已声明项目固定成本但金额（amount）缺失——计入 FIXED_PRETAX "
                "或利润扣减都算不出"))
        elif not isinstance(amount, (int, float)) or amount < 0:
            rep.results.append(_bad(
                "HC-05", STATUS_FAIL,
                f"project_fixed.amount={amount!r} 须为非负数值"))
        if enters is None:
            rep.results.append(_bad(
                "HC-05", STATUS_BLOCKED,
                "已声明项目固定成本但未声明是否计入 FIXED_PRETAX 桶"
                "（enters_fixed_pretax）——总竞争预算口径不明确"
                "（H-003 核心验收：明确哪些影响总竞争预算、哪些只影响利润）"))
        elif not isinstance(enters, bool):
            rep.results.append(_bad(
                "HC-05", STATUS_FAIL,
                f"project_fixed.enters_fixed_pretax={enters!r} 须为布尔值"))
        if amount is not None and isinstance(amount, (int, float)) and amount >= 0 \
                and isinstance(enters, bool):
            rep.results.append(_ok(
                "HC-05",
                f"项目固定成本已声明：金额 {amount:,.2f}，"
                + ("计入 FIXED_PRETAX 桶（影响总竞争预算）"
                   if enters else "单列扣减（只影响利润，不改变清单间排序）"),
                [f"enters_fixed_pretax={enters}"]))
    else:  # NONE
        rep.results.append(_ok("HC-05", "无项目固定成本（NONE）"))

    # ---- HC-06 FIXED_PRETAX 桶构成可追溯（哪些影响总竞争预算）----
    if _mode_of(pf) == "DECLARED" and pf.get("enters_fixed_pretax") is True:
        fp = policy.get("fixed_pretax_policy") or {}
        if not fp:
            rep.results.append(_bad(
                "HC-06", STATUS_SKIP,
                "项目固定成本声明计入 FIXED_PRETAX，但 fixed_pretax_policy 缺失——"
                "桶联动无从校验"))
        elif fp.get("mode") != "FIXED_CURRENT_VALUES":
            rep.results.append(_bad(
                "HC-06", STATUS_SKIP,
                f"fixed_pretax_policy.mode={fp.get('mode')!r} 非 "
                "FIXED_CURRENT_VALUES——构成合计校验挂起"))
        else:
            measure = fp.get("measure_fee")
            reg = fp.get("regulatory_fee")
            total = fp.get("fixed_pretax")
            if measure is None or reg is None or total is None:
                rep.results.append(_bad(
                    "HC-06", STATUS_SKIP,
                    "fixed_pretax_policy 未全量声明 measure_fee/regulatory_fee/"
                    "fixed_pretax——合计校验挂起"))
            else:
                expected = round(float(measure) + float(reg) + float(pf["amount"]), 2)
                actual = round(float(total), 2)
                if actual != expected:
                    rep.results.append(_bad(
                        "HC-06", STATUS_FAIL,
                        f"固定税前合计 {actual:,.2f} ≠ 构成之和 {expected:,.2f}"
                        f"（措施费 {measure:,.2f} + 规费 {reg:,.2f} + 项目固定 "
                        f"{pf['amount']:,.2f}）——影响总竞争预算的桶构成不可追溯"))
                else:
                    rep.results.append(_ok(
                        "HC-06", "FIXED_PRETAX 桶构成可追溯：合计 = 措施费 + 规费 "
                                 "+ 计入桶的项目固定成本"))
    else:
        rep.results.append(_bad(
            "HC-06", STATUS_SKIP,
            "项目固定成本未声明计入 FIXED_PRETAX 桶——桶联动校验挂起"))

    return rep
