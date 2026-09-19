"""T01-03A 缺失值与异常值判定。

字段级政策来自 ``config/field_schema.json``，本模块只负责把统一语义
落实为可执行判定：必需字段缺失、非法数值和把派生量当输入均不得静默放行。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..states import Status

__all__ = ["MissingValueDecision", "load_missing_policy", "assess_field"]


@dataclass(frozen=True)
class MissingValueDecision:
    field: str
    status: Status
    policy: str
    action: str
    reason: str
    value_source: str | None = None

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "status": self.status.value,
            "policy": self.policy,
            "action": self.action,
            "reason": self.reason,
            "value_source": self.value_source,
        }


def load_missing_policy(config_dir: Path) -> dict:
    """读取 T01-03A 规则表，并拒绝损坏或不完整的制品。"""
    path = config_dir / "missing_value_policy.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"policy_domain", "semantics", "policy_actions", "invariants"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"缺失值规则表缺少字段：{sorted(missing)}")
    return data


def assess_field(
    field_spec: dict[str, Any],
    value: Any = None,
    *,
    present: bool = True,
    valid: bool = True,
    value_source: str | None = None,
    policy: dict | None = None,
) -> MissingValueDecision:
    """按字段字典和 T01-03A 规则判定一个字段。

    ``present=False`` 表示 key 不存在；``value=None`` 表示已存在但为空。
    两者都属于 missing，但调用方仍可通过 ``present`` 保留审计差异。
    ``valid=False`` 表示解析失败或越界，优先级高于所有缺失策略。
    """
    name = str(field_spec.get("name", "<unnamed>"))
    pol = str(field_spec.get("missing_policy", ""))
    domain = set((policy or {}).get("policy_domain", ()))
    if domain and pol not in domain:
        return MissingValueDecision(name, Status.BLOCKED, pol, "reject",
                                    f"missing_policy 非法：{pol!r}")
    if pol == "DERIVED" and present:
        return MissingValueDecision(name, Status.BLOCKED, pol, "reject",
                                    "派生量不得作为输入字段提供")
    if not valid:
        return MissingValueDecision(name, Status.BLOCKED, pol, "reject",
                                    "字段值无法解析或违反声明约束")
    missing = (not present) or value is None
    if missing:
        if pol == "DERIVED":
            return MissingValueDecision(name, Status.BLOCKED, pol, "reject",
                                        "派生量不得作为输入字段提供")
        if pol == "ALLOW_EMPTY_NO_CAP":
            return MissingValueDecision(name, Status.PASS, pol, "preserve_no_cap",
                                        "空值具有不限价语义，保留 no_cap=true")
        if not field_spec.get("nullable", True):
            return MissingValueDecision(name, Status.BLOCKED, pol, "reject",
                                        "必需字段缺失：nullable=false")
        actions = (policy or {}).get("policy_actions", {})
        action = actions.get(pol, {}).get("action", "reject")
        if pol == "WARN":
            return MissingValueDecision(name, Status.WARN, pol, action, "可空字段缺失")
        if pol in {"DEFAULT", "IMPUTE", "IGNORE"}:
            if pol == "DEFAULT" and field_spec.get("default") is None:
                return MissingValueDecision(name, Status.BLOCKED, pol, "reject",
                                            "DEFAULT 策略缺少显式 default")
            return MissingValueDecision(name, Status.PASS, pol, action, "可空字段按声明策略处理",
                                        "defaulted" if pol == "DEFAULT" else "inferred" if pol == "IMPUTE" else None)
        return MissingValueDecision(name, Status.BLOCKED, pol, "reject",
                                    "缺失策略要求阻断")
    if value_source == "inferred":
        return MissingValueDecision(name, Status.WARN, pol, "retain_for_review",
                                    "值为推断值，必须保留来源并进入人工复核", value_source)
    return MissingValueDecision(name, Status.PASS, pol, "accept", "字段值存在且有效", value_source)
