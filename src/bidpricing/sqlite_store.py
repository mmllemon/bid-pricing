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
-- 项目执行四表（2026-10-07）：收入合同 / 成本台帐 / 进度款 / 签证变更。
-- project_id 统一为经营概览 projects.json 的项目 UUID，与 plan 表同口径。
CREATE TABLE IF NOT EXISTS exec_contract (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  contract_no TEXT,
  client TEXT,
  amount REAL,
  signed_at TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exec_contract_project ON exec_contract(project_id);
CREATE TABLE IF NOT EXISTS exec_cost (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  category TEXT,
  target REAL,
  actual REAL,
  occurred_at TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exec_cost_project ON exec_cost(project_id);
CREATE TABLE IF NOT EXISTS exec_payment (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  period TEXT,
  claimed REAL,
  claimed_at TEXT,
  status TEXT NOT NULL DEFAULT '待审',
  received REAL,
  received_at TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exec_payment_project ON exec_payment(project_id);
CREATE TABLE IF NOT EXISTS exec_visa (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  no TEXT,
  kind TEXT NOT NULL DEFAULT '签证',
  amount REAL,
  status TEXT NOT NULL DEFAULT '待批',
  date TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exec_visa_project ON exec_visa(project_id);
-- 结算（2026-10-07）：送审/审定，支持多轮（初审/终审）。
CREATE TABLE IF NOT EXISTS exec_settlement (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  round TEXT NOT NULL DEFAULT '终审',
  submit_amount REAL,
  submit_date TEXT,
  approved_amount REAL,
  approved_date TEXT,
  status TEXT NOT NULL DEFAULT '未送审',
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exec_settlement_project ON exec_settlement(project_id);
-- 劳务分包（2026-10-07）：分包合同与付款结算。
CREATE TABLE IF NOT EXISTS exec_subcontract (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  subcontractor TEXT,
  scope TEXT,
  amount REAL,
  signed_at TEXT,
  paid REAL,
  settled_amount REAL,
  status TEXT NOT NULL DEFAULT '未开工',
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exec_subcontract_project ON exec_subcontract(project_id);
-- 材料采购（2026-10-07）：材料台帐。
CREATE TABLE IF NOT EXISTS exec_material (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT,
  spec TEXT,
  unit TEXT,
  qty REAL,
  price REAL,
  amount REAL,
  supplier TEXT,
  date TEXT,
  status TEXT NOT NULL DEFAULT '待采购',
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exec_material_project ON exec_material(project_id);
"""


def resolve_db_path(db: Path | str | None = None) -> Path:
    """默认库路径在调用时解析，沿用 ``PROJECTS_DIR`` 的按用户重定向口径，
    运行方（如 api/app.py）后赋值 PROJECTS_DIR 即可让库落在对应用户目录下。"""
    if db is None:
        return PROJECTS_DIR / ".sqlite" / "quote.db"
    return Path(db)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


#: _SCHEMA 建立的对象清单：四表 + 六索引。探测要求**全部齐备**才跳过
#: executescript——为什么连索引一起探：_SCHEMA 里混着 CREATE TABLE 与
#: CREATE INDEX，只探表的话，「建了表但索引没建全」的库（历史版本或
#: 建库中断）会被误判为完整而缺索引。全部 DDL 都是 IF NOT EXISTS，
#: 多跑一次 executescript 只是慢一点，少跑则可能缺对象——探测宁严勿松。
_SCHEMA_OBJECTS = (
    ("table", "plan"), ("table", "plan_group"),
    ("table", "plan_slot"), ("table", "audit_log"),
    ("table", "exec_contract"), ("table", "exec_cost"),
    ("table", "exec_payment"), ("table", "exec_visa"),
    ("table", "exec_settlement"),
    ("table", "exec_subcontract"), ("table", "exec_material"),
    ("index", "idx_plan_project"), ("index", "idx_plan_saved"),
    ("index", "idx_plan_amount"), ("index", "idx_group_project"),
    ("index", "idx_audit_ts"), ("index", "idx_audit_action"),
    ("index", "idx_exec_contract_project"), ("index", "idx_exec_cost_project"),
    ("index", "idx_exec_payment_project"), ("index", "idx_exec_visa_project"),
    ("index", "idx_exec_settlement_project"),
    ("index", "idx_exec_subcontract_project"),
    ("index", "idx_exec_material_project"),
)


def _schema_complete(conn: sqlite3.Connection) -> bool:
    rows = conn.execute(
        "SELECT type, name FROM sqlite_master WHERE type IN ('table','index')"
    ).fetchall()
    present = {(r["type"], r["name"]) for r in rows}
    return all(obj in present for obj in _SCHEMA_OBJECTS)


def _connect(db: Path | str | None) -> sqlite3.Connection:
    path = resolve_db_path(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # busy_timeout：API 并发 / 迁移脚本会多连接写同一库，SQLite 默认遇锁
    # 立即抛 database is locked；给 5s 重试窗口把短锁冲突变成等待而非报错。
    conn.execute("PRAGMA busy_timeout=5000")
    # foreign_keys：plan_slot.group_id 声明了 REFERENCES plan_group(group_id)，
    # 不开此 PRAGMA 该外键只是摆设（SQLite 默认关闭外键强制）。
    conn.execute("PRAGMA foreign_keys=ON")
    # schema 一次化：每连接 executescript 全量建表是纯开销（且在写繁忙时
    # 拉长持锁时间）；对象齐备即跳过，不齐备则全量补齐（幂等）。
    if not _schema_complete(conn):
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


def _group_finalized(conn: sqlite3.Connection, plan_id: str) -> bool:
    """该 plan 是否为**已定稿组**的槽位方案（整组锁的判定口径）。

    锁的对象是组的**槽位**（契约原文：定稿=整组锁定、三槽位都不能删改），
    不是组内全部 plan 行——组内不占槽位的副本/草稿不在锁内（「复制后改参
    重算」是合法工作流）。只查 plan.finalized 行标志不够：group_finalize
    只更新组行、不落槽位方案的标志，照抄行标志会绕过整组锁。
    """
    row = conn.execute(
        "SELECT 1 FROM plan_slot ps JOIN plan_group g ON ps.group_id = g.group_id"
        " WHERE ps.plan_id = ? AND g.finalized = 1 LIMIT 1",
        (plan_id,)).fetchone()
    return row is not None


def save_plan(record: dict[str, Any], plan_id: str | None = None,
              db: Path | str | None = None,
              *, force: bool = False) -> tuple[str, str]:
    """持久化一个方案为一整行；重复保存同 plan_id 覆盖（原子 upsert）。

    返回 (plan_id, saved_at)。

    既有的 plan_id 受两道保护（对抗审查 A2/A4）：
    * 归属：既有行 project_id 与新记录不同 → PlanOwnershipError（整行接管拒绝）；
      新记录 project_id 为 None/空同样拒绝（「拒绝清空归属」）——否则不带
      project_id 的重算/草稿保存会把他人方案的归属静默抹掉，与跨项目接管
      只差一步；
    * 定稿锁：既有行 finalized=1 或其所属组 plan_group.finalized=1 且 force=False
      → StoreWriteLockedError（组锁是**行标志的真相来源**：group_finalize 只更新
      组行，不落槽位方案的 finalized 标志，只查行标志会绕过整组锁）。
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
                if old_pid and not (new_pid or "").strip():
                    if not force:
                        raise PlanOwnershipError(
                            f"方案 {plan_id} 已归属项目 {old_pid!r}，"
                            "新记录 project_id 为空——拒绝清空归属"
                            "（需显式给出同一 project_id，或 force=True / 先删旧方案）")
                elif old_pid and new_pid and old_pid != new_pid:
                    raise PlanOwnershipError(
                        f"方案 {plan_id} 已归属项目 {old_pid!r}，"
                        f"拒绝以项目 {new_pid!r} 的记录整行覆盖（需先删旧方案或新建方案）")
                if existing["finalized"] and not force:
                    raise StoreWriteLockedError(
                        f"方案 {plan_id} 已定稿（整组锁定），拒绝写入；"
                        "请先取消定稿（mark_finalized(False) / group_finalize）")
                if not force and _group_finalized(conn, plan_id):
                    raise StoreWriteLockedError(
                        f"方案 {plan_id} 所属方案组已定稿（整组锁定），拒绝写入；"
                        "请先 group_finalize(False) 取消组定稿")
        _write_plan(conn, record, rid, saved_at)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return rid, saved_at


def _plan_row(record: dict[str, Any], rid: str, saved_at: str) -> dict[str, Any]:
    """记录 dict → plan 表一行参数（save_plan 与 copy_group 共用，保证同构）。"""
    return {
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
    }


def _write_plan(conn: sqlite3.Connection, record: dict[str, Any],
                rid: str, saved_at: str) -> None:
    """save_plan 的核心 upsert，连接由调用方持有（可复用于同一事务）。

    与 save_plan 用**同一份** _UPSERT_SQL、同一份 _plan_row 装配——
    抽成「传入连接」的形式是为了 copy_group 能把新组行、槽位、方案行
    拷贝放进一个事务。归属/定稿守卫不在这里：copy_group 只写全新
    plan_id（uuid），守卫（针对既有行）对副本不适用。
    """
    conn.executemany(_UPSERT_SQL, [_plan_row(record, rid, saved_at)])


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

    已定稿方案或已定稿组的槽位方案拒绝删除（StoreWriteLockedError）；删除时
    同步清空指向该方案的槽位指针（回归 A4：槽位不再悬挂指向已删方案）。"""
    conn = _connect(db)
    try:
        row = conn.execute(
            "SELECT finalized FROM plan WHERE plan_id = ?", (plan_id,)).fetchone()
        if row is None:
            return False
        if row["finalized"]:
            raise StoreWriteLockedError(
                f"方案 {plan_id} 已定稿，拒绝删除；请先取消定稿")
        if _group_finalized(conn, plan_id):
            raise StoreWriteLockedError(
                f"方案 {plan_id} 是已定稿方案组的槽位方案（整组锁定），"
                "拒绝删除；请先 group_finalize(False) 取消组定稿")
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

_GROUP_SLOT_LETTER = {"optimal": "A", "uniform": "B", "unbalanced": "C"}
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


def _write_slot(conn: sqlite3.Connection, group_id: str, strategy: str,
                plan_id: str) -> None:
    """upsert_slot 的核心写，连接由调用方持有（可复用于同一事务）。

    与 upsert_slot 的 SQL 完全同构：槽位指到 plan_id 并标 computed，
    同时刷新组行的 saved_at。"""
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
        _write_slot(conn, group_id, strategy, plan_id)
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

    新组行、空槽位、方案行拷贝、槽位指向全部落在**同一连接的同一事务**里：
    中途任何一步异常即整体回滚，不留「有组无槽」「槽悬空指」的半拷贝状态
    （旧实现先提交组+空槽、再逐方案跨事务拷贝，中途崩掉就是半拷贝）。
    方案行写入复用 ``_write_plan``（与 save_plan 同一份 _UPSERT_SQL，同构），
    槽位写入复用 ``_write_slot``（与 upsert_slot 同构）。
    """
    src = _load_group_row(group_id, db)
    if src is None:
        return None
    src_slots = _load_slots(group_id, db)
    gid = uuid.uuid4().hex
    now = _now_iso()
    name = (group_name or "").strip() or f"{src['group_name']} · 副本"
    # 写事务开始前预取全部源方案记录：读走各自的既有连接，事务里只做写，
    # 避免写锁在手里时再开连接读库。
    copies: list[tuple[str, dict[str, Any], str]] = []
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
        # saved_at 口径与 save_plan 一致：记录自带优先，缺省才取当前时刻
        copies.append((letter, rec, rec.get("saved_at") or _now_iso()))
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
        for letter, rec, saved_at in copies:
            # 与旧实现同口径：save_plan(rec) 不带 plan_id → 全新 uuid 主键
            dup_id = uuid.uuid4().hex
            _write_plan(conn, rec, dup_id, saved_at)
            _write_slot(conn, gid, letter, dup_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
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


# ============ 项目执行四表（2026-10-07）============
#: 前端表名 → sqlite 真表名（API 层用短名校验，防止 SQL 注入式表名拼接）。
_EXEC_TABLES = {
    "contract": "exec_contract",
    "cost": "exec_cost",
    "payment": "exec_payment",
    "visa": "exec_visa",
    "settlement": "exec_settlement",
    "subcontract": "exec_subcontract",
    "material": "exec_material",
}
#: 各表可写字段（id/project_id/created_at/updated_at 由后端管理，不在白名单）。
_EXEC_FIELDS = {
    "contract": ("contract_no", "client", "amount", "signed_at", "note"),
    "cost": ("category", "target", "actual", "occurred_at", "note"),
    "payment": ("period", "claimed", "claimed_at", "status", "received",
                "received_at", "note"),
    "visa": ("no", "kind", "amount", "status", "date", "note"),
    "settlement": ("round", "submit_amount", "submit_date", "approved_amount",
                   "approved_date", "status", "note"),
    "subcontract": ("subcontractor", "scope", "amount", "signed_at", "paid",
                    "settled_amount", "status", "note"),
    "material": ("name", "spec", "unit", "qty", "price", "amount",
                 "supplier", "date", "status", "note"),
}


#: 数值型字段（存 REAL，空/非法转 NULL）。
_MONEY_FIELDS = ("amount", "target", "actual", "claimed", "received",
                 "submit_amount", "approved_amount", "paid", "settled_amount",
                 "qty", "price")


def _exec_table(name: str) -> str:
    try:
        return _EXEC_TABLES[name]
    except KeyError:
        raise ValueError(f"未知执行表：{name}（可选：{', '.join(sorted(_EXEC_TABLES))}）")


def _num_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def exec_list(table: str, project_id: str,
              db: Path | str | None = None) -> list[dict[str, Any]]:
    """列出某项目某执行表的全部记录（按创建时间正序）。"""
    t = _exec_table(table)
    conn = _connect(db)
    try:
        rows = conn.execute(
            f"SELECT * FROM {t} WHERE project_id = ? ORDER BY created_at, id",
            (project_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def exec_save(table: str, rec: dict[str, Any],
              db: Path | str | None = None) -> dict[str, Any]:
    """新增或更新一条执行记录。rec 须含 project_id；id 为空=新增。返回落盘记录。"""
    t = _exec_table(table)
    fields = _EXEC_FIELDS[table]
    pid = (rec.get("project_id") or "").strip()
    if not pid:
        raise ValueError("project_id 不能为空")
    rid = (rec.get("id") or "").strip() or uuid.uuid4().hex
    now = _now_iso()
    provided = set(rec.keys())  # 更新时只碰显式传入的字段，未传的不置 NULL
    data: dict[str, Any] = {"id": rid, "project_id": pid}
    for f in fields:
        if f not in provided:
            continue
        v = rec.get(f)
        if not v and f in ("status", "kind", "round"):
            continue  # 有 NOT NULL DEFAULT 的列：不传/空=用库默认
        if f in _MONEY_FIELDS:
            data[f] = _num_or_none(v)
        else:
            data[f] = (str(v).strip() or None) if v is not None else None
    conn = _connect(db)
    try:
        old = conn.execute(
            f"SELECT project_id, created_at FROM {t} WHERE id = ?", (rid,)).fetchone()
        if old is None:
            data["created_at"] = now
            data["updated_at"] = now
            cols = ", ".join(data.keys())
            conn.execute(f"INSERT INTO {t} ({cols}) VALUES ({', '.join('?' * len(data))})",
                         tuple(data.values()))
        else:
            if old["project_id"] != pid:
                raise ValueError("记录归属项目与传入 project_id 不一致，拒绝跨项目改写")
            data["created_at"] = old["created_at"]
            data["updated_at"] = now
            sets = ", ".join(f"{k} = ?" for k in data if k != "id")
            conn.execute(f"UPDATE {t} SET {sets} WHERE id = ?",
                         tuple(v for k, v in data.items() if k != "id") + (rid,))
        conn.commit()
    finally:
        conn.close()
    return data


def exec_delete(table: str, rid: str, db: Path | str | None = None) -> bool:
    """删除一条执行记录，不存在返回 False。"""
    t = _exec_table(table)
    conn = _connect(db)
    try:
        cur = conn.execute(f"DELETE FROM {t} WHERE id = ?", (rid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _sum_col(conn: sqlite3.Connection, table: str, col: str,
             project_id: str | None) -> float:
    sql = f"SELECT COALESCE(SUM({col}), 0) FROM {table}"
    params: list[Any] = []
    if project_id:
        sql += " WHERE project_id = ?"
        params.append(project_id)
    return float(conn.execute(sql, params).fetchone()[0] or 0)


def exec_summary(project_id: str | None = None,
                 db: Path | str | None = None) -> dict[str, Any]:
    """执行汇总：project_id 为空=全公司口径，否则单项目口径。

    资金口径（元）：
      contract_total  收入合同总额；received_total 累计到账；
      receivable = contract_total - received_total（应收未收）；
      fund_pressure = receivable / contract_total（合同额为 0 时为 None）。
    成本口径：cost_target 目标成本合计；cost_actual 实际成本合计；
      cost_variance = actual - target（正=超支）。
    签证口径：visa_approved 已批签证金额；visa_pending 待批签证金额。
    结算口径：settle_submit 送审金额合计；settle_approved 审定金额合计；
      settle_reduction = submit - approved（审减额，正=审减）。
    分包口径：subcontract_total 分包合同总额；subcontract_paid 已付；
      subcontract_payable = total - paid（应付未付）。
    材料口径：material_total 材料采购总额。
    """
    conn = _connect(db)
    try:
        contract_total = _sum_col(conn, "exec_contract", "amount", project_id)
        received_total = _sum_col(conn, "exec_payment", "received", project_id)
        cost_target = _sum_col(conn, "exec_cost", "target", project_id)
        cost_actual = _sum_col(conn, "exec_cost", "actual", project_id)
        visa_approved = float(conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM exec_visa WHERE status = '已批'"
            + (" AND project_id = ?" if project_id else ""),
            ([project_id] if project_id else [])).fetchone()[0] or 0)
        visa_pending = float(conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM exec_visa WHERE status != '已批'"
            + (" AND project_id = ?" if project_id else ""),
            ([project_id] if project_id else [])).fetchone()[0] or 0)
        settle_submit = _sum_col(conn, "exec_settlement", "submit_amount", project_id)
        settle_approved = _sum_col(conn, "exec_settlement", "approved_amount", project_id)
        subcontract_total = _sum_col(conn, "exec_subcontract", "amount", project_id)
        subcontract_paid = _sum_col(conn, "exec_subcontract", "paid", project_id)
        material_total = _sum_col(conn, "exec_material", "amount", project_id)
    finally:
        conn.close()
    receivable = round(contract_total - received_total, 2)
    return {
        "project_id": project_id,
        "contract_total": round(contract_total, 2),
        "received_total": round(received_total, 2),
        "receivable": receivable,
        "fund_pressure": round(receivable / contract_total, 4) if contract_total else None,
        "cost_target": round(cost_target, 2),
        "cost_actual": round(cost_actual, 2),
        "cost_variance": round(cost_actual - cost_target, 2),
        "visa_approved": round(visa_approved, 2),
        "visa_pending": round(visa_pending, 2),
        "settle_submit": round(settle_submit, 2),
        "settle_approved": round(settle_approved, 2),
        "settle_reduction": round(settle_submit - settle_approved, 2),
        "subcontract_total": round(subcontract_total, 2),
        "subcontract_paid": round(subcontract_paid, 2),
        "subcontract_payable": round(subcontract_total - subcontract_paid, 2),
        "material_total": round(material_total, 2),
    }
