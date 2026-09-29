"""命令行入口。

用法（在仓库根目录下）::

    PYTHONPATH=src python -m bidpricing.cli gate-check
    PYTHONPATH=src python -m bidpricing.cli ruleset-select --contract-date 2026-03-01
    PYTHONPATH=src python -m bidpricing.cli ruleset-selftest
    PYTHONPATH=src python -m bidpricing.cli freeze --all
    PYTHONPATH=src python -m bidpricing.cli freeze --gate gate_0a --key field_schema_version

    # 选择项（adjustment_scope 等）
    PYTHONPATH=src python -m bidpricing.cli options list
    PYTHONPATH=src python -m bidpricing.cli options set \\
        --key adjustment_scope --value FULL --rule-set GB/T50500-2024 \\
        --rationale "招标文件 §12.3 未约定分段，按 2024 字面口径"
    PYTHONPATH=src python -m bidpricing.cli options clear --key adjustment_scope
    PYTHONPATH=src python -m bidpricing.cli scope-impact --q0 100 --q1 130 --p0 10
    PYTHONPATH=src python -m bidpricing.cli contract-check

    # Q0→Q1 闭环（T07-02/03/04；输入束结构见 config/closed_loop_spec.json）
    PYTHONPATH=src python -m bidpricing.cli precision-monitor --records <闭环输入束.json>
    PYTHONPATH=src python -m bidpricing.cli calibrate --records <闭环输入束.json>
    PYTHONPATH=src python -m bidpricing.cli closed-loop --records <闭环输入束.json>
    PYTHONPATH=src python -m bidpricing.cli predict-register --input <取值.json> \
        --source manual --actor user --rationale "逐项独立算量，图纸版本 V2"


命令实现按域拆分（governance/profit/solver_checks/boq/quote/parity/
closedloop），共享助手见 common，参数组装见 parser。对外 API 不变：
``build_parser`` / ``main`` / ``config_dir`` / ``PREDICTED_Q1_SOURCE_CHOICES``。
"""
from __future__ import annotations

from .common import PREDICTED_Q1_SOURCE_CHOICES
from ..paths import config_dir  # 兼容旧入口：from bidpricing.cli import config_dir
from .parser import build_parser
from .main import main

__all__ = ["build_parser", "main", "config_dir",
           "PREDICTED_Q1_SOURCE_CHOICES"]
