"""T03-05 判定层测试矩阵：边界 × 约束笛卡尔积 + 变异体存活审计。

与相邻层的分工（每层只回答一个问题）：

* ``solver/constraint_judge.py``（T03-04）回答「给定候选 p，解合不合规」；
* 本模块回答「**那套判据判得对不对**」——它不新增判据，只**枚举**判据的
  边界格、并在替身（变异体）上检验判据的鉴别力。

三条硬规矩，全部来自已付过学费的失效模式：

1. **覆盖面不取决于被测数据**（ADR-0020 规则⑧）：用例集是
   ``13 约束 × 6 边界类 = 78 格`` 的笛卡尔积，由制品
   ``config/judgment_test_matrix_spec.json`` 声明。换一批项目数据，格数不变。
   空格必须被**显式声明**为 NOT_APPLICABLE 并给出理由——
   「沉默不是断言」（ADR-0007），未声明的空格 ⇒ 覆盖审计 BLOCKED。
2. **判据不得自证**（规则⑥）：矩阵通过 ``judge_fn(inputs, spec)``
   **参数化**被测判定器。真实实现与 19 条变异体走同一条用例生成路径；
   存活（没有任何探针杀掉）的变异体 ⇒ 判据存在盲区 ⇒ FAIL。
   这样「矩阵有鉴别力」与「实现正确」成两个可独立否证的命题。
3. **『1 个单位』必须具名**（规则⑨ / DV-02 同族）：对金额箱型是 0.01 元、
   对项数是 1 项、对无量纲偏离度是另一个量。制品逐约束绑定具名单位
   （``unit_binding``），用例里不出现裸数值。

浮点边界的处理（规格 ``exact_boundary_policy``）：容差类判据的
「恰好等于边界」格取**边界内侧 ``tol × 1e-3``** 处。理由：若取 ±0，
比较结果由 IEEE754 末位随机决定（``B - actual`` 的误差约 ulp(量级)），
该格测的就不再是判据方向而是舍入噪声；取 1e-3 个容差宽度使绝对裕度
比噪声高约 7 个数量级。箱型约束不受此影响——它们的边界是精确可表示的
十进制值，EXACT 格为真·相等（``p == U``）。
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..paths import config_dir
from ..solver.constraint_judge import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    JudgeInputs,
    ConstraintReport,
    judge_constraints,
)
from ..solver.instance import (
    Phase1Instance,
    Phase1Item,
    Phase1Params,
    ROLE_NON_COMPETITIVE,
)

SPEC_FILENAME = "judgment_test_matrix_spec.json"

CLASS_NOMINAL = "NOMINAL"
CLASS_NOT_ACTIVE = "NOT_ACTIVE"
CLASS_MISSING_INPUT = "MISSING_INPUT"
CLASS_OUT_OF_RANGE = "OUT_OF_RANGE"
CLASS_EXACT_BOUNDARY = "EXACT_BOUNDARY"
CLASS_BOUNDARY_PLUS_1 = "BOUNDARY_PLUS_1"

#: 容差类判据「恰好等于边界」格的内侧偏移比例（见模块 docstring）。
EXACT_INNER_FRAC = 1e-3

#: 四个具名单位的**探针侧**取值（制品 unit_binding 引用的名字 → 数值）。
#: ``tol_width`` 逐约束取该约束自己的容差，故不在此表。
UNIT_VALUES: dict[str, float] = {
    "res": 0.01,
    "count": 1.0,
    "sigma_step": 1e-6,
}

#: C1..C13 的具名容差名（供 ``tol_width`` 解析；制品 tolerances.entries 是唯一来源）。
TOL_NAMES_FOR_CONSTRAINT: dict[str, str] = {
    "C1": "eps_c1_abs",
    "C6": "eps_total",
    "C9": "eps_total",
    "C10": "eps_total",
    "C12": "eps_ratio",
}

# ---------------------------------------------------------------- 基础夹具
A_ITEM = Phase1Item(item_id="A", q0=1000.0, q1_point=900.0, c_i=400.0,
                    p0=500.0, cap=600.0, L=350.0, U=600.0)
B_ITEM = Phase1Item(item_id="B", q0=500.0, q1_point=500.0, c_i=300.0,
                    p0=400.0, cap=450.0, L=250.0, U=450.0)
F_ITEM = Phase1Item(item_id="F", q0=100.0, q1_point=100.0, c_i=200.0,
                    p0=250.0, cap=None, L=100.0, U=None)
N_ITEM = Phase1Item(item_id="N", role=ROLE_NON_COMPETITIVE, in_c1_scope=False,
                    q0=50.0, q1_point=50.0, c_i=100.0, p0=300.0)

#: 基准 p：C1 分子 = 500×1000 + 400×500 + 250×100 = 725000 = B（可逐项复算）。
BASE_P = {"A": 500.0, "B": 400.0, "F": 250.0}
BASE_FLOOR = {"A": 360.0, "B": 270.0, "F": 180.0}
BASE_B = 725_000.0
BASE_P_STAR = 800_000.0


def _base_items() -> tuple[Phase1Item, ...]:
    return (A_ITEM, B_ITEM, F_ITEM, N_ITEM)


def _inst(items: Sequence[Phase1Item] | None = None, *,
          B: float | None = BASE_B, P_star: float | None = BASE_P_STAR,
          active: Sequence[str] = (), theta: float | None = None,
          ) -> Phase1Instance:
    return Phase1Instance(
        items=tuple(_base_items() if items is None else items),
        B=B, P_star=P_star,
        active_soft_constraints=tuple(active),
        params=Phase1Params(theta=theta),
    )


def _p(**over: Any) -> dict[str, float]:
    d = dict(BASE_P)
    d.update(over)
    return d


def _without(key: str) -> dict[str, float]:
    d = dict(BASE_P)
    d.pop(key, None)
    return d


# =========================================================================
# 数据结构
# =========================================================================
@dataclass(frozen=True)
class Probe:
    """一格里的一个探针。

    ``expected`` 是**期望状态**（由制品语义推导，不由被测实现的输出决定）。
    ``spec_tweak`` 支持 'drop_tol:<name>'——删除某具名容差，用于证明
    「容差解析不出值 ⇒ BLOCKED」（DV-01 失效模式）。
    ``rows_expect`` 断言明细行状态（``(item_id, status)`` 对），用于钉住
    「该 SKIP 的子项必须真的 SKIP」这类**只在明细里可见**的语义。
    """

    probe_id: str
    constraint_id: str
    expected: str
    instance: Phase1Instance
    p_by_id: Mapping[str, float]
    note: str = ""
    spec_tweak: str | None = None
    rows_expect: tuple[tuple[str, str], ...] = ()
    kwargs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatrixCase:
    case_id: str
    constraint_id: str
    boundary_class: str
    applicable: bool
    probes: tuple[Probe, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ProbeResult:
    probe_id: str
    expected: str
    actual: str
    matched: bool
    detail: str = ""


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    applicable: bool
    results: tuple[ProbeResult, ...]
    reason: str = ""

    @property
    def matched(self) -> bool:
        return all(r.matched for r in self.results)

    @property
    def status(self) -> str:
        if not self.applicable:
            return STATUS_SKIP
        if not self.results:
            return STATUS_BLOCKED      # 有用例却零探针 ⇒ 「没判过」
        return STATUS_PASS if self.matched else STATUS_FAIL


def _probe(pid: str, cid: str, expected: str, instance: Phase1Instance,
           p_by_id: Mapping[str, float], *, note: str = "",
           spec_tweak: str | None = None,
           rows_expect: Sequence[tuple[str, str]] = (),
           **kw: Any) -> Probe:
    return Probe(probe_id=pid, constraint_id=cid, expected=expected,
                 instance=instance, p_by_id=dict(p_by_id), note=note,
                 spec_tweak=spec_tweak, rows_expect=tuple(rows_expect),
                 kwargs=dict(kw))


# =========================================================================
# 13 个约束 × 6 类边界：探针构造器
# =========================================================================
def _inner(tol: float) -> float:
    """「恰好等于边界」格的内侧偏移量（从恰好触界点向合法侧）。"""
    return abs(tol) * EXACT_INNER_FRAC


def _p1_c1() -> dict[str, list[Probe]]:
    """C1：Σ_{c1_scope} p·q0 == B，容差 eps_c1_abs（恒激活）。"""
    eps = 0.01            # eps_c1_abs（precision_profile.eps_abs）
    q0a = 1000.0

    def shifted(total_delta: float) -> dict[str, float]:
        """把总价偏移 total_delta（正=actual 偏大 ⇒ slack 为负）。"""
        return _p(A=500.0 + total_delta / q0a)

    return {
        CLASS_NOMINAL: [_probe("C1/NOMINAL", "C1", STATUS_PASS, _inst(), _p(),
                               note="基准报价：分子恰等于 B")],
        CLASS_NOT_ACTIVE: [],
        CLASS_MISSING_INPUT: [
            _probe("C1/MISSING_INPUT#no-B", "C1", STATUS_BLOCKED,
                   _inst(B=None), _p(),
                   note="B=P*_competitive 缺失——右端唯一提供者未落值，不是 SKIP"),
            _probe("C1/MISSING_INPUT#no-p", "C1", STATUS_BLOCKED,
                   _inst(), _without("A"), note="作用域内缺候选单价，不得补 0"),
            _probe("C1/MISSING_INPUT#unresolvable-tol", "C1", STATUS_BLOCKED,
                   _inst(), _p(), spec_tweak="drop_tol:eps_c1_abs",
                   note="容差名解析不出值 ⇒ BLOCKED（DV-01 失效模式）"),
        ],
        CLASS_OUT_OF_RANGE: [
            _probe("C1/OUT_OF_RANGE", "C1", STATUS_FAIL,
                   _inst(), shifted(eps * 11.0),
                   note="越过可容忍偏差 10 个单位（1 单位 = 1 个 eps_c1_abs）"),
        ],
        CLASS_EXACT_BOUNDARY: [
            _probe("C1/EXACT_BOUNDARY", "C1", STATUS_PASS,
                   _inst(), shifted(eps - _inner(eps)),
                   note="|slack| 恰好位于容差内侧 0.1%——判据用 <= 而非 <"),
        ],
        CLASS_BOUNDARY_PLUS_1: [
            _probe("C1/BOUNDARY_PLUS_1", "C1", STATUS_FAIL,
                   _inst(), shifted(eps * 2.0),
                   note="越过可容忍偏差恰好 1 个单位 ⇒ 必须 FAIL"),
        ],
    }


def _box(cls_id: str, *, bound_kind: str, upper: bool,
         ) -> dict[str, list[Probe]]:
    """箱型约束（C2/C3/C4/C5/C8）共用的探针骨架。

    ``upper=True`` 判 ``p ≤ bound``（上界）；否则判 ``p ≥ bound``（下界）。
    箱型比较是**金额精确比较**：恰好相等 ⇒ PASS（十进制值相等可精确表示）。
    """
    res = UNIT_VALUES["res"]
    if bound_kind == "U":
        bound_a = A_ITEM.U           # 600.0
        make_inst = lambda: _inst()  # noqa: E731
        item_field = "U"
    elif bound_kind == "L":
        bound_a = A_ITEM.L           # 350.0
        make_inst = lambda: _inst()  # noqa: E731
        item_field = "L"
    elif bound_kind == "floor":
        bound_a = BASE_FLOOR["A"]    # 360.0
        make_inst = lambda: _inst()  # noqa: E731
        item_field = "floor"
    elif bound_kind == "lb_c5":
        bound_a = max(1e-9 * BASE_P_STAR, res)   # 0.01
        make_inst = lambda: _inst()              # noqa: E731
        item_field = "lb_C5"
    elif bound_kind == "c8":
        bound_a = A_ITEM.c_i * (1.0 - 0.2)       # d_max = 0.2 ⇒ 320.0
        make_inst = lambda: _inst(active=("C8",))  # noqa: E731
        item_field = "c_i*(1-d_max)"
    else:  # pragma: no cover - 封闭枚举
        raise ValueError(bound_kind)

    def price_at(bound: float) -> dict[str, float]:
        """把 A 的单价放到给定 bound 上。"""
        return _p(A=bound)

    kwargs_common: dict[str, Any] = {}
    if bound_kind == "floor":
        kwargs_common["floor_by_id"] = dict(BASE_FLOOR)
    if bound_kind == "c8":
        kwargs_common["d_max"] = 0.2

    def off(units: float, scale: float) -> dict[str, float]:
        """从恰好触界点向**不合法侧**偏移 units 个单位。"""
        if upper:      # 上界：p 变大才违反
            return price_at(bound_a + units * scale)
        # 下界：p 变小才违反
        return price_at(bound_a - units * scale)

    probes: dict[str, list[Probe]] = {
        CLASS_NOMINAL: [
            _probe(f"{cls_id}/NOMINAL", cls_id, STATUS_PASS, make_inst(), _p(),
                   note=f"A 的报价 {_p()['A']} 在 {item_field} 界内",
                   **kwargs_common),
        ],
        CLASS_NOT_ACTIVE: [],
        CLASS_MISSING_INPUT: [],
        CLASS_OUT_OF_RANGE: [
            _probe(f"{cls_id}/OUT_OF_RANGE", cls_id, STATUS_FAIL, make_inst(),
                   off(10.0, res),
                   note=f"越过 {item_field} 10 个分辨率单位",
                   **kwargs_common),
        ],
        CLASS_EXACT_BOUNDARY: [
            _probe(f"{cls_id}/EXACT_BOUNDARY", cls_id, STATUS_PASS, make_inst(),
                   price_at(bound_a),
                   note=f"p 恰好等于 {item_field}（真·相等，非近似）",
                   **kwargs_common),
        ],
        CLASS_BOUNDARY_PLUS_1: [
            _probe(f"{cls_id}/BOUNDARY_PLUS_1", cls_id, STATUS_FAIL, make_inst(),
                   off(1.0, res),
                   note=f"越过 {item_field} 恰好 1 个分辨率单位（0.01 元）——"
                        "0.01 元的越界在提交报价表里同样是越界",
                   **kwargs_common),
        ],
    }
    return probes


def _p1_c2() -> dict[str, list[Probe]]:
    """C2：p ≤ U（限价上界）；空 cap 项 SKIP；U 缺失 ⇒ BLOCKED。"""
    base = _box("C2", bound_kind="U", upper=True)
    base[CLASS_MISSING_INPUT] = [
        _probe("C2/MISSING_INPUT#no-U", "C2", STATUS_BLOCKED,
               _inst((replace(A_ITEM, U=None), B_ITEM, F_ITEM, N_ITEM)), _p(),
               note="cap 非空但派生量层未给 U——缺口不得折 0"
                    "（空 cap ≠ 0，也不等于「U 缺失可以补」）"),
    ]
    base[CLASS_NOMINAL].append(
        _probe("C2/NOMINAL#free-item-skip", "C2", STATUS_PASS, _inst(), _p(),
               rows_expect=(("F", STATUS_SKIP),),
               note="F 为空 cap（ALLOW_EMPTY_NO_CAP）：不限价 ≠ 上界 0；"
                    "该明细必须**真的** SKIP，否则空 cap 被静默折 0"),
    )
    return base


def _p1_c3() -> dict[str, list[Probe]]:
    """C3：p ≥ L；L 缺失 ⇒ BLOCKED。"""
    base = _box("C3", bound_kind="L", upper=False)
    base[CLASS_MISSING_INPUT] = [
        _probe("C3/MISSING_INPUT#no-L", "C3", STATUS_BLOCKED,
               _inst((replace(A_ITEM, L=None), B_ITEM, F_ITEM, N_ITEM)), _p(),
               note="多来源取大的结果缺失=缺口，不得补 0"),
    ]
    return base


def _p1_c4() -> dict[str, list[Probe]]:
    """C4：p ≥ floor；floor 缺失 ⇒ BLOCKED（μ 未落值 OI-DQ-A 可见化）。"""
    base = _box("C4", bound_kind="floor", upper=False)
    no_floor = dict(BASE_FLOOR)
    no_floor.pop("A")
    base[CLASS_MISSING_INPUT] = [
        _probe("C4/MISSING_INPUT#no-floor", "C4", STATUS_BLOCKED, _inst(), _p(),
               floor_by_id=no_floor,
               note="μ 未落值 / 条款无基准——挂账必须在判定层可见"),
    ]
    return base


def _p1_c5() -> dict[str, list[Probe]]:
    """C5：p ≥ lb_C5 = max(eps_price·P*, resolution)；P_star 缺失 ⇒ BLOCKED。"""
    base = _box("C5", bound_kind="lb_c5", upper=False)
    lb = max(1e-9 * BASE_P_STAR, 0.01)      # = 0.01（被分辨率抬起）
    naked = 1e-9 * BASE_P_STAR              # = 8e-4（裸 eps_price 读法）
    base[CLASS_MISSING_INPUT] = [
        _probe("C5/MISSING_INPUT#no-P_star", "C5", STATUS_BLOCKED,
               _inst(P_star=None), _p(),
               note="P_star 缺失 ⇒ 下界无法确定"),
    ]
    # 在「裸 eps_price」与「抬升后 lb」之间的报价：正确实现 FAIL，不取 max 的
    # 变异体 PASS —— 这就是 ADR-0020「内层与外层舍入耦合点」的可执行形式。
    base[CLASS_BOUNDARY_PLUS_1].append(
        _probe("C5/BOUNDARY_PLUS_1#between-naked-and-lifted", "C5", STATUS_FAIL,
               _inst(), _p(A=(naked + lb) / 2.0),
               note=f"报价 {(naked + lb) / 2.0:.4g} 高于裸 eps_price·P* "
                    f"({naked:.4g}) 但低于抬升后 lb_C5 ({lb:.4g})——"
                    "不取 max 的实现会放行，提交时舍入成 0.00"),
    )
    return base


def _p1_c6() -> dict[str, list[Probe]]:
    """C6：Σ max(c−p,0)·q1 ≤ θ·P*（缺口按**结算量 q1** 加权）。"""
    eps = 0.01          # eps_total = max(0.01, 1e-9·800000) = 0.01
    theta = 0.01
    P_star = BASE_P_STAR
    limit = theta * P_star                      # 8000.0
    q1a = A_ITEM.q1_point                       # 900（≠ q0=1000）

    def price_for_gap(gap: float) -> dict[str, float]:
        """令 A 的缺口 (c_i − p)·q1 恰为 gap。"""
        return _p(A=A_ITEM.c_i - gap / q1a)

    common = {"theta": theta}

    return {
        CLASS_NOMINAL: [
            _probe("C6/NOMINAL", "C6", STATUS_PASS, _inst(active=("C6",), theta=theta),
                   _p(), note="无亏损项 ⇒ 缺口 0", **common),
            # 量纲鉴别点：q1 口径下在界内（PASS），q0 口径下越界（FAIL）。
            # 普通正常用例抓不到「用错量纲」——只有这种点能抓。
            _probe("C6/NOMINAL#dimension-discriminator", "C6", STATUS_PASS,
                   _inst(active=("C6",), theta=theta),
                   price_for_gap(limit * 0.999), **common,
                   note="q1 口径 actual≈limit（PASS）；改用 q0 加权会得到 "
                        "actual≈limit·(1000/900) > limit ⇒ FAIL——量纲混用鉴别点"),
        ],
        CLASS_NOT_ACTIVE: [
            _probe("C6/NOT_ACTIVE", "C6", STATUS_SKIP, _inst(active=()), _p(),
                   theta=theta, note="active_soft_constraints 未声明 C6"),
        ],
        CLASS_MISSING_INPUT: [
            _probe("C6/MISSING_INPUT#no-theta", "C6", STATUS_BLOCKED,
                   _inst(active=("C6",), theta=None), _p(),
                   note="激活但 theta 缺失 ⇒ BLOCKED（不是 SKIP）"),
        ],
        CLASS_OUT_OF_RANGE: [
            _probe("C6/OUT_OF_RANGE", "C6", STATUS_FAIL,
                   _inst(active=("C6",), theta=theta),
                   price_for_gap(limit + eps * 11.0), **common,
                   note="越过可容忍缺口 10 个单位"),
        ],
        CLASS_EXACT_BOUNDARY: [
            _probe("C6/EXACT_BOUNDARY", "C6", STATUS_PASS,
                   _inst(active=("C6",), theta=theta),
                   price_for_gap(limit + eps - _inner(eps)), **common,
                   note="actual 恰好位于可容忍上限内侧 0.1%"),
        ],
        CLASS_BOUNDARY_PLUS_1: [
            _probe("C6/BOUNDARY_PLUS_1", "C6", STATUS_FAIL,
                   _inst(active=("C6",), theta=theta),
                   price_for_gap(limit + eps * 2.0), **common,
                   note="越过可容忍缺口恰好 1 个单位"),
        ],
    }


def _c7_items(n_items: int, losses: int) -> tuple[Phase1Item, ...]:
    """C7 专用夹具：``losses`` 项亏损（p<c_i），其余不亏损。"""
    items = []
    for k in range(n_items):
        items.append(Phase1Item(
            item_id=f"I{k:02d}", q0=10.0, q1_point=10.0, c_i=100.0,
            p0=100.0, cap=200.0, L=50.0, U=200.0))
    return tuple(items)


def _c7_p(n_items: int, losses: int) -> dict[str, float]:
    return {f"I{k:02d}": (90.0 if k < losses else 110.0) for k in range(n_items)}


def _c7_z(n_items: int, losses: int) -> dict[str, float]:
    return {f"I{k:02d}": (1.0 if k < losses else 0.0) for k in range(n_items)}


def _p1_c7() -> dict[str, list[Probe]]:
    """C7：实际亏损项数 ≤ N_max；z 一致性**双向**核查。"""
    def inst(n: int, active: Sequence[str] = ("C7",)) -> Phase1Instance:
        return _inst(_c7_items(n, 0), active=active)

    return {
        CLASS_NOMINAL: [
            _probe("C7/NOMINAL", "C7", STATUS_PASS, inst(3), _c7_p(3, 0),
                   N_max=1.0, z_by_id=_c7_z(3, 0),
                   note="0 亏损项 ≤ N_max 且 z 与事实一致"),
            _probe("C7/NOMINAL#no-z-warns", "C7", STATUS_WARN, inst(3), _c7_p(3, 0),
                   N_max=1.0,
                   note="未提供 z 向量 ⇒ WARN（自称口径未核）——"
                        "「没核」不是「通过」（规则⑧）"),
        ],
        CLASS_NOT_ACTIVE: [
            _probe("C7/NOT_ACTIVE", "C7", STATUS_SKIP, inst(3, active=()),
                   _c7_p(3, 0), N_max=1.0, note="未声明 C7"),
        ],
        CLASS_MISSING_INPUT: [
            _probe("C7/MISSING_INPUT#no-N_max", "C7", STATUS_BLOCKED, inst(3),
                   _c7_p(3, 0), note="激活但 N_max 未声明"),
        ],
        CLASS_OUT_OF_RANGE: [
            _probe("C7/OUT_OF_RANGE", "C7", STATUS_FAIL, inst(12), _c7_p(12, 11),
                   N_max=1.0, z_by_id=_c7_z(12, 11),
                   note="11 个亏损项 vs N_max=1 ⇒ 越界 10 个单位"),
            _probe("C7/OUT_OF_RANGE#z-underreport", "C7", STATUS_FAIL, inst(3),
                   _c7_p(3, 1), N_max=5.0, z_by_id=_c7_z(3, 0),
                   note="亏损项数未超限，但 z=0 而 p<c_i（漏报）——"
                        "只查虚报、不查漏报的实现会放行"),
        ],
        CLASS_EXACT_BOUNDARY: [
            _probe("C7/EXACT_BOUNDARY", "C7", STATUS_PASS, inst(3), _c7_p(3, 1),
                   N_max=1.0, z_by_id=_c7_z(3, 1),
                   note="亏损项数恰好等于 N_max（整数真·相等）⇒ PASS"),
        ],
        CLASS_BOUNDARY_PLUS_1: [
            _probe("C7/BOUNDARY_PLUS_1", "C7", STATUS_FAIL, inst(3), _c7_p(3, 2),
                   N_max=1.0, z_by_id=_c7_z(3, 2),
                   note="亏损 2 项 vs N_max=1 ⇒ 超 1 项（1 单位 = 1 项）"),
        ],
    }


def _p1_c8() -> dict[str, list[Probe]]:
    """C8：p ≥ c_i·(1−d_max)；c_i=0 项 SKIP。"""
    base = _box("C8", bound_kind="c8", upper=False)
    base[CLASS_NOT_ACTIVE] = [
        _probe("C8/NOT_ACTIVE", "C8", STATUS_SKIP, _inst(active=()), _p(),
               d_max=0.2, note="未声明 C8（激活由输入是否声明决定，不由判定器推断）"),
    ]
    base[CLASS_MISSING_INPUT] = [
        _probe("C8/MISSING_INPUT#no-d_max", "C8", STATUS_BLOCKED,
               _inst(active=("C8",)), _p(),
               note="激活但 d_max 未声明"),
    ]
    zero_c = Phase1Item(item_id="Z", q0=10.0, q1_point=10.0, c_i=0.0,
                        p0=10.0, cap=20.0, L=0.0, U=20.0)
    base[CLASS_NOMINAL].append(
        _probe("C8/NOMINAL#zero-cost-skip", "C8", STATUS_PASS,
               _inst((A_ITEM, B_ITEM, F_ITEM, N_ITEM, zero_c), active=("C8",)),
               _p(Z=10.0), d_max=0.2, rows_expect=(("Z", STATUS_SKIP),),
               note="c_i=0 项本式退化为 p≥0，由 C5 承担 ⇒ 必须 SKIP 且留痕"
                    "（不得参与判定、不得除 0）"),
    )
    return base


def _p1_c9() -> dict[str, list[Probe]]:
    """C9：Z ≥ max(Z_min, pi_target·Σc·q1)；Z 由调用方经唯一收入实现传入。"""
    eps = 0.01
    Z_min = 5000.0

    def with_Z(Z: float) -> dict[str, Any]:
        return {"Z": Z, "Z_min": Z_min}

    return {
        CLASS_NOMINAL: [
            _probe("C9/NOMINAL", "C9", STATUS_PASS, _inst(active=("C9",)), _p(),
                   **with_Z(Z_min + 1000.0),
                   note="Z 显著高于下界；Z 为传入值（本层不重算 R_i）"),
            # 第二真相源鉴别点：传入 Z 在界内，而按 Σp·q1 重算得到的「Z」远低
            # ——本层若自行重算收入，本格即 FAIL。
            _probe("C9/NOMINAL#single-source", "C9", STATUS_PASS,
                   _inst(active=("C9",)), _p(), **with_Z(Z_min + 1.0),
                   note="传入 Z 略高于下界；重算 Σp·q1 会得到另一个量 ⇒ "
                        "「本层不重实现 R_i」的可执行形式"),
        ],
        CLASS_NOT_ACTIVE: [
            _probe("C9/NOT_ACTIVE", "C9", STATUS_SKIP, _inst(active=()), _p(),
                   **with_Z(Z_min + 1000.0), note="未声明 C9"),
        ],
        CLASS_MISSING_INPUT: [
            _probe("C9/MISSING_INPUT#no-Z", "C9", STATUS_BLOCKED,
                   _inst(active=("C9",)), _p(), Z_min=Z_min,
                   note="激活但 Z 缺失——须由唯一收入实现复算后传入"),
            _probe("C9/MISSING_INPUT#no-limits", "C9", STATUS_BLOCKED,
                   _inst(active=("C9",)), _p(), Z=Z_min + 1000.0,
                   note="Z_min 与 pi_target 均未声明"),
        ],
        CLASS_OUT_OF_RANGE: [
            _probe("C9/OUT_OF_RANGE", "C9", STATUS_FAIL,
                   _inst(active=("C9",)), _p(),
                   **with_Z(Z_min - eps * 11.0),
                   note="越过可容忍下界 10 个单位"),
        ],
        CLASS_EXACT_BOUNDARY: [
            _probe("C9/EXACT_BOUNDARY", "C9", STATUS_PASS,
                   _inst(active=("C9",)), _p(),
                   **with_Z(Z_min - eps + _inner(eps)),
                   note="Z 恰好位于可容忍下界内侧 0.1%"),
        ],
        CLASS_BOUNDARY_PLUS_1: [
            _probe("C9/BOUNDARY_PLUS_1", "C9", STATUS_FAIL,
                   _inst(active=("C9",)), _p(),
                   **with_Z(Z_min - eps * 2.0),
                   note="越过可容忍下界恰好 1 个单位"),
        ],
    }


def _p1_c10() -> dict[str, list[Probe]]:
    """C10：Σ_{T_front}(ρ·p − c)·q0 ≥ 0（**投标口径 q0**）。"""
    eps = 0.01
    front = {"A": 0.8}

    def price_for_actual(actual: float) -> dict[str, float]:
        """令 A 的 (ρ·p − c)·q0 恰为 actual。"""
        return _p(A=A_ITEM.c_i / 0.8 + actual / (0.8 * A_ITEM.q0))

    common = {"front_rho": front}

    return {
        CLASS_NOMINAL: [
            _probe("C10/NOMINAL", "C10", STATUS_PASS, _inst(), _p(A=550.0),
                   **common, note="前载收款 440 > 成本 400 ⇒ 正贡献"),
        ],
        CLASS_NOT_ACTIVE: [
            _probe("C10/NOT_ACTIVE", "C10", STATUS_SKIP, _inst(), _p(),
                   note="付款条款未声明 T_front ⇒ 不激活（沉默不是断言）"),
        ],
        CLASS_MISSING_INPUT: [
            _probe("C10/MISSING_INPUT#unknown-item", "C10", STATUS_BLOCKED,
                   _inst(), _p(), front_rho={"GHOST": 0.8},
                   note="T_front 声明了不存在的项——不得静默忽略"),
        ],
        CLASS_OUT_OF_RANGE: [
            _probe("C10/OUT_OF_RANGE", "C10", STATUS_FAIL, _inst(),
                   price_for_actual(-eps * 11.0), **common,
                   note="越过可容忍缺口 10 个单位"),
            _probe("C10/OUT_OF_RANGE#coarse", "C10", STATUS_FAIL, _inst(),
                   _p(A=400.0), **common,
                   note="大额越界（前载收款 320 < 成本 400）也必须 FAIL——"
                        "证明判据不是只在微观尺度灵敏"),
        ],
        CLASS_EXACT_BOUNDARY: [
            _probe("C10/EXACT_BOUNDARY", "C10", STATUS_PASS, _inst(),
                   price_for_actual(-eps + _inner(eps)), **common,
                   note="actual 恰好位于可容忍下限内侧 0.1%"),
        ],
        CLASS_BOUNDARY_PLUS_1: [
            _probe("C10/BOUNDARY_PLUS_1", "C10", STATUS_FAIL, _inst(),
                   price_for_actual(-eps * 2.0), **common,
                   note="越过可容忍下限恰好 1 个单位"),
            # 量纲鉴别点：q0 口径越界（FAIL），q1 口径在界内（PASS）。
            _probe("C10/BOUNDARY_PLUS_1#dimension-discriminator", "C10",
                   STATUS_FAIL, _inst(), price_for_actual(-eps * 1.1), **common,
                   note="q0 口径 actual=−0.011（FAIL）；若改用 q1 加权会得到 "
                        "−0.0099（PASS）——量纲混用鉴别点"),
        ],
    }


def _p1_c11() -> dict[str, list[Probe]]:
    """C11：σ(d) ≤ sigma_max（中心 0、基准 cap）；仅 kappa_max ⇒ BLOCKED。"""
    sigma_max = 0.02
    step = UNIT_VALUES["sigma_step"]
    cap_a, cap_b = A_ITEM.cap, B_ITEM.cap

    def symmetric(sigma: float) -> dict[str, float]:
        """构造两项对称偏离使 σ 恰为 sigma（d_A=+s, d_B=−s ⇒ σ=s）。"""
        return _p(A=cap_a * (1.0 + sigma), B=cap_b * (1.0 - sigma), F=250.0)

    return {
        CLASS_NOMINAL: [
            _probe("C11/NOMINAL", "C11", STATUS_PASS, _inst(), symmetric(0.0),
                   sigma_max=sigma_max, note="p 全等于 cap ⇒ σ=0"),
        ],
        CLASS_NOT_ACTIVE: [
            _probe("C11/NOT_ACTIVE", "C11", STATUS_SKIP, _inst(), _p(),
                   note="sigma_max / kappa_max 均未声明（当前 NOT_ACTIVE）"),
        ],
        CLASS_MISSING_INPUT: [
            _probe("C11/MISSING_INPUT#kappa-only", "C11", STATUS_BLOCKED,
                   _inst(), _p(), kappa_max=0.05,
                   note="仅给 kappa_max：MAD 形式已被 lp_formulation_spec 否决，"
                        "不得静默替换判据（方向性错误：MAD ≤ σ，最坏放松 √n 倍）"),
        ],
        CLASS_OUT_OF_RANGE: [
            _probe("C11/OUT_OF_RANGE", "C11", STATUS_FAIL, _inst(),
                   symmetric(sigma_max + 10.0 * step), sigma_max=sigma_max,
                   note="越过 sigma_max 10 个单位（1 单位 = sigma_step）"),
        ],
        CLASS_EXACT_BOUNDARY: [
            _probe("C11/EXACT_BOUNDARY", "C11", STATUS_PASS, _inst(),
                   symmetric(sigma_max - step * EXACT_INNER_FRAC),
                   sigma_max=sigma_max, note="σ 恰好位于界内侧一个极小步长"),
        ],
        CLASS_BOUNDARY_PLUS_1: [
            _probe("C11/BOUNDARY_PLUS_1", "C11", STATUS_FAIL, _inst(),
                   symmetric(sigma_max + step), sigma_max=sigma_max,
                   note="越过 sigma_max 恰好 1 个单位"),
        ],
    }


def _p1_c12() -> dict[str, list[Probe]]:
    """C12：R_pc ≥ R_min − eps_ratio（比值上的**绝对**容差，DV-02 显式隔离）。"""
    eps_ratio = 1e-9
    q0a = A_ITEM.q0
    num = 500.0 * 1000.0 + 400.0 * 500.0 + 250.0 * 100.0 + 300.0 * 50.0
    den = 400.0 * 1000.0 + 300.0 * 500.0 + 200.0 * 100.0 + 100.0 * 50.0
    r_pc = num / den

    def r_min_for(slack: float) -> float:
        """令 ``slack = R_pc − R_min`` 恰为给定值（负=越界到界下）。"""
        return r_pc - slack

    return {
        CLASS_NOMINAL: [
            _probe("C12/NOMINAL", "C12", STATUS_PASS, _inst(), _p(),
                   R_min=r_min_for(0.05),
                   note=f"R_pc={r_pc:.6f} 显著高于 R_min"),
        ],
        CLASS_NOT_ACTIVE: [
            _probe("C12/NOT_ACTIVE", "C12", STATUS_SKIP, _inst(), _p(),
                   note="R_min 未声明 ⇒ 前置可接受性判据不激活"),
        ],
        CLASS_MISSING_INPUT: [
            _probe("C12/MISSING_INPUT#no-c_i", "C12", STATUS_BLOCKED,
                   _inst((replace(A_ITEM, c_i=None), B_ITEM, F_ITEM, N_ITEM)),
                   _p(), R_min=r_min_for(0.05), note="任一项缺 c_i ⇒ 分母不可算"),
        ],
        CLASS_OUT_OF_RANGE: [
            _probe("C12/OUT_OF_RANGE", "C12", STATUS_FAIL, _inst(), _p(),
                   R_min=r_min_for(-eps_ratio * 11.0),
                   note="越过可容忍下界 10 个单位（1 单位 = 1 个 eps_ratio）"),
        ],
        CLASS_EXACT_BOUNDARY: [
            _probe("C12/EXACT_BOUNDARY", "C12", STATUS_PASS, _inst(), _p(),
                   R_min=r_min_for(-eps_ratio + _inner(eps_ratio)),
                   note="R_pc 恰好位于可容忍下界内侧 0.1%"),
        ],
        CLASS_BOUNDARY_PLUS_1: [
            # DV-02 核心格：若容差被写成 eps_price×P*=8e-4（放大 8e5 倍），
            # 本格的 slack=−2e-9 ≥ −8e-4 ⇒ 会误判 PASS。本格专杀该变异体。
            _probe("C12/BOUNDARY_PLUS_1", "C12", STATUS_FAIL, _inst(), _p(),
                   R_min=r_min_for(-eps_ratio * 2.0),
                   note="越过可容忍下界恰好 1 个单位；若容差误用 eps_price×P* "
                        "（比值上放大 ~8e5 倍）⇒ 会误判 PASS（DV-02）"),
        ],
    }


def _p1_c13() -> dict[str, list[Probe]]:
    """C13：恒 SKIP（结算期条件修正，投标期不可知——不新增判据）。"""
    return {
        CLASS_NOMINAL: [
            _probe("C13/NOMINAL", "C13", STATUS_SKIP, _inst(), _p(),
                   note="恒 SKIP：偏高侧是死分支（C2 保证 p≤cap），偏低侧触发条件"
                        "含结算期工程量事实。SKIP 不得折叠成 PASS（规则⑧）"),
        ],
        CLASS_NOT_ACTIVE: [],
        CLASS_MISSING_INPUT: [],
        CLASS_OUT_OF_RANGE: [],
        CLASS_EXACT_BOUNDARY: [],
        CLASS_BOUNDARY_PLUS_1: [],
    }


PROBE_BUILDERS: dict[str, Callable[[], dict[str, list[Probe]]]] = {
    "C1": _p1_c1, "C2": _p1_c2, "C3": _p1_c3, "C4": _p1_c4, "C5": _p1_c5,
    "C6": _p1_c6, "C7": _p1_c7, "C8": _p1_c8, "C9": _p1_c9, "C10": _p1_c10,
    "C11": _p1_c11, "C12": _p1_c12, "C13": _p1_c13,
}


# =========================================================================
# 制品加载 / 用例枚举 / 覆盖审计
# =========================================================================
def load_matrix_spec(config_path: Path | None = None) -> dict[str, Any]:
    """``config_path`` 可传目录（自动拼 SPEC_FILENAME）或制品文件路径。"""
    path = config_path if config_path is not None else config_dir()
    if path.is_dir():
        path = path / SPEC_FILENAME
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _tweaked_spec(spec: Mapping[str, Any], tweak: str | None) -> dict[str, Any]:
    """应用探针的 ``spec_tweak``（当前只支持删除具名容差）。

    返回**深拷贝**——探针不得污染调用方传入的制品（制品是冻结物）。
    """
    out = copy.deepcopy(dict(spec))
    if not tweak:
        return out
    if tweak.startswith("drop_tol:"):
        name = tweak.split(":", 1)[1]
        entries = out.get("tolerances", {}).get("entries", {})
        entries.pop(name, None)
        return out
    raise ValueError(f"未知 spec_tweak：{tweak!r}")  # pragma: no cover


def _exception_index(spec: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    idx: dict[tuple[str, str], str] = {}
    for exc in spec.get("coverage_requirements", {}).get("exceptions", ()):
        idx[(str(exc["constraint_id"]), str(exc["class_id"]))] = str(exc.get("reason", ""))
    return idx


def enumerate_cases(spec: Mapping[str, Any]) -> tuple[MatrixCase, ...]:
    """生成 ``约束 × 边界类`` 的完整笛卡尔积（含被声明为例外的空格）。

    **覆盖面只取决于制品声明的维度**，不取决于任何实例的取值。
    """
    cov = spec.get("coverage_requirements", {})
    constraints: Sequence[str] = cov.get("constraints", ())
    classes: Sequence[str] = cov.get("required_classes", ())
    exc = _exception_index(spec)
    builders = {cid: PROBE_BUILDERS[cid]() for cid in constraints if cid in PROBE_BUILDERS}

    cases: list[MatrixCase] = []
    for cid in constraints:
        for cls_id in classes:
            case_id = f"{cid}/{cls_id}"
            reason = exc.get((cid, cls_id))
            if reason is not None:
                cases.append(MatrixCase(case_id, cid, cls_id, applicable=False,
                                        reason=reason))
                continue
            probes = tuple(builders.get(cid, {}).get(cls_id, ()))
            if not probes:
                # 未被声明为例外、又无探针 ⇒ 未声明的空格（由覆盖审计判 BLOCKED）
                cases.append(MatrixCase(case_id, cid, cls_id, applicable=True,
                                        reason=""))
                continue
            cases.append(MatrixCase(case_id, cid, cls_id, applicable=True,
                                    probes=probes))
    return tuple(cases)


@dataclass(frozen=True)
class CoverageReport:
    total_cells: int
    covered: int
    declared_not_applicable: int
    undeclared_gaps: tuple[str, ...]
    probe_count: int

    @property
    def status(self) -> str:
        if self.total_cells == 0:
            return STATUS_BLOCKED        # 零格 ⇒ 没判过
        if self.undeclared_gaps:
            return STATUS_BLOCKED        # 沉默不是断言：空格必须被声明
        return STATUS_PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total_cells": self.total_cells,
            "covered": self.covered,
            "declared_not_applicable": self.declared_not_applicable,
            "undeclared_gaps": list(self.undeclared_gaps),
            "probe_count": self.probe_count,
        }


def audit_coverage(spec: Mapping[str, Any],
                   cases: Sequence[MatrixCase]) -> CoverageReport:
    """覆盖审计：每格要么已被覆盖，要么在制品 exceptions 里**显式声明**不适用。"""
    exc = _exception_index(spec)
    covered = 0
    na = 0
    gaps: list[str] = []
    probes = 0
    for c in cases:
        if not c.applicable:
            na += 1
            continue
        if c.probes:
            covered += 1
            probes += len(c.probes)
        else:
            gaps.append(c.case_id)
    # 制品里声明了但枚举不出的例外（维度写错名）也算未声明空格的对偶：
    for key in exc:
        if not any(c.constraint_id == key[0] and c.boundary_class == key[1]
                   for c in cases):
            gaps.append(f"{key[0]}/{key[1]}(例外声明的维度不存在)")
    expected = spec.get("coverage_requirements", {}).get("expected_total")
    if isinstance(expected, int) and expected != len(cases):
        gaps.append(f"格数不符：制品声明 {expected}，枚举得 {len(cases)}")
    return CoverageReport(len(cases), covered, na, tuple(sorted(gaps)), probes)


def ruleset_summary(spec: Mapping[str, Any]) -> dict[str, Any]:
    """制品自述摘要（供 CLI 与报告首部使用）。"""
    cov = spec.get("coverage_requirements", {})
    return {
        "spec_id": spec.get("spec_id"),
        "task": spec.get("task"),
        "constraints": list(cov.get("constraints", ())),
        "boundary_classes": [b["class_id"] for b in spec.get("boundary_classes", ())],
        "unit_binding": {k: v for k, v in spec.get("unit_binding", {}).items()
                         if not k.startswith("_")},
        "mutant_count": len(spec.get("mutants", {}).get("entries", ())),
    }


# =========================================================================
# 评估：探针 → 状态比对（judge_fn 参数化：真实实现与变异体同跑）
# =========================================================================
JudgeFn = Callable[[JudgeInputs, Mapping[str, Any]], ConstraintReport]


@dataclass(frozen=True)
class AggregateProbe:
    """不落在 78 格里的聚合不变量探针。

    六元组判定器之外的语义（聚合序 / 空集 / P1 不阻塞 P0）只在这里可见——
    它们**没有**对应的「约束 × 边界」格，故单列，同样计入变异体杀伤面。
    """

    probe_id: str
    verdicts: tuple[tuple[str, str, str], ...]     # (constraint_id, status, severity)
    expected_verdict: str
    expected_verdict_all: str | None = None
    note: str = ""


AGGREGATE_PROBES: tuple[AggregateProbe, ...] = (
    AggregateProbe("AP-01/empty-set", (), STATUS_BLOCKED, STATUS_BLOCKED,
                   note="空判据集 ⇒ BLOCKED——「没判过」不是 PASS（规则⑧）"),
    AggregateProbe("AP-02/skip-not-in-competition",
                   (("C1", STATUS_PASS, "P0"), ("C6", STATUS_SKIP, "P0")),
                   STATUS_PASS, STATUS_PASS,
                   note="SKIP 不参与最严竞争——否则任何带未激活项的实例永不到 PASS"),
    AggregateProbe("AP-03/all-skip",
                   (("C1", STATUS_SKIP, "P0"), ("C6", STATUS_SKIP, "P0")),
                   STATUS_SKIP, STATUS_SKIP,
                   note="全 SKIP ⇒ SKIP（「全部没判过」仍不是 PASS）"),
    AggregateProbe("AP-04/p1-fail-does-not-block-p0",
                   (("C1", STATUS_PASS, "P0"), ("C11", STATUS_FAIL, "P1")),
                   STATUS_PASS, STATUS_FAIL,
                   note="P1 的 FAIL 不阻塞 P0 主干，但必须在 verdict_all 里可见"),
)


def _make_report(items: Sequence[tuple[str, str, str]]) -> ConstraintReport:
    from ..solver.constraint_judge import ConstraintVerdict
    return ConstraintReport(verdicts=tuple(
        ConstraintVerdict(cid, st, None, None, None, sev) for cid, st, sev in items))


def _rows_violations(v: Any, rows_expect: Sequence[tuple[str, str]]) -> list[str]:
    bad: list[str] = []
    rows = {r.get("item_id"): r.get("status") for r in getattr(v, "rows", ())}
    for item_id, want in rows_expect:
        got = rows.get(item_id, "<无明细行>")
        if got != want:
            bad.append(f"{item_id} 明细状态 = {got}，期望 {want}")
    return bad


def evaluate_probe(probe: Probe, judge_spec: Mapping[str, Any],
                   judge_fn: JudgeFn) -> ProbeResult:
    """跑一个探针：调用被测判定器，比对**状态**与**明细行**。

    注意：期望值来自制品语义，**不由被测实现的输出决定**——否则判据自证（规则⑥）。

    ``judge_spec`` 是**判定器规格**（``constraint_judge_spec.json``，容差注册表
    的真值所在），不是矩阵规格——两者不可混用：矩阵规格声明"判哪些格"，
    判定器规格声明"判据怎么算"。用一个去冒充另一个就是 DV-01 的形态。
    """
    inputs = JudgeInputs(instance=probe.instance, p_by_id=dict(probe.p_by_id),
                         **dict(probe.kwargs))
    try:
        report = judge_fn(inputs, _tweaked_spec(judge_spec, probe.spec_tweak))
    except Exception as exc:                       # noqa: BLE001 - 异常也是「不符」
        return ProbeResult(probe.probe_id, probe.expected,
                           f"<异常:{type(exc).__name__}>", False, f"{exc}")
    v = report.of(probe.constraint_id)
    if v is None:
        return ProbeResult(probe.probe_id, probe.expected, "<无该约束结论>", False,
                           "判定器未给出该约束的六元组")
    bad = _rows_violations(v, probe.rows_expect)
    matched = (v.status == probe.expected) and not bad
    detail = probe.note
    if v.status != probe.expected:
        detail += f" ｜实测 {v.status}：{v.reason}"
    if bad:
        detail += " ｜" + "；".join(bad)
    return ProbeResult(probe.probe_id, probe.expected, v.status, matched, detail)


def evaluate_aggregate(probe: AggregateProbe) -> ProbeResult:
    report = _make_report(probe.verdicts)
    got = report.verdict()
    matched = got == probe.expected_verdict
    detail = probe.note
    if probe.expected_verdict_all is not None:
        got_all = report.verdict_all()
        if got_all != probe.expected_verdict_all:
            matched = False
            detail += f" ｜verdict_all 实测 {got_all}，期望 {probe.expected_verdict_all}"
    if got != probe.expected_verdict:
        detail += f" ｜verdict 实测 {got}，期望 {probe.expected_verdict}"
    return ProbeResult(probe.probe_id, probe.expected_verdict, got, matched, detail)


@dataclass(frozen=True)
class MatrixRun:
    verdict: str
    coverage: CoverageReport
    cases: tuple[CaseResult, ...]
    aggregates: tuple[ProbeResult, ...]
    mutants: tuple["MutantResult", ...] = ()
    rule_precedence: "RulePrecedenceReport | None" = None
    ruleset_switch: "RuleSetSwitchReport | None" = None

    @property
    def failed_cases(self) -> tuple[CaseResult, ...]:
        return tuple(c for c in self.cases if c.applicable and not c.matched)

    @property
    def surviving_mutants(self) -> tuple[str, ...]:
        return tuple(m.mutant_id for m in self.mutants if not m.killed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "coverage": self.coverage.to_dict(),
            "cases_total": len(self.cases),
            "cases_failed": [c.case_id for c in self.failed_cases],
            "aggregates_failed": [a.probe_id for a in self.aggregates if not a.matched],
            "mutants_killed": [m.mutant_id for m in self.mutants if m.killed],
            "mutants_surviving": list(self.surviving_mutants),
            "rule_precedence": (self.rule_precedence.to_dict()
                                if self.rule_precedence else None),
            "ruleset_switch": (self.ruleset_switch.to_dict()
                               if self.ruleset_switch else None),
        }


def evaluate_matrix(judge_fn: JudgeFn | None = None, *,
                    spec: Mapping[str, Any] | None = None,
                    cases: Sequence[MatrixCase] | None = None,
                    judge_spec: Mapping[str, Any] | None = None,
                    ) -> tuple[tuple[CaseResult, ...], tuple[ProbeResult, ...]]:
    """对给定 ``judge_fn`` 跑全矩阵（78 格 + 聚合探针）。

    ``spec`` 是矩阵规格（枚举用例），``judge_spec`` 是判定器规格（容差注册表）
    ——两者**不可混用**（见 :func:`evaluate_probe`）。
    """
    from ..solver.constraint_judge import load_constraint_spec
    spec = spec if spec is not None else load_matrix_spec()
    judge_spec = (judge_spec if judge_spec is not None
                  else load_constraint_spec())
    cases = cases if cases is not None else enumerate_cases(spec)
    fn = judge_fn if judge_fn is not None else _default_judge
    case_results: list[CaseResult] = []
    for case in cases:
        if not case.applicable:
            case_results.append(CaseResult(case.case_id, False, (), case.reason))
            continue
        results = tuple(evaluate_probe(p, judge_spec, fn) for p in case.probes)
        case_results.append(CaseResult(case.case_id, True, results, case.reason))
    agg = tuple(evaluate_aggregate(a) for a in AGGREGATE_PROBES)
    return tuple(case_results), agg


def _default_judge(inputs: JudgeInputs, spec: Mapping[str, Any]) -> ConstraintReport:
    return judge_constraints(inputs, spec=spec)


# =========================================================================
# 变异体：每条坏实现都必须被至少一个探针杀掉（存活 ⇒ 判据盲区 ⇒ FAIL）
# =========================================================================
@dataclass(frozen=True)
class MutantResult:
    mutant_id: str
    target: str
    defect: str
    killed: bool
    killed_by: tuple[str, ...] = ()
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutant_id": self.mutant_id,
            "target": self.target,
            "defect": self.defect,
            "killed": self.killed,
            "killed_by": list(self.killed_by),
        }


class _patch:
    """临时替换模块级属性（变异体不改内层源码，只在评估期替换）。"""

    def __init__(self, obj: Any, name: str, value: Any) -> None:
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self) -> Any:
        self._had = hasattr(self.obj, self.name)
        self._old = getattr(self.obj, self.name, None)
        setattr(self.obj, self.name, self.value)
        return self.value

    def __exit__(self, *exc: Any) -> None:
        if self._had:
            setattr(self.obj, self.name, self._old)
        else:                                   # pragma: no cover
            delattr(self.obj, self.name)


def _cj() -> Any:
    from ..solver import constraint_judge as cj
    return cj


def _skip_competes_verdict(self: Any) -> str:
    """M-17：SKIP 参与最严竞争（去掉 `status != SKIP` 过滤）。"""
    if not self.verdicts:
        return "BLOCKED"
    p0 = [v.status for v in self.verdicts if v.severity == "P0"]
    for s in ("FAIL", "BLOCKED", "WARN", "SKIP", "PASS"):
        if s in p0:
            return s
    return "BLOCKED"                            # pragma: no cover


def _empty_pass_verdict(self: Any) -> str:
    """M-18：空判据集返回 PASS（「没判过」被折叠成「通过」）。"""
    if not self.verdicts:
        return "PASS"
    p0 = [v.status for v in self.verdicts
          if v.severity == "P0" and v.status != "SKIP"]
    if not p0:
        return "SKIP"
    for s in ("FAIL", "BLOCKED", "WARN", "PASS"):
        if s in p0:
            return s
    return "BLOCKED"                            # pragma: no cover


def _mutator(mutant_id: str) -> Any:
    """返回 ``contextlib`` 风格的上下文管理器，进入即注入该变异体。"""
    cj = _cj()
    V = cj.ConstraintVerdict
    P, F, B, S, W = ("PASS", "FAIL", "BLOCKED", "SKIP", "WARN")

    if mutant_id == "M-01":
        # C1 自证：右端随候选 p 变 ⇒ 判据退化为恒真式
        return _patch(cj, "judge_c1",
                      lambda i, t, s: V("C1", P, None, None, 0.0, s,
                                        "右端随 p 变（恒真式）"))
    if mutant_id == "M-02":
        def f(i, s):
            v = cj.__dict__["_real_c2"](i, s)
            for it in i.instance.opt_items:
                if it.cap is None and it.U is None:
                    p = i.p_by_id.get(it.item_id)
                    if p is not None and float(p) > 0.0:
                        return V("C2", F, p, 0.0, -float(p), s,
                                 "空 cap 折 0（不限价被当成上界 0）")
            return v
        return _patch(cj, "judge_c2", f)
    if mutant_id == "M-03":
        def f(i, s):
            v = cj.__dict__["_real_c2"](i, s)
            if v.status == P and v.slack == 0.0:
                return V("C2", F, v.actual, v.limit, 0.0, s,
                         "边界归属写反：恰好触界被判违规")
            return v
        return _patch(cj, "judge_c2", f)
    if mutant_id == "M-04":
        def f(i, s):
            v = cj.__dict__["_real_c2"](i, s)
            if v.status == F and v.slack is not None and v.slack >= -5 * 0.01:
                return V("C2", P, v.actual, v.limit, v.slack, s,
                         "上界被放宽 5 个分辨率单位")
            return v
        return _patch(cj, "judge_c2", f)
    if mutant_id == "M-05":
        def f(i, s):
            v = cj.__dict__["_real_c3"](i, s)
            if v.status == B:
                # L 缺失按 0 继续判（缺口被静默补 0）
                patched = replace(i, instance=replace(
                    i.instance,
                    items=tuple(replace(it, L=0.0) if it.L is None else it
                                for it in i.instance.items)))
                return cj.__dict__["_real_c3"](patched, s)
            return v
        return _patch(cj, "judge_c3", f)
    if mutant_id == "M-06":
        def f(i, s):
            v = cj.__dict__["_real_c4"](i, s)
            if v.status == B:
                # floor 缺失按 0 顶上
                fl = dict(i.floor_by_id or {})
                for it in i.instance.opt_items:
                    fl.setdefault(it.item_id, 0.0)
                return cj.__dict__["_real_c4"](replace(i, floor_by_id=fl), s)
            return v
        return _patch(cj, "judge_c4", f)
    if mutant_id == "M-07":
        def f(i, t, s):
            v = cj.__dict__["_real_c5"](i, t, s)
            if v.status == F:
                naked = t.get("eps_price", 0.0) * (i.instance.P_star or 0.0)
                p = v.actual
                if p is not None and float(p) >= naked:
                    return V("C5", P, p, naked, float(p) - naked, s,
                             "下界用裸 eps_price·P*（未取 max 抬升到分辨率）")
            return v
        return _patch(cj, "judge_c5", f)
    if mutant_id == "M-08":
        def f(i, t, s):
            v = cj.__dict__["_real_c6"](i, t, s)
            if v.status == P:
                a0 = 0.0
                for it in i.instance.opt_items:
                    p = i.p_by_id.get(it.item_id)
                    if p is None or it.c_i is None or it.q0 is None:
                        continue
                    a0 += max(it.c_i - float(p), 0.0) * it.q0
                if v.limit is not None and a0 > float(v.limit) + 1e-12:
                    return V("C6", F, a0, v.limit, float(v.limit) - a0, s,
                             "缺口按 q0 加权（应用结算量 q1）")
            return v
        return _patch(cj, "judge_c6", f)
    if mutant_id == "M-09":
        def f(i, t, s):
            # 只查虚报、不查漏报：把「z=0 而实际亏损」改写成 z=1 再判
            if i.z_by_id:
                by = {it.item_id: it for it in i.instance.items}
                z2 = dict(i.z_by_id)
                for k, zv in i.z_by_id.items():
                    it = by.get(k)
                    p = i.p_by_id.get(k)
                    if (it is not None and it.c_i is not None and p is not None
                            and zv == 0.0 and float(p) < it.c_i):
                        z2[k] = 1.0
                return cj.__dict__["_real_c7"](replace(i, z_by_id=z2), t, s)
            return cj.__dict__["_real_c7"](i, t, s)
        return _patch(cj, "judge_c7", f)
    if mutant_id == "M-10":
        def f(i, t, s):
            # 未提供 z 直接 PASS：喂一个「与事实一致」的 z，跳过未核判定
            if i.z_by_id is None:
                by = {it.item_id: it for it in i.instance.items}
                zz = {k: (1.0 if (by[k].c_i is not None
                                  and float(i.p_by_id.get(k, 0.0)) < by[k].c_i)
                          else 0.0)
                      for k in i.p_by_id if k in by and by[k].c_i is not None}
                return cj.__dict__["_real_c7"](replace(i, z_by_id=zz), t, s)
            return cj.__dict__["_real_c7"](i, t, s)
        return _patch(cj, "judge_c7", f)
    if mutant_id == "M-11":
        def f(i, t, s):
            v = cj.__dict__["_real_c7"](i, t, s)
            if v.status == P and v.actual == v.limit:
                return V("C7", F, v.actual, v.limit, 0.0, s,
                         "边界归属写反：亏损项数恰好等于 N_max 被判违规")
            return v
        return _patch(cj, "judge_c7", f)
    if mutant_id == "M-12":
        def f(i, s):
            v = cj.__dict__["_real_c8"](i, s)
            rows = tuple(r for r in v.rows if r.get("status") != S)
            return V(v.constraint_id, v.status, v.actual, v.limit, v.slack,
                     v.severity, v.reason, rows)
        return _patch(cj, "judge_c8", f)
    if mutant_id == "M-13":
        def f(i, t, s):
            if i.Z is None:
                zz = 0.0
                for it in i.instance.opt_items:
                    p = i.p_by_id.get(it.item_id)
                    if p is None or it.q1_point is None:
                        continue
                    zz += float(p) * it.q1_point
                # 本层自行造 Z（第二真相源）⇒ 缺 Z 也不再 BLOCKED
                return cj.__dict__["_real_c9"](replace(i, Z=zz), t, s)
            return cj.__dict__["_real_c9"](i, t, s)
        return _patch(cj, "judge_c9", f)
    if mutant_id == "M-14":
        def f(i, t, s):
            v = cj.__dict__["_real_c10"](i, t, s)
            if v.status == F:
                front = i.front_rho or {}
                by_id = {it.item_id: it for it in i.instance.items}
                a1 = 0.0
                for iid, rho in front.items():
                    it = by_id.get(iid)
                    if it is None or it.c_i is None or it.q1_point is None:
                        continue
                    p = i.p_by_id.get(iid) if it.is_optimizable else it.p0
                    if p is None:
                        continue
                    a1 += (float(rho) * float(p) - it.c_i) * it.q1_point
                if a1 >= -abs(t.get("eps_total", 0.0)):
                    return V("C10", P, a1, 0, a1, s,
                             "前载项按 q1 加权（应用投标口径 q0）")
            return v
        return _patch(cj, "judge_c10", f)
    if mutant_id == "M-15":
        def f(i, s):
            v = cj.__dict__["_real_c11"](i, s)
            if v.status == B and i.kappa_max is not None:
                ds = []
                for it in i.instance.opt_items:
                    p = i.p_by_id.get(it.item_id)
                    if p is None or it.cap in (None, 0):
                        continue
                    ds.append((float(p) - it.cap) / it.cap)
                if ds:
                    ds.sort()
                    med = ds[len(ds) // 2]
                    mad = sorted(abs(d - med) for d in ds)[len(ds) // 2]
                    st = P if mad <= i.kappa_max else F
                    return V("C11", st, mad, i.kappa_max, i.kappa_max - mad, s,
                             "仅给 kappa_max 时用 MAD 形式顶上（静默替换判据）")
            return v
        return _patch(cj, "judge_c11", f)
    if mutant_id == "M-16":
        def f(i, t, s):
            v = cj.__dict__["_real_c12"](i, t, s)
            if v.status == F and v.slack is not None:
                wide = t.get("eps_price", 0.0) * (i.instance.P_star or 0.0)
                if float(v.slack) >= -wide:
                    return V("C12", P, v.actual, v.limit, v.slack, s,
                             "容差用 eps_price×P*（比值上被放大 ~8e5 倍，DV-02）")
            return v
        return _patch(cj, "judge_c12", f)
    if mutant_id == "M-17":
        from ..solver.constraint_judge import ConstraintReport
        return _patch(ConstraintReport, "verdict", _skip_competes_verdict)
    if mutant_id == "M-18":
        from ..solver.constraint_judge import ConstraintReport
        return _patch(ConstraintReport, "verdict", _empty_pass_verdict)
    if mutant_id == "M-19":
        def f(spec: Any, P_star: Any) -> Any:
            resolved, missing = cj.__dict__["_real_resolve_tolerances"](spec, P_star)
            for name in missing:
                resolved[name] = 0.0        # 用 0 顶替未解析的容差
            return resolved, missing
        return _patch(cj, "resolve_tolerances", f)
    raise KeyError(f"未登记的变异体 {mutant_id!r}")  # pragma: no cover


_REAL_NAMES = {
    "judge_c1": "judge_c1", "judge_c2": "judge_c2", "judge_c3": "judge_c3",
    "judge_c4": "judge_c4", "judge_c5": "judge_c5", "judge_c6": "judge_c6",
    "judge_c7": "judge_c7", "judge_c8": "judge_c8", "judge_c9": "judge_c9",
    "judge_c10": "judge_c10", "judge_c11": "judge_c11", "judge_c12": "judge_c12",
    "resolve_tolerances": "resolve_tolerances",
}


def snapshot_real_impl() -> None:
    """把真实实现的函数快照到 ``_real_*`` 名字下，供变异体调用。

    **必须在任何变异体注入前调用一次**，且这些名字是变异体的唯一委托对象——
    变异体自身不复制内层判据（除极简的「错法」外），只包装真实实现。
    """
    cj = _cj()
    for name, alias in _REAL_NAMES.items():
        real = getattr(cj, name, None)
        if real is not None:
            setattr(cj, f"_real_{alias.replace('judge_', '')}", real)


def audit_mutants(spec: Mapping[str, Any],
                  cases: Sequence[MatrixCase],
                  ) -> tuple[MutantResult, ...]:
    """逐条注入变异体，跑同一矩阵；没有任何探针失配 ⇒ 存活 ⇒ 判据盲区。"""
    snapshot_real_impl()
    out: list[MutantResult] = []
    for entry in spec.get("mutants", {}).get("entries", ()):
        mid = str(entry["mutant_id"])
        killed_by: list[str] = []
        try:
            ctx = _mutator(mid)
        except Exception as exc:                # noqa: BLE001
            out.append(MutantResult(mid, str(entry.get("target")), 
                                    str(entry.get("defect")), False, (),
                                    f"变异体构造失败：{exc}"))
            continue
        with ctx:
            cr, ag = evaluate_matrix(spec=spec, cases=cases)
        for c in cr:
            if c.applicable and not c.matched:
                killed_by.append(c.case_id)
        for a in ag:
            if not a.matched:
                killed_by.append(a.probe_id)
        out.append(MutantResult(
            mid, str(entry.get("target")), str(entry.get("defect")),
            bool(killed_by), tuple(dict.fromkeys(killed_by)),
            "已被至少一个探针否定" if killed_by else "**存活**：无探针能区分该错误实现",
        ))
    return tuple(out)


def _pc() -> Any:
    from ..contracts import pricing_card as pc
    return pc


def audit_mode_mutants(spec: Mapping[str, Any]) -> tuple[MutantResult, ...]:
    """规则优先级 / 规则集切换两族的变异体审计（MP-* / MR-*）。

    这两族的目标不是判定器而是**规则层**，故不落在 78 格里；它们通过「检查
    模式开关」注入（``use_real=False`` / ``clone_2024`` / ``clone_meta_field``），
    与判定器族的变异体并列计入杀伤面。
    """
    out: list[MutantResult] = []
    by_id: dict[str, dict[str, Any]] = {}
    for key in ("rule_precedence", "ruleset_switch"):
        for e in spec.get(key, {}).get("mutants", ()):
            by_id[str(e["mutant_id"])] = e

    def record(mid: str, killed_by: Sequence[str], note: str) -> None:
        e = by_id.get(mid, {})
        out.append(MutantResult(
            mid, str(e.get("target", "规则层")), str(e.get("defect", "")),
            bool(killed_by), tuple(dict.fromkeys(killed_by)),
            note if not killed_by else "已被至少一条检查否定"))

    # MP-01：覆盖只改参数、判定仍走实现常量
    rep = check_rule_precedence(use_real=False)
    record("MP-01", [c.check_id for c in rep.checks if not c.passed],
           "**存活**：阈值注入失效未被察觉")

    # MP-02：Standard 层标签冒充得以放行（互锁被绕过）
    pc = _pc()
    real_std = pc.resolve_parameters
    labels = pc.STANDARD_LAYER_LABELS

    def _skip_interlock(card: Any, override: Any = None, *,
                        source_label: str = "override") -> Any:
        pc.STANDARD_LAYER_LABELS = frozenset()
        try:
            return real_std(card, override, source_label=source_label)
        finally:
            pc.STANDARD_LAYER_LABELS = labels

    with _patch(pc, "resolve_parameters", _skip_interlock):
        rep = check_rule_precedence()
    record("MP-02", [c.check_id for c in rep.checks if not c.passed],
           "**存活**：Standard 层互锁被绕过未被察觉")

    # MP-03：未登记键静默忽略
    reg = pc.REGISTERED_OVERRIDES

    def _ignore_unknown(card: Any, override: Any = None, *,
                        source_label: str = "override") -> Any:
        ov = (None if not override
              else {k: v for k, v in override.items() if k in reg})
        return real_std(card, ov, source_label=source_label)

    with _patch(pc, "resolve_parameters", _ignore_unknown):
        rep = check_rule_precedence()
    record("MP-03", [c.check_id for c in rep.checks if not c.passed],
           "**存活**：未登记键被静默忽略未被察觉")

    # MR-01：2024 公式复用 2013 实现
    sw = check_ruleset_switch(clone_2024=True)
    record("MR-01", [ly.layer_id for ly in sw.layers if ly.status == STATUS_FAIL],
           "**存活**：公式被复制而两版仍被判为可区分")

    # MR-02 / MR-03：元信息被复制（数值同形时唯一可区分层失效）
    for mid, field in (("MR-02", "p1_source"), ("MR-03", "supported_scopes")):
        sw = check_ruleset_switch(clone_meta_field=field)
        record(mid, [ly.layer_id for ly in sw.layers if ly.status == STATUS_FAIL],
               "**存活**：元信息被复制未被察觉")
    return tuple(out)


# =========================================================================
# 规则优先级：标准阈值与合同阈值并存时证明**合同阈值生效**
# =========================================================================
@dataclass(frozen=True)
class PrecedenceCheck:
    check_id: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"check_id": self.check_id, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class RulePrecedenceReport:
    checks: tuple[PrecedenceCheck, ...]

    @property
    def status(self) -> str:
        if not self.checks:
            return STATUS_BLOCKED
        return STATUS_PASS if all(c.passed for c in self.checks) else STATUS_FAIL

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status,
                "checks": [c.to_dict() for c in self.checks]}


CONTRACT_OVERRIDE = {"decrease_threshold": 0.9, "increase_threshold": 1.1}
PROBE_R_LOW = 0.88        # 标准 IN_RANGE，合同 DECREASE
PROBE_R_HIGH = 1.12       # 标准 IN_RANGE，合同 INCREASE


def check_rule_precedence(*, use_real: bool = True) -> RulePrecedenceReport:
    """A1–A4 四条断言。``use_real=False`` 即注入 MP-01（覆盖只记参数不改判定）。"""
    from ..contracts.pricing_card import (
        PricingCardError, classify_branch, load_pricing_card, resolve_parameters,
    )
    from ..contracts.rule_sets.base import (
        BRANCH_DECREASE, BRANCH_INCREASE, RuleSet,
    )
    from ..paths import config_dir as _cfg

    checks: list[PrecedenceCheck] = []
    card = load_pricing_card(_cfg())

    def branch_of(r: float, *, overridden: bool) -> str:
        ov = CONTRACT_OVERRIDE if overridden else None
        label = "contract" if overridden else "override"
        params = resolve_parameters(card, ov, source_label=label)
        if use_real:
            return classify_branch(r, params)
        # MP-01：覆盖只改参数，判定仍走实现常量
        return RuleSet.classify_branch(r)

    # A1 低侧
    got_std = branch_of(PROBE_R_LOW, overridden=False)
    got_ctr = branch_of(PROBE_R_LOW, overridden=True)
    checks.append(PrecedenceCheck(
        "A1/contract-threshold-effective(decrease)", 
        got_std == "IN_RANGE" and got_ctr == BRANCH_DECREASE,
        f"r={PROBE_R_LOW}：标准阈值下 {got_std}，合同阈值下 {got_ctr}"
        f"（期望 IN_RANGE / {BRANCH_DECREASE}）"))
    # A1 高侧
    got_std_h = branch_of(PROBE_R_HIGH, overridden=False)
    got_ctr_h = branch_of(PROBE_R_HIGH, overridden=True)
    checks.append(PrecedenceCheck(
        "A1/contract-threshold-effective(increase)",
        got_std_h == "IN_RANGE" and got_ctr_h == BRANCH_INCREASE,
        f"r={PROBE_R_HIGH}：标准 {got_std_h}，合同 {got_ctr_h}"
        f"（期望 IN_RANGE / {BRANCH_INCREASE}）"))
    # A1 第三路径：结算引擎必须传注入阈值（否则结算与规则卡两处说法）
    try:
        from ..settlement import ContractContext, SettlementRule
        eng = SettlementRule(card=card)
        out = eng.evaluate(1.0, PROBE_R_LOW, 1.0,
                           ContractContext(rule_set_id="GB/T50500-2024",
                                           overrides=dict(CONTRACT_OVERRIDE),
                                           source_label="contract",
                                           adjustment_scope="SEGMENT"))
        got_eng = getattr(out, "rule_branch", None) or getattr(out, "branch", None)
        checks.append(PrecedenceCheck(
            "A1/settlement-engine-honours-override",
            got_eng == BRANCH_DECREASE,
            f"结算引擎在 r={PROBE_R_LOW} 判 {got_eng}（期望 {BRANCH_DECREASE}）"))
    except Exception as exc:                    # noqa: BLE001
        checks.append(PrecedenceCheck("A1/settlement-engine-honours-override",
                                      False, f"结算引擎调用失败：{exc}"))

    # A2 来源留痕
    params = resolve_parameters(card, CONTRACT_OVERRIDE, source_label="contract")
    srcs = dict(params.sources)
    checks.append(PrecedenceCheck(
        "A2/source-recorded",
        srcs.get("decrease_threshold") == "contract"
        and srcs.get("increase_threshold") == "contract",
        f"来源留痕 sources={srcs.get('decrease_threshold')}"
        f"/{srcs.get('increase_threshold')}（期望 contract）"))

    # A3 分层互锁不可绕过
    try:
        resolve_parameters(card, {"decrease_threshold": 0.7},
                           source_label="standard")
        ok3, d3 = False, "Standard 层标签下偏离实现常量未被拒绝——互锁被绕过"
    except PricingCardError as exc:
        ok3, d3 = True, f"Standard 层标签下偏离被拒：{exc}"
    checks.append(PrecedenceCheck("A3/standard-layer-interlock", ok3, d3))

    # A4 未登记键不得静默忽略
    try:
        resolve_parameters(card, {"not_registered_key": 1}, source_label="contract")
        ok4, d4 = False, "未登记 override 键被静默忽略（沉默不是断言）"
    except PricingCardError as exc:
        ok4, d4 = True, f"未登记键被拒：{exc}"
    checks.append(PrecedenceCheck("A4/unregistered-key-blocked", ok4, d4))

    return RulePrecedenceReport(tuple(checks))


# =========================================================================
# 规则集切换：2013 与 2024 同一输入下输出必须可区分（两层判据）
# =========================================================================
@dataclass(frozen=True)
class SwitchLayer:
    layer_id: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"layer_id": self.layer_id, "status": self.status,
                "detail": self.detail}


@dataclass(frozen=True)
class RuleSetSwitchReport:
    layers: tuple[SwitchLayer, ...]

    @property
    def status(self) -> str:
        if not self.layers:
            return STATUS_BLOCKED
        order = (STATUS_FAIL, STATUS_BLOCKED, STATUS_WARN, STATUS_SKIP, STATUS_PASS)
        for s in order:
            if any(ly.status == s for ly in self.layers):
                return s
        return STATUS_BLOCKED                      # pragma: no cover

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status,
                "layers": [ly.to_dict() for ly in self.layers]}


def check_ruleset_switch(*, rho_probe: float = 0.01,
                         delta: float = 1e-9,
                         clone_2024: bool = False,
                         clone_meta_field: str | None = None,
                         ) -> RuleSetSwitchReport:
    """L1（数值指纹，仅 FULL）+ L2（元信息，任何作用域）+ SEGMENT 退化登记。

    ``clone_2024=True`` 即注入 MR-01（2024 的公式直接复用 2013 实现）；
    ``clone_meta_field`` 即注入 MR-02/MR-03（把 2024 的某元信息字段抄成 2013 的）
    ——该注入**只动元信息、不动公式**，因此数值层 L1 完全不变，
    只有 L2 能抓到它：这正是「两层判据必须拆开」的可执行证据。
    """
    from ..contracts.rule_sets.gb50500_2013 import GB50500_2013_RuleSet
    from ..contracts.rule_sets.gbt50500_2024 import GBT50500_2024_RuleSet

    rs13 = GB50500_2013_RuleSet()
    rs24 = GBT50500_2024_RuleSet()
    layers: list[SwitchLayer] = []

    # ---- L1 数值指纹（仅 FULL 有鉴别力）---------------------------------
    jump_13 = rs13.fingerprint(rho_probe=rho_probe, delta=delta)
    if clone_2024:
        jump_24_full = jump_13               # MR-01：公式被复制
    else:
        jump_24_full = rs24.fingerprint(rho_probe=rho_probe, delta=delta, scope="FULL")
    expected = abs(1.15 * rho_probe)
    sep = abs(jump_24_full - jump_13)
    l1_ok = sep >= 0.5 * expected
    layers.append(SwitchLayer(
        "L1_NUMERIC@FULL",
        STATUS_PASS if l1_ok else STATUS_FAIL,
        f"阈值处跳变量：2013={jump_13:.6g}，2024(FULL)={jump_24_full:.6g}，"
        f"分离度={sep:.6g}（要求 ≥ {0.5 * expected:.6g}）"))
    l1_seg = abs(rs24.fingerprint(rho_probe=rho_probe, delta=delta,
                                  scope="SEGMENT") - jump_13)
    if l1_seg < 0.5 * expected:
        layers.append(SwitchLayer(
            "L1_NUMERIC@SEGMENT",
            STATUS_WARN,
            f"数值指纹**退化**：SEGMENT 下两版同形（分离度 {l1_seg:.6g}）。"
            "本格不得记作『已区分』（沉默不是断言）；区分依据退回 L2 与两版"
            "代码路径独立性。已登记于 selector.ruleset_self_test.advisories。"))

    # ---- L2 元信息（与作用域无关）---------------------------------------
    fields = ("p1_source", "supported_scopes", "standard_code", "legal_basis")
    vals_13 = {f: getattr(rs13, f) for f in fields}
    vals_24 = {f: getattr(rs24, f) for f in fields}
    if clone_meta_field:
        vals_24[clone_meta_field] = vals_13[clone_meta_field]
    missing = [f for f in fields if not vals_13[f] or not vals_24[f]]
    same = [f for f in fields if vals_13[f] == vals_24[f]]
    l2_ok = not missing and not same
    layers.append(SwitchLayer(
        "L2_META",
        STATUS_PASS if l2_ok else STATUS_FAIL,
        (f"两版元信息逐项不同：{{"
         + "；".join(f"{f}: {vals_13[f]} vs {vals_24[f]}"
                     for f in fields if vals_13[f] != vals_24[f])
         + "}")
        if l2_ok else
        (f"元信息缺失 {missing}；两版相同字段 {same}——"
         "数值同形时必须靠此层可区分")))
    return RuleSetSwitchReport(tuple(layers))


# =========================================================================
# 汇总
# =========================================================================
def run_matrix(*, spec: Mapping[str, Any] | None = None,
               judge_fn: JudgeFn | None = None,
               with_mutants: bool = True,
               with_precedence: bool = True,
               with_switch: bool = True) -> MatrixRun:
    """跑完整矩阵并汇总结论（最严：FAIL > BLOCKED > WARN > SKIP > PASS）。"""
    spec = spec if spec is not None else load_matrix_spec()
    cases = enumerate_cases(spec)
    coverage = audit_coverage(spec, cases)
    cr, ag = evaluate_matrix(judge_fn, spec=spec, cases=cases)
    mutants = ((audit_mutants(spec, cases) + audit_mode_mutants(spec))
               if with_mutants else ())
    prec = check_rule_precedence() if with_precedence else None
    sw = check_ruleset_switch() if with_switch else None

    if coverage.status == STATUS_BLOCKED:
        verdict = STATUS_BLOCKED
    elif (any(c.applicable and not c.matched for c in cr)
          or any(not a.matched for a in ag)
          or any(not m.killed for m in mutants)
          or (prec is not None and prec.status != STATUS_PASS)
          or (sw is not None and sw.status == STATUS_FAIL)):
        verdict = STATUS_FAIL
    elif sw is not None and sw.status == STATUS_WARN:
        verdict = STATUS_WARN
    else:
        verdict = STATUS_PASS
    return MatrixRun(verdict, coverage, cr, ag, mutants, prec, sw)
