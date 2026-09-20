"""Phase 1/2 对拍器（T04-04）。

本模块**只比较两条路径已经产出的结果，不替任一路径求解**；独立性签署未通过时
结论强制 BLOCKED，避免把同一作者的双重实现包装成「对拍通过」。

三级判定的分工（照 ``phase12_parity_spec.json`` 的 ``comparison_levels``）：

* ``L1`` 两条路径**都产出可比较的状态**——缺任一侧状态即 BLOCKED（规格
  ``blocked_rules`` 第 3 条）。**不得**因为「数值恰好相等」而跳过这一关：
  数值相等而状态不可比，恰恰是「两侧其实解了不同问题」的典型形态。
* ``L2`` 目标值与报价向量在**制品声明的**容差内一致。
* ``L3`` 层归属 + 约束残差在制品声明的 ``residual_abs`` 内一致。

★ 判决宽度一律来自 ``phase12_parity_spec.json`` 的 ``tolerances``（**唯一来源**），
函数入参只作**显式覆盖**。容差缺项且本次判定确实要用到它时判 BLOCKED——
不得静默退回代码里的默认数：那是 DV-01 家族（同一个量在两层各有一个宽度，
差 1e4 倍也看不出来）。

★ 「口径不可比」既不是 PASS 也不是 FAIL。L3 残差只有一侧提供时，两侧并不是
在同一个口径下比对过，判 BLOCKED 并写明是哪一侧缺。

★ 排序键/容差/单位这类「跨层同名的量」在本模块一律**具名**出现在结果里
（``tolerances`` / ``residual_abs`` / ``floor_source``），供报告逐项留痕。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

SPEC_FILENAME = "phase12_parity_spec.json"
SIGNOFF_FILENAME = "reference_review_signoff.json"

#: 制品声明的容差键。新增键须同时在 spec 与这里出现，否则会出现
#: 「制品写了宽度、比较器静默不读」的漏检。
TOLERANCE_KEYS: tuple[str, ...] = ("objective_abs", "price_abs", "residual_abs")

#: 目标/报价的取值别名（两条路径各自的历史命名）。
_OBJECTIVE_NAMES = ("objective", "Z", "Z_competitive")
_PRICE_NAMES = ("prices", "p_by_id")


@dataclass(frozen=True)
class ParityResult:
    status: str
    level: str | None
    reason: str
    objective_delta: float | None = None
    max_price_delta: float | None = None
    max_residual_delta: float | None = None
    mismatches: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()
    independence: str = "UNKNOWN"
    floor_source: str | None = None
    tolerances: Mapping[str, float] = field(default_factory=dict)
    phase1_status: str | None = None
    phase2_status: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.status == "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "level": self.level,
            "reason": self.reason,
            "objective_delta": self.objective_delta,
            "max_price_delta": self.max_price_delta,
            "max_residual_delta": self.max_residual_delta,
            "mismatches": list(self.mismatches),
            "obligations": list(self.obligations),
            "independence": self.independence,
            "floor_source": self.floor_source,
            "tolerances": dict(self.tolerances),
            "phase1_status": self.phase1_status,
            "phase2_status": self.phase2_status,
            "details": dict(self.details),
        }


def load_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def independence_status(
    signoff_path: Path | str = "docs/reference_review_signoff.json",
) -> str:
    path = Path(signoff_path)
    if not path.exists():
        return "BLOCKED"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "BLOCKED"
    return "PASS" if data.get("signed") is True and data.get("reviewer") else "BLOCKED"


def resolve_tolerances(
    spec: Mapping[str, Any] | None,
    *,
    overrides: Mapping[str, float | None] | None = None,
) -> tuple[dict[str, float], tuple[str, ...]]:
    """解析具名容差。

    返回 ``(已解析表, 未解析键)``。**未解析键不做任何默认填充**——由调用方按
    「这条判定是否真的用到它」决定是否 BLOCKED（SKIP 与 BLOCKED 不是一回事）。
    """
    declared = dict((spec or {}).get("tolerances") or {})
    resolved: dict[str, float] = {}
    unresolved: list[str] = []
    for key in TOLERANCE_KEYS:
        override = (overrides or {}).get(key)
        if override is not None:
            resolved[key] = float(override)
            continue
        raw = declared.get(key)
        if raw is None:
            unresolved.append(key)
            continue
        resolved[key] = float(raw)
    return resolved, tuple(unresolved)


def _status_of(data: Mapping[str, Any] | None) -> Any:
    """取一侧的归一状态；``None``/空串都表示「没给」。"""
    if not data:
        return None
    for name in ("status", "native_status", "verdict"):
        value = data.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def compare_phase12(
    phase1: Mapping[str, Any] | None,
    phase2: Mapping[str, Any] | None,
    *,
    applicable: bool = True,
    group: str = "A",
    signoff_path: Path | str = "docs/reference_review_signoff.json",
    spec: Mapping[str, Any] | None = None,
    objective_abs: float | None = None,
    price_abs: float | None = None,
    residual_abs: float | None = None,
    floor_source: str | None = None,
) -> ParityResult:
    """比较 Phase 1/2 的结果字典。

    结果可用 ``objective``/``Z``/``Z_competitive`` 表示目标值，
    ``prices``/``p_by_id`` 表示报价向量，``status`` 表示该路径的归一状态；
    ``layers``/``residuals`` 可选用于 L3。**缺失值不静默当作 0。**

    容差默认取 ``spec['tolerances']``；显式传参只作覆盖。``spec`` 为 ``None``
    时按 ``config/`` 下的制品加载。
    """
    if spec is None:
        spec = load_spec()
    tolerances, unresolved = resolve_tolerances(
        spec,
        overrides={"objective_abs": objective_abs, "price_abs": price_abs, "residual_abs": residual_abs},
    )
    obligations: list[str] = []
    if floor_source is None:
        # ADR-0026：报告须声明 floor 来源。两侧若取了不同地板会出现**假不一致**，
        # 却看不出来；故未声明时记义务（可追溯性），不改判定（算式本身没错）。
        obligations.append("floor 来源未声明（ADR-0026 要求报告声明）")

    independence = independence_status(signoff_path)
    kwargs: dict[str, Any] = {
        "independence": independence,
        "floor_source": floor_source,
        "tolerances": tolerances,
        "details": {"tolerance_unresolved": list(unresolved)},
    }

    def blocked(reason: str, **extra: Any) -> ParityResult:
        return ParityResult("BLOCKED", None, reason, obligations=tuple(obligations), **kwargs, **extra)

    if independence != "PASS":
        return blocked("T04-08 独立性签署状态非 PASS")
    if not applicable:
        return blocked("实例不在 T04-00 适用子集")
    if group not in {"A", "B"}:
        return blocked(f"未知对拍组 {group!r}")
    if not phase1 or not phase2:
        return blocked("任一路径缺少可比较结果")

    # ---- L1：两侧都产出可比较的状态 ------------------------------------
    s1, s2 = _status_of(phase1), _status_of(phase2)
    kwargs["phase1_status"], kwargs["phase2_status"] = s1, s2
    if s1 is None or s2 is None:
        missing = "Phase 1" if s1 is None else "Phase 2"
        return blocked(f"L1：{missing} 缺少可比较状态（规格 blocked_rules 第 3 条）")

    def value(data: Mapping[str, Any], names: tuple[str, ...]) -> Any:
        for name in names:
            if name in data:
                return data[name]
        return None

    # ---- L2：目标值 -----------------------------------------------------
    z1 = value(phase1, _OBJECTIVE_NAMES)
    z2 = value(phase2, _OBJECTIVE_NAMES)
    if z1 is None or z2 is None:
        return blocked("目标值缺失，无法进行 L2 对拍")
    if "objective_abs" not in tolerances:
        return blocked("L2 容差 objective_abs 未解析（不得静默按默认宽度判）")
    objective_delta = abs(float(z1) - float(z2))
    mismatches: list[str] = []
    if objective_delta > tolerances["objective_abs"]:
        mismatches.append(
            f"objective delta {objective_delta} > {tolerances['objective_abs']}（objective_abs）"
        )

    # ---- L2：报价向量 ---------------------------------------------------
    p1 = value(phase1, _PRICE_NAMES)
    p2 = value(phase2, _PRICE_NAMES)
    if not isinstance(p1, Mapping) or not isinstance(p2, Mapping):
        return blocked("报价向量缺失，无法进行 L2 对拍", objective_delta=objective_delta)
    if "price_abs" not in tolerances:
        return blocked("L2 容差 price_abs 未解析（不得静默按默认宽度判）", objective_delta=objective_delta)
    ids = sorted(set(p1) | set(p2))
    deltas = [abs(float(p1[k]) - float(p2[k])) for k in ids if k in p1 and k in p2]
    missing = [k for k in ids if k not in p1 or k not in p2]
    max_delta = max(deltas, default=0.0)
    if missing:
        mismatches.append("price ids missing: " + ",".join(missing))
    if max_delta > tolerances["price_abs"]:
        mismatches.append(f"price delta {max_delta} > {tolerances['price_abs']}（price_abs）")

    # ---- B 组：只加义务，不改判定（与 T04-00 的 A/B 约定一致）----------
    if group == "B":
        feasible = phase1.get("feasible")
        if not isinstance(feasible, bool):
            obligations.append("B 组判据未走到：Phase 1 可行性未声明（不得读成已成立）")
        elif feasible and float(z2) > float(z1) + tolerances.get("objective_abs", 0.0):
            obligations.append(
                "B 组：Phase 2 目标值优于 Phase 1 解析最优值 → 与最优性矛盾（须核对真实最优值）"
            )

    if mismatches:
        return ParityResult(
            "FAIL", "L2", "Phase 1/2 数值不一致",
            objective_delta, max_delta, None, tuple(mismatches), tuple(obligations), **kwargs,
        )

    # ---- L3：层归属 + 约束残差 -----------------------------------------
    l1, l2 = phase1.get("layers"), phase2.get("layers")
    r1, r2 = phase1.get("residuals"), phase2.get("residuals")
    layer_mismatch = l1 is not None or l2 is not None
    layer_mismatch = layer_mismatch and (l1 != l2)

    residual_delta: float | None = None
    residual_mismatches: list[str] = []
    if (r1 is None) != (r2 is None):
        side = "Phase 2" if r2 is None else "Phase 1"
        return ParityResult(
            "BLOCKED", "L3", f"L3 残差口径不可比：仅 {side} 提供 residuals",
            objective_delta, max_delta, None, tuple(), tuple(obligations), **kwargs,
        )
    if r1 is not None and r2 is not None:
        if not isinstance(r1, Mapping) or not isinstance(r2, Mapping):
            return ParityResult(
                "BLOCKED", "L3", "L3 残差结构不可比（须为 {item_id: 残差}）",
                objective_delta, max_delta, None, tuple(), tuple(obligations), **kwargs,
            )
        if "residual_abs" not in tolerances:
            return ParityResult(
                "BLOCKED", "L3", "L3 容差 residual_abs 未解析（不得静默按默认宽度判）",
                objective_delta, max_delta, None, tuple(), tuple(obligations), **kwargs,
            )
        rids = sorted(set(r1) | set(r2))
        rdeltas = [abs(float(r1[k]) - float(r2[k])) for k in rids if k in r1 and k in r2]
        rmissing = [k for k in rids if k not in r1 or k not in r2]
        residual_delta = max(rdeltas, default=0.0)
        if rmissing:
            residual_mismatches.append("residual ids missing: " + ",".join(rmissing))
        if residual_delta > tolerances["residual_abs"]:
            residual_mismatches.append(
                f"residual delta {residual_delta} > {tolerances['residual_abs']}（residual_abs）"
            )

    if residual_mismatches:
        return ParityResult(
            "FAIL", "L3", "Phase 1/2 约束残差不一致",
            objective_delta, max_delta, residual_delta, tuple(residual_mismatches),
            tuple(obligations), **kwargs,
        )
    if layer_mismatch:
        return ParityResult(
            "WARN", "L3", "报价一致但层归属不一致",
            objective_delta, max_delta, residual_delta, ("layers mismatch",),
            tuple(obligations), **kwargs,
        )
    if l1 is not None or l2 is not None or r1 is not None or r2 is not None:
        return ParityResult(
            "PASS", "L3", "三层对拍一致",
            objective_delta, max_delta, residual_delta, (), tuple(obligations), **kwargs,
        )
    return ParityResult(
        "PASS", "L2", "目标值与报价向量一致",
        objective_delta, max_delta, None, (), tuple(obligations), **kwargs,
    )
