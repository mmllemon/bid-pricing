"""原子文件写：同目录临时文件 + ``os.replace``，消灭「写到一半崩溃留下截断 JSON」。

全仓所有**状态型**持久文件（方案 JSON、组索引、导入登记表、受控制品注册表、
选择项落值、冻结制品）统一走本入口。``os.replace`` 在同一卷内是原子操作：
读者要么看到完整旧文件、要么看到完整新文件，不存在半成品状态。

报告类输出（解析日志、对比报告等可再生文件）不强制走这里，但走了也无害。

``project_overview._write_all`` 历史上是一份自造的 tmp+replace 内联实现（临时名
固定、无 fsync），已于 2026-10-08 并入本模块（B-P1-3）。全仓状态型持久文件
统一走本入口，不再手写。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = ["atomic_write_bytes", "atomic_write_text"]


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    """原子地写入字节。崩溃/断电时目标文件保持旧内容完整。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path | str, text: str) -> None:
    """原子地写入 UTF-8 文本。"""
    atomic_write_bytes(path, text.encode("utf-8"))
