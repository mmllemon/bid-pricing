"""schema 注册表一致性测试：_SCHEMA 的 DDL 对象必须与 _SCHEMA_OBJECTS 一一对应。

回归背景（2026-10-08）：B-P1-2 双真相收敛给 _SCHEMA 加了 project 表与两个索引，
但漏登记 _SCHEMA_OBJECTS。老库其余对象齐备 → _schema_complete() 判"完整" →
跳过 executescript → project 表永远建不出来 → /api/overview 全线 500
（no such table: project），且启动时的 projects.json 迁移也被静默拖死。

本测试不连库、纯静态比对两份清单，改 _SCHEMA 忘改注册表即刻红。
"""
from __future__ import annotations

import re
import unittest

from bidpricing import sqlite_store

_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", re.IGNORECASE)
_INDEX_RE = re.compile(r"CREATE INDEX IF NOT EXISTS\s+(\w+)", re.IGNORECASE)


def _ddl_objects() -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for m in _TABLE_RE.finditer(sqlite_store._SCHEMA):
        out.add(("table", m.group(1)))
    for m in _INDEX_RE.finditer(sqlite_store._SCHEMA):
        out.add(("index", m.group(1)))
    return out


class SchemaRegistryTest(unittest.TestCase):
    def test_registry_matches_ddl(self):
        ddl = _ddl_objects()
        reg = set(sqlite_store._SCHEMA_OBJECTS)
        self.assertEqual(
            reg, ddl,
            msg=(f"_SCHEMA_OBJECTS 与 _SCHEMA 漂移：漏登记={sorted(ddl - reg)}，"
                 f"多登记（DDL 里没有）={sorted(reg - ddl)}。"
                 "改 _SCHEMA 必须同步改 _SCHEMA_OBJECTS，否则老库会被误判完整而缺表。"),
        )

    def test_no_duplicate_entries(self):
        reg = list(sqlite_store._SCHEMA_OBJECTS)
        self.assertEqual(len(reg), len(set(reg)), "_SCHEMA_OBJECTS 有重复条目")


if __name__ == "__main__":
    unittest.main()
