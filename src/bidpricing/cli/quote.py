"""报价与组价命令（自 bidpricing/cli.py 逐字拆出）。

cost-check / qty-check / pricing-card。
"""
from __future__ import annotations

from ..atomic_io import atomic_write_text
from ..paths import GATE0_REGISTRY, PROJECT_SELECTION, config_dir, repo_root
from .common import _pricing_card_branch_scan


def cmd_cost_check(args) -> int:
    """T00-09 / T00-11：成本口径与 c_i 来源声明校验（可顺带落值声明）。"""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz

    from ..validation.cost_basis import check_cost_basis

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
        atomic_write_text(spec_path,
                          _json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
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
        atomic_write_text(spec_path,
                          _json.dumps(spec, ensure_ascii=False, indent=2) + _NL)
        print(f" ✓ 已冻结：frozen_at = {spec['frozen_at']}")

    from ..validation.cost_basis import check_cost_input_tax
    from ..validation.hidden_cost import check_hidden_cost_policy
    from ..validation.low_price_policy import check_low_price_policy

    rep = check_cost_basis(cdir)
    tax_rep = check_cost_input_tax(cdir)
    hidden_rep = check_hidden_cost_policy(cdir)
    low_rep = check_low_price_policy(cdir)
    combined = rep.results + tax_rep.results + hidden_rep.results + low_rep.results
    for r in combined:
        mark = {"PASS": "✓", "WARN": "⚠", "BLOCKED": "■",
                "FAIL": "■", "INFO": "ℹ", "SKIP": "–"}[r.status]
        print(f" {mark} [{r.status:>7}] {r.rule_id}  {r.detail}")
        for e in r.evidence:
            print(f"            · {e}")
    s: dict[str, int] = {}
    for r in combined:
        s[r.status] = s.get(r.status, 0) + 1
    blocking = [r for r in combined if r.status in ("BLOCKED", "FAIL")]
    status = "BLOCKED" if blocking else "PASS"
    print(f"\n 汇总：{status}   （" +
          " / ".join(f"{k} {v}" for k, v in sorted(s.items())) + "）")
    if status != "PASS":
        print(" 阻断项（c_i 不得进入 C4/C6 约束直至解除；含税成本未换算时"
              "『最优利润』结论不输出；低价留痕阻断时不输出『已完成低价合规复核』"
              "结论）：" +
              "、".join(r.rule_id for r in blocking))
    return 0 if status == "PASS" else 1


def cmd_qty_check(args) -> int:
    """T00-10A / T00-10B：结算工程量 q1 假设声明书校验（可顺带落值敏感性义务）。"""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz

    from ..validation.quantity_basis import check_quantity_basis

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
        atomic_write_text(spec_path,
                          _json.dumps(spec, ensure_ascii=False, indent=2) + _NL)
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
        atomic_write_text(spec_path,
                          _json.dumps(spec, ensure_ascii=False, indent=2) + _NL)
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


def cmd_pricing_card(args) -> int:
    """T00-01：展示计价规则卡；给定 Q0/Q1/P0 时试算 P1 与结算金额。"""
    from pathlib import Path as _P

    from ..contracts.pricing_card import (
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
