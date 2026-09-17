"""T04-02D 解校验器的区分度测试（SV-01..SV-13）。

两条纪律（与仓内其余测试同源）：

1. **每条判据都要有「什么会让它不通过」的用例**。只断言「真实制品上判 PASS」
   的测试对判据的否定能力毫无信息——一个恒真的判据也能全绿。
2. **不得依赖第三方库**。本文件在零依赖环境（无 PuLP）下必须全绿：需要解的分支
   直接构造赋值向量（等价于注入一个解），不调用求解器。

另有一条本文件特有的第三纪律：**复核层的独立性要有测试**——SV-12 不但要验
「真实源码判 PASS」，还要验「把内层调用塞回去会被抓住」。
"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from bidpricing.cli import config_dir
from bidpricing.contracts.pricing_card import load_pricing_card, resolve_parameters
from bidpricing.solver.compiler import (
    CompiledModel,
    CompiledRow,
    CompiledVar,
    compile_model,
    evaluate,
)
from bidpricing.solver.formulation import (
    PROBE_SOLVER_INPUTS,
    build_formulation,
    compute_lb_c5,
    probe_instance,
)
from bidpricing.solver.verifier import (
    EPS_Z_ABS_NAME,
    EPS_Z_REL_NAME,
    FORBIDDEN_CALLS,
    FORBIDDEN_IMPORTS,
    INNER_TOLERANCE_NAME,
    MIN_TOLERANCE_RATIO,
    OUTER_TOLERANCE_NAME,
    SCOPE,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    TIER_AMBIGUOUS,
    TIER_BOUNDARY_HIGH,
    TIER_BOUNDARY_LOW,
    TIER_INFEASIBLE,
    TIER_INTERIOR,
    VerifierError,
    audit_verifier_source,
    load_verifier_spec,
    resolve_row_tolerance,
    resolve_tolerances,
    row_verdicts,
    verify_solution,
)

CFG = config_dir()
PROFILE = json.loads((CFG / "precision_profile.json").read_text(encoding="utf-8"))
VSPEC = load_verifier_spec(CFG)
VERIFIER_SRC = (
    Path(__file__).resolve().parents[1] / "src" / "bidpricing" / "solver" / "verifier.py"
)

#: 探针 LP 变体的**手算可行解**：500·1000 + 700·2000 + 600·1000 + 100·500 = 2,550,000 = B。
FEASIBLE_PRICES = {"P-DEC": 500.0, "P-IN": 700.0, "P-INC": 600.0, "P-FREE": 100.0}

_PROBE_CACHE: dict[tuple[str, ...], tuple[CompiledModel, object, object]] = {}


def _resolved():
    return resolve_parameters(load_pricing_card(CFG))


def _probe_model(*, active=()):
    """探针实例的编译结果（带缓存，理由同 test_solver_backend）。"""
    key = tuple(active)
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    instance = probe_instance(active=active)
    fm = build_formulation(
        instance, _resolved(),
        eps_abs=float(PROFILE["eps_abs"]["value"]),
        eps_price=float(PROFILE["eps_price"]["value"]),
        resolution=float(PROFILE["rounding"]["resolution"]),
        **{k: PROBE_SOLVER_INPUTS[k] for k in
           ("theta", "n_max", "d_max", "r_min", "z_min", "pi_target")},
    )
    model = compile_model(
        fm, z_min=PROBE_SOLVER_INPUTS["z_min"],
        pi_target=PROBE_SOLVER_INPUTS["pi_target"], source="LP",
    )
    _PROBE_CACHE[key] = (model, fm, instance)
    return _PROBE_CACHE[key]


def _full_x(model, instance, prices=None):
    """构造一个**完整**的赋值向量（缺任何符号都会触发 SV-04）。"""
    prices = prices or FEASIBLE_PRICES
    c_of = {i.item_id: i.c_i for i in instance.items}
    x: dict[str, float] = {}
    for v in model.variables:
        if v.family == "p":
            x[v.symbol] = float(prices.get(v.item_id, 0.0))
        else:
            x[v.symbol] = 0.0
    for v in model.variables:
        if v.family == "s":
            x[v.symbol] = max(
                float(c_of.get(v.item_id) or 0.0) - x.get(f"p_{v.item_id}", 0.0), 0.0
            )
    return x


def _tolerances(instance, **overrides):
    P_ref = instance.P_star if instance.P_star is not None else instance.B
    tols, _ = resolve_tolerances(PROFILE, VSPEC, P_ref=P_ref)
    tols.update(overrides)
    return tols


def _verify(model, x, instance, **kwargs):
    return verify_solution(
        model, x, spec=VSPEC, profile=kwargs.pop("profile", PROFILE),
        instance=instance,
        verifier_source=kwargs.pop("verifier_source", VERIFIER_SRC.read_text(encoding="utf-8")),
        **kwargs,
    )


def _check(report, judge_id):
    c = report.of(judge_id)
    assert c is not None, f"报告里没有 {judge_id}"
    return c


# ---------------------------------------------------------------------------
# 容差名 → 数值
# ---------------------------------------------------------------------------


class TestToleranceResolution(unittest.TestCase):
    def test_all_layer_names_resolve(self):
        inst = probe_instance()
        tols, problems = resolve_tolerances(PROFILE, VSPEC, P_ref=inst.P_star)
        for name in (INNER_TOLERANCE_NAME, OUTER_TOLERANCE_NAME,
                     "eps_price", "eps_rel_price", "eps_total", "0（整数）"):
            self.assertIn(name, tols, name)
            self.assertIsInstance(tols[name], float)
        # eps_quantity 是预留名：解析不出（缺 Q_ref）**不**算问题被用到的名字。
        self.assertIn("eps_quantity", problems)

    def test_price_is_relative_times_p_ref(self):
        """DV-02 的名字分离：eps_price（绝对量）== eps_rel_price（相对量）× P_ref。"""
        tols, _ = resolve_tolerances(PROFILE, VSPEC, P_ref=3.0e6)
        self.assertAlmostEqual(tols["eps_price"], tols["eps_rel_price"] * 3.0e6, places=12)
        self.assertAlmostEqual(tols["eps_rel_price"], 1e-9, places=15)

    def test_lb_c5_must_use_the_relative_name(self):
        """把已 ×P* 的 eps_price 喂给 compute_lb_c5 会**乘重一遍**（DV-02 的复现）。"""
        tols, _ = resolve_tolerances(PROFILE, VSPEC, P_ref=3.0e6)
        right = compute_lb_c5(3.0e6, tols["eps_rel_price"], 0.01)
        wrong = compute_lb_c5(3.0e6, tols["eps_price"], 0.01)
        self.assertAlmostEqual(right, 0.01, places=12)          # max(0.003, 0.01)
        self.assertAlmostEqual(wrong, 9000.0, places=6)         # 0.003 × 3e6
        self.assertGreater(wrong / right, 1e5)

    def test_missing_p_ref_is_reported_per_name(self):
        _tols, problems = resolve_tolerances(PROFILE, VSPEC, P_ref=None)
        self.assertIn("eps_price", problems)
        self.assertIn("eps_total", problems)
        self.assertNotIn("eps_abs", problems)      # 不依赖 P_ref

    def test_unknown_resolver_verb_is_reported(self):
        bad = copy.deepcopy(VSPEC)
        bad["tolerance_name_resolution"]["table"]["eps_abs"]["resolver"] = "MAGIC"
        tols, problems = resolve_tolerances(PROFILE, bad, P_ref=1.0)
        self.assertNotIn("eps_abs", tols)
        self.assertIn("eps_abs", problems)

    def test_name_not_in_table_returns_none(self):
        """未声明的容差名不得静默取任何默认值。"""
        row = CompiledRow("C1", "C1", "EQUALITY", "==", 1.0, (), "eps_typo")
        name, value = resolve_row_tolerance(row, {"eps_abs": 0.01})
        self.assertEqual(name, "eps_typo")
        self.assertIsNone(value)

    def test_table_is_closed_over_allowed_resolvers(self):
        allowed = set(VSPEC["tolerance_name_resolution"]["resolvers"]["allowed"])
        for name, rule in VSPEC["tolerance_name_resolution"]["table"].items():
            self.assertIn(rule["resolver"], allowed, name)


# ---------------------------------------------------------------------------
# SV-01 声明容差名全可解析
# ---------------------------------------------------------------------------


class TestSV01(unittest.TestCase):
    def test_pass_on_real_probe(self):
        model, _fm, inst = _probe_model()
        rep = _verify(model, _full_x(model, inst), inst)
        self.assertEqual(_check(rep, "SV-01").status, STATUS_PASS)

    def test_blocks_on_unknown_row_tolerance_name(self):
        model, _fm, inst = _probe_model()
        bad_row = CompiledRow("CX", "CX", "LINEAR_INEQ", ">=", 0.0, (), "eps_typo")
        bad = CompiledModel(
            variables=model.variables, rows=model.rows + (bad_row,),
            objective_sense=model.objective_sense,
            objective_constant=model.objective_constant,
            solver_form=model.solver_form,
        )
        rep = _verify(bad, _full_x(model, inst), inst)
        c = _check(rep, "SV-01")
        self.assertEqual(c.status, STATUS_BLOCKED)
        self.assertIn("eps_typo", c.reason)


# ---------------------------------------------------------------------------
# SV-02 / SV-03 可行性 + 容差带
# ---------------------------------------------------------------------------


class TestSV02And03(unittest.TestCase):
    def test_feasible_solution_passes(self):
        model, _fm, inst = _probe_model()
        rep = _verify(model, _full_x(model, inst), inst)
        self.assertEqual(_check(rep, "SV-02").status, STATUS_PASS)

    def test_row_beyond_declared_tolerance_fails(self):
        """区分度：把 C1 的赋值推到超出声明容差，SV-02 必须 FAIL。"""
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        x["p_P-DEC"] = x["p_P-DEC"] + 1.0     # C1 残差 = 1.0·q0 = 1000 × … >> eps_solver
        rep = _verify(model, x, inst)
        c = _check(rep, "SV-02")
        self.assertEqual(c.status, STATUS_FAIL)
        self.assertIn("C1", c.reason)

    def test_band_row_is_pass_not_fail_and_is_flagged(self):
        """DV-01 的正例：残差落在 [1e-12, eps_solver] 内必须判 PASS 并标为带内。"""
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        q0 = dict(next(r for r in model.rows if r.constraint_id == "C1").coefficients)
        x["p_P-DEC"] = x["p_P-DEC"] + 5e-9 / q0["p_P-DEC"]
        tols = _tolerances(inst)
        rows = row_verdicts(model, x, tols)
        c1 = next(r for r in rows if r.constraint_id == "C1")
        self.assertGreater(c1.violation, 0.0)
        self.assertLessEqual(c1.violation, tols[INNER_TOLERANCE_NAME])
        self.assertTrue(c1.in_band)
        self.assertTrue(c1.ok_declared)

        rep = _verify(model, x, inst)
        self.assertEqual(_check(rep, "SV-02").status, STATUS_PASS)
        self.assertEqual(_check(rep, "SV-03").status, STATUS_PASS)

    def test_probe_does_not_exercise_the_band_so_judge_warns(self):
        """探针的最优值可精确表示 ⇒ 容差带没被走到 ⇒ SV-03 必须判 WARN 而不是 PASS。

        这一条防的是「把『这一轮没走到』读成『已成立』」。
        """
        model, _fm, inst = _probe_model()
        rep = _verify(model, _full_x(model, inst), inst)
        c = _check(rep, "SV-03")
        self.assertEqual(c.status, STATUS_WARN)
        self.assertIn("未被本实例验证", c.reason)


# ---------------------------------------------------------------------------
# SV-04 缺变量 / 未编译项
# ---------------------------------------------------------------------------


class TestSV04(unittest.TestCase):
    def test_pass_on_complete_solution(self):
        model, _fm, inst = _probe_model()
        rep = _verify(model, _full_x(model, inst), inst)
        self.assertEqual(_check(rep, "SV-04").status, STATUS_PASS)

    def test_blocks_on_missing_variable(self):
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        x.pop("p_P-DEC")
        rep = _verify(model, x, inst)
        self.assertEqual(_check(rep, "SV-04").status, STATUS_BLOCKED)

    def test_blocks_on_not_compiled_entry(self):
        """NOT_COMPILED 项必须让 SV-04 判 BLOCKED，不得当作「已满足」。"""
        model, _fm, inst = _probe_model()
        from bidpricing.solver.compiler import Simplification

        bad = CompiledModel(
            variables=model.variables, rows=model.rows,
            objective_sense=model.objective_sense,
            objective_constant=model.objective_constant,
            solver_form=model.solver_form,
            simplifications=(Simplification("NOT_COMPILED", "C9", "缺 z_min"),),
        )
        rep = _verify(bad, _full_x(model, inst), inst)
        c = _check(rep, "SV-04")
        self.assertEqual(c.status, STATUS_BLOCKED)
        self.assertIn("C9", c.reason)


# ---------------------------------------------------------------------------
# SV-05 目标值（跨来源）
# ---------------------------------------------------------------------------


class TestSV05(unittest.TestCase):
    def test_pass_when_reported_matches(self):
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        z = evaluate(model, x).objective
        rep = _verify(model, x, inst, reported_objective=z)
        self.assertEqual(_check(rep, "SV-05").status, STATUS_PASS)

    def test_fails_on_wrong_reported_objective(self):
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        z = evaluate(model, x).objective
        rep = _verify(model, x, inst, reported_objective=z + 10.0)
        self.assertEqual(_check(rep, "SV-05").status, STATUS_FAIL)

    def test_blocks_without_reported_objective(self):
        model, _fm, inst = _probe_model()
        rep = _verify(model, _full_x(model, inst), inst, reported_objective=None)
        self.assertEqual(_check(rep, "SV-05").status, STATUS_BLOCKED)

    def test_eps_z_uses_the_dimensionless_relative_name(self):
        """DV-02 的第二个复现面：ε_Z 的相对项用错名字会放大 1e5 倍。"""
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        rep = _verify(model, x, inst, reported_objective=evaluate(model, x).objective)
        c = _check(rep, "SV-05")
        self.assertEqual(c.status, STATUS_PASS)
        # ε_Z ≈ eps_abs + eps_rel_price·|Z| ≈ 0.01 + 1e-9 × 3.3e5 ≈ 0.0103
        eps_z = float(c.reason.split("ε_Z=")[1].rstrip("）"))
        self.assertGreater(eps_z, float(PROFILE["eps_abs"]["value"]))
        self.assertLess(eps_z, 1.0)
        self.assertNotIn("eps_price", EPS_Z_REL_NAME)

    def test_eps_z_names_are_declared_in_spec(self):
        table = VSPEC["tolerance_name_resolution"]["table"]
        self.assertIn(EPS_Z_ABS_NAME, table)
        self.assertIn(EPS_Z_REL_NAME, table)


# ---------------------------------------------------------------------------
# SV-06 两层容差宽度比（D1）
# ---------------------------------------------------------------------------


class TestSV06(unittest.TestCase):
    def test_real_profile_ratio_is_at_least_1e3(self):
        model, _fm, inst = _probe_model()
        rep = _verify(model, None, inst)
        c = _check(rep, "SV-06")
        self.assertEqual(c.status, STATUS_PASS)
        self.assertGreaterEqual(c.actual, MIN_TOLERANCE_RATIO)

    def test_downgrading_outer_to_inner_fails(self):
        """区分度：把外层容差压到与内层同宽 ⇒ 必须 FAIL（这正是 D1 禁的模式 B）。"""
        model, _fm, inst = _probe_model()
        prof = copy.deepcopy(PROFILE)
        prof["eps_abs"]["value"] = float(PROFILE["eps_solver"]["value"])
        rep = _verify(model, None, inst, profile=prof)
        c = _check(rep, "SV-06")
        self.assertEqual(c.status, STATUS_FAIL)
        self.assertAlmostEqual(c.actual, 1.0, places=12)


# ---------------------------------------------------------------------------
# SV-07 / SV-08 上下界
# ---------------------------------------------------------------------------


class TestSV07And08(unittest.TestCase):
    def test_blocks_when_floor_is_not_wired(self):
        """floor 缺席 ⇒ 该路 BLOCKED，且**不得**用 L_i 或 c_i 冒充。"""
        model, _fm, inst = _probe_model()
        rep = _verify(model, _full_x(model, inst), inst)
        c = _check(rep, "SV-07")
        self.assertEqual(c.status, STATUS_BLOCKED)
        self.assertIn("floor", c.reason)
        self.assertIn("不得用 L_i 或 c_i 冒充", c.reason)

    def test_pass_when_floor_is_supplied(self):
        model, _fm, inst = _probe_model()
        floor = {i.item_id: 0.0 for i in inst.items}
        rep = _verify(model, _full_x(model, inst), inst, floor_by_id=floor)
        self.assertEqual(_check(rep, "SV-07").status, STATUS_PASS)

    def test_violated_floor_fails_and_names_the_offending_bound(self):
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        floor = {i.item_id: 0.0 for i in inst.items}
        floor["P-DEC"] = x["p_P-DEC"] + 5.0          # 地板高于报价 ⇒ 违反
        rep = _verify(model, x, inst, floor_by_id=floor)
        c = _check(rep, "SV-07")
        self.assertEqual(c.status, STATUS_FAIL)
        self.assertIn("P-DEC", c.reason)
        self.assertIn("floor", c.reason)

    def test_binding_lower_is_reported(self):
        """编译侧把 C3/C4/C5 合并成一行，这里要把「哪一条在起作用」恢复出来。"""
        model, _fm, inst = _probe_model()
        floor = {"P-DEC": 0.0, "P-IN": 900.0, "P-INC": 0.0, "P-FREE": 0.0}
        rep = _verify(model, _full_x(model, inst), inst, floor_by_id=floor)
        binding = {b.item_id: b.binding_lower for b in rep.bounds}
        self.assertEqual(binding["P-IN"], "floor")     # 900 > L=400 > lb_C5=0.01
        self.assertEqual(binding["P-DEC"], "L")        # 300 > 0.01

    def test_upper_bound_violation_fails(self):
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        x["p_P-IN"] = 800.0                            # U = 700
        rep = _verify(model, x, inst)
        self.assertEqual(_check(rep, "SV-07").status, STATUS_FAIL)

    def test_small_bound_violation_is_warn_not_fail(self):
        """外层容差带内（≤ eps_abs）判 WARN；超过才 FAIL。"""
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        x["p_P-IN"] = 700.0 + 0.005                    # 半分辨率，仍在 eps_abs 内
        rep = _verify(model, x, inst)
        self.assertEqual(_check(rep, "SV-08").status, STATUS_WARN)

    def test_hard_bound_violation_is_fail(self):
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        x["p_P-IN"] = 700.0 + 1.0
        rep = _verify(model, x, inst)
        self.assertEqual(_check(rep, "SV-08").status, STATUS_FAIL)


# ---------------------------------------------------------------------------
# SV-09 / SV-10 / SV-11 层归属
# ---------------------------------------------------------------------------


class TestTierAttribution(unittest.TestCase):
    def _tiers(self, **kwargs):
        model, _fm, inst = _probe_model()
        floor = {i.item_id: 0.0 for i in inst.items}
        rep = _verify(model, _full_x(model, inst), inst,
                      floor_by_id=kwargs.pop("floor_by_id", floor), **kwargs)
        return rep, {t.item_id: t.tier for t in rep.tiers}

    def test_boundary_high_and_interior_are_distinguished(self):
        _rep, tiers = self._tiers()
        self.assertEqual(tiers["P-DEC"], TIER_BOUNDARY_HIGH)   # p == U
        self.assertEqual(tiers["P-FREE"], TIER_INTERIOR)       # 50 < 100，U 不限

    def test_boundary_low_when_price_sits_on_the_lower_bound(self):
        model, _fm, inst = _probe_model()
        floor = {i.item_id: 0.0 for i in inst.items}
        x = _full_x(model, inst, prices={**FEASIBLE_PRICES, "P-DEC": 300.0})
        rep = _verify(model, x, inst, floor_by_id=floor)
        tiers = {t.item_id: t.tier for t in rep.tiers}
        self.assertEqual(tiers["P-DEC"], TIER_BOUNDARY_LOW)
        self.assertEqual(_check(rep, "SV-10").status, STATUS_PASS)

    def test_missing_floor_makes_boundary_low_ambiguous(self):
        """floor 未接入 ⇒ 顶到下界的项**不得**直接归 BOUNDARY_LOW。"""
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst, prices={**FEASIBLE_PRICES, "P-DEC": 300.0})
        rep = _verify(model, x, inst)                     # floor_by_id=None
        tiers = {t.item_id: t.tier for t in rep.tiers}
        self.assertEqual(tiers["P-DEC"], TIER_AMBIGUOUS)
        self.assertEqual(_check(rep, "SV-10").status, STATUS_WARN)
        self.assertIn("floor", dict(rep.tiers and {"": ""}).get("", "") or
                      next(t.note for t in rep.tiers if t.item_id == "P-DEC"))

    def test_infeasible_tier_fails(self):
        model, _fm, inst = _probe_model()
        floor = {i.item_id: 0.0 for i in inst.items}
        x = _full_x(model, inst, prices={**FEASIBLE_PRICES, "P-DEC": 100.0})  # < L=300
        rep = _verify(model, x, inst, floor_by_id=floor)
        tiers = {t.item_id: t.tier for t in rep.tiers}
        self.assertEqual(tiers["P-DEC"], TIER_INFEASIBLE)
        self.assertEqual(_check(rep, "SV-11").status, STATUS_FAIL)

    def test_distribution_counts_every_class(self):
        _rep, _tiers = self._tiers()
        model, _fm, inst = _probe_model()
        floor = {i.item_id: 0.0 for i in inst.items}
        rep = _verify(model, _full_x(model, inst), inst, floor_by_id=floor)
        names = [k for k, _v in rep.tier_distribution]
        for expected in (TIER_BOUNDARY_LOW, TIER_INTERIOR, TIER_BOUNDARY_HIGH,
                         TIER_AMBIGUOUS, TIER_INFEASIBLE):
            self.assertIn(expected, names)


# ---------------------------------------------------------------------------
# SV-12 独立性
# ---------------------------------------------------------------------------


class TestSV12(unittest.TestCase):
    def test_real_source_passes(self):
        status, findings = audit_verifier_source(VERIFIER_SRC.read_text(encoding="utf-8"))
        self.assertEqual(status, STATUS_PASS)
        self.assertEqual(findings, [])

    def test_forbidden_call_is_caught(self):
        src = "from .compiler import evaluate\n\ndef f(m, x):\n    return evaluate(m, x)\n"
        status, findings = audit_verifier_source(src)
        self.assertEqual(status, STATUS_BLOCKED)
        self.assertTrue(any("evaluate" in f for f in findings))

    def test_check_solution_call_is_caught(self):
        src = "def f(i, p, r):\n    return check_solution(i, p, r)\n"
        status, findings = audit_verifier_source(src)
        self.assertEqual(status, STATUS_BLOCKED)
        self.assertTrue(any("check_solution" in f for f in findings))

    def test_solver_package_import_is_caught(self):
        src = "import pulp\n"
        status, _findings = audit_verifier_source(src)
        self.assertEqual(status, STATUS_BLOCKED)

    def test_mentioning_a_name_in_a_docstring_is_not_a_violation(self):
        """判据不得把正常实现报成违规：文档里提到这些名字不算调用。"""
        src = 'def f():\n    """本模块不调用 evaluate 与 check_solution。"""\n    return 1\n'
        status, findings = audit_verifier_source(src)
        self.assertEqual(status, STATUS_PASS)
        self.assertEqual(findings, [])

    def test_interface_has_no_solveresult_parameter(self):
        """类型级独立性：签名里不得出现 SolveResult。"""
        import inspect

        params = inspect.signature(verify_solution).parameters
        self.assertNotIn("result", params)
        self.assertNotIn("solve_result", params)
        kinds = {p.annotation for p in params.values()}
        self.assertFalse(
            any("SolveResult" in str(a) for a in kinds),
            f"签名里出现了 SolveResult：{kinds}",
        )

    def test_static_audit_lists_match_the_spec(self):
        level = VSPEC["independence"]["static_level"]
        self.assertEqual(tuple(level["forbidden_calls"]), FORBIDDEN_CALLS)
        self.assertEqual(tuple(level["forbidden_imports"]), FORBIDDEN_IMPORTS)


# ---------------------------------------------------------------------------
# SV-13 参考对照（T04-08 未落地 ⇒ BLOCKED）
# ---------------------------------------------------------------------------


class TestSV13(unittest.TestCase):
    def test_blocked_without_reference(self):
        model, _fm, inst = _probe_model()
        rep = _verify(model, _full_x(model, inst), inst)
        c = _check(rep, "SV-13")
        self.assertEqual(c.status, STATUS_BLOCKED)
        self.assertIn("T04-08", c.reason)

    def test_skipped_without_any_solution(self):
        """没有解 ⇒ 没检查（SKIP）；有解但没 Z_ref ⇒ 这一族没检查成（BLOCKED）。

        两者不得合并：合并会让「参考实现未落地」被读成「本轮没跑」。
        """
        model, _fm, inst = _probe_model()
        rep = _verify(model, None, inst)
        self.assertEqual(_check(rep, "SV-13").status, STATUS_SKIP)

    def test_pass_when_reference_agrees(self):
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        z = evaluate(model, x).objective
        rep = _verify(model, x, inst, reference=z)
        self.assertEqual(_check(rep, "SV-13").status, STATUS_PASS)

    def test_fail_when_reference_disagrees(self):
        model, _fm, inst = _probe_model()
        x = _full_x(model, inst)
        z = evaluate(model, x).objective
        rep = _verify(model, x, inst, reference=z * 1.1)
        self.assertEqual(_check(rep, "SV-13").status, STATUS_FAIL)

    def test_blocked_when_there_is_a_reference_but_no_solution(self):
        model, _fm, inst = _probe_model()
        rep = _verify(model, None, inst, reference=1.0)
        self.assertEqual(_check(rep, "SV-13").status, STATUS_SKIP)


# ---------------------------------------------------------------------------
# 汇总与缺输入
# ---------------------------------------------------------------------------


class TestVerdictAggregation(unittest.TestCase):
    def test_no_solution_is_skip_not_pass(self):
        model, _fm, inst = _probe_model()
        rep = _verify(model, None, inst)
        self.assertEqual(rep.verdict, STATUS_SKIP)
        for jid in ("SV-02", "SV-03", "SV-04", "SV-05",
                    "SV-07", "SV-08", "SV-09", "SV-10", "SV-11"):
            self.assertEqual(_check(rep, jid).status, STATUS_SKIP, jid)
        # 层级判据不需要解，照跑。
        self.assertEqual(_check(rep, "SV-01").status, STATUS_PASS)
        self.assertEqual(_check(rep, "SV-06").status, STATUS_PASS)
        self.assertEqual(_check(rep, "SV-12").status, STATUS_PASS)

    def test_no_instance_is_skip(self):
        model, _fm, _inst = _probe_model()
        rep = verify_solution(
            model, {"p_P-DEC": 1.0}, spec=VSPEC, profile=PROFILE,
            instance=None, verifier_source=VERIFIER_SRC.read_text(encoding="utf-8"),
        )
        self.assertEqual(_check(rep, "SV-02").status, STATUS_SKIP)

    def test_fail_outranks_blocked(self):
        """FAIL 与 BLOCKED 必须可分且都不得被忽略。"""
        from bidpricing.solver.verifier import VerifierCheck, _aggregate

        fail = VerifierCheck(SCOPE, "X", STATUS_FAIL, "")
        blocked = VerifierCheck(SCOPE, "Y", STATUS_BLOCKED, "")
        warn = VerifierCheck(SCOPE, "Z", STATUS_WARN, "")
        skip = VerifierCheck(SCOPE, "W", STATUS_SKIP, "")
        ok = VerifierCheck(SCOPE, "V", STATUS_PASS, "")
        self.assertEqual(_aggregate([ok, skip, warn]), STATUS_WARN)
        self.assertEqual(_aggregate([ok, blocked]), STATUS_BLOCKED)
        self.assertEqual(_aggregate([blocked, fail]), STATUS_FAIL)
        self.assertEqual(_aggregate([]), STATUS_BLOCKED)   # 无判据即无证据

    def test_report_is_json_serialisable(self):
        model, _fm, inst = _probe_model()
        rep = _verify(model, _full_x(model, inst), inst, reported_objective=0.0)
        text = json.dumps(rep.to_dict(), ensure_ascii=False, default=str)
        self.assertIn("SV-01", text)
        self.assertIn(rep.verdict, text)

    def test_judge_ids_are_unique_and_prefixed(self):
        model, _fm, inst = _probe_model()
        rep = _verify(model, _full_x(model, inst), inst)
        ids = [c.item.split()[0] for c in rep.checks]
        self.assertEqual(len(ids), len(set(ids)))


# ---------------------------------------------------------------------------
# 制品 ↔ 实现双向锁定
# ---------------------------------------------------------------------------


class TestSpecLock(unittest.TestCase):
    def test_declared_judges_equal_emitted_judges(self):
        declared = {j["id"] for j in VSPEC["judges"]}
        model, _fm, inst = _probe_model()
        rep = _verify(model, _full_x(model, inst), inst)
        # （未判）后缀只在 SKIP 路径出现，故两边都归一化。
        emitted = {c.item.split()[0] for c in rep.checks}
        self.assertEqual(declared, emitted)

    def test_every_judge_is_fully_described(self):
        for j in VSPEC["judges"]:
            for key in ("statement", "check", "on_violation"):
                self.assertTrue(j.get(key), f"{j['id']} 缺 {key}")

    def test_claims_reference_existing_judges(self):
        ids = {j["id"] for j in VSPEC["judges"]}
        claimed: set[str] = set()
        for c in VSPEC["claims"]:
            for jid in c["judges"]:
                self.assertIn(jid, ids, c["id"])
                claimed.add(jid)
        self.assertEqual(claimed, ids, "有判据没被任何声称引用")

    def test_tier_classes_match_module_constants(self):
        for name in (TIER_BOUNDARY_LOW, TIER_INTERIOR, TIER_BOUNDARY_HIGH,
                     TIER_INFEASIBLE, TIER_AMBIGUOUS):
            self.assertIn(name, VSPEC["tier_classes"])

    def test_ratio_rule_matches_constant(self):
        rule = VSPEC["tolerance_layers"]["ratio_rule"]
        self.assertAlmostEqual(float(rule["min"]), MIN_TOLERANCE_RATIO, places=6)
        self.assertEqual(rule["on_violation"], STATUS_FAIL)

    def test_layer_names_match_constants(self):
        layers = VSPEC["tolerance_layers"]
        self.assertEqual(layers["inner"]["name"], INNER_TOLERANCE_NAME)
        self.assertEqual(layers["outer"]["name"], OUTER_TOLERANCE_NAME)

    def test_discovered_defects_are_recorded(self):
        """两个实测缺陷必须留在制品里（否则日后有人按旧口径改回去）。"""
        self.assertIn("DV-01", VSPEC["discovered_defect"]["id"])
        self.assertIn("DV-02", VSPEC["discovered_defect_2"]["id"])
        self.assertIn("eps_rel_price",
                      VSPEC["discovered_defect_2"]["fix"])

    def test_spec_declares_evidence_pointer_to_existing_files(self):
        repo = Path(__file__).resolve().parents[1]
        for key, rel in VSPEC["evidence_pointer"].items():
            if key in ("cli",):
                continue
            self.assertTrue((repo / rel).exists(), f"{key} -> {rel} 不存在")


if __name__ == "__main__":
    unittest.main()
