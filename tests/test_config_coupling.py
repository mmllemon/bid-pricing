import copy
import unittest
from pathlib import Path

from bidpricing.config_coupling import audit_config_coupling
from bidpricing.config_schema import load_config_schema


ROOT = Path(__file__).resolve().parents[1]


class ConfigCouplingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_config_schema(ROOT / "config")

    def test_real_schema_audit(self):
        report = audit_config_coupling(self.schema)
        self.assertTrue(report.passed, report.to_dict())
        self.assertEqual(report.sheet_count, 3)
        self.assertEqual(report.field_count, 20)
        self.assertEqual(report.cross_sheet_references, 2)
        self.assertEqual(report.default_count, 0)

    def test_duplicate_field_is_detected(self):
        schema = copy.deepcopy(self.schema)
        schema["sheets"]["phase0_runtime"]["keys"]["other.project_id"] = dict(
            schema["sheets"]["phase0_runtime"]["keys"]["p_star"]
        )
        report = audit_config_coupling(schema)
        self.assertIn("project_id", report.duplicate_fields)

    def test_bad_cross_sheet_reference_is_detected(self):
        schema = copy.deepcopy(self.schema)
        schema["references"].append({"from": "phase0_runtime.nope", "to": "phase0_runtime.p_star"})
        report = audit_config_coupling(schema)
        self.assertEqual(len(report.invalid_references), 1)


if __name__ == "__main__":
    unittest.main()
