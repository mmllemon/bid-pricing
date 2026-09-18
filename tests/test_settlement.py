"""T03-01《结算规则引擎》的区分性测试（SR-01..SR-09）。

测试纪律（与仓内其它判据层同源）：

1. **每条判据都要能被注入的错误值否定**。只对正确实现放行的判据没有否定能力——
   故除「正确引擎全绿」外，下面还构造了三类**坏引擎**（边界写反 / 覆盖不生效 /
   未注册 id 默认取 2024），验证判据确实 FAIL。
2. **零第三方依赖**：只用 stdlib unittest 与仓内模块。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bidpricing.contracts.pricing_card import (  # noqa: E402
    PricingCardError,
    load_pricing_card,
    resolve_parameters,
)
from bidpricing.contracts.rule_sets import (  # noqa: E402
    BRANCH_DECREASE,
    BRANCH_IN_RANGE,
    BRANCH_INCREASE,
    GB50500_2013_RuleSet,
    GBT50500_2024_RuleSet,
)
from bidpricing.paths import config_dir  # noqa: E402
from bidpricing.settlement import (  # noqa: E402
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    ContractContext,
    SettlementRule,
    judge_settlement,
    load_settlement_spec,
    registry_from_spec,
)

Q0 = 1000.0
P0 = 100.0


def _ctx(rule_id="GB/T50500-2024", scope="SEGMENT", **overrides):
    return ContractContext(
        rule_set_id=rule_id, adjustment_scope=scope, overrides=overrides,
    )


class TestBranches(unittest.TestCase):
    """三段 + 边界归属（路线 §5.2 J2：触发条件是严格不等式）。"""

    def setUp(self):
        self.eng = SettlementRule()

    def _branch(self, r, **kw):
        return self.eng.evaluate(Q0, Q0 * r, P0, _ctx(**kw)).rule_branch

    def test_three_branches(self):
        self.assertEqual(self._branch(0.5), BRANCH_DECREASE)
        self.assertEqual(self._branch(1.0), BRANCH_IN_RANGE)
        self.assertEqual(self._branch(1.3), BRANCH_INCREASE)

    def test_boundaries_are_inclusive_of_in_range(self):
        # J2：0.85 与 1.15 恰好「不触发」调价
        self.assertEqual(self._branch(0.85), BRANCH_IN_RANGE)
        self.assertEqual(self._branch(1.15), BRANCH_IN_RANGE)

    def test_boundaries_two_sided(self):
        self.assertEqual(self._branch(0.85 - 1e-6), BRANCH_DECREASE)
        self.assertEqual(self._branch(0.85 + 1e-6), BRANCH_IN_RANGE)
        self.assertEqual(self._branch(1.15 - 1e-6), BRANCH_IN_RANGE)
        self.assertEqual(self._branch(1.15 + 1e-6), BRANCH_INCREASE)

    def test_six_hand_computed_cases(self):
        # rho=0 时金额与 P1 可手算；覆盖三段 × 两版
        for rule_id in ("GB50500-2013", "GB/T50500-2024"):
            with self.subTest(rule=rule_id):
                # 减量：Q1·P0·(1+ρ⁻)，ρ⁻=0 ⇒ 500·100 = 50000
                o = self.eng.evaluate(Q0, 500.0, P0, _ctx(rule_id))
                self.assertEqual(o.settlement_amount, 50_000.0)
                # 区间内：Q1·P0 = 110000
                o = self.eng.evaluate(Q0, 1100.0, P0, _ctx(rule_id))
                self.assertEqual(o.settlement_amount, 110_000.0)
                # 增量 SEGMENT：1.15·1000·100 + (1300−1150)·100 = 130000
                o = self.eng.evaluate(Q0, 1300.0, P0, _ctx(rule_id))
                self.assertAlmostEqual(o.settlement_amount, 130_000.0)

    def test_rho_effect_by_branch(self):
        # ρ>0：增量调低、减量调高，方向不得颠倒
        inc = self.eng.evaluate(Q0, 1300.0, P0, _ctx(rho_plus=0.05))
        dec = self.eng.evaluate(Q0, 500.0, P0, _ctx(rho_minus=0.05))
        self.assertAlmostEqual(
            inc.settlement_amount,
            1.15 * Q0 * P0 + (1300.0 - 1150.0) * P0 * 0.95)
        self.assertAlmostEqual(dec.settlement_amount, 500.0 * P0 * 1.05)


class TestRuleSetDispatch(unittest.TestCase):
    """rule_set_id 分发 + p1_source + 作用域合法性。"""

    def setUp(self):
        self.eng = SettlementRule()

    def test_unregistered_id_blocked_and_not_backfilled(self):
        out = self.eng.evaluate(Q0, 1200.0, P0, _ctx("GB50500-9999"))
        self.assertEqual(out.status, STATUS_BLOCKED)
        self.assertEqual(out.rule_id, "GB50500-9999")   # 不回填成默认值
        self.assertIsNone(out.settlement_amount)
        self.assertIn("未注册", out.blocked_reason)

    def test_rule_id_echoed_for_registered(self):
        for rid in ("GB50500-2013", "GB/T50500-2024"):
            with self.subTest(rule=rid):
                self.assertEqual(
                    self.eng.evaluate(Q0, 1200.0, P0, _ctx(rid)).rule_id, rid)

    def test_p1_source_differs_between_versions(self):
        a = self.eng.evaluate(Q0, 1300.0, P0, _ctx("GB50500-2013"))
        b = self.eng.evaluate(Q0, 1300.0, P0, _ctx("GB/T50500-2024"))
        self.assertEqual(a.p1_source, "REDETERMINE")
        self.assertEqual(b.p1_source, "ADJUST_ON_CONTRACT_PRICE")
        self.assertNotEqual(a.p1_source, b.p1_source)

    def test_p1_source_triple_consistency(self):
        spec = load_settlement_spec()
        reg = registry_from_spec(spec)
        for rid, impl in (("GB50500-2013", GB50500_2013_RuleSet()),
                          ("GB/T50500-2024", GBT50500_2024_RuleSet())):
            with self.subTest(rule=rid):
                self.assertEqual(reg[rid]["p1_source"], impl.p1_source)
                self.assertEqual(
                    self.eng.evaluate(Q0, 1300.0, P0, _ctx(rid)).p1_source,
                    impl.p1_source)

    def test_2013_full_scope_blocked(self):
        out = self.eng.evaluate(Q0, 1300.0, P0, _ctx("GB50500-2013", "FULL"))
        self.assertEqual(out.status, STATUS_BLOCKED)
        self.assertIn("adjustment_scope", out.blocked_reason)

    def test_2024_unfrozen_scope_blocked(self):
        # 卡片存在但作用域未落值、上下文也未给 ⇒ 未冻结（不得默认取任一侧）
        card = {
            "parameters": {"rho_plus": 0.0, "rho_minus": 0.0,
                           "increase_threshold": 1.15,
                           "decrease_threshold": 0.85},
            "adjustment_scope": None,
        }
        eng = SettlementRule(card=card, spec=load_settlement_spec())
        out = eng.evaluate(Q0, 1300.0, P0,
                           ContractContext(rule_set_id="GB/T50500-2024"))
        self.assertEqual(out.status, STATUS_BLOCKED)
        self.assertIn("adjustment_scope", out.blocked_reason)

    def test_2024_full_differs_from_segment(self):
        seg = self.eng.evaluate(Q0, 1300.0, P0, _ctx(scope="SEGMENT",
                                                     rho_plus=0.05))
        full = self.eng.evaluate(Q0, 1300.0, P0, _ctx(scope="FULL",
                                                      rho_plus=0.05))
        self.assertAlmostEqual(seg.settlement_amount,
                               1.15 * Q0 * P0 + 150.0 * P0 * 0.95)
        self.assertAlmostEqual(full.settlement_amount, 1300.0 * P0 * 0.95)


class TestOverrides(unittest.TestCase):
    """覆盖链：合同层覆盖标准阈值必须生效；未登记键必须 BLOCKED。"""

    def setUp(self):
        self.eng = SettlementRule()

    def test_contract_threshold_override_moves_boundary(self):
        in_range = self.eng.evaluate(Q0, 1100.0, P0, _ctx(rho_plus=0.05))
        overridden = self.eng.evaluate(
            Q0, 1100.0, P0,
            _ctx(rho_plus=0.05, increase_threshold=1.05))
        self.assertEqual(in_range.rule_branch, BRANCH_IN_RANGE)
        self.assertEqual(overridden.rule_branch, BRANCH_INCREASE)
        self.assertNotEqual(in_range.settlement_amount,
                            overridden.settlement_amount)
        self.assertAlmostEqual(overridden.settlement_amount,
                               1.05 * Q0 * P0 + 50.0 * P0 * 0.95)
        self.assertEqual(overridden.parameters["sources"]["increase_threshold"],
                         "contract")

    def test_decrease_threshold_override_moves_boundary(self):
        base = self.eng.evaluate(Q0, 900.0, P0, _ctx())
        self.assertEqual(base.rule_branch, BRANCH_IN_RANGE)
        ovr = self.eng.evaluate(Q0, 900.0, P0, _ctx(decrease_threshold=0.95))
        self.assertEqual(ovr.rule_branch, BRANCH_DECREASE)

    def test_unknown_override_key_blocked(self):
        out = self.eng.evaluate(Q0, 1300.0, P0, _ctx(threshold=1.05))
        self.assertEqual(out.status, STATUS_BLOCKED)
        self.assertIn("未登记", out.blocked_reason)

    def test_none_valued_override_ignored(self):
        out = self.eng.evaluate(Q0, 1300.0, P0, _ctx(increase_threshold=None))
        self.assertEqual(out.status, STATUS_PASS)
        self.assertEqual(out.parameters["increase_threshold"], 1.15)

    def test_standard_label_cannot_deviate(self):
        ctx = ContractContext(rule_set_id="GB/T50500-2024",
                              adjustment_scope="SEGMENT",
                              source_label="pricing_rule_card",
                              overrides={"increase_threshold": 1.05})
        out = self.eng.evaluate(Q0, 1300.0, P0, ctx)
        self.assertEqual(out.status, STATUS_BLOCKED)
        self.assertIn("Standard 层", out.blocked_reason)


class TestUndetermined(unittest.TestCase):
    """未定态一律 BLOCKED 且不产出金额（§8.4）。"""

    def setUp(self):
        self.eng = SettlementRule()

    def test_four_undetermined_cases(self):
        cases = {
            "Q0 缺失": (None, 1200.0, P0),
            "Q1 缺失": (Q0, None, P0),
            "P0 缺失": (Q0, 1200.0, None),
            "Q0=0": (0.0, 1200.0, P0),
        }
        for name, args in cases.items():
            with self.subTest(case=name):
                out = self.eng.evaluate(*args, _ctx())
                self.assertEqual(out.status, STATUS_BLOCKED)
                self.assertIsNone(out.settlement_amount)
                self.assertIsNone(out.effective_price)


class TestOutputAntiConflation(unittest.TestCase):
    """SR-08：settlement_amount / effective_price / adjusted_unit_price 三量分列。"""

    def setUp(self):
        self.eng = SettlementRule()

    def test_segment_increase_effective_price_differs_from_p1(self):
        out = self.eng.evaluate(Q0, 1300.0, P0, _ctx(rho_plus=0.05))
        self.assertAlmostEqual(out.adjusted_unit_price, 95.0)
        self.assertAlmostEqual(out.settlement_amount, 129_250.0)
        self.assertAlmostEqual(out.effective_price, 129_250.0 / 1300.0)
        self.assertGreater(abs(out.effective_price - out.adjusted_unit_price),
                           1e-6)

    def test_full_increase_effective_price_equals_p1(self):
        out = self.eng.evaluate(Q0, 1300.0, P0, _ctx(scope="FULL",
                                                     rho_plus=0.05))
        self.assertAlmostEqual(out.effective_price, out.adjusted_unit_price)

    def test_in_range_and_decrease_equal(self):
        for r in (1.0, 0.5):
            with self.subTest(r=r):
                out = self.eng.evaluate(Q0, Q0 * r, P0,
                                        _ctx(rho_minus=0.05))
                self.assertAlmostEqual(out.effective_price,
                                       out.adjusted_unit_price)


class _BadBoundaryEngine(SettlementRule):
    """坏引擎 ①：把 1.15/0.85 边界判成触发调价（<= 写成 < 的反向错误）。"""

    def evaluate(self, q0, q1, p0, context=None):
        out = super().evaluate(q0, q1, p0, context)
        if out.status == STATUS_PASS and out.r in (0.85, 1.15):
            from dataclasses import replace

            branch = (BRANCH_DECREASE if out.r == 0.85 else BRANCH_INCREASE)
            return replace(out, rule_branch=branch)
        return out


class _NoOverrideEngine(SettlementRule):
    """坏引擎 ②：覆盖只记参数，判定仍走常量（阈值覆盖不生效）。"""

    def _resolve(self, entry, impl, ctx):
        import copy

        ctx2 = ContractContext(
            rule_set_id=ctx.rule_set_id,
            overrides={k: v for k, v in dict(ctx.overrides or {}).items()
                       if k not in ("increase_threshold",
                                    "decrease_threshold")},
            source_label=ctx.source_label,
            adjustment_scope=ctx.adjustment_scope,
        )
        return super()._resolve(entry, impl, ctx2)


class _DefaultingEngine(SettlementRule):
    """坏引擎 ③：未注册 rule_set_id 落兜底到 2024 版（selector 的 else 兜底被复制）。"""

    def evaluate(self, q0, q1, p0, context=None):
        ctx = context or ContractContext(rule_set_id="")
        if ctx.rule_set_id not in self.registry:
            ctx = ContractContext(
                rule_set_id="GB/T50500-2024",
                overrides=ctx.overrides,
                source_label=ctx.source_label,
                adjustment_scope=ctx.adjustment_scope or "SEGMENT",
            )
        return super().evaluate(q0, q1, p0, ctx)


class TestJudgeFalsifiability(unittest.TestCase):
    """判据的否定能力：坏引擎必须被判 FAIL。"""

    def _report(self, factory):
        return judge_settlement(engine_factory=factory)

    def test_correct_engine_all_pass(self):
        rep = self._report(lambda: SettlementRule())
        self.assertEqual(rep.verdict(), STATUS_PASS, [
            (v.judge_id, v.status, v.detail) for v in rep.verdicts])

    def test_boundary_inverted_is_caught(self):
        rep = self._report(lambda: _BadBoundaryEngine())
        self.assertEqual(rep.of("SR-02").status, STATUS_FAIL)

    def test_override_ineffective_is_caught(self):
        rep = self._report(lambda: _NoOverrideEngine())
        self.assertEqual(rep.of("SR-05").status, STATUS_FAIL)

    def test_silent_default_rule_set_is_caught(self):
        rep = self._report(lambda: _DefaultingEngine())
        self.assertEqual(rep.of("SR-03").status, STATUS_FAIL)

    def test_skip_does_not_beat_pass(self):
        from bidpricing.settlement import STATUS_SKIP, SettlementReport, \
            SettlementVerdict
        rep = SettlementReport(verdicts=(
            SettlementVerdict("X-1", STATUS_PASS),
            SettlementVerdict("X-2", STATUS_SKIP),
        ))
        self.assertEqual(rep.verdict(), STATUS_PASS)

    def test_empty_verdicts_blocked(self):
        from bidpricing.settlement import SettlementReport
        self.assertEqual(SettlementReport().verdict(), STATUS_BLOCKED)


class TestPricingCardLayering(unittest.TestCase):
    """规则卡分层互锁（T03-01 修正）：Standard 层声明仍受常量约束，
    合同/招标层覆盖允许偏离并记录来源。"""

    def setUp(self):
        self.card = load_pricing_card(config_dir())

    def test_card_declaration_deviating_from_constant_is_blocked(self):
        import copy

        card = copy.deepcopy(self.card)
        card["parameters"]["increase_threshold"] = 1.20
        with self.assertRaises(PricingCardError) as ctx:
            resolve_parameters(card)
        self.assertIn("两处说法", str(ctx.exception))

    def test_contract_layer_override_allowed_and_recorded(self):
        params = resolve_parameters(
            self.card, {"increase_threshold": 1.05},
            source_label="contract")
        self.assertEqual(params.increase_threshold, 1.05)
        self.assertEqual(params.sources["increase_threshold"], "contract")
        # 未被覆盖的键仍来自标准层
        self.assertEqual(params.decrease_threshold, 0.85)
        self.assertEqual(params.sources["decrease_threshold"],
                         "pricing_rule_card")

    def test_standard_layer_label_cannot_deviate(self):
        with self.assertRaises(PricingCardError) as ctx:
            resolve_parameters(self.card, {"decrease_threshold": 0.90},
                               source_label="pricing_rule_card")
        self.assertIn("Standard 层", str(ctx.exception))

    def test_unknown_key_still_blocked(self):
        with self.assertRaises(PricingCardError):
            resolve_parameters(self.card, {"whatever": 1})


class TestSpecConsistency(unittest.TestCase):
    """制品与实现不得两处说法。"""

    def test_registry_matches_implementations(self):
        spec = load_settlement_spec()
        reg = registry_from_spec(spec)
        self.assertEqual(set(reg), {"GB50500-2013", "GB/T50500-2024"})
        for rid, impl in (("GB50500-2013", GB50500_2013_RuleSet()),
                          ("GB/T50500-2024", GBT50500_2024_RuleSet())):
            with self.subTest(rule=rid):
                e = reg[rid]
                self.assertEqual(e["standard_code"], impl.standard_code)
                self.assertEqual(tuple(e["supported_scopes"]),
                                 tuple(impl.supported_scopes))
                self.assertEqual(bool(e["scope_ambiguous"]),
                                 impl.scope_ambiguous)
                self.assertEqual(float(e["increase_threshold"]), 1.15)
                self.assertEqual(float(e["decrease_threshold"]), 0.85)

    def test_spec_judges_are_judged(self):
        # 制品声明的判据集必须与判定器实际输出的判据集一致（覆盖面不得漏项）
        spec = load_settlement_spec()
        declared = [j["judge_id"] for j in spec["judges"]]
        rep = judge_settlement(SettlementRule())
        self.assertEqual(declared, [v.judge_id for v in rep.verdicts])

    def test_probe_grid_is_fixed_in_spec(self):
        spec = load_settlement_spec()
        grid = spec["probe_grid"]
        self.assertGreaterEqual(len(grid["r_values"]), 7)
        self.assertEqual(len(grid["boundary_pairs"]), 2)
        self.assertEqual(grid["rule_sets"], ["GB50500-2013", "GB/T50500-2024"])

    def test_override_keys_align_with_card(self):
        spec = load_settlement_spec()
        card = load_pricing_card(config_dir())
        self.assertEqual(
            sorted(spec["override_policy"]["registered_keys"]),
            sorted(card["override_policy"]["registered_overrides"]))


if __name__ == "__main__":
    unittest.main()
