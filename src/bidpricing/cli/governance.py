"""治理与自检命令（自 bidpricing/cli.py 逐字拆出）。

gate-check / ruleset-select / ruleset-selftest / freeze / options /
scope-impact / status / identity-check / audit-verify。
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
from ..contracts.scope_impact import compare_scopes
from ..contracts.selector import ruleset_self_test, select_rule_set
from ..gates.gate0 import evaluate_gate_0
from ..identity import (
    check_component_sum,
    check_identity,
    decompose,
    load_pair_fixture,
    rates_from_fixture,
    stated_from_fixture,
    totals_from_fixture,
)
from ..paths import GATE0_REGISTRY, PROJECT_SELECTION, config_dir, repo_root
from ..status import collect as collect_status
from ..status import render as render_status
from ..status import write_state
from ..states import Status, aggregate
from .common import _STATUS_MARK, _load, _options_clear, _options_list, _options_set, _registry_path, _selection_from_args, _selection_path


def cmd_gate_check(args) -> int:
    registry = _load()
    selection = _selection_from_args(args)
    report = evaluate_gate_0(
        registry,
        config_dir(),
        selection,
        gate_0b_passed_at=args.gate_0b_passed_at,
        phase1_first_build_at=args.phase1_first_build_at,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["summary"]["gate_0a"] == "PASS" else 1

    print("=" * 78)
    print("Gate 0 机械判定（实施路线 v3.2.1 §7.1 / §7.1.1）")
    print("=" * 78)
    for key, title in (
        ("gate_0a", "Gate 0a — Technical Interface & Rule-Set Frozen"),
        ("gate_0b", "Gate 0b — Business Caliber & Compliance Frozen"),
        ("phase_0_input_gate",
         "Phase 0 输入门 — Selectable-Option Values Resolved"),
    ):
        section = report[key]
        print(f"\n[{section['status']:>7}] {title}")
        print(f"          目的：{section['purpose']}")
        for item in section["items"]:
            mark = _STATUS_MARK[item["status"]]
            print(f"    {mark:>7}  {item['item']:<32} {item['reason']}")
            if item["status"] in ("BLOCKED", "FAIL") and item["expected"] is not None:
                print(f"            {'':<32} actual={item['actual']!r} expected={item['expected']!r}")

    seq = report["assertion_5_sequence"]
    print(f"\n[{seq['status']:>7}] §7.1.1-5 时序断言   {seq['reason']}")

    ci = report["assertion_6_ci_gate"]
    print(f"\n[{ci['status']:>7}] §7.1.1-6 CI 门禁")
    for item in ci["items"]:
        print(f"    {_STATUS_MARK[item['status']]:>7}  {item['item']:<32} {item['reason']}")

    if report["advisories"]:
        print("\n遗留项（不参与机械判定，但需人工确认）")
        for adv in report["advisories"]:
            tag = "FREEZE-BLOCKER" if adv["kind"] == "freeze_blocker" else "OPEN-ITEM"
            print(f"    [{tag}] {adv['gate']}.{adv['key']}: {adv['text'][:120]}")

    print("\n" + "=" * 78)
    print(f"Gate 0a = {report['summary']['gate_0a']}   "
          f"Gate 0b = {report['summary']['gate_0b']}")
    print(f"Phase 0 输入门          = {report['summary']['phase_0_input_gate']}")
    print(f"Phase 0 准入            = {report['summary']['phase_0']}")
    print(f"WP4 求解层构建          = {report['summary']['wp4_solver_layer']}")
    print("=" * 78)

    gate_0a_ok = report["summary"]["gate_0a"] == "PASS"
    phase0_ok = report["summary"]["phase_0_input_gate"] == "PASS"

    if gate_0a_ok:
        print("\n结论：Gate 0a 通过，放行 WP1 / WP2 / WP3（解析器 / 配置层 / 判定层）。")
    else:
        print("\n结论：Gate 0a 未通过 —— WP1 / WP2 / WP3 暂不得开工。")
        print("      未通过项见上方 BLOCKED 行；技术接口类阻塞必须补齐后才放行。")

    if phase0_ok:
        print("Phase 0 输入门通过：项目级选择项与项目级输入数据均已就位，可启动 Phase 0 求解。")
    else:
        blocked_now = [
            i["item"] for i in report["phase_0_input_gate"]["items"]
            if i["status"] in ("BLOCKED", "FAIL")
        ]
        print("Phase 0 输入门未通过：以下项目级输入尚未就位 —— "
              f"{', '.join(blocked_now)}")
        print("      注意：这**不阻塞** Gate 0a 与 WP1/WP2/WP3。")
        print("      它们都是「求解启动前必须有、开发期不需要」的输入——")
        print("      机制（规则集/字段/分类规则书）已冻结即可开工，只有**取值/数据**被卡住。")
        # 提示只针对**实际**阻塞项输出，避免提示指向一个已经做完的动作
        # （历史上出现过：adjustment_scope 已落值，提示仍写「选择项取值未定」）。
        if "adjustment_scope" in blocked_now:
            print("      · 选择项取值未定（adjustment_scope）→ 两条分支都要求被实现，"
                  "选择只决定哪条生效")
            print("        落值：bidpricing options set --key adjustment_scope "
                  "--value <FULL|SEGMENT> --rule-set <rid> --rationale \"...\"")
            print("        撤销：bidpricing options clear --key adjustment_scope")
        if "project_classification_table" in blocked_now:
            print("      · 分类声明未就位 → 它随项目而异，规则书（分类机制）已冻结即可开工")
            print("        落地：填 config/project_classification_table.json —— "
                  "逐张清单声明**缺省角色** + 登记**例外**。")
            print("        注意：不需要逐行填分类（清单内缺省即可竞争项，例外由清单自带列机械命中）；")
            print("              exceptions / external_constants 取 [] 是合法结论，"
                  "但 key 必须存在——缺失会被判「没声明」。")
        other = [b for b in blocked_now
                 if b not in ("adjustment_scope", "project_classification_table")]
        if other:
            print(f"      · 其余未就位项：{', '.join(other)}（无内置提示，见制品说明）")

    return 0 if gate_0a_ok else 1


def cmd_ruleset_select(args) -> int:
    selection = _selection_from_args(args)
    print(json.dumps(selection, ensure_ascii=False, indent=2))
    return 0 if selection["status"] == "PASS" else 1


def cmd_ruleset_selftest(args) -> int:
    result = ruleset_self_test(rho_probe=args.rho_probe)
    print("T00-07 / T00-08 机械判据自检：两套 RuleSet 必须可被指纹区分")
    print(f"  探针 rho_probe = {result['rho_probe']}   delta = {result['delta']}\n")
    for name, chk in result["checks"].items():
        flag = "PASS" if chk["passed"] else "FAIL"
        scope = f"   [作用域 {chk['scope']}]" if "scope" in chk else ""
        print(f"  [{flag}] {name}{scope}")
        print(f"         actual = {chk['actual']!r}")
        if "expected" in chk:
            print(f"         expected = {chk['expected']!r} (tol {chk.get('tolerance')})")
        if "expected_abs_max" in chk:
            print(f"         |actual| <= {chk['expected_abs_max']}")
        if "expected_min" in chk:
            print(f"         |actual| >= {chk['expected_min']}")
        if chk.get("degenerate"):
            print("         [该作用域下判据退化——见遗留项]")
        print(f"         {chk['meaning']}")
    print(f"\n总判定：{'PASS' if result['passed'] else 'FAIL'}")
    for adv in result.get("advisories", []):
        print(f"\n  [遗留项] {adv}")
    return 0 if result["passed"] else 1


def cmd_freeze(args) -> int:
    registry = _load()
    cdir = config_dir()
    targets: list[tuple[str, str]] = []

    if args.all:
        for gate_key in ("gate_0a", "gate_0b"):
            for rec in parse_records(registry, gate_key):
                if rec.is_enum or not rec.artifact_path:
                    continue
                if (cdir / rec.artifact_path).exists():
                    targets.append((gate_key, rec.key))
    elif args.key:
        gate_key = args.gate or "gate_0a"
        targets.append((gate_key, args.key))
    else:
        print("[FATAL] 需指定 --all 或 --key", file=sys.stderr)
        return 2

    frozen, skipped = [], []
    for gate_key, key in targets:
        try:
            rec = freeze_record(registry, gate_key, key, cdir)
            frozen.append((gate_key, key, rec.hash))
        except ArtifactNotFreezable as exc:
            skipped.append((gate_key, key, str(exc)))
        except (FileNotFoundError, KeyError) as exc:
            skipped.append((gate_key, key, str(exc)))

    save_registry(_registry_path(), registry)

    for gate_key, key, digest in frozen:
        print(f"[FROZEN]        {gate_key}.{key:<32} {digest}")
    for gate_key, key, why in skipped:
        print(f"[NOT-FREEZABLE] {gate_key}.{key:<32} {why}", file=sys.stderr)

    print(f"\n冻结 {len(frozen)} 项，跳过 {len(skipped)} 项。")
    return 0 if not skipped else 1


def cmd_options(args) -> int:
    path = _selection_path()
    action = args.action

    if action == "list":
        return _options_list(path, args)
    if action == "set":
        return _options_set(path, args)
    if action == "clear":
        return _options_clear(path, args)
    print(f"[FATAL] 未知动作：{action}", file=sys.stderr)
    return 2


def cmd_scope_impact(args) -> int:
    result = compare_scopes(
        args.q0, args.q1, args.p0,
        rho_plus=args.rho_plus, rho_minus=args.rho_minus,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("=" * 78)
    print("选择项影响度量 —— GB/T 50500-2024 §8.9 作用域分叉（规则层）")
    print("=" * 78)
    inp = result["inputs"]
    print(f"输入：q0={inp['q0']}  q1={inp['q1']}  p0={inp['p0']}  "
          f"ρ⁺={inp['rho_plus']}  ρ⁻={inp['rho_minus']}")
    print(f"工程量比值 r = {result['quantity_ratio']:.6g}    分档 = {result['branch']}\n")
    rs = result["gb_t_50500_2024"]
    print(f"  FULL    结算金额 = {rs['FULL']:.6f}")
    print(f"  SEGMENT 结算金额 = {rs['SEGMENT']:.6f}")
    print(f"  差额（SEGMENT − FULL） = {rs['difference_segment_minus_full']:.6f}"
          + (f"   （{rs['divergence_pct']:.4f}%）" if rs["divergence_pct"] is not None else ""))
    print(f"  2013 参照值 = {result['gb_50500_2013_reference']:.6f}"
          f"    SEGMENT 与 2013 同值：{'是' if result['segment_equals_2013'] else '否'}")
    print(f"  本项上两作用域是否等价：{'是' if result['scope_equivalent_here'] else '否'}\n")
    for note in result["notes"]:
        print(f"  · {note}")
    print(f"\n  边界说明：{result['rules_to_optimizer_gap']}")
    print("=" * 78)
    return 0


def cmd_status(args) -> int:
    """状态快照 —— 跨会话交接的单一入口。

    刻意不做任何「读一份写好的进度文档」的动作：本命令的每一条都现场从
    权威源采集（git / 注册表 / 现场跑测试 / 任务板证据核对）。若本命令失败，
    说明权威源有问题，而不是「文档没更新」。
    """
    snap = collect_status(contract_date=args.contract_date)

    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2, default=str))
        return 0

    if not args.write:
        # 读路径：评估磁盘上已存在文档的新鲜度，过期则醒目拦截（机器判据）。
        from ..paths import docs_dir as _docs_dir
        from ..status import STATE_FILE, check_freshness
        state_p = _docs_dir() / STATE_FILE
        fresh = check_freshness(state_path=state_p)
        if not fresh["fresh"]:
            print(f"[H-005] 状态快照已过期：{len(fresh['stale_files'])} 个权威源比生成时点更新。")
            print(f"[H-005] 请运行 `python -m bidpricing.cli status --write` 重新生成后再交接。")
            print()
        text = render_status(snap, state_path=state_p)
    else:
        text = render_status(snap)

    if args.write:
        path = write_state(args.contract_date)
        print(f"已写入状态快照：{path}")
        print()
    if args.write and not args.print_md:
        # 写盘模式下默认只打印提纲，避免刷屏
        tests = snap["tests"]
        git = snap["git"]
        print(f"  提交      {git['head']}  ({git.get('subject', '')})")
        print(f"  闸门      Gate 0a={snap['gates'].get('gate_0a')}  "
              f"Gate 0b={snap['gates'].get('gate_0b')}  "
              f"Phase 0 输入门={snap['gates'].get('phase_0_input_gate')}")
        print(f"  测试      {tests['ran']} 项，{'通过' if tests['ok'] else '未通过'}")
        print(f"  遗留项    {len(snap['advisories'])} 条")
        print(f"  下一步    {', '.join(n['id'] for n in snap['next_steps']) or '（无）'}")
        return 0

    print(text)
    return 0


def cmd_identity_check(args) -> int:
    """总价恒等式核验 —— 对真实样本执行可执行判据。

    与 ``gate-check`` 的分工：``gate-check`` 判「能不能开工」，
    本命令判「算出来的总价链条是否与真实数据一致」。前者是流程闸门，
    后者是**数值判据**，二者都不依赖人工记忆。
    """
    fx = load_pair_fixture(args.fixture)
    side = args.side
    dec = decompose(
        totals_from_fixture(fx, side),
        *rates_from_fixture(fx, side),
    )
    stated = stated_from_fixture(fx, side)

    items = []
    # 输入保真：逐项明细求和 == 表列小计（只对报价侧有意义——限价侧无合价列）
    if side == "bid":
        known = [i for i in fx["items"] if i.get("amount_bid")]
        items.append(
            check_component_sum(
                {i["item_id"]: i["amount_bid"] for i in known},
                float(fx["summary_table_04"]["bid"]["分部分项工程费"]),
                "分部分项工程费（逐项明细 vs 表-04）",
            )
        )
    items += check_identity(
        dec, stated["总价"], stated["增值税"], stated["税金"]
    )

    if args.json:
        print(json.dumps(
            {"decomposition": dec.to_dict(),
             "checks": [i.to_dict() for i in items]},
            ensure_ascii=False, indent=2, default=str,
        ))
        return 0 if all(i.status is not Status.FAIL for i in items) else 1

    print("=" * 78)
    print(f"总价恒等式核验 ｜ {fx['fixture_id']} ｜ 口径：{'投标报价' if side == 'bid' else '招标限价'}")
    print("=" * 78)
    d = dec.to_dict()
    for k in ("分部分项工程费", "措施项目费", "其他项目费", "规费", "甲供材料费"):
        print(f"  {k:<12} {d[k]:>18,.2f}")
    print(f"  {'-' * 32}")
    print(f"  {'计税基数':<12} {d['计税基数']:>18,.2f}")
    print(f"  {'增值税':<12} {d['增值税']:>18,.2f}   （{d['增值税率']:.0%}）")
    print(f"  {'附加税':<12} {d['附加税']:>18,.2f}   （{d['附加税率']:.0%}）")
    print(f"  {'税金合计':<12} {d['税金合计']:>18,.2f}")
    print(f"  {'总价':<12} {d['总价']:>18,.2f}")
    print()
    for i in items:
        tag = {Status.PASS: "  PASS", Status.WARN: "  WARN",
               Status.FAIL: "  FAIL", Status.BLOCKED: "BLOCKED"}[i.status]
        print(f"[{tag}] {i.item}")
        print(f"           {i.reason}")
    print()
    ok = all(i.status is not Status.FAIL for i in items)
    print("结论：恒等式闭合。" if ok else "结论：恒等式**不闭合** —— 这不是精度问题，"
          "须先确认各分项是否同源于同一项目的同一单位工程。")
    return 0 if ok else 1


def cmd_audit_verify(args) -> int:
    """O19（治理审查 P3）：独立复核历史审计链文件。

    ``verify_audit_chain`` 已实现完整校验（previous_hash + event_hash +
    ISO 8601 时序 + operator 一致 + 外置锚点），但此前没有 CLI 入口，
    外部审计员无法脱离业务进程独立复核。本命令：
    * 读入审计链 JSON（事件数组，或含 ``events`` 键的对象）；
    * 逐条跑 ``verify_audit_chain``；
    * 可选 ``--anchor`` 外置链尾哈希——失配即判「链被整体重写」。
    校验通过退出 0，失败退出 1（与既有业务失败口令一致）。
    """
    from pathlib import Path as _P

    from ..audit_log import verify_audit_chain

    in_path = _P(args.input)
    if not in_path.exists():
        print(f"■ 审计链文件不存在：{in_path}")
        return 2
    try:
        doc = json.loads(in_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"■ 输入不是合法 JSON：{exc}")
        return 2
    events = doc.get("events") if isinstance(doc, dict) and "events" in doc else doc
    if not isinstance(events, list) or not events:
        print("■ 审计链须为事件数组或含 events 键的对象")
        return 2
    ok, errors = verify_audit_chain(events, anchor_hash=args.anchor)
    if args.json:
        print(json.dumps({"ok": ok, "errors": list(errors), "events": len(events)},
                         ensure_ascii=False, indent=2))
        return 0 if ok else 1
    if ok:
        print(f"[PASS] 审计链完整（{len(events)} 事件）"
              + (f"，外置锚点一致" if args.anchor else ""))
        return 0
    print(f"[BLOCKED] 审计链校验失败（{len(events)} 事件）：")
    for err in errors:
        print(f"   · {err}")
    return 1
