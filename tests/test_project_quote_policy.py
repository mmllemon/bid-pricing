import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectQuotePolicyTest(unittest.TestCase):
    def test_confirmed_policy_allows_item_loss_and_freezes_fixed_values(self):
        policy = json.loads((ROOT / "config/project_quote_policy.json").read_text(encoding="utf-8"))
        self.assertFalse(policy["cost_policy"]["hard_lower_bound"])
        self.assertTrue(policy["cost_policy"]["loss_allowed"])
        self.assertEqual(policy["fixed_pretax_policy"]["fixed_pretax"], 22381.74)
        self.assertEqual(policy["tax_policy"]["vat_rate"], 0.09)


if __name__ == "__main__":
    unittest.main()
