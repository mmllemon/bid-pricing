import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.solver.parity import compare_phase12, independence_status, load_spec


class ParityTest(unittest.TestCase):
    def signoff(self, root: Path, signed=True):
        p = root / "reference_review_signoff.json"
        p.write_text(json.dumps({"signed": signed, "reviewer": "reviewer" if signed else ""}), encoding="utf-8")
        return p

    def test_spec_and_signed_match(self):
        self.assertEqual(load_spec()["groups"], ["A", "B"])
        with tempfile.TemporaryDirectory() as d:
            signoff = self.signoff(Path(d))
            a = {"objective": 10.0, "prices": {"x": 2.0}, "layers": {"x": "INTERIOR"}}
            result = compare_phase12(a, dict(a), signoff_path=signoff)
            self.assertEqual(result.status, "PASS")
            self.assertEqual(result.level, "L3")

    def test_unsigned_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            signoff = self.signoff(Path(d), signed=False)
            result = compare_phase12({"objective": 1, "prices": {}}, {"objective": 1, "prices": {}}, signoff_path=signoff)
            self.assertEqual(result.status, "BLOCKED")

    def test_numeric_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as d:
            signoff = self.signoff(Path(d))
            result = compare_phase12({"objective": 1, "prices": {"x": 1}}, {"objective": 2, "prices": {"x": 1}}, signoff_path=signoff)
            self.assertEqual(result.status, "FAIL")
            self.assertEqual(result.level, "L2")

    def test_inapplicable_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            signoff = self.signoff(Path(d))
            result = compare_phase12({"objective": 1, "prices": {}}, {"objective": 1, "prices": {}}, applicable=False, signoff_path=signoff)
            self.assertEqual(result.status, "BLOCKED")

    def test_missing_signoff_is_blocked(self):
        self.assertEqual(independence_status("does-not-exist.json"), "BLOCKED")


if __name__ == "__main__":
    unittest.main()
