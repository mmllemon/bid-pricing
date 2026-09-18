"""T03-05 判定层测试矩阵的**元测试**：矩阵自身必须有效。

本文件测的不是判定器，而是「那套测试集判得对不对」。五个判据族：

1. **制品与枚举**：78 格（13 约束 × 6 边界类）由制品声明，格 id 集合与
   「约束 × 边界」笛卡尔积逐项相等；每约束绑定一个具名单位（C13 为 null
   是**已声明**例外，不是漏登记）。
2. **覆盖审计**：未声明的空格 ⇒ BLOCKED（沉默不是断言）；零格 ⇒ BLOCKED；
   有人把某约束的探针清空 ⇒ 必须被发现（证明「缺格会被发现」而不是祈祷）。
3. **真实实现全绿 + 变异体全灭**：78 探针零失配；25 条变异体逐条被杀，
   且制品声明的 ``kills_by`` ⊆ 实际杀格（声明与实际不符即判据漂移）。
4. **覆盖面不依赖被测数据**（规则⑧）：枚举只吃制品，重复调用结果恒等，
   格数与任何实例取值无关。
5. **规则优先级 / 规则集切换**：A1–A4 全过；MP-01（阈值注入失效）必须被 A1
   抓住；L1 与 L2 必须**各自独立**可失败——只动元信息的注入不得影响 L1，
   只复制公式的注入不得靠 L2 蒙混。
"""

from __future__ import annotations

import unittest

from bidpricing.validation.judgment_matrix import (
    AGGREGATE_PROBES,
    CLASS_BOUNDARY_PLUS_1,
    CLASS_EXACT_BOUNDARY,
    CLASS_MISSING_INPUT,
    CLASS_NOMINAL,
    CLASS_NOT_ACTIVE,
    CLASS_OUT_OF_RANGE,
    PROBE_BUILDERS,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    MatrixCase,
    audit_coverage,
    audit_mutants,
    check_rule_precedence,
    check_ruleset_switch,
    enumerate_cases,
    evaluate_matrix,
    load_matrix_spec,
    run_matrix,
)

ALL_CLASSES = (CLASS_NOMINAL, CLASS_NOT_ACTIVE, CLASS_MISSING_INPUT,
               CLASS_OUT_OF_RANGE, CLASS_EXACT_BOUNDARY, CLASS_BOUNDARY_PLUS_1)
CONSTRAINTS = tuple(f"C{i}" for i in range(1, 14))
EXPECTED_CELLS = len(CONSTRAINTS) * len(ALL_CLASSES)   # 78


def _cached_run():
    if not hasattr(_cached_run, "_run"):
        _cached_run._run = run_matrix()       # noqa: SLF001
    return _cached_run._run                # noqa: SLF001


class TestSpecAndEnumeration(unittest.TestCase):
    """判据族 1：制品声明与枚举一致。"""

    @classmethod
    def setUpClass(cls):
        cls.spec = load_matrix_spec()
        cls.cases = enumerate_cases(cls.spec)

    def test_cell_count_is_declared_product(self):
        self.assertEqual(len(self.cases), EXPECTED_CELLS)
        self.assertEqual(
            self.spec["coverage_requirements"]["expected_total"], EXPECTED_CELLS)

    def test_cell_ids_are_full_cartesian_product(self):
        got = {(c.constraint_id, c.boundary_class) for c in self.cases}
        want = {(c, k) for c in CONSTRAINTS for k in ALL_CLASSES}
        self.assertEqual(got, want)
        self.assertEqual(len(got), len(self.cases), "格 id 不得重复")

    def test_every_constraint_has_named_boundary_unit(self):
        binding = self.spec["unit_binding"]
        for cid in CONSTRAINTS:
            self.assertIn(cid, binding, f"{cid} 未绑定具名单位（规则⑨）")
        # null 只允许出现在 C13，且必须有例外声明支撑
        nulls = {k for k, v in binding.items() if v is None and not k.startswith("_")}
        self.assertEqual(nulls, {"C13"})
        reasons = {(e["constraint_id"], e["class_id"]) for e in
                   self.spec["coverage_requirements"]["exceptions"]}
        self.assertEqual(len([r for r in reasons if r[0] == "C13"]), 5,
                         "C13 的 5 个不适用格必须逐格声明理由")

    def test_declared_boundary_unit_names_exist(self):
        units = {k for k in self.spec["boundary_units"] if not k.startswith("_")}
        for cid, name in self.spec["unit_binding"].items():
            if name is None or cid.startswith("_"):
                continue
            self.assertIn(name, units, f"{cid} 绑定了未登记的单位名 {name}")

    def test_every_constraint_has_a_builder(self):
        for cid in CONSTRAINTS:
            self.assertIn(cid, PROBE_BUILDERS)

    def test_missing_probe_for_declared_unit_is_flagged(self):
        """被声明为「有探针」的格一旦探针为空，覆盖审计必须报缺口。"""
        import bidpricing.validation.judgment_matrix as jm
        spec = self.spec
        orig = jm.PROBE_BUILDERS["C4"]
        try:
            jm.PROBE_BUILDERS["C4"] = lambda: {k: [] for k in ALL_CLASSES}
            cases = enumerate_cases(spec)
            rep = audit_coverage(spec, cases)
            self.assertEqual(rep.status, STATUS_BLOCKED)
            self.assertIn("C4/NOMINAL", rep.undeclared_gaps)
        finally:
            jm.PROBE_BUILDERS["C4"] = orig


class TestCoverageAudit(unittest.TestCase):
    """判据族 2：覆盖审计的三种结论可区分。"""

    @classmethod
    def setUpClass(cls):
        cls.spec = load_matrix_spec()

    def test_real_spec_passes(self):
        rep = audit_coverage(self.spec, enumerate_cases(self.spec))
        self.assertEqual(rep.status, STATUS_PASS)
        self.assertEqual(rep.declared_not_applicable, 12)
        self.assertEqual(rep.covered + rep.declared_not_applicable, EXPECTED_CELLS)

    def test_zero_cells_is_blocked_not_pass(self):
        rep = audit_coverage(self.spec, ())
        self.assertEqual(rep.status, STATUS_BLOCKED)

    def test_undeclared_gap_is_blocked(self):
        # 人为制造一个「有用例却零探针」的格
        cases = list(enumerate_cases(self.spec))
        for i, c in enumerate(cases):
            if c.case_id == "C9/NOMINAL":
                cases[i] = MatrixCase(c.case_id, c.constraint_id,
                                      c.boundary_class, True, ())
        rep = audit_coverage(self.spec, cases)
        self.assertEqual(rep.status, STATUS_BLOCKED)
        self.assertIn("C9/NOMINAL", rep.undeclared_gaps)

    def test_declared_exception_does_not_count_as_gap(self):
        rep = audit_coverage(self.spec, enumerate_cases(self.spec))
        self.assertEqual(rep.undeclared_gaps, ())


class TestMatrixAgainstRealImplementation(unittest.TestCase):
    """判据族 3a：真实实现必须零失配。"""

    @classmethod
    def setUpClass(cls):
        cls.spec = load_matrix_spec()
        cls.cases = enumerate_cases(cls.spec)

    def test_no_failed_cases(self):
        cr, ag = evaluate_matrix(spec=self.spec, cases=self.cases)
        failed = [c.case_id for c in cr if c.applicable and not c.matched]
        self.assertEqual(failed, [])
        self.assertEqual([a.probe_id for a in ag if not a.matched], [])

    def test_aggregate_probes_are_present(self):
        self.assertGreaterEqual(len(AGGREGATE_PROBES), 4)

    def test_case_status_reflects_mismatch(self):
        """把 judge_fn 换成恒 PASS 的替身 ⇒ 该格必须 FAIL（判据非自证）。"""
        from bidpricing.solver.constraint_judge import (
            ConstraintReport, ConstraintVerdict,
        )

        def broken(inputs, spec):                # noqa: ARG001
            return ConstraintReport(verdicts=(
                ConstraintVerdict("C1", STATUS_PASS, None, None, None, "P0"),
                ConstraintVerdict("C2", STATUS_FAIL, None, None, None, "P0"),
            ))
        cr, _ = evaluate_matrix(broken, spec=self.spec, cases=self.cases)
        c1_nominal = next(c for c in cr if c.case_id == "C1/NOMINAL")
        c1_out = next(c for c in cr if c.case_id == "C1/OUT_OF_RANGE")
        self.assertTrue(c1_nominal.matched)
        self.assertFalse(c1_out.matched)         # 期望 FAIL，替身给 PASS
        missing = [c.case_id for c in cr if c.applicable and not c.matched]
        self.assertIn("C1/OUT_OF_RANGE", missing)


class TestMutants(unittest.TestCase):
    """判据族 3b：每条变异体都必须被杀，且声明与实际对账。"""

    @classmethod
    def setUpClass(cls):
        cls.spec = load_matrix_spec()
        cls.cases = enumerate_cases(cls.spec)
        cls.mutants = audit_mutants(cls.spec, cls.cases)

    def test_all_mutants_killed(self):
        survived = [m.mutant_id for m in self.mutants if not m.killed]
        self.assertEqual(survived, [], f"存活变异体 = 判据盲区：{survived}")

    def test_mutant_count_matches_spec(self):
        self.assertEqual(len(self.mutants),
                         len(self.spec["mutants"]["entries"]))

    def test_declared_kills_by_is_actually_killed_by(self):
        """制品声明的 kills_by 是**下界**：声明的格必须真的杀掉它。"""
        declared = {e["mutant_id"]: list(e.get("kills_by", ()))
                    for e in self.spec["mutants"]["entries"]}
        by_id = {m.mutant_id: m for m in self.mutants}
        for mid, cells in declared.items():
            m = by_id[mid]
            for cell in cells:
                self.assertIn(cell, m.killed_by,
                              f"{mid} 声明由 {cell} 杀，实际杀格 {m.killed_by}")

    def test_no_mutant_targets_reason_text(self):
        """变异体不得依赖被测实现的可解释性文案（首轮 M-05/M-06 假存活的教训）。"""
        import inspect
        import bidpricing.validation.judgment_matrix as jm
        src = inspect.getsource(jm._mutator)      # noqa: SLF001
        for bad in ('"L 缺失" in', '"floor 缺失" in', '"漏报" in',
                    '"未提供 z" in'):
            self.assertNotIn(bad, src,
                             f"变异体判定依赖 reason 文案：{bad}")


class TestCoverageIndependentOfData(unittest.TestCase):
    """判据族 4：覆盖面由制品声明，不取决于被测数据（规则⑧）。"""

    @classmethod
    def setUpClass(cls):
        cls.spec = load_matrix_spec()

    def test_enumeration_is_pure_function_of_spec(self):
        a = [(c.case_id, len(c.probes)) for c in enumerate_cases(self.spec)]
        b = [(c.case_id, len(c.probes)) for c in enumerate_cases(self.spec)]
        self.assertEqual(a, b)

    def test_enumeration_ignores_instance_values(self):
        """枚举签名只吃 spec——实例取值再离谱也不改变格集合。"""
        import inspect
        sig = inspect.signature(enumerate_cases)
        self.assertEqual(list(sig.parameters), ["spec"])

    def test_probe_count_is_stable_across_runs(self):
        r1 = audit_coverage(self.spec, enumerate_cases(self.spec))
        r2 = audit_coverage(self.spec, enumerate_cases(self.spec))
        self.assertEqual(r1.probe_count, r2.probe_count)
        self.assertGreaterEqual(r1.probe_count, EXPECTED_CELLS - 12)


class TestRulePrecedence(unittest.TestCase):
    """判据族 5a：标准阈值与合同阈值并存 ⇒ 合同阈值必须生效。"""

    def test_all_checks_pass_on_real_implementation(self):
        rep = check_rule_precedence()
        self.assertEqual(rep.status, STATUS_PASS,
                         [c.detail for c in rep.checks if not c.passed])

    def test_contract_threshold_is_what_decides(self):
        rep = check_rule_precedence()
        by_id = {c.check_id: c for c in rep.checks}
        self.assertTrue(by_id["A1/contract-threshold-effective(decrease)"].passed)
        self.assertTrue(by_id["A1/contract-threshold-effective(increase)"].passed)

    def test_mutated_threshold_injection_is_caught(self):
        """MP-01：覆盖只改参数、判定仍走实现常量 ⇒ A1 必须失败。"""
        rep = check_rule_precedence(use_real=False)
        self.assertEqual(rep.status, STATUS_FAIL)
        failed = [c.check_id for c in rep.checks if not c.passed]
        self.assertIn("A1/contract-threshold-effective(decrease)", failed)

    def test_standard_layer_interlock_and_unknown_key(self):
        rep = check_rule_precedence()
        ids = {c.check_id for c in rep.checks if c.passed}
        self.assertIn("A3/standard-layer-interlock", ids)
        self.assertIn("A4/unregistered-key-blocked", ids)


class TestRuleSetSwitch(unittest.TestCase):
    """判据族 5b：2013 与 2024 同一输入下输出必须可区分（两层独立）。"""

    def test_full_numeric_separation(self):
        rep = check_ruleset_switch()
        by_id = {ly.layer_id: ly for ly in rep.layers}
        self.assertEqual(by_id["L1_NUMERIC@FULL"].status, STATUS_PASS)
        self.assertEqual(by_id["L2_META"].status, STATUS_PASS)

    def test_segment_is_declared_warn_not_pass(self):
        """SEGMENT 下数值指纹退化 ⇒ 必须是 WARN（不得记作「已区分」，规则⑤）。"""
        rep = check_ruleset_switch()
        by_id = {ly.layer_id: ly for ly in rep.layers}
        seg = by_id["L1_NUMERIC@SEGMENT"]
        self.assertEqual(seg.status, STATUS_WARN)
        self.assertIn("退化", seg.detail)

    def test_cloned_formula_is_caught_by_numeric_layer(self):
        """MR-01：公式被复制 ⇒ L1 必须 FAIL。"""
        rep = check_ruleset_switch(clone_2024=True)
        by_id = {ly.layer_id: ly for ly in rep.layers}
        self.assertEqual(by_id["L1_NUMERIC@FULL"].status, STATUS_FAIL)

    def test_cloned_meta_is_caught_only_by_meta_layer(self):
        """MR-02/MR-03：只动元信息 ⇒ L2 FAIL、L1 仍 PASS（两层判据独立）。"""
        for field in ("p1_source", "supported_scopes"):
            with self.subTest(field=field):
                rep = check_ruleset_switch(clone_meta_field=field)
                by_id = {ly.layer_id: ly for ly in rep.layers}
                self.assertEqual(by_id["L2_META"].status, STATUS_FAIL)
                self.assertEqual(by_id["L1_NUMERIC@FULL"].status, STATUS_PASS,
                                 "只动元信息的注入不应改变数值层结论")


class TestModeMutants(unittest.TestCase):
    """判据族 5c：MP-* / MR-* 六条模式变异体必须被杀。"""

    @classmethod
    def setUpClass(cls):
        cls.spec = load_matrix_spec()

    def test_all_mode_mutants_killed(self):
        from bidpricing.validation.judgment_matrix import audit_mode_mutants
        ms = audit_mode_mutants(self.spec)
        self.assertEqual(len(ms), 6)
        survived = [m.mutant_id for m in ms if not m.killed]
        self.assertEqual(survived, [])

    def test_mode_mutant_kills_by_declared(self):
        from bidpricing.validation.judgment_matrix import audit_mode_mutants
        ms = {m.mutant_id: m for m in audit_mode_mutants(self.spec)}
        declared = {}
        for key in ("rule_precedence", "ruleset_switch"):
            for e in self.spec[key]["mutants"]:
                declared[e["mutant_id"]] = list(e.get("kills_by", ()))
        for mid, cells in declared.items():
            for cell in cells:
                self.assertIn(cell, ms[mid].killed_by,
                              f"{mid} 声明由 {cell} 杀，实际 {ms[mid].killed_by}")


class TestMatrixVerdict(unittest.TestCase):
    """总结论语义：最严聚合 + 退化必须可见。"""

    def test_end_to_end_verdict(self):
        run = _cached_run()
        self.assertEqual(run.coverage.status, STATUS_PASS)
        self.assertEqual(run.failed_cases, ())
        self.assertEqual(run.surviving_mutants, ())
        self.assertEqual(run.rule_precedence.status, STATUS_PASS)
        # 规则集切换在 SEGMENT 下退化 ⇒ 总结论 WARN（可见但不阻塞）
        self.assertEqual(run.ruleset_switch.status, STATUS_WARN)
        self.assertEqual(run.verdict, STATUS_WARN)

    def test_report_serialisable(self):
        import json
        d = _cached_run().to_dict()
        json.dumps(d, ensure_ascii=False)
        self.assertEqual(d["cases_total"], EXPECTED_CELLS)
        self.assertEqual(d["mutants_surviving"], [])

    def test_verdict_is_fail_when_a_mutant_survives(self):
        """存活变异体 ⇒ 总结论必须 FAIL（而不是被『大部分被杀』稀释成 PASS）。"""
        import bidpricing.validation.judgment_matrix as jm
        real = jm.audit_mutants

        def _one_survivor(spec, cases):          # noqa: ARG001
            return (jm.MutantResult("M-Z", "C1", "桩：从不被任何探针否定", False),)

        try:
            jm.audit_mutants = _one_survivor
            run = jm.run_matrix(with_precedence=False, with_switch=False)
        finally:
            jm.audit_mutants = real
        self.assertEqual(run.verdict, STATUS_FAIL)
        self.assertEqual(run.surviving_mutants, ("M-Z",))

    def test_verdict_is_blocked_when_coverage_incomplete(self):
        """覆盖有未声明空格 ⇒ BLOCKED（不是 FAIL、更不是 PASS）。"""
        import bidpricing.validation.judgment_matrix as jm
        spec = load_matrix_spec()
        saved = jm.PROBE_BUILDERS["C2"]
        try:
            jm.PROBE_BUILDERS["C2"] = lambda: {k: [] for k in ALL_CLASSES}
            run = jm.run_matrix(spec=spec, with_mutants=False,
                                with_precedence=False, with_switch=False)
        finally:
            jm.PROBE_BUILDERS["C2"] = saved
        self.assertEqual(run.coverage.status, STATUS_BLOCKED)
        self.assertEqual(run.verdict, STATUS_BLOCKED)


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
