"""Real search smoke tests for Hell Mode CLI alpha; no physical-record claims."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from hellmode.demo import optimize, run_files, _same_copper_columns
from hellmode.copper_model import reconstruct_electrical
from hellmode.verify_layout import verify_layout


ROOT = Path(__file__).resolve().parent.parent


def tiny():
    return {
        "board": {"rows": 4, "cols": 6, "cuts": [], "wires": [
            {"id": "W1", "from": {"row": 0, "col": 1},
             "to": {"row": 2, "col": 1}},
            {"id": "W2", "from": {"row": 0, "col": 2},
             "to": {"row": 2, "col": 2}},
        ]},
        "componentDefs": [{"id": "one", "pins": [
            {"id": "1", "offsetRow": 0, "offsetCol": 0}],
            "bodyCells": []}],
        "components": [
            {"id": "A", "defId": "one", "boardPos": {"row": 0, "col": 0}},
            {"id": "B", "defId": "one", "boardPos": {"row": 2, "col": 0}},
        ],
        "netAssignments": [
            {"componentId": "A", "pinId": "1", "netId": "N"},
            {"componentId": "B", "pinId": "1", "netId": "N"},
        ],
    }


class RunnableHellModeAlphaTests(unittest.TestCase):
    def test_real_search_prunes_electrically_redundant_wire(self):
        source = tiny()
        untouched = copy.deepcopy(source)
        best, run = optimize(source, moves=25, seed=7)
        self.assertEqual(source, untouched)
        self.assertEqual(run["baseline"]["wires"], 2)
        # Later search stages may relocate a component and eliminate
        # the last jumper as well; never require a worse fixed count.
        self.assertLessEqual(run["best_exploratory"]["wires"], 1)
        self.assertEqual(len(run["redundant_wires_removed"]), 1)
        self.assertEqual(reconstruct_electrical(best)["status"], "PASS")
        self.assertFalse(run["record_eligible"])
        self.assertFalse(run["physical_pass"])
        self.assertEqual(run["cut_access"], "unverified")
        self.assertEqual(run["mode"], "HELL_MODE_ALPHA_ELECTRICAL_ONLY")
        
    def test_seeded_search_replays_same_result_and_counts(self):
        first, a = optimize(tiny(), moves=40, seed=1337)
        second, b = optimize(tiny(), moves=40, seed=1337)
        self.assertEqual(first, second)
        self.assertEqual(a, b)

    def test_invalid_electrical_source_is_not_returned_as_solution(self):
        invalid = tiny()
        invalid["board"]["wires"] = []
        with self.assertRaises(ValueError):
            optimize(invalid, moves=10)

    def test_column_domain_respects_fixed_between_hole_cuts(self):
        board = tiny()["board"]
        board["cuts"] = [{"row": 0, "col": 1, "kind": "between"},
                         {"row": 2, "col": 3, "kind": "between"}]
        self.assertEqual(_same_copper_columns(board, 0, 1), {0, 1})
        self.assertEqual(_same_copper_columns(board, 2, 1), {0, 1, 2, 3})

    def test_run_files_writes_baseline_search_result_and_replay_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.json"
            source.write_text(json.dumps(tiny()))
            outdir = root / "result"
            report = run_files(source, outdir, moves=10, seed=5)
            self.assertTrue((outdir / "run.json").exists())
            self.assertTrue((outdir / "baseline_solved.json").exists())
            self.assertTrue((outdir / "best_electrical.json").exists())
            self.assertTrue((outdir / "history.csv").exists())
            self.assertFalse((outdir / "best_solved.json").exists())
            self.assertEqual(report["seed"], 5)
            self.assertEqual(report["baseline"]["wires"], 2)
            self.assertLessEqual(report["best_exploratory"]["wires"], 1)
            self.assertEqual(json.loads((outdir / "baseline_solved.json").read_text()), tiny())

    def test_actual_motomix_alpha_smoke_never_false_certifies(self):
        project = json.loads((ROOT / "benchmarks/moto/motomix-autorouted.json").read_text())
        original = copy.deepcopy(project)
        best, report = optimize(project, moves=8, seed=1)
        self.assertEqual(project, original)
        self.assertEqual(reconstruct_electrical(best)["status"], "PASS")
        self.assertTrue(report["baseline"]["electrical_pass"])
        self.assertFalse(report["record_eligible"])
        self.assertFalse(report["physical_pass"])
        self.assertLessEqual(
            report["best_exploratory"]["excess_gap_occupancy"],
            report["baseline"]["excess_gap_occupancy"],
        )
        self.assertFalse(verify_layout(best)["record_eligible"])


if __name__ == "__main__":
    unittest.main()
