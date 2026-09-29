"""一致性验收命令（自 bidpricing/cli.py 逐字拆出）。

parity-check / parity-suite。
"""
from __future__ import annotations

import json
from ..paths import GATE0_REGISTRY, PROJECT_SELECTION, config_dir, repo_root


def cmd_parity_check(args) -> int:
    """T04-04：跑 Phase 1/2 对拍并产出**可复算**的报告。

    ★ 本命令不替任一路径求解（同 ``parity.py`` 契约）：它比较的是两条路径
    **已产出**的结果留痕。缺 ``--bundle`` 时结论为 BLOCKED 并具名 owner——
    「没跑」不得被读成「通过」，也不得被读成「不适用」。

    退出码：结论为 FAIL/BLOCKED ⇒ 1（与 ``verify-solution`` / ``derive-check``
    同属**预期可能非零**的命令，不进「必须退 0」的常驻验证环）。
    """
    from pathlib import Path as _P

    from ..solver import parity_runner as pr

    bundle_path = _P(args.bundle) if args.bundle else None
    bundle = None
    if bundle_path is not None:
        try:
            bundle = pr.load_bundle(bundle_path)
        except pr.BundleError as exc:
            print(f"■ [BLOCKED] {exc}")
            return 1

    report = pr.run_parity(
        bundle,
        config_dir=config_dir(),
        signoff_path=args.signoff,
        bundle_path=bundle_path,
    )

    if not args.no_write:
        pr.write_report(report, _P(args.out))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        concl = report["conclusion"]
        print(f"■ [{concl}] T04-04 Phase 1/2 对拍")
        print(f"   独立性签署（{(report['independence'] or {}).get('required_task')}）："
              f"{(report['independence'] or {}).get('status')}")
        print(f"   制品容差（唯一来源 phase12_parity_spec.json）：{report['tolerances_used']}")
        print(f"   floor 来源：{report['floor_source'] or '未声明（ADR-0026 要求声明）'}")
        for case in report["cases"]:
            print(f"     · {case['case_id']} [{case['group']}组] {case['status']}"
                  f"（{case['level'] or '-'}）{case['reason']}")
        print(f"   结论：{concl} —— {report['reason']}")
        if report.get("owner"):
            print(f"   owner：{report['owner']}")
        if report["obligations"]:
            print("   义务（不参与 A 组判定）：")
            for item in report["obligations"]:
                print(f"     - {item}")
        if not args.no_write:
            print(f"   报告已写入 {args.out}")

    return 1 if report["conclusion"] in {"FAIL", "BLOCKED"} else 0


def cmd_parity_suite(args) -> int:
    """T04-04：从 golden_dataset_v1 生成对拍 input bundle（结果留痕）。

    与 ``parity-check`` 分层：本命令**生产** bundle（两条路径的结果留痕），
    ``parity-check --bundle`` **消费**它。生成器只收录适用子集内的正例；
    不可用/不适用者显式写入 ``provenance.skipped`` 留痕，不静默冒充覆盖。
    """
    from pathlib import Path as _P

    from ..solver import parity_suite as ps

    bundle = ps.build_bundle(config_dir=config_dir())
    ps.write_bundle(bundle, _P(args.out))

    if args.json:
        import json as _json
        print(_json.dumps(bundle, ensure_ascii=False, indent=2))
    else:
        cases = bundle["cases"]
        produced = bundle["provenance"]["produced"]
        gver = bundle["provenance"]["golden_version"]
        print(f"■ golden{gver} 对拍 bundle 已生成：{len(cases)} case")
        print(f"   两条路径均已产出：Phase1={produced['phase1']} "
              f"Phase2={produced['phase2']}（可对拍 {len(cases)}）")
        print(f"   floor 来源：{bundle['floor_source']}")
        for c in cases:
            print(f"     · {c['case_id']} [A]" 
                  f" Z1={c['phase1']['objective']:.6f}"
                  f" Z2={c['phase2']['objective']:.6f}")
        if bundle["provenance"]["skipped"]:
            print("   跳过留痕（不参与对拍）：")
            for s in bundle["provenance"]["skipped"]:
                print(f"     - {s}")
        print(f"   bundle 已写入 {args.out}")
    return 0
