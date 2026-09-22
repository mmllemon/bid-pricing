"""报价策略注册表与「等比下浮」策略（方案 B）的解析实现。

optimal（方案 A，MILP 逐项寻优）与 uniform（方案 B，全场统一报价比率）共用
**同一 payload 契约**：

* 两个函数签名一致：``(all_items, params, low_policy, config_dir, matched,
  tax_policy_override) -> (result, payload, status_code)``，与 app.py 的错误码
  约定一致（400 = 输入/口径阻断，422 = 求解非 PASS，200 = PASS）；
* PASS 分支的 payload 与 ``quote_resolve.run_resolve`` **同构**（items 字段、
  item_count / ratio_min / ratio_max / low_ratio_* / unbalanced_clause /
  cost_input_tax / matched / anomalies / low_price_policy / low_price_confirmation
  逐一对应），前端与导出脚本无需区分策略。

uniform 解析解：报价单价 = 最高限价 × r（全场同一 r），r 使含税报价总额等于
目标总报价——

    B = compute_P_competitive(target_total, fixed_pretax, vat_rate, surtax_rate)   # C1 右端
    r = B / Σ(q0_i·cap_i)
    r += residual / ((1+k)·cap_q0_sum)   # 抛光至 total_from_competitive(r·Σq0·cap) == target_total

其中 k = vat_rate·(1+surtax_rate)，S=甲供材=0。r 低于 ratio_min 或高于 ratio_max
**不阻断**：标记 ``low_ratio_review_required``，并把对应项报价状态标为
``MANUAL_REVIEW``（需人工复核）。利润口径与 optimal 一致：结算调整后利润
（不含增值税），objective = Σ settlement_revenue_adjusted − Σ c_i·q1（c_i 为
H-002 换算后的不含税有效成本）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .io.match import MatchReport
from .money import money
from .quote_pipeline import QuotePipelineResult, resolve_cost_plan
from .quote_resolve import TAX_SCOPE_USER_HINT, run_resolve
from .reconciliation import reconcile_total
from .total_price import compute_P_competitive, total_from_competitive
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

#: 等比下浮解析解的抛光迭代上限（镜像 compute_P_competitive 的残差/(1+k) 抛光；
#: 每次残差 < 0.01 元、步长除以 (1+k)，16 次远超所需）。
_POLISH_ITERS = 16


def solve_uniform(all_items: list[dict], params: Mapping[str, Any], low_policy: Mapping[str, Any],
                  config_dir: Path | str = "config", matched: MatchReport | None = None,
                  tax_policy_override: Mapping[str, Any] | None = None) -> tuple:
    """等比下浮（方案 B）：全场统一报价比率 r，解析求解，不走 MILP。

    返回 ``(result, payload, status_code)``，PASS 分支与 ``run_resolve`` 同构：

    - 成本税口径不可计算：result=None，payload 为 BLOCKED 说明，status_code=400；
    - 无可优化项：result=None，payload 为 BLOCKED 说明，status_code=400；
    - 解析解未收敛 / 舍入调和失败：非 PASS 管线结果，status_code=422；
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
    clause = {"enabled": True, "reference": "CAP", "tol_lo": 0.5, "tol_hi": 0.5, "mechanism": "SETTLEMENT_ADJUSTMENT"}

    # ---- H-002 换算/阻断（与 run_resolve 同一入口、同一语义）----
    cfg_policy = read_cost_input_tax_policy(config_dir)
    tax_policy = tax_policy_override if tax_policy_override is not None else cfg_policy
    plan, tax_error = resolve_cost_plan(
        all_items, config_dir,
        policy_section=(tax_policy_override if tax_policy_override is not None else None))
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

    # ---- 解析解：统一比率 r（不走 MILP）----
    budget = compute_P_competitive(target_total, fixed_pretax, vat_rate, surtax_rate)
    cap_q0_sum = sum(float(item["q0"]) * float(item["cap"]) for item in items)
    if cap_q0_sum <= 0:
        blocked = {"status": "BLOCKED", "reason": "等比下浮不可计算：所有项目的最高限价×工程量合计为 0，无法确定统一报价比率。", "manual_item_count": len(manual_items), "cost_input_tax": tax_payload}
        if matched is not None:
            blocked["anomalies"] = [a.to_dict() for a in matched.anomalies]
        return None, blocked, 400
    k = vat_rate * (1.0 + surtax_rate)
    r = budget / cap_q0_sum
    # 抛光：r += residual/((1+k)·cap_q0_sum)，使含税总额 == 目标总报价。
    # 目标总报价若落在金额舍入步进函数的不可达格点上（money() 逐级四舍五入使
    # 部分 0.01 元档位不可精确到达，如 80350518.70），抛光会在 ±0.01 残差处
    # 振荡——此时与 optimal（MILP，同样以 compute_P_competitive 预算为 C1 右端）
    # 保持一致：回退到最近可达总价并显式留痕 warning，**不硬阻断**。
    polish_warning: str | None = None
    for _ in range(_POLISH_ITERS):
        got = total_from_competitive(r * cap_q0_sum, fixed_pretax, vat_rate, surtax_rate)
        residual = target_total - got
        if abs(residual) <= 1e-6:
            break
        r += residual / ((1.0 + k) * cap_q0_sum)
    else:
        r = budget / cap_q0_sum
        got = total_from_competitive(r * cap_q0_sum, fixed_pretax, vat_rate, surtax_rate)
        polish_warning = (f"目标总报价 {target_total:.2f} 在金额舍入步进函数上不可精确到达，"
                          f"按最近可达含税总额 {got:.2f} 报价（残差 {target_total - got:+.2f} 元，"
                          "与 optimal 策略口径一致）")

    prices = {item["item_id"]: float(item["cap"]) * r for item in items}
    line_amounts = {
        item["item_id"]: money(float(item["q0"]) * prices[item["item_id"]])
        for item in items
    }
    reconciliation = reconcile_total(
        [{"item": item["item_id"], "quantity": item["q0"], "unit_price": prices[item["item_id"]]}
         for item in items],
        declared_total=money(budget),
    )
    if reconciliation.status != "PASS":
        result = QuotePipelineResult(
            "BLOCKED", target_total, budget, prices, line_amounts, None,
            "UNIFORM_RATIO", (), "分项舍入调和未通过: " + reconciliation.reason,
            (), plan.multiplier, tuple(plan.trace_dicts()),
        )
        return result, result.to_dict(), 422

    # 目标函数（EXCL_VAT 口径，与 optimal 一致）：Σ 结算调整后收入 − Σ 有效成本
    objective = 0.0
    for item in items:
        revenue = settlement_revenue_adjusted(
            item["q0"], item["q1_point"], prices[item["item_id"]], item["cap"])
        objective += revenue - (item["q1_point"] or 0) * item["c_i"]
    result = QuotePipelineResult(
        "PASS", target_total, budget, prices, line_amounts, objective,
        "UNIFORM_RATIO", (),
        "等比下浮解析解：全场统一报价比率 r，含税报价总额与目标总报价调和一致",
        (polish_warning,) if polish_warning else (),
        plan.multiplier, tuple(plan.trace_dicts()),
    )
    payload = result.to_dict()

    in_range = (ratio_min - 1e-9) <= r <= (ratio_max + 1e-9)

    def output_item(item: dict, manual: bool = False) -> dict:
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
        price = prices[item["item_id"]]
        revenue = settlement_revenue_adjusted(item["q0"], item["q1_point"], price, item["cap"])
        margin = revenue - (item["q1_point"] or 0) * cost_eff
        ratio = price / item["cap"] if item["cap"] not in (None, 0) else None
        ratio_note = "；报价比率低于50%，需确认招标文件低价条款" if ratio is not None and ratio < 0.5 - 1e-9 else ""
        if not in_range:
            note = "报价比率超出设定区间，需人工复核" + ("" if margin >= 0 else "；单项毛利为负") + ratio_note
            status = "MANUAL_REVIEW"
        else:
            note = ("单项毛利为负，需人工复核；目标函数与约束复验通过" if margin < 0
                    else "目标函数与约束复验通过") + ratio_note
            status = "OPTIMIZED"
        return {**common, "最优报价单价": price, "报价比率": ratio,
                "报价合价": (item["q0"] or 0) * price,
                "成本合价": (item["q1_point"] or 0) * cost_eff,
                "结算收入": revenue, "单项毛利": margin,
                "报价状态": status, "说明": note}
    optimized_ids = {id(item) for item in items}
    payload["items"] = [output_item(item, manual=id(item) not in optimized_ids) for item in all_items]
    low_ratio_items = [{"项目编码": item["item_id"], "报价比率": prices[item["item_id"]] / item["cap"]} for item in items if item["cap"] not in (None, 0) and prices[item["item_id"]] / item["cap"] < 0.5 - 1e-9]
    payload.update({"item_count": len(items), "manual_item_count": len(manual_items), "ratio_min": ratio_min, "ratio_max": ratio_max, "low_ratio_confirmed": low_ratio_confirmed, "low_ratio_review_required": bool(low_ratio_items) or not in_range, "low_ratio_items": low_ratio_items, "unbalanced_clause": clause})
    # H-002 成本税口径留痕：声明内容 + 换算系数 + 逐项痕迹（与 run_resolve 同构）
    tax_payload["adjustment_trace"] = plan.trace_dicts()
    payload["cost_input_tax"] = tax_payload
    if matched is not None:
        payload.update({"matched_count": matched.n_matched, "anomalies": [a.to_dict() for a in matched.anomalies]})
    else:
        payload.setdefault("anomalies", [])
    # H-004 低价确认留痕（与 run_resolve 同构）
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


#: 报价策略注册表：app.py 据此分发（非法值由 API 层 400 拒绝）。
STRATEGIES: dict[str, Any] = {"optimal": run_resolve, "uniform": solve_uniform}
