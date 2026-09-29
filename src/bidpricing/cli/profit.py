"""总价与利润桥命令（自 bidpricing/cli.py 逐字拆出）。

total-price-check / profit-check。
"""
from __future__ import annotations

import json
from ..atomic_io import atomic_write_text
from ..paths import GATE0_REGISTRY, PROJECT_SELECTION, config_dir, repo_root
from ..validation.profit_bridge import check_profit_bridge
from ..states import Status, aggregate
from ..total_price import (
    check_partition,
    check_tax_base_document,
    check_tax_response,
    load_fixture,
    partition_from_fixture,
    tax_basis_text_from_fixture,
)
from .common import _read_config


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
        atomic_write_text(spec_path,
                          json.dumps(spec_doc, ensure_ascii=False, indent=2) + "\n")
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
