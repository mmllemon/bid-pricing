"""T06-08 不可变审计运行记录链。"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SPEC_FILENAME = "audit_log_spec.json"
CHAIN = ("RunID", "Input", "Config", "RuleSet", "Model", "Solver", "Output", "Decision")


def load_audit_log_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def _event_hash(event: Mapping[str, Any]) -> str:
    body = {key: event[key] for key in ("sequence", "run_id", "operator", "created_at", "event_type", "payload", "previous_hash")}
    return "sha256:" + hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEvent:
    sequence: int
    run_id: str
    operator: str
    created_at: str
    event_type: str
    payload: Mapping[str, Any]
    previous_hash: str | None
    event_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {"sequence": self.sequence, "run_id": self.run_id, "operator": self.operator, "created_at": self.created_at, "event_type": self.event_type, "payload": dict(self.payload), "previous_hash": self.previous_hash, "event_hash": self.event_hash}


@dataclass(frozen=True)
class AuditChain:
    status: str
    events: tuple[AuditEvent, ...]
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "events": [event.to_dict() for event in self.events], "errors": list(self.errors)}


def build_audit_chain(
    sections: Mapping[str, Mapping[str, Any]],
    *,
    run_id: str | None = None,
    operator: str,
    created_at: str | None = None,
) -> AuditChain:
    """按固定八段生成不可变 hash 链；缺段或空 payload 不静默补全。"""
    run_id = run_id or str(uuid.uuid4())
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    errors: list[str] = []
    if not str(operator).strip():
        errors.append("operator 不能为空")
    events: list[AuditEvent] = []
    previous: str | None = None
    for index, event_type in enumerate(CHAIN):
        payload = sections.get(event_type)
        if not isinstance(payload, Mapping) or not payload:
            errors.append(f"缺少或为空的审计段: {event_type}")
            continue
        draft = {"sequence": index, "run_id": run_id, "operator": operator, "created_at": created_at, "event_type": event_type, "payload": dict(payload), "previous_hash": previous}
        event = AuditEvent(**draft, event_hash=_event_hash(draft))
        events.append(event)
        previous = event.event_hash
    if len(events) != len(CHAIN):
        errors.append("审计链段数不完整")
    chain = AuditChain("PASS" if not errors else "BLOCKED", tuple(events), tuple(errors))
    if chain.status == "PASS":
        valid, verify_errors = verify_audit_chain(chain.events)
        if not valid:
            return AuditChain("BLOCKED", chain.events, tuple(verify_errors))
    return chain


def verify_audit_chain(events: Sequence[AuditEvent | Mapping[str, Any]]) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    if len(events) != len(CHAIN):
        errors.append(f"事件数量应为 {len(CHAIN)}")
    previous = None
    for index, raw in enumerate(events):
        event = raw if isinstance(raw, AuditEvent) else AuditEvent(**raw)
        if event.sequence != index or event.event_type != (CHAIN[index] if index < len(CHAIN) else None):
            errors.append(f"序号或事件类型错误: {event.sequence}/{event.event_type}")
        if event.previous_hash != previous:
            errors.append(f"{event.event_type} previous_hash 链接错误")
        if event.event_hash != _event_hash(event.to_dict()):
            errors.append(f"{event.event_type} event_hash 校验失败")
        previous = event.event_hash
    return not errors, tuple(errors)
