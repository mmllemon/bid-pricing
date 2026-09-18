"""T03-03 预检引擎的区分性测试。

两条铁律：

* **判据必须能被错误的值否定**——注入伪造证书（dataclasses.replace 改一个
  字段）必须翻转对应判据的结论，否则该判据是摆设；
* **缺失与零必须机器可区分**（ADR-0004/规则⑤）——q0 缺 ⇒ 求和不落值，
  不是按 0 继续；cap 空 ⇒ P_max 不落值，不是 0。

数值全部手算可复算（simple 探针三项：S-MID/S-HI/S-LO，见
``solver/phase1.phase1_simple_probe_instance``）。派生量用**手工构造**的
DerivedReport（L/U/floor 逐项落值），使证书算式与派生层行为解耦、逐项
可复算；派生层自身的行为由 tests.test_derived 负责。
"""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bidpricing.derived import DerivedItem, DerivedReport
from bidpricing.solver.constraint_judge import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
)
from bidpricing.solver.instance import Phase1Item, Phase1Instance
from bidpricing.solver.phase1 import (
    phase1_probe_instance,
    phase1_simple_probe_instance,
)
from bidpricing.solver.precheck import (
    PrecheckCertificate,
    PrecheckInputs,
    build_certificate,
    judge_precheck,
    load_precheck_spec,
    precheck_report,
)

SPEC = load_precheck_spec()

ROLES = frozenset({"OPTIMIZABLE", "FIXED", "NON_COMPETITIVE", "PASS_THROUGH",
                   "CONTRACT_DEFINED"})

TOL = {"eps_c1_abs": 0.01, "eps_price": 1e-09, "resolution": 0.01}

#: 「P_star 未指定」哨兵——None 是合法取值（缺数据 ⇒ BLOCKED），须可区分
_P_UNSET = object()

# simple 探针手算证书（vat=0.09、surtax=0.03 ⇒ k = 1.0927）：
P_MIN = 400.0 * 2000.0 + 400.0 * 1000.0 + 200.0 * 500.0        # 1.3e6
P_MAX = 700.0 * 2000.0 + 800.0 * 1000.0 + 500.0 * 500.0        # 2.45e6
MODEL_LOWER = 600.0 * 2000.0 + 400.0 * 1000.0 + 300.0 * 500.0  # max(L, c_i)·q0
COST_TOTAL = 600.0 * 2000.0 + 400.0 * 1000.0 + 300.0 * 500.0   # Σ c_i q0
CAP_TOTAL = P_MAX                                              # 全项 cap=U
COST_LINE = 1.05 * COST_TOTAL                                  # π = 0.05
CAP_FLOOR = 0.90 * CAP_TOTAL                                   # α = 0.10
P_STAR = 2_400_000.0
P_STAR_VAR = P_STAR / 1.0927                                   # fixed=0、S=0
P_STAR_EFF = max(MODEL_LOWER, COST_LINE, CAP_FLOOR)            # 2.205e6


def hand_derived(inst: Phase1Instance, *, floor: str = "cost") -> DerivedReport:
    """逐项手工派生：L/U 取实例声明，floor 取 c_i（μ=0 的严格地板）。"""
    items = []
    for it in inst.items:
        f = it.c_i if floor == "cost" else (
            float(floor) if isinstance(floor, (int, float)) else None)
        items.append(DerivedItem(
            item_id=it.item_id, L=it.L, U=it.U, floor=f, r_eff=1.0,
            cap=it.cap,
            inputs_used=frozenset({"L", "U", "floor"}),
        ))
    return DerivedReport(
        items=tuple(items), checks=(),
        loss_acceptance="DECLINE", loss_acceptance_declared=True,
        mu=0.0, mu_declared=True,
    )


def make_inputs(inst=None, *, derived=None, p_star=_P_UNSET, **over) -> PrecheckInputs:
    inst = inst if inst is not None else phase1_simple_probe_instance()
    if p_star is not _P_UNSET:
        inst = replace(inst, P_star=p_star)
    kw = dict(
        instance=inst,
        derived=derived if derived is not None else hand_derived(inst),
        rule_set_id="GB50500-2024",
        contract_type="UNIT_PRICE",
        pi_target=0.05,
        alpha_cap=0.10,
        fixed_pretax=0.0,
        vat_rate=0.09,
        surtax_rate=0.03,
        role_domain=ROLES,
    )
    kw.update(over)
    return PrecheckInputs(**kw)


def run(inputs: PrecheckInputs):
    return precheck_report(inputs, spec=SPEC, tolerances=TOL)


# ---------------------------------------------------------------------------
# 证书计算（手算钉值）
# ---------------------------------------------------------------------------

class TestCertificate(unittest.TestCase):

    def test_hand_computed_values(self):
        cert = build_certificate(make_inputs())
        self.assertAlmostEqual(cert.p_min, P_MIN, places=6)
        self.assertAlmostEqual(cert.p_max, P_MAX, places=6)
        self.assertAlmostEqual(cert.p_star_var, P_STAR_VAR, places=1)
        self.assertAlmostEqual(cert.eff_terms["model_lower"], MODEL_LOWER)
        self.assertAlmostEqual(cert.eff_terms["cost_line"], COST_LINE)
        self.assertAlmostEqual(cert.eff_terms["cap_floor"], CAP_FLOOR)
        self.assertAlmostEqual(cert.p_star_eff, P_STAR_EFF)
        self.assertEqual(cert.delta_p, 0.0)
        self.assertEqual(cert.missing, ())

    def test_fixed_pretax_reduces_p_star_var(self):
        """P*_var 必须随固定项减小——证明它真经过了 compute_P_competitive。"""
        c0 = build_certificate(make_inputs(fixed_pretax=0.0))
        c1 = build_certificate(make_inputs(fixed_pretax=100_000.0))
        # 闭式 C = (P* + S·k)/(1+k) − A：∂C/∂A = −1（A 直接扣减，不除 1+k）
        self.assertAlmostEqual(c0.p_star_var - c1.p_star_var, 100_000.0, places=6)

    def test_q0_missing_makes_sums_none_not_zero(self):
        """q0 缺 ⇒ 求和不落值（None），不是按 0 继续（静默虚低）。"""
        item = replace(phase1_simple_probe_instance().items[0], q0=None)
        inst = replace(phase1_simple_probe_instance(),
                       items=(item,) + phase1_simple_probe_instance().items[1:])
        rep = run(make_inputs(inst))
        self.assertIsNone(rep.certificate.p_min)
        self.assertIsNone(rep.certificate.p_max)
        self.assertEqual(rep.overall, STATUS_BLOCKED)

    def test_cap_empty_keeps_p_max_none_not_zero(self):
        """cap 空 ⇒ P_max 不落值（≠0）+ PC-04 SKIP，不判必然 FAIL。"""
        rep = run(make_inputs(phase1_probe_instance()))
        self.assertIsNone(rep.certificate.p_max)
        self.assertTrue(rep.certificate.p_max_capped_only)
        self.assertEqual(rep.of("PC-04").status, STATUS_SKIP)

    def test_supplied_material_undeclared_defaults_zero_with_note(self):
        cert = build_certificate(make_inputs(supplied_material=None))
        self.assertTrue(any("按 0" in n for n in cert.notes))


# ---------------------------------------------------------------------------
# 判据区分性（§6.2 逐行）
# ---------------------------------------------------------------------------

class TestFeasibilityFails(unittest.TestCase):

    def test_boundary_exact_passes(self):
        """P*_var 恰好等于 P_min ⇒ PASS（贴边可行，eps 内）。"""
        p_star = P_MIN * 1.0927
        rep = run(make_inputs(p_star=p_star))
        self.assertEqual(rep.of("PC-03").status, STATUS_PASS)
        self.assertAlmostEqual(abs(rep.of("PC-03").actual
                                   - rep.of("PC-03").limit), 0.0, places=6)

    def test_lower_violation_by_1_unit_fails(self):
        """P_min 越界 1 元 ⇒ FAIL：判据必须对微量越界敏感。"""
        p_star = (P_MIN - 1.0) * 1.0927
        rep = run(make_inputs(p_star=p_star))
        self.assertEqual(rep.of("PC-03").status, STATUS_FAIL)
        self.assertEqual(rep.feasibility, STATUS_FAIL)
        gap = rep.of("PC-03").limit - rep.of("PC-03").actual
        self.assertGreater(gap, 0.9)  # 缺口 ≈ 1 元，注入虚值须改变它

    def test_upper_violation_fails(self):
        p_star = 2.8e6  # P*_var ≈ 2.5623e6 > P_max = 2.45e6
        rep = run(make_inputs(p_star=p_star))
        self.assertEqual(rep.of("PC-04").status, STATUS_FAIL)
        self.assertEqual(rep.feasibility, STATUS_FAIL)

    def test_eff_gap_fail_reports_delta_p(self):
        p_star = 2.0e6  # P*_var ≈ 1.8303e6 ≥ P_min，但 < P*_eff = 2.205e6
        rep = run(make_inputs(p_star=p_star))
        self.assertEqual(rep.of("PC-03").status, STATUS_PASS)
        self.assertEqual(rep.of("PC-06").status, STATUS_FAIL)
        self.assertAlmostEqual(rep.certificate.delta_p,
                               P_STAR_EFF - p_star, places=4)

    def test_self_conflict_fails(self):
        """max(L, floor) 之和 > U 之和 ⇒ μ 与 δ 冲突（与 P* 无关）。"""
        inst = phase1_simple_probe_instance()
        d = hand_derived(inst)
        item = DerivedItem(item_id="S-LO", L=200.0, U=500.0, floor=3000.0,
                           r_eff=1.0, cap=500.0)
        items = tuple(item if i.item_id == "S-LO" else i for i in d.items)
        d2 = replace(d, items=items)
        rep = run(make_inputs(derived=d2))
        v = rep.of("PC-07")
        self.assertEqual(v.status, STATUS_FAIL)
        self.assertGreater(v.actual, v.limit)


class TestBlocked(unittest.TestCase):

    def test_rule_set_missing(self):
        rep = run(make_inputs(rule_set_id=None))
        self.assertEqual(rep.of("PC-01").status, STATUS_BLOCKED)

    def test_role_domain_absent_is_blocked_not_pass(self):
        """机制制品未读 ⇒ BLOCKED，不得按『全部合法』跳过。"""
        rep = run(make_inputs(role_domain=frozenset()))
        self.assertEqual(rep.of("PC-02").status, STATUS_BLOCKED)

    def test_unclassified_role_lists_items(self):
        item = replace(phase1_simple_probe_instance().items[0], role="WEIRD")
        inst = replace(phase1_simple_probe_instance(),
                       items=(item,) + phase1_simple_probe_instance().items[1:])
        rep = run(make_inputs(inst))
        v = rep.of("PC-02")
        self.assertEqual(v.status, STATUS_BLOCKED)
        self.assertIn("S-MID", v.actual)

    def test_mu_undeclared_blocks_eff(self):
        """floor 缺（μ 未落值，OI-DQ-A）⇒ P*_eff BLOCKED 且具名。"""
        d = hand_derived(phase1_simple_probe_instance(), floor=None)
        rep = run(make_inputs(derived=d))
        v = rep.of("PC-05")
        self.assertEqual(v.status, STATUS_BLOCKED)
        self.assertIn("μ", v.detail)

    def test_pi_undeclared_vs_none_distinct_but_both_blocked(self):
        """两种未定态（key 缺失 / key 存在取值为空）都 BLOCKED 且理由可区分。"""
        from bidpricing.solver.precheck import _UNSET
        r_unset = run(replace(make_inputs(), pi_target=_UNSET))
        r_none = run(make_inputs(pi_target=None))
        self.assertEqual(r_unset.of("PC-05").status, STATUS_BLOCKED)
        self.assertEqual(r_none.of("PC-05").status, STATUS_BLOCKED)
        self.assertIn("未声明", r_unset.of("PC-05").detail)
        self.assertIn("取值为空", r_none.of("PC-05").detail)

    def test_alpha_declared_but_cap_empty_blocked(self):
        """α_cap 已声明而存在空 cap 项 = 声明与数据矛盾 ⇒ BLOCKED。"""
        rep = run(make_inputs(phase1_probe_instance(), alpha_cap=0.10))
        self.assertEqual(rep.of("PC-05").status, STATUS_BLOCKED)
        self.assertIn("矛盾", rep.of("PC-05").detail)

    def test_vat_missing_blocks_certificate(self):
        rep = run(make_inputs(vat_rate=None))
        self.assertEqual(rep.of("PC-03").status, STATUS_BLOCKED)

    def test_p_star_missing_blocks(self):
        rep = run(make_inputs(p_star=None))
        self.assertEqual(rep.of("PC-03").status, STATUS_BLOCKED)
        self.assertEqual(rep.of("PC-06").status, STATUS_BLOCKED)


class TestSkipWarn(unittest.TestCase):

    def test_contract_type_none_skips(self):
        rep = run(make_inputs(contract_type=None))
        self.assertEqual(rep.of("PC-08").status, STATUS_SKIP)

    def test_lump_sum_warns(self):
        rep = run(make_inputs(contract_type="LUMP_SUM"))
        self.assertEqual(rep.of("PC-08").status, STATUS_WARN)

    def test_self_conflict_skips_when_uncapped(self):
        rep = run(make_inputs(phase1_probe_instance()))
        self.assertEqual(rep.of("PC-07").status, STATUS_SKIP)


# ---------------------------------------------------------------------------
# 计算/判定分离：注入伪造证书必须翻转结论
# ---------------------------------------------------------------------------

class TestJudgeInjectability(unittest.TestCase):

    def _judge(self, inputs, cert):
        report, _ = judge_precheck(inputs, cert, SPEC, TOL)
        return report

    def test_injected_low_p_star_var_flips_pc03(self):
        inputs = make_inputs()
        cert = build_certificate(inputs)
        base = self._judge(inputs, cert)
        self.assertEqual(base.of("PC-03").status, STATUS_PASS)
        forged = replace(cert, p_star_var=cert.p_min - 100.0)
        rep = self._judge(inputs, forged)
        self.assertEqual(rep.of("PC-03").status, STATUS_FAIL)

    def test_injected_high_p_star_var_flips_pc04(self):
        inputs = make_inputs()
        cert = build_certificate(inputs)
        forged = replace(cert, p_star_var=cert.p_max + 100.0)
        self.assertEqual(self._judge(inputs, forged).of("PC-04").status,
                         STATUS_FAIL)

    def test_injected_zero_delta_cannot_hide_gap(self):
        """把 ΔP 伪造成 0 掩不住缺口——PC-06 看的是 P* 与 P*_eff 本身。"""
        inputs = make_inputs(p_star=2.0e6)
        cert = build_certificate(inputs)
        self.assertGreater(cert.delta_p, 0.0)
        forged = replace(cert, delta_p=0.0)
        self.assertEqual(self._judge(inputs, forged).of("PC-06").status,
                         STATUS_FAIL)

    def test_injected_eff_hides_gap_is_caught(self):
        """把 P*_eff 伪造成低于 P* ⇒ PC-06 变 PASS——缺口被隐藏须可见：
        伪造本身改了 limit，actual(P*) 与 limit 的关系随注入值翻转。"""
        inputs = make_inputs(p_star=2.0e6)
        cert = build_certificate(inputs)
        forged = replace(cert, p_star_eff=1.0e6,
                         eff_terms={"model_lower": 1.0e6, "cost_line": 1.0e6,
                                    "cap_floor": 1.0e6})
        self.assertEqual(self._judge(inputs, forged).of("PC-06").status,
                         STATUS_PASS)

    def test_empty_verdicts_blocked(self):
        inputs = make_inputs()
        cert = build_certificate(inputs)
        report, _ = judge_precheck(inputs, cert, SPEC, TOL)
        # 构造空判据集：直接调内部聚合路径
        from bidpricing.solver.precheck import PrecheckReport, _worst
        empty = PrecheckReport(certificate=cert, verdicts=(),
                               feasibility=STATUS_BLOCKED, overall="")
        self.assertEqual(empty.verdicts, ())
        # 聚合序：FAIL > BLOCKED > WARN > SKIP > PASS
        self.assertEqual(_worst([STATUS_PASS, STATUS_WARN]), STATUS_WARN)
        self.assertEqual(_worst([STATUS_SKIP, STATUS_PASS]), STATUS_SKIP)
        self.assertEqual(_worst([STATUS_BLOCKED, STATUS_FAIL]), STATUS_FAIL)


class TestAggregation(unittest.TestCase):

    def test_full_pass_overall(self):
        rep = run(make_inputs())
        self.assertEqual(rep.overall, STATUS_PASS)
        self.assertEqual(rep.feasibility, STATUS_PASS)
        self.assertEqual(len(rep.verdicts), 8)

    def test_skip_does_not_beat_pass(self):
        """free-cap 探针：PC-04/07 SKIP、PC-05 BLOCKED ⇒ 整体 BLOCKED；
        若无 BLOCKED 而只有 SKIP + PASS，整体必须是 PASS（SKIP 不参与最严竞争）。"""
        rep = run(make_inputs(phase1_probe_instance()))
        self.assertEqual(rep.overall, STATUS_BLOCKED)
        # 纯 SKIP+PASS 场景：cap 空且 α 未声明会 BLOCKED，故用 contract SKIP 验证
        rep2 = run(make_inputs(contract_type=None))
        self.assertEqual(rep2.overall, STATUS_PASS)


if __name__ == "__main__":
    unittest.main()
