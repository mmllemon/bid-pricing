"""测试包。

在包导入时把 ``src/`` 加入 ``sys.path``，使测试无需安装即可运行::

    python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
