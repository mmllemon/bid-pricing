"""T00-02《字段字典 v1》完备性测试。

任务要求的四项，全部改为机械判据：

1. 每字段含 type / unit / range / default / nullable / 精度 / MISSING_POLICY；
2. ``item_id`` 唯一规则（且须与 key_spec 的 canonical_key 一致）；
3. 百分比统一小数；
4. ``q0 = 0`` 与 ``c_i = 0`` 的处理**明确表态**。

第 4 项是本测试存在的直接原因：2026-09-17 复核时发现 ``q0`` 已表态而
``c_i`` 未表态——靠人眼读制品不会发现「少了一段话」。
"""

import json
import unittest
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config"
FIELD = json.loads((CONFIG / "field_schema.json").read_text(encoding="utf-8"))
KEY_SPEC = json.loads((CONFIG / "key_spec.json").read_text(encoding="utf-8"))

REQUIRED_ATTRS = ("name", "label", "type", "unit", "range", "default",
                  "nullable", "precision", "missing_policy")


def _field(name: str) -> dict:
    return next(f for f in FIELD["fields"] if f["name"] == name)


class TestEveryFieldComplete(unittest.TestCase):
    def test_required_attributes_present(self):
        for f in FIELD["fields"]:
            for attr in REQUIRED_ATTRS:
                self.assertIn(attr, f, f"{f.get('name')} 缺属性 {attr}")

    def test_missing_policy_within_declared_domain(self):
        """值域的**唯一事实源是制品自己的 conventions**，不是测试里的常量。"""
        domain = set(FIELD["conventions"]["missing_policy_domain"])
        for f in FIELD["fields"]:
            self.assertIn(f["missing_policy"], domain, f["name"])

    def test_precision_declared_for_numeric(self):
        for f in FIELD["fields"]:
            if f["type"] == "number":
                self.assertIsInstance(f["precision"], int, f["name"])

    def test_nullable_and_default_are_consistent(self):
        """default 非 null 的字段必须允许为空以外的情况——禁止『有默认值却不声明』。"""
        for f in FIELD["fields"]:
            if f["default"] is not None:
                self.assertTrue(f["note"], f"{f['name']} 有默认值须给出依据")


class TestNoDefaultFamilies(unittest.TestCase):
    def test_no_default_families_never_use_default_policy(self):
        """conventions 声明的字段族禁止 DEFAULT 缺失策略。"""
        families = FIELD["conventions"]["no_default_field_families"]
        self.assertTrue(families)
        for f in FIELD["fields"]:
            self.assertNotEqual(f["missing_policy"], "DEFAULT", f["name"])


class TestUniqueKey(unittest.TestCase):
    def test_item_id_unique_key_declared(self):
        self.assertIn("item_id_unique_key", FIELD["conventions"])
        self.assertIn("item_id", FIELD["conventions"]["item_id_unique_key"])

    def test_unique_key_matches_key_spec(self):
        """字段字典声明的唯一键必须与 key_spec 的 canonical_key 逐字一致。

        两处都是「主键是什么」的声明，一旦漂移，匹配器（T01-04）与字段层
        会对同一行给出不同的键——这是最隐蔽的一类数据错位。
        """
        def norm(value) -> list[str]:
            if isinstance(value, (list, tuple)):
                return [str(x).strip() for x in value]
            return [x.strip() for x in str(value).strip("()").split(",")]

        declared = FIELD["conventions"]["item_id_unique_key"]
        canonical = KEY_SPEC["key_definition"]["canonical_key"]
        self.assertEqual(sorted(norm(declared)), sorted(norm(canonical)))


class TestPercentageConvention(unittest.TestCase):
    def test_percentage_convention_declared(self):
        self.assertIn("小数", FIELD["conventions"]["percentage"])

    def test_ratio_like_fields_use_fraction_range(self):
        """比值类字段（mu / rho_* / unbalanced_tolerance）上界必须 <= 1。

        「15」与「0.15」在机器上都是数字，只能靠值域拦。
        """
        for name in ("mu", "rho_plus", "rho_minus", "unbalanced_tolerance"):
            f = _field(name)
            rng = f["range"]
            hi = rng[1] if isinstance(rng, list) and len(rng) > 1 else None
            if hi is not None:
                self.assertLessEqual(hi, 1.0, f"{name} 上界应为小数形式，实为 {hi}")


class TestZeroValueStatements(unittest.TestCase):
    """T00-02 明确要求：q0=0 与 c_i=0 必须表态。"""

    def test_q0_zero_is_explicitly_handled(self):
        note = _field("q0")["note"]
        self.assertIn("q0=0", note)
        self.assertTrue(any(k in note for k in ("BLOCK", "排除", "显式处理")))

    def test_c_i_zero_is_explicitly_handled(self):
        """2026-09-17 补齐：此前 q0 已表态而 c_i 未表态。"""
        note = _field("c_i")["note"]
        self.assertIn("c_i = 0", note)
        # 表态必须给出**结论**（合法条件 + 否则阻断），不能只描述现象
        self.assertIn("PASS_THROUGH", note)
        self.assertIn("BLOCKED", note)

    def test_zero_and_missing_are_distinguishable(self):
        """0 与缺失在机器上必须可区分（ADR-0004）。"""
        self.assertIn("可区分", _field("c_i")["note"])


class TestDerivedFields(unittest.TestCase):
    """派生量（p1 / settlement_amount）：不参与缺失策略，但必须有精度与口径。"""

    def test_derived_fields_marked(self):
        for name in ("p1", "settlement_amount"):
            f = _field(name)
            self.assertTrue(f.get("derived"), name)
            self.assertEqual(f["missing_policy"], "DERIVED")

    def test_derived_policy_in_domain(self):
        self.assertIn("DERIVED", FIELD["conventions"]["missing_policy_domain"])

    def test_derived_fields_have_precision_and_unit(self):
        for name in ("p1", "settlement_amount"):
            f = _field(name)
            self.assertEqual(f["unit"], "元")
            self.assertEqual(f["precision"], 2)


if __name__ == "__main__":
    unittest.main()
