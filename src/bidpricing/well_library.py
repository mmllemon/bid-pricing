"""井库持久化：用户手动保存的井记录，落盘为单个 well-library.json。

与项目经营概览（projects.json）同一用户目录（outputs/projects/<user>/），
采用“整表读写”模型：前端 loadLib 改数组 → saveLib 整表回写。
单用户本机场景无并发写竞争；写操作走临时文件 + 原子替换，防半截文件。

纯逻辑、不依赖 FastAPI，可独立单测。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from bidpricing import project_store

_FILE_NAME = "well-library.json"
#: 记录数上限（井库是手动条目，500 绰绰有余；防前端 bug 刷爆）。
_MAX_ITEMS = 500
#: 单文件上限 20MB（快照含完整钢筋逐根表，localStorage 5MB 配额曾是痛点；落盘后放宽）。
_MAX_BYTES = 20 * 1024 * 1024


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _path() -> Path:
    """库文件路径：调用时解析，沿用 project_store 的按用户重定向约定。"""
    return Path(project_store.PROJECTS_DIR) / _FILE_NAME


def list_records() -> list[dict[str, Any]]:
    """读出全部井记录；文件不存在/损坏返回空列表（损坏时不抛，前端显示空库）。"""
    p = _path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        items = data.get("items", [])
    else:
        items = data
    if not isinstance(items, list):
        return []
    return [r for r in items if isinstance(r, dict) and r.get("id")]


def save_records(items: list[dict[str, Any]]) -> int:
    """整表覆盖保存。校验失败抛 ValueError（调用方转 400）。返回保存条数。"""
    if not isinstance(items, list):
        raise ValueError("items 必须是数组")
    if len(items) > _MAX_ITEMS:
        raise ValueError(f"井库最多保存 {_MAX_ITEMS} 条")
    for i, r in enumerate(items):
        if not isinstance(r, dict) or not str(r.get("id") or "").strip():
            raise ValueError(f"第 {i + 1} 条记录缺少 id")
    payload = {"saved_at": _now_iso(), "items": items}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("井库数据过大（>20MB），请删除部分记录后重试")
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".well-library-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return len(items)
