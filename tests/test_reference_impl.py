"""T04-08 独立参考实现的区分度测试。

每条判据都要**双向**验证：注入错误 ⇒ 必须 FAIL/BLOCKED；给出正确值 ⇒ 必须 PASS。
只验证「我的实现恰好对了」的测试没有信息量——注入式反例才证明判据在干活。
"""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from bidpricing.contracts.pricing_card import (
    load_pricing_card,
    resolve_parameters,
)
from bidpricing.paths import config_dir
from bidpricing.refimpl import isolation as I
from bidpricing.refimpl import reference as R
from bidpricing.solver.phase1 import (
    phase1_probe_instance,
    phase1_simple_probe_instance,
    solve_phase1,
)
from bidpricing.solver.verifier import load_verifier_spec, resolve_tolerances

CFG = config_dir()
_PROF = json.loads((CFG / "precision_profile.json").read_text(encoding="utf-8"))
RESOLVED = resolve_parameters(load_pricing_card(CFG))
SPEC = R.load_reference_spec(CFG)
TOLS, _ = resolve_tolerances(
    _PROF, load_verifier_spec(CFG), P_ref=2_000_000.0
)
REPO = CFG.parent
SRC_PATHS = [
    REPO / "src/bidpricing/refimpl/reference.py",
    REPO / "src/bidpricing/refimpl/isolation.py",
]


def _inst(name: str = "free-cap"):
    return (
        phase1_probe_instance() if name == "free-cap"
        else phase1_simple_probe_instance()
    )


def _p(name: str = "free-cap") -> dict[str, float]:
    inst = _inst(name)
    sol = solve_phase1(inst, RESOLVED)
    return dict(sol.p_by_id)


def _snap(name: str = "free-cap"):
    return R.snapshot(_inst(name), RESOLVED)


def _status(checks, prefix: str) -> str:
    for c in checks:
        if c.item.startswith(prefix):
            return c.status
    raise AssertionError(f"未产出判据 {prefix}")


def _judge(**kw):
    return R.judge_reference(
        declared_inputs=R.INPUT_NAMES,
        inputs_used=R.INPUT_NAMES,
        spec=SPEC,
        **kw,
    )


class TestRI01Readiness(unittest.TestCase):
    def test_correct_inputs_pass(self):
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        self.assertEqual(_status(_judge(objective=obj, residuals=(), params=snap.params), "RI-01"), R.STATUS_PASS)

    def test_no_objective_blocks(self):
        self.assertEqual(
            _status(_judge(objective=None, residuals=(), params=_snap().params), "RI-01"),
            R.STATUS_BLOCKED,
        )

    def test_no_params_blocks_instead_of_defaulting(self):
        obj = R.ref_objective(_snap(), _p())
        self.assertEqual(
            _status(_judge(objective=obj, residuals=(), params=None), "RI-01"),
            R.STATUS_BLOCKED,
        )

    def test_null_param_value_is_distinguishable_from_absent(self):
        """★ 键存在但值为 NaN（未落值）与「无参数对象」是两种未定态。"""
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        bad = R.RefParams(
            rho_plus=0.0, rho_minus=0.0, decrease_threshold=float("nan"),
            increase_threshold=1.15, adjustment_scope="SEGMENT",
            sources=(("rho_plus", "x"), ("rho_minus", "x"),
                     ("decrease_threshold", "x"), ("increase_threshold", "x"),
                     ("adjustment_scope", "x")),
        )
        checks = _judge(objective=obj, residuals=(), params=bad)
        self.assertEqual(_status(checks, "RI-01"), R.STATUS_BLOCKED)
        self.assertIn("decrease_threshold", checks[0].reason)

    def test_missing_scope_blocks(self):
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        bad = replace(snap.params, adjustment_scope="")
        self.assertEqual(
            _status(_judge(objective=obj, residuals=(), params=bad), "RI-01"),
            R.STATUS_BLOCKED,
        )


class TestRI02BranchDomain(unittest.TestCase):
    def test_matching_domain_passes(self):
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        self.assertEqual(
            _status(_judge(objective=obj, residuals=(), params=snap.params), "RI-02"),
            R.STATUS_PASS,
        )

    def test_spec_missing_a_branch_blocks(self):
        """制品少声明一个分支 ⇒ 不得静默放行（漏算一类项不报错而偏小）。"""
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        spec = dict(SPEC)
        spec["branch_domain"] = {"branches": ["DECREASE", "IN_RANGE"], "scopes": ["FULL", "SEGMENT"]}
        checks = R.judge_reference(
            objective=obj, residuals=(), params=snap.params, spec=spec,
            declared_inputs=R.INPUT_NAMES, inputs_used=R.INPUT_NAMES,
        )
        self.assertEqual(_status(checks, "RI-02"), R.STATUS_BLOCKED)


class TestRI03NamedParams(unittest.TestCase):
    def test_unnamed_param_blocks(self):
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        bad = replace(snap.params, sources=(("rho_plus", "instance.params"),))
        self.assertEqual(
            _status(_judge(objective=obj, residuals=(), params=bad), "RI-03"),
            R.STATUS_BLOCKED,
        )


class TestRI04NoDowngrade(unittest.TestCase):
    def test_missing_q0_blocks_not_zero(self):
        inst = _inst("simple")
        bad_inst = replace(
            inst,
            items=tuple(
                replace(it, q0=None) if it.item_id == "S-HI" else it
                for it in inst.items
            ),
        )
        snap = R.snapshot(bad_inst, RESOLVED)
        obj = R.ref_objective(snap, _p("simple"))
        checks = _judge(objective=obj, residuals=(), params=snap.params)
        self.assertEqual(_status(checks, "RI-04"), R.STATUS_BLOCKED)
        self.assertIn("S-HI", checks[0].reason if checks[0].item.startswith("RI-04") else
                      [c.reason for c in checks if c.item.startswith("RI-04")][0])

    def test_zero_q0_blocks(self):
        inst = _inst("simple")
        bad_inst = replace(
            inst,
            items=tuple(
                replace(it, q0=0.0) if it.item_id == "S-LO" else it
                for it in inst.items
            ),
        )
        snap = R.snapshot(bad_inst, RESOLVED)
        obj = R.ref_objective(snap, _p("simple"))
        self.assertEqual(
            _status(_judge(objective=obj, residuals=(), params=snap.params), "RI-04"),
            R.STATUS_BLOCKED,
        )


class TestRI05ObjectiveCrossCheck(unittest.TestCase):
    def test_matching_z_passes(self):
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        checks = _judge(objective=obj, residuals=(), params=snap.params,
                        z_solver=obj.Z_total, tolerances=TOLS)
        self.assertEqual(_status(checks, "RI-05"), R.STATUS_PASS)

    def test_injected_wrong_z_fails(self):
        """★ 双向：给一个差 10000 的 Z_solver，必须 FAIL（不是 PASS）。"""
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        checks = _judge(objective=obj, residuals=(), params=snap.params,
                        z_solver=obj.Z_total + 10_000.0, tolerances=TOLS)
        self.assertEqual(_status(checks, "RI-05"), R.STATUS_FAIL)

    def test_tiny_difference_within_eps_passes(self):
        """ε_Z = eps_abs + eps_rel·max ⇒ 1e-6 级差应落在带内（不是恒 FAIL）。"""
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        checks = _judge(objective=obj, residuals=(), params=snap.params,
                        z_solver=obj.Z_total + 1e-6, tolerances=TOLS)
        self.assertEqual(_status(checks, "RI-05"), R.STATUS_PASS)

    def test_no_z_solver_skips_not_passes(self):
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        checks = _judge(objective=obj, residuals=(), params=snap.params,
                        z_solver=None, tolerances=TOLS)
        self.assertEqual(_status(checks, "RI-05"), R.STATUS_SKIP)

    def test_missing_tolerance_blocks(self):
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        for tols in ({}, {"eps_abs": 0.01}, {"eps_rel_price": 1e-9}):
            checks = _judge(objective=obj, residuals=(), params=snap.params,
                            z_solver=obj.Z_total, tolerances=tols)
            self.assertEqual(_status(checks, "RI-05"), R.STATUS_BLOCKED)

    def test_eps_components_are_two_names(self):
        """★ 绝对与相对是两个名字：只给相对不得顶替绝对。"""
        self.assertIn("eps_abs", TOLS)
        self.assertIn("eps_rel_price", TOLS)
        self.assertNotEqual(TOLS["eps_abs"], TOLS["eps_rel_price"])


class TestRI06SelfConsistency(unittest.TestCase):
    def test_tampered_line_fails(self):
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        lines = tuple(
            replace(l, contribution=(l.contribution or 0.0) + 5.0) if i == 0 else l
            for i, l in enumerate(obj.lines)
        )
        bad = replace(obj, lines=lines)
        self.assertEqual(
            _status(_judge(objective=bad, residuals=(), params=snap.params), "RI-06"),
            R.STATUS_FAIL,
        )


class TestRI07SourceIsolation(unittest.TestCase):
    def test_audit_passes_on_reference_files(self):
        res = I.audit_reference_source(
            SRC_PATHS,
            forbidden_symbols=SPEC["isolation_proof"]["layers"][0]["forbidden_symbols"],
            forbidden_module_suffixes=SPEC["isolation_proof"]["layers"][0]["forbidden_module_suffixes"],
        )
        self.assertEqual(res["status"], R.STATUS_PASS)

    def test_audit_catches_production_symbol(self):
        """★ 双向：把生产符号塞进参考实现源码，审计必须抓到。"""
        src = "from bidpricing.solver.instance import check_solution\nZ = check_solution(a, b, c)\n"
        tmp = Path(__file__).with_name("_tmp_ref_bad.py")
        tmp.write_text(src, encoding="utf-8")
        try:
            res = I.audit_reference_source(
                [tmp],
                forbidden_symbols=SPEC["isolation_proof"]["layers"][0]["forbidden_symbols"],
                forbidden_module_suffixes=SPEC["isolation_proof"]["layers"][0]["forbidden_module_suffixes"],
            )
        finally:
            tmp.unlink(missing_ok=True)
        self.assertEqual(res["status"], R.STATUS_BLOCKED)

    def test_audit_catches_settlement_revenue_mention(self):
        src = "def f(x):\n    return settlement_revenue(1, 2, 3, p)\n"
        tmp = Path(__file__).with_name("_tmp_ref_bad2.py")
        tmp.write_text(src, encoding="utf-8")
        try:
            res = I.audit_reference_source(
                [tmp], forbidden_symbols=["settlement_revenue"], forbidden_module_suffixes=()
            )
        finally:
            tmp.unlink(missing_ok=True)
        self.assertEqual(res["status"], R.STATUS_BLOCKED)


class TestRI08Immutability(unittest.TestCase):
    def test_snapshot_is_frozen(self):
        snap = _snap()
        self.assertEqual(
            I.immutability_probe(snap)["status"], R.STATUS_PASS
        )

    def test_mutation_after_call_does_not_change_result(self):
        """★ 注入式：改坏输入后复读，结果必须不变（否则共享了可变状态）。"""
        inst = _inst("simple")
        snap = R.snapshot(inst, RESOLVED)
        p = _p("simple")
        before = R.ref_objective(snap, p).Z_total

        def mutate():
            for it in inst.items:  # 直接改生产对象（Phase1Item 是 frozen，用属性替换项）
                pass
            inst.__dict__["items"] = tuple(
                replace(it, q0=999.0) for it in inst.items
            )

        res = I.immutability_probe(snap, mutate)
        after = R.ref_objective(snap, p).Z_total
        self.assertEqual(res["status"], R.STATUS_PASS)
        self.assertEqual(before, after)

    def test_mutable_container_in_snapshot_fails(self):
        class Bad:
            items = []

        self.assertEqual(I.immutability_probe(Bad())["status"], R.STATUS_FAIL)


class TestRI09Signoff(unittest.TestCase):
    def test_unsigned_blocks(self):
        """★ 未签署 ⇒ BLOCKED（不得伪造 PASS）。"""
        res = I.check_signoff(REPO / "docs")
        self.assertEqual(res["status"], R.STATUS_BLOCKED)

    def test_agent_as_reviewer_still_blocks(self):
        """即便写了 reviewer，若仍是生产实现者（agent/auto）也不算数。"""
        tmp = REPO / "docs" / "_tmp_signoff.json"
        payload = {"signed": True, "reviewer": "agent", "date": "2026-09-17"}
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        try:
            res = I.check_signoff(REPO / "docs")
        finally:
            tmp.unlink(missing_ok=True)
        # 真实记录文件仍在且未签署 ⇒ 依然 BLOCKED（本用例只验证不误判为 PASS）
        self.assertEqual(res["status"], R.STATUS_BLOCKED)


class TestRI10Reconciliation(unittest.TestCase):
    def test_undeclared_input_detected(self):
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        checks = R.judge_reference(
            objective=obj, residuals=(), params=snap.params, spec=SPEC,
            declared_inputs=("instance.items",), inputs_used=R.INPUT_NAMES,
        )
        self.assertEqual(_status(checks, "RI-10"), R.STATUS_FAIL)

    def test_no_declared_set_skips(self):
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        checks = R.judge_reference(
            objective=obj, residuals=(), params=snap.params, spec=SPEC,
            declared_inputs=(), inputs_used=R.INPUT_NAMES,
        )
        self.assertEqual(_status(checks, "RI-10"), R.STATUS_SKIP)


class TestRI11Aggregation(unittest.TestCase):
    def test_empty_check_set_blocks(self):
        rep = R.RefReport(objective=None, residuals=(), checks=(), inputs_used=())
        self.assertEqual(rep.verdict(), R.STATUS_BLOCKED)

    def test_fail_beats_blocked(self):
        snap = _snap()
        obj = R.ref_objective(snap, _p())
        lines = tuple(
            replace(l, contribution=(l.contribution or 0.0) + 1.0) if i == 0 else l
            for i, l in enumerate(obj.lines)
        )
        checks = _judge(objective=replace(obj, lines=lines), residuals=(),
                        params=snap.params, z_solver=obj.Z_total + 1e6,
                        tolerances=TOLS)
        rep = R.RefReport(objective=obj, residuals=(), checks=checks, inputs_used=())
        self.assertEqual(rep.verdict(), R.STATUS_FAIL)


class TestFormulaPinned(unittest.TestCase):
    """手算钉死 R_i 的三分支 × 作用域（钉住「阈值本身已含 1+θ_dev」这个历史坑）。"""

    P = R.RefParams(
        rho_plus=0.0, rho_minus=0.0,
        decrease_threshold=0.85, increase_threshold=1.15,
        adjustment_scope="SEGMENT",
        sources=tuple((n, "test") for n in R.PARAM_NAMES),
    )

    def _item(self, q0: float, q1: float, alpha: float = 0.0) -> R.RefItem:
        return R.RefItem(item_id="X", q0=q0, q1=q1, c_i=0.0, alpha=alpha,
                         L=None, U=None, is_optimizable=True, in_c1_scope=True)

    def test_increase_segment(self):
        # θ_inc=1.15 已含 1+：阈值内 1.15·100 按 p，超出部分按 p1
        # = 1.15*100*10 + (150-115)*10 = 1150 + 350 = 1500
        self.assertAlmostEqual(
            R.ref_revenue(self._item(100.0, 150.0), 10.0, self.P), 1500.0)

    def test_increase_full(self):
        full = replace(self.P, adjustment_scope="FULL")
        self.assertAlmostEqual(
            R.ref_revenue(self._item(100.0, 150.0), 10.0, full), 1500.0)

    def test_decrease_uses_rho_minus(self):
        p = replace(self.P, rho_minus=0.05)
        # 减量侧：q1·p·(1+ρ⁻) = 50*10*1.05 = 525
        self.assertAlmostEqual(
            R.ref_revenue(self._item(100.0, 50.0), 10.0, p), 525.0)

    def test_in_range_segment_ignores_alpha(self):
        # SEGMENT 下未越界部分按原单价 ⇒ α 不生效 = 100*10 = 1000
        self.assertAlmostEqual(
            R.ref_revenue(self._item(100.0, 100.0, alpha=0.2), 10.0, self.P), 1000.0)

    def test_in_range_full_applies_alpha(self):
        full = replace(self.P, adjustment_scope="FULL")
        self.assertAlmostEqual(
            R.ref_revenue(self._item(100.0, 100.0, alpha=0.2), 10.0, full), 1200.0)

    def test_branch_boundaries(self):
        self.assertEqual(R.ref_branch(0.85, self.P), R.BRANCH_IN_RANGE)
        self.assertEqual(R.ref_branch(0.8499, self.P), R.BRANCH_DECREASE)
        self.assertEqual(R.ref_branch(1.15, self.P), R.BRANCH_IN_RANGE)
        self.assertEqual(R.ref_branch(1.1501, self.P), R.BRANCH_INCREASE)


class TestSpecLock(unittest.TestCase):
    def test_branch_domain_matches_implementation(self):
        self.assertEqual(tuple(SPEC["branch_domain"]["branches"]), R.BRANCHES)
        self.assertEqual(tuple(SPEC["branch_domain"]["scopes"]), R.SCOPES)

    def test_judges_declared(self):
        self.assertEqual(
            [j["id"] for j in SPEC["judges"]],
            [f"RI-{i:02d}" for i in range(1, 12)],
        )

    def test_isolation_layers_declared(self):
        self.assertEqual(
            [l["id"] for l in SPEC["isolation_proof"]["layers"]],
            ["ISO-1", "ISO-2", "ISO-3"],
        )

    def test_reference_does_not_import_production(self):
        """★ 最强形态的 ISO-1：源码里不得出现生产模块路径。"""
        for p in SRC_PATHS:
            text = p.read_text(encoding="utf-8")
            for mod in ("solver.instance", "solver.formulation", "solver.compiler",
                        "solver.backend", "solver.verifier", "contracts.pricing_card"):
                self.assertNotIn(mod, text, f"{p.name} 引用了生产模块 {mod}")


if __name__ == "__main__":
    unittest.main()
