"""T00-10A / T00-10B 结算工程量 q1 假设声明书的机器可执行校验。

与 :mod:`bidpricing.validation.cost_basis`（c_i）同构，但**判据重心不同**：

* c_i 是已发生事实 → 判「来源可信度」（谁说的）；
* q1 是未发生的预测 → 判「不确定性的表达」（取点值还是区间），以及点值假设
  是否承担了相应的敏感性义务。

五态语义沿用校验层（ADR-0008）；附证交叉满足沿用 ADR-0011。
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
    _bad,
    _ok,
    _read,
)

#: format → 字段字典中必须存在的字段。**键序即规范顺序**。
FORMAT_FIELD_REQUIREMENT = {
    "POINT": ("q1_point",),
    "INTERVAL": ("q1_lo", "q1_hi"),
    "SCENARIO_SET": ("q1_point", "q1_lo", "q1_hi"),
}


def check_quantity_basis(config_dir: Path) -> CostBasisReport:
    """执行 T00-10A / T00-10B 全部判据。

    判据顺序**有语义**：QB-03（附证）要交叉引用 QB-02 的结果，
    故 QB-02 必须先入列。
    """
    rep = CostBasisReport()
    spec = _read(config_dir, "q1_assumption_spec.json")
    field_schema = _read(config_dir, "field_schema.json")
    basis_decl = _read(config_dir, "basis_declarations.json")

    if spec is None:
        rep.results.append(_bad(
            "QB-01", STATUS_SKIP,
            "q1 假设声明书缺失（q1_assumption_spec.json）——T00-10A/B 未冻结，"
            "结算量预判无据"))
        return rep

    three = spec.get("three_elements") or {}

    # ---------------- QB-01 取值依据（basis） ----------------
    base = three.get("basis") or {}
    value = base.get("value")
    vocab = base.get("vocabulary") or []
    if value is None:
        rep.results.append(_bad(
            "QB-01", STATUS_BLOCKED,
            "q1 取值依据未声明——q1 直接进入目标函数（与 P* 相乘），"
            "依据未声明则 P* 的量级无据；禁止按 Q0_NO_CHANGE 静默补全"
            "（那等于放弃工程量套利的建模，是商务选择不是默认值）"))
    elif value not in vocab:
        rep.results.append(_bad(
            "QB-01", STATUS_FAIL,
            f"q1 取值依据 {value!r} 不在词表 {vocab} 内", [str(value)]))
    else:
        rep.results.append(_ok("QB-01", f"q1 取值依据已声明：{value}"))

    # ---------------- QB-02 差异归因（跨文件，须先于 QB-03） ----------------
    attribution = (basis_decl or {}).get("default_attribution")
    if not attribution:
        rep.results.append(_bad(
            "QB-02", STATUS_BLOCKED,
            "工程量差异归因未声明（basis_declarations.json → default_attribution）——"
            "q1 与 q0 为何不同无从解释"))
    elif attribution == "UNKNOWN":
        rep.results.append(_bad(
            "QB-02", STATUS_WARN,
            "差异归因为 UNKNOWN——q1 与 q0 的差异无解释，"
            "减量/增量分支判定失去依据（W01/W04 会据此告警）"))
    else:
        rep.results.append(_ok(
            "QB-02", f"差异归因已声明：{attribution}（来源：basis_declarations.json）"))

    # ---------------- QB-03 附证齐备（含交叉满足） ----------------
    if value in vocab:
        need = (base.get("required_when") or {}).get(value) or []
        declared = base.get("declared_evidence") or {}
        cross = {k: v for k, v in (base.get("cross_satisfied_by") or {}).items()
                 if not k.startswith("_")}
        satisfied, stale = [], []
        for k, rule_id in cross.items():
            hit = next((x for x in rep.results if x.rule_id == rule_id), None)
            if hit is not None and hit.status == STATUS_PASS:
                satisfied.append(k)
            else:
                stale.append(f"{k}→{rule_id}(未 PASS)")
        lack = [k for k in need if k not in declared and k not in satisfied]
        ev = [f"须附全量：{need}", f"已附：{sorted(declared) or '无'}"]
        if satisfied:
            ev.append("交叉满足：" + "、".join(
                f"{k}（由 {cross[k]} 锁定）" for k in satisfied))
        if stale:
            ev.append("交叉引用失效：" + "、".join(stale))
        if not need:
            rep.results.append(_ok("QB-03", f"取值依据 {value} 无强制附证要求"))
        elif lack:
            rep.results.append(_bad(
                "QB-03", STATUS_WARN,
                f"取值依据 {value} 仍缺附证 {lack}——补齐前 q1 不得进入目标函数",
                ev))
        else:
            rep.results.append(_ok(
                "QB-03", f"取值依据 {value} 附证齐备：{sorted(declared)}", ev))
    else:
        rep.results.append(_bad("QB-03", STATUS_SKIP,
                                "取值依据未定，附证齐备性未校验"))

    # ---------------- QB-04 格式 ↔ 字段字典 ----------------
    fmt = three.get("format") or {}
    fv = fmt.get("value")
    if fv not in (fmt.get("allowed") or []):
        rep.results.append(_bad(
            "QB-04", STATUS_FAIL,
            f"q1 格式 {fv!r} 不在允许集合 {fmt.get('allowed')} 内"))
    elif field_schema is None:
        rep.results.append(_bad("QB-04", STATUS_SKIP,
                                "字段字典缺失，格式一致性未校验"))
    else:
        names = {f.get("name") for f in (field_schema.get("fields") or [])}
        required = FORMAT_FIELD_REQUIREMENT.get(fv, ())
        missing = [n for n in required if n not in names]
        if missing:
            rep.results.append(_bad(
                "QB-04", STATUS_FAIL,
                f"格式 {fv} 需要字段 {list(required)}，字段字典缺 {missing}——"
                "格式与字段脱节时区间信息无处落地",
                [f"已有：{sorted(names)}"]))
        else:
            rep.results.append(_ok(
                "QB-04", f"格式 {fv} 与字段字典一致（需 {list(required)} 均存在）"))

    # ---------------- QB-05 点值假设的敏感性义务 ----------------
    sens = spec.get("sensitivity_requirement") or {}
    sv = sens.get("value")
    if fv != "POINT":
        rep.results.append(_ok(
            "QB-05", f"格式 {fv} 自带不确定性表达，无强制敏感性义务"))
    elif sv is None:
        rep.results.append(_bad(
            "QB-05", STATUS_BLOCKED,
            "q1 取点值但未声明敏感性义务——点值会把 P* 算成确定值，"
            "掩盖工程量风险（q1 在投标期不可观测，精度是虚假的）"))
    elif sv not in (sens.get("vocabulary") or []):
        rep.results.append(_bad(
            "QB-05", STATUS_FAIL,
            f"敏感性义务 {sv!r} 不在词表 {sens.get('vocabulary')} 内"))
    else:
        rep.results.append(_ok("QB-05", f"敏感性义务已声明：{sv}"))

    # ---------------- QB-06 冻结时点 ----------------
    timing = three.get("freeze_timing") or {}
    if not (timing.get("value") or "").strip():
        rep.results.append(_bad("QB-06", STATUS_BLOCKED, "冻结时点未声明"))
    elif spec.get("frozen_at") in (None, ""):
        rep.results.append(_bad(
            "QB-06", STATUS_WARN,
            "尚未冻结（冻结时点：Gate 0b 之前）——当前为未定态，"
            "冻结前 q1 不得进入目标函数"))
    else:
        rep.results.append(_ok("QB-06", f"已冻结于 {spec['frozen_at']}"))

    return rep
