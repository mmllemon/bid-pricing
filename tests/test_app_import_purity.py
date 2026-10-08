"""P1-3 判据：`import api.app` 必须无副作用；启动副作用改由 lifespan 承担。

实测到的假绿（本测试的来由）
--------------------------------
改造前 `api/app.py` 在 **import 期**执行：建 outputs 目录、把
`project_store.PROJECTS_DIR` / `sqlite_store.PROJECTS_DIR` 覆盖成真实用户目录、
跑两次 SQLite 迁移、打印安全告警。后果是：

    python -m unittest tests.test_project_credential.…test_real_project_passes
        → FAIL      （单跑）
    python -m unittest discover -s tests
        → OK        （整套）

差别只在导入顺序：单跑时 `from api.app import …` 现场执行模块体，那句
`sqlite_store.PROJECTS_DIR = USER_PROJECTS` 把测试刚 patch 好的临时目录**覆盖回
真实库**，于是"真实存在的 id"查不到 → 被 403 拦下。整套跑时 api.app 已被更早的
用例 import 并缓存，模块体不再执行，缺陷被隐藏。这不是"测试不稳定"，是判据本身
依赖执行顺序——**绿色会随跑法改变**。

本测试把口径钉死为两件事（缺一不可）：
  1. import api.app **不得**产生 outputs 下的目录创建、不得打印启动告警、
     不得改写两个存储模块的 PROJECTS_DIR。
  2. 这些行为**没有消失，只是搬到了启动钩子**：驱动 `_lifespan` 后，
     PROJECTS_DIR 必须落到该用户目录（否则服务启动即拿错库，比假绿更糟）。

取证跑在**子进程**里：`import api.app` 的模块体只在首次导入时执行，
同进程内先 import 会让断言失去意义。
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 子进程探针：先记录副作用，再 import，再驱动 lifespan，最后输出事实 JSON。
_PROBE = r"""
import asyncio, io, json, sys
from contextlib import redirect_stdout
from pathlib import Path

from bidpricing import project_store, sqlite_store

ROOT = Path(sys.argv[1]).resolve()
DEFAULT_PS = str(project_store.PROJECTS_DIR)
DEFAULT_SS = str(sqlite_store.PROJECTS_DIR)

# --- 记录器：mkdir 落在 outputs 下的调用 + 启动告警打印 ---
made_dirs = []
_orig_mkdir = Path.mkdir
def _spy_mkdir(self, *a, **kw):
    try:
        rp = str(self.resolve())
    except OSError:
        rp = str(self)
    if str(ROOT / "outputs") in rp:
        made_dirs.append(rp)
    return _orig_mkdir(self, *a, **kw)
Path.mkdir = _spy_mkdir

printed = []
_real_write = sys.stdout.write
def _spy_write(s):
    if isinstance(s, str) and "bidpricing" in s:
        printed.append(s.strip()[:80])
    return _real_write(s)
sys.stdout.write = _spy_write

facts = {"phase": "before-import",
         "default_ps": DEFAULT_PS, "default_ss": DEFAULT_SS}

import api.app as appmod   # ← 被测：这次 import 不应有任何副作用

facts["phase"] = "after-import"
# 快照必须**拷贝**：spy 往同一个 list 持续追加，而 json.dumps 在驱动 lifespan
# 之后才执行——直接存引用会把启动钩子里的预期行为（建目录/告警）误记到 import 阶段。
facts["mkdir_calls"] = list(made_dirs)
facts["printed"] = list(printed)
facts["ps_dir_after_import"] = str(project_store.PROJECTS_DIR)
facts["ss_dir_after_import"] = str(sqlite_store.PROJECTS_DIR)
facts["user_projects"] = str(appmod.USER_PROJECTS)

# --- 驱动启动钩子：行为必须在这里发生，而不是消失 ---
async def _drive():
    async with appmod._lifespan(appmod.app):
        pass
asyncio.run(_drive())

facts["ps_dir_after_lifespan"] = str(project_store.PROJECTS_DIR)
facts["ss_dir_after_lifespan"] = str(sqlite_store.PROJECTS_DIR)
print("PROBE_JSON " + json.dumps(facts))
"""


class AppImportPurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 子进程取证：模块体只在首次 import 时执行，同进程内先 import 会让断言失去意义。
        # 显式清掉 token 相关变量，并声明 encoding（否则中文 Windows 上 stdout 会变 None，
        # 症状与代码表面无关联）。
        import os
        full = dict(os.environ)
        full["PYTHONPATH"] = str(ROOT / "src")
        # 探针会打印中文（路径与告警文案）；管道上子进程按本机 locale 编码，
        # 中文 Windows（CP=936）下可能截断——与仓内既有口径一致钉 UTF-8。
        full["PYTHONIOENCODING"] = "utf-8"
        full["PYTHONUTF8"] = "1"
        full.pop("BIDPRICING_API_TOKEN", None)
        full.pop("BIDPRICING_REQUIRE_TOKEN", None)
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE, str(ROOT)],
            cwd=str(ROOT), env=full, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
        )
        line = next((l for l in (proc.stdout or "").splitlines() if l.startswith("PROBE_JSON ")), None)
        if line is None:
            raise AssertionError(
                f"探针未产出事实。\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr[-3000:]}"
            )
        cls.facts = json.loads(line[len("PROBE_JSON "):])

    def test_import_makes_no_outputs_dirs(self):
        self.assertEqual(
            self.facts["mkdir_calls"], [],
            msg=f"import api.app 期间创建了 outputs 下的目录（副作用未移干净）："
                f"{self.facts['mkdir_calls']}",
        )

    def test_import_prints_no_startup_banner(self):
        self.assertEqual(
            self.facts["printed"], [],
            msg=f"import api.app 期间打印了启动信息（应只在 lifespan/启动钩子里发生）："
                f"{self.facts['printed']}",
        )

    def test_import_does_not_mutate_store_project_dirs(self):
        """最关键的一条：import 期改写 PROJECTS_DIR 会覆盖测试的临时目录补丁。"""
        self.assertEqual(
            self.facts["ps_dir_after_import"], self.facts["default_ps"],
            msg="import api.app 改写了 project_store.PROJECTS_DIR",
        )
        self.assertEqual(
            self.facts["ss_dir_after_import"], self.facts["default_ss"],
            msg=("import api.app 改写了 sqlite_store.PROJECTS_DIR —— 这正是"
                 "test_project_credential 单跑 FAIL / 整套 OK 的根因"),
        )
        # 且默认值不该等于用户目录（若相等说明改动没生效或默认口径变了）
        self.assertNotEqual(self.facts["default_ss"], self.facts["user_projects"])

    def test_lifespan_still_applies_user_scope(self):
        """行为是搬家不是消失：驱动 lifespan 后必须落到该用户目录。"""
        want = self.facts["user_projects"]
        self.assertEqual(self.facts["ps_dir_after_lifespan"], want,
                         msg="_lifespan 没有应用 project_store 的用户目录")
        self.assertEqual(self.facts["ss_dir_after_lifespan"], want,
                         msg="_lifespan 没有应用 sqlite_store 的用户目录（服务会拿错库）")


if __name__ == "__main__":
    unittest.main()
