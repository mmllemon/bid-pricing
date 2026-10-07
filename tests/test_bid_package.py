"""报价包存储单测：用临时目录隔离 PROJECTS_DIR。"""
import json

import pytest

from bidpricing import bid_package
from bidpricing import project_store


@pytest.fixture()
def tmp_projects(tmp_path, monkeypatch):
    d = tmp_path / "projects"
    d.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", d)
    return d


def _pkg(bid_id="BID-001"):
    return {
        "bid_id": bid_id,
        "project_name": "测试工程",
        "version": "v1",
        "status": "测算中",
        "target_total": 100.0,
        "items": [{"key": "A", "qty": 1, "cost": 10.0}],
    }


def test_save_get_list_delete(tmp_projects):
    assert bid_package.save_package(_pkg()) == "BID-001"
    got = bid_package.get_package("BID-001")
    assert got["project_name"] == "测试工程"
    assert got["updated_at"]
    lst = bid_package.list_packages()
    assert len(lst) == 1 and lst[0]["bid_id"] == "BID-001"
    assert lst[0]["item_count"] == 1
    assert bid_package.delete_package("BID-001") is True
    assert bid_package.get_package("BID-001") is None
    assert bid_package.list_packages() == []


def test_bad_id_rejected(tmp_projects):
    with pytest.raises(ValueError):
        bid_package.save_package(_pkg(bid_id="../../evil"))
    with pytest.raises(ValueError):
        bid_package.get_package("..")


def test_items_must_be_list(tmp_projects):
    with pytest.raises(ValueError):
        bid_package.save_package({"bid_id": "BID-002", "items": "nope"})


def test_missing_returns_none(tmp_projects):
    assert bid_package.get_package("NOPE") is None
    assert bid_package.delete_package("NOPE") is False


def test_json_on_disk_is_utf8(tmp_projects):
    bid_package.save_package(_pkg())
    raw = (tmp_projects / "bids" / "BID-001.json").read_bytes()
    assert json.loads(raw.decode("utf-8"))["project_name"] == "测试工程"
