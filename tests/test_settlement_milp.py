"""pa06 内核优化：严重低价二元变量收紧大 M（low_price_big_m）+ 公式级冒烟测试。

背景（settlement_milp.py 原 L108）：``M = max(upper-lower, upper, 1.0)`` 过松，
默认 0.5~1.0·cap 区间下 M≈cap，数值病态风险高。收紧为两条约束同时成立的
最小安全值 ``max(upper-threshold, threshold-lower, 1e-9)``：

* ``p + M·y <= threshold + M``（y=1 → p<=threshold）要求 M>=upper-threshold；
* ``p + M·y >= threshold``（y=0 → p>=threshold）要求 M>=threshold-lower
  （y=1 时不得切掉低价可行域）。

本测试同时证明收紧后两分支都保持可行（不改变最优解），且公式级冒烟确认
求解器构造的 C13 约束确实使用收紧后的 M。
"""

import unittest

from bidpricing.solver.instance import Phase1Instance
from bidpricing.solver.settlement_milp import (
    build_settlement_adjustment_formulation,
    low_price_big_m,
)

CLAUSE = {"enabled": True, "reference": "CAP", "tol_lo": 0.5, "tol_hi": 0.5,
          "mechanism": "SETTLEMENT_ADJUSTMENT"}


class LowPriceBigMTest(unittest.TestCase):
    def test_default_case_is_tightened(self):
        # 默认 0.5~1.0·cap：upper=cap=100, lower=threshold=50
        # 收紧前 M=max(50, 100, 1)=100；收紧后 M=50
        self.assertEqual(low_price_big_m(100.0, 50.0, 50.0), 50.0)

    def test_max_of_two_branch_requirements(self):
        # 约束1需 M>=upper-threshold=30；约束2需 M>=threshold-lower=20 → 30
        self.assertEqual(low_price_big_m(80.0, 30.0, 50.0), 30.0)

    def test_upper_below_threshold(self):
        # upper<threshold：高价分支本就不可行，M 由约束2决定 = threshold-lower
        self.assertEqual(low_price_big_m(40.0, 20.0, 50.0), 30.0)

    def test_degenerate_single_point_uses_epsilon(self):
        # upper==lower==threshold：M 取极小量，避免 0 把两分支压成单点
        self.assertAlmostEqual(low_price_big_m(50.0, 50.0, 50.0), 1e-9)

    def test_both_branches_stay_feasible(self):
        # 收紧后仍满足：y=0 时 upper<=threshold+M；y=1 时 lower>=threshold-M
        for upper, lower, threshold in [
            (100.0, 50.0, 50.0), (80.0, 30.0, 50.0), (40.0, 20.0, 50.0),
            (120.0, 10.0, 60.0), (70.0, 70.0, 60.0),
        ]:
            M = low_price_big_m(upper, lower, threshold)
            self.assertGreaterEqual(threshold + M, upper - 1e-12)
            self.assertLessEqual(threshold - M, lower + 1e-12)


class FormulationSmokeTest(unittest.TestCase):
    def test_binary_row_uses_tight_m(self):
        # q1=80 < 0.85*q0=85 → 触发严重低价二元分支；L=50, U=cap=100, threshold=50
        rows = [{"item_id": "A", "q0": 100.0, "q1_point": 80.0, "c_i": 30.0,
                 "cap": 100.0, "L": 50.0, "U": 100.0}]
        inst = Phase1Instance.from_master(
            rows, price_column="cap", B=5000.0, P_star=6000.0,
            source="test_settlement_milp")
        built = build_settlement_adjustment_formulation(inst, clause=CLAUSE, vat_rate=0.09)
        c13_le = next(r for r in built.formulation.rows
                      if r.constraint_id == "C13" and r.sense == "<=")
        m_coeff = dict(c13_le.coefficients)["y_A"]
        # 收紧后 M = upper - threshold = 100 - 50 = 50（收紧前为 100）
        self.assertAlmostEqual(m_coeff, 50.0)
        self.assertAlmostEqual(c13_le.rhs, 50.0 + m_coeff)


if __name__ == "__main__":
    unittest.main()
