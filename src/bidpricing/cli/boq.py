"""清单（BOQ）管道命令（自 bidpricing/cli.py 逐字拆出）。

parse / clean / match / validate / import-register / import-verify。
"""
from __future__ import annotations

from ..io.boq import parse_listing, write_report
from ..io.xlsx import XlsxError
from ..paths import GATE0_REGISTRY, PROJECT_SELECTION, config_dir, repo_root


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

    from ..io.clean import clean_listing_rows

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

    from ..io.match import match_canonical_rows

    try:
        cap_parsed = parse_listing(args.cap_xlsx, args.project_id)
        cost_parsed = parse_listing(args.cost_xlsx, args.project_id)
    except XlsxError as exc:
        print(f"■ 解析失败：{exc}")
        return 1

    from ..io.clean import clean_listing_rows

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
    """T01-06：D01–D13 校验 —— 求解前数据体检（10 阻断 + 3 告警）。

    复用 T01-04 管线（解析→清洗→匹配），再对 MatchReport 执行校验。
    规范事实源 = config/validation_rules.json。阻断级 FAIL/BLOCKED → 退出码 1。
    """
    import json as _json
    from pathlib import Path as _P

    from ..io.clean import clean_listing_rows
    from ..io.match import match_canonical_rows
    from ..validation.checks import (
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
    # 配置缺失/坏 JSON 直接 traceback 会把「环境没配好」伪装成程序 bug；
    # 与上方 basis_declarations 的守卫同口径：打印 BLOCKED 文案并 return 1。
    for fname in ("project_classification_table.json", "project_selection.json"):
        f = cdir / fname
        if not f.exists():
            print(f"▲ BLOCKED：缺少校验配置 {f}\n"
                  "  D01–D13 需要项目分类表与选项目录作事实源，不得默认；"
                  "请先在 config/ 下补齐该文件")
            return 1
    try:
        cls = _json.loads(
            (cdir / "project_classification_table.json").read_text(encoding="utf-8"))
        sel = _json.loads((cdir / "project_selection.json").read_text(encoding="utf-8"))
    except _json.JSONDecodeError as exc:
        print(f"▲ BLOCKED：校验配置 JSON 无法解析（{cdir}）：{exc}")
        return 1
    rules_cfg = load_validation_rules(cdir)


    vrep = run_validation(
        rep,
        classification=cls, selection=sel, sheet_roles=sheet_roles,
        basis=basis, history=None,
        p_star=args.p_star, p_star_max=args.p_star_max,
        p_star_min=args.p_star_min,
        missing_unit_price_sheets={
            "cap": list(cap_parsed.missing_unit_price_sheets),
            "cost": list(cost_parsed.missing_unit_price_sheets),
        },
        thresholds=rules_cfg["thresholds"],
    )

    print("=" * 78)
    print(f"D01–D13 数据校验（T01-06）：{args.project_id}")
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

    from ..io.import_registry import register_import, registry_path_for

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
    from ..io.import_registry import registry_path_for, verify_import

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
