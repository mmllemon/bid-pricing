"""部署基础设施（H-012）：按用户隔离输出目录 + 生产访问日志。

不鉴权、只做『目录级隔离』：以运行账号（或 X-User 之类传入的 user）作为命名空间，
项目/方案/结果分别落到 ``outputs/<root>/<user>/`` 下，避免多人共用机器时互相串数据。
日志以 JSONL 追加到 ``outputs/logs/access-YYYY-MM-DD.jsonl``，记录时间/用户/端点和
结果状态，便于审计与排障。
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

#: 用户名允许字符；其它一律转 `_`，杜绝目录穿越。
_SAFE = re.compile(r"[^\w.\-]")
_USER_MAX = 64

#: 单进程内写入互斥。
# FastAPI 中间件每次请求都会调 log_event，异步并发下多个请求可能同时进 open+write，
# Windows 下 `open("a")` 的 write 不保证小于 PIPE_BUF 时原子。用 threading.Lock 让
# 「open → write → close」序列互斥，避免同进程内行错乱。
# 多进程部署（如 uvicorn --workers N）需运维侧确保单 worker，或用文件锁/队列外部协调。
_LOG_LOCK = threading.Lock()


def safe_user(raw: str | None) -> str:
    """把任意身份输入规范成安全目录名；空/超长回落为 ``default``。"""
    s = (_SAFE.sub("_", (raw or "").strip()) or "default").strip("._")
    if not s:
        return "default"
    return s[:_USER_MAX]


def user_scope(base_dir: Path | str, user: str | None) -> Path:
    """返回 ``base_dir/<safe_user>``，并确保目录存在。"""
    p = Path(base_dir) / safe_user(user)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _log_path(log_dir: Path, ts_day: str) -> Path:
    return log_dir / f"access-{ts_day}.jsonl"


def log_event(log_dir: Path | str, user: str | None, endpoint: str, outcome,
              *, project_id: str | None = None, **extra) -> Path:
    """追加一行 JSONL 访问/审计日志；返回日志文件路径（幂等可重复调用）。"""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    line: dict = {"ts": now.isoformat(), "user": safe_user(user),
                  "endpoint": endpoint, "outcome": outcome}
    if project_id:
        line["project_id"] = project_id
    line.update(extra)
    path = _log_path(log_dir, now.date().isoformat())
    with _LOG_LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path