import unittest
from pathlib import Path

from bidpricing.audit_log import CHAIN, build_audit_chain, load_audit_log_spec, verify_audit_chain


ROOT = Path(__file__).resolve().parents[1]


def sections():
    return {name: {"value": name.lower()} for name in CHAIN}


class AuditLogTest(unittest.TestCase):
    def test_spec_declares_chain(self):
        spec = load_audit_log_spec(ROOT / "config")
        self.assertEqual(spec["chain"], list(CHAIN))

    def test_complete_chain_passes(self):
        chain = build_audit_chain(sections(), run_id="run-1", operator="alice", created_at="2026-01-01T00:00:00Z")
        self.assertEqual(chain.status, "PASS")
        self.assertEqual(len(chain.events), 8)
        self.assertTrue(verify_audit_chain(chain.events)[0])

    def test_tamper_is_detected(self):
        chain = build_audit_chain(sections(), run_id="run-1", operator="alice", created_at="2026-01-01T00:00:00Z")
        tampered = list(chain.events)
        tampered[3] = type(tampered[3])(**{**tampered[3].to_dict(), "payload": {"value": "changed"}})
        ok, errors = verify_audit_chain(tampered)
        self.assertFalse(ok)
        self.assertTrue(any("校验失败" in error or "链接错误" in error for error in errors))

    def test_missing_section_blocks(self):
        raw = sections()
        del raw["Decision"]
        chain = build_audit_chain(raw, operator="alice")
        self.assertEqual(chain.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
