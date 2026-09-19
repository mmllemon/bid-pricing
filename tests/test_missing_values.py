import json
import unittest
from pathlib import Path

from bidpricing.states import Status
from bidpricing.validation.missing_values import assess_field, load_missing_policy


ROOT = Path(__file__).resolve().parents[1]


class MissingValuePolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_missing_policy(ROOT / "config")
        cls.fields = json.loads((ROOT / "config/field_schema.json").read_text(encoding="utf-8"))["fields"]

    def field(self, name):
        return next(f for f in self.fields if f["name"] == name)

    def test_policy_artifact_is_complete(self):
        self.assertIn("BLOCK", self.policy["policy_domain"])
        self.assertIn("cap_empty != cap_zero", self.policy["invariants"])
        self.assertEqual(set(self.policy["policy_domain"]), set(self.policy["policy_actions"]))

    def test_required_missing_blocks(self):
        d = assess_field(self.field("q0"), None, policy=self.policy)
        self.assertIs(d.status, Status.BLOCKED)

    def test_invalid_numeric_blocks_even_if_nullable(self):
        d = assess_field(self.field("item_feature"), "bad", valid=False, policy=self.policy)
        self.assertIs(d.status, Status.BLOCKED)

    def test_cap_empty_is_not_zero(self):
        d = assess_field(self.field("cap"), None, policy=self.policy)
        self.assertIs(d.status, Status.PASS)
        self.assertEqual(d.action, "preserve_no_cap")

    def test_derived_field_cannot_be_input(self):
        d = assess_field(self.field("p1"), None, policy=self.policy)
        self.assertIs(d.status, Status.BLOCKED)
        d = assess_field(self.field("p1"), 12.3, policy=self.policy)
        self.assertIs(d.status, Status.BLOCKED)

    def test_inferred_value_is_flagged(self):
        d = assess_field(self.field("item_name"), "名称", value_source="inferred", policy=self.policy)
        self.assertIs(d.status, Status.WARN)
        self.assertEqual(d.value_source, "inferred")

    def test_zero_is_a_present_value(self):
        d = assess_field(self.field("q0"), 0.0, policy=self.policy)
        self.assertIs(d.status, Status.PASS)


if __name__ == "__main__":
    unittest.main()
