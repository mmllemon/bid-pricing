"""T03-01 结算规则引擎 —— 三段调价 / 边界归属 / 规则集分发 / 合同覆盖。

分工（与 ADR-0025/0029/0030/0031 同源）
--------------------------------------
* **公式唯一实现**在 ``contracts/rule_sets``（两版独立实现，T00-07）。
  本模块**不自建任何调价公式**——它是「分发 + 施加覆盖链 + 归一输出」的壳。
  一旦此处出现第二份公式，「同一规则两处说法」会以「Phase 1 与 Phase 2 结果对不上」
  的形式在 T04-04 对拍时才暴露（排查成本远高于集中一次）。
* **参数默认值**来自规则卡（``rho`` 是机制层默认 0，非数据缺省）与
  规格注册表（阈值 / ``p1_source`` / 合法作用域）。
* **判定与计算分离**：``judge_settlement`` 只吃 ``SettlementOutcome`` 与制品，
  不重新计算结算额；它可以被喂入构造的错误结论以验证否定能力。

三态纪律（§8.4）
----------------
``BLOCKED`` = 规则版本未知 / P1 依据缺失 / 输入未定态——**禁止以内置默认值继续计算**
（ADR-0004：未定态不得降级为默认值）。典型触发：``rule_id`` 未注册、``Q0<=0``、
``(Q0, Q1, P0)`` 任一缺失、出现未登记的覆盖键。

★ 关于「未注册 rule_set_id」：``contracts/selector.py`` 的 ``_ruleset_for`` 用
``else`` 兜底到 2024 版——那是**选择器层**的兜底，由其自身状态机与 Gate 0a 把关。
本层**不复制**该兜底：同一规则两处说法即漂移源（用户已两次踩过「改口径漏改老表述」）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts.pricing_card import (
    PricingCardError,
    load_pricing_card,
    resolve_parameters,
)
from .contracts.rule_sets import (
    BRANCH_DECREASE,
    BRANCH_IN_RANGE,
    BRANCH_INCREASE,
    GB50500_2013_RuleSet,
    GBT50500_2024_RuleSet,
    RuleSet,
)
from .paths import config_dir

SPEC_FILENAME = "settlement_rule_spec.json"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_WARN = "WARN"
STATUS_SKIP = "SKIP"

#: 严重度序（SKIP 不参与最严竞争，见 ADR-0029 跨层不变量）
_SEVERITY = {
    STATUS_FAIL: 0,
    STATUS_BLOCKED: 1,
    STATUS_WARN: 2,
    STATUS_SKIP: 3,
    STATUS_PASS: 4,
}

P1_REDETERMINE = "REDETERMINE"
P1_ADJUST_ON_CONTRACT_PRICE = "ADJUST_ON_CONTRACT_PRICE"

#: 实现侧注册表：rule_set_id → RuleSet 实例。
#: 新增规则集必须同时登记进本表与制品 ``rule_set_registry.entries``（SR-04 交叉核对）。
IMPLEMENTATIONS: dict[str, RuleSet] = {
    "GB50500-2013": GB50500_2013_RuleSet(),
    "GB/T50500-2024": GBT50500_2024_RuleSet(),
}


def _worst(statuses: Sequence[str]) -> str:
    """最严状态。**SKIP 不参与竞争**——把 SKIP 排在 PASS 之前会让任何带未激活项的
    报告永远到不了 PASS（ADR-0029 跨层不变量）。"""
    live = [s for s in statuses if s != STATUS_SKIP]
    if not live:
        return STATUS_BLOCKED if statuses else STATUS_BLOCKED
    return min(live, key=lambda s: _SEVERITY.get(s, 2))


# ---------------------------------------------------------------------------
# 数据载体
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractContext:
    """结算所依据的规则上下文。

    ``rule_set_id``   —— 生效规则集；由 Gate 0a / 选择器决定，本层只校验与分发。
    ``overrides``     —— **合同层**（或招标/地方层）对标准参数的覆盖；
                         未登记键 ⇒ BLOCKED（ADR-0007 沉默不是断言）。
    ``source_label``  —— 覆盖来源层标签；Standard 层标签下不得偏离实现常量。
    ``adjustment_scope`` —— 项目级选择项落值（2024 必需；2013 规范明文 SEGMENT）。
                            合同层若在 ``overrides`` 里另给 scope，则覆盖层优先。
    ``declared_by``   —— 依据出处（合同条款号等），留痕用。
    """

    rule_set_id: str
    overrides: Mapping[str, Any] = field(default_factory=dict)
    source_label: str = "contract"
    adjustment_scope: str | None = None
    declared_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_set_id": self.rule_set_id,
            "overrides": dict(self.overrides),
            "source_label": self.source_label,
            "adjustment_scope": self.adjustment_scope,
            "declared_by": self.declared_by,
        }


@dataclass(frozen=True)
class SettlementOutcome:
    """一次结算评估的结论。

    ★ 三个量**不得混用**（SR-08）：
      ``settlement_amount``      结算金额（元，未含税）
      ``effective_price``        = settlement_amount / Q1（**加权平均**结算单价）
      ``adjusted_unit_price``    = P1（调整后的单价本身）
    SEGMENT 增量段 ``effective_price != adjusted_unit_price``——阈值内部分仍按 P0。
    """

    status: str
    rule_id: str
    rule_branch: str | None = None
    r: float | None = None
    settlement_amount: float | None = None
    effective_price: float | None = None
    adjusted_unit_price: float | None = None
    p1_source: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    basis: tuple[str, ...] = ()
    blocked_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "rule_id": self.rule_id,
            "rule_branch": self.rule_branch,
            "r": self.r,
            "settlement_amount": self.settlement_amount,
            "effective_price": self.effective_price,
            "adjusted_unit_price": self.adjusted_unit_price,
            "p1_source": self.p1_source,
            "parameters": dict(self.parameters),
            "basis": list(self.basis),
            "blocked_reason": self.blocked_reason,
        }


# ---------------------------------------------------------------------------
# 规格加载
# ---------------------------------------------------------------------------


def load_settlement_spec(config_path: Path | None = None) -> dict[str, Any]:
    """读结算规则规格。**传目录时自动拼接文件名**（与其它 load_* 同款）。"""
    path = Path(config_path) if config_path is not None else config_dir()
    if path.is_dir():
        path = path / SPEC_FILENAME
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def registry_from_spec(spec: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    entries = spec.get("rule_set_registry", {}).get("entries", ())
    return {str(e["rule_set_id"]): dict(e) for e in entries}


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------


class SettlementRule:
    """结算规则引擎。``evaluate`` 是任务书规定的唯一入口。"""

    def __init__(
        self,
        card: Mapping[str, Any] | None = None,
        *,
        spec: Mapping[str, Any] | None = None,
        implementations: Mapping[str, RuleSet] | None = None,
    ) -> None:
        self.spec = dict(spec) if spec is not None else load_settlement_spec()
        self.registry = registry_from_spec(self.spec)
        self.impls = dict(implementations if implementations is not None
                          else IMPLEMENTATIONS)
        self._card = card
        self._card_loaded = card is not None

    # -- 规则卡（惰性加载；缺失 ⇒ BLOCKED，不以内置默认值顶上）--------------

    def _load_card(self) -> Mapping[str, Any] | None:
        if self._card is not None:
            return self._card
        if self._card_loaded:
            return None
        try:
            self._card = load_pricing_card(config_dir())
        except PricingCardError:
            self._card = None
        self._card_loaded = True
        return self._card

    # -- 入口 ---------------------------------------------------------------

    def evaluate(
        self,
        q0: float | None,
        q1: float | None,
        p0: float | None,
        context: ContractContext | None = None,
    ) -> SettlementOutcome:
        ctx = context if context is not None else ContractContext(rule_set_id="")
        rule_id = str(ctx.rule_set_id or "")

        # ---- ① 未定态：不得降级为 0 或默认值（SR-07）------------------------
        missing = [n for n, v in (("Q0", q0), ("Q1", q1), ("P0", p0))
                   if v is None]
        if missing:
            return self._blocked(
                rule_id,
                f"未定态：{'、'.join(missing)} 缺失，结算金额不可计算"
                "（§8.4 BLOCKED 清单含『P1 依据缺失』）",
            )
        if float(q0) <= 0:
            return self._blocked(
                rule_id,
                "Q0 <= 0：阈值 r = Q1/Q0 无意义，须在数据层按 MISSING_POLICY 处理",
            )

        # ---- ② 规则集分发：未注册 ⇒ BLOCKED（不得落到任一侧默认值，SR-03）---
        entry = self.registry.get(rule_id)
        impl = self.impls.get(rule_id)
        if entry is None or impl is None:
            return self._blocked(
                rule_id,
                f"规则集 {rule_id!r} 未注册：注册表="
                f"{sorted(self.registry)}、实现表={sorted(self.impls)}。"
                "**不得**默认取任一版本（ADR-0004：未定态不降级为默认值）",
            )

        # ---- ③ 参数：注册表默认值 + 覆盖链 ----------------------------------
        params, scope, err = self._resolve(entry, impl, ctx)
        if err is not None:
            return self._blocked(rule_id, err)

        # ---- ④ 分档与公式（唯一实现 = 规则集）--------------------------------
        q0f, q1f, p0f = float(q0), float(q1), float(p0)
        r = q1f / q0f
        branch = impl.classify_branch(
            r,
            decrease_threshold=params["decrease_threshold"],
            increase_threshold=params["increase_threshold"],
        )
        try:
            amount = impl.settlement_amount(
                q0f, q1f, p0f,
                rho_plus=params["rho_plus"], rho_minus=params["rho_minus"],
                scope=scope,
                decrease_threshold=params["decrease_threshold"],
                increase_threshold=params["increase_threshold"],
            )
        except Exception as exc:  # noqa: BLE001 - 规则集拒绝计算 ⇒ BLOCKED
            return self._blocked(rule_id, f"规则集拒绝计算：{exc}")

        if branch == BRANCH_DECREASE:
            p1 = p0f * (1.0 + params["rho_minus"])
        elif branch == BRANCH_INCREASE:
            p1 = p0f * (1.0 - params["rho_plus"])
        else:
            p1 = p0f

        basis = (
            f"rule_id={rule_id}（{impl.standard_code}）",
            f"branch={branch}（r={r:.9f}，阈值 "
            f"[{params['decrease_threshold']}, {params['increase_threshold']}]，"
            f"来源：{params['sources']['increase_threshold']}）",
            f"scope={scope}",
            f"p1_source={impl.p1_source}",
            "ρ±=({}, {})——规范只写『合理』无量化系数，默认 0 为**机制层默认**"
            "而非数据缺省".format(params["rho_plus"], params["rho_minus"]),
        )

        return SettlementOutcome(
            status=STATUS_PASS,
            rule_id=rule_id,
            rule_branch=branch,
            r=r,
            settlement_amount=amount,
            effective_price=amount / q1f,
            adjusted_unit_price=p1,
            p1_source=impl.p1_source,
            parameters=params,
            basis=basis,
        )

    # -- 内部 ---------------------------------------------------------------

    def _blocked(self, rule_id: str, reason: str) -> SettlementOutcome:
        return SettlementOutcome(
            status=STATUS_BLOCKED, rule_id=rule_id, blocked_reason=reason,
            basis=(reason,),
        )

    def _resolve(
        self,
        entry: Mapping[str, Any],
        impl: RuleSet,
        ctx: ContractContext,
    ) -> tuple[dict[str, Any], str | None, str | None]:
        """解析参数与作用域。返回 ``(params, scope, err)``。"""
        # ③-a 跨来源互锁：注册表 ↔ 实现类（SR-04）
        if str(entry.get("p1_source")) != impl.p1_source:
            return {}, None, (
                f"p1_source 两处说法不一致：注册表={entry.get('p1_source')!r}、"
                f"实现={impl.p1_source!r}（rule_id={impl.rule_set_id}）"
            )
        if tuple(entry.get("supported_scopes", ())) != tuple(impl.supported_scopes):
            return {}, None, (
                f"supported_scopes 两处说法不一致：注册表="
                f"{entry.get('supported_scopes')}、实现={list(impl.supported_scopes)}"
            )
        if float(entry.get("increase_threshold")) != self._impl_threshold(impl, "inc"):
            return {}, None, "increase_threshold 注册表与实现不一致"
        if float(entry.get("decrease_threshold")) != self._impl_threshold(impl, "dec"):
            return {}, None, "decrease_threshold 注册表与实现不一致"

        # ③-b 参数默认值：rho 来自规则卡（机制层默认 0），阈值来自注册表
        card = self._load_card()
        if card is None:
            rho_plus = rho_minus = 0.0
            card_scope = None
        else:
            rho_plus = float(card["parameters"]["rho_plus"])
            rho_minus = float(card["parameters"]["rho_minus"])
            card_scope = card.get("adjustment_scope")

        params: dict[str, Any] = {
            "rho_plus": rho_plus,
            "rho_minus": rho_minus,
            "increase_threshold": float(entry["increase_threshold"]),
            "decrease_threshold": float(entry["decrease_threshold"]),
            "sources": {
                "rho_plus": "pricing_rule_card",
                "rho_minus": "pricing_rule_card",
                "increase_threshold": "settlement_rule_spec",
                "decrease_threshold": "settlement_rule_spec",
            },
        }

        # ③-c 覆盖链：合同 > 招标 > 地方 > 标准（未登记键 ⇒ BLOCKED，SR-06）
        overrides = dict(ctx.overrides or {})
        registered = set(self.spec.get("override_policy", {}).get(
            "registered_keys", ()))
        unknown = sorted(k for k in overrides if k not in registered)
        if unknown:
            return {}, None, (
                f"出现未登记的覆盖键 {unknown}：已登记键 = "
                f"{sorted(registered)}。未登记约定不得静默忽略（ADR-0007）"
            )
        standard_labels = {"standard", "pricing_rule_card"}
        for key, value in overrides.items():
            if value is None:
                continue
            if key in ("increase_threshold", "decrease_threshold") and \
                    ctx.source_label in standard_labels:
                baseline = (self._impl_threshold(impl, "inc")
                            if key == "increase_threshold"
                            else self._impl_threshold(impl, "dec"))
                if float(value) != baseline:
                    return {}, None, (
                        f"Standard 层标签 {ctx.source_label!r} 下覆盖 {key}="
                        f"{value} 与实现常量 {baseline} 不一致"
                    )
            if key == "adjustment_scope":
                continue          # 作用域单独处理（合法性随规则集而变）
            params[key] = float(value) if key != "source" else value
            params["sources"][key] = ctx.source_label

        # ③-d 作用域：合同覆盖 > 项目级落值 > 规则集默认
        scope = overrides.get("adjustment_scope", ctx.adjustment_scope)
        if scope is None:
            scope = card_scope
        if scope is None:
            scope = ("SEGMENT" if len(impl.supported_scopes) == 1 else None)
        if scope not in impl.supported_scopes:
            return {}, None, (
                f"adjustment_scope={scope!r} 不在 {impl.rule_set_id} 的合法取值 "
                f"{list(impl.supported_scopes)} 内"
                + ("（2013 §9.6.2 明文 SEGMENT，落 FULL 判 BLOCKED，不得静默覆盖）"
                   if len(impl.supported_scopes) == 1 else
                   "（2024 未明说 ⇒ 项目级选择项，缺失即未冻结）")
            )
        params["adjustment_scope"] = scope
        params["sources"]["adjustment_scope"] = (
            ctx.source_label if "adjustment_scope" in overrides else
            ("project_selection" if card_scope is not None else "rule_set_registry")
        )
        return params, scope, None

    @staticmethod
    def _impl_threshold(impl: RuleSet, which: str) -> float:
        from .contracts.rule_sets import DECREASE_THRESHOLD, INCREASE_THRESHOLD

        return INCREASE_THRESHOLD if which == "inc" else DECREASE_THRESHOLD


def evaluate_settlement(
    q0: float | None,
    q1: float | None,
    p0: float | None,
    context: ContractContext | None = None,
    *,
    card: Mapping[str, Any] | None = None,
    spec: Mapping[str, Any] | None = None,
) -> SettlementOutcome:
    """模块级便捷入口（等价于 ``SettlementRule(...).evaluate(...)``）。"""
    return SettlementRule(card=card, spec=spec).evaluate(q0, q1, p0, context)


# ---------------------------------------------------------------------------
# 判定器（T03-01 SR-01..SR-09）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SettlementVerdict:
    judge_id: str
    status: str
    detail: str = ""
    actual: Any = None
    limit: Any = None
    severity: str = "P0"


@dataclass(frozen=True)
class SettlementReport:
    verdicts: tuple[SettlementVerdict, ...] = ()
    overall: str = STATUS_BLOCKED

    def of(self, judge_id: str) -> SettlementVerdict | None:
        for v in self.verdicts:
            if v.judge_id == judge_id:
                return v
        return None

    def verdict(self) -> str:
        """P0 判据的最严状态（P1 的 FAIL 不阻塞 P0 主干）。"""
        p0 = [v.status for v in self.verdicts if v.severity == "P0"]
        if not p0:
            return STATUS_BLOCKED
        return _worst(p0)

    def verdict_all(self) -> str:
        if not self.verdicts:
            return STATUS_BLOCKED
        return _worst([v.status for v in self.verdicts])


def judge_settlement(
    engine: SettlementRule | None = None,
    *,
    spec: Mapping[str, Any] | None = None,
    engine_factory: Callable[[], SettlementRule] | None = None,
) -> SettlementReport:
    """在**制品固定的探针网格**上跑 SR-01..SR-09。

    ``engine_factory`` 是注入点：测试可以塞入一个「边界写反」「覆盖不生效」
    「默认取 2024」的坏引擎，验证判据确实能 FAIL——只对正确实现在放行的判据
    等于没判（「能被错误值否定」与「不能被正确值否定」是同一要求两方向）。
    """
    sp = dict(spec) if spec is not None else (engine.spec if engine else
                                              load_settlement_spec())
    grid = sp["probe_grid"]
    make = engine_factory or (lambda: engine or SettlementRule(spec=sp))
    eng = make()

    q0 = float(grid["q0"])
    p0 = float(grid["p0"])
    rho_p = float(grid["rho_plus_probe"])
    rho_m = float(grid["rho_minus_probe"])
    verdicts: list[SettlementVerdict] = []

    def run(rule_id: str, r: float, *, scope: str | None = "SEGMENT",
            overrides: Mapping[str, Any] | None = None,
            engine_obj: SettlementRule | None = None) -> SettlementOutcome:
        ctx = ContractContext(
            rule_set_id=rule_id,
            overrides=dict(overrides or {"rho_plus": rho_p,
                                         "rho_minus": rho_m}),
            adjustment_scope=scope,
        )
        return (engine_obj or eng).evaluate(q0, q0 * r, p0, ctx)

    # ---- SR-01 三段覆盖 ----------------------------------------------------
    branches: dict[str, str] = {}
    for r in grid["r_values"]:
        out = run("GB/T50500-2024", r)
        if out.rule_branch:
            branches[out.rule_branch] = f"r={r}"
    covered = sorted(branches)
    verdicts.append(SettlementVerdict(
        "SR-01",
        STATUS_PASS if len(covered) == 3 else STATUS_FAIL,
        f"固定网格覆盖分支：{covered}（每支首见：{branches}）",
        actual=len(covered), limit=3,
    ))

    # ---- SR-02 边界归属（双向） -------------------------------------------
    problems: list[str] = []
    for pair in grid["boundary_pairs"]:
        r = float(pair["r"])
        expect_lo, expect_hi = pair["expected"]
        got_lo = run("GB/T50500-2024", r - 1e-6).rule_branch
        got_eq = run("GB/T50500-2024", r).rule_branch
        got_hi = run("GB/T50500-2024", r + 1e-6).rule_branch
        if got_lo != expect_lo:
            problems.append(f"r={r}−ε 期望 {expect_lo} 实得 {got_lo}")
        if got_eq != "IN_RANGE":
            problems.append(f"r={r} 期望 IN_RANGE 实得 {got_eq}")
        if got_hi != expect_hi:
            problems.append(f"r={r}+ε 期望 {expect_hi} 实得 {got_hi}")
    verdicts.append(SettlementVerdict(
        "SR-02",
        STATUS_PASS if not problems else STATUS_FAIL,
        "；".join(problems) or "两个边界的 ±ε 三侧归属全部正确（J2 严格不等式）",
        actual=len(problems), limit=0,
    ))

    # ---- SR-03 规则集分发 --------------------------------------------------
    bogus = eng.evaluate(q0, q0 * 1.2, p0,
                         ContractContext(rule_set_id="GB50500-9999"))
    echo_bad = bogus.status == STATUS_PASS or bogus.rule_id != "GB50500-9999"
    ok_dispatch = all(
        run(rid, 1.3).rule_id == rid for rid in grid["rule_sets"]
    )
    verdicts.append(SettlementVerdict(
        "SR-03",
        STATUS_FAIL if (echo_bad or not ok_dispatch) else STATUS_PASS,
        ("未注册 id 被放行或其 rule_id 被回填" if echo_bad else
         ("已注册 id 未按请求分发" if not ok_dispatch else
          f"未注册 id ⇒ {bogus.status}；已注册 id 原样回传")),
        actual=f"未注册⇒{bogus.status}", limit="BLOCKED 且 rule_id 不被回填",
    ))

    # ---- SR-04 P1 来源随规则集分发 ----------------------------------------
    p1_sources = {rid: run(rid, 1.3).p1_source for rid in grid["rule_sets"]}
    entry_sources = {rid: eng.registry.get(rid, {}).get("p1_source")
                     for rid in grid["rule_sets"]}
    impl_sources = {rid: getattr(eng.impls.get(rid), "p1_source", None)
                    for rid in grid["rule_sets"]}
    triple_ok = all(
        p1_sources[rid] == entry_sources[rid] == impl_sources[rid]
        for rid in grid["rule_sets"]
    )
    distinct = len(set(p1_sources.values())) == len(p1_sources)
    verdicts.append(SettlementVerdict(
        "SR-04",
        STATUS_PASS if (triple_ok and distinct) else STATUS_FAIL,
        f"出口={p1_sources}；注册表={entry_sources}；实现={impl_sources}"
        + ("" if distinct else "——两版 p1_source 相同，等于把两种生成方式混为一谈"),
        actual=len(set(p1_sources.values())),
        limit=len(grid["rule_sets"]),
    ))

    # ---- SR-05 合同覆盖阈值生效 -------------------------------------------
    wit = grid["threshold_override_witness"]
    rid_w = str(wit["rule_set_id"])
    r_w = float(wit["r"])
    base_out = run(rid_w, r_w)
    ovr_out = run(rid_w, r_w,
                  overrides={**wit["override"], "rho_plus": rho_p})
    moved = (base_out.rule_branch != ovr_out.rule_branch
             or base_out.settlement_amount != ovr_out.settlement_amount)
    verdicts.append(SettlementVerdict(
        "SR-05",
        STATUS_PASS if moved else STATUS_FAIL,
        f"见证 r={r_w}：覆盖前 {base_out.rule_branch}/{base_out.settlement_amount}"
        f" → 覆盖后 {ovr_out.rule_branch}/{ovr_out.settlement_amount}"
        + ("" if moved else "——覆盖只记参数、判定仍走常量"),
        actual=ovr_out.rule_branch, limit=f"≠ {base_out.rule_branch}",
    ))

    # ---- SR-06 未登记覆盖键 -----------------------------------------------
    bad_key = eng.evaluate(q0, q0 * 1.3, p0, ContractContext(
        rule_set_id="GB50500-2013", overrides={"threshold_override": 1.05}))
    verdicts.append(SettlementVerdict(
        "SR-06",
        STATUS_PASS if bad_key.status == STATUS_BLOCKED else STATUS_FAIL,
        f"未登记键 ⇒ {bad_key.status}：{bad_key.blocked_reason}",
        actual=bad_key.status, limit=STATUS_BLOCKED,
    ))

    # ---- SR-07 未定态不降级 -----------------------------------------------
    cases = {
        "Q0 缺失": (None, 1.0, p0),
        "Q1 缺失": (q0, None, p0),
        "P0 缺失": (q0, q0, None),
        "Q0=0": (0.0, q0, p0),
    }
    leaks = []
    for name, (a, b, c) in cases.items():
        out = eng.evaluate(a, b, c, ContractContext(rule_set_id="GB50500-2013"))
        if out.status != STATUS_BLOCKED or out.settlement_amount is not None:
            leaks.append(f"{name} ⇒ {out.status}/{out.settlement_amount}")
    verdicts.append(SettlementVerdict(
        "SR-07",
        STATUS_PASS if not leaks else STATUS_FAIL,
        "；".join(leaks) or "四类未定态全部 BLOCKED 且未产出金额（无 0 值降级）",
        actual=len(leaks), limit=0,
    ))

    # ---- SR-08 三量不得混用 -----------------------------------------------
    eps_ratio = float(sp["tolerances"]["eps_ratio"]["value"])
    inc = run("GB/T50500-2024", 1.3, scope="SEGMENT")
    deg = run("GB/T50500-2024", 1.30, scope="SEGMENT",
              overrides={"rho_plus": rho_p})
    inr = run("GB/T50500-2024", 1.0)
    dec = run("GB/T50500-2024", 0.5)
    problems8 = []
    if abs(inc.effective_price - inc.adjusted_unit_price) <= eps_ratio:
        problems8.append("SEGMENT 增量段 effective_price == P1（把两量当同一个）")
    for tag, out in (("区间内", inr), ("减量段", dec)):
        if abs(out.effective_price - out.adjusted_unit_price) > eps_ratio:
            problems8.append(f"{tag} effective_price != P1（SEGMENT 语义下应相等）")
    if abs(deg.settlement_amount - deg.effective_price * q0 * 1.30) > 1e-6:
        problems8.append("effective_price 与 S/Q1 不一致")
    verdicts.append(SettlementVerdict(
        "SR-08",
        STATUS_PASS if not problems8 else STATUS_FAIL,
        "；".join(problems8) or (
            f"SEGMENT 增量段 P1={inc.adjusted_unit_price:.4f} ≠ "
            f"有效单价={inc.effective_price:.4f}；其余段相等"),
        actual=len(problems8), limit=0,
    ))

    # ---- SR-09 与规则集指纹方向对账（跨来源） ------------------------------
    delta = float(grid.get("fingerprint_delta", 1e-9))
    jumps = {
        "GB50500-2013": _engine_jump(eng, "GB50500-2013", "SEGMENT", rho_p, delta),
        "2024-FULL": _engine_jump(eng, "GB/T50500-2024", "FULL", rho_p, delta),
        "2024-SEGMENT": _engine_jump(eng, "GB/T50500-2024", "SEGMENT", rho_p, delta),
    }
    tol = 1e-6
    ok9 = (
        abs(jumps["GB50500-2013"]) <= tol
        and abs(jumps["2024-SEGMENT"]) <= tol
        and jumps["2024-FULL"] < -1e-9
    )
    verdicts.append(SettlementVerdict(
        "SR-09",
        STATUS_PASS if ok9 else STATUS_FAIL,
        f"出口差分跳变量：{ {k: round(v, 9) for k, v in jumps.items()} }"
        "——2013 与 SEGMENT 应≈0（分段累加连续），2024-FULL 应 <0（调整单价跳降）",
        actual=round(jumps["2024-FULL"], 9), limit="< 0",
    ))

    report = SettlementReport(verdicts=tuple(verdicts))
    return SettlementReport(verdicts=report.verdicts, overall=report.verdict())


def _engine_jump(
    eng: SettlementRule, rule_id: str, scope: str,
    rho_probe: float, delta: float,
) -> float:
    """引擎出口的 ``r_eff`` 跳变量（与规则集 ``fingerprint`` 走**不同路径**）。

    同源相减恒为 0（规则⑥），故此处用 ``settlement_amount`` 出口差分，
    而规则集指纹走 ``effective_revenue_multiple`` 差分——两者参数化相同但
    代码路径不同，可互为对账。
    """
    q0, p0 = 1000.0, 100.0

    def r_eff(r: float) -> float:
        out = eng.evaluate(q0, q0 * r, p0, ContractContext(
            rule_set_id=rule_id, adjustment_scope=scope,
            overrides={"rho_plus": rho_probe, "rho_minus": rho_probe}))
        assert out.settlement_amount is not None
        return out.settlement_amount / (q0 * p0)

    return r_eff(1.15 + delta) - r_eff(1.15 - delta)
