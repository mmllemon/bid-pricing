"""T02-04 配置耦合度体检。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

from .config_schema import validate_config_schema


@dataclass(frozen=True)
class CouplingAudit:
    sheet_count: int
    field_count: int
    duplicate_fields: tuple[str, ...]
    cross_sheet_references: int
    default_count: int
    invalid_references: tuple[str, ...]
    schema_issues: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.duplicate_fields and not self.invalid_references and not self.schema_issues

    def to_dict(self) -> dict:
        return {
            "sheet_count": self.sheet_count,
            "field_count": self.field_count,
            "duplicate_fields": list(self.duplicate_fields),
            "cross_sheet_references": self.cross_sheet_references,
            "default_count": self.default_count,
            "invalid_references": list(self.invalid_references),
            "schema_issues": list(self.schema_issues),
            "passed": self.passed,
        }


def audit_config_coupling(schema: Mapping[str, Any]) -> CouplingAudit:
    sheets = schema.get("sheets") or {}
    names: list[str] = []
    paths: set[str] = set()
    defaults = 0
    for sheet, spec in sheets.items():
        for key, definition in (spec.get("keys") or {}).items():
            names.append(key.rsplit(".", 1)[-1])
            paths.add(f"{sheet}.{key}")
            if definition.get("default") is not None:
                defaults += 1
    counts = Counter(names)
    # ``options.*.value`` 是项目选择项的统一载荷槽位，跨选项重复是有意的
    # 结构复用，不属于字段定义冲突；其余同名叶字段才视为耦合风险。
    duplicates = tuple(sorted(name for name, count in counts.items() if count > 1 and name != "value"))
    invalid_refs: list[str] = []
    references = schema.get("references") or []
    for ref in references:
        if not isinstance(ref, Mapping) or ref.get("from") not in paths or ref.get("to") not in paths:
            invalid_refs.append(str(dict(ref)) if isinstance(ref, Mapping) else repr(ref))
    schema_issues = tuple(i.reason for i in validate_config_schema(dict(schema)))
    return CouplingAudit(
        sheet_count=len(sheets),
        field_count=len(names),
        duplicate_fields=duplicates,
        cross_sheet_references=len(references),
        default_count=defaults,
        invalid_references=tuple(sorted(invalid_refs)),
        schema_issues=schema_issues,
    )
