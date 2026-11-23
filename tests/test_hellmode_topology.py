"""Topology-changing experimental Hell Mode alpha routing checks.

M1/M2 full verification and build certification remain incomplete.
"""
from __future__ import annotations

import copy
import random
import unittest

from hellmode.topology_moves import (
    StripSegments, apply_topology_proposal, topology_proposal,
)
from hellmode.copper_model import reconstruct_electrical
from hellmode.verify_layout import verify_layout
from hellmode.demo import optimize


def mini(*, chain=False):
    segments = [
        {"id": "A", "defId": "pad", "boardPos": {"row": 0, "col": 0}},
        {"id": "B", "defId": "pad", "boardPos": {"row": 4, "col": 0}},
    ]
    wires = [
        {"id": "W", "from": {"row": 0, "col": 1},
         "to": {"row": 2 if chain else 4, "col": 1}},
    ]
    if chain:
        wires.append({
            "id": "W2", "from": {"row": 2, "col": 2},
            "to": {"row": 4, "col": 2},
        })
    return {
        "board": {"rows": 5, "cols": 6, "cuts": [], "wires": wires},
        "componentDefs": [{"id": "pad", "pins": [
            {"id": "1", "offsetRow": 0, "offsetCol": 0}],
            "bodyCells": []}],
        "components": segments,
        "netAssignments": [
            {"componentId": "A", "pinId": "1", "netId": "N"},
            {"componentId": "B", "pinId": "1", "netId": "N"},
        ],
    }


class TopologyMovesTests(unittest.TestCase):
    def test_single_bridge_changes_endpoint_rows_while_preserving_net(self):
        project = mini(chain=True)
        original = copy.deepcopy(project)
        model = StripSegments(project["board"])
        proposals, required = model.candidate_bridges(
            project["board"], "W", allow_detour=False, max_candidates=1000
        )
        self.assertTrue(required)
        self.assertTrue(proposals)
        row_change = [replacement for replacement in proposals if
                      {replacement[0]["from"]["row"], replacement[0]["to"]["row"]}
                      == {0, 4}]
        self.assertTrue(row_change, "must rebridge to other electrically owned row")
        trial = apply_topology_proposal(project, "W", row_change[0])
        self.assertEqual(reconstruct_electrical(trial)["status"], "PASS")
        self.assertEqual(project, original)

    def test_two_wire_detour_connects_through_one_idle_copper_strip(self):
        project = mini(chain=False)
        original = copy.deepcopy(project)
        model = StripSegments(project["board"])
        proposals, required = model.candidate_bridges(
            project["board"], "W", allow_detour=True,
            max_candidates=1000
        )
        self.assertTrue(required)
        detours = [candidate for candidate in proposals
                   if len(candidate) == 2
                   and candidate[0]["from"]["col"] != candidate[1]["from"]["col"]]
        self.assertTrue(detours, "must propose electrically valid two-wire detours")
        good = [apply_topology_proposal(project, "W", p) for p in detours]
        verified = [j for j in good if reconstruct_electrical(j)["status"] == "PASS"]
        self.assertTrue(verified)
        self.assertEqual(len(verified[0]["board"]["wires"]), 2)
        self.assertEqual(project, original)
        self.assertFalse(verify_layout(verified[0])["record_eligible"])

    def test_changed_cut_topology_keeps_endpoints_in_correct_segments(self):
        project = mini()
        project["board"]["cuts"] = [
            {"row": 0, "col": 2, "kind": "between"},
            {"row": 4, "col": 3, "kind": "between"},
        ]
        model = StripSegments(project["board"])
        candidates, required = model.candidate_bridges(
            project["board"], "W", allow_detour=False,
            max_candidates=1000,
        )
        self.assertTrue(required)
        self.assertTrue(candidates)
        self.assertTrue(all(
            p[0]["from"]["col"] <= 2 and p[0]["to"]["col"] <= 2
            for p in candidates
        ))

    def test_same_electrical_component_has_no_essential_rebridge(self):
        project = mini(chain=True)
        project["board"]["wires"].append({
            "id": "W3", "from": {"row": 0, "col": 3},
            "to": {"row": 4, "col": 3},
        })
        model = StripSegments(project["board"])
        proposals, essential = model.candidate_bridges(
            project["board"], "W", allow_detour=True
        )
        self.assertFalse(essential)
        self.assertEqual(proposals, [])

    def test_new_wire_ids_cannot_duplicate_existing_wire(self):
        project = mini(chain=True)
        replacement = (
            {"id": "W2", "from": {"row": 0, "col": 3},
             "to": {"row": 4, "col": 3}},
        )
        with self.assertRaises(ValueError):
            apply_topology_proposal(project, "W", replacement)

    def test_topology_random_proposal_is_seeded_and_pure(self):
        project = mini(chain=True)
        original = copy.deepcopy(project)
        a = topology_proposal(project, random.Random(7), detour=False)
        b = topology_proposal(project, random.Random(7), detour=False)
        self.assertEqual(a, b)
        self.assertIsNotNone(a)
        self.assertEqual(project, original)

    def test_optimize_reports_topology_activity_but_never_physical_pass(self):
        project = mini(chain=True)
        best, report = optimize(project, moves=12, seed=4)
        self.assertEqual(report["moves_requested"], 12)
        self.assertIn("moves_topology_proposed", report)
        self.assertEqual(report["moves_proposed"],
                         report["moves_topology_proposed"]
                         + report["moves_with_column_alternative"])
        self.assertEqual(reconstruct_electrical(best)["status"], "PASS")
        self.assertFalse(report["record_eligible"])
        self.assertFalse(report["physical_pass"])


if __name__ == "__main__":
    unittest.main()
