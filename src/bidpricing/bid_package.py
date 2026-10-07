"""报价包持久化：不平衡报价的工作成果，落盘为 outputs/projects/<user>/bids/<bid_id>.json。

与井库（well-library.json）同一用户目录，采用“整包读写”模型：
前端编辑报价包 → 整体回写。单用户本机场景无并发写竞争；
写操作走临时文件 + 原子替换，防半截文件。

数据模型见 docs/BID_DESIGN.md §1：BidPackage {id, project_name, 版本, 状态,
target_total, m_min, m_max, items[], results?, updated_at}。

纯逻辑、不依赖 FastAPI，可独立单测。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from bidpricing import project_store

_DIR_NAME = "bids"
#: 报价包数量上限（防前端 bug 刷爆；正常一年几十个项目绰绰有余）。
_MAX_PACKAGES = 200
#: 单包清单项上限（万行清单也够）。
_MAX_ITEMS = 20000
#: 单文件上限 20MB。
_MAX_BYTES = 20 * 1024 * 1024

_BID_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dir() -> Path:
    d = Path(project_store.PROJECTS_DIR) / _DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(bid_id: str) -> Path:
    if not _BID_ID_RE.match(bid_id):
        raise ValueError(f"非法报价包 id：{bid_id!r}")
    p = _dir() / f"{bid_id}.json"
    # 防目录穿越：解析后必须仍在 _dir() 内
    if p.resolve().parent != _dir().resolve():
        raise ValueError(f"非法报价包 id：{bid_id!r}")
    return p


def _check_size(p: Path) -> None:
    try:
        if p.stat().st_size > _MAX_BYTES:
            raise ValueError(f"报价包文件超过 {_MAX_BYTES // 1024 // 1024}MB 上限")
    except OSError:
        pass


def list_packages() -> list[dict[str, Any]]:
    """列出全部报价包摘要（id/项目名/版本/状态/更新时间/项数），按更新时间倒序。"""
    out = []
    for p in sorted(_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if not _BID_ID_RE.match(p.stem):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        items = data.get("items") or []
        out.append({
            "bid_id": p.stem,
            "project_name": data.get("project_name") or "",
            "version": data.get("version") or "",
            "status": data.get("status") or "测算中",
            "target_total": data.get("target_total"),
            "item_count": len(items) if isinstance(items, list) else 0,
            "updated_at": data.get("updated_at") or "",
        })
    return out


def get_package(bid_id: str) -> dict[str, Any] | None:
    """读出单个报价包全文；不存在/损坏返回 None。"""
    p = _path(bid_id)
    _check_size(p)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_package(pkg: dict[str, Any]) -> str:
    """整包覆盖保存。校验失败抛 ValueError（调用方转 400）。返回 bid_id。"""
    if not isinstance(pkg, dict):
        raise ValueError("报价包必须是对象")
    bid_id = str(pkg.get("bid_id") or "").strip()
    if not _BID_ID_RE.match(bid_id):
        raise ValueError("bid_id 非法（字母数字开头，最多 64 字符，仅允许 -_）")
    if len(list_packages()) >= _MAX_PACKAGES and not _path(bid_id).exists():
        raise ValueError(f"报价包最多保存 {_MAX_PACKAGES} 个")
    items = pkg.get("items")
    if not isinstance(items, list):
        raise ValueError("items 必须是数组")
    if len(items) > _MAX_ITEMS:
        raise ValueError(f"清单项最多 {_MAX_ITEMS} 条")
    for i, r in enumerate(items):
        if not isinstance(r, dict):
            raise ValueError(f"第 {i + 1} 项不是对象")
    pkg = dict(pkg)
    pkg["bid_id"] = bid_id
    pkg["updated_at"] = _now_iso()
    p = _path(bid_id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(pkg, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)  # 原子替换
    return bid_id


def delete_package(bid_id: str) -> bool:
    """删除报价包；不存在返回 False。"""
    p = _path(bid_id)
    try:
        p.unlink()
        return True
    except OSError:
        return False
