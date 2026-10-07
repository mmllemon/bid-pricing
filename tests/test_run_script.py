"""run.ps1 启动器的静态判据。

背景
----
`run.ps1` 是运维脚本，不是 Python 制品，零依赖测试环境里没有 PowerShell 运行时可供执行，
因此这里用的是**静态判据**。它们不是「大概检查一下文件里有没有某个词」——
每条都钉在一个**实际发生过、且失败形态很隐蔽**的缺陷上，并写明它击落什么：

1. 编码（UTF-8 with BOM）——PowerShell 5.1 对无 BOM 的 .ps1 按系统 ANSI 解码。
   脚本含中文时，丢 BOM 会解码错乱、吃掉引号与大括号，报出一批**离奇的语法错误**
   （实测：有 BOM 解析 0 错，剥掉 BOM 同一份文件解析出 6 个错误）。
   这类回归极易被误判成「写错了代码」，实际只是存盘编码变了。
2. `Wait-Process -Id $a -Id $b`——参数只能给一次，多进程必须传数组；
   旧版写重复了，按 Ctrl+C 停止时直接抛参数绑定失败（用户实际遇到的报错）。
3. 解释器判定必须看**能力**而不是**存在性**——WindowsApps 下的 0 字节应用执行别名占位符
   能被 Test-Path / Get-Command 命中，执行时却只打印「Python was not found」。
4. 探测的能力必须是**真正需要的能力**——只验 `--version` 会漏掉 `_ssl` 加载失败的残缺
   安装：它能打印版本号，pip 却走不了 HTTPS。
5. 必须探到 HTTP 200 才打印成功——否则「假成功」：进程根本没起来，脚本照样报一切正常。
6. 原生命令（pip）会往 stderr 写警告，`$ErrorActionPreference="Stop"` 会把它升级成**终止
   性错误**，脚本在装依赖中途暴毙。故原生命令须统一走容错包装。

反向对照：第 1 条已用「剥掉 BOM 的副本 / 保留 BOM 的原件」做过对照，判据有区分力；
其余各条对应的是已复现过的真实失败（参数绑定报错、0 字节占位符、pip 中途暴毙）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run.ps1"
UTF8_BOM = b"\xef\xbb\xbf"


class RunScriptEncodingTest(unittest.TestCase):
    """编码回归：丢 BOM ⇒ PowerShell 5.1 按 ANSI 解码 ⇒ 中文脚本语法崩坏。"""

    def setUp(self) -> None:
        self.raw = SCRIPT.read_bytes()

    def test_script_exists(self) -> None:
        self.assertTrue(SCRIPT.is_file(), f"缺少启动脚本：{SCRIPT}")

    def test_non_ascii_script_is_saved_as_utf8_with_bom(self) -> None:
        """含非 ASCII 的 .ps1 必须带 UTF-8 BOM，否则 PowerShell 5.1 会按 ANSI 解码。"""
        has_non_ascii = any(b > 0x7F for b in self.raw)
        if not has_non_ascii:
            self.skipTest("脚本为纯 ASCII，编码无关紧要")
        self.assertTrue(
            self.raw.startswith(UTF8_BOM),
            "run.ps1 含非 ASCII 字符却没有 UTF-8 BOM。"
            "PowerShell 5.1 会按系统 ANSI（中文 Windows = GBK）解码，"
            "中文会被解错并吃掉引号/大括号，报出一批离奇语法错误。"
            "修法：以 UTF-8 with BOM 重新保存。",
        )

    def test_body_decodes_as_utf8(self) -> None:
        text = self.raw[len(UTF8_BOM):] if self.raw.startswith(UTF8_BOM) else self.raw
        text.decode("utf-8")  # 抛 UnicodeDecodeError 即失败


class RunScriptStopPathTest(unittest.TestCase):
    """停止路径：`-Id` 重复绑定会让 Ctrl+C 直接报错。"""

    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8-sig")
        self.lines = self.text.splitlines()

    def test_wait_process_id_is_not_repeated(self) -> None:
        offenders = []
        for idx, line in enumerate(self.lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue  # 注释里会举反例，不算
            if "Wait-Process" in line and line.count("-Id") > 1:
                offenders.append(f"  第 {idx} 行: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "Wait-Process 的 -Id 只能出现一次，多进程必须传数组（-Id @($a, $b)）。"
            "写成 -Id $a -Id $b 会以「多次指定了参数 Id」参数绑定失败：\n"
            + "\n".join(offenders),
        )

    def test_stop_process_passes_array(self) -> None:
        self.assertRegex(
            self.text,
            r"Stop-Process\s+-Id\s+@\(",
            "停止服务时 Stop-Process 的 -Id 应以数组传入，避免沿用单值写法时误加第二个 -Id。",
        )


class RunScriptInterpreterProbeTest(unittest.TestCase):
    """解释器判定：能力探测，且探的是真正需要的能力。"""

    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8-sig")

    def test_skips_windowsapps_alias_placeholders(self) -> None:
        """WindowsApps 下的 0 字节别名必须被剔除，否则「假成功」。"""
        self.assertIn(
            r"\WindowsApps\*",
            self.text,
            "必须显式跳过 %LOCALAPPDATA%\\Microsoft\\WindowsApps 下的应用执行别名占位符："
            "它们能被 Get-Command 命中，执行时却只打印「Python was not found」。",
        )

    def test_probe_checks_ssl_capability_not_only_version(self) -> None:
        """探测能力必须是 ssl/venv，而不只是 --version。"""
        self.assertRegex(
            self.text,
            r"-c\",\s*\"import[^\"]*\bssl\b",
            "解释器探测必须真跑一次 import ssl,venv：只验 --version 会漏掉 _ssl 加载失败的"
            "残缺安装——它打印得出版本号，pip 却走不了 HTTPS，装依赖必然失败。",
        )

    def test_rejects_zero_byte_interpreter(self) -> None:
        self.assertRegex(
            self.text,
            r"Length\s+-eq\s+0",
            "0 字节文件就是应用执行别名占位符，应在探测阶段直接判否。",
        )

    def test_fails_loudly_when_no_interpreter(self) -> None:
        self.assertRegex(
            self.text,
            r"找不到可用的 Python[\s\S]{0,1500}?exit 1",
            "找不到可用解释器时必须报错并以非零码退出，不能静默继续。",
        )


class RunScriptStartupHonestyTest(unittest.TestCase):
    """「假成功」防护：必须探活通过才允许打印成功横幅。"""

    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8-sig")

    def test_success_banner_comes_after_health_probe(self) -> None:
        probe = self.text.find('Wait-HttpOk "http://127.0.0.1:$BackendPort/api/health"')
        banner = self.text.find('Write-Host "  frontend: ')
        self.assertNotEqual(probe, -1, "必须对 /api/health 做真实探活")
        self.assertNotEqual(banner, -1, "缺少成功横幅")
        self.assertLess(
            probe,
            banner,
            "成功横幅必须排在探活之后：否则进程没起来也会打印「一切正常」（假成功）。",
        )

    def test_exit_codes_reported_on_startup_failure(self) -> None:
        self.assertRegex(
            self.text,
            r"HasExited[\s\S]{0,200}?ExitCode",
            "启动失败时应报出子进程退出码，便于定位（而不是只显示一句「未就绪」）。",
        )


class RunScriptPortHardeningTest(unittest.TestCase):
    """端口加固（2026-09-29）：预检占用 / 探活后校验进程存活 / 端口可覆盖。

    背景：8080 被本机 CAD 阅读器（CADReader.exe）占用过。http.server 绑定失败
    会静默退出，而探活 GET / 可能被占用方的 HTTP 服务答 200 —— 旧版会打印
    「成功」而前端实际没起来，正好绕过「探到 200 才报成功」的假成功防线。
    """

    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8-sig")

    def test_ports_overridable_via_env(self) -> None:
        """端口撞车时必须能换端口而不改脚本；覆盖值须做合法性校验。"""
        # P0 架构收敛（2026-10-07）：:8080 并入 :8000、:8010 并入 :3456，只剩两个端口变量
        for env in ("BIDPRICING_BACKEND_PORT", "BIDPRICING_WORKBENCH_PORT"):
            self.assertIn(env, self.text, f"缺少端口覆盖变量 {env}")
        self.assertIn(
            "[int]::TryParse",
            self.text,
            "环境变量给的端口必须校验（1-65535），不能直接转 int 冒异常。",
        )

    def test_port_occupancy_checked_before_spawn(self) -> None:
        """起服务前必须预检端口占用并报出占用者，不能等探活误导。"""
        pre = self.text.find("Assert-PortFree")
        spawn = self.text.find("Start-Process")
        self.assertNotEqual(pre, -1, "缺少端口预检（Assert-PortFree）")
        self.assertNotEqual(spawn, -1)
        self.assertLess(
            pre, spawn, "端口预检必须发生在 Start-Process 之前：占用就明说谁占的。")
        self.assertIn(
            "Get-NetTCPConnection",
            self.text,
            "预检须真实查询监听端口（Get-NetTCPConnection），不得只凭探活。",
        )

    def test_probe_success_verifies_spawned_process_alive(self) -> None:
        """探活 200 可能由占用同端口的外来服务答出——须校验自己拉起的进程还活着。"""
        backend_guards = list(re.finditer(r"\$backend\.HasExited", self.text))
        self.assertGreaterEqual(
            len(backend_guards), 2,
            "后端至少两处 HasExited：探活失败分支（报退出码）+ 探活成功后的假成功拦截。")
        # P0 架构收敛（2026-10-07）：前端静态已并入后端同进程（:8000 的 / 挂 frontend/），
        # 不再有独立 $frontend 进程；假成功拦截由后端的 HasExited 覆盖。
        # 此处只要求：无残留 $frontend 引用，且静态挂载本身被探活（目录缺失时 mount 跳过会 404）。
        self.assertNotIn("$frontend", self.text, "不应再有独立前端进程变量残留")
        self.assertIn(
            'Wait-HttpOk "http://127.0.0.1:$BackendPort/"',
            self.text,
            "前端静态（:8000 的 /）必须被探活，确认 mount 生效。")
        banner = self.text.find('Write-Host "  frontend: ')
        self.assertGreater(
            banner, backend_guards[-1].start(),
            "假成功拦截必须先于成功横幅。")

    def test_false_success_guard_precedes_success_banner(self) -> None:
        banner = self.text.find('Write-Host "  frontend: ')
        guard = self.text.find("假成功拦截")
        self.assertNotEqual(guard, -1, "缺少假成功拦截文案")
        self.assertLess(guard, banner, "假成功拦截必须出现在成功横幅之前。")


class RunScriptNativeCommandTest(unittest.TestCase):
    """原生命令的 stderr 陷阱：Stop 偏好会把 pip 的警告升级成终止错误。"""

    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8-sig")

    def test_native_calls_go_through_tolerant_wrapper(self) -> None:
        self.assertIn(
            "function Invoke-Native",
            self.text,
            "原生命令须有统一包装：临时把 ErrorActionPreference 降为 Continue，"
            "否则原生命令写 stderr（pip 的警告）会被 Stop 升级为终止性错误。",
        )
        self.assertRegex(
            self.text,
            r'Invoke-Native[^\r\n]*"pip",\s*"install"',
            "pip install 必须走 Invoke-Native。实测：直接调用时 pip 的 "
            "「Disabling truststore since ssl support is missing」警告会被 "
            "$ErrorActionPreference=\"Stop\" 升级成终止错误，脚本在装依赖中途暴毙。",
        )

    def test_pip_targets_venv_and_requirements_file(self) -> None:
        self.assertIn(
            "requirements-web.txt",
            self.text,
            "依赖清单须以 requirements-web.txt 为准，不得在脚本里另写一份包名。",
        )
        self.assertIn(
            'Join-Path $Root ".venv"',
            self.text,
            "依赖应装进仓库内 .venv，避免污染系统解释器。",
        )


class RunScriptDocConsistencyTest(unittest.TestCase):
    """口径一致性：脚本行为变了，文档必须跟着变（否则又出现「文档说 A、实现做 B」）。"""

    def test_readme_and_handoff_mention_venv_and_bom_contract(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        handoff = (ROOT / "docs" / "PROJECT_HANDOFF.md").read_text(encoding="utf-8")
        for name, text in (("README.md", readme), ("PROJECT_HANDOFF.md", handoff)):
            with self.subTest(doc=name):
                self.assertIn(".venv", text, f"{name} 未说明 .venv 隔离")
                self.assertIn("能力探测", text, f"{name} 未说明解释器能力探测")
                self.assertIn(".python-path", text, f"{name} 未说明 .python-path 钉死方式")

    def test_gitignore_covers_launcher_artifacts(self) -> None:
        gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pat in (".venv/", ".venv.broken-*/", ".python-path"):
            with self.subTest(pattern=pat):
                self.assertIn(pat, gi, f".gitignore 未忽略 {pat}")


if __name__ == "__main__":
    unittest.main()
