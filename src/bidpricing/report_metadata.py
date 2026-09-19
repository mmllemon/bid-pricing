"""T06-07 报告元信息与 calculation/artifact hash 分层。"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SPEC_FILENAME = "report_metadata_spec.json"
REQUIRED_BINDINGS = ("model_version", "config_version", "input_hash", "rule_set_version")
VOLATILE_FIELDS = {"timestamp", "created_at", "run_id", "operator", "artifact_hash"}


def load_report_metadata_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def _stable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _stable(value[k]) for k in sorted(value, key=str) if k not in VOLATILE_FIELDS}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    return value


def calculation_hash(calculation: Any) -> str:
    payload = json.dumps(_stable(calculation), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def artifact_hash(path: Path | str) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class ReportMetadata:
    calculation_hash: str
    artifact_hash: str | None
    run_id: str
    created_at: str
    operator: str
    model_version: str
    config_version: str
    input_hash: str
    rule_set_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "calculation_hash": self.calculation_hash, "artifact_hash": self.artifact_hash,
            "run_id": self.run_id, "created_at": self.created_at, "operator": self.operator,
            "model_version": self.model_version, "config_version": self.config_version,
            "input_hash": self.input_hash, "rule_set_version": self.rule_set_version,
        }


def build_report_metadata(
    calculation: Any,
    *,
    model_version: str,
    config_version: str,
    input_hash: str,
    rule_set_version: str,
    operator: str,
    artifact_path: Path | str | None = None,
    run_id: str | None = None,
    created_at: str | None = None,
) -> ReportMetadata:
    bindings = {"model_version": model_version, "config_version": config_version, "input_hash": input_hash, "rule_set_version": rule_set_version}
    missing = [key for key, value in bindings.items() if not str(value).strip()]
    if missing:
        raise ValueError("报告绑定字段缺失: " + ", ".join(missing))
    if not str(operator).strip():
        raise ValueError("operator 不能为空")
    return ReportMetadata(
        calculation_hash=calculation_hash(calculation),
        artifact_hash=None if artifact_path is None else artifact_hash(artifact_path),
        run_id=run_id or str(uuid.uuid4()),
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        operator=str(operator),
        **{key: str(value) for key, value in bindings.items()},
    )


def validate_report_metadata(metadata: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    required = ("calculation_hash", "run_id", "created_at", "operator", *REQUIRED_BINDINGS)
    errors = [key + " 缺失" for key in required if not str(metadata.get(key, "")).strip()]
    if metadata.get("calculation_hash") and not str(metadata["calculation_hash"]).startswith("sha256:"):
        errors.append("calculation_hash 必须带 sha256: 前缀")
    return ("PASS" if not errors else "BLOCKED", tuple(errors))
