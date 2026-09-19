"""T02-05 配置/模型版本绑定校验。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .artifact import compute_artifact_hash

MODEL_VERSION = "0.3"


@dataclass(frozen=True)
class VersionBindingIssue:
    kind: str
    key: str
    reason: str
    actual: Any = None
    expected: Any = None


@dataclass(frozen=True)
class VersionBindingReport:
    issues: tuple[VersionBindingIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        return {"passed": self.passed, "issues": [i.__dict__ for i in self.issues]}


def capture_binding(registry: Mapping[str, Any], *, model_version: str = MODEL_VERSION) -> dict:
    """从当前注册表捕获一份不可隐式漂移的版本绑定快照。"""
    artifacts: dict[str, dict[str, str]] = {}
    for gate in ("gate_0a", "gate_0b"):
        for key, spec in (registry.get(gate) or {}).items():
            if isinstance(spec, Mapping) and spec.get("kind") == "versioned":
                artifacts[f"{gate}.{key}"] = {
                    "version": str(spec.get("version") or ""),
                    "hash": str(spec.get("hash") or ""),
                }
    return {"model_version": model_version, "artifacts": artifacts}


def validate_binding(
    binding: Mapping[str, Any],
    registry: Mapping[str, Any],
    config_dir: Path,
    *,
    expected_model_version: str = MODEL_VERSION,
) -> VersionBindingReport:
    issues: list[VersionBindingIssue] = []
    if binding.get("model_version") != expected_model_version:
        issues.append(VersionBindingIssue("model", "model_version", "模型版本不兼容", binding.get("model_version"), expected_model_version))
    expected = binding.get("artifacts")
    if not isinstance(expected, Mapping) or not expected:
        return VersionBindingReport(tuple(issues + [VersionBindingIssue("missing", "artifacts", "版本绑定未声明任何制品")]))
    for qualified, pinned in expected.items():
        if not isinstance(pinned, Mapping):
            issues.append(VersionBindingIssue("format", qualified, "制品绑定必须是对象"))
            continue
        try:
            gate, key = qualified.split(".", 1)
        except ValueError:
            issues.append(VersionBindingIssue("unknown", qualified, "制品绑定键必须为 gate.key"))
            continue
        spec = (registry.get(gate) or {}).get(key)
        if not isinstance(spec, Mapping) or spec.get("kind") != "versioned":
            issues.append(VersionBindingIssue("unknown", qualified, "注册表中不存在 versioned 制品"))
            continue
        current_version, current_hash = spec.get("version"), spec.get("hash")
        if not current_version or not current_hash:
            issues.append(VersionBindingIssue("unfrozen", qualified, "制品未冻结", current_hash))
            continue
        if current_version != current_hash:
            issues.append(VersionBindingIssue("registry", qualified, "注册表 version/hash 不一致", current_version, current_hash))
        path = config_dir / str(spec.get("artifact_path", ""))
        if not path.exists():
            issues.append(VersionBindingIssue("missing", qualified, "制品文件不存在", str(path)))
            continue
        actual_hash = compute_artifact_hash(path)
        if actual_hash != current_hash:
            issues.append(VersionBindingIssue("drift", qualified, "制品内容与注册表 hash 不一致", actual_hash, current_hash))
        if pinned.get("version") != current_version or pinned.get("hash") != current_hash:
            issues.append(VersionBindingIssue("mismatch", qualified, "运行绑定快照与当前注册表不一致", {"version": current_version, "hash": current_hash}, dict(pinned)))
    return VersionBindingReport(tuple(issues))
