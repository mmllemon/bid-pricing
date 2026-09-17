"""MILP 独立验收协议（T04-07）。

回答一个且仅一个问题：**这一次求解的结果能不能被当作「已证最优」接受**。

与 T04-02C（求解与状态归一）的分工：后者回答「这次求解是什么状态」，
本模块回答「这个状态够不够格被当作最优」。状态域**复用** T04-02C 的归一
结果，不另立一套词表——另立一套等于把同一种机器状态编码两次（规则⑨同族）。

三条纪律（对应制品 ``config/milp_acceptance_spec.json`` 的 ``forbidden``）：

1. **求解器自报 ``Optimal`` 不是验收结论**。最优性必须由可核的量证明：
   对偶界 + 相对间隙 + 整数性违规。缺任何一项 ⇒ 最优性未证。
2. **never_upgrade**：验收结论只能比归一状态更宽松，绝不能更严。
   这一条最容易被「让报告好看一点」的冲动绕过。
3. **禁用 KKT 证 MILP 最优性**——MILP 可行域非凸，KKT 既非必要也非充分。

★ **计算与判定分离**（ADR-0025 同款）：``build_acceptance`` 是生产者，
``judge_milp`` 只吃 ``MilpFacts`` + ``MilpAcceptance``。这样判据能被注入的
错误结论否定——若两者合一，判据只能验证「自己的实现恰好对自己」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

__all__ = [
    "ACCEPT_BLOCKED",
    "ACCEPT_FEASIBLE",
    "ACCEPT_INFEASIBLE",
    "ACCEPT_OPTIMAL",
    "ACCEPT_UNSOLVED",
    "DEFAULT_TOLERANCES",
    "MilpAcceptance",
    "MilpCheck",
    "MilpError",
    "MilpFacts",
    "MilpReport",
    "SCOPE",
    "SPEC_FILENAME",
    "STATUS_BLOCKED",
    "STATUS_FAIL",
    "STATUS_PASS",
    "STATUS_SKIP",
    "STATUS_WARN",
    "acceptance_report",
    "build_acceptance",
    "facts_from_result",
    "judge_milp",
    "load_milp_spec",
    "resolve_gap_tolerances",
]

SCOPE = "MA"
SPEC_FILENAME = "milp_acceptance_spec.json"

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_SKIP = "SKIP"
_STATUS_ORDER = (STATUS_FAIL, STATUS_BLOCKED, STATUS_WARN, STATUS_SKIP, STATUS_PASS)

#: 验收结论域（制品 status_domain 的字面镜像）。
ACCEPT_OPTIMAL = "OPTIMAL"
ACCEPT_FEASIBLE = "FEASIBLE"
ACCEPT_UNSOLVED = "UNSOLVED"
ACCEPT_INFEASIBLE = "INFEASIBLE"
ACCEPT_BLOCKED = "BLOCKED"
_ACCEPT_DOMAIN = (
    ACCEPT_OPTIMAL, ACCEPT_FEASIBLE, ACCEPT_UNSOLVED,
    ACCEPT_INFEASIBLE, ACCEPT_BLOCKED,
)

#: 归一状态 → 验收结论的**上限**（never_upgrade："更严"排在前面）。
#: 未列出的归一状态（AMBIGUOUS / UNAVAILABLE / UNSUPPORTED / ERROR …）
#: ⇒ BLOCKED：那些状态本身就不是结论，协议无从验收。
_CEILING: dict[str, str] = {
    "OPTIMAL": ACCEPT_OPTIMAL,
    "FEASIBLE": ACCEPT_FEASIBLE,
    "INFEASIBLE": ACCEPT_INFEASIBLE,
    "UNSOLVED": ACCEPT_UNSOLVED,
}

DEFAULT_TOLERANCES: dict[str, float] = {
    "eps_gap_abs": 0.01,
    "eps_gap_rel": 1e-08,
    "eps_int": 1e-06,
}


class MilpError(ValueError):
    """制品缺失或形态不可判。"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MilpFacts:
    """判定所需的**原始量**——刻意不含 ``SolveResult`` / ``CompiledModel``。

    与 T04-02D 的 SV-12 同款理由：复核层若拿到求解器侧的对象，就会被诱惑去
    读它的便利属性（那些属性多半是**待验对象本身**），独立性随即丧失。
    """

    form: str
    normalized_status: str
    carried_solution: bool
    variables: Mapping[str, float] = field(default_factory=dict)
    integer_symbols: tuple[str, ...] = ()
    objective: float | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    time_limit: float | None = None
    timed_out: bool = False
    maximize: bool = True
    #: 目标常量 ``objective_constant``。**对偶界不含它**（T04-07 接线实证：
    #: 探针常量 −2,270,000，HiGHS 报的界少这一项 ⇒ 直接换算差 5 倍，
    #: 由 MA-06 跨来源对账抓出）。故换算时必须补回去，否则间隙恒为假。
    objective_constant: float = 0.0

    def best_bound_min(self) -> float | None:
        """求解器侧（min 口径）对偶界。"""
        value = self.diagnostics.get("mip_dual_bound")
        return None if value is None else float(value)

    def reported_gap(self) -> float | None:
        """求解器自报相对间隙。"""
        value = self.diagnostics.get("mip_gap")
        return None if value is None else float(value)


@dataclass(frozen=True)
class MilpAcceptance:
    """验收结论。``accepted=None`` 表示「本协议不适用」（形态非 MILP）。"""

    form: str
    normalized_status: str
    accepted: str | None
    optimality_proven: bool
    integer_feasible: bool | None
    objective: float | None
    best_bound: float | None
    gap_reported: float | None
    gap_recomputed: float | None
    time_limit: float | None
    incumbent: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "form": self.form,
            "normalized_status": self.normalized_status,
            "accepted": self.accepted,
            "optimality_proven": self.optimality_proven,
            "integer_feasible": self.integer_feasible,
            "objective": self.objective,
            "best_bound": self.best_bound,
            "gap_reported": self.gap_reported,
            "gap_recomputed": self.gap_recomputed,
            "time_limit": self.time_limit,
            "incumbent": self.incumbent,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class MilpCheck:
    """一条判据的结论。"""

    item: str
    status: str
    reason: str
    actual: Any = None
    expected: Any = None

    @property
    def blocks_progress(self) -> bool:
        return self.status in (STATUS_FAIL, STATUS_BLOCKED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "status": self.status,
            "reason": self.reason,
            "actual": self.actual,
            "expected": self.expected,
        }


@dataclass(frozen=True)
class MilpReport:
    """验收结论 + 判据集。"""

    acceptance: MilpAcceptance
    checks: tuple[MilpCheck, ...]

    def verdict(self) -> str:
        """聚合：取最严；**空判据集 ⇒ BLOCKED**（「没判过」不是 PASS）。"""
        if not self.checks:
            return STATUS_BLOCKED
        seen = {c.status for c in self.checks}
        for s in _STATUS_ORDER:
            if s in seen:
                return s
        return STATUS_BLOCKED  # pragma: no cover - 状态域封闭，兜底

    def of(self, judge_id: str) -> MilpCheck | None:
        for c in self.checks:
            if c.item == judge_id:
                return c
        return None

    def blocking(self) -> tuple[MilpCheck, ...]:
        return tuple(c for c in self.checks if c.blocks_progress)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict(),
            "acceptance": self.acceptance.to_dict(),
            "checks": [c.to_dict() for c in self.checks],
        }


# ---------------------------------------------------------------------------
# 规格加载与容差解析
# ---------------------------------------------------------------------------


def load_milp_spec(config_dir: Path) -> dict[str, Any]:
    """读取受控制品 ``config/milp_acceptance_spec.json``。"""
    path = Path(config_dir) / SPEC_FILENAME
    if not path.exists():
        raise MilpError(f"MILP 验收协议制品不存在：{path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def resolve_gap_tolerances(
    spec: Mapping[str, Any] | None = None,
    overrides: Mapping[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, str]]:
    """解析三个具名容差，返回 ``(tolerances, problems)``。

    ★ **容差必须具名**（DV-01 / CC-12 同族）：返回的是 ``{名字: 数值}``，
    下游不得再硬编码另一个数。制品缺任一键 ⇒ 该键进 ``problems``，
    判 BLOCKED **而不按 0 放行**——按 0 等于把「没声明宽度」当成「宽度为零」。
    """
    names = ("eps_gap_abs", "eps_gap_rel", "eps_int")
    declared: dict[str, Any] = {}
    if spec:
        block = spec.get("tolerances") or {}
        for name in names:
            entry = block.get(name)
            if isinstance(entry, Mapping) and "value" in entry:
                declared[name] = entry["value"]

    if spec is None:
        # 调用方没给制品 ⇒ 用内置默认值，但**仍然具名**（名字来自本模块常量）。
        merged: dict[str, Any] = dict(DEFAULT_TOLERANCES)
        merged.update(declared)
    else:
        # 给了制品 ⇒ 制品是唯一声明处；制品没写的就是**没声明**，
        # 不偷偷用默认值补（补了等于把「没声明宽度」当成「宽度是默认值」）。
        merged = {name: declared.get(name) for name in names}

    if overrides:
        merged.update(dict(overrides))

    problems: dict[str, str] = {}
    for name in names:
        value = merged.get(name)
        if value is None:
            problems[name] = (
                "制品未声明 ⇒ 判据宽度不可知"
                if spec is not None else "默认值缺失 ⇒ 判据宽度不可知"
            )
        else:
            try:
                merged[name] = float(value)
            except (TypeError, ValueError):
                problems[name] = f"声明值 {value!r} 不可解析为数值"
    return merged, problems


def _safe_tolerances(tolerances: Mapping[str, Any]) -> dict[str, float]:
    """把可能为 ``None`` 的容差换成内置默认值，**仅供生产者内部使用**。

    判据侧看到的仍是原始（含 ``None``）的那一份，于是「制品漏声明」能被
    MA-04 判 BLOCKED；而生产者不会因 ``None`` 崩溃——**判据先于实现报错**，
    不是实现先崩再谈判据。
    """
    out = dict(DEFAULT_TOLERANCES)
    for key, value in (tolerances or {}).items():
        if value is not None:
            try:
                out[key] = float(value)
            except (TypeError, ValueError):   # pragma: no cover - 已在 problems 里
                pass
    return out


# ---------------------------------------------------------------------------
# 生产者
# ---------------------------------------------------------------------------


def _bound_in_model_sense(facts: MilpFacts) -> float | None:
    """把求解器侧（min 口径）对偶界换算到模型口径。

    两步换算（缺任一步都会得到一个**看起来合理**的错界）：

    1. 口径取反：PuLP 恒以 min 口径送求解器 ⇒ 最大化模型取反；
    2. 补回常量：HiGHS 的 ``mip_dual_bound`` **不含** ``objective_constant``
       （T04-07 接线实证：探针常量 −2,270,000 ⇒ 少补一步就是 2,730,000 对
       460,000，间隙 4.9 而自报 0.0，由 MA-06 抓出）。

    若将来后端改变任一约定，MA-06 的跨来源对账会当场分叉——这正是它要做的。
    """
    raw = facts.best_bound_min()
    if raw is None:
        return None
    signed = -raw if facts.maximize else raw
    return signed + float(facts.objective_constant or 0.0)


def _gap_recomputed(
    z: float | None, bound: float | None, eps_gap_abs: float
) -> float | None:
    """由 ``(Z, bound)`` 复算的相对间隙。分母用 ``max(|Z|, eps_gap_abs)`` 兜底。"""
    if z is None or bound is None:
        return None
    denom = max(abs(z), abs(eps_gap_abs))
    if denom <= 0.0:
        return None
    return abs(z - bound) / denom


def _integer_feasible(
    facts: MilpFacts, eps_int: float
) -> tuple[bool | None, tuple[str, ...]]:
    """逐变量复算整数可行性。返回 ``(结论, 违规变量)``。

    缺失变量 ⇒ ``None``（**不可判**，不是「通过」）：按 item_id / 符号取变量
    时取错族会让该符号根本不在表里（T04-08 实证过 z_i 覆盖 p_i），此时若按
    「没找到就算通过」处理，判据会静默失效。
    """
    if eps_int is None:
        return None, ()
    if not facts.integer_symbols:
        return True, ()
    missing = [s for s in facts.integer_symbols if s not in facts.variables]
    if missing:
        return None, tuple(missing[:5])
    bad = []
    for sym in facts.integer_symbols:
        value = float(facts.variables[sym])
        if abs(value - round(value)) > float(eps_int):
            bad.append(sym)
    return (not bad), tuple(bad[:5])


def build_acceptance(
    facts: MilpFacts,
    *,
    tolerances: Mapping[str, float] | None = None,
) -> MilpAcceptance:
    """产出验收结论（**可被 ``judge_milp`` 否定的那一半**）。

    降级是单向下坡：``OPTIMAL`` 只可能因为缺 bound / 整数违规 / 间隙超标
    而退成 ``FEASIBLE``，绝无反向路径。
    """
    tols = _safe_tolerances(tolerances)
    if facts.form != "MILP":
        return MilpAcceptance(
            form=facts.form, normalized_status=facts.normalized_status,
            accepted=None, optimality_proven=False, integer_feasible=None,
            objective=facts.objective, best_bound=None, gap_reported=None,
            gap_recomputed=None, time_limit=facts.time_limit,
            incumbent=facts.carried_solution,
            reasons=(f"形态 {facts.form!r} ≠ MILP ⇒ 本协议不适用（判 SKIP 不判 PASS）",),
        )

    ceiling = _CEILING.get(facts.normalized_status)
    if ceiling is None:
        return MilpAcceptance(
            form=facts.form, normalized_status=facts.normalized_status,
            accepted=ACCEPT_BLOCKED, optimality_proven=False,
            integer_feasible=None, objective=facts.objective, best_bound=None,
            gap_reported=facts.reported_gap(), gap_recomputed=None,
            time_limit=facts.time_limit, incumbent=facts.carried_solution,
            reasons=(f"归一状态 {facts.normalized_status!r} 不在协议状态域内 ⇒ 无从验收",),
        )

    if ceiling == ACCEPT_INFEASIBLE:
        return MilpAcceptance(
            form=facts.form, normalized_status=facts.normalized_status,
            accepted=ACCEPT_INFEASIBLE, optimality_proven=False,
            integer_feasible=None, objective=facts.objective, best_bound=None,
            gap_reported=facts.reported_gap(), gap_recomputed=None,
            time_limit=facts.time_limit, incumbent=False,
            reasons=("已证无可行解（沿用归一状态）",),
        )

    if facts.timed_out or ceiling == ACCEPT_UNSOLVED:
        accepted = ACCEPT_FEASIBLE if facts.carried_solution else ACCEPT_UNSOLVED
        reason = (
            "超时且有 incumbent ⇒ FEASIBLE（禁宣最优）"
            if accepted == ACCEPT_FEASIBLE else
            "超时且无 incumbent ⇒ UNSOLVED（≠ INFEASIBLE）"
        )
        return MilpAcceptance(
            form=facts.form, normalized_status=facts.normalized_status,
            accepted=accepted, optimality_proven=False, integer_feasible=None,
            objective=facts.objective, best_bound=_bound_in_model_sense(facts),
            gap_reported=facts.reported_gap(), gap_recomputed=None,
            time_limit=facts.time_limit, incumbent=facts.carried_solution,
            reasons=(reason,),
        )

    bound = _bound_in_model_sense(facts)
    gap_calc = _gap_recomputed(facts.objective, bound, tols["eps_gap_abs"])

    if ceiling != ACCEPT_OPTIMAL:
        # 归一状态本身就没说最优 ⇒ 直接继承，不得因为「碰巧四条都满足」
        # 而升成 OPTIMAL——那正是 MA-02 要拦的非法升级。
        return MilpAcceptance(
            form=facts.form, normalized_status=facts.normalized_status,
            accepted=ACCEPT_FEASIBLE, optimality_proven=False,
            integer_feasible=_integer_feasible(facts, tols["eps_int"])[0],
            objective=facts.objective, best_bound=bound,
            gap_reported=facts.reported_gap(), gap_recomputed=gap_calc,
            time_limit=facts.time_limit, incumbent=facts.carried_solution,
            reasons=(f"归一状态 {facts.normalized_status} 未声明最优 ⇒ 继承为 FEASIBLE",),
        )

    # ---- 以下只在 ceiling == OPTIMAL 时：逐条核验能否保住「最优」 ----------
    gap_rep = facts.reported_gap()
    gap_calc = _gap_recomputed(facts.objective, bound, tols["eps_gap_abs"])
    int_feasible, offenders = _integer_feasible(facts, tols["eps_int"])

    reasons: list[str] = []
    accepted = ACCEPT_OPTIMAL
    if bound is None:
        accepted = ACCEPT_FEASIBLE
        reasons.append("best_bound 未提供 ⇒ 最优性不可证（不得用 Z 顶替）")
    if int_feasible is False:
        accepted = ACCEPT_FEASIBLE
        reasons.append(f"整数性违规：{', '.join(offenders)}")
    if int_feasible is None:
        accepted = ACCEPT_FEASIBLE
        reasons.append("整数变量取值缺失 ⇒ 整数性不可判")
    if gap_calc is not None:
        tol = tols["eps_gap_abs"] + tols["eps_gap_rel"] * max(
            abs(facts.objective or 0.0), abs(bound or 0.0)
        )
        if gap_calc * max(abs(facts.objective or 0.0), tols["eps_gap_abs"]) > tol:
            accepted = ACCEPT_FEASIBLE
            reasons.append(f"间隙 {gap_calc:.3e} 超过容差 ⇒ 最优性未证")
    else:
        accepted = ACCEPT_FEASIBLE
        reasons.append("间隙不可算（Z 或 bound 缺失）⇒ 最优性未证")

    if not reasons:
        reasons.append("四条全满足：状态 OPTIMAL + 整数可行 + bound 已知 + 间隙达标")

    return MilpAcceptance(
        form=facts.form, normalized_status=facts.normalized_status,
        accepted=accepted, optimality_proven=(accepted == ACCEPT_OPTIMAL),
        integer_feasible=int_feasible, objective=facts.objective,
        best_bound=bound, gap_reported=gap_rep, gap_recomputed=gap_calc,
        time_limit=facts.time_limit, incumbent=facts.carried_solution,
        reasons=tuple(reasons),
    )


# ---------------------------------------------------------------------------
# 判据（只吃 MilpFacts + MilpAcceptance，不读求解中间量）
# ---------------------------------------------------------------------------


def _ma01(facts: MilpFacts) -> MilpCheck:
    if facts.form == "MILP":
        return MilpCheck(
            "MA-01", STATUS_PASS, f"形态 {facts.form!r} ⇒ 协议适用",
            actual=facts.form, expected="MILP",
        )
    return MilpCheck(
        "MA-01", STATUS_SKIP,
        f"形态 {facts.form!r} ≠ MILP ⇒ 本协议不适用。"
        "「没走到」既不是通过也不是违反 ⇒ 判 SKIP（LP 的最优性由 LP 侧口径负责）",
        actual=facts.form, expected="MILP",
    )


def _ma02(facts: MilpFacts, acc: MilpAcceptance) -> MilpCheck:
    """never_upgrade：验收结论不得比归一状态更严。"""
    if acc.accepted is None:
        return MilpCheck(
            "MA-02", STATUS_SKIP, "协议不适用 ⇒ 本条不判",
            actual=None, expected=None,
        )
    ceiling = _CEILING.get(facts.normalized_status)
    if ceiling is None:
        return MilpCheck(
            "MA-02", STATUS_BLOCKED,
            f"归一状态 {facts.normalized_status!r} 不在映射表内 ⇒ 上限不可知",
            actual=facts.normalized_status, expected=sorted(_CEILING),
        )
    if acc.accepted == ACCEPT_OPTIMAL and ceiling != ACCEPT_OPTIMAL:
        return MilpCheck(
            "MA-02", STATUS_FAIL,
            f"非法升级：归一状态 {facts.normalized_status!r} 的上限是 "
            f"{ceiling}，却给出 {acc.accepted}。这是本协议最容易被绕过的一条",
            actual=acc.accepted, expected=ceiling,
        )
    return MilpCheck(
        "MA-02", STATUS_PASS,
        f"结论 {acc.accepted} 未超出上限 {ceiling}",
        actual=acc.accepted, expected=ceiling,
    )


def _ma03(
    facts: MilpFacts, acc: MilpAcceptance, eps_int: float | None
) -> MilpCheck:
    if acc.accepted is None:
        return MilpCheck("MA-03", STATUS_SKIP, "协议不适用 ⇒ 本条不判")
    if eps_int is None:
        return MilpCheck(
            "MA-03", STATUS_BLOCKED,
            "eps_int 未具名 ⇒ 整数性判据宽度不可知（不得按 0 放行）",
            actual=None, expected="eps_int",
        )
    verdict, offenders = _integer_feasible(facts, eps_int)
    if verdict is None:
        return MilpCheck(
            "MA-03", STATUS_BLOCKED,
            f"整数变量取值缺失，无法逐变量核：{', '.join(offenders) or '<空表>'}。"
            "「没找到变量」不等于「变量都是整数」",
            actual=None, expected="≤eps_int",
        )
    if verdict is False:
        return MilpCheck(
            "MA-03", STATUS_FAIL,
            f"整数性违规（到最近整数的距离 > {eps_int:g}）：{', '.join(offenders)}",
            actual=True, expected=False,
        )
    return MilpCheck(
        "MA-03", STATUS_PASS,
        f"逐变量核验通过（{len(facts.integer_symbols)} 个整数/二元变量，eps_int={eps_int:g}）",
        actual=False, expected=False,
    )


def _ma04(
    tolerances: Mapping[str, float],
    problems: Mapping[str, str],
    declared_names: Sequence[str],
) -> MilpCheck:
    """容差双具名 + 实现不得读制品未声明的容差。"""
    if problems:
        return MilpCheck(
            "MA-04", STATUS_BLOCKED,
            "容差不可解析：" + "；".join(f"{k}：{v}" for k, v in problems.items()),
            actual=sorted(problems), expected=sorted(DEFAULT_TOLERANCES),
        )
    undeclared = [n for n in tolerances if n not in declared_names]
    if undeclared:
        return MilpCheck(
            "MA-04", STATUS_BLOCKED,
            "实现读了制品未声明的容差：" + "、".join(sorted(undeclared))
            + "——制品漏写一条时实现多读一项**不报错**，判据整体变严却没信号",
            actual=sorted(undeclared), expected=sorted(declared_names),
        )
    return MilpCheck(
        "MA-04", STATUS_PASS,
        "三个容差均具名可查：" + "、".join(
            f"{k}={tolerances[k]:g}" for k in sorted(tolerances)
        ),
        actual=sorted(tolerances), expected=sorted(declared_names),
    )


def _ma05(facts: MilpFacts, acc: MilpAcceptance) -> MilpCheck:
    if acc.accepted is None:
        return MilpCheck("MA-05", STATUS_SKIP, "协议不适用 ⇒ 本条不判")
    if facts.best_bound_min() is None:
        if acc.accepted == ACCEPT_OPTIMAL:
            return MilpCheck(
                "MA-05", STATUS_FAIL,
                "best_bound 缺失却仍标 OPTIMAL ⇒ 最优性是自证的（|Z−Z|=0 恒真）",
                actual=acc.accepted, expected="FEASIBLE",
            )
        return MilpCheck(
            "MA-05", STATUS_WARN,
            "适配层未取到对偶界 ⇒ 最优性未证（如实结论，非缺陷）。"
            "命令行型后端（CBC）恒为此格；换 persistent 型后端可取证",
            actual=None, expected="bound",
        )
    return MilpCheck(
        "MA-05", STATUS_PASS,
        f"bound 已取得（min 口径 {facts.best_bound_min():g}）",
        actual=facts.best_bound_min(), expected="not None",
    )


def _ma06(
    facts: MilpFacts,
    acc: MilpAcceptance,
    tolerances: Mapping[str, float],
) -> MilpCheck:
    """对偶界 × 自报间隙 的跨来源对账（规则⑥：判据不得自证）。"""
    if acc.accepted is None:
        return MilpCheck("MA-06", STATUS_SKIP, "协议不适用 ⇒ 本条不判")
    tols = _safe_tolerances(tolerances)
    rep = acc.gap_reported
    calc = acc.gap_recomputed
    if rep is None and calc is None:
        return MilpCheck(
            "MA-06", STATUS_BLOCKED,
            "自报间隙与复算间隙都缺失 ⇒ 无对照可判",
            actual=None, expected="两个来源",
        )
    if rep is None or calc is None:
        have = "自报" if rep is not None else "复算"
        return MilpCheck(
            "MA-06", STATUS_BLOCKED,
            f"只有{have}间隙 ⇒ 同源自证，不构成对账（规则⑥）",
            actual={"reported": rep, "recomputed": calc},
            expected="两个来源同时在场",
        )
    z = facts.objective
    scale = max(abs(z or 0.0), abs(tolerances["eps_gap_abs"]))
    diff = abs(rep - calc)
    limit = tols["eps_gap_rel"] + tols["eps_gap_abs"] / scale if scale else 0.0
    if diff > limit:
        return MilpCheck(
            "MA-06", STATUS_BLOCKED,
            f"两个来源不一致：自报 {rep:.3e} vs 复算 {calc:.3e}（Δ={diff:.3e} > "
            f"{limit:.3e}）⇒ sense 约定失效或量纲错位，最优性不可判",
            actual={"reported": rep, "recomputed": calc}, expected=limit,
        )
    return MilpCheck(
        "MA-06", STATUS_PASS,
        f"两侧一致：自报 {rep:.3e} ≈ 复算 {calc:.3e}（Δ={diff:.3e}）",
        actual={"reported": rep, "recomputed": calc}, expected=limit,
    )


def _ma07(facts: MilpFacts, acc: MilpAcceptance) -> MilpCheck:
    if acc.accepted is None:
        return MilpCheck("MA-07", STATUS_SKIP, "协议不适用 ⇒ 本条不判")
    if facts.time_limit is None:
        return MilpCheck(
            "MA-07", STATUS_BLOCKED,
            "time_limit 未声明 ⇒ 无法区分「算完了」与「被中断」",
            actual=None, expected="秒",
        )
    if not facts.timed_out:
        return MilpCheck(
            "MA-07", STATUS_PASS,
            f"时限已声明（{facts.time_limit:g}s）且未被中断",
            actual=facts.time_limit, expected="not None",
        )
    want = ACCEPT_FEASIBLE if facts.carried_solution else ACCEPT_UNSOLVED
    if acc.accepted != want:
        return MilpCheck(
            "MA-07", STATUS_FAIL,
            f"超时分叉错误：{'有' if facts.carried_solution else '无'} incumbent "
            f"应为 {want}，实际 {acc.accepted}。"
            "把「没算出解」写成 INFEASIBLE 会让对拍器以为 Phase 2 真的不可行",
            actual=acc.accepted, expected=want,
        )
    return MilpCheck(
        "MA-07", STATUS_PASS,
        f"超时分叉正确 ⇒ {acc.accepted}（最优性未证）",
        actual=acc.accepted, expected=want,
    )


def _ma08(acc: MilpAcceptance) -> MilpCheck:
    if acc.accepted is None:
        return MilpCheck("MA-08", STATUS_SKIP, "协议不适用 ⇒ 本条不判")
    if acc.accepted != ACCEPT_OPTIMAL and acc.optimality_proven:
        return MilpCheck(
            "MA-08", STATUS_FAIL,
            f"结论 {acc.accepted} 却置 optimality_proven=True ⇒ "
            "下游会把未证结果当作真实最优值使用（对拍 B 组判据随即退化为恒真）",
            actual=acc.optimality_proven, expected=False,
        )
    return MilpCheck(
        "MA-08", STATUS_PASS,
        f"optimality_proven={acc.optimality_proven} 与结论 {acc.accepted} 一致",
        actual=acc.optimality_proven, expected=acc.accepted == ACCEPT_OPTIMAL,
    )


def _ma09(facts: MilpFacts, domain: Sequence[str]) -> MilpCheck:
    if facts.normalized_status in domain:
        return MilpCheck(
            "MA-09", STATUS_PASS,
            f"归一状态 {facts.normalized_status!r} 在协议状态域内",
            actual=facts.normalized_status, expected=sorted(domain),
        )
    return MilpCheck(
        "MA-09", STATUS_BLOCKED,
        f"归一状态 {facts.normalized_status!r} 不在状态域内 ⇒ 不得按默认值顶掉"
        "（未知状态是信息，不是缺失值）",
        actual=facts.normalized_status, expected=sorted(domain),
    )


def _ma10(checks: Sequence[MilpCheck]) -> MilpCheck:
    if not checks:
        return MilpCheck(
            "MA-10", STATUS_BLOCKED, "判据集为空 ⇒「什么都没判」不得显示绿",
        )
    seen = {c.status for c in checks}
    agg = next((s for s in _STATUS_ORDER if s in seen), STATUS_BLOCKED)
    return MilpCheck(
        "MA-10", STATUS_PASS,
        f"聚合序 FAIL>BLOCKED>WARN>SKIP>PASS ⇒ {agg}（{len(checks)} 条）",
        actual=agg, expected=_STATUS_ORDER,
    )


def judge_milp(
    facts: MilpFacts,
    acceptance: MilpAcceptance,
    *,
    spec: Mapping[str, Any] | None = None,
    tolerances: Mapping[str, float] | None = None,
    tolerance_problems: Mapping[str, str] | None = None,
) -> tuple[MilpCheck, ...]:
    """MA-01..MA-10。**只吃原始量与结论**，不读求解中间量。"""
    tols, problems = resolve_gap_tolerances(spec, tolerances)
    if tolerance_problems:
        problems = dict(problems)
        problems.update(tolerance_problems)

    declared_names = sorted(DEFAULT_TOLERANCES)
    if spec:
        block = spec.get("tolerances") or {}
        declared_names = sorted(
            [k for k, v in block.items() if isinstance(v, Mapping) and "value" in v]
            or DEFAULT_TOLERANCES
        )
    domain = [str(d["id"]) for d in (spec or {}).get("status_domain", [])] or list(
        _ACCEPT_DOMAIN
    )

    checks = [_ma01(facts)]
    if facts.form != "MILP":
        return (checks[0],)

    checks.append(_ma02(facts, acceptance))
    checks.append(_ma03(facts, acceptance, tols.get("eps_int")))
    checks.append(_ma04(tols, problems, declared_names))
    checks.append(_ma05(facts, acceptance))
    checks.append(_ma06(facts, acceptance, tols))
    checks.append(_ma07(facts, acceptance))
    checks.append(_ma08(acceptance))
    checks.append(_ma09(facts, domain))
    checks.append(_ma10(checks))
    return tuple(checks)


def acceptance_report(
    facts: MilpFacts,
    *,
    spec: Mapping[str, Any] | None = None,
    tolerances: Mapping[str, float] | None = None,
) -> MilpReport:
    """一次性产出「结论 + 判据」的完整报告。"""
    tols, problems = resolve_gap_tolerances(spec, tolerances)
    acc = build_acceptance(facts, tolerances=tols)
    checks = judge_milp(
        facts, acc, spec=spec, tolerances=tols, tolerance_problems=problems
    )
    return MilpReport(acceptance=acc, checks=checks)


def facts_from_result(
    result: Any,
    model: Any,
    *,
    time_limit: float | None = None,
    timed_out: bool = False,
) -> MilpFacts:
    """把 ``SolveResult`` + ``CompiledModel`` 翻译成判据要吃的原始量。

    刻意**不在**判据里直接收这两个对象（SV-12 同款）：这里是唯一的翻译点，
    翻译完剩下的都是数字与字符串，于是判据可以被注入的假数据否定。
    """
    status = getattr(result, "status", None)
    normalized = getattr(status, "normalized", None) or str(status)
    objective = getattr(result, "recomputed_objective", None)
    if objective is None:
        objective = getattr(result, "reported_objective", None)
    variables = dict(getattr(result, "variables", {}) or {})
    integer_symbols = tuple(
        s for s in (getattr(model, "binary_symbols", lambda: ())() or ())
    )
    integer_symbols += tuple(
        v.symbol for v in getattr(model, "variables", ())
        if getattr(v, "kind", "") == "INTEGER"
    )
    sense = str(getattr(model, "objective_sense", "MAX")).upper()
    return MilpFacts(
        form=str(getattr(model, "solver_form", "UNKNOWN")),
        normalized_status=str(normalized),
        carried_solution=bool(getattr(result, "solved", bool(variables))),
        variables=variables,
        integer_symbols=tuple(dict.fromkeys(integer_symbols)),
        objective=None if objective is None else float(objective),
        diagnostics=dict(getattr(result, "diagnostics", {}) or {}),
        time_limit=time_limit,
        timed_out=timed_out,
        maximize=sense.startswith("MAX"),
        objective_constant=float(getattr(model, "objective_constant", 0.0) or 0.0),
    )
