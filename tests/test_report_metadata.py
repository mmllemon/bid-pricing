import tempfile
import unittest
from pathlib import Path

from bidpricing.report_metadata import build_report_metadata, calculation_hash, load_report_metadata_spec, validate_report_metadata


ROOT = Path(__file__).resolve().parents[1]


class ReportMetadataTest(unittest.TestCase):
    def test_spec_declares_hash_layers(self):
        spec = load_report_metadata_spec(ROOT / "config")
        self.assertIn("calculation_hash", spec["hash_layers"])
        self.assertIn("artifact_hash", spec["hash_layers"])

    def test_calculation_hash_excludes_volatile_fields(self):
        a = {"value": 1, "run_id": "a", "created_at": "t1", "operator": "x"}
        b = {"value": 1, "run_id": "b", "created_at": "t2", "operator": "y"}
        self.assertEqual(calculation_hash(a), calculation_hash(b))

    def test_report_binds_versions_and_artifact(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"report")
            path = handle.name
        metadata = build_report_metadata({"total": 10}, model_version="m1", config_version="c1", input_hash="sha256:in", rule_set_version="r1", operator="alice", artifact_path=path)
        self.assertTrue(metadata.artifact_hash.startswith("sha256:"))
        self.assertEqual(validate_report_metadata(metadata.to_dict())[0], "PASS")

    def test_missing_binding_is_rejected(self):
        with self.assertRaises(ValueError):
            build_report_metadata({}, model_version="", config_version="c1", input_hash="in", rule_set_version="r1", operator="alice")


if __name__ == "__main__":
    unittest.main()
