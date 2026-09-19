"""方案持久化（H-007）：把一次报价计算保存为可『打开 / 复制 / 重算』的本地 JSON。

不依赖 FastAPI，可独立单测。每个方案一个 JSON 文件，文件名为该方案的 id。
**按项目名归集到子目录**：``outputs/projects/<用户>/<项目名>/<plan_id>.json``，
避免所有方案平铺在同一目录导致文件名不可区分（方案多了很难管理）。
目录可通过 ``PROJECTS_DIR`` 替换（测试用临时目录），正式运行时取项目 outputs/projects。

向后兼容：旧版把方案直接平铺在 ``<用户>/<plan_id>.json``，读取时两者都兼容；
新保存一律写入项目子目录，若存在同 id 的旧平铺文件会先清除以免重复。
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECTS_DIR = Path(__file__).resolve().parents[2] / "outputs" / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

#: 方案记录中作为"可重算输入"持久化、且允许被 recompute 覆盖的参数。
RECHECK_PARAMS = ("target_total", "fixed_pretax", "vat_rate", "surtax_rate",
                  "ratio_min", "ratio_max", "low_ratio_confirmed", "low_price_confirmed_by")

#: Windows 文件名非法字符（含控制符）。目录名既要防止写入失败，也要防止目录穿越。
_INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_dir(dir_path: Path | None) -> Path:
    """默认目录在**调用时**解析，而不是在函数定义时绑定。
    这样运行方（如 api/app.py 按用户重定向 PROJECTS_DIR）的后赋值才能生效。"""
    return PROJECTS_DIR if dir_path is None else Path(dir_path)


def _safe_folder(name: str | None) -> str:
    """把项目名转成安全的子目录名：剔除非法字符与首尾点/空格，防空串。"""
    s = _INVALID_PATH_CHARS.sub("_", str(name or "")).strip().rstrip(". ")
    return s or "未命名项目"


def _project_dir(dir_path: Path, record: dict[str, Any]) -> Path:
    """项目归集目录；project_name 优先（真实 id 不作目录名），回退 project_id/name。"""
    proj = record.get("project_name") or record.get("project_id") or record.get("name")
    return dir_path / _safe_folder(proj)


def _find_plan_file(dir_path: Path, plan_id: str) -> Path | None:
    """在项目子目录与旧平铺目录中找同名方案文件，返回首个命中。"""
    # 旧平铺文件优先（同名同 id，可能是历史遗留）
    flat = dir_path / f"{plan_id}.json"
    if flat.exists():
        return flat
    if not dir_path.exists():
        return None
    for folder in dir_path.iterdir():
        if folder.is_dir():
            cand = folder / f"{plan_id}.json"
            if cand.exists():
                return cand
            # 新布局：方案文件命名为 "<报价金额>_<id>.json"，按 id 后缀匹配
            match = list(folder.glob(f"*_{plan_id}.json"))
            if match:
                return match[0]
    return None


def _amount_tag(record: dict[str, Any]) -> str:
    """从参数里取目标总报价（投标报价金额），作为方案文件名的可读前缀。"""
    t = (record.get("params") or {}).get("target_total")
    if t is None:
        return "plan"
    try:
        return str(int(round(float(t))))
    except (TypeError, ValueError):
        return "plan"


def _plan_filename(record: dict[str, Any], rid: str) -> str:
    """方案文件命名规则：``<报价金额>_<id>.json``，金额可读、id 保唯一且可按 id 查找。"""
    return f"{_amount_tag(record)}_{rid}.json"


def _summary(rec: dict[str, Any], p: Path) -> dict[str, Any]:
    """方案摘要（不含 items/result 大字段），供列表展示与按项目分组。"""
    items = rec.get("all_items") or []
    return {
        "id": rec.get("id") or p.stem,
        "name": rec.get("name") or p.stem,
        "project_id": rec.get("project_id") or rec.get("name") or p.stem,
        "project_name": rec.get("project_name") or rec.get("name") or p.stem,
        "item_count": len(items),
        "saved_at": rec.get("saved_at"),
        "competitive_budget": (rec.get("result") or {}).get("competitive_budget"),
        "objective": (rec.get("result") or {}).get("objective"),
        "target_total": (rec.get("params") or {}).get("target_total"),
        "finalized": bool(rec.get("finalized")),
        "finalized_at": rec.get("finalized_at"),
    }


def _iter_plan_files(dir_path: Path):
    """依次产出 (plan_file, record) ；兼容旧平铺与新的项目子目录两种布局。"""
    if not dir_path.exists():
        return
    for p in dir_path.glob("*.json"):          # 旧平铺布局（含 projects.json 等）
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(rec, dict):
            yield p, rec
    for folder in sorted(x for x in dir_path.iterdir() if x.is_dir()):
        for p in folder.glob("*.json"):        # 新按项目归集布局
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(rec, dict):
                yield p, rec


def _remove_any_id(dir_path: Path, rid: str) -> None:
    """删除任一布局下已存在的同 id 物理文件，保证一个方案只有一份。"""
    legacy = dir_path / f"{rid}.json"
    try:
        if legacy.exists():
            legacy.unlink()
        if dir_path.exists():
            for folder in dir_path.iterdir():
                for cand in [folder / f"{rid}.json", *folder.glob(f"*_{rid}.json")]:
                    try:
                        if folder.is_dir() and cand.exists():
                            cand.unlink()
                    except OSError:
                        pass
    except OSError:
        pass


def save_plan(record: dict[str, Any], plan_id: str | None = None,
              dir_path: Path | str | None = None) -> tuple[str, str]:
    """持久化一个方案记录，返回 (plan_id, saved_at)。重复保存同 id 会覆盖。

    新方案写入 ``<项目名>`` 子目录（按 project_id/name 归集），删除任一旧布局下
    存在的同 id 文件，保证同一方案始终只有一个物理文件。
    """
    dir_path = _resolve_dir(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    rid = plan_id or uuid.uuid4().hex
    saved_at = record.get("saved_at") or _now_iso()
    stored = dict(record)
    stored["id"] = rid
    stored["saved_at"] = saved_at
    _remove_any_id(dir_path, rid)
    target_dir = _project_dir(dir_path, stored)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / _plan_filename(stored, rid)).write_text(
        json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rid, saved_at


def load_plan(plan_id: str, dir_path: Path | str | None = None) -> dict[str, Any] | None:
    p = _find_plan_file(_resolve_dir(dir_path), plan_id)
    if p is None:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_plans(dir_path: Path | str | None = None) -> list[dict[str, Any]]:
    """列出全部方案摘要（不含 items/result 大字段），按 saved_at 倒序。"""
    dir_path = _resolve_dir(dir_path)
    out: list[dict[str, Any]] = [
        _summary(rec, p) for p, rec in _iter_plan_files(dir_path)
    ]
    out.sort(key=lambda r: r.get("saved_at") or "", reverse=True)
    return out


def delete_plan(plan_id: str, dir_path: Path | str | None = None) -> bool:
    p = _find_plan_file(_resolve_dir(dir_path), plan_id)
    if p is None:
        return False
    p.unlink()
    return True


def _proj_key(rec: dict[str, Any]) -> str:
    """方案所属项目判定键（与归集目录口径一致）。"""
    return rec.get("project_id") or rec.get("name") or rec.get("id") or ""


def mark_finalized(plan_id: str, dir_path: Path | str | None = None,
                   finalized: bool = True) -> bool:
    """设定方案的『已定稿』状态：写入 finalized/finalized_at。
    finalized=True 打上已定稿标记，且**同一项目下只保留一个已定稿方案**，
    其余同项目方案的定稿会被自动取消；False 则取消当前方案的定稿。"""
    dir_path = _resolve_dir(dir_path)
    rec = load_plan(plan_id, dir_path)
    if rec is None:
        return False
    if finalized:
        # 同一项目下已定稿的其他方案自动取消（一个项目只允许一份定稿方案）
        my_key = _proj_key(rec)
        for p, other in _iter_plan_files(dir_path):
            if other.get("id") == plan_id or not other.get("finalized"):
                continue
            if _proj_key(other) != my_key:
                continue
            other.pop("finalized", None)
            other.pop("finalized_at", None)
            save_plan(other, plan_id=other.get("id"), dir_path=dir_path)
        rec["finalized"] = True
        rec["finalized_at"] = rec.get("finalized_at") or _now_iso()
    else:
        rec.pop("finalized", None)
        rec.pop("finalized_at", None)
    save_plan(rec, plan_id=plan_id, dir_path=dir_path)
    return True