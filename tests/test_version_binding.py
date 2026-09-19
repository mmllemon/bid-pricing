import copy
import json
import tempfile
import unittest
from pathlib import Path

from bidpricing.artifact import compute_artifact_hash
from bidpricing.version_binding import capture_binding, validate_binding


class VersionBindingTest(unittest.TestCase):
    def registry(self, root):
        p = root / "a.json"
        p.write_text('{"x": 1}\n', encoding="utf-8")
        h = compute_artifact_hash(p)
        return {"gate_0a": {"a": {"kind": "versioned", "artifact_path": "a.json", "version": h, "hash": h}}, "gate_0b": {}}

    def test_capture_and_validate_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); reg = self.registry(root)
            binding = capture_binding(reg)
            self.assertTrue(validate_binding(binding, reg, root).passed)

    def test_model_version_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); reg = self.registry(root)
            binding = capture_binding(reg, model_version="0.2")
            self.assertFalse(validate_binding(binding, reg, root).passed)

    def test_artifact_drift_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); reg = self.registry(root); binding = capture_binding(reg)
            (root / "a.json").write_text('{"x": 2}\n', encoding="utf-8")
            kinds = {i.kind for i in validate_binding(binding, reg, root).issues}
            self.assertIn("drift", kinds)

    def test_binding_snapshot_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); reg = self.registry(root); binding = capture_binding(reg)
            binding["artifacts"]["gate_0a.a"]["hash"] = "sha256:000000000000"
            kinds = {i.kind for i in validate_binding(binding, reg, root).issues}
            self.assertIn("mismatch", kinds)

    def test_unfrozen_registry_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); reg = self.registry(root); binding = capture_binding(reg)
            reg["gate_0a"]["a"]["hash"] = None
            self.assertFalse(validate_binding(binding, reg, root).passed)


if __name__ == "__main__":
    unittest.main()
