"""项目文档存储（2026-10-07）：按项目归档文件，解决"资料散在硬盘找不着"。

落盘：outputs/projects/<user>/docs/<project_id>/<文件名>，元数据同目录
.index.json（分类/上传时间/大小）。project_id 必须为经营概览的真实项目 UUID。
纯逻辑、不依赖 FastAPI，可独立单测。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from bidpricing import project_overview
from bidpricing import project_store
from bidpricing.atomic_io import atomic_write_bytes, atomic_write_text

#: 文档分类（前端下拉唯一选项）。
CATEGORIES = ("招标文件", "图纸", "合同", "签证", "结算", "其他")

_DOCS_DIR = "docs"
_INDEX_NAME = ".index.json"
_PID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _docs_root() -> Path:
    """文档根目录：复用 project_store 的按用户命名空间目录（调用时解析）。"""
    return Path(project_store.PROJECTS_DIR) / _DOCS_DIR


def _project_dir(project_id: str) -> Path:
    return _docs_root() / project_id


def _check_pid(project_id: str) -> str:
    """校验 project_id 合法且项目存在，返回清洗后的 id。"""
    pid = (project_id or "").strip()
    if not _PID_RE.match(pid):
        raise ValueError("project_id 非法")
    if project_overview.get_project(pid) is None:
        raise ValueError("项目不存在或已删除")
    return pid


def _safe_name(filename: str) -> str:
    """文件名清洗：只取 basename，去掉路径分隔符与控制字符，空则报错。"""
    base = Path(filename or "").name.strip()
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base)
    base = base.strip(". ")
    if not base:
        raise ValueError("文件名无效")
    # 防止 .index.json 被覆盖/冒充
    if base == _INDEX_NAME:
        base = "_index.json"
    return base


def _load_index(pdir: Path) -> dict[str, Any]:
    idx = pdir / _INDEX_NAME
    if not idx.is_file():
        return {}
    try:
        data = json.loads(idx.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_index(pdir: Path, index: dict[str, Any]) -> None:
    atomic_write_text(pdir / _INDEX_NAME, json.dumps(index, ensure_ascii=False, indent=2))


def _unique_name(pdir: Path, name: str) -> str:
    """同名文件自动加 (2)/(3)… 后缀，避免静默覆盖。"""
    if not (pdir / name).exists():
        return name
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    else:
        suffix = "." + suffix
    i = 2
    while True:
        cand = f"{stem}({i}){suffix}"
        if not (pdir / cand).exists():
            return cand
        i += 1


def list_docs(project_id: str) -> list[dict[str, Any]]:
    """列出某项目文档（含元数据），按上传时间倒序。"""
    pid = _check_pid(project_id)
    pdir = _project_dir(pid)
    index = _load_index(pdir)
    out = []
    for name, meta in index.items():
        fp = pdir / name
        if not fp.is_file():
            continue
        m = dict(meta) if isinstance(meta, dict) else {}
        m["name"] = name
        m.setdefault("size", fp.stat().st_size)
        out.append(m)
    out.sort(key=lambda r: r.get("uploaded_at") or "", reverse=True)
    return out


def save_doc(project_id: str, filename: str, data: bytes,
             category: str = "其他") -> dict[str, Any]:
    """保存一个文档，返回元数据（含最终文件名）。"""
    pid = _check_pid(project_id)
    name = _safe_name(filename)
    cat = (category or "").strip() or "其他"
    if cat not in CATEGORIES:
        raise ValueError(f"未知分类：{cat}（可选：{'、'.join(CATEGORIES)}）")
    pdir = _project_dir(pid)
    pdir.mkdir(parents=True, exist_ok=True)
    name = _unique_name(pdir, name)
    atomic_write_bytes(pdir / name, data)
    meta = {
        "original": Path(filename or "").name,
        "category": cat,
        "size": len(data),
        "uploaded_at": _now_iso(),
    }
    index = _load_index(pdir)
    index[name] = meta
    _save_index(pdir, index)
    return {"name": name, **meta}


def delete_doc(project_id: str, name: str) -> bool:
    """删除一个文档（含元数据），不存在返回 False。"""
    pid = _check_pid(project_id)
    safe = _safe_name(name)
    pdir = _project_dir(pid)
    fp = pdir / safe
    if fp.resolve().parent != pdir.resolve():
        raise ValueError("文件名非法")
    index = _load_index(pdir)
    existed = fp.is_file()
    try:
        fp.unlink(missing_ok=True)
    except OSError:
        return False
    if safe in index:
        del index[safe]
        _save_index(pdir, index)
    return existed


def doc_path(project_id: str, name: str) -> Path | None:
    """取文档磁盘路径（下载用），不存在返回 None。"""
    pid = _check_pid(project_id)
    safe = _safe_name(name)
    fp = _project_dir(pid) / safe
    if not fp.is_file():
        return None
    # 双保险：解析后必须仍在项目目录内
    if fp.resolve().parent != _project_dir(pid).resolve():
        return None
    return fp
