"""T04-02B 的测试：``Formulation`` → ``CompiledModel`` 的编译保真与判据区分度。

分三层（与 ``test_lp_formulation`` 同构）：

1. **构造层**：``compile_model`` 的形状与展开（C9 从目标系数、C10 从 T_front）。
2. **判据层**：CC-01..CC-12 在正确实现上不得出现 FAIL/BLOCKED（本机 CC-09 SKIP；
   LP 变体 CC-08 SKIP）。
3. **区分度层**（本文件最重要的一层）：把已知的错误编译注入回去，确认对应判据
   真的 FAIL/BLOCKED。**判据「全 PASS」本身不说明任何事——能被错误的值否定
   才是判据的全部价值。**

区分度层的每个样本都对应一条真实失效模式（不是为测试造的假想）：
吞掉一行的模型看起来完全正常；凭空多出一行 = 手写约束；把 M_hi 取小会切掉
可行区间却不报错；把 NOT_COMPILED 从 BLOCKED 降级会让「算不出」被读成「通过」。
"""

from __future__ import annotations

import dataclasses
import json
import unittest
from pathlib import Path

from bidpricing.contracts.pricing_card import ResolvedParameters
from bidpricing.solver import formulation as fm
from bidpricing.solver.compiler import (
    DEFAULT_LITERAL_ALLOWLIST,
    CompiledModel,
    CompiledRow,
    CompiledVar,
    Simplification,
    _audit_literals,
    check_compiled,
    compile_model,
    evaluate,
    extract_pulp_structure,
    to_pulp,
)
from bidpricing.solver.formulation import PROBE_SOLVER_INPUTS, build_formulation, probe_instance

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config"


def _resolved(scope: str = "SEGMENT") -> ResolvedParameters:
    return ResolvedParameters(
        rho_plus=0.0, rho_minus=0.0,
        increase_threshold=1.15, decrease_threshold=0.85,
        adjustment_scope=scope,
    )


def _load(name: str) -> dict:
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


_SOLVER_INPUTS = dict(PROBE_SOLVER_INPUTS)


def _formulation(active=(), **overrides):
    inst = probe_instance(active=tuple(active))
    inputs = dict(_SOLVER_INPUTS)
    inputs.update(overrides)
    return inst, build_formulation(inst, _resolved(), **inputs)


def _cc(checks, prefix: str):
    return next(c for c in checks if c.item.startswith(prefix))


def _run_checks(model, formulation, instance, *, schema=None, fspec=None,
                compiler_source=None, allow=None, eps_total=0.01):
    return check_compiled(
        model, formulation,
        instance=instance, resolved=_resolved(),
        constraint_schema=schema, formulation_spec=fspec,
        compiler_source=compiler_source, literal_allowlist=allow,
        eps_total=eps_total,
    )


class TestCompileConstruction(unittest.TestCase):
    def test_lp_variant_shapes(self):
        inst, f = _formulation()
        model = compile_model(f)
        self.assertEqual(model.n_vars, f.n_vars, "变量列必须一一对应，不增不减")
        self.assertEqual(model.solver_form, "LP")
        src_keys = {f"{r.constraint_id}:{r.form}" for r in f.rows}
        for row in model.rows:
            self.assertIn(row.origin, src_keys,
                          "编译器产出的每一行都必须带可溯源的 origin")

    def test_c9_expansion_from_objective(self):
        inst, f = _formulation(("C9",))
        model = compile_model(f, z_min=1000.0, pi_target=0.05)
        c9a = model.rows_of("C9a")
        c9b = model.rows_of("C9b")
        self.assertEqual(len(c9a), 1)
        self.assertEqual(len(c9b), 1)
        obj_const = f.objective_constant
        self.assertAlmostEqual(c9a[0].rhs, 1000.0 - obj_const, places=6)
        self.assertAlmostEqual(c9b[0].rhs, -(1.0 + 0.05) * obj_const, places=6)
        # 系数必须**复制**自目标系数，而不是重写一遍公式
        p_coeff = {c.symbol: c.objective_coeff for c in f.variables
                   if c.family == "p" and abs(c.objective_coeff) > 1e-15}
        got = dict(c9a[0].coefficients)
        self.assertEqual(set(got), set(p_coeff))
        for s, v in got.items():
            self.assertAlmostEqual(v, p_coeff[s], places=9)

    def test_c9_not_compiled_without_inputs(self):
        inst, f = _formulation(("C9",))
        model = compile_model(f)          # 不给 z_min / pi_target
        self.assertEqual(model.rows_of("C9a"), ())
        self.assertEqual(model.rows_of("C9b"), ())
        kinds = {(s.kind, s.subject) for s in model.simplifications}
        self.assertIn(("NOT_COMPILED", "C9a"), kinds)
        self.assertIn(("NOT_COMPILED", "C9b"), kinds)

    def test_c10_expansion(self):
        inst, f = _formulation(("C10",))
        tf = {"P-DEC": [0.3, 1000.0, 400.0], "P-IN": [0.2, 2000.0, 600.0]}
        model = compile_model(f, tf_terms=tf)
        c10 = model.rows_of("C10")
        self.assertEqual(len(c10), 1)
        self.assertAlmostEqual(c10[0].rhs, 400.0 * 1000.0 + 600.0 * 2000.0, places=6)
        got = dict(c10[0].coefficients)
        self.assertAlmostEqual(got["p_P-DEC"], 0.3 * 1000.0, places=9)
        self.assertAlmostEqual(got["p_P-IN"], 0.2 * 2000.0, places=9)

    def test_c10_not_compiled_without_terms(self):
        inst, f = _formulation(("C10",))
        model = compile_model(f)
        self.assertEqual(model.rows_of("C10"), ())
        self.assertIn(("NOT_COMPILED", "C10"),
                      {(s.kind, s.subject) for s in model.simplifications})

    def test_c10_partial_input_drops_whole_row(self):
        inst, f = _formulation(("C10",))
        # P-IN 只给 rho 与 q0，缺 c_i ⇒ 整行不得生成（跳过该项会得到更弱的约束）
        tf = {"P-DEC": [0.3, 1000.0, 400.0], "P-IN": [0.2, 2000.0, None]}
        model = compile_model(f, tf_terms=tf)
        self.assertEqual(model.rows_of("C10"), ())
        self.assertIn(("NOT_COMPILED", "C10"),
                      {(s.kind, s.subject) for s in model.simplifications})

    def test_missing_rhs_row_dropped_and_logged(self):
        # C6 激活但未给 theta ⇒ 汇总行 rhs = None ⇒ 不得进模型，须登记 NOT_COMPILED
        inst, f = _formulation(("C6",), theta=None)
        model = compile_model(f)
        self.assertEqual(model.rows_of("C6"), ())
        self.assertIn(("NOT_COMPILED", "C6:LINEAR_INEQ"),
                      {(s.kind, s.subject) for s in model.simplifications})


class TestEvaluate(unittest.TestCase):
    def _tiny(self) -> CompiledModel:
        return CompiledModel(
            variables=(
                CompiledVar("p_I", "p", "I", "CONTINUOUS", 0.0, 10.0, 2.0),
            ),
            rows=(
                CompiledRow(
                    constraint_id="C1", origin="C1:EQUALITY", form="EQUALITY",
                    sense="==", rhs=4.0, coefficients=(("p_I", 1.0),),
                    tolerance="eps_solver"),
            ),
            objective_sense="MAXIMIZE",
            objective_constant=1.0,
            solver_form="LP",
        )

    def test_feasible_and_objective(self):
        ev = evaluate(self._tiny(), {"p_I": 4.0})
        self.assertTrue(ev.feasible)
        self.assertAlmostEqual(ev.objective, 1.0 + 2.0 * 4.0, places=9)

    def test_infeasible_when_row_violated(self):
        ev = evaluate(self._tiny(), {"p_I": 5.0})
        self.assertFalse(ev.feasible)
        self.assertTrue(ev.violations())
        self.assertEqual(ev.violations()[0].constraint_id, "C1")

    def test_missing_assignment_is_not_silently_zero(self):
        ev = evaluate(self._tiny(), {})
        self.assertFalse(ev.feasible)
        self.assertEqual(ev.missing, ("p_I",))


class TestCheckLayerGreen(unittest.TestCase):
    """正确实现上，判据不得出现 FAIL/BLOCKED。"""

    def setUp(self):
        self.schema = _load("constraint_schema.json")
        self.fspec = _load("lp_formulation_spec.json")
        self.src = (REPO / "src" / "bidpricing" / "solver" / "compiler.py").read_text(
            encoding="utf-8")

    def test_lp_probe_no_fail_no_blocked(self):
        inst, f = _formulation()
        model = compile_model(f)
        checks = _run_checks(model, f, inst, schema=self.schema,
                             fspec=self.fspec, compiler_source=self.src)
        bad = [c.item for c in checks if c.blocks_progress]
        self.assertEqual(bad, [], f"LP 探针不应有 FAIL/BLOCKED：{bad}")
        # CC-08（无 C7 行）与 CC-09（无 PuLP）必须 SKIP，而不是 PASS
        self.assertEqual(_cc(checks, "CC-08").status, "SKIP")
        self.assertEqual(_cc(checks, "CC-09").status, "SKIP")

    def test_milp_probe_cc08_actually_checks(self):
        inst, f = _formulation(("C7",))
        model = compile_model(f)
        checks = _run_checks(model, f, inst, schema=self.schema,
                             fspec=self.fspec, compiler_source=self.src)
        cc08 = _cc(checks, "CC-08")
        self.assertEqual(cc08.status, "PASS")
        bad = [c.item for c in checks if c.blocks_progress]
        self.assertEqual(bad, [], f"MILP 探针（给了 N_max）不应有 FAIL/BLOCKED：{bad}")

    def test_milp_without_nmax_blocks_cc05(self):
        # 未给 N_max ⇒ C7 汇总行 rhs=None ⇒ NOT_COMPILED ⇒ BLOCKED（ADR-0013：
        # 激活了却算不出 = 算式算不出）。**不得**静默当恒真而放行。
        inst, f = _formulation(("C7",), n_max=None)
        model = compile_model(f)
        checks = _run_checks(model, f, inst, schema=self.schema, fspec=self.fspec)
        self.assertEqual(_cc(checks, "CC-05").status, "BLOCKED")

    def test_cc07_skips_without_instance(self):
        inst, f = _formulation()
        model = compile_model(f)
        checks = check_compiled(
            model, f, constraint_schema=self.schema, formulation_spec=self.fspec,
            eps_total=0.01)
        cc07 = _cc(checks, "CC-07")
        self.assertEqual(cc07.status, "SKIP")
        self.assertIn("SKIP", cc07.reason)


class TestDistinctionLayer(unittest.TestCase):
    """注入错误实现 ⇒ 对应判据必须 FAIL/BLOCKED。"""

    def setUp(self):
        self.schema = _load("constraint_schema.json")
        self.fspec = _load("lp_formulation_spec.json")

    def _base(self, active=()):
        inst, f = _formulation(active)
        model = compile_model(f)
        return inst, f, model

    def _checks(self, model, f, inst, **kw):
        return _run_checks(model, f, inst, schema=self.schema, fspec=self.fspec, **kw)

    def test_cc01_catches_dropped_row(self):
        inst, f, model = self._base()
        rows = tuple(r for r in model.rows if r.constraint_id != "C2")
        broken = dataclasses.replace(model, rows=rows)
        self.assertEqual(_cc(self._checks(broken, f, inst), "CC-01").status, "FAIL")

    def test_cc02_catches_invented_row(self):
        inst, f, model = self._base()
        extra = CompiledRow(
            constraint_id="C2", origin="C2:BOX_UPPER", form="BOX_UPPER",
            sense="<=", rhs=12345.0,
            coefficients=(("p_P-IN", 1.0),), tolerance="eps_price")
        broken = dataclasses.replace(model, rows=model.rows + (extra,))
        self.assertEqual(_cc(self._checks(broken, f, inst), "CC-02").status, "FAIL")

    def test_cc03_catches_symbol_outside_table(self):
        inst, f, model = self._base()
        rows = list(model.rows)
        rows[0] = dataclasses.replace(
            rows[0], coefficients=(("p_GHOST", 1.0),))
        broken = dataclasses.replace(model, rows=tuple(rows))
        self.assertEqual(_cc(self._checks(broken, f, inst), "CC-03").status, "FAIL")

    def test_cc04_catches_changed_bound(self):
        inst, f, model = self._base()
        vs = list(model.variables)
        vs[0] = dataclasses.replace(vs[0], upper=1.0)
        broken = dataclasses.replace(model, variables=tuple(vs))
        self.assertEqual(_cc(self._checks(broken, f, inst), "CC-04").status, "FAIL")

    def test_cc05_blocks_on_not_compiled(self):
        inst, f, model = self._base()
        broken = dataclasses.replace(
            model,
            simplifications=model.simplifications + (
                Simplification("NOT_COMPILED", "C10", "缺 T_front"),))
        self.assertEqual(_cc(self._checks(broken, f, inst), "CC-05").status,
                         "BLOCKED")

    def test_cc05_blocks_on_empty_coefficients(self):
        inst, f, model = self._base()
        bad = CompiledRow(
            constraint_id="C1", origin="C1:EQUALITY", form="EQUALITY",
            sense="==", rhs=1.0, coefficients=(), tolerance="eps_solver")
        broken = dataclasses.replace(model, rows=model.rows + (bad,))
        self.assertEqual(_cc(self._checks(broken, f, inst), "CC-05").status,
                         "BLOCKED")

    def test_cc06_catches_changed_objective_constant(self):
        inst, f, model = self._base()
        broken = dataclasses.replace(model, objective_constant=0.0)
        self.assertEqual(_cc(self._checks(broken, f, inst), "CC-06").status, "FAIL")

    def test_cc08_catches_undersized_m_hi(self):
        inst, f, model = self._base(("C7",))
        rows = []
        touched = False
        for r in model.rows:
            if r.constraint_id == "C7.upper":
                touched = True
                aux = tuple((k, v * 0.1 if k == "M_hi" else v) for k, v in r.aux)
                r = dataclasses.replace(r, aux=aux)
            rows.append(r)
        self.assertTrue(touched, "MILP 变体应含 C7.upper 行")
        broken = dataclasses.replace(model, rows=tuple(rows))
        self.assertEqual(_cc(self._checks(broken, f, inst), "CC-08").status, "FAIL")

    def test_cc10_catches_artifact_divergence(self):
        inst, f, model = self._base()
        bad_fspec = json.loads(json.dumps(self.fspec))
        for c in bad_fspec["constraint_map"]:
            if c.get("constraint_id") == "C11":
                c["model_form"] = "NONLINEAR_DEFERRED"
        checks = _run_checks(model, f, inst, schema=self.schema,
                             fspec=bad_fspec)
        self.assertEqual(_cc(checks, "CC-10").status, "FAIL")

    def test_cc10_catches_missing_selected_form(self):
        inst, f, model = self._base()
        bad_schema = json.loads(json.dumps(self.schema))
        for c in bad_schema["constraints"]:
            if c.get("id") == "C11":
                c["selected_form"] = None
        checks = _run_checks(model, f, inst, schema=bad_schema,
                             fspec=self.fspec)
        self.assertEqual(_cc(checks, "CC-10").status, "FAIL")

    def test_cc11_catches_reason_without_dominated_quantity(self):
        inst, f, model = self._base()
        broken = dataclasses.replace(
            model,
            simplifications=(Simplification(
                "DEGENERATE_DOMINATED", "C8:p_X", "该行被下界支配"),))
        self.assertEqual(_cc(self._checks(broken, f, inst), "CC-11").status, "FAIL")

    def test_cc12_catches_bare_literal_in_source(self):
        inst, f, model = self._base()
        src = "def f(cap):\n    return 0.85 * cap\n"
        checks = self._checks(model, f, inst, compiler_source=src)
        self.assertEqual(_cc(checks, "CC-12").status, "FAIL")


class TestLiteralAudit(unittest.TestCase):
    """CC-12 的规则是「数值必须具名」，不是「数值必须为 0/1」。"""

    def test_actual_compiler_source_is_clean(self):
        src = (REPO / "src" / "bidpricing" / "solver" / "compiler.py").read_text(
            encoding="utf-8")
        found = _audit_literals(src, set(DEFAULT_LITERAL_ALLOWLIST))
        self.assertEqual(found, [], f"编译器源码不应有裸字面量：{found}")

    def test_named_constant_is_exempt(self):
        src = "SLACK_ATOL = 1e-9\nx = SLACK_ATOL\n"
        self.assertEqual(_audit_literals(src, set(DEFAULT_LITERAL_ALLOWLIST)), [])

    def test_subscript_index_is_structural(self):
        # term[2] 的 2 是下标不是系数（制品明写「切片下标」属结构系数）
        src = "def f(term):\n    return term[2] + term[3]\n"
        self.assertEqual(_audit_literals(src, set(DEFAULT_LITERAL_ALLOWLIST)), [])

    def test_bare_coefficient_is_caught(self):
        src = "def f(cap):\n    return 0.85 * cap + 1e9\n"
        found = _audit_literals(src, set(DEFAULT_LITERAL_ALLOWLIST))
        vals = sorted({v for _l, v in found})
        self.assertIn(0.85, vals)
        self.assertIn(1e9, vals)


class TestPulpLazyExport(unittest.TestCase):
    """零依赖环境：导出是可选层，缺失判 SKIP 而非 FAIL。"""

    def test_to_pulp_returns_none_without_pulp(self):
        inst, f = _formulation()
        model = compile_model(f)
        try:
            import pulp  # noqa: F401
            available = True
        except ImportError:
            available = False
        if not available:
            self.assertIsNone(to_pulp(model))

    def test_extract_pulp_structure_with_stub(self):
        class _Cons:
            def __init__(self, sense, constant, items):
                self.sense = sense
                self.constant = constant
                self._items = items

            def items(self):
                return self._items

        class _Var:
            def __init__(self, name):
                self.name = name

        class _Obj:
            constant = 1.25

            def items(self):
                return [(_Var("p_I"), 2.0)]

        class _Prob:
            constraints = {"C1": _Cons(1, 0.0, [(_Var("p_I"), 1.0)])}
            objective = _Obj()

            def variables(self):
                return [_Var("p_I")]

        struct = extract_pulp_structure(_Prob())
        self.assertEqual(struct["rows"][0]["sense"], ">=")
        self.assertEqual(struct["rows"][0]["coefficients"], {"p_I": 1.0})
        self.assertAlmostEqual(struct["objective_constant"], 1.25)
        self.assertEqual(struct["variables"], ["p_I"])


if __name__ == "__main__":
    unittest.main()
