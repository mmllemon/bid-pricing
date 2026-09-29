"""共享助手与打印器（自 bidpricing/cli.py 逐字拆出）。

实例加载、注册表/选择项读写、结算参考解析、各命令共用的 _print_* 输出器。
"""
from __future__ import annotations

import json
import sys
from ..artifact import (
    ArtifactNotFreezable,
    freeze_record,
    load_registry,
    parse_records,
    save_registry,
)
from ..contracts.selector import ruleset_self_test, select_rule_set
from ..paths import GATE0_REGISTRY, PROJECT_SELECTION, config_dir, repo_root
from ..selection_options import (
    SELECTABLE_OPTIONS,
    clear_option,
    read_option_entry,
    resolve_option,
    write_option,
)


_STATUS_MARK = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL", "BLOCKED": "BLOCKED"}


RULE_SET_CHOICES = ("GB/T50500-2024", "GB50500-2013")


# predicted_q1 来源词表——与 config/predicted_q1_spec.json / closed_loop_spec.json
# 的 source_domain 双向锁定（tests/test_predicted_q1.py），不得单方面扩域。
PREDICTED_Q1_SOURCE_CHOICES = ("historical_replay", "model", "manual")


def _registry_path():
    return config_dir() / GATE0_REGISTRY


def _selection_path():
    return config_dir() / PROJECT_SELECTION


def _load():
    path = _registry_path()
    if not path.exists():
        print(f"[FATAL] 注册表不存在：{path}", file=sys.stderr)
        raise SystemExit(2)
    return load_registry(path)


def _selection_from_args(args) -> dict:
    selection = select_rule_set(
        tender_document_date=args.tender_document_date,
        contract_date=args.contract_date,
        standard_version_declared=args.standard_version_declared,
        region=args.region,
        project_type=args.project_type,
        funding_type=args.funding_type,
        tender_document_override=args.tender_document_override,
        contract_override=args.contract_override,
        adjustment_scope_declared=args.adjustment_scope,
        selection_file=getattr(args, "selection_file", None),
    )
    return selection.to_dict()


def _options_list(path, args) -> int:
    rule_set_id = args.rule_set
    rows = []
    for key, option in SELECTABLE_OPTIONS.items():
        allowed = option.allowed_for(rule_set_id)
        entry = read_option_entry(path, key)
        resolution = (
            resolve_option(key, rule_set_id, path=path) if rule_set_id else None
        )
        rows.append(
            {
                "option": option.to_dict(),
                "allowed_here": list(allowed),
                "discretionary_here": option.is_discretionary(rule_set_id),
                "file_entry": entry,
                "resolution": resolution.to_dict() if resolution else None,
            }
        )

    if args.json:
        print(json.dumps({"selection_file": str(path), "options": rows},
                         ensure_ascii=False, indent=2))
        return 0

    print("=" * 78)
    print("选择项清单（《实施路线 v3.2.1》§7.1.1 断言 1/2/6 的落地）")
    print(f"落值文件：{path}")
    print("=" * 78)
    for row in rows:
        option = row["option"]
        print(f"\n■ {option['key']}  —— {option['title']}")
        print(f"  所属闸门：{option['gate']}    规格出处：{option['spec_ref']}")
        print(f"  取值集合（按规则集）：")
        for rs, values in option["allowed_by_rule_set"].items():
            print(f"      {rs:<16} {' | '.join(values)}")
        print(f"  默认值：{option['default']}（选择项永无默认值）")
        if rule_set_id:
            print(f"  当前规则集 {rule_set_id} 下合法取值：{' | '.join(row['allowed_here'])}"
                  f"    是否真有选择余地：{'是' if row['discretionary_here'] else '否（规范明文确定）'}")
            res = row["resolution"]
            print(f"  解析结果：{res['status']}    取值={res['value']!r}    来源={res['source']}")
            for err in res["errors"]:
                print(f"      [冲突] {err}")
        else:
            print("  （未指定 --rule-set：不解析当前取值）")
        if row["file_entry"]:
            entry = row["file_entry"]
            print(f"  已落值：{entry.get('value')!r} @ {entry.get('selected_at')}"
                  f" by {entry.get('actor')}")
            if entry.get("rationale"):
                print(f"     依据：{entry['rationale']}")
        else:
            print("  已落值：（无——未选择）")
        for value, text in option["impact"].items():
            print(f"  影响 [{value}]：{text}")
        print(f"  下游消费方：{'、'.join(option['consumers'])}")
        print(f"  为何是选择项：{option['rationale']}")
    print("\n" + "=" * 78)
    print("说明：未落值的选择项在 T00-08 输出中**不写 key**。未落值**不阻塞** "
          "Gate 0a 与\n"
          "      WP1/WP2/WP3（两条分支都要求被实现，选择只决定生效分支），"
          "但会阻塞\n"
          "      Phase 0 输入门——§7.1.1 断言 2 的熔断点在那里。")
    print("落值命令：bidpricing options set --key <key> --value <value> --rule-set <rid>")
    return 0


def _options_set(path, args) -> int:
    key = args.key
    option = SELECTABLE_OPTIONS.get(key)
    if option is None:
        print(f"[FATAL] 未登记的选择项：{key}（已登记：{list(SELECTABLE_OPTIONS)}）",
              file=sys.stderr)
        return 2
    rule_set_id = args.rule_set
    if rule_set_id is None:
        print("[FATAL] options set 必须显式给出 --rule-set（合法取值随规则集而变）",
              file=sys.stderr)
        return 2

    # 先校验再落值：合法性判据只有一处（selection_options.resolve_option）
    probe = resolve_option(key, rule_set_id, cli_value=args.value)
    if probe.errors:
        print(f"[REJECTED] {probe.errors[0]}", file=sys.stderr)
        print(f"           该规则集下合法取值：{list(probe.allowed)}", file=sys.stderr)
        return 2
    if not option.is_discretionary(rule_set_id):
        print(
            f"[REJECTED] {key} 在规则集 {rule_set_id} 下由规范明文确定为 "
            f"{probe.value}，不构成可选项；无需（也不允许）落值。",
            file=sys.stderr,
        )
        return 2

    doc = write_option(
        path, key, args.value,
        rule_set_id=rule_set_id,
        rationale=args.rationale or "",
        actor=args.actor,
    )
    entry = (doc.get("options") or {}).get(key, {})
    print(f"[SELECTED] {key} = {args.value}   （规则集 {rule_set_id}）")
    print(f"           落值文件：{path}")
    print(f"           落值时间：{entry.get('selected_at')}   落值人：{entry.get('actor')}")
    if entry.get("rationale"):
        print(f"           依据：{entry['rationale']}")
    else:
        print("           [提示] 未提供 --rationale：该选择项将缺少决策依据快照")
    print("\n下一步：PYTHONPATH=src python -m bidpricing.cli gate-check "
          "--contract-date <合同签订日期>    # 复查 Gate 0a 剩余阻塞项")
    return 0


def _options_clear(path, args) -> int:
    clear_option(path, args.key)
    print(f"[CLEARED]  {args.key} → 未选择（不写 value 字段）")
    print(f"           落值文件：{path}")
    print("           注意：未选择的选择项**不阻塞** Gate 0a 与 WP1/WP2/WP3，"
          "但会让\n"
          "                 Phase 0 输入门判 BLOCKED（§7.1.1 断言 2 熔断）")
    return 0


def _read_config(fname: str) -> dict | None:
    p = config_dir() / fname
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _print_exactness(verdict, title: str) -> None:
    from ..solver.exactness import IMPLEMENTABILITY_IDS

    print("=" * 78)
    print(f"Phase 1 精确性条件判定（T04-00）｜ {title}")
    print("=" * 78)
    print(f"  结论：{verdict.verdict}　（solver_form = {verdict.solver_form}）")
    if verdict.verdict == "EXACT":
        print("       阈值分割解与 P_A 最优解一致——Phase 1 解析解可用作 candidate")
    elif verdict.verdict == "INAPPLICABLE":
        print("       阈值分割解**不是** P_A 的最优解——必须交 Phase 2（LP/MILP）")
    else:
        print("       输入未定态，判据算不出来——不得降级为 EXACT")
    print()
    for c in verdict.conditions:
        tag = {"PASS": "  PASS", "WARN": "  WARN",
               "FAIL": "  FAIL", "BLOCKED": "BLOCKED"}[c.status]
        group = "A 精确性" if c.id not in IMPLEMENTABILITY_IDS else "B 可实现性"
        print(f"[{tag}] {c.id} {c.name}　（{group}）")
        print(f"           {c.detail}")
    if verdict.implementation_notes:
        print()
        print("  实施性义务（不改变结论，但不做会出错）：")
        for n in verdict.implementation_notes:
            print(f"    · {n}")
    print()


def _print_formulation(fm, rows, title: str) -> None:
    print("=" * 78)
    print(f"T04-02A LP 形式化（制品↔实现双向锁定）｜ {title}")
    print("=" * 78)
    print(f"  求解器形态：{fm.solver_form}　（active_soft_constraints = "
          f"{list(fm.active) or '空'}）")
    print(f"  变量 {fm.n_vars} 列 / 约束行 {fm.n_rows} 行")
    print(f"  目标：{fm.objective_expr}")
    print(f"        常量项 = {fm.objective_constant:,.2f}（不进系数，须出现在报告层）")
    print(f"  C5 下界 lb_c5 = {fm.lb_c5:.6g} 元（= max(eps_price·P*, 报价分辨率)）")
    if fm.box_notes:
        print("  箱型警告：")
        for n in fm.box_notes:
            print(f"    [!] {n}")
    if fm.constant_checks:
        for cc in fm.constant_checks:
            verdict = {True: "PASS", False: "FAIL", None: "只报值不判"}[cc.passes]
            print(f"  常量判据 {cc.constraint_id}（{cc.metric}）= "
                  f"{cc.value if cc.value is None else round(cc.value, 6)} ⇒ {verdict}")
            print(f"           {cc.reason}")
    if fm.deferred:
        print("  挂账项（不静默丢弃）：")
        for d in fm.deferred:
            print(f"    · {d.constraint_id} [{d.form}] → {d.owner_task}：{d.reason}")
    print()
    print("  逐条判据：")
    for it in rows:
        tag = {"PASS": "  PASS", "WARN": "  WARN", "SKIP": "  SKIP",
               "FAIL": "  FAIL", "BLOCKED": "BLOCKED"}[it.status]
        print(f"  [{tag}] {it.item}")
        print(f"           {it.reason}")
    print()


def build_derived_for_cli(cfg, instance, resolved):
    """CLI 便捷：μ=0 / DECLINE / 无不平衡条款的派生量（探针与演示用）。

    真实项目的派生量声明由 Phase 0 输入门传入，不得经由本函数静默补齐。
    """
    from ..solver.precheck import build_derived

    return build_derived(instance, resolved)


def _print_reference(report, title: str, iso, z_solver) -> None:
    obj = report.objective
    print("=" * 78)
    print(f"T04-08 独立参考实现（第二条计算路径）｜ {title}")
    print("=" * 78)
    print("  公式来源：路线 §5.3 S0  Z = Σ[R_i(p_i) − c_i·q_i^1]；"
          "分支与系数取自规则卡与利润桥接表（**不由生产代码抄录**）")
    if obj is not None:
        print(f"  Z_total（全量，§5.3 S0）      = {obj.Z_total:,.4f} 元")
        print(f"  Z_competitive（目标层，X_opt）= {obj.Z_competitive:,.4f} 元")
        print(f"  constant_part（常数差）       = {obj.constant_part:,.4f} 元")
        if z_solver is not None:
            print(f"  Z_solver（对照侧）            = {z_solver:,.4f} 元")
        print()
        print("  项目          分支        r          p         R_i           成本         贡献")
        for l in obj.lines:
            r = "—" if l.r is None else f"{l.r:.4f}"
            p = "—" if l.p is None else f"{l.p:.2f}"
            rev = "—" if l.revenue is None else f"{l.revenue:,.2f}"
            cost = "—" if l.cost is None else f"{l.cost:,.2f}"
            ctr = "—" if l.contribution is None else f"{l.contribution:,.2f}"
            print(f"  {l.item_id:<12}  {l.branch:<9}  {r:>7}  {p:>9}  "
                  f"{rev:>13}  {cost:>12}  {ctr:>13}")
        if obj.blocked:
            print()
            for b in obj.blocked:
                print(f"  ✗ {b}")
    print()
    print("  三层隔离证明（路线 v3.2.1 P2-⑩）：")
    for key, label in (("ISO-1", "① 源码文件不重叠"),
                       ("ISO-2", "② 不共享可变状态"),
                       ("ISO-3", "③ 作者分离已签署")):
        layer = iso.get(key, {})
        print(f"    {label}：{layer.get('status','?')}　{layer.get('reason','')}")
    print()
    print("-" * 78)
    for c in report.checks:
        print(f"[{c.status:>7}] {c.item}　{c.reason}")
    print("-" * 78)
    tally: dict[str, int] = {}
    for c in report.checks:
        tally[c.status] = tally.get(c.status, 0) + 1
    summary = "  ".join(f"{k}×{tally[k]}" for k in
                        ("FAIL", "BLOCKED", "WARN", "SKIP", "PASS") if tally.get(k))
    print(f"  {summary}　⇒ 聚合结论 {report.verdict()}")
    if iso.get("ISO-3", {}).get("status") != "PASS":
        print("  ★ 隔离③未成立 ⇒ T04-04 对拍结论栏**强制 BLOCKED**，"
              "不得出现『对拍通过』字样")


def _print_milp(tag: str, model, result, report) -> None:
    acc = report.acceptance
    print("=" * 72)
    print(f"■ {tag}：形态 {model.solver_form} / 归一状态 {acc.normalized_status}")
    print(f"  诊断量：{dict(result.diagnostics) or '（后端未提供）'}")
    print(
        f"  验收结论：{acc.accepted} ｜ 最优性已证：{acc.optimality_proven}"
        f" ｜ 聚合：{report.verdict()}"
    )
    if acc.accepted is None:
        print("  说明：形态非 MILP ⇒ 本协议不适用（SKIP，不是 PASS）")
    else:
        print(
            f"  Z={acc.objective} ｜ 对偶界={acc.best_bound} ｜ "
            f"间隙(自报)={acc.gap_reported} ｜ 间隙(复算)={acc.gap_recomputed}"
        )
        for reason in acc.reasons:
            print(f"    · {reason}")
    for check in report.checks:
        print(f"  {check.item} {check.status} ｜ {check.reason}")
        if check.status in ("FAIL", "BLOCKED"):
            print(f"        actual={check.actual} / expected={check.expected}")


def _print_phase1(report, title: str) -> None:
    sol = report.solution
    print("=" * 78)
    print(f"T04-01 Phase 1 解析解（排序 + 二分 + 贪心定容）｜ {title}")
    print("=" * 78)
    print(f"  求解状态：{sol.status}　适用性：{sol.applicability or '—'}")
    print(f"  定位：role={sol.role}、is_final={sol.is_final}——"
          "**不承担最终解职责**（T04-05 验收最终解）")
    print(f"        {sol.relates_to_full_problem}")
    print(f"  {sol.reason}")
    if sol.assignments:
        lam = sol.lam
        print()
        print(f"  λ = {lam.value}　（{lam.kind}，临界项 {lam.critical_item}）")
        if lam.interval and lam.interval[0] != lam.interval[1]:
            print(f"        合法 λ 区间：{list(lam.interval)}")
        print(f"        {lam.reason}")
        print()
        print("  位次  项目          p            下界        上界        r_eff   层归属")
        for a in sol.assignments:
            ub = "不限价" if a.upper is None else f"{a.upper:>10.4f}"
            print(f"  {a.rank:>3}   {a.item_id:<12}  {a.p:>11.4f}  "
                  f"{a.lower:>10.4f}  {ub:>10}  {a.r_eff:>7.4f}  {a.layer}")
    if report.referee is not None:
        r = report.referee
        print()
        print(f"  独立裁判（check_solution，非本层自算）：Z = {r.Z:,.2f} 元、"
              f"C1 残差 = {r.c1_residual}, 可行 = {r.feasible}")
        if r.violations:
            for v in r.violations[:8]:
                print(f"    ✗ {v}")
    if sol.notes:
        print()
        print("  实施性义务（B 组，不改变结论但不做会出错）：")
        for n in sol.notes:
            print(f"    · {n}")
    print()
    print("-" * 78)
    for c in report.checks:
        print(f"[{c.status:>7}] {c.item}　{c.reason}")
    print("-" * 78)
    tally: dict[str, int] = {}
    for c in report.checks:
        tally[c.status] = tally.get(c.status, 0) + 1
    summary = "  ".join(f"{k}×{tally[k]}" for k in
                        ("FAIL", "BLOCKED", "WARN", "SKIP", "PASS") if tally.get(k))
    print(f"  {summary}　⇒ 聚合结论 {report.verdict()}")
    if report.verdict() != "PASS":
        print("  说明：本命令在 verdict≠PASS 时返回 1。若原因是适用范围守卫"
              "（INAPPLICABLE/BLOCKED），那是**如实反映**，不是实现缺陷——"
              "两条路径不一致在此处是正确行为（impl_plan_v321 §4.1）。")


def _print_backend(model, result, checks, cc_rows, title: str) -> None:
    print("=" * 78)
    print(f"求解后端适配（T04-02C）｜ {title}")
    print("=" * 78)
    st = result.status
    print(f"  模型：{model.solver_form}　变量 {model.n_vars}　行 {model.n_rows}")
    print(f"  所需能力：{list(result.selection.required)}")
    print(f"  选中后端：{result.selection.name!r}"
          f"（active={result.selection.active!r}）")
    for c in result.selection.candidates:
        mark = "✓" if c.verdict == "SELECTED" else "✗"
        print(f"      {mark} {c.name}: {c.verdict} — {c.reason}")
    print(f"  归一状态：{st.normalized}（class={st.status_class}）"
          f"⇒ 判据 {st.judge}")
    if st.native is not None:
        print(f"      原生状态 {st.native!r}　归一路径 {st.via}")
    print(f"      理由：{st.reason}")
    if result.solved:
        print(f"  目标值：自报 {result.reported_objective!r}"
              f"　复算 {result.recomputed_objective!r}"
              f"　Δ {result.objective_delta!r}")
        print(f"  解：{len(result.variables)} 个变量"
              f"{'，缺 ' + str(list(result.missing)) if result.missing else ''}")
        if result.solution_check is not None:
            sc = result.solution_check
            print(f"  业务侧：feasible={sc.feasible}　Z={sc.Z!r}"
                  f"　C1 残差={sc.c1_residual!r}")
    print(f"  耗时：{result.seconds * 1000:.1f} ms")
    print()
    for r in checks:
        mark = {"PASS": "✓", "FAIL": "✗", "BLOCKED": "■", "SKIP": "○"}.get(
            r.status, "?")
        print(f" {mark} [{r.item}] {r.status}")
        print(f"      {r.reason}")
    print("-" * 78)


def _print_derived(report, title: str) -> None:
    from ..derived import STATUS_PASS

    print("=" * 78)
    print(f"派生量计算（T03-02）｜ {title}")
    print("=" * 78)
    print(f"  结论：{report.verdict()}")
    print(f"  μ = {report.mu!r}（已声明={report.mu_declared}）"
          f"　loss_acceptance = {report.loss_acceptance}"
          f"（已落值={report.loss_acceptance_declared}）")
    print()
    print("  逐项派生量：")
    print(f"    {'项':<14}{'L':>12}{'U':>12}{'floor':>12}{'r_eff':>10}")
    for it in report.items:
        def _f(v):
            return "—" if v is None else f"{v:g}"
        print(f"    {it.item_id:<14}{_f(it.L):>12}{_f(it.U):>12}"
              f"{_f(it.floor):>12}{_f(it.r_eff):>10}")
    print()
    non_pass = [c for c in report.checks if c.status != STATUS_PASS]
    if non_pass:
        print("  判据（非 PASS）：")
        for c in non_pass:
            print(f"    [{c.status}] {c.item}")
            print(f"        {c.reason}")
    else:
        print("  判据：全部 PASS（见 --json 的 checks 全表）")
    blocking = report.blocking()
    if blocking:
        print()
        print(f"  ⚠ 阻塞项 {len(blocking)} 条 —— 派生量未全部闭合成正确性前置。")
    print()


def _resolve_z_ref(cfg, instance, resolved, model, variables, explicit=None):
    """``Z_ref`` 的来源解析 —— **唯一实现**（与 floor 同款「必须自述来源」）。

    三条优先级：

    ① 显式 ``--reference`` ⇒ 人工实验/外部对照值，最高优先；
    ② 否则由 **T04-08 独立参考实现**（``bidpricing.refimpl``）现场重算——
       它是 §5.3 S0 要求的**第二条路径**，不 import 任何生产计算模块；
    ③ 无解或参考层不可用 ⇒ ``None``（下游 SV-13 如实判 BLOCKED，
       不得拿生产侧自算值顶替——那是同源对账，恒真式）。

    返回 ``(Z_ref 或 None, 来源描述)``。
    """
    from pathlib import Path as _P

    if explicit is not None:
        return float(explicit), f"显式 --reference {float(explicit):g}"
    if not variables:
        return None, "无解 ⇒ 不产 Z_ref"
    try:
        from ..refimpl import reference as _R
        from ..refimpl import isolation as _I

        # ★ 必须按**变量族**过滤：C7 的二值 z_i 与 p_i 共用同一个 item_id，
        #   不过滤的话 0/1 会把单价覆盖掉（而且不报错，只是 Z_ref 静默偏掉）。
        #   ——这个 bug 正是被 SV-13 的跨来源对照抓到的。
        p_by_id = {
            v.item_id: float(variables[v.symbol])
            for v in model.variables
            if v.family == "p" and v.item_id and v.symbol in variables
        }
        if not p_by_id:
            return None, "模型中无单价变量 ⇒ 不产 Z_ref"
        spec = _R.load_reference_spec(cfg)
        snap = _R.snapshot(instance, resolved)
        iso = _I.collect_isolation(
            source_paths=[
                _P(__file__).resolve().parents[1] / "refimpl" / "reference.py",
                _P(__file__).resolve().parents[1] / "refimpl" / "isolation.py",
            ],
            snapshot_obj=snap,
            # 原 parents[1]/"docs" 是 src 布局迁移前的陈旧锚点（src/docs 不存在），
        # 致 RI-09 隔离③看不见已签署的 docs/reference_review_signoff.json；
        # 改用仓库根锚定（布局无关）。
        docs_dir=repo_root() / "docs",
            spec=spec,
        )
        rep = _R.reference_report(
            instance, p_by_id, resolved=resolved, spec=spec, isolation=iso,
        )
        obj = rep.objective
        if obj is None or obj.blocked:
            return None, (
                "T04-08 参考层未产出 Z_ref（" +
                ("；".join(obj.blocked) if obj else "无快照") + "）"
            )
        iso_txt = "、".join(
            f"{k}={iso[k]['status']}" for k in ("ISO-1", "ISO-2", "ISO-3")
        )
        return obj.Z_total, (
            f"T04-08 参考实现重算（{len(p_by_id)} 项，隔离 {iso_txt}）"
        )
    except Exception as exc:  # pragma: no cover - 参考层不可用不应中断复核
        return None, f"参考层不可用（{type(exc).__name__}）"


class InstanceLoadError(Exception):
    """``--instance`` 文件读不出来（不存在 / 坏 JSON）。

    为什么抛异常而不是返回 None：各 ``cmd_*`` 在自己的函数体里无法替
    调用方 ``return 1`` 退出码，逐个调用点写 try/except 又是把同一套
    样板复制 N 份——统一在这里抛出，由 ``main()`` 兜成「打印 + return 1」。
    """


def _load_instance_doc(args) -> dict:
    """``--instance`` 分支共用的「读文件 → JSON dict」。

    「文件不存在 → 报错」「坏 JSON → 报错」两件事的口径在这里**只写一遍**
    （原来「不存在」在各命令里抄了 11 份，「坏 JSON」直接裸 traceback）。
    """
    from pathlib import Path as _P

    path = _P(args.instance)
    if not path.exists():
        raise InstanceLoadError(f"实例文件不存在：{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InstanceLoadError(
            f"实例文件不是合法 JSON：{path}（{exc}）") from exc


def _load_phase1_instance(args, *, wrapped: bool = False):
    """``--instance`` 分支共用的「读文件 → Phase1Instance」。

    ``wrapped=False``：整个文档就是实例（多数命令的形态）；
    ``wrapped=True``：文档是 ``{"instance": {...}, "p"/"z"/"Z"/...: ...}``
    包装（constraint-judge / precheck / diagnose 的形态），实例取
    ``doc["instance"]`` 键、缺键回退整个文档（与原各处口径一致）。
    返回 ``(instance, doc, path)``：doc 供调用点取附加键，path 供 title 沿用。
    """
    from pathlib import Path as _P

    from ..solver.instance import Phase1Instance

    path = _P(args.instance)
    doc = _load_instance_doc(args)
    inst_doc = doc.get("instance", doc) if wrapped else doc
    return Phase1Instance.from_dict(inst_doc, source=str(path)), doc, path


def _resolve_floor_by_id(cfg, instance, resolved, explicit_json=None):
    """``floor_i`` 的来源解析 —— **唯一实现**（verify-solution 与 phase1-solve 共用）。

    三条优先级，且**必须自述来源**（②与③后果相同但来源不同）：

    ① 显式 ``--floor-json`` ⇒ 人工实验，最高优先（便于独立复核某一张地板表）；
    ② 否则由 T03-02 派生量层现场产出——真实项目上 μ 未落值时为空表，
       于是下游如实判 BLOCKED，而不是拿 ``c_i`` 或 ``L_i`` 冒充地板；
    ③ 派生量层不可用 ⇒ ``None``。

    返回 ``(floor_by_id 或 None, 来源描述)``。
    """
    from pathlib import Path as _P

    if explicit_json:
        fpath = _P(explicit_json)
        if not fpath.exists():
            return None, f"显式文件不存在：{fpath}"
        table = {
            str(k): float(v)
            for k, v in json.loads(fpath.read_text(encoding="utf-8")).items()
        }
        return (table or None), f"显式文件 {explicit_json}（{len(table)} 项）"
    try:
        from ..derived import (
            compute_derived as _compute_derived,
            inputs_from_project as _inputs_from_project,
            load_derived_spec as _load_derived_spec,
        )

        _pin = _inputs_from_project(cfg)
        _drep = _compute_derived(
            instance, resolved,
            mu=_pin["mu"], loss_acceptance=_pin["loss_acceptance"],
            unbalanced=_pin["unbalanced"], spec=_load_derived_spec(cfg),
        )
        _floor = _drep.floor_by_id()
        return (_floor or None), (
            f"T03-02 派生量层（verdict={_drep.verdict()}，{len(_floor)} 项）"
            if _floor else
            f"T03-02 派生量层未产出 floor（verdict={_drep.verdict()}）"
        )
    except Exception as exc:  # pragma: no cover - 派生层不可用不应中断命令
        return None, f"派生量层不可用（{type(exc).__name__}）"


def _print_verification(report, result, title: str) -> None:
    print("=" * 78)
    print(f"解校验（T04-02D）｜ {title}")
    print("=" * 78)
    print(f"  结论：{report.verdict}　（求解状态 {result.status.normalized}）")
    print("  容差表：" + ", ".join(
        f"{k}={v!r}" for k, v in report.tolerances))
    if report.objective:
        print("  目标值：" + ", ".join(f"{k}={v!r}" for k, v in report.objective))
    if report.tier_distribution:
        print("  层归属分布：" + ", ".join(
            f"{k}={v}" for k, v in report.tier_distribution))
    print()
    for c in report.checks:
        mark = {"PASS": "✓", "WARN": "△", "FAIL": "✗",
                "BLOCKED": "■", "SKIP": "○"}.get(c.status, "?")
        print(f" {mark} [{c.item}] {c.status}")
        print(f"      {c.reason}")
    print("-" * 78)


def _print_compiled(model, checks, title: str) -> None:
    print("=" * 78)
    print(f"约束编译（T04-02B）｜ {title}")
    print("=" * 78)
    print(f"  目标：{model.objective_sense}  obj_const = {model.objective_constant!r}"
          f"　形态 = {model.solver_form}")
    fams: dict[str, int] = {}
    for v in model.variables:
        fams[v.family] = fams.get(v.family, 0) + 1
    print(f"  变量：{model.n_vars}（" + "、".join(f"{k}×{n}" for k, n in sorted(fams.items())) + "）")
    print(f"  行  ：{model.n_rows}")
    by_cid: dict[str, int] = {}
    for r in model.rows:
        by_cid[r.constraint_id] = by_cid.get(r.constraint_id, 0) + 1
    print("        " + "、".join(f"{k}×{n}" for k, n in sorted(by_cid.items())))
    if model.simplifications:
        print(f"  化简台账（{len(model.simplifications)} 条）：")
        for s in model.simplifications:
            print(f"    · [{s.kind}] {s.subject}")
            print(f"        {s.reason[:110]}")
    if model.notes:
        print("  说明：")
        for n in model.notes:
            print(f"    · {n[:110]}")
    print()
    tags = {"PASS": "  PASS", "WARN": "  WARN", "SKIP": "  SKIP",
            "FAIL": "  FAIL", "BLOCKED": "BLOCKED", "INFO": "  INFO"}
    for c in checks:
        print(f"  {tags.get(c.status, c.status)}  {c.item}")
        print(f"        {c.reason[:150]}")
    print()


def _pricing_card_branch_scan(card: dict, override: dict | None, path) -> int:
    import json as _json
    from pathlib import Path as _P

    """按规则卡对匹配报告逐项判分支——分支只依赖 r=Q1/Q0，与 P0 无关。

    输出的是**优化空间的第一手证据**：区间内项无论怎么报价结算结构不变；
    越界项才是 P1 生效的地方，也是不平衡报价条款的作用域。
    """
    from collections import Counter

    from ..contracts.pricing_card import classify_branch, resolve_parameters

    report = _json.loads(_P(path).read_text(encoding="utf-8"))
    items = report.get("items", report if isinstance(report, list) else [])
    params = resolve_parameters(card, override)

    counts: Counter = Counter()
    undetermined: list[str] = []
    out_of_range: list[tuple[str, float]] = []
    for it in items:
        q0, q1 = it.get("q0"), it.get("q1_point")
        if q0 is None or q1 is None or not q0:
            undetermined.append(it.get("item_id", "?"))
            continue
        r = q1 / q0
        branch = classify_branch(r, params)
        counts[branch] += 1
        if branch != "IN_RANGE":
            out_of_range.append((it.get("item_id", "?"), r))

    total = sum(counts.values())
    print(f"\n 分支扫描 ← {path}（Q0/Q1 齐备 {total} 项）")
    for branch in ("IN_RANGE", "DECREASE", "INCREASE"):
        n = counts.get(branch, 0)
        pct = (n / total * 100) if total else 0.0
        print(f"   {branch:<9} {n:>4} 项（{pct:5.1f}%）")
    if out_of_range:
        print("   越界项（P1 生效 / 不平衡报价条款作用域）：")
        for item_id, r in sorted(out_of_range, key=lambda x: x[1]):
            print(f"     · {item_id}  r={r:.4f}")
    if undetermined:
        print(f"   未定态 {len(undetermined)} 项（Q0 或 Q1 缺失）："
              f"{undetermined[:5]}{' …' if len(undetermined) > 5 else ''}")
    return 0


def _load_closed_loop_bundle(records_arg: str) -> tuple[object, str | None]:
    """加载闭环输入束；失败时返回 (None, 原因)——原因必须具名，不静默。"""
    from ..closed_loop import ClosedLoopError, load_closed_loop_bundle

    try:
        return load_closed_loop_bundle(records_arg), None
    except ClosedLoopError as exc:
        return None, str(exc)


def _run_closed_loop_for_bundle(bundle, spec) -> object:
    from ..closed_loop import run_closed_loop

    return run_closed_loop(
        bundle.records,
        replay_status=bundle.replay_status,
        base_config_version=bundle.base_config_version,
        proposed_config_version=bundle.proposed_config_version,
        proposed_changes=bundle.proposed_changes,
        current_config=bundle.current_config,
        predicted_q1_source=bundle.predicted_q1_source,
        predicted_q1_source_ref=bundle.predicted_q1_source_ref,
        predicted_q1_declaration=bundle.predicted_q1_declaration,
        actual_q1_source=bundle.actual_q1_source,
        segment=bundle.segment,
        project_type=bundle.project_type,
        confidence_interval=bundle.confidence_interval,
        min_sample_size=bundle.min_sample_size or 30,
        q_min=bundle.q_min if bundle.q_min is not None else 1.0,
        spec=spec,
        source=bundle.source,
    )
