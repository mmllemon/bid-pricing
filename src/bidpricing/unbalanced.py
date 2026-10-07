"""不平衡报价分配器（纯逻辑，不依赖 FastAPI，可独立单测）。

输入：清单项（工程量 / 成本单价 / 控制价 / 策略标签）+ 目标总价 T
输出：每项报价单价 p_i，满足 Σ(p_i·q_i) = T，且每项落在 [下界, 上界] 内。

策略权重（设计文档 docs/BID_DESIGN.md §2）：
    前期（早收款）/ 预计工程量增加 → 1.5
    正常 → 1.0
    预计工程量减少 → 0.5
让利（T < 成本总价）时权重反转：预计减项多让、预计增项少让。

单价保留 2 位小数；舍入残差补到工程量最大的未锁项，保证合价加总 == T。
"""
from __future__ import annotations

from typing import Any

#: 策略标签 → 权重
STRATEGY_WEIGHTS: dict[str, float] = {
    "early": 1.5,      # 前期项（早收款）
    "increase": 1.5,   # 预计工程量增加
    "normal": 1.0,     # 正常
    "decrease": 0.5,   # 预计工程量减少
}

_DEFAULT_WEIGHT = 1.0
_MAX_ITER = 100
_EPS = 0.01


def _weight(strategy: str | None, invert: bool, overrides: dict[str, float] | None) -> float:
    table = dict(STRATEGY_WEIGHTS)
    if overrides:
        table.update({k: float(v) for k, v in overrides.items() if float(v) > 0})
    w = table.get((strategy or "normal"), _DEFAULT_WEIGHT)
    return (1.0 / w) if invert and w > 0 else w


def allocate(
    items: list[dict[str, Any]],
    target_total: float,
    m_min: float = 0.0,
    m_max: float = 0.3,
    weights: dict[str, float] | None = None,
    locked: dict[str, float] | None = None,
) -> dict[str, Any]:
    """执行不平衡报价分配。

    items 每项：{"key": str, "qty": float, "cost": float|None,
                 "cap": float|None, "strategy": str|None}
    locked：{key: 单价}，锁定的项不参与分配、金额计入总价。
    返回：{"ok": bool, "reason": str|None, "rows": [...], "totals": {...}}
    """
    locked = locked or {}
    rows: list[dict[str, Any]] = []
    problems: list[str] = []

    target = float(target_total)
    if not items:
        return {"ok": False, "reason": "清单为空", "rows": [], "totals": {}, "problems": problems}

    # ---- 规范化每项：qty/cost/cap/界 ----
    norm: list[dict[str, Any]] = []
    for it in items:
        key = str(it.get("key") or "").strip()
        try:
            qty = float(it.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        cost_raw = it.get("cost")
        try:
            cost = float(cost_raw) if cost_raw is not None and str(cost_raw).strip() != "" else None
        except (TypeError, ValueError):
            cost = None
        if cost is None:
            problems.append(f"{key or '?'}：成本单价缺失，按 0 参与分配")
            cost = 0.0
        cap_raw = it.get("cap")
        try:
            cap = float(cap_raw) if cap_raw is not None and str(cap_raw).strip() != "" else None
        except (TypeError, ValueError):
            cap = None
        lower = cost * (1.0 + m_min)
        upper = cap if cap is not None else cost * (1.0 + m_max)
        if upper < lower:
            # 控制价低于成本下界：上界退化为下界（该项只能报成本价），并提示
            problems.append(f"{key or '?'}：控制价低于成本下界，该项按成本价锁定")
            upper = lower
        norm.append({
            "key": key, "qty": qty, "cost": cost, "cap": cap,
            "strategy": it.get("strategy") or "normal",
            "lower": lower, "upper": upper,
            "name": it.get("name") or "", "unit": it.get("unit") or "",
            "item_id": it.get("item_id") or key,
        })

    active = [n for n in norm if n["qty"] > 0]
    skipped = [n for n in norm if n["qty"] <= 0]

    cost_total = sum(n["cost"] * n["qty"] for n in norm)
    locked_amount = 0.0
    free = []
    for n in active:
        if n["key"] in locked:
            try:
                lp = float(locked[n["key"]])
            except (TypeError, ValueError):
                lp = n["cost"]
            lp = min(max(lp, n["lower"]), n["upper"])
            n["price"] = round(lp, 2)
            n["bound_hit"] = "upper" if lp >= n["upper"] - 1e-9 else ("lower" if lp <= n["lower"] + 1e-9 else None)
            n["locked"] = True
            locked_amount += n["price"] * n["qty"]
        else:
            n["locked"] = False
            free.append(n)

    # ---- 可行性预检 ----
    min_possible = locked_amount + sum(n["lower"] * n["qty"] for n in free)
    max_possible = locked_amount + sum(n["upper"] * n["qty"] for n in free)
    if target < min_possible - _EPS:
        return {"ok": False, "reason": f"目标总价不可达：已低于下界合计 {min_possible:,.2f}（差 {min_possible - target:,.2f}）",
                "rows": [], "totals": {}, "problems": problems}
    if target > max_possible + _EPS:
        return {"ok": False, "reason": f"目标总价不可达：已高于上界合计 {max_possible:,.2f}（差 {target - max_possible:,.2f}）",
                "rows": [], "totals": {}, "problems": problems}

    # ---- 迭代分配 ----
    s_total = target - cost_total - locked_amount  # 待分配利润（相对成本口径，锁定项已剔除）
    invert = s_total < 0
    for n in free:
        n["w"] = _weight(n["strategy"], invert, weights)

    remaining = target - locked_amount  # free 部分需要凑到的合价
    # 先全部按成本价，再把差额按权重分
    prices = {n["key"]: n["cost"] for n in free}
    for _ in range(_MAX_ITER):
        cur_free_total = sum(prices[n["key"]] * n["qty"] for n in free)
        diff = remaining - cur_free_total
        if abs(diff) < _EPS:
            break
        # 只把还有调节空间的项纳入本轮（按差额方向过滤顶界项）
        if diff > 0:
            movable = [n for n in free if prices[n["key"]] < n["upper"] - 1e-9]
        else:
            movable = [n for n in free if prices[n["key"]] > n["lower"] + 1e-9]
        if not movable:
            break
        denom = sum(n["w"] * n["qty"] for n in movable)
        if denom <= 0:
            break
        for n in movable:
            share = diff * (n["w"] * n["qty"]) / denom
            p = prices[n["key"]] + share / n["qty"]
            prices[n["key"]] = min(max(p, n["lower"]), n["upper"])

    for n in free:
        n["price"] = prices[n["key"]]
        if n["price"] >= n["upper"] - 1e-9:
            n["bound_hit"] = "upper"
        elif n["price"] <= n["lower"] + 1e-9:
            n["bound_hit"] = "lower"
        else:
            n["bound_hit"] = None

    # ---- 舍入到分 + 尾差吸收 ----
    # 单价保留 2 位小数；尾差按 1 分步进贪心吸收（从小工程量项开始，
    # 每步总价变化 0.01*qty，小 qty 更不容易 overshoot）。实在吸不掉的
    # （如单项 qty=3、目标 100 元在 2dp 下无解）如实报告，由用户手工微调。
    for n in norm:
        if "price" not in n:
            n["price"] = round(n["cost"], 2)  # qty=0 的跳过项
            n["bound_hit"] = None
        else:
            n["price"] = round(n["price"], 2)

    def _total() -> float:
        return round(sum(n["price"] * n["qty"] for n in norm), 2)

    residual = round(target - _total(), 2)
    if abs(residual) >= 0.005:
        for n in sorted(free, key=lambda x: x["qty"]):
            step = 0.01 if residual > 0 else -0.01
            per_step = round(step * n["qty"], 2)
            if per_step == 0 or abs(per_step) > abs(residual) + 1e-9:
                continue  # 这一步会 overshoot，换更小的项
            new_price = round(n["price"] + step, 2)
            if not (n["lower"] - 1e-9 <= new_price <= n["upper"] + 1e-9):
                continue
            # 连续吃，直到这项顶界或残差小于该项步长
            while abs(residual) >= abs(per_step) - 1e-9:
                new_price = round(n["price"] + step, 2)
                if not (n["lower"] - 1e-9 <= new_price <= n["upper"] + 1e-9):
                    break
                n["price"] = new_price
                n["bound_hit"] = None
                residual = round(target - _total(), 2)
            if abs(residual) < 0.005:
                break
        if abs(residual) >= 0.005:
            problems.append(f"尾差 {residual:,.2f} 元在 2 位小数精度下无法归位，请手工微调某一项单价")

    for n in norm:
        n["amount"] = round(n["price"] * n["qty"], 2)

    actual_total = round(sum(n["amount"] for n in norm), 2)
    profit = round(target - cost_total, 2)

    rows_out = [{
        "key": n["key"], "item_id": n["item_id"], "name": n["name"], "unit": n["unit"],
        "qty": n["qty"], "cost": round(n["cost"], 2),
        "cap": round(n["cap"], 2) if n["cap"] is not None else None,
        "strategy": n["strategy"], "locked": n.get("locked", False),
        "price": n["price"], "amount": n["amount"], "bound_hit": n.get("bound_hit"),
        "lower": round(n["lower"], 2), "upper": round(n["upper"], 2),
    } for n in norm]

    return {
        "ok": True, "reason": None,
        "rows": rows_out,
        "totals": {
            "cost_total": round(cost_total, 2),
            "target_total": round(target, 2),
            "actual_total": actual_total,
            "residual": round(target - actual_total, 2),
            "profit": profit,
            "profit_rate": round(profit / target * 100, 2) if target else 0.0,
            "inverted": invert,
            "locked_amount": round(locked_amount, 2),
        },
        "problems": problems,
    }
