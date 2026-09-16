"""选择项（Selectable Option）机制 —— ``adjustment_scope`` 的落地方式。

问题
----
``adjustment_scope`` 决定 GB/T 50500-2024 §8.9「工程量偏差」的结算口径：
``FULL``（全部工程量按调整后单价结算）与 ``SEGMENT``（仅超出 1.15·Q0 的部分
按调整后单价）。规范原文未明说是否分段，而两种解读下**最优报价结构相反、
利润差约 4.5 倍**。

因此它既不是可由代码推断的常量，也不适合当作「一次裁决后写死」的常量——
不同项目、不同合同条款下，正确口径可能不同。它是**项目级选择项**。

设计（四条硬约束）
------------------
1. **取值集合按规则集而定**：GB 50500-2013 §9.6.2 明文分段累加 → 该规则集下
   只有 ``SEGMENT`` 可选；GB/T 50500-2024 → ``FULL`` / ``SEGMENT`` 二选一。
   在 2013 项目上选择 ``FULL`` 不是"另一种解读"，而是**错误配置**，直接 BLOCKED。
2. **不设默认值**。默认值会让「未选择」与「已选择」在机器上不可区分，
   等价于在该误差区间内做优化——§7.1.1 断言 2 要拦的正是这条路径。
3. **未选择时不写 value 字段**，与断言 1「未定态 = key 完全缺失」同构，
   使"还没选"成为机器可判状态而非靠人自觉。
4. **落值携带来源与依据**（``source`` / ``actor`` / ``selected_at`` / ``rationale``），
   构成报价决策的审计快照——独立互审指出 v3.1/v3.2 缺"决策依据快照"，
   本模块把它下沉到选择项本身，而不是事后补一张表。

落值通道与优先级
----------------
``CLI`` → ``config/project_selection.json`` → 规则集确定值 → **未定（BLOCKED）**。

其中「规则集确定值」只对非歧义规则集成立（2013），此时来源标记为
:data:`SOURCE_RULE_SET`，与"人工选择"在审计上严格区分。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------- 来源标签

SOURCE_CLI = "CLI"
SOURCE_FILE = "PROJECT_SELECTION_FILE"
SOURCE_RULE_SET = "RULE_SET_DETERMINED"
SOURCE_UNSELECTED = "UNSELECTED"


@dataclass(frozen=True)
class SelectableOption:
    """一个选择项的元定义。"""

    key: str
    title: str
    gate: str
    spec_ref: str
    consumers: tuple[str, ...]
    allowed_by_rule_set: dict[str, tuple[str, ...]]
    rationale: str
    impact: dict[str, str] = field(default_factory=dict)

    @property
    def default(self) -> None:
        """选择项**永无默认值**（§7.1.1 断言 6①）。"""
        return None

    def allowed_for(self, rule_set_id: str | None) -> tuple[str, ...]:
        """该规则集下的合法取值集合。

        规则集未定时返回**全部取值的并集**并保持稳定顺序——用于报告展示，
        不作为放行依据（规则集未定本身已足以 BLOCK）。
        """
        if rule_set_id is None:
            seen: list[str] = []
            for values in self.allowed_by_rule_set.values():
                for value in values:
                    if value not in seen:
                        seen.append(value)
            return tuple(seen)
        return tuple(self.allowed_by_rule_set.get(rule_set_id, ()))

    def determined_value(self, rule_set_id: str | None) -> str | None:
        """规则集本身已确定该口径（无选择余地）时返回该值，否则 ``None``。"""
        allowed = self.allowed_for(rule_set_id)
        return allowed[0] if len(allowed) == 1 else None

    def is_discretionary(self, rule_set_id: str | None) -> bool:
        """该规则集下该选择项是否真的有选择余地。"""
        return len(self.allowed_for(rule_set_id)) > 1

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "kind": "enum",
            "gate": self.gate,
            "spec_ref": self.spec_ref,
            "consumers": list(self.consumers),
            "allowed_by_rule_set": {
                k: list(v) for k, v in self.allowed_by_rule_set.items()
            },
            "default": self.default,
            "rationale": self.rationale,
            "impact": dict(self.impact),
        }


ADJUSTMENT_SCOPE = SelectableOption(
    key="adjustment_scope",
    title="§8.9 工程量偏差调整作用域",
    gate="gate_0a",
    spec_ref="T00-08 / T00-01",
    consumers=(
        "WP3 判定层 R_i(·) 分段逻辑",
        "WP4 求解层目标函数与约束",
        "WP4 Phase 1/2 对拍",
        "WP6 报价表与总价分解输出",
    ),
    allowed_by_rule_set={
        "GB/T50500-2024": ("FULL", "SEGMENT"),
        "GB50500-2013": ("SEGMENT",),
    },
    rationale=(
        "GB/T 50500-2024 §8.9 未明说是否分段。FULL 与 SEGMENT 下最优报价结构相反、"
        "利润差约 4.5 倍，故列为项目级选择项：系统同时实现两条路径，由显式选择决定"
        "生效分支，**不设默认值**。"
    ),
    impact={
        "FULL": (
            "字面口径：该清单项目**全部工程量**按调整后单价结算。"
            "r_eff 在 r=1.15 处**跳降** ≈ −1.15·ρ⁺（收益结构不连续）"
        ),
        "SEGMENT": (
            "分段口径：仅超出 1.15·Q0 的部分按调整后单价，其余按合同单价。"
            "r_eff 在阈值处**连续**（与 2013 同形）"
        ),
    },
)

#: 全局选择项注册表
SELECTABLE_OPTIONS: dict[str, SelectableOption] = {
    ADJUSTMENT_SCOPE.key: ADJUSTMENT_SCOPE,
}


# ------------------------------------------------------------- 解析结果

@dataclass(frozen=True)
class OptionResolution:
    """一次选择项解析的结果。"""

    key: str
    value: str | None
    source: str
    rule_set_id: str | None
    allowed: tuple[str, ...]
    rationale: str = ""
    actor: str | None = None
    selected_at: str | None = None
    errors: tuple[str, ...] = ()

    @property
    def is_resolved(self) -> bool:
        return self.value is not None and not self.errors

    @property
    def is_undetermined(self) -> bool:
        """未定：既没选、也没有配置错误。"""
        return self.value is None and not self.errors

    @property
    def is_conflict(self) -> bool:
        """已给出取值但与规则集冲突（含规则集未定）。"""
        return bool(self.errors)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "rule_set_id": self.rule_set_id,
            "allowed": list(self.allowed),
            "rationale": self.rationale,
            "actor": self.actor,
            "selected_at": self.selected_at,
            "status": (
                "RESOLVED" if self.is_resolved
                else "CONFLICT" if self.is_conflict
                else "UNSELECTED"
            ),
            "errors": list(self.errors),
        }


# ------------------------------------------------------------- 文件落值

SELECTION_ID = "project_selection_v1"

SELECTION_FILE_NOTE = (
    "项目级选择项落值文件。**未选择的选择项不写 value 字段**——"
    "与《实施路线 v3.2.1》§7.1.1 断言 1「未定态 = key 完全缺失」同构，"
    "使「还没选」在机器上可判。本文件由 `bidpricing options set` 写入，"
    "禁止手工填默认值（断言 6① 会拒绝）。"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_project_selection(path: Path | None) -> dict:
    """读取选择项落值文件；不存在或损坏时返回空文档（等价于全部未选择）。"""
    if path is None or not Path(path).exists():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def read_option_entry(path: Path | None, key: str) -> dict | None:
    entry = (load_project_selection(path).get("options") or {}).get(key)
    return entry if isinstance(entry, dict) else None


def write_option(
    path: Path,
    key: str,
    value: str,
    *,
    rule_set_id: str,
    rationale: str = "",
    actor: str = "operator",
    now: datetime | None = None,
) -> dict:
    """写入一条选择项落值（保留文件内其他选择项）。

    只做**写入**，不做合法性判断——合法性由 :func:`resolve_option` 统一负责，
    避免两处判据漂移。
    """
    path = Path(path)
    doc = load_project_selection(path)
    doc.setdefault("selection_id", SELECTION_ID)
    doc.setdefault("note", SELECTION_FILE_NOTE)
    options = doc.setdefault("options", {})
    options[key] = {
        "value": value,
        "rule_set_id": rule_set_id,
        "source": "OPERATOR",
        "actor": actor,
        "selected_at": (now or datetime.now(timezone.utc))
        .replace(microsecond=0)
        .isoformat(),
        "rationale": rationale,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return doc


def clear_option(path: Path, key: str) -> dict:
    """撤销一条选择项落值，回到「未选择」（不写 value 字段）。"""
    path = Path(path)
    doc = load_project_selection(path)
    options = doc.setdefault("options", {})
    options.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return doc


# --------------------------------------------------------------- 解析

def resolve_option(
    key: str,
    rule_set_id: str | None,
    *,
    cli_value: str | None = None,
    path: Path | None = None,
) -> OptionResolution:
    """按固定优先级解析一个选择项的取值。

    优先级：``CLI`` → ``PROJECT_SELECTION_FILE`` → ``RULE_SET_DETERMINED`` → 未定。
    **任何情况下都不猜**：无值即未定，未定即 BLOCKED。
    """
    option = SELECTABLE_OPTIONS[key]

    if rule_set_id is None:
        return OptionResolution(
            key=key,
            value=None,
            source=SOURCE_UNSELECTED,
            rule_set_id=None,
            allowed=option.allowed_for(None),
            errors=("规则集未定，选择项的合法取值集合不可判定（须先解决规则集选择）",),
        )

    allowed = option.allowed_for(rule_set_id)

    # ---------------------------------------------------- 1) 命令行（最高优先）
    actor: str | None = None
    selected_at: str | None = None
    rationale = ""
    if cli_value is not None:
        value, source = cli_value, SOURCE_CLI
    else:
        entry = read_option_entry(path, key)
        if entry and entry.get("value"):
            entry_rule_set = entry.get("rule_set_id")
            if entry_rule_set and entry_rule_set != rule_set_id:
                # 规则集切换后落值一律失效（禁止沿用）——依据快照是在旧规则集下
                # 做出的，沿用会把"当时的前提"静默带到"现在的前提"。
                # 但若当前规则集本就无选择余地（如 2013 只有 SEGMENT），
                # "重新选择"是空操作，此时明确提示清除即可，避免把人引到
                # 一个不存在的动作上。
                if option.is_discretionary(rule_set_id):
                    remedy = "必须以当前规则集重新选择（禁止沿用）"
                else:
                    remedy = (
                        f"且当前规则集 {rule_set_id} 下该口径由规范明文确定为 "
                        f"{list(allowed)}，不构成可选项——清除本条落值即可"
                        f"（options clear），清除后按规则集自动取值"
                    )
                return OptionResolution(
                    key=key,
                    value=None,
                    source=SOURCE_FILE,
                    rule_set_id=rule_set_id,
                    allowed=allowed,
                    errors=(
                        f"选择项落值记录属于规则集 {entry_rule_set}，当前规则集为 "
                        f"{rule_set_id}；二者不匹配，{remedy}",
                    ),
                )
            value, source = entry["value"], SOURCE_FILE
            actor = entry.get("actor")
            selected_at = entry.get("selected_at")
            rationale = str(entry.get("rationale") or "")
        else:
            determined = option.determined_value(rule_set_id)
            if determined is not None:
                return OptionResolution(
                    key=key,
                    value=determined,
                    source=SOURCE_RULE_SET,
                    rule_set_id=rule_set_id,
                    allowed=allowed,
                    rationale=f"{rule_set_id} 已由规范明文确定该口径，非人工可选项",
                )
            return OptionResolution(
                key=key,
                value=None,
                source=SOURCE_UNSELECTED,
                rule_set_id=rule_set_id,
                allowed=allowed,
            )

    # ------------------------------------------------------------ 2) 合法性
    if value not in allowed:
        extra = (
            "（该规则集下该口径由规范明文确定，不构成可选项）"
            if not option.is_discretionary(rule_set_id)
            else ""
        )
        return OptionResolution(
            key=key,
            value=None,
            source=source,
            rule_set_id=rule_set_id,
            allowed=allowed,
            errors=(
                f"选择项 {key}={value!r} 在规则集 {rule_set_id} 下不可选；"
                f"合法取值仅 {list(allowed)}{extra}",
            ),
        )

    return OptionResolution(
        key=key,
        value=value,
        source=source,
        rule_set_id=rule_set_id,
        allowed=allowed,
        rationale=rationale,
        actor=actor,
        selected_at=selected_at,
    )
