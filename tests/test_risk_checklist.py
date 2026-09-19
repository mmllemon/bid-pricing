import unittest

from bidpricing.risk_checklist import CHECK_IDS, build_risk_checklist


def _inputs():
    return {key: {"actual": True, "threshold": True, "operator": "eq"} for key in CHECK_IDS}


class RiskChecklistTest(unittest.TestCase):
    def test_nine_checks_and_pass(self):
        report = build_risk_checklist(_inputs())
        self.assertEqual(report.verdict, "PASS")
        self.assertEqual(len(report.checks), 9)

    def test_missing_actual_is_blocked(self):
        data = _inputs()
        data["cost_evidence"] = {"threshold": True}
        report = build_risk_checklist(data)
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(report.checks[4].actual, None)

    def test_numeric_delta_is_explicit(self):
        data = _inputs()
        data["budget_residual"] = {"actual": 3.0, "threshold": 1.0, "operator": "lte"}
        report = build_risk_checklist(data)
        check = next(c for c in report.checks if c.check_id == "budget_residual")
        self.assertEqual(check.status, "FAIL")
        self.assertEqual(check.delta, -2.0)

    def test_warn_can_be_aggregated(self):
        data = _inputs()
        data["reference_parity"] = {"actual": False, "threshold": True, "operator": "eq", "failure_status": "WARN"}
        self.assertEqual(build_risk_checklist(data).verdict, "WARN")


if __name__ == "__main__":
    unittest.main()
