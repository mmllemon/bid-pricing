import json
import unittest
from pathlib import Path

from bidpricing.state_machine import LowPriceState, aggregate_global, decide_low_price
from bidpricing.states import Status


ROOT = Path(__file__).resolve().parents[1]


class StateMachineTest(unittest.TestCase):
    def test_spec_declares_domains(self):
        spec = json.loads((ROOT / "config/state_machine_spec.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["global_precedence"], ["BLOCKED", "FAIL", "WARN", "PASS"])
        self.assertEqual(len(spec["low_price_status_domain"]), 3)

    def test_global_precedence(self):
        self.assertIs(aggregate_global([Status.PASS, Status.WARN]), Status.WARN)
        self.assertIs(aggregate_global(["FAIL", "BLOCKED"]), Status.BLOCKED)

    def test_infeasibility_has_highest_low_price_priority(self):
        d = decide_low_price(feasibility_status=Status.BLOCKED, cost_evidence_status="MISSING", p_star=1, p_star_min=2)
        self.assertIs(d.state, LowPriceState.POTENTIAL_INFEASIBILITY)

    def test_cost_evidence_before_low_price_review(self):
        d = decide_low_price(feasibility_status=Status.PASS, cost_evidence_status="UNKNOWN", p_star=1, p_star_min=2)
        self.assertIs(d.state, LowPriceState.COST_EVIDENCE_REQUIRED)

    def test_low_price_review_when_inputs_ready(self):
        d = decide_low_price(feasibility_status=Status.PASS, cost_evidence_status="PASS", p_star=1, p_star_min=2)
        self.assertIs(d.state, LowPriceState.LOW_PRICE_REVIEW_REQUIRED)

    def test_not_triggered(self):
        d = decide_low_price(feasibility_status=Status.PASS, cost_evidence_status="PASS", p_star=2, p_star_min=1)
        self.assertFalse(d.triggered)
        self.assertIsNone(d.state)


if __name__ == "__main__":
    unittest.main()
