"""方案组（PlanGroup）持久化（H-008）：把同项目、同目标总报价下的 A/B/C 多策略
统一成一个「方案组」管理。

组索引存放在项目子目录下的 ``.groups.json``：``outputs/projects/<用户>/<项目名>/.groups.json``。
单方案的物理 JSON 文件不变（仍由 project_store.save_plan 写入 ``<项目名>/<plan_id>.json``），
组索引只记录「组元数据 + 槽位 plan_id 指针」。

组结构：:
    {
        "group_id": "<uuid>",
        "group_name": "目标报价<X> · 第<N>组",
        "project_id": "<项目UUID>",
        "project_name": "展示/目录名",
        "strategy_slots": {
            "A": {"plan_id": "...", "status": "computed"},   # status ∈ pending/computed
            "B": {"plan_id": "...", "status": "pending"},
            "C": {"plan_id": null,  "status": "pending"},
        },
        "computed_at": "ISO",
        "saved_at": "ISO",
        "finalized": false,
        "finalized_at": null,
        "parent_group_id": null,   # 副本来源组；null 表示根组
    }

定稿锁在**整组**：finalized=True 锁定整组（所有槽位不可删改）。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from bidpricing.project_store import (
    PROJECTS_DIR,
    _resolve_dir,
    _safe_folder,
    _now_iso,
    save_plan,
    load_plan,
    delete_plan,
)

# ---------------------------------------------------------------------------
# 低层：组索引文件的定位与读写
# ---------------------------------------------------------------------------


def _groups_path_for(project_dir: Path) -> Path:
    """组索引文件路径：项目目录下的 .groups.json。"""
    return project_dir / ".groups.json"


def _iter_project_dirs(dir_path: Path):
    """产出项目子目录（跳过隐藏项与旧平铺布局）。"""
    if not dir_path.exists():
        return
    for folder in sorted(x for x in dir_path.iterdir() if x.is_dir()):
        if folder.name.startswith("."):
            continue
        yield folder


def _load_index(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = data.get("groups") if isinstance(data, dict) else data
        return groups if isinstance(groups, list) else []
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def _save_index(path: Path, groups: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"groups": groups}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _project_dir_for(project_name: str | None, project_id: str | None,
                     dir_path: Path) -> Path:
    return dir_path / _safe_folder(project_name or project_id or "未命名项目")


def _locate_groups(project_dir: Path) -> Path:
    return _groups_path_for(project_dir)


def _find_index(project_key: str, dir_path: Path) -> Path | None:
    """按项目归一键（project_id or name）找其 .groups.json；找不到返回 None。

    需在启动迁移后调用，确保旧单方案已并组。按 project_id 优先匹配，回退 name。
    """
    for folder in _iter_project_dirs(dir_path):
        p = _locate_groups(folder)
        if not p.exists():
            continue
        for g in _load_index(p):
            if g.get("project_id") == project_key or g.get("project_name") == project_key:
                return p
    return None


# ---------------------------------------------------------------------------
# 组对象工具
# ---------------------------------------------------------------------------

def _new_group(project_id: str | None, project_name: str | None,
               group_name: str | None = None,
               parent_group_id: str | None = None) -> dict[str, Any]:
    now = _now_iso()
    return {
        "group_id": uuid.uuid4().hex,
        "group_name": group_name or f"目标报价 · 第1组",
        "project_id": project_id or "",
        "project_name": project_name or "",
        "strategy_slots": {
            "A": {"plan_id": None, "status": "pending"},
            "B": {"plan_id": None, "status": "pending"},
            "C": {"plan_id": None, "status": "pending"},
        },
        "computed_at": now,
        "saved_at": now,
        "finalized": False,
        "finalized_at": None,
        "parent_group_id": parent_group_id,
    }


def _default_group_name(groups: list[dict[str, Any]], target_total: Any) -> str:
    """默认组名：目标报价 + 序号（第 N 组）。"""
    seq = len(groups) + 1
    t = ""
    try:
        t = str(int(round(float(target_total))))
    except (TypeError, ValueError):
        pass
    return f"目标报价{t} · 第{seq}组"


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------

def list_groups(dir_path: Path | str | None = None) -> list[dict[str, Any]]:
    """列出全部方案组（含槽位指针与各槽位方案摘要），按 saved_at 倒序。

    未迁移时先触发归组迁移。
    """
    dir_path = _resolve_dir(dir_path)
    migrate_dangling(dir_path)
    out: list[dict[str, Any]] = []
    for folder in _iter_project_dirs(dir_path):
        p = _locate_groups(folder)
        for g in _load_index(p):
            out.append(_group_with_slot_summaries(g, dir_path))
    out.sort(key=lambda g: g.get("saved_at") or "", reverse=True)
    return out


def list_groups_for_project(project_key: str, dir_path: Path | str | None = None) -> list[dict[str, Any]]:
    """列出某项目（project_id or name 归一键）的全部方案组，按 saved_at 倒序。"""
    dir_path = _resolve_dir(dir_path)
    idx = _find_index(project_key, dir_path)
    if idx is None:
        return []
    groups = [_group_with_slot_summaries(g, dir_path) for g in _load_index(idx)]
    groups.sort(key=lambda g: g.get("saved_at") or "", reverse=True)
    return groups


def find_group_by_id(group_id: str, dir_path: Path | str | None = None)\
        -> tuple[dict[str, Any], Path] | None:
    dir_path = _resolve_dir(dir_path)
    for folder in _iter_project_dirs(dir_path):
        p = _locate_groups(folder)
        for g in _load_index(p):
            if g.get("group_id") == group_id:
                return g, p
    return None


def find_recent_group(project_key: str, dir_path: Path | str | None = None) -> dict[str, Any] | None:
    """某项目最近保存的方案组（saved_at 最新）。"""
    groups = list_groups_for_project(project_key, dir_path)
    if not groups:
        return None
    return max(groups, key=lambda g: g.get("saved_at") or "")


def find_slot_plan_id(group_id: str, strategy: str, dir_path: Path | str | None = None) -> str | None:
    """查某组指定策略槽位已计算的 plan_id；未命中返回 None。"""
    hit = find_group_by_id(group_id, dir_path)
    if hit is None:
        return None
    slot = hit[0].get("strategy_slots") or {}
    for key in (strategy, {"optimal": "A", "uniform": "B"}.get(strategy, strategy)):
        s = slot.get(key)
        if s and s.get("plan_id"):
            return s["plan_id"]
    return None


def find_group_by_plan_id(plan_id: str, dir_path: Path | str | None = None) -> str | None:
    """查指定 plan_id 归入的组 group_id；找不到返回 None。"""
    dir_path = _resolve_dir(dir_path)
    rec = load_plan(plan_id, dir_path) or {}
    if rec.get("group_id"):
        return rec["group_id"]
    # 回退：扫所有组索引，找引用此 plan_id 的组
    for folder in _iter_project_dirs(dir_path):
        idx_path = _locate_groups(folder)
        for g in _load_index(idx_path):
            for s in (g.get("strategy_slots") or {}).values():
                if (s or {}).get("plan_id") == plan_id:
                    return g.get("group_id")
    return None


def create_group(project_id: str | None, project_name: str | None,
                 group_name: str | None = None, target_total: Any = None,
                 parent_group_id: str | None = None,
                 dir_path: Path | str | None = None) -> dict[str, Any]:
    """新建一个方案组并写入索引；返回组 dict。"""
    dir_path = _resolve_dir(dir_path)
    project_dir = _project_dir_for(project_name, project_id, dir_path)
    idx_path = _locate_groups(project_dir)
    groups = _load_index(idx_path)
    g = _new_group(project_id, project_name, group_name, parent_group_id)
    if not group_name and target_total is not None:
        g["group_name"] = _default_group_name(groups, target_total)
    g["saved_at"] = _now_iso()
    groups.append(g)
    _save_index(idx_path, groups)
    return g


def upsert_slot(group_id: str, strategy: str, plan_id: str,
                dir_path: Path | str | None = None) -> bool:
    """把某组指定策略槽位指向 plan_id 并标 computed；找不到组返回 False。"""
    hit = find_group_by_id(group_id, dir_path)
    if hit is None:
        return False
    g, idx_path = hit
    slot_key = {"optimal": "A", "uniform": "B"}.get(strategy, strategy)
    g.setdefault("strategy_slots", {})
    g["strategy_slots"][slot_key] = {"plan_id": plan_id, "status": "computed"}
    g["saved_at"] = _now_iso()
    _update_group(idx_path, g)
    return True


def _update_group(idx_path: Path, target: dict[str, Any]) -> None:
    groups = _load_index(idx_path)
    for i, g in enumerate(groups):
        if g.get("group_id") == target.get("group_id"):
            groups[i] = target
            break
    else:
        groups.append(target)
    _save_index(idx_path, groups)


def rename_group(group_id: str, new_name: str, dir_path: Path | str | None = None) -> bool:
    hit = find_group_by_id(group_id, dir_path)
    if hit is None:
        return False
    g, idx_path = hit
    g["group_name"] = (new_name or "").strip() or g["group_name"]
    g["saved_at"] = _now_iso()
    _update_group(idx_path, g)
    return True


def group_finalize(group_id: str, dir_path: Path | str | None = None,
                   finalized: bool = True) -> bool:
    """整组定稿/取消。定稿锁锁整组（三个槽位都不能删改）。"""
    hit = find_group_by_id(group_id, dir_path)
    if hit is None:
        return False
    g, idx_path = hit
    if finalized:
        g["finalized"] = True
        g["finalized_at"] = g.get("finalized_at") or _now_iso()
    else:
        g["finalized"] = False
        g["finalized_at"] = None
    g["saved_at"] = _now_iso()
    _update_group(idx_path, g)
    return True


def copy_group(group_id: str, dir_path: Path | str | None = None,
               group_name: str | None = None) -> dict[str, Any] | None:
    """复制整组为独立新组：深拷贝物理方案文件 + 槽位指针；新组可独立改参。"""
    dir_path = _resolve_dir(dir_path)
    hit = find_group_by_id(group_id, dir_path)
    if hit is None:
        return None
    src, idx_path = hit
    new = _new_group(
        src.get("project_id"), src.get("project_name"),
        group_name or f"{src.get('group_name')} · 副本",
        parent_group_id=src.get("group_id"),
    )
    new["saved_at"] = _now_iso()
    new_slots: dict[str, Any] = {}
    for slot_key, s in (src.get("strategy_slots") or {}).items():
        src_pid = (s or {}).get("plan_id")
        if not src_pid:
            new_slots[slot_key] = {"plan_id": None, "status": "pending"}
            continue
        rec = load_plan(src_pid, dir_path)
        if rec is None:
            new_slots[slot_key] = {"plan_id": None, "status": "pending"}
            continue
        rec["group_id"] = new["group_id"]
        rec["is_copy"] = True
        dup_id, _ = save_plan(rec, dir_path=dir_path)
        new_slots[slot_key] = {"plan_id": dup_id, "status": "computed"}
    new["strategy_slots"] = new_slots
    groups = _load_index(idx_path)
    groups.append(new)
    _save_index(idx_path, groups)
    return new


def delete_group(group_id: str, dir_path: Path | str | None = None,
                 keep_plans: bool = False) -> bool:
    """删除一组；keep_plans=False 时一并删除组内槽位方案物理文件。"""
    hit = find_group_by_id(group_id, dir_path)
    if hit is None:
        return False
    g, idx_path = hit
    if not keep_plans:
        for s in (g.get("strategy_slots") or {}).values():
            pid = (s or {}).get("plan_id")
            if pid:
                delete_plan(pid, dir_path)
    groups = _load_index(idx_path)
    groups = [x for x in groups if x.get("group_id") != group_id]
    _save_index(idx_path, groups)
    return True


# ---------------------------------------------------------------------------
# 摘要组装与迁移
# ---------------------------------------------------------------------------

_SLOT_LETTER = {"optimal": "A", "uniform": "B"}


def _group_with_slot_summaries(group: dict[str, Any], dir_path: Path) -> dict[str, Any]:
    g = dict(group)
    slots: dict[str, Any] = {}
    for slot_key, s in (g.get("strategy_slots") or {}).items():
        entry = dict(s or {"plan_id": None, "status": "pending"})
        pid = entry.get("plan_id")
        entry["summary"] = None
        if pid and (rec := load_plan(pid, dir_path)):
            entry["summary"] = {
                "plan_id": pid,
                "strategy": ({v: k for k, v in _SLOT_LETTER.items()}).get(slot_key, "optimal"),
                "competitive_budget": (rec.get("result") or {}).get("competitive_budget"),
                "objective": (rec.get("result") or {}).get("objective"),
                "profit": ((rec.get("result") or {}).get("profit")
                           or (rec.get("result") or {}).get("net_profit")),
                "target_total": (rec.get("params") or {}).get("target_total"),
                "item_count": len(rec.get("all_items") or []),
                "saved_at": rec.get("saved_at"),
            }
        slots[slot_key] = entry
    g["strategy_slots"] = slots
    return g


def migrate_dangling(dir_path: Path | str | None = None) -> int:
    """把旧「无 .groups.json」的单方案归入方案组（幂等）。

    规则：
    - 某项目目录下若已有 .groups.json 则跳过（已迁移）。
    - 否则该项目下所有单方案：同名最近（saved_at）的基础方案入第 1 组并按其
      strategy 放在对应槽位；其余归入「历史组 N」对应 strategy 槽位。
    - 同项目多份已定稿压缩为整组定稿（取最近定稿）。
    返回本次新建的组数。
    """
    dir_path = _resolve_dir(dir_path)
    created = 0
    for folder in _iter_project_dirs(dir_path):
        idx_path = _locate_groups(folder)
        if idx_path.exists():
            continue
        plans = []
        for p in folder.glob("*.json"):
            if p.name.startswith("."):
                continue
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(rec, dict) and rec.get("id"):
                plans.append(rec)
        if not plans:
            continue
        plans.sort(key=lambda r: r.get("saved_at") or "", reverse=True)
        # 基础组 = 最近一份；其余为历史组
        base = plans[0]
        g = _new_group(
            base.get("project_id") or base.get("name"),
            base.get("project_name") or base.get("name"),
            group_name=f"目标报价 · 第1组",
        )
        g["saved_at"] = base.get("saved_at") or _now_iso()
        if base.get("finalized"):
            g["finalized"] = True
            g["finalized_at"] = base.get("finalized_at") or _now_iso()
        g["strategy_slots"] = _slot_from_plan(base)
        groups = [g]
        history_n = 1
        for rec in plans[1:]:
            hg = _copy_group_for_migration(rec, folder.name, history_n)
            if hg is not None:
                groups.append(hg)
                history_n += 1
        _save_index(idx_path, groups)
        created += 1
    return created


def _slot_from_plan(rec: dict[str, Any]) -> dict[str, Any]:
    strat = rec.get("strategy") or "optimal"
    slot_key = _SLOT_LETTER.get(strat, strat if strat in ("A", "B", "C") else "A")
    slots = {"A": {"plan_id": None, "status": "pending"},
             "B": {"plan_id": None, "status": "pending"},
             "C": {"plan_id": None, "status": "pending"}}
    slots[slot_key if slot_key in slots else "A"] = {
        "plan_id": rec.get("id"), "status": "computed",
    }
    return slots


def _copy_group_for_migration(rec: dict[str, Any], project_name: str,
                              n: int) -> dict[str, Any] | None:
    g = _new_group(rec.get("project_id") or rec.get("name"),
                   rec.get("project_name") or project_name,
                   group_name=f"历史组 {n}")
    g["saved_at"] = rec.get("saved_at") or _now_iso()
    if rec.get("finalized"):
        g["finalized"] = True
        g["finalized_at"] = rec.get("finalized_at") or _now_iso()
    g["strategy_slots"] = _slot_from_plan(rec)
    return g