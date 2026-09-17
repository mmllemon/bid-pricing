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
