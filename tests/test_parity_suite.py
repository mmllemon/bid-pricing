"""T04-04 实测校验：golden_dataset_v1 → bundle 的两条路径结果留痕可复算。

本测试**不 mock**——直接跑真实 golden 正例的 Phase 1（解析解）与 Phase 2
（编译 LP），验证：
1. 生成器可复算（两次生成，收入 bundle 的 case 一致）；
2. 适用子集内的正例（A/D/F）两条路径都产出，且目标值在容差护栏内一致；
3. 边界退化（B_pos 单点、E_pos 极端尺度）与空/负例被**显式跳过留痕**，
   而不是被静默冒充为覆盖。
"""
import unittest

from bidpricing.solver import parity_suite as ps

GOLDEN_PASS_CASES = {"A_pos", "D_pos", "F_pos"}


class GoldenParitySuiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = ps.build_bundle(config_dir="config")
        cls.cases = {c["case_id"]: c for c in cls.bundle["cases"]}
        cls.skipped = cls.bundle["provenance"]["skipped"]

    def test_bundle_schema_and_provenance(self):
        self.assertEqual(self.bundle["schema_id"], ps.BUNDLE_SCHEMA)
        self.assertEqual(self.bundle["provenance"]["golden_version"] != "", True)
        self.assertIn("tie_break_policy", self.bundle["provenance"])
        # floor 来源必须 self-describing（ADR-0004/0026 精神）
        self.assertIn("tie_break", self.bundle["floor_source"])

    def test_passes_cover_at_least_A_D_F(self):
        self.assertTrue(GOLDEN_PASS_CASES <= set(self.cases),
                        f"缺少适用子集正例，实际={sorted(self.cases)}")

    def test_each_pass_case_has_both_paths_and_matching_objective(self):
        for cid in GOLDEN_PASS_CASES:
            c = self.cases[cid]
            p1, p2 = c["phase1"], c["phase2"]
            self.assertEqual(p1["status"], "OPTIMAL")
            self.assertFalse(p2["status"].startswith("ERROR"))
            self.assertIsNotNone(p1["objective"])
            self.assertIsNotNone(p2["objective"])
            # 数值一致性是硬断言：解析解与 LP 应收敛到同一目标
            self.assertAlmostEqual(p1["objective"], p2["objective"], places=6)
            # 价格逐项一致
            self.assertEqual(set(p1["prices"]), set(p2["prices"]))
            for k in p1["prices"]:
                self.assertAlmostEqual(p1["prices"][k], p2["prices"][k], places=6)
            # 层归属（L3）两侧同语言
            self.assertEqual(set(p1.get("layers", {})),
                             set(p2.get("layers", {})))

    def test_reproducible(self):
        again = ps.build_bundle(config_dir="config")
        self.assertEqual(
            {c["case_id"]: (c["phase1"]["objective"], c["phase2"]["objective"])
             for c in again["cases"]},
            {c["case_id"]: (c["phase1"]["objective"], c["phase2"]["objective"])
             for c in self.bundle["cases"]})

    def test_skipped_are_labelled_not_silently_ignored(self):
        joined = "\n".join(self.skipped)
        for fragment in ("negative 不参与对拍", "无两侧齐备可优化项",
                         "Phase2 非 OPTIMAL", "Phase1 非 OPTIMAL"):
            self.assertIn(fragment, joined, f"缺跳过留痕类别：{fragment}")


if __name__ == "__main__":
    unittest.main()