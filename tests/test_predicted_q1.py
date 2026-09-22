import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.cli import PREDICTED_Q1_SOURCE_CHOICES
from bidpricing.closed_loop import load_closed_loop_spec, run_closed_loop
from bidpricing.predicted_q1 import (
    DECLARATION_SCHEMA_ID,
    PROVENANCE_FIELDS,
    PredictionDeclarationError,
    load_declaration,
    load_predicted_q1_spec,
    register_declaration,
    verify_and_merge,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = load_predicted_q1_spec(ROOT / "config")


def _declaration_file(directory: Path, values, source="manual", **overrides) -> Path:
    doc = {
        "schema_id": DECLARATION_SCHEMA_ID,
        "source": source,
        "declared_by": "user",
        "declared_at": "2026-09-22T00:00:00Z",
        "rationale": "测试声明",
        "records": [{"item": k, "predicted_q1": v} for k, v in values.items()],
    }
    doc.update(overrides)
    path = Path(directory) / "decl.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


class SpecLockTest(unittest.TestCase):
    def test_source_domain_locked_across_specs_and_cli(self):
        closed = load_closed_loop_spec(ROOT / "config")
        self.assertEqual(SPEC["source_domain"], closed["predicted_q1_sources"])
        self.assertEqual(list(PREDICTED_Q1_SOURCE_CHOICES), SPEC["source_domain"])

    def test_provenance_and_record_fields_locked(self):
        self.assertEqual(list(PROVENANCE_FIELDS), SPEC["provenance_required"])
        self.assertEqual(SPEC["record_fields"], ["item", "predicted_q1"])
        self.assertEqual(SPEC["status_domain"], ["PASS", "BLOCKED"])


class RegisterDeclarationTest(unittest.TestCase):
    def _kwargs(self, out, **overrides):
        kwargs = dict(source="manual", records={"A": 1.0, "B": 2.5},
                      declared_by="user", declared_at="2026-09-22T00:00:00Z",
                      rationale="测试依据", spec=SPEC, out_path=out)
        kwargs.update(overrides)
        return kwargs

    def test_register_writes_full_provenance_and_reloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "decl.json"
            register_declaration(**self._kwargs(out))
            reloaded = load_declaration(out)
            self.assertEqual(reloaded.records, {"A": 1.0, "B": 2.5})
            self.assertEqual(reloaded.source, "manual")
            self.assertEqual(reloaded.declared_by, "user")

    def test_unregistered_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PredictionDeclarationError):
                register_declaration(**self._kwargs(tmp, source="q0_estimate"))

    def test_blank_provenance_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ({"declared_by": ""}, {"declared_at": "  "}, {"rationale": ""}):
                with self.assertRaises(PredictionDeclarationError, msg=str(bad)):
                    register_declaration(**self._kwargs(tmp, **bad))

    def test_bad_values_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for records in ({"A": -1}, {"A": "x"}, {"A": None}, {"A": True}, {}):
                with self.assertRaises(PredictionDeclarationError, msg=str(records)):
                    register_declaration(**self._kwargs(tmp, records=records))

    def test_overwrite_requires_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "decl.json"
            register_declaration(**self._kwargs(out))
            with self.assertRaises(PredictionDeclarationError):
                register_declaration(**self._kwargs(out))
            register_declaration(**self._kwargs(out, replace=True))


class LoadDeclarationTest(unittest.TestCase):
    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PredictionDeclarationError):
                load_declaration(Path(tmp) / "nope.json")

    def test_missing_provenance_field_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _declaration_file(Path(tmp), {"A": 1.0}, declared_by="")
            with self.assertRaises(PredictionDeclarationError):
                load_declaration(path)

    def test_wrong_schema_id_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _declaration_file(Path(tmp), {"A": 1.0}, schema_id="other_v1")
            with self.assertRaises(PredictionDeclarationError):
                load_declaration(path)


class VerifyMergeTest(unittest.TestCase):
    def _declaration(self, tmp):
        return load_declaration(_declaration_file(Path(tmp), {"A": 12.0, "B": 8.0}))

    def test_fills_missing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            declaration = self._declaration(tmp)
            merged, errors = verify_and_merge(
                [{"item": "A"}, {"item": "B", "predicted_q1": 8.0}], declaration)
            self.assertEqual(errors, ())
            self.assertEqual(merged[0]["predicted_q1"], 12.0)
            self.assertEqual(merged[1]["predicted_q1"], 8.0)

    def test_mismatched_value_blocks_with_named_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            declaration = self._declaration(tmp)
            _, errors = verify_and_merge([{"item": "A", "predicted_q1": 99.0}], declaration)
            self.assertEqual(len(errors), 1)
            self.assertIn("A", errors[0])
            self.assertIn("不一致", errors[0])

    def test_uncovered_item_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            declaration = self._declaration(tmp)
            _, errors = verify_and_merge([{"item": "C"}], declaration)
            self.assertEqual(len(errors), 1)
            self.assertIn("C", errors[0])
            self.assertIn("未被声明书覆盖", errors[0])


class ClosedLoopDeclarationTest(unittest.TestCase):
    def _loop_kwargs(self, decl_path, **overrides):
        kwargs = dict(
            replay_status="PASS",
            base_config_version="c1",
            proposed_config_version="c2",
            proposed_changes=[{"key": "k", "new_value": 2, "reason": "测试"}],
            current_config={"k": 1},
            predicted_q1_source="manual",
            predicted_q1_declaration=str(decl_path),
            segment="s",
            project_type="t",
            confidence_interval={"low": 0.0, "high": 1.0},
            min_sample_size=2,
            spec=load_closed_loop_spec(ROOT / "config"),
        )
        kwargs.update(overrides)
        return kwargs

    def _records(self):
        return [
            {"item": "A", "q0": 10.0, "actual_q1": 11.0},
            {"item": "B", "q0": 10.0, "actual_q1": 9.0},
        ]

    def test_declaration_flips_loop_to_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            decl = _declaration_file(Path(tmp), {"A": 12.0, "B": 8.0})
            report = run_closed_loop(self._records(), **self._loop_kwargs(decl))
            self.assertEqual(report.status, "READY")
            self.assertEqual([s.status for s in report.stages], ["PASS", "PASS", "PASS"])
            self.assertEqual(report.quantity_comparison.comparisons[0].predicted_q1, 12.0)
            self.assertEqual(report.calibration.status, "PASS")
            self.assertEqual(report.calibration.approval_status, "PENDING")

    def test_tampered_value_blocks_precision_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            decl = _declaration_file(Path(tmp), {"A": 12.0, "B": 8.0})
            records = [{"item": "A", "q0": 10.0, "actual_q1": 11.0, "predicted_q1": 99.0},
                       {"item": "B", "q0": 10.0, "actual_q1": 9.0}]
            report = run_closed_loop(records, **self._loop_kwargs(decl))
            self.assertEqual(report.status, "BLOCKED")
            self.assertEqual(report.stages[1].status, "BLOCKED")
            self.assertIn("不一致", report.stages[1].detail)
            self.assertIsNone(report.precision)

    def test_declaration_source_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            decl = _declaration_file(Path(tmp), {"A": 12.0, "B": 8.0}, source="manual")
            report = run_closed_loop(
                self._records(),
                **self._loop_kwargs(decl, predicted_q1_source="model"))
            self.assertEqual(report.status, "BLOCKED")
            self.assertIn("不一致", report.stages[1].detail)

    def test_missing_declaration_file_blocks(self):
        report = run_closed_loop(
            self._records(),
            **self._loop_kwargs("no_such_declaration.json"))
        self.assertEqual(report.status, "BLOCKED")
        self.assertIn("不存在", report.stages[1].detail)


if __name__ == "__main__":
    unittest.main()
