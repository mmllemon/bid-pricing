import unittest
from pathlib import Path

from bidpricing.calibration import PREREQUISITES
from bidpricing.closed_loop import (
    ClosedLoopBundle,
    ClosedLoopError,
    DEFAULT_ACTUAL_Q1_SOURCE,
    DEFAULT_PREDICTED_Q1_SOURCES,
    STAGES,
    STATUS_DOMAIN,
    check_predicted_source,
    load_closed_loop_spec,
    run_closed_loop,
)


ROOT = Path(__file__).resolve().parents[1]


def _records(n=32):
    return [
        {"item": f"I{i:02d}", "q0": 10.0, "predicted_q1": 12.0 + i, "actual_q1": 11.0 + i}
        for i in range(n)
    ]


def _spec():
    return load_closed_loop_spec(ROOT / "config")


def _full_kwargs(**overrides):
    kwargs = dict(
        replay_status="PASS",
        base_config_version="c1",
        proposed_config_version="c2",
        proposed_changes=[{"key": "rho_plus", "new_value": 0.05, "reason": "置信区间内稳定偏差"}],
        current_config={"rho_plus": 0.02},
        predicted_q1_source="model",
        predicted_q1_source_ref="docs/model_v2_predictions.json",
        actual_q1_source="cost.q1_point",
        segment="foundation",
        project_type="civil",
        confidence_interval={"method": "bootstrapped", "low": 0.02, "high": 0.06},
    )
    kwargs.update(overrides)
    return kwargs


class ClosedLoopSpecLockTest(unittest.TestCase):
    def test_module_constants_track_spec(self):
        spec = _spec()
        self.assertEqual(spec["predicted_q1_sources"], list(DEFAULT_PREDICTED_Q1_SOURCES))
        self.assertEqual(spec["stages"], list(STAGES))
        self.assertEqual(spec["status_domain"], list(STATUS_DOMAIN))
        self.assertEqual(DEFAULT_ACTUAL_Q1_SOURCE, "cost.q1_point")
        self.assertIn(DEFAULT_ACTUAL_Q1_SOURCE, spec["independence_rule"])
        self.assertEqual(len(PREREQUISITES), 3)

    def test_spec_declares_independence_and_closed_when(self):
        spec = _spec()
        self.assertIn("independence_rule", spec)
        self.assertEqual(len(spec["closed_when"]), 3)
        self.assertEqual(spec["task"], "T07-03/T07-04")


class ClosedLoopBundleTest(unittest.TestCase):
    def test_array_doc_is_accepted(self):
        bundle = ClosedLoopBundle.from_dict(_records())
        self.assertEqual(len(bundle.records), 32)
        self.assertIsNone(bundle.predicted_q1_source)
        self.assertEqual(bundle.base_config_version, "unversioned")

    def test_malformed_structure_raises(self):
        with self.assertRaises(ClosedLoopError):
            ClosedLoopBundle.from_dict({"records": "not-a-list"})
        with self.assertRaises(ClosedLoopError):
            ClosedLoopBundle.from_dict({"records": [_records(1)[0]], "min_sample_size": 0})
        with self.assertRaises(ClosedLoopError):
            ClosedLoopBundle.from_dict({"records": [], "confidence_interval": [1, 2]})


class CheckPredictedSourceTest(unittest.TestCase):
    def test_registered_source_is_independent(self):
        bundle = ClosedLoopBundle(
            records=tuple(_records()), replay_status=None, base_config_version="c1",
            proposed_config_version=None, proposed_changes=(), current_config={},
            predicted_q1_source="model", predicted_q1_source_ref="ref",
            predicted_q1_declaration=None,
            actual_q1_source="cost.q1_point", segment=None, project_type=None,
            confidence_interval=None, min_sample_size=None, q_min=None, source="x")
        ok, note = check_predicted_source(bundle, _spec())
        self.assertTrue(ok)
        self.assertIn("ref", note)
        self.assertIn("'model'", note)

    def test_unregistered_source_rejected(self):
        bundle = ClosedLoopBundle(
            records=(), replay_status=None, base_config_version="c1",
            proposed_config_version=None, proposed_changes=(), current_config={},
            predicted_q1_source="q0_estimate", predicted_q1_source_ref=None,
            predicted_q1_declaration=None,
            actual_q1_source=None, segment=None, project_type=None,
            confidence_interval=None, min_sample_size=None, q_min=None, source=None)
        ok, note = check_predicted_source(bundle, _spec())
        self.assertFalse(ok)
        self.assertIn("q0_estimate", note)


class RunClosedLoopTest(unittest.TestCase):
    def test_full_closure_is_ready(self):
        report = run_closed_loop(_records(), spec=_spec(), **_full_kwargs())
        self.assertEqual(report.status, "READY")
        self.assertEqual([s.status for s in report.stages], ["PASS", "PASS", "PASS"])
        self.assertEqual(list(report.evidence), list(PREREQUISITES))
        self.assertEqual(report.evidence["precision_promotion_status"], "READY")
        rec = report.calibration
        self.assertEqual(rec.status, "PASS")
        self.assertEqual(rec.approval_status, "PENDING")
        self.assertFalse(rec.applied)
        self.assertEqual(rec.changes[0].old_value, 0.02)
        self.assertEqual(rec.changes[0].new_value, 0.05)
        self.assertEqual(rec.proposed_config_version, "c2")

    def test_missing_records_block_everything(self):
        report = run_closed_loop([], spec=_spec(), **_full_kwargs())
        self.assertEqual(report.status, "BLOCKED")
        self.assertEqual(report.stages[0].status, "BLOCKED")
        self.assertEqual(report.precision.status, "BLOCKED")
        self.assertEqual(report.calibration.status, "BLOCKED")

    def test_source_shared_with_actual_blocks(self):
        report = run_closed_loop(
            _records(), spec=_spec(),
            **_full_kwargs(predicted_q1_source="cost.q1_point"))
        self.assertEqual(report.status, "BLOCKED")
        self.assertEqual(report.stages[1].status, "BLOCKED")
        self.assertIn("独立性", report.stages[1].detail)
        self.assertIsNone(report.precision)
        self.assertEqual(report.evidence["precision_promotion_status"], "BLOCKED")
        self.assertEqual(report.calibration.status, "BLOCKED")

    def test_unregistered_source_blocks_even_with_values(self):
        report = run_closed_loop(
            _records(), spec=_spec(),
            **_full_kwargs(predicted_q1_source="q0_estimate"))
        self.assertEqual(report.status, "BLOCKED")
        self.assertIn("未登记", report.stages[1].detail)
        self.assertIsNone(report.precision)

    def test_missing_source_declaration_blocks(self):
        report = run_closed_loop(
            _records(), spec=_spec(),
            **_full_kwargs(predicted_q1_source=None))
        self.assertEqual(report.status, "BLOCKED")
        self.assertIn("未登记", report.stages[1].detail)

    def test_holding_precision_holds_calibration(self):
        report = run_closed_loop(
            _records(), spec=_spec(),
            **_full_kwargs(confidence_interval=None))
        self.assertEqual(report.status, "BLOCKED")
        self.assertEqual(report.stages[1].status, "WARN")
        self.assertEqual(report.precision.promotion_status, "HOLD")
        self.assertEqual(report.calibration.status, "BLOCKED")
        self.assertIn("精度升级 HOLD", report.reason)
        self.assertIn("calibrate BLOCKED", report.reason)

    def test_replay_blocked_blocks_calibration_only(self):
        report = run_closed_loop(
            _records(), spec=_spec(),
            **_full_kwargs(replay_status="BLOCKED"))
        self.assertEqual(report.status, "BLOCKED")
        self.assertEqual(report.stages[1].status, "PASS")
        self.assertEqual(report.precision.promotion_status, "READY")
        self.assertEqual(report.calibration.status, "BLOCKED")
        self.assertIn("replay", report.calibration.reason)

    def test_no_changes_blocks_calibration(self):
        report = run_closed_loop(
            _records(), spec=_spec(),
            **_full_kwargs(proposed_changes=[]))
        self.assertEqual(report.calibration.status, "BLOCKED")
        self.assertIn("没有可审计的参数变更建议", report.calibration.reason)


if __name__ == "__main__":
    unittest.main()
