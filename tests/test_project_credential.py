"""项目凭证存在性校验（B-P1-5）。

背景
----
`optimize_quote` 曾对 `project_id` 形如「任意字符串照单全收」：组归属校验（A2）只在
「组已存在且调用方又声明了一个项目」时比对——传入一个从未存在的 id，只会把组建在
该孤儿名下，无人拦截。修复用**存在性**（而非 UUID 格式）当防线：伪造的合法 UUID
格式挡得住格式校验，挡不住存在性。

判据（刀口只钉一种）：
  - 空字符串 → 放行（前端未选项目的合法空态，保持旧行为）；
  - "当前项目" → 放行（AI 助手 run_calculation 不传 project_id 的哨兵；
    agent-service/server.mjs 的 execute 根本不 append 该字段）；
  - 真实概览 id → 放行；
  - 其余任意字符串 → 403 FORBIDDEN。

隔离：同时 patch `project_store.PROJECTS_DIR` 与 `sqlite_store.PROJECTS_DIR` 到临时
目录（与 test_atomic_io.py 同口径）。只 patch 前者会漏：project_overview.create_project
经 sqlite_store.resolve_db_path() 读的是后者，回归（2026-10-08）：「凭证项目」曾因此
被写进生产库 outputs/projects/leema/.sqlite/quote.db。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bidpricing import project_overview, project_store


class ProjectCredentialTest(unittest.TestCase):
    def setUp(self) -> None:
        # 注意：经营概览的 SQLite 落盘走 sqlite_store.PROJECTS_DIR（调用时解析），
        # 不是 project_store.PROJECTS_DIR——只 patch 后者的话，create_project 会
        # 把"凭证项目"写进真实 quote.db。两个都 patch，保证测试完全隔离。
        from bidpricing import project_store as _ps
        from bidpricing import sqlite_store as _ss
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ps = _ps.PROJECTS_DIR
        self._saved_ss = _ss.PROJECTS_DIR
        _ps.PROJECTS_DIR = Path(self._tmp.name)
        _ss.PROJECTS_DIR = Path(self._tmp.name)
        self._proj = project_overview.create_project({"name": "凭证项目"})

    def tearDown(self) -> None:
        from bidpricing import project_store as _ps
        from bidpricing import sqlite_store as _ss
        _ps.PROJECTS_DIR = self._saved_ps
        _ss.PROJECTS_DIR = self._saved_ss
        self._tmp.cleanup()

    def test_empty_and_sentinel_pass(self) -> None:
        from api.app import _resolve_project_credential
        for pid in ("", "   ", "当前项目"):
            uid, blocked = _resolve_project_credential(pid)
            self.assertIsNone(blocked, f"{pid!r} 应放行")
            self.assertEqual(uid, pid.strip())

    def test_real_project_passes(self) -> None:
        from api.app import _resolve_project_credential
        uid, blocked = _resolve_project_credential(self._proj["id"])
        self.assertIsNone(blocked)
        self.assertEqual(uid, self._proj["id"])

    def test_fake_id_blocked_with_403(self) -> None:
        from api.app import _resolve_project_credential
        uid, blocked = _resolve_project_credential("a" * 32)  # 合法 UUID 格式仍被存在性拦住
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked.status_code, 403)
        body = blocked.body if isinstance(blocked.body, (bytes, bytearray)) else b""
        self.assertIn("FORBIDDEN", body.decode("utf-8", "replace"))
        uid2, blocked2 = _resolve_project_credential("audit-probe-proj")
        self.assertIsNotNone(blocked2, "历史探针用的假 id 也应被拦")

    def test_whitespace_is_stripped_before_check(self) -> None:
        from api.app import _resolve_project_credential
        uid, blocked = _resolve_project_credential(f"  {self._proj['id']}  ")
        self.assertIsNone(blocked)
        self.assertEqual(uid, self._proj["id"])


if __name__ == "__main__":
    unittest.main()