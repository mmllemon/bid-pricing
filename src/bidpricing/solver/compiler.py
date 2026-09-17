"""T04-02B 约束编译器：``Formulation`` → ``CompiledModel``。

**这份文件存在的理由**：T04-02A 产出的是「模型长什么样」的受控声明
（``Formulation``：变量表 + 稀疏行 + 目标 + 挂账），本模块负责把它翻成
**建模器/求解器可消费的规范形式**。两者分家的意义是让「实现与规格一致」
成为可机械判定的事——否则编译器里任何一处手写的系数都会让 T04-02D 的
复核失去对象（复核的是一个与声明无关的模型）。

三条设计纪律
------------

1. **系数只许来自 ``Row.coefficients``，或来自制品声明的展开规则。**
   唯一允许"新造"系数的地方是 C9 的展开，而它的系数直接复制目标系数向量
   （``Column.objective_coeff``）——即「Z 对 p 的偏导」，不是另写一遍公式。
   ``check_compiled`` 的 CC-02 逐项比对这个来源关系。
2. **不得静默丢弃，也不得静默生成。** 被化简掉的行进 ``simplifications``
   台账（含可复算的理由）；推不出系数的行**不生成**并判 BLOCKED。
   ``rhs is None`` 的行一律不得进入模型——它会被求解器读成「无约束」或
   「0 ≥ rhs」，两种误读都不报错。
3. **零第三方依赖。** 环境无 PuLP / HiGHS（实测），故核心是纯 Python 的
   规范形式 + 自带的求值器。``to_pulp`` 是惰性导出：装了 PuLP 才能用，
   没装判 SKIP 而**不判 FAIL**（缺后端不等于模型错）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..contracts.pricing_card import ResolvedParameters
from .formulation import (
    Formulation,
    FormulationError,
    Row,
    _f,
)

SPEC_FILENAME = "lp_compiler_spec.json"

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_SKIP = "SKIP"

#: 浮点比较容差——系数逐项比对用。取相对容差的理由是系数跨多个量级
#: （q0 可达 1e5、r_eff ~ 1），绝对容差会在大系数上误判。
COEFF_RTOL = 1e-12
COEFF_ATOL = 1e-15

#: 化简判定用的零阈。与 formulation.BIG_M_FLOOR_EPS 同量级。
ZERO_EPS = 1e-12

# 以下四个是**判据自身的参数**，不是业务系数。它们被具名化的理由是 CC-12：
# 审计规则要求「数值必须具名」——具名的常量可被审计名字，写死在表达式里的
# 数值只可能是手写。故这些量即便与业务无关，也必须提出来。（2026-09-17）
#: 表达式内允许出现的数值字面量——只有结构系数。业务数值必须先具名（见 CC-12）。
DEFAULT_LITERAL_ALLOWLIST: tuple[float, ...] = (0, 1, -1, 0.0, 1.0, -1.0)

FINGERPRINT_ND = 9          # 指纹取整位数（浮点比较）
SLACK_RTOL = 1e-6           # 残差比较：相对容差
SLACK_ATOL = 1e-9           # 残差比较：绝对容差
SAMPLE_LIMIT = 5            # 诊断输出里每类最多列举几项
REASON_TRUNC = 60           # 诊断理由的截断长度


class CompilerError(ValueError):
    """编译器无法机械完成转换（缺展开所需输入等）。"""


# ---------------------------------------------------------------------------
# 模型对象
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledVar:
    """一列变量——与 ``formulation.Column`` 同域，但只含求解器需要的字段。"""

    symbol: str
    family: str
    item_id: str
    kind: str
    lower: float | None
    upper: float | None
    objective_coeff: float
    present_in: tuple[str, ...] = ("LP", "MILP")

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "family": self.family,
            "kind": self.kind,
            "lower": self.lower,
            "upper": self.upper,
            "objective_coeff": self.objective_coeff,
        }


@dataclass(frozen=True)
class CompiledRow:
    """一行约束。``origin`` 指向它在 ``Formulation`` 里的来源行 id。

    ``origin`` 是「无手写约束」的抓手：CC-01 用它做双向集合比较，
    CC-02 用它取源行系数做逐项对账。没有 ``origin`` 的行即无法溯源，
    编译器不得产出这样的行。
    """

    constraint_id: str
    origin: str
    form: str
    sense: str
    rhs: float
    coefficients: tuple[tuple[str, float], ...]
    tolerance: str
    sources: tuple[str, ...] = ()
    scope: str = ""
    detail: str = ""
    expanded_from_objective: bool = False
    aux: tuple[tuple[str, Any], ...] = ()

    def aux_get(self, key: str) -> Any:
        for k, v in self.aux:
            if k == key:
                return v
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "origin": self.origin,
            "form": self.form,
            "sense": self.sense,
            "rhs": self.rhs,
            "coefficients": [
                {"symbol": s, "coeff": c} for s, c in self.coefficients
            ],
            "tolerance": self.tolerance,
            "sources": list(self.sources),
            "scope": self.scope,
            "detail": self.detail,
            "expanded_from_objective": self.expanded_from_objective,
            "aux": dict(self.aux),
        }


@dataclass(frozen=True)
class Simplification:
    """一条被化简掉的约束/变量，以及**可复算**的理由。

    台账的意义：化简是编译器的自由裁量动作，若不登记，「少了三行」与
    「被正确化简了三行」在制品上无法区分。
    """

    kind: str            # DEGENERATE_DOMINATED | DEGENERATE_FIXED | NOT_COMPILED
    subject: str         # 行 id 或变量 symbol
    reason: str
    removed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "reason": self.reason,
            "removed": self.removed,
        }


@dataclass(frozen=True)
class CompiledModel:
    """建模器无关的规范形式。"""

    variables: tuple[CompiledVar, ...]
    rows: tuple[CompiledRow, ...]
    objective_sense: str
    objective_constant: float
    solver_form: str
    simplifications: tuple[Simplification, ...] = ()
    notes: tuple[str, ...] = ()
    source: str = ""

    @property
    def n_vars(self) -> int:
        return len(self.variables)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    def var_index(self) -> dict[str, int]:
        return {v.symbol: i for i, v in enumerate(self.variables)}

    def price_symbols(self) -> tuple[str, ...]:
        return tuple(v.symbol for v in self.variables if v.family == "p")

    def binary_symbols(self) -> tuple[str, ...]:
        return tuple(v.symbol for v in self.variables if v.kind == "BINARY")

    def rows_of(self, constraint_id: str) -> tuple[CompiledRow, ...]:
        return tuple(r for r in self.rows if r.constraint_id == constraint_id)

    def all_symbols(self) -> set[str]:
        out: set[str] = set()
        for r in self.rows:
            for s, _c in r.coefficients:
                out.add(s)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_sense": self.objective_sense,
            "objective_constant": self.objective_constant,
            "solver_form": self.solver_form,
            "n_vars": self.n_vars,
            "n_rows": self.n_rows,
            "variables": [v.to_dict() for v in self.variables],
            "rows": [r.to_dict() for r in self.rows],
            "simplifications": [s.to_dict() for s in self.simplifications],
            "notes": list(self.notes),
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# 求值器——编译结果的独立裁判
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RowEval:
    """单行代回结果。``slack`` 为**符号无关的违反量**：≥ 0 表示满足。"""

    constraint_id: str
    lhs: float
    sense: str
    rhs: float
    slack: float

    @property
    def ok(self) -> bool:
        return self.slack >= -ZERO_EPS

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "lhs": self.lhs,
            "sense": self.sense,
            "rhs": self.rhs,
            "slack": self.slack,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class Evaluation:
    """把一个**完整**赋值代回编译后的模型。"""

    objective: float
    feasible: bool
    rows: tuple[RowEval, ...]
    missing: tuple[str, ...]

    def violations(self) -> tuple[RowEval, ...]:
        return tuple(r for r in self.rows if not r.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "feasible": self.feasible,
            "missing": list(self.missing),
            "rows": [r.to_dict() for r in self.rows],
        }


def evaluate(model: CompiledModel, x: Mapping[str, float]) -> Evaluation:
    """把赋值 ``x`` 代回 ``model``。

    这是**独立于编译路径**的裁判：只做「按行求和、比较」。它同时是 CC-07
    的一侧——另一侧是业务侧的 ``check_solution``（代回原式）。两者若同源，
    CC-07 就退化为恒真式；正因如此它们必须分别实现。

    缺赋值 ⇒ 进 ``missing`` 并且**不可行**，不得把缺项当 0 静默累加。
    """
    missing = tuple(
        v.symbol for v in model.variables if v.symbol not in x
    )
    rows: list[RowEval] = []
    for r in model.rows:
        lhs = 0.0
        for s, c in r.coefficients:
            lhs += c * float(x.get(s, 0.0))
        if r.sense == "==":
            slack = -abs(lhs - r.rhs)
        elif r.sense == "<=":
            slack = r.rhs - lhs
        elif r.sense == ">=":
            slack = lhs - r.rhs
        else:
            raise CompilerError(f"未知 sense：{r.sense!r}")
        rows.append(RowEval(r.constraint_id, lhs, r.sense, r.rhs, slack))

    objective = model.objective_constant + sum(
        v.objective_coeff * float(x.get(v.symbol, 0.0)) for v in model.variables
    )
    violated = any(not r.ok for r in rows)
    return Evaluation(
        objective=objective,
        feasible=not violated and not missing,
        rows=tuple(rows),
        missing=missing,
    )


# ---------------------------------------------------------------------------
# 编译
# ---------------------------------------------------------------------------


def compile_model(
    formulation: Formulation,
    *,
    z_min: float | None = None,
    pi_target: float | None = None,
    tf_terms: Mapping[str, Sequence[float]] | None = None,
    source: str = "",
) -> CompiledModel:
    """把 ``Formulation`` 翻译为 ``CompiledModel``。

    **不收任何"额外约束"参数**：能在模型里出现的行，只能来自
    ``formulation.rows`` 或制品声明的展开规则。多加一个参数就等于多一个
    手写约束的入口。

    展开规则（制品 ``lp_compiler_spec.expansion_rules``）：

    * ``C9``（盈利门槛）——系数 := 各 p 列的 ``objective_coeff``（即 ∂Z/∂p）；
      ``C9a`` 的 rhs := ``z_min − objective_constant``；
      ``C9b`` 的 rhs := ``−(1 + pi_target) · objective_constant``。
      缺 ``z_min`` / ``pi_target`` ⇒ 该子式**不生成**并登记 NOT_COMPILED。
    * ``C10``（现金流前载）——系数 := ``rho_i · q0_i``，rhs := ``Σ c_i q0_i``；
      ``tf_terms`` 须给 ``{item_id: (rho_i, q0_i, c_i)}``。未提供 ⇒ NOT_COMPILED。
    """
    if formulation.objective_sense not in ("MAXIMIZE", "MINIMIZE"):
        raise CompilerError(f"未知目标方向：{formulation.objective_sense!r}")

    variables = tuple(
        CompiledVar(
            symbol=c.symbol,
            family=c.family,
            item_id=c.item_id,
            kind=c.kind,
            lower=c.lower,
            upper=c.upper,
            objective_coeff=c.objective_coeff,
            present_in=c.present_in,
        )
        for c in formulation.variables
    )

    lower_by_symbol = {v.symbol: v.lower for v in variables}
    simplifications: list[Simplification] = []
    notes: list[str] = list(formulation.box_notes)
    rows: list[CompiledRow] = []

    # 界已固定（lower == upper）的变量：已被 Big-M 退化判定固定。保留在变量表里
    # （**不删除**——删掉会让解向量不完整，校验器无从复核），但必须登记：
    # 「有个变量界退化」与「编译器忘了给它界」在制品上否则无法区分。
    for v in variables:
        if v.lower is not None and v.upper is not None and v.lower == v.upper:
            simplifications.append(
                Simplification(
                    "DEGENERATE_FIXED", v.symbol,
                    f"lower == upper == {v.lower!r} ⇒ 该变量由退化判定固定，"
                    "不再引入自由度。保留在变量表内以便解校验器复核，"
                    "但任何把它当自由变量的推理都是错的。",
                    removed=False,
                )
            )

    def _unit_rows(row: Row) -> CompiledRow | None:
        """把一条源行原样翻译（系数逐项复制，不做任何"修正"）。"""
        if row.rhs is None:
            simplifications.append(
                Simplification(
                    "NOT_COMPILED", f"{row.constraint_id}:{row.form}",
                    "源行 rhs 为 None ⇒ 该行没有可执行的右端。"
                    "它会被求解器读成「无约束」或「0 ≥ rhs」，两种误读都不报错，"
                    "故不得进入模型；须先补输入或在调用方判 BLOCKED。",
                    removed=True,
                )
            )
            return None
        # C8 的退化：rhs 严格小于变量下界 ⇒ 被界支配，移除且留痕。
        if row.constraint_id == "C8" and len(row.coefficients) == 1:
            sym, coef = row.coefficients[0]
            lo = lower_by_symbol.get(sym)
            if coef > 0 and lo is not None and row.rhs < lo - ZERO_EPS:
                simplifications.append(
                    Simplification(
                        "DEGENERATE_DOMINATED", f"C8:{sym}",
                        f"rhs = c_i·(1−d_max) = {row.rhs!r} < lb_i = {lo!r} ⇒ "
                        "该行被变量下界**支配**（任何满足界的解都满足它）。"
                        "典型来源：c_i = 0 时 rhs = 0，而 lb_C5 = 0.01 ⇒ 行冗余。"
                        "保留下来的话，诊断层会把一个恒真的行报成「C8 通过」，"
                        "掩盖「该项没有有效成本地板」这一事实。",
                        removed=True,
                    )
                )
                return None
        return CompiledRow(
            constraint_id=row.constraint_id,
            origin=f"{row.constraint_id}:{row.form}",
            form=row.form,
            sense=row.sense,
            rhs=float(row.rhs),
            coefficients=tuple(row.coefficients),
            tolerance=row.tolerance,
            sources=tuple(row.sources),
            scope=row.scope,
            detail=row.detail,
            aux=tuple(row.aux),
        )

    for row in formulation.rows:
        if row.constraint_id == "C9":
            rows.extend(_expand_c9(formulation, z_min, pi_target, simplifications))
            continue
        if row.constraint_id == "C10":
            expanded = _expand_c10(formulation, tf_terms, simplifications)
            if expanded is not None:
                rows.append(expanded)
            continue
        compiled = _unit_rows(row)
        if compiled is not None:
            rows.append(compiled)

    if formulation.lb_c5 > 0:
        notes.append(
            f"C5 的 LP 下界已抬到报价分辨率：lb_C5 = {formulation.lb_c5!r}"
            "（= max(eps_price·P*, rounding.resolution)）"
        )

    return CompiledModel(
        variables=variables,
        rows=tuple(rows),
        objective_sense=formulation.objective_sense,
        objective_constant=float(formulation.objective_constant),
        solver_form=formulation.solver_form,
        simplifications=tuple(simplifications),
        notes=tuple(notes),
        source=source or formulation.source,
    )


def _p_coefficients_from_objective(
    formulation: Formulation,
) -> tuple[tuple[str, float], ...]:
    """C9 的系数 = 各 p 列的目标系数（∂Z/∂p）。

    **刻意从 ``Column.objective_coeff`` 复制**，而不是重写一遍
    ``q0_i · r_eff_i``：重写会引入第二个真相来源，两处一旦分叉，
    C9 就变成一条与目标不一致的约束，且不触发任何检查。
    系数为 0 的列不进稀疏行（LP 稀疏性）；判据 CC-06 会对目标的**非零**
    系数集合做对账，故此处跳过 0 不会漏项。
    """
    return tuple(
        (c.symbol, float(c.objective_coeff))
        for c in formulation.variables
        if c.family == "p" and abs(float(c.objective_coeff)) > ZERO_EPS
    )


def _expand_c9(
    formulation: Formulation,
    z_min: float | None,
    pi_target: float | None,
    simplifications: list[Simplification],
) -> list[CompiledRow]:
    """展开 C9 的两条子式。

    ``Z = Σ coef_i·p_i + obj_const``，故
    ``Z ≥ Z_min`` ⇔ ``Σ coef_i·p_i ≥ Z_min − obj_const``；
    而 ``Σ c_i q1_i = −obj_const``（目标常量项即负的成本总额），故
    ``Z ≥ pi_target·Σ c_i q1_i`` ⇔ ``Σ coef_i·p_i ≥ −(1 + pi_target)·obj_const``。
    两式的 rhs 全部由 ``objective_constant`` 推出，无第二处常量。
    """
    out: list[CompiledRow] = []
    coefs = _p_coefficients_from_objective(formulation)
    obj_const = float(formulation.objective_constant)

    if not coefs:
        simplifications.append(
            Simplification(
                "NOT_COMPILED", "C9",
                "目标系数全为 0（无有效 p 列）⇒ Z 对 p 恒定，C9 无对象",
                removed=True,
            )
        )
        return out

    if z_min is None:
        simplifications.append(
            Simplification(
                "NOT_COMPILED", "C9a",
                "未给 Z_min ⇒ 该子式不生成。注意：不生成 ≠ 满足——"
                "调用方须据此判 BLOCKED（激活了却算不出）。",
                removed=True,
            )
        )
    else:
        out.append(
            CompiledRow(
                constraint_id="C9a", origin="C9:LINEAR_INEQ", form="LINEAR_INEQ",
                sense=">=", rhs=float(z_min) - obj_const, coefficients=coefs,
                tolerance="eps_total", sources=("Z", "Z_min"),
                detail=f"Σ (q1·r_eff)_i · p_i >= Z_min − obj_const = {float(z_min) - obj_const!r}",
                expanded_from_objective=True,
            )
        )

    if pi_target is None:
        simplifications.append(
            Simplification(
                "NOT_COMPILED", "C9b",
                "未给 pi_target ⇒ 该子式不生成（同上，须在调用方判 BLOCKED）",
                removed=True,
            )
        )
    else:
        out.append(
            CompiledRow(
                constraint_id="C9b", origin="C9:LINEAR_INEQ", form="LINEAR_INEQ",
                sense=">=", rhs=-(1.0 + float(pi_target)) * obj_const,
                coefficients=coefs, tolerance="eps_total",
                sources=("Z", "pi_target", "c_i", "q1_point"),
                detail=(
                    "Σ (q1·r_eff)_i · p_i >= −(1 + pi_target)·obj_const"
                    f" = {-(1.0 + float(pi_target)) * obj_const!r}"
                    "（分母 Σ c_i q1_i 为常量，已移项）"
                ),
                expanded_from_objective=True,
            )
        )
    return out


def _expand_c10(
    formulation: Formulation,
    tf_terms: Mapping[str, Sequence[float]] | None,
    simplifications: list[Simplification],
) -> CompiledRow | None:
    """C10：``Σ_{i∈T_front} (rho_i·p_i − c_i)·q0_i ≥ 0``。

    移项后：``Σ_{i∈T_front} (rho_i·q0_i)·p_i ≥ Σ_{i∈T_front} c_i·q0_i``。
    系数 ``rho_i·q0_i`` 与 rhs ``Σ c_i q0_i`` 都由 ``tf_terms`` 里的三元组算出
    ——本函数不"猜"任何一项。

    ``T_front`` 与 ``rho_i`` 来自招标文件付款条款（外生），不在 ``Formulation``
    里。未提供时**不生成**并登记 NOT_COMPILED。绝不退回「假设 T_front 为空」
    （那会把「未声明」算成「约束恒成立」，ADR-0007 同类失效）或「用全部项代替」
    （那是另一条约束，不是本条）。
    """
    if not tf_terms:
        simplifications.append(
            Simplification(
                "NOT_COMPILED", "C10",
                "T_front / rho_i 未声明（来自付款条款，非从数据推断的量）⇒ "
                "该约束不生成。**不得**退回「T_front 为空 ⇒ 恒成立」——"
                "那是把「未声明」读成「已声明为空」。",
                removed=True,
            )
        )
        return None

    coefs: list[tuple[str, float]] = []
    rhs = 0.0
    missing: list[str] = []
    for c in formulation.variables:
        if c.family != "p":
            continue
        term = tf_terms.get(c.item_id)
        if term is None:
            continue
        rho, q0, ci = (float(term[0]), _f(term[1]), _f(term[2]))
        if q0 is None or ci is None:
            missing.append(c.item_id)
            continue
        coefs.append((c.symbol, rho * q0))
        rhs += ci * q0

    if missing:
        simplifications.append(
            Simplification(
                "NOT_COMPILED", "C10",
                f"T_front 含项 {sorted(missing)}，但缺 q0 或 c_i ⇒ 系数不可算。"
                "不生成而非跳过该几项——跳过会得到一条**比原约束更弱**的约束"
                "（少了几项的正贡献），且不报错。",
                removed=True,
            )
        )
        return None
    if not coefs:
        simplifications.append(
            Simplification("NOT_COMPILED", "C10",
                           "T_front 与 X_opt 无交集 ⇒ 无可展开的项", removed=True)
        )
        return None
    return CompiledRow(
        constraint_id="C10", origin="C10:LINEAR_INEQ", form="LINEAR_INEQ",
        sense=">=", rhs=rhs, coefficients=tuple(coefs), tolerance="eps_total",
        sources=("rho_i", "q0", "c_i", "T_front"),
        detail=f"Σ_{{T_front}} (rho_i·q0_i)·p_i >= Σ_{{T_front}} c_i·q0_i = {rhs!r}",
    )


# ---------------------------------------------------------------------------
# 制品与判据
# ---------------------------------------------------------------------------


def load_compiler_spec(config_dir: Path) -> dict[str, Any]:
    return json.loads(
        (Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# 符号 ↔ 建模器名：可逆编码
#
# **为什么必须自己做编码。** 建模器对变量名有自己的规矩，且规矩是「净化」而不是
# 「报错」：PuLP 把 ``-`` / ``/`` / 空格 / ``[`` / ``]`` / ``+`` 一律替换成 ``_``
# 之后才存名字。后果有两条，都不报错：
#
# ① **两个不同符号可能合并成同一个变量。** 实测 ``p_A-B`` 与 ``p_A_B`` 在 PuLP
#    里都变成 ``a_b`` 风格的名字，导出的模型里只有一个变量——原模型的两个决策
#    变量被静默焊成了一个。
# ② **回读时符号对不上。** ``prob.variables()`` 给的是净化后的名字，适配层按
#    ``CompiledModel`` 的符号去取值会一个也取不到 ⇒ 解被判「全部缺失」。
#
# 修法不是在适配层做字符串修补（那是把建模器的规矩抄进业务侧），而是：**导出层
# 自己拥有一套可逆编码**，把符号映到建模器一定不会改动的字符集 ``[A-Za-z0-9_]``，
# 并在 CC-09 里验证这套编码在真实符号集上**单射**（合并是这里唯一灾难性的失败）。
# ---------------------------------------------------------------------------

#: 转义引导符。它本身不在安全字符集内，故永远不会以裸字符出现在编码结果里。
SYMBOL_ESCAPE = "~"
#: 转义后的定长十六进制码位数（``~%04x``），保证解码无歧义。
SYMBOL_ESCAPE_HEX = 4
#: 转义码的进制。**必须具名**——CC-12 要求表达式里不得出现裸数值，连 ``int(x, 16)``
#: 的进制也不例外（首跑就被本判据抓出来，见 ADR-0023 决策七）。
SYMBOL_ESCAPE_RADIX = 16
#: 建模器放行的额外字符。``~`` 是转义引导符——**必须先验证它自己不会被净化**，
#: 否则编码出来的名字照样走样。2026-09-17 实测 PuLP 3.3.2 放行 ``~``。
SYMBOL_SAFE_EXTRA = "_~"
#: 实测（2026-09-17，PuLP 3.3.2，穷举全部可打印字符）：建模器**只**把这七个字符
#: 换成 ``_``——``+ - / > [ ]`` 与空格。这份清单不参与判定（判定用上面的白名单，
#: 白名单比黑名单稳），它的用途只有一个：让「编码结果不含这些字符」成为可断言的
#: 事（tests/test_solver_backend.py 直接断言与之不相交）。
MODELER_MANGLED_CHARS = "+-/ >[]"


def _symbol_char_is_safe(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch in SYMBOL_SAFE_EXTRA)


def encode_symbol(symbol: str) -> str:
    """模型符号 → 建模器安全名。**可逆且单射**（安全字符集外一律转义）。"""
    out: list[str] = []
    for ch in symbol:
        if _symbol_char_is_safe(ch):
            out.append(ch)
        else:
            out.append(
                SYMBOL_ESCAPE + format(ord(ch), "0{}x".format(SYMBOL_ESCAPE_HEX))
            )
    return "".join(out)


def decode_symbol(name: str) -> str:
    """建模器安全名 → 模型符号。``encode_symbol`` 的逆。"""
    out: list[str] = []
    i = 0
    step = 1 + SYMBOL_ESCAPE_HEX
    while i < len(name):
        if name[i] == SYMBOL_ESCAPE and i + step <= len(name):
            out.append(chr(int(name[i + 1: i + step], SYMBOL_ESCAPE_RADIX)))
            i += step
        else:
            out.append(name[i])
            i += 1
    return "".join(out)


def pulp_name_map(model: "CompiledModel") -> dict[str, str]:
    """``{建模器安全名: 模型符号}``。适配层回读解时用它，不再靠名字猜。"""
    return {encode_symbol(v.symbol): v.symbol for v in model.variables}


def pulp_available() -> bool:
    """本机能否导入 PuLP——探测方式与 ``to_pulp`` **逐字相同**（``import pulp``）。

    为什么这个探针住在本模块而不是 CLI：求解器包只允许在 ``solver/backend.py``
    与 ``solver/compiler.py`` 的函数体内导入（``solver_backend_spec.audit``
    的 BB-03）。若 CLI 自己 ``import pulp`` 去写输出文案，BB-03 会（正确地）
    判违规。探针放在这里，叙事与 CC-09 的 SKIP 判据同源：**「本机有没有后端」
    这件事只有一个答案来源**，CLI 只是读它，不另造一个。

    用途：让 CLI 的「N 条 SKIP」提示**别再把环境说反**。SKIP ≠ PASS 这句话
    永远成立；但「本机无 PuLP」只是一个**猜测**——装上 PuLP 后它就成了假话，
    而剩下的 SKIP（如 LP 变体的 CC-08）是结构性豁免，与 PuLP 无关。
    """
    try:
        import pulp  # noqa: F401                        # type: ignore
    except ImportError:
        return False
    return True


def to_pulp(model: CompiledModel) -> Any:
    """惰性导出为 PuLP 对象。**未安装 PuLP 时返回 ``None``**（调用方判 SKIP）。

    本函数不求解、不调用 HiGHS——那属 T04-02C（backend adapter）。
    """
    try:                                        # pragma: no cover - 环境相关
        import pulp                                          # type: ignore
    except ImportError:
        return None

    sense = (
        pulp.LpMaximize if model.objective_sense == "MAXIMIZE" else pulp.LpMinimize
    )
    prob = pulp.LpProblem("bid_pricing", sense)
    xv: dict[str, Any] = {}
    for v in model.variables:
        safe = encode_symbol(v.symbol)
        if v.kind == "BINARY":
            var = pulp.LpVariable(safe, cat="Binary")
        else:
            var = pulp.LpVariable(
                safe,
                lowBound=v.lower if v.lower is not None else None,
                upBound=v.upper if v.upper is not None else None,
            )
        xv[v.symbol] = var
    # 符号闭包在**构造前**自查。理由不是洁癖：CC-09 会调用本函数，若这里抛
    # KeyError，那条本来该报「符号闭包破了」的判据会以异常形态炸掉整条校验，
    # 而不是报出一条 FAIL——判据不能在它该拦的输入上崩。故转成 CompilerError，
    # 由 CC-09 归一到 BLOCKED 并带出缺口清单。
    undeclared = sorted(model.all_symbols() - set(xv))
    if undeclared:
        raise CompilerError(
            f"行里引用了变量表未声明的符号 {undeclared} ⇒ 无法构造后端对象。"
            "这属符号闭包缺口（CC-03 的职责），导出层只如实拒绝，不代它补声明。"
        )
    prob += pulp.lpSum(
        v.objective_coeff * xv[v.symbol] for v in model.variables
    ) + model.objective_constant
    for r in model.rows:
        expr = pulp.lpSum(c * xv[s] for s, c in r.coefficients)
        if r.sense == "==":
            prob += (expr == r.rhs)
        elif r.sense == "<=":
            prob += (expr <= r.rhs)
        else:
            prob += (expr >= r.rhs)
    return prob


#: PuLP 的 LpConstraintSense 取值（pulp.constants：LE = -1, EQ = 0, GE = 1）。
#: 写成常量表而不是引用 pulp 的符号名，是为了让本函数能在**未安装 PuLP** 的环境里
#: 用替身对象单测——否则这段代码在本仓永远不会被执行到（PuLP 确实未安装）。
PULP_SENSE = {-1: "<=", 0: "==", 1: ">="}

#: PuLP 的优化方向取值。**先核实后写死**：PuLP 的常量是 ``LpMinimize = 1``、
#: ``LpMaximize = -1``（与直觉相反）。2026-09-17 实测确认（``pulp.LpMinimize = 1``）。
#: 写成表以免为了取方向而在本模块顶层 import pulp。
PULP_OBJECTIVE_SENSE = {-1: "MAXIMIZE", 1: "MINIMIZE"}


def extract_pulp_structure(prob: Any) -> dict[str, Any]:
    """把 PuLP 对象还原成可比较的稀疏结构（供 CC-09 后端等价性对账）。

    刻意**不调用 solve**：等价性是对模型的，不是对解的。

    **名字一律经 ``decode_symbol`` 还原成模型符号**：建模器存的是净化过的名字，
    直接拿它去和 ``CompiledModel`` 比会把名字差异报成结构差异，也会让真正的
    结构差异（系数错位）淹没在噪声里。

    依赖的 PuLP 接口面压到最小——``prob.constraints`` /
    ``LpConstraint.sense`` / ``.items()`` / ``.constant`` / ``prob.objective`` /
    ``prob.sense`` / ``prob.variables()``。接口面越小，替身对象单测越有意义。
    """
    rows: list[dict[str, Any]] = []
    for name, cons in prob.constraints.items():
        sense = PULP_SENSE.get(getattr(cons, "sense", None))
        if sense is None:
            raise CompilerError(
                f"无法识别 PuLP 约束 {name!r} 的 sense="
                f"{getattr(cons, 'sense', None)!r}。PuLP 的 LpConstraintSense "
                "取值若变更，此处必须同步——不得退回『默认 <=』之类的猜测，"
                "那会静默反转不等式方向。"
            )
        rows.append(
            {
                "name": str(name),
                "sense": sense,
                "rhs": -float(getattr(cons, "constant", 0.0) or 0.0),
                "coefficients": {
                    decode_symbol(v.name): float(c) for v, c in cons.items()
                },
            }
        )
    obj = prob.objective
    raw_sense = getattr(prob, "sense", None)
    obj_sense = PULP_OBJECTIVE_SENSE.get(raw_sense, f"UNKNOWN({raw_sense!r})")
    return {
        "rows": rows,
        "objective_sense": obj_sense,
        "objective_coefficients": {
            decode_symbol(v.name): float(c) for v, c in obj.items()
        },
        "objective_constant": float(getattr(obj, "constant", 0.0) or 0.0),
        "variables": sorted(decode_symbol(v.name) for v in prob.variables()),
    }


# ---------------------------------------------------------------------------
# CC 判据：编译正确性
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompilerCheck:
    """一条 CC 判据的结果。状态域与 F 判据同构。"""

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


def _round(x: Any, nd: int = FINGERPRINT_ND) -> Any:
    return round(float(x), nd) if isinstance(x, (int, float)) else x


def _fingerprint(rhs: Any, coefs: Iterable[tuple[str, float]]) -> tuple:
    """一行的可比较指纹。**按值取整，不做归一化**——归一化会把
    ``c_i`` 与 ``cap_i`` 折叠成同一个数值指纹，恰好放过要拦的那个错。
    """
    return (_round(rhs), tuple(sorted((str(s), _round(c)) for s, c in coefs)))


def _match(src: list[tuple], mod: list[tuple]) -> tuple[list[tuple], list[tuple]]:
    """多重集配对：返回 ``(仅在 src、仅在 mod)``。"""
    a, b = list(src), list(mod)
    for fp in list(a):
        if fp in b:
            a.remove(fp)
            b.remove(fp)
    return a, b


def check_compiled(
    model: CompiledModel,
    formulation: Formulation,
    *,
    instance: Any = None,
    resolved: ResolvedParameters | None = None,
    constraint_schema: Mapping[str, Any] | None = None,
    formulation_spec: Mapping[str, Any] | None = None,
    compiler_source: str | None = None,
    literal_allowlist: Sequence[float] | None = None,
    eps_total: float,
) -> tuple[CompilerCheck, ...]:
    """CC-01..CC-12。

    这批判据回答一句话：**编译出来的模型，确实是那份声明的模型吗？**
    故它们全部是**跨来源对账**——一侧是 ``Formulation``（声明），一侧是
    ``CompiledModel``（实现产物），CC-07 再加一侧业务公式。
    两侧同源的对账（「编译系数 == 编译系数」）在这里毫无意义。
    """
    from .instance import check_solution          # 延迟导入，避免环

    items: list[CompilerCheck] = []
    S = "T04-02B"
    declared = {v.symbol for v in model.variables}
    src_vars = {c.symbol: c for c in formulation.variables}
    registered = {s.subject for s in model.simplifications}
    model_origins = {r.origin for r in model.rows}

    # ---------------- CC-01 行溯源双向一致 -----------------------------
    src_keys = {f"{r.constraint_id}:{r.form}" for r in formulation.rows}
    unknown = sorted(model_origins - src_keys)
    missing: list[str] = []
    for r in formulation.rows:
        key = f"{r.constraint_id}:{r.form}"
        if key in model_origins:
            continue
        if r.constraint_id in ("C9", "C10"):
            continue          # 展开型由 CC-05 / CC-11 单独管
        if any(sub.split(":")[0] == r.constraint_id for sub in registered):
            continue          # 已在化简台账登记
        missing.append(key)
    items.append(CompilerCheck(
        S, "CC-01 行集溯源双向一致",
        STATUS_PASS if not (unknown or missing) else STATUS_FAIL,
        ("编译出的每一行都可溯源到 Formulation，且声明的行无遗漏"
         if not (unknown or missing)
         else f"无法溯源的行 {unknown}；声明了却既未编译也未登记的行 {missing}"),
        actual={"unknown_origins": unknown, "missing_origins": sorted(set(missing))},
        expected=[],
    ))

    # ---------------- CC-02 系数与源行逐项一致 -------------------------
    src_by_key: dict[str, list[tuple]] = {}
    for r in formulation.rows:
        if r.rhs is None:
            continue
        src_by_key.setdefault(f"{r.constraint_id}:{r.form}", []).append(
            _fingerprint(r.rhs, r.coefficients)
        )
    mod_by_key: dict[str, list[tuple]] = {}
    for row in model.rows:
        if row.expanded_from_objective:
            continue
        mod_by_key.setdefault(row.origin, []).append(
            _fingerprint(row.rhs, row.coefficients)
        )
    extra: dict[str, list] = {}
    lost: dict[str, list] = {}
    for key in set(src_by_key) | set(mod_by_key):
        a, b = _match(src_by_key.get(key, []), mod_by_key.get(key, []))
        if b:
            extra[key] = b
        if a and not any(
            sub.split(":")[0] == key.split(":")[0] for sub in registered
        ):
            lost[key] = a
    items.append(CompilerCheck(
        S, "CC-02 系数/右端与源行逐项一致",
        STATUS_PASS if not (extra or lost) else STATUS_FAIL,
        ("全部行的系数与 rhs 与 Formulation 逐项相同（未做任何改写）"
         if not (extra or lost)
         else f"编译器凭空多出的行 {extra}；未编译也未登记的源行 {lost}"),
        actual={"invented": extra, "dropped": lost}, expected={},
    ))

    # ---------------- CC-03 符号闭包 -----------------------------------
    orphans = sorted(model.all_symbols() - declared)
    items.append(CompilerCheck(
        S, "CC-03 行的符号闭包",
        STATUS_PASS if not orphans else STATUS_FAIL,
        ("所有行引用的符号都在变量表内" if not orphans
         else f"行引用了未声明的变量 {orphans}——典型来源是手写了一列变量"),
        actual=orphans, expected=[],
    ))

    # ---------------- CC-04 变量表与 Formulation 一致 -------------------
    var_diffs: list[str] = []
    if set(src_vars) != declared:
        var_diffs.append(
            f"符号集不同：仅在声明侧 {sorted(set(src_vars) - declared)}，"
            f"仅在编译侧 {sorted(declared - set(src_vars))}"
        )
    for v in model.variables:
        c = src_vars.get(v.symbol)
        if c is None:
            continue
        for f in ("kind", "family"):
            if getattr(c, f) != getattr(v, f):
                var_diffs.append(
                    f"{v.symbol}.{f}: {getattr(c, f)!r} -> {getattr(v, f)!r}")
        for f in ("lower", "upper", "objective_coeff"):
            if _round(getattr(c, f)) != _round(getattr(v, f)):
                var_diffs.append(
                    f"{v.symbol}.{f}: {getattr(c, f)!r} -> {getattr(v, f)!r}")
    items.append(CompilerCheck(
        S, "CC-04 变量表（界/类型/目标系数）一致",
        STATUS_PASS if not var_diffs else STATUS_FAIL,
        ("变量表与 Formulation 逐字段相同" if not var_diffs
         else f"{len(var_diffs)} 处不一致：{var_diffs[:SAMPLE_LIMIT]}"),
        actual=var_diffs, expected=[],
    ))

    # ---------------- CC-05 可执行性 -----------------------------------
    # NOT_COMPILED 也必须计入：源行存在（即该约束被激活）却因缺输入没能进模型，
    # 就是「算式算不出」——按 ADR-0013 判 BLOCKED，不得因为「已登记」就放行。
    # 登记解决的是**可追溯性**（查得到为什么没编译），不是**正确性**。
    bad_rows: list[str] = []
    for row in model.rows:
        if not row.coefficients:
            bad_rows.append(
                f"{row.constraint_id}: 系数为空 ⇒ 该行是 0 {row.sense} {row.rhs}，"
                "求解器读作恒真或恒假，须判 BLOCKED 而非放行")
        if row.rhs != row.rhs or row.rhs in (float("inf"), float("-inf")):
            bad_rows.append(f"{row.constraint_id}: rhs = {row.rhs!r} 非有限")
    not_compiled = [s for s in model.simplifications if s.kind == "NOT_COMPILED"]
    bad_rows.extend(
        f"{s.subject}: 该约束被激活却未能编译（{s.reason[:REASON_TRUNC]}…）"
        for s in not_compiled
    )
    items.append(CompilerCheck(
        S, "CC-05 每行可执行（非空系数、有限右端）",
        STATUS_PASS if not bad_rows else STATUS_BLOCKED,
        (f"{model.n_rows} 行全部可执行，且无被激活却未编译的约束"
         if not bad_rows
         else f"{len(bad_rows)} 处不可执行/未编译：{bad_rows[:SAMPLE_LIMIT]}"),
        actual=bad_rows, expected=[],
    ))

    # ---------------- CC-06 目标一致 -----------------------------------
    obj_diffs: list[str] = []
    for v in model.variables:
        c = src_vars.get(v.symbol)
        if c is not None and _round(c.objective_coeff) != _round(v.objective_coeff):
            obj_diffs.append(
                f"{v.symbol}: {c.objective_coeff!r} -> {v.objective_coeff!r}")
    if _round(formulation.objective_constant) != _round(model.objective_constant):
        obj_diffs.append(
            f"objective_constant: {formulation.objective_constant!r} -> "
            f"{model.objective_constant!r}")
    if formulation.objective_sense != model.objective_sense:
        obj_diffs.append(
            f"objective_sense: {formulation.objective_sense!r} -> "
            f"{model.objective_sense!r}")
    items.append(CompilerCheck(
        S, "CC-06 目标方向/系数/常量一致",
        STATUS_PASS if not obj_diffs else STATUS_FAIL,
        ("目标与 Formulation 一致" if not obj_diffs
         else f"{len(obj_diffs)} 处不一致：{obj_diffs[:SAMPLE_LIMIT]}"),
        actual=obj_diffs, expected=[],
    ))

    # ---------------- CC-07 代回复核（编译侧 vs 业务式，跨来源）----------
    if instance is None or resolved is None:
        items.append(CompilerCheck(
            S, "CC-07 代回复核（编译侧 vs 业务式，跨来源）", STATUS_SKIP,
            "未提供实例 ⇒ 无法与业务侧 check_solution 对账。"
            "**SKIP 不等于 PASS**——它只表示本轮没检查。",
        ))
    else:
        p_by_id = {
            i.item_id: float(i.p0 if i.p0 is not None else 0.0)
            for i in instance.items
            if i.role == "OPTIMIZABLE"
        }
        x: dict[str, float] = {}
        for v in model.variables:
            if v.family == "p":
                x[v.symbol] = p_by_id.get(v.item_id, 0.0)
            elif v.family == "s":
                c_i = next((i.c_i for i in instance.items
                            if i.item_id == v.item_id), None)
                x[v.symbol] = max(
                    float(c_i or 0.0) - x.get(f"p_{v.item_id}", 0.0), 0.0)
            else:
                x[v.symbol] = 0.0
        ev = evaluate(model, x)
        biz = check_solution(instance, p_by_id, resolved, eps_total=eps_total)
        diffs: list[str] = []
        c1_row = next((r for r in ev.rows if r.constraint_id == "C1"), None)
        if c1_row is not None and biz.competitive_total is not None:
            if abs(c1_row.lhs - biz.competitive_total) > max(
                SLACK_RTOL, SLACK_ATOL * abs(biz.competitive_total)
            ):
                diffs.append(
                    f"C1 左端：编译侧 {c1_row.lhs!r} vs 业务侧 "
                    f"{biz.competitive_total!r}")
        if abs(ev.objective - biz.Z) > max(
            SLACK_RTOL, SLACK_ATOL * max(abs(biz.Z), 1.0)
        ):
            diffs.append(f"目标值：编译侧 {ev.objective!r} vs 业务侧 {biz.Z!r}")
        items.append(CompilerCheck(
            S, "CC-07 代回复核（编译侧 vs 业务式，跨来源）",
            STATUS_PASS if not diffs else STATUS_FAIL,
            ("同一报价向量下，编译模型的 C1 左端与目标值均与业务式重算一致"
             if not diffs else "；".join(diffs)),
            actual=diffs, expected=[],
        ))

    # ---------------- CC-08 C7 双 M 的恒真性 ---------------------------
    m_bad: list[str] = []
    n_checked = 0
    for row in model.rows:
        if row.constraint_id == "C7.lower":
            m_lo = row.aux_get("M_lo")
            lb_i = row.aux_get("lb_i")
            if m_lo is None or lb_i is None:
                continue
            n_checked += 1
            c_i = row.rhs                     # C7.lower 的 rhs 就是 c_i
            if float(c_i) - float(m_lo) > float(lb_i) + ZERO_EPS:
                m_bad.append(
                    f"{row.constraint_id}: z=1 时 p >= c_i - M_lo = "
                    f"{float(c_i) - float(m_lo)!r} > lb_i = {lb_i!r} ⇒ "
                    "该式在 z=1 处并非恒真，会额外收紧下界")
        elif row.constraint_id == "C7.upper":
            m_hi = row.aux_get("M_hi")
            ub_eff = row.aux_get("ub_eff")
            eps = row.aux_get("eps_res")
            if m_hi is None or ub_eff is None or eps is None:
                continue
            n_checked += 1
            need = float(ub_eff) - float(row.aux_get("c_i") or 0.0) + float(eps)
            if float(m_hi) < need - ZERO_EPS:
                m_bad.append(
                    f"{row.constraint_id}: M_hi = {m_hi!r} < ub_eff - c_i + eps = "
                    f"{need!r} ⇒ z=0 时该行把 p 压到 {row.rhs!r}，切掉 "
                    f"({row.rhs!r}, {ub_eff!r}] 的可行区间")
            if row.rhs < float(ub_eff) - ZERO_EPS:
                m_bad.append(
                    f"{row.constraint_id}: z=0 时 p <= rhs = {row.rhs!r} < "
                    f"ub_eff = {ub_eff!r} ⇒ 该式在 z=0 处并非恒真")
    if n_checked == 0:
        items.append(CompilerCheck(
            S, "CC-08 C7 双 M 的恒真条件", STATUS_SKIP,
            "本变体不含 C7 指示式（未激活）⇒ 无可检对象。"
            "**SKIP 不等于 PASS**：恒真条件是否被满足，取决于 MILP 变体的结果。",
        ))
    else:
        items.append(CompilerCheck(
            S, "CC-08 C7 双 M 的恒真条件",
            STATUS_PASS if not m_bad else STATUS_FAIL,
            (f"{n_checked} 条指示式各自满足其恒真条件（下式的 M 覆盖 lb、"
             "上式的 M 覆盖 ub）" if not m_bad
             else f"{len(m_bad)} 处不满足：{m_bad[:SAMPLE_LIMIT]}"),
            actual=m_bad, expected=[],
        ))

    # ---------------- CC-09 PuLP 后端等价（缺失 ⇒ SKIP）-----------------
    #
    # 三条出口必须分开，否则「导出层拒绝了这份模型」会被读成「本机没装 PuLP」：
    #   ① 构造失败（符号闭包缺口等）⇒ BLOCKED，带出缺口；
    #   ② PuLP 未安装（to_pulp 返回 None）⇒ SKIP，带复跑条件；
    #   ③ 构造成功 ⇒ 逐项对账。
    prob = None
    export_error: str | None = None
    try:
        prob = to_pulp(model)
    except CompilerError as exc:
        export_error = str(exc)
    if export_error is not None:
        items.append(CompilerCheck(
            S, "CC-09 PuLP 后端结构等价", STATUS_BLOCKED,
            f"导出层无法构造后端对象：{export_error}",
        ))
    elif prob is None:
        items.append(CompilerCheck(
            S, "CC-09 PuLP 后端结构等价", STATUS_SKIP,
            "环境未安装 PuLP ⇒ 本轮未验证导出等价性。**SKIP 不等于 PASS**："
            "本判据须在装有 PuLP 的环境（T04-02C）复跑。",
        ))
    else:
        try:
            struct = extract_pulp_structure(prob)
        except CompilerError as exc:
            items.append(CompilerCheck(
                S, "CC-09 PuLP 后端结构等价", STATUS_BLOCKED, str(exc)))
        else:
            # 覆盖面（2026-09-17 T04-02C 补齐）：变量集、行数、**逐行系数多重集**、
            # 逐行 sense、逐行 rhs、目标方向、目标常量、目标系数。
            #
            # 原实现只比 sense/rhs/目标系数，漏掉逐行系数、目标常量与目标方向——
            # 而导出层最常见的三种走样恰好落在漏掉的区间里：① 系数漏乘/错位；
            # ② 目标常量丢符号；③ 最大化↔最小化反向。三者都满足「变量集相同、
            # 行数相同、sense 相同、rhs 相同、目标系数相同」。
            #
            # 行比对改为**多重集配对**（与 CC-02 同构），不按下标：原实现隐含假设
            # 「CompiledModel.rows 的顺序 == PuLP constraints 的插入顺序」，该假设
            # 从未被声明，一旦 PuLP 改字典行为就会以「rhs 不同」的名义报一堆假 FAIL，
            # 把真问题（某行系数错了）淹没。
            bad: list[str] = []
            eng_vars = set(struct["variables"])
            if eng_vars != declared:
                bad.append(f"变量集不同：{sorted(eng_vars ^ declared)}")
            # 符号编码必须**单射**：两个符号映到同一安全名 ⇒ 导出后它们会被
            # 建模器当成同一个变量（实测 PuLP 把 `-` `/` 空格 `[` `]` `+` 一律
            # 换成 `_`），两个决策变量静默焊成一个，不报任何错。这是导出层唯一
            # 灾难性的失败，单独判。
            safe_seen: dict[str, list[str]] = {}
            for s in declared:
                safe_seen.setdefault(encode_symbol(s), []).append(s)
            collisions = {
                safe: syms for safe, syms in safe_seen.items() if len(syms) > 1
            }
            if collisions:
                bad.append(
                    "符号编码不单射（导出后会被静默合并成一个变量）："
                    f"{list(collisions.items())[:SAMPLE_LIMIT]}"
                )
            # 往返一致：编码后必须落在建模器不会改动的字符集里，否则回读的
            # 名字与模型符号对不上 ⇒ 解会被判「全部变量缺失」。
            not_roundtrip = [
                s for s in declared if decode_symbol(encode_symbol(s)) != s
            ]
            if not_roundtrip:
                bad.append(
                    f"编码不可逆：{not_roundtrip[:SAMPLE_LIMIT]}"
                )
            if struct["objective_sense"] != model.objective_sense:
                bad.append(
                    f"目标方向 {struct['objective_sense']!r} != "
                    f"{model.objective_sense!r}（方向反向会让最优解变成最劣解）"
                )
            if abs(struct["objective_constant"] - model.objective_constant) > (
                COEFF_ATOL + COEFF_RTOL * abs(model.objective_constant)
            ):
                bad.append(
                    f"目标常量 {struct['objective_constant']!r} != "
                    f"{model.objective_constant!r}（丢符号是最常见的形态）"
                )
            if len(struct["rows"]) != model.n_rows:
                bad.append(f"行数 {len(struct['rows'])} != {model.n_rows}")
            src_fp = [
                _fingerprint(r.rhs, r.coefficients) for r in model.rows
            ]
            eng_fp = [
                _fingerprint(r["rhs"], list(r["coefficients"].items()))
                for r in struct["rows"]
            ]
            only_src, only_eng = _match(src_fp, eng_fp)
            for fp in only_src[:SAMPLE_LIMIT]:
                bad.append(f"模型里有而导出后没有的行：{fp}")
            for fp in only_eng[:SAMPLE_LIMIT]:
                bad.append(f"导出后有而模型里没有的行：{fp}")
            for v in model.variables:
                got = struct["objective_coefficients"].get(v.symbol, 0.0)
                if abs(got - v.objective_coeff) > (
                    COEFF_ATOL + COEFF_RTOL * abs(v.objective_coeff)
                ):
                    bad.append(f"{v.symbol}: 目标系数 {got} != {v.objective_coeff}")
            bad = [str(b) for b in bad[:SAMPLE_LIMIT]]
            items.append(CompilerCheck(
                S, "CC-09 PuLP 后端结构等价",
                STATUS_PASS if not bad else STATUS_FAIL,
                ("导出的 PuLP 对象与 CompiledModel 结构一致"
                 "（变量集/行系数多重集/sense/rhs/目标方向/目标常量/目标系数）"
                 if not bad else f"{len(bad)} 处不一致：{bad}"),
                actual=bad, expected=[],
            ))

    # ---------------- CC-10 C11 裁定落值一致（跨制品）-------------------
    c11_problems: list[str] = []
    sel = None
    if constraint_schema is not None:
        c11 = next((c for c in constraint_schema.get("constraints", [])
                    if c.get("id") == "C11"), None)
        if c11 is None:
            c11_problems.append("constraint_schema 缺 C11")
        else:
            sel = c11.get("selected_form")
            expr = str(c11.get("expression") or "")
            if not sel:
                c11_problems.append(
                    "C11.selected_form 缺失 ⇒ 形式未定。**未定不得静默处理**："
                    "要么在 LP 内（须给 model_form），要么移出 LP（须登记）。")
            elif "sigma" in expr and str(sel).startswith("MAD"):
                c11_problems.append(
                    f"expression 用 sigma 而 selected_form = {sel} ⇒ 度量替换。"
                    "MAD <= sigma（Cauchy-Schwarz）是**放松**，"
                    "不得作为 sigma 约束的实现。")
    if formulation_spec is not None:
        c11f = next((c for c in formulation_spec.get("constraint_map", [])
                     if c.get("constraint_id") == "C11"), None)
        if c11f is None:
            c11_problems.append("lp_formulation_spec 缺 C11")
        elif sel and c11f.get("model_form") != sel:
            c11_problems.append(
                f"两份制品的 C11 形式不一致：constraint_schema={sel!r} vs "
                f"lp_formulation_spec={c11f.get('model_form')!r}")
    if constraint_schema is None and formulation_spec is None:
        items.append(CompilerCheck(
            S, "CC-10 C11 裁定落值一致（跨制品）", STATUS_SKIP, "未提供制品"))
    else:
        items.append(CompilerCheck(
            S, "CC-10 C11 裁定落值一致（跨制品）",
            STATUS_PASS if not c11_problems else STATUS_FAIL,
            (f"C11 形式 = {sel!r}，两份制品一致且无度量替换"
             if not c11_problems else "；".join(c11_problems)),
            actual=c11_problems, expected=[],
        ))

    # ---------------- CC-11 化简台账完备 -------------------------------
    ledger_bad: list[str] = []
    for s in model.simplifications:
        if not s.reason.strip():
            ledger_bad.append(f"{s.subject}: 无理由")
        if s.kind == "DEGENERATE_DOMINATED" and "lb_i" not in s.reason:
            ledger_bad.append(f"{s.subject}: 支配性判定未给出被支配的量")
    items.append(CompilerCheck(
        S, "CC-11 化简台账完备（不得静默丢弃）",
        STATUS_PASS if not ledger_bad else STATUS_FAIL,
        (f"{len(model.simplifications)} 条化简/未编译项均已登记且带可复算理由"
         if not ledger_bad else f"{ledger_bad[:SAMPLE_LIMIT]}"),
        actual=sorted(registered), expected=[],
    ))

    # ---------------- CC-12 编译器字面量审计 ---------------------------
    if compiler_source is None:
        items.append(CompilerCheck(
            S, "CC-12 编译器字面量审计", STATUS_SKIP, "未提供编译器源码"))
    else:
        allow = set(literal_allowlist or DEFAULT_LITERAL_ALLOWLIST)
        found = _audit_literals(compiler_source, allow)
        items.append(CompilerCheck(
            S, "CC-12 编译器字面量审计",
            STATUS_PASS if not found else STATUS_FAIL,
            (f"源码中的数值字面量全部在白名单内（{sorted(allow)}）——"
             "没有手写系数" if not found
             else f"出现白名单外的数值字面量：{found[:SAMPLE_LIMIT]}。"
                  "编译器的系数必须来自制品/Row，字面量即手写约束的可疑入口"),
            actual=found, expected=sorted(allow),
        ))

    return tuple(items)


def _audit_literals(source: str, allow: set[float]) -> list[tuple[int, float]]:
    """列出源码中**直接出现在表达式里**的、不在 ``allow`` 内的数值字面量。

    规则是「**数值必须具名**」而非「数值必须为 0/1」：
    赋给具名常量的字面量被豁免（有名字即可审计名字、可被引用、可被 grep），
    直接躺在表达式里的才报出来。这比按值白名单更贴合本判据要拦的东西——
    手写系数长这样：``rhs = 0.85 * cap``、``M = 1e9``；而比较容差长这样：
    ``SLACK_ATOL = 1e-9``。

    2026-09-17 首版按值白名单，结果把本模块自己的比较容差（1e-6 / 1e-9）与
    截断长度（60 / 5）全部报成「手写系数」——**判据把正常实现报成违规**，
    于是白名单被越加越长，判据也就慢慢失去意义。
    同日第二处同类误报：``term[2]`` 的切片下标 2。两次都指向同一条经验——
    **判据把正常实现报成违规，先改判据**。
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:                   # pragma: no cover
        raise CompilerError(f"编译器源码无法解析：{exc}") from exc

    named: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            val = node.value
            if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)):
                named.add(id(val))

    # 切片下标/边界也是**结构系数**（制品 literal_allowlist.rationale 明写
    # 「切片下标、偏移」）。``term[2]`` 里的 2 是下标不是系数：若不豁免，判据
    # 又会把正常实现报成违规（首跑即把 ``_expand_c10`` 的 ``term[2]`` 报成
    # 「手写系数 (585, 2)」）——与首版按值白名单犯的是同一类错：判据的问题，
    # 不是实现的问题。故把出现在 Subscript 索引位 / Slice 边界的常量一并豁免。
    structural: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            for c in ast.walk(node.slice):
                if isinstance(c, ast.Constant):
                    structural.add(id(c))
        elif isinstance(node, ast.Slice):
            for b in (node.lower, node.upper, node.step):
                if isinstance(b, ast.Constant):
                    structural.add(id(b))

    allowed = {float(a) for a in allow}
    out: list[tuple[int, float]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            continue
        if id(node) in named or id(node) in structural:
            continue
        if float(node.value) in allowed:
            continue
        out.append((getattr(node, "lineno", -1), node.value))
    return sorted(set(out))
