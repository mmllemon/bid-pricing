"""T03-02 派生量计算：``L_i`` / ``U_i`` / ``floor_i`` / ``r_eff_i`` 的**唯一实现**。

**为什么单独一层**：T04-02A 落地时 ``floor_i`` 缺席，编译层只能以 ``floor_by_id``
入参占位（当时的注释：「缺省表示尚未接入，此时不得用 c_i 或 L_i 冒充地板」）。
占位的问题双向：编译侧看起来已接上，判定侧（T03-04）又会各自硬编码 C3/C4 的
阈值 ⇒ 同一个地板出现**两个真相来源**，两侧各自自洽地错着、永远撞不上。

本层只做三件事：**取大 / 取小 / 委派**。不做优化、不做判定、不做诊断。
把「算不出」表达为**具名理由**（``DerivedCheck``），而不是默认值。

★ 三条容易静默出错的地方，都在本层用判据守住：

1. **空 cap 不是 0**（DQ-03 / DQ-05）：``cap`` 为空是合法语义「不限价」。
   把它折成 0 会把可行解变不可行；在 ACCEPT 钳制里把它当 0 则会把地板
   静默压到 0（地板失效，且不报错）。
2. **未定态不得降级**（DQ-01 / DQ-09）：``mu`` 的 key 缺失与 ``mu = 0`` 是
   两件事（ADR-0004）。前者 ⇒ BLOCKED，后者 ⇒ 合法的严格地板。
3. **委派而非重实现**（DQ-08）：``r_eff`` 的唯一实现是
   ``contracts/pricing_card.compute_r_eff``。本模块**不得**调用
   ``settlement_revenue`` —— 那等于自造 ``dR/dp``。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts.pricing_card import ResolvedParameters

#: 判据范围前缀（与 CC / BB / SV / EC 并列）。
SCOPE = "DQ"

SPEC_FILENAME = "derived_quantities_spec.json"

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_SKIP = "SKIP"

#: 聚合序：取最严。BLOCKED 排在 WARN 之前，因为「算不出」会让下游所有
#: 结论失去依据，而 WARN 至少还有一个成立的值。
_STATUS_ORDER = (STATUS_FAIL, STATUS_BLOCKED, STATUS_WARN, STATUS_SKIP, STATUS_PASS)

#: ``loss_acceptance`` 的取值域（selection_options.LOSS_ACCEPTANCE）。
LOSS_ACCEPT = "ACCEPT"
LOSS_DECLINE = "DECLINE"

#: 不平衡报价条款的基准取值（field_schema.unbalanced_reference）。
REF_CAP = "CAP"

#: 本模块**禁止**出现的符号：它是 R_i 的实现，调用它即可自造 ``dR/dp``。
FORBIDDEN_SYMBOLS = ("settlement_revenue",)

#: ``expr`` 文本里的符号 → 实现侧「实际读取的字段名」的映射。
#: 用于 DQ-10：把**制品声明的输入集**与**实现实际用到的输入集**对账。
SYMBOL_TO_INPUT = {
    "L_i": "L",
    "c_i": "c_i",
    "mu_i": "mu",
    "cap_i": "cap",
}

#: 「未声明」的哨兵。**不要**用 ``None`` 表示未声明——``None`` 必须是
#: 「已声明但无值」以外的东西；用哨兵才能让「key 缺失」在机器上可判（ADR-0004）。
_UNSET: Any = object()


class DerivedError(ValueError):
    """派生量层的不合法调用（结构错误，非数据问题）。"""


# --------------------------------------------------------------------------
# 判据载体
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DerivedCheck:
    """一条具名判据结果。

    ``status`` 取值域与闸门层同构；``reason`` 必须自述**为什么**，
    使下游（T03-03/T03-04/T04-02D）不必回头猜。
    """

    scope: str
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
            "scope": self.scope,
            "item": self.item,
            "status": self.status,
            "reason": self.reason,
            "actual": self.actual,
            "expected": self.expected,
            "blocks_progress": self.blocks_progress,
        }


@dataclass(frozen=True)
class DerivedItem:
    """单个报价项的派生量。

    任一字段为 ``None`` ⇒ **算不出**（不得替换成 0）。``reasons`` 记录该项目
    特有的处置理由（如「cap 空 ⇒ U 不限价」），使输出可审计。
    """

    item_id: str
    L: float | None
    U: float | None
    floor: float | None
    r_eff: float | None
    cap: float | None = None
    inputs_used: frozenset[str] = field(default_factory=frozenset)
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "L": self.L,
            "U": self.U,
            "floor": self.floor,
            "r_eff": self.r_eff,
            "cap": self.cap,
            "inputs_used": sorted(self.inputs_used),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class DerivedReport:
    """派生量层的整体结论。"""

    items: tuple[DerivedItem, ...]
    checks: tuple[DerivedCheck, ...]
    loss_acceptance: str
    loss_acceptance_declared: bool
    mu: float | None
    mu_declared: bool

    # ---- 便捷视图 -------------------------------------------------------
    def of(self, item_id: str) -> DerivedItem | None:
        for it in self.items:
            if it.item_id == item_id:
                return it
        return None

    def verdict(self) -> str:
        """聚合判定：取最严；**空判据集 ⇒ BLOCKED**（「没判过」不是 PASS）。"""
        if not self.checks:
            return STATUS_BLOCKED
        seen = {c.status for c in self.checks}
        for s in _STATUS_ORDER:
            if s in seen:
                return s
        return STATUS_BLOCKED  # pragma: no cover - 状态域封闭，兜底

    def floor_by_id(self) -> dict[str, float]:
        """``floor_i`` 表 —— **下游的唯一来源**（formulation 的 ``floor_by_id``）。

        只收录算得出的项；算不出的项**不出现**（不填 0）。
        """
        out: dict[str, float] = {}
        for it in self.items:
            if it.floor is not None:
                out[it.item_id] = float(it.floor)
        return out

    def lower_by_id(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for it in self.items:
            if it.L is not None:
                out[it.item_id] = float(it.L)
        return out

    def upper_by_id(self) -> dict[str, float]:
        """**只收录有限上界**；不限价项（``U=None``）刻意缺席，不得折成 0。"""
        out: dict[str, float] = {}
        for it in self.items:
            if it.U is not None:
                out[it.item_id] = float(it.U)
        return out

    def blocking(self) -> tuple[DerivedCheck, ...]:
        return tuple(c for c in self.checks if c.blocks_progress)

    def to_dict(self) -> dict[str, Any]:
        return {
            "loss_acceptance": self.loss_acceptance,
            "loss_acceptance_declared": self.loss_acceptance_declared,
            "mu": self.mu,
            "mu_declared": self.mu_declared,
            "verdict": self.verdict(),
            "items": [i.to_dict() for i in self.items],
            "checks": [c.to_dict() for c in self.checks],
        }


# --------------------------------------------------------------------------
# 规格加载
# --------------------------------------------------------------------------


def load_derived_spec(config_dir: Path) -> dict[str, Any]:
    """读取受控制品 ``config/derived_quantities_spec.json``。"""
    import json

    path = Path(config_dir) / SPEC_FILENAME
    if not path.exists():
        raise DerivedError(f"派生量规格不存在：{path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def inputs_from_project(config_dir: Path | str) -> dict[str, Any]:
    """从**已存在的**项目落值文件解析 :func:`compute_derived` 的输入。

    ★ 本函数**只读已落值的位置，绝不代填**。找不到就返回「未声明」，
    让 BLOCKED 如实发生——那正是当前项目的真实状态（μ 与
    ``unbalanced_clause`` 至今没有任何落值文件）。

    已接线的位置：
    * ``config/project_selection.json`` → ``options.loss_acceptance.value``

    尚未接线（见制品的 ``open_items`` OI-DQ-A / OI-DQ-B）：``mu`` 与
    ``unbalanced_clause``。它们没有既定落值位置，**不得**为了「让流程跑通」
    而在这里发明一个文件——那是 ADR-0004 禁止的默认值填充。待用户声明后，
    在此处接线即可（``compute_derived`` 的接口不变）。
    """
    import json

    out: dict[str, Any] = {"loss_acceptance": None, "mu": _UNSET, "unbalanced": None}
    cfg = Path(config_dir)

    sel = cfg / "project_selection.json"
    if sel.exists():
        try:
            data = json.loads(sel.read_text(encoding="utf-8"))
        except json.JSONDecodeError:  # pragma: no cover - 文件损坏应当向上暴露
            data = {}
        opt = ((data.get("options") or {}).get("loss_acceptance") or {})
        if "value" in opt:
            out["loss_acceptance"] = str(opt["value"])
    return out


def _declared_inputs(spec: Mapping[str, Any] | None, symbol: str) -> frozenset[str]:
    """从规格的 ``expr`` 文本里提取**应出现**的输入符号。

    这是 DQ-10 的一半：制品说 floor 依赖 ``{L, c_i, mu}``，实现就必须真的
    读到这三个字段。只提取**标识符级**的符号，不做公式解析——足够发现
    「漏读 mu」「用 L 冒充 floor」这类实质分歧。
    """
    if not spec:
        return frozenset()
    for dq in spec.get("derived_quantities") or ():
        if dq.get("symbol") == symbol:
            text = str(dq.get("expr") or "")
            return frozenset(
                v for k, v in SYMBOL_TO_INPUT.items() if k in text
            )
    return frozenset()


# --------------------------------------------------------------------------
# 静态审计（DQ-08）
# --------------------------------------------------------------------------


def audit_derived_source(
    source: str | None = None, *, path: Path | str | None = None
) -> dict[str, Any]:
    """AST 静态审计：本模块不得调用 ``settlement_revenue``。

    委派与重实现的界线在**符号级**：调用 ``compute_r_eff`` 是委派（允许，
    它本身就是唯一实现）；调用 ``settlement_revenue`` 意味着要自己做差分
    求 ``dR/dp``（禁止）。文档字符串里的字面出现不算违规。
    """
    if source is None and path is None:
        raise DerivedError("必须给出 source 或 path 之一")
    if source is None:
        with Path(path).open(encoding="utf-8") as fh:  # type: ignore[arg-type]
            source = fh.read()

    tree = ast.parse(source)
    docstrings = _collect_docstrings(tree)

    calls: list[str] = []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name:
                calls.append(name)
        elif isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
            imports.extend(f"{node.module or ''}.{a.name}" for a in node.names)

    text_calls = [c for c in calls if c not in docstrings]
    forbidden_calls = sorted(
        {c for c in text_calls if c in FORBIDDEN_SYMBOLS}
    )
    forbidden_imports = sorted(
        {
            imp
            for imp in imports
            for f in FORBIDDEN_SYMBOLS
            if imp == f or imp.endswith(f".{f}")
        }
    )
    return {
        "ok": not forbidden_calls and not forbidden_imports,
        "forbidden_calls": forbidden_calls,
        "forbidden_imports": forbidden_imports,
        "checked_calls": len(text_calls),
    }


def _collect_docstrings(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            ds = ast.get_docstring(node)
            if ds:
                out.add(ds)
    return out


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


# --------------------------------------------------------------------------
# 判定（与计算分离）
# --------------------------------------------------------------------------


def judge_derived(
    items: Iterable[DerivedItem],
    *,
    loss_acceptance: str = LOSS_DECLINE,
    declared_inputs: frozenset[str] = frozenset(),
    spec_provided: bool = True,
    mu_declared: bool = True,
    audit: Mapping[str, Any] | None = None,
) -> tuple[DerivedCheck, ...]:
    """对**已算出的派生量**做判定。

    刻意与 :func:`compute_derived` 分离，且**只吃** :class:`DerivedItem`
    序列（不吃实例、不吃配置）：因此可以对**任意注入的坏数据**判出问题。
    这正是区分度测试能双向验证的前提——「正确的值不被误杀」与「错误的
    值必被抓住」都要能被独立检验（规则⑧）。
    """
    rows = tuple(items)
    checks: list[DerivedCheck] = []

    # ---- DQ-03：空 cap 的语义（U 必须恒等于 cap，None 不得折成值）------
    for it in rows:
        if it.cap is None and it.U is not None:
            checks.append(
                DerivedCheck(
                    SCOPE, f"DQ-03 U_i（{it.item_id}）", STATUS_FAIL,
                    f"{it.item_id}: cap 为空（不限价）但 U={it.U!r} —— "
                    "空 cap 被折成了一个值。这会凭空给不限价项造出上界，"
                    "把可行解判成不可行（ADR-0007：沉默不是断言）。",
                    actual=it.U, expected=None,
                )
            )
        elif it.cap is not None and it.U is not None and abs(it.U - it.cap) > 1e-9:
            checks.append(
                DerivedCheck(
                    SCOPE, f"DQ-03 U_i（{it.item_id}）", STATUS_FAIL,
                    f"{it.item_id}: U={it.U!r} != cap={it.cap!r}。"
                    "C2 定义 U_i = cap_i —— 两者分叉说明有一侧错。",
                    actual=it.U, expected=it.cap,
                )
            )

    # ---- DQ-06：floor >= L（结构性不变量）-----------------------------
    for it in rows:
        if it.floor is not None and it.L is not None and it.floor < it.L - 1e-12:
            checks.append(
                DerivedCheck(
                    SCOPE, f"DQ-06 floor>=L（{it.item_id}）", STATUS_FAIL,
                    f"{it.item_id}: floor={it.floor!r} < L={it.L!r} ⇒ 违反结构性"
                    "不变量（floor = max(L, ·)）。",
                    actual=it.floor, expected=f">= {it.L!r}",
                )
            )

    # ---- DQ-07：逐条原始阈值的箱型可行性 -------------------------------
    for it in rows:
        if it.L is not None and it.U is not None and it.L > it.U + 1e-12:
            checks.append(
                DerivedCheck(
                    SCOPE, f"DQ-07 箱型（{it.item_id}）", STATUS_FAIL,
                    f"{it.item_id}: L={it.L!r} > U={it.U!r} ⇒ C3 与 C2 冲突，"
                    "**逐条原始阈值**已判不可行（不得交求解器报泛化 infeasible）。",
                    actual=it.L, expected=f"<= {it.U!r}",
                )
            )
        if it.floor is not None and it.U is not None and it.floor > it.U + 1e-12:
            if loss_acceptance == LOSS_ACCEPT:
                checks.append(
                    DerivedCheck(
                        SCOPE, f"DQ-07 箱型（{it.item_id}）", STATUS_FAIL,
                        f"{it.item_id}: floor={it.floor!r} > U={it.U!r}，而 "
                        "loss_acceptance=ACCEPT ⇒ 地板本应被钳到 cap，"
                        "说明**钳制失效**。",
                        actual=it.floor, expected=f"<= {it.U!r}",
                    )
                )
            else:
                checks.append(
                    DerivedCheck(
                        SCOPE, f"DQ-07 箱型（{it.item_id}）", STATUS_FAIL,
                        f"{it.item_id}: floor={it.floor!r} > U={it.U!r} 且 "
                        "loss_acceptance=DECLINE ⇒ 可行域为空（对应 D07 FAIL）。"
                        "须先修成本数据或改声明。",
                        actual=it.floor, expected=f"<= {it.U!r}",
                    )
                )

    # ---- DQ-05：ACCEPT 钳制（正向断言 + 无样本不得判 PASS）-------------
    if loss_acceptance == LOSS_ACCEPT and not any(
        it.U is not None for it in rows if it.floor is not None
    ):
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-05 钳制条件", STATUS_WARN,
                "loss_acceptance=ACCEPT，但本轮**没有 cap 非空且 floor 算得出**"
                "的项 ⇒ 钳制路径未被走到。**不得判 PASS**——「这一轮没走到」"
                "不等于「已成立」（T04-02D SV-03 的同一条教训）。",
                actual=0, expected=">= 1 项",
            )
        )

    # ---- DQ-09：未定态不得降级为默认值 ---------------------------------
    if not mu_declared:
        leaked = [it.item_id for it in rows if it.floor is not None]
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-09 未定态不降级", STATUS_FAIL if leaked else STATUS_PASS,
                (
                    f"μ 未声明，但以下项仍产出了 floor（疑似默认值填充）：{leaked}"
                    if leaked else
                    "μ 未声明 ⇒ 所有 floor 均为 None，未见默认值填充（ADR-0004）"
                ),
                actual=leaked, expected=[],
            )
        )
    else:
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-09 未定态不降级", STATUS_PASS,
                "μ 已声明 ⇒ 未定态降级检查的触发条件不成立（本轮无相关样本）",
                actual=None, expected=None,
            )
        )

    # ---- DQ-10：制品声明 vs 实现实际的输入集对账（跨来源）-------------
    sample = [it for it in rows if it.floor is not None]
    if not spec_provided or not declared_inputs:
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-10 声明—实现对账", STATUS_WARN,
                "未提供规格 ⇒ 无从对账（**不得**记为 PASS：没有依据的通过等于没判）",
                actual=None, expected="derived_quantities_spec",
            )
        )
    elif not sample:
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-10 声明—实现对账", STATUS_SKIP,
                "本轮**没有任何项产出 floor**（上游未定 ⇒ 全 BLOCKED）⇒ 对账无"
                f"样本，声明依赖 {sorted(declared_inputs)} 既未被证实也未被证伪。"
                "**SKIP 不是 PASS**：「没走到」不等于「已成立」，但也**不等于"
                "「已违反」**（把无样本判成 FAIL 属判据过紧）。",
                actual=0, expected=f">= 1 个样本（声明依赖 {sorted(declared_inputs)}）",
            )
        )
    else:
        all_used: set[str] = set()
        for it in sample:
            all_used |= set(it.inputs_used)
        missing = sorted(declared_inputs - all_used)
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-10 声明—实现对账",
                STATUS_FAIL if missing else STATUS_PASS,
                (
                    f"规格声明 floor 依赖 {sorted(declared_inputs)}，但实现从未"
                    f"读取 {missing} ⇒ 声明与实现分叉。"
                    if missing else
                    f"规格声明 floor 依赖 {sorted(declared_inputs)}，实现确实读到"
                    f"了全部输入（样本 {len(sample)} 项）"
                ),
                actual=sorted(all_used), expected=sorted(declared_inputs),
            )
        )

    # ---- DQ-08：静态审计（r_eff 的委派性）------------------------------
    if audit is None:
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-08 r_eff 委派性", STATUS_SKIP,
                "未提供静态审计结果 ⇒ 本环节没查（SKIP 不是 PASS）",
                actual=None, expected="audit 结果",
            )
        )
    else:
        ok = bool(audit.get("ok"))
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-08 r_eff 委派性", STATUS_PASS if ok else STATUS_FAIL,
                (
                    "本模块未调用 settlement_revenue ⇒ r_eff 只走委派路径"
                    if ok else
                    f"本模块出现 R_i 的实现符号：calls={audit.get('forbidden_calls')} "
                    f"imports={audit.get('forbidden_imports')}"
                ),
                actual=dict(audit),
                expected={"forbidden_calls": [], "forbidden_imports": []},
            )
        )

    return tuple(checks)


# --------------------------------------------------------------------------
# 主计算
# --------------------------------------------------------------------------


def compute_derived(
    instance: Any,
    resolved: ResolvedParameters,
    *,
    mu: Any = _UNSET,
    loss_acceptance: str | None = None,
    unbalanced: Mapping[str, Any] | None = None,
    spec: Mapping[str, Any] | None = None,
) -> DerivedReport:
    """计算全部派生量并逐条产出判据。

    :param instance: :class:`Phase1Instance`
    :param resolved: 规则卡解析出的参数（``r_eff`` 的输入）
    :param mu: 允许亏损深度。**不传 = 未声明**（BLOCKED）；``mu=0`` 是合法取值。
    :param loss_acceptance: ``ACCEPT`` / ``DECLINE``；``None`` = 未落值（按严格算 + WARN）
    :param unbalanced: 不平衡报价条款块。``None`` = 未声明（BLOCKED）；
        ``{"enabled": False}`` = 已核查无此条款（合法结论）
    :param spec: 受控规格（用于 DQ-10 的声明—实现对账）
    """
    mu_declared = mu is not _UNSET
    mu_value: float | None = _num(mu) if mu_declared else None
    loss = str(loss_acceptance) if loss_acceptance else LOSS_DECLINE
    loss_declared = loss_acceptance is not None

    checks: list[DerivedCheck] = []
    items: list[DerivedItem] = []

    # ---- DQ-01：μ 的声明式就绪性（key 在不在，不是值等不等于 0）----------
    if not mu_declared:
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-01 μ 声明式就绪", STATUS_BLOCKED,
                "μ（允许亏损深度）**未声明**（key 缺失）——C4 地板 "
                "c_i(1−μ_i) 不可计算。μ=0 是合法取值，与「未声明」是两件事"
                "（ADR-0004），故不得按 0 继续。",
                actual=None, expected="标量 key 存在",
            )
        )
    elif mu_value is None:
        # key 存在但取值为 null：与「key 缺失」是**不同的**未定态，
        # 机器上必须可区分（ADR-0004），因此理由不同、判据条目相同。
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-01 μ 声明式就绪", STATUS_BLOCKED,
                "μ 的 key **存在但取值为空**（null）⇒ 值缺失，仍不可计算。"
                "这与「key 完全缺失」不同（前者说明声明流程走到了一半），"
                "故分别报出；两者都必须 BLOCKED。",
                actual=None, expected="数值或 0",
            )
        )
    else:
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-01 μ 声明式就绪", STATUS_PASS,
                f"μ 已声明 = {mu_value!r}（0 亦为合法取值，代表不允许任何亏损）",
                actual=mu_value, expected="标量 key 存在",
            )
        )

    # ---- loss_acceptance 未落值：按严格口径算，但必须显式说明 -----------
    if not loss_declared:
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-01b loss_acceptance 落值", STATUS_WARN,
                "loss_acceptance 未落值 ⇒ 本层按 **DECLINE（严格地板）** 计算。"
                "这是「宁可判死也不静默放宽」的方向；落值后须复算。",
                actual=None, expected="ACCEPT / DECLINE",
            )
        )
    else:
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-01b loss_acceptance 落值", STATUS_PASS,
                f"loss_acceptance = {loss}",
                actual=loss, expected="ACCEPT / DECLINE",
            )
        )

    # ---- 不平衡报价条款：声明式就绪（ADR-0006 / OI-04）------------------
    ub_enabled: bool | None = None
    ub_reference: str | None = None
    ub_tol_lo: float | None = None
    if unbalanced is None:
        checks.append(
            DerivedCheck(
                SCOPE, "DQ-04 L_i 不编造 δ⁻", STATUS_BLOCKED,
                "unbalanced_clause **未声明**（整块缺失）——`enabled` 这个标量 "
                "key 都不在 ⇒ L_i^tender 无从判断。注意 enabled=false（已核查无"
                "该条款）是**合法结论**，与「没声明」不同（ADR-0007）。",
                actual=None, expected="enabled 标量 key 存在",
            )
        )
    else:
        if "enabled" not in unbalanced:
            checks.append(
                DerivedCheck(
                    SCOPE, "DQ-04 L_i 不编造 δ⁻", STATUS_BLOCKED,
                    "unbalanced_clause.enabled **缺失** ⇒ 沉默不是断言"
                    "（ADR-0007），不得当作 false。",
                    actual=None, expected="enabled 标量 key 存在",
                )
            )
        else:
            ub_enabled = bool(unbalanced.get("enabled"))
            ub_reference = unbalanced.get("reference")
            tol = unbalanced.get("tol_lo")
            ub_tol_lo = float(tol) if tol is not None else None
            if not ub_enabled:
                checks.append(
                    DerivedCheck(
                        SCOPE, "DQ-04 L_i 不编造 δ⁻", STATUS_PASS,
                        "unbalanced_clause.enabled=false（已核查：无该条款）"
                        "⇒ L_i^tender 不参与取大，L_i = 0。这是**结论**，"
                        "不是「未实现」",
                        actual=False, expected="enabled 标量 key 存在",
                    )
                )
            elif ub_reference == REF_CAP and ub_tol_lo is None:
                checks.append(
                    DerivedCheck(
                        SCOPE, "DQ-04 L_i 不编造 δ⁻", STATUS_BLOCKED,
                        "条款 enabled=true 且 reference=CAP，但 tol_lo 缺失 "
                        "⇒ 幅度不可知。**禁用默认值**：阈值没有招标依据时"
                        "不得编造。",
                        actual=None, expected="tol_lo 数值",
                    )
                )

    # ---- 逐项计算 --------------------------------------------------------
    for item in instance.items:
        item_id = str(getattr(item, "item_id", "?"))
        reasons: list[str] = []
        used: set[str] = set()
        role = str(getattr(item, "role", "OPTIMIZABLE"))

        # --- L_i：多来源**取大**（C3 重定义后的口径）------------------------
        # 来源①：实例显式给出的下界（可能来自招标限价表的下限列或其它条款）；
        # 来源②：不平衡报价条款在 reference=CAP 时给出的 cap_i·(1−tol_lo)。
        # **取大**——不是二选一，也不是「后到者覆盖」（那会让两条依据互相抹掉）。
        use_clause = (
            ub_enabled is True
            and ub_reference == REF_CAP
            and ub_tol_lo is not None
        )
        cap = _num(getattr(item, "cap", None))
        inst_L = _num(getattr(item, "L", None))
        inst_U = _num(getattr(item, "U", None))

        l_sources: list[tuple[str, float]] = []
        if inst_L is not None:
            l_sources.append(("实例下界", float(inst_L)))
        if use_clause:
            if cap is None:
                # OI-DQ-D：条款有基准缺项 —— 报具名 WARN，不取 0 也不阻塞
                checks.append(
                    DerivedCheck(
                        SCOPE, f"DQ-04 L_i（{item_id}）", STATUS_WARN,
                        f"{item_id}: 条款以 CAP 为基准，但该项 cap 为空 ⇒ 条款对"
                        "本项无基准可算。**不判 BLOCKED**（条款对不限价项的适用性"
                        "本身未声明，属可解释性而非正确性），**也不取 0 冒充**。"
                        "本项下界只按其它来源计。",
                        actual=None, expected=f"cap_i·(1−{ub_tol_lo})",
                    )
                )
            else:
                l_sources.append(
                    (f"条款 cap·(1−{ub_tol_lo})", float(cap) * (1.0 - float(ub_tol_lo)))
                )
        elif ub_enabled is False:
            reasons.append("无不平衡报价条款 ⇒ 条款侧不提供下界")

        if l_sources:
            L = max(v for _, v in l_sources)
            L = max(L, 0.0)
            reasons.append(
                "L = max(" + ", ".join(f"{n}={v:g}" for n, v in l_sources) + f") = {L:g}"
            )
        else:
            L = 0.0
            reasons.append("两侧下界来源均无取值 ⇒ L = 0（不得为此编造 δ⁻）")

        # --- U_i（cap 空 = 不限价，**不是 0**）-----------------------------
        U: float | None = cap
        if cap is None:
            reasons.append("cap 空 ⇒ U = None（不限价，ALLOW_EMPTY_NO_CAP）")
        elif inst_U is not None and abs(inst_U - cap) > 1e-9:
            # 同一物理量的两个来源分叉：C2 定义 U_i = cap_i，实例又自带 U。
            # ADR-0015：判据不得自证，必须**跨来源**——两侧不一致说明有一侧错。
            checks.append(
                DerivedCheck(
                    SCOPE, f"DQ-03b cap 对账（{item_id}）", STATUS_FAIL,
                    f"{item_id}: 实例 U={inst_U!r} 与 cap={cap!r} 不一致。"
                    "C2 定义 U_i = cap_i，两者是同一量的两个来源，分叉即有一侧错。",
                    actual=inst_U, expected=cap,
                )
            )

        # --- floor_i -------------------------------------------------------
        mu_item: float | None = mu_value
        floor: float | None = None
        if mu_item is None:
            floor = None
            reasons.append("μ 未声明 ⇒ floor 算不出（None，不取 0）")
        else:
            c_i = _num(getattr(item, "c_i", None))
            if c_i is None:
                floor = None
                reasons.append("c_i 缺失 ⇒ floor 算不出（None）")
            elif c_i == 0.0 and role == "OPTIMIZABLE":
                floor = None
                reasons.append("c_i=0 且 role=OPTIMIZABLE ⇒ BLOCKED（见 DQ-02）")
            else:
                used.update({"L", "c_i", "mu"})
                base = max(L, c_i * (1.0 - mu_item))
                if loss == LOSS_ACCEPT and cap is not None:
                    used.add("cap")
                    floor = min(base, cap)
                    if floor != base:
                        reasons.append(
                            f"ACCEPT 钳制：min({base:g}, cap={cap:g}) = {floor:g}"
                        )
                    else:
                        reasons.append(f"floor = {floor:g}（未触钳）")
                elif loss == LOSS_ACCEPT and cap is None:
                    # ★ 最容易静默出错的一处：cap 空时**不得**钳制
                    floor = base
                    reasons.append(
                        f"floor = {base:g}（ACCEPT 但 cap 空 ⇒ **不钳制**；"
                        "把空 cap 当 0 会把地板静默压到 0）"
                    )
                else:
                    floor = base
                    reasons.append(f"floor = {floor:g}（严格地板）")

        # --- DQ-02：c_i 就绪性与零值语义 -----------------------------------
        c_i_val = _num(getattr(item, "c_i", None))
        if role == "OPTIMIZABLE" and c_i_val == 0.0:
            checks.append(
                DerivedCheck(
                    SCOPE, f"DQ-02 c_i（{item_id}）", STATUS_BLOCKED,
                    f"{item_id}: role=OPTIMIZABLE 但 c_i=0 ⇒ BLOCKED。"
                    "成本为零的可竞争项会使 C4 地板失效、C6 亏损口径失真，"
                    "属**数据可疑**而非合法取值（field_schema.c_i）。",
                    actual=0.0, expected="> 0",
                )
            )

        # --- r_eff_i（**委派**，不重实现）----------------------------------
        r_eff = None
        try:
            r_eff = instance.r_eff(item, resolved)
        except Exception:  # pragma: no cover - 实例层应自行吞掉缺数据
            r_eff = None
        if r_eff is None:
            reasons.append("r_eff 算不出（None，不降级为 0）")

        items.append(
            DerivedItem(
                item_id=item_id,
                L=L,
                U=U,
                floor=floor,
                r_eff=r_eff,
                cap=cap,
                inputs_used=frozenset(used),
                reasons=tuple(reasons),
            )
        )

    # ---- 判定期判据：委托 judge_derived（计算与判定分离）----------------
    # 计算期只产生「输入侧」判据（DQ-01/01b/02/03b/04）；对**产出值**的判定
    # 一律走 judge_derived——这样区分度测试可以注入坏数据独立验证判据本身，
    # 而不是只能验证「我的实现恰好是对的」。
    declared = _declared_inputs(spec, "floor_i")
    try:
        audit = audit_derived_source(path=Path(__file__))
    except Exception as exc:  # pragma: no cover - 审计读不到自身时才发生
        audit = {"ok": False, "forbidden_calls": [str(exc)], "forbidden_imports": []}
    checks.extend(
        judge_derived(
            items,
            loss_acceptance=loss,
            declared_inputs=declared,
            spec_provided=bool(spec),
            mu_declared=mu_declared,
            audit=audit,
        )
    )


    return DerivedReport(
        items=tuple(items),
        checks=tuple(checks),
        loss_acceptance=loss,
        loss_acceptance_declared=loss_declared,
        mu=mu_value,
        mu_declared=mu_declared,
    )


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _item_of(instance: Any, item_id: str) -> Any:  # pragma: no cover - 保留供调试
    for it in instance.items:
        if str(getattr(it, "item_id", "")) == item_id:
            return it
    return None


__all__ = [
    "DerivedCheck",
    "DerivedError",
    "DerivedItem",
    "DerivedReport",
    "LOSS_ACCEPT",
    "LOSS_DECLINE",
    "SCOPE",
    "STATUS_BLOCKED",
    "STATUS_FAIL",
    "STATUS_PASS",
    "STATUS_SKIP",
    "STATUS_WARN",
    "audit_derived_source",
    "compute_derived",
    "load_derived_spec",
]
