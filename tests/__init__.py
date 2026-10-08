"""测试包。

在包导入时把 ``src/`` 加入 ``sys.path``，使测试无需安装即可运行::

    python -m pytest tests/ -q

口径**必须是 pytest**：本目录有 4 个模块是裸函数 `def test_`（共 31 项），
`unittest discover` 在装了 pytest 的机器上会**跳过它们且不报错、照样报 OK**
（实测；没装时才 FAILED(errors)），数字与 CI 不可比较。CI 固定用 pytest，
见 `.github/workflows/ci.yml` 的「全量测试」步与本仓 `status.py::run_tests` 的口径选择。
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
