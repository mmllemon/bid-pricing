import unittest
from pathlib import Path

from bidpricing.historical_replay import MINIMUM_PROJECTS, load_historical_replay_spec, replay_historical_projects


ROOT = Path(__file__).resolve().parents[1]


class HistoricalReplayTest(unittest.TestCase):
    def test_spec_requires_three_projects(self):
        spec = load_historical_replay_spec(ROOT / "config")
        self.assertEqual(spec["minimum_projects"], MINIMUM_PROJECTS)

    def test_insufficient_history_is_blocked(self):
        report = replay_historical_projects([{"project_id": "only-one"}], lambda project: {"total": 1})
        self.assertEqual(report.status, "BLOCKED")
        self.assertEqual(report.completed_projects, 1)

    def test_three_complete_projects_pass(self):
        projects = [{"project_id": f"p{i}"} for i in range(3)]
        report = replay_historical_projects(projects, lambda project: {"project_id": project["project_id"], "total": 100})
        self.assertEqual(report.status, "PASS")
        self.assertEqual(report.completed_projects, 3)

    def test_failed_project_is_retained_in_report(self):
        projects = [{"project_id": f"p{i}"} for i in range(3)]
        report = replay_historical_projects(projects, lambda project: (_ for _ in ()).throw(RuntimeError("bad input")) if project["project_id"] == "p1" else {"ok": True})
        self.assertEqual(report.status, "BLOCKED")
        self.assertEqual(report.results[1].status, "FAIL")


if __name__ == "__main__":
    unittest.main()
