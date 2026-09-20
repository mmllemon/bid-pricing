"""T00-09 成本口径证明包 + T00-11 c_i 假设声明书的机器可执行校验。

六态语义（ADR-0008 五态 + ADR-0013 新增 **INFO**）：

* **FAIL / BLOCKED 区分**：数据违反 ≠ 声明缺失。成本来源写了词表外的值是
  **FAIL**（说了但说错了）；真正影响算式的前提缺失才是 **BLOCKED**（如格式）。
* **WARN**：声明齐全但尚未冻结、或存在**影响结论解释力**的缺口。
* **INFO**：留痕项缺失——**记录但无需任何行动**，不影响计算，仅供将来复核
  与责任划分（ADR-0013：台账不是关卡）。
* **SKIP**：判据所需制品不存在——显式记录，不静默通过。

**判断准则（ADR-0013）**：一个字段缺失会让**算式算不出或算错**，才配 BLOCKED；
只让结论**说不清出处**的，一律 INFO。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..money import money

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_WARN = "WARN"
STATUS_INFO = "INFO"
STATUS_SKIP = "SKIP"

#: T00-09 要求的八项分解——**键序即规范顺序**，改任一侧须同步两侧。
REQUIRED_COMPONENTS = (
    "labor", "material", "equipment", "subcontract",
    "management", "allocated_overhead", "tax_and_fee_treatment", "risk_reserve",
)


@dataclass
class CostCheckItem:
    rule_id: str
    status: str
    detail: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "status": self.status,
                "detail": self.detail, "evidence": list(self.evidence)}


@dataclass
class CostBasisReport:
    results: list[CostCheckItem] = field(default_factory=list)

    @property
    def blocking(self) -> list[CostCheckItem]:
        return [r for r in self.results
                if r.status in (STATUS_BLOCKED, STATUS_FAIL)]

    @property
    def status(self) -> str:
        return "BLOCKED" if self.blocking else "PASS"

    def by_rule(self, rule_id: str) -> CostCheckItem:
        return next(r for r in self.results if r.rule_id == rule_id)

    def to_dict(self) -> dict:
        summary = {}
        for r in self.results:
            summary[r.status] = summary.get(r.status, 0) + 1
        return {"status": self.status, "summary": summary,
                "results": [r.to_dict() for r in self.results]}


def _ok(rule: str, detail: str, ev=()) -> CostCheckItem:
    return CostCheckItem(rule, STATUS_PASS, detail, list(ev))


def _bad(rule: str, status: str, detail: str, ev=()) -> CostCheckItem:
    return CostCheckItem(rule, status, detail, list(ev))


def _read(config_dir: Path, fname: str) -> dict | None:
    p = Path(config_dir) / fname
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def check_cost_basis(config_dir: Path) -> CostBasisReport:
    """执行 T00-09 / T00-11 全部判据。"""
    rep = CostBasisReport()
    basis = _read(config_dir, "cost_basis_spec.json")
    assumption = _read(config_dir, "cost_assumption_spec.json")
    field_schema = _read(config_dir, "field_schema.json")

    # ---------------- T00-09 成本口径证明包 ----------------
    if basis is None:
        rep.results.append(_bad("CB-01", STATUS_SKIP,
                                "成本口径证明包缺失（cost_basis_spec.json）——"
                                "T00-09 未冻结，c_i 口径无据"))
    else:
        obj = basis.get("cost_object") or {}
        if obj.get("key") != "INDIVIDUAL":
            rep.results.append(_bad(
                "CB-01", STATUS_FAIL,
                f"成本对象应为 INDIVIDUAL（个别成本），实为 {obj.get('key')!r}——"
                "用社会平均成本当地板会把个别成本高于平均的项误判为必然亏损"))
        elif "不等于社会平均成本" not in (obj.get("declaration") or ""):
            rep.results.append(_bad(
                "CB-01", STATUS_FAIL,
                "未显式声明 C_individual ≠ C_market_average"))
        else:
            rep.results.append(_ok("CB-01", "成本对象 = 投标人自身个别成本，"
                                            "且已显式声明 ≠ 社会平均成本"))

        comps = basis.get("components") or []
        keys = [c.get("key") for c in comps]
        missing = [k for k in REQUIRED_COMPONENTS if k not in keys]
        extra = [k for k in keys if k not in REQUIRED_COMPONENTS]
        if missing or extra:
            rep.results.append(_bad(
                "CB-02", STATUS_FAIL,
                f"八项分解不完整：缺 {missing} 多 {extra}",
                [f"实为 {keys}"]))
        else:
            rep.results.append(_ok("CB-02", f"八项分解齐备（{len(keys)} 项）"))

        alloc = next((c for c in comps if c.get("key") == "allocated_overhead"), {})
        if not (alloc.get("allocation_rule") or "").strip():
            rep.results.append(_bad(
                "CB-03", STATUS_BLOCKED,
                "分摊费用未声明分摊基数与费率——未声明分摊规则的分摊额不得进 c_i"))
        else:
            rep.results.append(_ok("CB-03", "分摊规则已声明"))

        tax = next((c for c in comps if c.get("key") == "tax_and_fee_treatment"), {})
        if "不含增值税" not in (tax.get("declaration") or ""):
            rep.results.append(_bad(
                "CB-04", STATUS_FAIL,
                "税口径未声明为不含增值税——与 D08 / 2024 2.0.8 冲突"))
        else:
            rep.results.append(_ok("CB-04", "c_i 与 p_i 同为不含增值税口径"))

        risk = next((c for c in comps if c.get("key") == "risk_reserve"), {})
        decl = risk.get("declaration") or ""
        if "必须显式声明" not in decl:
            rep.results.append(_bad(
                "CB-05", STATUS_BLOCKED,
                "风险储备是否计入 c_i 未要求显式声明——计入与否改变 C4 地板高度，"
                "不得默认"))
        else:
            rep.results.append(_ok("CB-05", "风险储备计入口径已要求显式声明"))

    # ---------------- T00-11 c_i 假设声明书 ----------------
    if assumption is None:
        rep.results.append(_bad("AS-01", STATUS_SKIP,
                                "c_i 假设声明书缺失（cost_assumption_spec.json）"))
    else:
        three = assumption.get("three_elements") or {}
        src = three.get("source") or {}
        value = src.get("value")
        vocab = src.get("vocabulary") or []
        if value is None:
            rep.results.append(_bad(
                "AS-01", STATUS_INFO,
                "c_i 来源未登记（台账空缺）——**不影响计算**：c_i 的数值本身由"
                "字段字典的 missing_policy 把关，来源只决定将来能否说清出处。"
                "已按 ADR-0013 从 BLOCKED 降级：台账不是关卡"))
        elif value not in vocab:
            rep.results.append(_bad(
                "AS-01", STATUS_FAIL,
                f"c_i 来源 {value!r} 不在词表 {vocab} 内", [str(value)]))
        else:
            need = (src.get("required_when") or {}).get(value) or []
            rep.results.append(_ok(
                "AS-01", f"c_i 来源已声明：{value}（须附 {need}）"))
            # AS-02：证据齐备性——**逐项列出缺什么**，不笼统告警。
            # 交叉满足：附证已在其它受控制品里声明过的（如税口径由 CB-04 锁定），
            # 不再要求重复声明——「没说」和「在别处说过」必须区分开（ADR-0002）。
            declared = src.get("declared_evidence") or {}
            cross = {k: v for k, v in (src.get("cross_satisfied_by") or {}).items()
                     if not k.startswith("_")}
            satisfied, stale = [], []
            for k, rule_id in cross.items():
                hit = next((x for x in rep.results if x.rule_id == rule_id), None)
                if hit is not None and hit.status == STATUS_PASS:
                    satisfied.append(k)
                else:
                    stale.append(f"{k}→{rule_id}(未 PASS)")
            lack = [k for k in need
                    if k not in declared and k not in satisfied]
            ev = [f"须附全量：{need}", f"已附：{sorted(declared) or '无'}"]
            if satisfied:
                ev.append("交叉满足：" + "、".join(
                    f"{k}（由 {cross[k]} 锁定）" for k in satisfied))
            if stale:
                ev.append("交叉引用失效：" + "、".join(stale))
            if not need:
                rep.results.append(_ok("AS-02", f"来源 {value} 无强制附证要求"))
            elif lack:
                rep.results.append(_bad(
                    "AS-02", STATUS_INFO,
                    f"来源 {value} 的留痕项待补 {lack}——**不影响计算**，"
                    "仅在复核成本出处时需要（ADR-0013：留痕项不阻塞）", ev))
            else:
                rep.results.append(_ok(
                    "AS-02", f"来源 {value} 附证齐备：{sorted(declared)}", ev))

        fmt = three.get("format") or {}
        if fmt.get("value") not in (fmt.get("allowed") or []):
            rep.results.append(_bad(
                "AS-03", STATUS_FAIL,
                f"c_i 格式 {fmt.get('value')!r} 不在允许集合 {fmt.get('allowed')} 内"))
        elif field_schema:
            f = next((x for x in (field_schema.get("fields") or [])
                      if x.get("name") == "c_i"), None)
            if f is None:
                rep.results.append(_bad(
                    "AS-03", STATUS_FAIL,
                    "字段字典缺 c_i 字段——格式一致性无从校验"))
            elif (f.get("unit"), f.get("precision")) != ("元", 2):
                rep.results.append(_bad(
                    "AS-03", STATUS_FAIL,
                    f"c_i 字段口径与声明不一致：unit={f.get('unit')} "
                    f"precision={f.get('precision')}（应为 元 / 2）"))
            else:
                rep.results.append(_ok(
                    "AS-03", f"格式 {fmt['value']} 与字段字典 c_i 一致（元 / 2 位）"))
        else:
            rep.results.append(_bad("AS-03", STATUS_SKIP,
                                    "字段字典缺失，格式一致性未校验"))

        timing = three.get("freeze_timing") or {}
        if not (timing.get("value") or "").strip():
            rep.results.append(_bad("AS-04", STATUS_BLOCKED,
                                    "冻结时点未声明"))
        elif assumption.get("frozen_at") in (None, ""):
            rep.results.append(_bad(
                "AS-04", STATUS_WARN,
                "尚未冻结（冻结时点：Gate 0b 之前）——当前为未定态，"
                "冻结前 c_i 不得进入 C4/C6 约束"))
        else:
            rep.results.append(_ok("AS-04", f"已冻结于 {assumption['frozen_at']}"))

    return rep


# ======================================================================
# H-002 成本含税 → 有效成本转换声明（CT-*）
# ======================================================================
#
# 背景：成本清单综合单价是**含税成本单价**（cost_input_incl_vat），而比价/利润
# 口径是不含增值税（basis_declarations.cost_tax_scope = EXCL_VAT）。二者直接
# 相减无意义，必须先把含税成本换算为**不含税有效成本**（cost_effective）。
# 换算所需的两项输入——进项税率、进项税抵扣模式——缺失会让利润算式**算错**，
# 故按 ADR-0013 配 BLOCKED：声明缺失时阻断「最优利润」结论（H-002 验收标准）。

CREDIT_MODE_VOCABULARY: tuple[str, ...] = ("FULL", "PARTIAL", "NONE", "UNKNOWN")

#: 成本构成分解默认键（前端顺序即此）；人工进项税率为 0（无进项税可抵）。
COMPOSITION_KEYS: tuple[str, ...] = ("material", "equipment", "subcontract", "labor", "measure")
COMPOSITION_DEFAULT_LABELS: dict[str, str] = {
    "material": "材料", "equipment": "设备", "subcontract": "分包",
    "labor": "人工", "measure": "措施费",
}
#: 各构成默认进项税率（小数）：材料/设备 13%，分包/措施 9%，人工 0%。
COMPOSITION_DEFAULT_RATES: dict[str, float] = {
    "material": 0.13, "equipment": 0.13, "subcontract": 0.09,
    "labor": 0.00, "measure": 0.09,
}


def effective_cost_multiplier(
    vat_rate: float | None,
    credit_mode: str,
    credit_ratio: float | None = None,
) -> float | None:
    """含税 → 有效成本换算系数 k，``cost_effective = cost_input_incl_vat × k``。

    统一式：``k = 1 − vat_rate × credit_ratio / (1 + vat_rate)``
      FULL    → credit_ratio 恒为 1 → ``k = 1/(1+vat_rate)``（进项税全额抵扣）
      NONE    → 不可抵扣（简易计税/无进项票）→ ``k = 1``（含税即有效成本，**不需要税率**）
      PARTIAL → ``credit_ratio`` 必须显式声明（0 < ratio < 1）
      UNKNOWN → 返回 None：不可计算，调用方不得据此输出利润结论

    模式不在词表内属程序错误 → ``ValueError``（不静默返回 None 掩盖 Bug）；
    输入不足（税率/比例缺失）→ 返回 None（业务未声明，不是程序错误）。
    """
    if credit_mode not in CREDIT_MODE_VOCABULARY:
        raise ValueError(
            f"credit_mode 须在 {list(CREDIT_MODE_VOCABULARY)}，收到 {credit_mode!r}")
    if credit_mode == "UNKNOWN":
        return None
    if credit_mode == "NONE":
        return 1.0
    if vat_rate is None:
        return None
    if credit_mode == "FULL":
        ratio = 1.0
    else:  # PARTIAL
        if credit_ratio is None:
            return None
        ratio = credit_ratio
    return 1.0 - vat_rate * ratio / (1.0 + vat_rate)


def validate_cost_composition(composition) -> tuple[bool, float | None, str]:
    """校验成本构成分解（分项多税率精算的输入）。

    返回 ``(ok, derived_credit_ratio, detail)``：
    * ``ok`` —— 占比求和≈1、各项 ``proportion∈[0,1]`` 且 ``input_vat_rate∈[0,1]``；
    * ``derived_credit_ratio`` —— 可抵扣进项税的成本占比（proportion 之和 where rate>0）；
      即模型旧的 ``credit_ratio`` 在分项口径下的精确等价量；
    * ``detail`` —— 不合法时的原因（供 BLOCKED 文案点名）。

    无构成 / 空 → ``(False, None, "成本构成缺失")``（由调用方决定走旧单税率路径）。
    """
    if not composition:
        return False, None, "成本构成缺失"
    total = 0.0
    credit = 0.0
    for c in composition:
        key = c.get("key") or c.get("label") or "?"
        p = c.get("proportion")
        r = c.get("input_vat_rate")
        if p is None or r is None:
            return False, None, f"{key} 须同时给出 proportion 与 input_vat_rate"
        if not (0 <= float(p) <= 1):
            return False, None, f"{key} 占比越界（须 0~1）：{p}"
        if not (0 <= float(r) <= 1):
            return False, None, f"{key} 进项税率越界（须 0~1）：{r}"
        total += float(p)
        if float(r) > 0:
            credit += float(p)
    if abs(total - 1.0) > 1e-6:
        return False, None, f"各项占比之和须为 1.00，当前 {total:.4f}"
    return True, round(credit, 6), ""


def effective_cost_multiplier_from_composition(composition) -> float | None:
    """分项多税率精确换算系数。

    每个构成 j 带 ``proportion``（含税成本占比）与 ``input_vat_rate``（该构成进项税率），
    则含税成本中嵌入的进项税 = ``Σ_j p_j × r_j/(1+r_j)``，故：

        k = 1 − Σ_j p_j × r_j/(1+r_j)

    对任意段数、任意税率**严格精确**（不再像旧单税率 PARTIAL 那样只在加权意义下近似）。
    人工（r=0）自然不贡献抵扣；材料/设备/分包/措施按各自真实税率除税。
    构成非法（见 ``validate_cost_composition``）→ 返回 None（业务未声明，非程序错误）。
    """
    ok, _, _ = validate_cost_composition(composition)
    if not ok:
        return None
    k = 1.0 - sum(
        float(c["proportion"]) * float(c["input_vat_rate"]) / (1.0 + float(c["input_vat_rate"]))
        for c in composition)
    return round(k, 12)


def effective_cost(
    cost_input_incl_vat: float | None,
    vat_rate: float | None,
    credit_mode: str,
    credit_ratio: float | None = None,
) -> float | None:
    """含税成本单价 → 不含税有效成本（元，2 位）；不可计算时返回 None。"""
    k = effective_cost_multiplier(vat_rate, credit_mode, credit_ratio)
    if k is None or cost_input_incl_vat is None:
        return None
    return round(cost_input_incl_vat * k, 2)


def check_cost_input_tax(config_dir: Path) -> CostBasisReport:
    """H-002：成本含税 → 有效成本转换声明校验（CT-01~CT-05）。

    判据基准（ADR-0013）：进项税率/抵扣模式缺失会让**利润算式算错**
    （含税 c_i 与不含税 p_i 直接相减无意义）——配 BLOCKED；
    说了但说错了（税率不在 (0,1]、模式不在词表）——FAIL；
    模式未定时税率是否必需无从判定——SKIP（显式记录，不编造）。
    任一项 BLOCKED/FAIL → 不输出「最优利润」结论。
    """
    rep = CostBasisReport()
    policy = _read(config_dir, "project_quote_policy.json")
    if policy is None:
        rep.results.append(_bad(
            "CT-01", STATUS_SKIP,
            "项目报价策略缺失（project_quote_policy.json）——转换声明无从校验"))
        return rep
    sec = policy.get("cost_input_tax_policy") or {}
    if not sec:
        rep.results.append(_bad(
            "CT-01", STATUS_BLOCKED,
            "project_quote_policy.json 缺 cost_input_tax_policy——含税成本→有效成本"
            "转换未声明，利润结论无定义（H-002）"))
        return rep

    rate = sec.get("cost_input_vat_rate")
    mode = sec.get("input_vat_credit_mode")
    ratio = sec.get("credit_ratio")
    composition = sec.get("cost_composition") or sec.get("cost_compose")
    comp_ok, comp_cr, comp_detail = (
        validate_cost_composition(composition) if composition else (False, None, ""))

    rep.results.append(_ok(
        "CT-01", "成本清单综合单价声明为含税成本（cost_input_incl_vat），"
                 "换算目标为不含税有效成本（cost_effective）"))

    # ---- CT-02 进项税率 ----
    if mode in ("FULL", "PARTIAL"):
        if composition is not None:
            if comp_ok:
                rep.results.append(_ok(
                    "CT-02", f"成本构成已分项声明进项税率（可抵扣占比 {comp_cr}），"
                             "分项多税率精算覆盖 CT-02/CT-04"))
            else:
                rep.results.append(_bad(
                    "CT-02", STATUS_BLOCKED,
                    f"成本构成（cost_composition）不合法——{comp_detail}"))
        elif rate is None:
            rep.results.append(_bad(
                "CT-02", STATUS_BLOCKED,
                f"抵扣模式 {mode} 下进项税率未声明——含税成本无法换算为不含税"
                "有效成本，『最优利润』结论被阻断（H-002）"))
        elif not (0 < rate <= 1):
            rep.results.append(_bad(
                "CT-02", STATUS_FAIL,
                f"cost_input_vat_rate={rate!r} 须在 (0,1] 内"))
        else:
            rep.results.append(_ok("CT-02", f"进项税率已声明：{rate}"))
    elif mode == "NONE":
        if rate is None:
            rep.results.append(_ok(
                "CT-02", "抵扣模式 NONE：有效成本=含税成本，无需税率"))
        elif 0 < rate <= 1:
            rep.results.append(_ok(
                "CT-02", f"进项税率已声明（NONE 下仅供留痕）：{rate}"))
        else:
            rep.results.append(_bad(
                "CT-02", STATUS_FAIL,
                f"cost_input_vat_rate={rate!r} 须在 (0,1] 内"))
    else:  # UNKNOWN / 缺失
        rep.results.append(_bad(
            "CT-02", STATUS_SKIP,
            "抵扣模式未定，税率是否必需无从判定——挂起（由 CT-03 阻断）"))

    # ---- CT-03 抵扣模式 ----
    if mode is None or mode == "UNKNOWN":
        rep.results.append(_bad(
            "CT-03", STATUS_BLOCKED,
            "input_vat_credit_mode 未声明（UNKNOWN）——含税成本能否抵扣、抵扣多少"
            "不可知，『最优利润』结论被阻断（H-002）"))
    elif mode not in CREDIT_MODE_VOCABULARY:
        rep.results.append(_bad(
            "CT-03", STATUS_FAIL,
            f"input_vat_credit_mode={mode!r} 不在词表 "
            f"{list(CREDIT_MODE_VOCABULARY)}"))
    else:
        rep.results.append(_ok("CT-03", f"抵扣模式：{mode}"))

    # ---- CT-04 部分抵扣比例 ----
    if mode == "PARTIAL":
        if composition is not None:
            if comp_ok:
                rep.results.append(_ok(
                    "CT-04", f"成本构成已声明（可抵扣占比 {comp_cr}），"
                             "分项多税率精算即精确表达『可抵扣成本占比』"))
            else:
                rep.results.append(_bad(
                    "CT-04", STATUS_BLOCKED,
                    f"成本构成（cost_composition）不合法——{comp_detail}"))
        elif ratio is None or not (0 < ratio < 1):
            rep.results.append(_bad(
                "CT-04", STATUS_BLOCKED,
                "PARTIAL 模式必须显式声明 credit_ratio ∈ (0,1)——"
                "否则有效成本不可计算"))
        else:
            rep.results.append(_ok("CT-04", f"抵扣比例：{ratio}"))
    elif mode in ("FULL", "NONE"):
        rep.results.append(_ok(
            "CT-04", f"模式 {mode} 无需抵扣比例（FULL=1 / NONE=0）"))
    else:
        rep.results.append(_bad(
            "CT-04", STATUS_SKIP, "模式未定，抵扣比例判定挂起"))

    # ---- CT-05 换算可计算性兜底 ----
    if mode not in CREDIT_MODE_VOCABULARY:
        rep.results.append(_bad(
            "CT-05", STATUS_SKIP, "模式非法（CT-03 已 FAIL），换算系数判定挂起"))
    elif mode == "UNKNOWN" or mode is None:
        rep.results.append(_bad(
            "CT-05", STATUS_SKIP, "模式未定，换算系数挂起（由 CT-03 阻断）"))
    elif effective_cost_multiplier(rate, mode, ratio) is None:
        rep.results.append(_bad(
            "CT-05", STATUS_BLOCKED,
            "当前声明下换算系数不可计算——利润结论必须挂起"))
    else:
        rep.results.append(_ok("CT-05", "换算系数可计算"))

    # ---- CT-06 词表声明 ↔ 实现常量 跨来源对账（★ 双向）----
    spec = load_cost_input_tax_spec(config_dir)
    if spec is None:
        rep.results.append(_bad(
            "CT-06", STATUS_SKIP,
            f"机制制品缺失（{COST_INPUT_TAX_SPEC_FILENAME}）——词表声明无从对账"))
    else:
        declared = declared_credit_modes(spec)
        only_spec = sorted(set(declared) - set(CREDIT_MODE_VOCABULARY))
        only_code = sorted(set(CREDIT_MODE_VOCABULARY) - set(declared))
        if only_spec or only_code:
            rep.results.append(_bad(
                "CT-06", STATUS_FAIL,
                f"抵扣模式词表两处不一致——制品声明独有 {only_spec or '无'}，"
                f"实现常量独有 {only_code or '无'}。判定器读的是实现常量，"
                "制品改了代码没改即静默失效（DV-01 同族）"))
        else:
            rep.results.append(_ok(
                "CT-06", f"词表一致（{len(declared)} 项）：{list(declared)}"))

    return rep


# ======================================================================
# H-002 机制制品读取与**唯一换算入口**
# ======================================================================
#
# 词表、换算式、判据已搬入 config/cost_input_tax_spec.json（机制住制品）。
# 代码里保留 CREDIT_MODE_VOCABULARY 作**实现侧副本**：判定函数要保持纯
# （不依赖 config_dir），词表是它的输入契约。副本由 CT-06 **双向**对账钉住
# —— 单向比对会漏掉「实现多判一个模式而制品没声明」。

COST_INPUT_TAX_SPEC_FILENAME = "cost_input_tax_spec.json"

#: 税口径标签（制品 field_names.cost_tax_scope.vocabulary）
INCL_VAT = "INCL_VAT"
EXCL_VAT = "EXCL_VAT"


def load_cost_input_tax_spec(config_dir: Path | str) -> dict | None:
    """读 H-002 机制制品；不存在返回 None（由 CT-06 判 SKIP，不静默通过）。"""
    return _read(Path(config_dir), COST_INPUT_TAX_SPEC_FILENAME)


def declared_credit_modes(spec: Mapping[str, Any] | None) -> tuple[str, ...]:
    """制品声明的抵扣模式键集合（键序即声明序）。"""
    return tuple(((spec or {}).get("credit_mode_vocabulary") or {}).keys())


def read_cost_input_tax_policy(config_dir: Path | str) -> dict:
    """读项目级取值段；文件或段落缺失均返回 ``{}``（调用方须视为未声明）。"""
    policy = _read(Path(config_dir), "project_quote_policy.json")
    if policy is None:
        return {}
    return dict(policy.get("cost_input_tax_policy") or {})


@dataclass(frozen=True)
class CostAdjustment:
    """单项换算痕迹（制品 field_names.cost_adjustment_trace）。"""

    item_id: str
    cost_unit_price_input: float
    multiplier: float
    cost_unit_price_effective: float

    def to_dict(self) -> dict:
        return {"item_id": self.item_id,
                "cost_unit_price_input": self.cost_unit_price_input,
                "multiplier": self.multiplier,
                "cost_unit_price_effective": self.cost_unit_price_effective}


@dataclass(frozen=True)
class EffectiveCostPlan:
    """换算方案。

    ``PASS`` ⇒ ``items`` 内 ``c_i`` 已是**不含税有效成本**，且每项带
    ``cost_tax_scope=EXCL_VAT``（这正是二次换算防护的机械依据）。
    ``BLOCKED`` ⇒ ``reason`` 必须点名**缺哪一项**以及缺了会让哪个数字失真。
    """

    status: str
    reason: str
    multiplier: float | None
    items: tuple[dict, ...]
    trace: tuple[CostAdjustment, ...] = ()

    @property
    def blocking(self) -> bool:
        return self.status == STATUS_BLOCKED

    def trace_dicts(self) -> list[dict]:
        return [t.to_dict() for t in self.trace]


def build_effective_costs(
    items: Sequence[Mapping[str, Any]],
    config_dir: Path | str | None = None,
    *,
    policy_section: Mapping[str, Any] | None = None,
) -> EffectiveCostPlan:
    """含税成本单价 → 不含税有效成本（H-002 的**唯一换算入口**）。

    ``policy_section`` 显式给出时优先于从 ``config_dir`` 读（测试注入用）。
    返回的 ``items`` 是**新建的 dict 序列**，不修改调用方传入的数据。

    阻断条件（任一成立即 BLOCKED，理由点名缺哪一项）：
      ① 策略段整体缺失；② 抵扣模式缺失或 UNKNOWN；③ 模式非法（词表外）；
      ④ 模式需要税率而税率缺失/越界；⑤ PARTIAL 而比例缺失/越界；
      ⑥ 换算系数不可计算（兜底）；⑦ 待换算项已标 EXCL_VAT（CT-07 二次换算防护）。
    """
    sec = (dict(policy_section) if policy_section is not None
           else read_cost_input_tax_policy(config_dir))
    if not sec:
        return EffectiveCostPlan(
            STATUS_BLOCKED,
            "成本税口径未定：project_quote_policy.json 缺 cost_input_tax_policy 段——"
            "成本清单综合单价为含税（INCL_VAT），换算为不含税有效成本所需的口径声明"
            "完全缺失，毛利与目标函数无定义（H-002）",
            None, tuple(dict(r) for r in items))

    mode = sec.get("input_vat_credit_mode")
    rate = sec.get("cost_input_vat_rate")
    ratio = sec.get("credit_ratio")
    composition = sec.get("cost_composition") or sec.get("cost_compose")

    if mode is None or mode == "UNKNOWN":
        return EffectiveCostPlan(
            STATUS_BLOCKED,
            "成本税口径未定：input_vat_credit_mode 未声明（UNKNOWN）——含税成本能否抵扣、"
            "能抵扣多少不可知，无法把含税 c_i 换算为不含税有效成本，"
            "『最优利润』与『单项毛利』结论被阻断（H-002 / CT-03）",
            None, tuple(dict(r) for r in items))
    if mode not in CREDIT_MODE_VOCABULARY:
        return EffectiveCostPlan(
            STATUS_BLOCKED,
            f"成本税口径声明非法：input_vat_credit_mode={mode!r} 不在词表 "
            f"{list(CREDIT_MODE_VOCABULARY)}（CT-03 FAIL——说了但说错，不降级放行）",
            None, tuple(dict(r) for r in items))

    # ---- 换算系数 k：优先用成本构成（分项多税率精算），否则回退旧单税率 ----
    derived_credit_ratio: float | None = None
    basis_desc = ""
    if mode == "NONE":
        k = 1.0
        basis_desc = "（NONE 模式：含税即有效成本，不读进项税率）"
    else:
        comp_ok, comp_cr, comp_detail = validate_cost_composition(composition)
        if composition is not None:
            if not comp_ok:
                return EffectiveCostPlan(
                    STATUS_BLOCKED,
                    f"成本税口径未定：成本构成（cost_composition）不合法——{comp_detail}"
                    "，无法做分项多税率换算（H-002 / CT-04）",
                    None, tuple(dict(r) for r in items))
            k = effective_cost_multiplier_from_composition(composition)
            derived_credit_ratio = comp_cr
            basis_desc = (f"（分项多税率精算：可抵扣占比 {comp_cr}；"
                          f"材料/设备/分包/人工/措施按各自进项税率除税）")
        else:
            # 旧单税率路径（无构成时回退，保证向后兼容既有配置/CLI）
            if rate is None:
                return EffectiveCostPlan(
                    STATUS_BLOCKED,
                    f"成本税口径未定：抵扣模式 {mode} 下 cost_input_vat_rate（进项税率）未声明——"
                    "含税成本无法除税换算为不含税有效成本，毛利与目标函数被阻断（H-002 / CT-02）",
                    None, tuple(dict(r) for r in items))
            if not (0 < float(rate) <= 1):
                return EffectiveCostPlan(
                    STATUS_BLOCKED,
                    f"成本税口径声明非法：cost_input_vat_rate={rate!r} 须在 (0,1] 内，"
                    "如 0.13=13%（CT-02 FAIL）",
                    None, tuple(dict(r) for r in items))
            eff_ratio = 1.0 if mode == "FULL" else ratio
            if mode == "PARTIAL" and (eff_ratio is None or not (0 < float(eff_ratio) < 1)):
                return EffectiveCostPlan(
                    STATUS_BLOCKED,
                    "成本税口径未定：PARTIAL 模式须显式声明 credit_ratio ∈ (0,1)"
                    f"（当前 {ratio!r}）——它表示『可抵扣成本（如货物）占含税成本的比重』，"
                    "缺了有效成本不可计算（CT-04）",
                    None, tuple(dict(r) for r in items))
            k = effective_cost_multiplier(
                float(rate), str(mode),
                float(eff_ratio) if eff_ratio is not None else None)
            derived_credit_ratio = (1.0 if mode == "FULL"
                                    else (float(ratio) if ratio is not None else None))
            basis_desc = (f"(进项税率 {rate}"
                          + (f"，可抵扣成本占比 {ratio}" if mode == "PARTIAL" else "")
                          + ")")
    if k is None:
        return EffectiveCostPlan(
            STATUS_BLOCKED,
            "成本税口径未定：当前声明组合下换算系数不可计算——利润结论必须挂起（CT-05）",
            None, tuple(dict(r) for r in items))

    # ---- CT-07 二次换算防护（★ 靠口径标记机械判定，不靠调用顺序的君子协定）----
    # 无成本项（c_i is None）没有可换算的口径，不参与本判据。
    already = sorted(str(r.get("item_id")) for r in items
                     if r.get("cost_tax_scope") == EXCL_VAT and r.get("c_i") is not None)
    if already:
        shown = ", ".join(already[:8]) + ("…" if len(already) > 8 else "")
        return EffectiveCostPlan(
            STATUS_BLOCKED,
            "拒绝二次换算：以下项的 cost_tax_scope 已是 EXCL_VAT（不含税口径），"
            f"再乘一次换算系数会让成本静默偏小、毛利静默偏大：{shown}（CT-07）",
            None, tuple(dict(r) for r in items))

    out: list[dict] = []
    trace: list[CostAdjustment] = []
    for row in items:
        new_row = dict(row)
        new_row["cost_tax_scope"] = EXCL_VAT
        raw = row.get("c_i")
        if raw is None:
            new_row["cost_unit_price_input"] = None
            out.append(new_row)
            continue
        effective = money(float(raw) * k)
        new_row["cost_unit_price_input"] = float(raw)
        new_row["c_i"] = effective
        out.append(new_row)
        trace.append(CostAdjustment(str(row.get("item_id")), float(raw), k, effective))

    return EffectiveCostPlan(
        STATUS_PASS,
        f"已按 {mode}{basis_desc} 换算 {len(trace)} 项，系数 k={k:.8f}；"
        "c_i 已由含税替换为不含税有效成本",
        k, tuple(out), tuple(trace))
