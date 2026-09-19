"""T01-04 三表交叉匹配的测试。

判据（任务板原文）：
* 以 master item set 为基准 LEFT JOIN；逐字段统计缺失覆盖率
  （missing_quantity / missing_cost / missing_limit）；
* 未匹配项 100% 进异常清单，禁止静默丢弃；
* 同侧重复 key 必须 BLOCK，禁止自动合并（T01-04A 判据的机械部分）。

测试构造 CleanRow 走 ``_mk`` 辅助函数，不耦合仓库实时状态。
"""

from __future__ import annotations

import unittest

from bidpricing.io.clean import CleanRow
from bidpricing.io.match import (
    ANOMALY_ATTR_MISMATCH,
    ANOMALY_ONLY_IN_CAP,
    ANOMALY_ONLY_IN_COST,
    ANOMALY_ZERO_CAP,
    ANOMALY_ZERO_COST,
    match_canonical_rows,
)


def _mk(item_id, side, *, q=None, p=None, unit="m", name="项", no_cap=False,
        zero_price=False, pass_through=False, project_id="p1",
        unit_work="电气", attribution=None):
    return CleanRow(
        project_id=project_id, unit_work=unit_work, item_id=item_id,
        code_kind="STANDARD", item_name=name, item_feature="", unit=unit,
        q0=q if side == "cap" else None,
        q1_point=q if side == "cost" else None,
        cap=p if side == "cap" else None,
        c_i=p if side == "cost" else None,
        no_cap=no_cap if side == "cap" else False,
        zero_price=zero_price,
        pass_through=pass_through,
        attribution=attribution,
        provenance={"side": side, "source_sheet": f"s-{side}", "source_row": 1,
                    "source_table_no": "表-09"},
    )


class MasterUnionTest(unittest.TestCase):
    def test_both_sides_match(self):
        rep = match_canonical_rows(
            [_mk("A", "cap", q=10, p=100), _mk("B", "cap", q=2, p=50)],
            [_mk("A", "cost", q=12, p=80), _mk("B", "cost", q=2, p=40)],
        )
        self.assertEqual(rep.n_master, 2)
        self.assertEqual(rep.n_matched, 2)
        self.assertEqual(rep.anomalies, [])
        self.assertFalse(rep.blocked)
        a = rep.items[0]
        self.assertEqual((a.q0, a.cap, a.q1_point, a.c_i), (10, 100.0, 12, 80.0))
        self.assertEqual(a.missing, [])

    def test_only_in_cost_goes_to_anomaly_list(self):
        """未匹配项 100% 进异常清单——仅成本侧存在的键不得静默丢弃。"""
        rep = match_canonical_rows(
            [_mk("A", "cap", q=10, p=100)],
            [_mk("A", "cost", q=12, p=80), _mk("X", "cost", q=1, p=9)],
        )
        self.assertEqual(rep.n_master, 2)
        self.assertEqual(rep.n_only_cost, 1)
        kinds = {a.kind for a in rep.anomalies}
        self.assertIn(ANOMALY_ONLY_IN_COST, kinds)
        x = next(i for i in rep.items if i.item_id == "X")
        self.assertIn("missing_limit", x.missing)
        self.assertIn(ANOMALY_ONLY_IN_COST, x.anomalies)

    def test_only_in_cap_goes_to_anomaly_list(self):
        rep = match_canonical_rows(
            [_mk("A", "cap", q=10, p=100), _mk("Y", "cap", q=3, p=30)],
            [_mk("A", "cost", q=12, p=80)],
        )
        self.assertEqual(rep.n_only_cap, 1)
        kinds = {a.kind for a in rep.anomalies}
        self.assertIn(ANOMALY_ONLY_IN_CAP, kinds)
        y = next(i for i in rep.items if i.item_id == "Y")
        self.assertIn("missing_cost", y.missing)

    def test_master_order_follows_cap_then_cost_input_order(self):
        """输出顺序必须保持原清单顺序，不能按项目编码重新排序。"""
        rep = match_canonical_rows(
            [_mk("B", "cap", q=1, p=20), _mk("A", "cap", q=1, p=10)],
            [_mk("B", "cost", q=1, p=15), _mk("A", "cost", q=1, p=8),
             _mk("C", "cost", q=1, p=3)],
        )
        self.assertEqual([item.item_id for item in rep.items], ["B", "A", "C"])


class CoverageTest(unittest.TestCase):
    def test_coverage_counters(self):
        rep = match_canonical_rows(
            [_mk("A", "cap", q=10, p=100),
             _mk("B", "cap", q=2, p=None, no_cap=True),
             _mk("C", "cap", q=None, p=7)],
            [_mk("A", "cost", q=12, p=80),
             _mk("B", "cost", q=2, p=40),
             _mk("C", "cost", q=None, p=5)],
        )
        cov = rep.coverage
        # B：cap 空 = 不限价（合法语义）→ 计 missing_limit 且单独计数
        self.assertEqual(cov["missing_limit"], 1)
        self.assertEqual(rep.n_no_cap, 1)
        self.assertFalse(rep.blocked)
        # C：两侧量都缺失
        self.assertEqual(cov["missing_quantity"], 1)
        self.assertEqual(cov["missing_quantity_cap"], 1)
        self.assertEqual(cov["missing_quantity_cost"], 1)
        self.assertEqual(cov["missing_cost"], 0)
        b = next(i for i in rep.items if i.item_id == "B")
        self.assertIn("missing_limit", b.missing)
        # no_cap 是合法语义不是异常：B 不产生 ONLY_IN_*/零价异常
        self.assertNotIn(
            any(a.item_id == "B" and a.kind.startswith("ONLY_IN") for a in rep.anomalies),
            [True])

    def test_no_cap_is_not_zero(self):
        """cap 空 ≠ cap=0：no_cap 标志必须为 True 且 cap 字段保持 None。"""
        rep = match_canonical_rows(
            [_mk("A", "cap", q=10, p=None, no_cap=True)],
            [_mk("A", "cost", q=10, p=50)],
        )
        a = rep.items[0]
        self.assertTrue(a.no_cap)
        self.assertIsNone(a.cap)
        self.assertNotIn(ANOMALY_ZERO_CAP, a.anomalies)


class DuplicateKeyTest(unittest.TestCase):
    def test_duplicate_cap_key_blocks(self):
        """同侧重复 key 必须 BLOCK，禁止自动合并；全部副本进异常清单。"""
        rep = match_canonical_rows(
            [_mk("A", "cap", q=10, p=100), _mk("A", "cap", q=11, p=101)],
            [_mk("A", "cost", q=12, p=80)],
        )
        self.assertTrue(rep.blocked)
        self.assertEqual(len(rep.duplicate_keys), 1)
        dup_anoms = [a for a in rep.anomalies if a.kind == "DUPLICATE_KEY_CAP"]
        self.assertEqual(len(dup_anoms), 2)  # 两个副本各一条
        # 融合行仍产出（取首行），但 blocked=1 由调用方拦截求解
        self.assertEqual(rep.n_master, 1)

    def test_duplicate_cost_key_blocks(self):
        rep = match_canonical_rows(
            [_mk("A", "cap", q=10, p=100)],
            [_mk("A", "cost", q=12, p=80), _mk("A", "cost", q=12, p=81)],
        )
        self.assertTrue(rep.blocked)
        self.assertTrue(any(a.kind == "DUPLICATE_KEY_COST" for a in rep.anomalies))


class SignalTest(unittest.TestCase):
    def test_zero_price_signals(self):
        rep = match_canonical_rows(
            [_mk("A", "cap", q=10, p=0, zero_price=True)],
            [_mk("A", "cost", q=10, p=0, zero_price=True)],
        )
        kinds = {a.kind for a in rep.anomalies}
        self.assertIn(ANOMALY_ZERO_CAP, kinds)
        self.assertIn(ANOMALY_ZERO_COST, kinds)

    def test_attribute_mismatch_warned(self):
        """用户口径：两侧名称/单位完全一致——不一致 ≈ 键对错位的前兆。"""
        rep = match_canonical_rows(
            [_mk("A", "cap", q=10, p=100, unit="m", name="电缆敷设")],
            [_mk("A", "cost", q=10, p=80, unit="km", name="电缆")],
        )
        kinds = [a.kind for a in rep.anomalies]
        self.assertEqual(kinds.count(ANOMALY_ATTR_MISMATCH), 2)  # 名称 + 单位

    def test_pass_through_flag_from_either_side(self):
        rep = match_canonical_rows(
            [_mk("A", "cap", q=10, p=100)],
            [_mk("A", "cost", q=10, p=80, pass_through=True)],
        )
        self.assertTrue(rep.items[0].pass_through)


if __name__ == "__main__":
    unittest.main()
