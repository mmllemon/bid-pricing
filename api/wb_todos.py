"""工作台域 —— 本地待办（`/api/wb/todos*`）。

为什么建独立模块：
    沿用 P1（`api/wb_proxy.py`）/ P3-a（`api/wb_local.py`）的同一约定——`api/app.py`
    已是 2000+ 行单文件单 app，新域一律另建模块再挂载。

为什么必须注册在 wb_proxy 之前：
    `wb_proxy` 用 `/api/wb/{path:path}` 兜底转发到 Express(:3456)。FastAPI 按注册
    顺序匹配，本模块的具体路径注册在前才能「短路」掉它——前端契约
    （`/api/wb/todos*`）不变，页面零改动。

移植范围（为什么只搬这些）：
    lshu 的待办域共 12 个端点（`index.ts` 7 个 + `productivityRoutes.ts` 5 个），
    其中除 CRUD 外的全部端点都依赖外部数据源：Things / 飞书 / Apple 日历连接器、
    桌面扫描证据（`todo_source_evidence`）、DeepSeek 排程（`plan-day/*`）、
    日历写入（`*/commit`）。P0.1 已实测这些凭证与服务**全部不可用**，且本项目
    从未接入这些连接器——搬过来只能得到「永远返回空/永远报错」的空壳，属于
    `V3_INTEGRATION_PLAN.md` §0 明确拒绝的「占位 UI / 假数据」。
    故本次只收编**待办本体**（标题 / 优先级 / 勾选 / 备注 / 置顶）的存储：
    把母项目原在 `localStorage` 的 `gc-workbench-v2.data.todo` 落到 SQLite，
    并沿用 lshu `todos` 表的 `created_at` / `updated_at` 记账字段。
    `created_at` / `updated_at` 目前无 UI 消费者，保留它们是照抄 lshu 表结构的
    结果，也是排障时唯一的取证线索（本表是持久化存储，不再是浏览器缓存）。

DTO 为什么用 camelCase：
    前端 `workbench.js` 的待办项形状是 `{id,title,note,priority,done,pinned}`。
    直接以 camelCase 出参可省掉 JS 侧的一层字段映射，减少「映射漏字段」的
    出错面。这是与 Express 的**有意偏离**（它的 DTO 是 snake_case + 连接器字段），
    理由：本端点的唯一消费者是本项目前端，且不移植连接器语义。

存储契约：
    · 表名 `wb_todos`，新前缀 `wb_`，不侵入既有 `plan` / `plan_group` /
      `plan_slot` / `audit_log`（红线 5）。
    · 库文件沿用 `sqlite_store.resolve_db_path()`，即
      `outputs/projects/<user>/.sqlite/quote.db`，与项目其余持久化数据同库不同表。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from bidpricing import sqlite_store

router = APIRouter()

#: 本模块版本号，仅用于排障时识别部署批次。
_VERSION = "v3-p3b"

#: 字段长度上限。母项目原 localStorage 实现无任何约束，超长标题会把卡片撑破；
#: 这里按「远大于正常输入」取值，只防异常，不做业务限制。
_MAX_TITLE = 200
_MAX_NOTE = 2000
_MAX_PRIORITY = 8
#: 未指定优先级时的缺省值（对齐前端 `newItem()` 的 P1）。
_DEFAULT_PRIORITY = "P1"
#: 单次批量导入上限（一次性迁移用；母项目 localStorage 里不可能有这么多条目）。
_MAX_IMPORT = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wb_todos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  priority TEXT NOT NULL DEFAULT 'P1',
  done INTEGER NOT NULL DEFAULT 0,
  pinned INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wb_todos_order ON wb_todos(id DESC);
"""


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    """打开本项目用户库并确保 `wb_todos` 就绪。

    不复用 `sqlite_store._connect()`：那是私有函数，且它每次都会探测并校验
    方案域的四表六索引——待办请求没必要为此付出代价。此处只建自己需要的表。
    """
    path = sqlite_store.resolve_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    return conn


def _iso_ms() -> str:
    """产出与 JS `Date.prototype.toISOString()` 同形的字符串（固定 3 位毫秒 + Z）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _row_dto(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "note": row["note"],
        "priority": row["priority"],
        "done": bool(row["done"]),
        "pinned": bool(row["pinned"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# 输入清洗
# ---------------------------------------------------------------------------
def _clean_text(value: object, limit: int) -> str | None:
    """字符串清洗：非字符串返回 None；超长截断（只防异常，不报错）。

    不沿用 JS 的 `String(x)` 强转——那会把 `{title: {}}` 变成 "[object Object]"
    静默入库。浏览器只会送字符串，收紧不影响任何真实调用。
    """
    if not isinstance(value, str):
        return None
    return value.strip()[:limit]


def _clean_priority(value: object) -> str:
    text = _clean_text(value, _MAX_PRIORITY)
    return text or _DEFAULT_PRIORITY


async def _json_object(request: Request) -> dict | None:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001  非 JSON / 空体一律按非法处理
        return None
    return body if isinstance(body, dict) else None


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": "INVALID_REQUEST", "message": message})


def _not_found() -> JSONResponse:
    """与 Express 侧同形（`{code:'NOT_FOUND', message:'待办不存在'}`）。"""
    return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": "待办不存在"})


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@router.get("/api/wb/todos", include_in_schema=False)
async def list_todos() -> JSONResponse:
    """全部待办。顺序 `id DESC` —— 对应前端原有的 `unshift` 语义（新条目在最前）。

    Express 版 `/api/todos` 返回裸数组，此处沿用同一形态。
    """
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM wb_todos ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    return JSONResponse(content=[_row_dto(r) for r in rows])


@router.post("/api/wb/todos", include_in_schema=False)
async def create_todo(request: Request) -> JSONResponse:
    body = await _json_object(request)
    if body is None:
        return _bad_request("请求体必须是 JSON 对象")
    title = _clean_text(body.get("title"), _MAX_TITLE)
    if not title:
        return _bad_request("待办标题不能为空")

    now = _iso_ms()
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO wb_todos (title, note, priority, done, pinned, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                _clean_text(body.get("note"), _MAX_NOTE) or "",
                _clean_priority(body.get("priority")),
                1 if body.get("done") is True else 0,
                1 if body.get("pinned") is True else 0,
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM wb_todos WHERE id = ?", (cur.lastrowid,)).fetchone()
    finally:
        conn.close()
    return JSONResponse(content=_row_dto(row))


@router.post("/api/wb/todos/import", include_in_schema=False)
async def import_todos(request: Request) -> JSONResponse:
    """一次性迁移入口：把前端 localStorage 里的既有待办导入本库。

    必须是单事务（`executemany` + 一次 commit）：迁移到一半失败会留下
    「前端已标记完成、后端只有一半数据」的不可恢复态。非法条目跳过而非整体
    拒绝——迁移的目标是尽量不丢用户数据，一条坏数据不该拖垮其余条目。

    幂等性由调用方保证（仅当后端列表为空时调用）；本端点不做去重——按标题
    去重会误删用户真实存在的同名待办。
    """
    body = await _json_object(request)
    if body is None:
        return _bad_request("请求体必须是 JSON 对象")
    raw = body.get("items")
    if not isinstance(raw, list):
        return _bad_request("items 必须是数组")
    if len(raw) > _MAX_IMPORT:
        return _bad_request(f"单次最多导入 {_MAX_IMPORT} 条")

    now = _iso_ms()
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), _MAX_TITLE)
        if not title:
            continue
        rows.append((
            title,
            _clean_text(item.get("note"), _MAX_NOTE) or "",
            _clean_priority(item.get("priority")),
            1 if item.get("done") is True else 0,
            1 if item.get("pinned") is True else 0,
            now,
            now,
        ))

    conn = _connect()
    try:
        if rows:
            conn.executemany(
                "INSERT INTO wb_todos (title, note, priority, done, pinned, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        result = [_row_dto(r) for r in conn.execute("SELECT * FROM wb_todos ORDER BY id DESC").fetchall()]
    finally:
        conn.close()
    return JSONResponse(content=result)


@router.patch("/api/wb/todos/{todo_id}", include_in_schema=False)
async def update_todo(todo_id: int, request: Request) -> JSONResponse:
    """局部更新。仅接受显式出现的字段——「未传」不等于「置空」。"""
    body = await _json_object(request)
    if body is None:
        return _bad_request("请求体必须是 JSON 对象")

    sets: list[str] = []
    params: list[object] = []
    if "title" in body:
        title = _clean_text(body.get("title"), _MAX_TITLE)
        if not title:
            return _bad_request("待办标题不能为空")
        sets.append("title = ?")
        params.append(title)
    if "note" in body:
        sets.append("note = ?")
        params.append(_clean_text(body.get("note"), _MAX_NOTE) or "")
    if "priority" in body:
        sets.append("priority = ?")
        params.append(_clean_priority(body.get("priority")))
    for key in ("done", "pinned"):
        if key in body:
            value = body.get(key)
            if not isinstance(value, bool):
                return _bad_request(f"{key} 必须是布尔值")
            sets.append(f"{key} = ?")
            params.append(1 if value else 0)

    if not sets:
        return _bad_request("没有可更新的字段")
    sets.append("updated_at = ?")
    params.append(_iso_ms())
    params.append(todo_id)

    conn = _connect()
    try:
        cur = conn.execute(f"UPDATE wb_todos SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        if cur.rowcount == 0:
            return _not_found()
        row = conn.execute("SELECT * FROM wb_todos WHERE id = ?", (todo_id,)).fetchone()
    finally:
        conn.close()
    return JSONResponse(content=_row_dto(row))


@router.delete("/api/wb/todos/{todo_id}", include_in_schema=False)
async def delete_todo(todo_id: int) -> JSONResponse:
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM wb_todos WHERE id = ?", (todo_id,))
        conn.commit()
    finally:
        conn.close()
    if cur.rowcount == 0:
        return _not_found()
    return JSONResponse(content={"ok": True, "id": todo_id})
