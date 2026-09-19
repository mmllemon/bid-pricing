import unittest

from bidpricing.import_preview import PREVIEW_FIELDS, build_listing_preview
from bidpricing.io.match import MatchReport, MatchedItem


def _item(item_id, unit_work="电气工程", cap_row=True, cost_row=True, cap=100.0, c_i=60.0):
    # 默认两侧字段均落值；row 旗标只表示"该侧是否存在行"，用于匹配覆盖统计。
    return MatchedItem(
        project_id="P1", unit_work=unit_work, item_id=item_id,
        code_kind="normal", item_name="项", unit="m",
        q0=1.0, cap=cap, cap_row=cap_row, q1_point=1.0, c_i=c_i, cost_row=cost_row)


class ImportPreviewTest(unittest.TestCase):
    def test_duplicate_item_id_across_unit_work_is_reported(self):
        items = [
            _item("X", unit_work="电气工程"),
            _item("X", unit_work="动力工程"),
            _item("Y"),
        ]
        matched = MatchReport(
            n_cap_rows=3, n_cost_rows=3, n_master=1, n_matched=2, items=items)
        p = build_listing_preview(matched, "P1")
        self.assertEqual(p["status"], "PASS")
        self.assertEqual(p["duplicate_item_id_across_unit_work"], ["X"])
        self.assertEqual(p["match"]["master_keys"], 1)
        self.assertEqual(p["optimizable_count"], 3)

    def test_match_coverage_and_optimizable_split(self):
        items = [
            _item("CAP_ONLY", cap_row=True, cost_row=False),
            _item("COST_ONLY", cap_row=False, cost_row=True),
            _item("FULL"),
            MatchedItem(project_id="P1", unit_work="电气工程", item_id="NO_CAP",
                        code_kind="normal", item_name="项", unit="m",
                        q0=1.0, cap=None, cap_row=True,
                        q1_point=1.0, c_i=60.0, cost_row=True),
        ]
        matched = MatchReport(
            n_cap_rows=2, n_cost_rows=2, n_master=4, n_matched=2,
            n_only_cap=1, n_only_cost=1, items=items)
        p = build_listing_preview(matched, "P1")
        self.assertEqual(p["match"]["only_cap_ids"], ["CAP_ONLY"])
        self.assertEqual(p["match"]["only_cost_ids"], ["COST_ONLY"])
        # 可优化 = q0/q1_point/c_i/cap 齐全 → CAP_ONLY/COST_ONLY/FULL（NO_CAP 缺 cap）
        self.assertEqual(p["optimizable_count"], 3)
        self.assertEqual(p["manual_count"], 1)
        self.assertEqual(p["missing_cap_ids"], ["NO_CAP"])
        self.assertEqual(p["missing_cost_ids"], [])

    def test_duplicate_keys_forward_blocked(self):
        matched = MatchReport(
            items=[_item("A")], blocked=True,
            duplicate_keys=["(P1, 电气工程, A)"])
        p = build_listing_preview(matched, "P1")
        self.assertTrue(p["match"]["blocked"])
        self.assertEqual(p["match"]["duplicate_keys"], ["(P1, 电气工程, A)"])

    def test_field_map_reflects_adapter_presence(self):
        matched = MatchReport(items=[_item("A")])
        p = build_listing_preview(matched, "P1")
        self.assertEqual(set(p["fields"]), set(PREVIEW_FIELDS))
        self.assertTrue(p["fields"]["item_id"])
        self.assertTrue(p["fields"]["cap"])
        self.assertTrue(p["fields"]["q0"])
        # 全缺值 → 字段覆盖为 False（仅 item_id 仍为 str 恒真）
        none_items = [MatchedItem(
            project_id="P1", unit_work="电气工程", item_id="C",
            code_kind="normal", item_name="项", unit="m",
            q0=None, cap=None, cap_row=True, q1_point=None, c_i=None, cost_row=True)]
        p2 = build_listing_preview(MatchReport(items=none_items), "P1")
        self.assertTrue(p2["fields"]["item_id"])
        self.assertFalse(p2["fields"]["q0"])
        self.assertFalse(p2["fields"]["cap"])


if __name__ == "__main__":
    unittest.main()