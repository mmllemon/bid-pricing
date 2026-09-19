"""T06-04 一键复算协议：R1-A 可重复性、R1-B 正确性、R1-C 环境记录。"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

SPEC_FILENAME = "rerun_spec.json"
ENVIRONMENT_FIELDS = ("python", "pulp", "highs", "os", "arch", "solver_options", "random_seed")


def load_rerun_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k]) for k in sorted(value, key=str) if k not in {"run_id", "timestamp", "created_at", "operator"}}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def result_hash(result: Any) -> str:
    """对不含运行元信息的规范结果计算稳定 SHA-256。"""
    payload = json.dumps(_canonical(result), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def environment_record(*, solver_options: Mapping[str, Any] | None = None, random_seed: int | None = None) -> dict[str, Any]:
    """记录 R1-C 所需环境；未安装的可选求解器显式为 null。"""
    return {
        "python": sys.version.split()[0],
        "pulp": _package_version("PuLP"),
        "highs": _package_version("highspy"),
        "os": platform.platform(),
        "arch": platform.machine(),
        "solver_options": dict(solver_options or {}),
        "random_seed": random_seed,
    }


@dataclass(frozen=True)
class RerunCheck:
    check_id: str
    status: str
    actual: Any
    expected: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"check_id": self.check_id, "status": self.status, "actual": self.actual, "expected": self.expected, "reason": self.reason}


@dataclass(frozen=True)
class RerunReport:
    status: str
    result_hash: str | None
    checks: tuple[RerunCheck, ...]
    environment: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "result_hash": self.result_hash, "checks": [c.to_dict() for c in self.checks], "environment": self.environment}


def build_rerun_report(
    runner: Callable[[Any], Any],
    input_payload: Any,
    *,
    expected_result: Any | None = None,
    solver_options: Mapping[str, Any] | None = None,
    random_seed: int | None = None,
) -> RerunReport:
    """执行两次同输入复算，并可选地对绑定 expected 做逐结果比较。"""
    first = runner(input_payload)
    second = runner(input_payload)
    first_hash, second_hash = result_hash(first), result_hash(second)
    checks: list[RerunCheck] = [RerunCheck("R1-A", "PASS" if first_hash == second_hash else "FAIL", second_hash, first_hash, "同输入两次 result_hash 一致" if first_hash == second_hash else "同输入两次 result_hash 不一致")]
    if expected_result is None:
        checks.append(RerunCheck("R1-B", "BLOCKED", None, None, "未绑定 golden expected，不能宣称正确性通过"))
    else:
        expected_hash = result_hash(expected_result)
        checks.append(RerunCheck("R1-B", "PASS" if first_hash == expected_hash else "FAIL", first_hash, expected_hash, "结果匹配绑定 golden expected" if first_hash == expected_hash else "结果不匹配绑定 golden expected"))
    env = environment_record(solver_options=solver_options, random_seed=random_seed)
    missing = [name for name, value in env.items() if name in {"python", "os", "arch", "solver_options", "random_seed"} and value is None]
    checks.append(RerunCheck("R1-C", "BLOCKED" if missing else "PASS", env, ENVIRONMENT_FIELDS, "环境字段已完整记录" if not missing else "环境字段缺失: " + ", ".join(missing)))
    statuses = {check.status for check in checks}
    status = "BLOCKED" if "BLOCKED" in statuses else ("FAIL" if "FAIL" in statuses else "PASS")
    return RerunReport(status, first_hash, tuple(checks), env)
