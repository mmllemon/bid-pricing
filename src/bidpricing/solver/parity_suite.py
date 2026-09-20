"""T04-04：从 golden_dataset_v1 构造对拍实例并产出 input bundle。

**为什么需要这一层**：``parity_runner.py`` 只消费「已产出的两条路径结果」，
但它不替任一路径求解——bundle 得由**别处**生产。本模块把「结果留痕」闭合成
一条可由代码复算的链：解析 golden 制品 → 构造求解层实例 → 分别跑 Phase 1
（解析解）与 Phase 2（LP，同一条公式的编译求解）→ 序列化为
``phase12_parity_input_v1`` bundle。

**为什么放在求解层而不是 tests**：ADR-0036 的 buy-in 是「报告必须由代码产出、
可复算、能证伪」。测试目录里的生成器无法被 ``parity-check`` 引用；而本模块
产出的 bundle 可被 CLI 直接喂给 ``parity-check --bundle``。

**golden 分层 A–F 的取舍（诚实声明，不掩盖）**：
* 正例 A/B/D/F：加 ``tie_break_policy`` 声明后通过 Phase 1 EXACT（EC-5 平台
  可被 tie-break 豁免，见 exactness._ec5），进入 A 组适用子集；
* E_pos（2000 行极端尺度）：B 超出加权上界（EC-7 FAIL），**不可用**——本
  生成器显式跳过并写入 skip 清单，不静默冒充「覆盖到 E 了」；
* C_pos（0 数据行）：无变量可优化（EC-1 FAIL），跳过。
* 负例一律跳过（对拍只应在适用子集内要求一致性，ADR-0036）。

每 case 的 ``layer`` ``p0``/``L``/``B`` 取值都是**从 golden 派生、在报告里
self-describing** 的（ADR-0026 floor 来源、ADR-0004 缺值不压成 0）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..io.boq import parse_listing
from ..io.clean import clean_listing_rows
from ..io.golden import GOLDEN_VERSION
from ..io.match import match_canonical_rows
from ..paths import repo_root
from ..contracts.pricing_card import load_pricing_card, resolve_parameters
from .backend import load_backend_spec, solve_compiled
from .compiler import compile_model
from .exactness import EXACTNESS_IDS, check_exactness
from .formulation import build_formulation
from .instance import ROLE_OPTIMIZABLE, Phase1Instance, check_solution
from .phase1 import _layer_for, solve_phase1
from .verifier import load_verifier_spec, resolve_tolerances

BUNDLE_SCHEMA = "phase12_parity_input_v1"
TIE_BREAK = "CANONICAL_ITEM_ID"


def golden_dir() -> Path:
    return repo_root() / "tests" / "data" / "golden" / GOLDEN_VERSION


def _build_instance(items: list[dict[str, Any]], *, B: float,
                    source: str) -> Phase1Instance:
    """构造求解层实例：p0=cap、U=cap、L=0，加 tie-break 声明（EC-5 豁免）。"""
    return Phase1Instance.from_dict(
        {
            "items": [
                {
                    "item_id": i["item_id"],
                    "role": ROLE_OPTIMIZABLE,
                    "in_c1_scope": True,
                    "q0": i["q0"],
                    "q1_point": i["q1_point"],
                    "c_i": i["c_i"],
                    "cap": i["cap"],
                    "p0": i["cap"],
                    "L": 0.0,
                    "U": i["cap"],
                }
                for i in items
            ],
            "B": B,
            "P_star": B,
            "tie_break_policy": TIE_BREAK,
        },
        source=source,
    )


def load_case_items(entry: Mapping[str, Any]) -> tuple[list[dict[str, Any]], float, str]:
    """解析一个 golden case 的 cap/cost 双侧并融合为可构造实例的 items。

    返回 ``(items, B, skip_reason)``。``skip_reason`` 非空表示该 case **不可用**
    （异常/封锁/无变量/未匹配），上层据它写入 skip 清单。
    """
    gd = golden_dir()
    cap_rows, cost_rows = [], []
    for side, sink in (("cap", cap_rows), ("cost", cost_rows)):
        f = entry.get("files", {}).get(side)
        if f is None:
            continue
        rep = parse_listing(gd / f, "golden")
        cleaned, _cr = clean_listing_rows(rep.rows, side)
        sink.extend(cleaned)
    mrep = match_canonical_rows(cap_rows, cost_rows)
    if mrep.blocked or mrep.anomalies:
        return [], 0.0, f"blocked/anomalies(n={len(mrep.anomalies)})"
    items: list[dict[str, Any]] = []
    B = 0.0
    for m in mrep.items:
        if not m.cap_row or not m.cost_row:
            continue
        if m.cap is None or m.q0 is None:
            continue
        items.append({
            "item_id": m.item_id,
            "q0": m.q0,
            "q1_point": m.q1_point,
            "c_i": m.c_i,
            "cap": m.cap,
        })
        B += float(m.cap) * float(m.q0)
    if not items:
        return [], 0.0, "无两侧齐备可优化项(n=0)"
    return items, B, ""


def build_bundle(
    *,
    config_dir: Path | str = "config",
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """跑 golden 正例的 Phase 1/2 两条路径，返回可复算的 input bundle。"""
    cfg = Path(config_dir)
    card = load_pricing_card(cfg)
    resolved = resolve_parameters(card)
    bspec = load_backend_spec(cfg)
    prof = json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))
    vspec = load_verifier_spec(cfg)

    gd = golden_dir()
    mf = manifest if manifest is not None else json.loads(
        (gd / "manifest.json").read_text(encoding="utf-8"))
    eps_abs = float(prof["eps_abs"]["value"])
    eps_price = float(prof["eps_price"]["value"])
    resolution = float((prof.get("rounding") or {}).get("resolution", 0.01))

    cases: list[dict[str, Any]] = []
    skipped: list[str] = []
    produced = {"phase1": 0, "phase2": 0}

    for entry in mf["cases"]:
        cid = entry["case_id"]
        if entry.get("kind") != "positive":
            skipped.append(f"{cid}:negative 不参与对拍")
            continue
        items, B, skip = load_case_items(entry)
        if skip:
            skipped.append(f"{cid}:{skip}")
            continue
        inst = _build_instance(items, B=B, source=f"golden/{cid}/{GOLDEN_VERSION}")

        # 适用性子集检查：EC 有一项非 PASS(EXACT group) 即不可用
        verdict = check_exactness(inst, resolved)
        a_group = [c for c in verdict.conditions
                   if c.id in EXACTNESS_IDS and c.group == "EXACTNESS"]
        if any(c.status in ("FAIL", "BLOCKED") for c in a_group):
            bad = ",".join(f"{c.id}={c.status}" for c in a_group
                           if c.status in ("FAIL", "BLOCKED"))
            skipped.append(f"{cid}:Phase1 解析解不适用({bad})")
            continue

        # ---- Phase 1：解析解 ------------------------------------------
        sol1 = solve_phase1(inst, resolved, eps_abs=eps_abs, eps_price=eps_price)
        if not sol1.optimal:
            skipped.append(f"{cid}:Phase1 非 OPTIMAL（{sol1.status}）")
            continue
        p1 = dict(sol1.p_by_id)
        layers1 = sol1.layers()
        produced["phase1"] += 1

        # ---- Phase 2：编译 LP 求解 -------------------------------------
        fm = build_formulation(inst, resolved, eps_abs=eps_abs,
                               eps_price=eps_price, resolution=resolution)
        model = compile_model(fm, source=f"parity_suite:{cid}")
        P_ref = inst.P_star if inst.P_star is not None else inst.B
        tolerances, _ = resolve_tolerances(prof, vspec, P_ref=P_ref)
        r2 = solve_compiled(model, spec=bspec, instance=inst, resolved=resolved,
                            eps_total=eps_abs, tolerances=tolerances)
        if not r2.solved:
            skipped.append(f"{cid}:Phase2 非 OPTIMAL（{r2.status.normalized}）")
            continue
        p2 = {k[2:]: v for k, v in r2.variables.items() if k.startswith("p_")}
        produced["phase2"] += 1

        # ---- 目标值：同一独立裁判（check_solution）给两侧，保证口径一致 ----
        ck1 = check_solution(inst, p1, resolved, eps_total=eps_abs,
                             tolerances={"eps_price": eps_price})
        ck2 = check_solution(inst, p2, resolved, eps_total=eps_abs,
                             tolerances={"eps_price": eps_price})

        # ---- 层归属（复用 Phase1 的 _layer_for，保证两侧同语言）-----------
        layers2: dict[str, str] = {}
        for item in inst.opt_items:
            if item.item_id not in p2:
                continue
            layers2[item.item_id] = _layer_for(p2[item.item_id], item.L, item.U)

        cases.append({
            "case_id": cid,
            "group": "A",
            "applicable": True,
            "phase1": {"status": "OPTIMAL", "objective": ck1.Z,
                       "prices": p1, "layers": layers1},
            "phase2": {"status": r2.status.normalized, "objective": ck2.Z,
                       "prices": p2, "layers": layers2},
        })

    return {
        "schema_id": BUNDLE_SCHEMA,
        "provenance": {
            "produced_by": "src/bidpricing/solver/parity_suite.py::build_bundle",
            "golden_version": GOLDEN_VERSION,
            "tie_break_policy": TIE_BREAK,
            "skipped": skipped,
            "produced": produced,
        },
        "floor_source": (
            f"golden_dataset_v1：p0=cap、U=cap、L=0、B=Σ(cap_i·q0_i)，"
            f"tie_break={TIE_BREAK}"
        ),
        "cases": cases,
    }


def write_bundle(bundle: Mapping[str, Any], out_path: Path | str) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return p


def load_manifest() -> dict[str, Any]:
    return json.loads((golden_dir() / "manifest.json").read_text(encoding="utf-8"))


def iter_cases(bundle: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    """公开遍历案例以供测试断言数据集覆盖情况。"""
    return bundle.get("cases", [])