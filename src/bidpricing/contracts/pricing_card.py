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
