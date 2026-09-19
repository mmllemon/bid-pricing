"""把『all_items + 参数』解析为结果 payload 的纯逻辑（供 optimize / recompute 共用）。

不依赖 FastAPI，只依赖业务层与匹配层，因此可独立做单元测试。
API 层的接线（文件读取、参数绑定、错误码 JSON）在 app.py 完成，这里专注计算。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .io.match import MatchReport
from .quote_pipeline import QuotePipelineResult, run_settlement_adjusted_quote_pipeline
from .validation.low_price_policy import (
    DISPOSITION_CONFIRM_ONLY,
    DISPOSITION_NOTE,
    build_low_price_confirmation,
)
from .validation.unbalanced import settlement_revenue_adjusted


def run_resolve(all_items: list[dict], params: Mapping[str, Any], low_policy: Mapping[str, Any],
                config_dir: Path | str = "config", matched: MatchReport | None = None) -> tuple:
    """解析结果；返回 ``(result, payload, status_code)``，与 app.py 的错误码约定一致。

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

    items = [item for item in all_items if item["q0"] is not None and item["q1_point"] is not None and item["c_i"] is not None and item["cap"] is not None]
    manual_items = [item for item in all_items if item not in items]
    if not items:
        blocked = {"status": "BLOCKED", "reason": "没有可纳入 C13 联合优化的项目：所有项目均缺少最高限价，请先人工确定报价。", "manual_item_count": len(manual_items)}
        if matched is not None:
            blocked["anomalies"] = [a.to_dict() for a in matched.anomalies]
        return None, blocked, 400
    clause = {"enabled": True, "reference": "CAP", "tol_lo": 0.5, "tol_hi": 0.5, "mechanism": "SETTLEMENT_ADJUSTMENT"}
    result: QuotePipelineResult = run_settlement_adjusted_quote_pipeline(target_total=target_total, items=items, fixed_pretax=fixed_pretax, vat_rate=vat_rate, surtax_rate=surtax_rate, config_dir=config_dir, unbalanced_clause=clause)
    payload = result.to_dict()
    if payload.get("status") != "PASS":
        return result, payload, 422

    def output_item(item: dict, manual: bool = False) -> dict:
        if manual:
            has_cap = item["cap"] is not None
            has_cost = item["c_i"] is not None and item["q1_point"] is not None
            if not has_cap and not has_cost:
                note = "无最高限价且缺少成本锚点，需人工报价并补充成本"
            elif not has_cap:
                note = "无最高限价，未纳入 C13 优化，需人工报价"
            else:
                note = "缺少成本锚点，未纳入 C13 优化，需补充成本或人工确认"
            cost_amount = (item["q1_point"] or 0) * item["c_i"] if has_cost else None
            return {"项目编码": item["item_id"], "项目名称": item.get("item_name", ""), "单位": item.get("unit", ""), "工程量": item["q0"], "成本工程量": item["q1_point"], "含税成本单价": item["c_i"], "最高限价": item["cap"], "最优报价单价": None, "报价比率": None, "报价合价": None, "成本合价": cost_amount, "结算收入": None, "单项毛利": None, "报价状态": "MANUAL_REVIEW", "说明": note}
        price = result.p_by_id[item["item_id"]]
        revenue = settlement_revenue_adjusted(item["q0"], item["q1_point"], price, item["cap"])
        margin = revenue - (item["q1_point"] or 0) * item["c_i"]
        note = "单项毛利为负，需人工复核；目标函数与约束复验通过" if margin < 0 else "目标函数与约束复验通过"
        ratio = price / item["cap"] if item["cap"] not in (None, 0) else None
        ratio_note = "；报价比率低于50%，需确认招标文件低价条款" if ratio is not None and ratio < 0.5 - 1e-9 else ""
        return {"项目编码": item["item_id"], "项目名称": item.get("item_name", ""), "单位": item.get("unit", ""), "工程量": item["q0"], "成本工程量": item["q1_point"], "含税成本单价": item["c_i"], "最高限价": item["cap"], "最优报价单价": price, "报价比率": ratio, "报价合价": (item["q0"] or 0) * price, "成本合价": (item["q1_point"] or 0) * item["c_i"], "结算收入": revenue, "单项毛利": margin, "报价状态": "OPTIMIZED", "说明": note + ratio_note}
    optimized_ids = {id(item) for item in items}
    payload["items"] = [output_item(item, manual=id(item) not in optimized_ids) for item in all_items]
    low_ratio_items = [{"项目编码": item["item_id"], "报价比率": output_item(item)["报价比率"]} for item in items if item["cap"] not in (None, 0) and result.p_by_id[item["item_id"]] / item["cap"] < 0.5 - 1e-9]
    payload.update({"item_count": len(items), "manual_item_count": len(manual_items), "ratio_min": ratio_min, "ratio_max": ratio_max, "low_ratio_confirmed": low_ratio_confirmed, "low_ratio_review_required": bool(low_ratio_items), "low_ratio_items": low_ratio_items, "unbalanced_clause": clause})
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