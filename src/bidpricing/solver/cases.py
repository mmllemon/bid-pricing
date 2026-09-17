"""反例集/正例集的机械复算器（T04-00 的自检）。

**为什么必须机械复算**：``config/phase1_exactness_spec.json`` 里的
``expected`` 与 ``witness`` 是**手写的判据**。手写判据最典型的失效方式是
「实现改了、制品没改，或反过来」——两边都自洽，只有实际行为不同。
本模块把制品里的期望值逐条喂给实现，任何不一致立即显式暴露。

复算分两层：

1. **条件层**：``expected`` 逐条比对 ``check_exactness`` 的判定；
2. **见证层**：``witness.assertions`` 用 ``check_solution`` 把误用解与正确解
   代回原式，验证「误用解更优但不可行 / 可行但次优」这类定性结论。

见证层的断言用**结构化布尔键**而不是可执行表达式——后者是一个不受控的
求值口，且失败时无法定位是哪一项不成立。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..contracts.pricing_card import ResolvedParameters
from .exactness import (
    DEFAULT_EPS_ABS,
    DEFAULT_EPS_PRICE,
    ExactnessVerdict,
    check_exactness,
)
from .instance import Phase1Instance, SolutionCheck, check_solution

SPEC_FILENAME = "phase1_exactness_spec.json"

#: 见证层支持的断言键——新增键须同时在 spec 与 tests 里出现，
#: 否则会出现「制品写了断言、复算器静默忽略」的漏检。
WITNESS_ASSERTIONS: tuple[str, ...] = (
    "wrong_solution_feasible",
    "right_solution_feasible",
    "wrong_competitive_total_gt_B",
    "wrong_Z_gt_right_Z",
)


@dataclass(frozen=True)
class WitnessCheck:
    """见证层复算结果。

    每条断言记成 ``(键, 制品声明值, 实现复算值)`` 三元组——把**声明值**留在
    结果里是刻意的：只报「通过/不通过」时，一旦制品与实现同时改错（同一个
    误解写进两边），复核者无从发现两者原本期望什么。
    """

    assertions: tuple[tuple[str, bool, bool], ...]
    detail: str
    wrong: SolutionCheck | None = None
    right: SolutionCheck | None = None

    @property
    def ok(self) -> bool:
        return all(declared == actual for _k, declared, actual in self.assertions)

    def failures(self) -> tuple[str, ...]:
        return tuple(
            f"{k}（制品声明 {declared}，实现复算 {actual}）"
            for k, declared, actual in self.assertions
            if declared != actual
        )


@dataclass(frozen=True)
class CaseResult:
    """单个 case 的复算结果。"""

    case_id: str
    kind: str
    title: str
    violates: str | None
    verdict: ExactnessVerdict
    expected_verdict: str
    condition_mismatches: tuple[str, ...]
    witness: WitnessCheck | None

    @property
    def ok(self) -> bool:
        return not self.condition_mismatches and (self.witness is None or self.witness.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "kind": self.kind,
            "title": self.title,
            "violates": self.violates,
            "expected_verdict": self.expected_verdict,
            "actual_verdict": self.verdict.verdict,
            "ok": self.ok,
            "condition_mismatches": list(self.condition_mismatches),
            "conditions": [c.to_dict() for c in self.verdict.conditions],
            "implementation_notes": list(self.verdict.implementation_notes),
            "witness": (
                None if self.witness is None else {
                    "ok": self.witness.ok,
                    "assertions": [
                        {"key": k, "declared": d, "actual": a, "match": d == a}
                        for k, d, a in self.witness.assertions
                    ],
                    "failures": list(self.witness.failures()),
                    "detail": self.witness.detail,
                    "wrong": None if self.witness.wrong is None
                             else self.witness.wrong.to_dict(),
                    "right": None if self.witness.right is None
                             else self.witness.right.to_dict(),
                }
            ),
        }


def load_exactness_spec(config_dir: Path) -> dict[str, Any]:
    """读制品。缺文件是**未定态**，抛错而非返回空字典（ADR-0004）。"""
    path = Path(config_dir) / SPEC_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"Phase 1 精确性条件制品缺失：{path}。"
            "T04-00 未完成时 §4.1 的实验不得称为「数学等价性实验」。"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def iter_cases(spec: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for case in spec.get("counterexamples", []):
        yield "counterexample", case
    for case in spec.get("positive_examples", []):
        yield "positive_example", case


def run_cases(
    spec: Mapping[str, Any],
    resolved: ResolvedParameters,
    *,
    eps_abs: float = DEFAULT_EPS_ABS,
    eps_price: float = DEFAULT_EPS_PRICE,
    only: str | None = None,
) -> list[CaseResult]:
    """跑全部（或指定）case 的条件层与见证层复算。"""
    results: list[CaseResult] = []
    for kind, case in iter_cases(spec):
        case_id = str(case.get("id", "?"))
        if only and only not in (case_id, "all"):
            continue
        instance = Phase1Instance.from_dict(
            case.get("instance") or {}, source=str(case.get("title", ""))
        )
        verdict = check_exactness(
            instance, resolved, eps_abs=eps_abs, eps_price=eps_price
        )
        mismatches = _compare_expected(case.get("expected") or {}, verdict)
        witness = _run_witness(case, instance, resolved, eps_abs, eps_price)
        results.append(
            CaseResult(
                case_id=case_id,
                kind=kind,
                title=str(case.get("title", "")),
                violates=case.get("violates"),
                verdict=verdict,
                expected_verdict=str((case.get("expected") or {}).get("verdict", "")),
                condition_mismatches=mismatches,
                witness=witness,
            )
        )
    return results


def _compare_expected(
    expected: Mapping[str, Any], verdict: ExactnessVerdict
) -> tuple[str, ...]:
    """双向比对：制品声明的每一项都要与实现一致，**且实现判否的条件不得漏声明**。

    只做单向比对（制品说了什么就查什么）会留下一个真实漏洞：制品漏写一条
    FAIL 时，实现多判一条 FAIL 反而不报错——判据整体变严却没有信号。
    CE-07 曾经就踩到过（EC-5 的平台判定被漏写）。
    """
    from .exactness import EXACTNESS_IDS

    mismatches: list[str] = []
    for key, want in expected.items():
        got = verdict.verdict if key == "verdict" else verdict.status_of(key)
        if got is None:
            mismatches.append(f"{key}: 制品声明 {want}，实现无此判据")
        elif str(got) != str(want):
            mismatches.append(f"{key}: 制品期望 {want}，实现判 {got}")

    declared = set(expected)
    for c in verdict.conditions:
        if c.id in EXACTNESS_IDS and c.status in ("FAIL", "BLOCKED") and c.id not in declared:
            mismatches.append(
                f"{c.id}: 实现判 {c.status}（{c.name}），制品 expected 未声明该条件"
                "——判据整体变严却没有信号"
            )
    return tuple(mismatches)


def _run_witness(
    case: Mapping[str, Any],
    instance: Phase1Instance,
    resolved: ResolvedParameters,
    eps_abs: float,
    eps_price: float,
) -> WitnessCheck | None:
    witness = case.get("witness") or {}
    asserts = witness.get("assertions")
    if not asserts:
        return None

    eps_total = _eps_total(instance, eps_abs, eps_price)
    wrong = _solve_one(instance, witness.get("wrong_solution"), resolved, eps_total)
    right = _solve_one(instance, witness.get("right_solution"), resolved, eps_total)

    checks: list[tuple[str, bool, bool]] = []
    for key, declared in asserts.items():
        declared_bool = bool(declared)
        if key not in WITNESS_ASSERTIONS:
            # 制品写了未登记的断言键 => 必须报不通过，不得静默忽略
            # （否则「制品声明了这回事、实现却没查」会被读成已查过）。
            checks.append((key, declared_bool, not declared_bool))
            continue
        checks.append(
            (key, declared_bool, _evaluate_assertion(key, instance, wrong, right))
        )

    detail_parts: list[str] = []
    if wrong is not None:
        detail_parts.append(
            f"误用解：Z={wrong.Z:.4f}，可竞争部分={wrong.competitive_total:.4f}，"
            f"可行={wrong.feasible}"
            + (f"（{'; '.join(wrong.violations[:2])}）" if wrong.violations else "")
        )
    if right is not None:
        detail_parts.append(
            f"正确解：Z={right.Z:.4f}，可竞争部分={right.competitive_total:.4f}，"
            f"可行={right.feasible}"
            + (f"（{'; '.join(right.violations[:2])}）" if right.violations else "")
        )
    return WitnessCheck(
        assertions=tuple(checks),
        detail=" ｜ ".join(detail_parts),
        wrong=wrong,
        right=right,
    )


def _solve_one(
    instance: Phase1Instance,
    solution: Mapping[str, Any] | None,
    resolved: ResolvedParameters,
    eps_total: float,
) -> SolutionCheck | None:
    if not solution:
        return None
    p_values = solution.get("p")
    if not p_values:
        return None
    opt = instance.opt_items
    if len(p_values) != len(instance.items):
        return None
    p_by_id = {item.item_id: float(v) for item, v in zip(instance.items, p_values)}
    return check_solution(instance, p_by_id, resolved, eps_total=eps_total)


def _evaluate_assertion(
    key: str,
    instance: Phase1Instance,
    wrong: SolutionCheck | None,
    right: SolutionCheck | None,
) -> bool:
    if key == "wrong_solution_feasible":
        return wrong is not None and wrong.feasible
    if key == "right_solution_feasible":
        return right is not None and right.feasible
    if key == "wrong_competitive_total_gt_B":
        if wrong is None or instance.B is None:
            return False
        return wrong.competitive_total > instance.B
    if key == "wrong_Z_gt_right_Z":
        if wrong is None or right is None:
            return False
        return wrong.Z > right.Z
    return False  # pragma: no cover - 由 WITNESS_ASSERTIONS 白名单挡住


def _eps_total(
    instance: Phase1Instance, eps_abs: float, eps_price: float
) -> float:
    base = instance.B if instance.B is not None else 0.0
    return max(eps_abs, eps_price * base)
