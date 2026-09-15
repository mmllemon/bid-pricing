"""GB/T 50500-2024 规则集 —— 独立实现。

规范依据：**《建设工程工程量清单计价标准》GB/T 50500-2024**
（住建部公告 2024 年第 212 号，2024-11-26），**自 2025-09-01 起实施**。
相关条文：§8.2.1（清单缺陷）、§8.9.1~8.9.3（工程变更）、§10.2（施工过程结算）。

机制特征（路线 §8.3 校正一）
---------------------------
1. §9.6.2「工程量偏差」独立条款**已不存在**，同一实质问题被拆为两条路径。
2. 工程量增加 > 15% 时，字面口径是**「合理下调其合同单价」**——
   **调整的是单价本身**，而非仅对增量部分打折。后果：``r_eff`` 在阈值处
   **由连续变为不连续**，跳变量 ≈ ``-1.15·ρ⁺``。
3. 规范**未明说是否分段**，因此必须冻结
   ``adjustment_scope ∈ {FULL, SEGMENT}``：两种解读下最优报价结构相反
   （规格书附录 B 例 2R：``Z`` 相差约 4.5 倍）。

作用域语义（本实现的核心分叉）
-----------------------------
* ``FULL``    —— 字面口径：该清单项目**全部工程量**按调整后单价结算。
* ``SEGMENT`` —— 分段口径：仅超出 1.15·Q0 的部分按调整后单价结算（与 2013 同形）。

**未冻结（``scope`` 非枚举值）时一律抛异常**，不得自行取任一侧——
这是路线 §7.1.1 断言 2「未定态熔断」在求解层面的落地。

注意：本版的作用域是**项目级选择项**而非一次性裁决常量，取值由
:mod:`bidpricing.selection_options` 统一登记与落值（``config/project_selection.json``），
本模块只负责"取到非法/缺失值时拒绝计算"。

本地实现**不共享** 2013 版的任何调价公式。
"""

from __future__ import annotations

from .base import (
    BRANCH_DECREASE,
    BRANCH_INCREASE,
    INCREASE_THRESHOLD,
    RuleSet,
)

VALID_SCOPES = ("FULL", "SEGMENT")


class AdjustmentScopeNotFrozen(RuntimeError):
    """``adjustment_scope`` 未冻结即尝试求解。"""


class GBT50500_2024_RuleSet(RuleSet):
    rule_set_id = "GB/T50500-2024"
    standard_code = "GB/T 50500-2024"
    effective_date = "2025-09-01"
    legal_basis = (
        "《建设工程工程量清单计价标准》GB/T 50500-2024 "
        "§8.2.1、§8.9.1~8.9.3、§10.2"
        "（住建部公告 2024 年第 212 号，2024-11-26，自 2025-09-01 施行）"
    )
    #: 规范未明说是否分段 —— 必须由 T00-01 冻结
    scope_ambiguous = True
    #: 该规则集下 adjustment_scope 属**项目级选择项**（两种解读均合法）
    supported_scopes = VALID_SCOPES

    @staticmethod
    def _require_scope(scope: str | None) -> str:
        if scope not in VALID_SCOPES:
            raise AdjustmentScopeNotFrozen(
                "adjustment_scope 未冻结（当前值："
                f"{scope!r}）。合法值仅 {VALID_SCOPES}；"
                "FULL 与 SEGMENT 两种解读下最优报价结构相反、利润差约 4.5 倍，"
                "默认取任一侧等价于在该误差区间内做优化（§7.1.1 断言 2）。"
            )
        return scope

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
        resolved = self._require_scope(scope)
        branch = self.classify_branch(q1 / q0)

        if branch == BRANCH_DECREASE:
            # §8.9：工程量减少后，剩余工程量单价调高。
            # 注意：减量侧 FULL 与 SEGMENT 等价——「减少后剩余部分」本就是全部 q1。
            return q1 * p0 * (1.0 + rho_minus)

        if branch == BRANCH_INCREASE:
            adjusted_unit_price = p0 * (1.0 - rho_plus)
            if resolved == "FULL":
                return q1 * adjusted_unit_price
            # SEGMENT：仅超出部分按调整后单价
            contract_part = INCREASE_THRESHOLD * q0 * p0
            excess_part = (q1 - INCREASE_THRESHOLD * q0) * adjusted_unit_price
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
        # 指纹自检使用 SEGMENT 之外的默认作用域会掩盖不连续性，
        # 故此处显式要求 scope；调用方（fingerprint）由子类覆写提供探针值。
        resolved = self._require_scope(scope)
        return self.settlement_amount(
            q0, q1, p0, rho_plus=rho_plus, rho_minus=rho_minus, scope=resolved
        ) / (q0 * p0)

    def fingerprint(
        self,
        rho_probe: float = 0.01,
        delta: float = 1e-9,
        scope: str = "FULL",
    ) -> float:
        """按指定作用域取 ``r_eff`` 在 ``r = 1.15 ± δ`` 处的跳变量。

        默认 ``FULL``——2024 版字面口径，也是**唯一产生跳降的分支**。
        ``scope="SEGMENT"`` 时跳变量回到 ``≈ 0``（与 2013 同形），
        这是已知的**指纹退化条件**：一旦项目选择 SEGMENT，
        数值指纹便无法再区分两套实现，区分依据退回条款覆盖（§8.2/§8.9 双路径）
        与两版代码路径的独立实现。自检必须同时输出两个作用域的结果。
        """
        lo = self.effective_revenue_multiple(
            1.0, INCREASE_THRESHOLD - delta, 1.0,
            rho_plus=rho_probe, rho_minus=rho_probe, scope=scope,
        )
        hi = self.effective_revenue_multiple(
            1.0, INCREASE_THRESHOLD + delta, 1.0,
            rho_plus=rho_probe, rho_minus=rho_probe, scope=scope,
        )
        return hi - lo
