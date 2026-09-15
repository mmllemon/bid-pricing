"""GB 50500-2013 规则集 —— 独立实现。

规范依据：**《建设工程工程量清单计价规范》GB 50500-2013**，第 9.6.2 条「工程量偏差」。
该规范自 **2025-09-01 起废止**（住建部公告 2024 年第 212 号），仅适用于过渡项目。

机制特征（路线 §8.3 校正一）
---------------------------
1. §9.6.2 是**独立条款**，同时覆盖「数量偏差」，2024 版已将其拆为
   §8.2（清单缺陷）与 §8.9（工程变更）两条路径。
2. 工程量增加 > 15% 时采用**分段累加**：超出 1.15·Q0 的部分在调整后单价下结算，
   其余部分仍按合同单价 —— 因此 ``r_eff`` 在阈值处**连续**。
3. 工程量减少 > 15% 时，「减少后剩余部分」的单价调高。

本地实现**不共享** 2024 版的任何调价公式。
"""

from __future__ import annotations

from .base import (
    BRANCH_DECREASE,
    BRANCH_INCREASE,
    INCREASE_THRESHOLD,
    RuleSet,
)


class GB50500_2013_RuleSet(RuleSet):
    rule_set_id = "GB50500-2013"
    standard_code = "GB 50500-2013"
    effective_date = "2013-07-01"
    legal_basis = (
        "《建设工程工程量清单计价规范》GB 50500-2013 §9.6.2"
        "（住建部公告第 1567 号）。**自 2025-09-01 起废止**"
        "（住建部公告 2024 年第 212 号），仅适用于过渡项目或合同另有约定者"
    )
    #: 2013 版 §9.6.2 已明确规定分段累加，不存在作用域歧义
    scope_ambiguous = False
    #: 该规则集下 adjustment_scope **只有一种合法取值** → 非选择项（规范明文确定）
    supported_scopes = ("SEGMENT",)

    def settlement_amount(
        self,
        q0: float,
        q1: float,
        p0: float,
        rho_plus: float = 0.0,
        rho_minus: float = 0.0,
        scope: str | None = None,
    ) -> float:
        if q0 <= 0:
            raise ValueError("q0 必须大于 0（0 工程量项应在数据层按 MISSING_POLICY 处理）")
        branch = self.classify_branch(q1 / q0)

        if branch == BRANCH_DECREASE:
            # §9.6.2 后半句：工程量减少 15% 以上，减少后剩余部分单价调高
            return q1 * p0 * (1.0 + rho_minus)

        if branch == BRANCH_INCREASE:
            # §9.6.2 前半句：工程量增加 15% 以上，"其增加部分"单价调低 —— 分段累加
            contract_part = INCREASE_THRESHOLD * q0 * p0
            excess_part = (q1 - INCREASE_THRESHOLD * q0) * p0 * (1.0 - rho_plus)
            return contract_part + excess_part

        return q1 * p0

    def effective_revenue_multiple(
        self,
        q0: float,
        q1: float,
        p0: float,
        rho_plus: float = 0.0,
        rho_minus: float = 0.0,
        scope: str | None = None,
    ) -> float:
        return self.settlement_amount(
            q0, q1, p0, rho_plus=rho_plus, rho_minus=rho_minus, scope=scope
        ) / (q0 * p0)
