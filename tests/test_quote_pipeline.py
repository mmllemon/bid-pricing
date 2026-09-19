import unittest
from pathlib import Path

from bidpricing.quote_pipeline import (
    load_quote_pipeline_spec,
    run_quote_pipeline,
    run_settlement_adjusted_quote_pipeline,
)
from bidpricing.solver.instance import Phase1Instance, Phase1InstanceError
from bidpricing.solver.phase1 import phase1_probe_instance


ROOT = Path(__file__).resolve().parents[1]

SETTLEMENT_CLAUSE = {"enabled": True, "reference": "CAP", "tol_lo": 0.5, "tol_hi": 0.5,
                     "mechanism": "SETTLEMENT_ADJUSTMENT"}


class QuotePipelineTest(unittest.TestCase):
    def test_spec_declares_main_flow(self):
        spec = load_quote_pipeline_spec(ROOT / "config")
        self.assertEqual(spec["steps"][0], "compute_P_competitive")
        self.assertIn("target_total", spec["inputs"])

    def test_missing_cost_floor_blocks_instead_of_guessing(self):
        result = run_quote_pipeline(target_total=100, items=[{"item_id": "A", "q0": 1, "q1_point": 1, "c_i": 50, "cap": 80}], fixed_pretax=0, vat_rate=0, surtax_rate=0)
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("L", result.reason)

    def test_invalid_total_blocks(self):
        result = run_quote_pipeline(target_total=0, items=[], fixed_pretax=0, vat_rate=0, surtax_rate=0)
        self.assertEqual(result.status, "BLOCKED")

    def test_probe_instance_runs_end_to_end(self):
        instance = phase1_probe_instance()
        rows = [{
            "item_id": item.item_id, "q0": item.q0, "q1_point": item.q1_point,
            "c_i": item.c_i, "cap": item.cap, "L": item.L, "U": item.U,
            "p0": item.p0, "pricing_role": item.role,
        } for item in instance.items]
        result = run_quote_pipeline(target_total=instance.B, items=rows, fixed_pretax=0, vat_rate=0, surtax_rate=0)
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.solver_status, "OPTIMAL")
        self.assertEqual(set(result.p_by_id), {item.item_id for item in instance.items})


class DuplicateItemIdGuardTest(unittest.TestCase):
    """H-009：相同 item_id 不得被字典覆盖——入口挡位拒绝而非静默覆盖。"""

    def _rows(self):
        return [
            {"item_id": "A", "q0": 1, "q1_point": 1, "c_i": 50, "cap": 80, "L": 50, "U": 80},
            {"item_id": "A", "q0": 2, "q1_point": 2, "c_i": 60, "cap": 90, "L": 55, "U": 90},
            {"item_id": "B", "q0": 1, "q1_point": 1, "c_i": 40, "cap": 70, "L": 45, "U": 70},
        ]

    def test_quote_pipeline_blocks_duplicate(self):
        result = run_quote_pipeline(target_total=100, items=self._rows(),
                                    fixed_pretax=0, vat_rate=0, surtax_rate=0)
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("重复 item_id", result.reason)
        self.assertIn("A", result.reason)
        self.assertEqual(result.p_by_id, {})

    def test_settlement_pipeline_blocks_duplicate(self):
        result = run_settlement_adjusted_quote_pipeline(
            target_total=100, items=self._rows(), fixed_pretax=0, vat_rate=0,
            surtax_rate=0, unbalanced_clause=SETTLEMENT_CLAUSE)
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("重复 item_id", result.reason)
        self.assertIn("A", result.reason)
        self.assertEqual(result.p_by_id, {})

    def test_from_master_defensive_raise(self):
        with self.assertRaises(Phase1InstanceError):
            Phase1Instance.from_master(
                self._rows(), price_column="cap", B=100.0, P_star=100.0,
                source="test_duplicate_guard")

    def test_from_dict_defensive_raise(self):
        with self.assertRaises(Phase1InstanceError):
            Phase1Instance.from_dict(
                {"items": [dict(r, role="OPTIMIZABLE") for r in self._rows()]},
                source="test_duplicate_guard")


if __name__ == "__main__":
    unittest.main()
