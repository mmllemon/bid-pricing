"""金额舍入模块的验收用例。

立场：``config/precision_profile.json`` 的 ``rounding.rule`` 要求**四舍五入**。
Python 内建 ``round()`` 是银行家舍入，二者在半厘值上结果不同。本文件用
可区分算例把「用错舍入」变成可失败的断言——否则这类缺陷只会在某一天
恒等式差 0.01 元时以「时好时坏」的形式出现。
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from bidpricing.money import (
    MONEY_PLACES,
    is_money_aligned,
    money,
    money_dec,
    money_sum,
)


class HalfUpVsBankersTest(unittest.TestCase):
    """本模块存在的理由：内建 round() 不是规范要求的四舍五入。"""

    def test_discriminating_cases(self):
        # 0.125 与 2.675 是半厘/半分的分界点，两种规则在此分岔
        self.assertEqual(round(0.125, 2), 0.12)   # 银行家舍入：向偶
        self.assertEqual(money(0.125), 0.13)      # 规范要求：四舍五入
        self.assertNotEqual(money(0.125), round(0.125, 2))

        self.assertEqual(round(2.675, 2), 2.67)   # 二进制表示导致向下
        self.assertEqual(money(2.675), 2.68)

    def test_negative_tie_rounds_away_from_zero(self):
        self.assertEqual(money(-0.125), -0.13)

    def test_binary_tail_does_not_leak(self):
        """float 的二进制尾巴不得被当成有效数字。"""
        self.assertEqual(money(0.1 + 0.2), 0.30)

    def test_accepts_str_and_decimal(self):
        self.assertEqual(money("1.005"), 1.01)
        self.assertEqual(money(Decimal("1.005")), 1.01)
        self.assertEqual(money_dec("1.005"), Decimal("1.01"))

    def test_bool_is_rejected(self):
        """bool 是 int 的子类，静默当成 0/1 会把标记位算进金额。"""
        with self.assertRaises(TypeError):
            money(True)


class MoneySumTest(unittest.TestCase):
    """「汇总后再舍入一次」≠「逐项舍入后累加」。"""

    def test_sum_then_round_differs_from_round_then_sum(self):
        parts = [0.004, 0.004, 0.004]
        self.assertEqual(money_sum(parts), 0.01)
        self.assertEqual(sum(money(p) for p in parts), 0.00)
        self.assertNotEqual(money_sum(parts), sum(money(p) for p in parts))

    def test_exact_decimal_accumulation(self):
        """0.1 累加 10 次必须精确等于 1.00。

        注意：Python **3.12 起**内建 ``sum()`` 对 float 启用了补偿求和
        （Neumaier），所以此处刻意用显式循环暴露朴素浮点累加的误差——
        3.12 上若用 ``sum()`` 断言，这个用例会变成空真通过。
        """
        naive = 0.0
        for _ in range(10):
            naive += 0.1
        self.assertNotEqual(naive, 1.00)
        self.assertEqual(money_sum([0.1] * 10), 1.00)

    def test_empty_sum_is_zero(self):
        self.assertEqual(money_sum([]), 0.0)


class AlignmentTest(unittest.TestCase):
    def test_alignment(self):
        self.assertTrue(is_money_aligned(12.34))
        self.assertFalse(is_money_aligned(12.345))
        self.assertEqual(MONEY_PLACES, 2)


if __name__ == "__main__":
    unittest.main()
