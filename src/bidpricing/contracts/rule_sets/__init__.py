"""RuleSet 实现集合。

**独立性约束（T00-07）**：各版本仅共享 ``base.RuleSet`` 接口，
禁止共享核心调价公式。修改任一版本的公式不得影响另一版本。
"""

from .base import (
    BRANCH_DECREASE,
    BRANCH_IN_RANGE,
    BRANCH_INCREASE,
    DECREASE_THRESHOLD,
    INCREASE_THRESHOLD,
    RuleSet,
)
from .gb50500_2013 import GB50500_2013_RuleSet
from .gbt50500_2024 import GBT50500_2024_RuleSet, AdjustmentScopeNotFrozen, VALID_SCOPES

__all__ = [
    "BRANCH_DECREASE",
    "BRANCH_IN_RANGE",
    "BRANCH_INCREASE",
    "DECREASE_THRESHOLD",
    "INCREASE_THRESHOLD",
    "RuleSet",
    "GB50500_2013_RuleSet",
    "GBT50500_2024_RuleSet",
    "AdjustmentScopeNotFrozen",
    "VALID_SCOPES",
]
