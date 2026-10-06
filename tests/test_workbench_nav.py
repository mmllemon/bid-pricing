"""工作台二级导航的漂移守卫（静态判据）。

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

反向对照的说明：断言的是「集合相等」而非「包含」——只测包含会漏掉「清单里多了
一条不存在于路由的项」这一半。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV_JS = ROOT / "frontend" / "js" / "workbench-nav.js"
APP_TSX = ROOT / "workbench-app" / "src" / "App.tsx"

# WB_NAV 数组内的条目形如：{ to: '/todos', label: '待办', code: 'T-02', icon: 'todo' },
_NAV_ITEM_RE = re.compile(r"\{\s*to:\s*'([^']*)'\s*,\s*label:\s*'([^']*)'\s*,\s*code:\s*'([^']*)'\s*,\s*icon:\s*'([^']*)'\s*\}")
# ICONS 映射里的键形如：  todo: '<rect .../>',
_ICON_KEY_RE = re.compile(r"^\s*(\w+):\s*'", re.MULTILINE)
# App.tsx 里带 path 的路由：<Route path="/todos" element={<TodosPage />} />
_ROUTE_PATH_RE = re.compile(r"<Route\s+path=\"([^\"]+)\"")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class WorkbenchNavDriftGuardTest(unittest.TestCase):
    """workbench-nav.js 的 to 集合必须与 App.tsx 的路由集合逐字相等。"""

    def setUp(self) -> None:
        for p in (NAV_JS, APP_TSX):
            self.assertTrue(p.is_file(), f"缺少文件：{p}")
        self.nav_src = _read(NAV_JS)
        self.app_src = _read(APP_TSX)
        self.items = _NAV_ITEM_RE.findall(self.nav_src)

    def test_nav_list_is_parsable(self) -> None:
        """清单可解析且非空（解析不到条目 ⇒ 本测试退化成假绿）。"""
        self.assertTrue(
            self.items,
            "未从 workbench-nav.js 解析出任何 WB_NAV 条目。"
            "若条目写法变了（字段顺序/引号），本测试的正则需同步更新，"
            "否则会退化成「永远通过」的假绿。",
        )

    def test_tos_match_react_routes(self) -> None:
        """路径集合与 App.tsx 路由集合相等（双向：多一条/少一条都失败）。"""
        nav_tos = {to for to, _label, _code, _icon in self.items}
        route_tos = set(_ROUTE_PATH_RE.findall(self.app_src))
        only_in_nav = sorted(nav_tos - route_tos)
        only_in_routes = sorted(route_tos - nav_tos)
        self.assertEqual(
            nav_tos,
            route_tos,
            "外层二级导航与 React 路由漂移。\n"
            f"  仅存在于 workbench-nav.js（点了会落空）：{only_in_nav}\n"
            f"  仅存在于 App.tsx（外层点不到）：{only_in_routes}\n"
            "修法：同步两边，或删除多余项。",
        )

    def test_tos_and_codes_are_unique(self) -> None:
        """路径与编号不重复（重复会让高亮匹配错项）。"""
        tos = [to for to, _l, _c, _i in self.items]
        codes = [code for _t, _l, code, _i in self.items]
        self.assertEqual(len(tos), len(set(tos)), f"WB_NAV 存在重复路径：{tos}")
        self.assertEqual(len(codes), len(set(codes)), f"WB_NAV 存在重复编号：{codes}")

    def test_icon_keys_exist(self) -> None:
        """每项的图标键都在 ICONS 中存在（否则渲染出空 <svg>）。"""
        icon_keys = set(_ICON_KEY_RE.findall(self.nav_src))
        # ICONS 映射定义在 WB_NAV 之前；用其键集合校验引用，避免渲染出空 <svg>。
        missing = sorted({icon for _t, _l, _c, icon in self.items} - icon_keys)
        self.assertFalse(
            missing,
            f"WB_NAV 引用了不存在的图标键：{missing}（渲染结果会是空白方块）",
        )


if __name__ == "__main__":
    unittest.main()
