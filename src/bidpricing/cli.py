"""命令行入口。

用法（在仓库根目录下）::

    PYTHONPATH=src python -m bidpricing.cli gate-check
    PYTHONPATH=src python -m bidpricing.cli ruleset-select --contract-date 2026-03-01
    PYTHONPATH=src python -m bidpricing.cli ruleset-selftest
    PYTHONPATH=src python -m bidpricing.cli freeze --all
    PYTHONPATH=src python -m bidpricing.cli freeze --gate gate_0a --key field_schema_version

    # 选择项（adjustment_scope 等）
    PYTHONPATH=src python -m bidpricing.cli options list
    PYTHONPATH=src python -m bidpricing.cli options set \\
        --key adjustment_scope --value FULL --rule-set GB/T50500-2024 \\
        --rationale "招标文件 §12.3 未约定分段，按 2024 字面口径"
    PYTHONPATH=src python -m bidpricing.cli options clear --key adjustment_scope
    PYTHONPATH=src python -m bidpricing.cli scope-impact --q0 100 --q1 130 --p0 10
    PYTHONPATH=src python -m bidpricing.cli contract-check
"""

from __future__ import annotations

import argparse
import json
import sys

from .artifact import (
    ArtifactNotFreezable,
    freeze_record,
    load_registry,
    parse_records,
    save_registry,
)
from .contracts.consistency import check_contract_consistency
from .contracts.scope_impact import compare_scopes
from .contracts.selector import ruleset_self_test, select_rule_set
from .gates.gate0 import evaluate_gate_0
from .io.boq import parse_listing, write_report
from .io.xlsx import XlsxError
from .identity import (
    check_component_sum,
    check_identity,
    decompose,
    load_pair_fixture,
    rates_from_fixture,
    stated_from_fixture,
    totals_from_fixture,
)
from .paths import GATE0_REGISTRY, PROJECT_SELECTION, config_dir, repo_root
from .selection_options import (
    SELECTABLE_OPTIONS,
    clear_option,
    read_option_entry,
    resolve_option,
    write_option,
)
from .status import collect as collect_status
from .status import render as render_status
from .status import write_state
from .validation.profit_bridge import check_profit_bridge
from .states import Status, aggregate
from .total_price import (
    check_partition,
    check_tax_base_document,
    check_tax_response,
    load_fixture,
    partition_from_fixture,
    tax_basis_text_from_fixture,
)

_STATUS_MARK = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL", "BLOCKED": "BLOCKED"}

RULE_SET_CHOICES = ("GB/T50500-2024", "GB50500-2013")


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


# --------------------------------------------------------------- gate-check


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


# ----------------------------------------------------------- ruleset-select


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


# ------------------------------------------------------------------- freeze


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


# ------------------------------------------------------------------ options


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


# ------------------------------------------------------------ scope-impact


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


# ------------------------------------------------------------------ status


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


# --------------------------------------------------------------------- main


def cmd_total_price_check(args) -> int:
    """T00-06B 总价分解核验 —— 划分是否闭合、联动函数是否往返一致。

    与 ``identity-check`` 的关系：``identity-check`` 判「总价恒等式闭不闭合」，
    本命令在它之上判**总价怎么被划分成可竞争/固定/税金三块**，以及 C1 约束
    右端 ``P_competitive`` 的取值。二者共用同一套舍入与容差口径。
    """
    fx = load_fixture(args.fixture)
    side = args.side
    part = partition_from_fixture(fx, side)
    items = check_partition(part, part.declared_total)
    items += check_tax_response(part)
    items.append(check_tax_base_document(tax_basis_text_from_fixture(fx, side)))

    if args.json:
        print(json.dumps(
            {"partition": part.to_dict(),
             "checks": [i.to_dict() for i in items]},
            ensure_ascii=False, indent=2, default=str,
        ))
        return 0

    d = part.to_dict()
    print("=" * 78)
    print(f"总价分解核验（T00-06B）｜ {fx['fixture_id']} ｜ 口径："
          f"{'投标报价' if side == 'bid' else '招标限价'}")
    print("=" * 78)
    print(f"  {'可竞争 COMPETITIVE':<22} {d['competitive']:>18,.2f}")
    print(f"  {'固定 FIXED_PRETAX':<22} {d['fixed_pretax']:>18,.2f}")
    print(f"  {'税金 TAX':<22} {d['tax']:>18,.2f}")
    print(f"  {'-' * 42}")
    print(f"  {'总价':<22} {d['total']:>18,.2f}")
    print(f"  其中：暂列金额（披露）      {d['provisional_disclosed']:>18,.2f}"
          "   ← 已是父项内部的一笔，不另计")
    print(f"  计税基数 = 税前合计 − 甲供材  {d['tax_base']:>17,.2f}")
    print()
    for i in items:
        tag = {Status.PASS: "  PASS", Status.WARN: "  WARN",
               Status.FAIL: "  FAIL", Status.BLOCKED: "BLOCKED"}[i.status]
        print(f"[{tag}] {i.item}")
        print(f"           {i.reason}")
    print()
    bad = [i for i in items if i.status in (Status.FAIL, Status.BLOCKED)]
    print("结论：划分闭合、联动往返一致。" if not bad
          else f"结论：{len(bad)} 条判据不通过——先查分项是否有重复计或漏计。")
    return 0 if not bad else 1


def cmd_profit_check(args) -> int:
    """T00-12 利润口径桥接表核验 —— 目标口径、同源同值、亏损政策。

    与 ``total-price-check`` 的分工：后者判「总价怎么分」，本命令判
    「分完之后算的是哪个口径的利润」。两者共用同一份真实样本划分。
    """
    from datetime import datetime as _dt, timezone as _tz

    part = None
    if args.with_fixture:
        fx = load_fixture(args.fixture)
        part = partition_from_fixture(fx, args.side)

    if args.freeze and not args.actor:
        print("■ 拒绝冻结：必须用 --actor 如实标明执行人（业务声明=user，"
              "代操作=agent(...)）。不写等于把责任归属留空")
        return 1
    if args.freeze:
        spec_path = config_dir() / "profit_bridge_spec.json"
        if not spec_path.exists():
            print(f"■ 桥接表缺失：{spec_path}")
            return 1
        probe = check_profit_bridge(config_dir(), partition=part)
        if probe.blocking:
            print("■ 拒绝冻结：尚有阻断项 " +
                  "、".join(r.rule_id for r in probe.blocking) +
                  "——带病冻结等于把未定态伪装成已定态")
            return 1
        spec_doc = json.loads(spec_path.read_text(encoding="utf-8"))
        spec_doc["frozen_at"] = _dt.now(_tz.utc).isoformat()
        spec_doc["frozen_by"] = args.actor
        spec_path.write_text(
            json.dumps(spec_doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f" ✓ 已冻结：frozen_at = {spec_doc['frozen_at']}"
              "（注意：制品内容已变，须重新 freeze --all 更新登记表 hash）")

    rep = check_profit_bridge(config_dir(), partition=part)
    spec = _read_config("profit_bridge_spec.json") or {}

    if args.json:
        print(json.dumps(
            {"objective": spec.get("objective"),
             "levels": spec.get("levels"),
             "checks": rep.to_dict()},
            ensure_ascii=False, indent=2, default=str,
        ))
        return 0 if not rep.blocking else 1

    print("=" * 78)
    print("利润口径桥接表核验（T00-12）")
    print("=" * 78)
    print(f"  {'层级':<22} {'kind':<26} {'进目标':<6}")
    print(f"  {'-' * 60}")
    for lv in spec.get("levels") or []:
        mark = "← 是" if lv.get("enters_objective") else ""
        print(f"  {lv['key']:<22} {lv['kind']:<26} {mark}")
    obj = spec.get("objective") or {}
    print(f"\n  目标口径：{obj.get('level')}（{obj.get('sense')}，"
          f"{spec.get('tax_caliber_of_objective')}）")
    loss = (spec.get("single_item_loss_policy") or {}).get("declared")
    print(f"  单项亏损：{loss}")
    print()
    for r in rep.results:
        tag = {"PASS": "  PASS", "WARN": "  WARN", "FAIL": "  FAIL",
               "BLOCKED": "BLOCKED", "INFO": "  ℹINFO", "SKIP": "   SKIP",
               }.get(r.status, r.status)
        print(f"[{tag}] {r.rule_id}")
        print(f"           {r.detail}")
    print()
    print("结论：目标口径明确、与总价分解同源同值。" if not rep.blocking
          else f"结论：{len(rep.blocking)} 条判据阻断——目标函数口径未定，"
               "WP4 不得开工。")
    return 0 if not rep.blocking else 1


def _read_config(fname: str) -> dict | None:
    p = config_dir() / fname
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bidpricing",
        description="投标报价利润最大化测算模型 —— 实施路线 v3.2.1 执行工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_selection_args(p):
        p.add_argument("--tender-document-date", default=None, help="招标文件发布日期 YYYY-MM-DD")
        p.add_argument("--contract-date", default=None, help="合同签订日期 YYYY-MM-DD")
        p.add_argument("--standard-version-declared", default=None, help="招标文件/合同声明的规范版本")
        p.add_argument("--region", default=None)
        p.add_argument("--project-type", default=None)
        p.add_argument("--funding-type", default=None)
        p.add_argument("--tender-document-override", default=None)
        p.add_argument("--contract-override", default=None)
        p.add_argument("--adjustment-scope", default=None, choices=["FULL", "SEGMENT"],
                       help="选择项 adjustment_scope 的临时落值（优先级高于落值文件）")
        p.add_argument("--selection-file", default=None,
                       help=f"选择项落值文件，默认 config/{PROJECT_SELECTION}")

    p_gate = sub.add_parser("gate-check", help="执行 Gate 0 全部机械判据")
    add_selection_args(p_gate)
    p_gate.add_argument("--gate-0b-passed-at", default=None, help="Gate 0b 通过时间戳（ISO 8601）")
    p_gate.add_argument("--phase1-first-build-at", default=None, help="WP4 Phase 1 首次构建时间戳")
    p_gate.add_argument("--json", action="store_true", help="输出 JSON")
    p_gate.set_defaults(func=cmd_gate_check)

    p_sel = sub.add_parser("ruleset-select", help="执行 T00-08 规则集选择")
    add_selection_args(p_sel)
    p_sel.set_defaults(func=cmd_ruleset_select)

    p_st = sub.add_parser("ruleset-selftest", help="执行 T00-07/T00-08 机械判据自检")
    p_st.add_argument("--rho-probe", type=float, default=0.01)
    p_st.set_defaults(func=cmd_ruleset_selftest)

    p_fz = sub.add_parser("freeze", help="冻结契约制品（写入 version/hash/frozen_at）")
    p_fz.add_argument("--all", action="store_true", help="冻结注册表内全部已存在的制品")
    p_fz.add_argument("--gate", default=None, choices=["gate_0a", "gate_0b"])
    p_fz.add_argument("--key", default=None)
    p_fz.set_defaults(func=cmd_freeze)

    # ------------------------------------------------------------ options
    p_opt = sub.add_parser(
        "options",
        help="查看 / 落值 / 撤销项目级选择项（adjustment_scope 等）",
    )
    p_opt.add_argument("action", choices=["list", "set", "clear"])
    p_opt.add_argument("--key", default=None, help="选择项 key（set/clear 必填）")
    p_opt.add_argument("--value", default=None, help="取值（set 必填）")
    p_opt.add_argument("--rule-set", default=None, choices=list(RULE_SET_CHOICES),
                       help="规则集——合法取值集合随规则集而变，故必须显式给出")
    p_opt.add_argument("--rationale", default=None, help="选择依据（计入审计快照）")
    p_opt.add_argument("--actor", default="operator", help="落值人标识")
    p_opt.add_argument("--json", action="store_true", help="输出 JSON（list）")
    p_opt.set_defaults(func=cmd_options)

    # ------------------------------------------------------- scope-impact
    p_si = sub.add_parser(
        "scope-impact",
        help="度量 adjustment_scope 两个取值在**规则层**的结算分叉",
    )
    p_si.add_argument("--q0", type=float, required=True, help="投标基准工程量")
    p_si.add_argument("--q1", type=float, required=True, help="实施工程量")
    p_si.add_argument("--p0", type=float, required=True, help="投标单价")
    p_si.add_argument("--rho-plus", type=float, default=0.0, help="ρ⁺（默认 0，规范无量化依据）")
    p_si.add_argument("--rho-minus", type=float, default=0.0, help="ρ⁻（默认 0）")
    p_si.add_argument("--json", action="store_true")
    p_si.set_defaults(func=cmd_scope_impact)

    # ------------------------------------------------------------ status
    p_stat = sub.add_parser(
        "status",
        help="生成项目状态快照（全部现场派生，可写入 docs/STATE.md）",
    )
    p_stat.add_argument("--contract-date", default="2026-03-01",
                        help="合同基准日 YYYY-MM-DD（决定规则集选择）")
    p_stat.add_argument("--write", action="store_true",
                        help="写入 docs/STATE.md（跨会话交接用）")
    p_stat.add_argument("--print-md", action="store_true",
                        help="配合 --write 时仍打印完整 Markdown")
    p_stat.add_argument("--json", action="store_true", help="输出 JSON 原始快照")
    p_stat.set_defaults(func=cmd_status)

    # ------------------------------------------------------ identity-check
    p_id = sub.add_parser(
        "identity-check",
        help="总价恒等式核验（对真实样本执行数值判据）",
    )
    p_id.add_argument(
        "--fixture",
        default=str(repo_root() / "tests" / "data" / "xiyong_l_district" / "pair.json"),
        help="限价/报价配对样本 JSON 路径",
    )
    p_id.add_argument("--side", choices=["bid", "cap"], default="bid",
                      help="核验哪一侧：bid=投标报价（默认，数据完整）/ cap=招标限价")
    p_id.add_argument("--json", action="store_true", help="输出 JSON")
    p_id.set_defaults(func=cmd_identity_check)

    # ------------------------------------------------------ total-price-check
    p_tp = sub.add_parser(
        "total-price-check",
        help="T00-06B 总价分解核验（划分闭合 + P_competitive 联动往返）",
    )
    p_tp.add_argument(
        "--fixture",
        default=str(repo_root() / "tests" / "data" / "xiyong_l_district" / "pair.json"),
        help="限价/报价配对样本 JSON 路径",
    )
    p_tp.add_argument("--side", default="bid", choices=("bid", "cap"),
                      help="报价侧(bid) 或限价侧(cap)")
    p_tp.add_argument("--json", action="store_true", help="输出 JSON")
    p_tp.set_defaults(func=cmd_total_price_check)

    # ------------------------------------------------------ profit-check
    p_pb = sub.add_parser(
        "profit-check",
        help="T00-12 利润口径桥接表核验（目标口径 / 同源同值 / 亏损政策）",
    )
    p_pb.add_argument(
        "--fixture",
        default=str(repo_root() / "tests" / "data" / "xiyong_l_district" / "pair.json"),
        help="用于 PB-03 数值对账的配对样本",
    )
    p_pb.add_argument("--side", default="bid", choices=("bid", "cap"))
    p_pb.add_argument("--no-fixture", dest="with_fixture", action="store_false",
                      default=True, help="跳过 PB-03 数值对账")
    p_pb.add_argument("--json", action="store_true")
    p_pb.add_argument("--freeze", action="store_true",
                      help="写入 frozen_at（须先解除全部阻断项）")
    p_pb.add_argument("--actor", default=None,
                      help="冻结执行人标识，**必填且如实填写**："
                           "业务声明须为 user（ADR-0007）；机制冻结若由 Agent "
                           "代操作，须写明 agent(...)，不得冒充用户")
    p_pb.set_defaults(func=cmd_profit_check)

    # ------------------------------------------------------ contract-check
    p_cc = sub.add_parser(
        "contract-check",
        help="跨制品契约一致性判据（拦截「同一规则在两份制品里说法不同」）",
    )
    p_cc.add_argument("--json", action="store_true", help="输出 JSON")
    p_cc.set_defaults(func=cmd_contract_check)

    # ------------------------------------------------------------ parse-boq
    p_pb = sub.add_parser(
        "parse-boq",
        help="T01-00B：解析清单 xlsx 为规范行（解析日志 + 字段映射报告 + 失败样本清单）",
    )
    p_pb.add_argument("xlsx", help="清单文件路径（限价/报价/成本清单同构）")
    p_pb.add_argument("--project-id", required=True,
                      help="项目编号（主键第一段；身份命名空间，不携带计价规则）")
    p_pb.add_argument("--out-dir", default=None,
                      help="三项产出的落盘目录（默认 docs/parsed/<文件名>）")
    p_pb.set_defaults(func=cmd_parse_boq)

    # ------------------------------------------------------------ clean-boq
    p_cb = sub.add_parser(
        "clean-boq",
        help="T01-03：解析 + 规范化清洗 → 类型化 canonical 行（含空值语义与异常清单）",
    )
    p_cb.add_argument("xlsx", help="清单文件路径（限价/报价/成本清单同构）")
    p_cb.add_argument("--project-id", required=True,
                      help="项目编号（主键第一段）")
    p_cb.add_argument("--side", required=True, choices=["cap", "cost"],
                      help="清单侧：cap=限价清单（q0/cap），cost=成本清单（q1_point/c_i）")
    p_cb.add_argument("--attribution", default=None,
                      choices=["DRAWING_DIFF", "CHANGE_ORDER", "BOTH", "UNKNOWN"],
                      help="q0≠q1 的变化归因标签（OI-01；默认 UNKNOWN）")
    p_cb.add_argument("--out-dir", default=None,
                      help="产出落盘目录（默认 docs/cleaned/<文件名>/<side>）")
    p_cb.set_defaults(func=cmd_clean_boq)

    # ------------------------------------------------------------ match-boq
    p_mb = sub.add_parser(
        "match-boq",
        help="T01-04：限价侧 + 成本侧 → master 并集融合 + 覆盖率 + 异常清单",
    )
    p_mb.add_argument("--cap-xlsx", required=True, help="限价清单 xlsx")
    p_mb.add_argument("--cost-xlsx", required=True, help="成本清单 xlsx")
    p_mb.add_argument("--project-id", required=True,
                      help="项目编号（主键第一段）")
    p_mb.add_argument("--attribution", default=None,
                      choices=["DRAWING_DIFF", "CHANGE_ORDER", "BOTH", "UNKNOWN"],
                      help="q0≠q1 的变化归因标签（OI-01；默认 UNKNOWN）")
    p_mb.add_argument("--out-dir", default=None,
                      help="产出落盘目录（默认 docs/matched/<project_id>）")
    p_mb.set_defaults(func=cmd_match_boq)

    # -------------------------------------------------------- import-register
    p_ir = sub.add_parser(
        "import-register",
        help="T01-05：登记一次源文件导入（指纹 + 逐 sheet 哈希，追加式）",
    )
    p_ir.add_argument("xlsx", help="源清单 xlsx")
    p_ir.add_argument("--project-id", required=True, help="项目编号")
    p_ir.add_argument("--side", required=True, choices=["cap", "cost"],
                      help="清单侧（登记表按 project×side 分文件）")
    p_ir.add_argument("--source-owner", default="UNKNOWN",
                      help="文件来源方（招标人/用户/…）")
    p_ir.add_argument("--version-note", default=None,
                      help="人工版本说明（缺省=内容指纹 sha256[:12]）")
    p_ir.set_defaults(func=cmd_import_register)

    # ---------------------------------------------------------- import-verify
    p_iv = sub.add_parser(
        "import-verify",
        help="T01-05：复算前校验源文件指纹（被替换 → 拒绝复用旧复算结果）",
    )
    p_iv.add_argument("xlsx", help="源清单 xlsx")
    p_iv.add_argument("--project-id", required=True, help="项目编号")
    p_iv.add_argument("--side", required=True, choices=["cap", "cost"],
                      help="清单侧")
    p_iv.set_defaults(func=cmd_import_verify)

    p_vb = sub.add_parser("validate-boq",
                          help="T01-06：D01–D12 数据校验（9 阻断 + 3 告警）")
    p_vb.add_argument("--cap-xlsx", required=True, help="限价清单 xlsx")
    p_vb.add_argument("--cost-xlsx", required=True, help="成本清单 xlsx")
    p_vb.add_argument("--project-id", required=True)
    p_vb.add_argument("--attribution", default=None,
                      help="q1_point 归属标签（DRAWING_DIFF/CHANGE_ORDER/BOTH/UNKNOWN）")
    p_vb.add_argument("--p-star", type=float, default=None, help="报价总价（用户给定）")
    p_vb.add_argument("--p-star-max", type=float, default=None, help="总价限价")
    p_vb.add_argument("--p-star-min", type=float, default=None, help="总价下界（可选）")
    p_vb.add_argument("--basis-json", default=None,
                      help="税口径声明 JSON（cap_tax_scope/cost_tax_scope）")
    p_vb.set_defaults(func=cmd_validate_boq)

    # ---- T00-01 计价规则卡 -----------------------------------------------
    p_pc = sub.add_parser(
        "pricing-card", help="T00-01 计价规则卡：展示口径 / 试算单项 P1")
    p_pc.add_argument("--q0", type=float, default=None,
                      help="招标清单工程量 Q0（试算用）")
    p_pc.add_argument("--q1", type=float, default=None,
                      help="结算预期工程量 Q1（试算用）")
    p_pc.add_argument("--p0", type=float, default=None,
                      help="中标综合单价 P0（试算用）")
    p_pc.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                      help="override：rho_plus/rho_minus/adjustment_scope 等"
                           "（未登记键一律阻断）")
    p_pc.add_argument("--from-match", default=None, metavar="MATCH_REPORT",
                      help="读取 T01-04 匹配报告，统计真实各项的 r 分支分布"
                           "（分支只依赖 r=Q1/Q0，与 P0 无关）")
    p_pc.set_defaults(func=cmd_pricing_card)

    # ---- T00-09 / T00-11 成本口径 ----------------------------------------
    p_cc = sub.add_parser(
        "cost-check", help="T00-09 成本口径证明包 + T00-11 c_i 假设声明书校验")
    p_cc.add_argument("--declare-source", default=None,
                      choices=["COST_DB", "HISTORICAL_SETTLEMENT",
                               "SUPPLIER_QUOTE", "EXPERT_ESTIMATE"],
                      help="声明 c_i 来源并落值（写入假设声明书，需 --actor）")
    p_cc.add_argument("--actor", default=None, help="声明人（与 --declare-source 同用）")
    p_cc.add_argument("--evidence", action="append", default=[],
                      help="来源证据条目（可多次），如 '询价日期=2026-09-10'")
    p_cc.add_argument("--freeze", action="store_true",
                      help="冻结假设声明书（写 frozen_at；须先解除全部阻断项）")
    p_cc.set_defaults(func=cmd_cost_check)

    # ---- T00-10A / T00-10B 结算工程量 q1 -------------------------------
    p_qc = sub.add_parser(
        "qty-check", help="T00-10A/10B 结算工程量 q1 假设声明书校验")
    p_qc.add_argument("--declare-sensitivity", default=None,
                      choices=["RATIO_SCAN", "SCENARIO_SWEEP",
                               "NOT_REQUIRED_JUSTIFIED"],
                      help="声明点值 q1 的敏感性义务并落值（需 --actor）")
    p_qc.add_argument("--actor", default=None,
                      help="声明人（与 --declare-sensitivity 同用）")
    p_qc.add_argument("--freeze", action="store_true",
                      help="冻结 q1 假设声明书（须先解除全部阻断项）")
    p_qc.set_defaults(func=cmd_qty_check)

    # ---- T04-00 Phase 1 精确性条件 -------------------------------------
    p_p1 = sub.add_parser(
        "phase1-check",
        help="T04-00 Phase 1 精确性条件判定 + 反例集复算")
    p_p1.add_argument("--case", default="all",
                      help="只跑指定 case（CE-01…CE-09 / PE-01）；默认 all")
    p_p1.add_argument("--instance", default=None,
                      help="对自定义实例 JSON 跑判定（结构见 "
                           "Phase1Instance.from_dict）")
    p_p1.add_argument("--json", action="store_true", help="输出 JSON")
    p_p1.set_defaults(func=cmd_phase1_check)

    # ---- T04-01 Phase 1 解析解 ------------------------------------------
    p_p1s = sub.add_parser(
        "phase1-solve",
        help="T04-01 Phase 1 解析解（排序+二分+贪心定容；输出 λ 与层归属）")
    p_p1s.add_argument("--instance", default=None,
                       help="对自定义实例 JSON 求解（结构见 Phase1Instance.from_dict）")
    p_p1s.add_argument("--probe", default="free-cap", choices=("free-cap", "simple"),
                       help="无 --instance 时用哪个内置探针：free-cap（含不限价项与"
                            "平台）或 simple（上界全有限、λ 内点唯一）")
    p_p1s.add_argument("--floor-json", default=None,
                       help="显式 floor_i 表 JSON：{item_id: 值}。不给则自动向 "
                            "T03-02 派生量层索取（与 verify-solution 共用同一处解析）")
    p_p1s.add_argument("--json", action="store_true", help="输出 JSON")
    p_p1s.set_defaults(func=cmd_phase1_solve)

    # ---- T03-04 约束判定器 ----------------------------------------------
    p_cj = sub.add_parser(
        "constraint-check",
        help="T03-04 约束判定器：对候选报价向量逐条判定 C1–C13（六元组）")
    p_cj.add_argument("--instance", default=None,
                      help="JSON 文件：{'instance': {...}, 'p': {...}, 'z': {...},"
                           " 'Z': ..., 以及 N_max/d_max/Z_min/pi_target/R_min/"
                           "sigma_max/kappa_max/front_rho}。缺 instance 键时整个"
                           "文档视为实例，p 取 Phase 1 解析解")
    p_cj.add_argument("--probe", default="free-cap", choices=("free-cap", "simple"),
                      help="无 --instance 时用哪个内置探针")
    p_cj.add_argument("--floor-json", default=None,
                      help="显式 floor_i 表 JSON：{item_id: 值}（缺省自动向 "
                           "T03-02 派生量层索取）")
    p_cj.add_argument("--json", action="store_true", help="输出 JSON")
    p_cj.set_defaults(func=cmd_constraint_check)

    # ---- T03-03 Phase 0 预检与可行性证书 ---------------------------------
    p_pc = sub.add_parser(
        "precheck",
        help="T03-03 Phase 0 预检：可行性证书（P_min/P_max/P*_var/P*_eff/ΔP）"
             " + PC-01..PC-08 判定；越界判 INFEASIBLE 且不进求解器")
    p_pc.add_argument("--instance", default=None,
                      help="JSON 文件：{'instance': {...}, 'rule_set_id': ...,"
                           " 'contract_type': ..., 'pi_target': ..., "
                           "'alpha_cap': ..., 'fixed_pretax': ..., "
                           "'vat_rate': ..., 'surtax_rate': ..., "
                           "'supplied_material': ..., 'env_tax': ...}")
    p_pc.add_argument("--probe", default="simple", choices=("free-cap", "simple"),
                      help="无 --instance 时用哪个内置探针（默认 simple：全项"
                           "有界、全链可 PASS；free-cap 演示 SKIP 与声明矛盾）")
    p_pc.add_argument("--json", action="store_true", help="输出 JSON")
    p_pc.set_defaults(func=cmd_precheck)

    # ---- T03-06 不可行诊断 ------------------------------------------------
    p_dg = sub.add_parser(
        "diagnose",
        help="T03-06 不可行诊断：结构冲突（Pass A）+ 删除过滤器冲突集"
             "（Pass B）+ §6.3 建议动作；三态 INFEASIBLE/UNKNOWN/BLOCKED 分列")
    p_dg.add_argument("--instance", default=None,
                      help="JSON 文件：{'instance': {...}, 'floor': {...}}")
    p_dg.add_argument("--probe", default="simple", choices=("free-cap", "simple"),
                      help="无 --instance 时用哪个内置探针")
    p_dg.add_argument("--oracle", default="phase1",
                      choices=("phase1", "milp", "chain"),
                      help="预言机：phase1=解析侧内置（T03-06）；milp=编译链"
                           "（T04-02E，零依赖环境自动退 UNKNOWN）；"
                           "chain=phase1 优先、MILP 兜底（首个非 UNKNOWN 胜出）")
    p_dg.add_argument("--json", action="store_true", help="输出 JSON")
    p_dg.set_defaults(func=cmd_diagnose)

    # ---- T04-07：MILP 独立验收协议 --------------------------------
    p_ma = sub.add_parser(
        "milp-check",
        help="MILP 独立验收协议（T04-07）——这次求解够不够格被当作「已证最优」",
        description=(
            "按 config/milp_acceptance_spec.json 验收一次求解：六字段"
            "（status / integer_feasible / objective_gap / best_bound /"
            " time_limit / incumbent）逐项核验，输出「最优性已证 / 未证 / 不可判」。"
            "★ 求解器自报 Optimal 不是验收结论；never_upgrade；禁 KKT 证 MILP。"
        ),
    )
    p_ma.add_argument(
        "--form", choices=("LP", "MILP", "both"), default="both",
        help="要验收的模型形态（默认 both：LP 应判 SKIP、MILP 才适用）",
    )
    p_ma.add_argument(
        "--time-limit", type=float, default=30.0,
        help="求解时限（秒）。未声明时限 ⇒ MA-07 判 BLOCKED（无法区分算完与被中断）",
    )
    p_ma.add_argument("--json", action="store_true", help="输出 JSON")
    p_ma.set_defaults(func=cmd_milp_check)

    # ---- T04-08 独立参考实现 --------------------------------------------
    p_ref = sub.add_parser(
        "ref-check",
        help="T04-08 独立参考实现（第二条路径重算 R_i/残差/Z + 三层隔离证明）")
    p_ref.add_argument("--instance", default=None,
                       help="对自定义实例 JSON 重算（结构见 Phase1Instance.from_dict）")
    p_ref.add_argument("--probe", default="free-cap", choices=("free-cap", "simple"),
                       help="无 --instance 时用哪个内置探针")
    p_ref.add_argument("--p-json", default=None,
                       help="显式报价向量 JSON：{item_id: p}。不给则用 T04-01 "
                            "解析解（仅作「给参考层喂一组 p」的用途）")
    p_ref.add_argument("--z-solver", type=float, default=None,
                       help="对照侧的 Z_solver（不给则用独立裁判 check_solution 的 Z）")
    p_ref.add_argument("--json", action="store_true", help="输出 JSON")
    p_ref.set_defaults(func=cmd_ref_check)

    p_cc = sub.add_parser(
        "compile-check",
        help="T04-02B 约束编译判定（Formulation → CompiledModel 的保真性）")
    p_cc.add_argument("--instance", default=None,
                      help="对自定义实例 JSON 跑判定")
    p_cc.add_argument("--json", action="store_true",
                      help="输出完整模型（含稀疏行与化简台账），供 T04-02C 消费")
    # 求解层入参（不属实例结构，须单独给）。探针分支用合成值；--instance 分支
    # 缺省为 None ⇒ 对应占位行 NOT_COMPILED ⇒ CC-05 BLOCKED（ADR-0013）。
    p_cc.add_argument("--n-max", type=float, default=None,
                      help="C7 亏损项数上限 N_max（缺 ⇒ C7 汇总行不编译）")
    p_cc.add_argument("--theta", type=float, default=None,
                      help="C6 亏损缺口上限 θ（×P*）")
    p_cc.add_argument("--d-max", type=float, default=None,
                      help="C8 地板下浮上限 d_max")
    p_cc.add_argument("--z-min", type=float, default=None,
                      help="C9a 盈利门槛 Z_min")
    p_cc.add_argument("--pi-target", type=float, default=None,
                      help="C9b 目标利润率 π")
    p_cc.add_argument("--tf-terms", default=None,
                      help="C10 的 T_front 三元组 JSON 文件：{item_id: [rho, q0, c]}")
    p_cc.set_defaults(func=cmd_compile_check)


    # ------------------------------------------------------- formulate-check
    p_fm = sub.add_parser(
        "formulate-check",
        help="T04-02A LP 形式化（变量/目标/约束映射 + 制品↔实现双向锁定）")
    p_fm.add_argument("--instance", default=None,
                      help="Phase 1 实例 JSON；省略则用内置探针实例")
    p_fm.add_argument("--json", action="store_true", help="输出 JSON")
    p_fm.set_defaults(func=cmd_formulate_check)

    # ------------------------------------------------------- backend-check
    p_bk = sub.add_parser(
        "backend-check",
        help="T04-02C 求解后端适配（BB-01..BB-09 + CC-09 复跑）")
    p_bk.add_argument("--instance", default=None,
                      help="对自定义实例 JSON 跑判定")
    p_bk.add_argument("--prefer", default=None,
                      help="临时指定后端条目（不写制品，用于替换性检验）")
    p_bk.add_argument("--json", action="store_true", help="输出 JSON")
    p_bk.set_defaults(func=cmd_backend_check)

    # ------------------------------------------------------- verify-solution
    p_vs = sub.add_parser(
        "verify-solution",
        help="T04-02D 解校验器（SV-01..SV-13：可行性/目标值/上下界/层归属）")
    p_vs.add_argument("--instance", default=None,
                      help="对自定义实例 JSON 跑复核；省略则用内置探针实例")
    p_vs.add_argument("--prefer", default=None,
                      help="临时指定后端条目（求解步用）")
    p_vs.add_argument("--reference", type=float, default=None,
                      help="独立参考实现给出的 Z_ref（owner = T04-08）；不给则 SV-13 判 BLOCKED")
    p_vs.add_argument("--floor-json", default=None,
                      help="显式指定 floor_i 表 JSON：{item_id: 值}。"
                           "**不给**时本命令自动向 T03-02 派生量层索取"
                           "（唯一生产者）；两者都拿不到才判 BLOCKED，"
                           "且不得用 L_i 或 c_i 冒充")
    p_vs.add_argument("--json", action="store_true", help="输出 JSON")
    p_vs.set_defaults(func=cmd_verify_solution)

    # --------------------------------------------------------- derive-check
    p_dq = sub.add_parser(
        "derive-check",
        help="T03-02 派生量计算（DQ-01..DQ-10：L/U/floor/r_eff 与地板口径）")
    p_dq.add_argument("--instance", default=None,
                      help="对自定义实例 JSON 跑判定；省略则用内置探针实例")
    p_dq.add_argument("--mu", type=float, default=None,
                      help="允许亏损深度 μ。**不给 = 未声明** ⇒ floor 判 BLOCKED"
                           "（μ=0 是合法取值，与「未声明」不是一回事）")
    p_dq.add_argument("--loss-acceptance", default=None,
                      choices=("ACCEPT", "DECLINE"),
                      help="覆盖项目落值；不给则读 project_selection.json")
    p_dq.add_argument("--unbalanced-json", default=None,
                      help="不平衡报价条款块 JSON：{enabled, reference, tol_lo}")
    p_dq.add_argument("--no-unbalanced-clause", action="store_true",
                      help='等价于 --unbalanced-json \'{"enabled": false}\''
                           "（已核查：本项目无该条款）")
    p_dq.add_argument("--json", action="store_true", help="输出 JSON")
    p_dq.set_defaults(func=cmd_derive_check)

    return parser


def _print_exactness(verdict, title: str) -> None:
    from .solver.exactness import IMPLEMENTABILITY_IDS

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

    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .solver.formulation import (
        build_formulation,
        check_formulation,
        load_formulation_spec,
        probe_instance,
    )
    from .solver.instance import Phase1Instance

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
        path = Path(args.instance)
        if not path.exists():
            print(f"■ 实例文件不存在：{path}")
            return 1
        base = Phase1Instance.from_dict(
            json.loads(path.read_text(encoding="utf-8")), source=str(path)
        )
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
            eps_abs=eps_abs, eps_price=eps_price, resolution=resolution,
            theta=getattr(instance.params, "theta", None),
        )
        rows = check_formulation(
            spec, fm,
            instance=instance, resolved=resolved,
            constraint_schema=schema, precision_profile=prof,
            eps_price=eps_price, eps_abs=eps_abs,
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

    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .solver.cases import load_exactness_spec, run_cases
    from .solver.exactness import condition_status_line, overall_line
    from .solver.exactness import check_exactness
    from .solver.instance import Phase1Instance

    cfg = config_dir()
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    eps_abs = float(prof["eps_abs"]["value"])
    eps_price = float(prof["eps_price"]["value"])
    card = load_pricing_card(cfg)
    resolved = resolve_parameters(card)

    if args.instance:
        inst_path = Path(args.instance)
        if not inst_path.exists():
            print(f"■ 实例文件不存在：{inst_path}")
            return 1
        instance = Phase1Instance.from_dict(
            json.loads(inst_path.read_text(encoding="utf-8")), source=str(inst_path)
        )
        verdict = check_exactness(
            instance, resolved, eps_abs=eps_abs, eps_price=eps_price
        )
        if args.json:
            print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
        else:
            _print_exactness(verdict, str(inst_path))
        return 0 if verdict.exact else 1

    spec = load_exactness_spec(cfg)
    results = run_cases(
        spec, resolved, eps_abs=eps_abs, eps_price=eps_price, only=args.case
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
    from pathlib import Path as _P

    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .solver.instance import Phase1Instance
    from .solver.phase1 import (
        STATUS_PASS,
        load_phase1_spec,
        phase1_probe_instance,
        phase1_report,
        phase1_simple_probe_instance,
    )
    from .solver.verifier import load_verifier_spec, resolve_tolerances

    cfg = config_dir()
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    eps_abs = float(prof["eps_abs"]["value"])
    eps_price = float(prof["eps_price"]["value"])
    resolution = float(prof["rounding"]["resolution"])
    resolved = resolve_parameters(load_pricing_card(cfg))
    spec = load_phase1_spec(cfg)
    vspec = load_verifier_spec(cfg)

    if args.instance:
        path = _P(args.instance)
        if not path.exists():
            print(f"■ 实例文件不存在：{path}")
            return 1
        instance = Phase1Instance.from_dict(
            json.loads(path.read_text(encoding="utf-8")), source=str(path)
        )
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
        eps_abs=eps_abs, eps_price=eps_price, resolution=resolution,
        floor_by_id=floor_by_id, tolerances=tolerances, spec=spec,
    )

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.verdict() == STATUS_PASS else 1

    _print_phase1(report, title)
    return 0 if report.verdict() == STATUS_PASS else 1


def cmd_constraint_check(args) -> int:
    """T03-04 约束判定器 —— 对候选报价向量逐条判定 C1–C13。

    与相邻命令的分工：``verify-solution`` 判「解对不对」（可行性/层归属/
    目标复算）；本命令判「解合不合规」（每约束一个六元组，Gate 2 判定层）。
    输入默认是 Phase 1 解析解（与 phase1-solve 同一来源），也可用
    ``--instance`` 提供任意候选 p（JSON：instance + p/z/Z/限值）。
    """
    from pathlib import Path as _P

    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .solver.constraint_judge import (
        JudgeInputs,
        judge_constraints,
        load_constraint_spec,
    )
    from .solver.instance import Phase1Instance
    from .solver.phase1 import (
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
        path = _P(args.instance)
        if not path.exists():
            print(f"■ 实例文件不存在：{path}")
            return 1
        doc = json.loads(path.read_text(encoding="utf-8"))
        inst_doc = doc.get("instance", doc)
        instance = Phase1Instance.from_dict(inst_doc, source=str(path))
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
    from pathlib import Path as _P

    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .solver.instance import Phase1Instance
    from .solver.phase1 import (
        phase1_probe_instance,
        phase1_simple_probe_instance,
    )
    from .solver.precheck import (
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
        path = _P(args.instance)
        if not path.exists():
            print(f"■ 实例文件不存在：{path}")
            return 1
        doc = json.loads(path.read_text(encoding="utf-8"))
        inst_doc = doc.get("instance", doc)
        instance = Phase1Instance.from_dict(inst_doc, source=str(path))
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


def build_derived_for_cli(cfg, instance, resolved):
    """CLI 便捷：μ=0 / DECLINE / 无不平衡条款的派生量（探针与演示用）。

    真实项目的派生量声明由 Phase 0 输入门传入，不得经由本函数静默补齐。
    """
    from .solver.precheck import build_derived

    return build_derived(instance, resolved)


def cmd_diagnose(args) -> int:
    """T03-06 不可行诊断 —— 结构冲突 + 删除过滤器 + §6.3 建议动作。

    输出四字段：constraint_id / blocking / conflicting_set / suggested_relaxation。
    三态纪律：INFEASIBLE（已证空域）≠ UNKNOWN（预言机不足）≠ BLOCKED（输入缺失）。
    """
    from pathlib import Path as _P

    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .solver.diagnose import (
        chained_oracle,
        diagnose,
        load_diagnosis_spec,
        load_toggleable_ids,
        milp_oracle,
        phase1_oracle,
    )
    from .solver.instance import Phase1Instance
    from .solver.phase1 import (
        phase1_probe_instance,
        phase1_simple_probe_instance,
    )

    cfg = config_dir()
    resolved = resolve_parameters(load_pricing_card(cfg))
    spec = load_diagnosis_spec(cfg)
    toggleable = load_toggleable_ids(cfg)

    if args.instance:
        path = _P(args.instance)
        if not path.exists():
            print(f"■ 实例文件不存在：{path}")
            return 1
        doc = json.loads(path.read_text(encoding="utf-8"))
        instance = Phase1Instance.from_dict(doc.get("instance", doc), source=str(path))
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

    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .refimpl import isolation as _I
    from .refimpl import reference as _R
    from .solver.instance import Phase1Instance, check_solution
    from .solver.phase1 import (
        phase1_probe_instance,
        phase1_simple_probe_instance,
        solve_phase1,
    )
    from .solver.verifier import load_verifier_spec, resolve_tolerances

    cfg = config_dir()
    resolved = resolve_parameters(load_pricing_card(cfg))
    spec = _R.load_reference_spec(cfg)
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    vspec = load_verifier_spec(cfg)

    if args.instance:
        path = _P(args.instance)
        if not path.exists():
            print(f"■ 实例文件不存在：{path}")
            return 1
        instance = Phase1Instance.from_dict(
            json.loads(path.read_text(encoding="utf-8")), source=str(path)
        )
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
            _P(__file__).resolve().parents[0] / "refimpl" / "reference.py",
            _P(__file__).resolve().parents[0] / "refimpl" / "isolation.py",
        ],
        snapshot_obj=snap,
        docs_dir=_P(__file__).resolve().parents[1] / "docs",
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
    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .solver.backend import load_backend_spec, solve_compiled
    from .solver.compiler import compile_model
    from .solver.formulation import build_formulation, probe_instance
    from .solver.milp_acceptance import (
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
            instance, resolved, eps_abs=eps_abs, eps_price=eps_price
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

    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .solver.backend import (
        check_backend,
        load_backend_spec,
        solve_compiled,
    )
    from .solver.compiler import (
        check_compiled,
        compile_model,
        load_compiler_spec,
        pulp_available,
    )
    from .solver.formulation import (
        PROBE_SOLVER_INPUTS,
        build_formulation,
        load_formulation_spec,
        probe_instance,
    )
    from .solver.instance import Phase1Instance
    from .solver.verifier import load_verifier_spec, resolve_tolerances

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
    # 本文件即 src/bidpricing/cli.py ⇒ parents[0] 既是包根也含 solver/compiler.py
    pkg_root = _P(__file__).resolve().parents[0]
    compiler_path = pkg_root / "solver" / "compiler.py"
    if not compiler_path.exists():
        print(f"■ 编译器源码不在预期位置：{compiler_path}")
        return 1
    compiler_source = compiler_path.read_text(encoding="utf-8")

    if args.instance:
        path = _P(args.instance)
        if not path.exists():
            print(f"■ 实例文件不存在：{path}")
            return 1
        base = Phase1Instance.from_dict(
            json.loads(path.read_text(encoding="utf-8")), source=str(path)
        )
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
            eps_abs=eps_abs, eps_price=eps_price, resolution=resolution,
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
    from .derived import STATUS_PASS

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

    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .derived import (
        DerivedError,
        compute_derived,
        inputs_from_project,
        load_derived_spec,
    )
    from .solver.formulation import probe_instance
    from .solver.instance import Phase1Instance

    cfg = config_dir()
    try:
        spec = load_derived_spec(cfg)
    except DerivedError as exc:
        print(f"■ {exc}")
        return 1
    card = load_pricing_card(cfg)
    resolved = resolve_parameters(card)

    if args.instance:
        path = _P(args.instance)
        if not path.exists():
            print(f"■ 实例文件不存在：{path}")
            return 1
        inst = Phase1Instance.from_dict(
            json.loads(path.read_text(encoding="utf-8")), source=str(path)
        )
        title = args.instance
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
        from .refimpl import reference as _R
        from .refimpl import isolation as _I

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
                _P(__file__).resolve().parents[0] / "refimpl" / "reference.py",
                _P(__file__).resolve().parents[0] / "refimpl" / "isolation.py",
            ],
            snapshot_obj=snap,
            docs_dir=_P(__file__).resolve().parents[1] / "docs",
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
        from .derived import (
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


def cmd_verify_solution(args) -> int:
    """T04-02D：**独立复核**一个解（可行性 / 目标值 / 上下界 / 层归属）。

    与 ``backend-check`` 的分工：后者判「后端这条链路**走样**没有」（BB 判据），
    本命令判「这个解**本身**站得住吗」（SV 判据），并产出**逐行 + 逐项**的复核
    报告。二者不互相替代（见 solver_backend_spec 的 T04-02D 交接条目）。

    本命令**不**消费求解决论：它把 ``SolveResult`` 拆成原始量（变量赋值 +
    自报目标值）再交给复核层——这是独立性在接口层的落地。
    """
    from pathlib import Path as _P

    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .solver.backend import load_backend_spec, solve_compiled
    from .solver.compiler import compile_model, load_compiler_spec
    from .solver.formulation import (
        PROBE_SOLVER_INPUTS,
        build_formulation,
        load_formulation_spec,
        probe_instance,
    )
    from .solver.instance import Phase1Instance
    from .solver.verifier import (
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
        path = _P(args.instance)
        if not path.exists():
            print(f"■ 实例文件不存在：{path}")
            return 1
        base = Phase1Instance.from_dict(
            json.loads(path.read_text(encoding="utf-8")), source=str(path)
        )
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

    verifier_source = (_P(__file__).resolve().parents[0]
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
            eps_abs=eps_abs, eps_price=eps_price, resolution=resolution,
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

    from .contracts.pricing_card import load_pricing_card, resolve_parameters
    from .solver.compiler import (
        check_compiled,
        compile_model,
        load_compiler_spec,
        pulp_available,
        to_pulp,
    )
    from .solver.formulation import (
        PROBE_SOLVER_INPUTS,
        build_formulation,
        load_formulation_spec,
        probe_instance,
    )
    from .solver.instance import Phase1Instance

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
    # 本文件即 src/bidpricing/cli.py ⇒ parents[0] = src/bidpricing
    compiler_path = _P(__file__).resolve().parents[0] / "solver" / "compiler.py"
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
        path = _P(args.instance)
        if not path.exists():
            print(f"■ 实例文件不存在：{path}")
            return 1
        base = Phase1Instance.from_dict(
            json.loads(path.read_text(encoding="utf-8")), source=str(path)
        )
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
            eps_abs=eps_abs, eps_price=eps_price, resolution=resolution,
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


def cmd_parse_boq(args) -> int:
    """T01-00B：清单 xlsx → 规范行 + 三项产出。

    解析器只做机械信号命中：命不中的行进失败样本清单并给原因，
    **不猜列、不补数、不静默丢弃**——数值化与清洗属 T01-03，不在此处。
    """
    from pathlib import Path as _P

    out_dir = _P(args.out_dir) if args.out_dir else (
        repo_root() / "docs" / "parsed" / _P(args.xlsx).stem
    )
    try:
        report = parse_listing(args.xlsx, args.project_id)
    except XlsxError as exc:
        print(f"■ 解析失败：{exc}")
        return 1

    print("=" * 78)
    print(f"清单解析：{_P(args.xlsx).name}")
    print("=" * 78)
    print(f" sha256[:12] = {report.source_sha256}   project_id = {args.project_id}")
    for s in report.sheets:
        print(f" · {s['sheet_name']}")
        print(f"     角色 {s['role']} ｜ 单位工程「{s['unit_work']}」｜ {s['state']}")
        mapping = report.column_mapping.get(s["sheet_name"])
        if mapping:
            print("     列映射: " + "  ".join(
                f"{k}←{m['header']}" for k, m in mapping.items()))
    print("-" * 78)
    print(" " + report.summary_line())

    by_kind: dict[str, int] = {}
    for r in report.rows:
        by_kind[r.code_kind] = by_kind.get(r.code_kind, 0) + 1
    if by_kind:
        print(" 编码形态: " + "、".join(f"{k} {v}" for k, v in sorted(by_kind.items()))
              + "（位数不参与合法性判定，UNKNOWN 不阻塞、交人工确认）")

    if report.failures:
        print(f" 失败样本（前 {min(10, len(report.failures))} 条 / 共 "
              f"{len(report.failures)}）:")
        for f in report.failures[:10]:
            print(f"   ■ {f.source_sheet} r{f.source_row}: {f.reason}")
    if report.notes:
        for n in report.notes:
            print(f"   ! {n}")

    paths = write_report(report, out_dir)
    print("-" * 78)
    print(" 三项产出：")
    for k, v in paths.items():
        print(f"   {k:>9}: {v}")
    return 0


def cmd_clean_boq(args) -> int:
    """T01-03：解析 → 规范化清洗 → 类型化 canonical 行 + 清洗报告。

    清洗口径全部来自冻结制品（canonical_schema / field_schema / cap 空值裁定），
    清洗器只做机械归一，不猜、不补、不静默丢弃。
    """
    import json as _json
    from pathlib import Path as _P

    from .io.clean import clean_listing_rows

    out_dir = _P(args.out_dir) if args.out_dir else (
        repo_root() / "docs" / "cleaned" / _P(args.xlsx).stem / args.side
    )
    try:
        report = parse_listing(args.xlsx, args.project_id)
    except XlsxError as exc:
        print(f"■ 解析失败：{exc}")
        return 1

    rows, crep = clean_listing_rows(report.rows, args.side, args.attribution)

    print("=" * 78)
    print(f"清洗（T01-03）：{_P(args.xlsx).name}  [{args.side} 侧]")
    print("=" * 78)
    print(f" 行数 {crep.n_rows_in} → {crep.n_rows_out}（canonical）")
    print(f" 不限价项（cap 空 = 不限价但不得为 0）：{len(crep.no_cap_items)}"
          + (f" {crep.no_cap_items[:6]}" if crep.no_cap_items else ""))
    print(f" 零报价信号（C5）：{len(crep.zero_price_items)}")
    print(f" 暂估价透传信号：{len(crep.pass_through_items)}")
    print(f" 数值解析失败：{len(crep.numeric_errors)}（原样保留，禁止猜）")
    for e in crep.numeric_errors[:8]:
        print(f"   ■ {e['source_sheet']} r{e['source_row']} {e['column']}: {e['error']}")

    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "canonical_rows.json"
    rep_path = out_dir / "cleaning_report.json"
    rows_path.write_text(
        _json.dumps([r.to_dict() for r in rows], ensure_ascii=False, indent=1),
        encoding="utf-8")
    payload = crep.to_dict()
    payload["source_file"] = str(args.xlsx)
    payload["source_sha256"] = report.source_sha256
    payload["project_id"] = args.project_id
    payload["attribution"] = args.attribution or "UNKNOWN"
    rep_path.write_text(
        _json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("-" * 78)
    print(f" canonical: {rows_path}")
    print(f" 清洗报告: {rep_path}")
    return 0


def cmd_match_boq(args) -> int:
    """T01-04：解析两侧 → 清洗 → master 并集匹配 → 覆盖率 + 异常清单。

    未匹配项 100% 进异常清单；同侧重复 key → BLOCKED（禁止自动合并）。
    存在 DUPLICATE_KEY / ONLY_IN_* 异常时退出码 1——**数据问题必须人工裁定**，
    匹配器不替用户做合并决策。
    """
    import json as _json
    from pathlib import Path as _P

    from .io.match import match_canonical_rows

    try:
        cap_parsed = parse_listing(args.cap_xlsx, args.project_id)
        cost_parsed = parse_listing(args.cost_xlsx, args.project_id)
    except XlsxError as exc:
        print(f"■ 解析失败：{exc}")
        return 1

    from .io.clean import clean_listing_rows

    cap_rows, cap_rep = clean_listing_rows(cap_parsed.rows, "cap")
    cost_rows, cost_rep = clean_listing_rows(cost_parsed.rows, "cost", args.attribution)
    rep = match_canonical_rows(cap_rows, cost_rows)

    print("=" * 78)
    print(f"三表交叉匹配（T01-04）：{_P(args.cap_xlsx).name} × {_P(args.cost_xlsx).name}")
    print("=" * 78)
    print(f" cap 侧 {rep.n_cap_rows} 行（清洗异常 {len(cap_rep.numeric_errors)}）｜"
          f"cost 侧 {rep.n_cost_rows} 行（清洗异常 {len(cost_rep.numeric_errors)}）")
    print(" " + rep.summary_line())
    if rep.duplicate_keys:
        print(f" ■ 重复 key（禁止自动合并，须人工裁定）：{rep.duplicate_keys[:10]}")

    by_kind: dict[str, int] = {}
    for a in rep.anomalies:
        by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
    if by_kind:
        print(" 异常分布: " + "、".join(f"{k} {v}" for k, v in sorted(by_kind.items())))
        for a in rep.anomalies[:12]:
            print(f"   ■ [{a.kind}] {a.item_id}: {a.detail[:90]}")
        if len(rep.anomalies) > 12:
            print(f"   …其余 {len(rep.anomalies) - 12} 条见异常清单文件")

    out_dir = _P(args.out_dir) if args.out_dir else (
        repo_root() / "docs" / "matched" / args.project_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = rep.to_dict()
    payload["inputs"] = {
        "cap_xlsx": str(args.cap_xlsx), "cap_sha256": cap_parsed.source_sha256,
        "cost_xlsx": str(args.cost_xlsx), "cost_sha256": cost_parsed.source_sha256,
        "project_id": args.project_id, "attribution": args.attribution or "UNKNOWN",
    }
    out_path = out_dir / "match_report.json"
    out_path.write_text(
        _json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("-" * 78)
    print(f" 匹配报告: {out_path}")
    return 1 if rep.blocked else 0


def cmd_validate_boq(args) -> int:
    """T01-06：D01–D12 校验 —— 求解前数据体检（9 阻断 + 3 告警）。

    复用 T01-04 管线（解析→清洗→匹配），再对 MatchReport 执行校验。
    规范事实源 = config/validation_rules.json。阻断级 FAIL/BLOCKED → 退出码 1。
    """
    import json as _json
    from pathlib import Path as _P

    from .io.clean import clean_listing_rows
    from .io.match import match_canonical_rows
    from .validation.checks import (
        STATUS_FAIL,
        STATUS_SKIP,
        load_validation_rules,
        run_validation,
    )

    try:
        cap_parsed = parse_listing(args.cap_xlsx, args.project_id)
        cost_parsed = parse_listing(args.cost_xlsx, args.project_id)
    except XlsxError as exc:
        print(f"■ 解析失败：{exc}")
        return 1

    # 税口径声明（D08）+ 默认 attribution：以 config/basis_declarations.json 为事实源，
    # CLI 参数可覆盖；制品缺失 → D08 BLOCKED（未定态，不得默认）。
    basis: dict | None = None
    default_attr = None
    bd = config_dir() / "basis_declarations.json"
    if bd.exists():
        bd_json = _json.loads(bd.read_text(encoding="utf-8"))
        basis = {k: bd_json.get(k) for k in ("cap_tax_scope", "cost_tax_scope")}
        if basis.get("cap_tax_scope") is None or basis.get("cost_tax_scope") is None:
            basis = None        # 声明不完整 = 未定态，不降级为默认值
        default_attr = bd_json.get("default_attribution")
    if getattr(args, "basis_json", None):
        basis = _json.loads(_P(args.basis_json).read_text(encoding="utf-8"))
    attribution = args.attribution or default_attr

    cap_rows, _ = clean_listing_rows(cap_parsed.rows, "cap")
    cost_rows, _ = clean_listing_rows(cost_parsed.rows, "cost", attribution)
    rep = match_canonical_rows(cap_rows, cost_rows)

    # sheet → source_list 映射（D10 行级覆盖判据的机械输入）
    _ROLE2LIST = {"DETAIL_BOQ": "BOQ", "TECH_MEASURE": "TECH_MEASURE",
                  "ORG_MEASURE": "ORG_MEASURE", "OTHER": "OTHER"}
    sheet_roles = {
        s["sheet_name"]: _ROLE2LIST[s["role"]]
        for s in cap_parsed.sheets if s.get("role") in _ROLE2LIST
    }

    cdir = config_dir()
    cls = _json.loads(
        (cdir / "project_classification_table.json").read_text(encoding="utf-8"))
    sel = _json.loads((cdir / "project_selection.json").read_text(encoding="utf-8"))
    rules_cfg = load_validation_rules(cdir)


    vrep = run_validation(
        rep,
        classification=cls, selection=sel, sheet_roles=sheet_roles,
        basis=basis, history=None,
        p_star=args.p_star, p_star_max=args.p_star_max,
        p_star_min=args.p_star_min,
        thresholds=rules_cfg["thresholds"],
    )

    print("=" * 78)
    print(f"D01–D12 数据校验（T01-06）：{args.project_id}")
    print("=" * 78)
    print(" " + rep.summary_line())
    print(" " + vrep.summary_line())
    print("-" * 78)
    for r in vrep.results:
        mark = {"PASS": "✓", "FAIL": "■", "BLOCKED": "▲", "WARN": "⚠", "INFO": "ℹ", "SKIP": "–"}[
            r.status]
        print(f" {mark} [{r.rule_id:^4}] {r.status:<8} {r.detail}")
        for ev in r.evidence[:8]:
            print(f"          · {ev}")
        if len(r.evidence) > 8:
            print(f"          …其余 {len(r.evidence) - 8} 条见报告文件")

    out_dir = repo_root() / "docs" / "validated" / args.project_id
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = vrep.to_dict()
    payload["inputs"] = {
        "project_id": args.project_id,
        "cap_xlsx": str(args.cap_xlsx), "cost_xlsx": str(args.cost_xlsx),
        "p_star": args.p_star, "p_star_max": args.p_star_max,
        "p_star_min": args.p_star_min,
        "basis": basis,
        "attribution": attribution,
        "sheet_roles": sheet_roles,
        "rules_config": "config/validation_rules.json",
    }
    out_path = out_dir / "validation_report.json"
    out_path.write_text(
        _json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("-" * 78)
    print(f" 校验报告: {out_path}")
    return 1 if vrep.blocked else 0


def cmd_import_register(args) -> int:
    """T01-05：登记导入。登记表 = 事实记录，追加式不删旧行。"""
    from pathlib import Path as _P

    from .io.import_registry import register_import, registry_path_for

    try:
        rec = register_import(
            args.xlsx, args.project_id, args.side, repo_root(),
            source_owner=args.source_owner,
            file_version_note=args.version_note,
        )
    except FileNotFoundError as exc:
        print(f"■ {exc}")
        return 1
    except XlsxError as exc:
        print(f"■ xlsx 打不开：{exc}")
        return 1
    print("=" * 78)
    print(f"导入登记（T01-05）：{_P(args.xlsx).name}  [{args.project_id}/{args.side}]")
    print(f" import_seq      = {rec.import_seq}")
    print(f" file_hash       = {rec.file_hash}")
    print(f" file_version    = {rec.file_version}")
    print(f" import_time     = {rec.import_timestamp}")
    print(f" source_owner    = {rec.source_owner}")
    print(f" sheets          = {len(rec.sheet_hash)} 张（逐 sheet 哈希已记录）")
    print(f" 登记表          = {registry_path_for(repo_root(), args.project_id, args.side)}")
    return 0


def cmd_import_verify(args) -> int:
    """T01-05：复算前校验。BLOCKED = 拒绝复用旧复算结果（硬判据）。"""
    from .io.import_registry import registry_path_for, verify_import

    r = verify_import(args.xlsx, args.project_id, args.side, repo_root())
    mark = "✓" if r.status == "PASS" else "■"
    print(f" {mark} [{r.status}] {args.project_id}/{args.side} ← {args.xlsx}")
    print(f"   {r.reason}")
    if r.changed_sheets:
        print(f"   变化 sheet：{r.changed_sheets}")
    if r.record:
        print(f"   比对基准：import_seq={r.record.import_seq} "
              f"file_version={r.record.file_version} "
              f"导入于 {r.record.import_timestamp}")
    return 0 if r.status == "PASS" else 1


def cmd_cost_check(args) -> int:
    """T00-09 / T00-11：成本口径与 c_i 来源声明校验（可顺带落值声明）。"""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    from pathlib import Path as _P

    from .validation.cost_basis import check_cost_basis

    _NL = chr(10)
    cdir = config_dir()

    if args.declare_source:
        spec_path = cdir / "cost_assumption_spec.json"
        if not spec_path.exists():
            print(f"■ 假设声明书缺失：{spec_path}")
            return 1
        spec = _json.loads(spec_path.read_text(encoding="utf-8"))
        src = spec.setdefault("three_elements", {}).setdefault("source", {})
        src["value"] = args.declare_source
        src["status"] = "RESOLVED"
        evidence = {}
        for pair in args.evidence:
            if "=" in pair:
                k, v = pair.split("=", 1)
                evidence[k.strip()] = v.strip()
        src["declared_evidence"] = evidence
        src["declared_by"] = args.actor or "UNKNOWN"
        src["declared_at"] = _dt.now(_tz.utc).isoformat()
        spec_path.write_text(
            _json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f" ✓ 已落值 c_i 来源 = {args.declare_source}"
              f"（声明人：{src['declared_by']}）")
        if evidence:
            print(f"   证据：{evidence}")
        need = (src.get("required_when") or {}).get(args.declare_source) or []
        cross = [k for k in (src.get("cross_satisfied_by") or {})
                 if not k.startswith("_")]
        lack = [k for k in need if k not in evidence and k not in cross]
        if cross:
            print(f"   · 已由其它制品交叉满足，无需重复声明：{cross}")
        if lack:
            print(f" ⚠ 该来源要求附证：{need}；仍缺：{lack}")

    if args.freeze:
        spec_path = cdir / "cost_assumption_spec.json"
        if not spec_path.exists():
            print(f"■ 假设声明书缺失：{spec_path}")
            return 1
        probe = check_cost_basis(cdir)
        if probe.blocking:
            print("■ 拒绝冻结：尚有阻断项 " +
                  "、".join(r.rule_id for r in probe.blocking) +
                  "——带病冻结等于把未定态伪装成已定态")
            return 1
        spec = _json.loads(spec_path.read_text(encoding="utf-8"))
        spec["frozen_at"] = _dt.now(_tz.utc).isoformat()
        spec_path.write_text(
            _json.dumps(spec, ensure_ascii=False, indent=2) + _NL,
            encoding="utf-8")
        print(f" ✓ 已冻结：frozen_at = {spec['frozen_at']}")

    rep = check_cost_basis(cdir)
    for r in rep.results:
        mark = {"PASS": "✓", "WARN": "⚠", "BLOCKED": "■",
                "FAIL": "■", "INFO": "ℹ", "SKIP": "–"}[r.status]
        print(f" {mark} [{r.status:>7}] {r.rule_id}  {r.detail}")
        for e in r.evidence:
            print(f"            · {e}")
    s = rep.to_dict()["summary"]
    print(f"\n 汇总：{rep.status}   （" +
          " / ".join(f"{k} {v}" for k, v in sorted(s.items())) + "）")
    if rep.status != "PASS":
        print(" 阻断项（c_i 不得进入 C4/C6 约束直至解除）：" +
              "、".join(r.rule_id for r in rep.blocking))
    return 0 if rep.status == "PASS" else 1


def cmd_qty_check(args) -> int:
    """T00-10A / T00-10B：结算工程量 q1 假设声明书校验（可顺带落值敏感性义务）。"""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz

    from .validation.quantity_basis import check_quantity_basis

    _NL = chr(10)
    cdir = config_dir()
    spec_path = cdir / "q1_assumption_spec.json"

    if args.declare_sensitivity:
        if not spec_path.exists():
            print(f"■ q1 假设声明书缺失：{spec_path}")
            return 1
        spec = _json.loads(spec_path.read_text(encoding="utf-8"))
        sens = spec.setdefault("sensitivity_requirement", {})
        voc = sens.get("vocabulary") or []
        if args.declare_sensitivity not in voc:
            print(f"■ 敏感性义务 {args.declare_sensitivity!r} 不在词表 {voc} 内")
            return 1
        sens["value"] = args.declare_sensitivity
        sens["status"] = "RESOLVED"
        sens["declared_by"] = args.actor or "UNKNOWN"
        sens["declared_at"] = _dt.now(_tz.utc).isoformat()
        spec_path.write_text(
            _json.dumps(spec, ensure_ascii=False, indent=2) + _NL, encoding="utf-8")
        print(f" ✓ 已落值敏感性义务 = {args.declare_sensitivity}"
              f"（声明人：{sens['declared_by']}）")

    if args.freeze:
        if not spec_path.exists():
            print(f"■ q1 假设声明书缺失：{spec_path}")
            return 1
        probe = check_quantity_basis(cdir)
        if probe.blocking:
            print("■ 拒绝冻结：尚有阻断项 " +
                  "、".join(r.rule_id for r in probe.blocking) +
                  "——带病冻结等于把未定态伪装成已定态")
            return 1
        spec = _json.loads(spec_path.read_text(encoding="utf-8"))
        spec["frozen_at"] = _dt.now(_tz.utc).isoformat()
        spec_path.write_text(
            _json.dumps(spec, ensure_ascii=False, indent=2) + _NL, encoding="utf-8")
        print(f" ✓ 已冻结：frozen_at = {spec['frozen_at']}")

    if spec_path.exists():
        rep = check_quantity_basis(cdir)
        for r in rep.results:
            mark = {"PASS": "✓", "WARN": "⚠", "BLOCKED": "■",
                    "FAIL": "■", "INFO": "ℹ", "SKIP": "–"}[r.status]
            print(f" {mark} [{r.status:>7}] {r.rule_id}  {r.detail}")
            for e in r.evidence:
                print(f"            · {e}")
        s = rep.to_dict()["summary"]
        print(f"\n 汇总：{rep.status}   （" +
              " / ".join(f"{k} {v}" for k, v in sorted(s.items())) + "）")
        if rep.status != "PASS":
            print(" 阻断项（q1 不得进入目标函数直至解除）：" +
                  "、".join(r.rule_id for r in rep.blocking))
        return 0 if rep.status == "PASS" else 1

    print(f"■ q1 假设声明书缺失：{spec_path}")
    return 1


def _pricing_card_branch_scan(card: dict, override: dict | None, path) -> int:
    import json as _json
    from pathlib import Path as _P

    """按规则卡对匹配报告逐项判分支——分支只依赖 r=Q1/Q0，与 P0 无关。

    输出的是**优化空间的第一手证据**：区间内项无论怎么报价结算结构不变；
    越界项才是 P1 生效的地方，也是不平衡报价条款的作用域。
    """
    from collections import Counter

    from .contracts.pricing_card import classify_branch, resolve_parameters

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


def cmd_pricing_card(args) -> int:
    """T00-01：展示计价规则卡；给定 Q0/Q1/P0 时试算 P1 与结算金额。"""
    from pathlib import Path as _P

    from .contracts.pricing_card import (
        PricingCardError,
        compute_p1,
        load_pricing_card,
        resolve_parameters,
    )

    try:
        card = load_pricing_card(config_dir())
    except PricingCardError as exc:
        print(f"■ 规则卡不可用：{exc}")
        return 1

    override: dict = {}
    for pair in args.set:
        if "=" not in pair:
            print(f"■ --set 须为 KEY=VALUE 形式：{pair!r}")
            return 1
        k, v = pair.split("=", 1)
        try:
            override[k] = float(v)
        except ValueError:
            override[k] = v

    print(f" 计价规则卡 {card['card_id']}（{card['title']}）")
    print(f"   规则集      ：{card['rule_set_id']}")
    print(f"   合同类型    ：{card.get('contract_type')}")
    print(f"   调价作用域  ：{card.get('adjustment_scope')}"
          f"（来源：{card.get('adjustment_scope_source', '—')}）")
    try:
        params = resolve_parameters(card, override or None)
    except PricingCardError as exc:
        print(f"■ 参数解析阻断：{exc}")
        return 1
    print(f"   阈值        ：r<{params.decrease_threshold} 减量 / "
          f"r>{params.increase_threshold} 增量（r = Q1/Q0）")
    print(f"   ρ±          ：({params.rho_plus}, {params.rho_minus})"
          f" ← {params.sources['rho_plus']}")
    print("   五项澄清    ：" + "、".join(
        f"{c['id']}={c['status']}" for c in card["p1_clarifications"]))

    if getattr(args, "from_match", None):
        return _pricing_card_branch_scan(card, override or None,
                                         _P(args.from_match))

    if args.q0 is None and args.q1 is None and args.p0 is None:
        print("\n （未给 --q0/--q1/--p0，仅展示口径；试算请补齐三者）")
        return 0

    try:
        res = compute_p1(args.q0, args.q1, args.p0, card, override or None)
    except PricingCardError as exc:
        print(f"■ 试算阻断：{exc}")
        return 1
    if res.status != "PASS":
        print(f"■ [BLOCKED] {res.blocked_reason}")
        return 1
    print(f"\n   r = Q1/Q0 = {res.r:.6f} → 分支 {res.branch}")
    print(f"   P0 = {res.p0}  →  P1 = {res.p1}")
    print(f"   结算金额 S = {res.settlement}")
    for b in res.basis:
        print(f"     · {b}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
