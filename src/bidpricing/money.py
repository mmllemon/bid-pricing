"""金额舍入 —— 全仓唯一入口。

为什么需要一个模块
------------------

``config/precision_profile.json`` 的 ``rounding.rule`` 写的是
**「分项四舍五入至 0.01 元，汇总后再舍入一次」**。而 Python 内建的
``round()`` 做的是**银行家舍入**（round-half-to-even）::

    round(0.125, 2)  ->  0.12      # 期望 0.13
    round(2.675, 2)  ->  2.67      # 期望 2.68（二进制表示所致）

两者在「恰好半厘」的值上给出不同结果，且**方向可正可负**。投标报价里
分项金额出现半厘并不罕见（费率相乘尤其容易：``1,234,567.89 × 9% = 111,111.1101``
一类），一旦口径不同，恒等式在汇总处对不上 0.01 元——恰好落在 ``eps_abs``
容差上，形成「有时过、有时不过」的闪烁判据。故此处按规范实现**四舍五入**，
并且**全仓只此一处**：同一个数在两处按不同规则舍入，就是口径分叉。

实现说明
--------

* 先 ``str(x)`` 再进 :class:`~decimal.Decimal`，避免把 float 的二进制尾巴
  （``0.1 + 0.2 = 0.30000000000000004``）当成有效数字；
* 中间量一律用 ``Decimal`` 参与运算，只在出口转回 float；
* 默认 2 位（元，分），与 ``precision_profile.rounding.resolution`` 一致。
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

#: 金额分辨率（元）——取自 precision_profile.rounding.resolution
MONEY_PLACES = 2

_QUANT = Decimal("0.01")


def money(value: float | int | str | Decimal) -> float:
    """四舍五入到 0.01 元，返回 float。

    用于**金额**（分项、汇总、税金）。**不要**用于单价残差或容差——
    那些是无量纲/相对量，见 ``precision_profile.eps_*``。
    """
    return float(_dec(value).quantize(_QUANT, rounding=ROUND_HALF_UP))


def money_dec(value: float | int | str | Decimal) -> Decimal:
    """:func:`money` 的 Decimal 版本，供需要连续运算的场合使用。"""
    return _dec(value).quantize(_QUANT, rounding=ROUND_HALF_UP)


def _dec(value: float | int | str | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool 是 int 的子类，明确拒绝以免静默 0/1
        raise TypeError("金额不接受 bool")
    return Decimal(str(value))


def money_sum(values) -> float:
    """先按 Decimal 精确相加，再整体舍入一次 —— **不是**逐个舍入后累加。"""
    total = Decimal("0")
    for v in values:
        total += _dec(v)
    return float(total.quantize(_QUANT, rounding=ROUND_HALF_UP))


def is_money_aligned(value: float, places: int = MONEY_PLACES) -> bool:
    """判断一个数是否已是该分辨率上的精确值（用于「汇总后再舍入一次」的自检）。"""
    q = Decimal(1).scaleb(-places)
    return _dec(value).quantize(q, rounding=ROUND_HALF_UP) == _dec(value)
