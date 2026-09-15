"""选择项影响度量 —— 在**规则层**量化 FULL / SEGMENT 的分叉。

为什么需要
----------
``adjustment_scope`` 已被做成项目级选择项（见 :mod:`bidpricing.selection_options`），
但"可选"不等于"可以随便选"：两个取值导致的结算曲线不同，进而改变求解器看到的目标
函数形状。因此在落值之前，必须先能看到**这一具体项目上**两者差多少。

本模块给出**单清单项**层面的分叉度量：
给定 ``q0 / q1 / p0 / ρ⁺ / ρ⁻``，直接算出两个作用域下的结算金额及其差异。

边界说明（必须与结论一同阅读）
----------------------------
* 本模块度量的是**规则层分叉**，即"同一个报价（p 相同）在两种口径下结算多少"。
* 规格书附录 B 例 2R 中出现的**约 4.5 倍最优利润差**发生在**报价决策层**：
  两种口径下最优的单价结构相反（一处靠"薄利放量"、一处靠"保价控量"），
  需由 WP4 求解器在两条口径下分别求最优后比较。
* 因此本模块的输出是**选择项的合理性依据**，不是利润差的替代品。
  ``rules_to_optimizer_gap`` 字段显式保留这一区别。

``ρ⁺ / ρ⁻`` 默认取 0：规范未给量化依据，非零取值属待证假设（T00-11 管辖）。
"""

from __future__ import annotations

from .rule_sets.base import INCREASE_THRESHOLD
from .rule_sets.gb50500_2013 import GB50500_2013_RuleSet
from .rule_sets.gbt50500_2024 import GBT50500_2024_RuleSet

_RS_2013 = GB50500_2013_RuleSet()
_RS_2024 = GBT50500_2024_RuleSet()

RULES_TO_OPTIMIZER_GAP = (
    "本结果为「同一报价在两种口径下的结算差」，属规则层度量；"
    "规格书附录 B 例 2R 的约 4.5 倍最优利润差属报价决策层结果，"
    "须由 WP4 在两条口径下分别求解后比较，二者不可互相替代。"
)


def compare_scopes(
    q0: float,
    q1: float,
    p0: float,
    *,
    rho_plus: float = 0.0,
    rho_minus: float = 0.0,
) -> dict:
    """对比 GB/T 50500-2024 在 ``FULL`` / ``SEGMENT`` 下的单项结算金额。"""
    if q0 <= 0:
        raise ValueError("q0 必须大于 0（0 工程量项应在数据层按 MISSING_POLICY 处理）")

    ratio = q1 / q0
    branch = _RS_2024.classify_branch(ratio)

    full = _RS_2024.settlement_amount(
        q0, q1, p0, rho_plus=rho_plus, rho_minus=rho_minus, scope="FULL"
    )
    segment = _RS_2024.settlement_amount(
        q0, q1, p0, rho_plus=rho_plus, rho_minus=rho_minus, scope="SEGMENT"
    )
    reference_2013 = _RS_2013.settlement_amount(
        q0, q1, p0, rho_plus=rho_plus, rho_minus=rho_minus
    )

    difference = segment - full
    divergence = (difference / full * 100.0) if full else None

    notes: list[str] = []
    if branch == "IN_RANGE":
        notes.append(
            f"r = {ratio:.6g} 落在 [{0.85}, {INCREASE_THRESHOLD}] 区间内，"
            "两版均不触发调价：作用域在本项上不产生任何差异"
        )
    elif branch == "DECREASE":
        notes.append(
            f"r = {ratio:.6g} < 0.85（减量侧）：2024 减量侧 FULL 与 SEGMENT 等价——"
            "「减少后剩余部分」本就是全部 q1，故作用域分叉只出现在增量侧"
        )
    else:
        if abs(difference) < 1e-9:
            notes.append(
                f"r = {ratio:.6g} > {INCREASE_THRESHOLD}（增量侧），但两作用域数值相同——"
                "调整后单价与合同单价一致，见下方 ρ 说明"
            )
        else:
            notes.append(
                f"r = {ratio:.6g} > {INCREASE_THRESHOLD}（增量侧）：作用域分叉在此显形，"
                f"SEGMENT 比 FULL 多结算 {difference:.6f}（{divergence:.4f}%）"
            )
    if abs(segment - reference_2013) < 1e-9:
        notes.append(
            "SEGMENT 口径下 2024 的结算金额与 2013 完全相同——"
            "这也是项目选择 SEGMENT 后机械指纹退化的原因"
        )
    if rho_plus == 0.0 and rho_minus == 0.0:
        notes.append(
            "ρ⁺ = ρ⁻ = 0（规范默认、无量化依据）：此时即使进入增量侧，"
            "调整后单价与合同单价相同，两作用域数值也相等。"
            "要观测分叉必须给定非零 ρ（属待证假设，由 T00-11 管辖）"
        )

    return {
        "inputs": {
            "q0": q0, "q1": q1, "p0": p0,
            "rho_plus": rho_plus, "rho_minus": rho_minus,
        },
        "quantity_ratio": ratio,
        "branch": branch,
        "gb_t_50500_2024": {
            "FULL": full,
            "SEGMENT": segment,
            "difference_segment_minus_full": difference,
            "divergence_pct": divergence,
        },
        "gb_50500_2013_reference": reference_2013,
        "segment_equals_2013": abs(segment - reference_2013) < 1e-9,
        "scope_equivalent_here": abs(difference) < 1e-9,
        "notes": notes,
        "rules_to_optimizer_gap": RULES_TO_OPTIMIZER_GAP,
    }
