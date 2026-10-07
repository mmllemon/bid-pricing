"""工作台二级导航的漂移守卫（执行判据，不解析源码）。

背景
----
P-W8 把导航收敛为「单一竖栏」后，工作台 9 页的路径同时出现在两个地方：

  - ``frontend/js/workbench-nav.js`` 的 ``WB_NAV`` —— 外层侧栏的文案/图标/路径清单
  - ``workbench-app/src/App.tsx`` 的 ``<Route path>`` —— 「页面是否存在」的事实源

两者本该一致，但**没有任何编译期约束**把静态 JS 和 React 路由绑在一起。
最隐蔽的失败形态是：有人新增了一个 React 页面（或改了某条路由），忘了同步
外层清单——外层照样渲染出 9 个二级项、点进去却 404/落回首页，而且**只在点击那
一项时才暴露**。本测试就是钉住这个缺陷：不比对文案与图标（允许漂移，已在计划
§9.3-1 登记为已知残留），只要求**路径集合相等**。

实现方式（P2，2026-10-06）
----
旧版用正则从 workbench-nav.js 里抠 ``{ to: ... }`` —— 条目换行/字段顺序一变
就解析失败或假绿。现在改用 Node **真实执行**该文件（window 打桩），直接读
``window.WB_NAV``，与源码写法解耦。

为什么不用 wb-nav.json 两侧同读：vanilla 侧必须同步加载（file:// 直接打开
场景下 fetch 不可用），异步化会动侧栏渲染时序；React 侧 <Route> 仍需显式写
组件映射，JSON 驱动不彻底。执行判据达到同样的去正则目的，零运行时风险。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV_JS = ROOT / "frontend" / "js" / "workbench-nav.js"
APP_TSX = ROOT / "workbench-app" / "src" / "App.tsx"

# App.tsx 里带 path 的路由：<Route path="/todos" element={<TodosPage />} />
_ROUTE_PATH_RE = re.compile(r'<Route\s+path="([^"]+)"')

# 站点级路由：属于全站顶栏导航（SiteTopBar 的域），不属于工作台 9 个二级项。
# 前端整合（docs/FRONTEND_UNIFY_PLAN.md）把母项目页面逐个迁入 React，迁入一个在这里登记一个，
# 否则本用例会把它当成「外层点不到的漂移路由」而变红。显式清单而非前缀通配，保持可审计。
_SITE_LEVEL_ROUTES = {'/portal', '/quote', '/tools', '/tools/duct', '/tools/cable', '/tools/earth', '/tools/well'}

_NODE_RUNNER = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf-8');
globalThis.window = {};
eval(src);
const nav = globalThis.window.WB_NAV;
const icons = globalThis.window.WB_NAV_ICONS;
if (!Array.isArray(nav)) { console.error('WB_NAV is not an array'); process.exit(2); }
console.log(JSON.stringify({ nav, icons: icons ? Object.keys(icons) : [] }));
"""


def _load_nav_from_js() -> tuple[list[dict], list[str]]:
    """用 Node 执行 workbench-nav.js，返回 (WB_NAV 条目, ICONS 键)。

    编码必须**显式**指定：``text=True`` 缺省按本机 locale 解码，而 node 输出永远是 UTF-8。
    中文 Windows（控制台 CP=936）下这条路径会 UnicodeDecodeError → 读取线程挂掉使
    ``proc.stdout`` 变成 ``None`` → ``json.loads(None)`` TypeError → setUpClass 抛错，
    于是**本类 3 项用例静默不运行**（实测：全量从 1619 变 1616，只多一条 error，极难发现）。
    与 status.run_tests / api/app.py 的导出子进程是同一类事故（见 tests/test_subprocess_encoding.py）。
    """
    proc = subprocess.run(
        ["node", "-e", _NODE_RUNNER, str(NAV_JS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"执行 workbench-nav.js 失败：{proc.stderr.strip()[:300]}")
    if not proc.stdout:
        raise RuntimeError("执行 workbench-nav.js 未产生输出（子进程输出读取失败？）")
    data = json.loads(proc.stdout)
    return data["nav"], data["icons"]


@unittest.skipIf(shutil.which("node") is None, "需要 node 来执行 workbench-nav.js")
class WorkbenchNavDriftGuardTest(unittest.TestCase):
    """workbench-nav.js 的 to 集合必须与 App.tsx 的路由集合逐字相等。"""

    @classmethod
    def setUpClass(cls) -> None:
        for p in (NAV_JS, APP_TSX):
            assert p.is_file(), f"缺少文件：{p}"
        cls.items, cls.icon_keys = _load_nav_from_js()
        assert cls.items, (
            "执行 workbench-nav.js 后 WB_NAV 为空——若文件写法变了"
            "（不再向 window.WB_NAV 赋值），本测试需同步更新。"
        )
        cls.app_src = APP_TSX.read_text(encoding="utf-8")

    def test_tos_match_react_routes(self) -> None:
        """路径集合与 App.tsx 路由集合相等（双向：多一条/少一条都失败）。

        带参数的详情路由（如 /biz/:id）豁免：它不是二级导航项——侧栏只列 9 个
        静态入口，详情页由项目卡片 navigate 进入，不在 WB_NAV 中占位。
        豁免按「含 : 即参数路由」显式过滤，而非逐个列名，避免新增详情页时漏改。
        """
        nav_tos = {it["to"] for it in self.items}
        # 带参详情路由（/biz/:id）与站点级路由（/portal）都不是工作台二级项：
        # 前者由卡片 navigate 进入，后者是全站顶栏的域。两者一并豁免。
        route_tos = {
            r for r in _ROUTE_PATH_RE.findall(self.app_src)
            if ":" not in r and r not in _SITE_LEVEL_ROUTES
        }
        param_routes = sorted(r for r in _ROUTE_PATH_RE.findall(self.app_src) if ":" in r)
        only_in_nav = sorted(nav_tos - route_tos)
        only_in_routes = sorted(route_tos - nav_tos)
        self.assertEqual(
            nav_tos,
            route_tos,
            "外层二级导航与 React 路由漂移。\n"
            f"  仅存在于 workbench-nav.js（点了会落空）：{only_in_nav}\n"
            f"  仅存在于 App.tsx（外层点不到）：{only_in_routes}\n"
            f"  参数路由豁免（详情页，不占二级项）：{param_routes}\n"
            f"  站点级路由豁免（全站顶栏域，不占二级项）：{sorted(_SITE_LEVEL_ROUTES)}\n"
            "修法：同步两边，或删除多余项。",
        )

    def test_tos_and_codes_are_unique(self) -> None:
        """路径与编号不重复（重复会让高亮匹配错项）。"""
        tos = [it["to"] for it in self.items]
        codes = [it["code"] for it in self.items]
        self.assertEqual(len(tos), len(set(tos)), f"WB_NAV 存在重复路径：{tos}")
        self.assertEqual(len(codes), len(set(codes)), f"WB_NAV 存在重复编号：{codes}")

    def test_icon_keys_exist(self) -> None:
        """每项的图标键都在 ICONS 中存在（否则渲染出空 <svg>）。"""
        icon_keys = set(self.icon_keys)
        missing = sorted({it["icon"] for it in self.items} - icon_keys)
        self.assertFalse(
            missing,
            f"WB_NAV 引用了不存在的图标键：{missing}（渲染结果会是空白方块）",
        )


if __name__ == "__main__":
    unittest.main()
