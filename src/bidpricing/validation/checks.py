"""T01-06 D01–D13 校验器 —— 求解前数据体检（10 阻断 + 3 告警）。

规范事实源 = config/validation_rules.json（thresholds/rules）；本模块实现与
规范由 tests/test_validation_rules.py 双向锁定（防「同一规则两处说法」）。

状态语义（与闸门层同构）：
* ``FAIL``    —— 数据违反规则（阻断级 → 拒绝运行）。违反 ≠ 未定态。
* ``BLOCKED`` —— 前置声明缺失，无法判定（未定态 = key 完全缺失）。
* ``WARN``    —— 告警触发，写入体检单，不阻断。
* ``SKIP``    —— 输入数据不足，显式跳过，**不静默通过**。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

__all__ = [
    "STATUS_PASS", "STATUS_FAIL", "STATUS_BLOCKED", "STATUS_WARN", "STATUS_SKIP",
    "RuleResult", "ValidationReport",
    "load_validation_rules", "run_validation",
]

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_WARN = "WARN"
STATUS_SKIP = "SKIP"

RULES_CONFIG = "validation_rules.json"

BLOCK_RULES = [f"D{i:02d}" for i in range(1, 12)]   # D01–D11
WARN_SUBRULES = ["W01", "W02", "W03"]               # v0.3 的 D10/D11/D12


@dataclass
class RuleResult:
    rule_id: str
    level: str            # BLOCK / WARN
    status: str
    detail: str
    evidence: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationReport:
    results: list[RuleResult] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(r.level == "BLOCK" and r.status in (STATUS_FAIL, STATUS_BLOCKED)
                   for r in self.results)

    def by_rule(self, rule_id: str) -> RuleResult | None:
        return next((r for r in self.results if r.rule_id == rule_id), None)

    def summary_line(self) -> str:
        n_fail = sum(1 for r in self.results if r.status == STATUS_FAIL)
        n_blk = sum(1 for r in self.results if r.status == STATUS_BLOCKED)
        n_warn = sum(1 for r in self.results if r.status == STATUS_WARN)
        n_skip = sum(1 for r in self.results if r.status == STATUS_SKIP)
        n = len(self.results)
        verdict = "■ BLOCKED" if self.blocked else "✓ PASS"
        return (f"{verdict}  规则 {n} 条：FAIL={n_fail} BLOCKED={n_blk} "
                f"WARN={n_warn} SKIP={n_skip}")

    def to_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "summary": self.summary_line(),
            "results": [r.to_dict() for r in self.results],
        }


def load_validation_rules(config_dir: Path) -> dict:
    return json.loads((config_dir / RULES_CONFIG).read_text(encoding="utf-8"))


def _ok(rid: str, detail: str = "") -> RuleResult:
    return RuleResult(rid, "BLOCK", STATUS_PASS, detail)


def _fail(rid: str, detail: str, evidence: list) -> RuleResult:
    return RuleResult(rid, "BLOCK", STATUS_FAIL, detail, evidence)


def _blocked(rid: str, detail: str) -> RuleResult:
    return RuleResult(rid, "BLOCK", STATUS_BLOCKED, detail)


def _warn_result(rid: str, detail: str, evidence: list) -> RuleResult:
    return RuleResult(rid, "WARN", STATUS_WARN, detail, evidence)


def _item_value(it) -> float:
    """W01 计值：优先 cap，缺 cap 用 c_i；无量则 0。"""
    p = it.cap if it.cap is not None else it.c_i
    q = it.q1_point if it.q1_point is not None else 0.0
    return (p or 0.0) * q


def run_validation(report, *, classification: dict, selection: dict,
                   sheet_roles: dict | None = None, basis: dict | None = None,
                   history: dict | None = None, p_star: float | None = None,
                   p_star_max: float | None = None,
                   p_star_min: float | None = None,
                   thresholds: dict | None = None,
                   missing_unit_price_sheets: dict | None = None) -> ValidationReport:
    """对 MatchReport 执行 D01–D11 阻断 + W01–W03 告警。

    threshold 默认取 config/validation_rules.json.thresholds 的值。
    """
    th = thresholds or {
        "D05_min_coverage": 0.98,
        "D06_max_unknown_ratio": 0.20,
        "W01_max_unknown_value_share": 0.15,
        "W02_ratio_band": [0.2, 5.0],
        "W03_sigma": 3.0,
    }
    items = list(report.items)
    res = ValidationReport()

    # ---- D01 编码唯一（UNKNOWN 不阻塞，仅记录 —— D1 裁定） ----------------
    n_unknown = sum(1 for it in items if it.code_kind == "UNKNOWN")
    if report.duplicate_keys:
        res.results.append(_fail(
            "D01", "存在同侧重复 key（匹配层已 BLOCK，此处复核 canonical 行）",
            list(report.duplicate_keys)))
    else:
        d = "编码唯一性通过"
        if n_unknown:
            d += f"；{n_unknown} 项编码形态 UNKNOWN（D1 裁定：不阻塞，仅记录）"
        res.results.append(_ok("D01", d))

    # ---- D02 q1_point > 0（pass_through 豁免） -----------------------------
    bad_q = [(it.item_id, it.q1_point) for it in items
             if it.cost_row and not it.pass_through
             and (it.q1_point is None or it.q1_point <= 0)]
    if bad_q:
        res.results.append(_fail(
            "D02", f"{len(bad_q)} 项 q1_point 缺失或 ≤0（成本清单工程量为结算量预判，"
                   "pass_through 豁免）", [f"{k}={v}" for k, v in bad_q]))
    else:
        res.results.append(_ok("D02", "cost_row 非 pass_through 项 q1_point 全部 > 0"))

    # ---- D03 cap > 0 或 no_cap ---------------------------------------------
    bad_cap = [(it.item_id, it.cap) for it in items
               if it.cap_row and not it.no_cap
               and (it.cap is None or it.cap <= 0)]
    if bad_cap:
        res.results.append(_fail(
            "D03", f"{len(bad_cap)} 项 cap ≤ 0 或缺失且未走 no_cap 通道"
                   "（base:=cap 裁定后判据收缩为上界自身有效）",
            [f"{k}={v}" for k, v in bad_cap]))
    else:
        n_nc = sum(1 for it in items if it.no_cap)
        res.results.append(_ok(
            "D03", "cap 全部 > 0 或合法 no_cap"
            + (f"（no_cap {n_nc} 项，上界由 P* ≤ P*_max 兜底）" if n_nc else "")))

    # ---- D04 c_i > 0 --------------------------------------------------------
    bad_c = [(it.item_id, it.c_i) for it in items
             if it.cost_row and (it.c_i is None or it.c_i <= 0)]
    if bad_c:
        res.results.append(_fail(
            "D04", f"{len(bad_c)} 项 c_i 缺失或 ≤0（C4 成本地板信号）",
            [f"{k}={v}" for k, v in bad_c]))
    else:
        res.results.append(_ok("D04", "cost_row 项 c_i 全部 > 0"))

    # ---- D05 覆盖率 ≥ 阈值 ---------------------------------------------------
    n_master = report.n_master
    if n_master <= 0:
        res.results.append(_blocked("D05", "master item set 为空，无法判定覆盖度"))
    else:
        cov = report.n_matched / n_master
        min_cov = float(th["D05_min_coverage"])
        if cov < min_cov:
            miss_cap = [it.item_id for it in items if not it.cap_row]
            miss_cost = [it.item_id for it in items if not it.cost_row]
            res.results.append(_fail(
                "D05", f"匹配覆盖率 {cov:.4f} < {min_cov}"
                       f"（仅 cap 侧 {len(miss_cap)} / 仅 cost 侧 {len(miss_cost)}）",
                miss_cap + miss_cost))
        else:
            res.results.append(_ok(
                "D05", f"匹配覆盖率 {cov:.4f} ≥ {min_cov}"
                       f"（matched {report.n_matched} / master {n_master}）"))

    # ---- D06 attribution 标注完成 --------------------------------------------
    need_attr = [it for it in items if it.cost_row and not it.pass_through]
    unlabeled = [it.item_id for it in need_attr if it.attribution is None]
    unknown = [it.item_id for it in need_attr if it.attribution == "UNKNOWN"]
    ratio = (len(unknown) / len(need_attr)) if need_attr else 0.0
    max_unk = float(th["D06_max_unknown_ratio"])
    if unlabeled:
        res.results.append(_fail(
            "D06", f"{len(unlabeled)} 项 q1_point 未标注 attribution"
                   "（OI-01 裁定：须补归属标签，未标注 ≠ UNKNOWN）", unlabeled))
    elif ratio > max_unk:
        res.results.append(_fail(
            "D06", f"UNKNOWN 占比 {ratio:.2%} > {max_unk:.0%}", unknown))
    else:
        res.results.append(_ok(
            "D06", f"attribution 标注完成（UNKNOWN {len(unknown)}/{len(need_attr)}"
                   f" = {ratio:.2%} ≤ {max_unk:.0%}）"))

    # ---- D07 亏损承接（C4 地板 vs C2 上限） -----------------------------------
    # loss_acceptance=ACCEPT（用户裁定：单项有亏有赚、整体利润优先）→
    # 亏损项不阻塞（WARN + 清单），C4 地板钳制到 cap、亏损总量由 C6 兜底。
    infeasible = [(it.item_id, it.c_i, it.cap, it.q1_point) for it in items
                  if it.cap is not None and it.c_i is not None and it.c_i > it.cap]
    opts07 = (selection or {}).get("options", {})
    la = opts07.get("loss_acceptance", {})
    la_val = la.get("value") if isinstance(la, dict) else la
    if infeasible and la_val == "ACCEPT":
        ev = [f"{k}: c={a} > cap={b}，最低亏损 {round((a - b) * (q or 0), 2)} 元"
              for k, a, b, q in infeasible]
        res.results.append(_warn_result(
            "D07", f"{len(infeasible)} 项 c_i > cap_i（接受亏损承接，ADR-0009）："
                   "C4 地板钳制到 cap（p=cap 止损），亏损总量由 C6 兜底", ev))
    elif infeasible:
        res.results.append(_fail(
            "D07", f"{len(infeasible)} 项 c_i > cap_i（floor > U，可行域为空）；"
                   "如接受单项亏损，请先落值选择项 loss_acceptance=ACCEPT",
            [f"{k}: c={a} > cap={b}" for k, a, b, _ in infeasible]))
    else:
        res.results.append(_ok("D07", "逐项 c_i ≤ cap_i 成立（no_cap 项无上界不参与）"))

    # ---- D08 税口径声明一致 -----------------------------------------------------
    if not isinstance(basis, dict) or not basis:
        res.results.append(_blocked(
            "D08", "税口径声明缺失（未定态 = key 完全缺失，ADR-0007：沉默不是断言）；"
                   "须声明 cap/cost 两侧 tax_scope（R2：均不含增值税）"))
    else:
        cap_b, cost_b = basis.get("cap_tax_scope"), basis.get("cost_tax_scope")
        if cap_b is None or cost_b is None:
            res.results.append(_blocked(
                "D08", f"声明不完整：cap_tax_scope={cap_b!r}, cost_tax_scope={cost_b!r}"))
        elif cap_b != cost_b:
            res.results.append(_fail(
                "D08", f"两侧税口径不一致：cap={cap_b} vs cost={cost_b}", []))
        else:
            res.results.append(_ok("D08", f"两侧税口径一致：{cap_b}"))

    # ---- D09 契约级输入完整 ------------------------------------------------------
    opts = (selection or {}).get("options", {})
    ct = opts.get("contract_type", {}).get("value") if isinstance(
        opts.get("contract_type"), dict) else opts.get("contract_type")
    rsid = (classification or {}).get("code_system")
    rho = opts.get("rho", {}).get("value") if isinstance(
        opts.get("rho"), dict) else opts.get("rho")
    if ct is None:
        res.results.append(_blocked(
            "D09", "contract_type 未声明（未定态）：须由用户给定（如 UNIT_PRICE/LUMP_SUM）"))
    elif rsid is None:
        res.results.append(_blocked("D09", "rule_set_id 缺失：分类表未声明 code_system"))
    else:
        d = f"contract_type={ct}，rule_set_id={rsid}"
        d += "，rho 未声明按 0（裁定：无规范依据）" if rho is None else f"，rho={rho}"
        res.results.append(_ok("D09", d))

    # ---- D10 pricing_role 判定完整 ------------------------------------------------
    cls = classification or {}
    if "covered_lists" not in cls:
        res.results.append(_blocked(
            "D10", "分类声明缺失（covered_lists key 完全缺失 = 未声明，ADR-0004）"))
    else:
        covered = {c.get("source_list") for c in cls.get("covered_lists", [])}
        bad_exc = [e for e in cls.get("exceptions", [])
                   if not all(e.get(k) for k in ("item_id", "unit_work", "pricing_role"))]
        uncovered: list[str] = []
        if sheet_roles:
            for it in items:
                pv = it.provenance or {}
                sheet = ((pv.get("cost") or {}).get("source_sheet")
                         or (pv.get("cap") or {}).get("source_sheet"))
                sl = sheet_roles.get(sheet)
                if sl is not None and sl not in covered:
                    uncovered.append(f"{it.item_id}({sl})")
        if bad_exc:
            res.results.append(_fail(
                "D10", f"{len(bad_exc)} 行例外声明缺必填字段"
                       "（item_id/unit_work/pricing_role）",
                [e.get("item_id", "?") for e in bad_exc]))
        elif uncovered:
            res.results.append(_fail(
                "D10", f"{len(uncovered)} 行落在未覆盖清单", uncovered[:20]))
        else:
            d = f"covered_lists 就位（{len(covered)} 张清单），exceptions 结构合法"
            if not sheet_roles:
                d += "；sheet_roles 未提供，行级映射子判据 SKIP"
            res.results.append(_ok("D10", d))

    # ---- D11 P* ∈ [P*_min, P*_max] ---------------------------------------------
    if p_star is None:
        res.results.append(_blocked(
            "D11", "P* 未提供（未定态）：报价总价由用户给定，不得默认"))
    else:
        problems = []
        if p_star_max is not None and p_star > p_star_max:
            problems.append(f"P*={p_star} > P*_max={p_star_max}")
        if p_star_min is not None and p_star < p_star_min:
            problems.append(f"P*={p_star} < P*_min={p_star_min}")
        if problems:
            res.results.append(_fail("D11", "；".join(problems), problems))
        else:
            band = (f"[{p_star_min if p_star_min is not None else '−∞'}, "
                    f"{p_star_max if p_star_max is not None else '+∞'}]")
            res.results.append(_ok("D11", f"P*={p_star} ∈ {band}"))

    # ---- D13 单价列完整性（列缺失 ≠ 单元格空） ------------------------------------
    # 上传侧：ParseReport.missing_unit_price_sheets 由解析器按列映射判定。
    # 列在而值空 = 合法 no_cap（D03 通道）；整列缺失 = 数据缺陷，必须阻断。
    if missing_unit_price_sheets is None:
        res.results.append(_blocked(
            "D13", "未提供列完整性事实（解析侧 missing_unit_price_sheets 未传入）"))
    else:
        cap_missing = list(missing_unit_price_sheets.get("cap") or [])
        cost_missing = list(missing_unit_price_sheets.get("cost") or [])
        if cap_missing or cost_missing:
            res.results.append(_fail(
                "D13",
                f"明细表缺少单价列（cap 侧 {len(cap_missing)} 张 / cost 侧 "
                f"{len(cost_missing)} 张）：空值会被当作『不限价』，"
                "限价与成本无法判定",
                [f"cap:{s}" for s in cap_missing] + [f"cost:{s}" for s in cost_missing]))
        else:
            res.results.append(_ok(
                "D13", "cap 与 cost 两侧明细表均含单价列"
                       "（『不限价』只指列在而值为空，整列缺失已排除）"))

    # ---- D12 告警组（v0.3 D10/D11/D12 → W01/W02/W03） ----------------------------
    # W01: UNKNOWN 项金额占比 > 15%
    vals = [(it, _item_value(it)) for it in items if it.cost_row]
    total = sum(v for _, v in vals)
    unk_share = (sum(v for it, v in vals if it.attribution == "UNKNOWN") / total
                 if total > 0 else 0.0)
    max_share = float(th["W01_max_unknown_value_share"])
    if total <= 0:
        res.results.append(RuleResult(
            "W01", "WARN", STATUS_SKIP, "可计值金额为 0，无法计算 UNKNOWN 占比"))
    elif unk_share > max_share:
        res.results.append(_warn_result(
            "W01", f"UNKNOWN 项金额占比 {unk_share:.2%} > {max_share:.0%}", []))
    else:
        res.results.append(RuleResult(
            "W01", "WARN", STATUS_PASS, f"UNKNOWN 占比 {unk_share:.2%} ≤ {max_share:.0%}"))

    # W02: 单项价值比 cap/c 超带
    lo, hi = (float(x) for x in th["W02_ratio_band"])
    outliers = [(it.item_id, it.cap / it.c_i) for it in items
                if it.cap is not None and it.c_i and it.c_i > 0
                and not (lo <= it.cap / it.c_i <= hi)]
    if outliers:
        res.results.append(_warn_result(
            "W02", f"{len(outliers)} 项价值比 cap/c 超出 [{lo}, {hi}]"
                   "（原效率比 re-base，见 ADR-0008）",
            [f"{k}={v:.3f}" for k, v in outliers]))
    else:
        res.results.append(RuleResult(
            "W02", "WARN", STATUS_PASS, f"全部价值比在 [{lo}, {hi}] 带内"))

    # W03: 偏离历史 3σ
    if not history or history.get("r_mean") is None or history.get("r_std") is None:
        res.results.append(RuleResult(
            "W03", "WARN", STATUS_SKIP,
            "历史同类项目 r 分布未提供（数据不足，显式跳过——不静默通过）"))
    else:
        pairs = [it.cap / it.c_i for it in items
                 if it.cap is not None and it.c_i and it.c_i > 0]
        if not pairs:
            res.results.append(RuleResult(
                "W03", "WARN", STATUS_SKIP, "无可比价值比样本"))
        else:
            mean = sum(pairs) / len(pairs)
            sigma = float(history["r_std"])
            z = abs(mean - float(history["r_mean"])) / sigma if sigma > 0 else 0.0
            lim = float(th["W03_sigma"])
            if z > lim:
                res.results.append(_warn_result(
                    "W03", f"整体价值比均值 {mean:.3f} 偏离历史 "
                           f"{float(history['r_mean']):.3f} 达 {z:.2f}σ > {lim}σ", []))
            else:
                res.results.append(RuleResult(
                    "W03", "WARN", STATUS_PASS, f"偏离 {z:.2f}σ ≤ {lim}σ"))

    return res
