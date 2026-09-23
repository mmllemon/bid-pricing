import unittest
from pathlib import Path

from bidpricing.audit_log import CHAIN, _event_hash, build_audit_chain, load_audit_log_spec, verify_audit_chain


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

    def _rewritten(self, chain, *, payload=None, operator=None):
        """整体重写链并逐条重算哈希（链内自洽）——用于验证锚点/行为人判据。"""
        evs = [dict(e.to_dict()) for e in chain.events]
        if payload is not None:
            evs[0]["payload"] = payload
        if operator is not None:
            evs[0]["operator"] = operator
        prev = None
        for e in evs:
            e["previous_hash"] = prev
            e["event_hash"] = _event_hash(e)
            prev = e["event_hash"]
        return evs

    def test_rewritten_chain_operator_change_detected(self):
        """回归（A5）：换 operator 重写整链——即便重算全部哈希，链内一致性也破。"""
        chain = build_audit_chain(sections(), run_id="run-1", operator="alice", created_at="2026-01-01T00:00:00Z")
        evs = self._rewritten(chain, operator="mallory")
        ok, errors = verify_audit_chain(evs)
        self.assertFalse(ok)
        self.assertTrue(any("operator" in m for m in errors))

    def test_rewritten_chain_anchor_mismatch(self):
        """回归（A5）：payload 被改 + 重算哈希后，外置锚点（链尾 hash）失配即判重写。"""
        chain = build_audit_chain(sections(), run_id="run-1", operator="alice", created_at="2026-01-01T00:00:00Z")
        anchor = chain.events[-1].event_hash
        evs = self._rewritten(chain, payload={"value": "被篡改"})
        ok, errors = verify_audit_chain(evs, anchor_hash=anchor)
        self.assertFalse(ok)
        self.assertTrue(any("锚点" in m for m in errors))

    def test_clean_chain_anchor_match(self):
        chain = build_audit_chain(sections(), run_id="run-1", operator="alice", created_at="2026-01-01T00:00:00Z")
        ok, errors = verify_audit_chain(chain.events, anchor_hash=chain.events[-1].event_hash)
        self.assertTrue(ok, errors)

    def test_future_timestamp_rejected(self):
        from datetime import datetime, timezone
        chain = build_audit_chain(sections(), run_id="run-1", operator="alice", created_at="2026-01-01T00:00:00Z")
        ok, errors = verify_audit_chain(chain.events, now=datetime(2020, 1, 1, tzinfo=timezone.utc))
        self.assertFalse(ok)
        self.assertTrue(any("未来" in m for m in errors))

    def test_explicit_bad_created_at_blocks_build(self):
        chain = build_audit_chain(sections(), operator="alice", created_at="不是时间戳")
        self.assertEqual(chain.status, "BLOCKED")
        self.assertTrue(any("ISO 8601" in m for m in chain.errors))


if __name__ == "__main__":
    unittest.main()
