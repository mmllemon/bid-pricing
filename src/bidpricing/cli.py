"""命令行入口。

用法（在仓库根目录下）::

    PYTHONPATH=src python -m bidpricing.cli gate-check
    PYTHONPATH=src python -m bidpricing.cli ruleset-select --contract-date 2026-03-01
    PYTHONPATH=src python -m bidpricing.cli ruleset-selftest
    PYTHONPATH=src python -m bidpricing.cli freeze --all
    PYTHONPATH=src python -m bidpricing.cli freeze --gate gate_0a --key field_schema_version
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
from .contracts.selector import ruleset_self_test, select_rule_set
from .gates.gate0 import evaluate_gate_0
from .paths import GATE0_REGISTRY, config_dir

_STATUS_MARK = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL", "BLOCKED": "BLOCKED"}


def _registry_path():
    return config_dir() / GATE0_REGISTRY


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
    print(f"Phase 0 准入            = {report['summary']['phase_0']}")
    print(f"WP4 求解层构建          = {report['summary']['wp4_solver_layer']}")
    print("=" * 78)

    if report["summary"]["gate_0a"] == "PASS":
        print("\n结论：Gate 0a 通过，放行 WP1 / WP2 / WP3。")
        return 0
    print("\n结论：Gate 0a 未通过 —— 按 §7.1.1 断言 2，Phase 0 判 BLOCKED，"
          "WP1 / WP2 / WP3 不得开工。")
    return 1


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
        print(f"  [{flag}] {name}")
        print(f"         actual = {chk['actual']!r}")
        if "expected" in chk:
            print(f"         expected = {chk['expected']!r} (tol {chk.get('tolerance')})")
        if "expected_abs_max" in chk:
            print(f"         |actual| <= {chk['expected_abs_max']}")
        if "expected_min" in chk:
            print(f"         |actual| >= {chk['expected_min']}")
        print(f"         {chk['meaning']}")
    print(f"\n总判定：{'PASS' if result['passed'] else 'FAIL'}")
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
                       help="T00-01 对 §8.9 是否分段的解读结论")

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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
