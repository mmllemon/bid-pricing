"""H-002 成本含税 → 有效成本转换声明（CT-*）测试。

主线：**进项税率/抵扣模式缺失 = BLOCKED（阻断『最优利润』结论）**——
这是 H-002 的验收标准，与 AS-01 的 INFO 降级（台账不是关卡）不同：
这里缺的是**算式前提**，缺了利润就**算错**，不是「说不清出处」。
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bidpricing.validation.cost_basis import (
    CREDIT_MODE_VOCABULARY,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    build_effective_costs,
    check_cost_input_tax,
    effective_cost,
    effective_cost_multiplier,
    effective_cost_multiplier_from_composition,
    validate_cost_composition,
)
from bidpricing.quote_resolve import run_resolve

CONFIG = Path(__file__).resolve().parents[1] / "config"


def _policy(**mut) -> dict:
    sec = {
        "mode": "UNKNOWN",
        "cost_input_vat_rate": None,
        "input_vat_credit_mode": "UNKNOWN",
        "credit_ratio": None,
    }
    sec.update(mut)
    return {"cost_input_tax_policy": sec}


class MultiplierTest(unittest.TestCase):
    def test_full_is_incl_over_one_plus_rate(self):
        k = effective_cost_multiplier(0.09, "FULL")
        self.assertAlmostEqual(k, 1.0 / 1.09)

    def test_none_keeps_incl_cost_without_rate(self):
        # NONE 不需要税率：含税即有效成本
        self.assertEqual(effective_cost_multiplier(None, "NONE"), 1.0)

    def test_partial_uses_credit_ratio(self):
        k = effective_cost_multiplier(0.09, "PARTIAL", 0.5)
        self.assertAlmostEqual(k, 1.0 - 0.09 * 0.5 / 1.09)

    def test_unknown_returns_none(self):
        self.assertIsNone(effective_cost_multiplier(None, "UNKNOWN"))

    def test_invalid_mode_is_program_error(self):
        with self.assertRaises(ValueError):
            effective_cost_multiplier(0.09, "HALF")

    def test_missing_rate_or_ratio_returns_none(self):
        self.assertIsNone(effective_cost_multiplier(None, "FULL"))
        self.assertIsNone(effective_cost_multiplier(0.09, "PARTIAL"))

    def test_effective_cost_rounds_to_cents(self):
        self.assertAlmostEqual(effective_cost(109.0, 0.09, "FULL"), 100.0)
        self.assertIsNone(effective_cost(None, 0.09, "FULL"))
        self.assertIsNone(effective_cost(109.0, 0.09, "PARTIAL"))  # 比例缺失


class RealRepoTest(unittest.TestCase):
    def test_undeclared_blocks_profit_conclusion(self):
        """未声明（UNKNOWN）进项税率/抵扣模式 → CT-03 BLOCKED（H-002）。"""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        (tmp / "project_quote_policy.json").write_text(
            json.dumps(_policy(mode="UNKNOWN", input_vat_credit_mode="UNKNOWN",
                              cost_input_vat_rate=None, credit_ratio=None),
                       ensure_ascii=False), encoding="utf-8")
        rep = check_cost_input_tax(tmp)
        self.assertEqual(rep.by_rule("CT-03").status, STATUS_BLOCKED)
        self.assertIn("H-002", rep.by_rule("CT-03").detail)
        self.assertEqual(rep.status, "BLOCKED")
        self.assertTrue(rep.blocking)

    def test_mechanism_passes_and_pending_is_skip_not_fail(self):
        # 真实仓库现已声明成本构成（PARTIAL + cost_composition）⇒ 全部 PASS
        rep = check_cost_input_tax(CONFIG)
        self.assertEqual(rep.by_rule("CT-01").status, STATUS_PASS)
        self.assertEqual(rep.by_rule("CT-02").status, STATUS_PASS)
        self.assertEqual(rep.by_rule("CT-03").status, STATUS_PASS)
        self.assertEqual(rep.by_rule("CT-04").status, STATUS_PASS)
        self.assertEqual(rep.by_rule("CT-05").status, STATUS_PASS)
        self.assertEqual(rep.status, "PASS")
        self.assertFalse(rep.blocking)


class SyntheticCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cdir = Path(self.tmp.name)
        self._write()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, **mut):
        (self.cdir / "project_quote_policy.json").write_text(
            json.dumps(_policy(**mut), ensure_ascii=False), encoding="utf-8")

    def test_full_declared_passes(self):
        self._write(mode="FULL", cost_input_vat_rate=0.09,
                    input_vat_credit_mode="FULL")
        rep = check_cost_input_tax(self.cdir)
        self.assertEqual(rep.status, "PASS")
        self.assertEqual(rep.blocking, [])

    def test_full_missing_rate_blocks(self):
        self._write(mode="FULL", input_vat_credit_mode="FULL")
        rep = check_cost_input_tax(self.cdir)
        self.assertEqual(rep.by_rule("CT-02").status, STATUS_BLOCKED)
        self.assertEqual(rep.by_rule("CT-05").status, STATUS_BLOCKED)

    def test_partial_missing_ratio_blocks(self):
        self._write(mode="PARTIAL", cost_input_vat_rate=0.09,
                    input_vat_credit_mode="PARTIAL")
        self.assertEqual(check_cost_input_tax(self.cdir)
                         .by_rule("CT-04").status, STATUS_BLOCKED)

    def test_none_mode_no_rate_required(self):
        self._write(mode="NONE", input_vat_credit_mode="NONE")
        rep = check_cost_input_tax(self.cdir)
        self.assertEqual(rep.status, "PASS")

    def test_rate_out_of_range_is_fail(self):
        self._write(mode="FULL", cost_input_vat_rate=1.5,
                    input_vat_credit_mode="FULL")
        self.assertEqual(check_cost_input_tax(self.cdir)
                         .by_rule("CT-02").status, STATUS_FAIL)

    def test_mode_out_of_vocabulary_is_fail(self):
        self._write(mode="FULL", cost_input_vat_rate=0.09,
                    input_vat_credit_mode="HALF")
        self.assertEqual(check_cost_input_tax(self.cdir)
                         .by_rule("CT-03").status, STATUS_FAIL)

    def test_missing_policy_skips(self):
        (self.cdir / "project_quote_policy.json").unlink()
        rep = check_cost_input_tax(self.cdir)
        self.assertEqual(rep.by_rule("CT-01").status, STATUS_SKIP)


# ======================================================================
# G. 成本构成分解（分项多税率精算）— 选项 C
# ======================================================================
DEFAULT_COMPOSITION = [
    {"key": "material", "label": "材料", "proportion": 0.40, "input_vat_rate": 0.13},
    {"key": "equipment", "label": "设备", "proportion": 0.22, "input_vat_rate": 0.13},
    {"key": "subcontract", "label": "分包", "proportion": 0.10, "input_vat_rate": 0.09},
    {"key": "labor", "label": "人工", "proportion": 0.23, "input_vat_rate": 0.00},
    {"key": "measure", "label": "措施费", "proportion": 0.05, "input_vat_rate": 0.09},
]
# 手算：k = 1 - Σ p_j·r_j/(1+r_j)
_HAND_K = 1.0 - (
    0.40 * 0.13 / 1.13 + 0.22 * 0.13 / 1.13
    + 0.10 * 0.09 / 1.09 + 0.05 * 0.09 / 1.09)


class CompositionExactnessTest(unittest.TestCase):
    def test_multiplier_equals_hand_calc(self):
        k = effective_cost_multiplier_from_composition(DEFAULT_COMPOSITION)
        self.assertIsNotNone(k)
        self.assertAlmostEqual(k, _HAND_K, places=12)

    def test_zero_rate_component_contributes_nothing(self):
        # 把人工(0.23, r=0)拆成 人工(0.10,r=0)+其他人工(0.13,r=0)，k 不变
        # ⇒ 进项税率为 0 的构成不贡献任何抵扣（公式正确性）
        split = [dict(c) for c in DEFAULT_COMPOSITION if c["key"] != "labor"]
        split.append({"key": "labor", "label": "人工", "proportion": 0.10, "input_vat_rate": 0.00})
        split.append({"key": "labor2", "label": "人工2", "proportion": 0.13, "input_vat_rate": 0.00})
        k_split = effective_cost_multiplier_from_composition(split)
        self.assertAlmostEqual(k_split, _HAND_K, places=12)

    def test_derived_credit_ratio_is_vatable_proportion(self):
        ok, cr, _ = validate_cost_composition(DEFAULT_COMPOSITION)
        self.assertTrue(ok)
        # 可抵扣占比 = 含正税率构成之和 = 0.40+0.22+0.10+0.05 = 0.77
        self.assertAlmostEqual(cr, 0.77, places=6)

    def test_composition_strictly_more_accurate_than_blended(self):
        # 旧单税率（全 13%）会把 9% 的分包/措施高估抵扣 ⇒ k 更小（有效成本更低）。
        # 分项精算的 k 必须 > 旧 blended(0.13, ratio=0.77) 的 k。
        k_comp = effective_cost_multiplier_from_composition(DEFAULT_COMPOSITION)
        k_blended = effective_cost_multiplier(0.13, "PARTIAL", 0.77)
        self.assertGreater(k_comp, k_blended)


class CompositionValidationTest(unittest.TestCase):
    def test_valid(self):
        ok, cr, detail = validate_cost_composition(DEFAULT_COMPOSITION)
        self.assertTrue(ok)
        self.assertEqual(detail, "")

    def test_sum_not_one_blocks(self):
        bad = [dict(c, proportion=c["proportion"] * 0.9) for c in DEFAULT_COMPOSITION]
        ok, _, detail = validate_cost_composition(bad)
        self.assertFalse(ok)
        self.assertIn("1.00", detail)

    def test_rate_out_of_range_blocks(self):
        bad = [dict(c) for c in DEFAULT_COMPOSITION]
        bad[0]["input_vat_rate"] = 1.5
        ok, _, detail = validate_cost_composition(bad)
        self.assertFalse(ok)
        self.assertIn("进项税率", detail)

    def test_missing_field_blocks(self):
        bad = [dict(c) for c in DEFAULT_COMPOSITION]
        bad[0].pop("proportion")
        ok, _, detail = validate_cost_composition(bad)
        self.assertFalse(ok)

    def test_empty_is_false_not_none(self):
        ok, cr, _ = validate_cost_composition(None)
        self.assertFalse(ok)
        self.assertIsNone(cr)


class BuildEffectiveCostsCompositionTest(unittest.TestCase):
    ROWS = [{"item_id": "A", "c_i": 113.0, "q0": 10.0, "q1_point": 10.0}]

    def test_pass_with_composition(self):
        plan = build_effective_costs(
            self.ROWS,
            policy_section={"input_vat_credit_mode": "PARTIAL",
                            "cost_composition": DEFAULT_COMPOSITION})
        self.assertEqual(plan.status, "PASS")
        self.assertAlmostEqual(plan.multiplier, _HAND_K, places=12)
        by_id = {r["item_id"]: r for r in plan.items}
        self.assertAlmostEqual(by_id["A"]["c_i"], 113.0 * _HAND_K, places=2)
        self.assertEqual(by_id["A"]["cost_unit_price_input"], 113.0)

    def test_invalid_composition_blocks(self):
        bad = [dict(c, proportion=c["proportion"] * 0.9) for c in DEFAULT_COMPOSITION]
        plan = build_effective_costs(
            self.ROWS,
            policy_section={"input_vat_credit_mode": "PARTIAL",
                            "cost_composition": bad})
        self.assertTrue(plan.blocking)
        self.assertIn("成本构成", plan.reason)

    def test_composition_overrides_legacy_credit_ratio(self):
        # 同时给构成与旧 credit_ratio=0.5 ⇒ 构成优先，k 取分项值而非 0.5 混合值
        plan = build_effective_costs(
            self.ROWS,
            policy_section={"input_vat_credit_mode": "PARTIAL",
                            "cost_input_vat_rate": 0.13, "credit_ratio": 0.5,
                            "cost_composition": DEFAULT_COMPOSITION})
        self.assertEqual(plan.status, "PASS")
        self.assertAlmostEqual(plan.multiplier, _HAND_K, places=12)

    def test_none_mode_ignores_composition(self):
        plan = build_effective_costs(
            self.ROWS,
            policy_section={"input_vat_credit_mode": "NONE",
                            "cost_composition": DEFAULT_COMPOSITION})
        self.assertEqual(plan.status, "PASS")
        self.assertEqual(plan.multiplier, 1.0)


# 复用 run_resolve 所需的轻量桩（与 test_cost_basis_wiring 同构，局部自洽）
from bidpricing.quote_pipeline import QuotePipelineResult  # noqa: E402


def _fake_item(item_id="0101", c_i=113.0, cap=200.0, q0=100.0, q1_point=100.0):
    return {"item_id": item_id, "item_name": "挖土方", "unit": "m3", "q0": q0,
            "q1_point": q1_point, "c_i": c_i, "cap": cap, "L": cap * 0.5, "U": cap}


def _fake_result(prices, objective=500.0):
    return QuotePipelineResult(status="PASS", target_total=1000.0,
                               competitive_budget=900.0, p_by_id=dict(prices),
                               line_amounts={}, objective=objective,
                               solver_status="OPTIMAL", violations=(), reason="ok")


class RunResolveCompositionOverrideTest(unittest.TestCase):
    def test_override_composition_echoed_in_payload(self):
        params = {"target_total": 1000.0, "fixed_pretax": 0.0, "vat_rate": 0.09,
                  "surtax_rate": 0.12, "ratio_min": 0.5, "ratio_max": 1.0,
                  "low_ratio_confirmed": True, "low_price_confirmed_by": "测试人"}
        override = {"input_vat_credit_mode": "PARTIAL",
                    "cost_composition": DEFAULT_COMPOSITION}
        with patch("bidpricing.quote_resolve.run_settlement_adjusted_quote_pipeline",
                   return_value=_fake_result({"0101": 150.0})):
            _, payload, code = run_resolve([_fake_item()], params,
                                           {"low_price_threshold": 0.5, "clause_basis": None},
                                           config_dir=CONFIG,
                                           tax_policy_override=override)
        self.assertEqual(code, 200)
        tax = payload["cost_input_tax"]
        self.assertEqual(tax["input_vat_credit_mode"], "PARTIAL")
        self.assertAlmostEqual(tax["credit_ratio"], 0.77, places=6)
        self.assertIsNotNone(tax["cost_composition"])
        self.assertAlmostEqual(tax["multiplier"], _HAND_K, places=10)
        # 有效成本单价 = 113 × k（分项精算，而非旧 113/(1.13)=100 或 113×0.9195）
        self.assertAlmostEqual(payload["items"][0]["有效成本单价"],
                               113.0 * _HAND_K, places=2)


if __name__ == "__main__":
    unittest.main()
