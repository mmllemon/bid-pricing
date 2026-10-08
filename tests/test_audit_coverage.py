"""审计埋点覆盖守卫（B-P1-9）。

背景
----
`audit_log` 表记录「谁在何时改了哪个方案/组」，是事后追责与事故复盘的唯一凭据。
但它靠**人工在端点里手写 `append_audit(...)`**——没有编译期约束，遗漏时页面一切正常，
只有出事翻记录才会发现关键那笔是空白。本用例把它变成静态判据：**列出的每个状态变更
端点都必须调用 `append_audit`**，漏一个即红。

不是「grep 有没有 append_audit」——而是按端点函数名逐个定位函数体，在体内查找调用。
端点重命名/拆分时本清单需同步（清单本身就是「哪些操作要留痕」的可审计声明）。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_PY = ROOT / "api" / "app.py"

#: 必须有审计埋点的端点函数名 → 期望的 action key（与前端 AUDIT_ACTIONS 词表对应）。
#: 只收「改变持久状态」或「构成决策留痕」的端点；纯查询（list/get/download）不在此列。
REQUIRED_AUDIT_ENDPOINTS: dict[str, str] = {
    # 报价
    "optimize_quote": "quote.optimize",
    # 方案
    "project_copy": "plan.copy",
    "project_recompute": "plan.recompute",
    "project_delete": "plan.delete",
    "project_mark_finalized": "plan.finalize",
    "project_compare": "plan.compare",
    # 方案组
    "group_create": "group.create",
    "group_rename": "group.rename",
    "group_set_finalized": "group.finalize",
    "group_copy": "group.copy",
    "group_delete": "group.delete",
    # 经营概览
    "overview_save": "project.overview.save",
    "overview_delete": "project.overview.delete",
    "overview_finalize": "project.overview.finalize",
}


def _module_functions() -> dict[str, ast.AST]:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _calls_in(func: ast.AST) -> set[str]:
    """函数体内（含嵌套定义）调用的函数名集合。"""
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def _audit_action_keys(func: ast.AST) -> list[str]:
    """提取 append_audit(...) 的第二位置参数（action 字符串字面量）。"""
    keys: list[str] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "append_audit":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                keys.append(str(node.args[1].value))
    return keys


class AuditCoverageTest(unittest.TestCase):
    """每个状态变更端点都必须写审计，且 action key 与声明一致。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.funcs = _module_functions()

    def test_all_required_endpoints_call_append_audit(self) -> None:
        missing = []
        for fname in REQUIRED_AUDIT_ENDPOINTS:
            func = self.funcs.get(fname)
            if func is None:
                missing.append(f"{fname}（端点不存在——重命名/删除后本清单需同步）")
                continue
            if "append_audit" not in _calls_in(func):
                missing.append(f"{fname}（端点存在但体内无 append_audit 调用）")
        self.assertEqual(
            missing, [],
            "以下状态变更端点缺少审计埋点（B-P1-9）——页面一切正常，只有出事翻记录才发现空白：\n  "
            + "\n  ".join(missing),
        )

    def test_action_keys_match_declared(self) -> None:
        wrong = []
        for fname, expected in REQUIRED_AUDIT_ENDPOINTS.items():
            func = self.funcs.get(fname)
            if func is None:
                continue
            keys = _audit_action_keys(func)
            if expected not in keys:
                wrong.append(f"{fname}: 期望 action={expected!r}，实际={keys}")
        self.assertEqual(wrong, [], "审计 action key 与声明不符（前端词表靠它对中文名）：\n  " + "\n  ".join(wrong))

    def test_action_keys_are_namespaced(self) -> None:
        """action key 必须形如 `域.动作`（如 group.delete）——前端按前缀分发中文名。"""
        bad = []
        for node in ast.walk(ast.parse(APP_PY.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "append_audit":
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    v = str(node.args[1].value)
                    if "." not in v:
                        bad.append(v)
        self.assertEqual(bad, [], f"action key 未按 `域.动作` 命名：{bad}")


if __name__ == "__main__":
    unittest.main()