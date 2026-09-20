"""把『all_items + 参数』解析为结果 payload 的纯逻辑（供 optimize / recompute 共用）。

不依赖 FastAPI，只依赖业务层与匹配层，因此可独立做单元测试。
API 层的接线（文件读取、参数绑定、错误码 JSON）在 app.py 完成，这里专注计算。

★ H-002（成本税口径）：本函数是网页侧的**唯一换算决策点**。成本清单综合单价
是含税口径，而报价与限价是不含税口径；没有换算就不能相减算毛利。因此本函数在
**产出任何毛利数字之前**先取得换算方案：不可计算即整体阻断（400），可计算则把
每一项的 ``c_i`` 换成不含税有效成本再往下走。下游管线见到 ``cost_tax_scope=EXCL_VAT``
标记即跳过换算，不会出现 k 乘两遍。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .io.match import MatchReport
from .quote_pipeline import (
    QuotePipelineResult,
    resolve_cost_plan,
    run_settlement_adjusted_quote_pipeline,
)
from .validation.cost_basis import (
    EXCL_VAT,
    read_cost_input_tax_policy,
    validate_cost_composition,
)
from .validation.low_price_policy import (
    DISPOSITION_CONFIRM_ONLY,
    DISPOSITION_NOTE,
    build_low_price_confirmation,
)
from .validation.unbalanced import settlement_revenue_adjusted

#: 成本税口径阻断时的用户提示（机器状态另有 status=BLOCKED，两者分列）
TAX_SCOPE_USER_HINT = (
    "成本清单的综合单价是含税成本，而限价与报价是不含税口径，直接相减会把毛利算低。"
    "请先声明进项税抵扣方式（以及税率/可抵扣占比），系统才能换算为不含税有效成本。"
)


def run_resolve(all_items: list[dict], params: Mapping[str, Any], low_policy: Mapping[str, Any],
                config_dir: Path | str = "config", matched: MatchReport | None = None,
                tax_policy_override: Mapping[str, Any] | None = None) -> tuple:
    """解析结果；返回 ``(result, payload, status_code)``，与 app.py 的错误码约定一致。

    - 成本税口径不可计算：result=None，payload 为 BLOCKED 说明，status_code=400；
    - 无可优化项：result=None，payload 为 BLOCKED 说明，status_code=400；
    - 求解非 PASS：result.status != PASS，payload 透传管线结果，status_code=422；
    - 成功：result.status == PASS，payload 为完整明细 payload，status_code=200。
    """
    target_total = params["target_total"]
    fixed_pretax = params["fixed_pretax"]
    vat_rate = params["vat_rate"]
    surtax_rate = params["surtax_rate"]
    ratio_min = params["ratio_min"]
    ratio_max = params["ratio_max"]
    low_ratio_confirmed = params["low_ratio_confirmed"]
    low_price_confirmed_by = params["low_price_confirmed_by"]
    low_threshold = float(low_policy.get("low_price_threshold", 0.5)) if low_policy.get("low_price_threshold") is not None else 0.5
    clause_basis = low_policy.get("clause_basis") or None

    # ---- H-002 换算/阻断：必须在任何毛利数字之前 ----
    # 复用 CLI 侧同一个决策函数（resolve_cost_plan），使两条入口共用**同名同语义**
    # 的口径判定——否则会出现「同一个约束两层各判一次、结论相反」的 DV-01 形态。
    cfg_policy = read_cost_input_tax_policy(config_dir)
    tax_policy = tax_policy_override if tax_policy_override is not None else cfg_policy
    plan, tax_error = resolve_cost_plan(
        all_items, config_dir,
        policy_section=(tax_policy_override if tax_policy_override is not None else None))
    # 分项多税率精算：派生可抵扣占比 + 回显构成（前端据以展示与复算）
    comp = tax_policy.get("cost_composition") or tax_policy.get("cost_compose")
    comp_ok, comp_cr, _ = validate_cost_composition(comp) if comp else (False, None, "")
    derived_credit_ratio = comp_cr if (comp and comp_ok) else tax_policy.get("credit_ratio")
    tax_payload = {
        "declaration_present": bool(tax_policy),
        "input_vat_credit_mode": tax_policy.get("input_vat_credit_mode"),
        "cost_input_vat_rate": tax_policy.get("cost_input_vat_rate"),
        "credit_ratio": derived_credit_ratio,
        "cost_composition": comp if (comp and comp_ok) else None,
        "cost_tax_scope_input": "INCL_VAT",
        "cost_tax_scope_effective": EXCL_VAT,
        "status": "BLOCKED" if tax_error is not None else plan.status,
        "multiplier": None if tax_error is not None else plan.multiplier,
        "reason": tax_error if tax_error is not None else plan.reason,
        "user_hint": TAX_SCOPE_USER_HINT,
    }
    if tax_error is not None:
        blocked = {"status": "BLOCKED", "reason": tax_error,
                   "cost_input_tax": tax_payload}
        if matched is not None:
            blocked["anomalies"] = [a.to_dict() for a in matched.anomalies]
        return None, blocked, 400
    all_items = list(plan.items)

    items = [item for item in all_items if item["q0"] is not None and item["q1_point"] is not None and item["c_i"] is not None and item["cap"] is not None]
    manual_items = [item for item in all_items if item not in items]
    if not items:
        blocked = {"status": "BLOCKED", "reason": "没有可纳入 C13 联合优化的项目：所有项目均缺少最高限价，请先人工确定报价。", "manual_item_count": len(manual_items), "cost_input_tax": tax_payload}
        if matched is not None:
            blocked["anomalies"] = [a.to_dict() for a in matched.anomalies]
        return None, blocked, 400
    clause = {"enabled": True, "reference": "CAP", "tol_lo": 0.5, "tol_hi": 0.5, "mechanism": "SETTLEMENT_ADJUSTMENT"}
    result: QuotePipelineResult = run_settlement_adjusted_quote_pipeline(target_total=target_total, items=items, fixed_pretax=fixed_pretax, vat_rate=vat_rate, surtax_rate=surtax_rate, config_dir=config_dir, unbalanced_clause=clause)
    payload = result.to_dict()
    if payload.get("status") != "PASS":
        return result, payload, 422

    def output_item(item: dict, manual: bool = False) -> dict:
        # ★ 成本列三件套：含税成本单价（输入原值）/ 成本税口径 / 有效成本单价（实际参与算账）
        #   —— 三个都不许省。只留一个的话，读表的人无法判断「这个毛利是按哪个成本口径算的」。
        cost_incl = item.get("cost_unit_price_input")
        cost_eff = item["c_i"]
        common = {"项目编码": item["item_id"], "项目名称": item.get("item_name", ""), "单位": item.get("unit", ""),
                  "工程量": item["q0"], "成本工程量": item["q1_point"],
                  "含税成本单价": cost_incl, "成本税口径": item.get("cost_tax_scope"),
                  "有效成本单价": cost_eff, "最高限价": item["cap"]}
        if manual:
            has_cap = item["cap"] is not None
            has_cost = item["c_i"] is not None and item["q1_point"] is not None
            if not has_cap and not has_cost:
                note = "无最高限价且缺少成本锚点，需人工报价并补充成本"
            elif not has_cap:
                note = "无最高限价，未纳入 C13 优化，需人工报价"
            else:
                note = "缺少成本锚点，未纳入 C13 优化，需补充成本或人工确认"
            cost_amount = (item["q1_point"] or 0) * cost_eff if has_cost else None
            return {**common, "最优报价单价": None, "报价比率": None, "报价合价": None,
                    "成本合价": cost_amount, "结算收入": None, "单项毛利": None,
                    "报价状态": "MANUAL_REVIEW", "说明": note}
        price = result.p_by_id[item["item_id"]]
        revenue = settlement_revenue_adjusted(item["q0"], item["q1_point"], price, item["cap"])
        # 口径一致：revenue 是不含税结算收入，成本用**有效成本**（已除税）
        margin = revenue - (item["q1_point"] or 0) * cost_eff
        note = "单项毛利为负，需人工复核；目标函数与约束复验通过" if margin < 0 else "目标函数与约束复验通过"
        ratio = price / item["cap"] if item["cap"] not in (None, 0) else None
        ratio_note = "；报价比率低于50%，需确认招标文件低价条款" if ratio is not None and ratio < 0.5 - 1e-9 else ""
        return {**common, "最优报价单价": price, "报价比率": ratio,
                "报价合价": (item["q0"] or 0) * price,
                "成本合价": (item["q1_point"] or 0) * cost_eff,
                "结算收入": revenue, "单项毛利": margin,
                "报价状态": "OPTIMIZED", "说明": note + ratio_note}
    optimized_ids = {id(item) for item in items}
    payload["items"] = [output_item(item, manual=id(item) not in optimized_ids) for item in all_items]
    low_ratio_items = [{"项目编码": item["item_id"], "报价比率": output_item(item)["报价比率"]} for item in items if item["cap"] not in (None, 0) and result.p_by_id[item["item_id"]] / item["cap"] < 0.5 - 1e-9]
    payload.update({"item_count": len(items), "manual_item_count": len(manual_items), "ratio_min": ratio_min, "ratio_max": ratio_max, "low_ratio_confirmed": low_ratio_confirmed, "low_ratio_review_required": bool(low_ratio_items), "low_ratio_items": low_ratio_items, "unbalanced_clause": clause})
    # H-002 成本税口径留痕：声明内容 + 换算系数 + 逐项痕迹（可据此复算任一行的 c_i_effective）
    tax_payload["adjustment_trace"] = plan.trace_dicts()
    payload["cost_input_tax"] = tax_payload
    if matched is not None:
        payload.update({"matched_count": matched.n_matched, "anomalies": [a.to_dict() for a in matched.anomalies]})
    else:
        payload.setdefault("anomalies", [])
    # H-004 低价确认留痕：结果记录用户/时间/条款依据；系统不作出废标判定（以招标文件为准）
    payload["low_price_policy"] = {"threshold": low_threshold, "clause_basis": clause_basis, "disposition": DISPOSITION_CONFIRM_ONLY, "disposition_note": DISPOSITION_NOTE}
    payload["low_price_confirmation"] = build_low_price_confirmation(
        confirmed=low_ratio_confirmed,
        threshold=low_threshold,
        has_low_items=bool(low_ratio_items),
        confirmed_by=(low_price_confirmed_by.strip() or None) if low_price_confirmed_by is not None else None,
        confirmed_at=datetime.now(timezone.utc).isoformat(),
        clause_basis=clause_basis,
    )
    return result, payload, 200
