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
2       未定态熔断：Phase 0 直接 BLOCKED                      :func:`check_phase0_inputs`
3       双闸门独立判定，放行清单不含 T00-10B                  :func:`check_gate_0a`
4       字段有效性机械化（hash 绑定 + 占位符黑名单）          :mod:`bidpricing.artifact`
5       Gate 0b 必须早于 WP4 Phase 1                          :func:`assertion_5_sequence`
6       CI 门禁：配置层零默认值 + 求解层硬门禁                :func:`assertion_6_config_zero_defaults`

Phase 0 输入门判两类东西
------------------------

断言 2 的落点 :func:`check_phase0_inputs` 判**两类项目级输入**，二者
性质相同、都属"求解启动前必须有、但开发期不需要"：

1. **项目级选择项取值**（``adjustment_scope``）—— :func:`check_selectable_option`
   的 ``phase_0`` 时点；
2. **项目级分类声明**（``project_classification_table``，T00-06 数据侧）
   —— :func:`check_project_input_artifacts`。

第 2 类是本版新增，修正的是一处与第 1 类**同型**的判定时点错误：早前把
「逐项可竞争性分类表」直接放在 Gate 0a 制品里，于是任一具体项目的清单数据
未就绪就阻塞解析器/配置层/判定层的开发。正确切法是——``T00-06`` 的
**规则书**（角色集合 + 缺省角色 + 例外信号 + 覆盖范围，跨项目复用）属 Gate 0a；
**项目级分类声明**（随项目而异）属 Phase 0 输入。2026-09-16 又把后者的判据
从「表里有没有行」改为「声明是否就绪」——清单内缺省即可竞争项、例外由清单
自带列机械命中，故不需逐行填表；而「例外为空」是**结论**，不能被误判为
「没做」（与 :func:`guard_representation` 的「未定态 = key 完全缺失」同型）。
======  ==================================================  ==========================

此外新增一条**选择项判据**（:func:`check_selectable_option`）：
``adjustment_scope`` 已是项目级选择项，其合法取值集合**依规则集而变**
（2013 只有 SEGMENT / 2024 二者皆可），因此不能再用全局枚举集校验——
否则「在 2013 项目上落值 FULL」会被判为合法。该判据同时把落值**来源与依据**
带进判定理由，构成决策审计快照。

判定时点：一次判据，两个时点
----------------------------
``check_selectable_option`` 接受 ``phase`` 参数，把「机制是否就绪」与
「取值是否已定」拆成两件事——这是对早前版本的修正：

* ``phase="gate_0a"``（默认）：只判**机制**。取值未定 **不阻塞** Gate 0a。
  理由：契约要求 WP3/WP4 **同时实现 FULL 与 SEGMENT 两条分支**，
  选择只决定「哪条分支生效」，不影响分支代码能否开工。
  把「还没选」当成 Gate 0a 阻塞项，等于用一个晚期决策卡住解析器与成本层开发。
* ``phase="phase_0"``：判**取值**。未定即 BLOCKED——这才是 §7.1.1 断言 2
  原文「未定态熔断：**Phase 0** 直接 BLOCKED」的落点（见
  :func:`check_phase0_inputs`）。

两种时点下，**配置冲突**（如 2013 项目落值 FULL）都直接 BLOCKED，
不因时点差异而放行。
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
from ..selection_options import SELECTABLE_OPTIONS, OptionResolution, resolve_option
from ..states import CheckItem, GateReport, Status

#: Gate 0a 放行的工作包（路线 §7.1.1 断言 3）
GATE_0A_RELEASES = ("WP1 数据层", "WP2 配置层", "WP3 判定层")

#: 明确**不在** Gate 0a 放行清单中的任务（依赖 WP1 的 T01-00B 合同解析产出）
GATE_0A_RELEASE_EXCLUSIONS = (
    ("T00-10B", "q^1 来源判定依赖 T01-00B 的合同条款解析结果，属 Gate 0b 前置"),
)

#: Gate 0b 要求的审批角色（断言：分级审批，每角色签署制品 hash 非空）
GATE_0B_APPROVAL_ROLES = ("合同", "造价", "法务", "项目经理")

#: ``contract_review.status`` 的合法取值。**词表是机制不是数据**（ADR-0002）——
#: 由本常量定义，不得依赖各项目制品自带一份（否则改词表就改了判据，
#: 且两份词表必然分叉）。制品中的 ``vocabulary`` 只作说明，须与本常量逐字一致。
CONTRACT_REVIEW_VOCAB: tuple[str, ...] = (
    "USER_DISCRETION",
    "REVIEWED_NO_EXTRA_CLAUSES",
    "REVIEWED_WITH_FINDINGS",
    "NOT_REVIEWED",
)

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


def _resolution_from_selection(
    rec: ArtifactRecord, selection: dict
) -> OptionResolution:
    """把 T00-08 的选择结果还原成一次选择项解析（含来源与依据）。"""
    option = SELECTABLE_OPTIONS[rec.key]
    rule_set_id = selection.get("rule_set_id")
    value = selection.get(rec.key)
    source = selection.get(f"{rec.key}_source")

    allowed = option.allowed_for(rule_set_id) if rule_set_id else tuple(rec.allowed)
    errors: tuple[str, ...] = ()
    if value is None:
        return OptionResolution(
            key=rec.key, value=None, source=source or "UNSELECTED",
            rule_set_id=rule_set_id, allowed=allowed,
        )
    if value not in allowed:
        errors = (
            f"取值 {value!r} 在规则集 {rule_set_id or '<未定>'} 下不可选；"
            f"合法取值仅 {list(allowed)}",
        )
    return OptionResolution(
        key=rec.key, value=None if errors else value, source=source or "UNKNOWN",
        rule_set_id=rule_set_id, allowed=allowed, errors=errors,
    )


def check_selectable_option(
    rec: ArtifactRecord, selection: dict, *, phase: str = "gate_0a"
) -> CheckItem:
    """选择项判据：取值必须**在该规则集的合法集合内**，且能说明来源。

    与 :func:`bidpricing.artifact.verify_enum` 的区别：

    * ``verify_enum`` 只对照注册表声明的**全局**取值集合——对
      ``adjustment_scope`` 而言是 ``{FULL, SEGMENT}`` 的并集，
      于是「在 2013 项目上落值 FULL」会被误判为合法；
    * 本函数按**规则集**取合法集合：2013 下只有 ``SEGMENT``，
      落值 ``FULL`` 属配置冲突，直接 BLOCKED（而不是静默改成 SEGMENT）——
      静默覆盖会让"系统建议值"与"人工落值"的差异从审计链上消失。

    参数 ``phase`` 决定**判定时点**（见模块 docstring）：

    * ``"gate_0a"``：取值未定 → **PASS**（机制就绪即可，不阻塞 WP1/WP2/WP3）；
    * ``"phase_0"``：取值未定 → **BLOCKED**（断言 2 熔断点）。

    配置冲突（``errors``）在两个时点下都 BLOCKED。
    """
    option = SELECTABLE_OPTIONS.get(rec.key)
    if option is None:  # 未登记的选择项退回通用枚举校验
        return verify_enum(rec, selection.get(rec.key), "T00-08 select_rule_set()")

    resolution = _resolution_from_selection(rec, selection)
    where = f"来源 {resolution.source}" + (
        f"，规则集 {resolution.rule_set_id}" if resolution.rule_set_id else ""
    )

    if resolution.value is None and not resolution.errors:
        if phase == "gate_0a":
            return CheckItem(
                scope="§7.1.1-1/2", item=rec.key, status=Status.PASS,
                reason=(
                    f"选择项机制就绪，取值未定：{option.title}。"
                    f"**取值未定不阻塞 Gate 0a**——下游被要求同时实现两条分支，"
                    f"选择只决定生效分支，不影响分支代码能否开工。"
                    f"未定态的熔断点在 **Phase 0 输入门**（§7.1.1 断言 2 原文即"
                    f"「Phase 0 直接 BLOCKED」）。该规则集下合法取值："
                    f"{list(resolution.allowed)}；"
                    f"落值通道：bidpricing options set --key {rec.key} --value ..."
                ),
                actual="<missing>", expected=list(resolution.allowed),
            )
        return CheckItem(
            scope="§7.1.1-2", item=rec.key, status=Status.BLOCKED,
            reason=(
                f"选择项未定（key 缺失）：{option.title}。该选择项**无默认值**，"
                f"Phase 0 求解启动前必须落值，否则直接判 BLOCKED。"
                f"该规则集下合法取值：{list(resolution.allowed)}；"
                f"落值通道：bidpricing options set --key {rec.key} --value ..."
            ),
            actual="<missing>", expected=list(resolution.allowed),
        )
    if resolution.errors:
        return CheckItem(
            scope="§7.1.1-1/2", item=rec.key, status=Status.BLOCKED,
            reason=resolution.errors[0],
            actual=selection.get(rec.key), expected=list(resolution.allowed),
        )
    return CheckItem(
        scope="§7.1.1-1/2", item=rec.key, status=Status.PASS,
        reason=(
            f"选择项已落值且在该规则集下合法（{where}"
            + (f"，依据：{resolution.rationale}" if resolution.rationale else "")
            + "）"
        ),
        actual=resolution.value, expected=list(resolution.allowed),
    )


def check_gate_0a(
    registry: dict,
    config_dir: Path,
    selection: dict,
) -> GateReport:
    """Gate 0a：Technical Interface & Rule-Set Frozen。

    机械判据：8 项全部通过（versioned 走 :func:`verify_versioned`，
    ``adjustment_scope`` 走 :func:`check_selectable_option` 的 ``gate_0a`` 时点——
    只判**机制就绪**，取值未定不阻塞）。

    注意：选择项的**取值**不在本闸门判定，而在 Phase 0 输入门
    （:func:`check_phase0_inputs`）。本闸门放行 WP1/WP2/WP3 —— 解析器、
    配置层与判定层都要求同时实现 FULL/SEGMENT 两条分支，不依赖取值。
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
        report.add(check_selectable_option(rec, selection, phase="gate_0a"))

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


# --------------------------------------------------------- Phase 0 输入门


def check_project_input_artifacts(registry: dict, config_dir: Path) -> list[CheckItem]:
    """项目级输入制品判据 —— 注册表 ``phase_0`` 段声明的数据侧制品。

    与 :func:`verify_versioned` 的区别：受控制品（Gate 0a/0b）判的是
    「契约是否冻结」，本判据判的是「**某个项目的数据是否已就位**」。
    前者跨项目复用，后者一项目一份。
    """
    specs = registry.get("phase_0") or {}
    if not specs:
        return [
            CheckItem(
                scope="§7.1.1-2", item="phase_0_input_registry", status=Status.BLOCKED,
                reason=(
                    "注册表未声明任何 Phase 0 项目级输入制品。这不是空真通过——"
                    "没有声明就没有判据，等于把项目数据的就绪性检查静默取消"
                ),
                actual=[], expected="phase_0 段至少声明一项",
            )
        ]
    return [
        _check_project_input(key, spec, config_dir) for key, spec in specs.items()
    ]


def _check_project_input(key: str, spec: dict, config_dir: Path) -> CheckItem:
    """项目级输入制品判据 —— **声明式就绪**，而非「表里有没有行」。

    2026-09-16 改。原判据是 ``len(rows) >= min_rows``，它把两件事混成一件：

    * 「**没做**分类」——没有任何声明，无从判定；
    * 「做了，且**结论是空的**」——本标段没有例外项，这是一个**结论**。

    前者的正确反应是 BLOCKED，后者是 PASS。用行数判定会把后者误判为前者，
    与 ``adjustment_scope`` 踩过的坑同型（把「没有」当成「没有做」）。

    现判据分三层：

    1. **标量字段**（``project_id`` / ``code_system`` / ``search_basis``）：key 缺失
       或空值 → BLOCKED（「没声明」）。
    2. **列表字段**（``covered_lists`` / ``external_constants`` / ``exceptions``）：
       key **必须存在**，但**取空列表是合法结论**——「已核查，无例外」。
       key 缺失与空列表在机器上必须可区分，这正是「未定态 = key 完全缺失」的用法。
    3. **逐条校验**：覆盖声明的缺省角色、例外行的字段与角色取值、
       汇总性外生常量的取值与依据。
    """
    scope = "§7.1.1-2"

    def bad(reason: str, actual=None, expected=None) -> CheckItem:
        return CheckItem(
            scope=scope, item=key, status=Status.BLOCKED,
            reason=reason, actual=actual, expected=expected,
        )

    rel = spec.get("artifact_path")
    if not rel:
        return bad(f"{key} 未声明 artifact_path，无法校验")
    path = config_dir / rel
    if not path.exists():
        return bad(f"项目级输入制品缺失：{rel}", actual=None, expected=rel)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return bad(f"JSON 解析失败：{exc}", actual=None, expected="合法 JSON")
    if not isinstance(payload, dict):
        return bad("顶层须为 JSON 对象", actual=type(payload).__name__, expected="object")

    scalar_fields = tuple(spec.get("required_scalar_fields") or ())
    list_fields = tuple(spec.get("required_list_fields") or ())
    allowed_roles = tuple(spec.get("allowed_roles") or ())
    allowed_lists = tuple(spec.get("allowed_source_lists") or ())

    # 1) 标量声明：缺失即为「没做」
    missing_scalars = [f for f in scalar_fields if not payload.get(f)]
    if missing_scalars:
        return bad(
            f"未作声明（key 缺失或为空）：{missing_scalars}。"
            "本判据判的是**声明是否就绪**——分部分项清单内缺省即可竞争项、"
            "例外由清单自带列（「其中:暂估价」列 / 甲供材）机械命中，"
            "所以不要求逐行填表；但项目身份（project_id）、"
            "计价机制（code_system，**不得由编码位数推断**）与"
            "例外检索方式（search_basis）必须显式给出",
            actual=missing_scalars, expected=f"非空：{list(scalar_fields)}",
        )

    # 2) 列表声明：key 必须存在；空列表是合法结论
    absent = [f for f in list_fields if f not in payload]
    if absent:
        return bad(
            f"缺少列表声明：{absent}。**key 缺失与空列表语义不同**——"
            "空列表表示「已核查、结论为空」，key 缺失表示「根本没声明」，"
            "后者没有判据（没有声明就没有检查，等于静默取消）",
            actual=absent, expected=f"key 须存在（取值可为 []）：{list(list_fields)}",
        )
    mistyped = [f for f in list_fields if not isinstance(payload.get(f), list)]
    if mistyped:
        return bad(
            f"以下字段须为列表：{mistyped}",
            actual={f: type(payload.get(f)).__name__ for f in mistyped},
            expected="list",
        )

    # 3) 计价机制声明合法
    allowed_cs = tuple(spec.get("allowed_code_systems") or ())
    code_system = payload.get("code_system")
    if allowed_cs and code_system not in allowed_cs:
        return bad(
            f"code_system={code_system!r} 不在 {list(allowed_cs)}",
            actual=code_system, expected=list(allowed_cs),
        )

    # 4) 覆盖声明：每张清单的**缺省角色**
    req_covered = tuple(spec.get("required_covered_list_fields") or ())
    covered = payload.get("covered_lists") or []
    if not covered:
        return bad(
            "covered_lists 为空：必须声明本标段覆盖了哪些清单、各自的**缺省角色**"
            "与判定依据。覆盖率不是可选项——X_opt 与 P_fixed 的完全划分依赖它",
            actual=0, expected=">= 1 项覆盖声明",
        )
    bad_covered: list[dict] = []
    for idx, entry in enumerate(covered):
        if not isinstance(entry, dict):
            bad_covered.append({"index": idx, "problems": ["非对象项"]})
            continue
        problems = [f"{f} 缺失" for f in req_covered if not entry.get(f)]
        sl = entry.get("source_list")
        if allowed_lists and sl not in allowed_lists:
            problems.append(f"source_list={sl!r} 不在 {list(allowed_lists)}")
        role = entry.get("default_role")
        if allowed_roles and role not in allowed_roles:
            problems.append(f"default_role={role!r} 不在 {list(allowed_roles)}")
        if problems:
            bad_covered.append({"index": idx, "source_list": sl, "problems": problems})
    if bad_covered:
        return bad(
            f"{len(bad_covered)} 项覆盖声明不合格（共 {len(covered)} 项）",
            actual=bad_covered[:10],
            expected=(
                f"每项含 {list(req_covered)}；"
                f"source_list ∈ {list(allowed_lists)}；default_role ∈ {list(allowed_roles)}"
            ),
        )

    # 5) 例外行（可为 0 条，但每一行都要有依据）
    req_row = tuple(spec.get("required_exception_row_fields") or ())
    exceptions = payload.get("exceptions") or []
    bad_rows: list[dict] = []
    for idx, row in enumerate(exceptions):
        if not isinstance(row, dict):
            bad_rows.append({"index": idx, "problems": ["非对象行"]})
            continue
        problems = [f"{f} 缺失" for f in req_row if not row.get(f)]
        role = row.get("pricing_role")
        if allowed_roles and role and role not in allowed_roles:
            problems.append(f"pricing_role={role!r} 不在 {list(allowed_roles)}")
        if problems:
            bad_rows.append(
                {"index": idx, "item_id": row.get("item_id"), "problems": problems}
            )
    if bad_rows:
        return bad(
            f"{len(bad_rows)} 条例外行不合格（共 {len(exceptions)} 条）",
            actual=bad_rows[:10],
            expected=f"每行含 {list(req_row)}；pricing_role ∈ {list(allowed_roles)}",
        )

    # 6) 汇总性外生常量声明（可为 0 条）
    req_ext = tuple(spec.get("required_external_constant_fields") or ())
    externals = payload.get("external_constants") or []
    bad_ext: list[dict] = []
    for idx, entry in enumerate(externals):
        if not isinstance(entry, dict):
            bad_ext.append({"index": idx, "problems": ["非对象项"]})
            continue
        problems = [f"{f} 缺失" for f in req_ext if not entry.get(f)]
        treatment = entry.get("treatment")
        if allowed_roles and treatment and treatment not in allowed_roles:
            problems.append(f"treatment={treatment!r} 不在 {list(allowed_roles)}")
        if problems:
            bad_ext.append({"index": idx, "fee": entry.get("fee"), "problems": problems})
    if bad_ext:
        return bad(
            f"{len(bad_ext)} 条汇总性外生常量声明不合格（共 {len(externals)} 条）",
            actual=bad_ext[:10],
            expected=f"每项含 {list(req_ext)}；treatment ∈ {list(allowed_roles)}",
        )

    return CheckItem(
        scope=scope, item=key, status=Status.PASS,
        reason=(
            "分类声明已就位：覆盖 "
            f"{len(covered)} 张清单（缺省角色已声明）／例外 {len(exceptions)} 条／"
            f"汇总性外生常量 {len(externals)} 项。"
            "例外与外部常量为 0 是**结论**而非缺省——key 存在且为 [] 与 key 缺失"
            "在机器上可区分"
        ),
        actual={"covered_lists": len(covered), "exceptions": len(exceptions),
                "external_constants": len(externals)},
        expected="三项声明齐备（后两项计数可为 0）",
    )


def check_phase0_inputs(
    registry: dict, selection: dict, config_dir: Path
) -> GateReport:
    """Phase 0 输入门 —— §7.1.1 断言 2「未定态熔断：Phase 0 直接 BLOCKED」的落点。

    为什么单独设这一道门，而不是把「未落值」挂在 Gate 0a
    ----------------------------------------------------
    项目级输入（选择项取值、分类声明）有一个共同性质：

    * **开发期不需要它** —— 契约要求 WP3 / WP4 同时实现 FULL 与 SEGMENT
      两条分支，分类声明则是数据不是机制；两者都改变不了"代码该不该写"；
    * **求解期必须有它** —— 没选 ``adjustment_scope`` 就跑求解器，等于在该
      误差区间内做优化（两种口径下最优报价结构相反、利润差约 4.5 倍）；
      没有分类声明则 ``X_opt`` 与 ``P_fixed`` 的划分无从生成，
      总价恒等式不闭合。

    把它挂在 Gate 0a 会同时造成两个后果：解析器被晚期决策无故阻塞，
    以及「机制就绪」与「数据就绪」两类不同性质的失败被混在同一个闸门里
    无法区分归因。本函数把后者独立出来，**判定时点与消耗时点对齐**。
    """
    report = GateReport(
        gate="Phase 0 输入门",
        purpose=(
            "求解层启动前，项目级选择项取值与项目级输入数据必须均已就位"
        ),
    )

    enum_recs = [r for r in parse_records(registry, "gate_0a") if r.is_enum]
    for rec in enum_recs:
        report.add(check_selectable_option(rec, selection, phase="phase_0"))

    if not enum_recs:
        report.add(
            CheckItem(
                scope="§7.1.1-2", item="selectable_option_registry", status=Status.PASS,
                reason="注册表未声明选择项，本门空真通过（vacuous pass）",
                actual=0, expected=">= 0",
            )
        )

    for item in check_project_input_artifacts(registry, config_dir):
        report.add(item)

    return report


# ----------------------------------------------------------------- Gate 0b


def _check_contract_review(registry: dict, config_dir: Path) -> CheckItem:
    """Gate 0b 对 ``contract_ruleset_version`` 的**业务层**判据。

    hash 只能证明「文件没改」，证明不了「合同条款已核对」——两者的差别正是
    路线隐藏依赖 19 要防的失效模式。故本项额外要求规则卡携带 ``contract_review``
    并给出可复核的核对结论。
    """
    spec = (registry.get("gate_0b") or {}).get("contract_ruleset_version") or {}
    rel = spec.get("artifact_path")
    target = config_dir / str(rel or "")
    if not rel or not target.exists():
        return CheckItem(
            scope="§7.1-Gate0b", item="contract_review", status=Status.BLOCKED,
            reason=f"规则卡不存在（artifact_path={rel!r}），contract_review 无从核对",
            actual=None, expected="pricing_rule_card.json",
        )
    try:
        card = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return CheckItem(
            scope="§7.1-Gate0b", item="contract_review", status=Status.FAIL,
            reason=f"规则卡解析失败：{exc}",
        )

    cr = card.get("contract_review")
    if not isinstance(cr, dict):
        return CheckItem(
            scope="§7.1-Gate0b", item="contract_review", status=Status.BLOCKED,
            reason=(
                "规则卡未声明 contract_review——合同条款核对结论缺失。"
                "只校验 hash 等于用「文件没改」冒充「条款已核对」"
            ),
            actual=None, expected=["contract_review"],
        )

    declared_vocab = cr.get("vocabulary")
    if isinstance(declared_vocab, dict) and set(declared_vocab) != set(CONTRACT_REVIEW_VOCAB):
        return CheckItem(
            scope="§7.1-Gate0b", item="contract_review", status=Status.FAIL,
            reason=(
                f"制品自带词表与机制层词表不一致：制品 {sorted(declared_vocab)} "
                f"vs 机制 {sorted(CONTRACT_REVIEW_VOCAB)}——两处各说各话"
            ),
            actual=sorted(declared_vocab), expected=sorted(CONTRACT_REVIEW_VOCAB),
        )

    status_v = cr.get("status")
    if status_v not in CONTRACT_REVIEW_VOCAB:
        return CheckItem(
            scope="§7.1-Gate0b", item="contract_review", status=Status.FAIL,
            reason=f"contract_review.status={status_v!r} 不在词表内",
            actual=status_v, expected=list(CONTRACT_REVIEW_VOCAB),
        )
    if status_v == "NOT_REVIEWED":
        return CheckItem(
            scope="§7.1-Gate0b", item="contract_review", status=Status.BLOCKED,
            reason="合同条款尚未核对（NOT_REVIEWED）——Gate 0b 不得通过",
        )
    if not cr.get("declared_by"):
        return CheckItem(
            scope="§7.1-Gate0b", item="contract_review", status=Status.BLOCKED,
            reason="contract_review 未署名（declared_by 缺失）——核对结论无责任人",
        )
    if status_v == "REVIEWED_WITH_FINDINGS" and not cr.get("findings"):
        return CheckItem(
            scope="§7.1-Gate0b", item="contract_review", status=Status.FAIL,
            reason="声明「已核对且有发现」却未列出 findings——结论不可复核",
        )

    agent = cr.get("agent_assertion", "NONE")
    tail = "（由用户承担结论，Agent 未代为断言）" if agent == "NONE" else ""
    return CheckItem(
        scope="§7.1-Gate0b", item="contract_review", status=Status.PASS,
        reason=f"合同条款核对结论合法：{status_v}，declared_by={cr['declared_by']}{tail}",
        actual=status_v, expected=list(CONTRACT_REVIEW_VOCAB),
    )


def _check_approvals(registry: dict, config_dir: Path) -> list[CheckItem]:
    """分级审批（路线 §7.1 Gate 0b + 隐藏依赖 19）。

    三档语义：

    * **已签署** —— 条目含 ``by``，且签署了该角色的**全部责任制品**，
      且每条签名 hash 与制品现值一致（制品被改动 → 签名自动作废）。
    * **NOT_COVERED（WARN）** —— 显式声明本角色无人承担并给出理由。
      ``signed={}`` 是「没人说过」，NOT_COVERED 是「说了没人负责」——
      前者是假审批（BLOCKED），后者是真话（不阻塞，但为风险敞口）。
    * **其余（BLOCKED）** —— 缺条目 / 无 ``by`` / 无制品 / 签了未声明制品 /
      hash 为空或失配。签署对象必须指向已声明制品：否则签一个与任何制品
      都无关的字符串，与打一个勾没有区别。
    """
    raw = registry.get("gate_0b", {}).get("approvals")
    if not isinstance(raw, dict):
        return [CheckItem(
            scope="§7.1-Gate0b", item="approvals", status=Status.BLOCKED,
            reason="注册表未声明 approvals 块",
        )]

    roles = tuple(raw.get("roles") or GATE_0B_APPROVAL_ROLES)
    resp = raw.get("responsibility") or {}
    signed = raw.get("signed") or {}

    recs = [r for r in parse_records(registry, "gate_0b") if r.kind != "approvals"]
    live = {r.artifact_path: r.hash for r in recs if r.artifact_path}

    ok_roles: list[str] = []
    not_covered: list[str] = []
    problems: list[str] = []

    for role in roles:
        entry = signed.get(role)
        if not isinstance(entry, dict) or not entry:
            problems.append(f"{role}：未签署")
            continue
        if entry.get("status") == "NOT_COVERED":
            if entry.get("reason"):
                not_covered.append(role)
            else:
                problems.append(
                    f"{role}：声明 NOT_COVERED 却未给理由——"
                    "「本角色无人负责」本身是断言，须写明原因"
                )
            continue

        role_problems: list[str] = []
        by = entry.get("by")
        arts = entry.get("artifacts")
        if not by:
            role_problems.append(f"{role}：未署名（by 缺失）")
        if not isinstance(arts, dict) or not arts:
            role_problems.append(f"{role}：未签署任何制品 hash")
        else:
            need = list((resp.get(role) or {}).get("artifacts") or [])
            lack = [a for a in need if a not in arts]
            if lack:
                role_problems.append(
                    f"{role}：未签署责任制品 {lack}——"
                    "签非责任制品与打一个勾无异"
                )
            for rel, sig in arts.items():
                if rel not in live:
                    role_problems.append(f"{role}：签署了未声明制品 {rel}")
                elif not sig:
                    role_problems.append(f"{role}：{rel} 的签名 hash 为空")
                elif sig != live.get(rel):
                    role_problems.append(
                        f"{role}：{rel} 的签名已失效（签 {str(sig)[:19]}，"
                        f"现值 {str(live[rel])[:19]}）——制品在签署后被改动，须重签"
                    )
        if role_problems:
            problems.extend(role_problems)
        else:
            ok_roles.append(role)

    if problems:
        return [CheckItem(
            scope="§7.1-Gate0b", item="approvals", status=Status.BLOCKED,
            reason=(
                "审批未到位：" + "；".join(problems)
                + "。v3.2 的单一布尔位可被一人勾选通过，业务口径并未真正冻结"
            ),
            actual={"signed": sorted(signed)}, expected=list(roles),
        )]
    if not_covered:
        return [CheckItem(
            scope="§7.1-Gate0b", item="approvals", status=Status.WARN,
            reason=(
                f"{len(ok_roles)}/{len(roles)} 个角色已签署各自责任制品；"
                f"{'、'.join(not_covered)} 显式声明无人承担——"
                "这是真话不是假审批，不阻塞 WP4，但构成风险敞口"
            ),
            actual={"signed": sorted(ok_roles), "not_covered": sorted(not_covered)},
            expected=list(roles),
        )]
    return [CheckItem(
        scope="§7.1-Gate0b", item="approvals", status=Status.PASS,
        reason=(
            f"{len(roles)} 个角色均已签署各自责任制品，且签名 hash 与制品现值一致"
            "（逐角色签署，非一次签署覆盖多角色）"
        ),
        actual=list(roles), expected=list(roles),
    )]


def check_gate_0b(registry: dict, config_dir: Path) -> GateReport:
    """Gate 0b：Business Caliber & Compliance Frozen。

    机械判据：5 项 versioned 制品齐备 ∧ 规则卡 contract_review 结论合法
    ∧ 分级审批 4 角色每角色签署**其责任制品**的 hash。

    v3.2 仅要求 ``all_required_approvals = true``，可被单人勾选通过；
    v3.2.1 改为分角色签署，但只校验「hash 非空」——签一个与制品无关的字符串
    仍可过关。本版补上「签署对象必须是已声明制品且覆盖该角色责任制品」。
    """
    report = GateReport(
        gate="Gate 0b",
        purpose="业务口径与合规依据冻结 → 阻塞 WP4 求解层，不阻塞 WP1/WP2/WP3",
    )

    for rec in parse_records(registry, "gate_0b"):
        if rec.kind == "approvals":
            continue
        report.add(verify_versioned(rec, config_dir))

    report.add(_check_contract_review(registry, config_dir))
    for item in _check_approvals(registry, config_dir):
        report.add(item)

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
    """执行 Gate 0 全部判据，返回可直接序列化的总报告。

    ``phase_0`` 由**两个条件共同**决定：Gate 0a 通过（技术接口冻结）
    **且** Phase 0 输入门通过（选择项取值已定 + 项目级输入数据已就位）。
    二者缺一即 BLOCKED。
    """
    gate_0a = check_gate_0a(registry, config_dir, selection)
    gate_0b = check_gate_0b(registry, config_dir)
    phase0 = check_phase0_inputs(registry, selection, config_dir)
    ci = assertion_6_config_zero_defaults(config_dir)
    ci.add(assert_wp4_build_allowed(gate_0b))
    seq = assertion_5_sequence(gate_0b_passed_at, phase1_first_build_at)

    phase_0_released = (
        gate_0a.status is Status.PASS and phase0.status is Status.PASS
    )
    return {
        "gate_0a": gate_0a.to_dict(),
        "gate_0b": gate_0b.to_dict(),
        "phase_0_input_gate": phase0.to_dict(),
        "assertion_5_sequence": seq.to_dict(),
        "assertion_6_ci_gate": ci.to_dict(),
        "advisories": advisories(registry, config_dir),
        "summary": {
            "gate_0a": gate_0a.status.value,
            "gate_0b": gate_0b.status.value,
            "phase_0_input_gate": phase0.status.value,
            "phase_0": "RELEASED" if phase_0_released else "BLOCKED",
            "wp4_solver_layer": (
                "ALLOWED" if gate_0b.status is Status.PASS else "BLOCKED"
            ),
        },
    }
