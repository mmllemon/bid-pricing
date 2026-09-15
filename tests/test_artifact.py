"""§7.1.1 断言 4（字段有效性判据机械化）与断言 1（未定态表示法）的测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.artifact import (
    PLACEHOLDER_PATTERN,
    ArtifactNotFreezable,
    ArtifactRecord,
    compute_artifact_hash,
    freeze_record,
    verify_enum,
    verify_versioned,
)
from bidpricing.states import Status


def _write(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class PlaceholderBlacklistTest(unittest.TestCase):
    """断言 4② ：占位符黑名单 —— 逐字采用路线原文正则。"""

    def test_pattern_is_verbatim_from_plan(self):
        self.assertEqual(
            PLACEHOLDER_PATTERN, r"(?i)(todo|tbd|fixme|draft|placeholder|待|暂)"
        )

    def test_short_samples_are_rejected(self):
        """路线点名的两个漏网样例：TBD_v2 与 待确认_2026。"""
        for rec in (
            ArtifactRecord(key="k", version="TBD_v2", hash="sha256:" + "a" * 12,
                           frozen_at="2026-09-16T00:00:00+00:00",
                           artifact_path="x.json"),
            ArtifactRecord(key="k", version="sha256:" + "a" * 12, hash="sha256:" + "a" * 12,
                           frozen_at="待确认_2026", artifact_path="x.json"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                _write(Path(tmp) / "x.json", {"k": 1})
                item = verify_versioned(rec, Path(tmp))
            self.assertIs(item.status, Status.BLOCKED)
            self.assertIn("占位符黑名单命中", item.reason)


class FreezeTest(unittest.TestCase):
    def test_freeze_writes_three_metadata_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            _write(cdir / "artifact.json", {"hello": "world"})
            registry = {
                "gate_0a": {
                    "artifact_version": {
                        "kind": "versioned", "artifact_path": "artifact.json",
                        "version": None, "hash": None, "frozen_at": None,
                    }
                }
            }
            rec = freeze_record(registry, "gate_0a", "artifact_version", cdir)
            self.assertTrue(rec.is_frozen)
            self.assertTrue(rec.hash.startswith("sha256:"))
            self.assertEqual(len(rec.hash) - len("sha256:"), 12)
            self.assertEqual(rec.hash, compute_artifact_hash(cdir / "artifact.json"))
            item = verify_versioned(rec, cdir)
            self.assertIs(item.status, Status.PASS)

    def test_freeze_refuses_self_declared_incomplete_artifact(self):
        """防止把未完成制品冻成"已通过"——Gate 0a 的关键安全阀。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            _write(cdir / "partial.json", {"freeze_blocker": "分类表为空，依赖真实清单"})
            registry = {
                "gate_0a": {
                    "partial_version": {
                        "kind": "versioned", "artifact_path": "partial.json",
                        "version": None, "hash": None, "frozen_at": None,
                    }
                }
            }
            with self.assertRaises(ArtifactNotFreezable):
                freeze_record(registry, "gate_0a", "partial_version", cdir)
            self.assertIsNone(registry["gate_0a"]["partial_version"]["hash"])

    def test_hash_mismatch_is_blocked(self):
        """制品改动后未重新冻结 → 契约失效。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            target = _write(cdir / "artifact.json", {"v": 1})
            registry = {
                "gate_0a": {
                    "artifact_version": {
                        "kind": "versioned", "artifact_path": "artifact.json",
                        "version": None, "hash": None, "frozen_at": None,
                    }
                }
            }
            rec = freeze_record(registry, "gate_0a", "artifact_version", cdir)
            _write(target, {"v": 2})  # 制品被改动
            item = verify_versioned(rec, cdir)
            self.assertIs(item.status, Status.BLOCKED)
            self.assertIn("hash 失配", item.reason)


class EnumFieldTest(unittest.TestCase):
    """断言 1 / 2：adjustment_scope 的未定态必须是 key 缺失。"""

    REC = ArtifactRecord(
        key="adjustment_scope", kind="enum", allowed=("FULL", "SEGMENT")
    )

    def test_missing_key_is_blocked_as_undetermined(self):
        item = verify_enum(self.REC, None, "T00-08")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("未定态", item.reason)

    def test_valid_values_pass(self):
        for value in ("FULL", "SEGMENT"):
            item = verify_enum(self.REC, value, "T00-08")
            self.assertIs(item.status, Status.PASS, value)

    def test_non_enum_strings_are_blocked(self):
        """v3.2 的熔断点正是被这类非空字符串绕过的。"""
        for value in ("未定", "UNDETERMINED", "PENDING", "pending", "待定"):
            item = verify_enum(self.REC, value, "T00-08")
            self.assertIs(item.status, Status.BLOCKED, value)


if __name__ == "__main__":
    unittest.main()
