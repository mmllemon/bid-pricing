"""T04-02C 求解后端适配层的区分度测试（BB-01..BB-09 + 符号编码回归）。

两条纪律（与仓内其余测试同源）：

1. **每条判据都要有「什么会让它不通过」的用例**。只断言「真实制品上判 PASS」
   的测试对判据的否定能力毫无信息——一个恒真的判据也能全绿。
2. **不得依赖第三方库**。本文件在零依赖环境（无 PuLP）下必须全绿；需要真求解的
   分支用**注入后端**代替（``solve_compiled(backend=...)`` 正是为此留的注入点），
   并在本机缺 PuLP 时把相应断言降级为对常量表/编码函数的直接断言。
"""

from __future__ import annotations

import contextlib
import copy
import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.cli import config_dir
from bidpricing.contracts.pricing_card import load_pricing_card, resolve_parameters
from bidpricing.solver.backend import (
    CLASS_NOT_RUN,
    NORM_UNAVAILABLE,
    NORM_UNSUPPORTED,
    VIA_UNKNOWN_ALIAS,
    RawOutcome,
    StatusDomain,
    audit_source_tree,
    check_backend,
    load_backend_spec,
    normalize_status,
    probe_backend,
    required_capability,
    select_backend,
    solve_compiled,
)
from bidpricing.solver.compiler import (
    MODELER_MANGLED_CHARS,
    PULP_OBJECTIVE_SENSE,
    CompiledModel,
    CompiledRow,
    CompiledVar,
    check_compiled,
    compile_model,
    decode_symbol,
    encode_symbol,
    evaluate,
    load_compiler_spec,
    to_pulp,
)
from bidpricing.solver.formulation import (
    PROBE_SOLVER_INPUTS,
    build_formulation,
    load_formulation_spec,
    probe_instance,
)

PKG_ROOT = Path(__file__).resolve().parents[1] / "src" / "bidpricing"
REAL_SPEC = load_backend_spec(config_dir())

#: 探针 LP 变体的一个**手算可行解**（代入 evaluate 与 check_solution 双侧均可行）。
#: 取值由 C1 定出：500·1000 + 700·2000 + 600·1000 + 100·500 = 2,550,000 = B。
FEASIBLE_X = {
    "p_P-DEC": 500.0,
    "p_P-IN": 700.0,
    "p_P-INC": 600.0,
    "p_P-FREE": 100.0,
}


def _spec(**mutate) -> dict:
    """真实制品的深拷贝，按需改写。"""
    out = copy.deepcopy(REAL_SPEC)
    for key, value in mutate.items():
        if key == "_entry":
            name, patch = value
            for e in out["registry"]["entries"]:
                if e["name"] == name:
                    e.update(patch)
        elif key == "selection":
            out["selection"].update(value)
        elif key == "status":
            out["status"].update(value)
        else:
            out[key] = value
    return out


def _resolved():
    return resolve_parameters(load_pricing_card(config_dir()))


_PROBE_CACHE: dict[tuple, tuple] = {}


def _probe_model(*, active=()):
    """探针实例的编译结果。带缓存——``build_formulation`` 用的是真实制品，
    每次重算会让本文件的运行时间从秒级涨到几十秒，而模型本身是确定性的。"""
    key = tuple(active)
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    cfg = config_dir()
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    instance = probe_instance(active=active)
    fm = build_formulation(
        instance,
        _resolved(),
        eps_abs=float(prof["eps_abs"]["value"]),
        eps_price=float(prof["eps_price"]["value"]),
        resolution=float(prof["rounding"]["resolution"]),
        **{k: PROBE_SOLVER_INPUTS[k] for k in
           ("theta", "n_max", "d_max", "r_min", "z_min", "pi_target")},
    )
    model = compile_model(
        fm,
        z_min=PROBE_SOLVER_INPUTS["z_min"],
        pi_target=PROBE_SOLVER_INPUTS["pi_target"],
        source="LP",
    )
    _PROBE_CACHE[key] = (model, fm, instance)
    return _PROBE_CACHE[key]


@contextlib.contextmanager
def _tmp_src(files: dict[str, str]):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        yield root


class FakeBackend:
    """制品外的替身后端——BB-06 的可替换性检验面。

    它不实现任何真实求解：给定 ``native`` 与 ``x`` 就如实回传。用它可以在没有
    PuLP 的机器上把「选后端 → 求解 → 状态归一 → 解回读」整条链路跑通。
    """

    def __init__(self, *, name="fake", family="PULP", provides=("LP",),
                 native="Optimal", x=None, reported=None, has_incumbent=None):
        self.name = name
        self.family = family
        self.provides = provides
        self.native = native
        self.x = dict(FEASIBLE_X if x is None else x)
        self.reported = reported
        self.has_incumbent = has_incumbent
        self.calls = 0

    def available(self) -> bool:
        return True

    def solve(self, model, options):                # noqa: ARG002 - 接口固定
        self.calls += 1
        return RawOutcome(
            family=self.family,
            native_status=self.native,
            x=self.x,
            reported_objective=self.reported,
            has_incumbent=(
                bool(self.x) if self.has_incumbent is None else self.has_incumbent
            ),
            message="替身后端（制品外注入）",
        )


def _solve_with(model, *, spec=None, instance=None, backend=None, resolved=True,
                tolerances=None):
    return solve_compiled(
        model,
        spec=spec if spec is not None else REAL_SPEC,
        instance=instance,
        resolved=_resolved() if (resolved and instance is not None) else None,
        backend=backend,
        tolerances=tolerances,
    )


def _declared_tolerances(instance):
    """行声明容差名的解析表（唯一来源 = solution_verifier_spec + verifier）。"""
    from bidpricing.solver.verifier import load_verifier_spec, resolve_tolerances

    prof = json.loads(
        (config_dir() / "precision_profile.json").read_text(encoding="utf-8")
    )
    P_ref = instance.P_star if instance.P_star is not None else instance.B
    table, _problems = resolve_tolerances(
        prof, load_verifier_spec(config_dir()), P_ref=P_ref
    )
    return table


def _row(checks, prefix):
    row = next((r for r in checks if r.item.startswith(prefix)), None)
    assert row is not None, f"没有 {prefix} 行：{[r.item for r in checks]}"
    return row


# ---------------------------------------------------------------------------
# 归一状态域（BB-05 的机制侧）
# ---------------------------------------------------------------------------


class TestStatusDomain(unittest.TestCase):
    def setUp(self):
        self.domain = StatusDomain.from_spec(REAL_SPEC)

    def test_full_table_walk_is_deterministic(self):
        """全表遍历：每个原生别名都必须命中映射，不得落到兜底。"""
        self.assertGreater(len(self.domain.all_natives), 0)
        misses = []
        for family, native in self.domain.all_natives:
            for inc in (True, False):
                ns = normalize_status(
                    native, domain=self.domain, family=family, has_incumbent=inc
                )
                if ns.via == VIA_UNKNOWN_ALIAS:
                    misses.append((family, native))
                if ns.normalized not in self.domain.classes:
                    misses.append((family, native, ns.normalized))
        self.assertEqual(misses, [], f"未命中的别名：{misses}")

    def test_no_native_alias_lands_in_not_run_class(self):
        """NOT_RUN 类不得有原生来源——那是用「没跑」冒充求解结论。"""
        for family, native in self.domain.all_natives:
            for inc in (True, False):
                ns = normalize_status(
                    native, domain=self.domain, family=family, has_incumbent=inc
                )
                self.assertNotEqual(
                    ns.status_class, CLASS_NOT_RUN,
                    f"{family}:{native} 落进了 NOT_RUN 类",
                )

    def test_ambiguous_survives_as_its_own_state(self):
        """HiGHS 自己说分不清 ⇒ 必须保留 AMBIGUOUS，不得折进无解/无界。"""
        ns = normalize_status(
            "kUnboundedOrInfeasible", domain=self.domain,
            family="HIGHS", has_incumbent=False,
        )
        self.assertEqual(ns.normalized, "AMBIGUOUS")
        self.assertNotIn(ns.normalized, ("INFEASIBLE", "UNBOUNDED"))
        self.assertNotEqual(ns.judge, "FAIL")

    def test_pulp_undefined_is_ambiguous_not_infeasible(self):
        """PuLP 的 Undefined 自带歧义 ⇒ 不得替它选一个确定结论。"""
        ns = normalize_status(
            "Undefined", domain=self.domain, family="PULP", has_incumbent=False
        )
        self.assertEqual(ns.normalized, "AMBIGUOUS")

    def test_pulp_not_solved_is_unsolved_not_error(self):
        """「尚未求解」既不是无解也不是出错。"""
        ns = normalize_status(
            "Not Solved", domain=self.domain, family="PULP", has_incumbent=False
        )
        self.assertEqual(ns.normalized, "UNSOLVED")
        self.assertEqual(ns.status_class, "NO_CONCLUSION")

    def test_time_limit_splits_by_incumbent(self):
        """超时本身不含结论：有 incumbent ⇒ FEASIBLE，无 ⇒ UNSOLVED。"""
        with_inc = normalize_status(
            "kTimeLimit", domain=self.domain, family="HIGHS", has_incumbent=True
        )
        without = normalize_status(
            "kTimeLimit", domain=self.domain, family="HIGHS", has_incumbent=False
        )
        self.assertEqual(with_inc.normalized, "FEASIBLE")
        self.assertEqual(without.normalized, "UNSOLVED")
        self.assertNotEqual(with_inc.normalized, without.normalized)

    def test_unknown_alias_does_not_claim_a_conclusion(self):
        """没见过的原生状态 ⇒ 兜底为歧义，且保留原值；不得抛错、不得默认成最优。"""
        ns = normalize_status(
            "kSomeBrandNewStatus", domain=self.domain,
            family="HIGHS", has_incumbent=True,
        )
        self.assertEqual(ns.via, VIA_UNKNOWN_ALIAS)
        self.assertNotIn(ns.normalized, ("OPTIMAL", "INFEASIBLE", "FEASIBLE"))
        self.assertEqual(ns.native, "kSomeBrandNewStatus")

    def test_family_isolation_same_string_different_meaning(self):
        """同一字符串在两族里语义不同时必须分族查，不得扁平化。"""
        spec = _spec()
        spec["status"]["native_map"][0]["aliases"].append(
            {"native": "Optimal", "normalized": "ERROR"}
        )
        domain = StatusDomain.from_spec(spec)
        self.assertEqual(
            normalize_status("Optimal", domain=domain, family="PULP").normalized,
            "OPTIMAL",
        )
        self.assertEqual(
            normalize_status("Optimal", domain=domain, family="HIGHS").normalized,
            "ERROR",
        )

    def test_judge_table_never_maps_not_run_to_pass_or_fail(self):
        """NOT_RUN 类映到 PASS/FAIL 就是把流程状态冒充成业务结论。"""
        for sid, cls in self.domain.classes.items():
            if cls == CLASS_NOT_RUN:
                self.assertNotIn(self.domain.judges[sid], ("PASS", "FAIL"))

    def test_unsupported_is_blocked_but_unavailable_is_skip(self):
        """环境缺失（没跑）与机制缺失（做不到）分属不同档，不得合并。"""
        self.assertEqual(self.domain.judges["UNAVAILABLE"], "SKIP")
        self.assertEqual(self.domain.judges["UNSUPPORTED"], "BLOCKED")
        self.assertNotEqual(
            self.domain.classes["UNAVAILABLE"], "CONCLUSION"
        )


# ---------------------------------------------------------------------------
# BB-01 / BB-02 注册表与能力
# ---------------------------------------------------------------------------


class TestRegistryAndCapability(unittest.TestCase):
    def test_real_spec_registry_is_complete(self):
        model, _fm, instance = _probe_model()
        result = _solve_with(model, instance=instance)
        checks = check_backend(model, result, spec=REAL_SPEC, src_root=PKG_ROOT)
        self.assertEqual(_row(checks, "BB-01").status, "PASS")

    def test_bb01_blocks_when_active_not_declared(self):
        spec = _spec(selection={"active": "no_such_backend"})
        model, _fm, instance = _probe_model()
        result = _solve_with(model, spec=spec, instance=instance)
        checks = check_backend(model, result, spec=spec, src_root=PKG_ROOT)
        self.assertEqual(_row(checks, "BB-01").status, "BLOCKED")

    def test_bb01_blocks_when_implemented_adapter_has_no_body(self):
        spec = _spec(_entry=("pulp_cbc", {"adapter": "IMAGINARY"}))
        model, _fm, instance = _probe_model()
        result = _solve_with(model, spec=spec, instance=instance)
        checks = check_backend(model, result, spec=spec, src_root=PKG_ROOT)
        self.assertEqual(_row(checks, "BB-01").status, "BLOCKED")

    def test_bb02_passes_for_milp_when_backend_provides_milp(self):
        model, _fm, instance = _probe_model(active=("C7",))
        self.assertEqual(model.solver_form, "MILP")
        result = _solve_with(model, instance=instance)
        checks = check_backend(model, result, spec=REAL_SPEC, src_root=PKG_ROOT)
        self.assertEqual(_row(checks, "BB-02").status, "PASS")

    def test_bb02_blocks_when_no_candidate_provides_the_capability(self):
        """模型要 MILP 而所有后端只给 LP ⇒ BLOCKED（不得降级成 LP）。"""
        spec = _spec()
        for e in spec["registry"]["entries"]:
            e["provides"] = [c for c in e["provides"] if c != "MILP"]
        model, _fm, instance = _probe_model(active=("C7",))
        result = _solve_with(model, spec=spec, instance=instance)
        checks = check_backend(model, result, spec=spec, src_root=PKG_ROOT)
        self.assertEqual(_row(checks, "BB-02").status, "BLOCKED")

    def test_capability_short_candidate_is_never_selected(self):
        """被淘汰的能力不足候选不得出现在选中结果里。"""
        spec = _spec()
        for e in spec["registry"]["entries"]:
            if e["name"] == "pulp_highs":
                e["provides"] = ["LP"]          # 主动降能力
        sel = select_backend(spec, required=("MILP",), ignore_availability=True)
        self.assertNotEqual(sel.name, "pulp_highs")
        verdicts = {c.name: c.verdict for c in sel.candidates}
        self.assertEqual(verdicts.get("pulp_highs"), "CAPABILITY_SHORT")

    def test_zero_dependency_placeholder_is_never_selected_for_a_real_model(self):
        """零依赖占位后端不提供任何能力 ⇒ 真实模型永远选不到它。"""
        sel = select_backend(REAL_SPEC, required=("LP",), ignore_availability=True)
        self.assertNotEqual(sel.name, "none")
        self.assertEqual(sel.name, "pulp_highs")

    def test_unimplemented_entry_yields_unsupported_not_fallback(self):
        """声明未实现的条目 ⇒ UNSUPPORTED，且**不回退**到同能力的其它后端。"""
        spec = _spec(selection={"active": "highspy_direct", "fallback_chain": []})
        sel = select_backend(spec, required=("MILP",), ignore_availability=True)
        self.assertFalse(sel.ok)
        self.assertEqual(sel.normalized, NORM_UNSUPPORTED)
        self.assertIn("NOT_IMPLEMENTED", [c.verdict for c in sel.candidates])

    def test_required_capability_unknown_form_takes_the_union(self):
        """未识别形态取并集——宁可 BLOCKED，不得按低要求放行。"""
        self.assertEqual(set(required_capability("LP", REAL_SPEC)), {"LP"})
        self.assertEqual(set(required_capability("MILP", REAL_SPEC)), {"MILP"})
        self.assertEqual(
            set(required_capability("SOMETHING_NEW", REAL_SPEC)), {"LP", "MILP"}
        )


# ---------------------------------------------------------------------------
# BB-03 静态审计
# ---------------------------------------------------------------------------


class TestStaticAudit(unittest.TestCase):
    def test_real_source_has_no_solver_leak(self):
        """真实源码：求解器包只在允许模块内、且只在函数体内导入。"""
        self.assertEqual(audit_source_tree(PKG_ROOT, REAL_SPEC), [])

    def test_business_module_importing_pulp_is_flagged(self):
        with _tmp_src({"contracts/price.py": "import pulp\n"}) as root:
            found = audit_source_tree(root, REAL_SPEC)
        self.assertTrue(any("contracts/price.py" in f for f in found), found)

    def test_module_level_import_in_allowed_module_is_flagged(self):
        """豁免模块也只许**惰性**导入：模块级 import 会让「没装包」变成 ImportError。"""
        with _tmp_src({"solver/compiler.py": "import pulp\n"}) as root:
            found = audit_source_tree(root, REAL_SPEC)
        self.assertTrue(any("模块级" in f for f in found), found)

    def test_lazy_import_in_allowed_module_is_clean(self):
        with _tmp_src({
            "solver/compiler.py": "def f():\n    import pulp\n    return pulp\n"
        }) as root:
            self.assertEqual(audit_source_tree(root, REAL_SPEC), [])

    def test_solve_call_outside_adapter_is_flagged(self):
        with _tmp_src({
            "io/run.py": "def go(prob):\n    return prob.solve()\n"
        }) as root:
            found = audit_source_tree(root, REAL_SPEC)
        self.assertTrue(any(".solve()" in f for f in found), found)

    def test_solve_call_inside_adapter_is_clean(self):
        with _tmp_src({
            "solver/backend.py": "def go(prob):\n    return prob.solve()\n"
        }) as root:
            self.assertEqual(audit_source_tree(root, REAL_SPEC), [])


# ---------------------------------------------------------------------------
# BB-04 后端缺失 ≠ 模型错
# ---------------------------------------------------------------------------


def _spec_with_missing_packages(**mutate) -> dict:
    """把所有后端的 package 改成一个不存在的名字 ⇒ 制造**纯环境缺失**。

    这样「未跑路径」在两个环境下都可复现（装了 PuLP 的机器上也能造出「没装」），
    判据的覆盖面因此不取决于跑测试的机器装了什么。
    """
    spec = _spec(**mutate)
    for e in spec["registry"]["entries"]:
        if e.get("package"):
            e["package"] = "definitely_not_a_real_package_for_tests"
    return spec


class TestBackendMissing(unittest.TestCase):
    def test_unavailable_is_skip_and_says_why(self):
        spec = _spec_with_missing_packages()
        model, _fm, instance = _probe_model()
        result = _solve_with(model, spec=spec, instance=instance)
        self.assertEqual(result.status.normalized, NORM_UNAVAILABLE)
        self.assertEqual(result.status.status_class, CLASS_NOT_RUN)
        self.assertEqual(result.status.judge, "SKIP")
        checks = check_backend(model, result, spec=spec, src_root=PKG_ROOT)
        self.assertEqual(_row(checks, "BB-04").status, "PASS")

    def test_bb04_fails_if_unavailable_is_reported_as_infeasible(self):
        """把「没跑」映成「无解」是最贵的错——判据必须抓到。"""
        spec = _spec_with_missing_packages()
        for n in spec["status"]["normalized"]:
            if n["id"] == "UNAVAILABLE":
                n["class"] = "CONCLUSION"
                n["judge"] = "FAIL"
        model, _fm, instance = _probe_model()
        result = _solve_with(model, spec=spec, instance=instance)
        self.assertEqual(result.status.normalized, NORM_UNAVAILABLE)
        checks = check_backend(model, result, spec=spec, src_root=PKG_ROOT)
        self.assertEqual(_row(checks, "BB-04").status, "FAIL")

    def test_bb04_fails_when_unavailable_is_reported_as_a_solution(self):
        """未跑却声称拿到解——状态与事实矛盾。"""
        spec = _spec_with_missing_packages()
        for n in spec["status"]["normalized"]:
            if n["id"] == "UNAVAILABLE":
                n["class"] = "CONCLUSION"
                n["judge"] = "PASS"
        model, _fm, instance = _probe_model()
        result = _solve_with(model, spec=spec, instance=instance)
        checks = check_backend(model, result, spec=spec, src_root=PKG_ROOT)
        self.assertEqual(_row(checks, "BB-04").status, "FAIL")


# ---------------------------------------------------------------------------
# BB-05 全表遍历判据（含「判据自身失效」的反向用例）
# ---------------------------------------------------------------------------


class TestBB05(unittest.TestCase):
    def _run(self, spec):
        model, _fm, instance = _probe_model()
        result = _solve_with(model, spec=spec, instance=instance)
        return _row(
            check_backend(model, result, spec=spec, src_root=PKG_ROOT), "BB-05"
        )

    def test_passes_on_real_spec(self):
        self.assertEqual(self._run(REAL_SPEC).status, "PASS")

    def test_fails_when_an_alias_maps_into_not_run_class(self):
        spec = _spec()
        for fam in spec["status"]["native_map"]:
            for a in fam["aliases"]:
                if a.get("native") == "kInfeasible":
                    a.pop("conditional", None)
                    a["normalized"] = "UNAVAILABLE"
        row = self._run(spec)
        self.assertEqual(row.status, "FAIL")

    def test_fails_when_an_alias_has_no_target_value(self):
        """表里有一条没有落值的映射，等于没映射——不得静默当作已登记。"""
        spec = _spec()
        spec["status"]["native_map"][1]["aliases"].append({"native": "Ghost"})
        row = self._run(spec)
        self.assertEqual(row.status, "FAIL")

    def test_fails_when_native_aliases_leak_into_adapter_source(self):
        """映射表若在代码里也有一份，就成了第二个真相来源。"""
        spec = _spec()
        spec["status"]["native_map"][1]["aliases"].append(
            {"native": "leaked_alias_marker", "normalized": "OPTIMAL"}
        )
        with _tmp_src({
            "solver/backend.py": "X = 'leaked_alias_marker'\n",
            "solver/compiler.py": "",
        }) as root:
            model, _fm, instance = _probe_model()
            result = _solve_with(model, spec=spec, instance=instance)
            row = _row(
                check_backend(model, result, spec=spec, src_root=root), "BB-05"
            )
        self.assertEqual(row.status, "FAIL")
        self.assertIn("leaked_alias_marker", json.dumps(row.actual))

    def test_docstrings_are_not_treated_as_a_second_source(self):
        """说明文字不是代码拷贝——判据不得惩罚文档的详尽程度。"""
        spec = _spec()
        spec["status"]["native_map"][1]["aliases"].append(
            {"native": "documented_alias", "normalized": "OPTIMAL"}
        )
        with _tmp_src({
            "solver/backend.py": "\"\"\"doc mentions documented_alias\"\"\"\nX = 1\n",
            "solver/compiler.py": "",
        }) as root:
            model, _fm, instance = _probe_model()
            result = _solve_with(model, spec=spec, instance=instance)
            row = _row(
                check_backend(model, result, spec=spec, src_root=root), "BB-05"
            )
        self.assertEqual(row.status, "PASS")


# ---------------------------------------------------------------------------
# BB-06 换后端只改配置
# ---------------------------------------------------------------------------


class TestReplaceability(unittest.TestCase):
    def test_passes_on_real_spec(self):
        model, _fm, instance = _probe_model()
        result = _solve_with(model, instance=instance)
        checks = check_backend(model, result, spec=REAL_SPEC, src_root=PKG_ROOT)
        self.assertEqual(_row(checks, "BB-06").status, "PASS")

    def test_changing_active_changes_the_selected_backend(self):
        """「换后端只改配置」的字面含义：改一个字段，选中的条目跟着变。"""
        a = select_backend(REAL_SPEC, required=("LP",), ignore_availability=True)
        spec = _spec(selection={"active": "pulp_cbc", "fallback_chain": []})
        b = select_backend(spec, required=("LP",), ignore_availability=True)
        self.assertEqual(a.name, "pulp_highs")
        self.assertEqual(b.name, "pulp_cbc")
        self.assertNotEqual(a.name, b.name)

    def test_fails_when_there_is_no_second_candidate(self):
        """只有一个候选 ⇒ 没有证据 ⇒ FAIL，不得记成 PASS。"""
        spec = _spec()
        spec["registry"]["entries"] = [
            e for e in spec["registry"]["entries"] if e["name"] == "pulp_highs"
        ] + [e for e in spec["registry"]["entries"] if e["name"] == "none"]
        model, _fm, instance = _probe_model()
        result = _solve_with(model, spec=spec, instance=instance)
        checks = check_backend(model, result, spec=spec, src_root=PKG_ROOT)
        self.assertEqual(_row(checks, "BB-06").status, "FAIL")

    def test_fails_when_a_backend_name_sits_in_a_branch(self):
        with _tmp_src({
            "solver/backend.py": (
                "def pick(name):\n"
                "    if name == 'pulp_highs':\n"
                "        return 1\n"
                "    return 0\n"
            ),
            "solver/compiler.py": "",
        }) as root:
            model, _fm, instance = _probe_model()
            result = _solve_with(model, instance=instance)
            row = _row(
                check_backend(model, result, spec=REAL_SPEC, src_root=root), "BB-06"
            )
        self.assertEqual(row.status, "FAIL")
        self.assertIn("pulp_highs", json.dumps(row.actual))

    def test_injected_backend_runs_the_whole_pipeline_unchanged(self):
        """注入制品外的后端 ⇒ 整链路跑通，源码零改动。"""
        model, _fm, instance = _probe_model()
        fake = FakeBackend(native="Optimal", reported=420000.0)
        result = _solve_with(model, instance=instance, backend=fake)
        self.assertEqual(fake.calls, 1)
        self.assertEqual(result.status.normalized, "OPTIMAL")
        self.assertEqual(result.selection.name, "fake")
        self.assertEqual(set(result.variables), set(FEASIBLE_X))


# ---------------------------------------------------------------------------
# BB-07 求解器自报值 vs 独立复算
# ---------------------------------------------------------------------------


class TestObjectiveReconciliation(unittest.TestCase):
    def _checks(self, model, result):
        return check_backend(
            model, result, spec=REAL_SPEC, src_root=PKG_ROOT,
            instance=None, resolved=None,
        )

    def test_passes_when_reported_matches_recomputed(self):
        model, _fm, instance = _probe_model()
        expected = evaluate(model, FEASIBLE_X).objective
        fake = FakeBackend(reported=expected)
        result = _solve_with(model, instance=instance, backend=fake)
        self.assertEqual(_row(self._checks(model, result), "BB-07").status, "PASS")

    def test_fails_when_the_objective_constant_is_dropped(self):
        """导出层丢目标常量 ⇒ 结构完全正常、数值差一个常量。"""
        model, _fm, instance = _probe_model()
        expected = evaluate(model, FEASIBLE_X).objective
        fake = FakeBackend(reported=expected - model.objective_constant)
        result = _solve_with(model, instance=instance, backend=fake)
        row = _row(self._checks(model, result), "BB-07")
        self.assertEqual(row.status, "FAIL")
        self.assertNotEqual(row.delta, 0.0)

    def test_skips_without_a_solution(self):
        """没解 ⇒ SKIP（不是 PASS）：这条对账没做过，不得记成做过。"""
        model, _fm, instance = _probe_model()
        # 制造「跑了但没结论」：HiGHS 超时且没有 incumbent ⇒ UNSOLVED。
        fake = FakeBackend(family="HIGHS", native="kTimeLimit", x={})
        result = _solve_with(model, instance=instance, backend=fake)
        self.assertFalse(result.solved)
        row = _row(self._checks(model, result), "BB-07")
        self.assertEqual(row.status, "SKIP")
        self.assertIn("SKIP ≠ PASS", row.reason)


# ---------------------------------------------------------------------------
# BB-08 解的双侧可行性
# ---------------------------------------------------------------------------


class TestTwoSidedFeasibility(unittest.TestCase):
    def test_passes_when_both_sides_agree(self):
        model, _fm, instance = _probe_model()
        fake = FakeBackend(reported=420000.0)
        result = _solve_with(model, instance=instance, backend=fake)
        checks = check_backend(
            model, result, spec=REAL_SPEC, src_root=PKG_ROOT,
            instance=instance, resolved=_resolved(),
        )
        self.assertEqual(_row(checks, "BB-08").status, "PASS")

    def test_fails_on_infeasible_solution(self):
        model, _fm, instance = _probe_model()
        bad = dict(FEASIBLE_X, **{"p_P-FREE": 200.0})       # C1 残差 +50,000
        fake = FakeBackend(x=bad, reported=0.0)
        result = _solve_with(model, instance=instance, backend=fake)
        checks = check_backend(
            model, result, spec=REAL_SPEC, src_root=PKG_ROOT,
            instance=instance, resolved=_resolved(),
        )
        self.assertEqual(_row(checks, "BB-08").status, "FAIL")

    def test_fails_when_business_side_was_never_checked(self):
        """只做单侧就判 PASS 是本判据要拦的偷懒。"""
        model, _fm, instance = _probe_model()
        fake = FakeBackend(reported=420000.0)
        result = _solve_with(model, instance=None, backend=fake)
        self.assertIsNotNone(result.evaluation)
        self.assertIsNone(result.solution_check)
        checks = check_backend(
            model, result, spec=REAL_SPEC, src_root=PKG_ROOT,
            instance=None, resolved=None,
        )
        self.assertEqual(_row(checks, "BB-08").status, "FAIL")


class TestBB08ToleranceCaliber(unittest.TestCase):
    """DV-01 的后端侧回归：**合法的**求解器回传不得被判「导出层走样」。

    注入 C1 残差 5.0e-9 —— 它在行上声明的内层容差 ``eps_solver = 1e-8`` **之内**，
    即一个合法的求解器回传。旧口径（不传容差表）下它落在 ``[1e-12, 1e-8]`` 带内，
    被判不可行，BB-08 会给出**错误归因**「求解器在另一个模型上求了最优解」。
    """

    def _band_x(self, model):
        q0 = dict(next(r for r in model.rows if r.constraint_id == "C1").coefficients)
        x = dict(FEASIBLE_X)
        x["p_P-DEC"] = x["p_P-DEC"] + 5e-9 / q0["p_P-DEC"]
        return x

    def test_band_residual_no_longer_gets_the_export_layer_diagnosis(self):
        model, _fm, instance = _probe_model()
        fake = FakeBackend(x=self._band_x(model), reported=420000.0)

        legacy = _solve_with(model, instance=instance, backend=fake)
        self.assertFalse(legacy.tolerances_applied)
        self.assertFalse(legacy.evaluation.feasible)
        row = _row(check_backend(
            model, legacy, spec=REAL_SPEC, src_root=PKG_ROOT,
            instance=instance, resolved=_resolved(),
        ), "BB-08")
        self.assertEqual(row.status, "FAIL")
        # 关键的修正在归因上：不得再说「导出层走样」，而要说口径不足。
        self.assertNotIn("导出层走样", row.reason)
        self.assertIn("未传入", row.reason)

    def test_same_solution_passes_once_the_declared_table_is_supplied(self):
        model, _fm, instance = _probe_model()
        fake = FakeBackend(x=self._band_x(model), reported=420000.0)
        fixed = _solve_with(
            model, instance=instance, backend=fake,
            tolerances=_declared_tolerances(instance),
        )
        self.assertTrue(fixed.tolerances_applied)
        self.assertTrue(fixed.evaluation.feasible,
                        "5e-9 在声明的 eps_solver=1e-8 之内 ⇒ 可行性判通过")
        c1 = next(r for r in fixed.evaluation.rows if r.constraint_id == "C1")
        self.assertTrue(c1.in_tolerance_band)
        row = _row(check_backend(
            model, fixed, spec=REAL_SPEC, src_root=PKG_ROOT,
            instance=instance, resolved=_resolved(),
        ), "BB-08")
        self.assertEqual(row.status, "PASS")

    def test_beyond_the_declared_tolerance_is_still_fail(self):
        """区分度：真要越过声明容差时，BB-08 必须仍然 FAIL。"""
        model, _fm, instance = _probe_model()
        q0 = dict(next(r for r in model.rows if r.constraint_id == "C1").coefficients)
        x = dict(FEASIBLE_X)
        x["p_P-DEC"] = x["p_P-DEC"] + 1e-5 / q0["p_P-DEC"]     # 1000× eps_solver
        fake = FakeBackend(x=x, reported=420000.0)
        result = _solve_with(
            model, instance=instance, backend=fake,
            tolerances=_declared_tolerances(instance),
        )
        self.assertFalse(result.evaluation.feasible)
        row = _row(check_backend(
            model, result, spec=REAL_SPEC, src_root=PKG_ROOT,
            instance=instance, resolved=_resolved(),
        ), "BB-08")
        self.assertEqual(row.status, "FAIL")
        self.assertIn("导出层走样", row.reason)      # 口径正确时才允许下这个结论

    def test_solveresult_dict_exposes_the_caliber(self):
        model, _fm, instance = _probe_model()
        fake = FakeBackend(x=dict(FEASIBLE_X), reported=420000.0)
        result = _solve_with(model, instance=instance, backend=fake)
        self.assertIn("tolerances_applied", result.to_dict())

    def test_partial_table_is_blocked_not_pass(self):
        """表在、但缺盒式容差名 ⇒ 业务侧按**严格口径**判 ⇒ 两侧不可比。

        这不是 PASS（口径可比）也不是 FAIL（发现了问题），而是 BLOCKED
        （这一环没查成）。把它误判成 PASS，就等于用一个没定义过的宽度
        冒充了「两侧一致」——同源规则②：未定态不得降级。
        """
        model, _fm, instance = _probe_model()
        fake = FakeBackend(x=dict(FEASIBLE_X), reported=420000.0)
        partial = {"eps_solver": 1e-8, "eps_total": 0.01}      # 刻意缺 eps_price
        result = _solve_with(model, instance=instance, backend=fake,
                             tolerances=partial)
        self.assertTrue(result.tolerances_applied)
        self.assertIsNotNone(result.solution_check)
        self.assertTrue(result.solution_check.feasible)
        self.assertEqual(result.solution_check.tolerance_name, "eps_price")
        self.assertFalse(result.solution_check.tolerance_resolved)
        row = _row(check_backend(
            model, result, spec=REAL_SPEC, src_root=PKG_ROOT,
            instance=instance, resolved=_resolved(),
        ), "BB-08")
        self.assertEqual(row.status, "BLOCKED")
        self.assertIn("未解析", row.reason)

    def test_full_table_resolves_the_box_caliber(self):
        """区分度：表里**有**该名时，口径自述为「已解析」且判 PASS。"""
        model, _fm, instance = _probe_model()
        fake = FakeBackend(x=dict(FEASIBLE_X), reported=420000.0)
        result = _solve_with(
            model, instance=instance, backend=fake,
            tolerances=_declared_tolerances(instance),
        )
        self.assertTrue(result.solution_check.tolerance_resolved)
        self.assertAlmostEqual(result.solution_check.tolerance_value, 0.003,
                               places=12)
        row = _row(check_backend(
            model, result, spec=REAL_SPEC, src_root=PKG_ROOT,
            instance=instance, resolved=_resolved(),
        ), "BB-08")
        self.assertEqual(row.status, "PASS")


# ---------------------------------------------------------------------------
# BB-09 CC-09 的闭合
# ---------------------------------------------------------------------------


class TestCC09Closure(unittest.TestCase):
    @staticmethod
    def _cc09(status):
        from bidpricing.solver.compiler import CompilerCheck

        return (CompilerCheck("CC", "CC-09 PuLP 后端结构等价", status, "stub"),)

    def test_skips_with_rerun_condition_when_pulp_is_absent(self):
        """PuLP 不在 ⇒ SKIP 且必须带复跑条件（不得无声通过）。

        用猴补 ``_package_importable`` 制造「没装」，使本用例在装了 PuLP 的机器上
        也可复现——判据是否被跑过，不该取决于机器装了什么。
        """
        import bidpricing.solver.backend as be

        original = be._package_importable
        be._package_importable = lambda pkg: False
        try:
            model, _fm, instance = _probe_model()
            result = _solve_with(model, instance=instance)
            row = _row(
                check_backend(
                    model, result, spec=REAL_SPEC, src_root=PKG_ROOT,
                    cc09=self._cc09("SKIP"),
                ),
                "BB-09",
            )
        finally:
            be._package_importable = original
        self.assertEqual(row.status, "SKIP")
        self.assertIn("复跑条件", row.reason)

    def test_fails_when_pulp_present_but_cc09_not_pass(self):
        import bidpricing.solver.backend as be

        original = be._package_importable
        be._package_importable = lambda pkg: True          # 假装装了 PuLP
        try:
            model, _fm, instance = _probe_model()
            result = _solve_with(model, instance=instance)
            row = _row(
                check_backend(
                    model, result, spec=REAL_SPEC, src_root=PKG_ROOT,
                    cc09=self._cc09("FAIL"),
                ),
                "BB-09",
            )
        finally:
            be._package_importable = original
        self.assertEqual(row.status, "FAIL")

    def test_passes_when_pulp_present_and_cc09_pass(self):
        import bidpricing.solver.backend as be

        original = be._package_importable
        be._package_importable = lambda pkg: True
        try:
            model, _fm, instance = _probe_model()
            result = _solve_with(model, instance=instance)
            row = _row(
                check_backend(
                    model, result, spec=REAL_SPEC, src_root=PKG_ROOT,
                    cc09=self._cc09("PASS"),
                ),
                "BB-09",
            )
        finally:
            be._package_importable = original
        self.assertEqual(row.status, "PASS")


# ---------------------------------------------------------------------------
# 符号编码：CC-09 复跑抓到的真 bug 的回归
# ---------------------------------------------------------------------------


class TestSymbolEncoding(unittest.TestCase):
    def test_roundtrip_on_probe_symbols(self):
        model, _fm, _instance = _probe_model()
        for v in model.variables:
            self.assertEqual(decode_symbol(encode_symbol(v.symbol)), v.symbol)

    def test_encoding_avoids_every_character_the_modeler_mangles(self):
        """编码结果必须与建模器的净化字符集**不相交**。

        ``MODELER_MANGLED_CHARS`` 是穷举实测出来的（PuLP 3.3.2 只动这七个），
        故本断言直接对着那份清单判——若将来某个建模器多净化一个字符，这里会
        先红，而不是等到解回读时以「变量全部缺失」的形态出现。
        """
        mangled = set(MODELER_MANGLED_CHARS)
        for sym in ("a-b", "a b", "x[0]", "p/1", "甲-乙", "a_b", "a>b", "a+b"):
            safe = encode_symbol(sym)
            self.assertFalse(
                set(safe) & mangled,
                f"{sym!r} -> {safe!r} 含建模器会改动的字符",
            )
            self.assertEqual(decode_symbol(safe), sym)

    def test_modeler_leaves_encoded_names_untouched(self):
        """白名单的效力必须实测，不能只靠文档：编码后的名字原样存进去。"""
        try:
            import pulp                                # noqa: PLC0415
        except ImportError:
            self.skipTest("本机未装 PuLP ⇒ 无法验证建模器行为")
        for sym in ("a-b", "a b", "x[0]", "p/1", "甲-乙", "a_b", "a>b"):
            safe = encode_symbol(sym)
            self.assertEqual(pulp.LpVariable(safe).name, safe)

    def test_encoding_is_injective_where_pulp_would_have_merged_them(self):
        """PuLP 会把 `-` `/` 空格 `[` `]` `+` 一律换成 `_`：`a-b` 与 `a_b` 会合并。

        本仓的编码必须先一步把它们分开——这是导出层唯一灾难性的失败。
        """
        pairs = [("a-b", "a_b"), ("a b", "a_b"), ("x[0]", "x_0_"), ("p+1", "p_1")]
        for left, right in pairs:
            self.assertNotEqual(
                encode_symbol(left), encode_symbol(right),
                f"{left!r} 与 {right!r} 编码后被合并",
            )

    def test_encoding_is_injective_on_the_real_symbol_set(self):
        model, _fm, _instance = _probe_model(active=("C7",))
        safe = [encode_symbol(v.symbol) for v in model.variables]
        self.assertEqual(len(set(safe)), len(safe), "真实符号集上编码不单射")

    def test_objective_sense_table_matches_pulp_constants(self):
        """方向常量实测：PuLP 的 LpMinimize = 1、LpMaximize = -1（与直觉相反）。

        对反了会把「最大化」读成「最小化」——这正是 CC-09 补齐覆盖面后立刻抓到
        的一处真问题（ADR-0023 决策四）。
        """
        self.assertEqual(PULP_OBJECTIVE_SENSE[1], "MINIMIZE")
        self.assertEqual(PULP_OBJECTIVE_SENSE[-1], "MAXIMIZE")
        try:
            import pulp                                # noqa: PLC0415
        except ImportError:
            return
        self.assertEqual(PULP_OBJECTIVE_SENSE[pulp.LpMinimize], "MINIMIZE")
        self.assertEqual(PULP_OBJECTIVE_SENSE[pulp.LpMaximize], "MAXIMIZE")

    def test_to_pulp_is_lazy(self):
        """没装 PuLP ⇒ 返回 None（调用方判 SKIP），装了 ⇒ 返回对象。

        「没装」不得抛 ImportError——那会把「本轮没检查」变成流程崩溃。
        """
        model, _fm, _instance = _probe_model()
        got = to_pulp(model)
        if probe_backend({"package": "pulp"}).available:
            self.assertIsNotNone(got)
        else:
            self.assertIsNone(got, "未装 PuLP 时应返回 None 而不是抛错")


# ---------------------------------------------------------------------------
# CC-09 覆盖面：注入错误必须被新补的覆盖面抓到
# ---------------------------------------------------------------------------


class _EmptyFormulation:
    """给 ``check_compiled`` 的最小声明桩：本测试只断言 CC-09 一行。

    其它判据（CC-01/02/04 等）会因为「声明为空」而 FAIL/SKIP，与本测试无关。
    """

    variables: tuple = ()
    rows: tuple = ()
    objective_constant: float = 0.0
    objective_sense: str = "MAXIMIZE"
    box_notes: tuple = ()


def _tiny_model(**patch) -> CompiledModel:
    """一个两变量一行的小模型，够 CC-09 比出结构差异。"""
    fields = {
        "variables": (
            CompiledVar("p_a", "p", "A", "CONTINUOUS", 0.0, 10.0, 3.0),
            CompiledVar("p_b", "p", "B", "CONTINUOUS", 0.0, 10.0, 5.0),
        ),
        "rows": (
            CompiledRow("C1", "C1:eq", "EQ", "==", 12.0,
                        (("p_a", 1.0), ("p_b", 2.0)), "absolute"),
        ),
        "objective_sense": "MAXIMIZE",
        "objective_constant": -7.0,
        "solver_form": "LP",
        "source": "test",
    }
    fields.update(patch)
    return CompiledModel(**fields)


class TestCC09Coverage(unittest.TestCase):
    """CC-09 的三种「结构正常、语义错」的走样必须被抓到。

    它们都满足旧版 CC-09 的全部比对项（变量集、行数、逐行 sense、逐行 rhs、
    目标系数）——这正是 T04-02C 补齐覆盖面的理由。

    **怎么构造走样**：CC-09 比的是「导出层交出来的东西」与「声明的模型」。
    所以要让它失配，必须让导出层拿到的是**另一份**模型（这正是「翻译走样」的
    语义：声明是 M，导出的却是 M′）。故此处猴补 ``to_pulp``，令它把一份带缺陷的
    模型交给真正的导出实现。
    """

    def setUp(self):
        try:
            import pulp                                # noqa: F401,PLC0415
        except ImportError:
            self.skipTest("CC-09 的实战分支需要 PuLP（本机未装）")

    def _install_broken_exporter(self, defect: CompiledModel):
        import bidpricing.solver.compiler as compiler

        original = compiler.to_pulp
        compiler.to_pulp = lambda _model: original(defect)
        self.addCleanup(lambda: setattr(compiler, "to_pulp", original))

    def _cc09(self, model):
        rows = check_compiled(
            model, _EmptyFormulation(),
            constraint_schema=None, formulation_spec=None,
            compiler_source=None, eps_total=0.0,
        )
        return next(r for r in rows if r.item.startswith("CC-09"))

    def test_clean_model_passes(self):
        self.assertEqual(self._cc09(_tiny_model()).status, "PASS")

    def test_row_coefficient_swap_is_caught(self):
        """系数漏乘/错位：sense 与 rhs 都不变，只有系数换了。"""
        self._install_broken_exporter(_tiny_model(rows=(
            CompiledRow("C1", "C1:eq", "EQ", "==", 12.0,
                        (("p_a", 2.0), ("p_b", 1.0)), "absolute"),
        )))
        self.assertEqual(self._cc09(_tiny_model()).status, "FAIL")

    def test_objective_constant_sign_is_caught(self):
        self._install_broken_exporter(_tiny_model(objective_constant=7.0))
        self.assertEqual(self._cc09(_tiny_model()).status, "FAIL")

    def test_reversed_objective_sense_is_caught(self):
        self._install_broken_exporter(_tiny_model(objective_sense="MINIMIZE"))
        self.assertEqual(self._cc09(_tiny_model()).status, "FAIL")

    def test_extra_row_is_caught(self):
        self._install_broken_exporter(_tiny_model(rows=(
            CompiledRow("C1", "C1:eq", "EQ", "==", 12.0,
                        (("p_a", 1.0), ("p_b", 2.0)), "absolute"),
            CompiledRow("C1", "C1:eq", "EQ", "==", 3.0,
                        (("p_a", 1.0),), "absolute"),
        )))
        self.assertEqual(self._cc09(_tiny_model()).status, "FAIL")

    def test_objective_coefficient_change_is_caught(self):
        self._install_broken_exporter(_tiny_model(variables=(
            CompiledVar("p_a", "p", "A", "CONTINUOUS", 0.0, 10.0, 3.0),
            CompiledVar("p_b", "p", "B", "CONTINUOUS", 0.0, 10.0, 9.0),
        )))
        self.assertEqual(self._cc09(_tiny_model()).status, "FAIL")

    def test_non_injective_encoding_is_caught(self):
        """编码若不单射，两个符号会被建模器静默合并成一个变量。

        这是导出层唯一灾难性的失败，故单独有一条覆盖面：直接从编码函数入手
        制造合并（而不是从模型入手——模型侧改符号只会落在「变量集不同」上）。
        """
        import bidpricing.solver.compiler as compiler

        original = compiler.encode_symbol
        compiler.encode_symbol = lambda s: s.replace("-", "_")   # 制造合并
        self.addCleanup(lambda: setattr(compiler, "encode_symbol", original))
        model = _tiny_model(
            variables=(
                CompiledVar("p_a-b", "p", "A", "CONTINUOUS", 0.0, 10.0, 3.0),
                CompiledVar("p_a_b", "p", "B", "CONTINUOUS", 0.0, 10.0, 5.0),
            ),
            rows=(
                CompiledRow("C1", "C1:eq", "EQ", "==", 12.0,
                            (("p_a-b", 1.0), ("p_a_b", 2.0)), "absolute"),
            ),
        )
        row = self._cc09(model)
        self.assertEqual(row.status, "FAIL")
        self.assertIn("不单射", row.reason)

    def test_symbol_closure_gap_blocks_instead_of_crashing(self):
        """判据不得在它该拦的输入上崩：符号闭包缺口 ⇒ BLOCKED，不是异常。"""
        model = _tiny_model(rows=(
            CompiledRow("C1", "C1:eq", "EQ", "==", 12.0,
                        (("p_ghost", 1.0),), "absolute"),
        ))
        row = self._cc09(model)
        self.assertEqual(row.status, "BLOCKED")
        self.assertIn("p_ghost", row.reason)


class TestSpecLock(unittest.TestCase):
    """制品与实现的**双向锁定**——任何一侧改动而另一侧未同步即失败。

    与 T04-00 的 ``SpecLockTest`` 同构：制品声明了哪些判据、实现实际产出哪些判据，
    两侧必须逐字对齐。只在单侧加一条判据（制品加了实现没加，或反之）都会红。
    """

    def setUp(self):
        self.spec = REAL_SPEC

    @staticmethod
    def _emitted_ids() -> set[str]:
        model, _fm, instance = _probe_model()
        result = _solve_with(model, instance=instance)
        rows = check_backend(model, result, spec=REAL_SPEC, src_root=PKG_ROOT)
        return {r.item.split()[0] for r in rows}

    def test_declared_check_ids_match_emitted_check_ids(self):
        declared = {c["id"] for c in self.spec["checks"]}
        self.assertEqual(declared, self._emitted_ids())

    def test_every_check_is_fully_described(self):
        for c in self.spec["checks"]:
            with self.subTest(check=c["id"]):
                for key in ("name", "statement", "check", "on_violation", "why"):
                    self.assertTrue(c.get(key), f"{c['id']} 缺 {key}")
                self.assertIn(
                    c["on_violation"].split("；")[0].split("；")[0],
                    ("FAIL", "BLOCKED", "WARN", "PASS", "SKIP"),
                    f"{c['id']} 的 on_violation 不是合法判据状态",
                )

    def test_registry_active_is_declared_and_implemented(self):
        names = {e["name"] for e in self.spec["registry"]["entries"]}
        self.assertIn(self.spec["selection"]["active"], names)
        self.assertTrue(
            any(e["implemented"] and e["name"] == self.spec["selection"]["active"]
                for e in self.spec["registry"]["entries"])
        )

    def test_fallback_chain_entries_are_declared(self):
        names = {e["name"] for e in self.spec["registry"]["entries"]}
        for name in self.spec["selection"]["fallback_chain"]:
            with self.subTest(entry=name):
                self.assertIn(name, names)

    def test_every_normalized_status_has_class_and_judge(self):
        allowed = {"CONCLUSION", "NO_CONCLUSION", "NOT_RUN"}
        for n in self.spec["status"]["normalized"]:
            with self.subTest(status=n["id"]):
                self.assertIn(n["class"], allowed)
                self.assertIn(
                    n["judge"], ("PASS", "WARN", "FAIL", "BLOCKED", "SKIP")
                )
                self.assertTrue(n.get("means"))

    def test_every_registered_entry_declares_a_known_family(self):
        families = {f["backend_family"]
                    for f in self.spec["status"]["native_map"]}
        for e in self.spec["registry"]["entries"]:
            if e["implemented"] and e["kind"] != "NONE":
                with self.subTest(entry=e["name"]):
                    self.assertIn(e["status_family"], families)

    def test_conditional_aliases_reference_a_declared_rule(self):
        rules = set(self.spec["status"]["resolution_rules"])
        rules.discard("_why")
        for fam in self.spec["status"]["native_map"]:
            for alias in fam["aliases"]:
                if "conditional" in alias:
                    with self.subTest(alias=alias["native"]):
                        self.assertIn(alias["conditional"], rules)

    def test_audit_baseline_is_not_empty(self):
        audit = self.spec["audit"]
        for key in ("solver_packages", "allow_lazy_import_in",
                    "allow_solve_call_in", "comparison_branch_rule"):
            with self.subTest(key=key):
                self.assertTrue(audit.get(key), f"audit.{key} 为空 ⇒ 无基准可比")

    def test_adapter_identifiers_used_by_implemented_entries_exist(self):
        """制品声明 implemented=true 的条目，其 adapter 标识必须真有实现体。

        BB-01 在运行时判这条；此处把它钉在制品↔实现之间，改动任一侧都会红。
        """
        from bidpricing.solver.backend import ADAPTERS

        for e in self.spec["registry"]["entries"]:
            if e["implemented"]:
                with self.subTest(entry=e["name"]):
                    self.assertIn(e["adapter"], ADAPTERS)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
