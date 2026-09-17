"""T04-02A 的测试：LP 形式化的完整性与判据区分度。

分三层：

1. **构造层**：``build_formulation`` 在探针实例上的形状（列数、行数、求解器形态、
   C1 作用域、C5 下界）——全部用构造的参数，不读项目实时状态。
2. **判据层**：F-01..F-10 在制品与实现一致时全 PASS；改坏任一侧即 FAIL。
3. **区分度层**（本文件最重要的一层）：把已知的错误实现注入回去，确认判据
   真的会 FAIL。判据「全 PASS」本身不说明任何事——**能被错误的值否定**才是
   判据的全部价值。

第 3 层的两个样本都来自本轮真抓到的 bug：

* ``settlement_revenue`` 的区间内分支漏了作用域判断（SEGMENT ∧ alpha≠0 时
  与 ``compute_r_eff`` 差 (1+alpha) 倍）；
* 判据自身首版借道 ``instance.r_eff``，被实例自己的 ``Phase1Params`` 覆盖了
  传入的 scope，**自己制造出假 FAIL**。
"""

from __future__ import annotations

import dataclasses
import json
import unittest
from pathlib import Path

from bidpricing.contracts.pricing_card import (
    BRANCH_DECREASE,
    BRANCH_INCREASE,
    ResolvedParameters,
    compute_r_eff,
    compute_p1,
    load_pricing_card,
    resolve_parameters,
    settlement_revenue,
)
from bidpricing.solver import formulation as fm
from bidpricing.solver.formulation import (
    FormulationError,
    build_formulation,
    check_c12_surface_constancy,
    check_formulation,
    compute_lb_c5,
    probe_instance,
    r_pc_from_vector,
    verify_marginal_coefficients,
)
from bidpricing.solver.instance import Phase1Params, Phase1Item

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config"


def _resolved(scope: str = "SEGMENT", rho_plus: float = 0.0) -> ResolvedParameters:
    return ResolvedParameters(
        rho_plus=rho_plus, rho_minus=0.0,
        increase_threshold=1.15, decrease_threshold=0.85,
        adjustment_scope=scope,
    )


def _schema() -> dict:
    """构造的约束字典——只为 F-03/F-07 提供集合，不读项目实时制品。"""
    return {
        "constraints": [
            {"id": "C1", "severity": "P0", "inputs": ["p_bid", "q0", "P*_competitive"],
             "metric": "|sum_i p_i q0_i - P*_competitive|"},
            {"id": "C2", "severity": "P0", "inputs": ["cap", "p0"]},
            {"id": "C3", "severity": "P0", "inputs": ["L"]},
            {"id": "C4", "severity": "P0", "inputs": ["floor", "c_i", "mu"]},
            {"id": "C5", "severity": "P0", "inputs": ["p_bid", "zero_price_prohibited"]},
            {"id": "C6", "severity": "P0", "inputs": ["c_i", "p_bid", "q1_point", "theta", "P*"]},
            {"id": "C7", "severity": "P0", "inputs": ["c_i", "p_bid", "N_max"]},
            {"id": "C8", "severity": "P0", "inputs": ["c_i", "p_bid", "d_max"]},
            {"id": "C9", "severity": "P0", "inputs": ["Z", "c_i", "q1_point", "Z_min", "pi_target"]},
            {"id": "C10", "severity": "P0", "inputs": ["rho_i", "p_bid", "c_i", "q0", "T_front"]},
            {"id": "C11", "severity": "P1", "inputs": ["p_bid", "p0", "kappa_max"]},
            {"id": "C12", "severity": "P1", "inputs": ["p_bid", "q0", "c_i", "R_min"]},
            {"id": "C13", "severity": "P0", "inputs": ["p_bid", "unbalanced_reference"]},
        ]
    }


def _profile(mode: str = "A", resolution: float = 0.01) -> dict:
    return {
        "eps_abs": {"value": 0.01},
        "eps_price": {"value": 1e-09},
        "eps_solver": {"value": 1e-08},
        "rounding": {"resolution": resolution},
        "equality_tolerance_mode": {"current": mode, "allowed": ["A", "B"]},
    }


class TestSettlementRevenueScopeFix(unittest.TestCase):
    """回归：区间内分支必须区分作用域（本轮修的真 bug）。"""

    def test_segment_in_range_ignores_alpha(self):
        q0, q1, p = 100.0, 100.0, 50.0
        got = settlement_revenue(q0, q1, p, _resolved("SEGMENT"), alpha=0.2)
        self.assertAlmostEqual(got, q1 * p, places=9)

    def test_full_in_range_applies_alpha(self):
        q0, q1, p = 100.0, 100.0, 50.0
        got = settlement_revenue(q0, q1, p, _resolved("FULL"), alpha=0.2)
        self.assertAlmostEqual(got, q1 * p * 1.2, places=9)

    def test_segment_matches_p1_business_interface(self):
        """与 compute_p1（带状态机的业务接口）在 SEIMENT 下逐值一致。"""
        card = load_pricing_card(CONFIG)
        q0, q1, p0 = 1000.0, 2000.0, 300.0
        res = compute_p1(q0, q1, p0, card)
        self.assertEqual(res.status, "PASS")
        pure = settlement_revenue(q0, q1, p0, _resolved(res.parameters["adjustment_scope"]))
        self.assertAlmostEqual(pure, res.settlement, places=6)


class TestMarginalClosure(unittest.TestCase):
    """F-02 的定义式：q0·r_eff == ∂R/∂p，且必须覆盖两种作用域。"""

    def test_scopes_are_swept_not_inherited(self):
        inst = probe_instance()
        checks = verify_marginal_coefficients(inst, _resolved("SEGMENT"))
        scopes = {c.case.split("|")[0] for c in checks}
        self.assertEqual(scopes, {"scope=FULL", "scope=SEGMENT"},
                         "判据必须自己扫作用域——沿用实例时会漏掉只在另一种作用域下出现的分叉")

    def test_all_grids_pass_on_fixed_implementation(self):
        checks = verify_marginal_coefficients(probe_instance(), _resolved())
        self.assertTrue(checks, "探针实例应产出非空格集")
        bad = [c for c in checks if not c.ok]
        self.assertEqual(bad, [], f"不应有格不一致：{bad[:2]}")

    def test_probe_covers_all_three_branches(self):
        inst = probe_instance()
        res = _resolved()
        branches = {c.item_id: compute_r_eff(inst_item.r(), res)
                    for c in inst.items
                    for inst_item in [c]}
        self.assertEqual(len(branches), 4)
        rng = {i.item_id: i.r() for i in inst.items}
        self.assertLess(rng["P-DEC"], 0.85)
        self.assertAlmostEqual(rng["P-IN"], 1.0)
        self.assertGreater(rng["P-INC"], 1.15)

    def test_wrong_implementation_is_caught(self):
        """区分度：注入「区间内漏 scope 判断」的旧实现，判据必须 FAIL。"""
        original = fm.settlement_revenue

        def buggy(q0, q1, p, params, alpha=0.0):
            r = q1 / q0
            b = compute_r_eff.__globals__["classify_branch"](r, params)
            if b == BRANCH_DECREASE:
                return q1 * p * (1.0 + params.rho_minus)
            if b == BRANCH_INCREASE:
                p1 = p * (1.0 - params.rho_plus)
                if params.adjustment_scope == "FULL":
                    return q1 * p1
                th = params.increase_threshold
                return th * q0 * p + (q1 - th * q0) * p1
            return q1 * p * (1.0 + alpha)      # ← 漏了 scope 判断

        fm.settlement_revenue = buggy
        try:
            checks = verify_marginal_coefficients(probe_instance(), _resolved())
            bad = [c for c in checks if not c.ok]
            self.assertTrue(bad, "旧分叉必须被判据抓到——否则判据无区分度")
            for b in bad:
                self.assertIn("scope=SEGMENT", b.case,
                              "该分叉只在 SEGMENT 下出现")
                self.assertIn("alpha=0.2", b.case)
        finally:
            fm.settlement_revenue = original

    def test_objective_marginal_equals_revenue_marginal(self):
        """目标侧 ∂Z/∂p 必须等于收入侧 ∂R/∂p = q0·r_eff，**不是** q1·r_eff。

        2026-09-17 修正。原断言写的是 q1·r_eff，并把两者的差异解释成
        「含结算量因子 q1」——但 Z = Σ(R_i − c_i·q1_i)，成本项与 p 无关
        ⇒ ∂Z/∂p ≡ ∂R/∂p。断言 q1·r_eff 在 LP 上等价于把排序键又乘一遍 r_i：

            LP 排序键 = (目标系数)/(C1 系数) = (q1·r_eff)/q0 = r_i·r_eff ≠ r_eff

        这恰是 T04-00 EC-2 警告过的失效模式（解满足全部约束但次优，
        不触发任何可行性检查）。该断言当年写反了，于是**测试在保护 bug**。
        """
        inst = probe_instance()
        res = _resolved()
        built = build_formulation(inst, res)
        by_id = {c.item_id: c for c in built.price_columns}
        n_r_nonunit = 0
        for item in inst.items:
            if item.role != "OPTIMIZABLE":
                continue
            r_eff = compute_r_eff(item.r(), res, item.alpha)
            got = by_id[item.item_id].objective_coeff
            self.assertAlmostEqual(
                got, item.q0 * r_eff, places=9,
                msg=f"{item.item_id}: ∂Z/∂p 应为 q0·r_eff")
            # 跨来源：与结算收入的实际边际（中心差分）对账
            #
            # 步长取相对量：p_ref=600、h=1e-6 时，R(p±h)≈1.2e6 的 1 ULP（≈2.3e-10）
            # 被 2h=2e-6 放大成 ~1e-4 的**伪**导数误差，足以把正确实现报成 FAIL
            # ——「判据把正常实现报成违规 = 判据的问题」。R 在每个分支内对 p 严格
            # 线性（branch 只由 r=q1/q0 决定，与 p 无关），故中心差分对任意 h 都
            # 精确到舍入；放大 h 只压低抵消误差，不改变结论。
            p_ref = item.p0
            h = max(1e-3, abs(p_ref) * 1e-9)
            numeric = (
                settlement_revenue(item.q0, item.q1_point, p_ref + h, res, item.alpha)
                - settlement_revenue(item.q0, item.q1_point, p_ref - h, res, item.alpha)
            ) / (2 * h)
            # 跨来源对账用**相对**容差：本条要证的是「解析边际 = 业务公式边际」，
            # 不是浮点末位。rel 1e-6 足以容纳 ULP 抵消，又远小于本项的真实分歧
            # （q0 vs q1：r≠1 项差 (r−1)·q0·r_eff 倍，量级 ≥1e-2）。
            self.assertAlmostEqual(
                got, numeric, delta=max(abs(got), 1.0) * 1e-6 + 1e-9,
                msg=f"{item.item_id}: 目标系数应等于数值 ∂R/∂p")
            if abs(item.r() - 1.0) > 1e-9:
                n_r_nonunit += 1
                self.assertNotAlmostEqual(
                    got, item.q1_point * r_eff, places=6,
                    msg=f"{item.item_id}: 不得退化为 q1·r_eff")
        self.assertGreater(
            n_r_nonunit, 0,
            "探针实例必须含 r≠1 的项，否则本例测不出 q0/q1 的分歧")



class TestBuildFormulation(unittest.TestCase):
    def test_c1_scope_coefficients(self):
        inst = probe_instance()
        built = build_formulation(inst, _resolved())
        c1 = built.rows_of("C1")
        self.assertEqual(len(c1), 1, "C1 应为一条等式（不是逐项展开）")
        self.assertEqual(c1[0].sense, "==")
        self.assertAlmostEqual(c1[0].rhs, inst.B, places=6)
        ids = {s.split("_", 1)[1] for s, _c in c1[0].coefficients}
        self.assertEqual(ids, {i.item_id for i in inst.items if i.in_c1_scope})

    def test_missing_rhs_blocks(self):
        inst = dataclasses.replace(probe_instance(), B=None)
        with self.assertRaises(FormulationError):
            build_formulation(inst, _resolved())

    def test_solver_form_switch(self):
        res = _resolved()
        self.assertEqual(build_formulation(probe_instance(), res).solver_form, "LP")
        milp = build_formulation(probe_instance(active=("C7",)), res)
        self.assertEqual(milp.solver_form, "MILP")

    def test_c2_rows_exclude_unpriced_items(self):
        inst = probe_instance()
        built = build_formulation(inst, _resolved())
        free = {i.item_id for i in inst.items if i.U is None}
        self.assertEqual(free, {"P-FREE"})
        c2_ids = {s.split("_", 1)[1] for r in built.rows_of("C2")
                  for s, _c in r.coefficients}
        self.assertNotIn("P-FREE", c2_ids, "不限价项不得出现在 C2 行里")
        self.assertEqual(len(built.rows_of("C2")), 3)

    def test_objective_constant_isolated(self):
        inst = probe_instance()
        built = build_formulation(inst, _resolved())
        expect = -sum(i.c_i * i.q1_point for i in inst.items
                      if i.c_i is not None and i.q1_point is not None)
        self.assertAlmostEqual(built.objective_constant, expect, places=6)
        self.assertTrue(all(c.objective_coeff >= 0 for c in built.price_columns))

    def test_box_infeasible_detected_before_solver(self):
        """lb > ub 必须在本层报出，不能交给求解器报泛化 infeasible。"""
        inst = probe_instance()
        broken = dataclasses.replace(
            inst,
            items=tuple(
                dataclasses.replace(i, L=999.0, U=1.0) if i.item_id == "P-IN" else i
                for i in inst.items
            ),
        )
        built = build_formulation(broken, _resolved())
        self.assertTrue(any("P-IN" in n for n in built.box_notes),
                        f"未报出箱型不可行：{built.box_notes}")

    def test_c7_degenerate_big_m_removed(self):
        """c_i ≤ lb_i ⇒ M_i ≤ 0 ⇒ z_i 固定 0 并从问题移除。"""
        items = (
            Phase1Item(item_id="CHEAP", q0=100.0, q1_point=100.0, c_i=10.0,
                       p0=100.0, cap=100.0, L=50.0, U=100.0),
        )
        inst = dataclasses.replace(
            probe_instance(active=("C7",)), items=items, B=10000.0)
        built = build_formulation(inst, _resolved())
        z = [c for c in built.variables if c.family == "z"]
        self.assertEqual(len(z), 1)
        self.assertIn("固定 0", z[0].note)
        self.assertEqual(built.rows_of("C7.lower"), ())


class TestFormulationChecks(unittest.TestCase):
    def _run(self, **kw):
        inst = kw.pop("instance", None) or probe_instance()
        spec = kw.pop("spec", None)
        if spec is None:
            spec = json.loads((CONFIG / "lp_formulation_spec.json")
                              .read_text(encoding="utf-8"))
        built = build_formulation(inst, _resolved())
        return check_formulation(
            spec, built,
            instance=inst, resolved=_resolved(),
            constraint_schema=kw.pop("schema", None) or _schema(),
            precision_profile=kw.pop("profile", None) or _profile(),
        )

    def test_config_spec_passes_on_probe(self):
        """受控制品 + 探针实例 ⇒ F 判据不得有 FAIL/BLOCKED。"""
        rows = self._run()
        bad = [r for r in rows if r.blocks_progress]
        self.assertEqual(bad, [], f"不应阻塞：{[(r.item, r.reason) for r in bad]}")
        self.assertTrue(all(r.status in ("PASS", "SKIP") for r in rows))

    def test_f04_blocks_when_mode_unfrozen(self):
        """模式未冻结 ⇒ BLOCKED，**不得**判 PASS。"""
        prof = _profile()
        prof["equality_tolerance_mode"]["current"] = None
        rows = self._run(profile=prof)
        f04 = next(r for r in rows if r.item.startswith("F-04"))
        self.assertEqual(f04.status, "BLOCKED")

    def test_f04_fails_on_mode_mismatch(self):
        rows = self._run(profile=_profile("B"))
        f04 = next(r for r in rows if r.item.startswith("F-04"))
        self.assertEqual(f04.status, "FAIL")

    def test_f03_fails_on_missing_p0_constraint(self):
        spec = json.loads((CONFIG / "lp_formulation_spec.json")
                          .read_text(encoding="utf-8"))
        spec["constraint_map"] = [
            c for c in spec["constraint_map"] if c["constraint_id"] != "C4"
        ]
        rows = self._run(spec=spec)
        f03 = next(r for r in rows if r.item.startswith("F-03"))
        self.assertEqual(f03.status, "FAIL")
        self.assertIn("C4", str(f03.reason))

    def test_f07_fails_on_bogus_source(self):
        spec = json.loads((CONFIG / "lp_formulation_spec.json")
                          .read_text(encoding="utf-8"))
        for c in spec["constraint_map"]:
            if c["constraint_id"] == "C1":
                c["coefficient_sources"] = ["q0", "TOTALLY_BOGUS_FIELD"]
        rows = self._run(spec=spec)
        f07 = next(r for r in rows if r.item.startswith("F-07 "))
        self.assertEqual(f07.status, "FAIL")

    def test_f07b_fails_when_nonlp_reason_missing(self):
        spec = json.loads((CONFIG / "lp_formulation_spec.json")
                          .read_text(encoding="utf-8"))
        for c in spec["constraint_map"]:
            if c["constraint_id"] == "C11":
                # C11 的形式 2026-09-17 由 NONLINEAR_DEFERRED 改为
                # DISCRETE_CHECK，理由字段随之由 why_deferred 变为 why_not_lp。
                c.pop("why_not_lp", None)
        rows = self._run(spec=spec)
        f07b = next(r for r in rows if r.item.startswith("F-07b"))
        self.assertEqual(f07b.status, "FAIL")

    def test_f06_raises_c5_bound_above_resolution(self):
        """小 P* 时裸 eps·P* 低于报价分辨率 ⇒ 必须抬到 0.01。"""
        self.assertAlmostEqual(compute_lb_c5(1.0e6, 1e-9, 0.01), 0.01)
        self.assertLess(1e-9 * 1.0e6, 0.01)
        self.assertAlmostEqual(compute_lb_c5(1.0e9, 1e-9, 0.01), 1.0)
        rows = self._run()
        f06 = next(r for r in rows if r.item.startswith("F-06"))
        self.assertEqual(f06.status, "PASS")

    def test_f09_both_variants(self):
        lp = self._run(instance=probe_instance())
        milp = self._run(instance=probe_instance(active=("C7",)))
        for rows, want in ((lp, "LP"), (milp, "MILP")):
            f09 = next(r for r in rows if r.item.startswith("F-09"))
            self.assertEqual(f09.status, "PASS")
            self.assertEqual(f09.expected, want)

    def test_skip_is_not_pass_when_instance_missing(self):
        """缺实例时必须 SKIP，不得静默 PASS（否则「没检查」会被读成「检查过」）。"""
        spec = json.loads((CONFIG / "lp_formulation_spec.json")
                          .read_text(encoding="utf-8"))
        built = build_formulation(probe_instance(), _resolved())
        rows = check_formulation(
            spec, built, instance=None, resolved=None,
            constraint_schema=_schema(), precision_profile=_profile())
        skips = [r for r in rows if r.status == "SKIP"]
        self.assertEqual(
            {r.item.split()[0] for r in skips},
            {"F-01", "F-02", "F-05", "F-09"},
            "缺实例时只有依赖实例的判据才 SKIP；F-03/F-04/F-06/F-07/F-08/F-10 不依赖实例，须照判",
        )
        self.assertTrue(all("SKIP" in r.reason or "未提供" in r.reason for r in skips))


class TestC12SurfaceConstancy(unittest.TestCase):
    """F-08：恒定性必须用**两组不同的 p 向量**验证，不能用同一个数复制两次。"""

    def test_two_distinct_vectors_agree(self):
        inst = probe_instance()
        ok, detail = check_c12_surface_constancy(inst)
        self.assertTrue(ok, detail)
        self.assertIn("同一 R_pc", detail)

    def test_the_two_vectors_are_actually_distinct(self):
        inst = probe_instance()
        items = [i for i in inst.items if i.c_i is not None and i.q0]
        B = inst.B
        p_a = {items[0].item_id: B / items[0].q0}
        p_b = {items[1].item_id: B / items[1].q0}
        self.assertNotEqual(p_a, p_b, "两组解必须不同，否则判据是恒真式")
        self.assertAlmostEqual(sum(p_a.values()), p_a[items[0].item_id])
        # 两组各自都满足 C1 的左端 = B
        for p_vec, item in ((p_a, items[0]), (p_b, items[1])):
            self.assertAlmostEqual(
                p_vec[item.item_id] * item.q0, B, places=6)

    def test_r_pc_is_not_a_function_constant(self):
        """R_pc 作为无约束函数偏导非零——恒定性只在约束面上成立。"""
        inst = probe_instance()
        item = next(i for i in inst.items if i.q0 and i.c_i)
        den = sum(i.c_i * i.q0 for i in inst.items if i.q0 and i.c_i)
        partial = item.q0 / den
        self.assertGreater(partial, 0.0)
        base = r_pc_from_vector({}, inst)
        bumped = r_pc_from_vector({item.item_id: 1.0}, inst)
        self.assertNotAlmostEqual(base, bumped, places=9)

    def test_degenerate_when_denominator_zero(self):
        items = (Phase1Item(item_id="Z", q0=0.0, q1_point=0.0, c_i=1.0,
                            p0=None, cap=None, L=0.0, U=None),)
        inst = dataclasses.replace(probe_instance(), items=items, B=0.0)
        with self.assertRaises(FormulationError):
            r_pc_from_vector({}, inst)


if __name__ == "__main__":
    unittest.main()
