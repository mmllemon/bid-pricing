"""CLI 主入口（自 bidpricing/cli.py 逐字拆出）。"""
from __future__ import annotations

import sys

from .common import InstanceLoadError
from .parser import build_parser


def harden_streams() -> None:
    """把 stdout/stderr 的编码错误策略降为 ``replace`` —— 只兜错误策略，不改编码。

    真实踩坑：中文 Windows 控制台 CP=936（GBK）下，``contract-check`` 打印第一
    条判据的 ``✓``、``ruleset-selftest`` 打印 ``⁺`` 都会抛 UnicodeEncodeError，
    命令以退出码 1 收场，而判据本身**全是 PASS**——看起来像逻辑失败，实为编码
    问题，且只在中文 Windows 上复现（其余平台默认 UTF-8，永远看不到）。

    这里做进程级兜底：**保留控制台原有编码**（不把中文打成乱码——改成 UTF-8
    输出反而会让 GBK 控制台显示乱码），只把无法表示的字符降级为 ``?``。
    判据的结论不受影响；符号丢字形远好于整条命令崩掉。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError, RuntimeError):
            # 被重定向到不支持 reconfigure 的对象（StringIO / 测试替身）时跳过。
            pass


def main(argv: list[str] | None = None) -> int:
    harden_streams()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except InstanceLoadError as exc:
        # _load_instance_doc / _load_phase1_instance 的统一出口：
        # --instance 缺文件 / 坏 JSON 在这一层变成「打印 + return 1」，
        # 各 cmd_* 不必重复 try/except 样板。
        print(f"■ {exc}")
        return 1
