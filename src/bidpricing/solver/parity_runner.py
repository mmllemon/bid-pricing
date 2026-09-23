"""Phase 1/2 对拍报告的执行器（T04-04）。

``parity.py`` 是**比较器**（只吃两条路径已产出的结果）；本模块是**执行器**：
把一次对拍的全部输入、逐 case 结论与聚合结论写成可复算的制品。

为什么要单独一层：原先 ``docs/phase12_parity_report.json`` 自称
``generated_by: parity.py``，但**仓库里没有任何代码产出它**——那意味着一份
写着「PASS」的制品无法复算、也无法证伪。本模块把「报告 = 输入 + 比较器」这条
链补上：报告里必须出现**输入的路径**与**复算命令**，否则结论不可追。

输入（bundle）结构：:

    {
      "schema_id": "phase12_parity_input_v1",
      "provenance": {"produced_by": "...", "produced_at": "...", "env": "..."},
      "floor_source": "两侧 floor 的来源说明",
      "cases": [
        {"case_id": "A_pos", "group": "A", "applicable": true,
         "phase1": {"status": "...", "objective": ..., "prices": {...}},
         "phase2": {"status": "...", "objective": ..., "prices": {...}}}
      ]
    }

★ 「两条路径的结果」**不由本模块代产**：本模块不替任一路径求解（同 ``parity.py``
的契约）。缺 bundle ⇒ 结论 BLOCKED 并**具名 owner**，绝不静默降级成「没跑过所以
不置评」——那会让一份未验证的报告看起来只是「还没跑」。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .parity import (
    ParityResult,
    compare_phase12,
    independence_status,
    load_spec,
    resolve_tolerances,
)
from ..states import _STATUS_ORDER

BUNDLE_SCHEMA = "phase12_parity_input_v1"
REPORT_TASK = "T04-04"
REPORTER = "src/bidpricing/solver/parity_runner.py"

#: 聚合序：FAIL 最严，PASS 最宽。**SKIP 不参与竞争**（否则带未激活项的报告
#: 永远到不了 PASS）；空判据集 ⇒ BLOCKED。
# _STATUS_ORDER 已统一至 states.py（O6 收敛）。

#: 缺输入时结论栏里必须出现的具名 owner——把「谁该补什么」写进制品。
MISSING_BUNDLE_OWNER = "T04-04（须给出两条路径的结果留痕：Phase 1 解析解 + Phase 2 LP/MILP）"


class BundleError(ValueError):
    """bundle 结构不合法（不是「没给」，而是「给了但读不出」）。"""


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    group: str
    result: ParityResult

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "group": self.group, **self.result.to_dict()}


def validate_bundle(raw: Any) -> dict[str, Any]:
    """校验 bundle 结构；非法即抛 :class:`BundleError`（**不崩、不猜**）。"""
    if not isinstance(raw, Mapping):
        raise BundleError("bundle 顶层须是对象")
    schema = raw.get("schema_id")
    if schema != BUNDLE_SCHEMA:
        raise BundleError(f"schema_id 须为 {BUNDLE_SCHEMA!r}，实际 {schema!r}")
    cases = raw.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        raise BundleError("cases 须是数组")
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise BundleError(f"cases[{index}] 须是对象")
        if not case.get("case_id"):
            raise BundleError(f"cases[{index}] 缺 case_id")
    return dict(raw)


def aggregate(statuses: Sequence[str]) -> str:
    """按最严竞争聚合。

    三条边界（缺一条都会让报告撒谎）：

    * **SKIP 不参与最严竞争**——存在非 SKIP 判定时按 ``FAIL>BLOCKED>WARN>PASS``
      取最严。把 SKIP 排进竞争会让「带未激活项」的报告永远到不了 PASS。
    * **全 SKIP ⇒ SKIP**（「本轮没判」是合法结论，不等于通过）。
    * **空判据集 ⇒ BLOCKED**（一条都没判成，不是 PASS）。
    """
    known = [s for s in statuses if s in _STATUS_ORDER]
    if not known:
        return "BLOCKED"
    competing = [s for s in known if s != "SKIP"]
    if not competing:
        return "SKIP"
    return min(competing, key=_STATUS_ORDER.index)


def run_parity(
    bundle: Any,
    *,
    config_dir: Path | str = "config",
    signoff_path: Path | str = "docs/reference_review_signoff.json",
    bundle_path: Path | str | None = None,
) -> dict[str, Any]:
    """跑一次对拍并返回**报告字典**（调用方决定落盘与否）。"""
    spec = load_spec(config_dir)
    signoff = independence_status(signoff_path)
    tolerances, unresolved = resolve_tolerances(spec)

    report: dict[str, Any] = {
        "task": REPORT_TASK,
        "spec": spec.get("schema_id"),
        "generated_by": REPORTER,
        "bundle_schema": BUNDLE_SCHEMA,
        "bundle_path": str(bundle_path) if bundle_path is not None else None,
        "bundle_present": bundle is not None,
        "reproduce_command": (
            "PYTHONPATH=src python -m bidpricing.cli parity-check"
            + (f" --bundle {bundle_path}" if bundle_path is not None else "")
        ),
        "independence": {
            "required_task": (spec.get("independence") or {}).get("required_task"),
            "signoff_file": str(signoff_path),
            "status": signoff,
            "non_pass_conclusion": (spec.get("independence") or {}).get("non_pass_conclusion"),
        },
        "tolerances_used": tolerances,
        "tolerances_unresolved": list(unresolved),
        "floor_source": None,
        "cases": [],
        "conclusion": "BLOCKED",
        "level": None,
        "reason": "",
        "obligations": [],
    }

    if bundle is None:
        report["reason"] = (
            "未提供可复算输入 bundle：对拍需要两条路径**已产出**的结果留痕。"
            "本次未对拍任何实例——这不是「已通过」，也不是「不适用」。"
        )
        report["owner"] = MISSING_BUNDLE_OWNER
        return report

    validated = validate_bundle(bundle)
    report["floor_source"] = validated.get("floor_source")
    report["provenance"] = dict(validated.get("provenance") or {})

    outcomes: list[CaseOutcome] = []
    for case in validated["cases"]:
        result = compare_phase12(
            case.get("phase1"),
            case.get("phase2"),
            applicable=bool(case.get("applicable", True)),
            group=str(case.get("group", "A")),
            signoff_path=signoff_path,
            spec=spec,
            floor_source=validated.get("floor_source"),
        )
        outcomes.append(CaseOutcome(str(case["case_id"]), str(case.get("group", "A")), result))

    report["cases"] = [o.to_dict() for o in outcomes]
    statuses = [o.result.status for o in outcomes]
    report["conclusion"] = aggregate(statuses)

    obligations: list[str] = []
    for outcome in outcomes:
        obligations.extend(f"[{outcome.case_id}] {o}" for o in outcome.result.obligations)
    report["obligations"] = obligations

    worst = [o for o in outcomes if o.result.status == report["conclusion"]]
    report["level"] = worst[0].result.level if worst else None
    if report["conclusion"] == "PASS":
        report["reason"] = f"{len(outcomes)} 个实例的 Phase 1/2 结果在制品容差内一致"
    else:
        report["reason"] = "；".join(
            f"[{o.case_id}] {o.result.status}：{o.result.reason}"
            for o in outcomes
            if o.result.status == report["conclusion"]
        ) or "无 case"
    return report


def write_report(report: Mapping[str, Any], out_path: Path | str) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def load_bundle(path: Path | str) -> dict[str, Any]:
    """读 bundle；读不出即抛 :class:`BundleError`（与「没给」区分开）。"""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BundleError(f"bundle 不存在：{p}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"bundle 不可解析：{p}（{exc}）") from exc
    return validate_bundle(raw)
