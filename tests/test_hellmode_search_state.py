"""Derived strip boundaries, graded incomplete-net search and RECORD barrier.

Tests are about search mechanics. Independently verified physical RECORD is
not implemented and must remain unconstructable on current fixtures.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from hellmode.search_state import (
    SearchState, CertifiedRecord, derive_required_cuts, grade_search_state,
)
from hellmode.copper_model import reconstruct_electrical


ROOT = Path(__file__).resolve().parent.parent


def two_pins(*, different=False, row_b=2, col_b=0, wires=True):
    return {
        "board": {
            "rows": 4, "cols": 7, "cuts": [],
            "wires": ([{"id": "J", "from": {"row": 0, "col": 1},
                       "to": {"row": 2, "col": 1}}] if wires else []),
        },
        "componentDefs": [{"id": "one", "pins": [
            {"id": "1", "offsetRow": 0, "offsetCol": 0}],
            "bodyCells": []}],
        "components": [
            {"id": "A", "defId": "one", "locked": True,
             "boardPos": {"row": 0, "col": 0}},
            {"id": "B", "defId": "one",
             "boardPos": {"row": row_b, "col": col_b}},
        ],
        "netAssignments": [
            {"componentId": "A", "pinId": "1", "netId": "N"},
            {"componentId": "B", "pinId": "1",
             "netId": "M" if different else "N"},
        ],
    }


class SearchStateContractTests(unittest.TestCase):
    def test_disconnected_net_groups_supply_graded_penalty_not_binary_failure(self):
        board = two_pins(wires=False)
        raw = copy.deepcopy(board)
        assessment = grade_search_state(board, {})
        self.assertEqual(assessment.disconnected_group_excess, 1)
        self.assertEqual(assessment.disconnected_net_count, 1)
        self.assertEqual(assessment.short_group_excess, 0)
        self.assertEqual(assessment.excess_gap_occupancy, 0)
        self.assertTrue(assessment.search_electrical_open)
        self.assertEqual(board, raw)
        self.assertEqual(reconstruct_electrical(board)["status"], "FAIL")

    def test_reconnecting_affected_terminal_groups_decreases_gradient(self):
        board = two_pins()
        penalty = grade_search_state(board, {"J": "N"})
        self.assertEqual(penalty.disconnected_group_excess, 0)
        self.assertEqual(penalty.short_group_excess, 0)
        self.assertEqual(penalty.max_stack_depth, 1)
        self.assertTrue(penalty.strict_2d_penalty_zero)
        self.assertEqual(reconstruct_electrical(board)["status"], "PASS")

    def test_derived_cut_is_inserted_only_for_different_net_anchors(self):
        source = two_pins(different=True, row_b=0, col_b=5, wires=False)
        self.assertGreater(grade_search_state(source, {}).short_group_excess, 0)
        candidate, provenance = derive_required_cuts(source, {})
        self.assertEqual(len(candidate["board"]["cuts"]), 1)
        self.assertEqual(provenance["cuts_added"], 1)
        self.assertEqual(provenance["electrical_certification"], "UNVERIFIED")
        self.assertEqual(grade_search_state(candidate, {}).short_group_excess, 0)
        self.assertEqual(reconstruct_electrical(candidate)["status"], "PASS")
        self.assertEqual(source["board"]["cuts"], [])

    def test_derived_cut_prefers_preexisting_safe_boundary_instead_of_searching(self):
        source = two_pins(different=True, row_b=0, col_b=5, wires=False)
        source["board"]["cuts"] = [
            {"row": 0, "col": 4, "kind": "between"},
            {"row": 3, "col": 0, "kind": "between"},
        ]
        result, report = derive_required_cuts(source, {})
        self.assertEqual(result["board"]["cuts"], [
            {"row": 0, "col": 4, "kind": "between"},
        ])
        self.assertEqual(report["cuts_kept_from_input"], 1)
        self.assertEqual(report["cuts_removed"], 1)
        self.assertEqual(report["cuts_added"], 0)
        self.assertEqual(source["board"]["cuts"].__len__(), 2)

    def test_jumper_endpoint_ownership_participates_in_derived_cut_policy(self):
        source = two_pins(different=True, row_b=2, col_b=6, wires=False)
        source["board"]["wires"] = [
            {"id": "N-W", "from": {"row": 0, "col": 0},
             "to": {"row": 1, "col": 0}},
            {"id": "M-W", "from": {"row": 2, "col": 6},
             "to": {"row": 1, "col": 6}},
        ]
        owner = {"N-W": "N", "M-W": "M"}
        self.assertGreater(grade_search_state(source, owner).short_group_excess, 0)
        changed, stats = derive_required_cuts(source, owner)
        self.assertEqual(changed["board"]["cuts"], [
            {"row": 1, "col": 2, "kind": "between"}
        ])
        self.assertEqual(stats["cuts_derived"], 1)
        self.assertEqual(reconstruct_electrical(changed)["status"], "PASS")

    def test_unrepairable_same_hole_shorts_are_not_mislabelled_cut_feasible(self):
        source = two_pins(different=True, row_b=0, col_b=0, wires=False)
        self.assertGreater(grade_search_state(source, {}).short_group_excess, 0)
        with self.assertRaisesRegex(ValueError, "share hole"):
            derive_required_cuts(source, {})

    def test_missing_wire_ownership_is_hard_error_never_inferred_from_label(self):
        source = two_pins()
        with self.assertRaisesRegex(ValueError, "ownership"):
            derive_required_cuts(source, {})
        with self.assertRaisesRegex(ValueError, "ownership"):
            grade_search_state(source, {})

    def test_search_state_is_immutable_snapshot_and_cannot_become_record(self):
        source = two_pins(wires=False)
        probe = SearchState.from_candidate(source, {})
        before = probe.fingerprint()
        candidate = probe.raw_candidate()
        candidate["board"]["rows"] = 333
        self.assertEqual(probe.fingerprint(), before)
        self.assertEqual(probe.raw_candidate(), source)
        self.assertTrue(probe.penalty.search_electrical_open)
        with self.assertRaisesRegex(RuntimeError, "SEARCH_STATE"):
            probe.to_record()

    def test_record_factory_independently_rejects_electrical_only_result(self):
        source = two_pins()
        self.assertEqual(reconstruct_electrical(source)["status"], "PASS")
        with self.assertRaisesRegex(ValueError, "withheld RECORD"):
            CertifiedRecord.from_project(source)
        with self.assertRaises(TypeError):
            CertifiedRecord(source, "pretend-verified")

    def test_original_motomix_search_gradient_matches_occupancy_fixture(self):
        source = json.loads(
            (ROOT / "benchmarks/moto/motomix-autorouted.json").read_text()
        )
        proof = reconstruct_electrical(source)
        self.assertEqual(proof["status"], "PASS")
        penalty = grade_search_state(source, proof["wire_nets"])
        self.assertEqual(penalty.disconnected_group_excess, 0)
        self.assertEqual(penalty.short_group_excess, 0)
        self.assertEqual(penalty.cut_count, 57)
        self.assertEqual(penalty.excess_gap_occupancy, 95)
        self.assertEqual(penalty.max_stack_depth, 7)


if __name__ == "__main__":
    unittest.main()
