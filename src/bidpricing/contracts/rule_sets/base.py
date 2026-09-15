"""RuleSet 抽象接口。

对应《实施路线 v3.2.1》T00-07 的硬性要求：

    各版 RuleSet **独立实现、仅共享接口、禁止共享核心调价公式**。

因此本模块**只**提供：
  * 元信息契约（``rule_set_id`` / ``standard_code`` / ``effective_date`` / ``legal_basis``）；
  * 分档边界的判定规则（阈值 15% 为两版共有条款，且路线 §5.2 J2 对边界归属有统一要求，
    故在接口层统一实现，避免两版各自漂移）；
  * 两个抽象方法签名。

**核心调价公式一律不在此处实现**，分别落在 ``gb50500_2013.py`` 与 ``gbt50500_2024.py``。

符号约定
--------
``r``              = ``q1 / q0``，工程量比值
``rho_plus``       = 路线中的 ρ⁺，**增量 > 15% 时对单价的调整幅度（调低）**，默认 0
``rho_minus``      = 路线中的 ρ⁻，**减量 > 15% 时对单价的调整幅度（调高）**，默认 0
``scope``          = ``adjustment_scope ∈ {FULL, SEGMENT}``（仅 2024 版有歧义）
``r_eff``          = 有效收入倍数 = ``SettlementAmount(q1) / (q0 · p0)``
                     以**投标基准量价** ``q0·p0`` 归一，使 15% 阈值处的
                     连续性/不连续性可直接观测（T00-08 机械判据即基于此定义）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

#: 两版标准共有的调价触发阈值（低于/高于 15% 才触发）
DECREASE_THRESHOLD = 0.85
INCREASE_THRESHOLD = 1.15

#: 分档标签
BRANCH_DECREASE = "DECREASE"
BRANCH_IN_RANGE = "IN_RANGE"
BRANCH_INCREASE = "INCREASE"


class RuleSet(ABC):
    """规则集接口。子类必须独立实现全部调价公式。"""

    rule_set_id: str = ""
    standard_code: str = ""
    effective_date: str = ""
    legal_basis: str = ""
    #: 该规则集的 ``adjustment_scope`` 是否在规范层面存在歧义
    scope_ambiguous: bool = False

    # ------------------------------------------------------------------ 分档

    @staticmethod
    def classify_branch(r: float) -> str:
        """工程量比值分档。

        边界归属遵循路线 §5.2 **J2**：
        ``Q1 = 0.85·Q0`` 判为「不触发减量调价」、``Q1 = 1.15·Q0`` 判为「不触发增量调价」，
        即触发条件为**严格不等式**。
        """
        if r < DECREASE_THRESHOLD:
            return BRANCH_DECREASE
        if r > INCREASE_THRESHOLD:
            return BRANCH_INCREASE
        return BRANCH_IN_RANGE

    # -------------------------------------------------------------- 调价公式

    @abstractmethod
    def settlement_amount(
        self,
        q0: float,
        q1: float,
        p0: float,
        rho_plus: float = 0.0,
        rho_minus: float = 0.0,
        scope: str | None = None,
    ) -> float:
        """某清单项的结算金额（未含税）。"""

    @abstractmethod
    def effective_revenue_multiple(
        self,
        q0: float,
        q1: float,
        p0: float,
        rho_plus: float = 0.0,
        rho_minus: float = 0.0,
        scope: str | None = None,
    ) -> float:
        """``r_eff`` —— 以 ``q0·p0`` 归一的结算收入倍数。"""

    # -------------------------------------------------------------- 自检指纹

    def fingerprint(self, rho_probe: float = 0.01, delta: float = 1e-9) -> float:
        """T00-08 机械判据：``r_eff`` 在 ``r = 1.15 ± δ`` 处的跳变量。

        取 ``delta → 0`` 的两侧值之差。路线给出的期望量级：

        * GB 50500-2013 —— ``≈ 0``（分段累加，收益结构连续）
        * GB/T 50500-2024 —— ``≈ -1.15·ρ⁺``（调整单价本身，跳降）

        该指纹用于识别「两套 RuleSet 是否只是改了条文号、公式其实相同」。
        """
        lo = self.effective_revenue_multiple(
            1.0, INCREASE_THRESHOLD - delta, 1.0,
            rho_plus=rho_probe, rho_minus=rho_probe,
        )
        hi = self.effective_revenue_multiple(
            1.0, INCREASE_THRESHOLD + delta, 1.0,
            rho_plus=rho_probe, rho_minus=rho_probe,
        )
        return hi - lo
