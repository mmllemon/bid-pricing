import json
import unittest
from pathlib import Path

from bidpricing.config_merge import merge_config
from bidpricing.config_schema import load_config_schema
from bidpricing.states import Status


ROOT = Path(__file__).resolve().parents[1]


class ConfigMergeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_config_schema(ROOT / "config")

    def test_explicit_wins_and_source_is_recorded(self):
        r = merge_config(
            {"phase0_runtime": {"p_star": 100}},
            {"phase0_runtime": {"p_star": 50}},
            schema=self.schema,
        )
        self.assertEqual(r.config["phase0_runtime"]["p_star"], 100)
        self.assertEqual(r.value_source["phase0_runtime.p_star"], "explicit")

    def test_required_field_cannot_be_defaulted(self):
        r = merge_config(
            {}, {"phase0_runtime": {"p_star": 50}}, schema=self.schema
        )
        self.assertIs(r.status, Status.BLOCKED)
        self.assertIn("phase0_runtime.p_star", r.missing_required)
        self.assertTrue(any("required 配置禁止" in e for e in r.errors))

    def test_missing_required_is_blocked(self):
        r = merge_config(
            {"phase0_runtime": {"p_star": 100}}, schema=self.schema
        )
        self.assertIs(r.status, Status.BLOCKED)
        self.assertIn("phase0_runtime.p_star_max", r.missing_required)

    def test_inferred_and_derived_sources_are_distinct(self):
        schema = {"sheets": {"x": {"keys": {
            "a": {"type": "number", "required": False, "default": None, "min": None, "max": None, "enum": None, "description": "a"},
            "b": {"type": "number", "required": False, "default": None, "min": None, "max": None, "enum": None, "description": "b"},
        }}}}
        r = merge_config({}, schema=schema, derived={"x": {"b": 2}}, inferred={"x": {"a": 1}})
        self.assertEqual(r.value_source, {"x.a": "inferred", "x.b": "derived"})

    def test_unregistered_key_is_blocked(self):
        r = merge_config({"phase0_runtime": {"typo": 1}}, schema=self.schema)
        self.assertIs(r.status, Status.BLOCKED)
        self.assertTrue(any("未注册配置键" in e for e in r.errors))

    def test_none_does_not_count_as_explicit(self):
        r = merge_config({"phase0_runtime": {"p_star": None}}, schema=self.schema)
        self.assertIn("phase0_runtime.p_star", r.missing_required)


if __name__ == "__main__":
    unittest.main()
