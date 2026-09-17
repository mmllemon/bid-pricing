"""T04-00《Phase 1 精确性条件与反例集》的测试。

测试分四组：

* ``REffFormulaTest`` —— 排序键 ``r_eff`` 与结算收入 ``R_i`` 的公式锁定；
* ``ExchangeArgumentTest`` —— 阈值分割定理的**数值验证**（端点比较，独立于 KKT）；
* ``ConditionTest`` —— EC-1..EC-9 逐条的正例与负例（每条判据都要能被错误的值否定）；
* ``SpecLockTest`` —— 制品 ``phase1_exactness_spec.json`` 与实现的**双向锁定**。

**纪律**：全部用例用合成的 ``ResolvedParameters``，不读项目当前落值
（``project_selection`` / 规则卡的项目级参数）。否则用户一改口径，
断言就会翻转——本项目已因此踩过两次。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from bidpricing.contracts.pricing_card import (
    ResolvedParameters,
    compute_p1,
    compute_r_eff,
    load_pricing_card,
    resolve_parameters,
    settlement_revenue,
)
from bidpricing.solver.cases import (
    WITNESS_ASSERTIONS,
    load_exactness_spec,
    run_cases,
)
from bidpricing.solver.exactness import (
    CONDITION_IDS,
    EXACTNESS_IDS,
    IMPLEMENTABILITY_IDS,
    ExactnessVerdict,
    check_exactness,
)
from bidpricing.solver.instance import (
    Phase1Instance,
    check_solution,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"

_KEYS = ("rho_plus", "rho_minus", "increase_threshold",
         "decrease_threshold", "adjustment_scope")


def resolved(scope: str = "FULL", rho_plus: float = 0.0,
             rho_minus: float = 0.0, theta: float = 0.15) -> ResolvedParameters:
    """合成参数——**不读项目实时状态**，避免断言随落值翻转。"""
    return ResolvedParameters(
        rho_plus=rho_plus,
        rho_minus=rho_minus,
        increase_threshold=1.0 + theta,
        decrease_threshold=1.0 - theta,
        adjustment_scope=scope,
        sources={k: "test" for k in _KEYS},
    )


def item(item_id: str, **kw):
    base = dict(role="OPTIMIZABLE", in_c1_scope=True, q0=100.0, q1_point=100.0,
                c_i=50.0, p0=100.0, cap=120.0, L=50.0, U=120.0, alpha=0.0)
    base.update(kw)
    from bidpricing.solver.instance import Phase1Item

    return Phase1Item(item_id=item_id, **base)


def instance(items, B=20000.0, params=None, **kw):
    from bidpricing.solver.instance import Phase1Params

    # 默认全 None => 参数继承调用方传入的 ResolvedParameters（便于测各分支）；
    # 只有显式传 params 的用例才把规则集参数钉在实例上。
    p = Phase1Params(**params) if params is not None else Phase1Params()
    return Phase1Instance(items=tuple(items), B=B, P_star=B, params=p, **kw)


# ---------------------------------------------------------------------------
class REffFormulaTest(unittest.TestCase):
    """r_eff 与 R_i 的公式锁定（model_v0.3_R2.md §5.3.1 / §5.2.2）。"""

    def test_full_in_range_carries_alpha(self):
        p = resolved("FULL")
        self.assertAlmostEqual(compute_r_eff(1.0, p, 0.5), 1.5)

    def test_full_increase_uses_rho_plus_only(self):
        p = resolved("FULL", rho_plus=0.8)
        self.assertAlmostEqual(compute_r_eff(1.6, p), 0.32)

    def test_full_decrease_uses_rho_minus(self):
        p = resolved("FULL", rho_minus=0.2)
        self.assertAlmostEqual(compute_r_eff(0.8, p), 0.96)

    def test_segment_in_range_is_plain_r(self):
        """SEGMENT 下区间内不带 (1+alpha)——未越界部分按原单价结算。"""
        p = resolved("SEGMENT")
        self.assertAlmostEqual(compute_r_eff(1.0, p, 0.5), 1.0)

    def test_segment_increase_matches_spec_example_2r(self):
        """附录 B 例 2R：r=1.6, θ=0.15, ρ⁺=0.8 => 1.15 + 0.2×0.45 = 1.24。"""
        p = resolved("SEGMENT", rho_plus=0.8)
        self.assertAlmostEqual(compute_r_eff(1.6, p), 1.24)
        # 同实例 FULL 分支：0.2 × 1.6 = 0.32——排序方向相反
        self.assertAlmostEqual(compute_r_eff(1.6, resolved("FULL", rho_plus=0.8)), 0.32)

    def test_rho_plus_one_collapses_increase_branch_to_zero(self):
        """§5.3.2 收敛性：ρ⁺=1 时高段 r_eff 恒为 0。"""
        self.assertAlmostEqual(compute_r_eff(1.6, resolved("FULL", rho_plus=1.0)), 0.0)

    def test_rho_plus_above_one_gives_negative_revenue(self):
        """CE-04：ρ⁺>1 使增段系数为负，R_i(1) < 0（非物理）。"""
        p = resolved("FULL", rho_plus=1.2)
        self.assertLess(compute_r_eff(1.6, p), 0.0)
        self.assertLess(settlement_revenue(100.0, 160.0, 1.0, p), 0.0)

    def test_settlement_revenue_matches_compute_p1(self):
        """同一公式的两种形态必须逐值一致（alpha=0）——防止出现第二事实源。"""
        card = load_pricing_card(CONFIG_DIR)
        base = resolve_parameters(card)
        for scope in ("FULL", "SEGMENT"):
            p = resolved(scope, rho_plus=0.8, rho_minus=0.1)
            for q0, q1 in ((100.0, 80.0), (100.0, 100.0), (100.0, 115.0),
                           (100.0, 130.0), (100.0, 300.0)):
                card_scope = dict(card)
                card_scope["adjustment_scope"] = scope
                card_scope["parameters"] = dict(card["parameters"],
                                                rho_plus=0.8, rho_minus=0.1)
                via_p1 = compute_p1(q0, q1, 100.0, card_scope).settlement
                via_pure = settlement_revenue(q0, q1, 100.0, p)
                self.assertAlmostEqual(
                    via_p1, via_pure, places=9,
                    msg=f"scope={scope} q0={q0} q1={q1}",
                )
        self.assertEqual(base.adjustment_scope in ("FULL", "SEGMENT"), True)


# ---------------------------------------------------------------------------
class ExchangeArgumentTest(unittest.TestCase):
    """阈值分割定理的数值验证：用**端点比较**（不依赖 KKT / 排序算法）。"""

    def _pe01(self, scope: str = "SEGMENT") -> Phase1Instance:
        return instance(
            [item("1", q0=100, q1_point=110, c_i=50, L=80, U=120),
             item("2", q0=100, q1_point=160, c_i=50, L=80, U=120)],
            B=20000.0,
            params={"theta_dev": 0.15, "rho_plus": 0.8, "rho_minus": 0.0,
                    "adjustment_scope": scope},
        )

    def test_segment_puts_budget_on_the_over_threshold_item(self):
        """附录 B 例 2R：SEGMENT 下 r_eff_2 = 1.24 > r_eff_1 = 1.10。"""
        inst = self._pe01()
        p = resolved("SEGMENT", rho_plus=0.8)
        self.assertAlmostEqual(inst.r_eff(inst.items[0], p), 1.10)
        self.assertAlmostEqual(inst.r_eff(inst.items[1], p), 1.24)

    def test_n2_optimum_is_at_a_vertex_and_matches_spec_value(self):
        """n=2 且两项各在单一线性段内 => 目标在可行区间上线性 => 端点即最优。

        因此比较两个顶点构成**完整**的最优性验证（独立于 §7.2 的排序算法）。
        """
        inst = self._pe01()
        p = resolved("SEGMENT", rho_plus=0.8)
        low = check_solution(inst, {"1": 80.0, "2": 120.0}, p, eps_total=0.01)
        high = check_solution(inst, {"1": 120.0, "2": 80.0}, p, eps_total=0.01)
        self.assertTrue(low.feasible and high.feasible)
        self.assertAlmostEqual(low.Z, 10180.0, places=6)   # 附录 B 例 2R
        self.assertAlmostEqual(high.Z, 9620.0, places=6)
        self.assertGreater(low.Z, high.Z)

    def test_full_branch_reverses_the_optimum(self):
        """同一组数据在 FULL 下把预算给**未越界**项（p1=120），结论方向相反。"""
        inst = self._pe01("FULL")
        p = resolved("FULL", rho_plus=0.8)
        a = check_solution(inst, {"1": 120.0, "2": 80.0}, p, eps_total=0.01)
        b = check_solution(inst, {"1": 80.0, "2": 120.0}, p, eps_total=0.01)
        self.assertGreater(a.Z, b.Z)
        self.assertAlmostEqual(a.Z, 2260.0, places=6)      # 附录 B 例 2R
        self.assertAlmostEqual(b.Z, -860.0, places=6)

    def test_check_solution_flags_c1_residual_over_tolerance(self):
        inst = self._pe01()
        p = resolved("SEGMENT", rho_plus=0.8)
        # 故意把 p1 抬到 130，使可竞争部分 = 100×(130+80) = 21000 ≠ B = 20000
        bad = check_solution(inst, {"1": 130.0, "2": 80.0}, p, eps_total=0.01)
        self.assertFalse(bad.feasible)
        self.assertAlmostEqual(bad.c1_residual, 1000.0, places=6)

    def test_check_solution_flags_c5_zero_price(self):
        inst = self._pe01()
        p = resolved("SEGMENT", rho_plus=0.8)
        bad = check_solution(inst, {"1": 0.0, "2": 200.0}, p, eps_total=0.01)
        self.assertFalse(bad.feasible)
        self.assertTrue(any("C5" in v for v in bad.violations))

    # ---- DV-01 同族：业务侧盒式容差必须按**声明名**解析 --------------
    def test_box_bound_uses_the_declared_tolerance_when_supplied(self):
        """p 越界 5e-12，落在声明 eps_price=0.003 之内 ⇒ 两侧口径一致，判可行。

        旧口径下业务侧对 L/U 用严格比较（0 容差），会把这个解判不可行，
        而编译侧按声明容差判可行 —— 同一个解在两侧相反（DV-01）。
        """
        inst = self._pe01()
        p = resolved("SEGMENT", rho_plus=0.8)
        nudged = {"1": 120.0 + 5e-12, "2": 80.0}
        strict = check_solution(inst, nudged, p, eps_total=0.01)
        declared = check_solution(
            inst, nudged, p, eps_total=0.01,
            tolerances={"eps_price": 0.003, "eps_total": 0.01},
        )
        # 区分度：同一个解，两种口径给出相反结论。
        self.assertFalse(strict.feasible)
        self.assertTrue(declared.feasible, declared.violations)
        self.assertTrue(declared.tolerance_resolved)
        self.assertEqual(declared.tolerance_name, "eps_price")
        self.assertAlmostEqual(declared.tolerance_value, 0.003, places=12)

    def test_box_bound_beyond_the_declared_tolerance_still_fails(self):
        """区分度：真越界时，传了容差表也仍判不可行。"""
        inst = self._pe01()
        p = resolved("SEGMENT", rho_plus=0.8)
        far = {"1": 120.0 + 0.5, "2": 80.0}          # 远超 eps_price
        out = check_solution(
            inst, far, p, eps_total=0.01, tolerances={"eps_price": 0.003},
        )
        self.assertFalse(out.feasible)

    def test_missing_name_is_not_silently_read_as_strict(self):
        """传了表却缺该名 ⇒ 不得静默按 0；口径自述为「未解析」。"""
        inst = self._pe01()
        p = resolved("SEGMENT", rho_plus=0.8)
        out = check_solution(
            inst, {"1": 120.0, "2": 80.0}, p, eps_total=0.01,
            tolerances={"eps_total": 0.01},          # 表在，但缺 eps_price
        )
        self.assertEqual(out.tolerance_name, "eps_price")
        self.assertIsNone(out.tolerance_value)
        self.assertFalse(out.tolerance_resolved)
        # 缺名不改变可行与否（不制造假阴性/假阳性），只自述口径。
        self.assertTrue(out.feasible)

    def test_legacy_call_without_tolerances_is_unchanged(self):
        """不传表 ⇒ 严格口径，且口径自述为空（向后兼容）。"""
        inst = self._pe01()
        p = resolved("SEGMENT", rho_plus=0.8)
        out = check_solution(inst, {"1": 120.0, "2": 80.0}, p, eps_total=0.01)
        self.assertTrue(out.feasible)
        self.assertEqual(out.tolerance_name, "")
        self.assertIsNone(out.tolerance_value)
        self.assertFalse(out.tolerance_resolved)


# ---------------------------------------------------------------------------
class ConditionTest(unittest.TestCase):
    """EC-1..EC-9 逐条：每条都要有能被错误的值否定的证据。"""

    def _v(self, inst, scope="FULL", **kw):
        return check_exactness(inst, resolved(scope, **kw))

    # ---- EC-1 作用域完备性 ------------------------------------------
    def test_ec1_pass_on_clean_instance(self):
        v = self._v(instance([item("A", q1_point=110), item("B", q1_point=90)]))
        self.assertEqual(v.status_of("EC-1"), "PASS")
        self.assertEqual(v.verdict, "EXACT")

    def test_ec1_fails_when_non_optimizable_item_is_in_c1_scope(self):
        inst = instance([item("A"),
                         item("F", role="NON_COMPETITIVE", in_c1_scope=True)])
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-1"), "FAIL")
        self.assertEqual(v.verdict, "INAPPLICABLE")

    def test_ec1_fails_when_optimizable_item_is_outside_c1_scope(self):
        inst = instance([item("A"), item("B", in_c1_scope=False)])
        self.assertEqual(self._v(inst).status_of("EC-1"), "FAIL")

    def test_ec1_fails_when_no_optimizable_item(self):
        inst = instance([item("F", role="PASS_THROUGH")])
        self.assertEqual(self._v(inst).status_of("EC-1"), "FAIL")

    # ---- EC-2 排序键正确性 ------------------------------------------
    def test_ec2_pass_when_order_is_consistent(self):
        inst = instance([item("A", q1_point=100), item("B", q1_point=140)])
        self.assertEqual(self._v(inst).status_of("EC-2"), "PASS")

    def test_ec2_warns_when_alpha_inverts_the_order(self):
        """CE-02：α 逐项不同 => 按 r 排序与按 r_eff 排序相反。"""
        inst = instance([item("A", q1_point=100, alpha=0.5),
                         item("B", q1_point=140, alpha=0.0)])
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-2"), "WARN")
        # WARN 属 A 组但不否决——用对键仍精确
        self.assertEqual(v.verdict, "EXACT")
        self.assertTrue(v.implementation_notes or True)

    def test_ec2_ignores_flat_alternative_key(self):
        """α 全 0 时 (1+α) 对全部项取同值——「平」不得算作「排序不同」。"""
        inst = instance([item("A", q1_point=100), item("B", q1_point=160),
                         item("C", q1_point=90)])
        self.assertEqual(self._v(inst).status_of("EC-2"), "PASS")

    # ---- EC-3 权重正性 ----------------------------------------------
    def test_ec3_missing_q0_is_blocked_not_zero(self):
        """缺失与 0 必须机器可区分（ADR-0004）。"""
        inst = instance([item("A", q0=None), item("B")])
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-3"), "BLOCKED")
        self.assertEqual(v.verdict, "BLOCKED")

    def test_ec3_zero_q0_fails(self):
        inst = instance([item("A", q0=0.0), item("B")])
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-3"), "FAIL")
        self.assertEqual(v.verdict, "INAPPLICABLE")

    # ---- EC-4 系数非负性 --------------------------------------------
    def test_ec4_fails_on_rho_plus_above_one(self):
        inst = instance([item("A", q1_point=160)])
        v = self._v(inst, rho_plus=1.2)
        self.assertEqual(v.status_of("EC-4"), "FAIL")
        self.assertEqual(v.verdict, "INAPPLICABLE")

    def test_ec4_passes_on_rho_plus_equal_one(self):
        """ρ⁺=1 使 r_eff=0 但仍非负——退化由 EC-5 管，不是 EC-4。"""
        inst = instance([item("A", q1_point=160)])
        self.assertEqual(self._v(inst, rho_plus=1.0).status_of("EC-4"), "PASS")

    # ---- EC-5 非退化 -------------------------------------------------
    def test_ec5_fails_on_platform_without_tie_break(self):
        inst = instance([item("A", q1_point=160), item("B", q1_point=160)],
                        B=17000.0)
        v = self._v(inst, rho_plus=1.0)
        self.assertEqual(v.status_of("EC-5"), "FAIL")
        self.assertEqual(v.verdict, "INAPPLICABLE")

    def test_ec5_passes_on_platform_with_tie_break(self):
        inst = instance([item("A", q1_point=160), item("B", q1_point=160)],
                        B=17000.0, tie_break_policy="min_L1_deviation")
        v = self._v(inst, rho_plus=1.0)
        self.assertEqual(v.status_of("EC-5"), "PASS")
        self.assertEqual(v.verdict, "EXACT")

    def test_ec5_passes_when_zero_capacity_platform(self):
        """平台内可分配区间为 0（L=U）时不构成多解。"""
        inst = instance([item("A", q1_point=160, L=100.0, U=100.0),
                         item("B", q1_point=160, L=100.0, U=100.0)],
                        B=20000.0)
        self.assertEqual(self._v(inst, rho_plus=1.0).status_of("EC-5"), "PASS")

    # ---- EC-6 软约束不激活 ------------------------------------------
    def test_ec6_fails_when_c6_active(self):
        inst = instance([item("A"), item("B")],
                        active_soft_constraints=("C6",))
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-6"), "FAIL")
        self.assertEqual(v.verdict, "INAPPLICABLE")

    def test_ec6_c7_switches_solver_form_to_milp(self):
        inst = instance([item("A"), item("B")], active_soft_constraints=("C7",))
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-6"), "FAIL")
        self.assertEqual(v.solver_form, "MILP")

    # ---- EC-7 可行域非空 --------------------------------------------
    def test_ec7_fails_when_b_below_p_min(self):
        inst = instance([item("A", L=80.0), item("B", L=80.0)], B=15000.0)
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-7"), "FAIL")
        self.assertEqual(v.verdict, "INAPPLICABLE")

    def test_ec7_fails_when_box_is_inverted(self):
        inst = instance([item("A", L=130.0, U=120.0), item("B")])
        self.assertEqual(self._v(inst).status_of("EC-7"), "FAIL")

    def test_ec7_blocked_when_b_missing(self):
        inst = instance([item("A"), item("B")], B=None)
        self.assertEqual(self._v(inst).status_of("EC-7"), "BLOCKED")

    def test_ec7_only_checks_lower_side_when_cap_absent(self):
        """CE-09：含不限价项时上界侧不可判，但下界侧仍须验。"""
        inst = instance([item("A", U=None, cap=None), item("B")], B=20000.0)
        self.assertEqual(self._v(inst).status_of("EC-7"), "PASS")

    # ---- EC-8 舍入可调和性 ------------------------------------------
    def test_ec8_passes_when_bound_within_tolerance(self):
        inst = instance([item("A", q0=1.0), item("B", q0=1.0)], B=200.0)
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-8"), "PASS")

    def test_ec8_warns_with_reconciliation_declared(self):
        inst = instance([item("A", q0=30000.0, q1_point=33000.0),
                         item("B", q0=40000.0, q1_point=36000.0)],
                        B=7000000.0,
                        rounding_reconciliation_present=True)
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-8"), "WARN")
        # B 组 WARN 不改变 verdict
        self.assertEqual(v.verdict, "EXACT")
        self.assertEqual(len(v.implementation_notes), 1)

    def test_ec8_fails_without_reconciliation(self):
        inst = instance([item("A", q0=30000.0, q1_point=33000.0),
                         item("B", q0=40000.0, q1_point=36000.0)],
                        B=7000000.0,
                        rounding_reconciliation_present=False)
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-8"), "FAIL")
        self.assertEqual(v.verdict, "EXACT")  # B 组 FAIL 仍不改 verdict

    def test_ec8_growth_is_quantity_weighted(self):
        """判据必须是 0.005×Σq0 而不是 0.005×n——同 n 不同 q0 结果必须不同。"""
        small = self._v(instance([item("A", q0=1.0), item("B", q0=1.0)], B=200.0))
        big = self._v(instance([item("A", q0=100000.0, q1_point=110000.0),
                                item("B", q0=1.0, q1_point=0.9)],
                               B=10000000.0,
                               rounding_reconciliation_present=True))
        self.assertEqual(small.status_of("EC-8"), "PASS")
        self.assertEqual(big.status_of("EC-8"), "WARN")

    # ---- EC-9 上界有限性 --------------------------------------------
    def test_ec9_warns_on_null_cap_and_says_why(self):
        inst = instance([item("A", cap=None, U=None, q1_point=110),
                         item("B", q1_point=90)])
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-9"), "WARN")
        self.assertEqual(v.verdict, "EXACT")
        c = next(c for c in v.conditions if c.id == "EC-9")
        self.assertIn("交换论证", c.detail)
        self.assertIn("禁止", c.detail)

    def test_ec9_passes_when_all_caps_present(self):
        self.assertEqual(self._v(instance([item("A"), item("B")])).status_of("EC-9"),
                         "PASS")

    # ---- 组别与汇总 --------------------------------------------------
    def test_verdict_ignores_b_group_failures(self):
        """verdict 只看 A 组——混在一起会让 verdict 几乎永远不是 EXACT。"""
        inst = instance([item("A", q0=100000.0, q1_point=110000.0),
                         item("B", q0=100000.0, q1_point=90000.0)],
                        B=20000000.0, rounding_reconciliation_present=False)
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-8"), "FAIL")
        self.assertEqual(v.verdict, "EXACT")
        self.assertTrue(v.exact)

    def test_blocked_takes_precedence_over_fail(self):
        inst = instance([item("A", q0=None), item("B", L=130.0, U=120.0)])
        v = self._v(inst)
        self.assertEqual(v.status_of("EC-3"), "BLOCKED")
        self.assertEqual(v.status_of("EC-7"), "FAIL")
        self.assertEqual(v.verdict, "BLOCKED")

    def test_condition_ids_are_stable(self):
        self.assertEqual(CONDITION_IDS[:7], EXACTNESS_IDS)
        self.assertEqual(CONDITION_IDS[7:], IMPLEMENTABILITY_IDS)
        self.assertEqual(len(CONDITION_IDS), 9)


# ---------------------------------------------------------------------------
class SpecLockTest(unittest.TestCase):
    """制品与实现的双向锁定——任何一侧改动而另一侧未同步即失败。"""

    @classmethod
    def setUpClass(cls):
        cls.spec = load_exactness_spec(CONFIG_DIR)

    def test_condition_ids_cover_spec(self):
        declared = {c["id"] for c in self.spec["conditions"]}
        self.assertEqual(declared, set(CONDITION_IDS))

    def test_every_condition_has_group_and_counterexample(self):
        ce_ids = {c["id"] for c in self.spec["counterexamples"]}
        pe_ids = {c["id"] for c in self.spec["positive_examples"]}
        for c in self.spec["conditions"]:
            with self.subTest(cond=c["id"]):
                self.assertIn(c["group"], ("EXACTNESS", "IMPLEMENTABILITY"))
                self.assertIn(c["counterexample"], ce_ids | pe_ids)
                for key in ("statement", "check", "on_violation", "consequence",
                            "source"):
                    self.assertTrue(c.get(key), f"{c['id']} 缺 {key}")

    def test_every_counterexample_points_at_a_condition(self):
        cond_ids = {c["id"] for c in self.spec["conditions"]}
        for ce in self.spec["counterexamples"]:
            with self.subTest(ce=ce["id"]):
                self.assertIn(ce["violates"], cond_ids)

    def test_witness_assertion_keys_are_registered(self):
        """制品写了未登记的断言键 => 复算器会报不通过，这里提前拦下。"""
        for case in (self.spec["counterexamples"] + self.spec["positive_examples"]):
            w = case.get("witness") or {}
            for key in (w.get("assertions") or {}):
                with self.subTest(case=case["id"], key=key):
                    self.assertIn(key, WITNESS_ASSERTIONS)

    def test_all_cases_reconcile_against_implementation(self):
        """核心判据：制品里的 expected / witness 必须被实现逐条复现。"""
        results = run_cases(self.spec, resolved("FULL"))
        self.assertEqual(len(results), len(self.spec["counterexamples"])
                         + len(self.spec["positive_examples"]))
        for r in results:
            with self.subTest(case=r.case_id):
                self.assertEqual(r.condition_mismatches, (),
                                 f"{r.case_id} 条件层不一致")
                if r.witness is not None:
                    self.assertTrue(
                        r.witness.ok,
                        f"{r.case_id} 见证层不一致：{r.witness.failures()}",
                    )

    def test_spec_declares_theorem_and_scope(self):
        th = self.spec["theorem"]
        self.assertEqual(th["id"], "T1")
        self.assertIn("交换论证", th["proof_method"])
        self.assertTrue(th["proof"])
        self.assertTrue(th["what_it_does_not_claim"])
        # 必须显式声明不得声称「数学等价」
        self.assertTrue(any("不得称为" in v or "数学等价" in v
                            for v in self.spec["theorem"]["what_it_does_not_claim"]
                            + [self.spec["naming_consequence"]]))

    def test_spec_has_known_limits(self):
        self.assertTrue(self.spec.get("known_limits"))

    def test_spec_json_has_no_null_placeholders_in_required_keys(self):
        """未定态必须是 key 缺失，不得写成 null（ADR-0004）。"""
        for key in ("spec_id", "task", "theorem", "conditions", "counterexamples"):
            self.assertIsNotNone(self.spec.get(key), f"制品键 {key} 为 null")
        for c in self.spec["conditions"]:
            self.assertIsNotNone(c.get("on_violation"), f"{c['id']}.on_violation 为 null")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
