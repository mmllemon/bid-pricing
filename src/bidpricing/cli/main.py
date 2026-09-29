"""CLI 主入口（自 bidpricing/cli.py 逐字拆出）。"""
from __future__ import annotations

from .common import InstanceLoadError
from .parser import build_parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except InstanceLoadError as exc:
        # _load_instance_doc / _load_phase1_instance 的统一出口：
        # --instance 缺文件 / 坏 JSON 在这一层变成「打印 + return 1」，
        # 各 cmd_* 不必重复 try/except 样板。
        print(f"■ {exc}")
        return 1
