"""T04-00《Phase 1 精确性条件》的机械判定器。

**这份文件存在的理由**：Phase 1 的「排序 + 二分 + 贪心定容」算法只在很窄的
条件下才与真实最优解一致。没有这份判定器，「Phase 1 与 Phase 2 对拍一致」
这句话就无法限定范围——**在不满足条件的实例上，两条路径不一致是正确行为**，
把它们一并判为「模型有 bug」会把正确的实现改坏。

设计纪律（见 config/phase1_exactness_spec.json）：

* 每条判据都必须能被**错误的值否定**。「r_eff 等于 r_eff」不是判据；
  「r_eff 与 r 的偏序是否一致」才是（CE-02 就是它被否定的见证）。
* 缺失让算式算不出 → ``BLOCKED``；说了但说错 → ``FAIL``；
  只是「结论说不清出处」→ ``WARN``（ADR-0013 三档治理）。
* 条件分两组：A 组（EC-1..EC-7）违反 ⇒ 阈值分割解**不是**最优解；
  B 组（EC-8/EC-9）违反 ⇒ 数学结论仍成立，只是算法或输出环节须走分支。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ..contracts.pricing_card import ResolvedParameters
from .instance import (
    PRICE_RESOLUTION,
    ROLE_OPTIMIZABLE,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_WARN,
    Phase1Instance,
    Phase1Item,
)

#: 判据编号——与 config/phase1_exactness_spec.json 的 conditions[].id 逐字一致。
#: A 组在前（违反即否决精确性），B 组在后（违反只加实现性义务）。
CONDITION_IDS: tuple[str, ...] = (
    "EC-1", "EC-2", "EC-3", "EC-4", "EC-5", "EC-6", "EC-7", "EC-8", "EC-9",
)

EXACTNESS_IDS: tuple[str, ...] = CONDITION_IDS[:7]
IMPLEMENTABILITY_IDS: tuple[str, ...] = CONDITION_IDS[7:]

#: 判定结论取值——与 spec 的 verdict_domain 同域。
VERDICT_EXACT = "EXACT"
VERDICT_INAPPLICABLE = "INAPPLICABLE"
VERDICT_BLOCKED = "BLOCKED"

#: r_eff 分级容差（§3.7 预处理 2 的 eps_r）。
EPS_R = 1e-6

#: 精度默认值——**仅作函数缺省**，调用方（CLI）必须从 precision_profile 传入。
DEFAULT_EPS_ABS = 0.01
DEFAULT_EPS_PRICE = 1e-9


@dataclass(frozen=True)
class ConditionResult:
    """单条条件的判定结果。"""

    id: str
    group: str
    name: str
    status: str
    detail: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "group": self.group,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class ExactnessVerdict:
    """总体结论。

    ``verdict`` 只看 A 组；``implementation_notes`` 收集 B 组的义务。
    把两者分开，是为了避免「舍入调和这类输出环节义务」污染
    「阈值分割解是否最优」这个数学判断——混在一起会让 verdict 永远不是 EXACT，
    从而失去区分力。
    """

    verdict: str
    conditions: tuple[ConditionResult, ...]
    implementation_notes: tuple[str, ...] = ()
    sort_key: tuple[tuple[str, float], ...] = ()
    solver_form: str = "LP"

    def status_of(self, cond_id: str) -> str | None:
        for c in self.conditions:
            if c.id == cond_id:
                return c.status
        return None

    def failures(self) -> tuple[ConditionResult, ...]:
        return tuple(c for c in self.conditions if c.status in (STATUS_FAIL, STATUS_BLOCKED))

    @property
    def exact(self) -> bool:
        """阈值分割解在本实例上是否与 P_A 最优解一致。"""
        return self.verdict == VERDICT_EXACT

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "solver_form": self.solver_form,
            "exact": self.exact,
            "sort_key": [[k, v] for k, v in self.sort_key],
            "conditions": [c.to_dict() for c in self.conditions],
            "implementation_notes": list(self.implementation_notes),
        }


def iter_conditions(verdict: ExactnessVerdict) -> Iterable[ConditionResult]:
    return iter(verdict.conditions)


# ---------------------------------------------------------------------------
# 逐条判据
# ---------------------------------------------------------------------------


def _items_with_r(instance: Phase1Instance, resolved: ResolvedParameters):
    """(item, r, r_eff) 三元组，只含 r 可算的可优化项。"""
    out = []
    for item in instance.opt_items:
        r = item.r()
        if r is None:
            continue
        out.append((item, r, instance.r_eff(item, resolved)))
    return out


def _ec1(instance: Phase1Instance) -> ConditionResult:
    """C1 作用域完备性——C1 求和集合必须恰为可自由取值的项集合。"""
    outside = [i.item_id for i in instance.items
               if i.role != ROLE_OPTIMIZABLE and i.in_c1_scope]
    inside_missing = [i.item_id for i in instance.items
                      if i.role == ROLE_OPTIMIZABLE and not i.in_c1_scope]
    if not instance.opt_items:
        return ConditionResult(
            "EC-1", "EXACTNESS", "C1 作用域完备性", STATUS_FAIL,
            "实例没有任何 OPTIMIZABLE 项——Phase 1 无变量可优化",
        )
    if outside or inside_missing:
        merged = [*(f"{i}(不可优化却在求和域)" for i in outside),
                  *(f"{i}(可优化却不在求和域)" for i in inside_missing)]
        return ConditionResult(
            "EC-1", "EXACTNESS", "C1 作用域完备性", STATUS_FAIL,
            "C1 作用域与可自由取值项集合不一致：" + "、".join(merged)
            + "。目标系数与 C1 系数不成比例，排序键不存在（见 CE-01）",
            tuple(outside) + tuple(inside_missing),
        )
    return ConditionResult(
        "EC-1", "EXACTNESS", "C1 作用域完备性", STATUS_PASS,
        f"C1 求和域 = {len(instance.c1_scope_items)} 项，与可优化项集合一致",
    )


def _ec2(instance: Phase1Instance, resolved: ResolvedParameters) -> ConditionResult:
    """排序键正确性——r_eff 与 r 的严格偏序是否一致。

    **不用「候选键逐一比较是否相同」**：``1 + alpha`` 在 alpha 全为 0 时
    对全部项取同一值（平序），若把「平」也算作「不同排序」，几乎所有实例
    都会 WARN，判据随即失去区分力。因此只比较**严格偏序**：
    若在 r 上 i 严格先于 j，在 r_eff 上却反向，那才是「误用键会得到不同解」。
    """
    pairs = _items_with_r(instance, resolved)
    if len(pairs) < 2:
        return ConditionResult(
            "EC-2", "EXACTNESS", "排序键正确性", STATUS_PASS,
            f"可算 r_eff 的项仅 {len(pairs)} 个，无可比较的排序对",
        )
    inversions: list[str] = []
    for a in range(len(pairs)):
        for b in range(a + 1, len(pairs)):
            ia, ra, ea = pairs[a]
            ib, rb, eb = pairs[b]
            if ea is None or eb is None:
                continue
            if (ra - rb) * (ea - eb) < 0:
                inversions.append(
                    f"{ia}(r={ra:.4f}, r_eff={ea:.4f}) 与 "
                    f"{ib}(r={rb:.4f}, r_eff={eb:.4f})"
                )
    if inversions:
        return ConditionResult(
            "EC-2", "EXACTNESS", "排序键正确性", STATUS_WARN,
            "r_eff 与 r 的排序不一致（" + "；".join(inversions)
            + "）——本实例对排序键的选择敏感：误用 r 排序会得到"
            "满足全部约束但次优的解（见 CE-02）。实现必须按 r_eff 排序并把"
            "本项记入体检单「临界/倒挂项」栏",
            tuple(inversions),
        )
    return ConditionResult(
        "EC-2", "EXACTNESS", "排序键正确性", STATUS_PASS,
        "r_eff 与 r 的严格偏序一致——本实例对排序键的选择不敏感",
    )


def _ec3(instance: Phase1Instance) -> ConditionResult:
    """权重正性——q0 > 0（缺失与 0 必须机器可区分）。"""
    missing = [i.item_id for i in instance.opt_items if i.q0 is None]
    zero = [i.item_id for i in instance.opt_items if i.q0 == 0]
    if missing:
        return ConditionResult(
            "EC-3", "EXACTNESS", "权重正性", STATUS_BLOCKED,
            "可优化项 q0 缺失：" + "、".join(missing) + "——排序键算不出，"
            "不得降级为 0 或默认值（ADR-0004）",
            tuple(missing),
        )
    if zero:
        return ConditionResult(
            "EC-3", "EXACTNESS", "权重正性", STATUS_FAIL,
            "可优化项 q0 = 0：" + "、".join(zero)
            + "——r 无定义、a_i = 0 使该变量脱离 C1 约束（见 CE-03）。"
            "应按 §3.7 预处理 1 剔除排序并锁定 p_i = base_i",
            tuple(zero),
        )
    return ConditionResult(
        "EC-3", "EXACTNESS", "权重正性", STATUS_PASS,
        f"{len(instance.opt_items)} 个可优化项 q0 > 0",
    )


def _ec4(instance: Phase1Instance, resolved: ResolvedParameters) -> ConditionResult:
    """系数非负性——r_eff >= 0（收入非负）。"""
    pairs = _items_with_r(instance, resolved)
    negative = [(i.item_id, e) for i, _r, e in pairs if e is not None and e < 0]
    if negative:
        detail = "、".join(f"{iid}(r_eff={e:.4f})" for iid, e in negative)
        return ConditionResult(
            "EC-4", "EXACTNESS", "系数非负性", STATUS_FAIL,
            f"r_eff < 0：{detail}——分段斜率系数为负使结算收入为负（非物理）。"
            "根因通常是 rho_plus > 1 或 rho_minus < -1，应由规则卡层拦截（见 CE-04）",
            tuple(iid for iid, _ in negative),
        )
    return ConditionResult(
        "EC-4", "EXACTNESS", "系数非负性", STATUS_PASS,
        "全部可优化项 r_eff >= 0——单价与结算收入单调同向",
    )


def _ec5(instance: Phase1Instance, resolved: ResolvedParameters) -> ConditionResult:
    """非退化——r_eff 不存在「可容纳总价分配」的重复平台。"""
    pairs = _items_with_r(instance, resolved)
    groups: dict[float, list[Phase1Item]] = {}
    for item, _r, e in pairs:
        if e is None:
            continue
        key = round(e / EPS_R)
        groups.setdefault(key, []).append(item)
    platforms = []
    for _key, members in groups.items():
        if len(members) < 2:
            continue
        span = 0.0
        for m in members:
            lo = 0.0 if m.L is None else m.L * (m.q0 or 0.0)
            hi = None if m.U is None else m.U * (m.q0 or 0.0)
            if hi is None:
                span = float("inf")
                break
            span += hi - lo
        if span > 0:
            platforms.append(([m.item_id for m in members], span))

    if platforms:
        desc = "、".join(f"{{{','.join(ids)}}}(可分配区间 {span:g})" for ids, span in platforms)
        status = STATUS_PASS if instance.tie_break_policy else STATUS_FAIL
        tail = (
            f"已声明 tie-break = {instance.tie_break_policy}"
            if instance.tie_break_policy
            else "实例未声明 tie_break_policy——多最优解下 §4.1 的三级变量一致性"
                 "判定不可执行，须先设 canonical tie-break（T04-06B）"
        )
        return ConditionResult(
            "EC-5", "EXACTNESS", "非退化", status,
            f"存在 r_eff 重复平台：{desc}——λ 落在平台，最优解不唯一。{tail}"
            "（见 CE-05）",
            tuple(i for ids, _ in platforms for i in ids),
        )
    return ConditionResult(
        "EC-5", "EXACTNESS", "非退化", STATUS_PASS,
        "无可容纳总价分配的 r_eff 重复平台",
    )


def _ec6(instance: Phase1Instance) -> ConditionResult:
    """软约束不激活——C6/C9/C10/C11/C12/C13 均不激活。"""
    active = tuple(instance.active_soft_constraints)
    if "C7" in active or any(str(a).upper() == "C7" for a in active):
        return ConditionResult(
            "EC-6", "EXACTNESS", "软约束不激活", STATUS_FAIL,
            "C7 已激活：问题升为 MILP，KKT 与阈值分割均不适用，"
            "须走 T04-07 独立验收协议",
            ("C7",),
        )
    if active:
        return ConditionResult(
            "EC-6", "EXACTNESS", "软约束不激活", STATUS_FAIL,
            "已激活软约束：" + "、".join(active)
            + "——C6 引入 q1 权重（与 C1 的 q0 权重不成比例）使结构变为"
            "多阈值分层；C11 的 MAD 线性化引入全项耦合（含均值 p̄）使阈值结构"
            "整体失效。该实例越出 Phase 1 论域（见 CE-06）",
            active,
        )
    return ConditionResult(
        "EC-6", "EXACTNESS", "软约束不激活", STATUS_PASS,
        "C6/C9/C10/C11/C12/C13 均未激活——问题退化为 A 组 P_A",
    )


def _ec7(instance: Phase1Instance, resolved: ResolvedParameters) -> ConditionResult:
    """可行域非空且边界自洽——L <= U 且 B 落在加权边界内。"""
    bad_box = [(i.item_id, i.L, i.U) for i in instance.opt_items
               if i.L is not None and i.U is not None and i.L > i.U]
    if bad_box:
        desc = "、".join(f"{iid}(L={l}, U={u})" for iid, l, u in bad_box)
        return ConditionResult(
            "EC-7", "EXACTNESS", "可行域非空且边界自洽", STATUS_FAIL,
            f"箱型区间倒置：{desc}——可行域为空，应由 D07 在预处理阶段拦截",
            tuple(iid for iid, _l, _u in bad_box),
        )
    if instance.B is None:
        return ConditionResult(
            "EC-7", "EXACTNESS", "可行域非空且边界自洽", STATUS_BLOCKED,
            "实例未给出 B = P*_competitive——C1 不可复核（未定态，不得判 PASS）",
        )

    # 边界证书：只用**有限**上界的项求和；有空 cap 项时上界侧不可判（由 EC-9 记 WARN）
    lo = 0.0
    hi = 0.0
    hi_finite = True
    for item in instance.c1_scope_items:
        q0 = item.q0 or 0.0
        lo += (item.L or 0.0) * q0
        if item.U is None:
            hi_finite = False
        else:
            hi += item.U * q0

    if instance.B < lo - 1e-9:
        return ConditionResult(
            "EC-7", "EXACTNESS", "可行域非空且边界自洽", STATUS_FAIL,
            f"B = {instance.B:g} < P_min = {lo:g}——不可行，应走 §6.3 放弃投标"
            f"判据表（上调 P* 重新预检），不得借不平衡报价把不可行变成"
            f"「可行」（见 CE-07）",
        )
    if hi_finite and instance.B > hi + 1e-9:
        return ConditionResult(
            "EC-7", "EXACTNESS", "可行域非空且边界自洽", STATUS_FAIL,
            f"B = {instance.B:g} > P_max = {hi:g}——不可行（见 CE-07）",
        )
    tail = "" if hi_finite else "（上界侧含不限价项，只验了下界侧）"
    return ConditionResult(
        "EC-7", "EXACTNESS", "可行域非空且边界自洽", STATUS_PASS,
        f"B = {instance.B:g} ∈ [P_min = {lo:g}, "
        f"{'P_max = %g' % hi if hi_finite else '+inf'}] {tail}".rstrip(),
    )


def _ec8(
    instance: Phase1Instance,
    eps_abs: float,
    eps_price: float,
) -> ConditionResult:
    """舍入可调和性——舍入残差上界与 eps_total 的量级对比。"""
    if instance.B is None:
        return ConditionResult(
            "EC-8", "IMPLEMENTABILITY", "舍入可调和性", STATUS_BLOCKED,
            "实例未给出 B——eps_total 算不出（未定态，不得判 PASS）",
        )
    sum_q0 = 0.0
    for item in instance.c1_scope_items:
        q0 = item.q0
        if q0 is None:
            return ConditionResult(
                "EC-8", "IMPLEMENTABILITY", "舍入可调和性", STATUS_BLOCKED,
                f"{item.item_id} 的 q0 缺失——加权残差上界算不出",
            )
        sum_q0 += q0

    half = PRICE_RESOLUTION / 2.0
    bound = half * sum_q0
    eps_total = max(eps_abs, eps_price * instance.B)
    if bound <= eps_total:
        return ConditionResult(
            "EC-8", "IMPLEMENTABILITY", "舍入可调和性", STATUS_PASS,
            f"舍入残差上界 {bound:g} ≤ eps_total {eps_total:g}——舍入不构成风险",
        )
    if instance.rounding_reconciliation_present:
        return ConditionResult(
            "EC-8", "IMPLEMENTABILITY", "舍入可调和性", STATUS_WARN,
            f"舍入残差上界 {bound:g} 远超 eps_total {eps_total:g}"
            f"（半分辨率 {half:g} × Σq0 {sum_q0:g}）——**误差与工程量同尺度**，"
            "与项数无关的 eps_abs 覆盖不了。已声明调和环节，义务："
            "S2 的舍入后复验必须由 T06-06 TotalPriceReconciliation 承担"
            "（见 CE-08）",
        )
    return ConditionResult(
        "EC-8", "IMPLEMENTABILITY", "舍入可调和性", STATUS_FAIL,
        f"舍入残差上界 {bound:g} 远超 eps_total {eps_total:g}，且实例未声明"
        "舍入调和环节——S2 的舍入后复验无处落地（见 CE-08）",
    )


def _ec9(instance: Phase1Instance) -> ConditionResult:
    """上界有限性——B 组：影响前缀和算法，不影响定理。"""
    no_cap = [i.item_id for i in instance.opt_items if i.U is None]
    if no_cap:
        return ConditionResult(
            "EC-9", "IMPLEMENTABILITY", "上界有限性", STATUS_WARN,
            f"{len(no_cap)} 项不限价（cap 空，合法语义 ALLOW_EMPTY_NO_CAP）："
            + "、".join(no_cap)
            + "——阈值分割定理的交换论证不要求 U_i 有限，故数学仍精确；"
            "受损的是「前缀和 + 二分」：S(k) 含 +inf 使比较退化。"
            "义务：实现须把不限价项固定为临界项显式求解。"
            "**禁止**把空 cap 当 0（U=0 < L 直接不可行）或当数据缺口拒收（见 CE-09）",
            tuple(no_cap),
        )
    return ConditionResult(
        "EC-9", "IMPLEMENTABILITY", "上界有限性", STATUS_PASS,
        "全部可优化项均有有限上界",
    )


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


def check_exactness(
    instance: Phase1Instance,
    resolved: ResolvedParameters,
    *,
    eps_abs: float = DEFAULT_EPS_ABS,
    eps_price: float = DEFAULT_EPS_PRICE,
) -> ExactnessVerdict:
    """判定 ``instance`` 是否落在 Phase 1 精确子集内。

    ``resolved`` 必须来自规则卡解析（``resolve_parameters``）——求解层不得
    自造一套阈值。``eps_abs`` / ``eps_price`` 由调用方从 ``precision_profile``
    读入；缺省值只作函数签名完整之用，**不构成项目口径**。
    """
    results = [
        _ec1(instance),
        _ec2(instance, resolved),
        _ec3(instance),
        _ec4(instance, resolved),
        _ec5(instance, resolved),
        _ec6(instance),
        _ec7(instance, resolved),
        _ec8(instance, eps_abs, eps_price),
        _ec9(instance),
    ]

    a_group = [r for r in results if r.group == "EXACTNESS"]
    if any(r.status == STATUS_BLOCKED for r in a_group):
        verdict = VERDICT_BLOCKED
    elif any(r.status == STATUS_FAIL for r in a_group):
        verdict = VERDICT_INAPPLICABLE
    else:
        verdict = VERDICT_EXACT

    notes = tuple(
        f"{r.id} ({r.name}): {r.detail}"
        for r in results
        if r.group == "IMPLEMENTABILITY" and r.status == STATUS_WARN
    )

    sort_key = tuple(
        (item.item_id, e)
        for item, _r, e in _items_with_r(instance, resolved)
        if e is not None
    )

    return ExactnessVerdict(
        verdict=verdict,
        conditions=tuple(results),
        implementation_notes=notes,
        sort_key=sort_key,
        solver_form="MILP" if "C7" in instance.active_soft_constraints else "LP",
    )


def _tally(conditions: Iterable[ConditionResult], ids: tuple[str, ...]) -> str:
    counts: dict[str, int] = {}
    for c in conditions:
        if c.id in ids:
            counts[c.status] = counts.get(c.status, 0) + 1
    order = (STATUS_PASS, STATUS_WARN, STATUS_FAIL, STATUS_BLOCKED)
    return " ".join(f"{k}×{counts[k]}" for k in order if counts.get(k))


def overall_line(verdict: ExactnessVerdict) -> str:
    """一行结论——CLI 与 HTML 报告共用，避免两处措辞漂移。"""
    a = _tally(verdict.conditions, EXACTNESS_IDS)
    b = _tally(verdict.conditions, IMPLEMENTABILITY_IDS)
    return (f"结论 {verdict.verdict}｜A 组（精确性）{a}｜"
            f"B 组（可实现性）{b}｜solver_form={verdict.solver_form}")


def condition_status_line(verdict: ExactnessVerdict) -> str:
    """条件层的补充说明——只在与结论有关时返回非空。"""
    failed = [c for c in verdict.conditions
              if c.status in (STATUS_FAIL, STATUS_BLOCKED)
              and c.id in EXACTNESS_IDS]
    if failed:
        return ("被否定的条件：" + "、".join(f"{c.id}({c.name})" for c in failed)
                + "——阈值分割解在此实例上不保证最优")
    if verdict.verdict == VERDICT_EXACT:
        return "A 组全部通过：阈值分割解与 P_A 最优解一致"
    return ""
