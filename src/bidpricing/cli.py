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
from .contracts.scope_impact import compare_scopes
from .contracts.selector import ruleset_self_test, select_rule_set
from .gates.gate0 import evaluate_gate_0
from .paths import GATE0_REGISTRY, PROJECT_SELECTION, config_dir
from .selection_options import (
    SELECTABLE_OPTIONS,
    clear_option,
    read_option_entry,
    resolve_option,
    write_option,
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
        print("      它们都是「求解启动前必须有、开发期不需要」的输入：")
        print("      · 选择项取值未定 → 两条分支都要求被实现，选择只决定哪条生效")
        print("      · 逐项分类表为空 → 它随项目而异，规则书（分类机制）已冻结即可开工")
        print("      落值命令：")
        print("      bidpricing options set --key adjustment_scope "
              "--value <FULL|SEGMENT> --rule-set <rid> --rationale \"...\"")
        print("      逐项分类表：由真实招标清单经 T01-00B 解析器产出后填入 "
              "config/project_classification_table.json")

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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
