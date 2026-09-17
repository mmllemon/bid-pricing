"""求解层（WP4）——把口径编译为约束、求解、并**独立复核**。

本包的存在前提是 Gate 0b 已通过（``WP4 求解层构建 = ALLOWED``）。
包内模块的分工：

* ``instance`` —— Phase 1 论域的数据结构（可自由优化项 + 总价锁定 + 规则集参数）；
* ``exactness`` —— T04-00《Phase 1 精确性条件》的机械判定器；
* ``formulation`` —— T04-02A 的模型形式化（只形式化，不建模）；
* ``compiler`` —— T04-02B 的约束编译器（Formulation → 求解器无关的 CompiledModel）；
* ``backend`` —— T04-02C 的后端适配层（**唯一**允许接触求解器包的模块）。

三条纪律（与仓内其余模块同源）：

1. **不得重实现既有口径**。``R_i`` 与 ``r_eff`` 的唯一实现在
   ``bidpricing.contracts.pricing_card``；本包只调用。
2. **判据必须能被错误的值否定**。``exactness`` 的每条判据都要给出
   「什么值会让它判 FAIL」；同源相减、自比较一类的恒真式一律不作判据
   （见 ADR 与 config/phase1_exactness_spec.json 的 check 字段）。
3. **业务层不得认识求解器**。``formulation`` / ``compiler`` 都不得调用
   ``solve()``；换后端只改 ``config/solver_backend_spec.json``。
"""

from .backend import (
    Availability,
    BackendCheck,
    BackendError,
    NormalizedStatus,
    Selection,
    SolveResult,
    StatusDomain,
    check_backend,
    load_backend_spec,
    normalize_status,
    required_capability,
    select_backend,
    solve_compiled,
)
from .compiler import (
    CompiledModel,
    CompiledRow,
    CompiledVar,
    CompilerCheck,
    Evaluation,
    Simplification,
    check_compiled,
    compile_model,
    evaluate,
    load_compiler_spec,
    pulp_available,
)
from .exactness import (
    CONDITION_IDS,
    ExactnessVerdict,
    check_exactness,
    iter_conditions,
)
from .formulation import (
    Formulation,
    FormulationCheck,
    build_formulation,
    check_formulation,
    load_formulation_spec,
    probe_instance,
)
from .instance import (
    Phase1Instance,
    Phase1Item,
    Phase1Params,
    SolutionCheck,
    check_solution,
)

__all__ = [
    "Availability",
    "BackendCheck",
    "BackendError",
    "CONDITION_IDS",
    "CompiledModel",
    "CompiledRow",
    "CompiledVar",
    "CompilerCheck",
    "Evaluation",
    "ExactnessVerdict",
    "Formulation",
    "FormulationCheck",
    "NormalizedStatus",
    "Phase1Instance",
    "Phase1Item",
    "Phase1Params",
    "Selection",
    "Simplification",
    "SolutionCheck",
    "SolveResult",
    "StatusDomain",
    "build_formulation",
    "check_backend",
    "check_compiled",
    "check_exactness",
    "check_formulation",
    "check_solution",
    "compile_model",
    "evaluate",
    "iter_conditions",
    "load_backend_spec",
    "load_compiler_spec",
    "load_formulation_spec",
    "normalize_status",
    "probe_instance",
    "required_capability",
    "select_backend",
    "solve_compiled",
]
