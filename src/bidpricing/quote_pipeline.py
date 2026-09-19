"""主业务链：给定总报价，计算分部分项最优综合单价。"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts.pricing_card import load_pricing_card, resolve_parameters
from .money import money
from .reconciliation import reconcile_total
from .solver.instance import Phase1Instance, check_solution
from .solver.phase1 import SOLUTION_OPTIMAL, solve_phase1
from .solver.backend import load_backend_spec, solve_compiled
from .solver.compiler import compile_model
from .solver.settlement_milp import (
    build_settlement_adjustment_formulation,
    settlement_adjusted_profit,
)
from .solver.verifier import load_verifier_spec, resolve_tolerances
from .total_price import compute_P_competitive, total_from_competitive
from .validation.unbalanced import (
    UnbalancedPolicyError,
    apply_validity_lower_bounds,
    parse_unbalanced_policy,
)

SPEC_FILENAME = "quote_pipeline_spec.json"


def _duplicate_item_ids(items: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """返回出现 ≥2 次的 item_id（按首现顺序去重）。

    canonical 主键是 ``(project_id, unit_work, item_id)``，而本层结果契约
    （``p_by_id`` / ``line_amounts``）以 ``item_id`` 为键。跨单位工程同编码
    时若放行，字典会静默覆盖。此处作为**入口挡位**：拒绝计算并点名冲突，
    不猜测、不合并（对齐 key_spec 的『重复 key BLOCK 禁止自动合并』纪律）。
    """
    seen: dict[str, int] = {}
    dup: list[str] = []
    for row in items:
        item_id = str(row.get("item_id", ""))
        if not item_id:
            continue
        seen[item_id] = seen.get(item_id, 0) + 1
        if seen[item_id] == 2:
            dup.append(item_id)
    return tuple(dup)


def load_quote_pipeline_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class QuotePipelineResult:
    status: str
    target_total: float
    competitive_budget: float | None
    p_by_id: Mapping[str, float]
    line_amounts: Mapping[str, float]
    objective: float | None
    solver_status: str | None
    violations: tuple[str, ...]
    reason: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "target_total": self.target_total, "competitive_budget": self.competitive_budget, "p_by_id": dict(self.p_by_id), "line_amounts": dict(self.line_amounts), "objective": self.objective, "solver_status": self.solver_status, "violations": list(self.violations), "reason": self.reason, "warnings": list(self.warnings)}


def run_quote_pipeline(
    *,
    target_total: float,
    items: Sequence[Mapping[str, Any]],
    fixed_pretax: float,
    vat_rate: float,
    surtax_rate: float,
    supplied_material: float = 0.0,
    env_tax: float = 0.0,
    config_dir: Path | str = "config",
    floor_by_id: Mapping[str, float] | None = None,
    unbalanced_clause: Mapping[str, Any] | None = None,
) -> QuotePipelineResult:
    """执行总报价到分项单价的主流程。

    ``items`` 至少需要 q0、q1_point、c_i、cap、L/U；L 可由已审计的成本
    地板模块提供。若基础资料不足，结果为 BLOCKED 而非猜测报价。
    """
    target_total = float(target_total)
    if target_total <= 0 or fixed_pretax < 0 or not (0.0 <= vat_rate <= 1.0) or not (0.0 <= surtax_rate <= 1.0):
        return QuotePipelineResult("BLOCKED", target_total, None, {}, {}, None, None, (), "总报价/固定项/税率输入非法（税率须为 0～1 之间的小数，如 0.09=9%）")
    required = ("item_id", "q0", "q1_point", "c_i", "cap", "L")
    missing = sorted({field for row in items for field in required if field not in row})
    if missing or not items:
        return QuotePipelineResult("BLOCKED", target_total, None, {}, {}, None, None, (), "输入缺少字段或为空: " + ", ".join(missing))
    dup = _duplicate_item_ids(items)
    if dup:
        return QuotePipelineResult("BLOCKED", target_total, None, {}, {}, None, None, (), "存在重复 item_id，拒绝计算以防字典静默覆盖: " + ", ".join(dup))
    warnings: tuple[str, ...] = ()
    try:
        policy = parse_unbalanced_policy(unbalanced_clause)
        items, warnings = apply_validity_lower_bounds(items, policy)
        budget = compute_P_competitive(target_total, fixed_pretax, vat_rate, surtax_rate, supplied_material, env_tax)
        card = load_pricing_card(Path(config_dir))
        resolved = resolve_parameters(card)
        instance = Phase1Instance.from_master(items, price_column="p0", B=budget, P_star=target_total, rounding_reconciliation_present=True, source="quote_pipeline")
        instance = replace(instance, tie_break_policy="CANONICAL_ITEM_ID")
        solution = solve_phase1(instance, resolved, floor_by_id=floor_by_id)
    except (UnbalancedPolicyError, ValueError, TypeError) as exc:
        return QuotePipelineResult("BLOCKED", target_total, None, {}, {}, None, None, (), f"主流程输入或规则解析失败: {exc}", warnings)
    if solution.status != SOLUTION_OPTIMAL:
        return QuotePipelineResult("BLOCKED", target_total, budget, dict(solution.p_by_id), {}, None, solution.status, (), solution.reason, warnings)
    checked = check_solution(instance, solution.p_by_id, resolved, eps_total=0.01, tolerances={"eps_price": 1e-9})
    if not checked.feasible:
        return QuotePipelineResult("FAIL", target_total, budget, dict(solution.p_by_id), {}, checked.Z, solution.status, tuple(checked.violations), "求解结果约束复验失败", warnings)
    line_amounts = {item.item_id: money(float(item.q0) * float(solution.p_by_id[item.item_id])) for item in instance.items}
    reconciliation = reconcile_total([{"item": item.item_id, "quantity": item.q0, "unit_price": solution.p_by_id[item.item_id]} for item in instance.items], declared_total=money(budget))
    if reconciliation.status != "PASS":
        return QuotePipelineResult("BLOCKED", target_total, budget, dict(solution.p_by_id), line_amounts, checked.Z, solution.status, (), "分项舍入调和未通过: " + reconciliation.reason, warnings)
    return QuotePipelineResult("PASS", target_total, budget, dict(solution.p_by_id), line_amounts, checked.Z, solution.status, (), "总报价已转换为可行分项综合单价并完成约束复验", warnings)


def run_settlement_adjusted_quote_pipeline(
    *,
    target_total: float,
    items: Sequence[Mapping[str, Any]],
    fixed_pretax: float,
    vat_rate: float,
    surtax_rate: float,
    unbalanced_clause: Mapping[str, Any],
    supplied_material: float = 0.0,
    env_tax: float = 0.0,
    config_dir: Path | str = "config",
    floor_by_id: Mapping[str, float] | None = None,
) -> QuotePipelineResult:
    """执行含不平衡报价结算调整的 Phase 2 MILP 主流程。

    该入口与旧的 Phase 1 解析解入口分开，避免把结算期分段收入误当成普通
    ``q1 * p``。求解器不可用、条款不完整或输入异常时均返回 BLOCKED。
    """
    target_total = float(target_total)
    if target_total <= 0 or fixed_pretax < 0 or not (0.0 <= vat_rate <= 1.0) or not (0.0 <= surtax_rate <= 1.0):
        return QuotePipelineResult("BLOCKED", target_total, None, {}, {}, None, None, (), "总报价/固定项/税率输入非法（税率须为 0～1 之间的小数，如 0.09=9%）")
    required = ("item_id", "q0", "q1_point", "c_i", "cap", "L")
    missing = sorted({field for row in items for field in required if field not in row})
    if missing or not items:
        return QuotePipelineResult("BLOCKED", target_total, None, {}, {}, None, None, (), "输入缺少字段或为空: " + ", ".join(missing))
    dup = _duplicate_item_ids(items)
    if dup:
        return QuotePipelineResult("BLOCKED", target_total, None, {}, {}, None, None, (), "存在重复 item_id，拒绝计算以防字典静默覆盖: " + ", ".join(dup))
    try:
        budget = compute_P_competitive(target_total, fixed_pretax, vat_rate, surtax_rate, supplied_material, env_tax)
        card = load_pricing_card(Path(config_dir))
        resolved = resolve_parameters(card)
        instance = Phase1Instance.from_master(
            items, price_column="p0", B=budget, P_star=target_total,
            rounding_reconciliation_present=True, source="quote_pipeline_settlement_milp",
        )
        built = build_settlement_adjustment_formulation(
            instance, clause=unbalanced_clause, vat_rate=vat_rate, floor_by_id=floor_by_id,
        )
        model = compile_model(built.formulation, source="quote_pipeline_settlement_milp")
        spec = load_backend_spec(Path(config_dir))
        profile = json.loads((Path(config_dir) / "precision_profile.json").read_text(encoding="utf-8"))
        verifier_spec = load_verifier_spec(Path(config_dir))
        tolerances, _ = resolve_tolerances(profile, verifier_spec, P_ref=target_total)
        solved = solve_compiled(
            model, spec=spec, instance=instance, resolved=resolved,
            tolerances=tolerances,
        )
    except Exception as exc:  # noqa: BLE001 - 业务入口统一归一为 BLOCKED
        return QuotePipelineResult("BLOCKED", target_total, None, {}, {}, None, None, (), f"结算调整 MILP 输入/求解失败: {exc}")
    if solved.status.normalized != "OPTIMAL":
        return QuotePipelineResult(
            "BLOCKED", target_total, budget, {}, {}, None,
            solved.status.normalized, (), solved.status.reason,
            tuple(built.warnings),
        )
    prices = {
        item.item_id: float(solved.variables[f"p_{item.item_id}"])
        for item in instance.items
        if f"p_{item.item_id}" in solved.variables
    }
    try:
        adjusted_profit = settlement_adjusted_profit(instance, prices, clause=unbalanced_clause, vat_rate=vat_rate)
    except Exception as exc:  # noqa: BLE001
        return QuotePipelineResult("FAIL", target_total, budget, prices, {}, None, solved.status.normalized, (), f"结算利润独立复算失败: {exc}", tuple(built.warnings))
    line_amounts = {
        item.item_id: money(float(item.q0) * prices[item.item_id])
        for item in instance.items if item.item_id in prices and item.q0 is not None
    }
    reconciliation = reconcile_total(
        [{"item": item.item_id, "quantity": item.q0, "unit_price": prices[item.item_id]}
         for item in instance.items if item.item_id in prices],
        declared_total=money(budget),
    )
    if reconciliation.status != "PASS":
        return QuotePipelineResult("BLOCKED", target_total, budget, prices, line_amounts, adjusted_profit, solved.status.normalized, (), "分项舍入调和未通过: " + reconciliation.reason, tuple(built.warnings))
    return QuotePipelineResult(
        "PASS", target_total, budget, prices, line_amounts, adjusted_profit,
        solved.status.normalized, (),
        "已按不平衡报价结算调整条款完成 Phase 2 MILP 求解与独立利润复算",
        tuple(built.warnings),
    )
