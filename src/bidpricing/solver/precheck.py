"""Phase 0 预检与可行性证书（T03-03）。

规格制品：``config/phase0_precheck_spec.json``（PC-01..PC-08）；
模型依据：model_v0.3_R2 §6.1/§6.2。

**本层是什么**：不调用求解器的纯算术预检——规则解析 + 求和 + 比较（O(n)）。
它的职责是在进入 Phase 1/2 **之前**把结构性不可行拦下来：P* 越界必须判
INFEASIBLE 且不进求解器，而不是让优化器用不平衡报价「硬找解」（§6.2 核心原则）。
缺了这一步，结构性不可行会被误报成「求解失败」，排查方向直接错。

**三条本仓规则的落点**：

* P*_var 的唯一提供者是 :func:`total_price.compute_P_competitive`（T00-06B ④，
  profit_bridge_spec 登记）——本层直接调用，禁止重实现求和/闭式逻辑（规则⑨）。
* L_i/U_i/floor_i 的唯一实现是 T03-02 的派生层；P_min 用其中的 L（多源取大
  merged_lower，ADR-0026 决策六——普通 L 求和会在条款下浮时虚低）。
* 空 cap ≠ 0：cap 空 ⇒ U 合法 ``None``（ALLOW_EMPTY_NO_CAP）⇒ P_max **不落值**
  而非记 0；把缺界记成 0 会把上界检查判成必然 FAIL（规则⑤同根因）。

**计算与判定分离**（ADR-0025/0029 同款）：:func:`build_certificate` 只算数，
:func:`judge_precheck` 只判——判定器吃 ``PrecheckInputs`` + 证书，故可以把
伪造的证书注入判定器验证区分度（判据必须能被错误的值否定）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..contracts.pricing_card import ResolvedParameters
from ..derived import DerivedReport, compute_derived
from ..paths import config_dir
from ..total_price import compute_P_competitive
from .constraint_judge import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    resolve_tolerances,
)
from .instance import Phase1Instance, ROLE_OPTIMIZABLE

SPEC_FILENAME = "phase0_precheck_spec.json"

#: 角色域机制制品（跨项目复用，不含项目级数据）
ROLES_SPEC_FILENAME = "competitiveness_classification.json"

_UNSET = object()


class PrecheckError(ValueError):
    """预检输入结构不合法。"""


# ---------------------------------------------------------------------------
# 输入 / 输出载体
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrecheckInputs:
    """预检的全部输入——**只有原始量**。

    声明类标量用「key 是否传了」区分未定态（ADR-0004）：

    * ``pi_target`` / ``alpha_cap`` 不传（_UNSET）= **未声明** ⇒ PC-05 BLOCKED；
      传 ``None`` 也按未声明处理但理由不同（key 存在取值为空）。
    * ``supplied_material`` / ``env_tax`` 未声明按 0 计并 WARN——取 0 是
      **收紧**方向（可竞争预算更小），不会静默放宽门槛；
    * ``vat_rate`` / ``surtax_rate`` 无默认值（税率结构缺失 ⇒ BLOCKED，
      与 :func:`compute_P_competitive` 的口径一致）。
    """

    instance: Phase1Instance
    derived: DerivedReport
    rule_set_id: str | None = None
    contract_type: str | None = None
    pi_target: Any = _UNSET
    alpha_cap: Any = _UNSET
    fixed_pretax: float | None = None
    vat_rate: float | None = None
    surtax_rate: float | None = None
    supplied_material: float | None = None
    env_tax: float | None = None
    #: 合法角色域；空 = 未提供角色域制品 ⇒ PC-02 BLOCKED（机制缺 ≠ 数据缺）
    role_domain: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PrecheckVerdict:
    """单条判据的六元组。"""

    check_id: str
    status: str
    actual: Any
    limit: Any
    detail: str
    severity: str = "P0"


@dataclass(frozen=True)
class PrecheckCertificate:
    """结构化可行性证书（§6.1）。字段不落值 = 算不出，不得替换成 0。"""

    #: P_min = Σ_{X_opt} L_i·q_i^0（L 为 merged_lower 多源取大）
    p_min: float | None
    #: P_max = Σ_{X_opt} U_i·q_i^0；存在合法不限价项 ⇒ None（≠0）
    p_max: float | None
    #: True = P_max 因 cap 空而不落值；此时 p_max_capped 仍有界项部分和（诊断用）
    p_max_capped_only: bool
    p_max_capped: float | None
    #: P*_var——compute_P_competitive 的闭式输出（唯一提供者）
    p_star_var: float | None
    #: P*_eff = max(三term)；任一 term 不可算 ⇒ None（丢项=静默放宽，禁止）
    p_star_eff: float | None
    eff_terms: dict[str, float | None] = field(default_factory=dict)
    #: ΔP = max(0, P*_eff − P*)
    delta_p: float | None = None
    #: 缺失输入的具名清单（BLOCKED 理由的可审计来源）
    missing: tuple[str, ...] = ()
    inputs_used: frozenset[str] = frozenset()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PrecheckReport:
    """预检整体报告。"""

    certificate: PrecheckCertificate
    verdicts: tuple[PrecheckVerdict, ...]
    #: 任一可行性判据 FAIL ⇒ "INFEASIBLE"；否则按聚合状态
    feasibility: str
    overall: str

    def of(self, check_id: str) -> PrecheckVerdict | None:
        for v in self.verdicts:
            if v.check_id == check_id:
                return v
        return None


_ORDER = (STATUS_FAIL, STATUS_BLOCKED, STATUS_WARN, STATUS_SKIP, STATUS_PASS)
_RANK = {s: i for i, s in enumerate(_ORDER)}


def _worst(statuses: list[str]) -> str:
    return min(statuses, key=lambda s: _RANK[s])


# ---------------------------------------------------------------------------
# 规格 / 容差
# ---------------------------------------------------------------------------

def load_precheck_spec(config_path: Path | None = None) -> dict[str, Any]:
    """``config_path`` 可传目录（自动拼 SPEC_FILENAME）或制品文件路径。"""
    path = config_path if config_path is not None else config_dir()
    if path.is_dir():
        path = path / SPEC_FILENAME
    import json

    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_role_domain(config_path: Path | None = None) -> frozenset[str]:
    """从角色域机制制品读合法角色集（跨项目复用，不含项目数据）。"""
    path = config_path if config_path is not None else config_dir() / ROLES_SPEC_FILENAME
    if path.is_dir():
        path = path / ROLES_SPEC_FILENAME
    import json

    with open(path, encoding="utf-8") as fh:
        spec = json.load(fh)
    return frozenset(r["role"] for r in spec.get("roles", ()))


def build_derived(
    instance: Phase1Instance,
    resolved: ResolvedParameters,
) -> DerivedReport:
    """便捷入口：μ=0（不允许亏损的严格地板）、DECLINE、无不平衡条款。

    仅供探针/演示用；真实项目应走 Phase 0 输入门声明后直接传
    :class:`DerivedReport`——声明缺失该 BLOCKED 的必须 BLOCKED。
    """
    return compute_derived(
        instance, resolved,
        mu=0.0, loss_acceptance="DECLINE",
        unbalanced={"enabled": False},
    )


# ---------------------------------------------------------------------------
# 计算：结构化可行性证书（§6.1）
# ---------------------------------------------------------------------------

def build_certificate(inputs: PrecheckInputs) -> PrecheckCertificate:
    """只算数不判定。任何算不出的字段落 ``None`` 并在 ``missing`` 具名。"""
    inst = inputs.instance
    notes: list[str] = []
    missing: list[str] = []
    inputs_used: set[str] = set()
    opt = inst.opt_items

    # ---- L/U/floor 逐项收集（derived 层唯一实现）-------------------------
    def _d(item_id: str):
        return inputs.derived.of(item_id)

    l_missing: list[str] = []
    u_missing: list[str] = []
    q_missing: list[str] = []
    floor_missing: list[str] = []
    c_missing: list[str] = []
    cap_empty: list[str] = []

    p_min = 0.0
    p_max: float | None = 0.0
    p_max_capped = 0.0
    capped_only = False
    model_lower = 0.0
    cap_total = 0.0
    cost_total = 0.0

    for it in opt:
        q0 = it.q0
        if q0 is None:
            q_missing.append(it.item_id)
            continue
        inputs_used.add(f"{it.item_id}.q0")
        d = _d(it.item_id)
        if d is None:
            l_missing.append(it.item_id)
            u_missing.append(it.item_id)
            floor_missing.append(it.item_id)
            continue
        # L：merged_lower（多源取大）——P_min 必须用它，ADR-0026 决策六
        if d.L is None:
            l_missing.append(it.item_id)
        else:
            p_min += d.L * q0
        # U：cap 空 ⇒ 合法 None（不是缺口）
        if d.U is None:
            if it.cap is None:
                capped_only = True
                cap_empty.append(it.item_id)
            else:
                u_missing.append(it.item_id)
        else:
            p_max += d.U * q0  # type: ignore[operator]
            p_max_capped += d.U * q0
        # floor / cap / c
        if d.L is None or d.floor is None:
            # max(L, floor) 需要**两个**都在——缺任一 ⇒ term1 不可算，
            # 不得把缺的那侧按 0 顶替（静默放宽下界）。
            floor_missing.append(it.item_id)
        else:
            model_lower += max(d.L, d.floor) * q0
        if it.cap is not None:
            cap_total += it.cap * q0
        if it.c_i is None:
            c_missing.append(it.item_id)
        else:
            cost_total += it.c_i * q0

    if q_missing:
        missing.extend(f"q0:{i}" for i in q_missing)
    if l_missing:
        missing.extend(f"L:{i}" for i in l_missing)
    if u_missing:
        missing.extend(f"U:{i}" for i in u_missing)
    if floor_missing:
        missing.extend(f"floor:{i}" for i in floor_missing)
    if c_missing:
        missing.extend(f"c_i:{i}" for i in c_missing)
    if capped_only:
        p_max = None
        notes.append(
            "存在合法不限价项（cap 空：" + "、".join(cap_empty) + "）⇒ P_max 不落值"
            "（≠0），上界检查 SKIP；上界由 P* 自身兜底。"
        )

    # ---- P*_var：唯一提供者 compute_P_competitive ------------------------
    p_star = inst.P_star
    p_star_var: float | None = None
    if p_star is None:
        missing.append("P_star")
    elif inputs.vat_rate is None or inputs.surtax_rate is None:
        missing.append("vat_rate" if inputs.vat_rate is None else "surtax_rate")
    elif inputs.fixed_pretax is None:
        missing.append("fixed_pretax")
    else:
        sm = inputs.supplied_material
        if sm is None:
            sm = 0.0
            notes.append("supplied_material 未声明，按 0 计（收紧方向，不会放宽门槛）。")
        et = inputs.env_tax
        if et is None:
            et = 0.0
            notes.append("env_tax 未声明，按 0 计（收紧方向，不会放宽门槛）。")
        p_star_var = compute_P_competitive(
            p_star, inputs.fixed_pretax, inputs.vat_rate,
            inputs.surtax_rate, sm, et,
        )
        inputs_used.update(
            ["P_star", "fixed_pretax", "vat_rate", "surtax_rate",
             "supplied_material", "env_tax"]
        )

    # ---- P*_eff 三 term：任一不可算 ⇒ 整体不落值（丢项=静默放宽）---------
    terms: dict[str, float | None] = {"model_lower": None, "cost_line": None,
                                      "cap_floor": None}
    eff_missing: list[str] = []

    if floor_missing:
        eff_missing.append("μ/floor（OI-DQ-A）")
    else:
        terms["model_lower"] = model_lower

    pi = inputs.pi_target
    if pi is _UNSET:
        eff_missing.append("π_target（未声明）")
    elif pi is None:
        eff_missing.append("π_target（key 存在取值为空）")
    elif c_missing:
        eff_missing.append("c_i")
    else:
        terms["cost_line"] = (1.0 + float(pi)) * cost_total

    alpha = inputs.alpha_cap
    if alpha is _UNSET:
        eff_missing.append("α_cap（未声明）")
    elif alpha is None:
        eff_missing.append("α_cap（key 存在取值为空）")
    elif capped_only:
        eff_missing.append("α_cap 已声明但存在空 cap 项（声明与数据矛盾）")
    else:
        terms["cap_floor"] = (1.0 - float(alpha)) * cap_total

    p_star_eff: float | None = None
    if eff_missing:
        missing.extend(eff_missing)
    else:
        vals = [v for v in terms.values() if v is not None]
        p_star_eff = max(vals) if vals else None

    delta_p: float | None = None
    if p_star_eff is not None and p_star is not None:
        delta_p = max(0.0, p_star_eff - p_star)

    return PrecheckCertificate(
        # q0 缺 ⇒ 求和本身不完整，证书两侧都不落值（部分和会静默虚低）
        p_min=p_min if not (l_missing or q_missing) else None,
        p_max=(p_max if not (u_missing or q_missing) else None),
        p_max_capped_only=capped_only,
        p_max_capped=p_max_capped if capped_only else None,
        p_star_var=p_star_var,
        p_star_eff=p_star_eff,
        eff_terms=terms,
        delta_p=delta_p,
        missing=tuple(missing),
        inputs_used=frozenset(inputs_used),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# 判定：PC-01..PC-08（§6.2）
# ---------------------------------------------------------------------------

def judge_precheck(
    inputs: PrecheckInputs,
    cert: PrecheckCertificate,
    spec: Mapping[str, Any],
    tolerances: Mapping[str, float] | None = None,
) -> tuple[PrecheckReport, tuple[str, ...]]:
    """对证书逐条落 PC 判据。返回 ``(报告, 缺失容差名单)``。

    判定器只吃 ``inputs`` + ``cert``——不重算任何求和（判据可注入验证）。
    """
    tol_missing: tuple[str, ...] = ()
    # 先按规格解析（含 eps_total 公式合成），再叠加调用方显式覆盖——
    # 调用方传表只是覆盖个别名，不是绕过解析（DV-01：名→数值单一来源）。
    resolved, tol_missing = resolve_tolerances(dict(spec), inputs.instance.P_star)
    if tolerances:
        resolved.update(dict(tolerances))
    eps_total = resolved.get("eps_total")

    inst = inputs.instance
    opt = inst.opt_items
    verdicts: list[PrecheckVerdict] = []
    feasibility_fails = 0

    def _add(check_id: str, status: str, actual: Any, limit: Any, detail: str,
             severity: str = "P0") -> None:
        nonlocal feasibility_fails
        if status == STATUS_FAIL and check_id in ("PC-03", "PC-04", "PC-06", "PC-07"):
            feasibility_fails += 1
        verdicts.append(PrecheckVerdict(check_id, status, actual, limit,
                                        detail, severity))

    # ---- PC-01 rule_set_id ------------------------------------------------
    if inputs.rule_set_id:
        _add("PC-01", STATUS_PASS, inputs.rule_set_id, "非空标量",
             f"rule_set_id = {inputs.rule_set_id}")
    else:
        _add("PC-01", STATUS_BLOCKED, None, "非空标量",
             "rule_set_id 未落值——规则集决定 R_i 结构与 adjustment_scope，"
             "不是参数差异，是结论差异（隐藏依赖 #11）。")

    # ---- PC-02 角色域 -----------------------------------------------------
    if not inputs.role_domain:
        _add("PC-02", STATUS_BLOCKED, None, "角色域制品",
             "角色域未提供（机制制品 competitiveness_classification.json 未读）"
             "——机制缺 ≠ 数据缺，不得按『全部合法』跳过。")
    else:
        bad = [it.item_id for it in inst.items if it.role not in inputs.role_domain]
        if bad:
            _add("PC-02", STATUS_BLOCKED, bad, sorted(inputs.role_domain),
                 f"{len(bad)} 项 role 不在角色域：{bad}——X_opt 与 P_fixed 的"
                 "划分不完整，恒等式无法闭合。")
        else:
            _add("PC-02", STATUS_PASS, [], sorted(inputs.role_domain),
                 f"全部 {len(inst.items)} 项 role 在角色域内。")

    cert_blocked = bool(cert.missing)

    # ---- PC-03 边界证书·下界 ----------------------------------------------
    if cert.p_min is None or cert.p_star_var is None:
        _add("PC-03", STATUS_BLOCKED, cert.p_star_var, cert.p_min,
             "证书不可出：缺失 " + ", ".join(
                 m for m in cert.missing if m.split(":")[0] in
                 ("P_star", "L", "q0", "vat_rate", "surtax_rate", "fixed_pretax"))
             + "——缺失会让算式算不出 ⇒ BLOCKED。")
    elif eps_total is None:
        _add("PC-03", STATUS_BLOCKED, cert.p_star_var, cert.p_min,
             "eps_total 未解析（容差缺失名单：" + ", ".join(tol_missing) + "）。")
    else:
        slack = cert.p_star_var - cert.p_min
        if cert.p_star_var < cert.p_min - eps_total:
            feasibility_fails += 1
            _add("PC-03", STATUS_FAIL, cert.p_star_var, cert.p_min,
                 f"P*_var 低于模型下界，缺口 {cert.p_min - cert.p_star_var:,.2f} 元"
                 " ⇒ INFEASIBLE：结构性不可行必须在这里拦下，不得进求解器。")
        else:
            _add("PC-03", STATUS_PASS, cert.p_star_var, cert.p_min,
                 f"P*_var ≥ P_min（slack {slack:,.2f}）")

    # ---- PC-04 边界证书·上界 ----------------------------------------------
    if cert.p_max is None and cert.p_max_capped_only:
        _add("PC-04", STATUS_SKIP, cert.p_star_var, None,
             "存在合法不限价项 ⇒ P_max 不落值，上界检查 SKIP（合法语义，非缺口）。")
    elif cert.p_max is None or cert.p_star_var is None:
        _add("PC-04", STATUS_BLOCKED, cert.p_star_var, cert.p_max,
             "P_max 或 P*_var 不可出：缺失 " + ", ".join(
                 m for m in cert.missing if m.split(":")[0] in
                 ("P_star", "U", "q0", "vat_rate", "surtax_rate", "fixed_pretax")))
    elif eps_total is None:
        _add("PC-04", STATUS_BLOCKED, cert.p_star_var, cert.p_max,
             "eps_total 未解析。")
    else:
        if cert.p_star_var > cert.p_max + eps_total:
            feasibility_fails += 1
            _add("PC-04", STATUS_FAIL, cert.p_star_var, cert.p_max,
                 f"P*_var 超出模型上界 {cert.p_star_var - cert.p_max:,.2f} 元"
                 " ⇒ INFEASIBLE（P* 定得过高：可竞争预算买不满下界约束的量）。")
        else:
            _add("PC-04", STATUS_PASS, cert.p_star_var, cert.p_max,
                 f"P*_var ≤ P_max（slack {cert.p_max - cert.p_star_var:,.2f}）")

    # ---- PC-05 P*_eff 输入就绪 --------------------------------------------
    if cert.p_star_eff is None:
        _add("PC-05", STATUS_BLOCKED, cert.eff_terms, "三 term 全可算",
             "P*_eff 不可出——缺失 " + "; ".join(
                 m for m in cert.missing if ("π_target" in m or "α_cap" in m
                                             or "μ" in m or "c_i" in m))
             + "。丢项取 max 会让下界变弱（静默放宽可行性门槛），故宁 BLOCKED。")
    else:
        _add("PC-05", STATUS_PASS, cert.eff_terms, "三 term 全可算",
             f"P*_eff 三 term 就绪：{cert.eff_terms}")

    # ---- PC-06 有效下界 ----------------------------------------------------
    if cert.p_star_eff is None or inst.P_star is None:
        _add("PC-06", STATUS_BLOCKED, inst.P_star, cert.p_star_eff,
             "P*_eff 或 P* 缺失，有效下界判不了（PC-05 连带）。")
    elif eps_total is None:
        _add("PC-06", STATUS_BLOCKED, inst.P_star, cert.p_star_eff,
             "eps_total 未解析。")
    else:
        if inst.P_star < cert.p_star_eff - eps_total:
            feasibility_fails += 1
            _add("PC-06", STATUS_FAIL, inst.P_star, cert.p_star_eff,
                 f"P* 低于有效总价下界，ΔP = {cert.delta_p:,.2f} 元 ⇒ INFEASIBLE"
                 "（P* 定得过低：上调 P* 重新预检，§6.3）。")
        else:
            _add("PC-06", STATUS_PASS, inst.P_star, cert.p_star_eff,
                 f"P* ≥ P*_eff（ΔP = {cert.delta_p:,.2f}）")

    # ---- PC-07 模型自相矛盾 ------------------------------------------------
    t1 = cert.eff_terms.get("model_lower")
    if t1 is None or (cert.p_max is None and not cert.p_max_capped_only):
        _add("PC-07", STATUS_BLOCKED, t1, cert.p_max,
             "model_lower 或 P_max 不可出，一致性判不了。")
    elif cert.p_max is None:
        _add("PC-07", STATUS_SKIP, t1, None,
             "存在合法不限价项 ⇒ 无完整上界可比，自相矛盾检查 SKIP。")
    elif eps_total is None:
        _add("PC-07", STATUS_BLOCKED, t1, cert.p_max, "eps_total 未解析。")
    else:
        if t1 > cert.p_max + eps_total:
            feasibility_fails += 1
            _add("PC-07", STATUS_FAIL, t1, cert.p_max,
                 f"模型下界之和超过上界之和 {t1 - cert.p_max:,.2f} 元 ⇒ "
                 "μ_i 与 δ_i 设置冲突（模型自相矛盾，数据校验失败）。")
        else:
            _add("PC-07", STATUS_PASS, t1, cert.p_max,
                 f"model_lower ≤ P_max（slack {cert.p_max - t1:,.2f}）")

    # ---- PC-08 合同类型 ----------------------------------------------------
    if inputs.contract_type is None:
        _add("PC-08", STATUS_SKIP, None, "非 LUMP_SUM",
             "contract_type 未声明——沉默不是断言，不按非 LUMP_SUM 继续。", "P1")
    elif str(inputs.contract_type).upper() == "LUMP_SUM":
        _add("PC-08", STATUS_WARN, inputs.contract_type, "非 LUMP_SUM",
             "总价合同 ⇒ 模型不给单价建议（§5.6），仅出预检与体检。", "P1")
    else:
        _add("PC-08", STATUS_PASS, inputs.contract_type, "非 LUMP_SUM",
             f"contract_type = {inputs.contract_type}", "P1")

    # ---- 聚合 --------------------------------------------------------------
    # SKIP 不参与最严竞争（T03-04 同款裁定）：否则带未激活判据的报告
    # 永远到不了 PASS。全部 SKIP = 一个判据都没判成 ⇒ BLOCKED。
    judged = [v.status for v in verdicts if v.status != STATUS_SKIP]
    if not verdicts or not judged:
        overall = STATUS_BLOCKED
    else:
        overall = _worst(judged)
    feasibility = STATUS_FAIL if feasibility_fails else overall

    report = PrecheckReport(
        certificate=cert, verdicts=tuple(verdicts),
        feasibility=feasibility, overall=overall,
    )
    return report, tol_missing


def precheck_report(inputs: PrecheckInputs, spec: Mapping[str, Any] | None = None,
                    tolerances: Mapping[str, float] | None = None) -> PrecheckReport:
    """端到端入口：算证书 + 判定。"""
    sp = spec if spec is not None else load_precheck_spec()
    cert = build_certificate(inputs)
    report, _ = judge_precheck(inputs, cert, sp, tolerances)
    return report
