"""M1-9 STRICT 2D occupancy acceptance tests — NOT full PHYSICAL_PASS.

The independent checker must never import the earlier spike, Quick Solve,
a router, or an electrical-verifier implementation.
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from hellmode.strict_occupancy import audit_strict_occupancy


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "hellmode/strict_occupancy.py"
GOLDEN = ROOT / "benchmarks/moto/motomix-autorouted.json"


def jumper(label, r0, r1, *, col=1, claimed_net=None):
    # claimed_net is deliberately untrusted and must be ignored.
    wire = {
        "id": label, "from": {"row": r0, "col": col},
        "to": {"row": r1, "col": col},
    }
    if claimed_net is not None:
        wire["netId"] = claimed_net
    return wire


def inspect(*wires, pads=None, ownership=None):
    return audit_strict_occupancy(
        {"rows": 6, "cols": 5, "cuts": [], "wires": list(wires)},
        pin_holes=pads, trusted_wire_nets=ownership,
    )


def codes(report):
    return {f["code"] for f in report["findings"]}


class StrictOccupancyM1Tests(unittest.TestCase):
    def test_motomix_frozen_projection_has_51_gaps_and_95_excess(self):
        project = json.loads(GOLDEN.read_text())
        report = audit_strict_occupancy(project["board"])
        self.assertEqual(report["status"], "STRICT_OCCUPANCY_VIOLATION")
        self.assertEqual(report["counts"]["wires"], 46)
        self.assertEqual(report["counts"]["overlap_pairs"], 33)
        self.assertEqual(report["counts"]["stacked_gaps"], 51)
        self.assertEqual(report["counts"]["excess_gap_occupancy"], 95)
        self.assertEqual(report["counts"]["max_stack_depth"], 7)
        self.assertEqual(report["counts"]["shared_landing_holes"], 0)
        self.assertIn("STACKING_VIOLATION", codes(report))
        critical = [f for f in report["findings"]
                    if f["code"] == "STACKING_VIOLATION"
                    and f["col"] == 2 and f["gap_row"] == 8]
        self.assertEqual(len(critical), 1)
        self.assertEqual(critical[0]["depth"], 7)
        self.assertEqual(set(critical[0]["wires"]), {
            "RM-W002", "RM-W007", "RM-W010", "RM-W016",
            "RM-W025", "RM-W031", "RM-W032",
        })
        self.assertEqual(report["pad_evidence"], "NOT_SUPPLIED")
        self.assertFalse(report["physical_pass"])
        self.assertEqual(report["cut_access"], "unverified")

    def test_identical_spans_fail_for_same_or_different_claimed_nets(self):
        for net_b in ("A", "B"):
            with self.subTest(net_b=net_b):
                report = inspect(jumper("w1", 0, 4, claimed_net="A"),
                                 jumper("w2", 0, 4, claimed_net=net_b))
                self.assertEqual(report["counts"]["stacked_gaps"], 4)
                self.assertEqual(report["counts"]["excess_gap_occupancy"], 4)
                self.assertEqual(report["counts"]["shared_landing_holes"], 2)
                self.assertEqual(report["status"], "STRICT_OCCUPANCY_VIOLATION")

    def test_contained_and_partially_overlapping_intervals_fail(self):
        for a, b, expected in ((jumper("a", 0, 5), jumper("b", 2, 4), 2),
                               (jumper("a", 0, 3), jumper("b", 2, 5), 1)):
            with self.subTest(a=a, b=b):
                report = inspect(a, b)
                self.assertEqual(report["counts"]["excess_gap_occupancy"], expected)
                self.assertIn("STACKING_VIOLATION", codes(report))

    def test_endpoint_on_other_span_has_explicit_reason(self):
        report = inspect(jumper("A", 0, 4), jumper("B", 2, 5))
        self.assertEqual(report["counts"]["endpoint_on_span_holes"], 2)
        self.assertIn("JUMPER_ENDPOINT_ON_SPAN", codes(report))

    def test_end_to_end_touching_has_shared_hole_but_no_shared_gap(self):
        report = inspect(jumper("A", 0, 3), jumper("B", 3, 5))
        self.assertEqual(report["counts"]["stacked_gaps"], 0)
        self.assertEqual(report["counts"]["shared_landing_holes"], 1)
        self.assertIn("JUMPER_SHARED_HOLE", codes(report))

    def test_separate_or_adjacent_columns_have_no_logical_gap_collision(self):
        report = inspect(jumper("A", 0, 5, col=1),
                         jumper("B", 0, 5, col=2))
        self.assertEqual(report["status"], "STRICT_2D_CLEAR")
        self.assertEqual(report["counts"]["stacked_gaps"], 0)
        self.assertFalse(report["physical_pass"])  # 2D != measured 2.5D
        self.assertEqual(report["pad_evidence"], "NOT_SUPPLIED")

    def test_jumper_body_cannot_pass_over_intermediate_pin_hole(self):
        pad = {"row": 3, "col": 1, "net_id": "A", "ref": "U1.1"}
        report = inspect(jumper("J1", 0, 5), pads=[pad],
                         ownership={"J1": "A"})
        self.assertIn("INTERMEDIATE_PAD_PASS_THROUGH", codes(report))
        self.assertEqual(report["counts"]["intermediate_pad_holes"], 1)

    def test_explicit_same_net_endpoint_landing_can_pass_2d_check(self):
        pad = {"row": 0, "col": 1, "net_id": "A", "ref": "R1.1"}
        report = inspect(jumper("J1", 0, 3), pads=[pad],
                         ownership={"J1": "A"})
        self.assertEqual(report["status"], "STRICT_2D_CLEAR")
        self.assertEqual(report["counts"]["landing_net_conflicts"], 0)
        self.assertEqual(report["counts"]["landing_net_unverified"], 0)
        self.assertFalse(report["physical_pass"])

    def test_different_net_endpoint_landing_is_rejected(self):
        pad = {"row": 0, "col": 1, "net_id": "B", "ref": "R1.1"}
        report = inspect(jumper("J1", 0, 3), pads=[pad],
                         ownership={"J1": "A"})
        self.assertIn("JUMPER_LANDING_DIFFERENT_NET", codes(report))
        self.assertEqual(report["counts"]["landing_net_conflicts"], 1)

    def test_missing_independent_net_evidence_withholds_landing_clearance(self):
        pad = {"row": 0, "col": 1, "net_id": "B", "ref": "R1.1"}
        report = inspect(jumper("J1", 0, 3, claimed_net="B"), pads=[pad])
        self.assertIn("PIN_LANDING_NET_UNVERIFIED", codes(report))
        self.assertEqual(report["wire_net_evidence"], "NOT_SUPPLIED")

    def test_different_net_component_pins_in_same_hole_rejected(self):
        pads = [{"row": 0, "col": 1, "net_id": "A", "ref": "A.1"},
                {"row": 0, "col": 1, "net_id": "B", "ref": "B.1"}]
        report = inspect(pads=pads, ownership={})
        self.assertIn("DIFFERENT_NET_PINS_SAME_HOLE", codes(report))
        self.assertEqual(report["counts"]["different_net_pad_holes"], 1)

    def test_rejects_non_vertical_outside_duplicate_and_invalid_boards(self):
        samples = [
            ({"rows": 3, "cols": 5, "wires": [jumper("A", 1, 1)]}, ValueError),
            ({"rows": 3, "cols": 5, "wires": [jumper("A", 0, 3)]}, ValueError),
            ({"rows": 6, "cols": 5, "wires": [jumper("A", 0, 3), jumper("A", 2, 5)]}, ValueError),
            ({"rows": 6, "cols": 5, "wires": [{"id": "B", "from": {"row": 0, "col": 0},
                                              "to": {"row": 2, "col": 1}}]}, ValueError),
        ]
        for board, error in samples:
            with self.subTest(board=board), self.assertRaises(error):
                audit_strict_occupancy(board)

    def test_import_graph_has_no_quick_solver_or_verifier_dependency(self):
        tree = ast.parse(SOURCE.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(x.name for x in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        for forbidden in ("solve", "router", "verify", "quick_rules",
                          "hellmode_m1_spike", "physical_geometry"):
            self.assertFalse(any(x == forbidden or x.startswith(forbidden + ".")
                                 for x in imports), imports)


if __name__ == "__main__":
    unittest.main()
