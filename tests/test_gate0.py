"""Gate 0a / 0b 与 §7.1.1 六条断言的测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.artifact import freeze_record, load_registry
from bidpricing.contracts.selector import select_rule_set
from bidpricing.gates.gate0 import (
    GATE_0A_RELEASE_EXCLUSIONS,
    GATE_0B_APPROVAL_ROLES,
    assert_wp4_build_allowed,
    assertion_5_sequence,
    assertion_6_config_zero_defaults,
    check_gate_0a,
    check_gate_0b,
    check_phase0_inputs,
    evaluate_gate_0,
    guard_representation,
)
from bidpricing.paths import GATE0_REGISTRY, config_dir
from bidpricing.states import Status

TECH_ARTIFACTS = {
    "rule_set_selector_spec": "ruleset_selector_spec.json",
    "field_schema_version": "field_schema.json",
    "constraint_schema_version": "constraint_schema.json",
    "precision_profile_version": "precision_profile.json",
    "architecture_decision_version": "architecture_decision.json",
    "competitiveness_classification": "competitiveness_classification.json",
    "input_protocol_schema": "input_protocol_schema.json",
}


def _stub_config(root: Path) -> None:
    """为正向测试构造一套可冻结的最小制品集（不含 freeze_blocker）。"""
    for path in TECH_ARTIFACTS.values():
        (root / path).write_text(
            json.dumps({"schema_id": path}, ensure_ascii=False), encoding="utf-8"
        )


def _stub_registry() -> dict:
    gate_0a = {
        key: {"kind": "versioned", "artifact_path": path,
              "version": None, "hash": None, "frozen_at": None}
        for key, path in TECH_ARTIFACTS.items()
    }
    gate_0a["adjustment_scope"] = {"kind": "enum", "allowed": ["FULL", "SEGMENT"]}
    return {"gate_0a": gate_0a, "gate_0b": {}}


class RepresentationGuardTest(unittest.TestCase):
    """断言 1：未定态必须是 key 缺失。"""

    def test_absent_key_passes(self):
        self.assertIs(guard_representation({}).status, Status.PASS)

    def test_null_value_fails(self):
        item = guard_representation({"adjustment_scope": None})
        self.assertIs(item.status, Status.FAIL)
        self.assertIn("null", item.reason)

    def test_non_enum_string_fails(self):
        for bad in ("未定", "UNDETERMINED", "PENDING"):
            item = guard_representation({"adjustment_scope": bad})
            self.assertIs(item.status, Status.FAIL, bad)
            self.assertIn("熔断点被绕过", item.reason)

    def test_valid_enum_passes(self):
        for good in ("FULL", "SEGMENT"):
            self.assertIs(
                guard_representation({"adjustment_scope": good}).status, Status.PASS
            )


class Gate0aTest(unittest.TestCase):
    def test_positive_path_passes_when_everything_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            _stub_config(cdir)
            registry = _stub_registry()
            for key in TECH_ARTIFACTS:
                freeze_record(registry, "gate_0a", key, cdir)
            report = check_gate_0a(registry, cdir, {"adjustment_scope": "FULL"})
            self.assertIs(report.status, Status.PASS, [i.to_dict() for i in report.items])

    def test_undetermined_scope_does_not_block_0a_but_blocks_phase_0(self):
        """选择项取值未定：Gate 0a 仍 PASS（机制就绪），Phase 0 输入门 BLOCKED。

        这是对早前版本的修正：把「机制是否就绪」与「取值是否已定」拆到
        两个时点判定。取值未定不该阻塞 WP1/WP2/WP3 —— 那两层被要求
        同时实现 FULL / SEGMENT 两条分支，选择只决定哪条生效。
        """
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            _stub_config(cdir)
            registry = _stub_registry()
            for key in TECH_ARTIFACTS:
                freeze_record(registry, "gate_0a", key, cdir)
            report = check_gate_0a(registry, cdir, {})  # key 缺失
            self.assertIs(
                report.status, Status.PASS, [i.to_dict() for i in report.items]
            )
            release = next(i for i in report.items if i.item == "release_scope")
            self.assertIn("WP1 数据层", release.reason)

            # 同一份选择：Phase 0 输入门必须熔断
            phase0 = check_phase0_inputs(registry, {})
            self.assertIs(phase0.status, Status.BLOCKED)
            self.assertIn("adjustment_scope", {i.item for i in phase0.blockers})

    def test_conflicting_scope_blocks_both_phases(self):
        """配置冲突（2013 项目落值 FULL）在两个时点下都必须 BLOCKED。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            _stub_config(cdir)
            registry = _stub_registry()
            for key in TECH_ARTIFACTS:
                freeze_record(registry, "gate_0a", key, cdir)
            selection = {"rule_set_id": "GB50500-2013", "adjustment_scope": "FULL"}
            self.assertIs(check_gate_0a(registry, cdir, selection).status, Status.BLOCKED)
            self.assertIs(check_phase0_inputs(registry, selection).status, Status.BLOCKED)

    def test_release_list_excludes_t00_10b(self):
        """断言 3：放行清单不含 T00-10B（依赖 WP1 的 T01-00B 产出）。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            _stub_config(cdir)
            registry = _stub_registry()
            for key in TECH_ARTIFACTS:
                freeze_record(registry, "gate_0a", key, cdir)
            report = check_gate_0a(registry, cdir, {"adjustment_scope": "SEGMENT"})
            release = next(i for i in report.items if i.item == "release_scope")
            self.assertIn("T00-10B", release.reason)
            self.assertEqual(GATE_0A_RELEASE_EXCLUSIONS[0][0], "T00-10B")

    def test_real_config_0a_blocks_only_on_classification(self):
        """真实仓库现状：技术制品可冻结，``competitiveness_classification`` 空表
        是 Gate 0a 的唯一阻塞项。

        显式关闭项目落值文件——该用例断言"未选择 adjustment_scope"这一状态，
        不得随本机 config/project_selection.json 内容变化。
        """
        cdir = config_dir()
        registry = load_registry(cdir / GATE0_REGISTRY)
        selection = select_rule_set(
            contract_date="2026-03-01", use_project_selection=False
        ).to_dict()
        report = check_gate_0a(registry, cdir, selection)
        self.assertIs(report.status, Status.BLOCKED)
        blocked = {i.item for i in report.blockers}
        self.assertIn("competitiveness_classification", blocked)
        # 机制就绪 → 未落值不再进入 Gate 0a 阻塞清单，但仍出现在判据清单里
        self.assertNotIn("adjustment_scope", blocked)
        self.assertIn("adjustment_scope", {i.item for i in report.items})

        # 同一份选择结果下，Phase 0 输入门因 adjustment_scope 未定而熔断
        phase0 = check_phase0_inputs(registry, selection)
        self.assertIs(phase0.status, Status.BLOCKED)
        self.assertIn("adjustment_scope", {i.item for i in phase0.blockers})


class Gate0bTest(unittest.TestCase):
    def test_real_config_blocked_on_all_items(self):
        cdir = config_dir()
        registry = load_registry(cdir / GATE0_REGISTRY)
        report = check_gate_0b(registry, cdir)
        self.assertIs(report.status, Status.BLOCKED)
        blocked = {i.item for i in report.blockers}
        for field in ("contract_ruleset_version", "cost_basis_spec",
                      "cost_assumption_spec", "q1_assumption_spec", "profit_bridge_spec"):
            self.assertIn(field, blocked)
        self.assertIn("approvals", blocked)

    def test_single_checkbox_cannot_freeze_business_caliber(self):
        """v3.2 的 all_required_approvals=true 可被一人勾选通过——本版必须拦住。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            registry = {
                "gate_0b": {
                    "approvals": {
                        "kind": "approvals",
                        "roles": list(GATE_0B_APPROVAL_ROLES),
                        "signed": {"合同": {"hash": "sha256:" + "a" * 12}},
                    }
                }
            }
            report = check_gate_0b(registry, cdir)
            approvals = next(i for i in report.items if i.item == "approvals")
            self.assertIs(approvals.status, Status.BLOCKED)
            self.assertIn("审批角色不齐", approvals.reason)

    def test_full_approvals_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            registry = {
                "gate_0b": {
                    "approvals": {
                        "kind": "approvals",
                        "roles": list(GATE_0B_APPROVAL_ROLES),
                        "signed": {
                            role: {"hash": "sha256:" + "a" * 12}
                            for role in GATE_0B_APPROVAL_ROLES
                        },
                    }
                }
            }
            report = check_gate_0b(registry, cdir)
            approvals = next(i for i in report.items if i.item == "approvals")
            self.assertIs(approvals.status, Status.PASS)


class Assertion5Test(unittest.TestCase):
    def test_vacuous_pass_when_phase1_not_built(self):
        self.assertIs(assertion_5_sequence(None, None).status, Status.PASS)

    def test_fail_when_phase1_built_before_gate_0b(self):
        item = assertion_5_sequence("2026-06-01T00:00:00", "2026-05-01T00:00:00")
        self.assertIs(item.status, Status.FAIL)
        self.assertIn("作废", item.reason)

    def test_fail_when_gate_0b_never_passed_but_phase1_built(self):
        item = assertion_5_sequence(None, "2026-05-01T00:00:00")
        self.assertIs(item.status, Status.FAIL)

    def test_pass_when_ordered_correctly(self):
        item = assertion_5_sequence("2026-04-01T00:00:00", "2026-05-01T00:00:00")
        self.assertIs(item.status, Status.PASS)


class Assertion6Test(unittest.TestCase):
    def test_real_config_has_no_forbidden_defaults(self):
        report = assertion_6_config_zero_defaults(config_dir())
        self.assertIs(report.status, Status.PASS, [i.to_dict() for i in report.items])

    def test_detects_forbidden_default_in_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            (cdir / "field_schema.json").write_text(
                json.dumps(
                    {
                        "fields": [
                            {"name": "q1_point", "default": 100.0},
                            {"name": "adjustment_scope", "default": "FULL"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report = assertion_6_config_zero_defaults(cdir)
            self.assertIs(report.status, Status.FAIL)
            scan = next(i for i in report.items if i.item == "zero_default_scan")
            self.assertEqual(len(scan.actual), 2)

    def test_null_default_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            (cdir / "field_schema.json").write_text(
                json.dumps(
                    {"fields": [{"name": "q1_point", "default": None}]}, ensure_ascii=False
                ),
                encoding="utf-8",
            )
            self.assertIs(
                assertion_6_config_zero_defaults(cdir).status, Status.PASS
            )

    def test_wp4_build_is_hard_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = {"gate_0b": {}}
            gate_0b = check_gate_0b(registry, Path(tmp))
            self.assertIs(gate_0b.status, Status.BLOCKED)
            self.assertIs(assert_wp4_build_allowed(gate_0b).status, Status.BLOCKED)


class EndToEndTest(unittest.TestCase):
    def test_evaluate_gate_0_real_repo_state(self):
        cdir = config_dir()
        registry = load_registry(cdir / GATE0_REGISTRY)
        selection = select_rule_set(
            contract_date="2026-03-01", use_project_selection=False
        ).to_dict()
        report = evaluate_gate_0(registry, cdir, selection)
        self.assertEqual(report["summary"]["gate_0a"], "BLOCKED")
        self.assertEqual(report["summary"]["phase_0_input_gate"], "BLOCKED")
        self.assertEqual(report["summary"]["phase_0"], "BLOCKED")
        self.assertEqual(report["summary"]["wp4_solver_layer"], "BLOCKED")
        # 遗留项必须被显式暴露，避免"已冻结"被误读为"已完备"
        self.assertTrue(any(a["kind"] == "freeze_blocker" for a in report["advisories"]))


if __name__ == "__main__":
    unittest.main()
