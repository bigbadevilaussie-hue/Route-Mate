"""Proof-targeted conflict repair: clustered wires, actual electrical proof."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from hellmode.hall_guided_repair import repair_hall_clusters
from hellmode.copper_model import reconstruct_electrical
from hellmode.demo import _electrically_valid, _priority, report_metrics, optimize


ROOT = Path(__file__).resolve().parent.parent


def pair_overlap():
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


def run(source, **kwargs):
    graph = reconstruct_electrical(source)
    return repair_hall_clusters(
        source, wire_nets=graph["wire_nets"],
        pads=graph["pin_holes"],
        electrical_check=_electrically_valid,
        metric_reader=report_metrics,
        quality_key=_priority,
        **kwargs,
    )


class HallGuidedRepairTests(unittest.TestCase):
    def test_targets_real_spatial_conflicts_and_reduces_stack(self):
        source = pair_overlap()
        baseline = copy.deepcopy(source)
        self.assertTrue(_electrically_valid(source))
        result, report = run(
            source, seed=3, max_pair_trials=200,
            candidates_per_wire=24, max_electrical_checks=20,
        )
        self.assertGreater(report["trials_scored"], 0)
        self.assertEqual(report["spatial_clusters"], 1)
        self.assertEqual(report["target_wire_groups"], [["M-W", "N-W"]])
        self.assertGreater(report["verified_improvements"], 0)
        self.assertLess(report_metrics(result)["excess_gap_occupancy"],
                        report["initial_excess"])
        self.assertTrue(_electrically_valid(result))
        self.assertFalse(report["record_eligible"])
        self.assertEqual(source, baseline)

    def test_seed_and_budget_reproducibility(self):
        source = pair_overlap()
        kwargs = dict(
            seed=21, max_pair_trials=70,
            candidates_per_wire=12, max_electrical_checks=10,
        )
        a, ra = run(source, **kwargs)
        b, rb = run(source, **kwargs)
        self.assertEqual(a, b)
        self.assertEqual(ra, rb)

    def test_electrical_failure_never_promoted_as_best(self):
        source = pair_overlap()
        before = copy.deepcopy(source)
        verified, report = run(
            source, seed=3, max_pair_trials=150,
            candidates_per_wire=16, max_electrical_checks=12,
        )
        self.assertTrue(_electrically_valid(verified))
        self.assertEqual(source, before)
        self.assertFalse(report["physical_pass"])

    def test_empty_conflict_board_is_noop(self):
        source = pair_overlap()
        source["board"]["wires"][1]["from"]["col"] = 4
        source["board"]["wires"][1]["to"]["col"] = 4
        self.assertTrue(_electrically_valid(source))
        result, report = run(source)
        self.assertEqual(result, source)
        self.assertEqual(report["spatial_clusters"], 0)
        self.assertEqual(report["trials_scored"], 0)

    def test_motomix_is_safe_and_never_regresses_verified_best(self):
        source = json.loads((
            ROOT / "benchmarks/moto/motomix-autorouted.json"
        ).read_text())
        before = copy.deepcopy(source)
        result, report = run(
            source, seed=5, max_pair_trials=45,
            candidates_per_wire=16, max_electrical_checks=5,
        )
        self.assertTrue(_electrically_valid(result))
        self.assertLessEqual(
            report_metrics(result)["excess_gap_occupancy"],
            report["initial_excess"],
        )
        self.assertEqual(source, before)

    def test_cli_exposes_repair_proof_metadata_without_record(self):
        output, manifest = optimize(pair_overlap(), moves=6, seed=1)
        self.assertIn("hall_guided_repair", manifest)
        self.assertTrue(_electrically_valid(output))
        self.assertFalse(manifest["record_eligible"])
        self.assertFalse(manifest["physical_pass"])


if __name__ == "__main__":
    unittest.main()
