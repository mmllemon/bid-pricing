"""不平衡报价策略（方案 C）单测：solve_unbalanced 经完整管线（H-002 税口→权重分配→调和→payload 同构）。"""
from pathlib import Path

import pytest

from bidpricing.quote_strategies import STRATEGIES, solve_unbalanced

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config"


def _items():
    # cost_tax_scope=EXCL_VAT → H-002 跳过换算，c_i 即有效成本（不含税口径）
    base = {"unit": "m", "q1_point": None, "cost_tax_scope": "EXCL_VAT", "item_name": "测试项"}
    rows = [
        {"item_id": "A", "q0": 100.0, "c_i": 10.0, "cap": 15.0},
        {"item_id": "B", "q0": 200.0, "c_i": 20.0, "cap": 30.0},
        {"item_id": "C", "q0": 50.0, "c_i": 30.0, "cap": 40.0},
    ]
    out = []
    for r in rows:
        d = dict(base)
        d.update(r)
        d["q1_point"] = r["q0"]
        out.append(d)
    return out


def _params(**kw):
    p = {
        "target_total": 7000.0, "fixed_pretax": 0.0, "vat_rate": 0.0, "surtax_rate": 0.0,
        "ratio_min": 0.5, "ratio_max": 1.0,
        "low_ratio_confirmed": True, "low_price_confirmed_by": "测试",
    }
    p.update(kw)
    return p


def _low_policy():
    return {"low_price_threshold": 0.5, "clause_basis": None}


def test_registered_as_third_strategy():
    assert STRATEGIES["unbalanced"] is solve_unbalanced
    assert set(STRATEGIES) == {"optimal", "uniform", "unbalanced"}


def test_weighted_allocation_sums_to_target():
    # vat=0 → budget = target_total；成本合计 6500，目标 7000
    result, payload, code = solve_unbalanced(
        _items(),
        _params(unbalanced_strategies={"A": "early", "B": "normal", "C": "decrease"}),
        _low_policy(), config_dir=CONFIG)
    assert code == 200, payload.get("reason")
    assert result.status == "PASS"
    assert payload["status"] == "PASS"
    total = sum(it["报价合价"] for it in payload["items"] if it["报价合价"] is not None)
    assert total == pytest.approx(7000.0, abs=0.05)
    # 前期项上浮幅度应大于正常项
    by_id = {it["项目编码"]: it for it in payload["items"]}
    assert (by_id["A"]["最优报价单价"] - 10.0) > (by_id["B"]["最优报价单价"] - 20.0) - 1e-6
    # 明细带策略列
    assert by_id["A"]["报价策略"] == "前期"
    assert by_id["C"]["报价策略"] == "预计减"
    # 特有回显
    assert payload["unbalanced"]["profit"] == pytest.approx(500.0, abs=0.05)


def test_default_strategy_is_normal():
    result, payload, code = solve_unbalanced(
        _items(), _params(unbalanced_strategies={}), _low_policy(), config_dir=CONFIG)
    assert code == 200
    by_id = {it["项目编码"]: it for it in payload["items"]}
    assert all(it["报价策略"] == "正常" for it in by_id.values())


def test_invalid_strategy_falls_back_to_normal():
    result, payload, code = solve_unbalanced(
        _items(), _params(unbalanced_strategies={"A": "nonsense"}), _low_policy(), config_dir=CONFIG)
    assert code == 200
    by_id = {it["项目编码"]: it for it in payload["items"]}
    assert by_id["A"]["报价策略"] == "正常"


def test_infeasible_target_returns_422():
    # 上界合计 = 100*15+200*30+50*40 = 9500 < 9600 → 不可达
    result, payload, code = solve_unbalanced(
        _items(), _params(target_total=9600.0), _low_policy(), config_dir=CONFIG)
    assert code == 422
    assert "不可达" in payload["reason"]


def test_payload_isomorphic_with_uniform():
    from bidpricing.quote_strategies import solve_uniform
    _, p_unb, _ = solve_unbalanced(_items(), _params(), _low_policy(), config_dir=CONFIG)
    _, p_uni, _ = solve_uniform(_items(), _params(), _low_policy(), config_dir=CONFIG)
    # 关键契约字段同构（前端 renderResult 无需区分策略）
    for key in ["status", "items", "item_count", "low_ratio_items",
                "unbalanced_clause", "cost_input_tax", "low_price_policy", "low_price_confirmation"]:
        assert key in p_unb, key
        assert key in p_uni, key
    assert set(p_unb["items"][0].keys()) >= set(p_uni["items"][0].keys()) - {"报价策略"}


def test_slot_letter_mapping_covers_all_strategies():
    """回归：新增策略必须有槽位字母映射，否则方案会写错槽位（2026-10-07 实测 unbalanced 写到 A）。"""
    from bidpricing import sqlite_store
    from bidpricing.quote_strategies import STRATEGIES
    for strategy in STRATEGIES:
        letter = sqlite_store._slot_key(strategy)
        assert letter in ("A", "B", "C"), f"{strategy} 无槽位映射"
    assert sqlite_store._slot_key("unbalanced") == "C"
    assert sqlite_store._slot_key("optimal") == "A"
    assert sqlite_store._slot_key("uniform") == "B"
