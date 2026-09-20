"""H-002 成本税口径：换算内核 + 两条报价入口接线的**双向**验证。

为什么单列一个文件（而不是塞进 test_cost_input_tax.py）：
``test_cost_input_tax.py`` 只测**声明校验器**（CT-01..CT-05 的状态码），
它证明「声明齐不齐」，**不证明**任何一个报价入口真的消费了这些声明。
历史上 C13 正是「判据齐全但从未被入口消费」——判据全绿而缺陷照旧。
所以本文件专测**消费侧**：换算数值是否钉死、阻断是否真发生在出数之前、
两块入口是否共用同一判据、反向（二次换算）是否也被挡住。

判据设计要点（对齐九条同源规则）：
* 数值钉死用**手算**目标值，不循环引用被测实现的输出；
* 「能被错误值否定」与「不能被正确值否定」都要有——既断言正确值通过，
  也断言具体错误值（销项税率冒充进项税率、raw 成本冒充有效成本）会被挡；
* 反向证明：把已换算输出**再喂回去**必须 BLOCKED（CT-07），
  否则「修一半」也能让正向用例全绿。
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from bidpricing.quote_pipeline import (
    QuotePipelineResult,
    resolve_cost_plan,
    run_quote_pipeline,
)
from bidpricing.quote_resolve import run_resolve
from bidpricing.solver.phase1 import phase1_probe_instance
from bidpricing.validation import cost_basis as cb
from bidpricing.validation.cost_basis import (
    CREDIT_MODE_VOCABULARY,
    EffectiveCostPlan,
    build_effective_costs,
    check_cost_input_tax,
    effective_cost,
    effective_cost_multiplier,
    load_cost_input_tax_spec,
)

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config"


# ------------------------------------------------------------------ helpers
@contextmanager
def _temp_config(**policy_over):
    """把 config/ 复制到临时目录并覆盖 ``cost_input_tax_policy`` 段。

    为什么复制而不是改真 config：``project_quote_policy.json`` 是**项目数据**
    （取值由责任人声明），单测不得耦合它的实时状态，更不得改动它。
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        shutil.copytree(CONFIG, tmp / "cfg")
        path = tmp / "cfg" / "project_quote_policy.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        section = {"cost_input_incl_vat": True}
        section.update(policy_over)
        doc["cost_input_tax_policy"] = section
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        yield tmp / "cfg"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _policy(**over) -> dict:
    sec = {"mode": "UNKNOWN", "cost_input_vat_rate": None,
           "input_vat_credit_mode": "UNKNOWN", "credit_ratio": None}
    sec.update(over)
    return sec


def _probe_rows():
    """phase1 探针实例 → 管道入参行（**不标** cost_tax_scope ⇒ 待本层换算）。"""
    inst = phase1_probe_instance()
    rows = [{"item_id": i.item_id, "q0": i.q0, "q1_point": i.q1_point, "c_i": i.c_i,
             "cap": i.cap, "L": i.L, "U": i.U, "p0": i.p0, "pricing_role": i.role}
            for i in inst.items]
    return inst, rows


def _resolve_params(**over) -> dict:
    p = {"target_total": 1000.0, "fixed_pretax": 0.0, "vat_rate": 0.09,
         "surtax_rate": 0.12, "ratio_min": 0.5, "ratio_max": 1.0,
         "low_ratio_confirmed": True, "low_price_confirmed_by": "测试人"}
    p.update(over)
    return p


def _low_policy() -> dict:
    return {"low_price_threshold": 0.5, "clause_basis": None}


# ======================================================================
# A. 换算内核：系数与有效成本的**手算钉死**
# ======================================================================
class MultiplierExactnessTest(unittest.TestCase):
    """k 的闭式必须与手算逐位一致——这是唯一换算入口，错一点全盘错。"""

    def test_full_equals_one_over_one_plus_rate(self):
        # FULL: 进项税全额抵扣 ⇒ k = 1/(1+r)；113 含税 → 100 不含税
        k = effective_cost_multiplier(0.13, "FULL")
        self.assertAlmostEqual(k, 1.0 / 1.13, places=15)
        self.assertEqual(effective_cost(113.0, 0.13, "FULL"), 100.0)

    def test_partial_equals_itemized_recomputation(self):
        # PARTIAL 必须**严格等价**于分项精算：货物 G 除税、人工 L 不动。
        # c=113, r=0.13, ρ=0.6 ⇒ G=67.8, L=45.2 ⇒ G/1.13+L = 60.0+45.2 = 105.2
        c, r, rho = 113.0, 0.13, 0.6
        g, l = c * rho, c * (1.0 - rho)
        itemized = g / (1.0 + r) + l
        self.assertAlmostEqual(itemized, 105.2, places=12)
        self.assertEqual(effective_cost(c, r, "PARTIAL", rho), 105.2)
        self.assertAlmostEqual(
            effective_cost(c, r, "PARTIAL", rho), itemized, places=9)

    def test_none_is_identity_and_needs_no_rate(self):
        # NONE: 不可抵扣（简易计税/无进项票）⇒ 含税即有效成本，**不读税率**
        self.assertEqual(effective_cost_multiplier(None, "NONE"), 1.0)
        self.assertEqual(effective_cost(113.0, None, "NONE"), 113.0)

    def test_unknown_returns_none(self):
        self.assertIsNone(effective_cost_multiplier(0.13, "UNKNOWN"))
        self.assertIsNone(effective_cost(113.0, 0.13, "UNKNOWN"))

    def test_invalid_mode_raises_not_silent(self):
        # 词表外模式是**程序错误**，必须抛而不是静默返回 None（静默会把 Bug 藏起来）
        with self.assertRaises(ValueError):
            effective_cost_multiplier(0.13, "MOSTLY")

    def test_two_vat_rates_are_distinct_names(self):
        """★ DV-02 同族：销项税率 vat_rate 与进项税率 cost_input_vat_rate 是
        **两个物理量**。此用例把「用错名字」的后果钉成可观测差异。"""
        k_in = effective_cost_multiplier(0.13, "FULL")   # 进项 13%
        k_out = effective_cost_multiplier(0.09, "FULL")  # 销项 9%（建筑服务）
        self.assertNotAlmostEqual(k_in, k_out, places=6)  # 混用即数值可辨
        self.assertEqual(effective_cost(113.0, 0.13, "FULL"), 100.0)
        self.assertNotEqual(effective_cost(113.0, 0.09, "FULL"), 100.0)


# ======================================================================
# B. build_effective_costs：七类阻断 + 正常换算 + 不改入参
# ======================================================================
class BuildEffectiveCostsTest(unittest.TestCase):
    ROWS = [{"item_id": "A", "c_i": 113.0, "q0": 10.0, "q1_point": 10.0},
            {"item_id": "B", "c_i": 226.0, "q0": 5.0, "q1_point": 6.0}]

    def test_pass_converts_and_records_trace(self):
        plan = build_effective_costs(
            self.ROWS, policy_section=_policy(input_vat_credit_mode="FULL",
                                              cost_input_vat_rate=0.13))
        self.assertEqual(plan.status, "PASS")
        self.assertFalse(plan.blocking)
        self.assertAlmostEqual(plan.multiplier, 1.0 / 1.13, places=15)
        by_id = {r["item_id"]: r for r in plan.items}
        self.assertEqual(by_id["A"]["c_i"], 100.0)
        self.assertEqual(by_id["B"]["c_i"], 200.0)
        # 原始含税值必须留在 cost_unit_price_input（只留一个数读表的人分不清口径）
        self.assertEqual(by_id["A"]["cost_unit_price_input"], 113.0)
        for row in plan.items:
            self.assertEqual(row["cost_tax_scope"], "EXCL_VAT")
        self.assertEqual(len(plan.trace), 2)
        t0 = plan.trace_dicts()[0]
        self.assertEqual(t0["item_id"], "A")
        self.assertEqual(t0["cost_unit_price_input"], 113.0)
        self.assertEqual(t0["cost_unit_price_effective"], 100.0)

    def test_input_rows_not_mutated(self):
        rows = [dict(r) for r in self.ROWS]
        build_effective_costs(rows, policy_section=_policy(
            input_vat_credit_mode="FULL", cost_input_vat_rate=0.13))
        # 入参不得被就地改口径，否则调用方再算一次就静默用了被改过的成本
        self.assertEqual(rows[0]["c_i"], 113.0)
        self.assertNotIn("cost_tax_scope", rows[0])

    def test_none_cost_items_pass_through(self):
        rows = self.ROWS + [{"item_id": "M", "c_i": None, "q0": 1.0, "q1_point": None}]
        plan = build_effective_costs(rows, policy_section=_policy(
            input_vat_credit_mode="NONE"))
        self.assertEqual(plan.status, "PASS")
        manual = next(r for r in plan.items if r["item_id"] == "M")
        self.assertIsNone(manual["c_i"])
        self.assertIsNone(manual["cost_unit_price_input"])
        self.assertEqual(len(plan.trace), 2)  # 无成本项不进换算痕迹

    def test_block_missing_policy_section(self):
        plan = build_effective_costs(self.ROWS, policy_section={})
        self.assertTrue(plan.blocking)
        self.assertIn("cost_input_tax_policy", plan.reason)

    def test_block_unknown_mode(self):
        plan = build_effective_costs(self.ROWS, policy_section=_policy())
        self.assertTrue(plan.blocking)
        self.assertIn("UNKNOWN", plan.reason)
        self.assertIsNone(plan.multiplier)

    def test_block_invalid_mode(self):
        plan = build_effective_costs(self.ROWS, policy_section=_policy(
            input_vat_credit_mode="MOSTLY"))
        self.assertTrue(plan.blocking)
        self.assertIn("词表", plan.reason)

    def test_block_full_without_rate(self):
        for mode in ("FULL", "PARTIAL"):
            plan = build_effective_costs(self.ROWS, policy_section=_policy(
                input_vat_credit_mode=mode, credit_ratio=0.5))
            self.assertTrue(plan.blocking, mode)
            self.assertIn("cost_input_vat_rate", plan.reason)

    def test_block_rate_out_of_range(self):
        for bad in (0.0, 1.5, -0.1):
            plan = build_effective_costs(self.ROWS, policy_section=_policy(
                input_vat_credit_mode="FULL", cost_input_vat_rate=bad))
            self.assertTrue(plan.blocking, bad)
            self.assertIn("(0,1]", plan.reason)

    def test_block_partial_bad_ratio(self):
        for bad in (None, 0.0, 1.0, 1.5):
            plan = build_effective_costs(self.ROWS, policy_section=_policy(
                input_vat_credit_mode="PARTIAL", cost_input_vat_rate=0.13,
                credit_ratio=bad))
            self.assertTrue(plan.blocking, bad)
            self.assertIn("credit_ratio", plan.reason)

    def test_vat_rate_cannot_stand_in_for_cost_input_vat_rate(self):
        """★ DV-02 守卫：只声明销项税率而缺进项税率 ⇒ BLOCKED，
        **不得**拿 vat_rate 顶替（顶替会静默算出错的成本）。"""
        plan = build_effective_costs(self.ROWS, policy_section=_policy(
            input_vat_credit_mode="FULL", cost_input_vat_rate=None, vat_rate=0.13))
        self.assertTrue(plan.blocking)
        self.assertIn("cost_input_vat_rate", plan.reason)

    def test_ct07_blocks_double_conversion(self):
        """★ 反向证明：把已换算（EXCL_VAT）的输出再喂回去必须 BLOCKED。"""
        first = build_effective_costs(self.ROWS, policy_section=_policy(
            input_vat_credit_mode="FULL", cost_input_vat_rate=0.13))
        second = build_effective_costs(list(first.items), policy_section=_policy(
            input_vat_credit_mode="FULL", cost_input_vat_rate=0.13))
        self.assertTrue(second.blocking)
        self.assertIn("二次换算", second.reason)
        self.assertIn("CT-07", second.reason)
        # ★ 判别力：把标记摘掉即放行 ⇒ 证明**标记本身**是这条判据的判别依据，
        #   而不是碰巧被别的条件挡住（否则「摘掉标记也阻断」会掩盖误判）。
        stripped = [dict(r) for r in first.items]
        for r in stripped:
            r.pop("cost_tax_scope", None)
        third = build_effective_costs(stripped, policy_section=_policy(
            input_vat_credit_mode="FULL", cost_input_vat_rate=0.13))
        self.assertEqual(third.status, "PASS")

    def test_ct07_ignores_costless_items(self):
        rows = self.ROWS + [{"item_id": "M", "c_i": None, "cost_tax_scope": "EXCL_VAT"}]
        plan = build_effective_costs(rows, policy_section=_policy(
            input_vat_credit_mode="NONE"))
        self.assertEqual(plan.status, "PASS")


# ======================================================================
# C. resolve_cost_plan：口径契约活在**数据标记**上
# ======================================================================
class ResolveCostPlanContractTest(unittest.TestCase):
    def test_all_labeled_excl_skips_conversion(self):
        rows = [{"item_id": "A", "c_i": 100.0, "cost_tax_scope": "EXCL_VAT"}]
        plan, err = resolve_cost_plan(rows, CONFIG)
        self.assertIsNone(err)
        self.assertIsNone(plan.multiplier)      # 不再换算 ⇒ k 无意义
        self.assertEqual(plan.items[0]["c_i"], 100.0)

    def test_unlabeled_converts(self):
        rows = [{"item_id": "A", "c_i": 113.0}]
        with _temp_config(input_vat_credit_mode="FULL", cost_input_vat_rate=0.13) as cfg:
            plan, err = resolve_cost_plan(rows, cfg)
        self.assertIsNone(err)
        self.assertEqual(plan.items[0]["c_i"], 100.0)

    def test_no_cost_items_skips_without_blocking(self):
        rows = [{"item_id": "M", "c_i": None}]
        plan, err = resolve_cost_plan(rows, CONFIG)   # 真 config 是 UNKNOWN，也不该拦
        self.assertIsNone(err)
        self.assertIsNone(plan.multiplier)

    def test_mixed_scope_blocks_and_names_items(self):
        rows = [{"item_id": "A", "c_i": 100.0, "cost_tax_scope": "EXCL_VAT"},
                {"item_id": "B", "c_i": 113.0}]
        plan, err = resolve_cost_plan(rows, CONFIG)
        self.assertIsNone(plan)
        self.assertIn("不一致", err)
        self.assertIn("A", err)

    def test_costless_items_do_not_trigger_mixed(self):
        rows = [{"item_id": "A", "c_i": 100.0, "cost_tax_scope": "EXCL_VAT"},
                {"item_id": "M", "c_i": None}]           # 无成本项不进一致性判定
        plan, err = resolve_cost_plan(rows, CONFIG)
        self.assertIsNone(err)


# ======================================================================
# D. run_quote_pipeline（CLI/分析侧入口）接线
# ======================================================================
class QuotePipelineWiringTest(unittest.TestCase):
    def test_unknown_mode_blocks_before_numbers(self):
        """mode=UNKNOWN ⇒ 阻断，且不泄露任何报价数字。"""
        inst, rows = _probe_rows()
        with _temp_config(input_vat_credit_mode="UNKNOWN", cost_input_vat_rate=None,
                          credit_ratio=None) as cfg:
            r = run_quote_pipeline(target_total=inst.B, items=rows, fixed_pretax=0,
                                   vat_rate=0.09, surtax_rate=0.03, config_dir=cfg)
        self.assertEqual(r.status, "BLOCKED")
        self.assertIn("成本税口径", r.reason)
        self.assertEqual(r.p_by_id, {})
        self.assertIsNone(r.objective)
        self.assertIsNone(r.cost_multiplier)

    def test_full_mode_converts_and_solves(self):
        inst, rows = _probe_rows()
        with _temp_config(input_vat_credit_mode="FULL", cost_input_vat_rate=0.13) as cfg:
            r = run_quote_pipeline(target_total=inst.B, items=rows, fixed_pretax=0,
                                   vat_rate=0.09, surtax_rate=0.03, config_dir=cfg)
        self.assertEqual(r.status, "PASS")
        self.assertAlmostEqual(r.cost_multiplier, 1.0 / 1.13, places=15)
        self.assertEqual(len(r.cost_adjustment_trace), len(rows))

    def test_profit_regression_under_new_basis(self):
        """★ 旧结果在新口径下必须重算：ΔZ == Σ q1·(c_incl − c_eff)，且 ΔZ > 0。

        旧缺陷把含税成本当有效成本直接与不含税收入相减 ⇒ 利润被**系统性低估**。
        本用例把「低估多少」钉成恒等式，任何一侧算错都会被否定。
        """
        inst, rows = _probe_rows()
        with _temp_config(input_vat_credit_mode="FULL", cost_input_vat_rate=0.13) as cfg:
            r_new = run_quote_pipeline(target_total=inst.B, items=rows, fixed_pretax=0,
                                       vat_rate=0.09, surtax_rate=0.03, config_dir=cfg)
            # 旧口径基线：把含税成本直接标成 EXCL_VAT（= 不换算）复现历史行为
            raw_rows = [dict(row, cost_tax_scope="EXCL_VAT") for row in rows]
            r_old = run_quote_pipeline(target_total=inst.B, items=raw_rows, fixed_pretax=0,
                                       vat_rate=0.09, surtax_rate=0.03, config_dir=cfg)
        self.assertEqual(r_new.status, "PASS")
        self.assertEqual(r_old.status, "PASS")
        plan = build_effective_costs(rows, policy_section=_policy(
            input_vat_credit_mode="FULL", cost_input_vat_rate=0.13))
        eff = {row["item_id"]: row["c_i"] for row in plan.items}
        expected = sum(float(row["q1_point"]) * (float(row["c_i"]) - eff[row["item_id"]])
                       for row in rows)
        self.assertGreater(expected, 0.0)
        self.assertAlmostEqual(r_new.objective - r_old.objective, expected, places=6)

    def test_converted_input_is_idempotent_not_double_converted(self):
        """★ 入口级反向证明：把已换算（EXCL_VAT）的清单再走一次入口，
        必须**幂等**（不再换算），而不是把 k 乘第二遍。

        两个方向各有守卫，缺一即「修一半」：
        * 入口侧：见 EXCL_VAT 标记即短路，不到换算内核 ⇒ 幂等；
        * 内核侧：若绕过标记直接把 EXCL_VAT 数据交给 ``build_effective_costs``，
          则 CT-07 阻断（见 ``BuildEffectiveCostsTest.test_ct07_blocks_double_conversion``）。
        本用例证明第一侧：二次换算若真发生，目标函数会额外虚增 Σq1·(c_eff − c_eff·k)，
        此处断言它**没有**虚增。
        """
        inst, rows = _probe_rows()
        with _temp_config(input_vat_credit_mode="FULL", cost_input_vat_rate=0.13) as cfg:
            r_new = run_quote_pipeline(target_total=inst.B, items=rows, fixed_pretax=0,
                                       vat_rate=0.09, surtax_rate=0.03, config_dir=cfg)
            self.assertEqual(r_new.status, "PASS")
            k = r_new.cost_multiplier
            converted = [
                dict(row, cost_tax_scope="EXCL_VAT",
                     c_i=t["cost_unit_price_effective"])
                for row, t in zip(rows, r_new.cost_adjustment_trace)
            ]
            idem = run_quote_pipeline(target_total=inst.B, items=converted, fixed_pretax=0,
                                      vat_rate=0.09, surtax_rate=0.03, config_dir=cfg)
        self.assertEqual(idem.status, "PASS")
        self.assertIsNone(idem.cost_multiplier)                 # 未再换算
        self.assertEqual(len(idem.cost_adjustment_trace), 0)    # 无换算痕迹
        self.assertAlmostEqual(idem.objective, r_new.objective, places=6)
        # 反证：若被二次换算，目标会额外虚增这么多——此处必须不相等
        from bidpricing.money import money
        ghost = r_new.objective + sum(
            float(row["q1_point"]) * (t["cost_unit_price_effective"]
                                      - money(t["cost_unit_price_effective"] * k))
            for row, t in zip(rows, r_new.cost_adjustment_trace))
        self.assertGreater(ghost, r_new.objective)
        self.assertNotAlmostEqual(idem.objective, ghost, places=2)

    def test_mixed_scope_blocks_at_entry(self):
        inst, rows = _probe_rows()
        rows = [dict(r) for r in rows]
        rows[0]["cost_tax_scope"] = "EXCL_VAT"
        r = run_quote_pipeline(target_total=inst.B, items=rows, fixed_pretax=0,
                               vat_rate=0.09, surtax_rate=0.03, config_dir=CONFIG)
        self.assertEqual(r.status, "BLOCKED")
        self.assertIn("不一致", r.reason)


# ======================================================================
# E. run_resolve（网页平台入口）接线
# ======================================================================
class ResolveEntryWiringTest(unittest.TestCase):
    @staticmethod
    def _item(item_id="0101", c_i=113.0, cap=200.0, q0=100.0, q1_point=100.0):
        return {"item_id": item_id, "item_name": "挖土方", "unit": "m3",
                "q0": q0, "q1_point": q1_point, "c_i": c_i, "cap": cap,
                "L": cap * 0.5, "U": cap}

    @staticmethod
    def _fake(prices, objective=500.0):
        return QuotePipelineResult(status="PASS", target_total=1000.0,
                                   competitive_budget=900.0, p_by_id=dict(prices),
                                   line_amounts={}, objective=objective,
                                   solver_status="OPTIMAL", violations=(), reason="ok")

    def test_unknown_mode_blocks_without_margin_numbers(self):
        with _temp_config(input_vat_credit_mode="UNKNOWN", cost_input_vat_rate=None,
                          credit_ratio=None) as cfg:
            result, payload, code = run_resolve([self._item()], _resolve_params(),
                                                _low_policy(), config_dir=cfg)
        self.assertIsNone(result)
        self.assertEqual(code, 400)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertIn("成本税口径", payload["reason"])
        # 阻断必须发生在出数之前：不得留下任何毛利/成本合价字段
        self.assertNotIn("items", payload)
        self.assertEqual(payload["cost_input_tax"]["status"], "BLOCKED")
        self.assertIn("user_hint", payload["cost_input_tax"])

    def test_full_mode_uses_effective_cost_in_margin(self):
        # FULL r=0.13 ⇒ c_eff = 100；价 150 ≥ 50%·cap=100 ⇒ 收入 = q1·p = 15000
        # 正确毛利 = 15000 − 100·100 = 5000；旧缺陷会算成 15000 − 100·113 = 3700
        with _temp_config(input_vat_credit_mode="FULL", cost_input_vat_rate=0.13) as cfg:
            with patch("bidpricing.quote_resolve.run_settlement_adjusted_quote_pipeline",
                       return_value=self._fake({"0101": 150.0})) as pipe:
                result, payload, code = run_resolve([self._item()], _resolve_params(),
                                                    _low_policy(), config_dir=cfg)
                pipe.assert_called_once()
        self.assertEqual(code, 200)
        self.assertEqual(payload["status"], "PASS")
        row = payload["items"][0]
        self.assertEqual(row["含税成本单价"], 113.0)
        self.assertEqual(row["成本税口径"], "EXCL_VAT")
        self.assertEqual(row["有效成本单价"], 100.0)
        self.assertEqual(row["成本合价"], 10000.0)
        self.assertEqual(row["结算收入"], 15000.0)
        self.assertEqual(row["单项毛利"], 5000.0)
        # 反向：毛利绝不能等于按含税成本算的 3700
        self.assertNotEqual(row["单项毛利"], 3700.0)

    def test_pipeline_receives_effective_cost_not_raw(self):
        """接线是否正确，看**传给求解器的项**里的 c_i，而不是看输出表格。"""
        with _temp_config(input_vat_credit_mode="FULL", cost_input_vat_rate=0.13) as cfg:
            with patch("bidpricing.quote_resolve.run_settlement_adjusted_quote_pipeline",
                       return_value=self._fake({"0101": 150.0})) as pipe:
                run_resolve([self._item()], _resolve_params(), _low_policy(), config_dir=cfg)
        passed_items = pipe.call_args.kwargs["items"]
        self.assertEqual(passed_items[0]["c_i"], 100.0)
        # 换算发生在入口，管道第二次见到 EXCL_VAT 标记不会重复换算
        self.assertEqual(passed_items[0]["cost_tax_scope"], "EXCL_VAT")

    def test_trace_present_for_recomputation(self):
        with _temp_config(input_vat_credit_mode="PARTIAL", cost_input_vat_rate=0.13,
                          credit_ratio=0.6) as cfg:
            with patch("bidpricing.quote_resolve.run_settlement_adjusted_quote_pipeline",
                       return_value=self._fake({"0101": 150.0})):
                _, payload, code = run_resolve([self._item()], _resolve_params(),
                                               _low_policy(), config_dir=cfg)
        self.assertEqual(code, 200)
        tax = payload["cost_input_tax"]
        self.assertEqual(tax["input_vat_credit_mode"], "PARTIAL")
        self.assertEqual(tax["cost_input_vat_rate"], 0.13)
        self.assertEqual(tax["credit_ratio"], 0.6)
        self.assertEqual(len(tax["adjustment_trace"]), 1)
        self.assertEqual(payload["items"][0]["有效成本单价"], 105.2)

    def test_mixed_scope_blocks_at_entry(self):
        rows = [self._item("0101"), dict(self._item("0102"), cost_tax_scope="EXCL_VAT")]
        result, payload, code = run_resolve(rows, _resolve_params(), _low_policy(),
                                            config_dir=CONFIG)
        self.assertIsNone(result)
        self.assertEqual(code, 400)
        self.assertIn("不一致", payload["reason"])


# ======================================================================
# F. 机制制品 ↔ 实现常量 双向对账（CT-06）
# ======================================================================
class SpecWordlistReconciliationTest(unittest.TestCase):
    def test_spec_declares_deployed_wordlist(self):
        spec = load_cost_input_tax_spec(CONFIG)
        self.assertIsNotNone(spec, "cost_input_tax_spec.json 必须存在（机制住制品）")
        declared = tuple((spec.get("credit_mode_vocabulary") or {}).keys())
        self.assertEqual(set(declared), set(CREDIT_MODE_VOCABULARY))

    def test_ct06_reports_pass_on_real_config(self):
        report = check_cost_input_tax(CONFIG)
        ct06 = report.by_rule("CT-06")
        self.assertEqual(ct06.status, "PASS")

    def test_ct06_catches_extra_declared_mode(self):
        # 制品多声明一个模式而实现不认 ⇒ 双向对账必须报 FAIL（单向比对会漏掉）
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(CONFIG, tmp / "cfg")
            p = tmp / "cfg" / "cost_input_tax_spec.json"
            doc = json.loads(p.read_text(encoding="utf-8"))
            doc["credit_mode_vocabulary"]["HALF"] = {"meaning": "注入的假模式"}
            p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            report = check_cost_input_tax(tmp / "cfg")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(report.by_rule("CT-06").status, "FAIL")

    def test_ct06_catches_missing_declared_mode(self):
        # 实现多一个模式而制品没声明 ⇒ 同样必须 FAIL
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(CONFIG, tmp / "cfg")
            p = tmp / "cfg" / "cost_input_tax_spec.json"
            doc = json.loads(p.read_text(encoding="utf-8"))
            doc["credit_mode_vocabulary"].pop("PARTIAL", None)
            p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            report = check_cost_input_tax(tmp / "cfg")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(report.by_rule("CT-06").status, "FAIL")


class MutationDiscriminationTest(unittest.TestCase):
    """变体注入：把 H-002 的每个机制逐个抽掉，**必须**被具名用例杀死。

    存活 ⇒ FAIL。为什么必做：一份「全绿」的测试可能只是没碰到缺陷
    （T03-05 首轮 M-05/M-06 假存活的教训）。这里对每个变体点名「谁杀它」，
    使「测试有区分度」成为可核量，而不是声明。
    """

    @staticmethod
    def _killed(fn, *patches) -> bool:
        for p in patches:
            p.start()
        try:
            fn()
            return False            # 变体通过 ⇒ 无区分度
        except AssertionError:
            return True             # 被断言杀死
        finally:
            for p in reversed(patches):
                p.stop()

    @staticmethod
    def _permissive(items, config_dir, **kwargs):
        """变体替身：假装换算已接线但实际什么都没做（成本保持含税）。"""
        return (EffectiveCostPlan("PASS", "mutant: 未接线", 1.0,
                                  tuple(dict(r) for r in items)), None)

    def test_v1_kernel_conversion_disabled_is_killed(self):
        """V1 换算恒等：k≡1 ⇒ 由数值钉死用例杀死。"""
        t = BuildEffectiveCostsTest("test_pass_converts_and_records_trace")
        self.assertTrue(
            self._killed(t.test_pass_converts_and_records_trace,
                         patch.object(cb, "effective_cost_multiplier",
                                      lambda *a, **kw: 1.0)),
            "V1（换算恒等）存活 ⇒ 数值钉死用例没有区分度")

    def test_v2_entry_blocking_removed_is_killed(self):
        """V2 入口不阻断：CLI 侧遇 UNKNOWN 仍出数 ⇒ 由阻断用例杀死。"""
        t = QuotePipelineWiringTest("test_unknown_mode_blocks_before_numbers")
        self.assertTrue(
            self._killed(t.test_unknown_mode_blocks_before_numbers,
                         patch("bidpricing.quote_pipeline.resolve_cost_plan",
                               self._permissive)),
            "V2（入口不阻断）存活 ⇒ 阻断用例没有区分度")

    def test_v3_entry_conversion_never_runs_is_killed(self):
        """V3 入口不换算：网页侧把含税成本传给求解器 ⇒ 由「看入参」用例杀死。"""
        t = ResolveEntryWiringTest("test_pipeline_receives_effective_cost_not_raw")
        self.assertTrue(
            self._killed(t.test_pipeline_receives_effective_cost_not_raw,
                         patch("bidpricing.quote_resolve.resolve_cost_plan",
                               self._permissive)),
            "V3（入口不换算）存活 ⇒ 入参断言没有区分度")

    def test_v4_entry_margin_uses_raw_cost_is_killed(self):
        """V4 毛利用含税成本：输出表看起来照旧 ⇒ 由毛利钉死用例杀死。"""
        t = ResolveEntryWiringTest("test_full_mode_uses_effective_cost_in_margin")
        self.assertTrue(
            self._killed(t.test_full_mode_uses_effective_cost_in_margin,
                         patch("bidpricing.quote_resolve.resolve_cost_plan",
                               self._permissive)),
            "V4（毛利用含税成本）存活 ⇒ 毛利钉死用例没有区分度")


if __name__ == "__main__":
    unittest.main()