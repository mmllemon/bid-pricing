"""T04-08 独立参考实现（第二条计算路径 + 三层隔离证明）。

* :mod:`.reference` —— 由制品推导的 ``R_i`` / 约束残差 / 目标函数重算；
* :mod:`.isolation` —— ISO-1/2/3 三层隔离证明。

★ 本包**不得 import 任何生产计算模块**（``bidpricing.solver.*`` /
``bidpricing.contracts.pricing_card``），否则「两条路径一致」失去信息量。
"""

from .isolation import (
    SIGNOFF_FILENAME,
    audit_reference_source,
    check_signoff,
    collect_isolation,
    immutability_probe,
)
from .reference import (
    BRANCHES,
    SCOPES,
    INPUT_NAMES,
    PARAM_NAMES,
    RefCheck,
    RefItem,
    RefLine,
    RefObjective,
    RefParams,
    RefReport,
    RefResidual,
    RefSnapshot,
    declared_input_names,
    judge_reference,
    load_reference_spec,
    ref_branch,
    ref_objective,
    ref_residuals,
    ref_revenue,
    reference_report,
    snapshot,
)

__all__ = [
    "BRANCHES",
    "INPUT_NAMES",
    "PARAM_NAMES",
    "RefCheck",
    "RefItem",
    "RefLine",
    "RefObjective",
    "RefParams",
    "RefReport",
    "RefResidual",
    "RefSnapshot",
    "SCOPES",
    "SIGNOFF_FILENAME",
    "audit_reference_source",
    "check_signoff",
    "collect_isolation",
    "declared_input_names",
    "immutability_probe",
    "judge_reference",
    "load_reference_spec",
    "ref_branch",
    "ref_objective",
    "ref_residuals",
    "ref_revenue",
    "reference_report",
    "snapshot",
]
