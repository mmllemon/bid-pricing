"""T00-09 成本口径证明包 + T00-11 c_i 假设声明书测试。

主线：**成本来源未声明 = BLOCKED（不是 FAIL，也不是默认补全）**。
"""

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.validation.cost_basis import (
    REQUIRED_COMPONENTS,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    check_cost_basis,
)

CONFIG = Path(__file__).resolve().parents[1] / "config"


class RealRepoTest(unittest.TestCase):
    def setUp(self):
        self.rep = check_cost_basis(CONFIG)

    def test_basis_artifact_passes(self):
        for rule in ("CB-01", "CB-02", "CB-03", "CB-04", "CB-05"):
            self.assertEqual(self.rep.by_rule(rule).status, STATUS_PASS,
                             f"{rule}: {self.rep.by_rule(rule).detail}")

    def test_basis_rules_never_block(self):
        """**不耦合实时数据**：T00-09 制品层（CB-*）在任何时候都必须 PASS。

        成本来源（AS-01）是可演进的项目声明——今天是未定态、明天可能落值，
        断言它「必须 BLOCKED」会在落值当天变红。制品层没有这种自由度。
        """
        for rule in ("CB-01", "CB-02", "CB-03", "CB-04", "CB-05"):
            self.assertEqual(self.rep.by_rule(rule).status, STATUS_PASS)
        self.assertNotIn("CB-01", [r.rule_id for r in self.rep.blocking])

    def test_all_rules_reported(self):
        ids = {r.rule_id for r in self.rep.results}
        self.assertEqual(ids, {"CB-01", "CB-02", "CB-03", "CB-04", "CB-05",
                               "AS-01", "AS-02", "AS-03", "AS-04"})
        for r in self.rep.results:
            self.assertIn(r.status, (STATUS_PASS, STATUS_FAIL, STATUS_BLOCKED,
                                     STATUS_WARN, STATUS_SKIP))

    def test_report_serialisable(self):
        d = self.rep.to_dict()
        self.assertIn("summary", d)
        json.dumps(d, ensure_ascii=False)


class SyntheticCase(unittest.TestCase):
    """构造场景：验证判据对「说错了」与「没说」的区别对待。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cdir = Path(self.tmp.name)
        for fname in ("field_schema.json", "cost_basis_spec.json",
                      "cost_assumption_spec.json"):
            src = CONFIG / fname
            if src.exists():
                (self.cdir / fname).write_text(
                    src.read_text(encoding="utf-8"), encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)

    def _patch_assumption(self, **mut):
        p = self.cdir / "cost_assumption_spec.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        for k, v in mut.items():
            if k == "source_value":
                s["three_elements"]["source"]["value"] = v
            elif k == "frozen_at":
                s["frozen_at"] = v
            elif k == "format_value":
                s["three_elements"]["format"]["value"] = v
        p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

    def _patch_source_null(self):
        p = self.cdir / "cost_assumption_spec.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        s["three_elements"]["source"]["value"] = None
        p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_undeclared_source_is_blocked_not_defaulted(self):
        """来源未声明 = BLOCKED，且**绝不静默补全为任一取值**。"""
        self._patch_source_null()
        rep = check_cost_basis(self.cdir)
        r = rep.by_rule("AS-01")
        self.assertEqual(r.status, STATUS_BLOCKED)
        self.assertIn("来源未声明", r.detail)

    def test_declared_source_passes_and_requires_evidence(self):
        self._patch_assumption(source_value="SUPPLIER_QUOTE")
        rep = check_cost_basis(self.cdir)
        self.assertEqual(rep.by_rule("AS-01").status, STATUS_PASS)
        self.assertEqual(rep.by_rule("AS-02").status, STATUS_WARN)
        self.assertIn("询价日期", rep.by_rule("AS-02").detail)

    def test_cross_satisfied_evidence_not_re_asked(self):
        """税口径已由 CB-04 锁定 → 不得再要求重复声明（ADR-0002）。

        「没说」与「在别处说过一次」必须区分：重复索取同一声明只会制造
        告警疲劳，最终导致真正的缺证被一起忽略。
        """
        rep = check_cost_basis(self.cdir)
        detail = rep.by_rule("AS-02").detail
        self.assertNotIn("含税/不含税口径", detail)
        self.assertTrue(any("交叉满足" in e for e in rep.by_rule("AS-02").evidence))

    def test_stale_cross_reference_falls_back_to_explicit(self):
        """交叉引用指向不存在的判据 → 退回要求显式附证，不得静默放行。"""
        p = self.cdir / "cost_assumption_spec.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        s["three_elements"]["source"]["value"] = "SUPPLIER_QUOTE"
        s["three_elements"]["source"]["cross_satisfied_by"] = {
            "含税/不含税口径": "CB-99"}
        p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        rep = check_cost_basis(self.cdir)
        r = rep.by_rule("AS-02")
        self.assertIn("含税/不含税口径", r.detail)
        self.assertTrue(any("交叉引用失效" in e for e in r.evidence))

    def test_out_of_vocabulary_source_is_fail_not_blocked(self):
        """说了但说错了 = FAIL（数据违反），不是 BLOCKED（声明缺失）。"""
        self._patch_assumption(source_value="GUT_FEELING")
        rep = check_cost_basis(self.cdir)
        self.assertEqual(rep.by_rule("AS-01").status, STATUS_FAIL)

    def test_frozen_assumption_passes(self):
        self._patch_assumption(source_value="COST_DB", frozen_at="2026-09-17")
        rep = check_cost_basis(self.cdir)
        self.assertEqual(rep.by_rule("AS-04").status, STATUS_PASS)
        self.assertNotIn("AS-01", [r.rule_id for r in rep.blocking])

    def test_bad_format_is_fail(self):
        self._patch_assumption(format_value="FUZZY")
        rep = check_cost_basis(self.cdir)
        self.assertEqual(rep.by_rule("AS-03").status, STATUS_FAIL)

    def test_missing_artifacts_are_skipped_not_vacuous(self):
        (self.cdir / "cost_basis_spec.json").unlink()
        (self.cdir / "cost_assumption_spec.json").unlink()
        rep = check_cost_basis(self.cdir)
        self.assertEqual(rep.by_rule("CB-01").status, STATUS_SKIP)
        self.assertEqual(rep.by_rule("AS-01").status, STATUS_SKIP)


class ComponentIntegrityTest(unittest.TestCase):
    def test_real_spec_has_eight_components_in_order(self):
        spec = json.loads((CONFIG / "cost_basis_spec.json").read_text(encoding="utf-8"))
        keys = [c["key"] for c in spec["components"]]
        self.assertEqual(tuple(keys), REQUIRED_COMPONENTS)

    def test_each_component_has_evidence(self):
        spec = json.loads((CONFIG / "cost_basis_spec.json").read_text(encoding="utf-8"))
        for c in spec["components"]:
            self.assertTrue(c.get("definition"), c["key"])
            self.assertTrue(c.get("evidence"), c["key"])

    def test_partial_declaration_policy_is_blocked(self):
        """只声明部分科目 = 成本口径未知 → 规范须明令 BLOCKED。"""
        spec = json.loads((CONFIG / "cost_basis_spec.json").read_text(encoding="utf-8"))
        self.assertIn("BLOCKED", spec["aggregation"]["partial_declaration_policy"])

    def test_declared_source_is_user_not_agent(self):
        """ADR-0007 回归锁：成本来源属**用户商务声明**，Agent 不得代为落值。

        2026-09-17 曾由 Agent 擅自落值 SUPPLIER_QUOTE 并已回滚留痕；本测试
        把该失效模式固化——声明人字段一旦出现 agent 自填即失败。
        """
        spec = json.loads(
            (CONFIG / "cost_assumption_spec.json").read_text(encoding="utf-8"))
        src = spec["three_elements"]["source"]
        self.assertEqual(src["value"], "SUPPLIER_QUOTE")
        who = (src.get("declared_by") or "").lower()
        self.assertTrue(who.startswith("user"),
                        f"c_i 来源须由用户声明，实为 {src.get('declared_by')!r}")

    def test_cross_references_point_to_real_rules(self):
        """交叉满足引用的判据必须真实存在——死引用会让附证要求被静默豁免。"""
        spec = json.loads(
            (CONFIG / "cost_assumption_spec.json").read_text(encoding="utf-8"))
        cross = spec["three_elements"]["source"].get("cross_satisfied_by") or {}
        need = spec["three_elements"]["source"]["required_when"]
        known = {"CB-01", "CB-02", "CB-03", "CB-04", "CB-05",
                 "AS-01", "AS-02", "AS-03", "AS-04"}
        for k, rule_id in cross.items():
            if k.startswith("_"):
                continue
            self.assertIn(rule_id, known, f"交叉引用 {k}→{rule_id} 指向不存在的判据")
        # 交叉满足的项必须本来就在 required_when 里，否则是无意义的声明
        for k in cross:
            if k.startswith("_"):
                continue
            self.assertTrue(any(k in v for v in need.values()),
                            f"交叉满足项 {k} 不在任何来源的 required_when 中")


if __name__ == "__main__":
    unittest.main()
