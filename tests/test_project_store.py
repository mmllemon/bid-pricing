"""H-007 方案持久化与解析纯逻辑的单元测试（不依赖 FastAPI）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bidpricing import project_store
from bidpricing.project_store import (
    PROJECTS_DIR,
    delete_plan,
    list_plans,
    load_plan,
    mark_finalized,
    save_plan,
)
from bidpricing.quote_pipeline import QuotePipelineResult
from bidpricing.quote_resolve import run_resolve


def _low_policy(**over) -> dict:
    base = {"low_price_threshold": 0.5, "clause_basis": "招标文件第X章" if False else None}
    base.update(over)
    return base


def _item(item_id="0101", cap=100.0, **over) -> dict:
    d = {"item_id": item_id, "item_name": "挖土方", "unit": "m3", "q0": 100.0,
         "q1_point": 100.0, "c_i": 60.0, "cap": cap,
         "L": (cap * 0.5 if cap is not None else 0.0), "U": cap}
    d.update(over)
    return d


class ProjectStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_roundtrip_load(self):
        rid, saved_at = save_plan({"name": "测试项目", "params": {"target_total": 1000.0}, "all_items": [_item()]}, plan_id="abc123", dir_path=self.dir)
        self.assertEqual(rid, "abc123")
        rec = load_plan("abc123", dir_path=self.dir)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["name"], "测试项目")
        self.assertEqual(rec["params"]["target_total"], 1000.0)
        self.assertEqual(rec["saved_at"], saved_at)
        self.assertEqual(rec["id"], "abc123")

    def test_load_missing_returns_none(self):
        self.assertIsNone(load_plan("nope", dir_path=self.dir))

    def test_list_sorted_and_summary(self):
        save_plan({"name": "早期", "all_items": [_item()]}, plan_id="p1", dir_path=self.dir)
        save_plan({"name": "晚期", "all_items": [_item(), _item("0102")], "result": {"competitive_budget": 900.0, "objective": 500.0}}, plan_id="p2", dir_path=self.dir)
        plans = list_plans(dir_path=self.dir)
        self.assertEqual(len(plans), 2)
        # 按 saved_at 倒序：p2 晚于 p1
        self.assertEqual(plans[0]["id"], "p2")
        self.assertEqual(plans[0]["item_count"], 2)
        self.assertEqual(plans[0]["competitive_budget"], 900.0)
        self.assertEqual(plans[1]["item_count"], 1)
        # 摘要不应包含大字段
        self.assertNotIn("all_items", plans[0])
        self.assertNotIn("result", plans[0])

    def test_save_overwrites_same_id_but_new_timestamp(self):
        save_plan({"name": "v1"}, plan_id="p", dir_path=self.dir)
        save_plan({"name": "v2"}, plan_id="p", dir_path=self.dir)
        rec = load_plan("p", dir_path=self.dir)
        self.assertEqual(rec["name"], "v2")
        # 若未显式带 saved_at，save 默认自动打时间戳，两次调用时间应不同（多数情况下）
        self.assertIn("saved_at", rec)

    def test_delete_plan(self):
        save_plan({"name": "x"}, plan_id="del", dir_path=self.dir)
        self.assertTrue(delete_plan("del", dir_path=self.dir))
        self.assertIsNone(load_plan("del", dir_path=self.dir))
        self.assertFalse(delete_plan("del", dir_path=self.dir))

    def test_delete_plan_nested_project_folder(self):
        # 新布局：方案归集在 <项目名>/<id>.json，删除应命中子目录文件
        save_plan({"name": "甲项目", "project_id": "甲项目", "all_items": [_item()]},
                  plan_id="pa", dir_path=self.dir)
        self.assertTrue((self.dir / "甲项目" / "plan_pa.json").exists())
        self.assertTrue(delete_plan("pa", dir_path=self.dir))
        self.assertFalse((self.dir / "甲项目" / "plan_pa.json").exists())
        self.assertIsNone(load_plan("pa", dir_path=self.dir))
        self.assertNotIn("pa", [p["id"] for p in list_plans(dir_path=self.dir)])

    def test_delete_plan_legacy_flat_file(self):
        # 旧布局平铺文件同样可删：直接手工写入 dir/<id>.json
        legacy = self.dir / "oldflat.json"
        legacy.write_text('{"id":"oldflat","name":"旧方案","project_id":"历史项目"}', encoding="utf-8")
        self.assertTrue(delete_plan("oldflat", dir_path=self.dir))
        self.assertFalse(legacy.exists())
        self.assertFalse(delete_plan("oldflat", dir_path=self.dir))

    def test_delete_plan_missing_returns_false(self):
        self.assertFalse(delete_plan("not_there", dir_path=self.dir))

    def test_mark_finalized_sets_flag(self):
        # 标记已定稿：写入 finalized/finalized_at，列表摘要应带出 finalized=true
        save_plan({"name": "x"}, plan_id="fin", dir_path=self.dir)
        self.assertFalse(list_plans(dir_path=self.dir)[0].get("finalized"))
        self.assertTrue(mark_finalized("fin", dir_path=self.dir))
        rec = list_plans(dir_path=self.dir)[0]
        self.assertTrue(rec["finalized"])
        self.assertIn("finalized_at", rec)

    def test_unmark_finalized_clears_flag(self):
        # 手动取消定稿：finalized=false 应清除 finalized/finalized_at
        save_plan({"name": "x"}, plan_id="fin", dir_path=self.dir)
        self.assertTrue(mark_finalized("fin", dir_path=self.dir))
        self.assertTrue(mark_finalized("fin", finalized=False, dir_path=self.dir))
        rec = list_plans(dir_path=self.dir)[0]
        self.assertFalse(rec.get("finalized"))
        self.assertIsNone(rec.get("finalized_at"))

    def test_mark_finalized_missing_returns_false(self):
        self.assertFalse(mark_finalized("nope", dir_path=self.dir))

    def test_mark_finalized_exclusive_per_project(self):
        # 同一项目下只保留一份定稿：先定稿 A，再定稿同项目的 B，A 应自动取消
        save_plan({"name": "项目X", "project_id": "项目X"}, plan_id="A", dir_path=self.dir)
        save_plan({"name": "项目X", "project_id": "项目X"}, plan_id="B", dir_path=self.dir)
        save_plan({"name": "项目Y", "project_id": "项目Y"}, plan_id="C", dir_path=self.dir)
        self.assertTrue(mark_finalized("A", dir_path=self.dir))
        self.assertTrue(mark_finalized("B", dir_path=self.dir))
        flags = {p["id"]: p["finalized"] for p in list_plans(dir_path=self.dir)}
        self.assertFalse(flags["A"])            # 同项目 A 被自动取消
        self.assertTrue(flags["B"])             # B 为当前定稿
        self.assertFalse(flags["C"])            # 不同项目不受影响

    def test_mark_finalized_summary_exposes_target_total(self):
        # 卡片主信息需要展示目标总报价：摘要应带出 target_total
        save_plan({"name": "p", "params": {"target_total": 123456.78}}, plan_id="t", dir_path=self.dir)
        self.assertEqual(list_plans(dir_path=self.dir)[0]["target_total"], 123456.78)

    def test_delete_plan_after_project_name_change_single_file(self):
        # 同一 id 两次保存、项目名从 v1 改成 v2：save 必须清掉旧物理文件，
        # 否则同 id 残留两份会让删除/加载命中旧副本（数据漂移）。
        save_plan({"name": "v1"}, plan_id="p", dir_path=self.dir)
        save_plan({"name": "v2", "project_id": "v2"}, plan_id="p", dir_path=self.dir)
        self.assertTrue((self.dir / "v2" / "plan_p.json").exists())
        self.assertFalse((self.dir / "v1" / "plan_p.json").exists())  # 旧归属已清理
        rec = load_plan("p", dir_path=self.dir)
        self.assertEqual(rec["name"], "v2")
        self.assertTrue(delete_plan("p", dir_path=self.dir))
        self.assertIsNone(load_plan("p", dir_path=self.dir))

    def test_project_store_dir_is_writable(self):
        # 模块级默认目录应可用（正式运行目录）
        self.assertTrue(PROJECTS_DIR.exists())

    def test_reassigned_default_dir_takes_effect(self):
        # H-012 真机暴露的 bug：dir_path 默认值必须在调用时解析，
        # 才能在运行方事后改 PROJECTS_DIR 时真正换目录（用户隔离）。
        sub = self.dir / "leema"
        save_plan({"name": "p", "result": {"objective": 1.0}}, plan_id="p1", dir_path=sub)
        # H-012 归集到项目子目录；同 id 物理文件只应存在一份
        self.assertTrue((sub / "p" / "plan_p1.json").exists())


class QuoteResolveTest(unittest.TestCase):
    """run_resolve 的轻量断言：mock 掉 MILP 求解器（本测试环境无后端），
    只验证 payload 构建、人工项分流、低价留痕与 BLOCKED 挡位。"""

    CONFIG = Path(__file__).resolve().parents[1] / "config"

    def _params(self, **over) -> dict:
        p = {"target_total": 1000.0, "fixed_pretax": 0.0, "vat_rate": 0.09,
             "surtax_rate": 0.12, "ratio_min": 0.5, "ratio_max": 1.0,
             "low_ratio_confirmed": True, "low_price_confirmed_by": "测试人"}
        p.update(over)
        return p

    @staticmethod
    def _fake(prices, objective=500.0):
        return QuotePipelineResult(status="PASS", target_total=1000.0,
                                   competitive_budget=900.0, p_by_id=dict(prices),
                                   line_amounts={}, objective=objective,
                                   solver_status="OPTIMAL", violations=(),
                                   reason="ok")

    def test_pass_builds_optimized_payload(self):
        all_items = [_item("0101", cap=120.0), _item("0102", cap=200.0, q0=80.0, q1_point=80.0)]
        with patch("bidpricing.quote_resolve.run_settlement_adjusted_quote_pipeline",
                   return_value=self._fake({"0101": 110.0, "0102": 150.0})) as pipe:
            result, payload, code = run_resolve(all_items, self._params(), _low_policy(), config_dir=self.CONFIG)
            pipe.assert_called_once()
        self.assertEqual(code, 200)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["item_count"], 2)
        self.assertEqual(len(payload["items"]), 2)
        self.assertTrue(all(x["报价状态"] == "OPTIMIZED" for x in payload["items"]))
        self.assertEqual(payload["low_price_policy"]["disposition"], "CONFIRM_ONLY")
        self.assertIn("是否构成废标", str(payload["low_price_policy"].get("disposition_note")))

    def test_mixed_manual_produces_review_row(self):
        all_items = [_item("0101", cap=120.0), _item("0109", cap=None, c_i=None, q1_point=None)]
        with patch("bidpricing.quote_resolve.run_settlement_adjusted_quote_pipeline",
                   return_value=self._fake({"0101": 110.0})):
            result, payload, code = run_resolve(all_items, self._params(), _low_policy(), config_dir=self.CONFIG)
        self.assertEqual(code, 200)
        self.assertEqual(payload["manual_item_count"], 1)
        manual = next(x for x in payload["items"] if x["项目编码"] == "0109")
        self.assertEqual(manual["报价状态"], "MANUAL_REVIEW")

    def test_all_manual_blocks(self):
        all_items = [_item("0101", cap=None, c_i=None)]
        result, payload, code = run_resolve(all_items, self._params(), _low_policy(), config_dir=self.CONFIG)
        self.assertIsNone(result)
        self.assertEqual(code, 400)
        self.assertEqual(payload["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()