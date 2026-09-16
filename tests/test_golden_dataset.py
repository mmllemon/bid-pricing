"""T01-02C Golden Dataset 复算断言 —— Gate 1 的「100% 通过」绑定版本号。

判据（任务板原文）：六类分层用例齐备（A 正常 / B 边界 / C 退化 / D 不可行 /
E 极端尺度 / F 对抗构造）；每类含正例与负例；**固定随机种子**；Gate 1 的
「100% 通过」必须绑定本数据集**版本号**，不允许开发人员用一个简单 Excel
声称通过。

本测试对 ``tests/data/golden/<version>/`` 的制品逐用例**复算**：

* ``manifest_hash`` 重算比对——手改期望（让红变绿）即失配；
* 每用例期望 ``expect`` 逐字段比对（解析/清洗/匹配全链路）；
* ``spot_check`` 抽样数值核对（q0 / cap / c_i 精确值）。

期望改动必须走 ``tools/make_golden.py`` 重生成，不允许在制品上手补。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from bidpricing.io.boq import parse_listing
from bidpricing.io.clean import clean_listing_rows
from bidpricing.io.golden import GOLDEN_VERSION, manifest_hash
from bidpricing.io.match import match_canonical_rows
from bidpricing.paths import repo_root

GOLDEN_DIR = repo_root() / "tests" / "data" / "golden" / GOLDEN_VERSION


class GoldenDatasetTest(unittest.TestCase):
    """数据集是**提交在 git 里的制品**——缺失即失败（不跳过）。"""

    @classmethod
    def setUpClass(cls):
        cls.manifest_path = GOLDEN_DIR / "manifest.json"
        cls.assertTrue(
            cls, cls.manifest_path.exists(),
            f"Golden Dataset 制品缺失：{cls.manifest_path}")
        cls.manifest = json.loads(cls.manifest_path.read_text(encoding="utf-8"))

    # ---------------------------------------------------- 制品完整性

    def test_version_bound(self):
        """Gate 1 绑定版本号：manifest 版本与生成器常量必须一致。"""
        self.assertEqual(self.manifest["golden_version"], GOLDEN_VERSION)

    def test_manifest_hash_unchanged(self):
        """期望表指纹：手改 manifest（让红变绿）→ 失配。"""
        self.assertEqual(
            self.manifest["manifest_hash"], manifest_hash(self.manifest))

    def test_six_categories_with_positive_and_negative(self):
        cats = {c["category"] for c in self.manifest["cases"]}
        self.assertEqual(cats, {"A", "B", "C", "D", "E", "F"})
        for cat in "ABCDEF":
            kinds = {c["kind"] for c in self.manifest["cases"]
                     if c["category"] == cat}
            self.assertEqual(kinds, {"positive", "negative"}, cat)
        for c in self.manifest["cases"]:
            for side in ("cap", "cost"):
                if side in c["files"]:
                    self.assertTrue(
                        (GOLDEN_DIR / c["files"][side]).exists(),
                        f"{c['case_id']} {side} 文件缺失")

    def test_seed_fixed(self):
        """固定随机种子：同种子重生成必须逐字节复现（下一测试实证）。"""
        self.assertEqual(self.manifest["seed"], 20260916)

    def test_regeneration_is_deterministic(self):
        """同种子重生成 → 期望表逐字节复现（数据集可复现）。"""
        import tempfile

        from bidpricing.io.golden import generate_golden

        with tempfile.TemporaryDirectory() as tmp:
            m2 = generate_golden(Path(tmp), version="regen-probe", seed=20260916)
        # 版本名统一后 hash 必须相等（cases 内容决定 hash，版本名只作隔离）
        self.assertEqual(
            manifest_hash({**m2, "golden_version": GOLDEN_VERSION}),
            manifest_hash(self.manifest))

    # ---------------------------------------------------- 逐用例复算

    def _run_case(self, entry: dict) -> dict:
        actual = {"rows": 0, "failures": 0, "skipped": 0,
                  "matched": 0, "blocked": False, "anomalies": 0}
        cap_rows, cost_rows = [], []
        for side, sink in (("cap", cap_rows), ("cost", cost_rows)):
            if side not in entry["files"]:
                continue
            rep = parse_listing(GOLDEN_DIR / entry["files"][side], "golden")
            cleaned, crep = clean_listing_rows(rep.rows, side)
            sink.extend(cleaned)
            actual["rows"] += len(rep.rows)
            actual["failures"] += len(rep.failures)
            actual["skipped"] += rep.skipped_rows
            if side == "cap":
                actual["no_cap"] = len(crep.no_cap_items)
        mrep = match_canonical_rows(cap_rows, cost_rows)
        actual["matched"] = mrep.n_matched
        actual["blocked"] = mrep.blocked
        actual["anomalies"] = len(mrep.anomalies)
        return actual

    def test_expectations_hold(self):
        """每个用例的期望逐字段复算比对——这是 Gate 1 的「100% 通过」。"""
        for entry in self.manifest["cases"]:
            with self.subTest(case=entry["case_id"]):
                actual = self._run_case(entry)
                for key, want in entry["expect"].items():
                    self.assertEqual(actual[key], want,
                                     f"{entry['case_id']}.{key}")

    def test_spot_check_values(self):
        """抽样数值核对：清洗后的 q0/cap/c_i 与生成时期望精确一致。"""
        for entry in self.manifest["cases"]:
            if not entry.get("spot_check"):
                continue
            parsed: dict[str, dict] = {}
            for side in ("cap", "cost"):
                if side not in entry["files"]:
                    continue
                rep = parse_listing(GOLDEN_DIR / entry["files"][side], "golden")
                cleaned, _ = clean_listing_rows(rep.rows, side)
                for r in cleaned:
                    d = parsed.setdefault(r.item_id, {})
                    if side == "cap":
                        d.update(q0=r.q0, cap=r.cap, no_cap=r.no_cap)
                    else:
                        d.update(q1_point=r.q1_point, c_i=r.c_i)
            with self.subTest(case=entry["case_id"]):
                for item_id, want in entry["spot_check"].items():
                    self.assertIn(item_id, parsed, item_id)
                    got = parsed[item_id]
                    for field, wv in want.items():
                        if field == "no_cap":
                            self.assertEqual(got.get(field), wv, item_id)
                        elif wv is None:
                            # no_cap 项：cap 保持 None（空值 ≠ 0）
                            self.assertIsNone(got.get(field), item_id)
                        else:
                            self.assertIsNotNone(got.get(field), item_id)
                            self.assertAlmostEqual(got[field], wv, places=6, msg=item_id)


if __name__ == "__main__":
    unittest.main()
