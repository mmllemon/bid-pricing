"""总价恒等式 —— 投标期总价分解的**可执行判据**。

恒等式（投标期口径）
--------------------
::

    计税基数 Base = 分部分项工程费 + 措施项目费 + 其他项目费 + 规费 − 甲供材料费
    增值税   VAT  = Base × 增值税率
    附加税   SUR  = VAT × 附加税率
    税金     TAX  = VAT + SUR + 环境保护税（按实计算，默认 0）
    总价     P    = 分部分项工程费 + 措施项目费 + 其他项目费 + 规费 + 税金

三条口径说明（均由实测裁定，勿按旧口径改回）
--------------------------------------------
1. **不可竞争费是外生常量**。安全文明施工费、规费、税金在**投标期**是招标文件
   给定的固定值，投标人无权更改。它们 **进总价**（是恒等式的加项），但
   **不进决策变量集合**。不要为它们建立关于报价 ``p`` 的仿射关系——那是
   **结算期**的做法（§ 契约偏差 D2/D3）。
2. **规费与税金不得独立复算**。规费的计算基础是纯文字规则（依赖人工费分解），
   清单不提供该分解；税金基数又含规费。因此二者只能作为**外生输入**接收金额，
   由 :func:`decompose` 从给定金额反推，而不是从清单重算。
3. **可用性边界**：恒等式只在**同一项目的同一单位工程**内闭合。
   实测四份跨项目示例模板的「工程名称」互不一致（措施/其他属土建、规费税金属安装、
   分部分项另属 5 个单位工程），跨文件比对差值达 3.21 倍。故本模块的每一项比较
   都必须先确认输入同源；跨项目比对**不是精度问题，是口径错误**。

与精度策略的衔接
----------------
容差取自 ``config/precision_profile.json`` 的 ``eps_total = max(eps_abs, eps_price × P*)``，
**两层必须使用同一 eps**——不得「求解时容差化、复核时严格等式」（路线 §8.2）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .money import money, money_sum
from .paths import config_dir
from .states import CheckItem, Status

#: 本项目恒等式各分项的规范名称，用于报告与追溯
COMPONENTS = ("分部分项工程费", "措施项目费", "其他项目费", "规费")

BACKEND_TAG = "T00-06B 总价分解规范"


@dataclass(frozen=True)
class Totals:
    """总价构成的五项加数（单位：元）。

    前四项是**税前**金额，``supplied_material`` 是计税基数的**减项**。
    """

    division: float = 0.0
    """分部分项工程费"""

    measures: float = 0.0
    """措施项目费（含施工技术措施 + 施工组织措施）"""

    other: float = 0.0
    """其他项目费（暂列金额 / 暂估价 / 计日工 / 总承包服务费 / 索赔与现场签证）"""

    fees: float = 0.0
    """规费（外生输入，不得复算）"""

    supplied_material: float = 0.0
    """甲供材料费——只减计税基数，不减总价"""

    @property
    def pre_tax(self) -> float:
        """税前合计 = 四项之和（不含甲供材减项）。"""
        return self.division + self.measures + self.other + self.fees

    @property
    def taxable_base(self) -> float:
        """计税基数 = 税前合计 − 甲供材料费。"""
        return self.pre_tax - self.supplied_material


@dataclass(frozen=True)
class TaxDecomposition:
    """恒等式的完整分解结果。"""

    totals: Totals
    vat_rate: float
    surtax_rate: float
    env_tax: float = 0.0

    @property
    def vat(self) -> float:
        return money(self.totals.taxable_base * self.vat_rate)

    @property
    def surtax(self) -> float:
        return money(self.vat * self.surtax_rate)

    @property
    def tax(self) -> float:
        """税金合计 = 增值税 + 附加税 + 环境保护税。"""
        return money(self.vat + self.surtax + self.env_tax)

    @property
    def total(self) -> float:
        return money(self.totals.pre_tax + self.tax)

    def to_dict(self) -> dict:
        return {
            "分部分项工程费": money(self.totals.division),
            "措施项目费": money(self.totals.measures),
            "其他项目费": money(self.totals.other),
            "规费": money(self.totals.fees),
            "甲供材料费": money(self.totals.supplied_material),
            "税前合计": money(self.totals.pre_tax),
            "计税基数": money(self.totals.taxable_base),
            "增值税率": self.vat_rate,
            "增值税": self.vat,
            "附加税率": self.surtax_rate,
            "附加税": self.surtax,
            "环境保护税": money(self.env_tax),
            "税金合计": self.tax,
            "总价": self.total,
        }


def decompose(
    totals: Totals,
    vat_rate: float,
    surtax_rate: float,
    env_tax: float = 0.0,
) -> TaxDecomposition:
    """按恒等式分解总价。

    ``vat_rate`` / ``surtax_rate`` 是**项目级外生数据**（本项目实测增值税 9%、
    附加税 12%），必须由调用方从数据源传入，**不得在此处写默认值**——
    写默认值等于把某个项目的税率冒充为规则。
    """
    for name, rate in (("增值税率", vat_rate), ("附加税率", surtax_rate)):
        if rate is None:
            raise ValueError(f"{name} 缺失：税率是项目级外生数据，无默认值")
    return TaxDecomposition(
        totals=totals, vat_rate=vat_rate, surtax_rate=surtax_rate, env_tax=env_tax
    )


# --------------------------------------------------------------- 容差口径


def load_precision_profile(cfg: Path | None = None) -> dict:
    cfg = cfg or config_dir()
    return json.loads((cfg / "precision_profile.json").read_text(encoding="utf-8"))


def eps_total(total: float, profile: dict | None = None) -> float:
    """总价类残差的容差 ``max(eps_abs, eps_price × P*)``。

    ``eps_price × P*`` 一项在高总价项目上会超过舍入分辨率 0.01 元；此时
    路线 §8.2 的 open_item 要求改用 ``eps_abs``。本函数按 max 取——两者
    都满足才算通过，且**求解层与复核层调用同一函数**，避免口径分叉。
    """
    p = profile or load_precision_profile()
    return max(p["eps_abs"]["value"], p["eps_price"]["value"] * abs(total))


# --------------------------------------------------------------- 判据


def check_identity(
    computed: TaxDecomposition,
    stated_total: float,
    stated_vat: float | None = None,
    stated_tax: float | None = None,
    eps: float | None = None,
) -> list[CheckItem]:
    """把恒等式核验为机械判据。

    返回逐条 :class:`CheckItem`；任一条 FAIL 即表示「该项目的总价链条不闭合」，
    此时**不是精度问题而是口径问题**，必须回到输入同源性排查（见模块 docstring 第 3 条）。
    """
    tol = eps if eps is not None else eps_total(stated_total)
    items: list[CheckItem] = []

    d_total = round(computed.total - stated_total, 4)
    items.append(
        CheckItem(
            scope="恒等式·总价",
            item="总价",
            status=Status.PASS if abs(d_total) <= tol else Status.FAIL,
            actual=computed.total,
            expected=stated_total,
            delta=d_total,
            reason=(
                f"分项舍入后重算总价 {computed.total:,.2f} vs 表列 {stated_total:,.2f}，"
                f"残差 {d_total:+.4f} 元，容差 {tol:.4f} 元"
                + ("" if abs(d_total) <= tol else "。容差内不通过 → 排查输入是否同源于同一单位工程")
            ),
        )
    )

    if stated_vat is not None:
        d = round(computed.vat - stated_vat, 4)
        items.append(
            CheckItem(
                scope="恒等式·增值税",
                item="增值税",
                status=Status.PASS if abs(d) <= tol else Status.FAIL,
                actual=computed.vat,
                expected=stated_vat,
                delta=d,
                reason=f"计税基数 {computed.totals.taxable_base:,.2f} × {computed.vat_rate:.0%}",
            )
        )

    if stated_tax is not None:
        d = round(computed.tax - stated_tax, 4)
        items.append(
            CheckItem(
                scope="恒等式·税金",
                item="税金",
                status=Status.PASS if abs(d) <= tol else Status.FAIL,
                actual=computed.tax,
                expected=stated_tax,
                delta=d,
                reason=f"增值税 {computed.vat:,.2f} + 附加税 {computed.surtax:,.2f}",
            )
        )
    return items


def check_component_sum(
    parts: dict[str, float],
    stated: float,
    label: str,
    eps: float | None = None,
) -> CheckItem:
    """核对「逐项明细之和 == 表列小计」。

    这是**输入保真性**判据：小计对不上通常意味着解析漏行、把分部标题行当明细，
    或把合计行重复计入——而不是业务问题。
    """
    got = money_sum(parts.values())
    tol = eps if eps is not None else eps_total(stated)
    d = round(got - stated, 4)
    return CheckItem(
        scope="输入保真",
        item=label,
        status=Status.PASS if abs(d) <= tol else Status.FAIL,
        actual=got,
        expected=stated,
        delta=d,
        reason=f"{len(parts)} 项明细求和 {got:,.2f} vs 表列小计 {stated:,.2f}",
    )


# --------------------------------------------------------------- 真实样本装载


def load_pair_fixture(path: str | Path) -> dict:
    """读取「限价 / 报价配对」真实样本（tests/data/ 下）。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def totals_from_fixture(fx: dict, side: str = "bid") -> Totals:
    """从配对样本的汇总表(表-04)取出五项加数。

    ``side`` 取 ``"bid"``（投标报价）或 ``"cap"``（招标限价）。
    """
    t = fx["summary_table_04"][side]

    def v(*keys: str) -> float:
        for k in keys:
            if t.get(k) is not None:
                return float(t[k])
        return 0.0

    return Totals(
        division=v("分部分项工程费"),
        measures=v("措施项目费"),
        other=v("其他项目费"),
        fees=v("规费"),
        supplied_material=v("甲供材料费"),
    )


def rates_from_fixture(fx: dict, side: str = "bid") -> tuple[float, float]:
    """从表-12 取增值税率与附加税率（项目级外生数据）。"""
    rows = {r["item_name"]: r for r in fx["fee_and_tax"][side] if r.get("item_name")}
    vat = float(rows["增值税"]["rate"]) / 100.0
    sur = float(rows["附加税"]["rate"]) / 100.0
    return vat, sur


def stated_from_fixture(fx: dict, side: str = "bid") -> dict:
    """从表-12 取实测的增值税 / 税金，从表-04 取实测总价。"""
    rows = {r["item_name"]: r for r in fx["fee_and_tax"][side] if r.get("item_name")}
    return {
        "增值税": float(rows["增值税"]["amount"]),
        "税金": float(rows["税金"]["amount"]),
        "总价": float(fx["summary_table_04"][side]["合计"]),
    }
