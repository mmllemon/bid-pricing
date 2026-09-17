"""求解层（WP4）——把口径编译为约束、求解、并**独立复核**。

本包的存在前提是 Gate 0b 已通过（``WP4 求解层构建 = ALLOWED``）。
包内模块的分工：

* ``instance`` —— Phase 1 论域的数据结构（可自由优化项 + 总价锁定 + 规则集参数）；
* ``exactness`` —— T04-00《Phase 1 精确性条件》的机械判定器。

两条纪律（与仓内其余模块同源）：

1. **不得重实现既有口径**。``R_i`` 与 ``r_eff`` 的唯一实现在
   ``bidpricing.contracts.pricing_card``；本包只调用。
2. **判据必须能被错误的值否定**。``exactness`` 的每条判据都要给出
   「什么值会让它判 FAIL」；同源相减、自比较一类的恒真式一律不作判据
   （见 ADR 与 config/phase1_exactness_spec.json 的 check 字段）。
"""

from .exactness import (
    CONDITION_IDS,
    ExactnessVerdict,
    check_exactness,
    iter_conditions,
)
from .instance import (
    Phase1Instance,
    Phase1Item,
    Phase1Params,
    SolutionCheck,
    check_solution,
)

__all__ = [
    "CONDITION_IDS",
    "ExactnessVerdict",
    "Phase1Instance",
    "Phase1Item",
    "Phase1Params",
    "SolutionCheck",
    "check_exactness",
    "check_solution",
    "iter_conditions",
]
