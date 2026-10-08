"""工作台二级导航的漂移守卫（执行判据，不解析渲染）。

背景（P4 前端整合后重写，2026-10-08）
------------------------------------
P-W8 时期，工作台 9 页的路径同时出现在两个地方：``frontend/js/workbench-nav.js``
（外层侧栏清单）与 ``workbench-app/src/App.tsx``（React 路由）。本用例当时用 Node
真实执行那份 JS，比对两侧的路径集合，钉住「外层点不到的漂移路由」。

P4 把原生前端整体删掉后，**只剩一个清单**：``workbench-app/src/features/nav/workbenchNav.tsx``。
漂移的形态随之从「两份清单不一致」变成「清单与路由不一致」——有人新增了一个 React
页面却忘了登记导航项（或反过来），导航渲染出的项点进去 404。本用例仍钉这个缺陷：
``WORKBENCH_NAV`` 的 ``to`` 集合必须与 ``App.tsx`` 的路由集合（扣除站点级路由与带参详情路由）
逐字相等。

实现方式
--------
从 ``workbenchNav.tsx`` 里抠 ``{ to: '...' }``（该文件是纯数据数组，条目格式由本用例
钉住；格式一变就解析失败或假绿，与旧版对 JS 的判据同等严格）。相比执行 TSX，正则
避免了为测试引入 JSX 转译链——收益大于「不解析源码」的洁癖，且条目写法已在下方断言。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV_TSX = ROOT / "workbench-app" / "src" / "features" / "nav" / "workbenchNav.tsx"
APP_TSX = ROOT / "workbench-app" / "src" / "App.tsx"

# App.tsx 里带 path 的路由：<Route path="/todos" element={<TodosPage />} />
_ROUTE_PATH_RE = re.compile(r'<Route\s+path="([^"]+)"')
# workbenchNav.tsx 里的导航条目：{ to: '/todos', label: '待办', ... }
_NAV_TO_RE = re.compile(r"\{\s*to:\s*'([^']+)'")
# 条目编号与图标键
_NAV_CODE_RE = re.compile(r"code:\s*'([^']+)'")

# 站点级路由：属于全站顶栏导航（SiteTopBar 的域），不属于工作台二级项。
_SITE_LEVEL_ROUTES = {'/portal', '/quote', '/tools', '/tools/duct', '/tools/cable', '/tools/earth', '/tools/well'}


class WorkbenchNavDriftGuardTest(unittest.TestCase):
    """workbenchNav.tsx 的 to 集合必须与 App.tsx 的路由集合逐字相等。"""

    @classmethod
    def setUpClass(cls) -> None:
        for p in (NAV_TSX, APP_TSX):
            assert p.is_file(), f"缺少文件：{p}"
        cls.nav_src = NAV_TSX.read_text(encoding="utf-8")
        cls.app_src = APP_TSX.read_text(encoding="utf-8")
        cls.nav_tos_raw = _NAV_TO_RE.findall(cls.nav_src)
        assert cls.nav_tos_raw, (
            "从 workbenchNav.tsx 未解析出任何 { to: '...' } 条目——条目写法变了，"
            "本用例的正则需同步更新（否则会假绿）。"
        )

    def test_tos_match_react_routes(self) -> None:
        """路径集合与 App.tsx 路由集合相等（双向：多一条/少一条都失败）。

        带参数的详情路由（如 /biz/:id）豁免：它不是二级导航项——只列静态入口，
        详情页由项目卡片 navigate 进入。豁免按「含 : 即参数路由」显式过滤。
        """
        nav_tos = set(self.nav_tos_raw)
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
            "工作台导航与 React 路由漂移。\n"
            f"  仅存在于 workbenchNav.tsx（点了会落空）：{only_in_nav}\n"
            f"  仅存在于 App.tsx（导航点不到）：{only_in_routes}\n"
            f"  参数路由豁免（详情页，不占二级项）：{param_routes}\n"
            f"  站点级路由豁免（全站顶栏域，不占二级项）：{sorted(_SITE_LEVEL_ROUTES)}\n"
            "修法：同步两边，或删除多余项。",
        )

    def test_tos_and_codes_are_unique(self) -> None:
        """路径与编号不重复（重复会让高亮匹配错项）。"""
        tos = self.nav_tos_raw
        codes = _NAV_CODE_RE.findall(self.nav_src)
        self.assertEqual(len(tos), len(set(tos)), f"WORKBENCH_NAV 存在重复路径：{tos}")
        self.assertEqual(len(codes), len(set(codes)), f"WORKBENCH_NAV 存在重复编号：{codes}")
        self.assertEqual(
            len(codes), len(tos),
            "条目数与编号数不一致——有条目缺 code 字段，正则可能漏解析。",
        )


if __name__ == "__main__":
    unittest.main()