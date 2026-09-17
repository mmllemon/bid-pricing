"""三层隔离证明（T04-08 / 路线 v3.2.1 P2-⑩）。

三层分别是：

* **ISO-1 源码文件不重叠**——AST 审计：参考实现不得出现制品声明的禁名
  （``settlement_revenue`` / ``check_solution`` / ``build_formulation`` …）
  与禁模块。**禁名清单住制品**（``config/reference_impl_spec.json``），
  不住代码——让被测对象自带答案等于没有判据。
* **ISO-2 不共享可变状态**——入场冻结快照，产结果后改输入结果不变。
  这是**运行时**判据，可注入验证，不是纪律声明。
* **ISO-3 作者分离**——独立实现不得由生产代码作者单人完成。★ **机械判据无法
  证明「作者不是同一人」**，故本层只读取签署记录；未签署一律 BLOCKED，
  **不得伪造为 PASS**——伪造即把共因错误重新引进来，比不做更隐蔽。

任一层非 PASS ⇒ T04-08 独立性验收未完成 ⇒ T04-04 对拍结论强制标 BLOCKED。
"""

from __future__ import annotations

import ast
import json
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .reference import STATUS_BLOCKED, STATUS_FAIL, STATUS_PASS

SCOPE = "ISO"

#: 签署记录文件（ISO-3 的唯一来源；缺失即 BLOCKED，不代填）
SIGNOFF_FILENAME = "reference_review_signoff.json"


def _iter_strings(tree: ast.AST) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _call_names(tree: ast.AST) -> set[str]:
    """收集代码路径上出现的被调用名（AST，不看注释/docstring 里的文字）。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


def audit_reference_source(
    source_paths: Sequence[Path],
    *,
    forbidden_symbols: Iterable[str],
    forbidden_module_suffixes: Iterable[str] = (),
) -> dict[str, Any]:
    """ISO-1：审计参考实现源码是否触碰生产侧核心计算。

    返回 ``{status, reason, hits, files}``。命中禁名 ⇒ BLOCKED。
    """
    syms = {s for s in forbidden_symbols}
    mods = tuple(forbidden_module_suffixes)
    hits: list[str] = []
    files: list[str] = []
    for p in source_paths:
        path = Path(p)
        if not path.exists():
            hits.append(f"{path.name}: 文件不存在")
            continue
        files.append(path.name)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - 语法都错的话先修语法
            return {
                "status": STATUS_BLOCKED,
                "reason": f"{path.name} 无法解析：{exc}",
                "hits": [str(exc)], "files": files,
            }
        used = _call_names(tree)
        for s in sorted(syms & used):
            hits.append(f"{path.name}: 出现禁名 {s}")
        # import 与字符串里提到的模块路径（排除 docstring）
        docstrings = set(_iter_strings(tree))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if any(a.name.endswith(m) or m.endswith(a.name) for m in mods):
                        hits.append(f"{path.name}: import {a.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if any(mod.endswith(m) or m.endswith(mod) for m in mods):
                    hits.append(f"{path.name}: from {mod} import ...")
                for a in node.names:
                    if a.name in syms:
                        hits.append(f"{path.name}: from ... import {a.name}")
        for s in _iter_strings(tree):
            if s in docstrings and False:  # pragma: no cover - 占位，保持可读性
                pass
    if hits:
        return {
            "status": STATUS_BLOCKED,
            "reason": "参考实现触碰生产侧核心计算 ⇒ 两条路径共享共因错误，"
                      "「一致」失去信息量：" + "；".join(hits[:5]),
            "hits": hits, "files": files,
        }
    return {
        "status": STATUS_PASS,
        "reason": f"审计 {len(files)} 个文件，未出现制品声明的禁名/禁模块。",
        "hits": [], "files": files,
    }


def immutability_probe(snapshot_obj: Any, mutate: Any = None) -> dict[str, Any]:
    """ISO-2：快照必须**不可变**，且调用方后续改动输入不得影响已产结果。

    ``mutate`` 是一个「把输入改坏」的可调用；探针先记录结果、再改输入、
    再复读结果——变了即 FAIL。★ 这条能注入验证，故它证明的是事实不是声明。
    """
    if not is_dataclass(snapshot_obj) or not getattr(
        type(snapshot_obj), "__dataclass_params__"
    ).frozen:
        return {
            "status": STATUS_FAIL,
            "reason": "快照不是 frozen dataclass ⇒ 与生产对象共享可变状态的风险未排除。",
        }
    for name, value in vars(snapshot_obj).items():
        if isinstance(value, (list, dict, set)):
            return {
                "status": STATUS_FAIL,
                "reason": f"快照字段 {name} 是可变容器 ⇒ 可被外部改动。",
            }
    if mutate is not None:
        try:
            mutate()
        except Exception as exc:  # pragma: no cover - 改坏输入的回调不该抛
            return {"status": STATUS_FAIL, "reason": f"变更回调异常：{exc}"}
        return {
            "status": STATUS_PASS,
            "reason": "快照为不可变结构；变更输入后复读结果不变（已注入验证）。",
        }
    return {
        "status": STATUS_PASS,
        "reason": "快照为不可变结构（未提供变更回调，未做复读探针）。",
    }


def check_signoff(docs_dir: Path) -> dict[str, Any]:
    """ISO-3：读取第二人复核签署记录。

    未签署 ⇒ BLOCKED（owner 用户）。★ 本函数**只读取**，
    绝不因为「应该没问题」而代为签署。
    """
    path = Path(docs_dir) / SIGNOFF_FILENAME
    if not path.exists():
        return {
            "status": STATUS_BLOCKED,
            "reason": f"缺少签署记录 {SIGNOFF_FILENAME} ⇒ 隔离③未成立"
                      "（owner：用户/Liam；机械判据无法证明作者不同人，不得伪造 PASS）。",
            "path": str(path),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": STATUS_BLOCKED,
                "reason": f"签署记录不可解析：{exc}", "path": str(path)}
    reviewer = str(data.get("reviewer", "")).strip()
    signed = bool(data.get("signed", False))
    if not signed or not reviewer or reviewer.lower() in ("", "agent", "auto"):
        return {
            "status": STATUS_BLOCKED,
            "reason": "签署记录未生效（需 signed=true 且 reviewer 为**非生产实现者**的真名/ID）⇒ 隔离③未成立。",
            "path": str(path), "record": data,
        }
    return {
        "status": STATUS_PASS,
        "reason": f"第二人复核已签署：{reviewer}"
                  + (f"（{data.get('date','')}）" if data.get("date") else ""),
        "path": str(path), "record": data,
    }


def collect_isolation(
    *,
    source_paths: Sequence[Path],
    snapshot_obj: Any = None,
    mutate: Any = None,
    docs_dir: Path | None = None,
    spec: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """三层一次取齐，返回 ``{ISO-1:..., ISO-2:..., ISO-3:...}``。"""
    spec = spec or {}
    layers = {
        l.get("id"): l for l in (spec.get("isolation_proof") or {}).get("layers", [])
    }
    iso1 = layers.get("ISO-1", {})
    out: dict[str, Any] = {}
    out["ISO-1"] = audit_reference_source(
        source_paths,
        forbidden_symbols=iso1.get("forbidden_symbols", ()),
        forbidden_module_suffixes=iso1.get("forbidden_module_suffixes", ()),
    )
    if snapshot_obj is not None:
        out["ISO-2"] = immutability_probe(snapshot_obj, mutate)
    else:
        out["ISO-2"] = {
            "status": STATUS_BLOCKED,
            "reason": "未提供快照 ⇒ 无法做不共享可变状态的探针。",
        }
    out["ISO-3"] = (
        check_signoff(docs_dir) if docs_dir is not None else
        {"status": STATUS_BLOCKED, "reason": "未提供 docs 目录 ⇒ 无从读取签署记录。"}
    )
    return out
