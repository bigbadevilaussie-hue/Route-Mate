"""Independent fixed-span feasibility and congestion morphology diagnostics."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from hellmode.diagnostic import diagnose, _clusters, _exact_coloring, _match
from hellmode.copper_model import reconstruct_electrical


ROOT = Path(__file__).resolve().parent.parent


def fixture(*, rows=4, cols=4, spans=((0, 3, 0), (0, 3, 1))):
    return {
        "board": {
            "rows": rows, "cols": cols, "cuts": [], "wires": [
                {"id": f"W{i+1}",
                 "from": {"row": lo, "col": col},
                 "to": {"row": hi, "col": col}}
                for i, (lo, hi, col) in enumerate(spans)
            ],
        },
        "componentDefs": [{"id": "one", "pins": [
            {"id": "1", "offsetRow": 0, "offsetCol": 0}], "bodyCells": []}],
        "components": [
            {"id": "A", "defId": "one", "boardPos": {"row": 0, "col": 0}},
            {"id": "B", "defId": "one", "boardPos": {"row": rows - 1, "col": 0}},
        ],
        "netAssignments": [
            {"componentId": "A", "pinId": "1", "netId": "N"},
            {"componentId": "B", "pinId": "1", "netId": "N"},
        ],
    }


class ExactFixedSpanDiagnosticTests(unittest.TestCase):
    def test_simple_sat_is_returned_and_independently_rechecked(self):
        board = fixture()
        pristine = copy.deepcopy(board)
        self.assertEqual(reconstruct_electrical(board)["status"], "PASS")
        report = diagnose(board)
        self.assertEqual(report["exact_global_fixed_span_assignment"]["status"],
                         "SAT_EXACT")
        self.assertEqual(report["hall_infeasible_row_gaps"], [])
        self.assertEqual(len(report["exact_global_fixed_span_assignment"][
            "column_assignment"]), 2)
        self.assertEqual(board, pristine)
        self.assertFalse(any("physical_pass" in x for x in report["counts"]))

    def test_hall_gap_infeasibility_is_actual_proof_not_heuristic(self):
        board = fixture(
            rows=3, cols=3,
            spans=((0, 2, 0), (0, 2, 1), (0, 2, 0)),
        )
        for row in (0, 2):
            board["board"]["cuts"].append({
                "row": row, "col": 1, "kind": "between"
            })
        self.assertEqual(reconstruct_electrical(board)["status"], "PASS")
        report = diagnose(board)
        self.assertEqual(report["exact_global_fixed_span_assignment"]["status"],
                         "UNSAT_PROVED_BY_HALL_GAP")
        self.assertIn(0, report["hall_infeasible_row_gaps"])
        hall = report["row_gap_bounds"][0]["hall_witness"]
        self.assertEqual(hall["jumper_count"], 3)
        self.assertEqual(hall["column_count"], 2)
        self.assertEqual(hall["minimum_collision_deficit"], 1)

    def test_global_endpoint_conflict_is_proven_even_when_each_gap_matches(self):
        board = fixture(
            rows=3, cols=2,
            spans=((0, 1, 0), (1, 2, 0)),
        )
        for row in (0, 1, 2):
            board["board"]["cuts"].append({
                "row": row, "col": 0, "kind": "between",
            })
        self.assertEqual(reconstruct_electrical(board)["status"], "PASS")
        report = diagnose(board)
        self.assertEqual(report["hall_infeasible_row_gaps"], [])
        self.assertEqual(report["exact_global_fixed_span_assignment"]["status"],
                         "UNSAT_EXACT")
        self.assertEqual(report["minimum_per_gap_deficit"], 0)

    def test_scattered_clusters_are_classified_separately(self):
        report = _clusters([
            {"code": "STACKING_VIOLATION", "col": 0, "gap_row": 1,
             "depth": 2, "wires": ["W1", "W2"]},
            {"code": "STACKING_VIOLATION", "col": 8, "gap_row": 8,
             "depth": 2, "wires": ["W3", "W4"]},
        ])
        self.assertEqual(report["spatial_cluster_count"], 2)
        self.assertEqual(report["wire_cluster_count"], 2)
        self.assertEqual(report["largest_spatial_share"], .5)
        self.assertEqual(report["largest_wire_conflict_share"], .5)

    def test_shared_wire_links_distant_spatial_conflicts(self):
        report = _clusters([
            {"code": "STACKING_VIOLATION", "col": 0, "gap_row": 0,
             "depth": 2, "wires": ["W1", "W2"]},
            {"code": "STACKING_VIOLATION", "col": 0, "gap_row": 5,
             "depth": 2, "wires": ["W2", "W3"]},
        ])
        self.assertEqual(report["spatial_cluster_count"], 2)
        self.assertEqual(report["wire_cluster_count"], 1)

    def test_exact_backtracker_never_labels_truncated_run_infeasible(self):
        domains = {f"W{i}": tuple(range(3)) for i in range(9)}
        spans = {wid: (0, 3) for wid in domains}
        result = _exact_coloring(domains, spans, node_limit=1)
        self.assertEqual(result["status"], "UNKNOWN_NODE_LIMIT")
        self.assertEqual(result["nodes_visited"], 1)

    def test_bipartite_max_matching_is_exact(self):
        options = {
            "a": (0, 1),
            "b": (0,),
            "c": (1, 2),
        }
        matching = _match(list(options), options)
        self.assertEqual(len(matching), 3)
        self.assertEqual(set(matching.values()), set(options))

    def test_original_motomix_known_row_gap_8_hall_witness(self):
        board = json.loads(
            (ROOT / "benchmarks/moto/motomix-autorouted.json").read_text()
        )
        report = diagnose(board)
        known = {
            "RM-W002", "RM-W007", "RM-W010", "RM-W016",
            "RM-W025", "RM-W031", "RM-W032",
        }
        options = report["jumper_domains"]
        subset = set().union(*(
            set(options[wid]["strict_pad_eligible_columns"])
            for wid in known
        ))
        self.assertLessEqual(len(subset), 5)
        self.assertIn(8, report["hall_infeasible_row_gaps"])
        self.assertEqual(report["exact_global_fixed_span_assignment"]["status"],
                         "UNSAT_PROVED_BY_HALL_GAP")
        self.assertEqual(report["counts"]["observed_excess_gap_occupancy"], 95)
        self.assertGreater(report["clusters"]["spatial_cluster_count"], 0)


if __name__ == "__main__":
    unittest.main()
