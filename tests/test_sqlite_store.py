"""sqlite_store 迁移落点单元测试。

覆盖：方案单表读写（含真列/JSON 大字段）、删除、按策略查找、单项目单定稿不变量、
方案组（建组/挂槽/查询/改名/整组定稿）、整组复制（深拷贝）、整组删除（级联）、
migrate/import_json_tree 幂等归库、audit_log 追加与过滤查询。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing import sqlite_store
from bidpricing.project_store import save_plan as fs_save_plan


def _record(project_id: str, project_name: str, strategy: str,
            group_id: str | None, target_total: int, plan_id: str) -> dict:
    return {
        "id": plan_id, "name": project_name, "project_id": project_id,
        "project_name": project_name, "group_id": group_id, "strategy": strategy,
        "params": {"target_total": target_total, "vat_rate": 0.09, "ratio_min": 0.5},
        "result": {"competitive_budget": target_total - 5000, "profit": 3000},
    }


class SqliteStorePlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "quote.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_load_list_roundtrip(self) -> None:
        rid, _ = sqlite_store.save_plan(_record("P1", "项目甲", "optimal", None, 100000, "p1"),
                                        plan_id="p1", db=self.db)
        self.assertEqual(rid, "p1")
        rec = sqlite_store.load_plan("p1", db=self.db)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["project_id"], "P1")
        self.assertEqual(rec["strategy"], "optimal")
        # JSON 大字段可往返；真列可查询
        self.assertEqual((rec["params"])["target_total"], 100000)
        self.assertEqual((rec["result"])["profit"], 3000)
        self.assertEqual(len(sqlite_store.list_plans(self.db)), 1)

    def test_save_overwrite_same_id(self) -> None:
        sqlite_store.save_plan(_record("P1", "甲", "optimal", None, 100000, "p1"),
                               plan_id="p1", db=self.db)
        sqlite_store.save_plan(_record("P1", "甲", "optimal", None, 200000, "p1"),
                               plan_id="p1", db=self.db)
        self.assertEqual(len(sqlite_store.list_plans(self.db)), 1)
        self.assertEqual((sqlite_store.load_plan("p1", db=self.db))["params"]["target_total"], 200000)

    def test_delete_plan(self) -> None:
        self.assertFalse(sqlite_store.delete_plan("ghost", db=self.db))
        sqlite_store.save_plan(_record("P1", "甲", "optimal", None, 1, "p1"), plan_id="p1", db=self.db)
        self.assertTrue(sqlite_store.delete_plan("p1", db=self.db))
        self.assertIsNone(sqlite_store.load_plan("p1", db=self.db))

    def test_find_plan_by_strategy(self) -> None:
        sqlite_store.save_plan(_record("P1", "甲", "optimal", "g1", 100000, "p-opt"),
                               plan_id="p-opt", db=self.db)
        sqlite_store.save_plan(_record("P1", "甲", "uniform", "g1", 101000, "p-uni"),
                               plan_id="p-uni", db=self.db)
        self.assertEqual(sqlite_store.find_plan_by_strategy("P1", "optimal", db=self.db), "p-opt")
        self.assertEqual(sqlite_store.find_plan_by_strategy("P1", "uniform", db=self.db), "p-uni")
        # 改名后的同名项目也能命中（project_name 归一键）
        self.assertEqual(sqlite_store.find_plan_by_strategy("甲", "optimal", db=self.db), "p-opt")
        # group_id 限定
        self.assertEqual(sqlite_store.find_plan_by_strategy("P1", "optimal", group_id="g1", db=self.db), "p-opt")
        self.assertIsNone(sqlite_store.find_plan_by_strategy("P1", "optimal", group_id="none", db=self.db))
        self.assertIsNone(sqlite_store.find_plan_by_strategy("P9", "optimal", db=self.db))

    def test_mark_finalized_single_per_project(self) -> None:
        sqlite_store.save_plan(_record("P1", "甲", "optimal", "g1", 100000, "a"), plan_id="a", db=self.db)
        sqlite_store.save_plan(_record("P1", "甲", "uniform", "g1", 101000, "b"), plan_id="b", db=self.db)
        self.assertFalse(sqlite_store.mark_finalized("ghost", db=self.db))
        self.assertTrue(sqlite_store.mark_finalized("a", db=self.db))
        self.assertTrue(sqlite_store.mark_finalized("b", db=self.db))
        finals = [r["id"] for r in sqlite_store.list_plans(self.db) if r["finalized"]]
        self.assertEqual(finals, ["b"])  # 同项目仅一份定稿
        # 取消定稿
        self.assertTrue(sqlite_store.mark_finalized("b", finalized=False, db=self.db))
        finals = [r["id"] for r in sqlite_store.list_plans(self.db) if r["finalized"]]
        self.assertEqual(finals, [])

    def test_save_plan_ownership_conflict_refused(self):
        """回归（A2）：同 plan_id 跨项目整行覆盖必须拒绝；同项目重算合法。"""
        sqlite_store.save_plan(_record("P1", "甲", "optimal", None, 100000, "p1"),
                               plan_id="p1", db=self.db)
        with self.assertRaises(sqlite_store.PlanOwnershipError):
            sqlite_store.save_plan(_record("P2", "乙", "optimal", None, 1, "p1"),
                                   plan_id="p1", db=self.db)
        sqlite_store.save_plan(_record("P1", "甲", "optimal", None, 200000, "p1"),
                               plan_id="p1", db=self.db)
        self.assertEqual(sqlite_store.load_plan("p1", db=self.db)["project_id"], "P1")

    def test_finalized_plan_write_lock(self):
        """回归（A4）：已定稿方案的写入/删除一律拒绝，取消定稿后恢复。"""
        sqlite_store.save_plan(_record("P1", "甲", "optimal", None, 1, "p1"),
                               plan_id="p1", db=self.db)
        self.assertTrue(sqlite_store.mark_finalized("p1", db=self.db))
        with self.assertRaises(sqlite_store.StoreWriteLockedError):
            sqlite_store.save_plan(_record("P1", "甲", "optimal", None, 2, "p1"),
                                    plan_id="p1", db=self.db)
        with self.assertRaises(sqlite_store.StoreWriteLockedError):
            sqlite_store.delete_plan("p1", db=self.db)
        self.assertTrue(sqlite_store.mark_finalized("p1", finalized=False, db=self.db))
        self.assertTrue(sqlite_store.delete_plan("p1", db=self.db))

    def test_finalized_mutual_exclusion_by_project_id_only(self):
        """回归（A3）：同名不同项目（P1/P2）的定稿互不取消。"""
        sqlite_store.save_plan(_record("P1", "同名项目", "optimal", None, 1, "a"),
                               plan_id="a", db=self.db)
        sqlite_store.save_plan(_record("P2", "同名项目", "optimal", None, 1, "b"),
                               plan_id="b", db=self.db)
        self.assertTrue(sqlite_store.mark_finalized("a", db=self.db))
        self.assertTrue(sqlite_store.mark_finalized("b", db=self.db))
        self.assertTrue(sqlite_store.load_plan("a", db=self.db)["finalized"])
        self.assertTrue(sqlite_store.load_plan("b", db=self.db)["finalized"])


class SqliteStoreGroupTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "quote.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed(self) -> str:
        g = sqlite_store.create_group("P1", "项目甲", target_total=120000, db=self.db)
        gid = g["group_id"]
        sqlite_store.save_plan(_record("P1", "项目甲", "optimal", gid, 120000, "opt"),
                               plan_id="opt", db=self.db)
        sqlite_store.upsert_slot(gid, "optimal", "opt", db=self.db)
        return gid

    def test_create_and_slot_wiring(self) -> None:
        gid = self._seed()
        self.assertEqual(sqlite_store.find_slot_plan_id(gid, "optimal", db=self.db), "opt")
        self.assertEqual(sqlite_store.find_group_by_plan_id("opt", db=self.db), gid)
        # 未挂槽的空组
        g = sqlite_store.create_group("P1", "项目甲", db=self.db)
        self.assertIsNone(sqlite_store.find_slot_plan_id(g["group_id"], "optimal", db=self.db))

    def test_rename_and_finalize(self) -> None:
        gid = self._seed()
        self.assertTrue(sqlite_store.rename_group(gid, "新组名", db=self.db))
        self.assertEqual(sqlite_store.find_group_by_id(gid, db=self.db)["group_name"], "新组名")
        self.assertTrue(sqlite_store.group_finalize(gid, db=self.db))
        self.assertTrue(sqlite_store.find_group_by_id(gid, db=self.db)["finalized"])
        self.assertTrue(sqlite_store.group_finalize(gid, finalized=False, db=self.db))
        self.assertFalse(sqlite_store.find_group_by_id(gid, db=self.db)["finalized"])
        self.assertFalse(sqlite_store.rename_group("ghost", "x", db=self.db))

    def test_list_groups_and_by_project(self) -> None:
        self._seed()
        sqlite_store.create_group("P2", "项目乙", db=self.db)
        self.assertEqual(len(sqlite_store.list_groups(db=self.db)), 2)
        self.assertEqual(len(sqlite_store.list_groups_for_project("P1", db=self.db)), 1)
        self.assertEqual(len(sqlite_store.list_groups_for_project("P2", db=self.db)), 1)
        # 槽位摘要带上金额
        first = sqlite_store.list_groups(db=self.db)[0]
        slot = (first["strategy_slots"] or {}).get("A")
        if slot and slot.get("plan_id"):
            self.assertEqual((slot["summary"])["target_total"], 120000)

    def test_copy_group_deep_copy(self) -> None:
        gid = self._seed()
        cp = sqlite_store.copy_group(gid, db=self.db)
        self.assertIsNotNone(cp)
        self.assertNotEqual(cp["group_id"], gid)
        cp_slot = cp["strategy_slots"]["A"]
        self.assertNotEqual(cp_slot["plan_id"], "opt")
        cp_rec = sqlite_store.load_plan(cp_slot["plan_id"], db=self.db)
        self.assertEqual(cp_rec["group_id"], cp["group_id"])
        self.assertTrue(cp_rec["is_copy"])
        self.assertEqual((cp_rec["params"])["target_total"], 120000)
        # 源组不受影响
        self.assertEqual(sqlite_store.find_slot_plan_id(gid, "optimal", db=self.db), "opt")

    def test_delete_group_cascade(self) -> None:
        gid = self._seed()
        self.assertTrue(sqlite_store.delete_group(gid, keep_plans=False, db=self.db))
        self.assertIsNone(sqlite_store.load_plan("opt", db=self.db))
        self.assertIsNone(sqlite_store.find_group_by_id(gid, db=self.db))
        self.assertFalse(sqlite_store.delete_group(gid, db=self.db))

    def test_finalized_group_locks_edits(self) -> None:
        """回归（A4）：已定稿组拒绝删除/改名/挂槽；取消定稿是唯解锁路径。"""
        gid = self._seed()
        self.assertTrue(sqlite_store.group_finalize(gid, db=self.db))
        with self.assertRaises(sqlite_store.StoreWriteLockedError):
            sqlite_store.delete_group(gid, db=self.db)
        with self.assertRaises(sqlite_store.StoreWriteLockedError):
            sqlite_store.rename_group(gid, "新名", db=self.db)
        with self.assertRaises(sqlite_store.StoreWriteLockedError):
            sqlite_store.upsert_slot(gid, "optimal", "ghost", db=self.db)
        self.assertTrue(sqlite_store.group_finalize(gid, finalized=False, db=self.db))
        self.assertTrue(sqlite_store.rename_group(gid, "新名", db=self.db))

    def test_delete_plan_clears_slot_pointer(self) -> None:
        """回归（A4）：删方案同步清槽位，不得悬挂指向已删方案。"""
        gid = self._seed()
        self.assertTrue(sqlite_store.delete_plan("opt", db=self.db))
        slot = sqlite_store._load_slots(gid, db=self.db)["A"]
        self.assertIsNone(slot["plan_id"])
        self.assertEqual(slot["status"], "pending")


class SqliteStoreMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = self.root / "user"
        self.db = self.root / "user" / ".sqlite" / "quote.db"
        self._build_tree()

    def _build_tree(self) -> None:
        proj = self.source / "项目甲"
        proj.mkdir(parents=True, exist_ok=True)
        fs_save_plan(_record("P1", "项目甲", "optimal", "g-a", 100000, "a" * 8),
                     plan_id="a" * 8, dir_path=self.source)
        fs_save_plan(_record("P1", "项目甲", "uniform", "g-a", 101000, "b" * 8),
                     plan_id="b" * 8, dir_path=self.source)
        groups = {"groups": [{
            "group_id": "g-a", "project_id": "P1", "project_name": "项目甲",
            "group_name": "目标报价 · 第1组",
            "strategy_slots": {"A": {"plan_id": "a" * 8, "status": "computed"},
                               "B": {"plan_id": "b" * 8, "status": "computed"},
                               "C": {"plan_id": None, "status": "pending"}},
            "computed_at": "2026-09-01T00:00:00", "saved_at": "2026-09-01T00:00:00",
            "finalized": False, "finalized_at": None, "parent_group_id": None}]}
        (proj / ".groups.json").write_text(json.dumps(groups, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_import_json_tree_idempotent(self) -> None:
        plans, groups = sqlite_store.import_json_tree(source_dir=self.source, db=self.db)
        self.assertEqual(plans, 2)
        self.assertEqual(groups, 1)
        # 幂等：重跑不产生重复行
        sqlite_store.import_json_tree(source_dir=self.source, db=self.db)
        self.assertEqual(len(sqlite_store.list_plans(self.db)), 2)
        self.assertEqual(len(sqlite_store.list_groups(self.db)), 1)
        # 迁移后的组槽位与方案摘要关联正确
        g = sqlite_store.find_group_by_id("g-a", db=self.db)
        self.assertEqual(g["strategy_slots"]["A"]["plan_id"], "a" * 8)


class SqliteStoreAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "quote.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_and_list_with_filters(self) -> None:
        sqlite_store.append_audit("alice", "quote.optimize", "PASS", project_id="P1",
                                  plan_id="p1", group_id="g1", objective="opt",
                                  detail={"target": 100000}, db=self.db)
        sqlite_store.append_audit("alice", "project.overview.delete", "PASS",
                                  project_id="P2", db=self.db)
        rows = sqlite_store.list_audit(db=self.db)
        self.assertEqual(len(rows), 2)
        newest = rows[0]
        self.assertEqual(newest["action"], "project.overview.delete")
        self.assertEqual(newest["detail"], None)
        # 过滤 action
        opt = sqlite_store.list_audit(action="quote.optimize", db=self.db)
        self.assertEqual(len(opt), 1)
        self.assertEqual(opt[0]["plan_id"], "p1")
        self.assertEqual(opt[0]["detail"]["target"], 100000)
        # 过滤 user
        self.assertEqual(len(sqlite_store.list_audit(user="bob", db=self.db)), 0)
        self.assertEqual(len(sqlite_store.list_audit(user="alice", db=self.db)), 2)
        # limit
        self.assertEqual(len(sqlite_store.list_audit(limit=1, db=self.db)), 1)


if __name__ == "__main__":
    unittest.main()
