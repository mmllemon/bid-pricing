"""Q0→Q1 闭环命令（自 bidpricing/cli.py 逐字拆出）。

precision-monitor / calibrate / closed-loop / predict-register。
"""
from __future__ import annotations

import json
from ..paths import GATE0_REGISTRY, PROJECT_SELECTION, config_dir, repo_root
from .common import _load_closed_loop_bundle, _run_closed_loop_for_bundle


def cmd_precision_monitor(args) -> int:
    """T07-03：Q1 精度监控 —— MAE/WAPE/sMAPE + 四元升级闸门。

    与 ``closed-loop`` 的分工：本命令只跑精度一级（监控模块本体），
    ``closed-loop`` 跑全链编排。来源判据与声明书交叉校验共用同一处实现
    （closed_loop.resolve_precision_inputs）——来源未登记或声明书对不上即
    BLOCKED，指标不计算，杜绝拿 q0/actual 顶替。
    """
    from pathlib import Path as _P

    from ..closed_loop import (
        load_closed_loop_spec,
        resolve_precision_inputs,
        resolve_promotion_inputs,
    )
    from ..precision_monitor import monitor_precision
    from ..quantity_reconciliation import compare_quantities

    bundle, err = _load_closed_loop_bundle(args.records)
    if err:
        print(f"■ [BLOCKED] {err}")
        return 1

    merged, note = resolve_precision_inputs(bundle, load_closed_loop_spec(config_dir()))
    if merged is None:
        report_dict = {
            "predicted_q1_source": bundle.predicted_q1_source,
            "note": note,
            "report": None,
        }
        if args.json:
            print(json.dumps(report_dict, ensure_ascii=False, indent=2))
            return 1
        print("=" * 78)
        print(f"Q1 精度监控（T07-03）｜ 输入束 {bundle.source}")
        print("=" * 78)
        print(f"■ [BLOCKED] {note}")
        return 1

    comparison = compare_quantities(merged)
    ci_eff, seg_eff, ptype_eff, gate_sources = resolve_promotion_inputs(
        merged, comparison, bundle
    )
    report = monitor_precision(
        merged,
        q_min=bundle.q_min if bundle.q_min is not None else 1.0,
        min_sample_size=bundle.min_sample_size or 30,
        confidence_interval=ci_eff,
        segment=seg_eff,
        project_type=ptype_eff,
    )

    if args.json:
        print(json.dumps({
            "predicted_q1_source": bundle.predicted_q1_source,
            "note": note,
            "promotion_sources": dict(gate_sources),
            "report": report.to_dict(),
        }, ensure_ascii=False, indent=2))
        return 0 if report.status != "BLOCKED" else 1

    print("=" * 78)
    print(f"Q1 精度监控（T07-03）｜ 输入束 {_P(bundle.source) if bundle.source else args.records}")
    print("=" * 78)
    print(f"  来源判据：{note}")
    for key, desc in gate_sources.items():
        print(f"  闸门来源 [{key}] {desc}")
    print(f"  样本量：{report.sample_size}（阈值 {bundle.min_sample_size or 30}；"
          f"q_min = {bundle.q_min if bundle.q_min is not None else 1.0}）")
    for m in report.metrics:
        label = "小工程量（q1<q_min）" if m.low_quantity else "总体口径"
        wape = "—" if m.wape is None else f"{m.wape:.4f}"
        print(f"  [{label}] n={m.sample_size}  MAE={m.mae:.4f}  WAPE={wape}  sMAPE={m.smape:.4f}")
    tag = {"PASS": "  PASS", "WARN": "  WARN", "BLOCKED": "BLOCKED"}[report.status]
    print(f"[{tag}] 升级闸门：{report.promotion_status}")
    print(f"          {report.reason}")
    if report.promotion_status == "HOLD":
        print("  ▲ HOLD ≠ 失败：升级/降级暂缓，须同时满足样本量、置信区间、"
              "segment、project_type 才 READY")
    return 0 if report.status != "BLOCKED" else 1


def cmd_calibrate(args) -> int:
    """T07-04：参数校准记录 —— 三门前置齐备才生成版本化建议。

    建议只记录 key/old_value/new_value/reason（审批 PENDING），
    **永不直接覆盖当前 config**；证据不足保持 BLOCKED 并具名缺口。
    """
    from ..closed_loop import load_closed_loop_spec

    bundle, err = _load_closed_loop_bundle(args.records)
    if err:
        print(f"■ [BLOCKED] {err}")
        return 1
    report = _run_closed_loop_for_bundle(bundle, load_closed_loop_spec(config_dir()))
    rec = report.calibration

    if args.json:
        print(json.dumps({
            "evidence": report.evidence,
            "predicted_source_note": report.predicted_source_note,
            "record": rec.to_dict(),
        }, ensure_ascii=False, indent=2))
        return 0 if rec.status == "PASS" else 1

    print("=" * 78)
    print("参数校准（T07-04）")
    print("=" * 78)
    print(f"  证据：replay={report.evidence['replay_status']}  "
          f"对照={report.evidence['quantity_comparison_status']}  "
          f"精度升级={report.evidence['precision_promotion_status']}")
    print(f"  来源判据：{report.predicted_source_note}")
    tag = "PASS" if rec.status == "PASS" else "BLOCKED"
    print(f"[{tag}] 校准记录（base={rec.base_config_version}"
          + (f" → proposed={rec.proposed_config_version}" if rec.proposed_config_version else "")
          + f"，审批 {rec.approval_status}，applied={rec.applied}）")
    print(f"       {rec.reason}")
    for c in rec.changes:
        old = "（未在当前 config 找到）" if c.old_value is None else c.old_value
        print(f"   · {c.key}: {old} → {c.new_value}（{c.reason}）")
    if rec.status == "BLOCKED":
        print("  ▲ 证据不足：不生成建议，也不允许静默改配置——"
              "缺哪门补哪门（replay / 实际对照 / 精度升级）")
    return 0 if rec.status == "PASS" else 1


def cmd_closed_loop(args) -> int:
    """Q0→Q1 闭环编排（T07-02→T07-03→T07-04）：三级串联，缺数据逐级如实 BLOCKED。

    与单级命令的分工：``precision-monitor`` / ``calibrate`` 各跑一级，
    本命令按 spec.stages 顺序跑全链并给出整体结论（spec.status_domain：
    READY 仅当 closed_when 三条全部成立；否则 BLOCKED 且 reason 具名缺口）。
    退出码：READY ⇒ 0，BLOCKED ⇒ 1（如实反映数据未齐，不是实现缺陷）。
    """
    from pathlib import Path as _P

    from ..closed_loop import load_closed_loop_spec

    bundle, err = _load_closed_loop_bundle(args.records)
    if err:
        print(f"■ [BLOCKED] {err}")
        return 1
    report = _run_closed_loop_for_bundle(bundle, load_closed_loop_spec(config_dir()))

    if not args.no_write:
        out_path = _P(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8")

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.status == "READY" else 1

    print("=" * 78)
    print("Q0→Q1 闭环编排（T07-02 对照 → T07-03 精度监控 → T07-04 参数校准）")
    print("=" * 78)
    print(f"  输入束：{bundle.source}")
    print(f"  来源判据：{report.predicted_source_note}")
    for stage in report.stages:
        tag = {"PASS": "  PASS", "WARN": "  WARN", "BLOCKED": "BLOCKED"}[stage.status]
        extra = ""
        if stage.stage.endswith("precision") and report.precision is not None:
            extra = f"（升级闸门 {report.precision.promotion_status}）"
        print(f" [{tag}] {stage.stage}{extra}")
        print(f"           {stage.detail}")
    print(f"  证据：replay={report.evidence['replay_status']}  "
          f"对照={report.evidence['quantity_comparison_status']}  "
          f"精度升级={report.evidence['precision_promotion_status']}")
    for key, desc in report.promotion_sources.items():
        print(f"  闸门 [{key}] {desc}")
    print("-" * 78)
    mark = "OK" if report.status == "READY" else "BLOCKED"
    print(f" [{mark}] 整体结论：{report.status} —— {report.reason}")
    rec = report.calibration
    if rec.status == "PASS":
        print(f"   校准建议 {len(rec.changes)} 条（审批 {rec.approval_status}，"
              f"base={rec.base_config_version} → proposed={rec.proposed_config_version}），"
              "须人工审批并冻结新版本后才生效。")
    if not args.no_write:
        print(f"   报告已写入 {args.out}")
    return 0 if report.status == "READY" else 1


def cmd_predict_register(args) -> int:
    """T07-03/T07-04：登记 predicted_q1 独立来源声明书（谁/何时/为什么 必给）。

    输入文件三种形态：``{item: 值}`` 映射、``[{"item", "predicted_q1"}]`` 数组、
    或含 ``records`` 键的对象（只取 records，source/留痕以 CLI 参数为准）。
    登记成功的声明书是 predicted_q1 的唯一事实源——闭环 bundle 通过
    ``predicted_q1_declaration`` 引用它做交叉校验。
    """
    from datetime import datetime as _dt, timezone as _tz
    from pathlib import Path as _P

    from ..predicted_q1 import (
        PredictionDeclarationError,
        load_predicted_q1_spec,
        register_declaration,
    )

    in_path = _P(args.input)
    if not in_path.exists():
        print(f"■ 输入文件不存在：{in_path}")
        return 1
    try:
        doc = json.loads(in_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"■ 输入不是合法 JSON：{exc}")
        return 1
    if isinstance(doc, dict) and "records" in doc:
        records = doc["records"]
    elif isinstance(doc, (dict, list)):
        records = doc
    else:
        print("■ 输入须为 {item: 值} 对象、records 数组或含 records 键的对象")
        return 1

    if not args.actor or not args.actor.strip():
        print("■ 必须用 --actor 如实标明声明人（业务声明=user，代操作=agent(...)）")
        return 1
    if not args.rationale or not args.rationale.strip():
        print("■ 必须用 --rationale 如实给出依据（留痕四件缺一即拒）")
        return 1

    spec = load_predicted_q1_spec(config_dir())
    out_path = _P(args.out)
    try:
        declaration = register_declaration(
            source=args.source,
            records=records,
            declared_by=args.actor.strip(),
            declared_at=args.at or _dt.now(_tz.utc).isoformat(),
            rationale=args.rationale.strip(),
            spec=spec,
            out_path=out_path,
            replace=args.replace,
        )
    except PredictionDeclarationError as exc:
        print(f"■ [REJECTED] {exc}")
        return 1

    print(f"[REGISTERED] predicted_q1 声明书：{out_path}")
    print(f"   source       = {declaration.source}（须与闭环 bundle 的 predicted_q1_source 一致）")
    print(f"   declared_by  = {declaration.declared_by}")
    print(f"   declared_at  = {declaration.declared_at}")
    print(f"   依据         = {declaration.rationale}")
    print(f"   覆盖项数     = {len(declaration.records)}")
    print(f"\n下一步：在闭环输入束里加 \"predicted_q1_declaration\": \"{out_path}\"，")
    print(f"        跑 closed-loop / precision-monitor 即自动交叉校验。")
    return 0
