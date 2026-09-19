import unittest

from bidpricing.solver.phase3 import verify_phase3


class Phase3Test(unittest.TestCase):
    def test_lp_passes_all_conditions(self):
        report = verify_phase3({"primal_feasible": True, "dual_feasible": True, "stationarity_residual": 0.0, "complementarity_residual": 1e-9, "objective_reported": 5.0, "objective_recomputed": 5.0}, form="LP")
        self.assertEqual(report.verdict, "PASS")

    def test_lp_missing_is_blocked(self):
        self.assertEqual(verify_phase3({}, form="LP").verdict, "BLOCKED")

    def test_lp_residual_fails(self):
        report = verify_phase3({"primal_feasible": True, "dual_feasible": True, "stationarity_residual": 1.0, "complementarity_residual": 0.0, "objective_reported": 5.0, "objective_recomputed": 5.0}, form="LP")
        self.assertEqual(report.verdict, "FAIL")

    def test_milp_gap_warns_without_kkt(self):
        report = verify_phase3({"primal_feasible": True, "objective_reported": 5.0, "objective_recomputed": 5.0, "mip_gap": 0.2, "mip_gap_tolerance": 0.1}, form="MILP")
        self.assertEqual(report.verdict, "WARN")
        self.assertEqual({c.name for c in report.checks}, {"primal_feasibility", "objective_recomputation", "mip_gap"})

    def test_milp_missing_gap_is_blocked(self):
        self.assertEqual(verify_phase3({"primal_feasible": True}, form="MILP").verdict, "BLOCKED")

    def test_unknown_form_blocked(self):
        self.assertEqual(verify_phase3({}, form="QP").verdict, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
