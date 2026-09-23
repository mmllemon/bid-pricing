import unittest
from pathlib import Path

from bidpricing.rerun import build_rerun_report, load_rerun_spec, result_hash


ROOT = Path(__file__).resolve().parents[1]


class RerunTest(unittest.TestCase):
    def test_spec_declares_three_checks(self):
        spec = load_rerun_spec(ROOT / "config")
        self.assertEqual([item["id"] for item in spec["checks"]], ["R1-A", "R1-B", "R1-C"])

    def test_hash_excludes_run_metadata(self):
        a = {"value": 1, "run_id": "a", "timestamp": "t1"}
        b = {"timestamp": "t2", "run_id": "b", "value": 1}
        self.assertEqual(result_hash(a), result_hash(b))

    def test_deep_metadata_fields_still_hashed(self):
        """回归（A6）：深层 operator/timestamp 是业务字段，须参与指纹；只剔除顶层元信息。"""
        a = {"items": [{"item_id": "X", "operator": "甲", "timestamp": "t1", "value": 1}]}
        b = {"items": [{"item_id": "X", "operator": "乙", "timestamp": "t1", "value": 1}]}
        self.assertNotEqual(result_hash(a), result_hash(b))

    def test_deterministic_runner_passes_reproducibility_and_correctness(self):
        report = build_rerun_report(lambda x: {"value": x * 2, "run_id": "volatile"}, 3, expected_result={"value": 6}, random_seed=7)
        self.assertEqual(report.status, "PASS")
        self.assertEqual({c.check_id: c.status for c in report.checks}, {"R1-A": "PASS", "R1-B": "PASS", "R1-C": "PASS"})

    def test_missing_expected_blocks_correctness(self):
        report = build_rerun_report(lambda x: {"value": x}, 1)
        self.assertEqual(report.status, "BLOCKED")
        self.assertEqual(report.checks[1].status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
