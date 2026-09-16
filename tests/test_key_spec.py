"""T01-04A Key 规范制品与 match.py 实现的一致性测试。

规范成文（config/key_spec.json）与机械实现（io/match.py）是**两处表达**——
正是 ADR-0007 / contract-check 要拦的「同一规则两处说法」失效模式。
本测试把两者锁在一起：规范改了实现不改（或反之）即红。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from bidpricing.io.clean import CleanRow
from bidpricing.io.match import match_canonical_rows, match_key

CONFIG = Path(__file__).resolve().parent.parent / "config"
SPEC_PATH = CONFIG / "key_spec.json"


def _mk(item_id, side, *, q=1, p=10, project_id="p1", unit_work="电气"):
    return CleanRow(
        project_id=project_id, unit_work=unit_work, item_id=item_id,
        code_kind="STANDARD", item_name="项", item_feature="", unit="m",
        q0=q if side == "cap" else None,
        q1_point=q if side == "cost" else None,
        cap=p if side == "cap" else None,
        c_i=p if side == "cost" else None,
        no_cap=False, zero_price=False, pass_through=False,
        attribution=None,
        provenance={"side": side, "source_sheet": "s", "source_row": 1,
                    "source_table_no": "表-09"},
    )


class KeySpecConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    def test_spec_exists_and_declares_canonical_key(self):
        self.assertEqual(self.spec["spec_id"], "canonical_key_spec_v1")
        self.assertEqual(
            self.spec["key_definition"]["canonical_key"],
            "(project_id, unit_work, item_id)",
        )

    def test_match_key_matches_spec_fields(self):
        """match_key 的取值必须按规范声明的字段顺序逐位对应。"""
        fields = list(self.spec["key_definition"]["fields"].keys())
        row = _mk("A", "cap")
        self.assertEqual(
            match_key(row), tuple(getattr(row, f) for f in fields))

    def test_spec_bans_row_number_and_name_keys(self):
        banned = self.spec["prohibited_keys"]
        for k in ("row_number", "item_name", "item_name_plus_unit"):
            self.assertIn(k, banned)

    def test_spec_extension_requires_manual_ruling(self):
        """扩展键只能人工触发——规范必须显式写明，不得留给实现自定。"""
        ext = self.spec["key_definition"]["extension_rule"]
        self.assertIn("人工裁定", ext["constraint"])

    def test_duplicate_policy_text_matches_implementation(self):
        """规范写 BLOCK，实现必须真的 blocked=True（双向锁定）。"""
        policy_text = json.dumps(self.spec["duplicate_key_policy"], ensure_ascii=False)
        self.assertIn("禁止自动合并",
                      self.spec["duplicate_key_policy"]["rule"])
        rep = match_canonical_rows(
            [_mk("A", "cap"), _mk("A", "cap")], [_mk("A", "cost")])
        self.assertTrue(rep.blocked)
        # 规范声明的两个异常 kind 与实现常量在文本上互现
        self.assertIn("DUPLICATE_KEY_CAP", policy_text)
        self.assertIn("DUPLICATE_KEY_COST", policy_text)


if __name__ == "__main__":
    unittest.main()
