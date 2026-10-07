"""不平衡报价分配器单测（纯逻辑，无 I/O）。"""
import pytest

from bidpricing.unbalanced import allocate


def _items():
    return [
        {"key": "A", "qty": 100, "cost": 10.0, "cap": 15.0, "strategy": "early"},
        {"key": "B", "qty": 200, "cost": 20.0, "cap": 30.0, "strategy": "normal"},
        {"key": "C", "qty": 50, "cost": 30.0, "cap": 40.0, "strategy": "decrease"},
    ]


def _by_key(res):
    return {r["key"]: r for r in res["rows"]}


def test_exact_total():
    # 成本总价 = 100*10+200*20+50*30 = 6500；目标 7000 → 利润 500
    res = allocate(_items(), 7000)
    assert res["ok"]
    assert res["totals"]["actual_total"] == pytest.approx(7000, abs=0.05)
    assert res["totals"]["profit"] == pytest.approx(500, abs=0.05)
    rows = _by_key(res)
    # 前期项 early 权重 1.5，应比 normal 项单价上浮更多
    assert (rows["A"]["price"] - 10.0) > (rows["B"]["price"] - 20.0) - 1e-6


def test_decrease_gets_less():
    res = allocate(_items(), 7000)
    rows = _by_key(res)
    # decrease 权重 0.5，上浮幅度应小于 normal
    assert (rows["C"]["price"] - 30.0) < (rows["B"]["price"] - 20.0) + 1e-6


def test_invert_on_discount():
    # 目标低于成本 → 让利，权重反转：decrease 项多让（需允许 m_min 为负）
    res = allocate(_items(), 6000, m_min=-0.10)
    assert res["ok"]
    assert res["totals"]["inverted"] is True
    assert res["totals"]["actual_total"] == pytest.approx(6000, abs=0.05)
    rows = _by_key(res)
    assert (30.0 - rows["C"]["price"]) > (20.0 - rows["B"]["price"]) - 1e-6


def test_cap_clamp_and_infeasible():
    items = _items()
    # 目标高到所有项都顶到控制价仍不够 → 不可达
    # 上界合计 = 100*15+200*30+50*40 = 9500
    res = allocate(items, 9600)
    assert not res["ok"] and "不可达" in res["reason"]
    # 目标 9400：可行，但应有顶界项
    res = allocate(items, 9400)
    assert res["ok"]
    assert res["totals"]["actual_total"] == pytest.approx(9400, abs=0.05)
    rows = _by_key(res)
    assert any(r["bound_hit"] == "upper" for r in rows.values())


def test_below_lower_infeasible():
    # 下界合计 = 成本合计 = 6500（m_min=0）
    res = allocate(_items(), 6000, m_min=0.05)
    # 下界 = 6500*1.05 = 6825 > 6000 → 不可达
    assert not res["ok"]


def test_locked_items():
    res = allocate(_items(), 7000, locked={"B": 22.0})
    assert res["ok"]
    rows = _by_key(res)
    assert rows["B"]["price"] == 22.0 and rows["B"]["locked"] is True
    assert res["totals"]["actual_total"] == pytest.approx(7000, abs=0.05)


def test_zero_qty_skipped():
    items = _items() + [{"key": "Z", "qty": 0, "cost": 99.0, "cap": 199.0, "strategy": "normal"}]
    res = allocate(items, 7000)
    assert res["ok"]
    assert res["totals"]["actual_total"] == pytest.approx(7000, abs=0.05)


def test_cap_below_cost_degrades():
    items = [{"key": "X", "qty": 10, "cost": 100.0, "cap": 90.0, "strategy": "normal"}]
    res = allocate(items, 1000)
    assert res["ok"]
    rows = _by_key(res)
    assert rows["X"]["price"] == 100.0  # 按成本价锁定
    assert any("控制价低于成本下界" in p for p in res["problems"])


def test_rounding_residual_absorbed():
    # 构造舍入残差：3 项单价 10/3 之类
    items = [
        {"key": "A", "qty": 3, "cost": 10.0, "cap": 20.0, "strategy": "normal"},
        {"key": "B", "qty": 3, "cost": 10.0, "cap": 20.0, "strategy": "normal"},
        {"key": "C", "qty": 3, "cost": 10.0, "cap": 20.0, "strategy": "normal"},
    ]
    res = allocate(items, 100)  # 每项 11.111... → 舍入残差
    assert res["ok"]
    assert res["totals"]["actual_total"] == pytest.approx(100, abs=0.05)
    assert abs(res["totals"]["residual"]) < 0.05
