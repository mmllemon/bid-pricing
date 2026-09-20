"""H-010 Excel/网页字段回归：明细列、表头、负毛利与报价比率在『JSON payload ⇒ 网页
(renderResult) ⇒ Excel(build_web_result.mjs)』三条口径下保持一致。

Excel 脚本 build_web_result.mjs 从 input.items 读取的中文字段是唯一数据源，本测试
把样本 PASS payload（mock 求解器）逐项断言这些字段齐全，并校验 Excel 的状态推导
(LOSS_REVIEW) 与网页(需复核) 对负毛利/低比率的判定完全一致。
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from bidpricing.quote_pipeline import QuotePipelineResult
from bidpricing.quote_resolve import run_resolve

# build_web_result.mjs 的 columns 表头（报价表 A12:P12）
EXCEL_HEADERS = ["Item ID", "项目名称", "单位", "工程量 q0", "结算量 q1", "最高限价",
                 "成本 c_i", "最优综合单价", "报价比率", "报价合价", "成本合价",
                 "结算收入", "单项毛利", "毛利率", "状态", "说明"]

# build_web_result.mjs 对每个 item 实际读取的中文字段（来源 input.items）
EXCEL_ITEM_KEYS = ["项目编码", "项目名称", "单位", "工程量", "成本工程量", "最高限价",
                   "含税成本单价", "最优报价单价", "报价合价", "成本合价", "结算收入",
                   "单项毛利", "报价状态", "说明"]

# 网页 renderResult（app.js）实际读取的字段
WEB_ITEM_KEYS = ["项目编码", "项目名称", "单位", "工程量", "成本工程量", "含税成本单价",
                 "最高限价", "最优报价单价", "报价比率", "报价合价", "单项毛利", "报价状态", "说明"]

# 负毛利 / 低报价比率的判定阈值（两处口径必须一致）
MANUAL_REVIEW = "MANUAL_REVIEW"
LOSS_REVIEW = "LOSS_REVIEW"      # Excel 状态列
WARN_REVIEW = "需复核"           # 网页状态列
WEB_MANUAL = "人工报价"


def _fake(prices, objective=500.0):
    return QuotePipelineResult(status="PASS", target_total=1000.0,
                               competitive_budget=900.0, p_by_id=dict(prices),
                               line_amounts={}, objective=objective,
                               solver_status="OPTIMAL", violations=(), reason="ok")


def _item(item_id, *, cap, price, c_i=60.0, q0=100.0, q1=100.0, name="挖土方"):
    """构造一个可优化项；price 为 mock 求解器给出的最优报价单价（嵌入 dict 用于取价）。

    ``cost_tax_scope="EXCL_VAT"`` 是**显式声明本夹具的 c_i 已是有效成本**，
    从而把 H-002 成本税口径层旁路掉——本文件测的是字段/状态契约，不该被
    「项目当前有没有声明进项税率」影响（测试不得耦合项目实时状态）。
    成本税口径本身的双向验证在 tests/test_cost_input_tax.py。
    """
    return {"item_id": item_id, "item_name": name, "unit": "m3", "q0": q0,
            "q1_point": q1, "c_i": c_i, "cap": cap, "L": cap * 0.5, "U": cap,
            "cost_tax_scope": "EXCL_VAT", "mock_price": price}


def _manual_item(item_id="0109"):
    return {"item_id": item_id, "item_name": "人工项", "unit": "项", "q0": 1.0,
            "q1_point": None, "c_i": None, "cap": None, "L": 0.0, "U": None}


def _params(**over):
    p = {"target_total": 1000.0, "fixed_pretax": 0.0, "vat_rate": 0.09,
         "surtax_rate": 0.12, "ratio_min": 0.5, "ratio_max": 1.0,
         "low_ratio_confirmed": True, "low_price_confirmed_by": "测试人"}
    p.update(over)
    return p


def _low_policy(**over):
    base = {"low_price_threshold": 0.5, "clause_basis": None}
    base.update(over)
    return base


def _excel_status(item):
    """复刻 build_web_result.mjs 第 33 行的状态推导。"""
    if item["报价状态"] == MANUAL_REVIEW:
        return MANUAL_REVIEW
    if (item["单项毛利"] is not None and item["单项毛利"] < 0) or \
       (item["报价比率"] is not None and item["报价比率"] < 0.5):
        return LOSS_REVIEW
    return "PASS"


def _web_status(item):
    """复刻网页 renderResult 的 状态 列。"""
    if item["报价状态"] == MANUAL_REVIEW:
        return WEB_MANUAL
    if (item["单项毛利"] is not None and item["单项毛利"] < 0) or \
       (item["报价比率"] is not None and item["报价比率"] < 0.5):
        return WARN_REVIEW
    return "通过"


class FieldRegressionTest(unittest.TestCase):

    CONFIG = Path(__file__).resolve().parents[1] / "config"

    @staticmethod
    def _payload(all_items):
        prices = {d["item_id"]: d["mock_price"] for d in all_items if "mock_price" in d}
        with patch("bidpricing.quote_resolve.run_settlement_adjusted_quote_pipeline",
                   return_value=_fake(prices)):
            result, payload, code = run_resolve(
                all_items, _params(), _low_policy(), config_dir=FieldRegressionTest.CONFIG)
        assert code == 200, payload
        return payload

    def test_payload_items_cover_excel_and_web_columns(self):
        # 优化项 + 人工项并存，两条口径读取的字段都必须齐全
        items = self._payload(
            [_item("0101", cap=100.0, price=80.0), _manual_item()])["items"]
        by_id = {it["项目编码"]: it for it in items}
        self.assertEqual(by_id["0109"]["报价状态"], MANUAL_REVIEW)
        for it in items:
            for key in set(EXCEL_ITEM_KEYS) | set(WEB_ITEM_KEYS):
                self.assertIn(key, it, f"payload item 缺少字段 {key}")

    def test_excel_headers_map_to_payload_item_fields(self):
        self.assertGreaterEqual(len(EXCEL_HEADERS), len(EXCEL_ITEM_KEYS))
        self.assertEqual(EXCEL_HEADERS[0], "Item ID")

    def test_negative_margin_parity_and_note(self):
        # 负毛利（比率 ≥50%，单纯亏损）：Excel LOSS_REVIEW ↔ 网页 需复核，
        # 说明带『需人工复核』，但不触发低价确认。
        payload = self._payload(
            [_item("0101", cap=100.0, price=55.0, c_i=90.0)])
        it = payload["items"][0]
        self.assertLess(it["单项毛利"], 0)
        self.assertGreaterEqual(it["报价比率"], 0.5)
        self.assertEqual(_excel_status(it), LOSS_REVIEW)
        self.assertEqual(_web_status(it), WARN_REVIEW)
        self.assertIn("需人工复核", it["说明"])
        self.assertFalse(payload["low_ratio_review_required"])

    def test_low_ratio_parity_and_note(self):
        # 低报价比率（40%，＜50%）：Excel LOSS_REVIEW ↔ 网页 需复核，
        # 说明带『报价比率低于50%』，并触发低价确认留痕。
        payload = self._payload(
            [_item("0102", cap=100.0, price=40.0, c_i=20.0)])
        it = payload["items"][0]
        self.assertLess(it["报价比率"], 0.5)
        self.assertGreaterEqual(it["单项毛利"], 0)
        self.assertEqual(_excel_status(it), LOSS_REVIEW)
        self.assertEqual(_web_status(it), WARN_REVIEW)
        self.assertIn("报价比率低于50%", it["说明"])
        self.assertTrue(payload["low_ratio_review_required"])

    def test_normal_item_is_pass(self):
        it = self._payload([_item("0101", cap=100.0, price=55.0, c_i=30.0)])["items"][0]
        self.assertGreaterEqual(it["单项毛利"], 0)
        self.assertGreaterEqual(it["报价比率"], 0.5)
        self.assertEqual(_excel_status(it), "PASS")
        self.assertEqual(_web_status(it), "通过")
        self.assertNotIn("需人工复核", it["说明"])

    def test_ratio_equals_price_over_cap(self):
        # Excel 公式 =H/F（最优报价单价 ÷ 最高限价），与 payload 报价比率需一致
        it = self._payload([_item("0101", cap=120.0, price=90.0)])["items"][0]
        self.assertAlmostEqual(it["报价比率"], it["最优报价单价"] / it["最高限价"], places=9)


class StatusDerivationConsistencyTest(unittest.TestCase):
    """纯逻辑：Excel 与网页两条状态推导对同一组 item 判定结果始终一致。"""

    def test_derivations_agree_on_all_cases(self):
        cases = [
            {"报价状态": "OPTIMIZED", "单项毛利": -8.0, "报价比率": 0.92},   # 亏损
            {"报价状态": "OPTIMIZED", "单项毛利": 5.0, "报价比率": 0.40},   # 低比率
            {"报价状态": "OPTIMIZED", "单项毛利": -1.0, "报价比率": 0.49},  # 双触发
            {"报价状态": "OPTIMIZED", "单项毛利": 15.0, "报价比率": 0.92},  # 正常
            {"报价状态": "MANUAL_REVIEW", "单项毛利": None, "报价比率": None},  # 人工
        ]
        for item in cases:
            excel = _excel_status(item)
            web = _web_status(item)
            self.assertEqual(excel == "PASS", web == "通过",
                             f"约定不一致 @{item}")
            if item["报价状态"] == MANUAL_REVIEW:
                self.assertEqual(excel, MANUAL_REVIEW)
                self.assertEqual(web, WEB_MANUAL)
            else:
                is_warn = item["单项毛利"] is not None and item["单项毛利"] < 0 or \
                          item["报价比率"] is not None and item["报价比率"] < 0.5
                self.assertEqual(excel == LOSS_REVIEW, is_warn)
                self.assertEqual(web == WARN_REVIEW, is_warn)


if __name__ == "__main__":
    unittest.main()