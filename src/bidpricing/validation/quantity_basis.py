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
    STATUS_INFO,
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
            "QB-01", STATUS_INFO,
            "q1 取值依据未登记（台账空缺）——**不影响计算**：q1 的数值本身由"
            "字段字典 missing_policy 把关，依据只决定将来能否说清量从哪来。"
            "已按 ADR-0013 从 BLOCKED 降级：台账不是关卡"))
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
                "QB-03", STATUS_INFO,
                f"取值依据 {value} 的留痕项待补 {lack}——**不影响计算**，"
                "仅在复核量从哪来时使用（ADR-0013：留痕项不阻塞）", ev))
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

    # ---------------- QB-05 敏感性分析（可选增强，默认关闭） ----------------
    # ADR-0013：敏感性分析是**分析能力**不是**数据前提**。用户给了成本清单量
    # 就是要按它直接测算，不启用该分析不影响结论成立，故不阻塞、不告警。
    sens = spec.get("sensitivity_requirement") or {}
    sv = sens.get("value")
    optional = sens.get("mode") == "OPTIONAL_ENHANCEMENT"
    enabled = bool(sens.get("enabled"))
    if fv != "POINT":
        rep.results.append(_ok(
            "QB-05", f"格式 {fv} 自带不确定性表达，无敏感性要求"))
    elif optional and not enabled:
        rep.results.append(_ok(
            "QB-05", "可选增强未启用（默认）——直接按 q1_point 测算；"
                     f"如需 r 敏感性曲线，可用 {sens.get('preferred_method')} 启用"))
    elif sv is None:
        rep.results.append(_bad(
            "QB-05", STATUS_WARN,
            "已启用敏感性分析但未声明方法"))
    elif sv not in (sens.get("vocabulary") or []):
        rep.results.append(_bad(
            "QB-05", STATUS_FAIL,
            f"敏感性方法 {sv!r} 不在词表 {sens.get('vocabulary')} 内"))
    else:
        rep.results.append(_ok("QB-05", f"敏感性方法已声明：{sv}"))

    # ---------------- QB-06 扫描网格（仅启用 RATIO_SCAN 时才有意义） ----------------
    scan = (spec.get("sensitivity_requirement") or {}).get("scan_config") or {}
    if not enabled:
        rep.results.append(_bad(
            "QB-06", STATUS_SKIP,
            "敏感性分析未启用，无扫描网格要求（已观测 r ∈ "
            f"[{(scan.get('observed_r_range') or {}).get('min')}, "
            f"{(scan.get('observed_r_range') or {}).get('max')}] 留档备查）"))
    elif sv != "RATIO_SCAN":
        rep.results.append(_ok("QB-06", f"敏感性方法为 {sv}，无扫描网格要求"))
    elif scan.get("grid") in (None, [], ""):
        obs = scan.get("observed_r_range") or {}
        rng = (f"已观测 r ∈ [{obs.get('min')}, {obs.get('max')}]"
               if obs else "未登记观测范围")
        rep.results.append(_bad(
            "QB-06", STATUS_WARN,
            "RATIO_SCAN 已启用但扫描网格未定——敏感性分析无法执行；"
            f"网格须覆盖真实偏差（{rng}），不得用未经论证的固定 ±5%"))
    else:
        rep.results.append(_ok("QB-06", f"扫描网格已定：{scan['grid']}"))

    # ---------------- QB-07 冻结时点 ----------------
    timing = three.get("freeze_timing") or {}
    if not (timing.get("value") or "").strip():
        rep.results.append(_bad("QB-07", STATUS_BLOCKED, "冻结时点未声明"))
    elif spec.get("frozen_at") in (None, ""):
        rep.results.append(_bad(
            "QB-07", STATUS_WARN,
            "尚未冻结（冻结时点：Gate 0b 之前）——当前为未定态，"
            "冻结前 q1 不得进入目标函数"))
    else:
        rep.results.append(_ok("QB-07", f"已冻结于 {spec['frozen_at']}"))

    return rep
