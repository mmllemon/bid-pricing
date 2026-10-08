"""原子文件写的判据（B-P1-3）。

背景
----
全仓状态型持久文件统一走 ``atomic_io``（``mkstemp`` 唯一临时名 + ``fsync`` +
``os.replace``）。``project_overview._write_all`` 历史上是自造的内联 tmp+replace
（临时名固定 ``<name>.tmp``、无 fsync），已于 2026-10-08 并入本模块。

三条判据各钉一个真实失败形态：
1. **崩溃/失败不留半成品**——写中途抛错时目标文件保持旧内容完整，且临时文件被清理。
2. **临时名唯一**——并发写同一目标不得互相踩踏（固定临时名会让两次写共用一个文件，
   其中一个的 ``os.replace`` 可能搬走另一个尚未写完的内容）。
3. **``project_overview`` 确实走本入口**——防止它被改回手写（用无 fsync 的实现也能
   通过功能测试，故需要有区分度的判据：把 ``atomic_io.atomic_write_text`` 探针替换后
   确认调用链真的经过它）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bidpricing import atomic_io, project_overview


class AtomicWriteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_writes_content_and_leaves_no_temp(self) -> None:
        target = self.dir / "a.json"
        atomic_io.atomic_write_text(target, '{"k":1}')
        self.assertEqual(target.read_text(encoding="utf-8"), '{"k":1}')
        leftovers = [p.name for p in self.dir.iterdir() if p.name != "a.json"]
        self.assertEqual(leftovers, [], f"不应留下临时文件：{leftovers}")

    def test_failure_keeps_old_content_intact(self) -> None:
        """失败注入：写入途中失败时，旧文件必须完好，临时文件被清理。"""
        target = self.dir / "b.json"
        target.write_text("OLD", encoding="utf-8")
        boom = RuntimeError("injected fsync failure")
        with mock.patch("os.fsync", side_effect=boom):
            with self.assertRaises(RuntimeError):
                atomic_io.atomic_write_text(target, "NEW")
        self.assertEqual(target.read_text(encoding="utf-8"), "OLD", "失败后旧内容须完好")
        leftovers = [p.name for p in self.dir.iterdir() if p.name != "b.json"]
        self.assertEqual(leftovers, [], f"失败后须清理临时文件：{leftovers}")

    def test_temp_name_is_unique_under_concurrency(self) -> None:
        """并发写同一目标：两次调用不得共用一个临时文件名。

        直接观测两次 mkstemp 产出的临时名不同（用真实并发不够稳定，故断言
        实现确实经由 mkstemp 派生唯一名——通过 patch 记录临时名并对比）。
        """
        target = self.dir / "c.json"
        names: list[str] = []
        real_mkstemp = tempfile.mkstemp

        def spy(*a, **k):
            fd, name = real_mkstemp(*a, **k)
            names.append(name)
            return fd, name

        with mock.patch("tempfile.mkstemp", side_effect=spy):
            atomic_io.atomic_write_text(target, "one")
            atomic_io.atomic_write_text(target, "two")
        self.assertGreaterEqual(len(names), 2)
        self.assertEqual(len(names), len(set(names)), f"临时名必须唯一：{names}")
        self.assertEqual(target.read_text(encoding="utf-8"), "two")


class ProjectOverviewAtomicWriteTest(unittest.TestCase):
    """B-P1-2 后：project_overview 走 SQLite（WAL+事务保证原子性），
    不再经由 atomic_write_text 写 projects.json。"""

    def setUp(self) -> None:
        from bidpricing import project_store, sqlite_store
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = project_store.PROJECTS_DIR
        self._saved_ss = sqlite_store.PROJECTS_DIR
        project_store.PROJECTS_DIR = Path(self._tmp.name)
        sqlite_store.PROJECTS_DIR = Path(self._tmp.name)

    def tearDown(self) -> None:
        from bidpricing import project_store, sqlite_store
        project_store.PROJECTS_DIR = self._saved
        # 两个模块级变量都要还原：只恢复 project_store 会把 sqlite_store 的
        # PROJECTS_DIR 漏在已删除的临时目录上，后续测试写库直接报错。
        sqlite_store.PROJECTS_DIR = self._saved_ss
        self._tmp.cleanup()

    def test_write_goes_through_sqlite(self) -> None:
        """create_project 应写入 SQLite project 表（而非 JSON 文件）。"""
        from bidpricing import sqlite_store
        rec = project_overview.create_project({"name": "原子写项目"})
        self.assertTrue(rec.get("id"))
        # 直接查 SQLite 确认落盘
        row = sqlite_store.get_project(rec["id"])
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "原子写项目")
        # 不应再产生 projects.json
        pj = Path(self._tmp.name) / "projects.json"
        self.assertFalse(pj.exists(), "不应再写 projects.json")

    def test_create_project_persists_and_no_leftover_tmp(self) -> None:
        rec = project_overview.create_project({"name": "落盘项目"})
        self.assertTrue(rec.get("id"))
        again = project_overview.load_all()
        self.assertTrue(any(p["id"] == rec["id"] for p in again))
        leftovers = [p.name for p in Path(self._tmp.name).iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [], f"不应留下固定名 .tmp：{leftovers}")


if __name__ == "__main__":
    unittest.main()