"""子进程文本模式的**编码守卫**（静态判据）。

背景：同一类事故在本仓已出现三次，且每次都很隐蔽——

1. ``status.run_tests``：``text=True`` 未指定编码 → 中文 Windows（控制台 CP=936）按 GBK 解码
   unittest 的 UTF-8 中文输出 → 读取线程 ``UnicodeDecodeError`` → ``out.stdout`` 变 ``None``
   → 字符串拼接 ``TypeError`` → **状态快照整条命令崩掉**。
2. ``tests/test_workbench_nav.py``：同样未指定编码 → 执行 ``workbench-nav.js`` 的子进程
   ``stdout`` 变 ``None`` → ``json.loads(None)`` → ``setUpClass`` 抛错 → 该类的 3 项用例
   **静默不运行**（实测全量从 1619 变 1616，只多一条 error）。
3. ``api/app.py`` 的 Excel 导出子进程：同病，只因该调用不看 stdout 才没显形。

判据：**凡 ``text=True``（文本模式）的子进程调用，必须显式声明 ``encoding=``**。

为什么值得做成测试：不显式指定编码，等于把「这条命令能不能跑」交给运行环境的区域设置——
在 Linux/UTF-8 的 CI 上**永远看不到**，只有中文 Windows 才炸；而一旦炸，症状（3 项用例
静默消失 / 快照生成不了）与代码本身毫无表面关联。与 CC-12、BB-05 同源：要拦的是
**代码路径上的硬拷贝/缺省依赖**，不是文档里提到这个词。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 扫描范围：生产代码 + 接口层 + 测试自身
SCAN_DIRS = ("src", "api", "tests")
SKIP_PARTS = ("node_modules", ".venv", ".git", ".rivet", ".yanagent", "backups")


def _strip_comments_and_docstrings(src: str) -> str:
    """去掉注释与文档字符串——判据只看**代码**（CC-12 教训：别把说明文字当违规）。"""
    src = re.sub(r'"""(?:.|\n)*?"""', ' ', src)
    src = re.sub(r"'''(?:.|\n)*?'''", ' ', src)
    src = re.sub(r"#[^\n]*", ' ', src)
    return src


def _call_spans(src: str, callee: str) -> list[str]:
    """取出 ``callee( ... )`` 的括号配对区间（字符串已剥，括号即结构）。"""
    spans: list[str] = []
    for m in re.finditer(re.escape(callee) + r"\(", src):
        i = m.end() - 1
        depth = 0
        for j in range(i, len(src)):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    spans.append(src[m.start():j + 1])
                    break
    return spans


class SubprocessEncodingGuardTest(unittest.TestCase):
    def test_text_mode_calls_declare_encoding(self) -> None:
        offenders: list[str] = []
        checked = 0
        for d in SCAN_DIRS:
            for path in sorted((ROOT / d).rglob("*.py")):
                if any(p in path.parts for p in SKIP_PARTS):
                    continue
                code = _strip_comments_and_docstrings(path.read_text(encoding="utf-8"))
                for span in _call_spans(code, "subprocess.run") + _call_spans(code, "subprocess.check_output") + _call_spans(code, "subprocess.Popen"):
                    if "text=True" not in span:
                        continue
                    checked += 1
                    if "encoding=" not in span:
                        rel = path.relative_to(ROOT).as_posix()
                        snippet = re.sub(r"\s+", " ", span)[:120]
                        offenders.append(f"{rel}: {snippet}")
        self.assertGreater(checked, 0, "应当扫到至少一处文本模式子进程调用——扫描逻辑可能失效")
        self.assertEqual(
            offenders, [],
            "文本模式（text=True）的子进程调用必须显式声明 encoding=（否则中文 Windows 上"
            "会 UnicodeDecodeError→stdout 变 None，症状与代码毫无表面关联）：\n  "
            + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
