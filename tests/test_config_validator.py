import copy
import unittest
from pathlib import Path

from bidpricing.config_schema import load_config_schema
from bidpricing.config_validator import validate_config
from bidpricing.states import Status


ROOT = Path(__file__).resolve().parents[1]


class ConfigValidatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_config_schema(ROOT / "config")
        cls.valid = {
            "project_selection": {"options": {"adjustment_scope": {"value": "SEGMENT", "rule_set_id": "GB/T50500-2024"}, "contract_type": {"value": "UNIT_PRICE"}, "loss_acceptance": {"value": "ACCEPT"}}, "source": "OPERATOR", "actor": "u", "selected_at": "2026-09-18T00:00:00+00:00", "rationale": "r"},
            "project_classification_table": {"project_id": "P", "code_system": "GB/T50500-2024", "covered_lists": [{"source_list": "BOQ"}], "exceptions": [], "external_constants": [], "search_basis": "checked"},
            "phase0_runtime": {"p_star": 100, "p_star_max": 120, "cap_tax_scope": "EXCL_VAT", "cost_tax_scope": "EXCL_VAT", "mu": 0.1, "unbalanced_clause": {"enabled": False}},
        }

    def test_valid_config_passes(self):
        self.assertIs(validate_config(self.valid, self.schema).status, Status.PASS)

    def test_missing_empty_type_range_unknown_duplicate_version(self):
        c = copy.deepcopy(self.valid)
        c["phase0_runtime"].pop("p_star")
        c["phase0_runtime"]["mu"] = 2
        c["project_selection"]["source"] = ""
        c["project_selection"]["extra"] = 1
        r = validate_config(c, self.schema, duplicate_paths=["project_selection.source"], value_source={"bad": "x"})
        kinds = {i.kind for i in r.issues}
        self.assertTrue({"missing", "range", "unknown", "duplicate"} <= kinds)

    def test_type_and_enum_are_checked(self):
        c = copy.deepcopy(self.valid)
        c["phase0_runtime"]["p_star"] = "100"
        c["phase0_runtime"]["cap_tax_scope"] = "VAT_UNKNOWN"
        r = validate_config(c, self.schema)
        self.assertEqual(len(r.by_kind("type")), 1)
        self.assertEqual(len(r.by_kind("range")), 1)

    def test_version_mismatch_is_blocked(self):
        c = copy.deepcopy(self.valid)
        c["schema_id"] = "other"
        c["schema_version"] = 9
        r = validate_config(c, self.schema)
        self.assertEqual(len(r.by_kind("version")), 2)


if __name__ == "__main__":
    unittest.main()
