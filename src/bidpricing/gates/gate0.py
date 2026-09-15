"""Gate 0a / Gate 0b 机械判据 —— 路线 §7.1 与 §7.1.1 的可执行实现。

为什么要有这个模块
------------------
v3.1 的 Gate 0 用「全部 version 字段非空」作单一冻结点，被独立互审指出两个缺陷：

1. 字段非空 **不代表内容有效/已冻结**（存一个 ``"未定"`` 字符串即可绕过）；
2. ``adjustment_scope`` 作为未证假设被带入开发，而 FULL / SEGMENT 两种解读下
   最优报价结构相反、利润差约 4.5 倍。

v3.2 / v3.2.1 因此把 Gate 0 拆为 **0a（技术接口）/ 0b（业务口径）**，
并写下六条死锁断言。本模块把这六条断言全部变成**CI 可执行**的判据——
换言之，"闸门"不再依赖人的自觉，而是构建流程的一部分。

六条断言与实现位置
------------------
======  ==================================================  ==========================
断言     内容                                                实现
======  ==================================================  ==========================
1       ``adjustment_scope`` 未定态 = key 完全缺失           :func:`guard_representation`
2       未定态熔断：Phase 0 直接 BLOCKED                      :func:`check_gate_0a`
3       双闸门独立判定，放行清单不含 T00-10B                  :func:`check_gate_0a`
4       字段有效性机械化（hash 绑定 + 占位符黑名单）          :mod:`bidpricing.artifact`
5       Gate 0b 必须早于 WP4 Phase 1                          :func:`assertion_5_sequence`
6       CI 门禁：配置层零默认值 + 求解层硬门禁                :func:`assertion_6_config_zero_defaults`
======  ==================================================  ==========================
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..artifact import (
    ArtifactRecord,
    advisories,
    parse_records,
    verify_enum,
    verify_versioned,
)
from ..states import CheckItem, GateReport, Status

#: Gate 0a 放行的工作包（路线 §7.1.1 断言 3）
GATE_0A_RELEASES = ("WP1 数据层", "WP2 配置层", "WP3 判定层")

#: 明确**不在** Gate 0a 放行清单中的任务（依赖 WP1 的 T01-00B 合同解析产出）
GATE_0A_RELEASE_EXCLUSIONS = (
    ("T00-10B", "q^1 来源判定依赖 T01-00B 的合同条款解析结果，属 Gate 0b 前置"),
)

#: Gate 0b 要求的审批角色（断言：分级审批，每角色签署制品 hash 非空）
GATE_0B_APPROVAL_ROLES = ("合同", "造价", "法务", "项目经理")

#: 断言 6：配置层**不得**为其提供任何默认值的字段（含模板与示例配置）
NO_DEFAULT_FIELD_PREFIXES = ("adjustment_scope", "q1", "c_i")

#: 断言 5：Gate 0b 必须在 WP4 Phase 1 之前
PHASE1_GUARDED_SCOPE = "WP4 Phase 1"


# --------------------------------------------------------------------- 工具


def _parse_ts(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def _iter_nodes(node, path="$"):
    """深度优先遍历 JSON 结构，产出 ``(path, node)``。"""
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_nodes(value, f"{path}.{key}")
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            yield from _iter_nodes(value, f"{path}[{idx}]")


def _is_watched(name: str) -> bool:
    return any(
        name == prefix or name.startswith(prefix + "_")
        for prefix in NO_DEFAULT_FIELD_PREFIXES
    )


# ------------------------------------------------------------- 断言 1：表示法


def guard_representation(selection: dict) -> CheckItem:
    """断言 1：未定态必须是 key 完全缺失，而不是任何非枚举字符串。

    反面样例（必须被拦截）：``{"adjustment_scope": "未定"}``、
    ``{"adjustment_scope": null}``、``{"adjustment_scope": "UNDETERMINED"}``。

    审计字段 ``adjustment_scope_status`` 允许存在，但**不参与放行判定**。
    """
    if "adjustment_scope" not in selection:
        return CheckItem(
            scope="§7.1.1-1", item="adjustment_scope_representation", status=Status.PASS,
            reason=(
                "key 完全缺失 → 机器可判的未定态（合格表示法）。"
                "该缺失将在 Gate 0a 判据中触发未定态熔断（断言 2）"
            ),
            actual="<missing>", expected="<missing> 或 {FULL, SEGMENT}",
        )

    value = selection["adjustment_scope"]
    if value is None:
        return CheckItem(
            scope="§7.1.1-1", item="adjustment_scope_representation", status=Status.FAIL,
            reason=(
                "写入了 null 而非删除 key。null 在多数 JSON→Python 转换后与"
                "「未提供」不可区分，且易被「非 None 即通过」的判据误判。"
                "正确做法：直接不输出该 key"
            ),
            actual="null", expected="<missing> 或 {FULL, SEGMENT}",
        )
    if str(value) in ("FULL", "SEGMENT"):
        return CheckItem(
            scope="§7.1.1-1", item="adjustment_scope_representation", status=Status.PASS,
            reason="已显式枚举为合法值", actual=str(value),
            expected=["FULL", "SEGMENT"],
        )
    return CheckItem(
        scope="§7.1.1-1", item="adjustment_scope_representation", status=Status.FAIL,
        reason=(
            f"非空字符串 {value!r} 冒充已冻结值——这正是 v3.2 熔断点被绕过的路径。"
            "未定态必须以「key 缺失」表示"
        ),
        actual=str(value), expected="<missing> 或 {FULL, SEGMENT}",
    )


# ----------------------------------------------------------------- Gate 0a


def check_gate_0a(
    registry: dict,
    config_dir: Path,
    selection: dict,
) -> GateReport:
    """Gate 0a：Technical Interface & Rule-Set Frozen。

    机械判据：8 项全部通过（versioned 走 :func:`verify_versioned`，
    ``adjustment_scope`` 走 :func:`verify_enum`，取值来自 T00-08 的选择结果）。
    """
    report = GateReport(
        gate="Gate 0a",
        purpose="技术接口与规则集冻结 → 放行 WP1 / WP2 / WP3 开发",
    )

    # 断言 1 先行：表示法不合格属结构性错误，直接 FAIL
    report.add(guard_representation(selection))

    records = parse_records(registry, "gate_0a")
    for rec in records:
        if rec.is_enum:
            continue
        report.add(verify_versioned(rec, config_dir))

    enum_recs = [r for r in records if r.is_enum]
    for rec in enum_recs:
        report.add(
            verify_enum(rec, selection.get(rec.key), "T00-08 select_rule_set()")
        )

    # 断言 3：双闸门独立判定 + 放行清单
    gate_status = report.status
    if gate_status is Status.PASS:
        release_reason = (
            f"放行 {', '.join(GATE_0A_RELEASES)}；"
            f"放行清单不含 {', '.join(t for t, _ in GATE_0A_RELEASE_EXCLUSIONS)}"
        )
    else:
        release_reason = (
            f"未放行任何下游工作包（{gate_status.value}）；"
            f"即使放行，清单亦不含 {', '.join(t for t, _ in GATE_0A_RELEASE_EXCLUSIONS)}"
        )
    report.add(
        CheckItem(
            scope="§7.1.1-3", item="release_scope", status=gate_status,
            reason=release_reason,
            actual=[i.item for i in report.blockers] or None,
            expected="8 项判据全通过",
        )
    )
    return report


# ----------------------------------------------------------------- Gate 0b


def check_gate_0b(registry: dict, config_dir: Path) -> GateReport:
    """Gate 0b：Business Caliber & Compliance Frozen。

    机械判据：5 项 versioned 制品齐备 + 分级审批 4 角色**每角色签署 hash 非空**。
    v3.2 仅要求 ``all_required_approvals = true``，可被单人勾选通过——本版修正。
    """
    report = GateReport(
        gate="Gate 0b",
        purpose="业务口径与合规依据冻结 → 阻塞 WP4 求解层，不阻塞 WP1/WP2/WP3",
    )

    records = parse_records(registry, "gate_0b")
    approval_rec: ArtifactRecord | None = None

    for rec in records:
        if rec.kind == "approvals":
            approval_rec = rec
            continue
        report.add(verify_versioned(rec, config_dir))

    # 分级审批（断言：每角色签署制品 hash 非空）
    raw = registry.get("gate_0b", {}).get("approvals", {})
    signed = raw.get("signed", {}) if isinstance(raw, dict) else {}
    missing_roles = []
    blank_hash_roles = []
    for role in GATE_0B_APPROVAL_ROLES:
        entry = signed.get(role)
        if not entry:
            missing_roles.append(role)
            continue
        if not isinstance(entry, dict) or not entry.get("hash"):
            blank_hash_roles.append(role)

    if missing_roles:
        report.add(
            CheckItem(
                scope="§7.1-Gate0b", item="approvals", status=Status.BLOCKED,
                reason=(
                    f"审批角色不齐，缺少：{', '.join(missing_roles)}。"
                    "v3.2 的单一布尔位可被一人勾选通过，业务口径并未真正冻结"
                ),
                actual=sorted(signed.keys()), expected=list(GATE_0B_APPROVAL_ROLES),
            )
        )
    elif blank_hash_roles:
        report.add(
            CheckItem(
                scope="§7.1-Gate0b", item="approvals", status=Status.BLOCKED,
                reason=f"以下角色的签署制品 hash 为空：{', '.join(blank_hash_roles)}",
                actual=signed, expected="每角色 {hash: sha256:...}",
            )
        )
    else:
        report.add(
            CheckItem(
                scope="§7.1-Gate0b", item="approvals", status=Status.PASS,
                reason=f"{len(GATE_0B_APPROVAL_ROLES)} 个角色均已签署且 hash 非空",
                actual=list(GATE_0B_APPROVAL_ROLES), expected=list(GATE_0B_APPROVAL_ROLES),
            )
        )
    _ = approval_rec
    return report


# ------------------------------------------------------------- 断言 5：时序


def assertion_5_sequence(
    gate_0b_passed_at: str | None,
    phase1_first_build_at: str | None,
) -> CheckItem:
    """断言 5：Gate 0b 必须先于 WP4 Phase 1。

    若发现 Phase 1 的求解记录时间早于 Gate 0b 通过时间，
    **该次求解结果一律作废并重跑**。
    """
    phase1 = _parse_ts(phase1_first_build_at)
    if phase1 is None:
        return CheckItem(
            scope="§7.1.1-5", item="gate0b_before_phase1", status=Status.PASS,
            reason=f"尚无 {PHASE1_GUARDED_SCOPE} 构建记录，断言空真（vacuous pass）",
            actual=None, expected="gate0b_passed_at < phase1_first_build_at",
        )

    gate0b = _parse_ts(gate_0b_passed_at)
    if gate0b is None:
        return CheckItem(
            scope="§7.1.1-5", item="gate0b_before_phase1", status=Status.FAIL,
            reason=(
                f"{PHASE1_GUARDED_SCOPE} 已有构建记录，但 Gate 0b 从未通过——"
                "求解层在业务口径未冻结时被构建，全部求解结果作废并重跑"
            ),
            actual=f"phase1={phase1_first_build_at}, gate0b=None",
            expected="gate0b_passed_at < phase1_first_build_at",
        )

    if gate0b >= phase1:
        return CheckItem(
            scope="§7.1.1-5", item="gate0b_before_phase1", status=Status.FAIL,
            reason="时序倒置：Phase 1 先于 Gate 0b 构建，该次求解结果作废并重跑",
            actual=f"gate0b={gate_0b_passed_at} >= phase1={phase1_first_build_at}",
            expected="gate0b_passed_at < phase1_first_build_at",
        )
    return CheckItem(
        scope="§7.1.1-5", item="gate0b_before_phase1", status=Status.PASS,
        reason="Gate 0b 通过时间早于 Phase 1 首次构建时间，时序正确",
        actual=f"gate0b={gate_0b_passed_at} < phase1={phase1_first_build_at}",
        expected="gate0b_passed_at < phase1_first_build_at",
    )


# --------------------------------------------------------------- 断言 6：CI


def assertion_6_config_zero_defaults(config_dir: Path) -> GateReport:
    """断言 6①：WP2 配置层不得为 ``adjustment_scope`` / ``q1`` / ``c_i`` 提供任何默认值。

    静态扫描 ``config/`` 下全部 ``*.json``，查找形如
    ``{"name": "q1_point", "default": 0.0}`` 的字段定义。
    命中即构建失败——否则开发者在 Gate 0a 前就能用模板绕过闸门试跑求解器，
    产生"伪结果"误导决策。
    """
    report = GateReport(
        gate="§7.1.1-6①",
        purpose="配置层零默认值静态扫描（防止用模板绕过 Gate 0a 试跑）",
    )
    violations: list[dict] = []

    for path in sorted(config_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.add(
                CheckItem(
                    scope="§7.1.1-6①", item=path.name, status=Status.FAIL,
                    reason=f"JSON 解析失败：{exc}",
                )
            )
            continue

        for node_path, node in _iter_nodes(data, path.name):
            if not isinstance(node, dict):
                continue
            name = node.get("name")
            if not isinstance(name, str) or not _is_watched(name):
                continue
            for slot in ("default", "template"):
                if node.get(slot) is not None:
                    violations.append(
                        {
                            "file": path.name,
                            "path": f"{node_path}.{slot}",
                            "field": name,
                            "value": node[slot],
                        }
                    )

    if violations:
        report.add(
            CheckItem(
                scope="§7.1.1-6①", item="zero_default_scan", status=Status.FAIL,
                reason=(
                    f"检出 {len(violations)} 处违禁默认值（字段 {NO_DEFAULT_FIELD_PREFIXES} "
                    "不得有 default/template）"
                ),
                actual=violations, expected=[],
            )
        )
    else:
        report.add(
            CheckItem(
                scope="§7.1.1-6①", item="zero_default_scan", status=Status.PASS,
                reason=(
                    f"扫描 {len(list(config_dir.glob('*.json')))} 个配置文件，"
                    "未发现被禁字段的 default/template"
                ),
                actual=0, expected=0,
            )
        )
    return report


def assert_wp4_build_allowed(gate_0b: GateReport) -> CheckItem:
    """断言 6②：Gate 0b 状态非 PASSED 时，WP4 任何模块不得被构建或执行。"""
    if gate_0b.status is Status.PASS:
        return CheckItem(
            scope="§7.1.1-6②", item="wp4_build_gate", status=Status.PASS,
            reason="Gate 0b 已通过，允许构建 / 执行 WP4 求解层",
            actual=gate_0b.status.value, expected="PASS",
        )
    return CheckItem(
        scope="§7.1.1-6②", item="wp4_build_gate", status=Status.BLOCKED,
        reason=(
            f"Gate 0b 状态为 {gate_0b.status.value}，WP4 求解层禁止构建或执行"
            "（构建脚本级硬门禁，非人工约定）"
        ),
        actual=gate_0b.status.value, expected="PASS",
    )


# ------------------------------------------------------------- 汇总入口


def evaluate_gate_0(
    registry: dict,
    config_dir: Path,
    selection: dict,
    gate_0b_passed_at: str | None = None,
    phase1_first_build_at: str | None = None,
) -> dict:
    """执行 Gate 0 全部判据，返回可直接序列化的总报告。"""
    gate_0a = check_gate_0a(registry, config_dir, selection)
    gate_0b = check_gate_0b(registry, config_dir)
    ci = assertion_6_config_zero_defaults(config_dir)
    ci.add(assert_wp4_build_allowed(gate_0b))
    seq = assertion_5_sequence(gate_0b_passed_at, phase1_first_build_at)

    return {
        "gate_0a": gate_0a.to_dict(),
        "gate_0b": gate_0b.to_dict(),
        "assertion_5_sequence": seq.to_dict(),
        "assertion_6_ci_gate": ci.to_dict(),
        "advisories": advisories(registry, config_dir),
        "summary": {
            "gate_0a": gate_0a.status.value,
            "gate_0b": gate_0b.status.value,
            "phase_0": (
                "RELEASED" if gate_0a.status is Status.PASS else "BLOCKED"
            ),
            "wp4_solver_layer": (
                "ALLOWED" if gate_0b.status is Status.PASS else "BLOCKED"
            ),
        },
    }
