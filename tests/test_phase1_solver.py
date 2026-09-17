"""T04-01 Phase 1 解析解的区分度测试。

★ 每条判据都必须能被**两个方向**验证：

1. **正确的值不被误杀**——判据太紧会把正常实现报成违规（规则⑧：能被错误的值
   否定，与不能被正确的值否定，是同一要求的两个方向）；
2. **错误的值必被抓住**——判据没有区分力就等于没判。

实现方式：``judge_phase1`` **只吃「实例 + 解对象」**，不读求解过程的中间量。
因此坏解可以被**直接注入**——把解换成篡改过的对象，对应判据必须翻成 FAIL。
做不到这一点的判据，在测试里就只能证明「我的实现恰好是对的」。

参数一律用**合成的** ``ResolvedParameters``，不读项目实时状态：否则断言会随
项目落值翻转（μ 一旦落值，今天写死的 BLOCKED 断言明天就绿了）。
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, replace

from bidpricing.contracts.pricing_card import ResolvedParameters
from bidpricing.paths import config_dir
from bidpricing.solver import phase1 as P1
from bidpricing.solver.formulation import probe_instance
from bidpricing.solver.instance import Phase1Instance, Phase1Item, Phase1Params

_KEYS = (
    "rho_plus",
    "rho_minus",
    "increase_threshold",
    "decrease_threshold",
    "adjustment_scope",
)

#: 盒式约束的**具名**容差（元）。真实项目里由 ``verifier.resolve_tolerances``
#: 解析 ``eps_price`` 得到；测试里给一个同量级的值即可。
TOLS = {"eps_price": 0.003}


def _resolved(
    scope: str = "SEGMENT",
    rho_plus: float = 0.0,
    rho_minus: float = 0.0,
    theta: float = 0.15,
) -> ResolvedParameters:
    """合成参数——**不读项目实时状态**。"""
    return ResolvedParameters(
        rho_plus=rho_plus,
        rho_minus=rho_minus,
        increase_threshold=1.0 + theta,
        decrease_threshold=1.0 - theta,
        adjustment_scope=scope,
        sources={k: "test" for k in _KEYS},
    )


def _params(rho_plus: float = 0.0, rho_minus: float = 0.0, theta: float = 0.15):
    return Phase1Params(
        theta_dev=theta, rho_plus=rho_plus, rho_minus=rho_minus,
        adjustment_scope="SEGMENT", theta=0.05,
    )


def _inst(items, B, *, P_star=None, tie_break=None, active=(), params=None):
    return Phase1Instance(
        items=tuple(items),
        B=B,
        P_star=P_star if P_star is not None else B,
        params=params if params is not None else _params(),
        active_soft_constraints=tuple(active),
        rounding_reconciliation_present=True,
        tie_break_policy=tie_break,
        source="tests/test_phase1_solver.py",
    )


def _item(iid, q0, q1, *, L, U, c=100.0, p0=None):
    return Phase1Item(
        item_id=iid, q0=q0, q1_point=q1, c_i=c,
        p0=p0 if p0 is not None else (L + U) / 2.0, cap=U, L=L, U=U,
    )


def _spec():
    return P1.load_phase1_spec(config_dir())


_AUTO_DECLARED = object()


def _all_checks(inst, resolved, solution, *, tolerances=TOLS, declared=_AUTO_DECLARED):
    declared_inputs = (
        P1.declared_input_names(_spec())
        if declared is _AUTO_DECLARED else declared
    )
    return P1.judge_phase1(
        inst, resolved, solution,
        tolerances=tolerances,
        declared_inputs=declared_inputs,
    )


def _status(checks, jid):
    for c in checks:
        if c.item == jid:
            return c.status
    raise AssertionError(f"判据 {jid} 未运行")


def _reason(checks, jid):
    for c in checks:
        if c.item == jid:
            return c.reason
    raise AssertionError(f"判据 {jid} 未运行")


@dataclass(frozen=True)
class _ZSolution(P1.Phase1Solution):
    """注入用：一个**自报目标值**的解（PS-10 的否定见证）。"""

    def to_dict(self):
        d = super().to_dict()
        d["Z"] = 0.0
        return d


# ---------------------------------------------------------------------------
# PS-01 适用范围守卫
# ---------------------------------------------------------------------------


class TestPS01Applicability(unittest.TestCase):
    def test_ec5_platform_without_tiebreak_blocks(self):
        """EC-5 FAIL 的实例 ⇒ 本层必须拒绝给解，并点名 EC-5。"""
        inst = probe_instance()  # P-IN 与 P-FREE 同为 r_eff=1.0，平台可分配
        sol = P1.solve_phase1(inst, _resolved())
        self.assertEqual(sol.status, P1.SOLUTION_BLOCKED)
        self.assertIn("EC-5", sol.reason)
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-01"), P1.STATUS_PASS)

    def test_ec5_with_tiebreak_proceeds(self):
        """声明 canonical tie-break 后同实例必须给解（另一个方向）。"""
        inst = P1.phase1_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        self.assertEqual(sol.status, P1.SOLUTION_OPTIMAL)
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-01"), P1.STATUS_PASS)

    def test_forged_solution_on_inapplicable_instance_is_caught(self):
        """★ 越界给解必须被抓：非 EXACT 却产出了 OPTIMAL 解。"""
        inst = probe_instance()
        forged = P1.Phase1Solution(
            status=P1.SOLUTION_OPTIMAL,
            applicability="INAPPLICABLE",
            assignments=(),
        )
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-01"), P1.STATUS_BLOCKED)

    def test_blocked_instance_marks_solution_judges_skip(self):
        """没产出解 ⇒ 需要解向量的判据判 SKIP（既不是 PASS 也不是 FAIL）。"""
        inst = probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        checks = _all_checks(inst, _resolved(), sol)
        for jid in ("PS-02", "PS-03", "PS-05", "PS-06", "PS-07", "PS-08", "PS-10"):
            self.assertEqual(_status(checks, jid), P1.STATUS_SKIP, jid)

    def test_unknown_tiebreak_policy_blocks_not_downgraded(self):
        """★ 未支持的 tie-break 政策 ⇒ BLOCKED（never_downgrade），不得静默换默认次序。"""
        inst = replace(
            P1.phase1_probe_instance(), tie_break_policy="LEXICOGRAPHIC_BY_NAME"
        )
        sol = P1.solve_phase1(inst, _resolved())
        self.assertEqual(sol.status, P1.SOLUTION_BLOCKED)
        self.assertIn("never_downgrade", sol.reason)


# ---------------------------------------------------------------------------
# PS-02 / PS-03：C1 与箱型
# ---------------------------------------------------------------------------


class TestPS02C1(unittest.TestCase):
    def test_correct_solution_passes(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-02"), P1.STATUS_PASS)

    def test_tampered_vector_breaks_c1(self):
        """★ 破坏 C1 的解必须被判 FAIL（残差由 check_solution 跨来源给出）。"""
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        bad = dict(sol.p_by_id)
        key = next(iter(bad))
        bad[key] += 1000.0
        forged = replace(sol, p_by_id=bad)
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-02"), P1.STATUS_FAIL)

    def test_missing_B_makes_eps_total_undefined(self):
        """★ 缺 B ⇒ eps_total 算不出 ⇒ BLOCKED（**口径不可比不是 PASS 也不是 FAIL**）。"""
        inst = _inst([_item("A", 1000.0, 1000.0, L=100.0, U=500.0)], None)
        sol = P1.Phase1Solution(
            status=P1.SOLUTION_OPTIMAL, applicability="EXACT",
            assignments=(P1.TierAssignment("A", 1.0, 300.0, 100.0, 500.0, P1.LAYER_INTERIOR),),
            p_by_id={"A": 300.0},
        )
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-02"), P1.STATUS_BLOCKED)


class TestPS03Box(unittest.TestCase):
    def test_no_named_tolerances_blocks(self):
        """★ 未给具名容差表 ⇒ BLOCKED，不得按严格算术冒充可行性结论（DV-01）。"""
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        checks = P1.judge_phase1(inst, _resolved(), sol, tolerances=None)
        self.assertEqual(_status(checks, "PS-03"), P1.STATUS_BLOCKED)

    def test_tolerance_table_missing_the_name_blocks(self):
        """传了表却缺 ``eps_price`` ⇒ BLOCKED（不得静默按 0）。"""
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        checks = P1.judge_phase1(inst, _resolved(), sol, tolerances={"eps_abs": 0.01})
        self.assertEqual(_status(checks, "PS-03"), P1.STATUS_BLOCKED)

    def test_correct_solution_passes(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-03"), P1.STATUS_PASS)

    def test_above_upper_bound_is_caught(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        a = sol.of("S-HI")
        forged = replace(
            sol,
            assignments=tuple(
                replace(x, p=(a.upper + 1.0)) if x.item_id == "S-HI" else x
                for x in sol.assignments
            ),
            p_by_id={**sol.p_by_id, "S-HI": a.upper + 1.0},
        )
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-03"), P1.STATUS_FAIL)

    def test_zero_price_is_caught(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        forged = replace(
            sol,
            assignments=tuple(
                replace(x, p=0.0) if x.item_id == "S-LO" else x
                for x in sol.assignments
            ),
            p_by_id={**sol.p_by_id, "S-LO": 0.0},
        )
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-03"), P1.STATUS_FAIL)


# ---------------------------------------------------------------------------
# PS-04 / PS-05：排序键与阈值结构
# ---------------------------------------------------------------------------


class TestPS04Lambda(unittest.TestCase):
    def test_correct_lambda_passes(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        self.assertEqual(sol.lam.kind, P1.LAMBDA_INTERIOR)
        self.assertAlmostEqual(sol.lam.value, 1.0)
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-04"), P1.STATUS_PASS)

    def test_lambda_reported_as_r_is_caught(self):
        """★ λ 必须是临界项的 **r_eff**。构造一个 r ≠ r_eff 的实例来否定它。"""
        inst = _inst(
            [
                # r = 1.5 > 1.15 ⇒ r_eff = 1.15 + 0.8·0.35 = 1.43 ≠ r
                _item("R-X", 1000.0, 1500.0, L=100.0, U=500.0),
                _item("R-Y", 1000.0, 900.0, L=100.0, U=500.0),
            ],
            400_000.0,
            params=_params(rho_plus=0.2),
        )
        resolved = _resolved(rho_plus=0.2)
        sol = P1.solve_phase1(inst, resolved)
        self.assertEqual(sol.status, P1.SOLUTION_OPTIMAL)
        crit = sol.of(sol.lam.critical_item)
        self.assertAlmostEqual(crit.r_eff, 1.43, places=6)
        forged = replace(sol, lam=replace(sol.lam, value=1.5))
        checks = _all_checks(inst, resolved, forged)
        self.assertEqual(_status(checks, "PS-04"), P1.STATUS_FAIL)
        self.assertIn("排序键被误用", _reason(checks, "PS-04"))

    def test_layer_inconsistent_with_lambda_is_caught(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        forged = replace(
            sol,
            assignments=tuple(
                replace(x, layer=P1.LAYER_LOW) if x.item_id == "S-MID" else x
                for x in sol.assignments
            ),
        )
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-04"), P1.STATUS_FAIL)

    def test_all_at_upper_without_lambda_is_honest(self):
        """全部顶格 ⇒ λ 如实未定（ALL_AT_UPPER），不得编一个数。"""
        inst = _inst(
            [_item("Z1", 1000.0, 1000.0, L=500.0, U=500.0)], 500_000.0
        )
        sol = P1.solve_phase1(inst, _resolved())
        self.assertEqual(sol.status, P1.SOLUTION_OPTIMAL)
        self.assertIsNone(sol.lam.value)
        self.assertEqual(sol.lam.kind, P1.LAMBDA_ALL_AT_UPPER)
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-04"), P1.STATUS_PASS)


class TestPS05Threshold(unittest.TestCase):
    def test_correct_solution_passes(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-05"), P1.STATUS_PASS)

    def test_inverted_layers_fail(self):
        """★ 高 r_eff 触底、低 r_eff 顶格 ⇒ 不存在这样的阈值 λ ⇒ FAIL。"""
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        swap = {"S-MID": 400.0, "S-HI": 700.0, "S-LO": 200.0}
        forged = replace(
            sol,
            assignments=tuple(
                replace(x, p=swap[x.item_id]) for x in sol.assignments
            ),
            p_by_id=swap,
        )
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-05"), P1.STATUS_FAIL)


class TestSortKeyIsREff(unittest.TestCase):
    """★ PS-04/PS-05 的核心见证：**r 与 r_eff 严格逆序**的实例。

    在 r 与 r_eff 同序的实例上，这两条判据没有区分力（按 r 排序与按 r_eff 排序
    给出同一个解）。只有逆序实例才能把「用错了键」照出来。
    """

    def _inst(self):
        # rho_minus = 0.5、θ = 0.15 ⇒ decrease_threshold = 0.85
        #   D-LOW : r = 0.84 < 0.85 ⇒ r_eff = (1+0.5)·0.84 = 1.26
        #   D-MID : r = 0.90 ∈ [0.85, 1.15] ⇒ r_eff = 0.90
        # r 序：D-MID(0.90) > D-LOW(0.84)；r_eff 序：D-LOW(1.26) > D-MID(0.90) ⇒ **逆序**
        return _inst(
            [
                _item("D-LOW", 1000.0, 840.0, L=100.0, U=500.0),
                _item("D-MID", 1000.0, 900.0, L=100.0, U=500.0),
            ],
            400_000.0,
            params=_params(rho_minus=0.5),
        )

    def test_instance_is_order_sensitive(self):
        resolved = _resolved(rho_minus=0.5)
        inst = self._inst()
        verdict = P1.check_exactness(inst, resolved)
        self.assertEqual(verdict.verdict, "EXACT", verdict.to_dict())
        self.assertEqual(verdict.status_of("EC-2"), P1.STATUS_WARN)

    def test_solver_sorts_by_r_eff_not_r(self):
        resolved = _resolved(rho_minus=0.5)
        inst = self._inst()
        sol = P1.solve_phase1(inst, resolved)
        self.assertEqual(sol.status, P1.SOLUTION_OPTIMAL)
        # 按 r_eff 排序 ⇒ D-LOW 先被顶格（或承载残差），D-MID 触底。
        self.assertEqual(sol.assignments[0].item_id, "D-LOW")
        self.assertGreater(sol.p_by_id["D-LOW"], sol.p_by_id["D-MID"])
        # 正确键的 Z 必须严格优于按 r 排序得到的解（次优但不违反任何约束）。
        from bidpricing.solver.instance import check_solution

        wrong = {"D-LOW": 100.0, "D-MID": 300.0}
        right = dict(sol.p_by_id)
        z_wrong = check_solution(inst, wrong, resolved, eps_total=0.01).Z
        z_right = check_solution(inst, right, resolved, eps_total=0.01).Z
        self.assertGreater(z_right, z_wrong)
        self.assertTrue(
            check_solution(inst, wrong, resolved, eps_total=0.01).feasible,
            "按 r 排序给出的解**满足全部约束**——这正是它危险的地方",
        )


# ---------------------------------------------------------------------------
# PS-06 数值交换见证
# ---------------------------------------------------------------------------


class TestPS06Exchange(unittest.TestCase):
    def test_correct_solution_passes(self):
        inst = P1.phase1_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-06"), P1.STATUS_PASS)

    def test_suboptimal_but_feasible_solution_is_caught(self):
        """★ 唯一能抓到「满足全部约束但次优」的判据。

        构造一个 C1 精确满足、箱型合法、但把最高 r_eff 项压在**下界**、
        最低 r_eff 项顶格的解 ⇒ 必存在有利交换。
        """
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        # S-HI(1.0) 顶格、S-MID(1.1) 未顶格、S-LO(0.8) 触底：C1 仍精确满足，
        # 但把 S-HI 的一点点额度转给 S-MID 会**提高** Z（1.1 > 1.0）⇒ 次优。
        p_smid, p_shi, p_slo = 600.0, 800.0, 200.0
        forged_p = {"S-MID": p_smid, "S-HI": p_shi, "S-LO": p_slo}
        from bidpricing.solver.instance import check_solution

        ref = check_solution(inst, forged_p, _resolved(), eps_total=0.01)
        self.assertTrue(ref.feasible, f"伪造解必须**可行**（否则测不出次优）{ref.violations}")
        forged = replace(
            sol,
            assignments=tuple(
                replace(x, p=forged_p[x.item_id]) for x in sol.assignments
            ),
            p_by_id=forged_p,
        )
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-06"), P1.STATUS_FAIL)
        self.assertIn("次优", _reason(checks, "PS-06"))

    def test_no_testable_exchange_skips(self):
        """★ 全部项贴在边界 ⇒ 交换根本没被走到 ⇒ SKIP（不是 PASS）。"""
        inst = _inst([_item("Z1", 1000.0, 1000.0, L=500.0, U=500.0)], 500_000.0)
        sol = P1.solve_phase1(inst, _resolved())
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-06"), P1.STATUS_SKIP)


# ---------------------------------------------------------------------------
# PS-07 不限价（空 cap）
# ---------------------------------------------------------------------------


class TestPS07NullCap(unittest.TestCase):
    def test_free_cap_probe_passes(self):
        inst = P1.phase1_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        self.assertIsNone(sol.of("P-FREE").upper)
        self.assertGreater(sol.p_by_id["P-FREE"], sol.of("P-FREE").lower)
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-07"), P1.STATUS_PASS)

    def test_no_free_item_passes_vacuously(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-07"), P1.STATUS_PASS)

    def test_big_M_trace_is_caught(self):
        """★ 把不限价项当成一个大 M ⇒ 超出 C1 隐式上界 ⇒ FAIL。"""
        inst = P1.phase1_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        forged_p = {**sol.p_by_id, "P-FREE": 1.0e9}
        forged = replace(
            sol,
            assignments=tuple(
                replace(x, p=1.0e9) if x.item_id == "P-FREE" else x
                for x in sol.assignments
            ),
            p_by_id=forged_p,
        )
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-07"), P1.STATUS_FAIL)

    def test_zeroing_free_item_is_caught(self):
        """★ 把空 cap 折成 0 ⇒ p ≤ 0（与 C5 冲突）⇒ FAIL。"""
        inst = P1.phase1_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        forged = replace(
            sol,
            assignments=tuple(
                replace(x, p=0.0) if x.item_id == "P-FREE" else x
                for x in sol.assignments
            ),
            p_by_id={**sol.p_by_id, "P-FREE": 0.0},
        )
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-07"), P1.STATUS_FAIL)


# ---------------------------------------------------------------------------
# PS-08 层划分
# ---------------------------------------------------------------------------


class TestPS08LayerPartition(unittest.TestCase):
    def test_correct_partition_passes(self):
        inst = P1.phase1_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        layers = sol.layers()
        self.assertEqual(layers["P-INC"], P1.LAYER_HIGH)
        self.assertEqual(layers["P-FREE"], P1.LAYER_INTERIOR)
        self.assertEqual(layers["P-IN"], P1.LAYER_LOW)
        self.assertEqual(layers["P-DEC"], P1.LAYER_LOW)
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-08"), P1.STATUS_PASS)

    def test_out_of_box_marks_infeasible_style_failure(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        forged = replace(
            sol,
            assignments=tuple(
                replace(x, p=x.upper + 10.0, layer=P1.LAYER_INFEASIBLE)
                if x.item_id == "S-HI" else x
                for x in sol.assignments
            ),
        )
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-08"), P1.STATUS_FAIL)

    def test_wrong_label_is_caught(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        forged = replace(
            sol,
            assignments=tuple(
                replace(x, layer=P1.LAYER_INTERIOR) if x.item_id == "S-MID" else x
                for x in sol.assignments
            ),
        )
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-08"), P1.STATUS_FAIL)


# ---------------------------------------------------------------------------
# PS-09 / PS-10 定位与裁判
# ---------------------------------------------------------------------------


class TestPS09Positioning(unittest.TestCase):
    def test_default_solution_passes(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        self.assertEqual(sol.role, P1.ROLE_CANDIDATE)
        self.assertFalse(sol.is_final)
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-09"), P1.STATUS_PASS)

    def test_claiming_final_is_caught(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        checks = _all_checks(inst, _resolved(), replace(sol, is_final=True))
        self.assertEqual(_status(checks, "PS-09"), P1.STATUS_FAIL)
        checks = _all_checks(inst, _resolved(), replace(sol, role="final"))
        self.assertEqual(_status(checks, "PS-09"), P1.STATUS_FAIL)


class TestPS10Referee(unittest.TestCase):
    def test_solution_does_not_self_report_Z(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        self.assertNotIn("Z", sol.to_dict())
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-10"), P1.STATUS_PASS)

    def test_self_reported_Z_is_caught(self):
        """★ 自报目标值 = 自造第二个 R_i 事实源。"""
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        forged = _ZSolution(**{f.name: getattr(sol, f.name)
                               for f in sol.__dataclass_fields__.values()})
        checks = _all_checks(inst, _resolved(), forged)
        self.assertEqual(_status(checks, "PS-10"), P1.STATUS_FAIL)


# ---------------------------------------------------------------------------
# PS-11 声明↔实现对账
# ---------------------------------------------------------------------------


class TestPS11Reconciliation(unittest.TestCase):
    def test_declared_inputs_cover_implementation(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        checks = _all_checks(inst, _resolved(), sol)
        self.assertEqual(_status(checks, "PS-11"), P1.STATUS_PASS)

    def test_undeclared_input_fails(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        declared = P1.declared_input_names(_spec()) - {"resolution"}
        checks = _all_checks(inst, _resolved(), sol, declared=declared)
        self.assertEqual(_status(checks, "PS-11"), P1.STATUS_FAIL)

    def test_no_declaration_blocks_and_no_sample_skips(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        self.assertEqual(
            _status(_all_checks(inst, _resolved(), sol, declared=None), "PS-11"),
            P1.STATUS_BLOCKED,
        )
        blocked = P1.solve_phase1(probe_instance(), _resolved())
        self.assertEqual(
            _status(_all_checks(probe_instance(), _resolved(), blocked), "PS-11"),
            P1.STATUS_SKIP,
        )


# ---------------------------------------------------------------------------
# 算法不变量与边界
# ---------------------------------------------------------------------------


class TestAlgorithmInvariants(unittest.TestCase):
    def test_c1_is_exactly_satisfied(self):
        for inst in (P1.phase1_probe_instance(), P1.phase1_simple_probe_instance()):
            sol = P1.solve_phase1(inst, _resolved())
            total = sum(
                float(i.q0) * sol.p_by_id[i.item_id] for i in inst.opt_items
            )
            self.assertAlmostEqual(total, float(inst.B), places=6)

    def test_below_merged_lower_is_infeasible_not_blocked(self):
        """★ INFEASIBLE（算出来了，可行域为空）≠ BLOCKED（算不出）。

        **可达条件**：``merged_lower > EC-7 所用的 L``（即 floor/lb_C5 把下界
        抬到了 L 之上）。此时 EC-7 的边界证书用**较弱**的下界，会判 PASS，
        而真实的 P_A 已经空了——这正是本层 INFEASIBLE 分支存在的理由。
        """
        inst = _inst([_item("F1", 1000.0, 1000.0, L=100.0, U=500.0)], 200_000.0)
        resolved = _resolved()
        # EC-7 只看 L（100·1000 = 1e5 ≤ B）⇒ PASS；但地板把下界抬到 400
        self.assertEqual(P1.check_exactness(inst, resolved).verdict, "EXACT")
        sol = P1.solve_phase1(inst, resolved, floor_by_id={"F1": 400.0})
        self.assertEqual(sol.status, P1.SOLUTION_INFEASIBLE)
        self.assertIn("P_min", sol.reason)

    def test_above_p_max_is_caught_by_ec7_guard(self):
        """上界侧由 EC-7 兜住（P_max 用同一份 U）⇒ 本层在守卫处判 BLOCKED。

        留此用例是为了**记录可达性**：本层 ``k* = n`` 之外的那条 INFEASIBLE
        分支在当前 EC-7 口径下不可达，属防御性兜底，不是主路径。
        """
        inst = replace(P1.phase1_simple_probe_instance(), B=1.0e12)
        sol = P1.solve_phase1(inst, _resolved())
        self.assertEqual(sol.status, P1.SOLUTION_BLOCKED)
        self.assertIn("EC-7", sol.reason)

    def test_platform_tie_break_is_deterministic(self):
        """平台下残差由 item_id 升序的第一个临界组成员承载（可复算）。"""
        inst = P1.phase1_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        self.assertEqual(sol.lam.critical_item, "P-FREE")
        self.assertEqual(sol.lam.kind, P1.LAMBDA_PLATFORM)
        self.assertAlmostEqual(sol.p_by_id["P-FREE"], 1700.0, places=6)
        self.assertAlmostEqual(sol.p_by_id["P-IN"], 400.0, places=6)

    def test_p_opt_by_id_is_opt_only(self):
        inst = P1.phase1_simple_probe_instance()
        sol = P1.solve_phase1(inst, _resolved())
        self.assertEqual(set(sol.p_opt_by_id()), {"S-MID", "S-HI", "S-LO"})

    def test_report_is_all_pass_on_probes(self):
        spec = _spec()
        for inst in (P1.phase1_probe_instance(), P1.phase1_simple_probe_instance()):
            rep = P1.phase1_report(
                inst, _resolved(), tolerances=TOLS, spec=spec
            )
            self.assertEqual(rep.verdict(), P1.STATUS_PASS, rep.to_dict())
            self.assertEqual(len(rep.checks), 11)

    def test_empty_checks_aggregate_to_blocked(self):
        rep = P1.Phase1Report(
            solution=P1.Phase1Solution(status=P1.SOLUTION_BLOCKED), checks=()
        )
        self.assertEqual(rep.verdict(), P1.STATUS_BLOCKED)


# ---------------------------------------------------------------------------
# 制品锁定
# ---------------------------------------------------------------------------


class TestSpecLock(unittest.TestCase):
    def test_spec_ids_and_domain(self):
        spec = _spec()
        ids = [j["id"] for j in spec["judges"]]
        self.assertEqual(ids, [f"PS-{i:02d}" for i in range(1, 12)])
        self.assertEqual(spec["task"], "T04-01")
        self.assertEqual(
            tuple(spec["layer_domain"]["values"]), P1.LAYER_VALUES
        )
        self.assertEqual(
            tuple(spec["algorithm"]["tie_break"]["supported"]),
            P1.SUPPORTED_TIE_BREAKS,
        )
        self.assertEqual(spec["positioning"]["solution_role"], P1.ROLE_CANDIDATE)
        self.assertFalse(spec["positioning"]["is_final"])

    def test_spec_declares_adr_pointer(self):
        spec = _spec()
        self.assertIn("ADR-0026", spec["evidence_pointer"])

    def test_spec_declared_inputs_match_implementation(self):
        """★ 制品声明的输入集必须覆盖实现实际读取的输入集（PS-11 的右侧）。"""
        declared = P1.declared_input_names(_spec())
        used = {"instance", "resolved", "floor_by_id", "eps_abs", "eps_price",
                "resolution"}
        self.assertEqual(used - declared, set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
