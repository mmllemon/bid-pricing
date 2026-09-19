"""T06-05 Calculation Trace：Source 到 Report 的可校验全链追溯。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SPEC_FILENAME = "calculation_trace_spec.json"
STAGES = ("Source", "Normalized", "Derived", "Constraint", "Solver", "Postprocess", "Report")
NODE_FIELDS = ("node_id", "source_refs", "inputs", "outputs", "derivation", "upstream_ids")


class TraceError(ValueError):
    """追溯链不完整或违反阶段顺序。"""


def load_calculation_trace_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class TraceNode:
    stage: str
    node_id: str
    source_refs: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    derivation: str
    upstream_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "node_id": self.node_id,
            "source_refs": list(self.source_refs),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "derivation": self.derivation,
            "upstream_ids": list(self.upstream_ids),
        }


@dataclass(frozen=True)
class CalculationTrace:
    status: str
    stages: tuple[tuple[str, tuple[TraceNode, ...]], ...]
    errors: tuple[str, ...] = ()

    @property
    def nodes(self) -> tuple[TraceNode, ...]:
        return tuple(node for _, nodes in self.stages for node in nodes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stages": {stage: [node.to_dict() for node in nodes] for stage, nodes in self.stages},
            "errors": list(self.errors),
        }


def _as_texts(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value or any(not str(item).strip() for item in value):
        raise TraceError(f"{field} 必须是非空字符串列表")
    return tuple(str(item) for item in value)


def build_calculation_trace(stages: Mapping[str, Sequence[Mapping[str, Any]]]) -> CalculationTrace:
    """构建并校验七阶段追溯链；任何缺口都返回 BLOCKED 而非静默补全。"""
    errors: list[str] = []
    if set(stages) != set(STAGES):
        missing = [stage for stage in STAGES if stage not in stages]
        extra = [stage for stage in stages if stage not in STAGES]
        if missing:
            errors.append("缺少阶段: " + ", ".join(missing))
        if extra:
            errors.append("未知阶段: " + ", ".join(extra))
    built: dict[str, tuple[TraceNode, ...]] = {}
    seen: set[str] = set()
    for stage in STAGES:
        raw_nodes = stages.get(stage, ())
        if not raw_nodes:
            errors.append(f"阶段 {stage} 没有节点")
        nodes: list[TraceNode] = []
        for raw in raw_nodes:
            missing_fields = [field for field in NODE_FIELDS if field not in raw]
            if missing_fields:
                errors.append(f"{stage} 节点缺少字段: {', '.join(missing_fields)}")
                continue
            node_id = str(raw["node_id"])
            if not node_id or node_id in seen:
                errors.append(f"node_id 重复或为空: {node_id!r}")
                continue
            try:
                node = TraceNode(stage, node_id, _as_texts(raw["source_refs"], "source_refs"), _as_texts(raw["inputs"], "inputs"), _as_texts(raw["outputs"], "outputs"), str(raw["derivation"]).strip(), _as_texts(raw["upstream_ids"], "upstream_ids") if stage != "Source" else tuple(str(item) for item in raw["upstream_ids"]))
                if not node.derivation:
                    raise TraceError("derivation 不能为空")
            except (TraceError, TypeError) as exc:
                errors.append(f"{stage}/{node_id}: {exc}")
                continue
            seen.add(node_id)
            nodes.append(node)
        built[stage] = tuple(nodes)
    for index, stage in enumerate(STAGES[1:], start=1):
        previous_ids = {node.node_id for node in built.get(STAGES[index - 1], ())}
        for node in built.get(stage, ()):
            if not set(node.upstream_ids) & previous_ids:
                errors.append(f"{stage}/{node.node_id} 未连接到前一阶段 {STAGES[index - 1]}")
            unknown = set(node.upstream_ids) - seen
            if unknown:
                errors.append(f"{stage}/{node.node_id} 引用了未知 upstream_ids: {', '.join(sorted(unknown))}")
    status = "PASS" if not errors else "BLOCKED"
    return CalculationTrace(status, tuple((stage, built.get(stage, ())) for stage in STAGES), tuple(errors))
