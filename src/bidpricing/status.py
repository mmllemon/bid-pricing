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
from datetime import datetime, timedelta
from pathlib import Path

from .artifact import load_registry, parse_records
from .contracts.consistency import check_contract_consistency
from .contracts.selector import select_rule_set
from .gates.gate0 import evaluate_gate_0
from .paths import GATE0_REGISTRY, config_dir, docs_dir, repo_root
from .states import aggregate

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
#: 待定/跳过：因缺外部条件（如真实项目数据）而非「可开工」遗留，不出现在下一步建议里。
DEFERRED_STATES = {"deferred"}

#: 快照新鲜度判据扫描的权威源目录（相对 repo_root）。
#: 不含 docs 顶层——STATE.md 自身、交接文档等不是快照来源。
FRESHNESS_SCAN_DIRS = ("src", "config", "tests", "docs/adr")

#: mtime 容差（秒）：同一秒内的写入不算「生成后改动」，避免同秒误报。
FRESHNESS_MTIME_TOLERANCE = 1.0


# --------------------------------------------------------------------- git


def _git(*args: str, timeout: int = 10) -> str:
    """运行 git 命令并返回 stdout（失败返回空串，不抛异常）。"""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(repo_root()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return (out.stdout or "").strip() if out.returncode == 0 else ""
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
    """核对任务的代码证据。返回 (是否成立, 说明)；无 evidence 声明返回 (None, "")。

    2026-09-17 修正三处缺口（原实现会让**真实成立的证据被判不成立**，
    从而逼着人往任务板里填假证据）：

    * ``kind="artifact"`` 原先**只查 gate_0a**。任一以 Gate 0b 受控制品为
      唯一证据的任务（如 T00-12 的 profit_bridge_spec）永远判不成立。
      现按 gate_0a ∪ gate_0b 取并集。
    * 新增 ``kind="adr"``：决策记录的路径是 ``docs/adr/<file>``，原实现
      只能写 module/file 的仓库相对路径，语义上分不清「代码」与「决策」。
    * 新增 **phase_0 项目级输入**分支：这类制品（project_classification_table）
      本就不做版本冻结，按「hash 已冻结」判会永远不成立。改用「文件存在」，
      与 Phase 0 输入门的「声明式就绪」判据同向。
    """
    ev = task.get("evidence") or []
    if not ev:
        return None, ""

    records = [r for gate in ("gate_0a", "gate_0b") for r in parse_records(registry, gate)]
    # phase_0 是**项目级输入**（如 project_classification_table），不做版本冻结——
    # 它的就绪性由 Phase 0 输入门按「声明式就绪」判（key 必须存在；空列表是合法
    # 结论）。故这里对它改用「文件存在」而非「hash 已冻结」判定。判据不得因为
    # 「这个制品本来就不该冻结」而把一个真实成立的证据判成不成立。
    project_inputs = {
        r.key: r for r in parse_records(registry, "phase_0") if r.artifact_path
    }

    details: list[str] = []
    ok = True
    for e in ev:
        kind = e.get("kind")
        if kind == "artifact":
            rec = next((r for r in records if r.key == e.get("key")), None)
            if rec is None:
                p0 = project_inputs.get(str(e.get("key")))
                if p0 is None:
                    ok = False
                    details.append(f"{e.get('key')} 未在注册表声明")
                else:
                    path = root / "config" / str(p0.artifact_path)
                    if path.exists():
                        details.append(
                            f"{e.get('key')} 存在（项目级输入，不冻结 hash）"
                        )
                    else:
                        ok = False
                        details.append(f"{e.get('key')} 缺失：{p0.artifact_path}")
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
        elif kind == "file":
            # 数据类证据（真实样本、Golden Dataset 等）。
            # 与 module 的区别只在语义：module 是代码，file 是数据；
            # 判定方式相同（存在即成立），因为数据未就位时也确实做不出下一步。
            p = root / str(e.get("path", ""))
            if p.exists():
                size = p.stat().st_size
                details.append(f"{e.get('path')} 存在（{size} 字节）")
            else:
                ok = False
                details.append(f"{e.get('path')} 缺失")
        elif kind == "adr":
            p = root / "docs" / "adr" / str(e.get("path", ""))
            if p.exists():
                details.append(f"ADR {e.get('path')} 存在")
            else:
                ok = False
                details.append(f"ADR {e.get('path')} 缺失")
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
        if effective_status(t) in DONE_STATES or effective_status(t) in DEFERRED_STATES:
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


def _detect_test_runner() -> str:
    """选跑测试的工具：优先 pytest，回退 unittest。

    为何不能就用 unittest（实测，非推演）：tests/ 下有 4 个 pytest 风格模块
    （test_project_docs / test_project_exec / test_solve_unbalanced / test_unbalanced），
    共 **31 个裸函数** `def test_` 用例、**0 个** `unittest.TestCase`：

      * 本机没装 pytest → 模块 import 失败，discover 报 `FAILED (errors=…)`——会痛，会暴露；
      * 本机装了 pytest → discover 只收 TestCase 子类，裸函数**一个都不跑且不报错**，
        returncode 0 → 报 `OK`。

    即「补齐依赖反而把缺口藏起来」。docs/STATE.md 的「质量门：单元测试 N 项，结果通过」
    正是在装了 pytest 的机器上用 unittest 生成的——它静默跳过了那 31 项却宣称通过。
    口径必须跟 CI 一致用 pytest；实在回退时不得伪装成同等可信（见 degraded）。
    """
    try:
        import importlib.util
        if importlib.util.find_spec("pytest") is not None:
            return "pytest"
    except (ImportError, ValueError):  # noqa: BLE001 探测本身不得弄坏快照
        pass
    return "unittest"


def _parse_test_counts(blob: str, runner: str) -> tuple[int | None, str]:
    """从输出取「跑了多少项」+ 一句话结果；unittest / pytest 两套尾行都得认。

    pytest `-q` 尾行形如 `1647 passed, 3 skipped in 45.2s`，**没有** unittest 那种
    `Ran N tests`；只认一种，换工具后质量门会变成「未运行」。
    """
    if runner == "pytest":
        # findall 返回 (数字, 词)，要的是 {词: 数字}——顺序写反会得到 int("failed")。
        nums: dict[str, int] = {}
        for v, k in re.findall(r"(\d+)\s+(passed|failed|errors?|skipped)", blob):
            nums[k] = int(v)
        ran = nums.get("passed")
        if ran is not None:
            ran += nums.get("failed", 0) + nums.get("errors", 0) + nums.get("error", 0)
        tail = next((ln.strip() for ln in reversed(blob.splitlines())
                     if re.search(r"\d+\s+(passed|failed|error)", ln)), "")
        return ran, tail
    m = re.search(r"Ran (\d+) tests?", blob)
    return (int(m.group(1)) if m else None), ""


def run_tests(root: Path, timeout: int = 180, *, runner: str | None = None) -> dict:
    """现场运行测试套件。不接受缓存结果——缓存会撒谎。

    `runner=None` 自动探测；测试可显式传 "pytest"/"unittest"，使断言**不依赖本机装了什么**——
    否则同一套断言会因环境不同而时绿时红，正是本函数要修的毛病。

    子进程输出**显式**按 UTF-8 读写（``encoding`` + ``errors`` + 传
    ``PYTHONIOENCODING`` 给孩子进程）：``text=True`` 缺省按本机 locale 解码，
    而 unittest 的报告含中文用例名/中文失败说明。在中文 Windows（控制台
    CP=936）上，父进程按 GBK 解 UTF-8 字节 → 读取线程抛 UnicodeDecodeError →
    ``out.stdout`` 变成 ``None`` → 紧接着的字符串拼接直接 TypeError，
    **整条 ``status`` 命令崩掉，状态快照根本生成不出来**。

    这条坑的教训与其它判据同源：不显式指定编码，等于把「能不能生成快照」
    交给运行环境的区域设置。显式指定后，控制台是 GBK 还是 UTF-8 都一样。
    """
    runner = runner or _detect_test_runner()
    # 自述解释器：质量门的数字得说得出是在哪个 Python 上跑出来的——
    # 本仓存在 CI 3.12 / 本地 3.14 / 声明 >=3.11 三个版本并存的情况，
    # 不自述就无法追溯「这个 OK 是谁验的」。
    interp = sys.version.split()[0]
    argv = ([sys.executable, "-m", "pytest", "tests/", "-q"]
            if runner == "pytest"
            else [sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    try:
        out = subprocess.run(
            argv,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={**_env(), "PYTHONPATH": "src", "PYTHONIOENCODING": "utf-8"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ran": None, "ok": None, "detail": f"无法运行：{exc}",
                "runner": runner, "degraded": runner == "unittest", "python": interp}

    # 读取线程异常时子进程对象仍会返回，但两个流可能是 None——不设兜底就会在
    # 拼接处抛 TypeError，把「子进程没读成」伪装成「状态模块自身坏了」。
    blob = (out.stdout or "") + (out.stderr or "")
    count, tail = _parse_test_counts(blob, runner)
    ok = out.returncode == 0
    if ok:
        detail = tail or "OK"
    else:
        detail = (tail
                  or (blob.strip().splitlines()[-1] if blob.strip() else "失败"))
    return {
        "ran": count,
        "ok": ok,
        "detail": detail,
        "runner": runner,
        "python": interp,
        # 回退 unittest 是**降级**：它会静默跳过裸函数用例仍报 OK，数字与 pytest
        # 口径不可比较。必须标出来，由渲染层写明——不能让降级后的绿灯和正常绿灯长得一样。
        "degraded": runner == "unittest",
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
    # 两个闸门都要列。只列 Gate 0a 会让 Gate 0b 的制品（成本口径/税口径/桥接表/
    # q^1 声明…）在交接文档里**完全看不到 hash**——而它们恰恰是「业务口径会不会
    # 悄悄改掉」的判据所在。kind=approvals 等非版本化记录不入表（它们没有待校验的
    # 内容 hash，列出来只会让「未冻结」这四个字失去含义）。
    for gate_key in ("gate_0a", "gate_0b"):
        for rec in parse_records(registry, gate_key):
            if rec.kind not in ("versioned", "enum"):
                continue
            artifacts.append(
                {
                    "key": rec.key,
                    "gate": gate_key,
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
        tests = {"ran": None, "ok": None, "detail": "已跳过（run_test_suite=False）",
                 "runner": None, "degraded": False, "python": None}

    # 跨制品一致性：与闸门正交的第四条验证环。此处**现场复算**而非读缓存，
    # 与测试同理——缓存过的结论会撒谎。
    cc_items = check_contract_consistency(cfg)
    contract_consistency = {
        "worst": aggregate(i.status for i in cc_items).value,
        "items": [i.to_dict() for i in cc_items],
        "headline": next(
            (i.reason for i in cc_items
             if i.item == "constraint_schema.inputs_declared"), ""
        ),
    }

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "contract_date": contract_date,
        "git": collect_git(),
        "gates": gate["summary"],
        "gate_0a_items": gate["gate_0a"]["items"],
        # 其余闸门的逐条判据也要进快照：只写「Gate 0b = BLOCKED」而不写被什么挡住，
        # 接手者仍得自己复跑 gate-check 才知道原因——那等于把快照最有价值的一半
        # 留在了命令输出里（本次实测：Gate 0b 的阻塞项是一条制品 hash 失配，
        # 快照完全没体现，而它正是那半个月潜伏不报的那个问题）。
        "gate_0b_items": gate["gate_0b"]["items"],
        "phase_0_input_gate_items": gate["phase_0_input_gate"]["items"],
        "artifacts": artifacts,
        "tests": tests,
        "contract_consistency": contract_consistency,
        "tasks": tasks,
        "task_counts": tasks_raw.get("counts", {}),
        "next_steps": derive_next_steps(tasks),
        "advisories": collect_advisories(root),
    }


# ------------------------------------------------------------ 快照新鲜度


def _parse_generated_at(text: str) -> datetime | None:
    """从 STATE.md 头部解析 ``生成于 <timestr>``。"""
    m = re.search(r"> 生成于 \*\*([0-9\- :]+)\*\*", text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _last_commit_times(root: Path) -> dict[str, datetime]:
    """一次 git 调用构建 {相对路径: 最近提交时间} 表。

    ``--pretty=format:%cI --name-only`` 输出形如：每个提交日期后跟一列文件名，
    以空行分隔块。按「日期行正则 → 后续文件名行归属该日期」解析。空表（git
    不可用）时退化为空 dict，由调用方改用 mtime。
    """
    out = _git("log", "--pretty=format:%cI", "--name-only")
    table: dict[str, datetime] = {}
    date: datetime | None = None
    for line in out.splitlines():
        if not line.strip():
            date = None
            continue
        # %cI 带时区偏移（如 2026-10-08T18:14:03+08:00）。旧正则只取到秒，
        # 把 "+08:00" 丢掉后按 naive 解析——在跑者时区 ≠ 提交者时区时
        # （如 CI 的 UTC vs 他的 +08:00），提交时间会被整体平移 8 小时，
        # 新鲜度判据误报/ flaky。必须保留偏移，再统一折成跑者本地墙钟
        # （与 datetime.now() / STATE.md 横幅时间的 naive 口径一致）。
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:?\d{2}|Z)?)", line)
        if m:
            try:
                parsed = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            except ValueError:
                date = None
                continue
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            date = parsed
            continue
        if date is not None:
            table.setdefault(line, date)
    return table


def _nondeterministic_mtime(path: Path, commit_times: dict[str, datetime]) -> datetime | None:
    """权威源的确定性变更时间。

    以「最近一次提交时间」优先（从一次批量调用所得的表里查），避免因 checkout /
    构建刷新了 mtime 而误报；未纳入版本控制的文件（如本次未提交改动）在表中查
    不到，退化为文件 mtime 即时探测。两者同作比较用，不需展示。
    """
    root = repo_root()
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = None
    if rel is not None and rel in commit_times:
        return commit_times[rel]
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def check_freshness(state_path: Path | None = None, root: Path | None = None,
                    *, generated_at: datetime | None = None,
                    source_dirs: Sequence[str] | None = None) -> dict:
    """判 STATE.md 是否已过期（源比快照新）。

    返回 dict（无 diff 时 ``fresh=True``，有 diff 时含 ``stale_files`` 列表）。
    幂等、无副作用——`status --write` 不会因此报错，只在输出层提示。
    ``state_path``/``root`` 供测试注入，默认取真实仓库。

    生成时点以 ``generated_at`` 为基准（渲染当前这份快照的时点），
    否则从 ``state_path`` 头部解析——后者仅用于「读旧文件」的路径。
    """
    root = root or repo_root()
    state_path = state_path or root / "docs" / STATE_FILE
    out: dict = {"fresh": True}

    if generated_at is not None:
        snap_generated = generated_at
    elif state_path.exists():
        snap_generated = _parse_generated_at(state_path.read_text(encoding="utf-8"))
    else:
        snap_generated = None

    if snap_generated is None:
        out["fresh"] = False
        out["stale_files"] = [{
            "path": str(state_path.relative_to(root)),
            "reason": "无法解析生成时间，快照可信度未知" if state_path.exists()
            else "快照不存在",
        }]
        return out

    stale: list[dict] = []
    commit_times = _last_commit_times(root)
    for rel in source_dirs or FRESHNESS_SCAN_DIRS:
        scan_dir = root / rel
        if not scan_dir.exists():
            continue
        for p in sorted(scan_dir.rglob("*")):
            if not p.is_file():
                continue
            src = _nondeterministic_mtime(p, commit_times)
            # 生成时点之后被改动（容差内视为同刻写入，不报）
            if src is not None and src > snap_generated + timedelta(seconds=FRESHNESS_MTIME_TOLERANCE):
                stale.append({
                    "path": str(p.relative_to(root)),
                    "reason": "源较快照更新或提交晚于快照生成时点",
                })

    if stale:
        out["fresh"] = False
        out["stale_files"] = stale
    return out


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


def render(snap: dict, *, state_path: Path | None = None) -> str:
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
        "## 〇、快照新鲜度",
        "",
    ]
    # 传入了 state_path → 评估「磁盘上这份文档」是否过期（读旧文档）;
    # 未传 → 评估「正在渲染的这份快照」（write 路径，其 generated_at=now，判新鲜）。
    if state_path is not None:
        fresh = check_freshness(state_path=state_path)
    else:
        try:
            _snap_generated = datetime.strptime(snap["generated_at"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            _snap_generated = None
        fresh = check_freshness(generated_at=_snap_generated)
    if fresh["fresh"]:
        L += ["> **快照较最新源为新鲜**：生成时点后未见 src/config/tests/docs 下的",
              "> 变更晚于生成时点。若你刚刚改过代码，请运行 `status --write` 重新生成。", ""]
    else:
        L += ["> **快照已过期**——以下权威源比生成时点更新，本文件结论可能失真：", ""]
        shown = fresh["stale_files"][:10]
        for s in shown:
            L.append(f"- `{s['path']}` — {s['reason']}")
        if len(fresh["stale_files"]) > len(shown):
            L.append(f"- …（另 {len(fresh['stale_files']) - len(shown)} 项）")
        L += ["", "> 请运行 `python -m bidpricing.cli status --write` 重新生成后再交接。", ""]

    L += [
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
        ">",
        "> **注意快照的固有滞后**：本文件本身要被提交，因此它记录的 HEAD 通常比当前 HEAD",
        "> 少一次提交（生成快照所需的那次变更尚未提交）。若上列 commit 与 `git log -1` 不一致，",
        "> 属正常现象——**以复算结果为准**，并重新生成快照。",
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

    # 其余闸门的阻塞明细。旧快照只写状态不写原因，接手者必须自己复跑 gate-check
    # 才能回答「被什么挡住」——而快照的全部意义就是免去这一步。明细取不到时
    # 明说「未采集」，不静默留白（本仓对「未定态」的一贯口径）。
    for gate_key, gate_label in (
        ("gate_0b", "Gate 0b"),
        ("phase_0_input_gate", "Phase 0 输入门"),
    ):
        if snap["gates"].get(gate_key) != "BLOCKED":
            continue
        blocked = [
            i for i in (snap.get(f"{gate_key}_items") or [])
            if i.get("status") == "BLOCKED"
        ]
        if not blocked:
            L += [
                f"**{gate_label} 为 BLOCKED，但明细未采集** —— 请运行 "
                "`gate-check` 查看阻塞项。",
                "",
            ]
            continue
        L += [f"**{gate_label} 阻塞项：**", ""]
        for b in blocked:
            L.append(f"- `{b['item']}` — {b['reason']}")
        L.append("")

    L += ["---", "", "## 三、契约制品冻结表", "",
          "| 制品 key | 闸门 | 类型 | hash | 冻结时间 |", "|---|---|---|---|---|"]
    for a in snap["artifacts"]:
        L.append(
            f"| `{a['key']}` | {a.get('gate', '—')} | {a['kind']} | "
            f"{a['hash'] or '**未冻结**'} | {a['frozen_at'] or '—'} |"
        )
    L += [
        "",
        "> hash = 制品内容 SHA-256 前 12 位。制品一改即失配，闸门自动失效——无需人工记忆。",
        "",
        "---",
        "",
        "## 四、质量门",
        "",
        f"- 单元测试：**{t['ran'] if t['ran'] is not None else '未运行'}** 项，"
        f"结果 **{'通过' if t['ok'] else '未通过' if t['ok'] is not None else '未知'}**（{t.get('detail', '')}）"
        f"—— 跑法：`{t.get('runner') or '未运行'}`"
        f"，解释器：`{t.get('python') or '未记录'}`",
        "",
    ]

    # 降级提醒：本机能跑 unittest 却跑不了 pytest 时，discover 会静默跳过
    # tests/ 里的裸函数用例（实测 31 项）并照样报 OK——这跟「全量通过」不是一回事，
    # 必得在绿门上插一道看得见的黄旗，否则数字会骗人。
    if t.get("degraded"):
        L += [
            "> ⚠ **本快照的测试数字是降级口径**：本机没装 pytest，回退到 `unittest discover`。",
            "> 该口径**不收集裸函数 `def test_` 用例**且**不报错**（实测：装了 pytest 后",
            "> 四个 pytest 风格模块共 31 项被静默跳过、returncode 仍为 0）。",
            "> 下方数字与 CI 的 pytest 口径**不可比较**。补依赖后重跑本命令：",
            "> `python -m pip install -r requirements-dev.txt`",
            "",
        ]

    if t["ran"] is not None:
        _cmd = ("python -m pytest tests/ -q" if t.get("runner") == "pytest"
                else "python -m unittest discover -s tests")
        L += [
            "```bash",
            f"cd bid-pricing && PYTHONPATH=src {_cmd}",
            "```",
            "",
        ]

    cc = snap.get("contract_consistency") or {}
    if cc:
        ok_n = sum(1 for i in cc.get("items", []) if i["status"] == "PASS")
        tot_n = len(cc.get("items", []))
        L += [
            f"- 跨制品一致性：**{cc.get('worst', '?')}**（{ok_n}/{tot_n} 项判据通过）"
            " —— 判「已冻结制品彼此是否自洽」，与闸门正交；"
            "两者的关系是「hash 对不对」与「说法一致不一致」，缺一不可",
            f"  - 核心判据：{cc.get('headline', '')}",
            "",
            "```bash",
            "cd bid-pricing && PYTHONPATH=src python -m bidpricing.cli contract-check",
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
        "# 3. 全量测试（口径与 CI 一致；未装 pytest 时先装：pip install -r requirements-dev.txt）",
        "PYTHONPATH=src python -m pytest tests/ -q",
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
