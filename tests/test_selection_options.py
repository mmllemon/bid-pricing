"""选择项机制测试 —— ``adjustment_scope`` 作为项目级选择项。

覆盖四类风险：

1. **漂移风险**：``RuleSet.supported_scopes`` 与选择项注册表登记不一致时，
   合法取值集合会出现两个真相源；
2. **默认值风险**：任何形式的默认值都会让"未选择"不可判；
3. **静默覆盖风险**：2013 项目落值 FULL 被悄悄改成 SEGMENT，审计链上留不下痕迹；
4. **审计缺失风险**：落值不带来源与依据时，无法回答"这个口径是谁定的、为什么"。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.contracts.rule_sets import (
    GB50500_2013_RuleSet,
    GBT50500_2024_RuleSet,
)
from bidpricing.contracts.scope_impact import compare_scopes
from bidpricing.contracts.selector import select_rule_set
from bidpricing.gates.gate0 import check_selectable_option
from bidpricing.selection_options import (
    SELECTABLE_OPTIONS,
    SOURCE_CLI,
    SOURCE_FILE,
    SOURCE_RULE_SET,
    clear_option,
    read_option_entry,
    resolve_option,
    write_option,
)
from bidpricing.states import Status

RS13 = GB50500_2013_RuleSet()
RS24 = GBT50500_2024_RuleSet()
SCOPE = SELECTABLE_OPTIONS["adjustment_scope"]


def _empty_registry_rec(allowed=("FULL", "SEGMENT")):
    """构造一个仅含选择项的注册表记录（不触盘）。"""
    from bidpricing.artifact import parse_records

    return parse_records(
        {"gate_0a": {"adjustment_scope": {"kind": "enum", "allowed": list(allowed)}}},
        "gate_0a",
    )[0]


class RegistryTest(unittest.TestCase):
    def test_scope_registered_without_default(self):
        self.assertIn("adjustment_scope", SELECTABLE_OPTIONS)
        self.assertIsNone(SCOPE.default, "选择项不得有默认值（断言 6①）")
        self.assertEqual(SCOPE.gate, "gate_0a")

    def test_allowed_values_depend_on_rule_set(self):
        self.assertEqual(set(SCOPE.allowed_for("GB/T50500-2024")), {"FULL", "SEGMENT"})
        self.assertEqual(SCOPE.allowed_for("GB50500-2013"), ("SEGMENT",))
        self.assertTrue(SCOPE.is_discretionary("GB/T50500-2024"))
        self.assertFalse(SCOPE.is_discretionary("GB50500-2013"))

    def test_registry_matches_rule_set_declarations(self):
        """防漂移：注册表与两套规则集的 supported_scopes 必须一致。"""
        for rule_set in (RS13, RS24):
            self.assertEqual(
                set(SCOPE.allowed_for(rule_set.rule_set_id)),
                set(rule_set.supported_scopes),
                f"{rule_set.rule_set_id} 的 supported_scopes 与选择项注册表不一致",
            )

    def test_undetermined_rule_set_reports_all_known_values(self):
        self.assertEqual(set(SCOPE.allowed_for(None)), {"FULL", "SEGMENT"})


class ResolvePrecedenceTest(unittest.TestCase):
    def test_cli_wins_over_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project_selection.json"
            write_option(path, "adjustment_scope", "SEGMENT",
                         rule_set_id="GB/T50500-2024")
            res = resolve_option("adjustment_scope", "GB/T50500-2024",
                                 cli_value="FULL", path=path)
            self.assertEqual(res.value, "FULL")
            self.assertEqual(res.source, SOURCE_CLI)

    def test_file_used_when_no_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project_selection.json"
            write_option(path, "adjustment_scope", "SEGMENT",
                         rule_set_id="GB/T50500-2024",
                         rationale="招标文件 §12.3", actor="cost-engineer")
            res = resolve_option("adjustment_scope", "GB/T50500-2024", path=path)
            self.assertEqual(res.value, "SEGMENT")
            self.assertEqual(res.source, SOURCE_FILE)
            self.assertEqual(res.actor, "cost-engineer")
            self.assertEqual(res.rationale, "招标文件 §12.3")

    def test_missing_file_means_unselected(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = resolve_option("adjustment_scope", "GB/T50500-2024",
                                 path=Path(tmp) / "nope.json")
            self.assertTrue(res.is_undetermined)
            self.assertIsNone(res.value)
            self.assertEqual(res.source, "UNSELECTED")

    def test_rule_set_determined_value_for_2013(self):
        res = resolve_option("adjustment_scope", "GB50500-2013", path=None)
        self.assertEqual(res.value, "SEGMENT")
        self.assertEqual(res.source, SOURCE_RULE_SET)

    def test_illegal_value_is_rejected(self):
        res = resolve_option("adjustment_scope", "GB/T50500-2024",
                             cli_value="HALF", path=None)
        self.assertTrue(res.is_conflict)
        self.assertIn("不可选", res.errors[0])

    def test_non_enum_string_is_rejected(self):
        """'未定' 这类字符串不得冒充已落值。"""
        res = resolve_option("adjustment_scope", "GB/T50500-2024",
                             cli_value="未定", path=None)
        self.assertTrue(res.is_conflict)

    def test_2013_rejects_full_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project_selection.json"
            write_option(path, "adjustment_scope", "FULL",
                         rule_set_id="GB50500-2013")
            res = resolve_option("adjustment_scope", "GB50500-2013", path=path)
            self.assertTrue(res.is_conflict, res.to_dict())
            self.assertIn("不可选", res.errors[0])

    def test_file_entry_for_other_rule_set_is_conflict(self):
        """落值记录属于另一个规则集时不得沿用。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project_selection.json"
            write_option(path, "adjustment_scope", "FULL",
                         rule_set_id="GB/T50500-2024")
            res = resolve_option("adjustment_scope", "GB50500-2013", path=path)
            self.assertTrue(res.is_conflict)
            self.assertIn("不匹配", res.errors[0])

    def test_conflict_remedy_points_at_a_real_action(self):
        """冲突提示必须指向当前规则集下**真实可做**的动作。

        2013 无选择余地（只有 SEGMENT）→ 提示应是「清除本条落值」，而不是
        「重新选择」——后者在该规则集下是空操作，会把人引到一个不存在的动作上。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project_selection.json"
            write_option(path, "adjustment_scope", "SEGMENT",
                         rule_set_id="GB/T50500-2024")
            res = resolve_option("adjustment_scope", "GB50500-2013", path=path)
            self.assertIn("清除本条落值", res.errors[0])
            self.assertNotIn("重新选择", res.errors[0])

    def test_conflict_remedy_asks_for_reselection_when_discretionary(self):
        """2024 有选择余地 → 提示应是「重新选择」，而非「清除」。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project_selection.json"
            write_option(path, "adjustment_scope", "SEGMENT",
                         rule_set_id="GB50500-2013")
            res = resolve_option("adjustment_scope", "GB/T50500-2024", path=path)
            self.assertIn("重新选择", res.errors[0])
            self.assertNotIn("清除本条落值", res.errors[0])


class SelectionFileTest(unittest.TestCase):
    def test_write_then_clear_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project_selection.json"
            write_option(path, "adjustment_scope", "FULL",
                         rule_set_id="GB/T50500-2024", rationale="r")
            self.assertIsNotNone(read_option_entry(path, "adjustment_scope"))
            clear_option(path, "adjustment_scope")
            self.assertIsNone(read_option_entry(path, "adjustment_scope"))
            self.assertTrue(path.exists())

    def test_cleared_file_has_no_value_key(self):
        """未选择 = 不写 value 字段（与断言 1 同构）。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project_selection.json"
            clear_option(path, "adjustment_scope")
            doc = json.loads(path.read_text(encoding="utf-8"))
            entry = (doc.get("options") or {}).get("adjustment_scope")
            self.assertTrue(entry is None or "value" not in entry)

    def test_repo_selection_file_stays_within_legal_values(self):
        """不变式：仓库落值文件里的取值，必须对其记录时所用规则集合法。

        不要求"仓库此刻未落值"——落值是预期动作；要求的是**一旦落值就合法**。
        """
        from bidpricing.paths import PROJECT_SELECTION, config_dir

        entry = read_option_entry(config_dir() / PROJECT_SELECTION, "adjustment_scope")
        if not entry or not entry.get("value"):
            return
        allowed = SCOPE.allowed_for(entry.get("rule_set_id"))
        self.assertIn(
            entry["value"], allowed,
            f"落值 {entry['value']!r} 对规则集 {entry.get('rule_set_id')} 非法",
        )

    def test_selector_reads_selection_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project_selection.json"
            write_option(path, "adjustment_scope", "FULL",
                         rule_set_id="GB/T50500-2024", rationale="合同未约定分段")
            sel = select_rule_set(contract_date="2026-03-01", selection_file=path)
            self.assertIs(sel.status, Status.PASS, sel.blockers)
            self.assertEqual(sel.adjustment_scope, "FULL")
            self.assertEqual(sel.adjustment_scope_source, SOURCE_FILE)

    def test_selector_ignores_file_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project_selection.json"
            write_option(path, "adjustment_scope", "FULL",
                         rule_set_id="GB/T50500-2024")
            sel = select_rule_set(contract_date="2026-03-01",
                                  selection_file=path, use_project_selection=False)
            self.assertIs(sel.status, Status.BLOCKED)
            self.assertNotIn("adjustment_scope", sel.to_dict())


class GateSelectableOptionTest(unittest.TestCase):
    def test_unselected_passes_at_gate_0a_and_blocks_at_phase_0(self):
        """未落值：Gate 0a 时点只判机制（PASS），Phase 0 时点判取值（BLOCKED）。"""
        selection = {"rule_set_id": "GB/T50500-2024"}
        rec = _empty_registry_rec()

        item = check_selectable_option(rec, selection, phase="gate_0a")
        self.assertIs(item.status, Status.PASS)
        self.assertIn("机制就绪", item.reason)

        item = check_selectable_option(rec, selection, phase="phase_0")
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("无默认值", item.reason)

    def test_valid_value_passes_with_source(self):
        selection = {
            "rule_set_id": "GB/T50500-2024",
            "adjustment_scope": "FULL",
            "adjustment_scope_source": SOURCE_FILE,
        }
        item = check_selectable_option(_empty_registry_rec(), selection)
        self.assertIs(item.status, Status.PASS)
        self.assertIn(SOURCE_FILE, item.reason)

    def test_rule_set_conflict_blocks(self):
        """2013 项目落值 FULL：按规则集取合法集合后必须 BLOCKED。"""
        selection = {"rule_set_id": "GB50500-2013", "adjustment_scope": "FULL"}
        item = check_selectable_option(_empty_registry_rec(), selection)
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("不可选", item.reason)

    def test_selection_without_rule_set_falls_back_to_registry(self):
        """规则集未定但取值在注册表并集内 —— 不因缺 rule_set_id 而崩。"""
        item = check_selectable_option(_empty_registry_rec(), {"adjustment_scope": "SEGMENT"})
        self.assertIs(item.status, Status.PASS)


class ScopeImpactTest(unittest.TestCase):
    def test_increase_side_segment_exceeds_full(self):
        result = compare_scopes(100.0, 130.0, 10.0, rho_plus=0.05)
        data = result["gb_t_50500_2024"]
        self.assertGreater(data["SEGMENT"], data["FULL"])
        self.assertFalse(result["scope_equivalent_here"])
        self.assertTrue(result["segment_equals_2013"])

    def test_decrease_side_scopes_are_equivalent(self):
        result = compare_scopes(100.0, 70.0, 10.0, rho_minus=0.05)
        self.assertTrue(result["scope_equivalent_here"])

    def test_in_range_scopes_are_equivalent(self):
        result = compare_scopes(100.0, 105.0, 10.0, rho_plus=0.05)
        self.assertTrue(result["scope_equivalent_here"])
        self.assertEqual(result["branch"], "IN_RANGE")

    def test_zero_rho_makes_increase_side_equal_and_says_so(self):
        """ρ⁺=0（规范默认）时分叉不可观测——必须显式说明原因，且不得自相矛盾。"""
        result = compare_scopes(100.0, 130.0, 10.0)
        self.assertTrue(result["scope_equivalent_here"])
        self.assertTrue(any("ρ⁺ = ρ⁻ = 0" in n for n in result["notes"]), result["notes"])
        self.assertFalse(
            any("分叉在此显形" in n for n in result["notes"]),
            f"差额为 0 时不得声称分叉显形：{result['notes']}",
        )

    def test_boundary_note_separates_rules_from_optimizer(self):
        result = compare_scopes(100.0, 130.0, 10.0, rho_plus=0.05)
        self.assertIn("4.5 倍", result["rules_to_optimizer_gap"])


class SpecArtifactTest(unittest.TestCase):
    def test_spec_declares_selectable_option_without_default(self):
        from bidpricing.paths import config_dir

        spec = json.loads(
            (config_dir() / "ruleset_selector_spec.json").read_text(encoding="utf-8")
        )
        options = {o["key"]: o for o in spec["selectable_options"]}
        self.assertIn("adjustment_scope", options)
        self.assertIsNone(options["adjustment_scope"]["default"])

    def test_spec_allowed_values_match_code(self):
        from bidpricing.paths import config_dir

        spec = json.loads(
            (config_dir() / "ruleset_selector_spec.json").read_text(encoding="utf-8")
        )
        option = next(o for o in spec["selectable_options"] if o["key"] == "adjustment_scope")
        for rule_set_id, values in option["allowed_by_rule_set"].items():
            self.assertEqual(
                set(values), set(SCOPE.allowed_for(rule_set_id)),
                f"{rule_set_id} 的合法取值在规格制品与代码之间不一致",
            )


if __name__ == "__main__":
    unittest.main()
