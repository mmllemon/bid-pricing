"""多方案对比（H-008）：把多个已保存的方案并列，输出利润、亏损项、风险项、单价差异。

纯逻辑、不依赖 FastAPI；输入是 ``project_store.load_plan`` 返回的 record 列表
（每个 record 含 all_items 与 result）。可直接单测。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

RISK_RATIO = 0.5  #: 报价比率低于该阈值视为"风险项"（与原低价条款口径一致）


def project_key(record: Mapping[str, Any]) -> str:
    """稳定指认方案所属项目：优先 project_id，旧方案退化用 name。"""
    return record.get("project_id") or record.get("name") or ""


def group_projects(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    """按项目把方案归组，返回 {项目key: [records]}。"""
    out: dict[str, list[dict]] = {}
    for r in records:
        out.setdefault(project_key(r), []).append(r)
    return out


def same_project(records: Sequence[Mapping[str, Any]]) -> tuple[bool, list[str] | None]:
    """校验是否为同一项目：是 → (True, None)；否 → (False, 涉及的项目列表)。"""
    g = group_projects(records)
    keys = sorted(g.keys())
    if len(keys) > 1:
        return False, keys
    return True, None


def _as_plans(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return list(records)


def _mk(records: Sequence[Mapping[str, Any]]) -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    plans = _as_plans(records)
    plan_ids = [p.get("id") or f"plan{i}" for i, p in enumerate(plans)]
    names = [p.get("name") or plan_ids[i] for i, p in enumerate(plans)]
    return plans, dict(zip(plan_ids, names)), dict(zip(plan_ids, enumerate(plans)))


def _price_index(plan: Mapping[str, Any]) -> dict[str, float]:
    """把方案 result.items 转成 {项目编码: 最优报价单价}。"""
    out: dict[str, float] = {}
    result = plan.get("result") or {}
    if result.get("status") != "PASS":
        return out
    for it in result.get("items") or []:
        price = it.get("最优报价单价")
        code = it.get("项目编码")
        if price is not None and code is not None:
            out[code] = float(price)
    return out


def _profit(plan: Mapping[str, Any]) -> float | None:
    result = plan.get("result") or {}
    if result.get("status") != "PASS":
        return None
    return None if result.get("objective") is None else float(result["objective"])


def _loss_items(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """单项毛利 < 0 的项目。"""
    result = plan.get("result") or {}
    if result.get("status") != "PASS":
        return []
    out = []
    for it in result.get("items") or []:
        margin = it.get("单项毛利")
        if margin is not None and float(margin) < 0:
            out.append({"项目编码": it.get("项目编码"), "项目名称": it.get("项目名称", ""), "单项毛利": float(margin)})
    return out


def _risk_items(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """报价比率 < RISK_RATIO 的项目（风险项）。"""
    result = plan.get("result") or {}
    if result.get("status") != "PASS":
        return []
    out = []
    for it in result.get("items") or []:
        ratio = it.get("报价比率")
        if ratio is not None and float(ratio) < RISK_RATIO - 1e-9:
            out.append({"项目编码": it.get("项目编码"), "项目名称": it.get("项目名称", ""), "报价比率": float(ratio)})
    return out


def compare_plans(records: Sequence[Mapping[str, Any]], base_id: str | None = None) -> dict[str, Any]:
    """对比多个方案，返回结构化结果。

    - ``plan_ids``：各方案 id（保持输入顺序）；
    - ``base_id``：单价差异的基准方案（缺省取第一个）；
    - ``summary``：每方案一行 {plan_id, name, computed, objective, item_count,
      loss_items, risk_items, avg_abs_price_delta}；
    - ``price_diffs``：按项目编码组织的单价差异 {编码: {item_name, base_price, deltas}}。
    """
    plans = [p for p in _as_plans(records) if p.get("id") is not None]
    plan_ids = [p["id"] for p in plans]
    if not plan_ids:
        return {"status": "PASS", "plan_ids": [], "base_id": None, "project": None, "summary": [], "price_diffs": {}}

    if base_id is None or base_id not in plan_ids:
        base_id = plan_ids[0]
    base_plan = next(p for p in plans if p["id"] == base_id)
    base_prices = _price_index(base_plan)

    summary: list[dict[str, Any]] = []
    for plan in plans:
        computed = (plan.get("result") or {}).get("status") == "PASS"
        price_index = _price_index(plan)
        deltas = []
        for code, base_price in base_prices.items():
            p = price_index.get(code)
            if p is not None:
                deltas.append(abs(p - base_price))
        loss = _loss_items(plan)
        risk = _risk_items(plan)
        summary.append({
            "plan_id": plan["id"],
            "name": plan.get("name") or plan["id"],
            "project": project_key(plan),
            "params": plan.get("params") or None,
            "computed": computed,
            "objective": _profit(plan),
            "item_count": len(price_index),
            "loss_items": loss,
            "risk_items": risk,
            "avg_abs_price_delta": (sum(deltas) / len(deltas)) if deltas else None,
        })

    # 单价差异明细：以 base_prices 的项为维度
    price_diffs: dict[str, Any] = {}
    for code, base_price in base_prices.items():
        entry = {"item_name": None, "base_price": base_price, "deltas": {}}
        for plan in plans:
            p = _price_index(plan).get(code)
            entry["deltas"][plan["id"]] = None if p is None else p - base_price
        # 尽量补上项目名称
        for it in (base_plan.get("result") or {}).get("items") or []:
            if it.get("项目编码") == code and it.get("项目名称"):
                entry["item_name"] = it.get("项目名称")
                break
        price_diffs[code] = entry

    return {"status": "PASS", "plan_ids": plan_ids, "base_id": base_id, "project": project_key(plans[0]), "summary": summary, "price_diffs": price_diffs}