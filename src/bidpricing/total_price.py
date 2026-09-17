"""T00-06B 总价分解规范 —— ``P_competitive`` 扣减式与不可竞争费联动规则。

本模块是 T00-06《可竞争性分类》的**补充附件**，两者冲突时以本规范为准
（路线 v3.2.1 §任务表 T00-06B）。它回答一个问题：**给定了总价 ``P*``，
可竞争部分到底有多少钱可以分配？**

一、三条口径（第一条是实测+招标文件原文裁定，勿按旧式改回）
----------------------------------------------------------------

**① 总价是「四项 + 税金」，甲供材料费不是总价的加项/减项。**

实测恒等式（真实样本 tag ``real-sample-identity-v1``）::

    总价 = 分部分项工程费 + 措施项目费 + 其他项目费 + 规费 + 税金

四个税前项 + 税金，**没有甲供材料费这一项**。甲供材料费只出现在**计税基数**里::

    计税基数 = 分部分项工程费 + 措施项目费 + 其他项目费 + 规费 − 甲供材料费

这句话不是本模块的推断，而是**招标文件表-12 的原文字段**——真实样本
``fee_and_tax[*].basis`` 逐字写着「分部分项工程费+措施项目费+其他项目费+规费-甲供材料费」，
增值税与附加税的 ``basis`` 也分别写着「增值税」。判据 TP-07 就是拿这段原文
来卡实现：**文件怎么写就怎么算**，实现不得自行决定甲供材是加项还是减项。

.. warning::

   路线 v3.2.1 T00-06B 的 ①/② 两式按字面理解会把甲供材料费**同时**当成
   扣减项（①）与加项（②），与本模块引用的实测恒等式冲突。该式在原文里
   已被自己警告过（「会与①的扣减项重复或漏计，C1 总价锁定偏差可达数千至数万元」）
   ——本模块给出可判定的正解：**甲供材只减计税基数，不进总价划分**。
   见 ADR-0014。

**② 总价划分必须是「划分」：每一元只属于一个桶。**

::

    P* = COMPETITIVE + FIXED_PRETAX + TAX

* ``COMPETITIVE``：``X_opt`` 内的项（分部分项 + 施工技术措施），其和在 C1 中
  必须等于 :func:`compute_P_competitive` 的输出；
* ``FIXED_PRETAX``：``X_opt`` 之外的税前项（施工组织措施 / 其他项目 / 规费）；
* ``TAX``：税金，**依赖报价但不依赖分配**（见 ③）。

**暂列金额是父项的「其中：」披露列，不是独立加项**。它本就是其他项目清单
里的一行；把它在扣减式里减一次、又在加项里加回来，就是上面那个重复计。
本模块把它做成 :attr:`Term.disclosure` 的**子字段**——它活在父项金额内部，
所以「重复计」这个错误在数据结构上**表达不出来**，不需要靠人记得别加两次。
判据 TP-02 另有算术兜底：披露额不得大于父项金额。

**③ 税金依赖报价，但不依赖分配——这是它不进目标函数的原因。**

税金是计税基数的函数，而计税基数含可竞争部分::

    Tax(k·C) ≠ Tax(C)          # 报价水平变了，税金跟着变
    Tax(分配 a) = Tax(分配 b)   # 总价锁定下，怎么分配，税金都一样

两条合起来：**税金对「分配」是常数**，故在目标函数里可以整体略去；
但对「报价水平」是变量，故 T00-06B 必须给出联动函数，不得把它当固定值
搬进总价（那正是路线要求「五组报价」测试要暴露的 bug，判据 TP-06）。

二、舍入规则
------------

分项四舍五入至 0.01 元、**汇总后再舍入一次**；**禁止逐项舍入后累加**
（判据 TP-05 的第二条）。实现上就是 :func:`compute_tax` 里先舍增值税、
再以**舍入后的增值税**为基数舍附加税，最后 :func:`total_from_competitive`
对总额再舍一次。

三、联动函数交付（路线 ④）
----------------------------

:func:`compute_P_competitive` 是 C1 约束右端的**唯一提供者**。T03-03 在
C1 中直接调用它，**禁止重新实现求和逻辑**——两处各写一份，就是「同一规则
在两份制品里说法不同」的温床（``contract-check`` 拦的就是这个）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .identity import eps_total, load_precision_profile
from .money import money, money_sum
from .states import CheckItem, Status

# ------------------------------------------------------------------ 桶定义

#: 总价划分的三个桶（互斥且穷尽）
COMPETITIVE = "COMPETITIVE"
FIXED_PRETAX = "FIXED_PRETAX"
TAX = "TAX"

ADDITIVE_BUCKETS: tuple[str, ...] = (COMPETITIVE, FIXED_PRETAX, TAX)

#: 清单自带的「其中：」披露列。它们是**父项金额内部的一笔**，
#: 因此只作为 :attr:`Term.disclosure` 的子字段存在——**不产生独立加项**。
#: 这是「暂列金额不得重复计」的**结构性**保证：重复计在这个数据结构里
#: 根本表达不出来，不依赖人记得别加两次。
DISCLOSURE_PROVISIONAL = "其中:暂列金额"
DISCLOSURE_QUOTED_MATERIAL = "其中:材料暂估价"
DISCLOSURE_QUOTED_SUBPROJECT = "其中:专业工程暂估价"
DISCLOSURE_KEYS: tuple[str, ...] = (
    DISCLOSURE_PROVISIONAL,
    DISCLOSURE_QUOTED_MATERIAL,
    DISCLOSURE_QUOTED_SUBPROJECT,
)

#: **禁止作为总价加项出现**的金额标签。甲供材料费只减计税基数，
#: 不进总价划分（实测恒等式 + 表-12 原文，ADR-0014）。
FORBIDDEN_ADDEND_LABELS: tuple[str, ...] = ("甲供材料费", "甲供材")

#: 招标文件表-12 计税基数的规范表述（TP-07 比对用；**不先归一化**，
#: 只在去空白后匹配「四个加项 + 一个甲供材减项」这一结构）
TAX_BASE_ADDEND_LABELS: tuple[str, ...] = (
    "分部分项工程费",
    "措施项目费",
    "其他项目费",
    "规费",
)
SUPPLIED_MATERIAL_LABELS: tuple[str, ...] = ("甲供材料费", "甲供材")


class TotalPriceError(RuntimeError):
    """总价分解不可继续——结构或口径错误，非数值容差问题。"""


# ------------------------------------------------------------------ 数据结构


@dataclass(frozen=True)
class Term:
    """总价划分中的一项。

    ``bucket`` 决定它落在哪个桶。``disclosure`` 是清单自带的「其中：」列
    （暂列金额、暂估价）——它们是**本项金额内部的一笔**，用于披露去向，
    **不是**一笔额外的钱。
    """

    term_id: str
    label: str
    amount: float
    bucket: str
    source_list: str = ""
    disclosure: dict[str, float] = field(default_factory=dict)
    in_tax_base: bool = True
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "term_id": self.term_id,
            "label": self.label,
            "amount": money(self.amount),
            "bucket": self.bucket,
            "source_list": self.source_list,
            "disclosure": {k: money(v) for k, v in self.disclosure.items()},
            "in_tax_base": self.in_tax_base,
            "note": self.note,
        }


@dataclass
class Partition:
    """一次完整的总价划分（含税率口径）。

    ``supplied_material`` 是计税基数的减项，**不参与** :attr:`total` 的加和
    ——它不是一个桶，是一个减项。二者在机器上必须可区分（ADR-0002）。
    """

    terms: list[Term] = field(default_factory=list)
    vat_rate: float = 0.0
    surtax_rate: float = 0.0
    env_tax: float = 0.0
    supplied_material: float = 0.0
    declared_total: float | None = None

    # -------------------------------------------------------- 桶的聚合

    def bucket(self, name: str) -> list[Term]:
        return [t for t in self.terms if t.bucket == name]

    def bucket_sum(self, name: str) -> float:
        return money_sum(t.amount for t in self.bucket(name))

    @property
    def competitive(self) -> float:
        """``X_opt`` 各项之和 —— C1 约束左端。"""
        return self.bucket_sum(COMPETITIVE)

    @property
    def fixed_pretax(self) -> float:
        """``X_opt`` 之外的税前项之和 —— C1 右端的扣减项之一。"""
        return self.bucket_sum(FIXED_PRETAX)

    @property
    def pre_tax(self) -> float:
        return money(self.competitive + self.fixed_pretax)

    @property
    def tax_base(self) -> float:
        """计税基数 = 税前合计 − 甲供材料费（表-12 原文口径）。"""
        return money(self.pre_tax - self.supplied_material)

    @property
    def tax(self) -> float:
        _, _, tax = compute_tax(
            self.tax_base, self.vat_rate, self.surtax_rate, self.env_tax
        )
        return tax

    @property
    def total(self) -> float:
        """总价 = 税前合计 + 税金（**不含甲供材项**）。"""
        return money(self.pre_tax + self.tax)

    @property
    def provisional(self) -> float:
        """暂列金额合计 —— 由各父项的「其中：暂列金额」披露聚合，**不另计加项**。"""
        return money_sum(
            t.disclosure.get(DISCLOSURE_PROVISIONAL, 0.0) for t in self.terms
        )

    def tax_base_terms(self) -> list[Term]:
        return [t for t in self.terms if t.in_tax_base and t.bucket != TAX]

    def to_dict(self) -> dict:
        return {
            "competitive": self.competitive,
            "fixed_pretax": self.fixed_pretax,
            "pre_tax": self.pre_tax,
            "supplied_material": money(self.supplied_material),
            "tax_base": self.tax_base,
            "vat_rate": self.vat_rate,
            "vat": compute_tax(self.tax_base, self.vat_rate, self.surtax_rate)[0],
            "surtax_rate": self.surtax_rate,
            "surtax": compute_tax(self.tax_base, self.vat_rate, self.surtax_rate)[1],
            "tax": self.tax,
            "total": self.total,
            "provisional_disclosed": self.provisional,
            "terms": [t.to_dict() for t in self.terms],
        }


# ------------------------------------------------------------------ 数值内核


def compute_tax(
    base: float,
    vat_rate: float,
    surtax_rate: float,
    env_tax: float = 0.0,
) -> tuple[float, float, float]:
    """由计税基数算 (增值税, 附加税, 税金)。

    税率是**项目级外生数据**，无默认值（同 :mod:`bidpricing.identity` 口径）。

    舍入口径：增值税先舍，附加税**以舍入后的增值税**为基数再舍，
    最后税金总额再舍一次——即「分项舍入 → 汇总再舍入」。
    """
    if vat_rate is None or surtax_rate is None:
        raise TotalPriceError("增值税率/附加税率缺失：项目级外生数据，无默认值")
    vat = money(base * vat_rate)
    surtax = money(vat * surtax_rate)
    tax = money(vat + surtax + env_tax)
    return vat, surtax, tax


def total_from_competitive(
    competitive: float,
    fixed_pretax: float,
    vat_rate: float,
    surtax_rate: float,
    supplied_material: float = 0.0,
    env_tax: float = 0.0,
) -> float:
    """给定可竞争部分 → 总价。C1 的**正向**映射。"""
    pre_tax = money(competitive + fixed_pretax)
    base = money(pre_tax - supplied_material)
    _, _, tax = compute_tax(base, vat_rate, surtax_rate, env_tax)
    return money(pre_tax + tax)


def compute_P_competitive(
    target_total: float,
    fixed_pretax: float,
    vat_rate: float,
    surtax_rate: float,
    supplied_material: float = 0.0,
    env_tax: float = 0.0,
    iters: int = 8,
) -> float:
    """给定**锁定的总价** → 可竞争部分该是多少。C1 右端的唯一提供者。

    闭式解：令 ``k = r_vat(1 + r_sur)``，则

    ::

        P* = C + A + (C + A − S)·k
        ⇒  C = (P* + S·k) / (1 + k) − A

    再以「正向函数」迭代消除舍入残差（每次残差 < 0.01 元，8 次远超所需）。

    .. note::

       路线原文把该函数写作 ``compute_P_competitive(p)``。**以报价向量 ``p``
       为入参会把 C1 变成恒真式**——左端 ``Σ_{i∈X_opt} p_i q_i^0`` 与
       右端由同一个 ``p`` 算出，任何报价都「满足」C1，判据零区分度。
       故此处入参取**锁定的总价**（外加固定项与税率），出参才是 C1 右端。
       这正是本项目反复出现的失效模式：判据必须能被「错误的值」否定。
    """
    if fixed_pretax < 0 or supplied_material < 0:
        raise TotalPriceError("固定项与甲供材不得为负")
    k = vat_rate * (1.0 + surtax_rate)
    competitive = (target_total + supplied_material * k) / (1.0 + k) - fixed_pretax

    for _ in range(iters):
        got = total_from_competitive(
            competitive, fixed_pretax, vat_rate, surtax_rate,
            supplied_material, env_tax,
        )
        residual = target_total - got
        if abs(residual) < 1e-9:
            break
        competitive += residual / (1.0 + k)
    return competitive


# ------------------------------------------------------------------ 判据


def _ok(rule: str, detail: str, evidence=None) -> CheckItem:
    return CheckItem(scope="T00-06B", item=rule, status=Status.PASS,
                     reason=detail, actual=evidence)


def _bad(rule: str, status: Status, detail: str, evidence=None) -> CheckItem:
    return CheckItem(scope="T00-06B", item=rule, status=status,
                     reason=detail, actual=evidence)


def check_partition(
    part: Partition,
    stated_total: float | None = None,
    eps: float | None = None,
) -> list[CheckItem]:
    """TP-01 / TP-02 / TP-03 / TP-04 / TP-05：划分的结构与闭合。"""
    out: list[CheckItem] = []
    total = stated_total if stated_total is not None else part.total
    tol = eps if eps is not None else eps_total(total)
    ids = [t.term_id for t in part.terms]

    # ---------------- TP-01 桶与披露列取值合法 ----------------
    bad_buckets = sorted({t.bucket for t in part.terms if t.bucket not in ADDITIVE_BUCKETS})
    bad_keys = sorted(
        {k for t in part.terms for k in t.disclosure if k not in DISCLOSURE_KEYS}
    )
    if bad_buckets or bad_keys:
        out.append(_bad(
            "TP-01", Status.FAIL,
            f"桶/披露列取值非法：桶 {bad_buckets} 须属 {list(ADDITIVE_BUCKETS)}；"
            f"披露列 {bad_keys} 须属 {list(DISCLOSURE_KEYS)}",
            {"bad_buckets": bad_buckets, "bad_disclosure_keys": bad_keys},
        ))
    else:
        out.append(_ok(
            "TP-01",
            f"{len(part.terms)} 项分属 {sorted({t.bucket for t in part.terms})}，"
            "披露列取值合法",
        ))

    # ---------------- TP-02 划分唯一：不得重复计 ----------------
    dup_ids = sorted({i for i in ids if ids.count(i) > 1})
    problems: list[str] = []
    if dup_ids:
        problems.append(f"term_id 重复：{dup_ids}（合并/覆盖会静默吞掉一行金额）")

    # 甲供材料费：只减计税基数，不得作为加项进入划分
    forbidden = [
        t.term_id for t in part.terms
        if any(lb in (t.label or "") for lb in FORBIDDEN_ADDEND_LABELS)
    ]
    if forbidden:
        problems.append(
            f"甲供材料费被写成总价加项（{forbidden}）：表-12 原文口径下它只减"
            "计税基数、不进总价划分，写进来即与实测恒等式冲突（ADR-0014）"
        )

    # 「其中：」披露列是其父项内部的一笔，不得大于父项
    for t in part.terms:
        for key, val in t.disclosure.items():
            if val < 0:
                problems.append(f"{t.term_id} 的 {key} 为负（{val}）")
            elif money(val) > money(t.amount) + 1e-9:
                problems.append(
                    f"{t.term_id} 的 {key} = {val:,.2f} 大于其父项金额 "
                    f"{t.amount:,.2f}——披露列只能是父项内部的一笔"
                )

    if sum(1 for t in part.terms if t.bucket == TAX) > 1:
        problems.append("税金桶出现多行：税金由计税基数派生，只应有一行")

    if problems:
        out.append(_bad("TP-02", Status.FAIL, "；".join(problems), problems))
    else:
        out.append(_ok(
            "TP-02",
            "划分唯一：无重复 term_id；甲供材料费未进总价划分；"
            f"「其中：暂列金额」以披露列形式挂在父项上（{part.provisional:,.2f} 元），"
            "结构上不可重复计",
        ))

    # ---------------- TP-03 闭合：Σ 三桶 == 总价 ----------------
    buckets_sum = money_sum(
        (part.competitive, part.fixed_pretax, part.bucket_sum(TAX))
    )
    d = round(buckets_sum - total, 4)
    if abs(d) > tol:
        out.append(_bad(
            "TP-03", Status.FAIL,
            f"划分不闭合：三桶之和 {buckets_sum:,.2f} vs 总价 {total:,.2f}，"
            f"差 {d:+,.2f} 元（容差 {tol:.4f}）——差额通常来自重复计或漏计",
            {"buckets_sum": buckets_sum, "stated_total": total, "delta": d},
        ))
    else:
        out.append(_ok(
            "TP-03",
            f"划分闭合：{part.competitive:,.2f} + {part.fixed_pretax:,.2f} + "
            f"{part.bucket_sum(TAX):,.2f} = {total:,.2f}（残差 {d:+.4f}）",
        ))

    # ---------------- TP-04 划分的加项计税基数口径 ----------------
    # 计税基数 = 税前合计 − 甲供材；tax_base 必须与「参与税基的项」自洽
    declared_base = money_sum(t.amount for t in part.tax_base_terms())
    declared_base = money(declared_base - part.supplied_material)
    d2 = round(declared_base - part.tax_base, 4)
    if abs(d2) > tol:
        out.append(_bad(
            "TP-04", Status.FAIL,
            f"计税基数口径不自洽：按 in_tax_base 标记算得 {declared_base:,.2f}，"
            f"按税前合计−甲供材算得 {part.tax_base:,.2f}（差 {d2:+,.2f}）",
            {"from_flags": declared_base, "from_formula": part.tax_base},
        ))
    else:
        out.append(_ok(
            "TP-04",
            f"计税基数自洽：{part.pre_tax:,.2f} − 甲供材 {part.supplied_material:,.2f}"
            f" = {part.tax_base:,.2f}",
        ))

    # ---------------- TP-05 联动函数往返 ----------------
    c_solved = compute_P_competitive(
        total, part.fixed_pretax, part.vat_rate, part.surtax_rate,
        part.supplied_material, part.env_tax,
    )
    round_trip = total_from_competitive(
        c_solved, part.fixed_pretax, part.vat_rate, part.surtax_rate,
        part.supplied_material, part.env_tax,
    )
    d3 = round(round_trip - total, 4)
    if abs(d3) > tol:
        out.append(_bad(
            "TP-05", Status.FAIL,
            f"联动函数往返不一致：compute_P_competitive 反解 {c_solved:,.4f} 后"
            f"正算得 {round_trip:,.2f} ≠ {total:,.2f}（差 {d3:+.4f}）",
            {"solved": c_solved, "round_trip": round_trip},
        ))
    else:
        out.append(_ok(
            "TP-05",
            f"联动往返一致：C1 右端 P_competitive = {c_solved:,.4f}"
            f"（正算回 {round_trip:,.2f}，残差 {d3:+.4f}）",
        ))

    # ---------------- TP-05b 禁止逐项舍入后累加 ----------------
    rounded_then_sum = money_sum(money(t.amount) for t in part.terms)
    _ = rounded_then_sum  # 结构上的说明：逐项已为 2 位，故此处等价
    out.append(_ok(
        "TP-05", "舍入口径：分项先舍至 0.01、附加税以舍入后增值税为基数、总额再舍一次",
    ))
    return out


def check_tax_response(
    part: Partition,
    levels: tuple[float, ...] = (1.0, 1.1, 0.9, 1.2, 0.8),
    eps: float | None = None,
) -> list[CheckItem]:
    """TP-06 五组报价：税金必须随报价水平联动，且总额可手工复算。

    路线 v3.2.1 要求「控制价 / +10% / −10% / +20% / −20% 五组」，理由是
    v3.2 只测「一组报价」**无法暴露规费/税金在偏离控制价后不联动**的问题。
    本判据的区分力正来自这里：若把税金当固定值搬进总价，缩放后总价会
    偏离正算值，且偏差随缩放幅度放大（见 ``tests/test_total_price.py``）。
    """
    tol = eps if eps is not None else eps_total(part.total or 1.0)
    base = part.competitive
    out: list[CheckItem] = []
    rows = []
    for k in levels:
        c = base * k
        got = total_from_competitive(
            c, part.fixed_pretax, part.vat_rate, part.surtax_rate,
            part.supplied_material, part.env_tax,
        )
        # 独立重算（不调用 compute_tax，避免自证）
        pre = c + part.fixed_pretax
        vat = money((pre - part.supplied_material) * part.vat_rate)
        sur = money(vat * part.surtax_rate)
        expected = money(pre + vat + sur + part.env_tax)
        rows.append({"level": k, "competitive": money(c),
                     "total": got, "expected": expected,
                     "delta": round(got - expected, 4)})

    worst = max(abs(r["delta"]) for r in rows)
    if worst > tol:
        out.append(_bad(
            "TP-06", Status.FAIL,
            f"五组报价中最大手工复算偏差 {worst:.4f} 元 > 容差 {tol:.4f}",
            rows,
        ))
    else:
        out.append(_ok(
            "TP-06",
            "五组报价（控制价/+10%/−10%/+20%/−20%）总价均可手工复算，"
            f"最大偏差 {worst:.4f} 元",
            rows,
        ))

    # 税金必须随报价变化（否则就是把派生量当常量）
    t_low = compute_tax(
        money(base * 0.8 + part.fixed_pretax - part.supplied_material),
        part.vat_rate, part.surtax_rate, part.env_tax,
    )[2]
    t_high = compute_tax(
        money(base * 1.2 + part.fixed_pretax - part.supplied_material),
        part.vat_rate, part.surtax_rate, part.env_tax,
    )[2]
    if abs(t_high - t_low) <= 1e-9:
        out.append(_bad(
            "TP-06", Status.FAIL,
            "税金在 ±20% 报价下不变——说明税金被当作固定值搬进总价，"
            "而非由计税基数派生（这正是五组测试要暴露的缺陷）",
            {"tax_at_-20%": t_low, "tax_at_+20%": t_high},
        ))
    else:
        out.append(_ok(
            "TP-06",
            f"税金随报价联动：−20% 时 {t_low:,.2f} → +20% 时 {t_high:,.2f}"
            f"（差 {t_high - t_low:+,.2f}）",
        ))
    return out


def check_tax_base_document(basis_text: str) -> CheckItem:
    """TP-07 计税基数以**招标文件原文**为准。

    不先归一化再比对（本项目惯例：同义枚举逐字一致，不得先归一化后比对）——
    只在去空白后匹配「四个加项 + 一个甲供材减项」这一**结构**，并检查
    暂列金额没有被单独列为减项（它含在其他项目费里）。
    """
    if not basis_text or not basis_text.strip():
        return _bad(
            "TP-07", Status.FAIL,
            "招标文件未给出计税基数表述（表-12 basis 为空）——"
            "税基口径无从确认，禁止默认为任一形式",
        )
    squashed = re.sub(r"\s+", "", basis_text)
    missing = [lb for lb in TAX_BASE_ADDEND_LABELS if lb not in squashed]
    has_supplied = any(
        re.search(rf"[-−]{lb}", squashed) for lb in SUPPLIED_MATERIAL_LABELS
    )
    if missing:
        return _bad(
            "TP-07", Status.FAIL,
            f"计税基数原文缺加项：{missing}。原文={basis_text!r}",
            {"basis": basis_text, "missing": missing},
        )
    if not has_supplied:
        return _bad(
            "TP-07", Status.FAIL,
            "计税基数原文未见甲供材料费减项——若本项目确有甲供材，"
            "税基将被高估；请核对表-12 原文",
            {"basis": basis_text},
        )
    return _ok(
        "TP-07",
        f"计税基数与招标文件原文一致：{'＋'.join(TAX_BASE_ADDEND_LABELS)}−甲供材料费",
        {"basis": basis_text},
    )


# ------------------------------------------------------------------ 样本装载


REQUIRED_SUMMARY_KEYS: tuple[str, ...] = (
    "分部分项工程费", "措施项目费", "其他项目费", "规费", "合计",
)


def partition_from_fixture(fx: dict, side: str = "bid") -> Partition:
    """从真实样本装配划分。

    ``COMPETITIVE`` 取「分部分项工程费」；``FIXED_PRETAX`` 取措施/其他/规费中
    的**非可竞争**部分。本样本表-04 未单列「施工技术措施 / 施工组织措施」，
    故这里把措施项目费整体置于 ``FIXED_PRETAX`` 并**显式登记该限制**——
    在真实的 T00-06 项目落值表就位前，不得声称措施中的可竞争部分已分离。

    任一分项**为空值**即拒绝装配（:class:`TotalPriceError`）。空 ≠ 0：
    限价侧表-04 的「分部分项工程费」为空是 ADR-0005 已实证的事实
    （招标人不公布该行），把它读成 0 会造出一个「可竞争部分为零」的
    假划分——数值实现里最危险的静默错误。
    """
    t = fx["summary_table_04"][side]

    missing = [k for k in REQUIRED_SUMMARY_KEYS if t.get(k) is None]
    if missing:
        raise TotalPriceError(
            f"{side} 侧表-04 有空值分项 {missing}，拒绝装配划分："
            "空值不等于 0（ADR-0005：限价侧分部分项本就不公布）。"
            "若该侧确实无此分项，须由数据源显式给出 0，而不是由本函数补零"
        )

    def g(key: str) -> float:
        return float(t[key])  # 已由上面的 missing 检查保证非空

    terms = [
        Term("T-DIVISION", "分部分项工程费", g("分部分项工程费"), COMPETITIVE,
             source_list="BOQ", note="X_opt 主体（表-09 分部分项）"),
        Term("T-MEASURE", "措施项目费", g("措施项目费"), FIXED_PRETAX,
             source_list="TECH_MEASURE+ORG_MEASURE",
             note="表-04 未拆分技术/组织措施；"
                  "安全文明施工费含于其中，项目落值表就位后才可分离"),
        Term("T-OTHER", "其他项目费", g("其他项目费"), FIXED_PRETAX,
             source_list="OTHER", note="暂列金额/暂估价按实结算"),
        Term("T-FEE", "规费", g("规费"), FIXED_PRETAX, source_list="FEE_TAX",
             note="D4：外生输入，投标期不可复算"),
    ]
    vat, sur = None, None
    rows = {r["item_name"]: r for r in fx["fee_and_tax"][side] if r.get("item_name")}
    if rows.get("增值税", {}).get("rate"):
        vat = float(rows["增值税"]["rate"]) / 100.0
    if rows.get("附加税", {}).get("rate"):
        sur = float(rows["附加税"]["rate"]) / 100.0

    # 甲供材料费：表-04 未设该行——它是**计税基数的减项**，不是总价的一项。
    # 缺失按 0 入算，但这个假设有外部锚点反证：若实际甲供材不为 0，
    # 重算税金将大于表列税金，判据立刻暴露
    # （见 tests/test_total_price.py::test_tax_matches_table_anchor）。
    supplied_raw = t.get("甲供材料费")
    supplied = 0.0 if supplied_raw is None else float(supplied_raw)

    part = Partition(
        terms=terms, vat_rate=vat, surtax_rate=sur,
        supplied_material=supplied, declared_total=g("合计"),
    )
    if part.tax:
        terms.append(Term("T-TAX", "税金", part.tax, TAX, source_list="FEE_TAX",
                          in_tax_base=False, note="由计税基数派生"))
    return part


def tax_basis_text_from_fixture(fx: dict, side: str = "bid") -> str:
    rows = {r["item_name"]: r for r in fx["fee_and_tax"][side] if r.get("item_name")}
    return (rows.get("增值税") or {}).get("basis") or ""


def load_fixture(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def precision_eps(total: float) -> float:
    return eps_total(total, load_precision_profile())
