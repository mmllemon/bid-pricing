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
from .states import Status, aggregate

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

    return parser


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
        mark = {"PASS": "✓", "FAIL": "■", "BLOCKED": "▲", "WARN": "⚠", "SKIP": "–"}[
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
