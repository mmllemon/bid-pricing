"""T02-02 配置有效值合并器。

合并器只允许三种可审计来源：用户显式值、调用方显式提供的默认值、
以及明确标记的派生/推断值。它不会把 ``None`` 当成默认，也不会替用户
补齐合同、成本、税费或不可竞争费口径。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .states import Status

VALUE_SOURCES = {"explicit", "defaulted", "derived", "inferred"}


@dataclass(frozen=True)
class ConfigMergeResult:
    config: dict[str, Any]
    value_source: dict[str, str]
    missing_required: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def status(self) -> Status:
        if self.errors or self.missing_required:
            return Status.BLOCKED
        return Status.PASS

    def to_dict(self) -> dict:
        return {
            "config": self.config,
            "value_source": self.value_source,
            "missing_required": list(self.missing_required),
            "errors": list(self.errors),
            "status": self.status.value,
        }


def _flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            out.update(_flatten(item, path))
        else:
            out[path] = item
    return out


def _assign(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = target
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def merge_config(
    user: Mapping[str, Any],
    defaults: Mapping[str, Any] | None = None,
    *,
    schema: Mapping[str, Any] | None = None,
    derived: Mapping[str, Any] | None = None,
    inferred: Mapping[str, Any] | None = None,
) -> ConfigMergeResult:
    """合并用户配置并返回每个叶子值的来源。

    优先级为 ``user > inferred > derived > defaults``。defaults 不是隐式
    值：必须由调用方显式传入，且不能覆盖 schema 中的 required 字段。
    """
    user_flat = _flatten(user)
    default_flat = _flatten(defaults or {})
    derived_flat = _flatten(derived or {})
    inferred_flat = _flatten(inferred or {})
    definitions: dict[str, dict] = {}
    for sheet, spec in (schema or {}).get("sheets", {}).items():
        for path, definition in (spec.get("keys", {}) or {}).items():
            # schema 中的 key 在各 Sheet 内声明；运行时路径带 Sheet 前缀。
            definitions[f"{sheet}.{path}"] = definition

    errors: list[str] = []
    source: dict[str, str] = {}
    result: dict[str, Any] = {}
    all_paths = set(user_flat) | set(default_flat) | set(derived_flat) | set(inferred_flat)
    for path in sorted(all_paths):
        definition = definitions.get(path)
        if definition is None and schema is not None:
            errors.append(f"未注册配置键：{path}")
            continue
        if path in user_flat and user_flat[path] is not None:
            value, origin = user_flat[path], "explicit"
        elif path in inferred_flat and inferred_flat[path] is not None:
            value, origin = inferred_flat[path], "inferred"
        elif path in derived_flat and derived_flat[path] is not None:
            value, origin = derived_flat[path], "derived"
        elif path in default_flat and default_flat[path] is not None:
            if definition and definition.get("required"):
                errors.append(f"required 配置禁止 default：{path}")
                continue
            value, origin = default_flat[path], "defaulted"
        else:
            continue
        if origin == "derived" and definition and definition.get("type") == "enum":
            errors.append(f"枚举配置不得由 derived 来源提供：{path}")
            continue
        _assign(result, path, value)
        source[path] = origin

    missing_required: list[str] = []
    for path, definition in definitions.items():
        if definition.get("required") and path not in source:
            missing_required.append(path)
    return ConfigMergeResult(
        config=result,
        value_source=source,
        missing_required=tuple(sorted(missing_required)),
        errors=tuple(sorted(errors)),
    )
