import json
import unittest
from pathlib import Path

from bidpricing.config_schema import load_config_schema, validate_config_schema


ROOT = Path(__file__).resolve().parents[1]


class ConfigSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_config_schema(ROOT / "config")

    def test_real_schema_is_valid(self):
        self.assertEqual(validate_config_schema(self.schema), [])

    def test_every_definition_has_required_shape(self):
        required = {"type", "required", "default", "min", "max", "enum", "description"}
        for spec in self.schema["sheets"].values():
            for definition in spec["keys"].values():
                self.assertTrue(required <= set(definition))

    def test_missing_definition_key_is_detected(self):
        broken = json.loads(json.dumps(self.schema))
        del broken["sheets"]["phase0_runtime"]["keys"]["p_star"]["description"]
        issues = validate_config_schema(broken)
        self.assertTrue(any(i.key == "p_star" for i in issues))

    def test_required_config_has_no_default(self):
        for sheet, spec in self.schema["sheets"].items():
            for key, definition in spec["keys"].items():
                if definition["required"]:
                    self.assertIsNone(definition["default"], (sheet, key))


if __name__ == "__main__":
    unittest.main()
