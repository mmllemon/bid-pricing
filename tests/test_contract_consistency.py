"""跨制品契约一致性判据的测试。

测试策略：把**真实** config/ 复制到临时目录后做**定向突变**——这样用例锁住的是
真实制品之间的一致性，而不是一组手写的替身（替身会与真实制品一起漂移，
那样测试通过也不代表仓库自洽）。

重点用例是 :meth:`EnumAgreementTest.test_historical_code_system_spelling_bug_blocks`：
它**精确复现** 2026-09-16 靠人眼才发现的那次事故，作为回归锁。
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from bidpricing.contracts.consistency import ARTIFACTS, check_contract_consistency
from bidpricing.paths import config_dir
from bidpricing.states import Status

_REAL_CONFIG = config_dir()


class _MutatingCase(unittest.TestCase):
    """把真实 config/ 复制到临时目录，允许定向改写后执行判据。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cdir = Path(self._tmp.name) / "config"
        shutil.copytree(_REAL_CONFIG, self.cdir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def _load(self, key: str) -> dict:
        return json.loads((self.cdir / ARTIFACTS[key]).read_text(encoding="utf-8"))

    def _save(self, key: str, data: dict) -> None:
        (self.cdir / ARTIFACTS[key]).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _check(self) -> list:
        return check_contract_consistency(self.cdir)

    def _item(self, name: str):
        return next(i for i in self._check() if i.item == name)


class RealRepoTest(_MutatingCase):
    """未突变的真实仓库必须全绿——否则判据本身是坏的。"""

    def test_real_repo_passes(self):
        items = self._check()
        bad = [i for i in items if i.status is not Status.PASS]
        self.assertEqual(bad, [], [i.to_dict() for i in bad])
        self.assertEqual(len(items), 10)

    def test_missing_artifact_blocks_not_vacuous(self):
        (self.cdir / ARTIFACTS["constraint_schema"]).unlink()
        items = self._check()
        self.assertEqual(len(items), 1)
        self.assertIs(items[0].status, Status.BLOCKED)
        self.assertIn("缺失", items[0].reason)

    def test_corrupt_json_blocks(self):
        (self.cdir / ARTIFACTS["field_schema"]).write_text("{not json", encoding="utf-8")
        items = self._check()
        self.assertIs(items[0].status, Status.BLOCKED)
        self.assertIn("JSON 解析失败", items[0].reason)


class FieldSchemaTest(_MutatingCase):
    def test_duplicate_field_names_block(self):
        art = self._load("field_schema")
        art["fields"].append(dict(art["fields"][0]))
        self._save("field_schema", art)
        item = self._item("field_schema.唯一性")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertEqual(item.actual, [art["fields"][0]["name"]])

    def test_illegal_missing_policy_blocks(self):
        art = self._load("field_schema")
        art["fields"][0]["missing_policy"] = "SHOUT"
        self._save("field_schema", art)
        item = self._item("field_schema.missing_policy")
        self.assertIs(item.status, Status.BLOCKED)

    def test_default_on_forbidden_family_blocks(self):
        """禁止 DEFAULT 的字段族（成本/限价/税费/合同口径）不得带默认值。"""
        art = self._load("field_schema")
        next(f for f in art["fields"] if f["name"] == "c_i").update(
            {"default": 0.0, "missing_policy": "DEFAULT"}
        )
        self._save("field_schema", art)
        item = self._item("field_schema.no_default_family")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("c_i", item.actual)


class EnumAgreementTest(_MutatingCase):
    """本类锁住 2026-09-16 的真实事故：两个本应相等的枚举用了两种写法。"""

    def test_two_spellings_in_real_repo_are_currently_consistent(self):
        item = self._item("field_schema.enum_agreement")
        self.assertIs(item.status, Status.PASS)
        # 逐字一致：不能出现不带斜杠的 GBT50500 形式
        self.assertNotIn("GBT50500-2024", str(item.actual))

    def test_historical_code_system_spelling_bug_blocks(self):
        """**回归锁**：把 code_system 改回事故时的写法（去掉斜杠）必须被判 BLOCKED。

        反向断言的必要性：若判据先做归一化（去斜杠、统一大小写）再比对，
        ``GBT50500-2024`` 与 ``GB/T50500-2024`` 会被折叠成同一个值，
        判据就会**放过它本要拦的那个 bug**——等于判据自我取消。
        """
        art = self._load("field_schema")
        cs = next(f for f in art["fields"] if f["name"] == "code_system")
        self.assertEqual(cs["range"], ["GB50500-2013", "GB/T50500-2024"])  # 前提
        cs["range"] = ["GB50500-2013", "GBT50500-2024"]  # 事故时的写法
        self._save("field_schema", art)

        item = self._item("field_schema.enum_agreement")
        self.assertIs(item.status, Status.BLOCKED, item.to_dict())
        self.assertIn("GBT50500-2024", json.dumps(item.actual, ensure_ascii=False))
        # 归一化后二者等价——若判据做了归一化，本断言就是唯一能揭穿它的地方
        rule_set_id = next(f for f in art["fields"] if f["name"] == "rule_set_id")
        self.assertEqual(
            {x.replace("/", "") for x in rule_set_id["range"]},
            {x.replace("/", "") for x in cs["range"]},
        )


class ConstraintInputsTest(_MutatingCase):
    """约束引用的输入必须是字段字典里真实存在的字段。"""

    def test_all_constraints_inputs_declared_in_real_repo(self):
        item = self._item("constraint_schema.inputs_declared")
        self.assertIs(item.status, Status.PASS)
        self.assertIn("13 条约束", item.reason)

    def test_constraint_referencing_undeclared_field_blocks(self):
        """模拟「新增约束但忘记同步字段字典」——C13 引入时的真实风险。"""
        art = self._load("constraint_schema")
        c13 = next(c for c in art["constraints"] if c["id"] == "C13")
        c13["inputs"] = list(c13["inputs"]) + ["unbalanced_tolerance_side"]
        self._save("constraint_schema", art)

        item = self._item("constraint_schema.inputs_declared")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("C13", item.actual)
        self.assertEqual(item.actual["C13"], ["unbalanced_tolerance_side"])

    def test_removing_a_declared_field_blocks(self):
        """反向：把 C13 依赖的字段从字典里删掉，同样必须 BLOCKED。

        两个方向都测，是因为「约束多引用」与「字段被误删」是同一失效模式的两面。
        """
        art = self._load("field_schema")
        art["fields"] = [f for f in art["fields"] if f["name"] != "unbalanced_clause"]
        self._save("field_schema", art)
        item = self._item("constraint_schema.inputs_declared")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("unbalanced_clause", json.dumps(item.actual, ensure_ascii=False))

    def test_unknown_tolerance_blocks(self):
        art = self._load("constraint_schema")
        next(c for c in art["constraints"] if c["id"] == "C13")["tolerance"] = "eps_imaginary"
        self._save("constraint_schema", art)
        item = self._item("constraint_schema.tolerance_defined")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertEqual(item.actual, {"C13": "eps_imaginary"})


class ListingStructureTest(_MutatingCase):
    def test_six_sheets_declared(self):
        item = self._item("listing_structure.sheets")
        self.assertIs(item.status, Status.PASS)
        self.assertEqual(item.expected, 6)

    def test_missing_listing_structure_blocks(self):
        art = self._load("input_protocol_schema")
        del art["listing_structure"]
        self._save("input_protocol_schema", art)
        item = self._item("input_protocol.listing_structure")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("示例模板", item.reason)

    def test_sheet_count_mismatch_blocks(self):
        art = self._load("input_protocol_schema")
        art["listing_structure"]["sheets"] = art["listing_structure"]["sheets"][:5]
        self._save("input_protocol_schema", art)
        item = self._item("listing_structure.sheets")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertEqual(item.actual, 5)

    def test_alias_less_field_blocks(self):
        """没有别名的逻辑字段 = 硬编码列名 = 换一个计价软件即失效。"""
        art = self._load("input_protocol_schema")
        art["listing_structure"]["column_aliases"]["unit_price"] = {"logical": "cap"}
        self._save("input_protocol_schema", art)
        item = self._item("listing_structure.column_aliases")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertEqual(item.actual, ["unit_price"])

    def test_missing_empty_vs_absent_rule_blocks(self):
        art = self._load("input_protocol_schema")
        del art["listing_structure"]["empty_vs_absent"]
        self._save("input_protocol_schema", art)
        item = self._item("listing_structure.empty_vs_absent")
        self.assertIs(item.status, Status.BLOCKED)


class OpenIssuesTest(_MutatingCase):
    """ADR-0007 的机械部分：被纠正过的条目必须留用户原话，不得静默改写。"""

    def test_resolved_without_decision_blocks(self):
        art = self._load("input_protocol_schema")
        oi = next(o for o in art["open_issues"] if o["id"] == "OI-01")
        del oi["decision"]
        self._save("input_protocol_schema", art)
        item = self._item("input_protocol.open_issues")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("OI-01", item.actual[0])

    def test_correction_without_user_words_blocks(self):
        """有 correction 但不记用户原话 → 无法复核记录者的转述是否忠实。"""
        art = self._load("input_protocol_schema")
        oi = next(o for o in art["open_issues"] if o["id"] == "OI-04")
        del oi["correction"]["user_actual_words"]
        self._save("input_protocol_schema", art)
        item = self._item("input_protocol.open_issues")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("未记录用户原话", item.reason)

    def test_oi04_keeps_the_correction_trail(self):
        """OI-04 必须**永久**保留纠正留痕——这正是本条目的价值所在。"""
        art = self._load("input_protocol_schema")
        oi = next(o for o in art["open_issues"] if o["id"] == "OI-04")
        self.assertIn("correction", oi)
        self.assertIn("没有给出单价下限", oi["correction"]["what_was_wrong"])
        self.assertIn("不能为0", oi["correction"]["user_actual_words"])
        self.assertIn("ADR-0007", oi["correction"]["failure_mode"])


class BoundClauseTest(_MutatingCase):
    """本轮变更的业务断言：C3/C5/C13 的新口径必须真的写进制品。"""

    def test_c5_upgraded_to_p0_non_toggleable(self):
        art = self._load("constraint_schema")
        c5 = next(c for c in art["constraints"] if c["id"] == "C5")
        self.assertEqual(c5["severity"], "P0")
        self.assertFalse(c5["toggleable"])
        self.assertIn("zero_price_prohibited", c5["inputs"])
        self.assertEqual(c5["supersedes"], "p_i >= 0（P1，可关，由 C4 蕴含）")

    def test_c3_no_longer_delta_minus_only(self):
        art = self._load("constraint_schema")
        c3 = next(c for c in art["constraints"] if c["id"] == "C3")
        self.assertNotIn("= base_i(1 - delta_eff_i)", c3["expression"])
        self.assertIn("L_i^tender", c3["expression"])
        self.assertIn("supersedes", c3)

    def test_c13_has_both_mechanism_branches(self):
        """机制进 Gate 0a：两条分支都必须声明，缺一条则该机制未被完整定义。"""
        art = self._load("constraint_schema")
        c13 = next(c for c in art["constraints"] if c["id"] == "C13")
        mechs = {b["mechanism"] for b in c13["mechanism_branches"]}
        self.assertEqual(mechs, {"BID_VALIDITY", "SETTLEMENT_ADJUSTMENT", "SCORING", "NONE"})
        self.assertTrue(c13["toggleable"])

    def test_zero_price_field_is_bl_indeed_blocking(self):
        art = self._load("field_schema")
        f = next(x for x in art["fields"] if x["name"] == "zero_price_prohibited")
        self.assertEqual(f["missing_policy"], "BLOCK")
        self.assertIsNone(f["default"])  # 未声明 = key 缺失，不得用 false 冒充

    def test_c4_note_points_at_redefined_c3(self):
        """C3 定义变了，C4 必须显式指出它引用的是**新**定义。"""
        art = self._load("constraint_schema")
        c4 = next(c for c in art["constraints"] if c["id"] == "C4")
        self.assertIn("C3", c4["note"])


if __name__ == "__main__":
    unittest.main()
