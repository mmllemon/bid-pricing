"""T01-06 D01–D12 校验器测试。

三部分：
1. 规范↔实现双向锁定（thresholds/levels/inputs 与 config/validation_rules.json
   逐字一致——防「同一规则两处说法」，ADR-0007 精神）；
2. 12 条规则逐条触发（阻断级 FAIL / 未定态 BLOCKED / 告警 WARN / 数据不足 SKIP）；
3. 端到端：通过样本全绿 + 失败样本聚合成 blocked=True。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.io.match import (
    AnomalyRow,
    MatchedItem,
    MatchReport,
)
from bidpricing.validation.checks import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    load_validation_rules,
    run_validation,
)

REPO = Path(__file__).resolve().parents[1]


def _mk(item_id: str = "041101001001", *, cap: float | None = 100.0,
        c_i: float | None = 80.0, q1: float | None = 10.0,
        no_cap: bool = False, cap_row: bool = True, cost_row: bool = True,
        attribution: str | None = "DRAWING_DIFF", code_kind: str = "STANDARD",
        pass_through: bool = False,
        source_sheet: str = "表-09 分部分项") -> MatchedItem:
    return MatchedItem(
        project_id="p1", unit_work="u1", item_id=item_id, code_kind=code_kind,
        item_name="变压器", unit="台", q0=10.0 if cap_row else None,
        cap=cap, no_cap=no_cap, cap_row=cap_row,
        q1_point=q1, c_i=c_i, cost_row=cost_row,
        attribution=attribution, pass_through=pass_through,
        provenance={"cost": {"source_sheet": source_sheet},
                    "cap": {"source_sheet": source_sheet}},
    )


def _report(items: list[MatchedItem], *, n_master: int | None = None,
            matched: int | None = None, duplicates: list[str] | None = None,
            blocked: bool = False) -> MatchReport:
    n_m = n_master if n_master is not None else len(items)
    n_matched = matched if matched is not None else sum(
        1 for it in items if it.cap_row and it.cost_row)
    return MatchReport(
        n_cap_rows=len(items), n_cost_rows=len(items), n_master=n_m,
        n_matched=n_matched, n_only_cap=0, n_only_cost=0, n_no_cap=0,
        duplicate_keys=duplicates or [], blocked=blocked, anomalies=[],
        items=items,
    )


CLS = {
    "code_system": "GB/T50500-2024",
    "covered_lists": [{"source_list": "BOQ"}, {"source_list": "TECH_MEASURE"}],
    "exceptions": [],
}
SEL = {"options": {"contract_type": {"value": "UNIT_PRICE"}}}
BASIS = {"cap_tax_scope": "EXCL_VAT", "cost_tax_scope": "EXCL_VAT"}
HIST = {"r_mean": 1.25, "r_std": 0.1}


class TestSpecImplementationLock(unittest.TestCase):
    """规范 ↔ 实现双向锁定。"""

    def setUp(self):
        self.spec = load_validation_rules(REPO / "config")

    def test_rule_ids_and_levels_match_spec(self):
        rules = {r["id"]: r for r in self.spec["rules"]}
        for i in range(1, 12):
            self.assertEqual(rules[f"D{i:02d}"]["level"], "BLOCK")
        self.assertEqual(rules["D13"]["level"], "BLOCK")
        d12 = rules["D12"]
        self.assertEqual(d12["level"], "WARN")
        self.assertEqual([s["id"] for s in d12["subrules"]],
                         ["W01", "W02", "W03"])

    def test_thresholds_are_the_single_source(self):
        th = self.spec["thresholds"]
        self.assertEqual(th["D05_min_coverage"], 0.98)
        self.assertEqual(th["D06_max_unknown_ratio"], 0.20)
        self.assertEqual(th["W01_max_unknown_value_share"], 0.15)
        self.assertEqual(th["W02_ratio_band"], [0.2, 5.0])
        self.assertEqual(th["W03_sigma"], 3.0)

    def test_every_rule_declares_rebase_rationale(self):
        for r in self.spec["rules"]:
            self.assertTrue(r.get("rebase", "").strip(),
                            f"{r['id']} 缺 rebase 依据")

    def test_basis_declarations_artifact_has_required_keys(self):
        """D08 事实源制品：必填键存在且口径在词表内（结构断言，不耦合取值）。"""
        bd = json.loads(
            (REPO / "config" / "basis_declarations.json").read_text(encoding="utf-8"))
        for k in ("cap_tax_scope", "cost_tax_scope", "default_attribution"):
            self.assertIn(k, bd, f"basis_declarations 缺 {k}")
        vocab = set(bd["tax_scope_vocabulary"])
        self.assertIn(bd["cap_tax_scope"], vocab)
        self.assertIn(bd["cost_tax_scope"], vocab)
        self.assertIn(bd["default_attribution"], bd["attribution_vocabulary"])


class TestBlockingRules(unittest.TestCase):
    """阻断级：FAIL（数据违反）与 BLOCKED（未定态）两条路径都要可触发。"""

    def validate(self, report, **kw):
        kw.setdefault("classification", CLS)
        kw.setdefault("selection", SEL)
        kw.setdefault("basis", BASIS)
        kw.setdefault("missing_unit_price_sheets", {"cap": [], "cost": []})
        return run_validation(report, **kw)

    def test_d01_duplicate_keys_fail(self):
        rep = self.validate(_report([_mk()], duplicates=["p1|u1|X (cap)"]))
        self.assertEqual(rep.by_rule("D01").status, STATUS_FAIL)
        self.assertIn("重复 key", rep.by_rule("D01").detail)

    def test_d01_unknown_recorded_not_blocking(self):
        rep = self.validate(_report([_mk(code_kind="UNKNOWN")]))
        self.assertEqual(rep.by_rule("D01").status, STATUS_PASS)
        self.assertIn("UNKNOWN", rep.by_rule("D01").detail)

    def test_d02_zero_and_missing_quantity_fail(self):
        rep = self.validate(_report([_mk("A", q1=0.0), _mk("B", q1=None)]))
        r = rep.by_rule("D02")
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertEqual(len(r.evidence), 2)

    def test_d02_pass_through_exempt(self):
        rep = self.validate(_report([_mk("A", q1=None, pass_through=True)]))
        self.assertEqual(rep.by_rule("D02").status, STATUS_PASS)

    def test_d03_zero_cap_fails_but_no_cap_passes(self):
        rep = self.validate(_report([_mk("A", cap=0.0)]))
        self.assertEqual(rep.by_rule("D03").status, STATUS_FAIL)
        rep2 = self.validate(_report([_mk("A", cap=None, no_cap=True)]))
        self.assertEqual(rep2.by_rule("D03").status, STATUS_PASS)
        self.assertIn("no_cap", rep2.by_rule("D03").detail)

    def test_d04_negative_cost_fails(self):
        rep = self.validate(_report([_mk("A", c_i=-1.0)]))
        self.assertEqual(rep.by_rule("D04").status, STATUS_FAIL)

    def test_d05_coverage_below_threshold_fails_with_missing_list(self):
        items = [_mk(f"K{i:03d}") for i in range(98)]
        items += [_mk(f"ONLY_CAP_{i}", cap=5.0, c_i=None, q1=None, cost_row=False)
                  for i in range(3)]
        rep = _report(items, n_master=101, matched=98)   # 98/101 ≈ 0.970 < 0.98
        out = self.validate(rep)
        r = out.by_rule("D05")
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertIn("ONLY_CAP_0", "".join(r.evidence))

    def test_d06_unlabeled_vs_unknown_are_two_failure_modes(self):
        rep = self.validate(_report([_mk("A", attribution=None)]))
        r = rep.by_rule("D06")
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertIn("未标注", r.detail)
        # UNKNOWN 20% 上限：5 项中 2 项 UNKNOWN = 40% > 20%
        items = [_mk(f"K{i}", attribution="CHANGE_ORDER") for i in range(3)] + \
                [_mk("U1", attribution="UNKNOWN"), _mk("U2", attribution="UNKNOWN")]
        rep2 = self.validate(_report(items))
        self.assertEqual(rep2.by_rule("D06").status, STATUS_FAIL)
        self.assertIn("UNKNOWN 占比", rep2.by_rule("D06").detail)

    def test_d07_floor_above_cap_infeasible(self):
        rep = self.validate(_report([_mk("A", cap=50.0, c_i=80.0)]))
        r = rep.by_rule("D07")
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertIn("可行域为空", r.detail)
        self.assertIn("loss_acceptance", r.detail)

    def test_d07_loss_acceptance_warns_with_loss_estimate(self):
        """用户裁定（ADR-0009）：loss_acceptance=ACCEPT → 亏损项 WARN 不阻塞。"""
        items = [_mk("A", cap=50.0, c_i=80.0, q1=10.0),   # 最低亏损 (80-50)*10=300
                 _mk("B", cap=100.0, c_i=80.0)]           # 正常项
        rep = self.validate(_report(items),
                            selection={"options": {
                                "contract_type": {"value": "UNIT_PRICE"},
                                "loss_acceptance": {"value": "ACCEPT"}}},
                            p_star=1000.0, p_star_max=2000.0)
        r = rep.by_rule("D07")
        self.assertEqual(r.status, STATUS_WARN)
        self.assertFalse(rep.blocked)
        self.assertIn("最低亏损 300", "".join(r.evidence))

    def test_d08_missing_declaration_blocked_inconsistency_fails(self):
        rep = self.validate(_report([_mk()]), basis=None)
        self.assertEqual(rep.by_rule("D08").status, STATUS_BLOCKED)
        rep2 = self.validate(_report([_mk()]),
                             basis={"cap_tax_scope": "EXCL_VAT",
                                    "cost_tax_scope": "INCL_VAT"})
        self.assertEqual(rep2.by_rule("D08").status, STATUS_FAIL)

    def test_d09_contract_type_missing_blocked(self):
        rep = self.validate(_report([_mk()]),
                            selection={"options": {}})
        self.assertEqual(rep.by_rule("D09").status, STATUS_BLOCKED)
        self.assertIn("contract_type", rep.by_rule("D09").detail)

    def test_d09_rho_absent_defaults_to_zero_note(self):
        rep = self.validate(_report([_mk()]))
        self.assertEqual(rep.by_rule("D09").status, STATUS_PASS)
        self.assertIn("rho 未声明按 0", rep.by_rule("D09").detail)

    def test_d10_covered_lists_missing_blocked(self):
        rep = self.validate(_report([_mk()]), classification={"code_system": "X"})
        self.assertEqual(rep.by_rule("D10").status, STATUS_BLOCKED)

    def test_d10_row_mapping_to_uncovered_list_fails(self):
        items = [_mk("A", source_sheet="表-10 施工组织措施")]
        rep = self.validate(_report(items),
                            sheet_roles={"表-10 施工组织措施": "ORG_MEASURE"})
        self.assertEqual(rep.by_rule("D10").status, STATUS_FAIL)
        self.assertIn("未覆盖清单", rep.by_rule("D10").detail)

    def test_d10_single_side_provenance_none_is_tolerated(self):
        """单侧项（ONLY_IN_CAP）的 provenance['cost']=None 不得炸行级映射。"""
        it = _mk("ONLY_CAP", cost_row=False)
        it.provenance = {"cap": {"source_sheet": "表-09 分部分项"}, "cost": None}
        rep = self.validate(_report([it]),
                            sheet_roles={"表-09 分部分项": "BOQ"})
        self.assertEqual(rep.by_rule("D10").status, STATUS_PASS)

    def test_d10_sheet_roles_absent_skips_row_subcheck(self):
        rep = self.validate(_report([_mk()]), sheet_roles=None)
        self.assertEqual(rep.by_rule("D10").status, STATUS_PASS)
        self.assertIn("SKIP", rep.by_rule("D10").detail)

    def test_d11_p_star_missing_blocked_out_of_band_fails(self):
        rep = self.validate(_report([_mk()]), p_star=None)
        self.assertEqual(rep.by_rule("D11").status, STATUS_BLOCKED)
        rep2 = self.validate(_report([_mk()]), p_star=2_000_000.0,
                             p_star_max=1_500_000.0)
        self.assertEqual(rep2.by_rule("D11").status, STATUS_FAIL)

    def test_d13_missing_price_column_blocked(self):
        """回归（A1）：缺单价列必须阻断，不得静默按「合法不限价」放行。"""
        rep = self.validate(_report([_mk()]),
                            missing_unit_price_sheets={"cap": ["表-09 分部分项"],
                                                       "cost": []})
        r = rep.by_rule("D13")
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertEqual(r.evidence[0], "cap:表-09 分部分项")
        self.assertTrue(rep.blocked)

    def test_d13_both_sides_clean_passes(self):
        rep = self.validate(_report([_mk()]),
                            missing_unit_price_sheets={"cap": [], "cost": []})
        self.assertEqual(rep.by_rule("D13").status, STATUS_PASS)

    def test_d13_fact_absent_blocked(self):
        """事实未提供 = 未定态，不得当成通过（沉默不是断言）。"""
        rep = run_validation(_report([_mk()]), classification=CLS, selection=SEL,
                            basis=BASIS)
        self.assertEqual(rep.by_rule("D13").status, STATUS_BLOCKED)
        self.assertIn("未提供列完整性事实", rep.by_rule("D13").detail)


class TestWarningRules(unittest.TestCase):
    def validate(self, items, **kw):
        kw.setdefault("classification", CLS)
        kw.setdefault("selection", SEL)
        kw.setdefault("basis", BASIS)
        return run_validation(_report(items), **kw)

    def test_w01_unknown_value_share_over_15pct_warns(self):
        items = [_mk("A", attribution="UNKNOWN", cap=90.0, c_i=80.0),
                 _mk("B", attribution="DRAWING_DIFF", cap=10.0, c_i=8.0)]
        r = self.validate(items).by_rule("W01")
        self.assertEqual(r.status, STATUS_WARN)
        self.assertIn("占比", r.detail)

    def test_w02_ratio_outside_band_warns(self):
        items = [_mk("A", cap=1000.0, c_i=80.0),   # 12.5 > 5.0
                 _mk("B", cap=10.0, c_i=80.0)]     # 0.125 < 0.2
        r = self.validate(items).by_rule("W02")
        self.assertEqual(r.status, STATUS_WARN)
        self.assertEqual(len(r.evidence), 2)

    def test_w02_normal_ratio_passes(self):
        r = self.validate([_mk()]).by_rule("W02")   # 100/80 = 1.25
        self.assertEqual(r.status, STATUS_PASS)

    def test_w03_no_history_explicit_skip(self):
        r = self.validate([_mk()], history=None).by_rule("W03")
        self.assertEqual(r.status, STATUS_SKIP)
        self.assertIn("数据不足", r.detail)

    def test_w03_deviation_over_3sigma_warns(self):
        r = self.validate([_mk(cap=100.0, c_i=20.0)],  # 均值 5.0
                          history={"r_mean": 1.25, "r_std": 0.1}).by_rule("W03")
        self.assertEqual(r.status, STATUS_WARN)


class TestEndToEndAggregation(unittest.TestCase):
    def test_clean_sample_all_pass(self):
        rep = run_validation(
            _report([_mk(f"K{i:03d}") for i in range(10)]),
            classification=CLS, selection=SEL, basis=BASIS,
            sheet_roles={"表-09 分部分项": "BOQ"},
            history=HIST, p_star=1_000_000.0, p_star_max=1_200_000.0,
            missing_unit_price_sheets={"cap": [], "cost": []})
        self.assertFalse(rep.blocked)
        self.assertEqual(rep.summary_line().split()[0], "✓")

    def test_failures_aggregate_to_blocked(self):
        items = [_mk("A", cap=0.0), _mk("B", c_i=-5.0)]
        rep = run_validation(_report(items), classification=CLS,
                             selection={"options": {}}, basis=None,
                             missing_unit_price_sheets={"cap": [], "cost": []})
        self.assertTrue(rep.blocked)
        d = rep.to_dict()
        self.assertTrue(d["blocked"])
        self.assertEqual(len(d["results"]), 15)   # 12 阻断 + 3 告警

    def test_report_serializable(self):
        rep = run_validation(_report([_mk()]), classification=CLS,
                             selection=SEL, basis=BASIS,
                             missing_unit_price_sheets={"cap": [], "cost": []})
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.json"
            p.write_text(json.dumps(rep.to_dict(), ensure_ascii=False),
                         encoding="utf-8")
            back = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(len(back["results"]), 15)


if __name__ == "__main__":
    unittest.main()
