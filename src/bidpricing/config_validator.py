"""T02-03 运行时配置校验器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from .config_merge import _flatten
from .states import Status


@dataclass(frozen=True)
class ConfigIssue:
    kind: str
    path: str
    reason: str
    actual: Any = None
    expected: Any = None


@dataclass(frozen=True)
class ConfigValidationReport:
    issues: tuple[ConfigIssue, ...]

    @property
    def status(self) -> Status:
        return Status.PASS if not self.issues else Status.BLOCKED

    def by_kind(self, kind: str) -> list[ConfigIssue]:
        return [i for i in self.issues if i.kind == kind]

    def to_dict(self) -> dict:
        return {"status": self.status.value, "issues": [i.__dict__ for i in self.issues]}


def _definitions(schema: Mapping[str, Any]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sheet, spec in (schema.get("sheets") or {}).items():
        for path, definition in (spec.get("keys") or {}).items():
            out[f"{sheet}.{path}"] = definition
    return out


def _type_ok(value: Any, typ: str) -> bool:
    if typ == "string": return isinstance(value, str)
    if typ == "number": return isinstance(value, (int, float)) and not isinstance(value, bool)
    if typ == "integer": return isinstance(value, int) and not isinstance(value, bool)
    if typ == "boolean": return isinstance(value, bool)
    if typ == "enum": return isinstance(value, str)
    if typ == "array": return isinstance(value, list)
    if typ == "object": return isinstance(value, Mapping)
    if typ == "datetime":
        if not isinstance(value, str): return False
        try: datetime.fromisoformat(value.replace("Z", "+00:00")); return True
        except ValueError: return False
    return False


def validate_config(
    config: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    value_source: Mapping[str, str] | None = None,
    duplicate_paths: Sequence[str] = (),
) -> ConfigValidationReport:
    """检查缺失/空值/类型/范围/未知键/重复键/版本七类问题。"""
    issues: list[ConfigIssue] = []
    defs = _definitions(schema)
    flat = _flatten(config)
    reserved = {"schema_id", "schema_version"}
    for path in duplicate_paths:
        issues.append(ConfigIssue("duplicate", path, "配置键重复出现"))
    if config.get("schema_id") is not None and config.get("schema_id") != schema.get("schema_id"):
        issues.append(ConfigIssue("version", "schema_id", "配置 schema_id 不匹配", config.get("schema_id"), schema.get("schema_id")))
    if config.get("schema_version") is not None and config.get("schema_version") != schema.get("version"):
        issues.append(ConfigIssue("version", "schema_version", "配置 schema_version 不匹配", config.get("schema_version"), schema.get("version")))
    for path, value in flat.items():
        if path in reserved:
            continue
        definition = defs.get(path)
        if definition is None:
            issues.append(ConfigIssue("unknown", path, "未知配置键", value))
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            if definition.get("required"):
                issues.append(ConfigIssue("missing", path, "必填配置为空", value))
            continue
        typ = definition.get("type")
        if not _type_ok(value, typ):
            issues.append(ConfigIssue("type", path, "配置值类型错误", value, typ))
            continue
        enum = definition.get("enum")
        if enum is not None and value not in enum:
            issues.append(ConfigIssue("range", path, "配置值不在枚举域内", value, enum))
        lo, hi = definition.get("min"), definition.get("max")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if lo is not None and value < lo: issues.append(ConfigIssue("range", path, "配置值低于最小值", value, lo))
            if hi is not None and value > hi: issues.append(ConfigIssue("range", path, "配置值高于最大值", value, hi))
        if value_source is not None:
            source = value_source.get(path)
            if source not in {"explicit", "defaulted", "derived", "inferred"}:
                issues.append(ConfigIssue("source", path, "value_source 非法", source))
    for path, definition in defs.items():
        if definition.get("required") and path not in flat:
            issues.append(ConfigIssue("missing", path, "必填配置键缺失"))
    return ConfigValidationReport(tuple(issues))
