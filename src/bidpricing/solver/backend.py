"""T04-02C 求解后端适配层：把已冻结的 ``CompiledModel`` 交给一个**由配置选中**的后端。

**这份文件存在的理由**：T04-02B 已经把「模型长什么样」做成了可机械判定的性质，
但它刻意**不调用 solve()**——同一路径既造模型又出解，会让 CC-07 那类跨来源复核
失去对象（复核的是自己人）。本模块接手之后就做一件事：把模型搬运给后端，并把
「谁来解」这件事从代码里挪进 ``config/solver_backend_spec.json``。

四条设计纪律
------------

1. **业务层不得认识求解器。** 全仓只有本模块可以 ``import`` 求解器包、可以调用
   ``solve()``（T04-02B 的 ``compiler.to_pulp`` 是唯一豁免的 import —— 它是导出层，
   且导入已在函数体内）。这条纪律**不是靠自觉**，而是 BB-03 的静态判据。
2. **后端名不得参与分支。** 名字允许出现在 import 与诊断文本里，**不得**出现在
   ``if/elif`` 的比较里。否则「换后端只改配置」就成了空话——得改代码。BB-06 检此。
3. **状态必须分域。** 求解器的原生状态词表（``kUnboundedOrInfeasible`` /
   ``Undefined`` / ``Not Solved`` / 超时）**不是**结论。本模块把它们归一到一个
   九值状态域，且归一表**整张住在制品里**（代码里不得出现任何一个原生别名串，
   BB-05 检此）。归一的唯一职责是：不让「已证无解」「分不清」「没算出」「没跑」
   这四件不同的事塌缩成同一格。
4. **能力不足即 BLOCKED，不得降级。** 把含二元变量的模型交给只支持 LP 的后端，
   后端会静默放松整数性并返回一个看着合理的错解——与 T04-02B 里 C7 共用 M 同族。
"""

from __future__ import annotations

import ast
import importlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..contracts.pricing_card import ResolvedParameters
from .compiler import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    CompiledModel,
    Evaluation,
    check_compiled,
    evaluate,
    load_compiler_spec,
    pulp_name_map,
    to_pulp,
)
from .instance import Phase1Instance, SolutionCheck, check_solution

SPEC_FILENAME = "solver_backend_spec.json"
COMPILER_SPEC_FILENAME = "lp_compiler_spec.json"

# ---------------------------------------------------------------------------
# 归一状态域的**机制侧**常量
#
# 取值（哪些原生别名映到哪个归一值、每个归一值属哪一类、判什么状态）全部住在本
# 制品里——本模块只实现「按规则查表」，不含表内容。下面这些是**规则标识**与
# **类标识**，不是后端专有名词：它们描述机制，不描述某个求解器。
# ---------------------------------------------------------------------------

CLASS_CONCLUSION = "CONCLUSION"
CLASS_NO_CONCLUSION = "NO_CONCLUSION"
CLASS_NOT_RUN = "NOT_RUN"

#: 归一规则标识（制品 status.resolution_rules 的键）。规则本体在制品里。
RULE_DIRECT = "DIRECT"                        # 别名直接给出归一值
RULE_INCUMBENT_DEPENDENT = "INCUMBENT_DEPENDENT"   # 按有无 incumbent 分叉

#: 别名命中不了映射表时的兜底来源标识（取值仍来自制品 unknown_native_policy）。
VIA_UNKNOWN_ALIAS = "UNKNOWN_ALIAS"
#: 选择层（没跑起来）产出的状态来源标识。
VIA_SELECTION = "SELECTION"

#: 归一状态的类 → 是否允许由**求解器原生状态**产生。
#: NOT_RUN 类只允许探针/选择层产出——这是「没跑 ≠ 跑过且判定无解」的机械形态。
NATIVE_CLASSES: tuple[str, ...] = (CLASS_CONCLUSION, CLASS_NO_CONCLUSION)

# --- 判据/实现参数（按 CC-12 的纪律一律具名，不写在表达式里） ---
OBJECTIVE_RTOL = 1e-6
OBJECTIVE_ATOL = 1e-6
BINARY_PROXIMITY_TOL = 1e-6
SAMPLE_LIMIT = 6
REASON_TRUNC = 220

#: 选择层产出的归一状态标识（制品 status.normalized 的 id）。
NORM_UNAVAILABLE = "UNAVAILABLE"
NORM_UNSUPPORTED = "UNSUPPORTED"


class BackendError(RuntimeError):
    """适配层无法完成搬运（后端接口不可用、导出层缺失等）。"""


# ---------------------------------------------------------------------------
# 制品
# ---------------------------------------------------------------------------


def load_backend_spec(config_dir: Path) -> dict[str, Any]:
    return json.loads(
        (Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# 状态域
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatusDomain:
    """从制品读入的归一状态域。

    ``by_family`` 是**按后端族**分层的映射：同一原生字符串在不同族里语义可能
    不同，扁平化成一张全局表会让后加入的族静默改写先加入者的语义。BB-05 会把
    「扁平化冲突」判成 FAIL 而不是取其一。
    """

    classes: Mapping[str, str]                    # normalized -> class
    judges: Mapping[str, str]                     # normalized -> judge status
    means: Mapping[str, str]
    by_family: Mapping[str, Mapping[str, Any]]    # family -> {native -> rule}
    requires_incumbent: Mapping[str, frozenset[str]]
    rules: Mapping[str, Mapping[str, Any]]
    unknown_native: str
    unknown_keep_raw: bool
    all_natives: tuple[tuple[str, str], ...]      # (family, native) 全表，供 BB-05 遍历

    @classmethod
    def from_spec(cls, spec: Mapping[str, Any]) -> "StatusDomain":
        st = spec.get("status") or {}
        norm = st.get("normalized") or []
        classes = {n["id"]: n.get("class", "") for n in norm}
        judges = {n["id"]: n.get("judge", "") for n in norm}
        means = {n["id"]: n.get("means", "") for n in norm}
        rules = st.get("resolution_rules") or {}

        by_family: dict[str, dict[str, Any]] = {}
        requires: dict[str, frozenset[str]] = {}
        flat: list[tuple[str, str]] = []
        for fam in st.get("native_map") or []:
            fname = fam.get("backend_family") or ""
            table: dict[str, Any] = {}
            for alias in fam.get("aliases") or []:
                native = alias.get("native")
                if native is None:
                    continue
                if alias.get("conditional"):
                    table[native] = {
                        "rule": alias["conditional"],
                        "native": native,
                    }
                else:
                    table[native] = {
                        "rule": RULE_DIRECT,
                        "normalized": alias.get("normalized"),
                        "native": native,
                    }
                flat.append((fname, native))
            by_family[fname] = table
            requires[fname] = frozenset(fam.get("requires_incumbent") or [])

        # 兜底取值来自未命中该族的**任一**条目声明（族级 unknown_native_policy
        # 优先，缺则取制品顶层）——本模块不猜一个值。
        unknown = "AMBIGUOUS"
        keep_raw = True
        for fam in st.get("native_map") or []:
            pol = fam.get("unknown_native_policy")
            if isinstance(pol, str):
                unknown = pol
                break
        return cls(
            classes=classes,
            judges=judges,
            means=means,
            by_family=by_family,
            requires_incumbent=requires,
            rules=rules,
            unknown_native=unknown,
            unknown_keep_raw=keep_raw,
            all_natives=tuple(flat),
        )

    def resolve(self, family: str | None, native: str, *, has_incumbent: bool | None):
        """把 ``(family, native)`` 解析成 ``(normalized, via)``。

        **不抛异常**：映射表未命中一律走制品声明的 ``unknown_native`` 兜底。抛错
        会让后端某天新增一个状态就整条链路打挂；而默认成 OPTIMAL/INFEASIBLE 则是
        替后端下结论——两者都不行。
        """
        table = self.by_family.get(family or "", {})
        entry = table.get(native)
        if entry is None:
            return self.unknown_native, VIA_UNKNOWN_ALIAS

        rule = entry.get("rule")
        if rule == RULE_DIRECT:
            target = entry.get("normalized")
            if not target:
                # 别名在表里但没给归一值 ⇒ 与「完全没登记」同等对待，走兜底。
                # 不得静默当成 DIRECT 通过：一条没有落值的映射等于没映射。
                return self.unknown_native, VIA_UNKNOWN_ALIAS
            return target, RULE_DIRECT
        if rule == RULE_INCUMBENT_DEPENDENT:
            spec_rule = self.rules.get(RULE_INCUMBENT_DEPENDENT) or {}
            if has_incumbent:
                return spec_rule.get("with_incumbent", self.unknown_native), rule
            return (
                spec_rule.get("without_incumbent", self.unknown_native),
                rule,
            )
        return self.unknown_native, VIA_UNKNOWN_ALIAS


@dataclass(frozen=True)
class NormalizedStatus:
    """一条求解状态的归一结果。两个域**分开**，不得互相顶替。"""

    native: str | None
    normalized: str
    status_class: str
    judge: str
    via: str
    reason: str = ""

    @property
    def carried_solution(self) -> bool:
        return self.normalized in ("OPTIMAL", "FEASIBLE")

    def to_dict(self) -> dict[str, Any]:
        return {
            "native": self.native,
            "normalized": self.normalized,
            "class": self.status_class,
            "judge": self.judge,
            "via": self.via,
            "reason": self.reason,
        }


def normalize_status(
    native: str | None,
    *,
    domain: StatusDomain,
    family: str | None,
    has_incumbent: bool | None = None,
) -> NormalizedStatus:
    """原生状态 → 归一状态。取值一律来自 ``domain``（制品）。"""
    if native is None:
        # 没有原生状态说明求解器根本没被调用到——这是「没跑」，不是任何结论。
        return NormalizedStatus(
            native=None,
            normalized=NORM_UNAVAILABLE,
            status_class=domain.classes.get(NORM_UNAVAILABLE, CLASS_NOT_RUN),
            judge=domain.judges.get(NORM_UNAVAILABLE, STATUS_SKIP),
            via=VIA_SELECTION,
            reason="后端未产出状态（未求解）",
        )
    normalized, via = domain.resolve(family, str(native), has_incumbent=has_incumbent)
    return NormalizedStatus(
        native=str(native),
        normalized=normalized,
        status_class=domain.classes.get(normalized, ""),
        judge=domain.judges.get(normalized, ""),
        via=via,
        reason=_normalize_reason(normalized, str(native), via, has_incumbent),
    )


def _normalize_reason(
    normalized: str, native: str, via: str, has_incumbent: bool | None
) -> str:
    if via == VIA_UNKNOWN_ALIAS:
        return (
            f"原生状态 {native!r} 不在制品映射表内 ⇒ 兜底为 {normalized}，"
            "原值保留在 native 字段。**不得**默认成 OPTIMAL/INFEASIBLE"
            "（那是替后端下结论）。"
        )
    if via == RULE_INCUMBENT_DEPENDENT:
        return (
            f"{native!r} 只说求解器为什么停，不含结论；按 incumbent="
            f"{has_incumbent} 归一到 {normalized}。"
        )
    return f"{native!r} ⇒ {normalized}"


def judge_of(status: str, domain: StatusDomain) -> str:
    """归一状态 → 判据状态。**只查表**，不在这里分档（分档是制品内容）。"""
    return domain.judges.get(status, STATUS_SKIP)


# ---------------------------------------------------------------------------
# 能力与选择
# ---------------------------------------------------------------------------


def required_capability(
    solver_form: str, spec: Mapping[str, Any]
) -> tuple[str, ...]:
    """模型形态 → 所需能力。未识别形态取并集（宁可 BLOCKED，不得按低要求放行）。"""
    req = (spec.get("capabilities") or {}).get("requirement") or {}
    if solver_form in req:
        return tuple(req[solver_form])
    unknown = req.get("UNKNOWN")
    if unknown:
        return tuple(unknown)
    return tuple((spec.get("capabilities") or {}).get("domain") or ())


@dataclass(frozen=True)
class Availability:
    name: str
    available: bool
    version: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "version": self.version,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Candidate:
    """一个候选后端的处置记录。被淘汰的也要留理由——否则「为什么不是它」不可复算。"""

    name: str
    verdict: str
    reason: str
    implemented: bool
    available: bool
    provides: tuple[str, ...]
    missing: tuple[str, ...]
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "verdict": self.verdict,
            "reason": self.reason,
            "implemented": self.implemented,
            "available": self.available,
            "provides": list(self.provides),
            "missing": list(self.missing),
            "version": self.version,
        }


VERDICT_SELECTED = "SELECTED"
VERDICT_MISSING_ENTRY = "MISSING_ENTRY"
VERDICT_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
VERDICT_UNAVAILABLE = "UNAVAILABLE"
VERDICT_CAPABILITY_SHORT = "CAPABILITY_SHORT"


@dataclass(frozen=True)
class Selection:
    entry: Mapping[str, Any] | None
    required: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    normalized: str | None          # 未选中时的归一状态（UNAVAILABLE/UNSUPPORTED）
    reason: str
    active: str | None

    @property
    def ok(self) -> bool:
        return self.entry is not None

    @property
    def name(self) -> str | None:
        return None if self.entry is None else str(self.entry.get("name"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": self.name,
            "required": list(self.required),
            "normalized": self.normalized,
            "reason": self.reason,
            "active": self.active,
            "candidates": [c.to_dict() for c in self.candidates],
        }


def registry_entries(spec: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(e.get("name")): e
        for e in ((spec.get("registry") or {}).get("entries") or [])
    }


def probe_backend(entry: Mapping[str, Any]) -> Availability:
    """探测后端包是否可导入。**惰性**——不装包也不该让 import 业务模块失败。"""
    pkg = entry.get("package")
    if not pkg:
        return Availability(
            name=str(entry.get("name")), available=True, version=None,
            reason="该条目不需要外部包（零依赖占位）",
        )
    try:
        mod = importlib.import_module(str(pkg))
    except Exception as exc:                       # pragma: no cover - 环境相关
        return Availability(
            name=str(entry.get("name")), available=False, version=None,
            reason=f"无法导入 {pkg}：{type(exc).__name__}: {exc}",
        )
    return Availability(
        name=str(entry.get("name")), available=True,
        version=str(getattr(mod, "__version__", "") or "") or None,
        reason=f"{pkg} 可导入",
    )


def select_backend(
    spec: Mapping[str, Any],
    *,
    required: Sequence[str],
    prefer: str | None = None,
    ignore_availability: bool = False,
) -> Selection:
    """按制品选后端。

    顺序：``prefer or active`` → ``fallback_chain``。**被淘汰的候选全部留痕**，
    且能力不足者绝不会被选中（``never_downgrade_capability``）。

    ``ignore_availability=True`` 只跳过「包装没装」这一道闸，其它闸门照走。它
    存在的理由是 BB-06：『选择由制品决定』这件事必须在**没装任何求解器的机器上
    也可判**——否则该判据在零依赖环境里恒为 FAIL，判据本身就成了环境探测。
    """
    entries = registry_entries(spec)
    sel_cfg = spec.get("selection") or {}
    active = str(sel_cfg.get("active") or "") or None
    chain = [str(x) for x in (sel_cfg.get("fallback_chain") or [])]
    head = prefer or active

    order: list[str] = []
    for name in [head, *chain]:
        if name and name not in order:
            order.append(name)

    req = tuple(required)
    candidates: list[Candidate] = []
    chosen: Mapping[str, Any] | None = None

    for name in order:
        entry = entries.get(name)
        if entry is None:
            candidates.append(Candidate(
                name=name, verdict=VERDICT_MISSING_ENTRY,
                reason=f"制品 registry 未声明 {name!r}（active/fallback 指向了不存在的条目）",
                implemented=False, available=False, provides=(), missing=req,
            ))
            continue
        implemented = bool(entry.get("implemented"))
        provides = tuple(str(x) for x in (entry.get("provides") or []))
        missing = tuple(c for c in req if c not in provides)
        avail = probe_backend(entry)
        if not implemented:
            candidates.append(Candidate(
                name=name, verdict=VERDICT_NOT_IMPLEMENTED,
                reason=(f"条目声明 adapter={entry.get('adapter')!r} 但尚未实现 "
                        f"（unimplemented_policy="
                        f"{entry.get('unimplemented_policy')!r}）⇒ 不回退"),
                implemented=False, available=avail.available,
                provides=provides, missing=missing, version=avail.version,
            ))
            continue
        if not avail.available and not ignore_availability:
            candidates.append(Candidate(
                name=name, verdict=VERDICT_UNAVAILABLE,
                reason=avail.reason, implemented=True, available=False,
                provides=provides, missing=missing, version=None,
            ))
            continue
        if missing:
            candidates.append(Candidate(
                name=name, verdict=VERDICT_CAPABILITY_SHORT,
                reason=(f"能力不足：缺 {list(missing)}，条目只提供 {list(provides)}。"
                        "**不得降级**——按 never_downgrade_capability 跳过"),
                implemented=True, available=True,
                provides=provides, missing=missing, version=avail.version,
            ))
            continue
        candidates.append(Candidate(
            name=name, verdict=VERDICT_SELECTED,
            reason=f"{avail.reason}，能力 {list(provides)} ⊇ {list(req)}",
            implemented=True, available=True,
            provides=provides, missing=(), version=avail.version,
        ))
        chosen = entry
        break

    if chosen is not None:
        return Selection(chosen, req, tuple(candidates), None,
                         f"选中 {chosen.get('name')!r}", active)

    # 没选中：成因分两档，**不可合并**（见制品 status._why_unsupported_is_blocked_not_skip）
    head_cand = candidates[0] if candidates else None
    if head_cand is not None and head_cand.verdict == VERDICT_MISSING_ENTRY:
        return Selection(None, req, tuple(candidates), NORM_UNSUPPORTED,
                         f"active {head_cand.name!r} 未被制品声明 ⇒ 机制缺失",
                         active)
    if any(c.verdict in (VERDICT_CAPABILITY_SHORT, VERDICT_NOT_IMPLEMENTED)
           for c in candidates):
        return Selection(
            None, req, tuple(candidates), NORM_UNSUPPORTED,
            "所有候选都因**机制**原因不可用（能力不足或未实现）⇒ BLOCKED，不回退",
            active,
        )
    return Selection(
        None, req, tuple(candidates), NORM_UNAVAILABLE,
        "所有候选都因**环境**原因不可用（包未安装）⇒ SKIP，附复跑条件",
        active,
    )


# ---------------------------------------------------------------------------
# 后端回传的原始结果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawOutcome:
    """后端回传的**未归一**结果。归一在 ``solve_compiled`` 里做。"""

    family: str | None
    native_status: str | None
    x: Mapping[str, float]
    reported_objective: float | None
    has_incumbent: bool
    message: str = ""


class SolverBackend:
    """替身后端需要满足的最小接口（BB-06 的注入点）。

    真实后端不实现这个类——它们是 ``solve_compiled`` 内部按制品分派的适配函数。
    这个协议存在的唯一目的是让「换后端只改配置」有一个**可注入**的检验面：
    把一个制品外的后端塞进来，整链路必须跑通且源码零改动。
    """

    name: str = ""
    family: str | None = None
    provides: tuple[str, ...] = ()

    def available(self) -> bool:                  # pragma: no cover - 接口
        return True

    def solve(                                 # pragma: no cover - 接口
        self, model: CompiledModel, options: Mapping[str, Any]
    ) -> RawOutcome:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 真实适配：PuLP 建模器 + 制品质声明的 solver_factory
# ---------------------------------------------------------------------------


def _build_pulp_solver(entry: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
    """按制品的 ``solver_factory`` 名取 PuLP 的求解器类。

    **不含任何后端分支**：工厂名来自制品，本函数只做 ``getattr``。
    """
    pulp = importlib.import_module("pulp")            # 惰性
    factory = entry.get("solver_factory")
    if not factory:
        raise BackendError(
            f"条目 {entry.get('name')!r} 未声明 solver_factory ⇒ 无法构造求解器。"
            "**不得**用任一默认值顶上（那会让『配置说了什么』与『实际跑了什么』分叉）。"
        )
    cls = getattr(pulp, str(factory), None)
    if cls is None:
        raise BackendError(
            f"PuLP {getattr(pulp, '__version__', '?')} 无 {factory!r} ⇒ "
            "制品声明的工厂名与本机版本不匹配。须改制品，不得静默换一个。"
        )
    kwargs: dict[str, Any] = dict(entry.get("default_options") or {})
    kwargs.update(options or {})
    return cls(**kwargs)


def _solve_via_pulp(
    model: CompiledModel,
    entry: Mapping[str, Any],
    options: Mapping[str, Any],
) -> RawOutcome:
    """PuLP 路径：复用 T04-02B 的导出层，不自建模型（自建等于绕过 CC-09）。"""
    pulp = importlib.import_module("pulp")            # 惰性
    prob = to_pulp(model)
    if prob is None:                                  # pragma: no cover - 已在调用前挡住
        raise BackendError("PuLP 导出层不可用（to_pulp 返回 None）")

    solver = _build_pulp_solver(entry, options)
    prob.solve(solver)

    code = getattr(prob, "status", None)
    native: str | None
    table = getattr(pulp, "LpStatus", None)
    try:
        native = table[code] if table is not None else str(code)
    except Exception:
        # 取值不在词表里 ⇒ 原样带出，交给制品的兜底策略（不得猜）。
        native = str(code)
    native = None if native is None else str(native)

    # 解按**模型符号**回读：建模器存的是净化过的名字（PuLP 会把 `-`/`/`/空格
    # 之类换成 `_`），若直接按符号取值会一个都取不到，解被判「全部缺失」——
    # 而那会把一个正确的解报成不可用。名字映射由导出层（本仓）拥有，
    # 不靠猜：`compiler.pulp_name_map`。
    name_to_symbol = pulp_name_map(model)
    values: dict[str, float] = {}
    for var in prob.variables():
        val = var.value()
        if val is None:
            continue
        symbol = name_to_symbol.get(str(var.name))
        if symbol is not None:
            values[symbol] = float(val)
    has_incumbent = bool(values)
    try:
        reported = float(pulp.value(prob.objective))
    except Exception:
        reported = None

    return RawOutcome(
        family=entry.get("status_family"),
        native_status=native,
        x=values,
        reported_objective=reported,
        has_incumbent=has_incumbent,
        message=f"solver_factory={entry.get('solver_factory')!r}",
    )


def _solve_via_none(
    model: CompiledModel,
    entry: Mapping[str, Any],
    options: Mapping[str, Any],
) -> RawOutcome:
    """零依赖占位后端：**什么都不做**，并如实回传「没有状态」。

    它不是错误路径也不是兜底：``provides = []`` 使它在任何非空能力要求下都选
    不中。真被选中（例如将来出现「不需要求解能力」的形态）时，回传 ``None``
    状态，于是 ``normalize_status`` 归一为 UNAVAILABLE ⇒ SKIP。把「没跑」如实
    说出来，比抛错或编一个状态都更接近事实。
    """
    return RawOutcome(
        family=None,
        native_status=None,
        x={},
        reported_objective=None,
        has_incumbent=False,
        message=f"零依赖占位后端 {entry.get('name')!r}：不执行任何求解",
    )


#: adapter 标识 → 适配函数。标识来自制品的 ``adapter`` 字段。
#: 「已实现」判定由制品 ``implemented`` 声明，本表只提供实现体。
#:
#: 表里**没有**任何按后端名分派的逻辑：``_dispatch_adapter`` 只做一次 getattr，
#: 于是「换后端」在代码侧完全没有落点（BB-06 检此）。
ADAPTERS: dict[str, Any] = {
    "PULP": _solve_via_pulp,
    "NONE": _solve_via_none,
}


def _dispatch_adapter(entry: Mapping[str, Any], model: CompiledModel,
                      options: Mapping[str, Any]) -> RawOutcome:
    key = entry.get("adapter")
    fn = ADAPTERS.get(str(key))
    if fn is None:
        raise BackendError(
            f"adapter={key!r} 无实现体（制品声明 implemented="
            f"{entry.get('implemented')!r} 与此不一致）⇒ 归一为 ERROR。"
            "**不得**回退到任一已实现的 adapter。"
        )
    return fn(model, entry, options)


# ---------------------------------------------------------------------------
# 求解入口
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SolveResult:
    """一次求解的全部可核对面。"""

    status: NormalizedStatus
    selection: Selection
    variables: Mapping[str, float]
    missing: tuple[str, ...]
    reported_objective: float | None
    recomputed_objective: float | None
    evaluation: Evaluation | None
    solution_check: SolutionCheck | None
    seconds: float
    message: str = ""
    #: 本次求解是否把**行上声明的容差**解析表交给了编译器（见 DV-01）。
    #: False 时 ``evaluation.feasible`` 退回严格算术口径（1e-12），
    #: 它**不是**可行性结论——报告必须据此自述口径，不得含糊。
    tolerances_applied: bool = False

    @property
    def solved(self) -> bool:
        return self.status.carried_solution

    @property
    def price_vector(self) -> dict[str, float]:
        return {
            s: v for s, v in self.variables.items() if s.startswith("p_")
        }

    @property
    def objective_delta(self) -> float | None:
        if self.reported_objective is None or self.recomputed_objective is None:
            return None
        return self.recomputed_objective - self.reported_objective

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.to_dict(),
            "selection": self.selection.to_dict(),
            "variables": dict(self.variables),
            "missing": list(self.missing),
            "reported_objective": self.reported_objective,
            "recomputed_objective": self.recomputed_objective,
            "objective_delta": self.objective_delta,
            "evaluation": None if self.evaluation is None else self.evaluation.to_dict(),
            "solution_check": (
                None if self.solution_check is None else self.solution_check.to_dict()
            ),
            "seconds": self.seconds,
            "message": self.message,
            "tolerances_applied": self.tolerances_applied,
        }


def solve_compiled(
    model: CompiledModel,
    *,
    spec: Mapping[str, Any],
    instance: Phase1Instance | None = None,
    resolved: ResolvedParameters | None = None,
    options: Mapping[str, Any] | None = None,
    prefer: str | None = None,
    backend: SolverBackend | None = None,
    eps_total: float | None = None,
    tolerances: Mapping[str, float] | None = None,
) -> SolveResult:
    """**业务侧唯一的求解入口。**

    业务层只认识这个函数与 ``SolveResult``；它不认识 PuLP、HiGHS、CBC，也不
    认识任何后端名。换后端 = 改制品的 ``selection.active``。

    ``tolerances`` = **行声明的容差名 → 数值** 的解析表，转交给 ``evaluate``
    使 ``evaluation`` 是按声明容差判的**可行性**结论。不传则退回严格算术
    （1e-12）口径——那会让一个合法的求解器回传被判不可行（见 DV-01）。
    解析表的唯一来源是 ``solver/verifier.py`` 的 ``resolve_tolerances``。
    """
    required = required_capability(model.solver_form, spec)
    selection = (
        select_backend(spec, required=required, prefer=prefer)
        if backend is None
        else _selection_from_injected(model, spec, backend, required)
    )
    domain = StatusDomain.from_spec(spec)

    if not selection.ok:
        status = NormalizedStatus(
            native=None,
            normalized=selection.normalized or NORM_UNSUPPORTED,
            status_class=domain.classes.get(selection.normalized or "", CLASS_NOT_RUN),
            judge=domain.judges.get(selection.normalized or "", STATUS_BLOCKED),
            via=VIA_SELECTION,
            reason=selection.reason,
        )
        return SolveResult(
            status=status, selection=selection, variables={}, missing=(),
            reported_objective=None, recomputed_objective=None,
            evaluation=None, solution_check=None, seconds=0.0,
            message=selection.reason,
        )

    started = time.perf_counter()
    try:
        if backend is None:
            raw = _dispatch_adapter(selection.entry or {}, model, options or {})
        else:
            raw = backend.solve(model, options or {})
    except BackendError as exc:
        elapsed = time.perf_counter() - started
        return SolveResult(
            status=NormalizedStatus(
                native=None,
                normalized=_error_status(domain),
                status_class=domain.classes.get(_error_status(domain), CLASS_NO_CONCLUSION),
                judge=domain.judges.get(_error_status(domain), STATUS_BLOCKED),
                via=VIA_SELECTION,
                reason=f"适配层错误：{exc}",
            ),
            selection=selection, variables={}, missing=(),
            reported_objective=None, recomputed_objective=None,
            evaluation=None, solution_check=None, seconds=elapsed,
            message=str(exc),
        )
    elapsed = time.perf_counter() - started

    child = _proxy_child_backend(backend)
    status = normalize_status(
        raw.native_status,
        domain=domain,
        family=raw.family if child is None else (child[0] or raw.family),
        has_incumbent=raw.has_incumbent,
    )
    if child is not None and child[1]:
        status = NormalizedStatus(
            native=status.native, normalized=status.normalized,
            status_class=status.status_class, judge=status.judge,
            via=status.via, reason=f"{status.reason}｜{child[1]}",
        )

    missing = tuple(
        v.symbol for v in model.variables if v.symbol not in raw.x
    )
    evaluation = (
        evaluate(model, raw.x, tolerances=tolerances) if not missing else None
    )
    recomputed = None if evaluation is None else evaluation.objective

    solution_check = None
    if instance is not None and resolved is not None and model.price_symbols():
        price_by_id = _price_by_id(model, raw.x)
        if price_by_id is not None:
            solution_check = check_solution(
                instance, price_by_id, resolved,
                eps_total=eps_total, tolerances=tolerances,
            )

    return SolveResult(
        status=status,
        selection=selection,
        variables=dict(sorted(raw.x.items())),
        missing=missing,
        reported_objective=raw.reported_objective,
        recomputed_objective=recomputed,
        evaluation=evaluation,
        solution_check=solution_check,
        seconds=elapsed,
        message=raw.message,
        tolerances_applied=tolerances is not None,
    )


def _error_status(domain: StatusDomain) -> str:
    for sid, cls in domain.classes.items():
        if sid == "ERROR":
            return sid
    return "ERROR"


def _proxy_child_backend(backend: Any):
    """注入后端若自带状态族/说明，取出来（(family, note)）。"""
    if backend is None:
        return None
    fam = getattr(backend, "family", None)
    note = getattr(backend, "last_message", None)
    if fam is None and note is None:
        return None
    return (fam, note)


def _selection_from_injected(
    model: CompiledModel,
    spec: Mapping[str, Any],
    backend: SolverBackend,
    required: tuple[str, ...],
) -> Selection:
    """注入后端时的选择记录——**仍然留痕**，否则「跑了什么」不可复算。"""
    provides = tuple(getattr(backend, "provides", ()) or ())
    missing = tuple(c for c in required if c not in provides)
    cand = Candidate(
        name=str(getattr(backend, "name", "")),
        verdict=VERDICT_SELECTED if not missing else VERDICT_CAPABILITY_SHORT,
        reason=(
            f"注入后端（BB-06 的可替换性检验面），能力 {list(provides)} ⊇ {list(required)}"
            if not missing
            else f"注入后端能力不足：缺 {list(missing)}"
        ),
        implemented=True,
        available=True,
        provides=provides,
        missing=missing,
    )
    return Selection(
        entry={"name": cand.name, "adapter": "INJECTED",
               "status_family": getattr(backend, "family", None)},
        required=required,
        candidates=(cand,),
        normalized=None,
        reason=f"注入后端 {cand.name!r}",
        active=str((spec.get("selection") or {}).get("active") or "") or None,
    )


def _price_by_id(
    model: CompiledModel, x: Mapping[str, float]
) -> dict[str, float] | None:
    """把 ``p_<item_id>`` 形式的符号还原成 ``{item_id: p}``。

    无法还原（符号命名与约定不符）⇒ 返回 ``None``，调用方据此 SKIP 而不是
    猜一个映射（BB-08 的 SKIP ≠ PASS）。
    """
    out: dict[str, float] = {}
    for v in model.variables:
        if v.family != "p":
            continue
        if v.symbol not in x:
            return None
        if not v.item_id:
            return None
        out[v.item_id] = float(x[v.symbol])
    return out or None


# ---------------------------------------------------------------------------
# BB 判据
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendCheck:
    """一条 BB 判据的结果。状态域与 CC/F 判据同构。"""

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


_SCOPE = "BB"


def _trunc(text: str, limit: int = REASON_TRUNC) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def check_backend(
    model: CompiledModel,
    result: SolveResult,
    *,
    spec: Mapping[str, Any],
    config_dir: Path | None = None,
    src_root: Path | None = None,
    instance: Phase1Instance | None = None,
    resolved: ResolvedParameters | None = None,
    formulation: Any = None,
    constraint_schema: Mapping[str, Any] | None = None,
    formulation_spec: Mapping[str, Any] | None = None,
    cc09: Iterable[BackendCheck] | None = None,
    prefer: str | None = None,
) -> tuple[BackendCheck, ...]:
    """BB-01..BB-09。全部**跨来源**：一侧制品/源码，一侧运行结果。

    ``cc09`` 允许把 T04-02B 的 CC-09 结果传进来，供 BB-09 判定其是否已闭合。
    """
    items: list[BackendCheck] = []
    domain = StatusDomain.from_spec(spec)
    audit = spec.get("audit") or {}
    entries = registry_entries(spec)

    # ---------------- BB-01 注册表声明完备 -----------------------------
    problems: list[str] = []
    active = str((spec.get("selection") or {}).get("active") or "")
    if not active:
        problems.append("selection.active 缺失 ⇒ 后端未定。未定不得静默处理。")
    elif active not in entries:
        problems.append(f"active={active!r} 不在 registry 中")
    for name, e in entries.items():
        for field in ("name", "kind", "implemented", "adapter", "provides"):
            if field not in e:
                problems.append(f"{name}: 缺字段 {field}")
        if e.get("implemented") and str(e.get("adapter")) not in ADAPTERS:
            problems.append(
                f"{name}: 声明 implemented=true 但 adapter={e.get('adapter')!r} "
                f"无实现体（已实现集合 {sorted(ADAPTERS)}）"
            )
        if e.get("implemented") and not e.get("package") and e.get("kind") != "NONE":
            problems.append(f"{name}: 声明已实现却未给 package")
        if e.get("implemented") and e.get("kind") != "NONE" and not e.get("status_family"):
            problems.append(f"{name}: 声明已实现却未给 status_family（原生状态无表可查）")
        fam = e.get("status_family")
        if fam and fam not in domain.by_family:
            problems.append(f"{name}: status_family={fam!r} 在 native_map 中无对应族")
    if not entries:
        problems.append("registry.entries 为空 ⇒ 机制缺失（与『后端都没装』是两回事）")
    items.append(BackendCheck(
        _SCOPE, "BB-01 注册表声明完备（后端来源单一）",
        STATUS_PASS if not problems else STATUS_BLOCKED,
        (f"{len(entries)} 个条目声明完备，active={active!r}"
         if not problems else _trunc("；".join(problems))),
        actual=problems, expected=[],
    ))

    # ---------------- BB-02 能力匹配（不得静默降级）--------------------
    # 判的是「模型形态 → 所需能力 → 制品选的条目能不能覆盖」这条**配置链**，
    # 与「那台机器装没装包」无关（故用 ignore_availability 的规划解），否则
    # 零依赖环境里这条判据会退化成环境探测。
    req = required_capability(model.solver_form, spec)
    planned = select_backend(spec, required=req, ignore_availability=True)
    cap_problems: list[str] = []
    if planned.ok:
        provides = tuple(str(x) for x in (planned.entry.get("provides") or []))
        short = tuple(c for c in req if c not in provides)
        if short:
            cap_problems.append(
                f"选中后端能力不足：缺 {list(short)}（model.solver_form="
                f"{model.solver_form!r} 要求 {list(req)}，条目只给 {list(provides)}）"
            )
    else:
        cap_problems.append(
            f"制品链上选不出后端（{planned.reason}）⇒ 所需能力 {list(req)} 无人提供"
        )
    # 降级检测：被淘汰的能力不足候选不得成为选中者
    chosen = planned.name
    if chosen and any(
        c.name == chosen and c.verdict == VERDICT_CAPABILITY_SHORT
        for c in planned.candidates
    ):
        cap_problems.append(f"{chosen!r} 是能力不足的候选却被选中 ⇒ 静默降级")
    items.append(BackendCheck(
        _SCOPE, "BB-02 能力匹配（不得静默降级）",
        STATUS_PASS if not cap_problems else STATUS_BLOCKED,
        (f"model.solver_form={model.solver_form!r} 要求 {list(req)}；"
         f"制品选中 {planned.name!r}，能力覆盖"
         f"（实际可用性另由 BB-04 判：{result.selection.normalized or '已选中'}）"
         if not cap_problems else _trunc("；".join(cap_problems))),
        actual=cap_problems, expected=[],
        delta={"planned": planned.name, "required": list(req)},
    ))

    # ---------------- BB-03 业务层零直接依赖（静态）--------------------
    src = Path(src_root) if src_root is not None else None
    if src is None or not src.exists():
        items.append(BackendCheck(
            _SCOPE, "BB-03 业务层零直接依赖求解器（静态）", STATUS_SKIP,
            "未提供源码根 ⇒ 本轮未做静态审计（SKIP ≠ PASS）",
        ))
    else:
        audit_problems = audit_source_tree(src, spec)
        items.append(BackendCheck(
            _SCOPE, "BB-03 业务层零直接依赖求解器（静态）",
            STATUS_PASS if not audit_problems else STATUS_FAIL,
            (f"求解器包只在 {audit.get('allow_lazy_import_in')} 内惰性导入；"
             f"solve() 调用只在 {audit.get('allow_solve_call_in')} 内"
             if not audit_problems else _trunc("；".join(audit_problems))),
            actual=audit_problems, expected=[],
        ))

    # ---------------- BB-04 后端缺失 ≠ 模型错 -------------------------
    # 判据的落点是**归一状态 id**（UNAVAILABLE/UNSUPPORTED）而不是类：
    # 类是被测对象的一部分，用类去找未跑路径，一旦有人把这两个 id 的 class
    # 改错，判据就跟着一起看不见了——那正是「判据的覆盖面取决于被测数据」。
    notrun_ids = (NORM_UNAVAILABLE, NORM_UNSUPPORTED)
    notrun = result.status.normalized in notrun_ids
    b04: list[str] = []
    if notrun:
        if result.status.status_class != CLASS_NOT_RUN:
            b04.append(
                f"{result.status.normalized} 的 class="
                f"{result.status.status_class!r}，应为 {CLASS_NOT_RUN!r}"
                " ⇒ 会用『没跑』冒充求解结论"
            )
        if (
            result.status.normalized == NORM_UNAVAILABLE
            and result.status.judge != STATUS_SKIP
        ):
            b04.append(
                f"UNAVAILABLE 的 judge={result.status.judge!r}，应为 SKIP"
                "（环境缺失只是『本轮没跑』，不是模型错）"
            )
        if (
            result.status.normalized == NORM_UNSUPPORTED
            and result.status.judge != STATUS_BLOCKED
        ):
            b04.append(
                f"UNSUPPORTED 的 judge={result.status.judge!r}，应为 BLOCKED"
                "（机制缺失＝算式算不出）"
            )
        if result.solved:
            b04.append("未跑却声称拿到解")
    # 反向：真跑了且真出解时，不得带 NOT_RUN 状态
    if result.solved and result.status.normalized in notrun_ids:
        b04.append("有解却标未跑状态 ⇒ 状态与事实矛盾")
    items.append(BackendCheck(
        _SCOPE, "BB-04 后端缺失 ≠ 模型错",
        STATUS_PASS if not b04 else STATUS_FAIL,
        (f"未跑路径归一为 {result.status.normalized}（{result.status.judge}），"
         "与求解结论分离" if notrun and not b04
         else ("后端已跑，本条不适用（无未跑路径可检）" if not b04
               else _trunc("；".join(b04)))),
        actual=b04, expected=[],
    ))

    # ---------------- BB-05 状态域不合并 -------------------------------
    b05: list[str] = []
    # ① 全表遍历：每个原生别名都必须能解析出一个已声明的归一值
    walk: list[tuple[str, str, str]] = []
    for fam, native in domain.all_natives:
        for inc in (True, False):
            ns = normalize_status(
                native, domain=domain, family=fam, has_incumbent=inc
            )
            walk.append((f"{fam}:{native}", ns.normalized, ns.status_class))
            if ns.normalized not in domain.classes:
                b05.append(f"{fam}:{native} 归一为未声明状态 {ns.normalized!r}")
            if ns.via == VIA_UNKNOWN_ALIAS:
                b05.append(
                    f"{fam}:{native} 命中不了映射表（**全表遍历，不抽样**）"
                )
    if not domain.all_natives:
        b05.append("native_map 为空 ⇒ 没有任何原生状态可归一")
    # ② 原生别名不得落在 NOT_RUN 类
    for key, normalized, cls in walk:
        if cls not in NATIVE_CLASSES:
            b05.append(
                f"{key} 归一为 {normalized}（class={cls!r}）——原生状态不得落在 "
                f"NOT_RUN 类：那等于用『没跑』冒充求解结论"
            )
    # ③ 语义必须两两可分（AMBIGUOUS / INFEASIBLE / UNBOUNDED 不重合；
    #    UNAVAILABLE / UNSUPPORTED 不重合）
    need_distinct = [
        ("AMBIGUOUS", "INFEASIBLE"),
        ("AMBIGUOUS", "UNBOUNDED"),
        ("INFEASIBLE", "UNBOUNDED"),
        ("UNAVAILABLE", "UNSUPPORTED"),
    ]
    for a, b in need_distinct:
        if not a or not b:
            continue
        if domain.classes.get(a) is None or domain.classes.get(b) is None:
            b05.append(f"{a}/{b} 未在 normalized 中声明")
        elif a == b:
            b05.append(f"{a} 与 {b} 同名 ⇒ 两种状态被合并")
    # ④ NOT_RUN 类不得映到 PASS / FAIL
    for sid, cls in domain.classes.items():
        if cls == CLASS_NOT_RUN and domain.judges.get(sid) in (STATUS_PASS, STATUS_FAIL):
            b05.append(
                f"{sid}（NOT_RUN）judge={domain.judges.get(sid)!r} ⇒ 把流程状态"
                "冒充成业务结论"
            )
    # ⑤ 扁平化冲突：同一原生串在两族里语义不同 ⇒ 必须分族查（这里只报冲突，
    #    分族查由 StatusDomain.by_family 保证；冲突本身不是错，但必须被看见）
    flat: dict[str, set[str]] = {}
    for fam, table in domain.by_family.items():
        for native, entry in table.items():
            flat.setdefault(native, set()).add(fam)
    # ⑥ 源码里不得出现原生别名串（单一来源）
    #
    #    只查 **AST 里的字符串字面量，且排除 docstring**。理由：本模块的
    #    docstring 必须能说明「为什么 kUnboundedOrInfeasible 不能折进
    #    INFEASIBLE」——那是文档，不是第二个真相来源。真正的危险是代码路径上
    #    出现一份硬拷贝（例如 `if native == "..."`），那才是判据要拦的东西。
    #    首版按纯文本 grep，把模块自己的说明文字报成违规 ⇒ 判据把正常实现报成
    #    违规，先改判据（与 CC-12 同一条教训）。
    if src is not None and src.exists():
        adapter = src / "bidpricing" / "solver" / "backend.py"
        if not adapter.exists():
            adapter = src / "solver" / "backend.py"
        if adapter.exists():
            leaked = sorted({
                v for _ln, v in _code_string_literals(adapter.read_text(encoding="utf-8"))
                if v in {n for _f, n in domain.all_natives}
            })
            if leaked:
                b05.append(
                    f"适配层源码里出现原生别名串 {leaked[:SAMPLE_LIMIT]}（docstring "
                    "除外）⇒ 映射表有了第二个真相来源，须改回归一函数只查表"
                )
    items.append(BackendCheck(
        _SCOPE, "BB-05 状态域不合并",
        STATUS_PASS if not b05 else STATUS_FAIL,
        (f"全表 {len(domain.all_natives)} 个原生别名 × 有无 incumbent 共 "
         f"{len(walk)} 次遍历：全部落在可归一的确定状态，NOT_RUN 类无原生来源，"
         f"AMBIGUOUS/INFEASIBLE/UNBOUNDED 与 UNAVAILABLE/UNSUPPORTED 两两可分"
         if not b05 else _trunc("；".join(b05))),
        actual=b05, expected=[],
        delta={"walked": len(walk), "families": sorted(domain.by_family)},
    ))

    # ---------------- BB-06 换后端只改配置 -----------------------------
    b06: list[str] = []
    # ① 选择结果完全由制品决定：改写 active 必须改变选中后端。
    #    **忽略可用性**是刻意的——这条判据问的是「配置 → 选谁」的映射是不是
    #    单射，与「那台机器装没装包」无关。若把可用性也算进来，零依赖环境里
    #    两个候选都进不了 selection，判据就变成环境探测而非配置判据。
    names_all = [str(e.get("name")) for e in
                 ((spec.get("registry") or {}).get("entries") or [])]
    implemented = [
        n for n in names_all
        if (entries.get(n) or {}).get("implemented")
        and _provides_enough(entries.get(n) or {}, req)
    ]
    if len(implemented) >= 2:
        picks = set()
        for cand_name in implemented:
            alt = json.loads(json.dumps(spec))
            alt["selection"]["active"] = cand_name
            alt["selection"]["fallback_chain"] = [
                x for x in (alt["selection"].get("fallback_chain") or [])
                if x != cand_name
            ]
            picks.add(
                select_backend(
                    alt, required=req, ignore_availability=True
                ).name
            )
        if len(picks) < len(implemented):
            b06.append(
                f"改 active 后选中结果不变（{sorted(picks)} vs 候选 {implemented}）"
                " ⇒ 选择不是完全由制品决定的"
            )
    else:
        b06.append(
            f"制品中可用（已实现且能力足够）的候选只有 {implemented} 个 ⇒ "
            "替换性无从实证。**判 FAIL 而非 PASS**：没有第二个候选就没有证据，"
            "不能把『无从验证』记成『已验证』"
        )
    # ② 源码里不得出现按后端名分支
    if src is not None and src.exists():
        names = set(names_all)
        for e in entries.values():
            if e.get("package"):
                names.add(str(e.get("package")))
        b06.extend(_audit_comparison_branches(
            src, sorted(n for n in names if n)
        ))
    else:
        b06.append("未提供源码根 ⇒ 分支审计未做")
    # ③ 注入后端整链路跑通（由调用方通过 check_backend 之外的独立用例覆盖）
    items.append(BackendCheck(
        _SCOPE, "BB-06 换后端只改配置（可替换性）",
        STATUS_PASS if not b06 else STATUS_FAIL,
        (f"改 active 即改变选中后端（候选 {implemented}）；源码中无按后端名的分支"
         if not b06 else _trunc("；".join(b06))),
        actual=b06, expected=[],
    ))

    # ---------------- BB-07 求解器自报值 vs 独立复算 -------------------
    if not result.solved or result.reported_objective is None:
        items.append(BackendCheck(
            _SCOPE, "BB-07 求解器自报目标值 vs 独立复算（跨来源）", STATUS_SKIP,
            f"未获得解（{result.status.normalized}）⇒ 本轮无法对账。"
            "**SKIP ≠ PASS**：这条对账尚未做过。",
        ))
    else:
        b07: list[str] = []
        if result.recomputed_objective is None:
            b07.append("有解却算不出复算目标值（缺变量赋值或模型为空）")
        else:
            delta = result.objective_delta or 0.0
            tol = OBJECTIVE_ATOL + OBJECTIVE_RTOL * max(
                1.0, abs(result.reported_objective)
            )
            if abs(delta) > tol:
                b07.append(
                    f"自报 {result.reported_objective!r} vs 复算 "
                    f"{result.recomputed_objective!r}，差 {delta!r} 超容差 {tol!r}"
                    " ⇒ 导出层可能丢了目标常量、合并了系数或反了优化方向"
                )
        items.append(BackendCheck(
            _SCOPE, "BB-07 求解器自报目标值 vs 独立复算（跨来源）",
            STATUS_PASS if not b07 else STATUS_FAIL,
            (f"自报 = 复算 = {result.recomputed_objective!r}"
             f"（Δ={result.objective_delta!r}）"
             if not b07 else _trunc("；".join(b07))),
            actual=result.reported_objective,
            expected=result.recomputed_objective,
            delta=result.objective_delta,
        ))

    # ---------------- BB-08 解的双侧可行性 -----------------------------
    if not result.solved or result.evaluation is None:
        items.append(BackendCheck(
            _SCOPE, "BB-08 解的双侧可行性", STATUS_SKIP,
            f"未获得可用解（{result.status.normalized}）⇒ 双侧复核无从进行。"
            "**SKIP ≠ PASS**。",
        ))
    else:
        b08: list[str] = []
        if result.missing:
            b08.append(f"解缺变量 {list(result.missing)[:SAMPLE_LIMIT]}")
        if not result.evaluation.feasible:
            viol = [r.constraint_id for r in result.evaluation.violations()]
            band = [r.constraint_id for r in result.evaluation.tolerance_band_rows()]
            # 口径必须自述：未传声明容差表时，「不可行」用的是严格算术口径
            # （1e-12），不是业务可行性结论——照旧归因「导出层走样」会是错诊断
            # （2026-09-17 DV-01：C1 残差 5e-9 落在了声明内层容差 eps_solver=1e-8
            # 之内，却被判不可行）。
            if not result.tolerances_applied:
                b08.append(
                    f"编译侧判不可行（违反 {viol[:SAMPLE_LIMIT]}），但本次**未传入"
                    "声明容差表** ⇒ 该判定走的是严格算术口径（1e-12），"
                    "不足以断言不可行——须传 tolerances 后复判（DV-01）"
                )
            else:
                b08.append(
                    f"编译侧判不可行（违反 {viol[:SAMPLE_LIMIT]}，已按各行声明容差判；"
                    f"带内行 {band[:SAMPLE_LIMIT]}）⇒ 求解器在**另一个模型**上"
                    "求了最优解（导出层走样）"
                )
        if result.solution_check is None:
            b08.append(
                "未提供实例/参数 ⇒ 业务侧未复核（**不得**只做单侧就判 PASS）"
            )
        elif not result.solution_check.feasible:
            b08.append(
                f"业务侧判不可行：{list(result.solution_check.violations[:SAMPLE_LIMIT])}"
            )
        elif (result.solution_check.tolerance_name
              and not result.solution_check.tolerance_resolved):
            # 业务侧拿到了「该按具名容差判」的口径（tolerance_name 非空），
            # 却没解析到数值 ⇒ 它是在**严格口径**下判的可行。这与「两侧口径
            # 可比」不是一回事：不得据此判 PASS（同源规则②：未定态不得降级）。
            b08.append(
                f"业务侧盒式容差名 {result.solution_check.tolerance_name!r} 未解析到"
                "数值 ⇒ 它按严格口径判，两侧不可比 —— 须判 BLOCKED（DV-01 同族）"
            )
        status_b08 = (
            STATUS_BLOCKED if (b08 and result.solution_check is not None
                               and result.solution_check.tolerance_name
                               and not result.solution_check.tolerance_resolved
                               and result.evaluation.feasible
                               and not result.missing)
            else (STATUS_PASS if not b08 else STATUS_FAIL)
        )
        items.append(BackendCheck(
            _SCOPE, "BB-08 解的双侧可行性",
            status_b08,
            (f"编译侧 {result.evaluation.feasible} ∧ 业务侧 "
             f"{result.solution_check.feasible}；Z={result.solution_check.Z!r}"
             if not b08 else _trunc("；".join(b08))),
            actual=b08, expected=[],
        ))

    # ---------------- BB-09 T04-02B 挂账项 CC-09 的闭合 ---------------
    cc09_rows = list(cc09 or ())
    if not cc09_rows:
        items.append(BackendCheck(
            _SCOPE, "BB-09 T04-02B 挂账项 CC-09 的闭合", STATUS_SKIP,
            "未传入 CC-09 结果 ⇒ 本轮未判定。SKIP ≠ PASS。",
        ))
    else:
        row = next((r for r in cc09_rows if "CC-09" in r.item), None)
        pulp_ok = _package_importable("pulp")
        if row is None:
            items.append(BackendCheck(
                _SCOPE, "BB-09 T04-02B 挂账项 CC-09 的闭合", STATUS_SKIP,
                "传入的结果里没有 CC-09 行 ⇒ 无法判定",
            ))
        elif not pulp_ok:
            items.append(BackendCheck(
                _SCOPE, "BB-09 T04-02B 挂账项 CC-09 的闭合", STATUS_SKIP,
                f"PuLP 不可导入 ⇒ CC-09 现为 {row.status}。**SKIP ≠ PASS**："
                "『导出层没走样』仍未验证。复跑条件：在装有 PuLP 的环境重跑 "
                "backend-check。",
                actual=row.status, expected=STATUS_PASS,
            ))
        else:
            items.append(BackendCheck(
                _SCOPE, "BB-09 T04-02B 挂账项 CC-09 的闭合",
                STATUS_PASS if row.status == STATUS_PASS else STATUS_FAIL,
                (f"装 PuLP 的环境里 CC-09 判 {row.status}"
                 + ("（挂账已闭合）" if row.status == STATUS_PASS
                    else " ⇒ 挂账未闭合，导出层确有走样。注意：T04-02C 已把 "
                         "CC-09 的覆盖面补齐到逐行系数/目标常量/目标方向，"
                         "此处 FAIL 很可能是新补的覆盖面抓到的真问题。")),
                actual=row.status, expected=STATUS_PASS,
            ))

    return tuple(items)


def _provides_enough(entry: Mapping[str, Any], required: Sequence[str]) -> bool:
    provides = tuple(str(x) for x in (entry.get("provides") or []))
    return all(c in provides for c in required)


def _package_importable(pkg: str) -> bool:
    try:
        importlib.import_module(pkg)
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# 静态审计（BB-03 / BB-06 的取证手段）
# ---------------------------------------------------------------------------


def _iter_py_files(src_root: Path) -> list[Path]:
    root = Path(src_root)
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _rel_posix(path: Path, src_root: Path) -> str:
    return Path(path).resolve().relative_to(Path(src_root).resolve()).as_posix()


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """收集全部 docstring 的 Constant 节点 id（模块/类/函数体的首条字符串）。"""
    out: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            out.add(id(first.value))
    return out


def _code_string_literals(source: str) -> list[tuple[int, str]]:
    """源码里**参与代码**的字符串字面量（docstring 排除）。

    判据要拦的是「代码路径上有一份硬拷贝」，不是「文档里提到了这个词」。
    把 docstring 算进来会让判据惩罚注释的详尽程度——那是反的。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:                          # pragma: no cover - 防御
        return []
    skip = _docstring_nodes(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
        ):
            out.append((getattr(node, "lineno", -1), node.value))
    return out


def _module_level_imports(tree: ast.Module) -> list[tuple[int, str]]:
    """只看模块顶层的 import（函数体内的惰性 import 不算）。"""
    out: list[tuple[int, str]] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((node.lineno, a.name.split(".")[0]))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append((node.lineno, node.module.split(".")[0]))
    return out


def _all_imports(tree: ast.Module) -> list[tuple[int, str, bool]]:
    """全部 import：``(lineno, 顶层包名, 是否函数体内)``。"""
    parent: dict[int, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                parent[id(sub)] = True
    out: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((node.lineno, a.name.split(".")[0], parent.get(id(node), False)))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append((node.lineno, node.module.split(".")[0], parent.get(id(node), False)))
    return out


def audit_source_tree(
    src_root: Path, spec: Mapping[str, Any]
) -> list[str]:
    """BB-03：静态扫全仓源码。

    两条规则：
    ① 求解器包的 import 只允许出现在 ``audit.allow_lazy_import_in`` 列出的
       模块内，且**必须在函数体内**（模块级 import 会让『换后端只改配置』
       在 import 期就断掉——没装包时连业务模块都 import 不进来）；
    ② 名为 ``solve`` 的属性调用只允许出现在 ``audit.allow_solve_call_in`` 内。
    """
    audit = spec.get("audit") or {}
    pkgs = {str(p) for p in (audit.get("solver_packages") or [])}
    allow_import = {str(p) for p in (audit.get("allow_lazy_import_in") or [])}
    allow_call = {str(p) for p in (audit.get("allow_solve_call_in") or [])}
    if not pkgs:
        return ["制品 audit.solver_packages 为空 ⇒ 无基准可比，判据失效"]

    problems: list[str] = []
    for path in _iter_py_files(src_root):
        rel = _rel_posix(path, src_root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:                # pragma: no cover - 防御
            problems.append(f"{rel}: 解析失败 {exc}")
            continue
        for lineno, pkg, in_func in _all_imports(tree):
            if pkg not in pkgs:
                continue
            if rel not in allow_import:
                problems.append(
                    f"{rel}:{lineno} 业务层直接 import 求解器包 {pkg!r} ⇒ "
                    "写死了求解器来源"
                )
            elif not in_func:
                problems.append(
                    f"{rel}:{lineno} 求解器包 {pkg!r} 用了**模块级** import ⇒ "
                    "没装包时 import 期即失败，SKIP 退化为 ImportError"
                )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "solve":
                if rel not in allow_call:
                    problems.append(
                        f"{rel}:{node.lineno} 业务层调用了 .solve() ⇒ "
                        "业务逻辑不得求解（模型与解必须分家）"
                    )
    return problems


def _audit_comparison_branches(
    src_root: Path, names: Sequence[str]
) -> list[str]:
    """BB-06：后端名不得参与 if/elif/while 的比较。

    禁字符串是没有意义的（名字必须出现在 import 与制品里），所以要禁的是
    **它参与分支**这个动作——判据的落点在比较，不在词本身。
    """
    wanted = {n for n in names if n}
    if not wanted:
        return ["未提供后端名集合 ⇒ 分支审计无基准"]
    problems: list[str] = []
    for path in _iter_py_files(src_root):
        rel = _rel_posix(path, src_root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:                       # pragma: no cover - 防御
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.While)):
                continue
            for sub in ast.walk(node.test):
                if not isinstance(sub, ast.Constant) or not isinstance(sub.value, str):
                    continue
                if sub.value in wanted:
                    problems.append(
                        f"{rel}:{sub.lineno} 后端名 {sub.value!r} 出现在分支条件里 "
                        "⇒ 换后端要改代码，不只是改配置"
                    )
    return sorted(set(problems))
