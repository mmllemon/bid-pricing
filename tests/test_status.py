"""状态快照派生机制的测试。

覆盖三条核心不变量：

1. **生效状态的双轨规则** —— 人工声明优先；未声明而证据成立判 done；
   `partial` 不被证据覆盖（否则会用"机制就绪"掩盖"数据未填"）。
2. **下一步派生** —— 只列依赖已满足且自身未完成的任务。
3. **证据核对** —— 制品 hash 非空 / 模块存在 才算成立。

注意：所有用例调用 `collect(..., run_test_suite=False)`。若传 True，
测试会去子进程跑测试套件，而套件里又包含本文件——无限递归。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.artifact import load_registry
from bidpricing.paths import GATE0_REGISTRY, config_dir, repo_root
from bidpricing.status import (
    check_evidence,
    collect,
    derive_next_steps,
    effective_status,
    render,
)


def _task(tid: str, **kw) -> dict:
    base = {"id": tid, "wp": "WP0", "title": tid, "deliverable": "", "deps": [],
            "status": "not_started", "note": ""}
    base.update(kw)
    return base


class EffectiveStatusTest(unittest.TestCase):
    """生效状态 = 人工声明优先；未声明而证据成立 → done。"""

    def test_evidence_promotes_undeclared_task(self):
        """人工没写状态，但证据成立 → 判 done。证据能证明的事不该要求人再抄一遍。"""
        t = _task("T00-02", status="not_started", evidence_ok=True)
        self.assertEqual(effective_status(t), "done")

    def test_manual_partial_not_overridden_by_evidence(self):
        """人工写 partial，即使证据成立也保持 partial。

        T00-06 即此情形：规则书已冻结（证据成立），但项目级落值表仍为空。
        若被覆盖成 done，等于宣布一个尚未完成的任务已完成。
        """
        t = _task("T00-06", status="partial", evidence_ok=True)
        self.assertEqual(effective_status(t), "partial")

    def test_manual_done_stays_done(self):
        t = _task("T00-08", status="done", evidence_ok=True)
        self.assertEqual(effective_status(t), "done")

    def test_no_evidence_no_promotion(self):
        """无证据声明且人工未填 → 保持 not_started。"""
        t = _task("T05-01", status="not_started", evidence_ok=None)
        self.assertEqual(effective_status(t), "not_started")


class EvidenceCheckTest(unittest.TestCase):
    def test_frozen_artifact_satisfies(self):
        registry = {"gate_0a": {"some_spec": {
            "kind": "versioned", "artifact_path": "x.json",
            "version": "v1", "hash": "sha256:abc", "frozen_at": "2026-01-01T00:00:00+00:00",
        }}}
        ok, detail = check_evidence(
            {"evidence": [{"kind": "artifact", "key": "some_spec"}]}, registry, repo_root()
        )
        self.assertTrue(ok)
        self.assertIn("已冻结", detail)

    def test_unfrozen_artifact_fails(self):
        registry = {"gate_0a": {"some_spec": {
            "kind": "versioned", "artifact_path": "x.json",
            "version": None, "hash": None, "frozen_at": None,
        }}}
        ok, detail = check_evidence(
            {"evidence": [{"kind": "artifact", "key": "some_spec"}]}, registry, repo_root()
        )
        self.assertFalse(ok)
        self.assertIn("未冻结", detail)

    def test_missing_artifact_key_fails(self):
        ok, _ = check_evidence(
            {"evidence": [{"kind": "artifact", "key": "nope"}]}, {"gate_0a": {}}, repo_root()
        )
        self.assertFalse(ok)

    def test_module_evidence(self):
        ok, _ = check_evidence(
            {"evidence": [{"kind": "module", "path": "src/bidpricing/status.py"}]},
            {"gate_0a": {}}, repo_root(),
        )
        self.assertTrue(ok)
        missing, _ = check_evidence(
            {"evidence": [{"kind": "module", "path": "src/bidpricing/nope.py"}]},
            {"gate_0a": {}}, repo_root(),
        )
        self.assertFalse(missing)

    def test_no_evidence_declared(self):
        ok, detail = check_evidence({"evidence": []}, {"gate_0a": {}}, repo_root())
        self.assertIsNone(ok)
        self.assertEqual(detail, "")

    def test_unknown_kind_fails_loudly(self):
        """未知证据类型必须判不成立——不能默默当作"无法判定"而放行。"""
        ok, detail = check_evidence(
            {"evidence": [{"kind": "telepathy"}]}, {"gate_0a": {}}, repo_root()
        )
        self.assertFalse(ok)
        self.assertIn("未知证据类型", detail)


class DeriveNextStepsTest(unittest.TestCase):
    def test_excludes_done_and_blocked_deps(self):
        tasks = [
            _task("T00-02", status="done"),
            _task("T01-00A", status="done"),
            _task("T01-00B", deps=["T00-02", "T01-00A"], status="ready"),
            _task("T01-01", deps=["T00-02"]),
            _task("T04-01", deps=["T03-07"]),      # 依赖未完成 → 不列
            _task("T03-07"),                        # 依赖为空 → 可列
        ]
        ids = [n["id"] for n in derive_next_steps(tasks)]
        self.assertIn("T01-00B", ids)
        self.assertIn("T01-01", ids)
        self.assertIn("T03-07", ids)
        self.assertNotIn("T04-01", ids)
        self.assertNotIn("T00-02", ids)   # done 的不列

    def test_partial_satisfies_dependency(self):
        """partial 视为依赖已满足——机制就绪即可下游开工（ADR-0002）。"""
        tasks = [_task("T00-06", status="partial"), _task("T00-06B", deps=["T00-06"])]
        self.assertIn("T00-06B", [n["id"] for n in derive_next_steps(tasks)])

    def test_external_deps_flagged(self):
        """依赖中指向任务表之外的部分（如语义性依赖）必须被标注出来。"""
        tasks = [
            _task("T00-01", status="done"),
            _task("T00-10B", deps=["T00-01", "T99-99"]),
        ]
        nxt = derive_next_steps(tasks)
        self.assertEqual(nxt[0]["id"], "T00-10B")
        self.assertEqual(nxt[0]["external_deps"], ["T99-99"])

    def test_sorted_by_wp_then_id(self):
        tasks = [_task("T03-01"), _task("T01-05"), _task("T01-01")]
        ids = [n["id"] for n in derive_next_steps(tasks)]
        self.assertEqual(ids, ["T01-01", "T01-05", "T03-01"])

    def test_limit_applied(self):
        tasks = [_task(f"T01-{i:02d}") for i in range(1, 12)]
        self.assertEqual(len(derive_next_steps(tasks, limit=3)), 3)


class AdvisoriesTest(unittest.TestCase):
    def test_known_limits_collected_recursively(self):
        from bidpricing.status import _walk_known_limits

        data = {"a": {"known_limits": ["x", "y"]}, "b": [{"freeze_blocker": "z"}]}
        found = _walk_known_limits(data)
        self.assertEqual(len(found), 3)
        self.assertTrue(any("z" in f for f in found))


class RenderTest(unittest.TestCase):
    def _snap(self) -> dict:
        return {
            "generated_at": "2026-09-16 10:00:00",
            "contract_date": "2026-03-01",
            "git": {"available": True, "head": "abc1234", "subject": "test",
                    "tags": ["v1"], "dirty": 0, "commits_total": "5", "unpushed": ""},
            "gates": {"gate_0a": "PASS", "gate_0b": "BLOCKED",
                      "phase_0_input_gate": "BLOCKED", "phase_0": "BLOCKED",
                      "wp4_solver_layer": "BLOCKED"},
            "gate_0a_items": [],
            "artifacts": [{"key": "k", "kind": "versioned",
                           "hash": "sha256:deadbeef", "frozen_at": "2026-01-01"}],
            "tests": {"ran": 98, "ok": True, "detail": "OK"},
            "tasks": [_task("T00-02", status="done", evidence_ok=True,
                            evidence_detail="已冻结", effective_status="done")],
            "task_counts": {"total": 68, "by_wp": {"WP0": 15}},
            "next_steps": [{"id": "T01-00B", "wp": "WP1", "title": "解析器",
                            "deliverable": "解析器", "status": "ready",
                            "note": "", "external_deps": []}],
            "advisories": ["某配置 → known_limits: 示例"],
        }

    def test_banner_forbids_manual_edit(self):
        """生成物必须自带「勿手改」声明——这是防漂移的第一道提示。"""
        out = render(self._snap())
        self.assertIn("自动生成", out)
        self.assertIn("请勿手工编辑", out)

    def test_contains_all_sections(self):
        out = render(self._snap())
        for section in ("一、版本锚点", "二、闸门状态", "三、契约制品冻结表",
                        "四、质量门", "五、任务进度", "六、下一步",
                        "七、遗留项", "八、复现全部结论"):
            self.assertIn(section, out)

    def test_lists_blocked_items_when_present(self):
        snap = self._snap()
        snap["gate_0a_items"] = [
            {"item": "x", "status": "BLOCKED", "reason": "缺项目数据"}
        ]
        out = render(snap)
        self.assertIn("Gate 0a 阻塞项", out)
        self.assertIn("缺项目数据", out)

    def test_states_no_blocker_when_gate_passes(self):
        out = render(self._snap())
        self.assertIn("无阻塞项", out)


class RealRepoStateTest(unittest.TestCase):
    """真实仓库上的派生结果——保证任务板与注册表能被正常消费。"""

    def test_collect_smoke(self):
        snap = collect(run_test_suite=False)   # 必须关掉，否则递归跑测试
        self.assertEqual(snap["task_counts"]["total"], 68)
        self.assertEqual(len(snap["tasks"]), 68)
        self.assertIn(snap["gates"]["gate_0a"], {"PASS", "BLOCKED"})

    def test_contract_consistency_is_collected_and_green(self):
        """跨制品一致性必须进快照，且真实仓库上应为 PASS。

        进快照的理由与测试数同理：**状态数字一律不手写**。若把「10/10」写进
        README 或 CHANGELOG，它迟早会漂移；派生出来才不会。
        """
        snap = collect(run_test_suite=False)
        cc = snap["contract_consistency"]
        self.assertEqual(cc["worst"], "PASS", [i for i in cc["items"]
                                               if i["status"] != "PASS"])
        self.assertTrue(cc["items"], "判据清单不应为空")
        self.assertIn("约束", cc["headline"])

    def test_contract_consistency_is_rendered(self):
        snap = collect(run_test_suite=False)
        text = render(snap)
        self.assertIn("跨制品一致性", text)
        self.assertIn("contract-check", text)

    def test_all_evidence_backed_tasks_resolve(self):
        """声明了证据的任务，其证据必须真的成立——否则任务板在撒谎。"""
        cdir = config_dir()
        registry = load_registry(cdir / GATE0_REGISTRY)
        tasks = json.loads(
            (repo_root() / "docs" / "tasks.json").read_text(encoding="utf-8")
        )["tasks"]
        with_evidence = [t for t in tasks if t.get("evidence")]
        self.assertTrue(with_evidence, "任务板里应当存在带证据的任务")
        for t in with_evidence:
            ok, detail = check_evidence(t, registry, repo_root())
            self.assertTrue(ok, f"{t['id']} 证据应成立：{detail}")

    def test_task_ids_unique(self):
        tasks = json.loads(
            (repo_root() / "docs" / "tasks.json").read_text(encoding="utf-8")
        )["tasks"]
        ids = [t["id"] for t in tasks]
        self.assertEqual(len(ids), len(set(ids)), "任务编号不得重复")

    def test_no_dangling_dependency(self):
        """依赖必须指向真实存在的任务，否则"可开工"判定会漏掉未满足的前置。"""
        tasks = json.loads(
            (repo_root() / "docs" / "tasks.json").read_text(encoding="utf-8")
        )["tasks"]
        ids = {t["id"] for t in tasks}
        for t in tasks:
            for d in t.get("deps", []):
                self.assertIn(d, ids, f"{t['id']} 依赖 {d} 不存在")


class WriteStateTest(unittest.TestCase):
    def test_write_creates_file_with_banner(self):
        """写盘路径可自定义——用临时目录验证，避免污染真实 docs/。"""
        import bidpricing.status as st

        original = st.docs_dir
        with tempfile.TemporaryDirectory() as tmp:
            st.docs_dir = lambda: Path(tmp)
            try:
                snap = st.collect(run_test_suite=False)
                target = Path(tmp) / "STATE.md"
                target.write_text(st.render(snap), encoding="utf-8")
                text = target.read_text(encoding="utf-8")
                self.assertIn("请勿手工编辑", text)
                self.assertIn("# 项目状态快照", text)
            finally:
                st.docs_dir = original


if __name__ == "__main__":
    unittest.main()
