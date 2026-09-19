"""T07-01 历史项目回放框架；不足三项目时明确阻断。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .rerun import result_hash

SPEC_FILENAME = "historical_replay_spec.json"
MINIMUM_PROJECTS = 3


def load_historical_replay_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class ReplayResult:
    project_id: str
    status: str
    result_hash: str | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "status": self.status, "result_hash": self.result_hash, "error": self.error}


@dataclass(frozen=True)
class ReplayReport:
    status: str
    minimum_projects: int
    completed_projects: int
    results: tuple[ReplayResult, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "minimum_projects": self.minimum_projects, "completed_projects": self.completed_projects, "results": [r.to_dict() for r in self.results], "reason": self.reason}


def replay_historical_projects(
    projects: Sequence[Mapping[str, Any]],
    runner: Callable[[Mapping[str, Any]], Any],
    *,
    minimum_projects: int = MINIMUM_PROJECTS,
) -> ReplayReport:
    results: list[ReplayResult] = []
    seen: set[str] = set()
    for project in projects:
        project_id = str(project.get("project_id", ""))
        if not project_id or project_id in seen:
            results.append(ReplayResult(project_id or "<missing>", "BLOCKED", None, "project_id 缺失或重复"))
            continue
        seen.add(project_id)
        try:
            output = runner(project)
            if output is None:
                raise ValueError("runner 返回空结果")
            results.append(ReplayResult(project_id, "PASS", result_hash(output)))
        except Exception as exc:  # 回放报告必须收集单项目错误而非中断全批次
            results.append(ReplayResult(project_id, "FAIL", None, str(exc)))
    completed = sum(result.status == "PASS" for result in results)
    if completed < minimum_projects:
        status = "BLOCKED"
        reason = f"可完整复算项目 {completed} 个，小于最低要求 {minimum_projects} 个"
    elif any(result.status == "FAIL" for result in results):
        status = "FAIL"
        reason = "存在历史项目回放失败"
    else:
        status = "PASS"
        reason = f"{completed} 个历史项目完整复算通过"
    return ReplayReport(status, minimum_projects, completed, tuple(results), reason)
