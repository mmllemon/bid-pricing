"""OI-MA-A 量化实验：C7 大 M 系数 M_hi 放大倍数对 HiGHS 分支定界收敛的影响。

挂账来源：T04-02B「M_hi 对分支定界收敛的影响待量化」，登记于
config/solver_backend_spec.json 的 open_items。本脚本是该挂账的
**可复算答案**：同一张模型按 k ∈ {1,2,5,10,100} 放大 C7.upper 的 M_hi
（z 系数与 RHS 同步放大；CC-08 恒真条件在放大方向恒成立，放大不切可行解），
记录 目标值 / LP 松弛 / B&B 节点数 / 耗时，并做语义守卫（Z 随 k 变化即 FAIL）。

合成口径（留痕，非项目数据；parity_suite 同款推导）：
- N 项全 OPTIMIZABLE、in_c1_scope，q0=10，cap=100+i，c_i=cap×0.85（全低于 cap，
  亏损分支是优化选择而非被迫）；B=P_star=Σ cap_i·q0_i；
- U=cap（显式箱上界），前段每 12 项 1 项 U=None（仅 C1 隐式上界——M_hi 放大敏感区）；
- params 同探针（theta_dev=0.15、SEGMENT），n_max=3（名额 < 候选数 ⇒ 真实组合选择）。

跑法：``PYTHONPATH=src python tools/oi_ma_a_experiment.py``（结果默认落
``docs/oi_ma_a_experiment.json``，与 phase12_parity_report.json 同款「可复算留痕」）。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from bidpricing.contracts.pricing_card import load_pricing_card, resolve_parameters  # noqa: E402
from bidpricing.paths import config_dir  # noqa: E402
from bidpricing.solver.backend import load_backend_spec, solve_compiled  # noqa: E402
from bidpricing.solver.compiler import compile_model, pulp_name_map, to_pulp  # noqa: E402
from bidpricing.solver.formulation import (  # noqa: E402
    PROBE_SOLVER_INPUTS,
    build_formulation,
    probe_instance,
)
from bidpricing.solver.instance import Phase1Instance  # noqa: E402

DEFAULT_SCALES = (1.0, 2.0, 5.0, 10.0, 100.0)
DEFAULT_N_RUNS = 5


def build_synthetic_instance(n: int) -> Phase1Instance:
    items = []
    caps = []
    for i in range(1, n + 1):
        cap = 100.0 + i
        items.append({
            "item_id": f"X{i:03d}",
            "role": "OPTIMIZABLE",
            "in_c1_scope": True,
            "q0": 10.0,
            "q1_point": round(10.0 * (0.95 + (i % 10) * 0.01), 4),
            "c_i": round(cap * 0.85, 2),
            "p0": cap,
            "cap": cap,
            "L": 0.0,
            "U": None if (i % 12 == 0 and i <= 36) else cap,
            "alpha": 0.0,
        })
        caps.append(cap * 10.0)
    doc = {
        "items": items,
        "B": round(sum(caps), 2),
        "P_star": round(sum(caps), 2),
        "params": {"theta_dev": 0.15, "rho_plus": 0.0, "rho_minus": 0.0,
                    "adjustment_scope": "SEGMENT", "theta": 0.05},
        "active_soft_constraints": ["C7"],
        "rounding_reconciliation_present": True,
        "tie_break_policy": "CANONICAL_ITEM_ID",
        "source": "oi-ma-a synthetic instance",
    }
    return Phase1Instance.from_dict(doc, source="oi-ma-a/synthetic")


def scale_m_hi(fm, k: float):
    """C7.upper 的 M_hi 放大 k 倍：z 系数与 RHS 同步（RHS = c_i − eps + k·M_hi）。"""
    new_rows = []
    for row in fm.rows:
        if row.constraint_id == "C7.upper":
            km = float(row.aux_get("M_hi")) * k
            new_coeffs = tuple(
                (sym, km) if sym.startswith("z_") else (sym, cf)
                for sym, cf in row.coefficients
            )
            new_rows.append(dataclasses.replace(
                row, coefficients=new_coeffs,
                rhs=float(row.aux_get("c_i")) - float(row.aux_get("eps_res")) + km))
        else:
            new_rows.append(row)
    return dataclasses.replace(fm, rows=tuple(new_rows))


def lp_relaxation_bound(model) -> float | None:
    """z 族全放连续解同一张模型的 LP 松弛（与生产同源 HiGHS；失败如实返 None）。"""
    try:
        import pulp
    except ImportError:
        return None
    prob = to_pulp(model)
    if prob is None:
        return None
    z_symbols = {v.symbol for v in model.variables if v.family == "z"}
    z_names = {name for name, sym in pulp_name_map(model).items() if sym in z_symbols}
    relaxed = 0
    for var in prob.variables():
        if var.name in z_names:
            var.cat = "Continuous"
            relaxed += 1
    if relaxed == 0:
        return None
    status = prob.solve(pulp.HiGHS(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        return None
    return float(pulp.value(prob.objective))


def run_scales(label, instance, fm, resolved, bspec, eps_abs, scales, n_runs) -> dict:
    results: dict[str, dict] = {}
    for k in scales:
        model = compile_model(fm if k == 1.0 else scale_m_hi(fm, k), source=f"{label}:k{k:g}")
        times: list[float] = []
        last = None
        for _ in range(n_runs):
            t0 = time.perf_counter()
            last = solve_compiled(model, spec=bspec, instance=instance, resolved=resolved, eps_total=eps_abs)
            times.append(time.perf_counter() - t0)
        assert last is not None
        diag = dict(last.diagnostics or {})
        z_opt = last.reported_objective
        lp_bound = lp_relaxation_bound(model)
        over = (
            None if lp_bound is None or not z_opt
            else round((lp_bound - z_opt) / abs(z_opt), 9)
        )
        results[str(k)] = {
            "k": k,
            "status": last.status.normalized,
            "mip_objective": z_opt,
            "lp_relaxation_objective": lp_bound,
            "lp_overoptimality_rel": over,
            "mip_node_count": diag.get("mip_node_count"),
            "mip_gap": diag.get("mip_gap"),
            "wall_ms_median": round(statistics.median(times) * 1000, 4),
            "wall_ms_max": round(max(times) * 1000, 4),
        }
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="OI-MA-A：M_hi 放大倍数 vs B&B 收敛（量化实验）")
    ap.add_argument("--n", type=int, default=60, help="合成实例项数（默认 60）")
    ap.add_argument("--scales", default="1,2,5,10,100", help="M_hi 放大倍数，逗号分隔")
    ap.add_argument("--runs", type=int, default=DEFAULT_N_RUNS, help="每档复跑次数（取中位耗时）")
    ap.add_argument("--out", default=str(REPO / "docs" / "oi_ma_a_experiment.json"),
                    help="结果落盘路径（默认 docs/oi_ma_a_experiment.json）")
    args = ap.parse_args()

    scales = tuple(float(s) for s in args.scales.split(",") if s)
    cfg = config_dir()
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    eps_abs = float(prof["eps_abs"]["value"])
    eps_price = float(prof["eps_price"]["value"])
    resolution = float(prof["rounding"]["resolution"])
    resolved = resolve_parameters(load_pricing_card(cfg))
    bspec = load_backend_spec(cfg)
    solver_inputs = {k: PROBE_SOLVER_INPUTS.get(k) for k in ("theta", "n_max", "d_max", "r_min", "z_min", "pi_target")}

    out: dict[str, object] = {
        "experiment": "OI-MA-A M_hi scaling vs HiGHS B&B convergence",
        "runs_per_k": args.runs,
        "scales": list(scales),
    }

    # 探针（根节点即解，作为「无 B&B」对照）
    probe = probe_instance(active=("C7",))
    fm_probe = build_formulation(probe, resolved, eps_abs=eps_abs, eps_price=eps_price,
                                 resolution=resolution, **solver_inputs)
    out["probe"] = run_scales("probe", probe, fm_probe, resolved, bspec, eps_abs, scales, args.runs)

    # 合成 N 项实例（真实 B&B）
    synth = build_synthetic_instance(args.n)
    fm_synth = build_formulation(synth, resolved, eps_abs=eps_abs, eps_price=eps_price,
                                 resolution=resolution, **solver_inputs)
    out["synthetic"] = {
        "n_items": args.n,
        "n_vars": fm_synth.n_vars,
        "n_rows": fm_synth.n_rows,
        "n_c7_upper_rows": len(fm_synth.rows_of("C7.upper")),
        "results": run_scales("synthetic", synth, fm_synth, resolved, bspec, eps_abs, scales, args.runs),
    }

    for tag in ("probe", "synthetic"):
        results = out[tag] if tag == "probe" else out[tag]["results"]
        zs = [r["mip_objective"] for r in results.values() if r["mip_objective"] is not None]
        spread = max(abs(z - zs[0]) / max(abs(zs[0]), 1e-9) for z in zs) if zs else 0.0
        out[f"{tag}_semantics_guard"] = (
            "PASS" if spread < 1e-9 else f"FAIL: Z 随 k 变化（相对差 {spread:.3e}）")
        for r in results.values():
            print(f"[{tag}] k={r['k']:>6g}  {r['status']:<9} Z={r['mip_objective']}  "
                  f"LP={r['lp_relaxation_objective']}  nodes={r['mip_node_count']}  "
                  f"med={r['wall_ms_median']}ms")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n语义守卫：{out['probe_semantics_guard']} / {out['synthetic_semantics_guard']}")
    print(f"结果已写入 {out_path}")
    return 0 if all(str(out[f"{t}_semantics_guard"]) == "PASS" for t in ("probe", "synthetic")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
