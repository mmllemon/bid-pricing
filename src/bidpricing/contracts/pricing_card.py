"""T00-01《计价规则卡》——合同计价与调价口径的机器可执行载体。

规则集选择器（T00-08）回答「用哪一版规范」；本模块回答「拿到
``Q0 / Q1 / P0`` 之后 ``P1`` 怎么算」。两者分工：

* 选择器 —— 判定 **rule_set_id**（机制层，跨项目复用）；
* 规则卡 —— 判定 **P1 公式的参数与口径**（阈值、ρ±、作用域、override 链）。

设计约束（沿用本项目既有纪律）：

1. **唯一事实源**：阈值与分支名的真值在
   ``bidpricing.contracts.rule_sets.base`` 的代码常量里，规则卡 JSON 只是
   **声明**；两侧由 ``tests/test_pricing_card.py`` 双向锁定，改一侧不同步
   另一侧即失败——杜绝「同一规则两处说法」。
2. **未定态 ≠ 违反**（ADR-0004/0005/0007）：参数缺失是 BLOCKED，不是默认值；
   未知 override 键是 BLOCKED，不是静默忽略。
3. **ρ± = 0 是机制层默认**（规范未给量化系数，不得编造），**不是**项目数据
   缺省——因此它参与计算但必须在输出里显式声明其来源，绝不声称
   「规范规定不调整」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .rule_sets.base import (
    BRANCH_DECREASE,
    BRANCH_IN_RANGE,
    BRANCH_INCREASE,
    DECREASE_THRESHOLD,
    INCREASE_THRESHOLD,
)

#: 状态取值——与闸门层/校验层同构
STATUS_PASS = "PASS"
STATUS_BLOCKED = "BLOCKED"

CARD_FILENAME = "pricing_rule_card.json"

#: 允许被上层（合同 / 招标文件 / 地方规则）覆盖的键。
#: 未登记键出现即 BLOCKED——沉默不是断言（ADR-0007）。
REGISTERED_OVERRIDES = (
    "rho_plus",
    "rho_minus",
    "increase_threshold",
    "decrease_threshold",
    "adjustment_scope",
)


class PricingCardError(RuntimeError):
    """规则卡缺失、结构不合法，或出现未登记 override。"""


class UndeterminedP1(RuntimeError):
    """P1 判据所需输入未定态（q0 / q1 / p0 缺失）。"""


@dataclass
class ResolvedParameters:
    """按 override 链解析后的参数。"""

    rho_plus: float
    rho_minus: float
    increase_threshold: float
    decrease_threshold: float
    adjustment_scope: str
    sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rho_plus": self.rho_plus,
            "rho_minus": self.rho_minus,
            "increase_threshold": self.increase_threshold,
            "decrease_threshold": self.decrease_threshold,
            "adjustment_scope": self.adjustment_scope,
            "sources": dict(self.sources),
        }


@dataclass
class P1Resolution:
    """单项 P1 的计算结果与依据。"""

    status: str
    branch: str | None = None
    r: float | None = None
    p0: float | None = None
    p1: float | None = None
    settlement: float | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    basis: list[str] = field(default_factory=list)
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "branch": self.branch,
            "r": self.r,
            "p0": self.p0,
            "p1": self.p1,
            "settlement": self.settlement,
            "parameters": dict(self.parameters),
            "basis": list(self.basis),
            "blocked_reason": self.blocked_reason,
        }


def load_pricing_card(config_dir: Path) -> dict[str, Any]:
    """读取规则卡制品。文件缺失是**未定态**，抛错而非返回空字典。"""
    path = Path(config_dir) / CARD_FILENAME
    if not path.exists():
        raise PricingCardError(
            f"规则卡缺失：{path}。T00-01 未冻结时 P1 口径悬空，"
            "禁止以内置默认值继续计算（ADR-0004：未定态不得降级为默认值）。"
        )
    card = json.loads(path.read_text(encoding="utf-8"))
    for key in ("card_id", "rule_set_id", "adjustment_scope", "parameters",
                "p1_clarifications", "p1_formula"):
        if key not in card:
            raise PricingCardError(f"规则卡缺必填键 {key!r}：{path}")
    return card


def _ordered_overrides(override: dict[str, Any] | None) -> Iterable[tuple[str, Any]]:
    if not override:
        return ()
    return ((k, v) for k, v in override.items() if v is not None)


def resolve_parameters(
    card: dict[str, Any],
    override: dict[str, Any] | None = None,
    *,
    source_label: str = "override",
) -> ResolvedParameters:
    """按 ``precedence_chain`` 解析参数：override 层优先于 Standard 层。

    出现规则卡未登记的 override 键 → ``PricingCardError``（BLOCKED）。
    """
    p = card["parameters"]
    scope = card.get("adjustment_scope")

    resolved = ResolvedParameters(
        rho_plus=float(p["rho_plus"]),
        rho_minus=float(p["rho_minus"]),
        increase_threshold=float(p["increase_threshold"]),
        decrease_threshold=float(p["decrease_threshold"]),
        adjustment_scope=str(scope),
        sources={k: "pricing_rule_card" for k in
                 ("rho_plus", "rho_minus", "increase_threshold",
                  "decrease_threshold", "adjustment_scope")},
    )

    unknown: list[str] = []
    for key, value in _ordered_overrides(override):
        if key not in REGISTERED_OVERRIDES:
            unknown.append(key)
            continue
        setattr(resolved, key, value)
        resolved.sources[key] = source_label

    if unknown:
        raise PricingCardError(
            "出现规则卡未登记的 override 键："
            f"{sorted(unknown)}。已登记键 = {list(REGISTERED_OVERRIDES)}。"
            "未登记约定不得静默忽略——请先补登记再计算（ADR-0007）。"
        )

    # ---- 与代码常量互锁：声明值必须等于实现常量 -------------------------
    if resolved.increase_threshold != INCREASE_THRESHOLD:
        raise PricingCardError(
            f"increase_threshold 声明值 {resolved.increase_threshold} 与实现常量 "
            f"{INCREASE_THRESHOLD} 不一致——同一规则出现两处说法。"
        )
    if resolved.decrease_threshold != DECREASE_THRESHOLD:
        raise PricingCardError(
            f"decrease_threshold 声明值 {resolved.decrease_threshold} 与实现常量 "
            f"{DECREASE_THRESHOLD} 不一致——同一规则出现两处说法。"
        )
    return resolved


def classify_branch(r: float, params: ResolvedParameters) -> str:
    """按 r = Q1/Q0 判分支。阈值来自解析后的参数（可被 override 覆盖）。"""
    if r < params.decrease_threshold:
        return BRANCH_DECREASE
    if r > params.increase_threshold:
        return BRANCH_INCREASE
    return BRANCH_IN_RANGE


def compute_p1(
    q0: float | None,
    q1: float | None,
    p0: float | None,
    card: dict[str, Any],
    override: dict[str, Any] | None = None,
) -> P1Resolution:
    """计算单项的 P1 与结算金额。

    未定态（``q0`` / ``q1`` / ``p0`` 任一为 ``None``）→ ``BLOCKED``，
    **不降级为 0 或其它默认值**。``q0 <= 0`` 同样 BLOCKED（应在数据层按
    MISSING_POLICY 先行处理，此处拒绝带病计算）。
    """
    missing = [n for n, v in (("Q0", q0), ("Q1", q1), ("P0", p0)) if v is None]
    if missing:
        return P1Resolution(
            status=STATUS_BLOCKED,
            blocked_reason=f"未定态：{'、'.join(missing)} 缺失，P1 不可计算",
        )
    if q0 <= 0:
        return P1Resolution(
            status=STATUS_BLOCKED,
            blocked_reason="Q0 <= 0：阈值 r=Q1/Q0 无意义，须在数据层按 MISSING_POLICY 处理",
        )

    params = resolve_parameters(card, override)
    r = q1 / q0                                    # type: ignore[operator]
    branch = classify_branch(r, params)
    basis = [
        f"rule_set={card['rule_set_id']}",
        f"branch={branch}（r={r:.6f}，阈值 "
        f"[{params.decrease_threshold}, {params.increase_threshold}]）",
        f"scope={params.adjustment_scope}",
    ]

    if branch == BRANCH_DECREASE:
        p1 = p0 * (1.0 + params.rho_minus)         # type: ignore[operator]
        settlement = q1 * p1                       # type: ignore[operator]
        basis.append(
            "减量侧：『减少后剩余部分』本就是全部 Q1 → FULL 与 SEGMENT 等价，不区分作用域"
        )
    elif branch == BRANCH_INCREASE:
        p1 = p0 * (1.0 - params.rho_plus)          # type: ignore[operator]
        if params.adjustment_scope == "FULL":
            settlement = q1 * p1                   # type: ignore[operator]
            basis.append("增量侧 FULL：全部工程量按调整后单价")
        else:
            contract_part = params.increase_threshold * q0 * p0    # type: ignore[operator]
            excess_part = (q1 - params.increase_threshold * q0) * p1  # type: ignore[operator]
            settlement = contract_part + excess_part
            basis.append(
                f"增量侧 SEGMENT：{params.increase_threshold}·Q0 内保原单价，"
                "仅超出部分按 P1"
            )
    else:
        p1 = p0
        settlement = q1 * p0                       # type: ignore[operator]
        basis.append("区间内：不调整，按 P0 结算")

    basis.append(
        f"ρ±=({params.rho_plus}, {params.rho_minus})，来源={params.sources['rho_plus']}"
        "——规范只写『合理』无量化系数，默认 0 为机制层默认而非数据缺省"
    )

    return P1Resolution(
        status=STATUS_PASS, branch=branch, r=r, p0=p0, p1=p1,
        settlement=settlement, parameters=params.to_dict(), basis=basis,
    )


# ---------------------------------------------------------------------------
# T04-00 所需两个派生量的**唯一实现**
# ---------------------------------------------------------------------------
# 求解层（``bidpricing.solver``）必须复用本处实现，不得自行推导 R_i 或 r_eff：
# 一旦 solver 里出现第二份公式，「同一规则两处说法」就会以「解析解与 LP 解对不上」
# 的形式在 Phase 1/Phase 2 对拍时才暴露，排查成本远高于在此处集中一次。
#
# 注意 SEGMENT 分支的**区间内**口径：r_eff ≡ r（不带 (1+alpha)）——因为
# SEGMENT 下未越界部分按原单价结算，协商调整率 alpha 只作用于 FULL 分支。
# 这与 model_v0.3_R2.md §5.3.1 的两组公式逐字对应，改动须同步 §5.3.1。


def compute_r_eff(
    r: float,
    params: ResolvedParameters,
    alpha: float = 0.0,
) -> float:
    """有效效率比 ``r_eff := (dR_i/dp_i) / q0_i``——**排序键**。

    ``r`` 是结算量比 ``q1/q0``；``alpha`` 是未越界时的协商调整率（8.9.1 情形 1 取 0）。

    ``r_eff`` 与 ``r`` 的分工是 T04-00 的核心：排序必须按 ``r_eff``，
    按 ``r`` 排序会给出**满足全部约束但次优**的解（见 CE-02）——这类错误
    不会触发任何可行性检查。
    """
    if r > params.increase_threshold:
        if params.adjustment_scope == "FULL":
            return (1.0 - params.rho_plus) * r
        # SEGMENT：阈值内保原单价，仅超出部分按 P1。
        # 注意 ``params.increase_threshold`` **本身已是 (1 + theta_dev)**——
        # 写成 ``1.0 + params.increase_threshold`` 会得到 2.15 而不是 1.15，
        # 使 r_eff 在越界段被系统性高估（tests/test_phase1_exactness.py
        # 的例 2R 用例抓到过这个错误）。
        return params.increase_threshold + (1.0 - params.rho_plus) * (
            r - params.increase_threshold
        )
    if r < params.decrease_threshold:
        return (1.0 + params.rho_minus) * r
    if params.adjustment_scope == "FULL":
        return (1.0 + alpha) * r
    return r


def settlement_revenue(
    q0: float,
    q1: float,
    p: float,
    params: ResolvedParameters,
    alpha: float = 0.0,
) -> float:
    """``R_i(p)``——投标单价 ``p`` 对应的结算收入（含调整作用域）。

    与 ``compute_p1`` 的关系：``compute_p1`` 是「给定 P0 求 P1」的**业务接口**
    （带状态机与依据链）；本函数是同一公式的**纯函数形态**，供求解层与
    反例复算器调用。``alpha = 0`` 时两者必须逐值一致，
    由 ``tests/test_pricing_card.py`` 交叉锁定。
    """
    r = q1 / q0
    branch = classify_branch(r, params)
    if branch == BRANCH_DECREASE:
        # 减量侧：「减少后剩余部分」本就是全部 Q1 → FULL 与 SEGMENT 等价
        return q1 * p * (1.0 + params.rho_minus)
    if branch == BRANCH_INCREASE:
        p1 = p * (1.0 - params.rho_plus)
        if params.adjustment_scope == "FULL":
            return q1 * p1
        in_range = params.increase_threshold * q0 * p
        excess = (q1 - params.increase_threshold * q0) * p1
        return in_range + excess
    # 区间内：协商调整率 alpha **只作用于 FULL 分支**（§5.3.1）——SEGMENT 下
    # 未越界部分按原单价结算，alpha 不生效。此处必须与 ``compute_r_eff`` 的
    # 区间内分支逐分支对齐：否则 ``settlement_revenue`` 与 ``q0·r_eff`` 会在
    # 「SEGMENT + 区间内 + alpha≠0」这一格上分歧（实测差 (1+alpha) 倍），
    # 表现形态是「解析解与 LP 解对不上」——由 tests/test_lp_formulation.py 的
    # 数值差分判据逐分支锁定。
    if params.adjustment_scope == "FULL":
        return q1 * p * (1.0 + alpha)
    return q1 * p
