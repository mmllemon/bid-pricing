"""T03-04 约束判定器测试。

三类判据必须逐条成立（区分性要求，与 derived/verifier/milp_acceptance 同规）：

1. 注入**错误值** ⇒ FAIL（判据能被错误的值否定）；
2. 缺**必需输入** ⇒ BLOCKED（缺数据不是通过，也不是 0）；
3. **未激活/不适用** ⇒ SKIP（没判与通过可区分——规则⑧）。

另钉住三条跨会话教训：

* C6 用 **q1** 加权（构造 q0≠q1 且结论相反的实例，证明量纲没混）；
* C7 的 z 一致性**双向**（虚报与漏报都要被抓——PS-06 同族）；
* C12 的容差是 ``eps_ratio``（比值上的绝对量），**不是** ``eps_price×P*``
  （DV-02：同一物理量两种量纲读法必须两个名字）。
"""

from __future__ import annotations

import math
import unittest

from bidpricing.solver.constraint_judge import (
    JudgeInputs,
    ConstraintReport,
    judge_constraints,
    resolve_tolerances,
    load_constraint_spec,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
)
from bidpricing.solver.instance import (
    Phase1Instance,
    Phase1Item,
    ROLE_NON_COMPETITIVE,
)

# --------------------------------------------------------------------------
# 基础实例：A/B/F 均可优化（F 不限价，cap 空，仍在 C1 作用域内），
# N 是非可竞争项（外生固定单价 p0，不进 C1 作用域）。逐项可复算：
#   C1 分子 = 500×1000 + 400×500 + 250×100 = 725000 = B
#   C12 分母 = 400×1000 + 300×500 + 200×100 = 570000
# --------------------------------------------------------------------------

def base_items(**over):
    a = over.pop("a", Phase1Item(
        item_id="A", q0=1000.0, q1_point=900.0, c_i=400.0,
        p0=500.0, cap=600.0, L=350.0, U=600.0))
    b = over.pop("b", Phase1Item(
        item_id="B", q0=500.0, q1_point=500.0, c_i=300.0,
        p0=400.0, cap=450.0, L=250.0, U=450.0))
    f = over.pop("f", Phase1Item(
        item_id="F", q0=100.0, q1_point=100.0, c_i=200.0,
        p0=250.0, cap=None, L=100.0, U=None))
    assert not over
    return (a, b, f)


def non_opt_item():
    return Phase1Item(item_id="N", role=ROLE_NON_COMPETITIVE,
                      in_c1_scope=False, q0=50.0, q1_point=50.0,
                      c_i=100.0, p0=300.0)


def base_instance(items=None, *, B=725_000.0, P_star=800_000.0,
                  active=()) -> Phase1Instance:
    return Phase1Instance(
        items=items if items is not None else (*base_items(), non_opt_item()),
        B=B,
        P_star=P_star,
        active_soft_constraints=tuple(active),
    )


def base_p(**over):
    p = {"A": 500.0, "B": 400.0, "F": 250.0}
    p.update(over)
    return p


def base_floor():
    return {"A": 360.0, "B": 270.0, "F": 180.0}


def run(instance=None, p=None, **kw) -> tuple[ConstraintReport, JudgeInputs]:
    inst = instance if instance is not None else base_instance()
    inputs = JudgeInputs(
        instance=inst,
        p_by_id=p if p is not None else base_p(),
        floor_by_id=kw.pop("floor_by_id", base_floor()),
        **kw,
    )
    return judge_constraints(inputs), inputs


# ==========================================================================
# CJ-01 C1
# ==========================================================================
class TestC1(unittest.TestCase):
    def test_pass(self):
        rep, _ = run()
        v = rep.of("C1")
        self.assertEqual(v.status, STATUS_PASS)
        self.assertEqual(v.actual, 725_000.0)
        self.assertEqual(v.slack, 0.0)

    def test_injected_wrong_p_fails(self):
        rep, _ = run(p=base_p(A=501.0))
        v = rep.of("C1")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertEqual(v.slack, -1_000.0)

    def test_missing_B_blocked(self):
        rep, _ = run(base_instance(B=None))
        self.assertEqual(rep.of("C1").status, "BLOCKED")

    def test_missing_q0_blocked_not_zero(self):
        a = Phase1Item(item_id="A", q0=None, q1_point=900.0, c_i=400.0,
                       p0=500.0, cap=600.0, L=350.0, U=600.0)
        rep, _ = run(base_instance(items=(a, base_items()[1], base_items()[2])))
        self.assertEqual(rep.of("C1").status, "BLOCKED")

    def test_rhs_is_exogenous_not_p_function(self):
        """右端随 p 变 ⇒ 恒真式。此处右端 B 固定，换 p 必须能翻转结论。"""
        rep1, _ = run()
        rep2, _ = run(p=base_p(A=600.0))
        self.assertEqual(rep1.of("C1").status, STATUS_PASS)
        self.assertEqual(rep2.of("C1").status, STATUS_FAIL)


# ==========================================================================
# CJ-02 C2
# ==========================================================================
class TestC2(unittest.TestCase):
    def test_pass_and_free_item_skipped(self):
        rep, _ = run()
        v = rep.of("C2")
        self.assertEqual(v.status, STATUS_PASS)
        frow = next(r for r in v.rows if r["item_id"] == "F")
        self.assertEqual(frow["status"], STATUS_SKIP)
        self.assertIn("不限价", frow["reason"])

    def test_injected_violation_fails(self):
        rep, _ = run(p=base_p(A=601.0))
        v = rep.of("C2")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertEqual(v.actual, 601.0)
        self.assertEqual(v.limit, 600.0)
        self.assertEqual(v.slack, -1.0)

    def test_empty_cap_is_not_zero_bound(self):
        """空 cap 不得折成 0：F 无 U ⇒ SKIP 行，不是 FAIL 行。"""
        rep, _ = run()
        frow = next(r for r in rep.of("C2").rows if r["item_id"] == "F")
        self.assertNotEqual(frow["status"], STATUS_FAIL)

    def test_cap_present_but_U_missing_blocked(self):
        a = Phase1Item(item_id="A", q0=1000.0, q1_point=900.0, c_i=400.0,
                       p0=500.0, cap=600.0, L=350.0, U=None)
        rep, _ = run(base_instance(items=(a, base_items()[1], base_items()[2])))
        self.assertEqual(rep.of("C2").status, "BLOCKED")

    def test_all_free_skip(self):
        items = tuple(
            Phase1Item(item_id=i.item_id, q0=i.q0, q1_point=i.q1_point,
                       c_i=i.c_i, p0=i.p0, cap=None, L=i.L, U=None)
            for i in base_items())
        rep, _ = run(base_instance(items=items))
        self.assertEqual(rep.of("C2").status, STATUS_SKIP)


# ==========================================================================
# CJ-03 C3
# ==========================================================================
class TestC3(unittest.TestCase):
    def test_pass(self):
        rep, _ = run()
        self.assertEqual(rep.of("C3").status, STATUS_PASS)

    def test_injected_violation_fails(self):
        rep, _ = run(p=base_p(B=249.0))
        v = rep.of("C3")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertEqual(v.slack, -1.0)

    def test_missing_L_blocked(self):
        a = Phase1Item(item_id="A", q0=1000.0, q1_point=900.0, c_i=400.0,
                       p0=500.0, cap=600.0, L=None, U=600.0)
        rep, _ = run(base_instance(items=(a, base_items()[1], base_items()[2])))
        self.assertEqual(rep.of("C3").status, "BLOCKED")


# ==========================================================================
# CJ-04 C4
# ==========================================================================
class TestC4(unittest.TestCase):
    def test_pass(self):
        rep, _ = run()
        self.assertEqual(rep.of("C4").status, STATUS_PASS)

    def test_floor_violation_fails(self):
        rep, _ = run(p=base_p(A=355.0))
        v = rep.of("C4")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertEqual(v.slack, -5.0)

    def test_missing_floor_blocked_visible(self):
        """μ 未落值（OI-DQ-A）必须在判定层以 BLOCKED 可见，不是 PASS。"""
        rep, _ = run(floor_by_id={})
        self.assertEqual(rep.of("C4").status, "BLOCKED")

    def test_partial_floor_blocked(self):
        rep, _ = run(floor_by_id={"A": 360.0})
        self.assertEqual(rep.of("C4").status, "BLOCKED")


# ==========================================================================
# CJ-05 C5
# ==========================================================================
class TestC5(unittest.TestCase):
    def test_pass_and_lb_is_max_not_bare_eps(self):
        rep, _ = run()
        v = rep.of("C5")
        self.assertEqual(v.status, STATUS_PASS)
        # eps_price×P* = 1e-9×8e5 = 8e-4 < resolution 0.01 ⇒ 下界必须是 0.01
        self.assertEqual(v.limit, 0.01)

    def test_sub_resolution_price_fails(self):
        rep, _ = run(p=base_p(F=0.005))
        v = rep.of("C5")
        self.assertEqual(v.status, STATUS_FAIL)

    def test_missing_P_star_blocked(self):
        rep, _ = run(base_instance(P_star=None))
        self.assertEqual(rep.of("C5").status, "BLOCKED")


# ==========================================================================
# CJ-06 C6
# ==========================================================================
class TestC6(unittest.TestCase):
    def test_inactive_skip(self):
        rep, _ = run()
        self.assertEqual(rep.of("C6").status, STATUS_SKIP)

    def test_active_pass(self):
        rep, _ = run(base_instance(active=("C6",)), theta=0.05)
        v = rep.of("C6")
        self.assertEqual(v.status, STATUS_PASS)
        self.assertEqual(v.actual, 0.0)
        self.assertEqual(v.limit, 40_000.0)

    def test_active_loss_exceeds_fail(self):
        rep, _ = run(base_instance(active=("C6",)), p=base_p(A=350.0),
                     theta=0.05)
        v = rep.of("C6")
        self.assertEqual(v.status, STATUS_FAIL)
        # s_A = 50，按 q1=900 加权 ⇒ 45000 > 40000
        self.assertEqual(v.actual, 45_000.0)

    def test_weighted_by_q1_not_q0(self):
        """q0≠q1 且结论相反：q1 加权 5000 ≤ 6000 PASS；q0 加权 20000 必 FAIL。"""
        a = Phase1Item(item_id="A", q0=2000.0, q1_point=500.0, c_i=400.0,
                       p0=500.0, cap=600.0, L=350.0, U=600.0)
        inst = base_instance(items=(a, base_items()[1], base_items()[2]),
                             active=("C6",))
        rep, _ = run(inst, p=base_p(A=390.0), theta=0.01)
        v = rep.of("C6")
        self.assertEqual(v.actual, 10.0 * 500.0)  # q1 加权
        self.assertEqual(v.status, STATUS_PASS)
        # 若误用 q0 加权：10×2000=20000 > 8000 ⇒ 必 FAIL
        self.assertEqual(v.limit, 0.01 * 800_000.0)

    def test_missing_theta_blocked(self):
        rep, _ = run(base_instance(active=("C6",)))
        self.assertEqual(rep.of("C6").status, "BLOCKED")


# ==========================================================================
# CJ-07 C7
# ==========================================================================
class TestC7(unittest.TestCase):
    def test_inactive_skip(self):
        rep, _ = run()
        self.assertEqual(rep.of("C7").status, STATUS_SKIP)

    def test_no_z_warn_not_pass(self):
        """亏损未超限但无 z 向量 ⇒ WARN（自称口径未核），不是 PASS。"""
        rep, _ = run(base_instance(active=("C7",)), p=base_p(A=350.0),
                     N_max=2.0)
        v = rep.of("C7")
        self.assertEqual(v.status, STATUS_WARN)
        self.assertEqual(v.actual, 1)

    def test_losses_over_limit_fail(self):
        rep, _ = run(base_instance(active=("C7",)), p=base_p(A=350.0, B=250.0),
                     N_max=1.0)
        self.assertEqual(rep.of("C7").status, STATUS_FAIL)

    def test_missing_N_max_blocked(self):
        rep, _ = run(base_instance(active=("C7",)))
        self.assertEqual(rep.of("C7").status, "BLOCKED")

    def test_z_consistent_pass(self):
        rep, _ = run(base_instance(active=("C7",)), p=base_p(A=350.0),
                     z_by_id={"A": 1.0, "B": 0.0, "F": 0.0}, N_max=1.0)
        self.assertEqual(rep.of("C7").status, STATUS_PASS)

    def test_z_overreport_fails(self):
        """虚报：z=1 但 p > c_i−eps_res（0.5 > 400−0.01）。"""
        rep, _ = run(base_instance(active=("C7",)), p=base_p(A=500.0),
                     z_by_id={"A": 1.0}, N_max=5.0)
        v = rep.of("C7")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertIn("虚报", v.reason)

    def test_z_underreport_fails(self):
        """漏报：z=0 但 p < c_i——双向核查的第二向。"""
        rep, _ = run(base_instance(active=("C7",)), p=base_p(A=350.0),
                     z_by_id={"A": 0.0}, N_max=5.0)
        v = rep.of("C7")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertIn("漏报", v.reason)


# ==========================================================================
# CJ-08 C8
# ==========================================================================
class TestC8(unittest.TestCase):
    def test_inactive_skip(self):
        rep, _ = run()
        self.assertEqual(rep.of("C8").status, STATUS_SKIP)

    def test_active_pass(self):
        rep, _ = run(base_instance(active=("C8",)), d_max=0.2)
        self.assertEqual(rep.of("C8").status, STATUS_PASS)

    def test_active_violation_fails(self):
        rep, _ = run(base_instance(active=("C8",)), p=base_p(A=310.0),
                     d_max=0.2)
        v = rep.of("C8")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertEqual(v.limit, 320.0)
        self.assertAlmostEqual(v.slack, 310.0 - 320.0)

    def test_zero_cost_item_skipped(self):
        a = Phase1Item(item_id="A", q0=1000.0, q1_point=900.0, c_i=0.0,
                       p0=500.0, cap=600.0, L=350.0, U=600.0)
        rep, _ = run(base_instance(items=(a, base_items()[1], base_items()[2]),
                                   active=("C8",)), d_max=0.2)
        v = rep.of("C8")
        self.assertEqual(v.status, STATUS_PASS)
        row = next(r for r in v.rows if r["item_id"] == "A")
        self.assertEqual(row["status"], STATUS_SKIP)

    def test_missing_d_max_blocked(self):
        rep, _ = run(base_instance(active=("C8",)))
        self.assertEqual(rep.of("C8").status, "BLOCKED")


# ==========================================================================
# CJ-09 C9
# ==========================================================================
class TestC9(unittest.TestCase):
    def test_inactive_skip(self):
        rep, _ = run()
        self.assertEqual(rep.of("C9").status, STATUS_SKIP)

    def test_pass_with_Z_min(self):
        rep, _ = run(base_instance(active=("C9",)), Z=50_000.0, Z_min=40_000.0)
        v = rep.of("C9")
        self.assertEqual(v.status, STATUS_PASS)
        self.assertEqual(v.slack, 10_000.0)

    def test_pi_target_fail(self):
        # Σ c·q1 = 400×900 + 300×500 = 510000；pi_target=0.2 ⇒ 102000
        rep, _ = run(base_instance(active=("C9",)), Z=50_000.0, pi_target=0.2)
        v = rep.of("C9")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertEqual(v.limit, 106_000.0)

    def test_missing_Z_blocked(self):
        rep, _ = run(base_instance(active=("C9",)), Z_min=1.0)
        self.assertEqual(rep.of("C9").status, "BLOCKED")

    def test_no_limit_declared_blocked(self):
        rep, _ = run(base_instance(active=("C9",)), Z=1.0)
        self.assertEqual(rep.of("C9").status, "BLOCKED")


# ==========================================================================
# CJ-10 C10
# ==========================================================================
class TestC10(unittest.TestCase):
    def test_no_front_skip(self):
        rep, _ = run()
        self.assertEqual(rep.of("C10").status, STATUS_SKIP)

    def test_pass_break_even(self):
        # (0.8×500 − 400)×1000 = 0
        rep, _ = run(front_rho={"A": 0.8})
        v = rep.of("C10")
        self.assertEqual(v.status, STATUS_PASS)
        self.assertEqual(v.actual, 0.0)

    def test_negative_front_fails(self):
        rep, _ = run(front_rho={"A": 0.3})
        v = rep.of("C10")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertEqual(v.actual, (0.3 * 500.0 - 400.0) * 1000.0)

    def test_unknown_front_item_blocked(self):
        rep, _ = run(front_rho={"NOPE": 0.5})
        self.assertEqual(rep.of("C10").status, "BLOCKED")


# ==========================================================================
# CJ-11 C11
# ==========================================================================
class TestC11(unittest.TestCase):
    def test_not_active_skip(self):
        rep, _ = run()
        self.assertEqual(rep.of("C11").status, STATUS_SKIP)

    def test_kappa_only_blocked_no_silent_mad(self):
        """MAD 已被否决：仅 kappa_max ⇒ BLOCKED，不得静默替换判据。"""
        rep, _ = run(kappa_max=0.1)
        self.assertEqual(rep.of("C11").status, "BLOCKED")

    def test_sigma_over_fail(self):
        # d_A = (500−600)/600 = −1/6；d_B = (400−450)/450 = −1/9
        sigma = math.sqrt(((1 / 6) ** 2 + (1 / 9) ** 2) / 2)
        rep, _ = run(sigma_max=0.1)
        v = rep.of("C11")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertAlmostEqual(v.actual, sigma, places=12)

    def test_sigma_under_pass_and_free_excluded(self):
        rep, _ = run(sigma_max=0.5)
        v = rep.of("C11")
        self.assertEqual(v.status, STATUS_PASS)
        row = next(r for r in v.rows if r["item_id"] == "F")
        self.assertEqual(row["status"], STATUS_SKIP)


# ==========================================================================
# CJ-12 C12
# ==========================================================================
class TestC12(unittest.TestCase):
    def test_not_active_skip(self):
        rep, _ = run()
        self.assertEqual(rep.of("C12").status, STATUS_SKIP)

    def test_pass(self):
        # num = 725000（X_opt）+ 300×50（N 用外生 p0）= 740000
        # den = 570000 + 100×50 = 575000
        rep, _ = run(R_min=0.8)
        v = rep.of("C12")
        self.assertEqual(v.status, STATUS_PASS)
        self.assertAlmostEqual(v.actual, 740_000.0 / 575_000.0, places=12)

    def test_fail_means_P_star_unacceptable(self):
        rep, _ = run(R_min=1.3)
        v = rep.of("C12")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertIn("P* 不可接受", v.reason)

    def test_tolerance_is_eps_ratio_not_eps_price_times_P(self):
        """DV-02 显式隔离：缺口 1e-6 元比值。

        eps_ratio = 1e-9 ⇒ FAIL（正确）。
        若误用 eps_price×P* = 8e-4 ⇒ 会 PASS（容差被放大 10⁶ 倍）。
        """
        r_pc = 740_000.0 / 575_000.0
        rep, _ = run(R_min=r_pc + 1e-6)
        self.assertEqual(rep.of("C12").status, STATUS_FAIL)

    def test_missing_c_blocked(self):
        a = Phase1Item(item_id="A", q0=1000.0, q1_point=900.0, c_i=None,
                       p0=500.0, cap=600.0, L=350.0, U=600.0)
        rep, _ = run(base_instance(items=(a, base_items()[1], base_items()[2])),
                     R_min=0.8)
        self.assertEqual(rep.of("C12").status, "BLOCKED")

    def test_non_opt_uses_exogenous_p0(self):
        """分子对非 X_opt 项用外生固定价 p0——改 p0 必须改变 R_pc。"""
        n = Phase1Item(item_id="N", role=ROLE_NON_COMPETITIVE,
                       in_c1_scope=False, q0=50.0, q1_point=50.0,
                       c_i=100.0, p0=1000.0)
        rep, _ = run(base_instance(items=(*base_items(), n)), R_min=0.8)
        v = rep.of("C12")
        num = 725_000.0 + 1000.0 * 50.0
        self.assertAlmostEqual(v.actual, num / 575_000.0, places=12)


# ==========================================================================
# CJ-13 C13
# ==========================================================================
class TestC13(unittest.TestCase):
    def test_always_skip(self):
        rep, _ = run(base_instance(active=("C13",)))
        v = rep.of("C13")
        self.assertEqual(v.status, STATUS_SKIP)
        self.assertIn("SETTLEMENT_ADJUSTMENT", v.reason)


# ==========================================================================
# 聚合与形状
# ==========================================================================
class TestAggregation(unittest.TestCase):
    def test_fail_beats_blocked(self):
        rep, _ = run(p=base_p(A=501.0), floor_by_id={})  # C1 FAIL + C4 BLOCKED
        self.assertEqual(rep.verdict(), STATUS_FAIL)
        self.assertIn("C1", [v.constraint_id for v in rep.blocking()])

    def test_blocked_when_only_blocked(self):
        rep, _ = run(floor_by_id={})
        self.assertEqual(rep.verdict(), "BLOCKED")

    def test_p1_fail_does_not_block_P0(self):
        """C12（P1）FAIL 不阻塞 P0 主干，但 verdict_all 可见。"""
        rep, _ = run(R_min=1.3)
        self.assertEqual(rep.verdict(), STATUS_PASS)
        self.assertEqual(rep.verdict_all(), STATUS_FAIL)

    def test_empty_verdict_set_blocked(self):
        self.assertEqual(ConstraintReport(verdicts=()).verdict(), "BLOCKED")

    def test_six_tuple_shape(self):
        rep, _ = run(base_instance(active=("C6", "C7", "C8", "C9")),
                     theta=0.05, N_max=2.0, d_max=0.2, Z=1.0, Z_min=0.5,
                     R_min=0.8, sigma_max=0.5)
        for v in rep.verdicts:
            self.assertEqual(v.severity, "P0" if v.constraint_id not in
                             ("C11", "C12") else "P1")
            if v.status in (STATUS_PASS, STATUS_WARN, STATUS_FAIL):
                self.assertIsNotNone(v.actual, v.constraint_id)
                self.assertIsNotNone(v.limit, v.constraint_id)
                self.assertIsNotNone(v.slack, v.constraint_id)


class TestTolerances(unittest.TestCase):
    def test_eps_total_formula_and_missing_P_star(self):
        spec = load_constraint_spec()
        tol, missing = resolve_tolerances(spec, 800_000.0)
        self.assertEqual(tol["eps_total"], max(0.01, 1e-9 * 800_000.0))
        self.assertNotIn("eps_total", missing)
        tol2, missing2 = resolve_tolerances(spec, None)
        self.assertNotIn("eps_total", tol2)
        self.assertIn("eps_total", missing2)

    def test_named_tolerances_resolved(self):
        spec = load_constraint_spec()
        tol, missing = resolve_tolerances(spec, 1.0)
        self.assertEqual(missing, ())
        for name in ("eps_c1_abs", "eps_res", "eps_ratio", "eps_price",
                     "resolution", "eps_total"):
            self.assertIn(name, tol)


if __name__ == "__main__":
    unittest.main()
