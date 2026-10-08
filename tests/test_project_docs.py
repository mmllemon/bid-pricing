"""项目文档存储单测：上传/列表/重名/删除/非法输入。"""
import tempfile
from pathlib import Path

import pytest

from bidpricing import project_docs, project_store


@pytest.fixture()
def user_dir(tmp_path, monkeypatch):
    d = tmp_path / "projects"
    d.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", str(d))
    # create_project 写 SQLite，库路走 sqlite_store.resolve_db_path()，读的是
    # sqlite_store.PROJECTS_DIR——两个都要 patch，否则生产库被测试脏数据污染。
    from bidpricing import sqlite_store
    monkeypatch.setattr(sqlite_store, "PROJECTS_DIR", str(d))
    # 造一个真实项目（project_docs 要求项目存在）
    from bidpricing import project_overview
    rec = project_overview.create_project({"name": "测试项目"})
    return d, rec["id"]


def test_save_list_delete(user_dir):
    _, pid = user_dir
    meta = project_docs.save_doc(pid, "招标文件.pdf", b"hello", "招标文件")
    assert meta["name"] == "招标文件.pdf"
    assert meta["category"] == "招标文件"
    assert meta["size"] == 5
    docs = project_docs.list_docs(pid)
    assert len(docs) == 1
    assert docs[0]["original"] == "招标文件.pdf"
    assert project_docs.delete_doc(pid, "招标文件.pdf") is True
    assert project_docs.delete_doc(pid, "招标文件.pdf") is False
    assert project_docs.list_docs(pid) == []


def test_duplicate_name_auto_suffix(user_dir):
    _, pid = user_dir
    m1 = project_docs.save_doc(pid, "a.pdf", b"1")
    m2 = project_docs.save_doc(pid, "a.pdf", b"22")
    assert m1["name"] == "a.pdf"
    assert m2["name"] == "a(2).pdf"
    assert len(project_docs.list_docs(pid)) == 2


def test_bad_project_rejected(user_dir):
    with pytest.raises(ValueError):
        project_docs.save_doc("not-exist", "a.pdf", b"x")
    with pytest.raises(ValueError):
        project_docs.list_docs("../evil")


def test_bad_filename_rejected(user_dir):
    _, pid = user_dir
    with pytest.raises(ValueError):
        project_docs.save_doc(pid, "", b"x")
    # 路径穿越被清洗为 basename
    meta = project_docs.save_doc(pid, "../../etc/passwd", b"x")
    assert "/" not in meta["name"] and "\\" not in meta["name"]
    # .index.json 不能被冒充覆盖
    meta2 = project_docs.save_doc(pid, ".index.json", b"x")
    assert meta2["name"] != ".index.json"


def test_bad_category_rejected(user_dir):
    _, pid = user_dir
    with pytest.raises(ValueError):
        project_docs.save_doc(pid, "a.pdf", b"x", "黑客分类")


def test_doc_path(user_dir):
    _, pid = user_dir
    project_docs.save_doc(pid, "b.pdf", b"data")
    p = project_docs.doc_path(pid, "b.pdf")
    assert isinstance(p, Path) and p.is_file()
    assert project_docs.doc_path(pid, "nope.pdf") is None
