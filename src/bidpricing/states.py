"""全局状态机与闸门判定数据结构。

对应《投标报价模型 v0.3 实施路线与任务清单 v3.2.1》§5「全局状态机」：

    PASS    全部机械判据通过
    WARN    P1 类不通过，经授权可 override，但必须留痕（进 T06-08 审计链）
    FAIL    检测到风险或不满足约束
    BLOCKED 数据或规则不足，**禁止继续计算**；不是 FAIL，也不允许 override 绕过

聚合优先级：``BLOCKED > FAIL > WARN > PASS``（路线 §7.2）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2, "BLOCKED": 3}


class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"

    @property
    def rank(self) -> int:
        return _RANK[self.value]

    @property
    def blocks_progress(self) -> bool:
        """FAIL 与 BLOCKED 均不得继续计算（P0 类不允许人工 override）。"""
        return self in (Status.FAIL, Status.BLOCKED)


# O6（治理审查 P1）：此前 STATUS_PASS 在 14 个模块各自声明、_STATUS_ORDER 在 6 处
# 独立 tuple 实现且与 _RANK 排序方向不一致。统一为单点定义，各模块 import 而非重定义。
STATUS_PASS = Status.PASS.value
STATUS_FAIL = Status.FAIL.value
STATUS_WARN = Status.WARN.value
STATUS_BLOCKED = Status.BLOCKED.value
STATUS_SKIP = "SKIP"
STATUS_INFO = "INFO"

#: 聚合遍历序（制品 verdict_aggregation.order 的镜像）：FAIL 最先检查，PASS 最后。
#: 注意与 _RANK 语义不同：_RANK 是数值比较（BLOCKED=3 最严），_STATUS_ORDER 是遍历顺序。
_STATUS_ORDER = (STATUS_FAIL, STATUS_BLOCKED, STATUS_WARN, STATUS_SKIP, STATUS_PASS)


def aggregate(statuses: Iterable[Status]) -> Status:
    worst = Status.PASS
    for s in statuses:
        if s.rank > worst.rank:
            worst = s
    return worst


@dataclass(frozen=True)
class CheckItem:
    """单条机械判据结果。字段命名对齐路线 §5.4 R3「actual + threshold + delta」。"""

    scope: str
    item: str
    status: Status
    reason: str
    actual: object | None = None
    expected: object | None = None
    delta: object | None = None

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "item": self.item,
            "status": self.status.value,
            "actual": self.actual,
            "expected": self.expected,
            "delta": self.delta,
            "reason": self.reason,
        }


@dataclass
class GateReport:
    """一个闸门的判定报告。"""

    gate: str
    purpose: str
    items: list[CheckItem] = field(default_factory=list)

    def add(self, item: CheckItem) -> "GateReport":
        self.items.append(item)
        return self

    @property
    def status(self) -> Status:
        return aggregate(i.status for i in self.items)

    @property
    def blockers(self) -> list[CheckItem]:
        return [i for i in self.items if i.status is Status.BLOCKED]

    @property
    def failures(self) -> list[CheckItem]:
        return [i for i in self.items if i.status is Status.FAIL]

    @property
    def warnings(self) -> list[CheckItem]:
        return [i for i in self.items if i.status is Status.WARN]

    @property
    def passed(self) -> bool:
        return self.status is Status.PASS

    def to_dict(self) -> dict:
        return {
            "gate": self.gate,
            "purpose": self.purpose,
            "status": self.status.value,
            "items": [i.to_dict() for i in self.items],
        }
