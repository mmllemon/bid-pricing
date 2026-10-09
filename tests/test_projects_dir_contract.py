"""PROJECTS_DIR 的消费契约：所有读取方必须同时接受 str 与 Path。

动因（2026-10-08 实测，CI 全量测试首次执行时 6 项 error）：
`project_store.PROJECTS_DIR` 与 `sqlite_store.PROJECTS_DIR` 是**两个同名全局**，
按设计都允许运行方（api/app.py 按用户隔离）与测试在事后重定向。但两者的消费写法
一度不一致：

    project_store._resolve_dir()      ->  Path(dir_path) 包过，赋 str 可用
    sqlite_store.resolve_db_path()    ->  PROJECTS_DIR / ".sqlite" 直接 `/`，赋 str 即
                                           TypeError: unsupported operand type(s) for /

于是「照抄邻居那行的 `str(d)` 写法」就能静默炸。更糟的是这个 bug **藏了很久**：
那 4 个 pytest 风格模块是裸函数 `def test_`，`unittest discover` 根本不收集它们
（见 requirements-dev.txt 与 status.py::run_tests 的口径说明），只有 CI 第一次
真正用 pytest 跑全量时才暴露。

本测试不是测某个函数返回值，而是钉住**跨模块的一致性**：把两个全局分别赋成
str 与 Path，四种组合下所有路径产出点都不得抛 TypeError。以后新增读取方
（或有人又把 Path() 去掉），这里会红。
"""
from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path

from bidpricing import (
    group_store,
    project_docs,
    project_overview,
    project_store,
    sqlite_store,
    well_library,
)

#: 暴露或转暴露 PROJECTS_DIR 的模块；重定向必须对全体一致生效。
_MODULES = (project_store, sqlite_store, group_store)


class ProjectsDirTypeContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self._saved = {m: m.PROJECTS_DIR for m in _MODULES}

    def tearDown(self) -> None:
        for m, v in self._saved.items():
            m.PROJECTS_DIR = v
        self.tmp.cleanup()

    def _point_all(self, value) -> None:
        """把三个模块的 PROJECTS_DIR 同时指到 value（可传 str）。"""
        for m in _MODULES:
            m.PROJECTS_DIR = value

    def test_resolve_dir_accepts_str_and_path(self):
        self._point_all(str(Path(self.tmp.name) / "users"))
        # project_store 的默认目录解析
        p = project_store._resolve_dir(None)
        self.assertIsInstance(Path(p), Path)

    def test_sqlite_default_db_path_accepts_str(self):
        """核心回归：赋成 str 后 resolve_db_path 曾抛 TypeError。"""
        self._point_all(str(Path(self.tmp.name) / "users"))
        got = sqlite_store.resolve_db_path()
        self.assertTrue(str(got).endswith(".sqlite/quote.db") or
                        str(got).replace("\\", "/").endswith(".sqlite/quote.db"),
                        f"库路径不对：{got}")
        self.assertIsInstance(got, Path)

    def test_path_outputs_identical_under_str_and_path(self):
        """同一目录，str 与 Path 两种赋值必须产出同一个路径（否则行为分叉）。"""
        base = Path(self.tmp.name) / "users"
        self._point_all(str(base))
        as_str = sqlite_store.resolve_db_path()
        self._point_all(base)
        as_path = sqlite_store.resolve_db_path()
        self.assertEqual(Path(as_str), Path(as_path))

    def test_downstream_readers_survive_str_assignment(self):
        """各读取方（docs / overview / well_library / group_store）都得扛住 str 赋值。

        它们历史上都写成 `Path(project_store.PROJECTS_DIR) / ...`（已包），本条
        是防「有人把 Path() 去掉」——而不是只测我们自己修过的那三处。
        """
        base = Path(self.tmp.name) / "users"
        self._point_all(str(base))
        # 真实调用点：路径解析函数在目录不存在时也不得抛 TypeError
        self.assertEqual(project_overview._dir(), base)
        # 用模块自己的常量拼期望值，不把目录名硬写在本测试里（否则两边各自漂移）。
        self.assertEqual(project_docs._docs_root(), base / project_docs._DOCS_DIR)
        self.assertEqual(well_library._path(), base / well_library._FILE_NAME)
        # group_store 不直接拼路径（它转 import project_store 的 `_safe_folder` 等），
        # 但它**转暴露**了一份同名 PROJECTS_DIR——两份必须同物，否则重定向会半生效。
        self.assertIs(group_store.PROJECTS_DIR, project_store.PROJECTS_DIR)

    def test_real_writes_land_in_str_assigned_dir(self):
        """端到端：PROJECTS_DIR 被赋成 str 时，写项目仍能落盘并读回。

        上一轮 CI 的 6 项 error 就是在写路径上炸的；只测路径解析不够，
        得让一次真实的 save→load 走到底。
        """
        base = Path(self.tmp.name) / "users"
        self._point_all(str(base))
        rec = project_overview.create_project({"name": "契约测试项目"})
        self.assertTrue(rec.get("id"))
        ids = [p["id"] for p in project_overview.list_projects()]
        self.assertIn(rec["id"], ids)
        # 库文件确实落在被赋成 str 的目录下
        self.assertTrue((base / ".sqlite" / "quote.db").exists(),
                        "库未落在重定向后的目录——重定向契约不成立")

    def test_no_module_still_does_raw_division_on_global(self):
        """静态兜底：源码里不得再出现「直接对 PROJECTS_DIR 做 /」的写法。

        动态测试只覆盖我想到的调用点；这条扫全文，防新增代码重蹈。
        """
        import re
        bad = []
        for m in _MODULES:
            src = Path(m.__file__).read_text(encoding="utf-8")
            for i, line in enumerate(src.splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                # PROJECTS_DIR / "..."  —— 未经 Path() 包裹
                if re.search(r"(?<!\))\bPROJECTS_DIR\s*/", line):
                    bad.append(f"{m.__name__}:{i}: {line.strip()}")
        self.assertEqual(
            bad, [],
            msg="这些行直接对 PROJECTS_DIR 做 `/`，一旦它被赋成 str 就抛 TypeError。"
                " 应写 Path(PROJECTS_DIR) / …：\n" + "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
