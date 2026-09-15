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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..states import Status
from .rule_sets.base import RuleSet
from .rule_sets.gb50500_2013 import GB50500_2013_RuleSet
from .rule_sets.gbt50500_2024 import GBT50500_2024_RuleSet, VALID_SCOPES

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
    decisions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def rule_set_id(self) -> str | None:
        return self.rule_set.rule_set_id if self.rule_set else None

    @property
    def scope_is_frozen(self) -> bool:
        return self.adjustment_scope in VALID_SCOPES

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
        return payload


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
) -> RuleSetSelection:
    """机械判定项目适用的规则集。

    参数
    ----
    adjustment_scope_declared
        **不属于路线原始 9 项输入**，是 T00-01 的落值通道：合同/招标文件对
        §8.9「是否分段」的解读结论。未提供且规则集为 2024 时，
        输出中将**不含** ``adjustment_scope`` key（未定态）。
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

    # ------------------------------------------------------------ 4. 作用域冻结
    adjustment_scope: str | None = None
    if rule_set is not None:
        if rule_set.scope_ambiguous:
            if adjustment_scope_declared is not None:
                if adjustment_scope_declared in VALID_SCOPES:
                    adjustment_scope = adjustment_scope_declared
                    decisions.append(
                        f"adjustment_scope 取自 T00-01 落值：{adjustment_scope}"
                    )
                else:
                    blockers.append(
                        f"adjustment_scope_declared={adjustment_scope_declared!r} 非合法枚举"
                        f"（只允许 {list(VALID_SCOPES)}）"
                    )
            else:
                blockers.append(
                    "adjustment_scope 未定：GB/T 50500-2024 §8.9 未明说是否分段，"
                    "FULL 与 SEGMENT 下最优报价结构相反、利润差约 4.5 倍。"
                    "按 §7.1.1 断言 2，Phase 0 直接判 BLOCKED"
                )
        else:
            adjustment_scope = "SEGMENT"
            decisions.append(
                "adjustment_scope=SEGMENT 由 GB 50500-2013 §9.6.2 明文规定（分段累加），"
                "非歧义、无需人工裁定"
            )
            if adjustment_scope_declared and adjustment_scope_declared != "SEGMENT":
                decisions.append(
                    f"注意：声明的 adjustment_scope={adjustment_scope_declared!r} "
                    "被规范明文覆盖为 SEGMENT（规范优先于约定解读）"
                )

    status = Status.BLOCKED if blockers else Status.PASS

    return RuleSetSelection(
        status=status,
        rule_set=rule_set,
        effective_date=rule_set.effective_date if rule_set else None,
        legal_basis=rule_set.legal_basis if rule_set else None,
        precedence_chain=PRECEDENCE_CHAIN,
        adjustment_scope=adjustment_scope,
        decisions=decisions,
        blockers=blockers,
    )


# --------------------------------------------------------------------- 自检

def ruleset_self_test(rho_probe: float = 0.01, delta: float = 1e-9) -> dict:
    """T00-07/T00-08 的强制自检：两套 RuleSet 必须能被指纹区分。

    路线原文：「同一输入下两套 RuleSet 输出不得仅因条文号不同而相同」。

    返回 dict，含两套规则集的实测跳变量与期望量级、以及是否通过。
    """
    jump_2013 = _RS_2013.fingerprint(rho_probe=rho_probe, delta=delta)
    jump_2024 = _RS_2024.fingerprint(rho_probe=rho_probe, delta=delta)

    expected_2024 = -1.15 * rho_probe
    tol = 1e-6

    checks = {
        "rs_2013_fingerprint": {
            "actual": jump_2013,
            "expected_abs_max": tol,
            "passed": abs(jump_2013) <= tol,
            "meaning": "分段累加 → 阈值处连续，跳变量 ≈ 0",
        },
        "rs_2024_fingerprint": {
            "actual": jump_2024,
            "expected": expected_2024,
            "tolerance": tol,
            "passed": abs(jump_2024 - expected_2024) <= tol,
            "meaning": "调整单价本身 → 阈值处跳降 ≈ -1.15·ρ⁺",
        },
        "separation": {
            "actual": abs(jump_2024 - jump_2013),
            "expected_min": 0.5 * abs(expected_2024),
            "passed": abs(jump_2024 - jump_2013) >= 0.5 * abs(expected_2024),
            "meaning": "两套实现必须可区分，否则说明公式被复制",
        },
    }
    return {
        "rho_probe": rho_probe,
        "delta": delta,
        "checks": checks,
        "passed": all(c["passed"] for c in checks.values()),
    }
