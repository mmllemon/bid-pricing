"""T00-10A / T00-10B 结算工程量 q1 假设声明书判据测试。

与 test_cost_basis.py 的分工：本文件判的是**预测**的声明方式，不是事实的来源。
重心不同——q1 投标期不可观测，所以判「不确定性怎么表达」与「点值是否承担
敏感性义务」。

**去耦合约定**：真实仓库只断言**已定态**的事实（取值依据、归因、格式↔字段）。
QB-05（敏感性义务）当前是未定态，其状态会随用户裁定改变，故只在合成目录测
**行为**，不在真实仓库断言当前值。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.validation.cost_basis import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
)
from bidpricing.validation.quantity_basis import (
    FORMAT_FIELD_REQUIREMENT,
    check_quantity_basis,
)

CONFIG = Path(__file__).resolve().parent.parent / "config"


class SyntheticCase(unittest.TestCase):
    """构造场景：验证「说错了」「没说」「说了但没承担义务」的区别对待。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cdir = Path(self.tmp.name)
        for fname in ("field_schema.json", "basis_declarations.json",
                      "q1_assumption_spec.json"):
            src = CONFIG / fname
            if src.exists():
                (self.cdir / fname).write_text(
                    src.read_text(encoding="utf-8"), encoding="utf-8")
        # **基线归零**：真实制品里 sensitivity_requirement 已由用户裁定（RATIO_SCAN），
        # 若直接沿用，QB-05/QB-06 的「未定态」断言会随用户裁定而翻转——测试必须
        # 与项目的实时取值解耦，故合成目录一律从「未声明」起测。
        self._reset_undeclared()
        self.addCleanup(self.tmp.cleanup)

    def _reset_undeclared(self) -> None:
        p = self.cdir / "q1_assumption_spec.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        s["sensitivity_requirement"]["value"] = None
        s["sensitivity_requirement"].setdefault("scan_config", {})["grid"] = None
        s["frozen_at"] = None
        p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

    def _patch(self, mutate) -> None:
        p = self.cdir / "q1_assumption_spec.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        mutate(s)
        p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------- QB-01 取值依据 ----------------
    def test_undeclared_basis_is_blocked_not_defaulted(self):
        """未声明 = BLOCKED，且绝不静默补全为 Q0_NO_CHANGE。

        Q0_NO_CHANGE 看似「最保守」，实为放弃工程量套利的建模——是商务选择，
        不是默认值（ADR-0004）。
        """
        self._patch(lambda s: s["three_elements"]["basis"].__setitem__("value", None))
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-01").status, STATUS_BLOCKED)
        self.assertIn("Q0_NO_CHANGE", rep.by_rule("QB-01").detail)

    def test_out_of_vocabulary_basis_is_fail_not_blocked(self):
        self._patch(lambda s: s["three_elements"]["basis"].__setitem__(
            "value", "CRYSTAL_BALL"))
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-01").status, STATUS_FAIL)

    # ---------------- QB-02 差异归因（跨文件） ----------------
    def test_unknown_attribution_is_warn(self):
        p = self.cdir / "basis_declarations.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        s["default_attribution"] = "UNKNOWN"
        p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-02").status, STATUS_WARN)

    def test_missing_attribution_file_is_blocked(self):
        (self.cdir / "basis_declarations.json").unlink()
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-02").status, STATUS_BLOCKED)

    # ---------------- QB-03 附证交叉满足（ADR-0011 跨文件复用） ----------------
    def test_cross_satisfied_attribution_not_re_asked(self):
        rep = check_quantity_basis(self.cdir)
        detail = rep.by_rule("QB-03").detail
        self.assertNotIn("与 q0 差异归因", detail)
        self.assertTrue(any("交叉满足" in e for e in rep.by_rule("QB-03").evidence))

    def test_stale_cross_reference_falls_back_to_explicit(self):
        def mut(s):
            s["three_elements"]["basis"]["cross_satisfied_by"] = {
                "与 q0 差异归因": "QB-99"}
        self._patch(mut)
        rep = check_quantity_basis(self.cdir)
        r = rep.by_rule("QB-03")
        self.assertIn("与 q0 差异归因", r.detail)
        self.assertTrue(any("交叉引用失效" in e for e in r.evidence))

    def test_attribution_warn_does_not_satisfy_evidence(self):
        """QB-02 为 WARN（UNKNOWN）时，交叉满足不成立——归因不明等于没归因。"""
        p = self.cdir / "basis_declarations.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        s["default_attribution"] = "UNKNOWN"
        p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        rep = check_quantity_basis(self.cdir)
        self.assertIn("与 q0 差异归因", rep.by_rule("QB-03").detail)

    # ---------------- QB-04 格式 ↔ 字段字典 ----------------
    def test_interval_format_requires_both_bound_fields(self):
        """区间格式缺半个字段 = FAIL：区间信息无处落地，且不得塞进 q1_point。"""
        def mut(s):
            s["three_elements"]["format"]["value"] = "INTERVAL"
        self._patch(mut)
        # 先确认字段齐全时通过
        self.assertEqual(check_quantity_basis(self.cdir).by_rule("QB-04").status,
                         STATUS_PASS)
        # 再删掉 q1_hi
        p = self.cdir / "field_schema.json"
        fs = json.loads(p.read_text(encoding="utf-8"))
        fs["fields"] = [f for f in fs["fields"] if f["name"] != "q1_hi"]
        p.write_text(json.dumps(fs, ensure_ascii=False, indent=2), encoding="utf-8")
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-04").status, STATUS_FAIL)
        self.assertIn("q1_hi", rep.by_rule("QB-04").detail)

    def test_bad_format_is_fail(self):
        self._patch(lambda s: s["three_elements"]["format"].__setitem__(
            "value", "FUZZY"))
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-04").status, STATUS_FAIL)

    # ---------------- QB-05 点值假设的敏感性义务 ----------------
    def test_point_without_sensitivity_is_blocked(self):
        """点值 q1 未声明敏感性义务 = BLOCKED：预测被算成确定值，精度是虚假的。"""
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-05").status, STATUS_BLOCKED)

    def test_declared_sensitivity_passes(self):
        def mut(s):
            s["sensitivity_requirement"]["value"] = "RATIO_SCAN"
        self._patch(mut)
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-05").status, STATUS_PASS)

    def test_interval_format_needs_no_sensitivity(self):
        """区间/场景集自带不确定性表达，不再叠加敏感性义务。"""
        def mut(s):
            s["three_elements"]["format"]["value"] = "INTERVAL"
        self._patch(mut)
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-05").status, STATUS_PASS)
        self.assertIn("自带不确定性", rep.by_rule("QB-05").detail)

    def test_sensitivity_out_of_vocabulary_is_fail(self):
        def mut(s):
            s["sensitivity_requirement"]["value"] = "HOPE"
        self._patch(mut)
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-05").status, STATUS_FAIL)

    # ---------------- QB-06 扫描网格 ----------------
    def test_ratio_scan_without_grid_is_warn(self):
        """网格未定 = 敏感性分析无法执行；且须提示真实偏差范围而非 ±5%。"""
        def mut(s):
            s["sensitivity_requirement"]["value"] = "RATIO_SCAN"
        self._patch(mut)
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-06").status, STATUS_WARN)
        self.assertIn("0.4286", rep.by_rule("QB-06").detail)

    def test_declared_grid_passes(self):
        def mut(s):
            s["sensitivity_requirement"]["value"] = "RATIO_SCAN"
            s["sensitivity_requirement"]["scan_config"]["grid"] = [0.43, 0.6, 0.8, 1.0]
        self._patch(mut)
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-06").status, STATUS_PASS)

    def test_non_ratio_scan_needs_no_grid(self):
        def mut(s):
            s["sensitivity_requirement"]["value"] = "SCENARIO_SWEEP"
        self._patch(mut)
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-06").status, STATUS_PASS)

    # ---------------- QB-07 冻结 ----------------
    def test_unfrozen_is_warn_and_frozen_passes(self):
        self.assertEqual(check_quantity_basis(self.cdir).by_rule("QB-07").status,
                         STATUS_WARN)
        self._patch(lambda s: s.__setitem__("frozen_at", "2026-09-17"))
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-07").status, STATUS_PASS)

    def test_missing_artifact_is_skipped_not_vacuous(self):
        (self.cdir / "q1_assumption_spec.json").unlink()
        rep = check_quantity_basis(self.cdir)
        self.assertEqual(rep.by_rule("QB-01").status, STATUS_SKIP)


class RealRepoTest(unittest.TestCase):
    """真实仓库：只断言**已定态**的事实，不断言会变的未定态。"""

    def setUp(self):
        self.rep = check_quantity_basis(CONFIG)

    def test_declared_facts_pass(self):
        self.assertEqual(self.rep.by_rule("QB-01").status, STATUS_PASS)
        self.assertEqual(self.rep.by_rule("QB-02").status, STATUS_PASS)
        self.assertEqual(self.rep.by_rule("QB-04").status, STATUS_PASS)

    def test_all_rules_reported(self):
        ids = {r.rule_id for r in self.rep.results}
        self.assertEqual(ids, {"QB-01", "QB-02", "QB-03", "QB-04",
                               "QB-05", "QB-06", "QB-07"})

    def test_basis_is_declared_by_user_not_agent(self):
        """ADR-0007 回归锁：q1 取值依据属商务声明，不得由 Agent 代为落值。"""
        spec = json.loads(
            (CONFIG / "q1_assumption_spec.json").read_text(encoding="utf-8"))
        who = (spec["three_elements"]["basis"].get("declared_by") or "").lower()
        self.assertTrue(who.startswith("user"),
                        f"q1 取值依据须由用户声明，实为 "
                        f"{spec['three_elements']['basis'].get('declared_by')!r}")

    def test_attribution_matches_basis_declarations(self):
        """两处不得各说各话：spec 记录的引用值必须等于声明文件现值。"""
        spec = json.loads(
            (CONFIG / "q1_assumption_spec.json").read_text(encoding="utf-8"))
        decl = json.loads(
            (CONFIG / "basis_declarations.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["attribution_ref"]["current"],
                         decl.get("default_attribution"))

    def test_format_field_requirements_exist_in_schema(self):
        """格式要求的所有字段都必须在字段字典里——否则格式是空头支票。"""
        fs = json.loads((CONFIG / "field_schema.json").read_text(encoding="utf-8"))
        names = {f["name"] for f in fs["fields"]}
        for fmt, req in FORMAT_FIELD_REQUIREMENT.items():
            for n in req:
                self.assertIn(n, names, f"格式 {fmt} 需要字段 {n}")

    def test_cross_references_point_to_real_rules(self):
        spec = json.loads(
            (CONFIG / "q1_assumption_spec.json").read_text(encoding="utf-8"))
        base = spec["three_elements"]["basis"]
        known = {"QB-01", "QB-02", "QB-03", "QB-04", "QB-05", "QB-06", "QB-07"}
        for k, rule_id in (base.get("cross_satisfied_by") or {}).items():
            if k.startswith("_"):
                continue
            self.assertIn(rule_id, known)
            self.assertTrue(any(k in v for v in base["required_when"].values()),
                            f"交叉满足项 {k} 不在任何取值依据的 required_when 中")


if __name__ == "__main__":
    unittest.main()
