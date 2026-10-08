"""受控制品的「字节保真」判据：干净检出必须复现注册表里的 hash。

动因（2026-10-08 实测）：`compute_artifact_hash` 对原始字节取 SHA-256，而开发者
全局 `~/.gitconfig` 的 `core.autocrlf=input` 会在提交时把 CRLF 转成 LF 存进索引。
结果工作树（CRLF）算出的 hash 与注册表一致，而**干净检出（LF）算出的不一致**，
9 个受控制品报「制品已变更但未重新冻结（契约失效）」，Gate 0a/0b 双双 BLOCKED。
CI 自 2026-10-07 上线起 90 次运行 0 次成功，且 Gate 之后的 contract-check、
全量测试被连带 skipped——为防「静默失效」而建的门禁，自己静默失效了一天。
（逐字节核对确认这 9 项内容级失配为 0，差异纯粹是行尾；即 git 擅自改写了
 用户 2026-09-17 以四角色签署过的字节。）

为什么这条判据要拆成两半（缺一不可）：
  A) HEAD blob 的 hash == 注册表声明的 hash；
  B) 该文件的 `text` 属性必须是 unset/false（即 .gitattributes 里的 `-text`）。

只看 A 会漏：若某文件没有 -text，`git show HEAD:path` 给出的是**存储时的原始 blob**，
而 `checkout` 会按 autocrlf **再转换一次**——两者此刻相等，检出后却不等。
所以必须同时钉 B：没有字节保真声明，A 的相等就是巧合而非保证。
A+B 合起来才等价于「做一次真实干净检出再算 hash」，且不必付 worktree 的开销。

本测试还顺手钉住 .gitattributes 自身的两条结构性质（顺序、覆盖面），因为它
本身就是个「手工清单」——写错顺序（git 属性后匹配者胜）或漏了某类制品，
保护就会**静默失效**，而这正是本仓反复踩过的同一族问题。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"
REGISTRY = CFG / "gate0_registry.json"
ATTRS = ROOT / ".gitattributes"

#: 不参与 hash 的注册表条目类型（enum 无制品文件）。
NON_HASHED_KINDS = ("enum", "approvals")


def _sha12(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          check=True).stdout


def _hashed_artifacts() -> list[tuple[str, str, str]]:
    """[(gate.key, 相对路径, 注册表 hash)]，只取需要复现 hash 的条目。"""
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    out = []
    for gate in ("gate_0a", "gate_0b"):
        for key, v in (reg.get(gate) or {}).items():
            if not isinstance(v, dict):
                continue
            path, hh = v.get("artifact_path"), v.get("hash")
            if not path or not hh or v.get("kind") in NON_HASHED_KINDS:
                continue
            out.append((f"{gate}.{key}", f"config/{path}", hh))
    return out


class ArtifactByteFidelityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not REGISTRY.exists():
            raise unittest.SkipTest(f"注册表不存在：{REGISTRY}")
        cls.artifacts = _hashed_artifacts()

    def test_registry_has_hashed_artifacts(self):
        """扫描本身要有效：取不到任何受控 hash 就说明解析逻辑坏了（防空转绿灯）。"""
        self.assertGreater(len(self.artifacts), 0,
                           "注册表里没解析出任何受控制品——测试逻辑可能失效")

    def test_clean_checkout_reproduces_declared_hash(self):
        """A：HEAD blob 的字节 hash == 注册表声明值。

        失配意味着「本机绿、干净检出红」：hash 是在某种行尾下算的，仓库里存的却是
        另一种字节。签署类制品尤其致命——签名指向的字节在版本库里并不存在。
        """
        bad = []
        for label, rel, declared in self.artifacts:
            blob = _git("show", f"HEAD:{rel}")
            got = "sha256:" + _sha12(blob)
            if got != declared:
                bad.append((label, rel, declared, got,
                            "CRLF" if b"\r\n" in blob else "LF"))
        self.assertEqual(
            bad, [],
            msg="干净检出的字节复现不出注册表 hash（行尾被 git 转换所致或制品未重冻）：\n"
                + "\n".join(f"  {k} ({p}) 声明={want} 检出={got} blob={eol}"
                            for k, p, want, got, eol in bad))

    def test_hashed_artifacts_are_marked_binary_safe(self):
        """B：每个受控制品的 text 属性必须是 unset/false（-text），否则 A 的相等只是巧合。"""
        unguarded = []
        for label, rel, _declared in self.artifacts:
            out = _git("check-attr", "text", "--", rel).decode("utf-8", "replace")
            # 形如：config/field_schema.json: text: unset
            val = out.rsplit(":", 1)[-1].strip().lower()
            if val not in ("unset", "false"):
                unguarded.append((rel, val))
        self.assertEqual(
            unguarded, [],
            msg="这些受控制品没有 `-text` 字节保真声明，autocrlf 可改写其字节：\n"
                + "\n".join(f"  {p} → text: {v}" for p, v in unguarded)
                + "\n修法：在 .gitattributes 的 `config/** -text` 覆盖范围内（且须位于"
                  "通用 `text eol=` 段之后，git 属性后匹配者胜）。")


class GitAttributesStructureTest(unittest.TestCase):
    """钉住 .gitattributes 自身的结构——它也是个手工清单，写坏了保护会静默消失。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not ATTRS.exists():
            raise unittest.SkipTest("缺少 .gitattributes")
        cls.lines = [ln.split("#", 1)[0].rstrip()
                     for ln in ATTRS.read_text(encoding="utf-8").splitlines()]
        cls.rules = [ln.strip() for ln in cls.lines if ln.strip()]

    def test_file_exists_and_nonempty(self):
        self.assertTrue(self.rules, ".gitattributes 里没有任何有效规则")

    def test_config_protect_rule_comes_after_generic_text_rules(self):
        """`config/** -text` 必须在 `*.json text eol=lf` **之后**：git 属性后匹配者胜。

        写反过一次（由 git check-attr 抓出）：彼时 config 下制品解成 text: set/eol: lf，
        保护形同虚设，而文件里看着一切正常。
        """
        def first_idx(pred):
            return next((i for i, r in enumerate(self.rules) if pred(r)), None)

        i_protect = first_idx(lambda r: r.startswith("config/**") and "-text" in r)
        self.assertIsNotNone(i_protect, "缺 `config/** -text` 规则")
        i_generic = first_idx(lambda r: r.startswith("*.json") and "eol=lf" in r)
        if i_generic is not None:
            self.assertGreater(
                i_protect, i_generic,
                msg="`config/** -text` 必须排在 `*.json text eol=lf` 之后——"
                    "git 属性后匹配者胜，顺序写反则受控制品仍会被转换行尾。")

    def test_run_ps1_is_byte_preserving(self):
        """run.ps1 靠 UTF-8 BOM 保命，字节须原样；不强加 eol（历史上它就是 LF）。"""
        self.assertTrue(
            any(r.startswith("*.ps1") and "-text" in r for r in self.rules),
            "run.ps1 应经 `*.ps1 -text` 保字节，且不写 eol（避免 checkout 时无谓改写）")


class WorktreeMatchesHeadForArtifactsTest(unittest.TestCase):
    """同一台机器上「工作树 == HEAD blob」也要成立：否则有人正拿着未提交的字节改动。

    与 test_clean_checkout_reproduces_declared_hash 合起来，才排除「本地一套、
    仓库一套」这种只在单机成立的 hash 治理。
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not REGISTRY.exists():
            raise unittest.SkipTest("缺少注册表")
        cls.artifacts = _hashed_artifacts()

    def test_worktree_bytes_match_head(self):
        drift = []
        for label, rel, _ in self.artifacts:
            p = ROOT / rel
            if not p.exists():
                continue
            head = _git("show", f"HEAD:{rel}")
            if p.read_bytes() != head:
                drift.append((label, rel))
        self.assertEqual(
            drift, [],
            msg="这些受控制品的工作树字节与 HEAD blob 不一致（未提交或工作树被改）：\n"
                + "\n".join(f"  {k} ({p})" for k, p in drift)
                + "\n受控制品的任何字节变更都必须走重新冻结，不留未提交状态。")


if __name__ == "__main__":
    unittest.main()
