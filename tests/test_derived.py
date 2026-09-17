"""T03-02 派生量计算的区分度测试。

★ 每条判据都必须能被**两个方向**验证：

1. **正确的值不被误杀**——判据太紧会把正常实现报成违规（规则⑧：能被错误的值
   否定，与不能被正确的值否定，是同一要求的两个方向）；
2. **错误的值必被抓住**——判据没有区分力就等于没判。

实现方式刻意分两类：
* 计算期判据（DQ-01/01b/02/03b/04）用**不同的输入**驱动；
* 判定期判据（DQ-03/05/06/07/08/09/10）用**直接构造的 DerivedItem** 驱动——
  ``judge_derived`` 只吃派生量序列，所以坏数据可以被注入。

参数一律用**合成的** ``ResolvedParameters``，不读项目实时状态：否则断言会随
项目落值翻转（例如 μ 一旦落值，今天写死的 BLOCKED 断言明天就绿了）。
"""

from __future__ import annotations

import unittest

from bidpricing.contracts.pricing_card import ResolvedParameters, compute_r_eff
from bidpricing.derived import (
    LOSS_ACCEPT,
    LOSS_DECLINE,
    SCOPE,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    DerivedItem,
    DerivedReport,
    audit_derived_source,
    compute_derived,
    judge_derived,
    load_derived_spec,
)
from bidpricing.paths import config_dir
from bidpricing.solver.instance import Phase1Instance

ROLE_OPT = "OPTIMIZABLE"
ROLE_PT = "PASS_THROUGH"

_KEYS = (
    "rho_plus",
    "rho_minus",
    "increase_threshold",
    "decrease_threshold",
    "adjustment_scope",
)


def _resolved(
    scope: str = "SEGMENT",
    rho_plus: float = 0.8,
    rho_minus: float = 0.5,
    theta: float = 0.15,
) -> ResolvedParameters:
    """合成参数——**不读项目实时状态**，避免断言随落值翻转。"""
    return ResolvedParameters(
        rho_plus=rho_plus,
        rho_minus=rho_minus,
        increase_threshold=1.0 + theta,
        decrease_threshold=1.0 - theta,
        adjustment_scope=scope,
        sources={k: "test" for k in _KEYS},
    )


def _row(
    item_id: str,
    *,
    cap: float | None = 500.0,
    c_i: float | None = 400.0,
    L: float | None = None,
    U: float | None = None,
    q0: float | None = 1000.0,
    q1: float | None = 1000.0,
    role: str = ROLE_OPT,
    alpha: float = 0.0,
) -> dict:
    d = {
        "item_id": item_id,
        "role": role,
        "q0": q0,
        "q1_point": q1,
        "c_i": c_i,
        "alpha": alpha,
    }
    if cap is not None:
        d["cap"] = cap
    if L is not None:
        d["L"] = L
    if U is not None:
        d["U"] = U
    return d


def _inst(rows, *, B: float = 2550000.0, P_star: float = 3000000.0) -> Phase1Instance:
    return Phase1Instance.from_dict(
        {
            "items": rows,
            "B": B,
            "P_star": P_star,
            "params": {"adjustment_scope": "SEGMENT"},
            "synthetic_note": "t03-02-test",
        },
        source="test",
    )


def _spec():
    return load_derived_spec(config_dir())


def _run(rows=None, **kw):
    rows = rows if rows is not None else [_row("A")]
    return compute_derived(_inst(rows), _resolved(), spec=_spec(), **kw)


def _status(checks, needle: str) -> list[str]:
    return [c.status for c in checks if needle in c.item]


# ---------------------------------------------------------------------------
# DQ-01：就绪性（声明式，不判行数）
# ---------------------------------------------------------------------------


class TestDQ01Readiness(unittest.TestCase):
    def test_mu_missing_blocks(self):
        r = _run(mu=None, unbalanced={"enabled": False})
        self.assertEqual(STATUS_BLOCKED, r.verdict())
        self.assertIn(STATUS_BLOCKED, _status(r.checks, "DQ-01 μ"))

    def test_mu_zero_is_a_legal_value_not_missing(self):
        """★ 反方向：μ=0 是「不允许任何亏损」这一**合法取值**，不得当成未声明。"""
        r = _run(mu=0.0, unbalanced={"enabled": False})
        self.assertNotEqual(STATUS_BLOCKED, r.verdict())
        self.assertIn(STATUS_PASS, _status(r.checks, "DQ-01 μ"))
        self.assertTrue(r.mu_declared)

    def test_mu_missing_yields_no_floor_at_all(self):
        r = _run(unbalanced={"enabled": False})
        self.assertEqual({}, r.floor_by_id())
        for it in r.items:
            self.assertIsNone(it.floor)

    def test_loss_acceptance_missing_falls_back_to_strict(self):
        r = _run(mu=0.1, loss_acceptance=None, unbalanced={"enabled": False})
        self.assertEqual(LOSS_DECLINE, r.loss_acceptance)
        self.assertFalse(r.loss_acceptance_declared)
        self.assertIn(STATUS_WARN, _status(r.checks, "DQ-01b"))

    def test_loss_acceptance_declared_passes(self):
        r = _run(mu=0.1, loss_acceptance=LOSS_ACCEPT, unbalanced={"enabled": False})
        self.assertIn(STATUS_PASS, _status(r.checks, "DQ-01b"))


# ---------------------------------------------------------------------------
# DQ-02：c_i 的就绪性与零值语义
# ---------------------------------------------------------------------------


class TestDQ02Cost(unittest.TestCase):
    def test_optimizable_with_zero_cost_blocks(self):
        r = _run([_row("A", c_i=0.0)], mu=0.1, unbalanced={"enabled": False})
        self.assertIn(STATUS_BLOCKED, _status(r.checks, "DQ-02"))
        self.assertIsNone(r.of("A").floor)

    def test_pass_through_with_zero_cost_does_not_block(self):
        """反方向：PASS_THROUGH 不经 C4，c_i=0 合法。"""
        r = _run(
            [_row("A", c_i=0.0, role=ROLE_PT)], mu=0.1, unbalanced={"enabled": False}
        )
        self.assertNotIn(STATUS_BLOCKED, _status(r.checks, "DQ-02"))

    def test_missing_cost_yields_no_floor(self):
        r = _run([_row("A", c_i=None)], mu=0.1, unbalanced={"enabled": False})
        self.assertIsNone(r.of("A").floor)


# ---------------------------------------------------------------------------
# DQ-03：空 cap 的语义
# ---------------------------------------------------------------------------


class TestDQ03NullCap(unittest.TestCase):
    def test_null_cap_yields_none_not_zero(self):
        r = _run([_row("A", cap=None, c_i=100.0)], mu=0.1, unbalanced={"enabled": False})
        self.assertIsNone(r.of("A").U)
        self.assertEqual({}, r.upper_by_id())  # 不限价项刻意缺席，不折 0

    def test_cap_present_equals_U(self):
        r = _run([_row("A", cap=500.0)], mu=0.1, unbalanced={"enabled": False})
        self.assertEqual(500.0, r.of("A").U)
        self.assertEqual({"A": 500.0}, r.upper_by_id())

    def test_injected_null_cap_folded_to_zero_is_caught(self):
        """★ 注入：空 cap 却给出 U —— 会凭空造上界，把可行解判成不可行。"""
        bad = (DerivedItem("X", L=0.0, U=0.0, floor=None, r_eff=1.0, cap=None),)
        st = [c.status for c in judge_derived(bad, audit={"ok": True})]
        self.assertIn(STATUS_FAIL, st)

    def test_instance_U_disagreeing_with_cap_is_caught(self):
        """跨来源对账：实例 U 与 cap 是同一物理量的两个来源，分叉即有一侧错。"""
        r = _run([_row("A", cap=500.0, U=777.0)], mu=0.1, unbalanced={"enabled": False})
        self.assertIn(STATUS_FAIL, _status(r.checks, "DQ-03b"))

    def test_agreeing_U_does_not_trip_the_check(self):
        r = _run([_row("A", cap=500.0, U=500.0)], mu=0.1, unbalanced={"enabled": False})
        self.assertNotIn(STATUS_FAIL, _status(r.checks, "DQ-03b"))


# ---------------------------------------------------------------------------
# DQ-04：L_i 的多来源取大 / 不编造 δ⁻
# ---------------------------------------------------------------------------


class TestDQ04LowerBound(unittest.TestCase):
    def test_clause_block_absent_blocks(self):
        r = _run(mu=0.1, unbalanced=None)
        self.assertIn(STATUS_BLOCKED, _status(r.checks, "DQ-04"))

    def test_clause_enabled_key_missing_blocks(self):
        """沉默不是断言：缺少 enabled 这个标量 key ⇒ BLOCKED（ADR-0007）。"""
        r = _run(mu=0.1, unbalanced={"reference": "CAP", "tol_lo": 0.5})
        self.assertIn(STATUS_BLOCKED, _status(r.checks, "DQ-04"))

    def test_clause_disabled_gives_zero_L(self):
        """enabled=false 是**合法结论**（已核查无该条款），不是「未实现」。"""
        r = _run([_row("A", L=300.0)], mu=0.1, unbalanced={"enabled": False})
        self.assertEqual(300.0, r.of("A").L)
        self.assertIn(STATUS_PASS, _status(r.checks, "DQ-04"))

    def test_clause_cap_reference_gives_cap_times_tol(self):
        r = _run(
            [_row("A", cap=500.0, L=0.0)],
            mu=0.1,
            loss_acceptance=LOSS_ACCEPT,
            unbalanced={"enabled": True, "reference": "CAP", "tol_lo": 0.5},
        )
        self.assertEqual(250.0, r.of("A").L)

    def test_L_takes_max_of_sources(self):
        """★ 多来源**取大**：条款给 250、实例给 300 ⇒ L=300（不是覆盖、不是取小）。"""
        r = _run(
            [_row("A", cap=500.0, L=300.0)],
            mu=0.1,
            loss_acceptance=LOSS_ACCEPT,
            unbalanced={"enabled": True, "reference": "CAP", "tol_lo": 0.5},
        )
        self.assertEqual(300.0, r.of("A").L)
        self.assertTrue(any("max(" in s for s in r.of("A").reasons))

    def test_clause_without_tolerance_blocks(self):
        """禁用默认值：阈值没有招标依据时不得编造。"""
        r = _run(
            mu=0.1,
            unbalanced={"enabled": True, "reference": "CAP"},
        )
        self.assertIn(STATUS_BLOCKED, _status(r.checks, "DQ-04"))

    def test_clause_with_null_cap_warns_not_blocks(self):
        """★ 三档治理：条款有基准缺项 ⇒ WARN（可解释性），不 BLOCKED、也不取 0 冒充。"""
        r = _run(
            [_row("A", cap=None, c_i=100.0, L=50.0)],
            mu=0.1,
            loss_acceptance=LOSS_ACCEPT,
            unbalanced={"enabled": True, "reference": "CAP", "tol_lo": 0.5},
        )
        self.assertIn(STATUS_WARN, _status(r.checks, "DQ-04 L_i"))
        self.assertNotIn(STATUS_BLOCKED, _status(r.checks, "DQ-04 L_i"))
        self.assertEqual(50.0, r.of("A").L)  # 只按其它来源计


# ---------------------------------------------------------------------------
# DQ-05：ACCEPT 钳制（含最易静默出错的一处）
# ---------------------------------------------------------------------------


class TestDQ05Clamp(unittest.TestCase):
    def test_accept_clamps_floor_to_cap(self):
        r = _run(
            [_row("A", cap=500.0, c_i=600.0, L=0.0)],
            mu=0.1,
            loss_acceptance=LOSS_ACCEPT,
            unbalanced={"enabled": False},
        )
        # max(0, 600·0.9) = 540 ⇒ ACCEPT 钳到 500
        self.assertEqual(500.0, r.of("A").floor)

    def test_accept_does_not_clamp_when_cap_is_null(self):
        """★★ 最关键的一条：cap 空 ⇒ **不得**钳制。

        把空 cap 当 0 会把地板静默压到 0——地板失效、且不报错。
        """
        r = _run(
            [_row("A", cap=None, c_i=100.0, L=50.0)],
            mu=0.1,
            loss_acceptance=LOSS_ACCEPT,
            unbalanced={"enabled": False},
        )
        self.assertEqual(90.0, r.of("A").floor)  # max(50, 100·0.9)，**不是 0**
        self.assertNotEqual(0.0, r.of("A").floor)

    def test_decline_keeps_strict_floor(self):
        r = _run(
            [_row("A", cap=500.0, c_i=450.0, L=0.0)],
            mu=0.1,
            loss_acceptance=LOSS_DECLINE,
            unbalanced={"enabled": False},
        )
        self.assertEqual(405.0, r.of("A").floor)  # 不钳

    def test_injected_clamp_failure_is_caught(self):
        bad = (DerivedItem("X", L=0.0, U=500.0, floor=600.0, r_eff=1.0, cap=500.0),)
        st = [c.status for c in judge_derived(bad, loss_acceptance=LOSS_ACCEPT)]
        self.assertIn(STATUS_FAIL, st)

    def test_correct_clamp_is_not_flagged(self):
        """反方向：钳制正确的项不得被误杀。"""
        good = (DerivedItem("X", L=0.0, U=500.0, floor=500.0, r_eff=1.0, cap=500.0),)
        st = [c.status for c in judge_derived(good, loss_acceptance=LOSS_ACCEPT)]
        self.assertNotIn(STATUS_FAIL, st)


# ---------------------------------------------------------------------------
# DQ-06：结构性不变量 floor >= L
# ---------------------------------------------------------------------------


class TestDQ06Invariant(unittest.TestCase):
    def test_floor_never_below_L(self):
        r = _run([_row("A", cap=900.0, c_i=100.0, L=300.0)], mu=0.1,
                 unbalanced={"enabled": False})
        self.assertGreaterEqual(r.of("A").floor, r.of("A").L)

    def test_injected_floor_below_L_is_caught(self):
        bad = (DerivedItem("X", L=300.0, U=900.0, floor=100.0, r_eff=1.0, cap=900.0),)
        st = [c.status for c in judge_derived(bad, audit={"ok": True})]
        self.assertIn(STATUS_FAIL, st)


# ---------------------------------------------------------------------------
# DQ-07：逐条原始阈值的箱型可行性
# ---------------------------------------------------------------------------


class TestDQ07Feasibility(unittest.TestCase):
    def test_L_above_U_fails(self):
        r = _run([_row("A", cap=200.0, c_i=100.0, L=300.0)], mu=0.1,
                 unbalanced={"enabled": False})
        self.assertEqual(STATUS_FAIL, r.verdict())
        self.assertIn(STATUS_FAIL, _status(r.checks, "DQ-07"))

    def test_decline_floor_above_cap_fails(self):
        r = _run([_row("A", cap=500.0, c_i=600.0, L=0.0)], mu=0.1,
                 loss_acceptance=LOSS_DECLINE, unbalanced={"enabled": False})
        self.assertIn(STATUS_FAIL, _status(r.checks, "DQ-07"))

    def test_accept_with_cost_above_cap_does_not_fail(self):
        """反方向：同一输入在 ACCEPT 下地板被钳到 cap ⇒ 可行，不得误杀。"""
        r = _run([_row("A", cap=500.0, c_i=600.0, L=0.0)], mu=0.1,
                 loss_acceptance=LOSS_ACCEPT, unbalanced={"enabled": False})
        self.assertNotIn(STATUS_FAIL, _status(r.checks, "DQ-07"))

    def test_boundary_equality_is_not_a_violation(self):
        r = _run([_row("A", cap=500.0, c_i=500.0, L=0.0)], mu=0.0,
                 loss_acceptance=LOSS_ACCEPT, unbalanced={"enabled": False})
        self.assertNotIn(STATUS_FAIL, _status(r.checks, "DQ-07"))


# ---------------------------------------------------------------------------
# DQ-08：r_eff 的委派性（静态审计 + 数值等价）
# ---------------------------------------------------------------------------


class TestDQ08Delegation(unittest.TestCase):
    def test_r_eff_equals_pricing_card_implementation(self):
        """数值层面证明是委派：与唯一实现 compute_r_eff 逐项一致。"""
        r = _run([_row("A", q0=1000.0, q1=1400.0)], mu=0.1,
                 unbalanced={"enabled": False})
        expected = compute_r_eff(1.4, _resolved(), 0.0)
        self.assertAlmostEqual(expected, r.of("A").r_eff, places=12)

    def test_audit_passes_on_this_module(self):
        self.assertTrue(audit_derived_source(path=__file__.replace(
            "tests\\test_derived.py", "src\\bidpricing\\derived.py").replace(
            "tests/test_derived.py", "src/bidpricing/derived.py"))["ok"])

    def test_audit_catches_settlement_revenue(self):
        """★ 注入：本模块若调用 settlement_revenue，等于自造 dR/dp。"""
        src = "from x import settlement_revenue\ndef f():\n    return settlement_revenue(1)\n"
        audit = audit_derived_source(src)
        self.assertFalse(audit["ok"])
        self.assertIn("settlement_revenue", audit["forbidden_calls"])

    def test_audit_ignores_docstring_mentions(self):
        """反方向：只在文档字符串里提到符号，不算违规。"""
        src = '"""This module must not call settlement_revenue directly."""\nx = 1\n'
        self.assertTrue(audit_derived_source(src)["ok"])

    def test_r_eff_none_when_q0_zero(self):
        r = _run([_row("A", q0=0.0)], mu=0.1, unbalanced={"enabled": False})
        self.assertIsNone(r.of("A").r_eff)


# ---------------------------------------------------------------------------
# DQ-09：未定态不得降级为默认值
# ---------------------------------------------------------------------------


class TestDQ09Undefined(unittest.TestCase):
    def test_missing_mu_yields_none_floor(self):
        r = _run(mu=None, unbalanced={"enabled": False})
        self.assertTrue(all(it.floor is None for it in r.items))

    def test_no_default_values_leak(self):
        r = _run([_row("A", c_i=None)], mu=0.1, unbalanced={"enabled": False})
        self.assertIsNone(r.of("A").floor)
        self.assertEqual({}, r.floor_by_id())

    def test_injected_leak_when_mu_undeclared_is_caught(self):
        """★ 注入：μ 未声明却产出了 floor ⇒ 默认值泄漏。"""
        bad = (DerivedItem("X", L=0.0, U=500.0, floor=100.0, r_eff=1.0, cap=500.0),)
        st = [c.status for c in judge_derived(bad, mu_declared=False)]
        self.assertIn(STATUS_FAIL, st)

    def test_declared_mu_does_not_trigger_the_leak_check(self):
        good = (DerivedItem("X", L=0.0, U=500.0, floor=100.0, r_eff=1.0, cap=500.0),)
        st = [c.status for c in judge_derived(good, mu_declared=True, audit={"ok": True})]
        self.assertNotIn(STATUS_FAIL, st)


# ---------------------------------------------------------------------------
# DQ-10：制品声明 vs 实现实际的输入集对账
# ---------------------------------------------------------------------------


class TestDQ10Reconciliation(unittest.TestCase):
    def test_declared_inputs_match_implementation(self):
        from bidpricing.derived import _declared_inputs

        self.assertEqual(
            {"L", "c_i", "mu"}, set(_declared_inputs(_spec(), "floor_i"))
        )

    def test_sample_present_passes(self):
        r = _run(mu=0.1, unbalanced={"enabled": False})
        self.assertIn(STATUS_PASS, _status(r.checks, "DQ-10"))

    def test_no_sample_skips_not_fails(self):
        """★ 反方向（原先是判据过紧的 bug）：上游全 BLOCKED ⇒ 无样本 ⇒ SKIP。

        「没走到」不等于「已成立」，但也**不等于「已违反」**。
        """
        r = _run(mu=None, unbalanced={"enabled": False})
        self.assertIn(STATUS_SKIP, _status(r.checks, "DQ-10"))
        self.assertNotIn(STATUS_FAIL, _status(r.checks, "DQ-10"))

    def test_missing_input_detected(self):
        """注入：实现漏读 mu（只读 L、c_i）⇒ 对账必须判出。"""
        partial = (
            DerivedItem("X", L=0.0, U=500.0, floor=100.0, r_eff=1.0, cap=500.0,
                        inputs_used=frozenset({"L", "c_i"})),
        )
        st = [c.status for c in judge_derived(
            partial, declared_inputs=frozenset({"L", "c_i", "mu"}), audit={"ok": True}
        ) if "DQ-10" in c.item]
        self.assertEqual([STATUS_FAIL], st)

    def test_no_spec_warns_not_passes(self):
        r = compute_derived(_inst([_row("A")]), _resolved(), mu=0.1,
                            unbalanced={"enabled": False}, spec=None)
        self.assertIn(STATUS_WARN, _status(r.checks, "DQ-10"))


# ---------------------------------------------------------------------------
# DQ-11：判定聚合
# ---------------------------------------------------------------------------


class TestDQ11Aggregation(unittest.TestCase):
    def test_empty_checks_blocked(self):
        """「没判过」不得记成 PASS。"""
        empty = DerivedReport((), (), LOSS_DECLINE, True, None, True)
        self.assertEqual(STATUS_BLOCKED, empty.verdict())

    def test_fail_beats_blocked(self):
        rep = DerivedReport((), (
            _chk(STATUS_BLOCKED), _chk(STATUS_FAIL), _chk(STATUS_WARN),
        ), LOSS_DECLINE, True, None, True)
        self.assertEqual(STATUS_FAIL, rep.verdict())

    def test_blocked_beats_warn(self):
        rep = DerivedReport((), (
            _chk(STATUS_WARN), _chk(STATUS_BLOCKED),
        ), LOSS_DECLINE, True, None, True)
        self.assertEqual(STATUS_BLOCKED, rep.verdict())

    def test_skip_beats_pass(self):
        rep = DerivedReport((), (_chk(STATUS_SKIP), _chk(STATUS_PASS)),
                            LOSS_DECLINE, True, None, True)
        self.assertEqual(STATUS_SKIP, rep.verdict())


def _chk(status: str):
    from bidpricing.derived import DerivedCheck

    return DerivedCheck(SCOPE, "synthetic", status, "test")


# ---------------------------------------------------------------------------
# 制品锁定
# ---------------------------------------------------------------------------


class TestSpecLock(unittest.TestCase):
    def test_spec_task_id(self):
        self.assertEqual("T03-02", _spec()["task"])

    def test_spec_declares_all_judges(self):
        ids = {j["id"] for j in _spec()["judges"]}
        for i in range(1, 12):
            self.assertIn(f"DQ-{i:02d}", ids)

    def test_spec_declares_the_sv07_handoff(self):
        """SV-07（floor）的 owner 是 T03-02 —— 交接条目必须在制品里可查。"""
        consumers = {c["task"] for c in _spec()["consumers"]}
        self.assertIn("T04-02D", consumers)
        self.assertIn("T04-01", consumers)

    def test_spec_declares_the_four_derived_quantities(self):
        syms = {d["symbol"] for d in _spec()["derived_quantities"]}
        self.assertEqual({"L_i", "U_i", "floor_i", "r_eff_i"}, syms)

    def test_spec_r_eff_points_at_the_unique_implementation(self):
        dq = {d["symbol"]: d for d in _spec()["derived_quantities"]}
        self.assertIn("compute_r_eff", dq["r_eff_i"]["unique_implementation"])

    def test_spec_records_the_clamp_caveat(self):
        dq = {d["symbol"]: d for d in _spec()["derived_quantities"]}
        self.assertIn("cap 为空时不得钳制", dq["floor_i"]["clamp_rule"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
