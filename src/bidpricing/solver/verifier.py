"""T04-02D 解校验器：独立复核**可行性 / 目标值 / 上下界 / 层归属**。

**本模块在链路中的位置。** 内层判据（T04-02B 的 CC、T04-02C 的 BB）回答的是
「模型/链路**走样**没有」——它们比的是同一条链路上的两侧。本模块是第一道
**外层复核**，回答的是「这个解**本身**站得住吗」。二者不是同一件事：

* 内层 `compiler.evaluate` 只做「按行求和、对 1e-12 比较」——它用的是一个
  **未具名**的严格常量，**从不解析**行上声明的容差名；
* 内层 `instance.check_solution` 只做「代回原式」，用 `eps_total` 判 C1；
* 两者都不产出「逐行 + 逐项 + 逐声称」的复核报告（`solver_backend_spec` 的
  交接条目写明：BB-07/BB-08 **不替代**解校验报告的逐行判定）。

**为什么不做成内层判据的封装。** ADR-0020 的 D1 已把它立成机械判据：外层复核
判据的宽度必须 ≥ 1e3 倍于内层，否则「残差恰好落在带内」的解会同时通过两关，
复核层即退化为内层判据的复制。故本模块：

1. **签名上就拿不到内层结论**——入参是原始量（决策变量赋值、求解器自报目标值），
   **刻意不提供 `SolveResult` 重载**。不接收即无从消费（SV-12）。
2. 自持行的求和实现，不调用 `evaluate` / `check_solution` / `solve_compiled`。
3. 判据宽度由制品解析（`resolve_tolerances`），并按 SV-06 断言两层宽度比。

**四族声称与各自的独立性来源**（详见 `config/solution_verifier_spec.json`
的 `why_not_a_copy`）：

============  ==================================================
可行性        唯一把「行上声明的容差」解析成数值并据此判定的地方
目标值        比的是**求解器自报** vs 本层复算（跨来源），ε_Z 具名
上下界        编译侧把 C3/C4/C5 合并成一行，**失去「哪一条在起作用」**
层归属        编译侧根本没有这个概念；只在层间可判
============  ==================================================
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .compiler import ZERO_EPS as INNER_STRICT_ZERO_EPS
from .compiler import CompiledModel, CompiledRow
from .formulation import compute_lb_c5
from .instance import (
    ROLE_OPTIMIZABLE,
    Phase1Instance,
    Phase1Item,
)

# ---------------------------------------------------------------------------
# 具名常量（CC-12 的精神：判据里出现的数值都必须具名）
# ---------------------------------------------------------------------------

SPEC_FILENAME = "solution_verifier_spec.json"

#: 状态域——与 F/CC/BB 判据同构的五态。
STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_SKIP = "SKIP"

#: 判据域（报告里的 scope）。
SCOPE = "SV"

#: 层归属类别（§4.2 的集合命名 + 一个显式的歧义类）。
TIER_BOUNDARY_LOW = "BOUNDARY_LOW"
TIER_INTERIOR = "INTERIOR"
TIER_BOUNDARY_HIGH = "BOUNDARY_HIGH"
TIER_INFEASIBLE = "INFEASIBLE"
TIER_AMBIGUOUS = "AMBIGUOUS"

#: 两层容差的具名来源。
INNER_TOLERANCE_NAME = "eps_solver"
OUTER_TOLERANCE_NAME = "eps_abs"

#: D1：外层/内层宽度比下限（ADR-0020）。
MIN_TOLERANCE_RATIO = 1.0e3

#: 解析器动词取值域（与制品 `tolerance_name_resolution.resolvers.allowed` 同域）。
RESOLVER_PROFILE_VALUE = "PROFILE_VALUE"
RESOLVER_PROFILE_TIMES_P_REF = "PROFILE_TIMES_P_REF"
RESOLVER_PROFILE_TIMES_Q_REF = "PROFILE_TIMES_Q_REF"
RESOLVER_MAX_ABS_PRICE_P = "MAX_ABS_PRICE_P"
RESOLVER_CONST_ZERO = "CONST_ZERO"
ALLOWED_RESOLVERS = (
    RESOLVER_PROFILE_VALUE,
    RESOLVER_PROFILE_TIMES_P_REF,
    RESOLVER_PROFILE_TIMES_Q_REF,
    RESOLVER_MAX_ABS_PRICE_P,
    RESOLVER_CONST_ZERO,
)

#: 上界的两路来源名（业务侧复算时使用的标签）。
BOUND_L = "L"
BOUND_FLOOR = "floor"
BOUND_U = "U"
BOUND_LB_C5 = "lb_C5"

#: 下界候选的顺序（决定 `binding` 的列举顺序；**不**决定取值，取值用 max）。
LOWER_BOUND_ORDER = (BOUND_L, BOUND_FLOOR, BOUND_LB_C5)

#: 报告与诊断输出的截断长度。
SAMPLE_LIMIT = 6
REASON_TRUNC = 220

#: 目标值对账：ε_Z 的绝对项来源（§4.1 要求绝对+相对混合形式）。
#: 绝对项取外层容差名；相对项**必须**取无量纲的 ``eps_rel_price``——
#: 不是已 ×P* 的 ``eps_price``（混用即乘重一遍，见制品 discovered_defect_2 / DV-02）。
EPS_Z_ABS_NAME = OUTER_TOLERANCE_NAME
EPS_Z_REL_NAME = "eps_rel_price"

#: SV-12 静态审计：本模块不得出现这些调用（代码路径上的调用，不含文档提及）。
FORBIDDEN_CALLS: tuple[str, ...] = ("evaluate", "check_solution", "solve_compiled")

#: SV-12 静态审计：本模块不得 import 求解器包。
FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "pulp", "highspy", "mip", "gurobipy", "cplex", "scipy", "numpy",
)


class VerifierError(ValueError):
    """解校验器无法机械完成复核（制品缺键、容差名不可解析等）。"""


# ---------------------------------------------------------------------------
# 判据与结论载体
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifierCheck:
    """一条 SV 判据的结果。状态域与 F/CC/BB 同构。"""

    scope: str
    item: str
    status: str
    reason: str
    actual: Any = None
    expected: Any = None
    delta: Any = None

    @property
    def blocks_progress(self) -> bool:
        return self.status in (STATUS_FAIL, STATUS_BLOCKED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "item": self.item,
            "status": self.status,
            "reason": self.reason,
            "actual": self.actual,
            "expected": self.expected,
            "delta": self.delta,
        }


@dataclass(frozen=True)
class RowVerdict:
    """一行的复核结果。

    ``ok_declared`` 是**本层的判定**（对声明容差比较）；``ok_strict`` 是内层
    那种严格算术判定（对 ``INNER_STRICT_ZERO_EPS`` 比较），保留它只为把
    「落在容差带内」的事实暴露出来——**不是**本层的结论。
    """

    constraint_id: str
    origin: str
    sense: str
    lhs: float
    rhs: float
    violation: float
    tolerance_name: str
    tolerance_value: float | None
    ok_declared: bool | None
    strict_violation: float
    in_band: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "origin": self.origin,
            "sense": self.sense,
            "lhs": self.lhs,
            "rhs": self.rhs,
            "violation": self.violation,
            "tolerance_name": self.tolerance_name,
            "tolerance_value": self.tolerance_value,
            "ok_declared": self.ok_declared,
            "strict_violation": self.strict_violation,
            "in_band": self.in_band,
        }


@dataclass(frozen=True)
class BoundVerdict:
    """一项报价的上下界复核结果。``parts`` 是四路阈值各自的判定。"""

    item_id: str
    p: float | None
    parts: tuple[tuple[str, dict[str, Any]], ...]
    binding_lower: str | None
    worst_violation: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "p": self.p,
            "parts": {k: v for k, v in self.parts},
            "binding_lower": self.binding_lower,
            "worst_violation": self.worst_violation,
            "note": self.note,
        }


@dataclass(frozen=True)
class TierVerdict:
    """一项的层归属。"""

    item_id: str
    tier: str
    p: float | None
    low: float | None
    high: float | None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "tier": self.tier,
            "p": self.p,
            "low": self.low,
            "high": self.high,
            "note": self.note,
        }


@dataclass(frozen=True)
class VerificationReport:
    """解校验报告——T04-02D 的交付物。"""

    spec_id: str
    verdict: str
    checks: tuple[VerifierCheck, ...]
    rows: tuple[RowVerdict, ...] = ()
    bounds: tuple[BoundVerdict, ...] = ()
    tiers: tuple[TierVerdict, ...] = ()
    tier_distribution: tuple[tuple[str, int], ...] = ()
    objective: tuple[tuple[str, Any], ...] = ()
    tolerances: tuple[tuple[str, float | None], ...] = ()

    def of(self, judge_id: str) -> VerifierCheck | None:
        for c in self.checks:
            if c.item.startswith(judge_id):
                return c
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "verdict": self.verdict,
            "tolerances": {k: v for k, v in self.tolerances},
            "tier_distribution": {k: v for k, v in self.tier_distribution},
            "objective": {k: v for k, v in self.objective},
            "checks": [c.to_dict() for c in self.checks],
            "rows": [r.to_dict() for r in self.rows],
            "bounds": [b.to_dict() for b in self.bounds],
            "tiers": [t.to_dict() for t in self.tiers],
        }


# ---------------------------------------------------------------------------
# 制品
# ---------------------------------------------------------------------------


def load_verifier_spec(config_dir: Path) -> dict[str, Any]:
    return json.loads(
        (Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8")
    )


def _trunc(text: str, limit: int = REASON_TRUNC) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# 容差名 → 数值：单一来源
# ---------------------------------------------------------------------------


def resolve_tolerances(
    profile: Mapping[str, Any],
    spec: Mapping[str, Any],
    *,
    P_ref: float | None = None,
    Q_ref: float | None = None,
) -> tuple[dict[str, float], dict[str, str]]:
    """按制品的解析表把**容差名**解析成数值。

    返回 ``(表, 逐名问题)``。问题表按**名字**记账而不是一根总清单，理由是
    「用到的名字解析不出」与「为将来预留的名字解析不出」必须可分：

    * 前者 ⇒ 该行判 BLOCKED（**不得**退回任何默认值）——这正是本层存在的
      理由之一：在此之前，行上声明的容差名从未被任何判据解析成数；
    * 后者 ⇒ 不构成阻塞。否则一个为将来预留的名字会让整条校验恒 BLOCKED，
      而那与「本轮没检查」是两件事。
    """
    problems: dict[str, str] = {}
    table = (spec.get("tolerance_name_resolution") or {}).get("table")
    if not isinstance(table, dict) or not table:
        raise VerifierError("制品缺 tolerance_name_resolution.table")

    def _value(key: str, owner: str) -> float | None:
        entry = profile.get(key)
        if not isinstance(entry, dict) or "value" not in entry:
            problems[owner] = f"precision_profile 缺 {key}.value"
            return None
        try:
            return float(entry["value"])
        except (TypeError, ValueError):
            problems[owner] = (
                f"precision_profile.{key}.value 不是数：{entry['value']!r}"
            )
            return None

    out: dict[str, float] = {}
    for name, rule in table.items():
        if not isinstance(rule, dict):
            problems[name] = "容差规则不是对象"
            continue
        verb = rule.get("resolver")
        if verb not in ALLOWED_RESOLVERS:
            problems[name] = f"resolver 未识别：{verb!r}"
            continue

        if verb == RESOLVER_CONST_ZERO:
            out[name] = 0.0
        elif verb == RESOLVER_PROFILE_VALUE:
            v = _value(str(rule.get("key")), name)
            if v is not None:
                out[name] = v
        elif verb == RESOLVER_PROFILE_TIMES_P_REF:
            v = _value(str(rule.get("key")), name)
            if P_ref is None:
                problems[name] = "需要 P_ref，但未给出"
            elif v is not None:
                out[name] = v * float(P_ref)
        elif verb == RESOLVER_PROFILE_TIMES_Q_REF:
            v = _value(str(rule.get("key")), name)
            if Q_ref is None:
                problems[name] = "需要 Q_ref，但未给出"
            elif v is not None:
                out[name] = v * float(Q_ref)
        elif verb == RESOLVER_MAX_ABS_PRICE_P:
            keys = list(rule.get("keys") or ())
            if len(keys) != 2:
                problems[name] = "keys 必须恰好两项"
                continue
            a = _value(str(keys[0]), name)
            b = _value(str(keys[1]), name)
            if P_ref is None:
                problems[name] = "需要 P_ref，但未给出"
            elif a is not None and b is not None:
                out[name] = max(a, b * float(P_ref))
    return out, problems


def resolve_row_tolerance(
    row: CompiledRow, tolerances: Mapping[str, float]
) -> tuple[str, float | None]:
    """取该行的声明容差。名字不在表里 ⇒ 返回 ``None``（调用方判 BLOCKED）。

    **不设默认值**：未声明的容差名退化成任何一个数，都会让一条没人定义过的
    判据宽度看起来像已定义。
    """
    name = row.tolerance
    if name in tolerances:
        return name, float(tolerances[name])
    return name, None


# ---------------------------------------------------------------------------
# 判定原语
# ---------------------------------------------------------------------------


def _violation(sense: str, lhs: float, rhs: float) -> float:
    """符号无关的**违反量**：> 0 表示违反（与 ``RowEval.slack`` 互为反号）。"""
    if sense == "==":
        return abs(lhs - rhs)
    if sense == "<=":
        return lhs - rhs
    if sense == ">=":
        return rhs - lhs
    raise VerifierError(f"未知 sense：{sense!r}")


def row_verdicts(
    model: CompiledModel,
    x: Mapping[str, float],
    tolerances: Mapping[str, float],
) -> tuple[RowVerdict, ...]:
    """逐行代回。**本函数自持求和实现**——不调用 ``compiler.evaluate``。

    共用一个求和实现会让「本层复核 = 内层复核」变成恒真式（同源规则⑥）。
    """
    out: list[RowVerdict] = []
    for row in model.rows:
        lhs = 0.0
        for symbol, coeff in row.coefficients:
            lhs += float(coeff) * float(x.get(symbol, 0.0))
        name, tol = resolve_row_tolerance(row, tolerances)
        vio = _violation(row.sense, lhs, float(row.rhs))
        strict_vio = max(0.0, vio - INNER_STRICT_ZERO_EPS) if vio > 0 else 0.0
        ok_declared = None if tol is None else (vio <= tol + INNER_STRICT_ZERO_EPS)
        in_band = bool(vio > INNER_STRICT_ZERO_EPS and tol is not None and vio <= tol)
        out.append(RowVerdict(
            constraint_id=row.constraint_id,
            origin=row.origin,
            sense=row.sense,
            lhs=lhs,
            rhs=float(row.rhs),
            violation=vio,
            tolerance_name=name,
            tolerance_value=tol,
            ok_declared=ok_declared,
            strict_violation=strict_vio,
            in_band=in_band,
        ))
    return tuple(out)


def bound_verdicts(
    instance: Phase1Instance,
    x: Mapping[str, float],
    *,
    tolerances: Mapping[str, float],
    P_ref: float | None,
    resolution: float,
    floor_by_id: Mapping[str, float] | None,
) -> tuple[BoundVerdict, ...]:
    """逐项复算 L_i / floor_i / U_i / lb_C5 四路阈值。

    编译侧把 C3/C4/C5 合并成一行（rhs = max 四路中的下界三路），合并后
    **是哪一条在起作用**在编译侧不可恢复——故只能在这里逐条重建。
    **``compute_lb_c5`` 的入参必须是无量纲的 ``eps_rel_price``**，不是已 ×P* 的
    ``eps_price``——后者会让该函数再乘一遍 P_ref（实测 lb_C5 由 0.01 元被放大
    成 9000 元，四项全判违反下界）。见制品 ``discovered_defect_2``（DV-02）。
    """
    eps_rel = tolerances.get(EPS_Z_REL_NAME)
    lb_c5: float | None = None
    if eps_rel is not None and P_ref is not None:
        lb_c5 = compute_lb_c5(float(P_ref), float(eps_rel), float(resolution))

    out: list[BoundVerdict] = []
    for item in instance.items:
        if item.role != ROLE_OPTIMIZABLE:
            continue
        p = x.get(f"p_{item.item_id}")
        parts: list[tuple[str, dict[str, Any]]] = []
        worst = 0.0
        binding: str | None = None
        notes: list[str] = []

        # ---- 下界三路 -------------------------------------------------
        cands: list[tuple[str, float]] = []
        if item.L is not None:
            cands.append((BOUND_L, float(item.L)))
        if floor_by_id is not None and floor_by_id.get(item.item_id) is not None:
            cands.append((BOUND_FLOOR, float(floor_by_id[item.item_id])))
        elif floor_by_id is None:
            notes.append("floor 未由派生量层产出（T03-02 已落地；本轮缺席通常因 μ 等上游未定）")
        if lb_c5 is not None:
            cands.append((BOUND_LB_C5, float(lb_c5)))

        for name in LOWER_BOUND_ORDER:
            if name == BOUND_FLOOR and floor_by_id is None:
                parts.append((name, {
                    "status": STATUS_BLOCKED,
                    "value": None,
                    "reason": ("floor_i 未经派生量层产出（floor_by_id 缺席）——不得用 L_i 或 c_i 冒充。"
                               "owner = T03-02 / derived.compute_derived，已落地"),
                }))
                continue
            value = next((v for n, v in cands if n == name), None)
            if value is None:
                parts.append((name, {
                    "status": STATUS_SKIP, "value": None,
                    "reason": "该路阈值不存在于本实例",
                }))
                continue
            if p is None:
                parts.append((name, {
                    "status": STATUS_BLOCKED, "value": value,
                    "reason": "解中缺该变量",
                }))
                continue
            vio = value - float(p)          # 违反量：p < value 时 > 0
            worst = max(worst, vio)
            parts.append((name, {
                "status": STATUS_PASS if vio <= 0 else STATUS_FAIL,
                "value": value,
                "violation": vio,
            }))
        if cands:
            binding = max(cands, key=lambda kv: kv[1])[0]

        # ---- 上界一路 -------------------------------------------------
        if item.U is not None:
            if p is None:
                parts.append((BOUND_U, {
                    "status": STATUS_BLOCKED, "value": float(item.U),
                    "reason": "解中缺该变量",
                }))
            else:
                vio = float(p) - float(item.U)
                worst = max(worst, vio)
                parts.append((BOUND_U, {
                    "status": STATUS_PASS if vio <= 0 else STATUS_FAIL,
                    "value": float(item.U),
                    "violation": vio,
                }))
            if item.cap is not None and abs(float(item.cap) - float(item.U)) > 0:
                notes.append("U 与 cap 不一致（U 是 C2 的实际阈值）")
        else:
            parts.append((BOUND_U, {
                "status": STATUS_SKIP, "value": None,
                "reason": "不限价（ALLOW_EMPTY_NO_CAP）——合法语义，不是数据缺口",
            }))

        out.append(BoundVerdict(
            item_id=item.item_id,
            p=None if p is None else float(p),
            parts=tuple(parts),
            binding_lower=binding,
            worst_violation=worst,
            note="；".join(notes),
        ))
    return tuple(out)


def tier_verdicts(
    bounds: Sequence[BoundVerdict],
    *,
    tol: float,
    floor_resolved: bool,
) -> tuple[TierVerdict, ...]:
    """层归属：BOUNDARY_LOW / INTERIOR / BOUNDARY_HIGH / INFEASIBLE / AMBIGUOUS。

    层判定容差取**外层**容差：层归属是「顶到没顶到边界」的问题，与求解器
    原始可行性的精度无关（§4.2 亦把它定位为描述性指标）。
    """
    out: list[TierVerdict] = []
    for bv in bounds:
        part = {k: v for k, v in bv.parts}
        lows = [
            v["value"] for k in LOWER_BOUND_ORDER
            if (v := part.get(k)) and v.get("value") is not None
        ]
        up = part.get(BOUND_U) or {}
        low = max(lows) if lows else None
        high = up.get("value")

        if bv.p is None:
            out.append(TierVerdict(bv.item_id, TIER_AMBIGUOUS, None, low, high,
                                   "解中缺该变量，层归属不可判"))
            continue
        if low is None:
            out.append(TierVerdict(bv.item_id, TIER_AMBIGUOUS, bv.p, None, high,
                                   "下界阈值全部不存在，层归属不可判"))
            continue

        p = bv.p
        if p < low - tol or (high is not None and p > high + tol):
            out.append(TierVerdict(bv.item_id, TIER_INFEASIBLE, p, low, high,
                                   "落在 [low, high] 之外（§4.2：理论上不可行）"))
            continue
        if abs(p - low) <= tol:
            note = "" if floor_resolved else "下界候选不完整（floor 未经派生量层产出）⇒ 归属含歧义"
            out.append(TierVerdict(
                bv.item_id, TIER_AMBIGUOUS if not floor_resolved else TIER_BOUNDARY_LOW,
                p, low, high, note))
            continue
        if high is not None and abs(p - high) <= tol:
            out.append(TierVerdict(bv.item_id, TIER_BOUNDARY_HIGH, p, low, high, ""))
            continue
        # 边界容差带内的「既像边界又像内部」也算歧义。
        if high is not None and high - p <= tol:
            out.append(TierVerdict(bv.item_id, TIER_AMBIGUOUS, p, low, high,
                                   "p 落在高边界容差带内"))
            continue
        out.append(TierVerdict(bv.item_id, TIER_INTERIOR, p, low, high, ""))
    return tuple(out)


# ---------------------------------------------------------------------------
# SV-12：静态独立性审计
# ---------------------------------------------------------------------------


def audit_verifier_source(
    source: str | None = None,
    path: Path | None = None,
) -> tuple[str, list[str]]:
    """AST 静态审计：本模块不得调用内层判据、不得 import 求解器包。

    用 AST 取**调用与导入**，不取纯文本——文档里提到 ``evaluate`` 这个名字
    不算违规（与 T04-02C 的 BB-05 同一条教训：判据不得把正常实现报成违规）。
    """
    if source is None:
        target = Path(path) if path is not None else Path(__file__)
        source = target.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:                       # pragma: no cover - 防御
        return STATUS_BLOCKED, [f"无法解析 verifier 源码：{exc}"]

    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.id if isinstance(fn, ast.Name)
                else fn.attr if isinstance(fn, ast.Attribute)
                else None
            )
            if name in FORBIDDEN_CALLS:
                findings.append(f"第 {node.lineno} 行调用了内层判据 {name}(...)")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORTS:
                    findings.append(f"第 {node.lineno} 行 import 了求解器包 {root}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_IMPORTS:
                findings.append(f"第 {node.lineno} 行 from {root} import ...")
    return (STATUS_PASS if not findings else STATUS_BLOCKED), findings


# ---------------------------------------------------------------------------
# 复核入口
# ---------------------------------------------------------------------------


def _aggregate(checks: Sequence[VerifierCheck]) -> str:
    """verdict = worst(...)：FAIL > BLOCKED > WARN > SKIP > PASS。

    FAIL 与 BLOCKED 必须可分且都不得被忽略：FAIL = 查出问题，BLOCKED =
    这一环没查成。把 BLOCKED 压在 FAIL 之下会让「有结论的问题」被「没结论的
    环节」盖住；反之则会让一个未检查的环伪装成已通过。判据集为空 ⇒ BLOCKED
    （无判据即无证据）。
    """
    if not checks:
        return STATUS_BLOCKED
    order = {
        STATUS_FAIL: 4, STATUS_BLOCKED: 3, STATUS_WARN: 2,
        STATUS_SKIP: 1, STATUS_PASS: 0,
    }
    return max((c.status for c in checks), key=lambda s: order.get(s, 0))


def verify_solution(
    model: CompiledModel,
    x: Mapping[str, float] | None,
    *,
    spec: Mapping[str, Any],
    profile: Mapping[str, Any],
    instance: Phase1Instance | None = None,
    reported_objective: float | None = None,
    floor_by_id: Mapping[str, float] | None = None,
    reference: float | None = None,
    verifier_source: str | None = None,
    resolution: float | None = None,
) -> VerificationReport:
    """独立复核一个解。**入参刻意不含 ``SolveResult``**（SV-12 的类型级保证）。

    ``x is None`` ⇒ 依赖解的判据判 SKIP，但层级判据（SV-01/SV-06/SV-12）
    仍照跑——它们不需要解。
    """
    checks: list[VerifierCheck] = []

    # ---- P_ref / resolution：与 formulation.compute_lb_c5 同源同值 ------
    P_ref: float | None = None
    if instance is not None:
        P_ref = instance.P_star if instance.P_star is not None else instance.B
    if resolution is None:
        rounding = (profile.get("rounding") or {})
        resolution = float(rounding.get("resolution", 0.0))

    tolerances, tol_problems = resolve_tolerances(profile, spec, P_ref=P_ref)

    # ---------------- SV-01 声明容差名全可解析 --------------------------
    declared = sorted({r.tolerance for r in model.rows})
    # 只有**用到的**名字解析不出才阻塞：预留的名字（如本层无行使用的
    # eps_quantity）解析不出不构成阻塞，否则一个为将来预留的名字会让整条
    # 校验恒 BLOCKED——那与「本轮没检查」是两件事。
    needed = sorted(set(declared) | {
        INNER_TOLERANCE_NAME, OUTER_TOLERANCE_NAME, EPS_Z_REL_NAME,
    })
    unknown = [n for n in declared if n not in tolerances]
    unusable = [n for n in needed if n not in tolerances]
    problems = [f"{n}：{tol_problems[n]}" for n in unusable if n in tol_problems]
    unused_unresolved = sorted(set(tol_problems) - set(needed))
    problems += [f"行上出现未声明的容差名：{n}" for n in unknown]
    checks.append(VerifierCheck(
        SCOPE, "SV-01 声明容差名全可解析",
        STATUS_PASS if not problems else STATUS_BLOCKED,
        ((f"行上 {len(declared)} 个容差名与本层 3 个层级名全部解析："
          f"{ {n: tolerances.get(n) for n in needed} }"
          + (f"；另有未使用的预留名 {unused_unresolved} 暂无解析（不阻塞）"
             if unused_unresolved else ""))
         if not problems else _trunc("；".join(problems))),
        actual=declared, expected=needed,
    ))

    # ---------------- SV-06 两层容差宽度比（D1）------------------------
    inner = tolerances.get(INNER_TOLERANCE_NAME)
    outer = tolerances.get(OUTER_TOLERANCE_NAME)
    if inner is None or outer is None or inner == 0:
        ratio = None
        checks.append(VerifierCheck(
            SCOPE, "SV-06 两层容差宽度比 R2 ≥ 1e3（复核层不得是内层判据的复制）",
            STATUS_BLOCKED,
            f"内层 {INNER_TOLERANCE_NAME}={inner!r} / 外层 {OUTER_TOLERANCE_NAME}"
            f"={outer!r} 解析不出 ⇒ 宽度比算不出。",
        ))
    else:
        ratio = float(outer) / float(inner)
        checks.append(VerifierCheck(
            SCOPE, "SV-06 两层容差宽度比 R2 ≥ 1e3（复核层不得是内层判据的复制）",
            STATUS_PASS if ratio >= MIN_TOLERANCE_RATIO else STATUS_FAIL,
            (f"R2 = {OUTER_TOLERANCE_NAME}/{INNER_TOLERANCE_NAME} = {ratio:g}"
             f" ≥ {MIN_TOLERANCE_RATIO:g}（两层失败模式可分）"
             if ratio >= MIN_TOLERANCE_RATIO else
             f"R2 = {ratio:g} < {MIN_TOLERANCE_RATIO:g} ⇒ 复核层退化为内层判据的复制"),
            actual=ratio, expected=MIN_TOLERANCE_RATIO, delta=ratio - MIN_TOLERANCE_RATIO,
        ))

    # ---------------- SV-12 静态独立性 ---------------------------------
    s12_status, s12_findings = audit_verifier_source(verifier_source)
    checks.append(VerifierCheck(
        SCOPE, "SV-12 独立性：不得消费内层判据的结论",
        s12_status,
        ("结论：只在原始量上工作（入参无 SolveResult）✅ 静态无禁用调用/导入"
         if s12_status == STATUS_PASS else _trunc("；".join(s12_findings))),
        actual=s12_findings, expected=[],
    ))

    rows: tuple[RowVerdict, ...] = ()
    bounds: tuple[BoundVerdict, ...] = ()
    tiers: tuple[TierVerdict, ...] = ()
    dist: tuple[tuple[str, int], ...] = ()
    obj: tuple[tuple[str, Any], ...] = ()

    # ---------------- 解依赖族 -----------------------------------------
    if x is None or instance is None:
        why = "未提供解" if x is None else "未提供实例"
        for jid in ("SV-02", "SV-03", "SV-04", "SV-05", "SV-07", "SV-08",
                    "SV-09", "SV-10", "SV-11"):
            checks.append(VerifierCheck(
                SCOPE, f"{jid}（未判）", STATUS_SKIP,
                f"{why} ⇒ 本判据本轮没检查。**SKIP ≠ PASS**。",
            ))
    else:
        rows = row_verdicts(model, x, tolerances)

        # ------------ SV-04 缺变量 / 未编译项 --------------------------
        missing = tuple(v.symbol for v in model.variables if v.symbol not in x)
        not_compiled = tuple(
            s.subject for s in model.simplifications if s.kind == "NOT_COMPILED"
        )
        s04: list[str] = []
        if missing:
            s04.append(f"解缺变量 {list(missing[:SAMPLE_LIMIT])}"
                       f"（共 {len(missing)}）")
        if not_compiled:
            s04.append(f"未编译项 {list(not_compiled[:SAMPLE_LIMIT])}"
                       f"（共 {len(not_compiled)}）⇒ 其约束不得被当作已满足")
        checks.append(VerifierCheck(
            SCOPE, "SV-04 缺变量 / 未编译项不得 PASS",
            STATUS_PASS if not s04 else STATUS_BLOCKED,
            "解覆盖全部变量，且无 NOT_COMPILED 项" if not s04
            else _trunc("；".join(s04)),
            actual=s04, expected=[],
        ))

        # ------------ SV-02 可行性（逐行，声明容差）--------------------
        bad = [r for r in rows if r.ok_declared is False]
        unresolved = [r for r in rows if r.ok_declared is None]
        s02: list[str] = []
        if unresolved:
            s02.append(f"容差不可解析的行 {sorted({r.tolerance_name for r in unresolved})}")
        if bad:
            s02.append("；".join(
                f"{r.constraint_id} 违反 {r.violation:g} > 容差 {r.tolerance_value:g}"
                for r in bad[:SAMPLE_LIMIT]
            ))
        checks.append(VerifierCheck(
            SCOPE, "SV-02 可行性：逐行残差 ≤ 该行声明容差",
            STATUS_PASS if not s02 else
            (STATUS_BLOCKED if unresolved else STATUS_FAIL),
            (f"{len(rows)} 行全部在声明容差内"
             f"（最大违反量 {max((r.violation for r in rows), default=0.0):g}）"
             if not s02 else _trunc("；".join(s02))),
            actual=len(bad), expected=0,
        ))

        # ------------ SV-03 容差带必须被实例真的走到 -------------------
        band = [r for r in rows if r.in_band]
        if band:
            checks.append(VerifierCheck(
                SCOPE, "SV-03 容差带内不得被报成违反（且带必须被实例走到）",
                STATUS_PASS,
                (f"{len(band)} 行落在容差带内（严格算术判违反、按声明容差判通过）："
                 + "；".join(
                     f"{r.constraint_id} 违反 {r.violation:.3e} ≤ "
                     f"{r.tolerance_value:.3e}" for r in band[:SAMPLE_LIMIT])
                 + " ⇒ 声明容差确为载荷"),
                actual=len(band), expected="≥1",
            ))
        else:
            checks.append(VerifierCheck(
                SCOPE, "SV-03 容差带内不得被报成违反（且带必须被实例走到）",
                STATUS_WARN,
                "本实例**没有任何行**落在容差带 [1e-12, 声明容差] 内 ⇒ 声明容差"
                "的载荷**未被本实例验证**（探针 C1 slack 恰为 0 即此类："
                "最优值可精确表示）。须用残差落在带内的实例复跑——"
                "「这一轮没走到」不得读成「已成立」。",
                actual=0, expected="≥1",
            ))

        # ------------ SV-05 目标值对账（跨来源）------------------------
        recomputed = (
            model.objective_constant
            + sum(v.objective_coeff * float(x.get(v.symbol, 0.0))
                  for v in model.variables)
        )
        eps_abs_v = tolerances.get(EPS_Z_ABS_NAME)
        eps_price_v = tolerances.get(EPS_Z_REL_NAME)
        if reported_objective is None or eps_abs_v is None or eps_price_v is None:
            checks.append(VerifierCheck(
                SCOPE, "SV-05 目标值：求解器自报 vs 本层独立复算（跨来源）",
                STATUS_BLOCKED,
                f"自报值 {reported_objective!r} 或 ε_Z 的组成项解析不出 ⇒ 对账无从进行。",
            ))
        else:
            eps_z = float(eps_abs_v) + float(eps_price_v) * max(
                abs(float(reported_objective)), abs(recomputed)
            )
            delta = recomputed - float(reported_objective)
            checks.append(VerifierCheck(
                SCOPE, "SV-05 目标值：求解器自报 vs 本层独立复算（跨来源）",
                STATUS_PASS if abs(delta) <= eps_z else STATUS_FAIL,
                (f"自报 {float(reported_objective):g} vs 复算 {recomputed:g}"
                 f"（Δ={delta:g}，ε_Z={eps_z:g}）"
                 if abs(delta) <= eps_z else
                 f"Δ={delta:g} 超出 ε_Z={eps_z:g} ⇒ 求解器报的目标值不是本模型的"),
                actual=float(reported_objective), expected=recomputed,
                delta=delta,
            ))
        obj = (
            ("reported", None if reported_objective is None else float(reported_objective)),
            ("recomputed", recomputed),
        )

        # ------------ SV-07 / SV-08 上下界 ----------------------------
        bounds = bound_verdicts(
            instance, x, tolerances=tolerances, P_ref=P_ref,
            resolution=float(resolution), floor_by_id=floor_by_id,
        )
        floor_missing = any(
            v.get("status") == STATUS_BLOCKED
            for bv in bounds for k, v in bv.parts if k == BOUND_FLOOR
        )
        s07_pass = (
            all(v.get("status") in (STATUS_PASS, STATUS_SKIP)
                for bv in bounds for _k, v in bv.parts)
            and not floor_missing
        )
        s07_reason = []
        if floor_missing:
            s07_reason.append("floor 一路判 BLOCKED：T03-02 的 floor_i 未接入，"
                              "不得用 L_i 或 c_i 冒充")
        violated = [
            (bv.item_id, k, v.get("violation"))
            for bv in bounds for k, v in bv.parts
            if v.get("status") == STATUS_FAIL
        ]
        if violated:
            s07_reason.append("；".join(
                f"{iid} 对 {k} 违反 {vv:g}" for iid, k, vv in violated[:SAMPLE_LIMIT]
            ))
        checks.append(VerifierCheck(
            SCOPE, "SV-07 上下界：逐项四路复算并指出起作用者",
            STATUS_PASS if s07_pass else
            (STATUS_BLOCKED if floor_missing and not violated else STATUS_FAIL),
            (f"{len(bounds)} 项四路阈值全部复算通过；"
             f"起作用下界：{ {b.item_id: b.binding_lower for b in bounds} }"
             if s07_pass else _trunc("；".join(s07_reason))),
            actual=[b.item_id for b in bounds], expected=None,
        ))

        eps_abs_num = tolerances.get(OUTER_TOLERANCE_NAME)
        if eps_abs_num is None:
            checks.append(VerifierCheck(
                SCOPE, "SV-08 上下界违反量按外层容差判", STATUS_BLOCKED,
                f"{OUTER_TOLERANCE_NAME} 解析不出 ⇒ 外层宽度未知。",
            ))
        else:
            hard = [(b.item_id, b.worst_violation) for b in bounds
                    if b.worst_violation > eps_abs_num]
            soft = [(b.item_id, b.worst_violation) for b in bounds
                    if 0.0 < b.worst_violation <= eps_abs_num]
            if hard:
                s08, msg = STATUS_FAIL, "；".join(
                    f"{iid} 违反 {v:g} > {eps_abs_num:g}" for iid, v in hard[:SAMPLE_LIMIT])
            elif soft:
                s08, msg = STATUS_WARN, "；".join(
                    f"{iid} 违反 {v:g} ≤ {eps_abs_num:g}（舍入分辨率内）"
                    for iid, v in soft[:SAMPLE_LIMIT])
            else:
                s08, msg = STATUS_PASS, f"全部在界内（外层容差 {eps_abs_num:g} 元）"
            checks.append(VerifierCheck(
                SCOPE, "SV-08 上下界违反量按外层容差判", s08, msg,
                actual=len(hard) + len(soft), expected=0,
            ))

        # ------------ SV-09 / SV-10 / SV-11 层归属 --------------------
        eps_tier = float(eps_abs_num) if eps_abs_num is not None else 0.0
        tiers = tier_verdicts(bounds, tol=eps_tier, floor_resolved=not floor_missing)
        amb = [t for t in tiers if t.tier == TIER_AMBIGUOUS]
        infeas = [t for t in tiers if t.tier == TIER_INFEASIBLE]
        checks.append(VerifierCheck(
            SCOPE, "SV-09 层归属分类",
            STATUS_WARN if (not tiers or amb) else STATUS_PASS,
            ((f"{len(tiers)} 项已归类："
              f"{ {c: sum(1 for t in tiers if t.tier == c) for c in sorted({t.tier for t in tiers})} }"
              "（本判据只管『归类是否完成』；INFEASIBLE 的存在由 SV-11 判 FAIL，"
              "歧义由 SV-10 判 WARN）")
             if tiers else "无项可归类（无可优化项）"),
            actual=[t.tier for t in tiers], expected=None,
        ))
        checks.append(VerifierCheck(
            SCOPE, "SV-10 层归属歧义须显式标记",
            STATUS_WARN if amb else STATUS_PASS,
            (f"{len(amb)} 项判 AMBIGUOUS：" + "；".join(
                f"{t.item_id}({t.note or 'p 落在容差带内'})" for t in amb[:SAMPLE_LIMIT])
             if amb else f"无歧义项（层判定容差 {eps_tier:g}）"),
            actual=len(amb), expected=0,
        ))
        n = len(tiers) or 1
        dist = tuple(
            (c, sum(1 for t in tiers if t.tier == c))
            for c in (TIER_BOUNDARY_LOW, TIER_INTERIOR, TIER_BOUNDARY_HIGH,
                      TIER_AMBIGUOUS, TIER_INFEASIBLE)
        )
        checks.append(VerifierCheck(
            SCOPE, "SV-11 层归属分布 + INFEASIBLE 即 FAIL",
            STATUS_FAIL if infeas else STATUS_PASS,
            (f"INFEASIBLE {len(infeas)} 项（§4.2：理论上不可行，出现即实现错误）："
             + "；".join(t.item_id for t in infeas[:SAMPLE_LIMIT])
             if infeas else
             "ρ_layer = " + ", ".join(f"{c} {v}/{n}" for c, v in dist)),
            actual={c: v for c, v in dist}, expected=None,
        ))

    # ---------------- SV-13 参考对照 -----------------------------------
    # 口径先后：**没有解** ⇒ 没检查（SKIP，与其余解依赖判据一致）；
    # **有解但没有 Z_ref** ⇒ 这一族确实没检查成（BLOCKED）。二者不是一件事，
    # 故不许合并成一个状态——合并会让「参考实现未落地」被读成「本轮没跑」。
    if x is None:
        checks.append(VerifierCheck(
            SCOPE, "SV-13 参考对照 |Z_solver − Z_ref| ≤ ε_Z", STATUS_SKIP,
            "未提供解 ⇒ 本轮没检查。**SKIP ≠ PASS**。",
        ))
    elif reference is None:
        checks.append(VerifierCheck(
            SCOPE, "SV-13 参考对照 |Z_solver − Z_ref| ≤ ε_Z",
            STATUS_BLOCKED,
            "有解但未提供独立参考实现给出的 Z_ref（owner = T04-08，"
            "当前 NOT_STARTED）⇒ 「业务利润是否正确」这一族**没检查成**。"
            "禁止用本层自算的业务式顶替——那与 CC-07 同源，构成恒真式。",
            actual=None, expected="T04-08 的 Z_ref",
        ))
    else:
        recomputed = (
            model.objective_constant
            + sum(v.objective_coeff * float(x.get(v.symbol, 0.0))
                  for v in model.variables)
        )
        eps_abs_v = tolerances.get(EPS_Z_ABS_NAME)
        eps_price_v = tolerances.get(EPS_Z_REL_NAME)
        if eps_abs_v is None or eps_price_v is None:
            checks.append(VerifierCheck(
                SCOPE, "SV-13 参考对照 |Z_solver − Z_ref| ≤ ε_Z", STATUS_BLOCKED,
                "ε_Z 的组成项解析不出。",
            ))
        else:
            eps_z = float(eps_abs_v) + float(eps_price_v) * max(
                abs(recomputed), abs(float(reference)))
            delta = recomputed - float(reference)
            checks.append(VerifierCheck(
                SCOPE, "SV-13 参考对照 |Z_solver − Z_ref| ≤ ε_Z",
                STATUS_PASS if abs(delta) <= eps_z else STATUS_FAIL,
                (f"Z_solver {recomputed:g} vs Z_ref {float(reference):g}"
                 f"（Δ={delta:g} ≤ ε_Z={eps_z:g}）"
                 if abs(delta) <= eps_z else
                 f"Δ={delta:g} > ε_Z={eps_z:g} ⇒ 两条路径目标值不一致，"
                 "须查共因错误或实现走样"),
                actual=recomputed, expected=float(reference), delta=delta,
            ))

    return VerificationReport(
        spec_id=str(spec.get("spec_id", "")),
        verdict=_aggregate(checks),
        checks=tuple(checks),
        rows=rows,
        bounds=bounds,
        tiers=tiers,
        tier_distribution=dist,
        objective=obj,
        tolerances=tuple((k, tolerances.get(k)) for k in sorted(tolerances)),
    )
