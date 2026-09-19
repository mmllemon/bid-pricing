"""项目经营概览数据集（H-013）：项目全生命周期参数与阶段流转的持久化。

与方案库存放同一用户目录（outputs/projects/<user>/），采用单个 projects.json
文件保存全部项目记录，默认目录在**调用时**解析（沿用 project_store 的用户隔离约定）。
纯逻辑、不依赖 FastAPI，可独立单测。

阶段(stage)取值：投标 / 中标在建 / 已竣工 / 已结算 / 售后 / 未中标。
派生的三个指标在读取时即时计算，不落盘，避免手工改字段后口径漂移：
    gross_profit  = bid_amount - bid_cost            （项目总毛利）
    gross_margin  = gross_profit / bid_amount          （总毛利率）
    actual_yield  = (actual_revenue - actual_cost) / actual_cost（实际收益率）
所有金额单位统一“元”，前端统一保留 2 位小数。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from bidpricing import project_store

#: 阶段候选值（下拉唯一选项，也是页面分栏依据）。
STAGES = ("投标", "中标在建", "已竣工", "已结算", "售后", "未中标")

_FILE_NAME = "projects.json"
#: 前端可编辑的字段白名单（派生字段与 id/时间戳不在此列）。
EDITABLE = ("name", "short_name", "limit_total", "bid_open_date", "stage", "bid_amount",
            "bid_cost", "actual_cost", "actual_revenue", "settle_amount",
            "completed_at")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dir() -> Path:
    """项目数据集目录：复用 project_store 的按用户命名空间目录（调用时解析）。"""
    return Path(project_store.PROJECTS_DIR)


def _path() -> Path:
    return _dir() / _FILE_NAME


def _num(*values: Any) -> float | None:
    """首个可转数值返回 float，否则返回 None。"""
    for v in values:
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def derive(proj: dict[str, Any]) -> dict[str, Any]:
    """在副本上补三个派生指标（不在原始记录上写），金额保留 2 位小数。"""
    p = {k: v for k, v in proj.items()}
    bid_amount = _num(p.get("bid_amount"))
    bid_cost = _num(p.get("bid_cost"))
    if bid_amount is not None and bid_cost is not None:
        gross = round(bid_amount - bid_cost, 2)
        p["gross_profit"] = gross
        p["gross_margin"] = round(gross / bid_amount, 4) if bid_amount else None
    else:
        p["gross_profit"] = None
        p["gross_margin"] = None
    actual_rev = _num(p.get("actual_revenue"))
    actual_cost = _num(p.get("actual_cost"))
    if actual_rev is not None and actual_cost:
        p["actual_yield"] = round((actual_rev - actual_cost) / actual_cost, 4)
    else:
        p["actual_yield"] = None
    return p


def load_all() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write_all(projects: list[dict[str, Any]]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(projects, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def list_projects() -> list[dict[str, Any]]:
    """返回全部项目（含派生指标），按创建时间倒序。"""
    out = [derive(p) for p in load_all()]
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return out


def get_project(pid: str) -> dict[str, Any] | None:
    for p in load_all():
        if p.get("id") == pid:
            return p
    return None


def create_project(fields: dict[str, Any]) -> dict[str, Any]:
    projects = load_all()
    now = _now_iso()
    rec = {k: fields.get(k) for k in EDITABLE if k in fields}
    if not rec.get("name", "").strip():
        raise ValueError("项目名称不能为空")
    rec.update({
        "id": uuid.uuid4().hex,
        "stage": rec.get("stage") if rec.get("stage") in STAGES else "投标",
        "created_at": now,
        "updated_at": now,
    })
    projects.append(rec)
    _write_all(projects)
    return derive(rec)


def update_project(pid: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """按 id 更新可编辑字段；跨用户隔离由上层按目录保证。返回更新后的记录。"""
    projects = load_all()
    for i, p in enumerate(projects):
        if p.get("id") != pid:
            continue
        for k in EDITABLE:
            if k in fields:
                p[k] = fields[k]
        if fields.get("stage") and fields["stage"] not in STAGES:
            raise ValueError(f"未知的项目阶段：{fields['stage']}")
        p["updated_at"] = _now_iso()
        projects[i] = p
        _write_all(projects)
        return derive(p)
    return None


def delete_project(pid: str) -> bool:
    projects = load_all()
    remaining = [p for p in projects if p.get("id") != pid]
    if len(remaining) == len(projects):
        return False
    _write_all(remaining)
    return True


def finalize(pid: str, bid_amount: Any, bid_cost: Any) -> dict[str, Any] | None:
    """报价定稿回写：只把投标报价金额写回项目并派生毛利/毛利率。

    投标成本测算(bid_cost)由用户在概览手动填写，定稿不回写、不覆盖其原值。
    bid_cost 参数仅为保持调用签名，实际被忽略。
    """
    projects = load_all()
    for i, p in enumerate(projects):
        if p.get("id") != pid:
            continue
        p["bid_amount"] = None if bid_amount is None or bid_amount == "" else round(float(bid_amount), 2)
        p["updated_at"] = _now_iso()
        projects[i] = p
        _write_all(projects)
        return derive(p)
    return None