"""AST 审计共享 visitor 工具（O9 收敛）。

此前 18 处 ``ast.walk`` 独立实现，每个审计规则（SV-12、BB-03、CC-12、
assertion_6）都自建 walk 循环。统一为单点定义，各模块 import 而非重定义。

refimpl/isolation.py 因隔离约束（仅 import stdlib）不引用本模块。
"""

from __future__ import annotations

import ast
from typing import Iterable

#: 函数/方法定义节点类型
_FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)

#: 模块体节点类型（含 docstring 的位置）
_DOC_PARENTS = (ast.Module, ast.ClassDef, *_FUNC_TYPES)


def iter_call_names(tree: ast.AST) -> Iterable[tuple[int, str]]:
    """遍历所有 ``ast.Call`` 节点，产出 ``(lineno, 被调用名)``。

    被调用名取 ``func.id``（``Name``）或 ``func.attr``（``Attribute``），
    均不存在时跳过。
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name):
            yield node.lineno, fn.id
        elif isinstance(fn, ast.Attribute):
            yield node.lineno, fn.attr


def iter_call_names_set(tree: ast.AST) -> set[str]:
    """收集全部被调用名集合（含 ``ast.Name`` 引用）。"""
    names: set[str] = set()
    for _lineno, name in iter_call_names(tree):
        names.add(name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
    return names


def iter_imports(tree: ast.AST) -> Iterable[tuple[int, str, bool]]:
    """遍历全部 import，产出 ``(lineno, 顶层包名, 是否在函数体内)``。"""
    in_func: dict[int, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, _FUNC_TYPES):
            for sub in ast.walk(node):
                in_func[id(sub)] = True
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name.split(".")[0], in_func.get(id(node), False)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.lineno, node.module.split(".")[0], in_func.get(id(node), False)


def iter_module_level_imports(tree: ast.Module) -> Iterable[tuple[int, str]]:
    """只看模块顶层的 import（函数体内的惰性 import 不算）。"""
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.lineno, node.module.split(".")[0]


def iter_import_modules(tree: ast.AST) -> Iterable[tuple[int, str]]:
    """遍历全部 import，产出 ``(lineno, 完整模块路径)``。

    用于需要精确匹配模块后缀的场景（如 ISO-1 禁模块审计）。
    ``Import`` 产出 ``a.name``；``ImportFrom`` 产出 ``node.module``。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.lineno, node.module


def docstring_node_ids(tree: ast.AST) -> set[int]:
    """收集全部 docstring 的 Constant 节点 id。

    docstring = 模块/类/函数体的首条字符串 ``Expr``。
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            out.add(id(first.value))
    return out


def iter_string_constants(tree: ast.AST) -> Iterable[tuple[int, str]]:
    """遍历所有字符串 ``ast.Constant`` 节点，产出 ``(lineno, value)``。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield getattr(node, "lineno", -1), node.value


def iter_code_string_literals(tree: ast.AST) -> Iterable[tuple[int, str]]:
    """源码里**参与代码**的字符串字面量（docstring 排除）。

    判据要拦的是「代码路径上有一份硬拷贝」，不是「文档里提到了这个词」。
    把 docstring 算进来会让判据惩罚注释的详尽程度——那是反的。
    """
    skip = docstring_node_ids(tree)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
        ):
            yield getattr(node, "lineno", -1), node.value


def iter_branch_string_constants(tree: ast.AST) -> Iterable[tuple[int, str]]:
    """遍历 If/While 条件里的字符串常量，产出 ``(lineno, value)``。

    用于 BB-06：后端名不得参与 if/elif/while 的比较。
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.If, ast.While)):
            continue
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                yield getattr(sub, "lineno", -1), sub.value


def named_numeric_constant_ids(tree: ast.AST) -> set[int]:
    """收集赋值目标上的数值常量的 id（含 ``Assign`` / ``AnnAssign``）。"""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            val = node.value
            if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)):
                out.add(id(val))
    return out


def structural_constant_ids(tree: ast.AST) -> set[int]:
    """收集切片下标/边界上的常量 id（``Subscript`` 索引 + ``Slice`` 边界）。"""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            for c in ast.walk(node.slice):
                if isinstance(c, ast.Constant):
                    out.add(id(c))
        elif isinstance(node, ast.Slice):
            for b in (node.lower, node.upper, node.step):
                if isinstance(b, ast.Constant):
                    out.add(id(b))
    return out


def iter_numeric_constants(tree: ast.AST) -> Iterable[tuple[int, float]]:
    """遍历所有数值 ``ast.Constant``（排除 bool），产出 ``(lineno, value)``。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            continue
        yield getattr(node, "lineno", -1), float(node.value)


def iter_docstring_values(tree: ast.AST) -> Iterable[str]:
    """遍历所有 docstring 的字符串值（模块/类/函数的首条 Expr 字符串）。"""
    for node in ast.walk(tree):
        if isinstance(node, _DOC_PARENTS):
            ds = ast.get_docstring(node)
            if ds:
                yield ds


def has_call_named(tree: ast.AST, name: str) -> bool:
    """检查源码中是否存在名为 ``name`` 的函数调用。"""
    for _lineno, n in iter_call_names(tree):
        if n == name:
            return True
    return False
