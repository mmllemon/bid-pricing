"""方案持久化的 SQLite 落点（增量第一步）。

只覆盖 ``save_plan / load_plan / list_plans`` 三个入口，签名与
``project_store`` 对齐，便于后续让 ``app.py`` 无缝切换。

设计要点（对应迁移结论）：
- **库为唯一真相**：一个方案 = 库中一行；元数据提成真列，大嵌套块
  （params / all_items / preview / result）作为 JSON 文本列。
- 一次性事务写（``upsert``），天然获得原子性，替代原文件直接覆盖写。
- 库文件沿用 ``PROJECTS_DIR`` 的按用户重定向模型，落在其下
  ``.sqlite/quote.db``，可用 ``db`` 参数替换（测试用临时文件）。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bidpricing.project_store import _iter_plan_files
from bidpricing.group_store import _iter_project_dirs, _groups_path_for, _load_index

PROJECTS_DIR = Path(__file__).resolve().parents[2] / "outputs" / "projects"

#: 元数据真列（从 record 顶层直接取值）；其余进 JSON 列。
_META_COLS = ("name", "project_id", "project_name", "group_id", "strategy",
              "saved_at", "finalized", "finalized_at", "is_copy")
#: 从 params 里提为可查询真列的金额/税率字段。
_PARAM_COLS = ("target_total", "fixed_pretax", "vat_rate", "surtax_rate",
               "ratio_min", "ratio_max")
#: 大嵌套块 → JSON 文本列。
_BLOB_COLS = ("params", "all_items", "preview", "result")

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS plan (
  plan_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  project_id TEXT,
  project_name TEXT,
  group_id TEXT,
  strategy TEXT NOT NULL DEFAULT 'optimal',
  saved_at TEXT NOT NULL,
  finalized INTEGER NOT NULL DEFAULT 0,
  finalized_at TEXT,
  is_copy INTEGER NOT NULL DEFAULT 0,
  target_total REAL,
  fixed_pretax REAL,
  vat_rate REAL,
  surtax_rate REAL,
  ratio_min REAL,
  ratio_max REAL,
  params_json TEXT,
  all_items_json TEXT,
  preview_json TEXT,
  result_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_plan_project ON plan(project_id);
CREATE INDEX IF NOT EXISTS idx_plan_saved   ON plan(saved_at);
CREATE INDEX IF NOT EXISTS idx_plan_amount  ON plan(target_total);

CREATE TABLE IF NOT EXISTS plan_group (
  group_id        TEXT PRIMARY KEY,
  project_id      TEXT,
  project_name    TEXT,
  group_name      TEXT,
  computed_at     TEXT,
  saved_at        TEXT,
  finalized       INTEGER NOT NULL DEFAULT 0,
  finalized_at    TEXT,
  parent_group_id TEXT,
  is_copy         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_group_project ON plan_group(project_id);

CREATE TABLE IF NOT EXISTS plan_slot (
  group_id TEXT NOT NULL REFERENCES plan_group(group_id),
  letter   TEXT NOT NULL,
  strategy TEXT NOT NULL,
  plan_id  TEXT,
  status   TEXT NOT NULL DEFAULT 'pending',
  PRIMARY KEY (group_id, letter)
);

CREATE TABLE IF NOT EXISTS audit_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         TEXT NOT NULL,
  user       TEXT NOT NULL,
  action     TEXT NOT NULL,
  status     TEXT,
  project_id TEXT,
  plan_id    TEXT,
  group_id   TEXT,
  objective  TEXT,
  detail     TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts     ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
"""


def resolve_db_path(db: Path | str | None = None) -> Path:
    """默认库路径在调用时解析，沿用 ``PROJECTS_DIR`` 的按用户重定向口径，
    运行方（如 api/app.py）后赋值 PROJECTS_DIR 即可让库落在对应用户目录下。"""
    if db is None:
        return PROJECTS_DIR / ".sqlite" / "quote.db"
    return Path(db)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db: Path | str | None) -> sqlite3.Connection:
    path = resolve_db_path(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _as_bool(v: Any) -> bool:
    return bool(v)


class PlanOwnershipError(Exception):
    """方案归属冲突：以既有 plan_id 写入不同 project 的记录。

    回归（对抗审查 A2）：find_plan_by_strategy 允许按名称归一键命中既有方案，
    随后 save_plan 对同 plan_id 整行覆盖——若无此拦截，攻击者可把他人方案
    改写成自己的 project_id（接管）。同 plan_id 重存须保持 project_id 不变。
    """


class StoreWriteLockedError(Exception):
    """定稿锁（对抗审查 A4）：已定稿方案/方案组上的写入与删除被拒绝。

    group_store 语义『定稿=整组锁定、三槽位都不能删改』在库层落实：
    save_plan / delete_plan / delete_group / rename_group / upsert_slot 一律拦截，
    唯一的解锁路径是 group_finalize(finalized=False) / mark_finalized(False)。
    """


def _param(rec: dict[str, Any], key: str) -> Any:
    """从 params 取金额/税率真列值（无则 None）。"""
    v = (rec.get("params") or {}).get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    """库行 → 与原 project_store 记录对齐的 dict。"""
    rec: dict[str, Any] = {
        "id": row["plan_id"],
        "name": row["name"],
        "project_id": row["project_id"],
        "project_name": row["project_name"],
        "group_id": row["group_id"],
        "strategy": row["strategy"],
        "saved_at": row["saved_at"],
        "finalized": _as_bool(row["finalized"]),
        "finalized_at": row["finalized_at"],
        "is_copy": _as_bool(row["is_copy"]),
    }
    for col in _BLOB_COLS:
        raw = row[f"{col}_json"]
        rec[col] = json.loads(raw) if raw is not None else {}
    return rec


def save_plan(record: dict[str, Any], plan_id: str | None = None,
              db: Path | str | None = None,
              *, force: bool = False) -> tuple[str, str]:
    """持久化一个方案为一整行；重复保存同 plan_id 覆盖（原子 upsert）。

    返回 (plan_id, saved_at)。

    既有的 plan_id 受两道保护（对抗审查 A2/A4）：
    * 归属：既有行 project_id 与新记录不同 → PlanOwnershipError（整行接管拒绝）；
    * 定稿锁：既有行 finalized=1 且 force=False → StoreWriteLockedError。
    ``force=True`` 仅供库内迁移/测试等显式场景。
    """
    rid = plan_id or uuid.uuid4().hex
    saved_at = record.get("saved_at") or _now_iso()
    conn = _connect(db)
    try:
        if plan_id is not None:
            existing = conn.execute(
                "SELECT project_id, finalized FROM plan WHERE plan_id = ?",
                (plan_id,)).fetchone()
            if existing is not None:
                old_pid, new_pid = existing["project_id"], record.get("project_id")
                if old_pid and new_pid and old_pid != new_pid:
                    raise PlanOwnershipError(
                        f"方案 {plan_id} 已归属项目 {old_pid!r}，"
                        f"拒绝以项目 {new_pid!r} 的记录整行覆盖（需先删旧方案或新建方案）")
                if existing["finalized"] and not force:
                    raise StoreWriteLockedError(
                        f"方案 {plan_id} 已定稿（整组锁定），拒绝写入；"
                        "请先取消定稿（mark_finalized(False) / group_finalize）")
        rows = [{
            "plan_id": rid,
            "name": record.get("name"),
            "project_id": record.get("project_id"),
            "project_name": record.get("project_name"),
            "group_id": record.get("group_id"),
            "strategy": record.get("strategy") or "optimal",
            "saved_at": saved_at,
            "finalized": 1 if record.get("finalized") else 0,
            "finalized_at": record.get("finalized_at"),
            "is_copy": 1 if record.get("is_copy") else 0,
            **{**{c: _param(record, c) for c in _PARAM_COLS},
               **{f"{c}_json": _dump(record.get(c)) for c in _BLOB_COLS}},
        }]
        conn.executemany(
            _UPSERT_SQL,
            rows,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return rid, saved_at


def _dump(v: Any) -> str | None:
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False)


_UPSERT_SQL = f"""
INSERT INTO plan (plan_id, name, project_id, project_name, group_id, strategy,
                  saved_at, finalized, finalized_at, is_copy,
                  target_total, fixed_pretax, vat_rate, surtax_rate, ratio_min, ratio_max,
                  params_json, all_items_json, preview_json, result_json)
VALUES (:plan_id, :name, :project_id, :project_name, :group_id, :strategy,
        :saved_at, :finalized, :finalized_at, :is_copy,
        :target_total, :fixed_pretax, :vat_rate, :surtax_rate, :ratio_min, :ratio_max,
        :params_json, :all_items_json, :preview_json, :result_json)
ON CONFLICT(plan_id) DO UPDATE SET
  name=excluded.name, project_id=excluded.project_id,
  project_name=excluded.project_name, group_id=excluded.group_id,
  strategy=excluded.strategy, saved_at=excluded.saved_at,
  finalized=excluded.finalized, finalized_at=excluded.finalized_at,
  is_copy=excluded.is_copy,
  target_total=excluded.target_total, fixed_pretax=excluded.fixed_pretax,
  vat_rate=excluded.vat_rate, surtax_rate=excluded.surtax_rate,
  ratio_min=excluded.ratio_min, ratio_max=excluded.ratio_max,
  params_json=excluded.params_json, all_items_json=excluded.all_items_json,
  preview_json=excluded.preview_json, result_json=excluded.result_json
"""


def load_plan(plan_id: str, db: Path | str | None = None) -> dict[str, Any] | None:
    conn = _connect(db)
    try:
        row = conn.execute(
            "SELECT * FROM plan WHERE plan_id = ?", (plan_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_record(row)


def list_plans(db: Path | str | None = None) -> list[dict[str, Any]]:
    """列出全部方案（含大字段的完整记录），按 saved_at 倒序。"""
    conn = _connect(db)
    try:
        rows = conn.execute("SELECT * FROM plan ORDER BY saved_at DESC").fetchall()
    finally:
        conn.close()
    return [_row_to_record(r) for r in rows]


def delete_plan(plan_id: str, db: Path | str | None = None) -> bool:
    """删除一个方案行；不存在返回 False。

    已定稿方案拒绝删除（StoreWriteLockedError）；删除时同步清空指向该方案的
    槽位指针（回归 A4：槽位不再悬挂指向已删方案）。"""
    conn = _connect(db)
    try:
        row = conn.execute(
            "SELECT finalized FROM plan WHERE plan_id = ?", (plan_id,)).fetchone()
        if row is None:
            return False
        if row["finalized"]:
            raise StoreWriteLockedError(
                f"方案 {plan_id} 已定稿，拒绝删除；请先取消定稿")
        cur = conn.execute("DELETE FROM plan WHERE plan_id = ?", (plan_id,))
        conn.execute("UPDATE plan_slot SET plan_id = NULL, status = 'pending'"
                     " WHERE plan_id = ?", (plan_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def find_plan_by_strategy(project_key: str, strategy: str = "optimal",
                          db: Path | str | None = None,
                          group_id: str | None = None) -> str | None:
    """按 (项目归一键, 报价策略) 查已有方案，返回 plan_id；未命中返回 None。

    归一键口径与 ``plan_compare.project_key`` 一致，使「固定槽位覆盖」的槽位判定
    与多方案对比的『同一项目』判定使用同一把尺子。group_id 可选：传入时仅在同组
    槽位内匹配；缺省不限组（兼容旧行为）。
    """
    sql = ("SELECT plan_id FROM plan"
           " WHERE (project_id = ? OR project_name = ?) AND strategy = ?")
    params: list[Any] = [project_key, project_key, strategy]
    if group_id:
        sql += " AND group_id = ?"
        params.append(group_id)
    sql += " ORDER BY saved_at DESC"
    conn = _connect(db)
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    for r in rows:
        if r["plan_id"]:
            return r["plan_id"]
    return None


def mark_finalized(plan_id: str, db: Path | str | None = None,
                   finalized: bool = True) -> bool:
    """设定方案的『已定稿』状态。
    finalized=True 打上已定稿标记，且**同一项目下只保留一个已定稿方案**，其余同项目
    方案的定稿自动取消；False 则取消当前方案的定稿。方案不存在返回 False。"""
    conn = _connect(db)
    try:
        row = conn.execute(
            "SELECT project_id, project_name FROM plan WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            return False
        if finalized:
            # 互斥范围 = 同一 project_id（回归 A3：按名称互斥会让「同名不同项目」
            # 的两个项目互相取消定稿；按名称匹配是查询侧特性，不进入定稿互斥）
            if row["project_id"]:
                conn.execute(
                    "UPDATE plan SET finalized = 0, finalized_at = NULL"
                    " WHERE finalized = 1 AND plan_id != ? AND project_id = ?",
                    (plan_id, row["project_id"]),
                )
            conn.execute(
                "UPDATE plan SET finalized = 1,"
                "                finalized_at = COALESCE(finalized_at, ?)"
                " WHERE plan_id = ?",
                (_now_iso(), plan_id),
            )
        else:
            conn.execute(
                "UPDATE plan SET finalized = 0, finalized_at = NULL WHERE plan_id = ?",
                (plan_id,),
            )
        conn.commit()
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 方案组（plan_group + plan_slot）
# ---------------------------------------------------------------------------

_GROUP_SLOT_LETTER = {"optimal": "A", "uniform": "B"}
_SLOT_LETTERS = ("A", "B", "C")


def _slot_key(strategy: str) -> str:
    return _GROUP_SLOT_LETTER.get(strategy, strategy if strategy in _SLOT_LETTERS else "A")


def create_group(project_id: str | None, project_name: str | None,
                 group_name: str | None = None, target_total: Any = None,
                 parent_group_id: str | None = None,
                 db: Path | str | None = None) -> dict[str, Any]:
    """新建一个方案组（含 A/B/C 三个空槽位）；返回组 dict。"""
    now = _now_iso()
    gid = uuid.uuid4().hex
    name = group_name or "目标报价 · 第1组"
    if not group_name and target_total is not None:
        t = ""
        try:
            t = str(int(round(float(target_total))))
        except (TypeError, ValueError):
            pass
        name = f"目标报价{t} · 第1组"
    conn = _connect(db)
    try:
        conn.execute(
            "INSERT INTO plan_group (group_id, project_id, project_name, group_name,"
            " computed_at, saved_at, finalized, finalized_at, parent_group_id, is_copy)"
            " VALUES (?,?,?,?,?,?,0,NULL,?,0)",
            (gid, project_id, project_name, name, now, now, parent_group_id),
        )
        conn.executemany(
            "INSERT INTO plan_slot (group_id, letter, strategy, plan_id, status)"
            " VALUES (?,?,?,NULL,'pending')",
            [(gid, letter, letter) for letter in _SLOT_LETTERS],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _group_snapshot(gid, db)["group"]


def _load_group_row(group_id: str, db: Path | str | None) -> dict[str, Any] | None:
    conn = _connect(db)
    try:
        row = conn.execute(
            "SELECT * FROM plan_group WHERE group_id = ?", (group_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return dict(row)


def _require_group_editable(group_id: str, db: Path | str | None) -> None:
    """可写性守卫：组不存在 → 静默（调用方按原逻辑返回 False）；
    已定稿 → StoreWriteLockedError（回归 A4：定稿=整组锁，挂槽/改名/删组一律拒绝）。"""
    g = _load_group_row(group_id, db)
    if g is not None and g.get("finalized"):
        raise StoreWriteLockedError(
            f"方案组 {group_id} 已定稿（整组锁定），拒绝写入槽位/改名；"
            "请先取消定稿")


def _load_slots(group_id: str, db: Path | str | None) -> dict[str, dict[str, Any]]:
    conn = _connect(db)
    try:
        rows = conn.execute(
            "SELECT letter, strategy, plan_id, status FROM plan_slot"
            " WHERE group_id = ? ORDER BY letter", (group_id,)
        ).fetchall()
    finally:
        conn.close()
    return {r["letter"]: dict(r) for r in rows}


def _slot_summary(pid: str | None, db: Path | str | None = None) -> dict[str, Any] | None:
    if not pid:
        return None
    rec = load_plan(pid, db)
    if rec is None:
        return None
    return {
        "plan_id": pid,
        "strategy": rec.get("strategy") or "optimal",
        "competitive_budget": (rec.get("result") or {}).get("competitive_budget"),
        "objective": (rec.get("result") or {}).get("objective"),
        "profit": ((rec.get("result") or {}).get("profit")
                   or (rec.get("result") or {}).get("net_profit")),
        "target_total": (rec.get("params") or {}).get("target_total"),
        "item_count": len(rec.get("all_items") or []),
        "saved_at": rec.get("saved_at"),
    }


def _group_snapshot(group_id: str, db: Path | str | None) -> dict[str, Any]:
    g = _load_group_row(group_id, db)
    slots = _load_slots(group_id, db)
    for letter, s in slots.items():
        s["summary"] = _slot_summary(s.get("plan_id"), db)
    g["strategy_slots"] = slots
    return {"group": g, "slots": slots}


def find_group_by_id(group_id: str, db: Path | str | None = None) -> dict[str, Any] | None:
    if _load_group_row(group_id, db) is None:
        return None
    return _group_snapshot(group_id, db)["group"]


def find_slot_plan_id(group_id: str, strategy: str,
                      db: Path | str | None = None) -> str | None:
    letters = [strategy, _slot_key(strategy)]
    conn = _connect(db)
    try:
        for letter in letters:
            row = conn.execute(
                "SELECT plan_id FROM plan_slot WHERE group_id = ? AND letter = ?",
                (group_id, letter),
            ).fetchone()
            if row is not None and row["plan_id"]:
                return row["plan_id"]
    finally:
        conn.close()
    return None


def find_group_by_plan_id(plan_id: str, db: Path | str | None = None) -> str | None:
    """查指定 plan_id 归入的组 group_id；找不到返回 None。"""
    conn = _connect(db)
    try:
        row = conn.execute(
            "SELECT group_id FROM plan WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is not None and row["group_id"]:
            return row["group_id"]
        row = conn.execute(
            "SELECT group_id FROM plan_slot WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is not None:
            return row["group_id"]
    finally:
        conn.close()
    return None


def upsert_slot(group_id: str, strategy: str, plan_id: str,
                db: Path | str | None = None) -> bool:
    """把某组指定策略槽位指向 plan_id 并标 computed；组不存在返回 False。"""
    _require_group_editable(group_id, db)
    conn = _connect(db)
    try:
        g = conn.execute(
            "SELECT 1 FROM plan_group WHERE group_id = ?", (group_id,)
        ).fetchone()
        if g is None:
            return False
        conn.execute(
            "INSERT INTO plan_slot (group_id, letter, strategy, plan_id, status)"
            " VALUES (?,?,?,?,'computed')"
            " ON CONFLICT(group_id, letter) DO UPDATE SET"
            " strategy=excluded.strategy, plan_id=excluded.plan_id, status='computed'",
            (group_id, _slot_key(strategy), strategy, plan_id),
        )
        conn.execute(
            "UPDATE plan_group SET saved_at = ? WHERE group_id = ?",
            (_now_iso(), group_id),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rename_group(group_id: str, new_name: str, db: Path | str | None = None) -> bool:
    _require_group_editable(group_id, db)
    conn = _connect(db)
    try:
        g = conn.execute(
            "SELECT group_name FROM plan_group WHERE group_id = ?", (group_id,)
        ).fetchone()
        if g is None:
            return False
        resolved = (new_name or "").strip() or g["group_name"]
        cur = conn.execute(
            "UPDATE plan_group SET group_name = ?, saved_at = ? WHERE group_id = ?",
            (resolved, _now_iso(), group_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def group_finalize(group_id: str, db: Path | str | None = None,
                   finalized: bool = True) -> bool:
    """整组定稿/取消；finalized=False 时清除定稿标记。"""
    # 定稿/取消是唯一的解锁路径，不做可写性检查（对不存在组 rowcount=0 返回 False）
    conn = _connect(db)
    try:
        cur = conn.execute(
            "UPDATE plan_group SET finalized = ?, finalized_at = ?, saved_at = ?"
            " WHERE group_id = ?",
            (1 if finalized else 0,
             _now_iso() if finalized else None, _now_iso(), group_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_groups(db: Path | str | None = None) -> list[dict[str, Any]]:
    """列出全部方案组（含槽位摘要），按 saved_at 倒序。"""
    conn = _connect(db)
    try:
        rows = conn.execute("SELECT group_id FROM plan_group ORDER BY saved_at DESC").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        snap = _group_snapshot(r["group_id"], db)
        out.append(snap["group"])
    return out


def list_groups_for_project(project_key: str,
                            db: Path | str | None = None) -> list[dict[str, Any]]:
    """列出某项目（project_id 或 project_name 归一键）的全部方案组。"""
    conn = _connect(db)
    try:
        rows = conn.execute(
            "SELECT group_id FROM plan_group WHERE project_id = ? OR project_name = ?"
            " ORDER BY saved_at DESC", (project_key, project_key),
        ).fetchall()
    finally:
        conn.close()
    return [_group_snapshot(r["group_id"], db)["group"] for r in rows]


def copy_group(group_id: str, db: Path | str | None = None,
               group_name: str | None = None) -> dict[str, Any] | None:
    """复制整组为独立新组：深拷贝槽位方案行 + 槽位指针；新组可独立改参。

    新组与槽位在同一事务写入；槽位指向拷贝出的新 plan 行（is_copy=1）。
    """
    src = _load_group_row(group_id, db)
    if src is None:
        return None
    src_slots = _load_slots(group_id, db)
    gid = uuid.uuid4().hex
    now = _now_iso()
    name = (group_name or "").strip() or f"{src['group_name']} · 副本"
    conn = _connect(db)
    try:
        conn.execute(
            "INSERT INTO plan_group (group_id, project_id, project_name, group_name,"
            " computed_at, saved_at, finalized, finalized_at, parent_group_id, is_copy)"
            " VALUES (?,?,?,?,?,?,0,?,?,1)",
            (gid, src["project_id"], src["project_name"], name, now, now,
             None, src["group_id"]),
        )
        conn.executemany(
            "INSERT INTO plan_slot (group_id, letter, strategy, plan_id, status)"
            " VALUES (?,?,?,NULL,'pending')",
            [(gid, letter, letter) for letter in _SLOT_LETTERS],
        )
        conn.commit()
    finally:
        conn.close()
    # 深拷贝物理方案行 → 指向新组槽位（各自独占事务，原子性足够）
    for letter, s in src_slots.items():
        pid = (s or {}).get("plan_id")
        if not pid:
            continue
        rec = load_plan(pid, db)
        if rec is None:
            continue
        rec["group_id"] = gid
        rec["is_copy"] = True
        # 副本不继承定稿（与 project_copy 同口径）：新组未定稿，
        # 且副本若带 finalized=1 会触发定稿互斥取消源方案定稿（回归 A3）
        rec["finalized"] = False
        rec["finalized_at"] = None
        dup_id, _ = save_plan(rec, db=db)
        upsert_slot(gid, letter, dup_id, db)
    return find_group_by_id(gid, db)


def delete_group(group_id: str, db: Path | str | None = None,
                 keep_plans: bool = False) -> bool:
    """删除一组；keep_plans=False 时一并删除组内槽位方案行。

    已定稿组拒绝删除（StoreWriteLockedError，回归 A4）。"""
    g = _load_group_row(group_id, db)
    if g is None:
        return False
    if g.get("finalized"):
        raise StoreWriteLockedError(
            f"方案组 {group_id} 已定稿（整组锁定），拒绝删除；请先取消定稿")
    slots = _load_slots(group_id, db)
    conn = _connect(db)
    try:
        if not keep_plans:
            pids = [(s["plan_id"],) for s in slots.values() if s.get("plan_id")]
            if pids:
                conn.executemany("DELETE FROM plan WHERE plan_id = ?", pids)
        conn.execute("DELETE FROM plan_slot WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM plan_group WHERE group_id = ?", (group_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 迁移：把现存 JSON 树幂等归库
# ---------------------------------------------------------------------------

def _iter_json_groups(source_dir: Path):
    """遍历现有项目目录，产出全部方案组 dict（沿用 group_store 的读取逻辑）。"""
    for folder in _iter_project_dirs(source_dir):
        idx = _groups_path_for(folder)
        for g in _load_index(idx):
            yield g


def _upsert_group_row(g: dict[str, Any], db: Path | str | None) -> None:
    conn = _connect(db)
    try:
        conn.execute(
            "INSERT INTO plan_group (group_id, project_id, project_name, group_name,"
            " computed_at, saved_at, finalized, finalized_at, parent_group_id, is_copy)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(group_id) DO UPDATE SET"
            " project_id=excluded.project_id, project_name=excluded.project_name,"
            " group_name=excluded.group_name, computed_at=excluded.computed_at,"
            " saved_at=excluded.saved_at, finalized=excluded.finalized,"
            " finalized_at=excluded.finalized_at, parent_group_id=excluded.parent_group_id,"
            " is_copy=excluded.is_copy",
            (g.get("group_id"), g.get("project_id"), g.get("project_name"),
             g.get("group_name"), g.get("computed_at"), g.get("saved_at"),
             1 if g.get("finalized") else 0, g.get("finalized_at"),
             g.get("parent_group_id"), 1 if g.get("is_copy") else 0),
        )
        conn.commit()
    finally:
        conn.close()


def _upsert_slot_row(group_id: str, letter: str, s: dict[str, Any] | None,
                     db: Path | str | None) -> None:
    s = s or {}
    conn = _connect(db)
    try:
        conn.execute(
            "INSERT INTO plan_slot (group_id, letter, strategy, plan_id, status)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(group_id, letter) DO UPDATE SET"
            " strategy=excluded.strategy, plan_id=excluded.plan_id, status=excluded.status",
            (group_id, letter,
             s.get("strategy") or letter,
             s.get("plan_id"),
             s.get("status") or ("computed" if s.get("plan_id") else "pending")),
        )
        conn.commit()
    finally:
        conn.close()


def import_json_tree(source_dir: Path | str | None = None,
                     db: Path | str | None = None) -> tuple[int, int]:
    """把现有 ``outputs/projects`` 下的 JSON 树幂等归库。

    兼容旧平铺（``<id>.json``）与新项目子目录（``<项目名>/<金额>_<id>.json``）
    两种布局。plan 按 plan_id upsert、plan_group 按 group_id upsert，因此可安全重跑。
    返回 (导入方案数, 导入方案组数)。
    """
    source = PROJECTS_DIR if source_dir is None else Path(source_dir)
    if not source.exists():
        return 0, 0
    plans = 0
    for _p, rec in _iter_plan_files(source):
        rid = rec.get("id")
        if not rid:
            continue
        save_plan(rec, plan_id=rid, db=db, force=True)
        plans += 1
    groups = 0
    for g in _iter_json_groups(source):
        gid = g.get("group_id")
        if not gid:
            continue
        _upsert_group_row(g, db)
        for letter, s in (g.get("strategy_slots") or {}).items():
            if letter in _SLOT_LETTERS:
                _upsert_slot_row(gid, letter, s, db)
        groups += 1
    return plans, groups


# ---------------------------------------------------------------------------
# 审计日志（audit_log）
# ---------------------------------------------------------------------------

def append_audit(user: str, action: str, status: str | None = None,
                 *, project_id: str | None = None, plan_id: str | None = None,
                 group_id: str | None = None, objective: str | None = None,
                 detail: dict[str, Any] | None = None,
                 db: Path | str | None = None) -> int:
    """写一条审计记录；detail 作为 JSON 文本列，避免频繁加列。返回自增 id。"""
    conn = _connect(db)
    try:
        cur = conn.execute(
            "INSERT INTO audit_log (ts, user, action, status, project_id, plan_id,"
            " group_id, objective, detail) VALUES (?,?,?,?,?,?,?,?,?)",
            (_now_iso(), user, action, status, project_id, plan_id, group_id,
             objective, _dump(detail)),
        )
        conn.commit()
        return int(cur.lastrowid)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_audit(db: Path | str | None = None,
               limit: int = 200,
               action: str | None = None,
               user: str | None = None) -> list[dict[str, Any]]:
    """列出审计记录（按 ts 倒序），可过滤 action/user。"""
    conn = _connect(db)
    try:
        sql = "SELECT * FROM audit_log WHERE 1=1"
        params: list[Any] = []
        if action:
            sql += " AND action = ?"
            params.append(action)
        if user:
            sql += " AND user = ?"
            params.append(user)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        params.append(int(limit))
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        rec = dict(r)
        raw = rec.pop("detail", None)
        rec["detail"] = json.loads(raw) if raw else None
        out.append(rec)
    return out
