"""不平衡报价条款的业务入口校验与投标期边界处理。

底层配置已经定义 C13，但主报价流程必须显式接入本模块，避免在存在不平衡
报价条款时仍把单价压到 0.01 元。当前只把 ``VALIDITY + CAP`` 机械落成单项
下界；结算调整机制需要改变结算收入函数，尚未接入前必须阻断，而不是假装
投标期报价已经等价。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


VALIDITY = "BID_VALIDITY"
SETTLEMENT_ADJUSTMENT = "SETTLEMENT_ADJUSTMENT"
SCORING = "SCORING"
NONE = "NONE"
SUPPORTED_MECHANISMS = {VALIDITY, SETTLEMENT_ADJUSTMENT, SCORING, NONE}
SUPPORTED_REFERENCES = {"CAP", "CONTROL_PRICE", "EVAL_BASE", "COST_SHARE"}


@dataclass(frozen=True)
class UnbalancedPolicy:
    enabled: bool
    reference: str | None = None
    tol_lo: float | None = None
    tol_hi: float | None = None
    mechanism: str = NONE


class UnbalancedPolicyError(ValueError):
    """条款声明缺失或不足以支持当前报价计算。"""


def settlement_revenue_adjusted(
    q0: float,
    q1: float,
    bid_price: float,
    cap_price: float,
    *,
    low_ratio: float = 0.5,
    quantity_tolerance: float = 0.15,
) -> float:
    """按已确认的“±50% + ±15%”条款计算结算收入。

    该函数只负责结算期收入，不负责求解。严重低价条件是严格 ``bid < 50%·cap``；
    工程量在 ±15% 内按投标价，增量超出部分按较低单价，减量超出部分按
    ``cap_price - bid_price`` 的差额对剩余投标价收入做修正。

    由于价格是否低于 50% 会改变斜率，接入报价优化时必须使用分段 LP/MILP，
    不能把本函数简单塞进当前 Phase 1 解析解。
    """
    q0, q1 = float(q0), float(q1)
    bid_price, cap_price = float(bid_price), float(cap_price)
    if q0 <= 0 or q1 < 0 or bid_price < 0 or cap_price <= 0:
        raise UnbalancedPolicyError("结算调整输入必须满足 q0>0、q1>=0、报价>=0、最高限价>0")
    # 求解器返回值可能在边界外侧留下 1e-12 级数值噪声；边界等于 50%
    # 时必须按“非严重低价”处理，不能因浮点误差误触发结算修正。
    if bid_price >= low_ratio * cap_price - 1e-8:
        return q1 * bid_price

    lower_q = (1.0 - quantity_tolerance) * q0
    upper_q = (1.0 + quantity_tolerance) * q0
    if q1 > upper_q:
        excess = q1 - upper_q
        return upper_q * bid_price + excess * min(bid_price, cap_price)
    if q1 < lower_q:
        excess_reduction = lower_q - q1
        return q1 * bid_price - excess_reduction * (cap_price - bid_price)
    return q1 * bid_price


def parse_unbalanced_policy(raw: Mapping[str, Any] | None) -> UnbalancedPolicy | None:
    """解析 C13 声明。

    ``None`` 表示项目尚未声明，不把它静默当成 ``enabled=false``；调用方可以
    将其作为 WARN（兼容旧接口）或 BLOCKED（正式产品入口）处理。
    """
    if raw is None:
        return None
    if "enabled" not in raw or not isinstance(raw["enabled"], bool):
        raise UnbalancedPolicyError("不平衡报价条款必须明确填写 enabled=true/false")
    if not raw["enabled"]:
        return UnbalancedPolicy(enabled=False)

    reference = str(raw.get("reference") or "").upper()
    mechanism = str(raw.get("mechanism") or "").upper()
    if reference not in SUPPORTED_REFERENCES:
        raise UnbalancedPolicyError(
            "不平衡报价条款已启用，但 reference 缺失或不受支持："
            "CAP/CONTROL_PRICE/EVAL_BASE/COST_SHARE"
        )
    if mechanism not in SUPPORTED_MECHANISMS:
        raise UnbalancedPolicyError(
            "不平衡报价条款已启用，但 mechanism 缺失或不受支持："
            "BID_VALIDITY/SETTLEMENT_ADJUSTMENT/SCORING/NONE"
        )

    def _tol(name: str) -> float:
        value = raw.get(name)
        if value is None:
            raise UnbalancedPolicyError(f"不平衡报价条款缺少 {name}")
        value = float(value)
        if not 0 <= value < 1:
            raise UnbalancedPolicyError(f"{name} 必须在 [0, 1) 范围内")
        return value

    return UnbalancedPolicy(
        enabled=True,
        reference=reference,
        tol_lo=_tol("tol_lo"),
        tol_hi=_tol("tol_hi"),
        mechanism=mechanism,
    )


def apply_validity_lower_bounds(
    items: Sequence[Mapping[str, Any]],
    policy: UnbalancedPolicy | None,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """把可机械执行的投标有效性条款写入逐项 L，并返回提示。

    当前仅支持 ``reference=CAP``，因为只有这一基准在现有输入中有明确逐项
    数值。无最高限价项没有 cap 基准，不能臆造下界，返回提示供用户确认。
    """
    rows = [dict(row) for row in items]
    if policy is None:
        return rows, ("不平衡报价条款未声明；本结果不应视为已完成 C13 合规复核",)
    if not policy.enabled:
        return rows, ()
    if policy.mechanism == SETTLEMENT_ADJUSTMENT:
        raise UnbalancedPolicyError(
            "当前系统尚未把结算调整机制接入 R_i(p_i)；禁止用投标期最优报价冒充结算后结果"
        )
    if policy.mechanism in {SCORING, NONE}:
        return rows, (f"C13 mechanism={policy.mechanism} 不改变当前投标单价可行域，需按招标评分/条款另行复核",)
    if policy.reference != "CAP":
        raise UnbalancedPolicyError(
            f"当前求解器尚未接入 reference={policy.reference} 的逐项基准，暂不能安全求解"
        )

    notes: list[str] = []
    for row in rows:
        cap = row.get("cap")
        if cap is None:
            notes.append(f"{row.get('item_id', '')}:无最高限价，C13=CAP 无法计算条款下界")
            continue
        clause_l = float(cap) * (1.0 - float(policy.tol_lo))
        old_l = row.get("L")
        row["L"] = max(float(old_l) if old_l is not None else 0.0, clause_l)
        row["unbalanced_lower_bound"] = clause_l
    return rows, tuple(notes)
