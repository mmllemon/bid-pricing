"""项目执行四表单测：合同 / 成本 / 进度款 / 签证的 CRUD 与汇总口径。"""
import tempfile
from pathlib import Path

import pytest

from bidpricing import sqlite_store


@pytest.fixture()
def db():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp) / "quote.db"


def test_contract_roundtrip(db):
    rec = sqlite_store.exec_save("contract", {
        "project_id": "P1", "contract_no": "HT-2026-001",
        "client": "甲方公司", "amount": 1000000, "signed_at": "2026-01-15",
    }, db=db)
    assert rec["id"]
    rows = sqlite_store.exec_list("contract", "P1", db=db)
    assert len(rows) == 1
    assert rows[0]["contract_no"] == "HT-2026-001"
    assert rows[0]["amount"] == 1000000.0
    # 更新
    rec2 = sqlite_store.exec_save("contract", {
        "id": rec["id"], "project_id": "P1", "amount": 1200000,
    }, db=db)
    assert rec2["amount"] == 1200000.0
    assert sqlite_store.exec_list("contract", "P1", db=db)[0]["amount"] == 1200000.0


def test_cross_project_write_rejected(db):
    rec = sqlite_store.exec_save("cost", {
        "project_id": "P1", "category": "人工", "target": 50000,
    }, db=db)
    with pytest.raises(ValueError):
        sqlite_store.exec_save("cost", {
            "id": rec["id"], "project_id": "P2", "actual": 60000,
        }, db=db)


def test_delete(db):
    rec = sqlite_store.exec_save("visa", {
        "project_id": "P1", "no": "QZ-01", "kind": "签证",
        "amount": 5000, "status": "待批",
    }, db=db)
    assert sqlite_store.exec_delete("visa", rec["id"], db=db) is True
    assert sqlite_store.exec_delete("visa", rec["id"], db=db) is False
    assert sqlite_store.exec_list("visa", "P1", db=db) == []


def test_unknown_table_rejected(db):
    with pytest.raises(ValueError):
        sqlite_store.exec_list("hacker'; DROP TABLE plan;--", "P1", db=db)
    with pytest.raises(ValueError):
        sqlite_store.exec_save("nope", {"project_id": "P1"}, db=db)


def test_summary_project_scope(db):
    sqlite_store.exec_save("contract", {"project_id": "P1", "amount": 1000000}, db=db)
    sqlite_store.exec_save("contract", {"project_id": "P2", "amount": 2000000}, db=db)
    sqlite_store.exec_save("payment", {
        "project_id": "P1", "period": "第1期", "claimed": 300000,
        "status": "已批", "received": 280000,
    }, db=db)
    sqlite_store.exec_save("cost", {
        "project_id": "P1", "category": "人工", "target": 400000, "actual": 420000,
    }, db=db)
    sqlite_store.exec_save("visa", {
        "project_id": "P1", "no": "QZ-01", "amount": 50000, "status": "已批",
    }, db=db)
    sqlite_store.exec_save("visa", {
        "project_id": "P1", "no": "QZ-02", "amount": 30000, "status": "待批",
    }, db=db)

    s = sqlite_store.exec_summary("P1", db=db)
    assert s["contract_total"] == 1000000.0
    assert s["received_total"] == 280000.0
    assert s["receivable"] == 720000.0
    assert s["fund_pressure"] == pytest.approx(0.72)
    assert s["cost_target"] == 400000.0
    assert s["cost_actual"] == 420000.0
    assert s["cost_variance"] == 20000.0  # 正=超支
    assert s["visa_approved"] == 50000.0
    assert s["visa_pending"] == 30000.0


def test_summary_company_scope(db):
    sqlite_store.exec_save("contract", {"project_id": "P1", "amount": 1000000}, db=db)
    sqlite_store.exec_save("contract", {"project_id": "P2", "amount": 2000000}, db=db)
    sqlite_store.exec_save("payment", {"project_id": "P2", "received": 500000}, db=db)
    s = sqlite_store.exec_summary(None, db=db)
    assert s["contract_total"] == 3000000.0
    assert s["received_total"] == 500000.0
    assert s["receivable"] == 2500000.0


def test_summary_empty_project(db):
    s = sqlite_store.exec_summary("PX", db=db)
    assert s["contract_total"] == 0
    assert s["receivable"] == 0
    assert s["fund_pressure"] is None
