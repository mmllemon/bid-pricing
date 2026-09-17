"""T04-07《MILP 独立验收协议》的判据测试（MA-01..MA-10）。

测试纪律与本仓其它判据层一致：**每条判据都要能被注入的错误值否定**。
只验证「自己的实现恰好对自己」的测试等于没测——故下面每个用例都成对：
正确值 ⇒ PASS/合理档，错误值 ⇒ FAIL/BLOCKED，且两者**档位不同**。

全程零依赖：不 import 求解器，构造的是 ``MilpFacts`` 原始量。
"""

from __future__ import annotations

import copy
import json
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from bidpricing.paths import config_dir
from bidpricing.solver import milp_acceptance as MA

SPEC_PATH = config_dir() / MA.SPEC_FILENAME


def _spec() -> dict[str, Any]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def _facts(**kw: Any) -> MA.MilpFacts:
    base = dict(
        form="MILP",
        normalized_status="OPTIMAL",
        carried_solution=True,
        variables={"z_A": 0.0, "z_B": 1.0},
        integer_symbols=("z_A", "z_B"),
        objective=460_000.0,
        diagnostics={"mip_dual_bound": -460_000.0, "mip_gap": 0.0},
        time_limit=30.0,
        timed_out=False,
        maximize=True,
        objective_constant=0.0,
    )
    base.update(kw)
    return MA.MilpFacts(**base)


def _report(facts: MA.MilpFacts, **kw: Any) -> MA.MilpReport:
    return MA.acceptance_report(facts, spec=_spec(), **kw)


def _status(report: MA.MilpReport, judge_id: str) -> str:
    check = report.of(judge_id)
    assert check is not None, f"缺判据 {judge_id}"
    return check.status


def _judge(
    facts: MA.MilpFacts, acc: MA.MilpAcceptance, **kw: Any
) -> MA.MilpReport:
    """只跑判据（不重算结论）——用于注入**错误结论**看判据抓不抓得住。"""
    return MA.MilpReport(
        acceptance=acc,
        checks=MA.judge_milp(facts, acc, spec=_spec(), **kw),
    )


class TestSpecLock(unittest.TestCase):
    """制品与实现的对账（制品漏改 ⇒ 这里先红）。"""

    def test_tolerance_names_match(self):
        declared = sorted(
            k for k, v in _spec()["tolerances"].items()
            if isinstance(v, dict) and "value" in v
        )
        self.assertEqual(declared, sorted(MA.DEFAULT_TOLERANCES))

    def test_judge_ids_are_the_declared_ten(self):
        ids = [j["id"] for j in _spec()["judges"]]
        self.assertEqual(ids, [f"MA-{i:02d}" for i in range(1, 11)])

    def test_status_domain_has_five(self):
        self.assertEqual(
            [d["id"] for d in _spec()["status_domain"]],
            ["OPTIMAL", "FEASIBLE", "UNSOLVED", "INFEASIBLE", "BLOCKED"],
        )

    def test_forbidden_bans_kkt(self):
        joined = "\n".join(_spec()["forbidden"])
        self.assertIn("KKT", joined)


class TestMA01Form(unittest.TestCase):
    def test_lp_is_skip_not_pass(self):
        """★ LP 形态下本协议不适用：必须 SKIP（「没走到」≠「已通过」）。"""
        report = _report(_facts(form="LP"))
        self.assertEqual(report.verdict(), MA.STATUS_SKIP)
        self.assertEqual(_status(report, "MA-01"), MA.STATUS_SKIP)
        self.assertIsNone(report.acceptance.accepted)

    def test_lp_is_not_reported_as_blocked(self):
        """「不适用」也不得被记成 BLOCKED——那是「算不出」，语义不同。"""
        self.assertEqual(_report(_facts(form="LP")).verdict(), MA.STATUS_SKIP)

    def test_milp_applies(self):
        self.assertEqual(_status(_report(_facts()), "MA-01"), MA.STATUS_PASS)


class TestMA02NeverUpgrade(unittest.TestCase):
    def test_optimal_from_optimal_is_pass(self):
        facts = _facts()
        acc = MA.build_acceptance(facts)
        self.assertEqual(acc.accepted, MA.ACCEPT_OPTIMAL)
        self.assertEqual(_status(_judge(facts, acc), "MA-02"), MA.STATUS_PASS)

    def test_injected_upgrade_is_caught(self):
        """★ 注入「FEASIBLE 状态却给 OPTIMAL 结论」⇒ 必须 FAIL。

        这是本协议最容易被绕过的一条：只要某处想让报告好看一点。
        """
        facts = _facts(normalized_status="FEASIBLE")
        acc = replace(
            MA.build_acceptance(facts), accepted=MA.ACCEPT_OPTIMAL,
            optimality_proven=True,
        )
        report = _judge(facts, acc)
        self.assertEqual(_status(report, "MA-02"), MA.STATUS_FAIL)

    def test_feasible_ceiling_is_respected(self):
        facts = _facts(normalized_status="FEASIBLE")
        acc = MA.build_acceptance(facts)
        self.assertEqual(acc.accepted, MA.ACCEPT_FEASIBLE)
        self.assertFalse(acc.optimality_proven)


class TestMA03IntegerFeasibility(unittest.TestCase):
    def test_binary_values_pass(self):
        self.assertEqual(_status(_report(_facts()), "MA-03"), MA.STATUS_PASS)

    def test_fractional_value_fails(self):
        facts = _facts(variables={"z_A": 0.5, "z_B": 1.0})
        report = _report(facts)
        self.assertEqual(_status(report, "MA-03"), MA.STATUS_FAIL)

    def test_missing_variable_is_blocked_not_pass(self):
        """★ 变量缺失 = 不可判（BLOCKED），不是「没找到就算通过」。"""
        facts = _facts(variables={"z_A": 0.0}, integer_symbols=("z_A", "z_B"))
        report = _report(facts)
        self.assertEqual(_status(report, "MA-03"), MA.STATUS_BLOCKED)

    def test_missing_eps_int_is_blocked(self):
        spec = _spec()
        del spec["tolerances"]["eps_int"]
        facts = _facts()
        acc = MA.build_acceptance(facts)
        checks = MA.judge_milp(facts, acc, spec=spec)
        status = next(c.status for c in checks if c.item == "MA-04")
        self.assertEqual(status, MA.STATUS_BLOCKED, "制品漏声明 eps_int ⇒ MA-04 BLOCKED")


class TestMA04NamedTolerances(unittest.TestCase):
    def test_all_three_declared_passes(self):
        self.assertEqual(_status(_report(_facts()), "MA-04"), MA.STATUS_PASS)

    def test_spec_missing_one_tolerance_blocks(self):
        spec = _spec()
        del spec["tolerances"]["eps_gap_rel"]
        facts = _facts()
        acc = MA.build_acceptance(facts)
        status = next(
            c.status for c in MA.judge_milp(facts, acc, spec=spec)
            if c.item == "MA-04"
        )
        self.assertEqual(status, MA.STATUS_BLOCKED)

    def test_undeclared_tolerance_read_by_impl_blocks(self):
        """实现多读一个制品没声明的容差 ⇒ BLOCKED（不报错但判据变严，须有信号）。"""
        facts = _facts()
        acc = MA.build_acceptance(facts)
        status = next(
            c.status for c in MA.judge_milp(
                facts, acc, spec=_spec(),
                tolerances={"eps_gap_abs": 0.01, "eps_gap_rel": 1e-8,
                            "eps_int": 1e-6, "eps_mystery": 1.0},
            ) if c.item == "MA-04"
        )
        self.assertEqual(status, MA.STATUS_BLOCKED)


class TestMA05BoundAbsent(unittest.TestCase):
    def test_bound_present_passes(self):
        self.assertEqual(_status(_report(_facts()), "MA-05"), MA.STATUS_PASS)

    def test_bound_absent_warns_and_demotes(self):
        facts = _facts(diagnostics={})
        report = _report(facts)
        self.assertEqual(_status(report, "MA-05"), MA.STATUS_WARN)
        self.assertEqual(report.acceptance.accepted, MA.ACCEPT_FEASIBLE)
        self.assertFalse(report.acceptance.optimality_proven)

    def test_bound_absent_but_claimed_optimal_fails(self):
        """★ 注入「无 bound 却标 OPTIMAL」⇒ FAIL（|Z−Z|=0 恒真的自证）。"""
        facts = _facts(diagnostics={})
        acc = replace(
            MA.build_acceptance(facts), accepted=MA.ACCEPT_OPTIMAL,
            optimality_proven=True,
        )
        self.assertEqual(_status(_judge(facts, acc), "MA-05"), MA.STATUS_FAIL)


class TestMA06CrossSourceReconciliation(unittest.TestCase):
    def test_consistent_sources_pass(self):
        self.assertEqual(_status(_report(_facts()), "MA-06"), MA.STATUS_PASS)

    def test_only_reported_gap_blocks(self):
        """只有自报间隙 = 同源自证（规则⑥）⇒ BLOCKED。"""
        facts = _facts(objective=None)
        report = _report(facts)
        self.assertEqual(_status(report, "MA-06"), MA.STATUS_BLOCKED)

    def test_inconsistent_sources_block(self):
        """自报 0.0 而复算 4.9 ⇒ BLOCKED（sense 约定失效或量纲错位）。"""
        facts = _facts(
            objective=460_000.0,
            diagnostics={"mip_dual_bound": -2_730_000.0, "mip_gap": 0.0},
            objective_constant=0.0,
        )
        report = _report(facts)
        self.assertEqual(_status(report, "MA-06"), MA.STATUS_BLOCKED)

    def test_constant_offset_fixes_the_bound(self):
        """★ 补回目标常量后两侧一致：2,730,000 + (−2,270,000) = 460,000。"""
        facts = _facts(
            objective=460_000.0,
            diagnostics={"mip_dual_bound": -2_730_000.0, "mip_gap": 0.0},
            objective_constant=-2_270_000.0,
        )
        report = _report(facts)
        self.assertAlmostEqual(report.acceptance.best_bound or 0.0, 460_000.0, places=6)
        self.assertEqual(_status(report, "MA-06"), MA.STATUS_PASS)
        self.assertEqual(report.acceptance.accepted, MA.ACCEPT_OPTIMAL)


class TestMA07Timeout(unittest.TestCase):
    def test_missing_time_limit_blocks(self):
        facts = _facts(time_limit=None)
        self.assertEqual(_status(_report(facts), "MA-07"), MA.STATUS_BLOCKED)

    def test_timeout_with_incumbent_is_feasible(self):
        facts = _facts(timed_out=True, carried_solution=True)
        report = _report(facts)
        self.assertEqual(report.acceptance.accepted, MA.ACCEPT_FEASIBLE)
        self.assertFalse(report.acceptance.optimality_proven)
        self.assertEqual(_status(report, "MA-07"), MA.STATUS_PASS)

    def test_timeout_without_incumbent_is_unsolved(self):
        facts = _facts(timed_out=True, carried_solution=False)
        self.assertEqual(_report(facts).acceptance.accepted, MA.ACCEPT_UNSOLVED)

    def test_injected_infeasible_on_timeout_fails(self):
        """★ 把「没算出解」写成 INFEASIBLE ⇒ FAIL（对拍器会以为真的不可行）。"""
        facts = _facts(timed_out=True, carried_solution=False)
        acc = replace(
            MA.build_acceptance(facts), accepted=MA.ACCEPT_INFEASIBLE,
        )
        self.assertEqual(_status(_judge(facts, acc), "MA-07"), MA.STATUS_FAIL)


class TestMA08OptimalityProven(unittest.TestCase):
    def test_consistent_pair_passes(self):
        self.assertEqual(_status(_report(_facts()), "MA-08"), MA.STATUS_PASS)

    def test_proven_true_on_demoted_conclusion_fails(self):
        facts = _facts(diagnostics={})
        acc = replace(MA.build_acceptance(facts), optimality_proven=True)
        self.assertEqual(_status(_judge(facts, acc), "MA-08"), MA.STATUS_FAIL)


class TestMA09StatusDomain(unittest.TestCase):
    def test_known_status_passes(self):
        self.assertEqual(_status(_report(_facts()), "MA-09"), MA.STATUS_PASS)

    def test_unknown_status_blocks(self):
        facts = _facts(normalized_status="AMBIGUOUS")
        report = _report(facts)
        self.assertEqual(_status(report, "MA-09"), MA.STATUS_BLOCKED)
        self.assertEqual(report.acceptance.accepted, MA.ACCEPT_BLOCKED)

    def test_infeasible_is_carried_through(self):
        facts = _facts(normalized_status="INFEASIBLE", carried_solution=False)
        self.assertEqual(_report(facts).acceptance.accepted, MA.ACCEPT_INFEASIBLE)


class TestMA10Aggregation(unittest.TestCase):
    def test_empty_check_set_is_blocked(self):
        """空判据集 ⇒ BLOCKED（「什么都没判」不得显示绿）。"""
        self.assertEqual(MA.MilpReport(acceptance=MA.build_acceptance(_facts()),
                                       checks=()).verdict(), MA.STATUS_BLOCKED)

    def test_fail_dominates(self):
        facts = _facts(variables={"z_A": 0.5, "z_B": 1.0})
        self.assertEqual(_report(facts).verdict(), MA.STATUS_FAIL)

    def test_blocked_dominates_warn(self):
        facts = _facts(diagnostics={})
        self.assertEqual(_report(facts).verdict(), MA.STATUS_BLOCKED)


class _FakeStatus:
    normalized = "OPTIMAL"


class _FakeResult:
    status = _FakeStatus()
    variables = {"z_A": 1.0}
    recomputed_objective = 460_000.0
    reported_objective = 460_000.0
    solved = True
    diagnostics = {"mip_dual_bound": -460_000.0}


class _FakeVar:
    def __init__(self, symbol: str, kind: str) -> None:
        self.symbol = symbol
        self.kind = kind


class _FakeModel:
    solver_form = "MILP"
    objective_sense = "MAXIMIZE"
    objective_constant = -1_000.0
    variables = (_FakeVar("z_A", "BINARY"), _FakeVar("p_A", "CONTINUOUS"))

    def binary_symbols(self):
        return ("z_A",)


class TestFactsTranslation(unittest.TestCase):
    """facts_from_result 只做翻译：把对象上的原始量抄成数字。"""

    def test_translation_picks_raw_quantities(self):
        f = MA.facts_from_result(_FakeResult(), _FakeModel(), time_limit=10.0)
        self.assertEqual(f.form, "MILP")
        self.assertEqual(f.normalized_status, "OPTIMAL")
        self.assertTrue(f.maximize)
        self.assertEqual(f.objective_constant, -1_000.0)
        self.assertEqual(f.integer_symbols, ("z_A",))
        self.assertEqual(f.objective, 460_000.0)

    def test_bound_uses_constant_offset(self):
        f = MA.facts_from_result(_FakeResult(), _FakeModel())
        acc = MA.build_acceptance(f)
        self.assertAlmostEqual(acc.best_bound or 0.0, 459_000.0, places=6)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
