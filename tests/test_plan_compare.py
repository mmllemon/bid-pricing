"""H-008 多方案对比 compare_plans 纯逻辑单元测试（不依赖 FastAPI）。"""
from __future__ import annotations

import unittest

from bidpricing.plan_compare import (
    RISK_RATIO,
    compare_plans,
    group_projects,
    project_key,
    same_project,
)


def _item(code, price, ratio, margin):
    return {"项目编码": code, "项目名称": f"项{code}", "最优报价单价": price,
            "报价比率": ratio, "单项毛利": margin}


def _rec(pid, name, items, objective):
    result = None if objective is None else {
        "status": "PASS", "objective": objective,
        "items": [dict(it, 项目名称=f"项{it['项目编码']}") for it in items],
    }
    return {"id": pid, "name": name, "result": result}


class PlanCompareTest(unittest.TestCase):
    def setUp(self):
        # 方案A：盈利高，无边线风险
        self.a = _rec("a", "方案A", [
            _item("0101", 110.0, 0.92, 15.0),
            _item("0102", 150.0, 0.75, 20.0),
        ], 35.0)
        # 方案B：有亏损项，报价比率也在边线
        self.b = _rec("b", "方案B", [
            _item("0101", 100.0, 0.83, -8.0),
            _item("0102", 160.0, 0.45, 12.0),
        ], 4.0)
        # 方案C：未计算
        self.c = _rec("c", "方案C", [_item("0101", 120.0, 1.0, 5.0)], None)

    def test_basic_columns_and_order(self):
        out = compare_plans([self.a, self.b, self.c])
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(out["plan_ids"], ["a", "b", "c"])
        self.assertEqual(out["base_id"], "a")  # 缺省基准为第一个
        self.assertEqual([s["plan_id"] for s in out["summary"]], ["a", "b", "c"])
        self.assertTrue(out["summary"][0]["computed"])
        self.assertFalse(out["summary"][2]["computed"])  # C 未计算
        self.assertEqual(out["summary"][0]["objective"], 35.0)
        self.assertIsNone(out["summary"][2]["objective"])

    def test_loss_items_and_risk_items(self):
        out = compare_plans([self.a, self.b])
        a, b = out["summary"]
        self.assertEqual(a["loss_items"], [])  # A 无亏损
        self.assertEqual(a["risk_items"], [])  # A 无边线风险
        self.assertEqual(len(b["loss_items"]), 1)
        self.assertEqual(b["loss_items"][0]["项目编码"], "0101")
        self.assertEqual(b["loss_items"][0]["单项毛利"], -8.0)
        self.assertEqual(len(b["risk_items"]), 1)
        self.assertEqual(b["risk_items"][0]["项目编码"], "0102")
        self.assertLess(b["risk_items"][0]["报价比率"], RISK_RATIO)
        self.assertEqual(RISK_RATIO, 0.5)

    def test_price_delta_against_base(self):
        out = compare_plans([self.a, self.b], base_id="a")
        diffs = out["price_diffs"]
        self.assertEqual(out["base_id"], "a")
        self.assertAlmostEqual(diffs["0101"]["deltas"]["a"], 0.0)  # 基准自身差 0
        self.assertAlmostEqual(diffs["0101"]["deltas"]["b"], -10.0)
        self.assertAlmostEqual(diffs["0102"]["deltas"]["b"], 10.0)
        self.assertEqual(diffs["0101"]["item_name"], "项0101")
        # avg_abs_price_delta：B 相对 A 平均 |Δ|
        self.assertAlmostEqual(out["summary"][1]["avg_abs_price_delta"], 10.0)

    def test_base_not_in_list_falls_back_to_first(self):
        out = compare_plans([self.b, self.a], base_id="zzz")
        self.assertEqual(out["base_id"], "b")

    def test_uncomputed_plan_has_no_prices(self):
        out = compare_plans([self.a, self.c], base_id="a")
        self.assertEqual(out["summary"][1]["item_count"], 0)
        self.assertEqual(out["summary"][1]["loss_items"], [])
        self.assertEqual(out["summary"][1]["risk_items"], [])
        self.assertIsNone(out["summary"][1]["avg_abs_price_delta"])
        # C 未含任何报价，单价差异 deltas 中 C 为 None
        self.assertIsNone(out["price_diffs"]["0101"]["deltas"]["c"])

    def test_empty_input(self):
        out = compare_plans([])
        self.assertEqual(out["plan_ids"], [])
        self.assertIsNone(out["base_id"])


class SameProjectTest(unittest.TestCase):
    """H-008 限定同一项目：project_key / group_projects / same_project。"""

    def test_project_key_uses_project_id_preferring_name(self):
        rec = {"project_id": "西永L分区", "name": "西永L分区（副本）", "id": "x1"}
        self.assertEqual(project_key(rec), "西永L分区")
        # 旧方案无 project_id → 退化用 name
        self.assertEqual(project_key({"id": "o", "name": "老项目"}), "老项目")

    def test_same_project_same_and_mixed(self):
        a = _rec("a", "P1", [_item("0101", 110.0, 0.9, 10.0)], 10.0) or {"id": "a", "project_id": "P1", "name": "P1", "result": None}
        bv = {"id": "b", "project_id": "P1", "name": "P1（副本）", "result": None}
        c = {"id": "c", "project_id": "P2", "name": "P2", "result": None}
        ok, projects = same_project([a, bv])
        self.assertTrue(ok)
        self.assertIsNone(projects)
        self.assertEqual(len(group_projects([a, bv])), 1)
        ok2, projs = same_project([a, c])
        self.assertFalse(ok2)
        self.assertEqual(projs, ["P1", "P2"])

    def test_params_carried_into_summary_and_project(self):
        a = {"id": "a", "project_id": "P1", "name": "P1", "params": {"target_total": 1000.0, "ratio_min": 0.5, "ratio_max": 0.9}, "result": {"status": "PASS", "objective": 10.0, "items": [_item("0101", 110.0, 0.9, 10.0)]}}
        bv = {"id": "b", "project_id": "P1", "name": "P1（副本）", "params": {"target_total": 950.0}, "result": {"status": "PASS", "objective": 8.0, "items": [_item("0101", 105.0, 0.9, 8.0)]}}
        out = compare_plans([a, bv], base_id="a")
        self.assertEqual(out["project"], "P1")
        self.assertEqual(out["summary"][0]["params"]["target_total"], 1000.0)
        self.assertEqual(out["summary"][1]["params"]["target_total"], 950.0)


if __name__ == "__main__":
    unittest.main()