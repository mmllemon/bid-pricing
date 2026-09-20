import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.solver import parity_runner as pr
from bidpricing.solver.parity import TOLERANCE_KEYS, load_spec


def _side(status="OPTIMAL", objective=10.0, prices=None, **kw):
    data = {"status": status, "objective": objective, "prices": prices or {"x": 2.0}}
    data.update(kw)
    return data


def _bundle(cases, floor_source="tests: floor 表显式给出"):
    return {
        "schema_id": pr.BUNDLE_SCHEMA,
        "provenance": {"produced_by": "tests"},
        "floor_source": floor_source,
        "cases": cases,
    }


class RunnerBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.signoff = self.root / "reference_review_signoff.json"
        self.signoff.write_text(
            json.dumps({"signed": True, "reviewer": "reviewer"}), encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def run_bundle(self, bundle):
        return pr.run_parity(bundle, signoff_path=self.signoff)


class MissingBundleTest(RunnerBase):
    def test_no_bundle_is_blocked_with_named_owner(self):
        report = self.run_bundle(None)
        self.assertEqual(report["conclusion"], "BLOCKED")
        self.assertEqual(report["cases"], [])
        self.assertIn("T04-04", report["owner"])
        self.assertFalse(report["bundle_present"])

    def test_blocked_is_not_reported_as_applicable_or_passed(self):
        report = self.run_bundle(None)
        self.assertNotIn("不适用", report["reason"].split("不是「不适用」")[0])


class BundleValidationTest(RunnerBase):
    def test_wrong_schema_raises(self):
        with self.assertRaises(pr.BundleError):
            pr.validate_bundle({"schema_id": "nope", "cases": []})

    def test_cases_must_be_list(self):
        with self.assertRaises(pr.BundleError):
            pr.validate_bundle({"schema_id": pr.BUNDLE_SCHEMA, "cases": {}})

    def test_case_needs_id(self):
        with self.assertRaises(pr.BundleError):
            pr.validate_bundle({"schema_id": pr.BUNDLE_SCHEMA, "cases": [{"group": "A"}]})

    def test_missing_file_raises_bundle_error_not_crash(self):
        """不给文件与给坏文件必须分开：后者是「给了但读不出」。"""
        with self.assertRaises(pr.BundleError):
            pr.load_bundle(self.root / "nope.json")


class AggregationTest(unittest.TestCase):
    def test_empty_judgement_set_is_blocked(self):
        self.assertEqual(pr.aggregate([]), "BLOCKED")

    def test_worst_wins(self):
        self.assertEqual(pr.aggregate(["PASS", "FAIL", "WARN"]), "FAIL")
        self.assertEqual(pr.aggregate(["PASS", "WARN"]), "WARN")
        self.assertEqual(pr.aggregate(["PASS", "BLOCKED"]), "BLOCKED")

    def test_skip_does_not_compete(self):
        """SKIP 排在最宽侧：带未激活项的报告不得永远到不了 PASS。"""
        self.assertEqual(pr.aggregate(["PASS", "SKIP"]), "PASS")

    def test_all_skip_is_skip_not_pass(self):
        self.assertEqual(pr.aggregate(["SKIP", "SKIP"]), "SKIP")

    def test_skip_policy_is_declared_in_spec(self):
        self.assertIn("SKIP 不参与最严竞争", load_spec()["report"]["skip_policy"])

    def test_unknown_status_does_not_silently_pass(self):
        self.assertEqual(pr.aggregate(["WEIRD"]), "BLOCKED")


class ReportTest(RunnerBase):
    def test_matching_case_passes_and_names_reproduce_command(self):
        bundle = _bundle([{"case_id": "A_pos", "group": "A",
                           "phase1": _side(), "phase2": _side()}])
        report = self.run_bundle(bundle)
        self.assertEqual(report["conclusion"], "PASS")
        self.assertEqual(report["tolerances_used"]["objective_abs"], 1e-7)
        self.assertTrue(report["reproduce_command"].startswith("PYTHONPATH=src"))

    def test_reproduce_command_mentions_bundle_path_when_given(self):
        bundle = _bundle([{"case_id": "A_pos", "group": "A",
                           "phase1": _side(), "phase2": _side()}])
        report = pr.run_parity(bundle, signoff_path=self.signoff, bundle_path="x/b.json")
        self.assertIn("--bundle x/b.json", report["reproduce_command"])

    def test_one_bad_case_dominates(self):
        bundle = _bundle([
            {"case_id": "ok", "group": "A", "phase1": _side(), "phase2": _side()},
            {"case_id": "bad", "group": "A", "phase1": _side(), "phase2": _side(objective=99.0)},
        ])
        report = self.run_bundle(bundle)
        self.assertEqual(report["conclusion"], "FAIL")
        self.assertIn("bad", report["reason"])

    def test_obligations_are_collected_per_case(self):
        bundle = _bundle([{"case_id": "B1", "group": "B",
                           "phase1": _side(objective=10.0), "phase2": _side(objective=10.0)}])
        report = self.run_bundle(bundle)
        self.assertTrue(any("B1" in o for o in report["obligations"]))
        self.assertEqual(report["conclusion"], "PASS")  # 义务不改判定

    def test_undeclared_floor_source_surfaces(self):
        report = self.run_bundle(None)
        self.assertIsNone(report["floor_source"])

    def test_write_report_round_trip(self):
        bundle = _bundle([{"case_id": "A_pos", "group": "A",
                           "phase1": _side(), "phase2": _side()}])
        report = self.run_bundle(bundle)
        path = pr.write_report(report, self.root / "out" / "r.json")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), report)


class SpecCodeReconciliationTest(unittest.TestCase):
    """制品声明 ↔ 实现常量 ↔ 测试三方对账（改任一侧即报错）。"""

    def test_bundle_schema_declared_in_spec_matches_code(self):
        spec = load_spec()
        self.assertEqual(spec["report"]["bundle_schema"], pr.BUNDLE_SCHEMA)

    def test_aggregation_order_declared_in_spec_matches_code(self):
        spec = load_spec()
        self.assertEqual(spec["report"]["aggregation_order"], list(pr._STATUS_ORDER))

    def test_empty_judgement_set_policy_declared(self):
        self.assertEqual(load_spec()["report"]["empty_judgement_set"], "BLOCKED")

    def test_report_output_path_declared(self):
        self.assertEqual(load_spec()["report"]["output"], "docs/phase12_parity_report.json")

    def test_generator_declared_is_this_module(self):
        self.assertEqual(load_spec()["report"]["generator"], pr.REPORTER)

    def test_floor_source_requirement_declared(self):
        self.assertTrue(load_spec()["report"]["floor_source_required"])

    def test_blocked_rules_cover_the_new_refusals(self):
        rules = " ".join(load_spec()["blocked_rules"])
        self.assertIn("可复算输入 bundle", rules)
        self.assertIn("口径不可比", rules)
        self.assertIn("具名容差", rules)

    def test_spec_still_declares_every_tolerance(self):
        self.assertEqual(set(load_spec()["tolerances"]), set(TOLERANCE_KEYS))


class MutationDiscriminationTest(RunnerBase):
    """变异体注入：坏实现必须被具名判据杀死。存活 ⇒ FAIL。"""

    def test_v7_empty_case_list_treated_as_pass_would_be_killed(self):
        """V7：空判据集判 PASS ⇒ 报告「没跑过」却显示通过。"""
        self.assertEqual(pr.aggregate([]), "BLOCKED")

    def test_v8_missing_bundle_treated_as_skip_would_be_killed(self):
        """V8：缺 bundle 判 SKIP/不适用 ⇒ 未验证的报告看起来只是「还没跑」。"""
        report = self.run_bundle(None)
        self.assertEqual(report["conclusion"], "BLOCKED")
        self.assertIn("不是「已通过」", report["reason"])

    def test_v9_dropping_obligations_in_report_would_be_killed(self):
        """V9：聚合报告丢掉逐 case 义务 ⇒ 可追溯项静默消失。"""
        bundle = _bundle([{"case_id": "B1", "group": "B",
                           "phase1": _side(objective=10.0), "phase2": _side(objective=10.0)}])
        self.assertNotEqual(self.run_bundle(bundle)["obligations"], [])

    def test_v10_tolerances_not_carried_into_report_would_be_killed(self):
        """V10：报告不带实际使用的容差 ⇒ 读者无法判断判决宽度。"""
        report = self.run_bundle(None)
        self.assertEqual(set(report["tolerances_used"]), set(TOLERANCE_KEYS))


if __name__ == "__main__":
    unittest.main()
