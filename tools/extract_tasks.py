"""从《实施路线》文档提取任务清单 → docs/tasks.json（机器可读任务板）。

## 为什么要有这个脚本

路线文档（`.agentchat/impl_plan_v321.md`）是任务定义的**权威源**，但它是
给人读的 Markdown 表格，代码无法消费。若要人工把 68 个任务誊抄进 JSON，
誊抄本身就是一次漂移源，而且路线升版（v3.3 已在文档第五节登记）后必然失配。

故本脚本**单向派生**：文档 → JSON。规则是

    结构字段（id/wp/title/deliverable/deps/type）  从文档提取，不接受手改
    状态字段（status/evidence/note）               保留 JSON 中已有值，脚本不覆盖

即：**改结构去改文档再重跑；改状态直接改 JSON**。两者互不污染。

## 用法

    python tools/extract_tasks.py            # 增量合并（保留已有人工字段）
    python tools/extract_tasks.py --check    # 只校验，不写盘；发现结构漂移则退出码 1

`--check` 供 CI 使用：路线文档改了而 tasks.json 未重新提取时，构建应当失败，
而不是让任务板悄悄过期。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPO.parent / ".agentchat" / "impl_plan_v321.md"
TASKS_JSON = REPO / "docs" / "tasks.json"

# 分节标题形如：## WP6 交付层 → **Gate 5A**（8 项）
#               ## WP7 闭环 → **Gate 6**（4 项，不阻塞交付）
# 括号内可能带附加说明，故用 [^）]* 而非直接闭括号——否则 WP7 无法识别，
# 其任务会被并入上一节（实测踩过：12/4 被错并为 12）。
WP_HEADING = re.compile(r"^##\s+WP(\d+)\s+(.*?)（(\d+)\s*项[^）]*）")
TASK_ROW = re.compile(r"^\|\s*\*{0,2}(T\d{2}-\d{2}[A-Z]?)\*{0,2}\s*\|")

#: 任务状态 → 由代码证据派生（见 status.py）。此处只声明「证据在哪」。
#: 键为任务号，值为 evidence 列表；每条 evidence 形如
#:   {"kind": "artifact", "key": "<注册表 key>"}    制品已冻结（hash 非 null）即判 done
#:   {"kind": "module",   "path": "src/..."}        模块存在即判 done
#:   {"kind": "file",     "path": "tests/data/..."} 数据类制品存在即判 done
#: 未列出的任务一律 status = "not_started"，需人工推进后再补证据。
EVIDENCE: dict[str, list[dict]] = {
    "T00-02": [{"kind": "artifact", "key": "field_schema_version"}],
    # 以下 T00-01/03/04/06/06B/12 六条系 2026-09-17 非破坏性回灌：
    # 方向是「tasks.json 的富 evidence → 字典」（存盘值更全、曾发现字典
    # 把 T00-06B 写成 identity.py 的错误路径），而非反向重写存盘值。
    "T00-01": [
        {"kind": "artifact", "key": "contract_ruleset_version"},
        {"kind": "module", "path": "src/bidpricing/contracts/pricing_card.py"},
        {"kind": "adr", "path": "ADR-0017-contract-review-must-be-attributed.md"},
    ],
    "T00-03": [
        {"kind": "artifact", "key": "constraint_schema_version"},
        {"kind": "file", "path": "config/constraint_schema.json"},
    ],
    "T00-04": [
        {"kind": "artifact", "key": "precision_profile_version"},
        {"kind": "file", "path": "config/precision_profile.json"},
        {"kind": "adr", "path": "ADR-0020-strict-equality-mode-a.md"},
    ],
    "T00-05": [{"kind": "artifact", "key": "architecture_decision_version"}],
    "T00-06": [
        {"kind": "artifact", "key": "competitiveness_classification"},
        {"kind": "artifact", "key": "project_classification_table"},
        {"kind": "file", "path": "config/competitiveness_classification.json"},
        {"kind": "file", "path": "config/project_classification_table.json"},
    ],
    "T00-07": [{"kind": "artifact", "key": "rule_set_selector_spec"}],
    "T00-08": [{"kind": "module", "path": "src/bidpricing/contracts/selector.py"}],
    "T00-06B": [
        {"kind": "module", "path": "src/bidpricing/total_price.py"},
        {"kind": "module", "path": "src/bidpricing/money.py"},
        {"kind": "adr", "path": "ADR-0014-total-price-is-a-partition.md"},
    ],
    "T00-12": [
        {"kind": "artifact", "key": "profit_bridge_spec"},
        {"kind": "module", "path": "src/bidpricing/validation/profit_bridge.py"},
        {"kind": "module", "path": "src/bidpricing/total_price.py"},
        {"kind": "adr", "path": "ADR-0015-objective-must-be-named.md"},
    ],
    "T01-00A": [{"kind": "artifact", "key": "input_protocol_schema"}],
    "T01-02C": [{"kind": "file", "path": "tests/data/xiyong_l_district/pair.json"}],
    # T04-00：证据的**唯一来源**是本字典（脚本派生），tasks.json 里的是派生物。
    # 两边必须一致，否则 extract_tasks --check 会报结构漂移。
    "T04-00": [
        {"kind": "file", "path": "config/phase1_exactness_spec.json"},
        {"kind": "module", "path": "src/bidpricing/solver/exactness.py"},
        {"kind": "module", "path": "src/bidpricing/solver/cases.py"},
        {"kind": "module", "path": "src/bidpricing/solver/instance.py"},
        {"kind": "module", "path": "tests/test_phase1_exactness.py"},
        {"kind": "adr", "path": "ADR-0019-phase1-exactness-by-exchange-argument.md"},
    ],
    "T04-02A": [
        {"kind": "file", "path": "config/lp_formulation_spec.json"},
        {"kind": "module", "path": "src/bidpricing/solver/formulation.py"},
        {"kind": "module", "path": "tests/test_lp_formulation.py"},
        {"kind": "adr", "path": "ADR-0021-lp-formulation-positions.md"},
    ],
    "T04-02B": [
        {"kind": "file", "path": "config/lp_compiler_spec.json"},
        {"kind": "module", "path": "src/bidpricing/solver/compiler.py"},
        {"kind": "module", "path": "tests/test_lp_compiler.py"},
        {"kind": "adr", "path": "ADR-0022-lp-compiler-positions.md"},
    ],
    "T04-02C": [
        {"kind": "file", "path": "config/solver_backend_spec.json"},
        {"kind": "module", "path": "src/bidpricing/solver/backend.py"},
        {"kind": "module", "path": "tests/test_solver_backend.py"},
        {"kind": "adr", "path": "ADR-0023-solver-backend-adapter.md"},
    ],
    "T04-02D": [
        {"kind": "file", "path": "config/solution_verifier_spec.json"},
        {"kind": "module", "path": "src/bidpricing/solver/verifier.py"},
        {"kind": "module", "path": "tests/test_solution_verifier.py"},
        {"kind": "adr", "path": "ADR-0024-solution-verifier.md"},
    ],
    "T03-02": [
        {"kind": "file", "path": "config/derived_quantities_spec.json"},
        {"kind": "module", "path": "src/bidpricing/derived.py"},
        {"kind": "module", "path": "tests/test_derived.py"},
        {"kind": "adr", "path": "ADR-0025-derived-quantities.md"},
    ],
    "T04-01": [
        {"kind": "file", "path": "config/phase1_solver_spec.json"},
        {"kind": "module", "path": "src/bidpricing/solver/phase1.py"},
        {"kind": "module", "path": "tests/test_phase1_solver.py"},
        {"kind": "adr", "path": "ADR-0026-phase1-analytic-solver.md"},
    ],
}

#: 初次提取时的状态种子。仅当 JSON 中不存在该任务时才写入；
#: 之后一切状态变更以 JSON 为准，脚本不再干预。
SEED_STATUS: dict[str, dict] = {
    # 已由证据派生为 done 的，这里不重复声明意义不大，但显式写出便于人读。
    "T00-01": {"status": "partial", "note": "规则集已承载调价口径；adjustment_scope 为选择项，取值待项目落值"},
    "T00-06": {"status": "partial", "note": "规则书已冻结；项目级落值表为空，属 Phase 0 输入门判据"},
    "T00-09": {"status": "not_started", "note": "需造价专业取数（八项成本分解）"},
    "T00-10A": {"status": "not_started", "note": "需人工：q^1 格式与冻结时点声明"},
    "T00-10B": {"status": "not_started", "note": "依赖 T01-00B 合同解析产出"},
    "T00-11": {"status": "not_started", "note": "需人工：c_i 来源与冻结时点声明"},
    "T00-12": {"status": "not_started", "note": "依赖 T00-06B、T00-09"},
    "T00-06B": {"status": "partial", "note": "恒等式判据已实现并过真实样本（残差 0）；P_competitive 扣减式与不可竞争费联动规则未落"},
    "T01-00B": {"status": "done", "note": "解析器 src/bidpricing/io/（零依赖 xlsx 读取器 + 表号/别名双键识别 + 双行表头合并 + 分节标题四信号判据）；三项产出经 CLI parse-boq 在真实配对样本上验证（82 行/0 失败/加权下浮 8.0084% 与 pair.json 交叉印证）；tests/test_io_boq.py 19 项"},
    "T01-02C": {"status": "partial", "note": "首份真实配对样本已固化；六类分层用例（A–F）未建，版本未锁定"},
}


def _clean(text: str) -> str:
    """去掉 Markdown 加粗标记与首尾空白。"""
    return text.replace("**", "").strip()


def parse_plan(path: Path) -> tuple[list[dict], list[str]]:
    """解析路线文档，返回 (任务列表, 警告列表)。"""
    if not path.exists():
        raise SystemExit(f"[extract_tasks] 路线文档不存在：{path}")

    lines = path.read_text(encoding="utf-8").splitlines()
    tasks: list[dict] = []
    warnings: list[str] = []
    wp, wp_title, wp_count = None, "", None

    for lineno, line in enumerate(lines, start=1):
        m = WP_HEADING.match(line)
        if m:
            wp, wp_title, wp_count = f"WP{m.group(1)}", _clean(m.group(2)), int(m.group(3))
            continue

        if not TASK_ROW.match(line):
            continue
        if wp is None:
            warnings.append(f"第 {lineno} 行任务出现在任何 WP 分节之前，已跳过")
            continue

        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            warnings.append(f"第 {lineno} 行只有 {len(cells)} 列，期望 ≥4，已跳过")
            continue

        raw_title = cells[1]
        # 标题形如：**成本口径证明包**（v3 新增/P0）、**规则集优先级冻结**（P0）
        # 括号内是版本/优先级标记，与任务名分开存；只在括号内容含标记关键字时才切，
        # 避免误伤本身以括号结尾的任务名。
        paren = re.search(
            r"[（(]([^（()）]*(?:新增|拆分|修订|v\d|P\d)[^（()）]*)[）)]\s*$", raw_title
        )
        title = _clean(raw_title[: paren.start()] if paren else raw_title)
        revision = paren.group(1) if paren else ""

        deps_raw = cells[6] if len(cells) >= 7 else ""
        deps = [d.strip() for d in re.split(r"[,\s、]+", deps_raw) if re.fullmatch(r"T\d{2}-\d{2}[A-Z]?", d.strip())]

        desc = _clean(cells[3]) if len(cells) >= 4 else ""
        if len(desc) > 160:
            desc = desc[:160] + "…"

        tasks.append(
            {
                "id": cells[0].strip("* ").strip(),
                "wp": wp,
                "wp_title": wp_title,
                "title": title,
                "revision_note": revision,
                "deliverable": _clean(cells[2]) if len(cells) >= 3 else "",
                "type": _clean(cells[4]) if len(cells) >= 5 else "",
                "review": _clean(cells[5]) if len(cells) >= 6 else "",
                "deps": deps,
                "summary": desc,
                "gate": "",
            }
        )

    if wp_count is not None:
        per_wp: dict[str, int] = {}
        for t in tasks:
            per_wp[t["wp"]] = per_wp.get(t["wp"], 0) + 1
    return tasks, warnings


def build(plan_path: Path, prev: dict) -> dict:
    tasks, warnings = parse_plan(plan_path)
    prev_tasks: dict[str, dict] = {t["id"]: t for t in prev.get("tasks", [])}

    # 门禁归属：WP0 → Gate 0a，WP1–WP3 → Gate 0a 放行，WP4 → Gate 0b，其余见路线 §7.1
    GATE_OF_WP = {
        "WP0": "Gate 0a / 0b",
        "WP1": "Gate 1",
        "WP2": "Gate 2",
        "WP3": "Gate 2",
        "WP4": "Gate 3",
        "WP5": "Gate 4",
        "WP6": "Gate 5A",
        "WP7": "Gate 6",
    }

    merged: list[dict] = []
    for t in tasks:
        t["gate"] = GATE_OF_WP.get(t["wp"], "")
        t["evidence"] = EVIDENCE.get(t["id"], [])
        old = prev_tasks.get(t["id"])
        if old:
            # 人工字段一律保留脚本不覆盖；结构字段以上文提取结果为准
            t["status"] = old.get("status", "not_started")
            t["note"] = old.get("note", "")
            # 人字段（status_note/updated_at）：不在本脚本 schema 内，
            # 但**重跑不得静默删除**——存在即原样保留（2026-09-17 修复）。
            for _human in ("status_note", "updated_at"):
                if _human in old:
                    t[_human] = old[_human]
        else:
            seed = SEED_STATUS.get(t["id"], {})
            t["status"] = seed.get("status", "not_started")
            t["note"] = seed.get("note", "")
        merged.append(t)

    by_id = {t["id"]: t for t in merged}
    for t in merged:  # 依赖校验：悬空依赖即报，不让它静默存在
        for d in t["deps"]:
            if d not in by_id:
                warnings.append(f"{t['id']} 依赖 {d}，但任务表中无此编号")

    return {
        "schema": "bidpricing.tasks/v1",
        "source": str(plan_path.name),
        "source_note": "结构字段由 tools/extract_tasks.py 从路线文档派生，请勿手改；status/note 为人工维护字段。",
        "counts": {
            "total": len(merged),
            "by_wp": {wp: sum(1 for t in merged if t["wp"] == wp) for wp in sorted({t["wp"] for t in merged})},
        },
        "warnings": warnings,
        "tasks": merged,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="从实施路线文档派生机器可读任务板")
    ap.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    ap.add_argument("--check", action="store_true", help="只校验不写盘；结构漂移则退出码 1")
    args = ap.parse_args()

    prev = {}
    if TASKS_JSON.exists():
        prev = json.loads(TASKS_JSON.read_text(encoding="utf-8"))

    data = build(args.plan, prev)

    if args.check:
        # 排除元组 = 全部「人维护字段」：status/note（schema 内）+
        # status_note/updated_at（人字段，build() 已改为存在即保留）。
        # 结构漂移只应反映结构字段，不得被人字段触发。
        HUMAN_FIELDS = ("status", "note", "status_note", "updated_at")
        old_struct = [
            {k: v for k, v in t.items() if k not in HUMAN_FIELDS}
            for t in prev.get("tasks", [])
        ]
        new_struct = [
            {k: v for k, v in t.items() if k not in HUMAN_FIELDS}
            for t in data["tasks"]
        ]
        if old_struct != new_struct:
            print("[extract_tasks] 任务板已过期：路线文档与 docs/tasks.json 不一致")
            print("                  请运行 python tools/extract_tasks.py 重新提取")
            return 1
        print(f"[extract_tasks] 校验通过：{data['counts']['total']} 项任务与路线文档一致")
        return 0

    TASKS_JSON.parent.mkdir(parents=True, exist_ok=True)
    TASKS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[extract_tasks] 已写入 {TASKS_JSON.relative_to(REPO)}")
    print(f"                任务总数 {data['counts']['total']}  分布 {data['counts']['by_wp']}")
    for w in data["warnings"]:
        print(f"  [warn] {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
