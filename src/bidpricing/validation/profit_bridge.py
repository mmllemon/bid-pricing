"""T00-12 利润口径桥接表的机器可执行校验。

判据 PB-01～PB-07，语义沿用校验层六态（ADR-0008 五态 + ADR-0013 INFO）：

* **BLOCKED**：缺失会让**算式算错**——目标层级不唯一、税口径未定、
  单项亏损政策未声明。这三样任一不确定，求解出来的「最优」就没有定义。
* **FAIL**：写了但与别处冲突——桥接恒等式与 T00-06B 的总价分解不符，
  或差额项引用了不存在的层级，或**目标口径声明与实现不一致**（PB-07）。
* **WARN**：尚未冻结。
* **INFO**：留痕项。
* **SKIP**：判据所需制品/输入不存在——显式记录，不静默通过。

PB-07（ADR-0035）是**跨层对账**：``tax_caliber_of_objective`` 是报告层声明，
而目标函数由求解层（``solver.settlement_milp``）构造。只判声明时，
实现侧把收入折算成含税也能全绿——这正是被实证抓到的真实缺陷
（报告利润虚增「应交增值税」，且**不改变最优解**，故结果复核发现不了）。

本模块**不读真实样本**：需要数值对账的部分（PB-03）要求调用方显式传入
一个 :class:`~bidpricing.total_price.Partition`；不传则记 SKIP，
而不是「默认通过」。
"""

from __future__ import annotations

import json
from pathlib import Path

from .cost_basis import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_INFO,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    CostBasisReport,
    CostCheckItem,
    _bad,
    _ok,
    _read,
)
from ..total_price import COMPETITIVE, FIXED_PRETAX, TAX, Partition

SPEC_NAME = "profit_bridge_spec.json"

#: 层级语义词表。前四种由本表定义；DECISION_SCOPE 表示「这里是决策发生的地方」。
LEVEL_KINDS: tuple[str, ...] = (
    "OBJECTIVE",
    "DECISION_SCOPE",
    "DERIVED",
    "DERIVED_FROM_PRICE_LEVEL",
    "EXOGENOUS_CONSTANT",
    "EXOGENOUS_LOCKED",
)

#: 每个层级行必须齐备的字段
REQUIRED_LEVEL_FIELDS: tuple[str, ...] = (
    "key", "label", "kind", "enters_objective", "is_objective",
    "formula", "source_of_truth",
)

#: 单项亏损处置词表。TOTAL_PROFIT_ONLY = 只约束总利润（本项目落值，ADR-0009）。
LOSS_POLICY_VOCABULARY: tuple[str, ...] = (
    "TOTAL_PROFIT_ONLY",
    "PER_ITEM_NO_LOSS",
    "PER_ITEM_FLOOR_AT_COST",
)

#: 与 T00-06B 必须一致的桥接恒等式
REQUIRED_IDENTITIES: tuple[str, ...] = ("B1", "B2", "B3")


def check_profit_bridge(
    config_dir: Path,
    partition: Partition | None = None,
    basis_declarations: dict | None = None,
) -> CostBasisReport:
    """执行 T00-12 全部判据。

    ``partition`` 给定时额外做 PB-03 的数值对账（桥接表 ↔ 总价分解同源同值）。
    """
    rep = CostBasisReport()
    spec = _read(config_dir, SPEC_NAME)
    if spec is None:
        rep.results.append(_bad(
            "PB-01", STATUS_SKIP,
            "利润口径桥接表缺失（profit_bridge_spec.json）——T00-12 未冻结，"
            "目标函数口径无从判定",
        ))
        return rep

    levels = spec.get("levels") or []
    by_key = {l.get("key"): l for l in levels if isinstance(l, dict)}

    # ---------------- PB-01 层级行字段齐备且取值合法 ----------------
    problems: list[str] = []
    for idx, lvl in enumerate(levels):
        if not isinstance(lvl, dict):
            problems.append(f"第 {idx} 行不是对象")
            continue
        lack = [f for f in REQUIRED_LEVEL_FIELDS if lvl.get(f) in (None, "")]
        if lack:
            problems.append(f"{lvl.get('key') or f'第{idx}行'} 缺字段 {lack}")
        if lvl.get("kind") not in LEVEL_KINDS:
            problems.append(
                f"{lvl.get('key')} 的 kind={lvl.get('kind')!r} 不在词表 {list(LEVEL_KINDS)}"
            )
        for flag in ("enters_objective", "is_objective"):
            if not isinstance(lvl.get(flag), bool):
                problems.append(
                    f"{lvl.get('key')} 的 {flag} 必须是布尔（不得用字符串）"
                )

    dup = sorted({l.get("key") for l in levels
                  if isinstance(l, dict)
                  and [x.get("key") for x in levels].count(l.get("key")) > 1})
    if dup:
        problems.append(f"层级 key 重复：{dup}")

    if problems:
        rep.results.append(_bad("PB-01", STATUS_FAIL, "；".join(problems), problems))
    else:
        rep.results.append(_ok(
            "PB-01",
            f"{len(levels)} 个层级行字段齐备，kind 取值合法（"
            f"{sorted({l['kind'] for l in levels})}）",
        ))

    # ---------------- PB-02 目标层级唯一 ----------------
    obj = spec.get("objective") or {}
    obj_key = obj.get("level")
    operands = list(obj.get("operands") or [])
    participate = {
        l.get("key") for l in levels
        if isinstance(l, dict) and l.get("enters_objective") is True
    }
    is_objective_rows = [
        l.get("key") for l in levels
        if isinstance(l, dict) and l.get("is_objective") is True
    ]
    kind_objective_rows = [
        l.get("key") for l in levels
        if isinstance(l, dict) and l.get("kind") == "OBJECTIVE"
    ]

    obj_problems: list[str] = []

    # ① 目标本身唯一，且与 objective.level 一致
    if len(is_objective_rows) != 1:
        obj_problems.append(
            f"is_objective=true 的行有 {len(is_objective_rows)} 个"
            f"（{is_objective_rows}）——目标函数必须恰好一个，"
            "否则无法回答「算的是哪个口径的利润」"
        )
    if obj_key not in by_key:
        obj_problems.append(f"objective.level={obj_key!r} 不是已声明的层级")
    elif is_objective_rows and is_objective_rows[0] != obj_key:
        obj_problems.append(
            f"objective.level={obj_key!r} 与标记行 {is_objective_rows[0]!r} 不一致"
            "——两处各说各话"
        )
    # kind=OBJECTIVE 的行必须就是目标本身（防漏标导致静默变派生量）
    stray = [k for k in kind_objective_rows if k not in is_objective_rows]
    if stray:
        obj_problems.append(f"kind=OBJECTIVE 但未标 is_objective 的行：{stray}")

    # ② 参与集合必须显式等于 {目标} ∪ 声明的操作数
    expected = {obj_key} | set(operands)
    if participate != expected:
        obj_problems.append(
            f"参与目标函数的层级与声明不符：标记 {sorted(participate)} vs "
            f"声明 {sorted(expected)}（目标 ∪ 操作数）——"
            "多标会把常数项误当决策项，少标会把决策项漏出目标"
        )
    unknown_ops = [k for k in operands if k not in by_key]
    if unknown_ops:
        obj_problems.append(f"objective.operands 引用未声明层级：{unknown_ops}")

    if obj.get("sense") not in ("MAXIMIZE", "MINIMIZE"):
        obj_problems.append(f"objective.sense={obj.get('sense')!r} 非法")

    if obj_problems:
        rep.results.append(_bad("PB-02", STATUS_BLOCKED, "；".join(obj_problems),
                                obj_problems))
    else:
        rep.results.append(_ok(
            "PB-02",
            f"目标层级唯一：{obj_key}（{obj.get('sense')}），"
            f"操作数 {operands}；其余 {len(levels) - len(participate)} 行为派生/外生量",
        ))

    # ---------------- PB-03 与 T00-06B 同源同值 ----------------
    ids = {i.get("id"): i for i in (spec.get("identities") or [])
           if isinstance(i, dict)}
    miss_ids = [k for k in REQUIRED_IDENTITIES if k not in ids]
    p3: list[str] = []
    if miss_ids:
        p3.append(f"缺恒等式 {miss_ids}——桥接表与总价分解对不上")

    # 差额项必须指向已声明层级（防「差额构成」写成一句形容词）
    diff_terms = ((spec.get("reported_vs_objective") or {}).get("difference_terms") or [])
    unknown_terms = [t for t in diff_terms if t not in by_key]
    if not diff_terms:
        p3.append("reported_vs_objective.difference_terms 为空——"
                  "「算税前、报含税」这个失效模式正是靠它显式化")
    elif unknown_terms:
        p3.append(f"差额项引用未声明层级：{unknown_terms}")

    if p3:
        rep.results.append(_bad("PB-03", STATUS_FAIL, "；".join(p3), p3))
    elif partition is None:
        rep.results.append(_bad(
            "PB-03", STATUS_SKIP,
            "结构判据通过，但未提供总价划分（Partition）——"
            "数值对账（B1/B2 在真实数据上是否成立）未执行，不视为通过",
        ))
    else:
        # 两个**非恒真**的对账（第一版写成了恒真式，被测试抓到）：
        #   ① 三桶之和 vs **外部给定**的总价（若只与派生总价比，恒等于 0）
        #   ② 声明的税金行 vs 由计税基数派生的税金（防两处各算一遍）
        stated = partition.declared_total
        additive = (partition.bucket_sum(COMPETITIVE)
                    + partition.bucket_sum(FIXED_PRETAX)
                    + partition.bucket_sum(TAX))
        n1 = abs(additive - (stated if stated is not None else partition.total))
        n2 = abs(partition.bucket_sum(TAX) - partition.tax)
        if n1 > 0.01 or n2 > 0.01:
            rep.results.append(_bad(
                "PB-03", STATUS_FAIL,
                f"桥接恒等式与总价分解不符：三桶之和与总价差 {n1:.4f} 元、"
                f"声明税金与派生税金差 {n2:.4f} 元",
                [f"三桶之和 {additive:,.2f} vs 总价 "
                 f"{(stated if stated is not None else partition.total):,.2f}",
                 f"税金行 {partition.bucket_sum(TAX):,.2f} vs 派生 {partition.tax:,.2f}"],
            ))
        else:
            anchor = "外部给定总价" if stated is not None else "派生总价（无外部锚点）"
            rep.results.append(_ok(
                "PB-03",
                f"与 T00-06B 同源同值：三桶之和 = {anchor}（残差 {n1:.4f}）、"
                f"税金行 = 派生税金（残差 {n2:.4f}）；差额项 {diff_terms} 均为已声明层级",
            ))

    # ---------------- PB-04 税口径一致 ----------------
    caliber = spec.get("tax_caliber_of_objective")
    basis = basis_declarations
    if basis is None:
        basis = _read(config_dir, "basis_declarations.json")
    basis = basis if isinstance(basis, dict) else {}

    # 只取两侧声明；**key 完全缺失 = 未定态**，不得用默认值填
    sides = {k: basis.get(k) for k in ("cap_tax_scope", "cost_tax_scope")}

    if not caliber:
        rep.results.append(_bad(
            "PB-04", STATUS_BLOCKED,
            "tax_caliber_of_objective 未声明——税前/含税口径未定，"
            "利润数字没有含义",
        ))
    elif caliber != "EXCL_VAT":
        rep.results.append(_bad(
            "PB-04", STATUS_FAIL,
            f"目标口径 {caliber} 与既有声明不符：c_i 与 p_i 均不含增值税"
            "（GB/T 50500-2024 2.0.8），含税口径下二者不可直接相减",
        ))
    elif any(v is None for v in sides.values()):
        missing = sorted(k for k, v in sides.items() if v is None)
        rep.results.append(_bad(
            "PB-04", STATUS_BLOCKED,
            f"basis_declarations 中税口径未定（key 完全缺失）：{missing}——"
            "未定态不得用默认值填（D08 口径）",
        ))
    elif any(v != "EXCL_VAT" for v in sides.values()):
        bad_sides = {k: v for k, v in sides.items() if v != "EXCL_VAT"}
        rep.results.append(_bad(
            "PB-04", STATUS_FAIL, f"与 basis_declarations 冲突：{bad_sides}",
        ))
    else:
        rep.results.append(_ok(
            "PB-04",
            "税口径一致：目标函数 EXCL_VAT ↔ basis_declarations 两侧均不含增值税"
            "（机制层已定，不重复索取声明——ADR-0011）",
            [f"{k}={v}" for k, v in sorted(sides.items())],
        ))

    # ---------------- PB-05 单项亏损政策已声明 ----------------
    loss = spec.get("single_item_loss_policy") or {}
    val = loss.get("declared")
    if val is None:
        rep.results.append(_bad(
            "PB-05", STATUS_BLOCKED,
            "单项亏损处置未声明——「目标只约束总利润」还是「逐项不得亏损」"
            "决定可行域形状；未声明则最优解没有定义",
        ))
    elif val not in LOSS_POLICY_VOCABULARY:
        rep.results.append(_bad(
            "PB-05", STATUS_FAIL,
            f"亏损政策 {val!r} 不在词表 {list(LOSS_POLICY_VOCABULARY)}",
        ))
    elif not loss.get("basis"):
        rep.results.append(_bad(
            "PB-05", STATUS_WARN,
            f"亏损政策 {val} 已声明但未注明依据——须能追溯到裁定或规范",
        ))
    else:
        rep.results.append(_ok("PB-05", f"单项亏损政策：{val}"))

    # ---------------- PB-06 冻结时点 ----------------
    if spec.get("frozen_at"):
        rep.results.append(_ok("PB-06", f"已冻结于 {spec['frozen_at']}"))
    else:
        rep.results.append(_bad(
            "PB-06", STATUS_WARN,
            "尚未冻结（冻结时点：Gate 0b 之前）——冻结前不得进入 WP4 求解层",
        ))

    # ---------------- PB-07 目标口径：声明 ↔ 实现 跨层对账 ----------------
    # ★ 为什么必须有这条：``tax_caliber_of_objective`` 是**报告层**的声明，而目标
    #   函数由**求解层**（solver.settlement_milp）构造。同一条口径判据分居两层，
    #   若只判声明，实现侧偷偷把收入折算成含税也能全绿——正是 ADR-0035 抓到的
    #   真实缺陷（收入侧乘 1+vat、成本侧只扣进项，报告利润虚增「应交增值税」）。
    #   故此处把两层的**具名量**拉在一起对账：声明口径 vs 实现常量 + 收入侧系数。
    from ..solver import settlement_milp as _sm  # 局部导入：避免校验层↔求解层的顶层耦合
    impl_caliber = getattr(_sm, "OBJECTIVE_CALIBER", None)
    probe_rate = 0.13  # 任意非零税率即可辨真假：EXCL_VAT 下系数必须与税率无关
    if not caliber:
        # 声明缺失时 PB-04 已 BLOCK；此处挂起，不与 PB-04 争最严（避免同一缺失报两次）
        rep.results.append(_bad(
            "PB-07", STATUS_SKIP,
            "声明口径缺失（PB-04 已阻断），跨层对账无从进行——挂起"))
    else:
        try:
            impl_factor = float(_sm.objective_revenue_factor(probe_rate))
        except Exception as exc:  # noqa: BLE001 - 实现侧不可调用即视为不可对账
            rep.results.append(_bad(
                "PB-07", STATUS_BLOCKED,
                f"目标收入侧口径系数不可探测（objective_revenue_factor）：{exc}——"
                "实现口径无法与声明对账，口径错层只能靠读代码发现"))
        else:
            if impl_caliber != caliber:
                rep.results.append(_bad(
                    "PB-07", STATUS_FAIL,
                    f"目标口径跨层不一致：声明 tax_caliber_of_objective={caliber!r}，"
                    f"实现 OBJECTIVE_CALIBER={impl_caliber!r}（求解层与报告层必须同名同义）"))
            elif caliber == "EXCL_VAT" and abs(impl_factor - 1.0) > 1e-12:
                rep.results.append(_bad(
                    "PB-07", STATUS_FAIL,
                    f"目标收入侧仍按含税折算：objective_revenue_factor({probe_rate})={impl_factor!r}，"
                    "EXCL_VAT 口径下必须恒为 1.0——收入折算为含税、成本只扣进项，"
                    "二者相减会让报告利润虚增 vat×Σ结算收入（ADR-0035）"))
            else:
                rep.results.append(_ok(
                    "PB-07",
                    f"目标口径跨层一致：声明 {caliber} ↔ 实现 {impl_caliber}，"
                    f"收入侧系数 {impl_factor}（与税率无关）"))

    for item in spec.get("open_items") or []:
        rep.results.append(_bad("PB-INFO", STATUS_INFO, str(item)))

    return rep
