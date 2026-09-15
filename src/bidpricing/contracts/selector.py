"""T00-08 规则集选择器 —— 路线的**起点任务**（Depends 为空）。

任务定义（《实施路线 v3.2.1》WP0 任务表）
-----------------------------------------
输入 9 项：
    ``tender_document_date`` / ``contract_date`` / ``standard_version_declared`` /
    ``region`` / ``project_type`` / ``funding_type`` /
    ``tender_document_override`` / ``contract_override``
输出：``rule_set_id`` / ``effective_date`` / ``legal_basis`` /
    ``precedence_chain`` / ``adjustment_scope``

判定规则
--------
* 默认指向 **GB/T 50500-2024 §8.9**；仅当输入证明属**过渡项目**
  （2025-09-01 前发布招标文件或已签合同）**或合同另有约定**时回落 2013。
* **规则版本无法判定时输出 BLOCKED，禁止默认取任一侧。**
* 优先级链：``Contract > Tender > Regional > Standard``。

关键实现选择（断言 1 的落地方式）
---------------------------------
``adjustment_scope`` 未定时，本模块**直接不输出该 key**，
而不是写入 ``None`` / ``"未定"`` / ``"UNDETERMINED"`` 等字符串——
后者会被「非空即通过」的判据当成已冻结，从而绕过 §7.1.1 的熔断点。

``adjustment_scope`` 的取值不再是"一次性裁决的常量"，而是一个
**项目级选择项**，由 :mod:`bidpricing.selection_options` 统一登记、校验与留痕：

* GB/T 50500-2024 —— ``FULL`` / ``SEGMENT`` 二选一（无默认值）；
* GB 50500-2013 —— 仅 ``SEGMENT``（§9.6.2 明文分段，**不可选 FULL**，
  在 2013 项目上出现 ``FULL`` 会被判为与规则集冲突而 BLOCKED，
  而不是被静默覆盖——静默覆盖会让"系统的建议值"与"人工落值"的差异消失于审计链）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..paths import PROJECT_SELECTION, config_dir
from ..selection_options import (
    SELECTABLE_OPTIONS,
    SOURCE_CLI,
    SOURCE_RULE_SET,
    resolve_option,
)
from ..states import Status
from .rule_sets.base import RuleSet
from .rule_sets.gb50500_2013 import GB50500_2013_RuleSet
from .rule_sets.gbt50500_2024 import GBT50500_2024_RuleSet

#: GB/T 50500-2024 施行日 / GB 50500-2013 废止日
CUTOVER_DATE = date(2025, 9, 1)

#: 规则优先级链（路线 T00-07）
PRECEDENCE_CHAIN = ("Contract", "Tender", "Regional", "Standard")

_RS_2013 = GB50500_2013_RuleSet()
_RS_2024 = GBT50500_2024_RuleSet()

_ALIASES_2013 = ("gb50500-2013", "gb 50500-2013", "gb50500_2013", "2013")
_ALIASES_2024 = (
    "gb/t50500-2024", "gb/t 50500-2024", "gbt50500-2024",
    "gb50500-2024", "gb 50500-2024", "2024",
)


def _normalize_standard(text: str | None) -> str | None:
    if text is None:
        return None
    t = str(text).strip().lower()
    if not t:
        return None
    if t in _ALIASES_2013:
        return "GB50500-2013"
    if t in _ALIASES_2024:
        return "GB/T50500-2024"
    return None


def _parse_date(text: str | date | None) -> date | None:
    if text is None:
        return None
    if isinstance(text, date):
        return text
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        return None


def _ruleset_for(rule_set_id: str) -> RuleSet:
    return _RS_2013 if rule_set_id == "GB50500-2013" else _RS_2024


@dataclass
class RuleSetSelection:
    """选择结果。``to_dict()`` 是写入 Gate 0 注册表的正式口径。"""

    status: Status
    rule_set: RuleSet | None
    effective_date: str | None
    legal_basis: str | None
    precedence_chain: tuple[str, ...]
    adjustment_scope: str | None
    adjustment_scope_source: str | None = None
    decisions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def rule_set_id(self) -> str | None:
        return self.rule_set.rule_set_id if self.rule_set else None

    @property
    def scope_allowed(self) -> tuple[str, ...]:
        """当前规则集下该选择项的合法取值集合。"""
        return SELECTABLE_OPTIONS["adjustment_scope"].allowed_for(self.rule_set_id)

    @property
    def scope_is_frozen(self) -> bool:
        return self.adjustment_scope in self.scope_allowed

    def to_dict(self) -> dict:
        payload: dict = {
            "status": self.status.value,
            "rule_set_id": self.rule_set_id,
            "standard_code": self.rule_set.standard_code if self.rule_set else None,
            "effective_date": self.effective_date,
            "legal_basis": self.legal_basis,
            "precedence_chain": list(self.precedence_chain),
            "decisions": list(self.decisions),
            "blockers": list(self.blockers),
        }
        # §7.1.1 断言 1：未定态 = key 完全缺失。
        if self.adjustment_scope is not None:
            payload["adjustment_scope"] = self.adjustment_scope
            if self.adjustment_scope_source:
                # 来源另立 key，不污染取值本身——取值必须恰好是枚举字面量
                payload["adjustment_scope_source"] = self.adjustment_scope_source
        return payload


def _default_selection_path() -> Path:
    return config_dir() / PROJECT_SELECTION


def select_rule_set(
    *,
    tender_document_date: str | date | None = None,
    contract_date: str | date | None = None,
    standard_version_declared: str | None = None,
    region: str | None = None,
    project_type: str | None = None,
    funding_type: str | None = None,
    tender_document_override: str | None = None,
    contract_override: str | None = None,
    adjustment_scope_declared: str | None = None,
    selection_file: str | Path | None = None,
    use_project_selection: bool = True,
) -> RuleSetSelection:
    """机械判定项目适用的规则集，并解析项目级选择项。

    参数
    ----
    adjustment_scope_declared
        **不属于路线原始 9 项输入**，是选择项的临时落值通道（最高优先级）。
        未提供时回落到项目选择项文件；两者都没有且规则集为 2024 时，
        输出中将**不含** ``adjustment_scope`` key（未定态）。
    selection_file
        项目选择项落值文件，默认 ``config/project_selection.json``。
        文件不存在或其中该选择项未落值，等价于"未选择"。
    use_project_selection
        置 ``False`` 可忽略落值文件（仅用于单测构造"未选择"场景）。
    """
    decisions: list[str] = []
    blockers: list[str] = []

    # ---------------------------------------------------------- 1. 优先级解析
    chosen: str | None = None
    source = ""
    if contract_override:
        chosen = _normalize_standard(contract_override)
        source = "Contract（合同约定，优先级最高）"
        decisions.append(f"命中 contract_override={contract_override!r} → {chosen}")
    elif tender_document_override:
        chosen = _normalize_standard(tender_document_override)
        source = "Tender（招标文件约定）"
        decisions.append(
            f"命中 tender_document_override={tender_document_override!r} → {chosen}"
        )
    elif standard_version_declared:
        chosen = _normalize_standard(standard_version_declared)
        source = "Standard（声明的规范版本）"
        decisions.append(
            f"命中 standard_version_declared={standard_version_declared!r} → {chosen}"
        )
    else:
        decisions.append("未提供显式规范版本约定，转入日期推断")

    td = _parse_date(tender_document_date)
    cd = _parse_date(contract_date)
    pre_cutover = (td is not None and td < CUTOVER_DATE) or (
        cd is not None and cd < CUTOVER_DATE
    )
    if pre_cutover:
        decisions.append(
            f"检测到过渡项目特征（招标文件 {td} / 合同 {cd} 早于 {CUTOVER_DATE}）"
        )

    # ---------------------------------------------------- 2. 显式约定与日期互证
    if source and chosen == "GB50500-2013":
        if not pre_cutover:
            if td is None and cd is None:
                blockers.append(
                    "声明沿用 GB 50500-2013，但未提供招标文件发布日期与合同签订日期，"
                    "无法验证过渡项目资格（§8.3 校正一要求二者同时成立）"
                )
            else:
                blockers.append(
                    f"声明沿用 GB 50500-2013，但日期（招标文件 {td} / 合同 {cd}）"
                    f"均不早于 {CUTOVER_DATE}，与过渡项目定义矛盾，需人工裁定"
                )
        else:
            decisions.append("过渡项目资格与 2013 版声明互证通过")
    elif chosen is None and source:
        blockers.append(
            f"来源为「{source}」但规范版本无法识别，"
            "禁止默认取任一侧（T00-08 完成判据）"
        )
    elif chosen is None and not source:
        # 无显式声明，仅靠日期
        if pre_cutover:
            blockers.append(
                "日期指向过渡项目窗口，但缺少招标文件/合同对规范版本的约定，"
                "按 §8.3 校正一「两个条件同时成立」的口径无法判定；"
                "请补充 standard_version_declared 或 override"
            )
        else:
            chosen = "GB/T50500-2024"
            decisions.append(
                f"无过渡项目特征，按 GB/T 50500-2024 自 {CUTOVER_DATE} 起施行的默认口径判定"
            )

    # -------------------------------------------------------- 3. 组装规则集对象
    rule_set = _ruleset_for(chosen) if chosen else None

    # 记录非决定性输入，避免"看起来用了但实际没用"
    for label, value in (
        ("region", region), ("project_type", project_type), ("funding_type", funding_type)
    ):
        if value:
            decisions.append(f"输入 {label}={value!r} 已记录；当前规则表未定义其分支作用（待 T00-01 补充）")

    # -------------------------------------------------------- 4. 选择项解析
    adjustment_scope: str | None = None
    adjustment_scope_source: str | None = None
    if rule_set is not None:
        if use_project_selection:
            selection_path = (
                Path(selection_file) if selection_file is not None
                else _default_selection_path()
            )
        else:
            selection_path = None

        resolution = resolve_option(
            "adjustment_scope",
            rule_set.rule_set_id,
            cli_value=adjustment_scope_declared,
            path=selection_path,
        )

        if resolution.errors:
            blockers.extend(resolution.errors)
        elif resolution.value is None:
            blockers.append(
                "选择项 adjustment_scope 未定：GB/T 50500-2024 §8.9 未明说是否分段，"
                "FULL 与 SEGMENT 两种解读下最优报价结构相反、利润差约 4.5 倍。"
                "该选择项**无默认值**，未落值前按 §7.1.1 断言 2 直接判 BLOCKED"
                "（落值通道：bidpricing options set --key adjustment_scope "
                f"--value {{{'|'.join(resolution.allowed)}}} --rule-set "
                f"{rule_set.rule_set_id}）"
            )
        else:
            adjustment_scope = resolution.value
            adjustment_scope_source = resolution.source
            decisions.append(
                f"选择项 adjustment_scope={adjustment_scope}"
                f"（来源：{resolution.source}；该规则集合法取值："
                f"{list(resolution.allowed)}）"
            )
            if resolution.source == SOURCE_RULE_SET:
                decisions.append(
                    f"{rule_set.standard_code} 已由规范明文确定该口径，"
                    "非人工可选项——因此不构成未证假设"
                )
            elif resolution.source == SOURCE_CLI:
                decisions.append(
                    "本次取值来自命令行（临时）。正式口径应写入 "
                    "config/project_selection.json 以留下决策依据快照"
                    "（bidpricing options set）"
                )
            if resolution.rationale:
                decisions.append(f"选择依据：{resolution.rationale}")
            if resolution.selected_at:
                decisions.append(
                    f"落值时间 {resolution.selected_at}"
                    + (f"，落值人 {resolution.actor}" if resolution.actor else "")
                )

    status = Status.BLOCKED if blockers else Status.PASS

    return RuleSetSelection(
        status=status,
        rule_set=rule_set,
        effective_date=rule_set.effective_date if rule_set else None,
        legal_basis=rule_set.legal_basis if rule_set else None,
        precedence_chain=PRECEDENCE_CHAIN,
        adjustment_scope=adjustment_scope,
        adjustment_scope_source=adjustment_scope_source,
        decisions=decisions,
        blockers=blockers,
    )


# --------------------------------------------------------------------- 自检

def ruleset_self_test(rho_probe: float = 0.01, delta: float = 1e-9) -> dict:
    """T00-07/T00-08 的强制自检：两套 RuleSet 必须能被指纹区分。

    路线原文：「同一输入下两套 RuleSet 输出不得仅因条文号不同而相同」。

    **指纹是作用域相关的**，因此必须同时报告 2024 的两个作用域：

    * ``FULL``     —— 跳降 ``≈ -1.15·ρ⁺``，与 2013 分离度显著 → 判据可用于区分实现；
    * ``SEGMENT``  —— 跳变量 ``≈ 0``，**与 2013 同形** → 数值指纹在此作用域下**退化**，
      不能再用于区分两套实现。这不是实现缺陷，而是所选口径的直接后果：
      SEGMENT 的结算曲线本就与 2013 同形。

    退化时区分依据退回条款覆盖（§8.2/§8.9 双路径 vs §9.6.2 单条款）与
    两版代码路径的独立实现，自检把这一点作为**遗留项**显式暴露，
    而不是让"自检通过"掩盖"此刻指纹已无鉴别力"。

    返回 dict，含两套规则集在各作用域下的实测跳变量、是否通过、以及遗留项。
    """
    jump_2013 = _RS_2013.fingerprint(rho_probe=rho_probe, delta=delta)
    jump_2024_full = _RS_2024.fingerprint(
        rho_probe=rho_probe, delta=delta, scope="FULL"
    )
    jump_2024_segment = _RS_2024.fingerprint(
        rho_probe=rho_probe, delta=delta, scope="SEGMENT"
    )

    expected_2024 = -1.15 * rho_probe
    tol = 1e-6

    checks = {
        "rs_2013_fingerprint": {
            "scope": "SEGMENT（§9.6.2 明文，非可选项）",
            "actual": jump_2013,
            "expected_abs_max": tol,
            "passed": abs(jump_2013) <= tol,
            "meaning": "分段累加 → 阈值处连续，跳变量 ≈ 0",
        },
        "rs_2024_fingerprint_FULL": {
            "scope": "FULL",
            "actual": jump_2024_full,
            "expected": expected_2024,
            "tolerance": tol,
            "passed": abs(jump_2024_full - expected_2024) <= tol,
            "meaning": "调整单价本身 → 阈值处跳降 ≈ -1.15·ρ⁺",
        },
        "separation_FULL": {
            "scope": "FULL",
            "actual": abs(jump_2024_full - jump_2013),
            "expected_min": 0.5 * abs(expected_2024),
            "passed": abs(jump_2024_full - jump_2013) >= 0.5 * abs(expected_2024),
            "meaning": "两套实现必须可区分，否则说明公式被复制",
        },
        "rs_2024_fingerprint_SEGMENT": {
            "scope": "SEGMENT",
            "actual": jump_2024_segment,
            "expected_abs_max": tol,
            "passed": abs(jump_2024_segment) <= tol,
            "degenerate": True,
            "meaning": (
                "该作用域下 2024 与 2013 同形（跳变量均 ≈ 0）："
                "指纹在此退化，失去对两套实现的鉴别力"
            ),
        },
    }

    advisories: list[str] = []
    if abs(jump_2024_segment) <= tol:
        advisories.append(
            "判据退化：选择 SEGMENT 时，GB/T 50500-2024 的 r_eff 曲线与 GB 50500-2013 同形"
            "（阈值处均连续）：**数值指纹不再能证明两套实现相互独立**。"
            "此时区分依据为条款覆盖（2024 拆为 §8.2 清单缺陷 / §8.9 工程变更两条路径，"
            "2013 为 §9.6.2 单条款）与两版代码路径的独立实现，"
            "不得以『指纹通过』替代该人工审查。"
        )
    if abs(rho_probe) < 1e-12:
        advisories.append(
            "判据退化：rho_probe=0 时两版指纹完全重合（已登记的退化条件）——"
            "自检必须使用非零探针值。"
        )

    return {
        "rho_probe": rho_probe,
        "delta": delta,
        "checks": checks,
        "advisories": advisories,
        "passed": all(c["passed"] for c in checks.values()),
    }
