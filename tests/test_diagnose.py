"""T03-06 不可行诊断——区分性测试。

每条判据都必须「能被错误的值否定」：注入错误冲突集 ⇒ FAIL；缺输入 ⇒ BLOCKED；
语义分列（INFEASIBLE / UNKNOWN / BLOCKED）各有一枚钉子。
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bidpricing.contracts.pricing_card import ResolvedParameters  # noqa: E402
from bidpricing.solver.diagnose import (  # noqa: E402
    FEASIBLE,
    INFEASIBLE,
    UNKNOWN,
    DiagnosisEntry,
    DiagnosisReport,
    StructuralConflict,
    deletion_filter,
    detect_structural_conflicts,
    diagnose,
    judge_diagnosis,
    load_diagnosis_spec,
    load_toggleable_ids,
    phase1_oracle,
)
from bidpricing.solver.instance import Phase1Instance, Phase1Item  # noqa: E402
from bidpricing.solver.phase1 import phase1_simple_probe_instance  # noqa: E402

# ---------------------------------------------------------------------------
# 手算夹具：A/B 两可优化项，数值可复算。
#   A: q0=1000, L=350, U=600, c=400, p0=500
#   B: q0=500,  L=250, U=450, c=300, p0=400
#   P_min = 350×1000 + 250×500 = 475000
#   P_max = 600×1000 + 450×500 = 825000
# ---------------------------------------------------------------------------


def base_items() -> tuple[Phase1Item, ...]:
    return (
        Phase1Item(item_id="A", q0=1000.0, q1_point=900.0, c_i=400.0, p0=500.0,
                   cap=600.0, L=350.0, U=600.0),
        Phase1Item(item_id="B", q0=500.0, q1_point=500.0, c_i=300.0, p0=400.0,
                   cap=450.0, L=250.0, U=450.0),
    )


def base_instance(*, B=700_000.0, items=None, active=()) -> Phase1Instance:
    return Phase1Instance(
        items=items if items is not None else base_items(),
        B=B, P_star=800_000.0,
        active_soft_constraints=tuple(active),
    )


_RESOLVED = ResolvedParameters(
    rho_plus=0.0, rho_minus=0.0,
    increase_threshold=1.15, decrease_threshold=0.85,
    adjustment_scope="SEGMENT", sources={"test": "test_diagnose"},
)
_SPEC = load_diagnosis_spec()
_TOGGLE = load_toggleable_ids()


def run_diagnose(inst, **kw):
    return diagnose(inst, _RESOLVED, spec=_SPEC, toggleable=_TOGGLE, **kw)


# ---------------------------------------------------------------------------
# Pass A：结构冲突
# ---------------------------------------------------------------------------


class TestStructural(unittest.TestCase):
    def test_healthy_instance_no_conflict(self):
        self.assertEqual(detect_structural_conflicts(base_instance()), ())

    def test_box_conflict_amount(self):
        # A 的下界 350 > 上界 300 ⇒ 缺口 50；B=500k 避开上界侧冲突
        # （P_min=475000 ≤ 500000 ≤ P_max=300×1000+450×500=525000）
        a = Phase1Item(item_id="A", q0=1000.0, q1_point=900.0, c_i=400.0, p0=500.0,
                       cap=300.0, L=350.0, U=300.0)
        b = base_items()[1]
        scs = detect_structural_conflicts(base_instance(B=500_000.0, items=(a, b)))
        self.assertEqual(len(scs), 1)
        self.assertEqual(scs[0].knob_id, "C2-CAP")
        self.assertEqual(scs[0].constraint_id, "C2")
        self.assertAlmostEqual(scs[0].amount, 50.0)

    def test_floor_conflict_counts_as_box(self):
        # floor_A = 500 > U_A = 450 ⇒ 同一箱通道（merged_lower 唯一实现）
        # B=650k：含地板 P_min=625000 ≤ 650000 ≤ P_max=675000，只剩箱冲突
        a = Phase1Item(item_id="A", q0=1000.0, q1_point=900.0, c_i=400.0, p0=500.0,
                       cap=450.0, L=350.0, U=450.0)
        b = base_items()[1]
        scs = detect_structural_conflicts(
            base_instance(B=650_000.0, items=(a, b)), floor_by_id={"A": 500.0}
        )
        self.assertEqual([s.knob_id for s in scs], ["C2-CAP"])
        self.assertAlmostEqual(scs[0].amount, 50.0)

    def test_total_floor_above_B(self):
        # P_min = 475000 > B = 400000 ⇒ 缺口 75000
        scs = detect_structural_conflicts(base_instance(B=400_000.0))
        by_knob = {s.knob_id: s for s in scs}
        self.assertIn("C1-B", by_knob)
        self.assertEqual(by_knob["C1-B"].constraint_id, "C1")
        self.assertAlmostEqual(by_knob["C1-B"].amount, 75_000.0)
        self.assertIn("上调 B", by_knob["C1-B"].suggested_relaxation)

    def test_total_cap_below_B(self):
        # P_max = 825000 < B = 900000 ⇒ 缺口 75000（上界侧，DG-02 穷举）
        scs = detect_structural_conflicts(base_instance(B=900_000.0))
        by_knob = {s.knob_id: s for s in scs}
        self.assertIn("C2-CAP", by_knob)
        self.assertAlmostEqual(by_knob["C2-CAP"].amount, 75_000.0)

    def test_empty_cap_suppresses_upper_side(self):
        # A 空 cap（U=None）⇒ 上界侧不可判，B>P_max 型冲突不报（∞ 兜底）
        a = Phase1Item(item_id="A", q0=1000.0, c_i=400.0, p0=500.0,
                       cap=None, L=350.0, U=None)
        b = base_items()[1]
        self.assertEqual(detect_structural_conflicts(base_instance(B=900_000.0, items=(a, b))), ())


# ---------------------------------------------------------------------------
# 预言机三态
# ---------------------------------------------------------------------------


class TestOracle(unittest.TestCase):
    def setUp(self):
        self.oracle = phase1_oracle(_RESOLVED)

    def test_feasible(self):
        self.assertEqual(self.oracle(base_instance()), FEASIBLE)

    def test_proven_infeasible_low_B(self):
        # EC-7 FAIL（B < P_min）——solve_phase1 对它返回 BLOCKED，
        # 预言机必须穿透为 INFEASIBLE（已证空域）。
        self.assertEqual(self.oracle(base_instance(B=400_000.0)), INFEASIBLE)

    def test_proven_infeasible_box_inversion(self):
        a = Phase1Item(item_id="A", q0=1000.0, q1_point=900.0, c_i=400.0, p0=500.0,
                       cap=300.0, L=350.0, U=300.0)
        self.assertEqual(
            self.oracle(base_instance(items=(a, base_items()[1]))), INFEASIBLE)

    def test_B_missing_is_UNKNOWN_not_INFEASIBLE(self):
        # EC-7 BLOCKED（B 缺失）是未定态——不得当成「B 定得太低」（ADR-0004）。
        self.assertEqual(self.oracle(base_instance(B=None)), UNKNOWN)

    def test_soft_active_is_UNKNOWN(self):
        # EC-6 FAIL（C9 激活）= 适用域外，可行性未知。
        self.assertEqual(
            self.oracle(base_instance(active=("C9",))), UNKNOWN)


# ---------------------------------------------------------------------------
# Pass B：删除过滤器
# ---------------------------------------------------------------------------


class TestDeletionFilter(unittest.TestCase):
    def test_single_conflict_found(self):
        sets, note = deletion_filter(
            base_instance(active=("C9",)),
            phase1_oracle(_RESOLVED),
            toggleable=_TOGGLE,
        )
        self.assertEqual(sets, [("C9",)])

    def test_pair_conflict_found(self):
        # C6 与 C9 单关都剩另一条（仍 BLOCKED）⇒ 成对关才可行（§6.3 互斥场景）
        sets, note = deletion_filter(
            base_instance(active=("C6", "C9")),
            phase1_oracle(_RESOLVED),
            toggleable=_TOGGLE,
        )
        self.assertEqual(sets, [("C6", "C9")])

    def test_minimality_suppresses_superset(self):
        # 注入预言机：C9 关掉即 FEASIBLE ⇒ 只报 {C9}，不得再报超集
        def orc(inst):
            return FEASIBLE if "C9" not in inst.active_soft_constraints else UNKNOWN

        sets, _ = deletion_filter(
            base_instance(active=("C6", "C9")), orc, toggleable=_TOGGLE
        )
        self.assertEqual(sets, [("C9",)])

    def test_all_unknown_reports_no_set(self):
        def orc(inst):
            return UNKNOWN

        sets, note = deletion_filter(
            base_instance(active=("C9",)), orc, toggleable=_TOGGLE
        )
        self.assertEqual(sets, [])
        self.assertIn("NO_CONFLICT_SET", note)

    def test_deterministic_order(self):
        # 两次运行冲突集顺序必须一致（frozenset 迭代序不定 ⇒ 内部排序）
        inst = base_instance(active=("C9", "C6", "C11"))
        s1, _ = deletion_filter(inst, phase1_oracle(_RESOLVED), toggleable=_TOGGLE)
        s2, _ = deletion_filter(inst, phase1_oracle(_RESOLVED), toggleable=_TOGGLE)
        self.assertEqual(s1, s2)


# ---------------------------------------------------------------------------
# 判定器可注入性（judge 只吃报告与原始量）
# ---------------------------------------------------------------------------


def _report(**over) -> DiagnosisReport:
    d = dict(
        baseline=INFEASIBLE,
        structural_conflicts=(),
        entries=(),
        verdicts=(),
        overall="PASS",
        min_conflict_sets=(),
    )
    d.update(over)
    return DiagnosisReport(**d)


class TestJudgeInjectability(unittest.TestCase):
    def test_minimality_catches_superset(self):
        rep = _report(min_conflict_sets=(("C6", "C9"), ("C9",)))
        verdicts = judge_diagnosis(rep, spec=_SPEC, toggleable=_TOGGLE)
        self.assertEqual(dict((j, s) for j, s, _ in verdicts)["DG-03"], "FAIL")

    def test_minimality_passes_on_correct(self):
        rep = _report(min_conflict_sets=(("C6",), ("C9",)))
        verdicts = judge_diagnosis(rep, spec=_SPEC, toggleable=_TOGGLE)
        self.assertEqual(dict((j, s) for j, s, _ in verdicts)["DG-03"], "PASS")

    def test_missing_suggestion_fails(self):
        rep = _report(entries=(
            DiagnosisEntry("C9", True, ("C9",), None),
        ))
        verdicts = judge_diagnosis(rep, spec=_SPEC, toggleable=_TOGGLE)
        self.assertEqual(dict((j, s) for j, s, _ in verdicts)["DG-04"], "FAIL")

    def test_non_toggleable_knob_fails(self):
        rep = _report(min_conflict_sets=(("C1",),))  # C1 硬约束不得进过滤器
        verdicts = judge_diagnosis(rep, spec=_SPEC, toggleable=_TOGGLE)
        self.assertEqual(dict((j, s) for j, s, _ in verdicts)["DG-05"], "FAIL")

    def test_amountless_structural_suggestion_fails(self):
        rep = _report(structural_conflicts=(
            StructuralConflict("C1-B", "C1", "d", "重新考虑商业条件", amount=None),
        ))
        verdicts = judge_diagnosis(rep, spec=_SPEC, toggleable=_TOGGLE)
        self.assertEqual(dict((j, s) for j, s, _ in verdicts)["DG-06"], "FAIL")

    def test_undecidable_baseline_blocked(self):
        rep = _report(baseline=UNKNOWN)
        verdicts = judge_diagnosis(rep, spec=_SPEC, toggleable=_TOGGLE)
        self.assertEqual(dict((j, s) for j, s, _ in verdicts)["DG-01"], "BLOCKED")

    def test_out_of_domain_baseline_fails(self):
        rep = _report(baseline="MAYBE")
        verdicts = judge_diagnosis(rep, spec=_SPEC, toggleable=_TOGGLE)
        self.assertEqual(dict((j, s) for j, s, _ in verdicts)["DG-08"], "FAIL")

    def test_empty_judge_set_blocked(self):
        verdicts = judge_diagnosis(_report(), spec={"judges": []}, toggleable=_TOGGLE)
        self.assertEqual(verdicts[0][1], "BLOCKED")


# ---------------------------------------------------------------------------
# 端到端编排
# ---------------------------------------------------------------------------


class TestDiagnoseEndToEnd(unittest.TestCase):
    def test_feasible_passes_without_fabricated_conflicts(self):
        rep = run_diagnose(base_instance())
        self.assertEqual(rep.baseline, FEASIBLE)
        self.assertEqual(rep.overall, "PASS")
        self.assertEqual(rep.entries, ())

    def test_low_B_diagnosed_with_quantified_suggestion(self):
        rep = run_diagnose(base_instance(B=400_000.0))
        self.assertEqual(rep.baseline, INFEASIBLE)
        entries = [e for e in rep.entries if e.constraint_id == "C1"]
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].blocking)
        self.assertIn("475000.00", entries[0].suggested_relaxation)

    def test_soft_C9_mapped_to_action_catalog(self):
        rep = run_diagnose(base_instance(active=("C9",)))
        self.assertEqual(rep.min_conflict_sets, (("C9",),))
        entry = next(e for e in rep.entries if e.constraint_id == "C9")
        self.assertIn("GIVE_UP_OR_REESTIMATE", entry.suggested_relaxation)
        self.assertIn("删除过滤器近似", entry.suggested_relaxation)

    def test_C6_C9_pair_gets_approval_action(self):
        rep = run_diagnose(base_instance(active=("C6", "C9")))
        self.assertEqual(rep.min_conflict_sets, (("C6", "C9"),))
        entry = next(e for e in rep.entries if e.constraint_id == "C6")
        self.assertIn("APPROVAL_THETA", entry.suggested_relaxation)

    def test_all_unknown_overall_blocked(self):
        # B 缺失 ⇒ 预言机 UNKNOWN、无结构冲突、无旋钮可关 ⇒ 不可判定 BLOCKED
        rep = run_diagnose(base_instance(B=None))
        self.assertEqual(rep.baseline, UNKNOWN)
        self.assertEqual(rep.overall, "BLOCKED")

    def test_probe_instance_still_feasible(self):
        # 回归锚：simple 探针在真实 resolved 参数下必须仍可行
        from bidpricing.contracts.pricing_card import load_pricing_card, resolve_parameters
        from bidpricing.paths import config_dir

        card = load_pricing_card(config_dir())
        rep = diagnose(
            phase1_simple_probe_instance(), resolve_parameters(card),
            spec=_SPEC, toggleable=_TOGGLE,
        )
        self.assertEqual(rep.baseline, FEASIBLE)
        self.assertEqual(rep.overall, "PASS")


if __name__ == "__main__":
    unittest.main()
