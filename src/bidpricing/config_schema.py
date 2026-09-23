"""T02-01 配置定义表的机械校验。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_DEFINITION_KEYS = {"type", "required", "default", "min", "max", "enum", "description"}


@dataclass(frozen=True)
class ConfigSchemaIssue:
    sheet: str
    key: str
    reason: str


def load_config_schema(config_dir: Path) -> dict[str, Any]:
    data = json.loads((config_dir / "config_schema.json").read_text(encoding="utf-8"))
    if data.get("schema_id") != "config_schema_v1":
        raise ValueError("config_schema.json schema_id 不匹配")
    return data


def validate_config_schema(schema: dict[str, Any]) -> list[ConfigSchemaIssue]:
    issues: list[ConfigSchemaIssue] = []
    sheets = schema.get("sheets")
    if not isinstance(sheets, dict) or not sheets:
        return [ConfigSchemaIssue("<root>", "sheets", "必须至少声明一个配置 Sheet")]
    for sheet, spec in sheets.items():
        keys = spec.get("keys") if isinstance(spec, dict) else None
        if not isinstance(keys, dict) or not keys:
            issues.append(ConfigSchemaIssue(sheet, "<sheet>", "keys 必须为非空对象"))
            continue
        for key, definition in keys.items():
            if not isinstance(definition, dict):
                issues.append(ConfigSchemaIssue(sheet, key, "字段定义必须为对象"))
                continue
            missing = REQUIRED_DEFINITION_KEYS - set(definition)
            if missing:
                issues.append(ConfigSchemaIssue(sheet, key, f"缺少定义字段：{sorted(missing)}"))
            if definition.get("type") not in {"string", "number", "integer", "boolean", "enum", "array", "object", "datetime"}:
                issues.append(ConfigSchemaIssue(sheet, key, "type 不在允许域内"))
            if definition.get("required") is not True and definition.get("required") is not False:
                issues.append(ConfigSchemaIssue(sheet, key, "required 必须是布尔值"))
            if definition.get("required") and definition.get("default") is not None:
                issues.append(ConfigSchemaIssue(sheet, key, "required 字段禁止配置隐式 default"))
            enum = definition.get("enum")
            if (definition.get("type") == "enum" and not isinstance(enum, list)) or (definition.get("type") != "enum" and enum is not None):
                issues.append(ConfigSchemaIssue(sheet, key, "enum 必须与 type=enum 一致"))
    return issues

