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

    rep.results.append(_ok(
        "CT-01", "成本清单综合单价声明为含税成本（cost_input_incl_vat），"
                 "换算目标为不含税有效成本（cost_effective）"))

    # ---- CT-02 进项税率 ----
    if mode in ("FULL", "PARTIAL"):
        if rate is None:
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
        if ratio is None or not (0 < ratio < 1):
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

    return rep
