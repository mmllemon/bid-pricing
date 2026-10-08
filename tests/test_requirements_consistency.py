"""依赖与版本口径的一致性守卫（单一来源）。

动因（2026-10-08）：CI 此前把 `pip install pytest "fastapi>=0.115,<1"
"python-multipart>=0.0.9,<1"` 的**版本上界 inline 写在 workflow 里**，与
requirements-*.txt 是两套真相；同日刚修过两例同族的「手工清单 ↔ 真实来源」漂移
（`sqlite_store._SCHEMA_OBJECTS` 漏登记 project 表、`quoteProxy.QUOTE_PREFIXES`
漏登记 graph）。本文件把这类漂移改成机械判据：

1. **同一包在两份 requirements 里出现时，版本约束必须逐字相同**。
   dev 与 web 共享 fastapi / python-multipart（前者给测试导入 api.app 用，
   后者给运行用）。约束不一致＝本地与 CI 装到不同版本，"全绿"含义漂移。
2. **dev 不得引入 solver 包**。CI 的 minimal 档存在的唯一目的，是验证
   README 声明的「零第三方依赖即可运行」这条硬约束；若 requirements-dev.txt
   把 pulp/highspy 拖进来（哪怕经由 `-r requirements-web.txt`），minimal 档
   就静默失去意义——判据变成了它本要检查的东西。
3. **ci.yml 不得再 inline 钉版本**。除 `-r <file>` 与 `--upgrade pip` 外，
   workflow 里出现 `pip install <pkg><specifier>` 即红。
4. **CI 测试的 Python 下界 == pyproject 声明的 requires-python 下界**。
   此前声明 >=3.11、CI 只跑 3.12、本地是 3.14——三者无一对齐：代码若用了
   3.12 才有的特性，声明就成假话，而 CI 永远看不见。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "requirements-web.txt"
DEV = ROOT / "requirements-dev.txt"
CI = ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = ROOT / "pyproject.toml"

#: 只允许这两个包同时出现在 web 与 dev 里（dev 为测试导入 api.app 所需）。
SHARED_ALLOWED = {"fastapi", "python-multipart"}
#: 不得进 dev：会污染 CI 的 minimal 依赖档。
SOLVER_PKGS = {"pulp", "highspy"}

_REQ_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*((?:[<>=!~]=[^,\s]+,?\s*)+)")
_PY_RE = re.compile(r'requires-python\s*=\s*">=\s*(\d+\.\d+)')


def _requirements(path: Path) -> dict[str, str]:
    """解析 requirements 文件为 {包名(小写): 约束串(去空格)}，跳过注释与 -r 引用。"""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = _REQ_RE.match(line)
        if m:
            out[m.group(1).lower()] = re.sub(r"\s+", "", m.group(2))
    return out


def _vkey(v: str) -> tuple[int, int]:
    a, b = v.split(".")[:2]
    return (int(a), int(b))


class RequirementsConsistencyTest(unittest.TestCase):
    def test_files_exist(self):
        for p in (WEB, DEV, CI, PYPROJECT):
            self.assertTrue(p.exists(), f"缺少 {p}")

    def test_shared_packages_have_identical_specifier(self):
        web, dev = _requirements(WEB), _requirements(DEV)
        self.assertTrue(web, "requirements-web.txt 解析为空——正则可能失效")
        self.assertTrue(dev, "requirements-dev.txt 解析为空——正则可能失效")
        drift = [(k, web[k], dev[k]) for k in web.keys() & dev.keys()
                 if web[k] != dev[k]]
        self.assertEqual(
            drift, [],
            msg="同一包在 web 与 dev 里版本约束不一致（两套真相会各自漂移）："
                + "; ".join(f"{k}: web={w} dev={d}" for k, w, d in drift))

    def test_dev_does_not_pull_solver_or_web_wholesale(self):
        dev = _requirements(DEV)
        # 只看真正的指令行（非注释）：文件里有一段注释写「不要 -r requirements-web.txt」，
        # 拿整文件做子串匹配会把这句提醒误判成违规。
        include_lines = [ln.strip() for ln in DEV.read_text(encoding="utf-8").splitlines()
                         if not ln.lstrip().startswith("#") and ln.strip().startswith("-r")]
        bad_include = [ln for ln in include_lines if "requirements-web" in ln]
        self.assertEqual(bad_include, [],
                         msg="dev 不得整份 include web：会把 pulp/highspy 带进 minimal 档")
        bad = sorted(SOLVER_PKGS & set(dev))
        self.assertEqual(bad, [], msg=f"requirements-dev.txt 引入了 solver 包 {bad}，"
                                     "会把 CI 的 minimal 依赖档变成 solver 档")
        self.assertIn("pytest", dev, "dev 必须有 pytest（否则 31 个裸函数用例被静默跳过）")

    def test_shared_set_is_what_we_think(self):
        """web∩dev 只该是 fastapi/python-multipart。多出别的包=口径又分叉了。"""
        web, dev = _requirements(WEB), _requirements(DEV)
        extra = sorted((web.keys() & dev.keys()) - SHARED_ALLOWED)
        self.assertEqual(extra, [], msg=f"web 与 dev 共享了计划外的包：{extra}")

    def test_ci_does_not_inline_pin_versions(self):
        ci = CI.read_text(encoding="utf-8")
        offenders = []
        for line in ci.splitlines():
            s = line.strip()
            if not s.startswith(("pip install", "run: pip install")):
                continue
            body = s.split("pip install", 1)[1].strip()
            if body.startswith("-r") or "--upgrade" in body:
                continue
            if re.search(r"[A-Za-z0-9_.\-]+\s*\"?[<>=!~]=", body):
                offenders.append(s)
        self.assertEqual(
            offenders, [],
            msg="ci.yml 里又 inline 钉了版本，应与 requirements-*.txt 单一来源一致："
                + " | ".join(offenders))

    def test_ci_python_matrix_is_consistent_with_declared_floor(self):
        """CI 测的版本与 pyproject 声明下界的关系，必须是**可陈述的**。

        不直接要求「下界必被测」——那会把未验证的断言伪装成已验证：若代码事实上
        已在用比下界新的特性，硬把下界加进 matrix 只会让 CI 变红，而这正是我们要防的
        「看起来有门禁、其实没有」。

        所以两种合法情形：
          A) CI 已覆盖声明下界；
          B) CI 未覆盖，但代码里摸不到任何 3.12+/3.13+ 专属语法与 stdlib API
             （即「声明与实测版本之间无已知不兼容点」，静态可查）。
        两者都不成立时红。同时断言 CI 不得低于声明下界（声明 3.11 却只测 3.10 = 假话）。
        """
        floor = _PY_RE.search(PYPROJECT.read_text(encoding="utf-8"))
        self.assertIsNotNone(floor, "pyproject 里找不到 requires-python")
        want = floor.group(1)
        ci = CI.read_text(encoding="utf-8")
        tested: set[str] = set()
        for m in re.finditer(r'python-version:\s*"?(\d+\.\d+)"?', ci):
            tested.add(m.group(1))
        for m in re.finditer(r'python-version:\s*\[([^\]]+)\]', ci):
            tested.update(x.strip().strip('"\'') for x in m.group(1).split(","))
        self.assertTrue(tested, "ci.yml 里没解析到 python-version")

        # CI 不得测比声明下界更低的版本：那等于用不存在的运行环境做验证
        too_low = sorted(v for v in tested if _vkey(v) < _vkey(want))
        self.assertEqual(too_low, [],
                         msg=f"CI 测了声明下界 {want} 以下的版本 {too_low}")

        if want in tested:
            return  # 情形 A

        offenders = _scan_newer_than_floor(_vkey(want))
        self.assertEqual(
            offenders, [],
            msg=(f"CI 实测版本 {sorted(tested)} 未覆盖声明下界 {want}，"
                 f"且代码里发现只有高版本才支持的写法：{offenders[:6]}。"
                 f"要么把 {want} 加进 ci.yml 的 python-version matrix，"
                 f"要么把 requires-python 抬到实际验证过的版本——"
                 f"不能留着一条没人验证过的声明。"))


def _scan_newer_than_floor(floor: tuple[int, int]) -> list[str]:
    """扫 src/ 与 api/ 里比声明下界更新的语法/导入（静态，能拦多少拦多少）。

    **不装完备**：真正的完备保证是「CI 在那个版本上跑过」；本函数只负责在下界未被
    CI 覆盖时，拦住建意用新特性。

    只认两种零歧义信号：
      1. PEP 695 语法（`type X = ...` / `class C[T]` / `def f[T]`）——3.12+；
      2. 确从 `typing` 导入 `override`/`TypeIs`、从 `itertools` 导入 `batched`——3.12+。
    不得按**名字**判：本仓有 17 处 `override` 是 CLI 的「参数覆盖」变量名，
    按名匹配会误报成 3.12 特性（第一版就这么错过）——误报的判据会被当噪音关掉，
    比没有判据更糟。
    """
    roots = [ROOT / "src", ROOT / "api"]
    offenders: list[str] = []
    if _vkey("3.12") <= floor:
        return offenders
    typing_new = {"override", "TypeIs", "TypeAliasType"}
    iter_new = {"batched"}
    for base in roots:
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            src = f.read_text(encoding="utf-8", errors="replace")
            loc = f"{f.relative_to(ROOT)}"
            for lineno, raw in enumerate(src.splitlines(), 1):
                if re.search(r"(?m)^\s*type\s+[A-Za-z_]\w*\s*=", raw):
                    offenders.append(f"{loc}:{lineno}: PEP695 type 别名（3.12+）")
                if re.search(r"(?m)^(class|def)\s+\w+\[", raw):
                    offenders.append(f"{loc}:{lineno}: PEP695 泛型语法（3.12+）")
                m = re.match(r"\s*from\s+typing\s+import\s+(.+)", raw)
                if m and any(n.strip().strip("()") in typing_new
                             for n in m.group(1).split(",")):
                    offenders.append(f"{loc}:{lineno}: typing 新名字（3.12+）")
                m = re.match(r"\s*from\s+itertools\s+import\s+(.+)", raw)
                if m and any(n.strip().strip("()") in iter_new
                             for n in m.group(1).split(",")):
                    offenders.append(f"{loc}:{lineno}: itertools.batched（3.12+）")
    return offenders


if __name__ == "__main__":
    unittest.main()
