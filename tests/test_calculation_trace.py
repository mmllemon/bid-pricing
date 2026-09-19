import unittest
from pathlib import Path

from bidpricing.calculation_trace import STAGES, build_calculation_trace, load_calculation_trace_spec


ROOT = Path(__file__).resolve().parents[1]


def chain():
    stages = {}
    previous = None
    for stage in STAGES:
        node_id = stage.lower()
        stages[stage] = [{
            "node_id": node_id,
            "source_refs": [f"source:{stage}"],
            "inputs": ["input" if previous is None else previous],
            "outputs": [node_id + ":out"],
            "derivation": f"{stage} deterministic derivation",
            "upstream_ids": [] if previous is None else [previous],
        }]
        previous = node_id
    return stages


class CalculationTraceTest(unittest.TestCase):
    def test_spec_declares_seven_stages(self):
        spec = load_calculation_trace_spec(ROOT / "config")
        self.assertEqual(spec["stages"], list(STAGES))

    def test_complete_chain_passes(self):
        trace = build_calculation_trace(chain())
        self.assertEqual(trace.status, "PASS")
        self.assertEqual(len(trace.nodes), 7)

    def test_missing_stage_is_blocked(self):
        stages = chain()
        del stages["Solver"]
        trace = build_calculation_trace(stages)
        self.assertEqual(trace.status, "BLOCKED")
        self.assertTrue(any("缺少阶段" in error for error in trace.errors))

    def test_broken_upstream_is_blocked(self):
        stages = chain()
        stages["Report"][0]["upstream_ids"] = ["not-exist"]
        trace = build_calculation_trace(stages)
        self.assertEqual(trace.status, "BLOCKED")
        self.assertTrue(any("未连接" in error or "未知 upstream" in error for error in trace.errors))


if __name__ == "__main__":
    unittest.main()
