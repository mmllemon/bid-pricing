"""状态快照派生 —— 让「项目进展」成为**计算出来的**，而不是**抄出来的**。

## 这个模块要解决的问题

本项目已经出现过三次同型事故：文档里写的数字与代码实际不符。

* `README.md` 写「Gate 0a 6/8 判据通过」，实际此时已是 8/8；
* `DEVELOPMENT.md` 写「89 项单元测试」，实际已增长到 98 项；
* `DEVELOPMENT.md` 曾把「提供真实招标清单」列为 WP1 开工前置条件，后被推翻。

三次的根因完全相同：**数字是手工抄进文档的，而数字的来源在变**。手抄必然漂移，
且漂移在「有人刚好读到那一行」之前不会被发现。靠人记得同步更新文档，是不成立的约定。

## 做法

把状态快照变成**生成物**而非**著作物**：

    bidpricing status --write   →   docs/STATE.md（头部标注自动生成，勿手改）

其中每一段都取自一个**已存在的权威源**，本模块不做二次判断：

| 段落 | 来源 | 为什么可信 |
|---|---|---|
| 版本锚点 | `git rev-parse` / `git describe` / `git status` | 提交历史不可篡改 |
| 闸门状态 | `gates.gate0.evaluate_gate_0()` | 与本地/CI 判据同源同值 |
| 制品冻结 | `config/gate0_registry.json` 的 hash 字段 | hash 由制品内容算出，改则失配 |
| 测试结果 | 现场运行 `unittest` | 不接受「上次跑过」 |
| 任务进度 | `docs/tasks.json` + **证据核对** | 状态须有代码证据支撑（见下） |
| 遗留项 | 各配置的 `known_limits` / `freeze_blocker` | 配置自声明，不被汇总掩盖 |

## 证据核对：状态为什么是可验证的

`tasks.json` 里每条任务可声明 `evidence`（制品 key 或模块路径）。本模块据此核对：

* `artifact` 类 → 该制品在注册表中 `hash` 非空即视为「证据成立」；
* `module` 类 → 文件存在即视为「证据成立」。

于是「已完成」不再是某人在文档里写了句「已完成」，而是**可以由代码复核的断言**。
人工状态（`status`）与证据核对（`evidence_ok`）**分列输出**——两者不一致时，
说明人工状态该更新了，而不是让证据去迁就文字。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .artifact import load_registry, parse_records
from .contracts.selector import select_rule_set
from .gates.gate0 import evaluate_gate_0
from .paths import GATE0_REGISTRY, config_dir, docs_dir, repo_root

STATE_FILE = "STATE.md"
TASKS_FILE = "tasks.json"

#: 生成物头部声明。放在文件最前面，任何打开文件的人第一眼就会看到。
BANNER = (
    "<!-- ⚠ 本文件由 `python -m bidpricing.cli status --write` 自动生成。\n"
    "     请勿手工编辑——手写的状态一定会在某次改动后过期。\n"
    "     要改内容，请改来源：git 提交 / config 注册表 / docs/tasks.json。 -->\n"
)

DONE_STATES = {"done"}
SATISFIED_FOR_DEPS = {"done", "partial"}


# --------------------------------------------------------------------- git


def _git(*args: str, timeout: int = 10) -> str:
    """运行 git 命令并返回 stdout（失败返回空串，不抛异常）。"""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(repo_root()),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def collect_git() -> dict:
    """版本锚点。git 不可用时降级为 «unknown»，而不是让整个快照失败。"""
    head = _git("rev-parse", "--short", "HEAD")
    if not head:
        return {"available": False, "head": "unknown", "subject": "", "tags": [], "dirty": None}

    subject = _git("log", "-1", "--pretty=%s")
    tags = [t for t in _git("describe", "--tags", "--abbrev=0").splitlines() if t]
    dirty_lines = [ln for ln in _git("status", "--porcelain").splitlines() if ln]
    ahead = _git("rev-list", "--count", "@{u}..HEAD") if _git("rev-parse", "@{u}") else ""
    return {
        "available": True,
        "head": head,
        "subject": subject,
        "tags": tags,
        "dirty": len(dirty_lines),
        "commits_total": _git("rev-list", "--count", "HEAD"),
        "unpushed": ahead,
    }


# ---------------------------------------------------------------- 证据核对


def check_evidence(task: dict, registry: dict, root: Path) -> tuple[bool | None, str]:
    """核对任务的代码证据。返回 (是否成立, 说明)；无 evidence 声明返回 (None, "")。"""
    ev = task.get("evidence") or []
    if not ev:
        return None, ""

    details: list[str] = []
    ok = True
    for e in ev:
        kind = e.get("kind")
        if kind == "artifact":
            rec = next((r for r in parse_records(registry, "gate_0a") if r.key == e.get("key")), None)
            if rec is None:
                ok = False
                details.append(f"{e.get('key')} 未在注册表声明")
            elif rec.hash:
                details.append(f"{e.get('key')} 已冻结 {str(rec.hash)[:19]}")
            else:
                ok = False
                details.append(f"{e.get('key')} 未冻结")
        elif kind == "module":
            p = root / str(e.get("path", ""))
            if p.exists():
                details.append(f"{e.get('path')} 存在")
            else:
                ok = False
                details.append(f"{e.get('path')} 缺失")
        else:
            ok = False
            details.append(f"未知证据类型 {kind!r}")
    return ok, "；".join(details)


def load_tasks(root: Path) -> dict:
    path = root / "docs" / TASKS_FILE
    if not path.exists():
        return {"tasks": [], "counts": {"total": 0, "by_wp": {}}, "warnings": ["tasks.json 不存在，请运行 tools/extract_tasks.py"]}
    return json.loads(path.read_text(encoding="utf-8"))


def effective_status(task: dict) -> str:
    """生效状态 = 人工声明优先；人工未声明而证据成立时，判为 done。

    这条规则是本模块的核心价值之一：**证据能证明的事，不应要求人再手工写一遍**。
    例如 T00-02（字段字典冻结）的证据是「`field_schema_version` 制品已有 hash」——
    制品一旦冻结，该任务事实上就完成了，此时若因为「没人去 tasks.json 里改状态」
    而把它列为待办，就是让手工誊抄重新成为必要环节，漂移随之回来。

    反过来，人工声明为 `partial` 时**不被证据覆盖**——制品冻结只证明机制就绪，
    不代表项目级数据已填（T00-06 即此情形：规则书已冻结，落值表仍为空）。
    """
    declared = task.get("status", "not_started")
    if declared not in ("not_started", ""):
        return declared
    if task.get("evidence_ok") is True:
        return "done"
    return declared


def derive_next_steps(tasks: list[dict], limit: int = 6) -> list[dict]:
    """可开工任务：依赖已满足（done/partial）且自身未完成。

    这是「下一步做什么」的**自动答案**——不依赖任何人记得上次进度。
    """
    by_id = {t["id"]: t for t in tasks}
    ready: list[dict] = []
    for t in tasks:
        if effective_status(t) in DONE_STATES:
            continue
        deps = t.get("deps") or []
        unsatisfied = [
            d for d in deps
            if d in by_id and effective_status(by_id[d]) not in SATISFIED_FOR_DEPS
        ]
        if unsatisfied:
            continue
        ready.append(
            {
                "id": t["id"],
                "wp": t["wp"],
                "title": t["title"],
                "deliverable": t.get("deliverable", ""),
                "status": effective_status(t),
                "note": t.get("note", ""),
                # 依赖在任务表之外的（如 T01-00B 依赖合同解析产出的语义），标注出来
                "external_deps": [d for d in deps if d not in by_id],
            }
        )
    ready.sort(key=lambda r: (r["wp"], r["id"]))
    return ready[:limit]


# ------------------------------------------------------------ 遗留项汇总


def _walk_known_limits(node, path: str = "") -> list[str]:
    """递归收集配置里的 known_limits / freeze_blocker 自声明遗留项。"""
    found: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{path}.{k}" if path else k
            if k in ("known_limits", "freeze_blocker") and v:
                if isinstance(v, list):
                    found.extend(f"{here}: {x}" for x in v)
                else:
                    found.append(f"{here}: {v}")
            elif isinstance(v, (dict, list)):
                found.extend(_walk_known_limits(v, here))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found.extend(_walk_known_limits(v, f"{path}[{i}]"))
    return found


def collect_advisories(root: Path) -> list[str]:
    cfg = root / "config"
    out: list[str] = []
    for f in sorted(cfg.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            out.append(f"{f.name}: JSON 解析失败")
            continue
        for line in _walk_known_limits(data):
            out.append(f"{f.name} → {line}")
    return out


def run_tests(root: Path, timeout: int = 180) -> dict:
    """现场运行测试套件。不接受缓存结果——缓存会撒谎。"""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**_env(), "PYTHONPATH": "src"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ran": None, "ok": None, "detail": f"无法运行：{exc}"}

    blob = out.stdout + out.stderr
    m = re.search(r"Ran (\d+) tests?", blob)
    count = int(m.group(1)) if m else None
    return {
        "ran": count,
        "ok": out.returncode == 0,
        "detail": "OK" if out.returncode == 0 else blob.strip().splitlines()[-1] if blob.strip() else "失败",
    }


def _env() -> dict:
    import os

    return dict(os.environ)


# ------------------------------------------------------------------- 汇总


def collect(
    contract_date: str = "2026-03-01",
    use_project_selection: bool = True,
    run_test_suite: bool = True,
) -> dict:
    """采集全部快照数据。纯数据，不渲染。

    ``run_test_suite=False`` 会跳过现场测试运行。存在的理由很实际：
    测试套件里若有用例调用 ``collect()``，而 ``collect()`` 又去跑测试套件，
    就会无限递归。故测试用例一律传 False，只验证其余采集与派生逻辑。
    """
    root = repo_root()
    cfg = config_dir()
    registry = load_registry(cfg / GATE0_REGISTRY)
    selection = select_rule_set(
        contract_date=contract_date, use_project_selection=use_project_selection
    ).to_dict()
    gate = evaluate_gate_0(registry, cfg, selection)

    artifacts = []
    for rec in parse_records(registry, "gate_0a"):
        artifacts.append(
            {
                "key": rec.key,
                "kind": rec.kind,
                "hash": rec.hash or "",
                "frozen_at": rec.frozen_at or "",
            }
        )

    tasks_raw = load_tasks(root)
    tasks = tasks_raw.get("tasks", [])
    for t in tasks:
        ok, detail = check_evidence(t, registry, root)
        t["evidence_ok"] = ok
        t["evidence_detail"] = detail
        t["effective_status"] = effective_status(t)

    if run_test_suite:
        tests = run_tests(root)
    else:
        tests = {"ran": None, "ok": None, "detail": "已跳过（run_test_suite=False）"}

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "contract_date": contract_date,
        "git": collect_git(),
        "gates": gate["summary"],
        "gate_0a_items": gate["gate_0a"]["items"],
        "artifacts": artifacts,
        "tests": tests,
        "tasks": tasks,
        "task_counts": tasks_raw.get("counts", {}),
        "next_steps": derive_next_steps(tasks),
        "advisories": collect_advisories(root),
    }


# ----------------------------------------------------------------- 渲染


def _task_table(tasks: list[dict]) -> list[str]:
    rows = ["| 任务 | 标题 | 生效状态 | 证据核对 | 备注 |", "|---|---|---|---|---|"]
    for t in tasks:
        ok = t.get("evidence_ok")
        mark = "—" if ok is None else ("✓ 成立" if ok else "✗ 不成立")
        detail = t.get("evidence_detail", "")
        note = "；".join(x for x in (t.get("note", ""), detail) if x) or "—"
        rows.append(
            f"| {t['id']} | {t['title']} | {effective_status(t)} | {mark} | {note} |"
        )
    return rows


def render(snap: dict) -> str:
    L: list[str] = [BANNER, ""]
    git = snap["git"]
    t = snap["tests"]

    dirty = git.get("dirty")
    if dirty is None:
        worktree = "未知"
    elif dirty == 0:
        worktree = "干净"
    else:
        worktree = f"有 {dirty} 处未提交改动"

    tags_str = ", ".join(f"`{x}`" for x in git["tags"]) if git["tags"] else "（无）"
    commits = git.get("commits_total") or "?"
    unpushed = f" ｜ 未推送 {git['unpushed']} 次提交" if git.get("unpushed") else ""

    L += [
        "# 项目状态快照",
        "",
        f"> 生成于 **{snap['generated_at']}** ｜ 合同基准日 `{snap['contract_date']}`",
        "> 本文件是**生成物**，用于跨会话交接。改内容请改来源，不要改本文件。",
        "",
        "---",
        "",
        "## 一、版本锚点",
        "",
        f"- 提交：`{git['head']}` ｜ 累计 {commits} 次提交{unpushed}",
        f"- 最新提交信息：{git.get('subject', '')}",
        f"- 最近里程碑标签：{tags_str}",
        f"- 工作区：{worktree}",
        "",
        "> 版本锚点是**结论可复算**的前提：任何一份交付物都能追到某个提交。",
        "",
        "---",
        "",
        "## 二、闸门状态",
        "",
        "| 闸门 | 状态 |",
        "|---|---|",
    ]
    for k, label in (
        ("gate_0a", "Gate 0a — 技术接口与规则集冻结"),
        ("gate_0b", "Gate 0b — 商务口径与合规冻结"),
        ("phase_0_input_gate", "Phase 0 输入门 — 项目级数据/取值"),
        ("phase_0", "Phase 0 准入（综合）"),
        ("wp4_solver_layer", "WP4 求解层构建"),
    ):
        if k in snap["gates"]:
            L.append(f"| {label} | **{snap['gates'][k]}** |")
    L.append("")

    blockers = [i for i in snap["gate_0a_items"] if i.get("status") == "BLOCKED"]
    if blockers:
        L += ["**Gate 0a 阻塞项：**", ""]
        for b in blockers:
            L.append(f"- `{b['item']}` — {b['reason']}")
        L.append("")
    else:
        L += [
            "**Gate 0a 无阻塞项**，已放行 WP1 数据层 / WP2 配置层 / WP3 判定层。",
            "",
        ]

    L += ["---", "", "## 三、契约制品冻结表", "", "| 制品 key | 类型 | hash | 冻结时间 |", "|---|---|---|---|"]
    for a in snap["artifacts"]:
        L.append(f"| `{a['key']}` | {a['kind']} | {a['hash'] or '**未冻结**'} | {a['frozen_at'] or '—'} |")
    L += [
        "",
        "> hash = 制品内容 SHA-256 前 12 位。制品一改即失配，闸门自动失效——无需人工记忆。",
        "",
        "---",
        "",
        "## 四、质量门",
        "",
        f"- 单元测试：**{t['ran'] if t['ran'] is not None else '未运行'}** 项，"
        f"结果 **{'通过' if t['ok'] else '未通过' if t['ok'] is not None else '未知'}**（{t.get('detail', '')}）",
        "",
    ]

    if t["ran"] is not None:
        L += [
            "```bash",
            "cd bid-pricing && PYTHONPATH=src python -m unittest discover -s tests",
            "```",
            "",
        ]

    L += ["---", "", "## 五、任务进度", ""]
    by_wp = snap["task_counts"].get("by_wp", {})
    total = snap["task_counts"].get("total", 0)
    per_wp_status: dict[str, dict[str, int]] = {}
    for task in snap["tasks"]:
        d = per_wp_status.setdefault(task["wp"], {})
        s = task.get("effective_status", task.get("status", ""))
        d[s] = d.get(s, 0) + 1

    L += ["| WP | 任务数 | 状态分布 |", "|---|---|---|"]
    for wp in sorted(by_wp):
        dist = per_wp_status.get(wp, {})
        pretty = "、".join(f"{k} {v}" for k, v in sorted(dist.items())) or "—"
        L.append(f"| {wp} | {by_wp[wp]} | {pretty} |")
    L += ["", f"共 **{total}** 项任务。", ""]

    started = [
        x for x in snap["tasks"]
        if x.get("effective_status", x.get("status")) not in ("not_started", "")
    ]
    if started:
        L += ["### 已启动 / 已完成任务", ""]
        L.append(
            f"> 共 {len(started)} 项。生效状态由「人工声明」与「证据核对」共同决定"
            "（见 `src/bidpricing/status.py::effective_status`）。"
        )
        L.append("")
        L += _task_table(started)
        L.append("")

    L += ["---", "", "## 六、下一步（自动派生）", ""]
    L += [
        "> 判据：依赖任务均已 `done`/`partial`，且自身未完成。**由代码算出，非人工推荐。**",
        "",
    ]
    nxt = snap["next_steps"]
    if nxt:
        L += ["| 任务 | WP | 标题 | 产出物 | 状态 |", "|---|---|---|---|---|"]
        for n in nxt:
            ext = f"（外部依赖：{', '.join(n['external_deps'])}）" if n["external_deps"] else ""
            L.append(f"| {n['id']} | {n['wp']} | {n['title']} | {n['deliverable']}{ext} | {n['status']} |")
        L.append("")
    else:
        L += ["（无——所有可开工任务均已完成或依赖未满足）", ""]

    L += ["---", "", "## 七、遗留项与已知限制", ""]
    adv = snap["advisories"]
    if adv:
        for a in adv:
            L.append(f"- {a}")
    else:
        L.append("（无自声明遗留项）")
    L += [
        "",
        "> 遗留项从各配置的 `known_limits` / `freeze_blocker` 自声明字段汇聚，",
        "> 因此不会被「汇总为一句已完成」而掩盖。",
        "",
        "---",
        "",
        "## 八、复现全部结论",
        "",
        "```bash",
        "cd bid-pricing",
        "# 1. 状态快照（本文件的来源）",
        "PYTHONPATH=src python -m bidpricing.cli status --write",
        "# 2. 闸门机械判定",
        "PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01",
        "# 3. 全量测试",
        "PYTHONPATH=src python -m unittest discover -s tests",
        "# 4. 规则集指纹自检（含退化条件登记）",
        "PYTHONPATH=src python -m bidpricing.cli ruleset-selftest",
        "```",
        "",
    ]
    return "\n".join(L)


def write_state(contract_date: str = "2026-03-01") -> Path:
    """采集 → 渲染 → 写盘，返回写入路径。"""
    snap = collect(contract_date)
    target = docs_dir() / STATE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(snap), encoding="utf-8")
    return target
