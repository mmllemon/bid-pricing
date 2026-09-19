"""H-012 部署基础设施单元测试：用户目录隔离 + 访问日志。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.deployment import log_event, safe_user, user_scope


class SafeUserTest(unittest.TestCase):
    def test_cleans_unsafe_chars(self):
        uid = safe_user("张 三/..\\root:1")
        # 不允许路径分隔符；不会成为危险的 "." 或 ".." 裸段
        self.assertNotIn("/", uid)
        self.assertNotIn("\\", uid)
        self.assertNotIn(":", uid)
        self.assertNotIn(uid, (".", ".."))
        # 点号仍被允许用于像 v1.2 这样的合法用户名
        self.assertEqual(safe_user("alice.v1.2"), "alice.v1.2")

    def test_all_dots_collapse_to_default(self):
        self.assertEqual(safe_user("..."), "default")
        self.assertEqual(safe_user(".."), "default")

    def test_default_when_empty(self):
        self.assertEqual(safe_user("   "), "default")
        self.assertEqual(safe_user(None), "default")

    def test_truncates_long(self):
        self.assertEqual(len(safe_user("x" * 400)), 64)

    def test_preserves_safe_names(self):
        self.assertEqual(safe_user("leema"), "leema")


class UserScopeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_scopes_per_user(self):
        a = user_scope(self.base, "alice")
        b = user_scope(self.base, "bob")
        self.assertTrue(a.exists())
        self.assertTrue(b.exists())
        self.assertNotEqual(a, b)
        self.assertEqual(a.name, "alice")

    def test_two_users_isolated(self):
        (user_scope(self.base, "alice") / "p1.json").write_text("{}", encoding="utf-8")
        # bob 目录不应看到 alice 的方案
        self.assertFalse((user_scope(self.base, "bob") / "p1.json").exists())


class LogEventTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.logdir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_jsonl_with_fields(self):
        path = log_event(self.logdir, "alice", "GET /api/health", 200,
                         project_id="P1", objective=123.4)
        self.assertTrue(path.exists())
        records = [json.loads(l) for l in path.read_text(encoding="utf-8").strip().splitlines()]
        self.assertEqual(len(records), 1)
        line = records[0]
        self.assertEqual(line["endpoint"], "GET /api/health")
        self.assertEqual(line["outcome"], 200)
        self.assertEqual(line["user"], "alice")
        self.assertEqual(line["project_id"], "P1")
        self.assertEqual(line["objective"], 123.4)
        self.assertIn("ts", line)

    def test_append_across_calls(self):
        log_event(self.logdir, "u", "a", 200)
        path = log_event(self.logdir, "u", "b", 404)
        records = [json.loads(l) for l in path.read_text(encoding="utf-8").strip().splitlines()]
        self.assertEqual(len(records), 2)

    def test_endpoint_outcome_required(self):
        self.assertRaises(TypeError, log_event, self.logdir, "u", "x")


if __name__ == "__main__":
    unittest.main()