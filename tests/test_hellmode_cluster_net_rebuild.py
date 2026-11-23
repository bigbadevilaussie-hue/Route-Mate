"""Electrical-only compound rip-up: all conflicting nets, derived cuts."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from hellmode.cluster_net_rebuild import rebuild_conflicting_nets
from hellmode.copper_model import reconstruct_electrical
from hellmode.demo import _electrically_valid, report_metrics, _priority, optimize

ROOT = Path(__file__).resolve().parent.parent


def fixture():
    return {
        "board": {"rows": 5, "cols": 8, "cuts": [], "wires": [
            {"id": "N-W", "from": {"row": 0, "col": 1},
             "to": {"row": 3, "col": 1}},
            {"id": "M-W", "from": {"row": 1, "col": 1},
             "to": {"row": 4, "col": 1}},
        ]},
        "componentDefs": [{
            "id": "pad", "pins": [
                {"id": "1", "offsetRow": 0, "offsetCol": 0}
            ], "bodyCells": [],
        }],
        "components": [
            {"id": "N1", "defId": "pad", "boardPos": {"row": 0, "col": 0}},
            {"id": "N2", "defId": "pad", "boardPos": {"row": 3, "col": 0}},
            {"id": "M1", "defId": "pad", "boardPos": {"row": 1, "col": 0}},
            {"id": "M2", "defId": "pad", "boardPos": {"row": 4, "col": 0}},
        ],
        "netAssignments": [
            {"componentId": "N1", "pinId": "1", "netId": "N"},
            {"componentId": "N2", "pinId": "1", "netId": "N"},
            {"componentId": "M1", "pinId": "1", "netId": "M"},
            {"componentId": "M2", "pinId": "1", "netId": "M"},
        ],
    }


def run(source, **opts):
    g = reconstruct_electrical(source)
    return rebuild_conflicting_nets(
        source,
        wire_nets=g["wire_nets"],
        pads=g["pin_holes"],
        electrical_check=_electrically_valid,
        metric_reader=report_metrics,
        quality_key=_priority,
        **opts,
    )


class ClusterNetRebuildTests(unittest.TestCase):
    def test_two_conflicting_net_trees_reroute_together(self):
        source = fixture()
        baseline = copy.deepcopy(source)
        self.assertTrue(_electrically_valid(source))
        final, report = run(source, seed=5, variants_per_cluster=8)
        self.assertGreater(report["whole_group_trials"], 0)
        self.assertEqual(report["cluster_nets"], [["M", "N"]])
        self.assertTrue(_electrically_valid(final))
        self.assertLess(report_metrics(final)["excess_gap_occupancy"],
                        report["initial_excess"])
        self.assertEqual(source, baseline)
        self.assertFalse(report["record_eligible"])

    def test_seeded_proposals_replay_exactly(self):
        board = fixture()
        kwargs = dict(seed=21, variants_per_cluster=4)
        a, x = run(board, **kwargs)
        b, y = run(board, **kwargs)
        self.assertEqual(a, b)
        self.assertEqual(x, y)

    def test_repair_of_motomix_cannot_make_verified_board_worse(self):
        source = json.loads(
            (ROOT / "benchmarks/moto/motomix-autorouted.json").read_text()
        )
        original = copy.deepcopy(source)
        final, summary = run(source, seed=1, variants_per_cluster=2)
        self.assertTrue(_electrically_valid(final))
        self.assertLessEqual(
            report_metrics(final)["excess_gap_occupancy"],
            summary["initial_excess"]
        )
        self.assertFalse(summary["physical_pass"])
        self.assertEqual(source, original)

    def test_real_alpha_reports_compound_net_step(self):
        output, report = optimize(fixture(), moves=4, seed=6)
        self.assertIn("cluster_net_rebuild", report)
        self.assertTrue(_electrically_valid(output))
        self.assertFalse(report["record_eligible"])
        self.assertFalse(report["physical_pass"])


if __name__ == "__main__":
    unittest.main()
