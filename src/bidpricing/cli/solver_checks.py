"""求解链检查命令（自 bidpricing/cli.py 逐字拆出）。

formulate/phase1/constraint/precheck/settlement/diagnose/ref/milp/
backend/derive/verify/compile/contract 各 check 与 judgment-matrix。
"""
from __future__ import annotations

import json
import sys
from ..contracts.consistency import check_contract_consistency
from ..paths import GATE0_REGISTRY, PROJECT_SELECTION, config_dir, repo_root
from ..states import Status, aggregate
from typing import Any  # 补：cmd_settlement_check 注解 dict[str, Any]
from .common import _load_phase1_instance, _print_backend, _print_compiled, _print_derived, _print_exactness, _print_formulation, _print_milp, _print_phase1, _print_reference, _print_verification, _resolve_floor_by_id, _resolve_z_ref, build_derived_for_cli


def cmd_formulate_check(args) -> int:
    """T04-02A LP 形式化判定 —— 「变量/目标/约束映射是否完整」。

    与 ``phase1-check`` 的分工：那个判**求解论域**（阈值分割解在这实例上是否
    最优）；本命令判**模型表述**——C1–C13 是否各有明确形式、变量集合是否与
    可竞争性分类闭合、目标线性性是否成立、以及制品与实现是否互相锁死。

    默认跑两个变体：``active_soft_constraints = ()``（LP）与 ``("C7",)``
    （MILP）——F-09 的判据要求「MILP 切换条件唯一」，只跑一侧等于没检。
    """
    import dataclasses
    from pathlib import Path

    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..solver.formulation import (
        build_formulation,
        check_formulation,
        load_formulation_spec,
        probe_instance,
    )

    cfg = config_dir()
    spec = load_formulation_spec(cfg)
    schema = json.loads((cfg / "constraint_schema.json").read_text(encoding="utf-8"))
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    card = load_pricing_card(cfg)
    resolved = resolve_parameters(card)
    eps_abs = float(prof["eps_abs"]["value"])
    eps_price = float(prof["eps_price"]["value"])
    resolution = float(prof["rounding"]["resolution"])

    variants: list[tuple[str, object]] = []
    if args.instance:
        base, _doc, _path = _load_phase1_instance(args)
        for tag, act in (("LP", ()), ("MILP", ("C7",))):
            variants.append(
                (tag, dataclasses.replace(base, active_soft_constraints=tuple(act)))
            )
    else:
        variants = [
            ("LP", probe_instance()),
            ("MILP", probe_instance(active=("C7",))),
        ]

    payload: list[dict] = []
    worst = 0
    for tag, instance in variants:
        fm = build_formulation(
            instance, resolved,
            eps_abs=eps_abs, eps_rel_price=eps_price, resolution=resolution,
            theta=getattr(instance.params, "theta", None),
        )
        rows = check_formulation(
            spec, fm,
            instance=instance, resolved=resolved,
            constraint_schema=schema, precision_profile=prof,
            eps_rel_price=eps_price, eps_abs=eps_abs,
        )
        payload.append({
            "variant": tag,
            "formulation": fm.to_dict(),
            "checks": [r.to_dict() for r in rows],
        })
        for r in rows:
            if r.blocks_progress:
                worst = 1
        if not args.json:
            _print_formulation(fm, rows, f"{'探针实例' if not args.instance else args.instance} · {tag}")

    if args.json:
        print(json.dumps(
            {"spec_id": spec.get("spec_id"), "variants": payload},
            ensure_ascii=False, indent=2, default=str,
        ))
        return worst

    total = sum(len(v["checks"]) for v in payload)
    npass = sum(1 for v in payload for c in v["checks"] if c["status"] == "PASS")
    nskip = sum(1 for v in payload for c in v["checks"] if c["status"] == "SKIP")
    print(f"  汇总：{npass} PASS / {nskip} SKIP / {total - npass - nskip} 待处理"
          f"（共 {total} 条，跨 {len(payload)} 个变体）")
    return worst


def cmd_phase1_check(args) -> int:
    """T04-00 Phase 1 精确性条件判定 —— 「阈值分割解在本实例上是不是最优」。

    与 ``gate-check`` / ``contract-check`` 的分工：那两个判「制品是否就绪、
    彼此是否自洽」；本命令判**求解论域**——Phase 1 的「排序 + 二分 + 贪心定容」
    解析解只在 EC-1..EC-7 全通过时才与 P_A 最优解一致。条件不满足时两条路径
    不一致是**正确行为**，把它们一并判成 bug 会把对的实现改坏
    （impl_plan_v321 §4.1 的实验名由此从「数学等价性实验」改为
    「解析候选解一致性实验」）。

    ``--case`` 只跑指定实例；无参数时跑制品里的全部反例与正例，
    并把制品的 ``expected`` 与实际判定逐条比对——这是**制品与实现的双向锁定**。
    """
    from pathlib import Path

    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..solver.cases import load_exactness_spec, run_cases
    from ..solver.exactness import condition_status_line, overall_line
    from ..solver.exactness import check_exactness

    cfg = config_dir()
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    eps_abs = float(prof["eps_abs"]["value"])
    eps_price = float(prof["eps_price"]["value"])
    card = load_pricing_card(cfg)
    resolved = resolve_parameters(card)

    if args.instance:
        instance, _doc, inst_path = _load_phase1_instance(args)
        verdict = check_exactness(
            instance, resolved, eps_abs=eps_abs, eps_rel_price=eps_price
        )
        if args.json:
            print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
        else:
            _print_exactness(verdict, str(inst_path))
        return 0 if verdict.exact else 1

    spec = load_exactness_spec(cfg)
    results = run_cases(
        spec, resolved, eps_abs=eps_abs, eps_rel_price=eps_price, only=args.case
    )
    if not results:
        print(f"■ 没有匹配 --case {args.case!r} 的实例"
              f"（可用：CE-01…CE-09 / PE-01 / all）")
        return 1

    if args.json:
        print(json.dumps(
            {
                "spec_id": spec.get("spec_id"),
                "eps_abs": eps_abs,
                "eps_price": eps_price,
                "cases": [r.to_dict() for r in results],
            },
            ensure_ascii=False, indent=2, default=str,
        ))
        return 0 if all(r.ok for r in results) else 1

    print("=" * 78)
    print(f"Phase 1 精确性条件 · 反例集与正例集复算（T04-00）｜ {spec.get('spec_id')}")
    print("=" * 78)
    print("  判据：制品 phase1_exactness_spec.json 的 expected / witness.assertions")
    print("        必须与实现逐条一致——任何不一致都是「制品与实现两处说法」")
    print()
    for r in results:
        mark = "✓" if r.ok else "✗"
        print(f" {mark} [{r.case_id}] {r.title}")
        print(f"      {overall_line(r.verdict)}")
        if r.condition_mismatches:
            for m in r.condition_mismatches:
                print(f"      ✗ 条件层不一致：{m}")
        mismatch_note = condition_status_line(r.verdict)
        if mismatch_note:
            print(f"      {mismatch_note}")
        if r.witness:
            print(f"      见证层：{'通过' if r.witness.ok else '**不一致**'}"
                  f"　{r.witness.detail}")
            for f in r.witness.failures():
                print(f"      ✗ 见证层不一致：{f}")
        print()
    bad = [r for r in results if not r.ok]
    print("-" * 78)
    print(f" 共 {len(results)} 个实例：通过 {len(results) - len(bad)}、不一致 {len(bad)}")
    print(" 结论：制品与实现一致。" if not bad
          else " 结论：制品与实现不一致——先查判据是否写成了恒真式，"
               "再查实现是否漏改。")
    return 0 if not bad else 1


def cmd_phase1_solve(args) -> int:
    """T04-01 Phase 1 解析解 —— 排序 + 二分 + 贪心定容。

    与 ``phase1-check`` 的分工：那个判**求解论域**（阈值分割解在这实例上是不是
    最优，T04-00 的 EC 判据）；本命令在**该论域之内**把解算出来，输出
    阈值 λ 与层归属（顶格 / 内点 / 触底）。二者的顺序是固定的：
    **论域不过关 ⇒ 本命令拒绝给解**（越界给解比不给更危险，见
    ``phase1_solver_spec.applicability_guard``）。

    定位：输出是 **candidate / 上界**，不承担最终解职责（T04-05 才验收）；
    与 Phase 2（LP/MILP）构成 T04-04 对拍的两方。

    目标值一律由 ``check_solution``（独立裁判）给出——本层**不自报 Z**。
    """

    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..solver.phase1 import (
        STATUS_PASS,
        load_phase1_spec,
        phase1_probe_instance,
        phase1_report,
        phase1_simple_probe_instance,
    )
    from ..solver.verifier import load_verifier_spec, resolve_tolerances

    cfg = config_dir()
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    eps_abs = float(prof["eps_abs"]["value"])
    eps_price = float(prof["eps_price"]["value"])
    resolution = float(prof["rounding"]["resolution"])
    resolved = resolve_parameters(load_pricing_card(cfg))
    spec = load_phase1_spec(cfg)
    vspec = load_verifier_spec(cfg)

    if args.instance:
        instance, _doc, path = _load_phase1_instance(args)
        title = str(path)
    else:
        instance = (
            phase1_simple_probe_instance()
            if args.probe == "simple" else phase1_probe_instance()
        )
        title = f"内置探针（{args.probe}）"

    floor_by_id, floor_source = _resolve_floor_by_id(
        cfg, instance, resolved, getattr(args, "floor_json", None)
    )
    # ★ 这些是**旁注**，不是机器可读输出的一部分：--json 时必须走 stderr，
    #   否则 stdout 前面多一行人话，整份 JSON 无法解析。
    _note = sys.stderr if args.json else sys.stdout
    print(f"■ floor_i 来源：{floor_source}", file=_note)

    tolerances, tol_problems = resolve_tolerances(
        prof, vspec, P_ref=instance.P_star
    )
    if "eps_price" in tol_problems:
        print(f"■ 盒式容差不可比：{tol_problems['eps_price']}", file=_note)

    report = phase1_report(
        instance, resolved,
        eps_abs=eps_abs, eps_rel_price=eps_price, resolution=resolution,
        floor_by_id=floor_by_id, tolerances=tolerances, spec=spec,
    )

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.verdict() == STATUS_PASS else 1

    _print_phase1(report, title)
    return 0 if report.verdict() == STATUS_PASS else 1


def cmd_judgment_matrix(args) -> int:
    """T03-05 判定层测试矩阵 —— 边界格枚举 + 变异体存活审计。

    与相邻命令的分工：``constraint-check`` 判「给定候选 p，解合不合规」；
    本命令判「**那套判据判得对不对**」——它不新增判据，只枚举判据的边界格，
    再把 25 条变异体（坏实现）逐条喂进同一套用例。

    **存活即盲区**：任何一条变异体没被探针杀掉 ⇒ 结论 FAIL，不得以
    「大部分被杀」通过。这不是覆盖率数字游戏，而是「判据能否被错误值否定」
    的可执行形式（规则⑧）。
    """
    from ..validation.judgment_matrix import run_matrix

    run = run_matrix(with_mutants=not args.no_mutants,
                     with_precedence=not args.no_precedence,
                     with_switch=not args.no_switch)

    if args.json:
        print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2))
        return 0 if run.verdict in ("PASS", "WARN") else 1

    cov = run.coverage
    print("=== T03-05 判定层测试矩阵 ===")
    print(f"用例格：{cov.total_cells} 格（覆盖 {cov.covered}／声明不适用 "
          f"{cov.declared_not_applicable}）｜探针 {cov.probe_count} 个")
    print(f"覆盖审计：{cov.status}"
          + (f"  未声明空格：{list(cov.undeclared_gaps)}"
             if cov.undeclared_gaps else ""))

    print(f"\n-- 边界格（{len(run.cases)}）--")
    if args.cases:
        for c in run.cases:
            tag = "N/A" if not c.applicable else ("OK" if c.matched else "**失配**")
            print(f"  {c.case_id:<24}{tag}")
    else:
        bad = [c for c in run.failed_cases]
        print("  全部通过" if not bad else "")
        for c in bad:
            print(f"  {c.case_id}：")
            for r in c.results:
                if not r.matched:
                    print(f"    - {r.probe_id}：期望 {r.expected}，实测 {r.actual}")
                    print(f"      {r.detail}")

    bad_agg = [a for a in run.aggregates if not a.matched]
    print(f"\n-- 聚合不变量探针（{len(run.aggregates)}）--")
    print("  全部通过" if not bad_agg else "")
    for a in bad_agg:
        print(f"  {a.probe_id}：期望 {a.expected}，实测 {a.actual}｜{a.detail}")

    if run.mutants:
        print(f"\n-- 变异体存活审计（{len(run.mutants)}）--")
        print(f"{'变异体':<9}{'结论':<10}{'被谁杀掉'}")
        for m in run.mutants:
            who = "、".join(m.killed_by[:3]) + (
                f" 等 {len(m.killed_by)} 处" if len(m.killed_by) > 3 else "")
            print(f"{m.mutant_id:<9}{'已否定' if m.killed else '**存活**':<10}"
                  f"{who or m.note}")
        if run.surviving_mutants:
            print("■ 存活变异体 ⇒ 判据盲区："
                  f"{list(run.surviving_mutants)}")
    else:
        print("\n-- 变异体审计：已跳过（--no-mutants）——结论不得据此通过 --")

    if run.rule_precedence is not None:
        print(f"\n-- 规则优先级（{run.rule_precedence.status}）--")
        for c in run.rule_precedence.checks:
            print(f"  [{'通过' if c.passed else '不通过'}] {c.check_id}")
            print(f"        {c.detail}")

    if run.ruleset_switch is not None:
        print(f"\n-- 规则集切换（{run.ruleset_switch.status}）--")
        for ly in run.ruleset_switch.layers:
            print(f"  [{ly.status}] {ly.layer_id}")
            print(f"        {ly.detail}")

    print(f"\n整体结论：{run.verdict}")
    return 0 if run.verdict in ("PASS", "WARN") else 1


def cmd_constraint_check(args) -> int:
    """T03-04 约束判定器 —— 对候选报价向量逐条判定 C1–C13。

    与相邻命令的分工：``verify-solution`` 判「解对不对」（可行性/层归属/
    目标复算）；本命令判「解合不合规」（每约束一个六元组，Gate 2 判定层）。
    输入默认是 Phase 1 解析解（与 phase1-solve 同一来源），也可用
    ``--instance`` 提供任意候选 p（JSON：instance + p/z/Z/限值）。
    """

    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..solver.constraint_judge import (
        JudgeInputs,
        judge_constraints,
        load_constraint_spec,
    )
    from ..solver.phase1 import (
        phase1_probe_instance,
        phase1_simple_probe_instance,
        solve_phase1,
    )

    cfg = config_dir()
    resolved = resolve_parameters(load_pricing_card(cfg))
    spec = load_constraint_spec(cfg)

    z_by_id = None
    Z = None
    extra = {}
    if args.instance:
        instance, doc, path = _load_phase1_instance(args, wrapped=True)
        if "instance" in doc:
            z_by_id = doc.get("z")
            Z = doc.get("Z")
            for k in ("theta", "N_max", "d_max", "Z_min", "pi_target",
                      "R_min", "sigma_max", "kappa_max"):
                if doc.get(k) is not None:
                    extra[k] = doc[k]
            p_by_id = {str(k): float(v) for k, v in (doc.get("p") or {}).items()}
            explicit_floor = doc.get("floor")
            title = str(path)
        else:
            # 整个文档就是实例 ⇒ 对其跑 Phase 1 解析解作为候选 p
            sol = solve_phase1(instance, resolved)
            p_by_id = dict(sol.p_by_id)
            explicit_floor = None
            title = f"{path}（p 取 Phase 1 解析解）"
        front_rho = doc.get("front_rho") if "instance" in doc else None
    else:
        instance = (
            phase1_simple_probe_instance()
            if args.probe == "simple" else phase1_probe_instance()
        )
        sol = solve_phase1(instance, resolved)
        p_by_id = dict(sol.p_by_id)
        z_by_id = None
        Z = None
        front_rho = None
        explicit_floor = None
        title = f"内置探针（{args.probe}）· Phase 1 解析解"

    floor_by_id, floor_source = _resolve_floor_by_id(
        cfg, instance, resolved, args.floor_json or (
            {str(k): float(v) for k, v in explicit_floor.items()}
            if explicit_floor else None)
    )
    note = sys.stderr if args.json else sys.stdout
    print(f"■ floor_i 来源：{floor_source}", file=note)
    if not p_by_id:
        print("■ 候选 p 为空：C1–C5 将按缺数据判 BLOCKED", file=note)

    report = judge_constraints(
        JudgeInputs(
            instance=instance,
            p_by_id=p_by_id,
            z_by_id=z_by_id,
            Z=Z,
            floor_by_id=floor_by_id,
            front_rho=front_rho,
            **extra,
        ),
        spec=spec,
    )

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"=== T03-04 约束判定 · {title}")
        print(f"{'约束':<6}{'状态':<9}{'严重度':<7}{'actual':>16}"
              f"{'limit':>16}{'slack':>16}")
        for v in report.verdicts:
            def _fmt(x):
                return "-" if x is None else (
                    f"{x:.4g}" if isinstance(x, float) else str(x))
            print(f"{v.constraint_id:<6}{v.status:<9}{v.severity:<7}"
                  f"{_fmt(v.actual):>16}{_fmt(v.limit):>16}{_fmt(v.slack):>16}")
        print(f"\n整体结论（P0）：{report.verdict()}；含 P1：{report.verdict_all()}")
        for v in report.verdicts:
            if v.status in ("FAIL", "BLOCKED"):
                print(f"  ■ {v.constraint_id}: {v.reason}")
    return 0 if report.verdict() in ("PASS", "WARN") else 1


def cmd_precheck(args) -> int:
    """T03-03 Phase 0 预检与可行性证书 —— 结构化证书 + PC-01..PC-08 判定。

    §6.2 核心原则在这里落地：P* 越界必须判 INFEASIBLE 且**不进求解器**，
    而不是让优化器用不平衡报价「硬找解」。探针模式的税率/π/α 是演示声明值，
    真实项目须走 Phase 0 输入门声明（--instance JSON 传入）。
    """

    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..solver.phase1 import (
        phase1_probe_instance,
        phase1_simple_probe_instance,
    )
    from ..solver.precheck import (
        PrecheckInputs,
        load_precheck_spec,
        load_role_domain,
        precheck_report,
    )

    cfg = config_dir()
    resolved = resolve_parameters(load_pricing_card(cfg))
    spec = load_precheck_spec(cfg)
    role_domain = load_role_domain(cfg)

    if args.instance:
        instance, doc, path = _load_phase1_instance(args, wrapped=True)
        decl = {k: doc.get(k) for k in (
            "rule_set_id", "contract_type", "pi_target", "alpha_cap",
            "fixed_pretax", "vat_rate", "surtax_rate",
            "supplied_material", "env_tax") if k in doc}
        title = str(path)
    else:
        instance = (
            phase1_simple_probe_instance()
            if args.probe == "simple" else phase1_probe_instance()
        )
        # 演示声明：真实项目由 Phase 0 输入门给出，缺失该 BLOCKED 的照样 BLOCKED
        decl = {
            "rule_set_id": "GB50500-2024",
            "contract_type": "UNIT_PRICE",
            "pi_target": 0.05,
            "alpha_cap": 0.10,
            "fixed_pretax": 0.0,
            "vat_rate": 0.09,
            "surtax_rate": 0.03,
        }
        title = f"内置探针（{args.probe}）· 演示声明值"

    inputs = PrecheckInputs(
        instance=instance,
        derived=build_derived_for_cli(cfg, instance, resolved),
        role_domain=role_domain,
        **decl,
    )
    rep = precheck_report(inputs, spec=spec)

    if args.json:
        cert = rep.certificate
        print(json.dumps({
            "certificate": {
                "p_min": cert.p_min,
                "p_max": cert.p_max,
                "p_max_capped_only": cert.p_max_capped_only,
                "p_star_var": cert.p_star_var,
                "p_star_eff": cert.p_star_eff,
                "eff_terms": cert.eff_terms,
                "delta_p": cert.delta_p,
                "cost_line_settlement": cert.cost_line_settlement,
                "missing": list(cert.missing),
                "notes": list(cert.notes),
            },
            "feasibility": rep.feasibility,
            "overall": rep.overall,
            "verdicts": [
                {"check_id": v.check_id, "status": v.status,
                 "actual": v.actual, "limit": v.limit,
                 "severity": v.severity, "detail": v.detail}
                for v in rep.verdicts
            ],
        }, ensure_ascii=False, indent=2))
    else:
        c = rep.certificate

        def _m(x):
            return "—（不落值）" if x is None else f"{x:,.2f}"

        print(f"=== T03-03 Phase 0 预检 · {title}")
        print(f"P_min = {_m(c.p_min)}    P_max = {_m(c.p_max)}"
              + ("（cap 空，不落值≠0）" if c.p_max_capped_only else ""))
        print(f"P*_var = {_m(c.p_star_var)}（compute_P_competitive 唯一提供者）")
        print(f"P*_eff = {_m(c.p_star_eff)}  terms = "
              + ", ".join(f"{k}={_m(v)}" for k, v in c.eff_terms.items()))
        print(f"ΔP = {_m(c.delta_p)}")
        print(f"成本线·结算量口径 = {_m(c.cost_line_settlement)}"
              "（信息量，不进 P*_eff，ADR-0030 D9）")
        for n in c.notes:
            print(f"  ▲ {n}")
        print(f"\n{'判据':<8}{'状态':<9}{'severity':<9}说明")
        for v in rep.verdicts:
            print(f"{v.check_id:<8}{v.status:<9}{v.severity:<9}{v.detail[:66]}")
        print(f"\n可行性：{rep.feasibility}    整体结论：{rep.overall}")
        if rep.feasibility == "FAIL":
            print("■ INFEASIBLE：不进求解器（§6.2 核心原则）。"
                  "处置见 §6.3 放弃投标判据表。")
    return 0 if rep.feasibility in ("PASS", "WARN") else 1


def cmd_settlement_check(args) -> int:
    """T03-01 结算规则引擎 —— 三段调价 / 边界归属 / 规则集分发 / 合同覆盖。

    ``--judge`` 跑 SR-01..SR-09 判据套件（在制品固定的探针网格上）；
    不带 ``--judge`` 则对给定 (Q0, Q1, P0, rule_set, overrides) 出一次结算结论。
    """
    from ..settlement import (
        ContractContext,
        SettlementRule,
        judge_settlement,
        load_settlement_spec,
    )

    spec = load_settlement_spec(config_dir())
    overrides: dict[str, Any] = {}
    for item in getattr(args, "override", None) or ():
        if "=" not in item:
            print(f"■ --override 需形如 key=value，收到 {item!r}")
            return 1
        k, v = item.split("=", 1)
        try:
            overrides[k.strip()] = float(v)
        except ValueError:
            overrides[k.strip()] = v.strip()

    rule_id = str(getattr(args, "rule_set", None) or "GB/T50500-2024")

    if args.judge:
        rep = judge_settlement(SettlementRule(spec=spec))
        if args.json:
            print(json.dumps({
                "spec_id": spec.get("spec_id"),
                "overall": rep.verdict(),
                "overall_all": rep.verdict_all(),
                "verdicts": [
                    {"judge_id": v.judge_id, "status": v.status,
                     "severity": v.severity, "detail": v.detail,
                     "actual": v.actual, "limit": v.limit}
                    for v in rep.verdicts
                ],
            }, ensure_ascii=False, indent=2))
        else:
            print("=== T03-01 结算规则引擎判据套件（固定探针网格）")
            print(f"{'判据':<8}{'状态':<9}{'severity':<9}说明")
            for v in rep.verdicts:
                print(f"{v.judge_id:<8}{v.status:<9}{v.severity:<9}{v.detail[:70]}")
            print(f"\n整体结论（P0）：{rep.verdict()}   含 P1：{rep.verdict_all()}")
        return 0 if rep.verdict() == "PASS" else 1

    # `x or 默认` 会把合法的 0（--q0 0 / --p0 0：零值本身就是待判定的
    # 边界输入）当成「没给参数」吞掉，改为显式判 None。
    _grid = spec["probe_grid"]
    _q0 = getattr(args, "q0", None)
    _q1 = getattr(args, "q1", None)
    _p0 = getattr(args, "p0", None)
    q0 = float(_q0) if _q0 is not None else float(_grid["q0"])
    q1 = float(_q1) if _q1 is not None else float(_grid["q0"]) * 1.3
    p0 = float(_p0) if _p0 is not None else float(_grid["p0"])
    ctx = ContractContext(
        rule_set_id=rule_id,
        overrides=overrides,
        source_label=str(getattr(args, "override_layer", None) or "contract"),
        adjustment_scope=getattr(args, "scope", None),
        declared_by=getattr(args, "declared_by", None),
    )
    out = SettlementRule(spec=spec).evaluate(q0, q1, p0, ctx)

    if args.json:
        print(json.dumps(out.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"=== T03-01 结算规则引擎 · rule_set={rule_id}")
        print(f"  入口：Q0={q0:,.4f}  Q1={q1:,.4f}  P0={p0:,.4f}"
              f"  覆盖={overrides or '（无）'}  层={ctx.source_label}")
        print(f"  结论：{out.status}"
              + (f" ｜ 分支 {out.rule_branch}（r={out.r:.6f}）"
                 if out.rule_branch else ""))
        if out.status == "PASS":
            print(f"  settlement_amount   = {out.settlement_amount:,.2f}")
            print(f"  effective_price     = {out.effective_price:,.6f}"
                  "（= 金额/Q1，加权平均）")
            print(f"  adjusted_unit_price = {out.adjusted_unit_price:,.6f}"
                  "（= P1 本身）")
            print(f"  p1_source           = {out.p1_source}")
            print("  ▲ effective_price 与 P1 在 SEGMENT 增量段**不相等**："
                  "阈值内部分仍按 P0 结算")
            for line in out.basis:
                print(f"    · {line}")
        else:
            print(f"  阻断原因：{out.blocked_reason}")
    return 0 if out.status == "PASS" else 1


def cmd_diagnose(args) -> int:
    """T03-06 不可行诊断 —— 结构冲突 + 删除过滤器 + §6.3 建议动作。

    输出四字段：constraint_id / blocking / conflicting_set / suggested_relaxation。
    三态纪律：INFEASIBLE（已证空域）≠ UNKNOWN（预言机不足）≠ BLOCKED（输入缺失）。
    """

    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..solver.diagnose import (
        chained_oracle,
        diagnose,
        load_diagnosis_spec,
        load_toggleable_ids,
        milp_oracle,
        phase1_oracle,
    )
    from ..solver.phase1 import (
        phase1_probe_instance,
        phase1_simple_probe_instance,
    )

    cfg = config_dir()
    resolved = resolve_parameters(load_pricing_card(cfg))
    spec = load_diagnosis_spec(cfg)
    toggleable = load_toggleable_ids(cfg)

    if args.instance:
        instance, doc, path = _load_phase1_instance(args, wrapped=True)
        floor_json = doc.get("floor")
        title = str(path)
    else:
        instance = (
            phase1_simple_probe_instance()
            if args.probe == "simple" else phase1_probe_instance()
        )
        floor_json = None
        title = f"内置探针（{args.probe}）"

    floor_by_id, floor_src = _resolve_floor_by_id(cfg, instance, resolved, floor_json)

    wanted = str(getattr(args, "oracle", "phase1") or "phase1")
    if wanted == "milp":
        orc = milp_oracle(resolved, floor_by_id=floor_by_id)
    elif wanted == "chain":
        orc = chained_oracle(
            phase1_oracle(resolved, floor_by_id=floor_by_id),
            milp_oracle(resolved, floor_by_id=floor_by_id),
        )
    else:
        orc = None  # diagnose 默认 = phase1 内置

    rep = diagnose(
        instance, resolved,
        oracle=orc,
        floor_by_id=floor_by_id, spec=spec, toggleable=toggleable,
    )

    print(f"== T03-06 不可行诊断 | {title} ｜ 预言机：{wanted}")
    print(f"   floor 来源：{floor_src}")
    print(f"   基线：{rep.baseline}（FEASIBLE / INFEASIBLE=已证空域 / UNKNOWN=预言机不足）")
    if rep.structural_conflicts:
        print("   -- 结构冲突（Pass A，参数级）--")
        for c in rep.structural_conflicts:
            print(f"   [{c.knob_id}] {c.detail}")
            print(f"      建议：{c.suggested_relaxation}")
    if rep.min_conflict_sets:
        print("   -- 冲突集（Pass B，删除过滤器近似，非完整 IIS）--")
        for cs in rep.min_conflict_sets:
            print(f"   {cs}")
    elif rep.baseline != "FEASIBLE":
        print("   -- 无 ≤2 阶冲突集（截断搜索边界，不是无冲突证明）--")
    if rep.entries:
        print("   -- 逐条诊断 --")
        for e in rep.entries:
            mark = "■" if e.blocking else "□"
            print(f"   {mark} {e.constraint_id:5} set={e.conflicting_set}")
            if e.suggested_relaxation:
                print(f"      建议：{e.suggested_relaxation}")
    for jid, status, detail in rep.verdicts:
        print(f"   {jid} {status:8} {detail}")
    print(f"== 诊断结论（判据聚合）：{rep.overall}")

    if args.json:
        print(json.dumps({
            "baseline": rep.baseline,
            "structural_conflicts": [
                {"knob_id": c.knob_id, "constraint_id": c.constraint_id,
                 "detail": c.detail, "suggested_relaxation": c.suggested_relaxation,
                 "amount": c.amount}
                for c in rep.structural_conflicts
            ],
            "min_conflict_sets": [list(c) for c in rep.min_conflict_sets],
            "entries": [
                {"constraint_id": e.constraint_id, "blocking": e.blocking,
                 "conflicting_set": list(e.conflicting_set) if e.conflicting_set else None,
                 "suggested_relaxation": e.suggested_relaxation}
                for e in rep.entries
            ],
            "overall": rep.overall,
        }, ensure_ascii=False, indent=1))
    return 0


def cmd_ref_check(args) -> int:
    """T04-08 独立参考实现 —— 第二条计算路径的重算与三层隔离证明。

    与 ``verify-solution`` 的 SV-13 是同一件事的两面：本命令把参考层**摊开**
    （逐项 R_i / 分支 / 成本 / 残差 + 三层隔离状态）供人工核对；
    SV-13 只取其中的 ``Z_ref`` 一个数值做跨来源对照。

    ★ 隔离③（ISO-3：作者分离）未签署时本命令返回 1 且**不宣称验收通过**——
    机械判据无法证明「作者不是同一人」，伪造 PASS 即把共因错误重新引进来。
    """
    from pathlib import Path as _P

    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..refimpl import isolation as _I
    from ..refimpl import reference as _R
    from ..solver.instance import Phase1Instance, check_solution
    from ..solver.phase1 import (
        phase1_probe_instance,
        phase1_simple_probe_instance,
        solve_phase1,
    )
    from ..solver.verifier import load_verifier_spec, resolve_tolerances

    cfg = config_dir()
    resolved = resolve_parameters(load_pricing_card(cfg))
    spec = _R.load_reference_spec(cfg)
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    vspec = load_verifier_spec(cfg)

    if args.instance:
        instance, _doc, path = _load_phase1_instance(args)
        title = str(path)
    else:
        instance = (
            phase1_simple_probe_instance()
            if args.probe == "simple" else phase1_probe_instance()
        )
        title = f"内置探针（{args.probe}）"

    sol = solve_phase1(instance, resolved)
    p_by_id = dict(sol.p_by_id)
    if args.p_json:
        pj = _P(args.p_json)
        if not pj.exists():
            print(f"■ 报价向量文件不存在：{pj}")
            return 1
        p_by_id = {str(k): float(v)
                   for k, v in json.loads(pj.read_text(encoding="utf-8")).items()}

    snap = _R.snapshot(instance, resolved)
    iso = _I.collect_isolation(
        source_paths=[
            _P(__file__).resolve().parents[1] / "refimpl" / "reference.py",
            _P(__file__).resolve().parents[1] / "refimpl" / "isolation.py",
        ],
        snapshot_obj=snap,
        docs_dir=repo_root() / "docs",  # 仓库根锚定（原 parents[1] 是 src 布局前陈旧锚点）
        spec=spec,
    )
    tolerances, _ = resolve_tolerances(
        prof, vspec, P_ref=instance.P_star if instance.P_star else instance.B
    )
    # 对照侧（Z_solver）：显式给就用给的；否则用**生产侧** check_solution 的 Z。
    # ★ 这正是本命令要干的事——拿生产路径与参考路径对拍；若对照侧也由参考层
    #   自算，就成了同源相减恒为 0 的恒真式（ADR-0015 / CC-07 同族）。
    z_solver = (
        float(args.z_solver) if args.z_solver is not None
        else check_solution(
            instance, p_by_id, resolved,
            eps_total=tolerances.get("eps_total"),
        ).Z
    )
    report = _R.reference_report(
        instance, p_by_id, resolved=resolved, spec=spec,
        tolerances=tolerances, z_solver=z_solver, isolation=iso,
    )

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.verdict() == _R.STATUS_PASS else 1

    _print_reference(report, title, iso, z_solver)
    return 0 if report.verdict() == _R.STATUS_PASS else 1


def cmd_milp_check(args) -> int:
    """T04-07 MILP 独立验收协议 —— 这次求解够不够格被当作「已证最优」。

    与 ``verify-solution`` 的分工：那个判**解对不对**（可行性 / 层归属 /
    目标复算）；本命令判**最优性有没有被证明**。两者的对象不同：
    一个解可以完全正确却仍未证最优（例如求解器被时限中断、或后端不给对偶界）。

    ★ 三条纪律：
      ① 求解器自报 ``Optimal`` **不是**验收结论，最优性须由 bound + gap +
         整数性三项可核的量证明；
      ② **never_upgrade**——结论只能比归一状态更宽松；
      ③ 禁用 KKT 证 MILP 最优性（可行域非凸，KKT 既非必要也非充分）。
    """
    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..solver.backend import load_backend_spec, solve_compiled
    from ..solver.compiler import compile_model
    from ..solver.formulation import build_formulation, probe_instance
    from ..solver.milp_acceptance import (
        STATUS_PASS,
        acceptance_report,
        facts_from_result,
        load_milp_spec,
    )

    cfg = config_dir()
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    eps_abs = float(prof["eps_abs"]["value"])
    eps_price = float(prof["eps_price"]["value"])
    resolved = resolve_parameters(load_pricing_card(cfg))
    spec = load_milp_spec(cfg)
    bspec = load_backend_spec(cfg)
    time_limit = float(getattr(args, "time_limit", 30.0) or 30.0)

    wanted = str(getattr(args, "form", "both") or "both").upper()
    candidates = {
        "LP": lambda: probe_instance(),
        "MILP": lambda: probe_instance(active=("C7",)),
    }
    forms = [f for f in ("LP", "MILP") if wanted in (f, "BOTH")]

    payload = []
    worst = 0
    for tag in forms:
        instance = candidates[tag]()
        formulation = build_formulation(
            instance, resolved, eps_abs=eps_abs, eps_rel_price=eps_price
        )
        model = compile_model(formulation, source=f"cli:milp-check:{tag}")
        result = solve_compiled(
            model, spec=bspec, instance=instance, resolved=resolved,
        )
        facts = facts_from_result(result, model, time_limit=time_limit)
        report = acceptance_report(facts, spec=spec)
        if args.json:
            payload.append({"form": tag, **report.to_dict()})
        else:
            _print_milp(tag, model, result, report)
        if report.verdict() != STATUS_PASS and report.verdict() != "SKIP":
            worst = max(worst, 0)
        if report.verdict() == "FAIL":
            worst = 1

    if args.json:
        print(json.dumps({"spec_id": spec.get("spec_id"), "variants": payload},
                         ensure_ascii=False, indent=2))
    return worst


def cmd_backend_check(args) -> int:
    """T04-02C 求解后端适配判定 —— 「换后端只改配置」是不是真的。

    与前三条命令的分工：``phase1-check`` 判**求解论域**；``formulate-check`` 判
    **模型表述**；``compile-check`` 判**翻译保真**；本命令判**执行链路**——
    模型交给谁解、解完的状态有没有被混域、求解器报的最优值与独立复算对不对得上。

    零依赖环境下 BB-07/BB-08/BB-09 与 CC-09 都会判 SKIP（= 本轮没检查），
    这是真话而不是失败：本机确实没有后端可跑。
    """
    import dataclasses
    from pathlib import Path as _P

    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..solver.backend import (
        check_backend,
        load_backend_spec,
        solve_compiled,
    )
    from ..solver.compiler import (
        check_compiled,
        compile_model,
        load_compiler_spec,
        pulp_available,
    )
    from ..solver.formulation import (
        PROBE_SOLVER_INPUTS,
        build_formulation,
        load_formulation_spec,
        probe_instance,
    )
    from ..solver.verifier import load_verifier_spec, resolve_tolerances

    cfg = config_dir()
    spec = load_backend_spec(cfg)
    compiler_spec = load_compiler_spec(cfg)
    fspec = load_formulation_spec(cfg)
    verifier_spec = load_verifier_spec(cfg)
    schema = json.loads((cfg / "constraint_schema.json").read_text(encoding="utf-8"))
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    card = load_pricing_card(cfg)
    resolved = resolve_parameters(card)
    eps_abs = float(prof["eps_abs"]["value"])
    eps_price = float(prof["eps_price"]["value"])
    resolution = float(prof["rounding"]["resolution"])

    allow = (compiler_spec.get("literal_allowlist") or {}).get("allowed_in_expressions")
    # 本文件即 src/bidpricing/cli.py ⇒ parents[1] 既是包根也含 solver/compiler.py
    pkg_root = _P(__file__).resolve().parents[1]
    compiler_path = pkg_root / "solver" / "compiler.py"
    if not compiler_path.exists():
        print(f"■ 编译器源码不在预期位置：{compiler_path}")
        return 1
    compiler_source = compiler_path.read_text(encoding="utf-8")

    if args.instance:
        base, _doc, _path = _load_phase1_instance(args)
        variants: list[tuple[str, object]] = [
            (tag, dataclasses.replace(base, active_soft_constraints=tuple(act)))
            for tag, act in (("LP", ()), ("MILP", ("C7",)))
        ]
        solver_inputs: dict[str, object] = dict(PROBE_SOLVER_INPUTS)
    else:
        variants = [
            ("LP", probe_instance()),
            ("MILP", probe_instance(active=("C7",))),
        ]
        solver_inputs = dict(PROBE_SOLVER_INPUTS)

    payload: list[dict] = []
    worst = 0
    for tag, instance in variants:
        fm = build_formulation(
            instance, resolved,
            eps_abs=eps_abs, eps_rel_price=eps_price, resolution=resolution,
            theta=solver_inputs.get("theta"),
            n_max=solver_inputs.get("n_max"),
            d_max=solver_inputs.get("d_max"),
            r_min=solver_inputs.get("r_min"),
            z_min=solver_inputs.get("z_min"),
            pi_target=solver_inputs.get("pi_target"),
        )
        model = compile_model(
            fm,
            z_min=solver_inputs.get("z_min"),
            pi_target=solver_inputs.get("pi_target"),
            source=tag,
        )
        cc_rows = check_compiled(
            model, fm,
            instance=instance, resolved=resolved,
            constraint_schema=schema, formulation_spec=fspec,
            compiler_source=compiler_source,
            literal_allowlist=allow,
            eps_total=eps_abs,
        )
        result = solve_compiled(
            model, spec=spec,
            instance=instance, resolved=resolved,
            prefer=args.prefer,
            eps_total=eps_abs,
            tolerances=resolve_tolerances(
                prof, verifier_spec,
                P_ref=(instance.P_star if instance.P_star is not None else instance.B),
            )[0],
        )
        rows = check_backend(
            model, result,
            spec=spec, config_dir=cfg, src_root=pkg_root,
            instance=instance, resolved=resolved,
            formulation=fm, constraint_schema=schema,
            formulation_spec=fspec, cc09=cc_rows, prefer=args.prefer,
        )
        payload.append({
            "variant": tag,
            "solver_form": model.solver_form,
            "solve": result.to_dict(),
            "checks": [r.to_dict() for r in rows],
            "cc09": [r.to_dict() for r in cc_rows if "CC-09" in r.item],
        })
        for r in rows:
            if r.blocks_progress:
                worst = 1
        if not args.json:
            _print_backend(
                model, result, rows, cc_rows,
                f"{'探针实例' if not args.instance else args.instance} · {tag}",
            )

    if args.json:
        print(json.dumps(
            {"spec_id": spec.get("spec_id"), "variants": payload},
            ensure_ascii=False, indent=2, default=str,
        ))
        return worst

    total = sum(len(v["checks"]) for v in payload)
    npass = sum(1 for v in payload for c in v["checks"] if c["status"] == "PASS")
    nskip = sum(1 for v in payload for c in v["checks"] if c["status"] == "SKIP")
    print(f"  汇总：{npass} PASS / {nskip} SKIP / {total - npass - nskip} 待处理"
          f"（共 {total} 条，跨 {len(payload)} 个变体）")
    if nskip:
        print(f"  ⚠ {nskip} 条 SKIP 表示**本轮没检查**，不等于通过")
        if pulp_available():
            print("     （本机有 PuLP：涉后端的判据已实跑；其余 SKIP 属结构性"
                  "豁免，逐条理由见上）")
        else:
            print("     （本机无 PuLP ⇒ 求解链路与 CC-09 未验证；须在装有 PuLP 的"
                  "环境复跑，见 solver_backend_spec.environment）")
    return worst


def cmd_derive_check(args) -> int:
    """T03-02：算出 ``L_i / U_i / floor_i / r_eff_i`` 并逐条给出判据。

    ★ 本命令是 ``floor_i`` 的**唯一生产者**：``formulation.merged_lower`` 的
    ``floor_by_id`` 入参由此而来。此前该入参只能由调用方手工提供（占位），
    于是「地板」在编译侧与判定侧各有一个真相来源——两侧会各自自洽地错着。

    退出码：存在 FAIL/BLOCKED ⇒ 1。**在当前项目上默认就会返回 1**（μ 与
    ``unbalanced_clause`` 尚未落值）——这是**如实反映数据未定**，不是实现缺陷，
    因此本命令与 ``verify-solution`` 一样**不进常驻验证环**。
    """
    from pathlib import Path as _P

    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..derived import (
        DerivedError,
        compute_derived,
        inputs_from_project,
        load_derived_spec,
    )
    from ..solver.formulation import probe_instance

    cfg = config_dir()
    try:
        spec = load_derived_spec(cfg)
    except DerivedError as exc:
        print(f"■ {exc}")
        return 1
    card = load_pricing_card(cfg)
    resolved = resolve_parameters(card)

    if args.instance:
        inst, _doc, path = _load_phase1_instance(args)
        title = str(path)
    else:
        inst = probe_instance()
        title = "内置探针实例"

    pin = inputs_from_project(cfg)
    mu = args.mu if args.mu is not None else pin["mu"]
    loss = args.loss_acceptance or pin["loss_acceptance"]

    unbalanced = None
    if getattr(args, "unbalanced_json", None):
        p = _P(args.unbalanced_json)
        if not p.exists():
            print(f"■ 条款文件不存在：{p}")
            return 1
        unbalanced = json.loads(p.read_text(encoding="utf-8"))
    elif getattr(args, "no_unbalanced_clause", False):
        unbalanced = {"enabled": False}

    report = compute_derived(
        inst, resolved, mu=mu, loss_acceptance=loss,
        unbalanced=unbalanced, spec=spec,
    )

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_derived(report, title)

    return 0 if report.verdict() == "PASS" else 1


def cmd_verify_solution(args) -> int:
    """T04-02D：**独立复核**一个解（可行性 / 目标值 / 上下界 / 层归属）。

    与 ``backend-check`` 的分工：后者判「后端这条链路**走样**没有」（BB 判据），
    本命令判「这个解**本身**站得住吗」（SV 判据），并产出**逐行 + 逐项**的复核
    报告。二者不互相替代（见 solver_backend_spec 的 T04-02D 交接条目）。

    本命令**不**消费求解决论：它把 ``SolveResult`` 拆成原始量（变量赋值 +
    自报目标值）再交给复核层——这是独立性在接口层的落地。
    """
    from pathlib import Path as _P

    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..solver.backend import load_backend_spec, solve_compiled
    from ..solver.compiler import compile_model, load_compiler_spec
    from ..solver.formulation import (
        PROBE_SOLVER_INPUTS,
        build_formulation,
        load_formulation_spec,
        probe_instance,
    )
    from ..solver.verifier import (
        load_verifier_spec,
        resolve_tolerances,
        verify_solution,
    )

    cfg = config_dir()
    vspec = load_verifier_spec(cfg)
    bspec = load_backend_spec(cfg)
    fspec = load_formulation_spec(cfg)
    compiler_spec = load_compiler_spec(cfg)
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    card = load_pricing_card(cfg)
    resolved = resolve_parameters(card)
    eps_abs = float(prof["eps_abs"]["value"])
    eps_price = float(prof["eps_price"]["value"])
    resolution = float(prof["rounding"]["resolution"])

    if args.instance:
        base, _doc, _path = _load_phase1_instance(args)
        variants: list[tuple[str, object]] = [
            (tag, dataclasses.replace(base, active_soft_constraints=tuple(act)))
            for tag, act in (("LP", ()), ("MILP", ("C7",)))
        ]
    else:
        variants = [
            ("LP", probe_instance()),
            ("MILP", probe_instance(active=("C7",))),
        ]
    solver_inputs: dict[str, object] = dict(PROBE_SOLVER_INPUTS)

    # ---- floor_i 的来源：唯一生产者是 T03-02 派生量层 -------------------
    # 解析逻辑抽到 _resolve_floor_by_id（与 phase1-solve 共用**同一处**口径——
    # 两条命令各写一遍就又是一处「同一约束两处实现」）。
    floor_by_id, floor_source = _resolve_floor_by_id(
        cfg, variants[0][1], resolved, getattr(args, "floor_json", None)
    )
    print(f"■ floor_i 来源：{floor_source}")

    verifier_source = (_P(__file__).resolve().parents[1]
                       / "solver" / "verifier.py")
    source_text = (
        verifier_source.read_text(encoding="utf-8")
        if verifier_source.exists() else None
    )

    payload: list[dict] = []
    worst = 0
    for tag, instance in variants:
        fm = build_formulation(
            instance, resolved,
            eps_abs=eps_abs, eps_rel_price=eps_price, resolution=resolution,
            theta=solver_inputs.get("theta"),
            n_max=solver_inputs.get("n_max"),
            d_max=solver_inputs.get("d_max"),
            r_min=solver_inputs.get("r_min"),
            z_min=solver_inputs.get("z_min"),
            pi_target=solver_inputs.get("pi_target"),
            floor_by_id=floor_by_id,
        )
        model = compile_model(
            fm,
            z_min=solver_inputs.get("z_min"),
            pi_target=solver_inputs.get("pi_target"),
            source=tag,
        )
        P_ref = instance.P_star if instance.P_star is not None else instance.B
        tolerances, _tol_problems = resolve_tolerances(prof, vspec, P_ref=P_ref)

        result = solve_compiled(
            model, spec=bspec, instance=instance, resolved=resolved,
            prefer=args.prefer, eps_total=eps_abs, tolerances=tolerances,
        )
        # ---- Z_ref 的来源：唯一生产者是 T04-08 独立参考实现 --------------
        z_ref, z_ref_source = _resolve_z_ref(
            cfg, instance, resolved, model,
            None if not result.solved else result.variables,
            explicit=args.reference,
        )
        print(f"■ Z_ref 来源：{z_ref_source}")
        # 只把**原始量**交给复核层：不传 SolveResult（SV-12 的接口级独立性）。
        report = verify_solution(
            model,
            None if not result.solved else result.variables,
            spec=vspec, profile=prof, instance=instance,
            reported_objective=result.reported_objective,
            floor_by_id=floor_by_id,
            reference=z_ref,
            verifier_source=source_text,
            resolution=resolution,
        )
        payload.append({
            "variant": tag,
            "solver_form": model.solver_form,
            "solve_status": result.status.normalized,
            "solved": result.solved,
            "report": report.to_dict(),
        })
        if any(c.blocks_progress for c in report.checks):
            worst = 1
        if not args.json:
            _print_verification(
                report, result,
                f"{'探针实例' if not args.instance else args.instance} · {tag}",
            )

    if args.json:
        print(json.dumps(
            {"spec_id": vspec.get("spec_id"), "variants": payload},
            ensure_ascii=False, indent=2, default=str,
        ))
        return worst

    verdicts = [v["report"]["verdict"] for v in payload]
    counts: dict[str, int] = {}
    for v in payload:
        for c in v["report"]["checks"]:
            counts[c["status"]] = counts.get(c["status"], 0) + 1
    print(f"  汇总：{verdicts}　"
          + " / ".join(f"{k} {v}" for k, v in sorted(counts.items()))
          + f"（共 {sum(counts.values())} 条，跨 {len(payload)} 个变体）")
    n_blocked = counts.get("BLOCKED", 0)
    if n_blocked:
        print(f"  ⚠ {n_blocked} 条 BLOCKED 表示**这一环没检查成**，"
              "不得读成通过（逐条理由见上）。")
    n_warn = counts.get("WARN", 0)
    if n_warn:
        print(f"  · {n_warn} 条 WARN 属可解释性提示，不阻塞推进。")
    return worst


def cmd_compile_check(args) -> int:
    """T04-02B 约束编译判定 —— 「编译出的模型，确实是那份声明吗」。

    与前两条命令的分工：``phase1-check`` 判**求解论域**（阈值分割解在这实例上
    是否最优）；``formulate-check`` 判**模型表述**（C1–C13 是否各有明确形式、
    变量集合是否闭合）；本命令判**翻译保真**——把 Formulation 编译成可消费的
    规范形式时，有没有被悄悄改写、漏掉或凭空添加。

    ``--json`` 输出完整模型（变量表 / 稀疏行 / 化简台账），供 T04-02C 消费。
    """
    import dataclasses
    from pathlib import Path as _P

    from ..contracts.pricing_card import load_pricing_card, resolve_parameters
    from ..solver.compiler import (
        check_compiled,
        compile_model,
        load_compiler_spec,
        pulp_available,
        to_pulp,
    )
    from ..solver.formulation import (
        PROBE_SOLVER_INPUTS,
        build_formulation,
        load_formulation_spec,
        probe_instance,
    )

    cfg = config_dir()
    compiler_spec = load_compiler_spec(cfg)
    fspec = load_formulation_spec(cfg)
    schema = json.loads((cfg / "constraint_schema.json").read_text(encoding="utf-8"))
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    card = load_pricing_card(cfg)
    resolved = resolve_parameters(card)
    eps_abs = float(prof["eps_abs"]["value"])
    eps_price = float(prof["eps_price"]["value"])
    resolution = float(prof["rounding"]["resolution"])

    # 制品里白名单字段名是 allowed_in_expressions；读错键会静默退回模块默认值，
    # 于是「制品是白名单的真相来源」这句话就不成立了。
    allow = (compiler_spec.get("literal_allowlist") or {}).get("allowed_in_expressions")
    # 本文件即 src/bidpricing/cli.py ⇒ parents[1] = src/bidpricing
    compiler_path = _P(__file__).resolve().parents[1] / "solver" / "compiler.py"
    if not compiler_path.exists():
        print(f"■ 编译器源码不在预期位置：{compiler_path}")
        return 1
    compiler_source = compiler_path.read_text(encoding="utf-8")

    tf_terms = None
    if args.tf_terms:
        tf_path = _P(args.tf_terms)
        if not tf_path.exists():
            print(f"■ T_front 三元组文件不存在：{tf_path}")
            return 1
        tf_terms = json.loads(tf_path.read_text(encoding="utf-8"))

    if args.instance:
        base, _doc, _path = _load_phase1_instance(args)
        variants: list[tuple[str, object]] = [
            (tag, dataclasses.replace(base, active_soft_constraints=tuple(act)))
            for tag, act in (("LP", ()), ("MILP", ("C7",)))
        ]
        # 入参由命令行给；缺省即 None ⇒ 对应占位行 NOT_COMPILED ⇒ CC-05 BLOCKED。
        solver_inputs: dict[str, object] = {
            "theta": args.theta, "n_max": args.n_max, "d_max": args.d_max,
            "r_min": None, "z_min": args.z_min, "pi_target": args.pi_target,
        }
    else:
        variants = [
            ("LP", probe_instance()),
            ("MILP", probe_instance(active=("C7",))),
        ]
        solver_inputs = dict(PROBE_SOLVER_INPUTS)

    payload: list[dict] = []
    worst = 0
    for tag, instance in variants:
        fm = build_formulation(
            instance, resolved,
            eps_abs=eps_abs, eps_rel_price=eps_price, resolution=resolution,
            theta=solver_inputs.get("theta"),
            n_max=solver_inputs.get("n_max"),
            d_max=solver_inputs.get("d_max"),
            r_min=solver_inputs.get("r_min"),
            z_min=solver_inputs.get("z_min"),
            pi_target=solver_inputs.get("pi_target"),
        )
        model = compile_model(
            fm,
            z_min=solver_inputs.get("z_min"),
            pi_target=solver_inputs.get("pi_target"),
            tf_terms=tf_terms,
            source=tag,
        )
        rows = check_compiled(
            model, fm,
            instance=instance, resolved=resolved,
            constraint_schema=schema, formulation_spec=fspec,
            compiler_source=compiler_source,
            literal_allowlist=allow,
            eps_total=eps_abs,
        )
        payload.append({
            "variant": tag,
            "model": model.to_dict(),
            "checks": [r.to_dict() for r in rows],
            "pulp_available": to_pulp(model) is not None,
        })
        for r in rows:
            if r.blocks_progress:
                worst = 1
        if not args.json:
            _print_compiled(
                model, rows,
                f"{'探针实例' if not args.instance else args.instance} · {tag}",
            )

    if args.json:
        print(json.dumps(
            {"spec_id": compiler_spec.get("spec_id"), "variants": payload},
            ensure_ascii=False, indent=2, default=str,
        ))
        return worst

    total = sum(len(v["checks"]) for v in payload)
    npass = sum(1 for v in payload for c in v["checks"] if c["status"] == "PASS")
    nskip = sum(1 for v in payload for c in v["checks"] if c["status"] == "SKIP")
    print(f"  汇总：{npass} PASS / {nskip} SKIP / {total - npass - nskip} 待处理"
          f"（共 {total} 条，跨 {len(payload)} 个变体）")
    if nskip:
        print(f"  ⚠ {nskip} 条 SKIP 表示**本轮没检查**，不等于通过")
        if pulp_available():
            print("     （本机有 PuLP ⇒ CC-09 已实跑；其余 SKIP 属结构性豁免，"
                  "逐条理由见上）")
        else:
            print("     （本机无 PuLP ⇒ CC-09 未执行；须在装有 PuLP 的环境复跑）")
    return worst


def cmd_contract_check(args) -> int:
    """跨制品契约一致性判据。

    与 ``gate-check`` 的分工：``gate-check`` 判「制品是否就绪、能不能开工」；
    本命令判「已就绪的制品**彼此之间**是否自相矛盾」。后者是历史上多次靠人眼
    才发现的失效模式（例如字段字典写 13/15 位体系、输入协议写位数不参与判定），
    因此必须机械化——人的纪律只能降低概率，不能拦截。
    """
    items = check_contract_consistency(config_dir())
    worst = aggregate(i.status for i in items)

    if args.json:
        print(json.dumps(
            {"worst": worst.value, "checks": [i.to_dict() for i in items]},
            ensure_ascii=False, indent=2, default=str,
        ))
        return 0 if worst is Status.PASS else 1

    print("=" * 78)
    print("跨制品契约一致性检查")
    print("=" * 78)
    for it in items:
        mark = {"PASS": "✓", "WARN": "!", "FAIL": "✗", "BLOCKED": "■"}[it.status.value]
        print(f" {mark} [{it.status.value:>7}] {it.item}")
        print(f"      {it.reason}")
        if it.status is not Status.PASS and it.actual is not None:
            print(f"      actual = {json.dumps(it.actual, ensure_ascii=False, default=str)[:300]}")
            print(f"      expect = {json.dumps(it.expected, ensure_ascii=False, default=str)[:300]}")
    print("-" * 78)
    print(f" 汇总：{worst.value}   （PASS {sum(1 for i in items if i.status is Status.PASS)}"
          f" / 共 {len(items)}）")
    return 0 if worst is Status.PASS else 1
