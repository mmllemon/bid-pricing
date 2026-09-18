"""T03-04 约束判定器：对任意候选报价向量 p 逐条判定 C1–C13。

与相邻层的分工（每层只回答一个问题）：

* ``formulation.py``（T04-02A）回答「模型长什么样」；
* ``verifier.py``（T04-02D）回答「**解对不对**」（可行性 / 层归属 / 目标复算）；
* 本模块回答「**解合不合规**」——每约束一个六元组
  ``constraint_id / status / actual / limit / slack / severity``。

三条硬规矩，全部来自已付过学费的失效模式：

1. **只吃原始量**（接口级独立性，ADR-0024 SV-12 同款）：入参是
   :class:`JudgeInputs`——实例、p 向量、可选 z 向量 / Z / floor 表 /
   前载系数表与外生限值。刻意**不收** ``SolveResult``、``Formulation``、
   ``DerivedReport``，使判据可被注入的错误结论否定（否则只能验证
   「实现恰好对」）。
2. **容差具名**（DV-01）：判据只引用容差名，解析不出值 ⇒ BLOCKED。
   代码里不允许出现裸数值容差。C12 的被测量是无量纲比值，与 eps_price
   的「×P*」读法是**两种量纲**，故独立具名 ``eps_ratio``（DV-02）——
   把 eps_price×P* 搬到比值上会把容差放大约 10⁶ 倍，判据静默失效。
3. **未判定必须可见**（规则⑧ / SV-03）：未激活⇒SKIP、缺输入⇒BLOCKED，
   都不得折叠成 PASS。聚合序 FAIL > BLOCKED > WARN > SKIP > PASS；
   空判据集 ⇒ BLOCKED。P1（C11/C12）的 FAIL 不阻塞 P0 主干，
   但必须在报告中可见。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .formulation import compute_lb_c5
from .instance import Phase1Instance, Phase1Item
from ..paths import config_dir

SPEC_FILENAME = "constraint_judge_spec.json"

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_SKIP = "SKIP"

#: 聚合序——最严在前；空判据集 ⇒ BLOCKED（「没判过」不是 PASS）。
STATUS_ORDER: tuple[str, ...] = (
    STATUS_FAIL,
    STATUS_BLOCKED,
    STATUS_WARN,
    STATUS_SKIP,
    STATUS_PASS,
)


class ConstraintJudgeError(ValueError):
    """判定器入参结构不合法。"""


def load_constraint_spec(config_path: Path | None = None) -> dict[str, Any]:
    """``config_path`` 可传目录（自动拼 SPEC_FILENAME）或制品文件路径。"""
    path = config_path if config_path is not None else config_dir()
    if path.is_dir():
        path = path / SPEC_FILENAME
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def severity_by_constraint(spec: Mapping[str, Any]) -> dict[str, str]:
    """从制品取 severity —— **同一约束在各层共用同一个名**（规则⑨）。"""
    out: dict[str, str] = {}
    for j in spec.get("judges", ()):
        cid = j.get("constraint_id")
        sev = j.get("severity")
        if cid and sev:
            out[str(cid)] = str(sev)
    return out


def resolve_tolerances(
    spec: Mapping[str, Any], P_star: float | None
) -> tuple[dict[str, float], tuple[str, ...]]:
    """解析具名容差。返回 ``(已解析表, 缺失名单)``。

    * ``eps_c1_abs`` / ``eps_res`` / ``eps_ratio``：制品直接落值；
    * ``eps_price`` / ``resolution``：同（来源 precision_profile，落值进制品）；
    * ``eps_total``：公式 ``max(eps_abs, eps_price × P*)``——P_star 缺失 ⇒
      该名**不写入**解析表（进缺失名单），依赖它的约束如实 BLOCKED，
      不得拿 0 顶替。
    """
    reg = spec.get("tolerances", {}).get("entries", {})
    resolved: dict[str, float] = {}
    missing: list[str] = []

    def _take(name: str) -> float | None:
        entry = reg.get(name) or {}
        v = entry.get("value")
        return None if v is None else float(v)

    for name in ("eps_c1_abs", "eps_res", "eps_ratio", "eps_price", "resolution"):
        v = _take(name)
        if v is None:
            missing.append(name)
        else:
            resolved[name] = v

    eps_abs = _take("eps_c1_abs")
    eps_price = _take("eps_price")
    if eps_abs is not None and eps_price is not None and P_star is not None:
        resolved["eps_total"] = max(eps_abs, eps_price * P_star)
    else:
        missing.append("eps_total")
    return resolved, tuple(missing)


@dataclass(frozen=True)
class JudgeInputs:
    """判定器的全部输入——**只有原始量**。

    ``p_by_id`` 只需覆盖 X_opt 项；非 X_opt 项在 C12 分子里用其外生固定
    单价 ``p0``。 ``z_by_id`` 是 C7 的二元向量（缺省=未提供 ⇒ C7 至多 WARN）。
    """

    instance: Phase1Instance
    p_by_id: Mapping[str, float]
    z_by_id: Mapping[str, float] | None = None
    Z: float | None = None
    floor_by_id: Mapping[str, float] | None = None
    front_rho: Mapping[str, float] | None = None
    # ---- 外生限值（None = 未声明 ⇒ 对应约束按激活语义处置）------------
    theta: float | None = None
    N_max: float | None = None
    d_max: float | None = None
    Z_min: float | None = None
    pi_target: float | None = None
    R_min: float | None = None
    sigma_max: float | None = None
    kappa_max: float | None = None


@dataclass(frozen=True)
class ConstraintVerdict:
    """单约束六元组 + 理由 + 逐项明细。

    ``slack`` 是有向余量（越大越安全）；SKIP/BLOCKED 时为 ``None``——
    「没有余量」与「没算余量」必须可区分。
    """

    constraint_id: str
    status: str
    actual: Any
    limit: Any
    slack: Any
    severity: str
    reason: str = ""
    rows: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def blocks(self) -> bool:
        return self.status in (STATUS_FAIL, STATUS_BLOCKED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "status": self.status,
            "actual": self.actual,
            "limit": self.limit,
            "slack": self.slack,
            "severity": self.severity,
            "reason": self.reason,
            "rows": list(self.rows),
        }


def _worst(statuses: Sequence[str]) -> str:
    for s in STATUS_ORDER:
        if s in statuses:
            return s
    return STATUS_BLOCKED  # pragma: no cover - 状态域封闭


def _row(item_id: str, status: str, reason: str, **detail: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"item_id": item_id, "status": status, "reason": reason}
    d.update(detail)
    return d


@dataclass(frozen=True)
class ConstraintReport:
    verdicts: tuple[ConstraintVerdict, ...]

    # ---- 便捷视图 -------------------------------------------------------
    def of(self, constraint_id: str) -> ConstraintVerdict | None:
        for v in self.verdicts:
            if v.constraint_id == constraint_id:
                return v
        return None

    def verdict(self) -> str:
        """整体结论 = **P0 约束**的最严状态（P1 的 FAIL 不阻塞 P0 主干）。

        SKIP 不参与「最严」竞争：全部判过且通过的报告必须是 PASS，
        「有约束未激活」不是缺陷——否则任何带未激活项的实例永远到不了
        PASS。全部 P0 均为 SKIP ⇒ 结论 SKIP（「没判过」，仍非 PASS）。
        """
        if not self.verdicts:
            return STATUS_BLOCKED  # 空判据集 ⇒ BLOCKED（「没判过」不是 PASS）
        p0 = [v.status for v in self.verdicts
              if v.severity == "P0" and v.status != STATUS_SKIP]
        if not p0:
            return STATUS_SKIP
        return _worst(p0)

    def verdict_all(self) -> str:
        """含 P1 的整体结论（报告可见性用）。"""
        if not self.verdicts:
            return STATUS_BLOCKED
        judged = [v.status for v in self.verdicts if v.status != STATUS_SKIP]
        if not judged:
            return STATUS_SKIP
        return _worst(judged)

    def blocking(self) -> tuple[ConstraintVerdict, ...]:
        return tuple(v for v in self.verdicts if v.blocks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict(),
            "verdict_all": self.verdict_all(),
            "verdicts": [v.to_dict() for v in self.verdicts],
            "blocking": [v.constraint_id for v in self.blocking()],
        }


# =========================================================================
# 各约束判定（CJ-01..CJ-13，与制品 judges[] 一一对应）
# =========================================================================
def _p_of(inputs: JudgeInputs, item: Phase1Item) -> float | None:
    """候选单价：X_opt 项从 p_by_id 取，缺失返回 None（不得补 0）。"""
    v = inputs.p_by_id.get(item.item_id)
    return None if v is None else float(v)


def judge_c1(inputs: JudgeInputs, tol: Mapping[str, float],
             severity: str) -> ConstraintVerdict:
    """CJ-01：Σ_{i∈C1_scope} p_i·q0_i == B（P*_competitive）。"""
    inst = inputs.instance
    B = inst.B
    if B is None:
        return ConstraintVerdict("C1", STATUS_BLOCKED, None, None, None, severity,
                                 "缺 B=P*_competitive——右端唯一提供者 "
                                 "total_price.compute_P_competitive 未落值")
    eps = tol.get("eps_c1_abs")
    if eps is None:
        return ConstraintVerdict("C1", STATUS_BLOCKED, None, B, None, severity,
                                 "容差 eps_c1_abs 未解析")
    actual = 0.0
    rows = []
    for it in inst.c1_scope_items:
        p = _p_of(inputs, it)
        if p is None or it.q0 is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED,
                             "C1 作用域内缺 p 或 q0（缺数据，不得补 0）"))
            continue
        actual += p * it.q0
    if any(r["status"] == STATUS_BLOCKED for r in rows):
        return ConstraintVerdict("C1", STATUS_BLOCKED, None, B, None, severity,
                                 "作用域内存在缺数据的项", rows=tuple(rows))
    slack = B - actual
    status = STATUS_PASS if abs(slack) <= eps else STATUS_FAIL
    return ConstraintVerdict(
        "C1", status, actual, B, slack, severity,
        "可竞争部分总价与 P*_competitive 的偏差（外层舍入调和口径）",
        rows=tuple(rows))


def _box_verdict(cid: str, severity: str, rows: list[dict[str, Any]],
                 margins: list[tuple[str, float, float]],
                 *, upper: bool, what: str) -> ConstraintVerdict:
    """C2/C3/C4 共用的箱型判定骨架。

    ``margins`` 是 (item_id, p, bound) 三元组；``upper=True`` 判 p ≤ bound。
    金额精确比较，不用容差——0.005 元的越界在报价表里同样是越界。
    """
    statuses = [r["status"] for r in rows]
    if STATUS_FAIL in statuses:
        bad = next(r for r in rows if r["status"] == STATUS_FAIL)
        return ConstraintVerdict(cid, STATUS_FAIL, bad.get("p"), bad.get("bound"),
                                 bad.get("slack"), severity,
                                 f"存在违反项（{what}）", rows=tuple(rows))
    if STATUS_BLOCKED in statuses:
        return ConstraintVerdict(cid, STATUS_BLOCKED, None, None, None, severity,
                                 f"存在缺数据的项（{what}）", rows=tuple(rows))
    judged = [(i, p, b) for (i, p, b) in margins]
    if not judged:
        return ConstraintVerdict(cid, STATUS_SKIP, None, None, None, severity,
                                 f"作用域为空，未判定（{what}）", rows=tuple(rows))
    if upper:
        worst = min(judged, key=lambda t: t[2] - t[1])
        slack = worst[2] - worst[1]
    else:
        worst = min(judged, key=lambda t: t[1] - t[2])
        slack = worst[1] - worst[2]
    return ConstraintVerdict(cid, STATUS_PASS, worst[1], worst[2], slack, severity,
                             f"全部通过（最紧项 {worst[0]}；{what}）",
                             rows=tuple(rows))


def judge_c2(inputs: JudgeInputs, severity: str) -> ConstraintVerdict:
    """CJ-02：p_i ≤ U_i for i∈N_cap；空 cap ⇒ 该项 SKIP（不限价 ≠ 0）。"""
    rows: list[dict[str, Any]] = []
    margins: list[tuple[str, float, float]] = []
    for it in inputs.instance.opt_items:
        if it.cap is None and it.U is None:
            rows.append(_row(it.item_id, STATUS_SKIP,
                             "不限价（ALLOW_EMPTY_NO_CAP 合法语义，不参与判定）"))
            continue
        p = _p_of(inputs, it)
        if p is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED, "缺 p"))
            continue
        if it.U is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED,
                             "cap 非空但派生量层未给出 U（缺口，不得折 0）",
                             cap=it.cap))
            continue
        slack = it.U - p
        ok = slack >= 0.0
        rows.append(_row(it.item_id, STATUS_PASS if ok else STATUS_FAIL,
                         "" if ok else "p > U", p=p, bound=it.U, slack=slack))
        margins.append((it.item_id, p, it.U))
    return _box_verdict("C2", severity, rows, margins, upper=True,
                        what="限价上界 U_i")


def judge_c3(inputs: JudgeInputs, severity: str) -> ConstraintVerdict:
    """CJ-03：p_i ≥ L_i；L 缺失 ⇒ BLOCKED（多来源取大的结果缺失=缺口）。"""
    rows: list[dict[str, Any]] = []
    margins: list[tuple[str, float, float]] = []
    for it in inputs.instance.opt_items:
        p = _p_of(inputs, it)
        if p is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED, "缺 p"))
            continue
        if it.L is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED,
                             "L 缺失（多来源取大未落值，不得补 0）"))
            continue
        slack = p - it.L
        ok = slack >= 0.0
        rows.append(_row(it.item_id, STATUS_PASS if ok else STATUS_FAIL,
                         "" if ok else "p < L", p=p, bound=it.L, slack=slack))
        margins.append((it.item_id, p, it.L))
    return _box_verdict("C3", severity, rows, margins, upper=False,
                        what="招标下界 L_i")


def judge_c4(inputs: JudgeInputs, severity: str) -> ConstraintVerdict:
    """CJ-04：p_i ≥ floor_i；floor 缺失 ⇒ BLOCKED（μ 未落值 OI-DQ-A 可见化）。"""
    floor_by_id = inputs.floor_by_id or {}
    rows: list[dict[str, Any]] = []
    margins: list[tuple[str, float, float]] = []
    for it in inputs.instance.opt_items:
        p = _p_of(inputs, it)
        if p is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED, "缺 p"))
            continue
        fl = floor_by_id.get(it.item_id)
        if fl is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED,
                             "floor 缺失（μ 未落值 OI-DQ-A 或条款无基准——"
                             "T03-02 是唯一实现，本层不重算）"))
            continue
        slack = p - fl
        ok = slack >= 0.0
        rows.append(_row(it.item_id, STATUS_PASS if ok else STATUS_FAIL,
                         "" if ok else "p < floor（成本地板击穿）",
                         p=p, bound=fl, slack=slack))
        margins.append((it.item_id, p, fl))
    return _box_verdict("C4", severity, rows, margins, upper=False,
                        what="成本地板 floor_i")


def judge_c5(inputs: JudgeInputs, tol: Mapping[str, float],
             severity: str) -> ConstraintVerdict:
    """CJ-05：p_i ≥ lb_C5 = max(eps_price×P*, resolution)（唯一实现复用）。"""
    P_star = inputs.instance.P_star
    eps_price = tol.get("eps_price")
    resolution = tol.get("resolution")
    if P_star is None or eps_price is None or resolution is None:
        return ConstraintVerdict("C5", STATUS_BLOCKED, None, None, None, severity,
                                 "P_star / eps_price / resolution 缺一即无法定下界")
    lb = compute_lb_c5(P_star, eps_price, resolution)
    rows: list[dict[str, Any]] = []
    margins: list[tuple[str, float, float]] = []
    for it in inputs.instance.opt_items:
        p = _p_of(inputs, it)
        if p is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED, "缺 p"))
            continue
        slack = p - lb
        ok = slack >= 0.0
        rows.append(_row(it.item_id, STATUS_PASS if ok else STATUS_FAIL,
                         "" if ok else "p < lb_C5（舍入后将变成 0.00）",
                         p=p, bound=lb, slack=slack))
        margins.append((it.item_id, p, lb))
    v = _box_verdict("C5", severity, rows, margins, upper=False,
                     what="最小可表示报价 lb_C5")
    if v.status == STATUS_PASS:
        v = ConstraintVerdict(v.constraint_id, v.status, v.actual, lb, v.slack,
                              v.severity, v.reason + f"；lb_C5={lb:.4g}",
                              v.rows)
    return v


def judge_c6(inputs: JudgeInputs, tol: Mapping[str, float],
             severity: str) -> ConstraintVerdict:
    """CJ-06：Σ max(c_i−p_i,0)·q1_i ≤ θ·P*（缺口按结算量加权）。"""
    inst = inputs.instance
    if "C6" not in inst.active_soft_constraints:
        return ConstraintVerdict("C6", STATUS_SKIP, None, None, None, severity,
                                 "未激活（active_soft_constraints 未声明）")
    theta = inputs.theta if inputs.theta is not None else inst.params.theta
    P_star = inst.P_star
    eps = tol.get("eps_total")
    if theta is None or P_star is None or eps is None:
        return ConstraintVerdict("C6", STATUS_BLOCKED, None, None, None, severity,
                                 "激活但 theta / P_star / eps_total 缺失")
    actual = 0.0
    rows = []
    for it in inst.opt_items:
        p = _p_of(inputs, it)
        if p is None or it.c_i is None or it.q1_point is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED, "缺 p / c_i / q1"))
            continue
        s = max(it.c_i - p, 0.0)
        actual += s * it.q1_point
        if s > 0:
            rows.append(_row(it.item_id, STATUS_PASS, f"亏损缺口 s={s:.4g}",
                             gap=s * it.q1_point))
    limit = theta * P_star
    slack = limit - actual
    status = STATUS_PASS if slack >= -eps else STATUS_FAIL
    return ConstraintVerdict("C6", status, actual, limit, slack, severity,
                             "亏损风险总量（结算量 q1 加权；用 q0 会按投标口径"
                             "低估 r<1 项的风险）", rows=tuple(rows))


def judge_c7(inputs: JudgeInputs, tol: Mapping[str, float],
             severity: str) -> ConstraintVerdict:
    """CJ-07：实际亏损项数 ≤ N_max；z 一致性双向核查（虚报与漏报都抓）。"""
    inst = inputs.instance
    if "C7" not in inst.active_soft_constraints:
        return ConstraintVerdict("C7", STATUS_SKIP, None, None, None, severity,
                                 "未激活（active_soft_constraints 未声明）")
    N_max = inputs.N_max
    if N_max is None:
        return ConstraintVerdict("C7", STATUS_BLOCKED, None, None, None, severity,
                                 "激活但 N_max 未声明")
    eps_res = tol.get("eps_res")
    rows = []
    losses = 0
    z_fail = False
    z_fail_reason = ""
    z_seen = False
    for it in inst.opt_items:
        p = _p_of(inputs, it)
        if p is None or it.c_i is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED, "缺 p / c_i"))
            continue
        loss = p < it.c_i
        if loss:
            losses += 1
        z = None
        if inputs.z_by_id is not None and it.item_id in inputs.z_by_id:
            z_seen = True
            z = float(inputs.z_by_id[it.item_id])
        if z is None:
            rows.append(_row(it.item_id, STATUS_PASS,
                             f"实际{'亏损' if loss else '未亏损'}（无 z，未核自称口径）",
                             p=p, c_i=it.c_i, loss=loss))
            continue
        if eps_res is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED, "容差 eps_res 未解析"))
            continue
        if z == 1 and p > it.c_i - eps_res:
            z_fail = True
            z_fail_reason = (f"{it.item_id}：z=1 但 p > c_i−eps_res——虚报亏损"
                             "（z 只许『允许』，不许无亏损也报 1）")
            rows.append(_row(it.item_id, STATUS_FAIL,
                             "z=1 但 p > c_i−eps_res：虚报亏损",
                             p=p, c_i=it.c_i, z=z))
        elif z == 0 and loss:
            z_fail = True
            z_fail_reason = f"{it.item_id}：z=0 但 p < c_i——漏报亏损"
            rows.append(_row(it.item_id, STATUS_FAIL,
                             "z=0 但 p < c_i：漏报亏损（双向核查的第二向）",
                             p=p, c_i=it.c_i, z=z))
        else:
            rows.append(_row(it.item_id, STATUS_PASS, "z 与事实一致",
                             p=p, c_i=it.c_i, z=z, loss=loss))
    blocked = any(r["status"] == STATUS_BLOCKED for r in rows)
    if blocked:
        return ConstraintVerdict("C7", STATUS_BLOCKED, None, N_max, None, severity,
                                 "存在缺数据的项", rows=tuple(rows))
    if z_fail:
        return ConstraintVerdict("C7", STATUS_FAIL, losses, N_max,
                                 N_max - losses, severity,
                                 z_fail_reason or "z 向量与实际亏损不一致",
                                 rows=tuple(rows))
    if losses > N_max:
        return ConstraintVerdict("C7", STATUS_FAIL, losses, N_max,
                                 N_max - losses, severity,
                                 "实际亏损项数超限", rows=tuple(rows))
    if not z_seen:
        return ConstraintVerdict("C7", STATUS_WARN, losses, N_max,
                                 N_max - losses, severity,
                                 "亏损项数未超限，但未提供 z 向量——自称亏损口径"
                                 "未核（z=1 只表示允许亏损，不表示确实亏损）",
                                 rows=tuple(rows))
    return ConstraintVerdict("C7", STATUS_PASS, losses, N_max, N_max - losses,
                             severity, "亏损项数与 z 向量一致且未超限",
                             rows=tuple(rows))


def judge_c8(inputs: JudgeInputs, severity: str) -> ConstraintVerdict:
    """CJ-08：p_i ≥ c_i·(1−d_max)；c_i=0 项 SKIP（退化由 C5 承担）。"""
    inst = inputs.instance
    if "C8" not in inst.active_soft_constraints:
        return ConstraintVerdict("C8", STATUS_SKIP, None, None, None, severity,
                                 "未激活（active_soft_constraints 未声明）")
    d_max = inputs.d_max
    if d_max is None:
        return ConstraintVerdict("C8", STATUS_BLOCKED, None, None, None, severity,
                                 "激活但 d_max 未声明")
    rows: list[dict[str, Any]] = []
    margins: list[tuple[str, float, float]] = []
    for it in inst.opt_items:
        p = _p_of(inputs, it)
        if p is None or it.c_i is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED, "缺 p / c_i"))
            continue
        if it.c_i == 0:
            rows.append(_row(it.item_id, STATUS_SKIP,
                             "c_i=0 退化为 p≥0，由 C5 的 lb_C5 承担"))
            continue
        bound = it.c_i * (1.0 - d_max)
        slack = p - bound
        ok = slack >= 0.0
        rows.append(_row(it.item_id, STATUS_PASS if ok else STATUS_FAIL,
                         "" if ok else "p < c_i·(1−d_max)",
                         p=p, bound=bound, slack=slack))
        margins.append((it.item_id, p, bound))
    return _box_verdict("C8", severity, rows, margins, upper=False,
                        what="最大降幅界 c_i·(1−d_max)")


def judge_c9(inputs: JudgeInputs, tol: Mapping[str, float],
             severity: str) -> ConstraintVerdict:
    """CJ-09：Z ≥ max(Z_min, pi_target·Σc_i·q1_i)；Z 由调用方复算后传入。"""
    inst = inputs.instance
    if "C9" not in inst.active_soft_constraints:
        return ConstraintVerdict("C9", STATUS_SKIP, None, None, None, severity,
                                 "未激活（active_soft_constraints 未声明）")
    Z = inputs.Z
    if Z is None:
        return ConstraintVerdict("C9", STATUS_BLOCKED, None, None, None, severity,
                                 "激活但 Z 缺失（须由唯一收入实现复算后传入，"
                                 "本层不重实现 R_i）")
    eps = tol.get("eps_total")
    if eps is None:
        return ConstraintVerdict("C9", STATUS_BLOCKED, None, None, None, severity,
                                 "容差 eps_total 未解析（通常因 P_star 缺失）")
    limits: list[float] = []
    notes: list[str] = []
    if inputs.Z_min is not None:
        limits.append(float(inputs.Z_min))
        notes.append(f"Z_min={inputs.Z_min:.4g}")
    if inputs.pi_target is not None:
        denom = 0.0
        ok = True
        for it in inst.opt_items:
            if it.c_i is None or it.q1_point is None:
                ok = False
                break
            denom += it.c_i * it.q1_point
        if not ok:
            return ConstraintVerdict("C9", STATUS_BLOCKED, Z, None, None, severity,
                                     "pi_target 激活但存在缺 c_i/q1 的项")
        limits.append(float(inputs.pi_target) * denom)
        notes.append(f"pi_target·Σc·q1={inputs.pi_target:.4g}·{denom:.4g}")
    if not limits:
        return ConstraintVerdict("C9", STATUS_BLOCKED, Z, None, None, severity,
                                 "激活但 Z_min 与 pi_target 均未声明")
    limit = max(limits)
    slack = Z - limit
    status = STATUS_PASS if slack >= -eps else STATUS_FAIL
    return ConstraintVerdict("C9", status, Z, limit, slack, severity,
                             "利润下界（" + "；".join(notes) + "）")


def judge_c10(inputs: JudgeInputs, tol: Mapping[str, float],
              severity: str) -> ConstraintVerdict:
    """CJ-10：Σ_{i∈T_front}(rho_i·p_i−c_i)·q0_i ≥ 0（投标口径 q0）。"""
    inst = inputs.instance
    front = inputs.front_rho or {}
    if not front:
        return ConstraintVerdict("C10", STATUS_SKIP, None, None, None, severity,
                                 "T_front 未声明（付款条款外生给定，沉默≠断言）")
    eps = tol.get("eps_total")
    if eps is None:
        return ConstraintVerdict("C10", STATUS_BLOCKED, None, None, None, severity,
                                 "容差 eps_total 未解析（通常因 P_star 缺失）")
    by_id = {it.item_id: it for it in inst.items}
    actual = 0.0
    rows = []
    for iid, rho in front.items():
        it = by_id.get(iid)
        if it is None:
            rows.append(_row(iid, STATUS_BLOCKED, "T_front 声明了不存在的项"))
            continue
        p = _p_of(inputs, it) if it.is_optimizable else it.p0
        if p is None or it.c_i is None or it.q0 is None:
            rows.append(_row(iid, STATUS_BLOCKED, "缺 p / c_i / q0"))
            continue
        actual += (float(rho) * p - it.c_i) * it.q0
        rows.append(_row(iid, STATUS_PASS,
                         f"前载贡献 (rho·p−c)·q0={(float(rho) * p - it.c_i) * it.q0:.4g}",
                         rho=float(rho)))
    if any(r["status"] == STATUS_BLOCKED for r in rows):
        return ConstraintVerdict("C10", STATUS_BLOCKED, None, 0, None, severity,
                                 "前载项存在缺数据的项", rows=tuple(rows))
    slack = actual
    status = STATUS_PASS if actual >= -eps else STATUS_FAIL
    return ConstraintVerdict("C10", status, actual, 0, slack, severity,
                             "前载集合收款−成本投入（按投标口径 q0；用 q1 是"
                             "量纲混用——进度款按清单工程量计价）", rows=tuple(rows))


def judge_c11(inputs: JudgeInputs, severity: str) -> ConstraintVerdict:
    """CJ-11：σ(d) ≤ sigma_max（DISCRETE_CHECK；MAD 已被否决不得静默替换）。"""
    sigma_max = inputs.sigma_max
    kappa_max = inputs.kappa_max
    if sigma_max is None and kappa_max is None:
        return ConstraintVerdict("C11", STATUS_SKIP, None, None, None, severity,
                                 "NOT_ACTIVE（sigma_max / kappa_max 均未声明）")
    if sigma_max is None:
        return ConstraintVerdict("C11", STATUS_BLOCKED, None, None, None, severity,
                                 "仅给 kappa_max：MAD 形式已被 lp_formulation_spec "
                                 "否决（同中心 Cauchy-Schwarz ⇒ MAD ≤ σ，最坏放松"
                                 " √n 倍，是方向性错误）——不得静默替换判据")
    ds: list[float] = []
    rows = []
    for it in inputs.instance.opt_items:
        p = _p_of(inputs, it)
        if p is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED, "缺 p"))
            continue
        if it.cap is None:
            rows.append(_row(it.item_id, STATUS_SKIP,
                             "cap 空 ⇒ 无归一化基准，从 d 统计剔除（不折 0、"
                             "不编造基准）"))
            continue
        if it.cap == 0:
            rows.append(_row(it.item_id, STATUS_BLOCKED, "cap=0 不能作归一化基准"))
            continue
        ds.append((p - it.cap) / it.cap)
        rows.append(_row(it.item_id, STATUS_PASS, f"d={ds[-1]:.4g}"))
    if any(r["status"] == STATUS_BLOCKED for r in rows):
        return ConstraintVerdict("C11", STATUS_BLOCKED, None, sigma_max, None,
                                 severity, "存在缺数据的项", rows=tuple(rows))
    if not ds:
        return ConstraintVerdict("C11", STATUS_SKIP, None, sigma_max, None,
                                 severity, "无可统计项（全部不限价）", rows=tuple(rows))
    sigma = math.sqrt(sum(d * d for d in ds) / len(ds))
    slack = sigma_max - sigma
    status = STATUS_PASS if slack >= 0.0 else STATUS_FAIL
    return ConstraintVerdict("C11", status, sigma, sigma_max, slack, severity,
                             "偏离度 σ(d)（中心 0、基准 cap，OI-05）",
                             rows=tuple(rows))


def judge_c12(inputs: JudgeInputs, tol: Mapping[str, float],
              severity: str) -> ConstraintVerdict:
    """CJ-12：R_pc ≥ R_min − eps_ratio（前置可接受性判据，非 LP 约束）。"""
    R_min = inputs.R_min
    if R_min is None:
        return ConstraintVerdict("C12", STATUS_SKIP, None, None, None, severity,
                                 "NOT_ACTIVE（R_min 未声明）")
    eps = tol.get("eps_ratio")
    if eps is None:
        return ConstraintVerdict("C12", STATUS_BLOCKED, None, R_min, None, severity,
                                 "容差 eps_ratio 未解析（比值上的绝对容差——"
                                 "禁止引用 eps_price×P*，DV-02）")
    inst = inputs.instance
    num = 0.0
    den = 0.0
    rows = []
    for it in inst.items:
        if it.c_i is None or it.q0 is None:
            rows.append(_row(it.item_id, STATUS_BLOCKED, "缺 c_i / q0"))
            continue
        if it.is_optimizable:
            p = _p_of(inputs, it)
            if p is None:
                rows.append(_row(it.item_id, STATUS_BLOCKED, "缺 p"))
                continue
        else:
            p = it.p0
            if p is None:
                rows.append(_row(it.item_id, STATUS_BLOCKED,
                                 "非 X_opt 项缺外生固定单价 p0"))
                continue
        num += p * it.q0
        den += it.c_i * it.q0
    if any(r["status"] == STATUS_BLOCKED for r in rows):
        return ConstraintVerdict("C12", STATUS_BLOCKED, None, R_min, None, severity,
                                 "存在缺数据的项", rows=tuple(rows))
    if den <= 0:
        return ConstraintVerdict("C12", STATUS_BLOCKED, None, R_min, None, severity,
                                 "分母 Σc·q0 ≤ 0，R_pc 无定义", rows=tuple(rows))
    r_pc = num / den
    slack = r_pc - R_min
    status = STATUS_PASS if slack >= -eps else STATUS_FAIL
    reason = ("成本回收率（全部项口径：X_opt 用候选 p，非 X_opt 用外生固定价；"
              "两种作用域读法在 C1 可行域上同值）。FAIL 的语义是『P* 不可接受』，"
              "不是求解器 infeasible")
    return ConstraintVerdict("C12", status, r_pc, R_min, slack, severity, reason,
                             rows=tuple(rows))


def judge_c13(severity: str) -> ConstraintVerdict:
    """CJ-13：恒 SKIP——结算期条件修正，投标期不可知。"""
    return ConstraintVerdict(
        "C13", STATUS_SKIP, None, None, None, severity,
        "机制=SETTLEMENT_ADJUSTMENT：偏高侧死分支（C2 保证 p≤cap），偏低侧触发"
        "条件含结算期工程量事实，投标期不可知——写成投标约束即『用不可知的"
        "信息定价』（ADR-0007 同类失效）。正确位置=结算修正模拟（待 OI-06）")


def judge_constraints(
    inputs: JudgeInputs,
    *,
    spec: Mapping[str, Any] | None = None,
) -> ConstraintReport:
    """对候选 p 向量逐条判定 C1–C13，返回六元组报告。"""
    spec = spec if spec is not None else load_constraint_spec()
    sev = severity_by_constraint(spec)
    tol, _missing = resolve_tolerances(spec, inputs.instance.P_star)

    def _sev(cid: str) -> str:
        return sev.get(cid, "P0")

    verdicts = (
        judge_c1(inputs, tol, _sev("C1")),
        judge_c2(inputs, _sev("C2")),
        judge_c3(inputs, _sev("C3")),
        judge_c4(inputs, _sev("C4")),
        judge_c5(inputs, tol, _sev("C5")),
        judge_c6(inputs, tol, _sev("C6")),
        judge_c7(inputs, tol, _sev("C7")),
        judge_c8(inputs, _sev("C8")),
        judge_c9(inputs, tol, _sev("C9")),
        judge_c10(inputs, tol, _sev("C10")),
        judge_c11(inputs, _sev("C11")),
        judge_c12(inputs, tol, _sev("C12")),
        judge_c13(_sev("C13")),
    )
    return ConstraintReport(verdicts=verdicts)
