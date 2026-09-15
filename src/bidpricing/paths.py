"""仓库路径解析。

config/ 位于仓库根目录（而非包内），便于非开发人员直接编辑配置，
因此代码侧统一通过本模块解析绝对路径，不依赖当前工作目录。
"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """仓库根目录。可用 BIDPRICING_ROOT 覆盖（CI 场景）。"""
    env = os.environ.get("BIDPRICING_ROOT")
    if env:
        return Path(env).resolve()
    # src/bidpricing/paths.py -> bidpricing -> src -> repo root
    return Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    return repo_root() / "config"


def docs_dir() -> Path:
    return repo_root() / "docs"


GATE0_REGISTRY = "gate0_registry.json"

#: 项目级选择项落值文件（adjustment_scope 等）。未选择 = 不写 value 字段。
PROJECT_SELECTION = "project_selection.json"
