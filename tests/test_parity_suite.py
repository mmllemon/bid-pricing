"""T04-04 实测校验：golden_dataset_v1 → bundle 的两条路径结果留痕可复算。

本测试**不 mock**——直接跑真实 golden 正例的 Phase 1（解析解）与 Phase 2
（编译 LP），验证：
1. 生成器可复算（两次生成，收入 bundle 的 case 一致）；
2. 适用子集内的正例（A/D/F）两条路径都产出，且目标值在容差护栏内一致；
3. 边界退化（B_pos 单点、E_pos 极端尺度）与空/负例被**显式跳过留痕**，
   而不是被静默冒充为覆盖。

能力口径（2026-10-08 补）：本仓 CI 跑两档依赖——minimal（零第三方）与
solver（装 PuLP+HiGHS）。Phase 2 需要真实求解器：无 PuLP 时
`build_bundle` 会把 A/D/F 记为「Phase2 非 OPTIMAL（UNAVAILABLE）」并**正当地**
跳过留痕，于是 `cases` 为空。此前两条断言把「必须覆盖 A/D/F」写成了无条件
硬断言，导致 minimal 档直接 FAIL（CI #99/#100/#101 就红在这里，只红 minimal、
solver 档全过，特征完全吻合）。

改法沿用本仓已有纪律（`test_solver_backend.py` 的 skipTest、`test_lp_compiler.py`
的 CC-09 双向探测）：**缺能力时 SKIP，有能力却空必须仍 FAIL**——两个方向
都是回归：前者把「没检查」读成「检查失败」，后者把「真坏了」读成「环境问题」。
"""
import unittest

from bidpricing.solver import parity_suite as ps

GOLDEN_PASS_CASES = {"A_pos", "D_pos", "F_pos"}


def _solver_available() -> bool:
    """与导出层同源的能力探测（`import pulp` 失败 ⇒ Phase 2 给不出结果）。"""
    try:
        import pulp  # noqa: F401
        return True
    except ImportError:
        return False


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

    def _require_phase2_capability(self) -> None:
        """Phase 2 需要真实求解器。仅在**确因缺求解器**而拿不到正例时跳过。

        两道前置缺一不可：
          ① 本机确实无 PuLP（能力探测与导出层同源）；
          ② 跳过留痕里确实写着 UNAVAILABLE（即真的是“没能力”，不是别的原因）。
        若 ① 不成立（装了 PuLP）却仍拿不到正例，**不跳过**，让原断言 FAIL——
        否则环境完备时的真缺陷会被当成“环境问题”掩盖掉。
        """
        if GOLDEN_PASS_CASES <= set(self.cases):
            return                      # 正例齐备，无需跳过
        if not _solver_available():
            joined = "\n".join(self.skipped)
            self.assertIn("UNAVAILABLE", joined,
                          msg="无求解器且留痕里没有 UNAVAILABLE——跳过原因不是「没能力」，"
                              "不得归为环境问题，继续原断言")
            raise unittest.SkipTest(
                "本机无 PuLP ⇒ Phase 2 无法产出 OPTIMAL（minimal 依赖档的正当行为）。"
                "求解层数值对拍由 solver 档负责；本档不得将「没检查」读成「检查失败」。"
            )

    def test_passes_cover_at_least_A_D_F(self):
        self._require_phase2_capability()
        self.assertTrue(GOLDEN_PASS_CASES <= set(self.cases),
                        f"缺少适用子集正例，实际={sorted(self.cases)}")

    def test_each_pass_case_has_both_paths_and_matching_objective(self):
        self._require_phase2_capability()
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
        # 「Phase2 非 OPTIMAL」类别不再出现（2026-09-28）：B_pos 含
        # merged_lower > U_eff 的真不可行箱，此前 Phase1 自报 OPTIMAL、
        # 由 Phase2 判不可行才跳过——正是 solve_phase1 缺 lower>upper
        # 熔断时的自相矛盾路径。熔断后该不可行在 Phase1 即 BLOCKED，
        # 落入「Phase1 非 OPTIMAL」类别。
        for fragment in ("negative 不参与对拍", "无两侧齐备可优化项",
                         "Phase1 非 OPTIMAL"):
            self.assertIn(fragment, joined, f"缺跳过留痕类别：{fragment}")


if __name__ == "__main__":
    unittest.main()