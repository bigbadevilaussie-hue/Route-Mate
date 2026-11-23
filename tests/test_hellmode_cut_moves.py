"""Cut mutations that can be tried by Hell Mode alpha without altering Quick Solve.

Electrical tests are separate from physical buildability. A cut may move
only if the post-mutation layout independently passes both verifiers.
"""
from __future__ import annotations

import copy
import random
import unittest

from hellmode.cut_moves import propose_cut_change, remove_redundant_cuts
from hellmode.demo import optimize, _electrically_valid
from hellmode.verify_layout import verify_layout


def project(*, different_nets: bool = False):
    return {
        "board": {
            "rows": 5, "cols": 7,
            "cuts": [{"kind": "between", "row": 0, "col": 1}],
            "wires": [
                {"id": "W", "from": {"row": 0, "col": 0},
                 "to": {"row": 2, "col": 0}},
            ],
        },
        "componentDefs": [{"id": "pad", "pins": [
            {"id": "1", "offsetRow": 0, "offsetCol": 0},
        ], "bodyCells": []}],
        "components": [
            {"id": "A", "defId": "pad", "boardPos": {"row": 0, "col": 0}},
            {"id": "B", "defId": "pad", "boardPos": {"row": 2, "col": 0}},
            {"id": "C", "defId": "pad", "boardPos": {"row": 0, "col": 3}},
        ],
        "netAssignments": [
            {"componentId": "A", "pinId": "1", "netId": "N"},
            {"componentId": "B", "pinId": "1", "netId": "N"},
            *([{"componentId": "C", "pinId": "1", "netId": "M"}]
              if different_nets else []),
        ],
    }


class CutMutationTests(unittest.TestCase):
    def test_cut_candidates_are_reproducible_and_pure(self):
        source = project()
        original = copy.deepcopy(source)
        first = propose_cut_change(source, random.Random(17))
        second = propose_cut_change(source, random.Random(17))
        self.assertEqual(first, second)
        self.assertIsNotNone(first)
        proposed, kind = first
        self.assertIn(kind, {"cut_remove", "cut_shift", "cut_row_change"})
        self.assertNotEqual(proposed["board"]["cuts"], source["board"]["cuts"])
        self.assertEqual(source, original)

    def test_all_single_cut_change_candidates_preserve_fixed_board(self):
        source = project()
        for seed in range(100):
            with self.subTest(seed=seed):
                result = propose_cut_change(source, random.Random(seed))
                self.assertIsNotNone(result)
                trial, _ = result
                self.assertEqual((trial["board"]["rows"], trial["board"]["cols"]),
                                 (5, 7))
                self.assertEqual(trial["components"], source["components"])
                self.assertEqual(trial["board"]["wires"], source["board"]["wires"])
                self.assertLessEqual(len(trial["board"]["cuts"]), 1)
                if trial["board"]["cuts"]:
                    cut = trial["board"]["cuts"][0]
                    self.assertTrue(0 <= cut["row"] < 5)
                    self.assertTrue(0 <= cut["col"] < 6)

    def test_redundant_cut_is_removed_only_after_dual_electrical_pass(self):
        source = project(different_nets=False)
        self.assertTrue(_electrically_valid(source))
        best, removed = remove_redundant_cuts(source, _electrically_valid)
        self.assertEqual(removed, [(0, 1)])
        self.assertEqual(best["board"]["cuts"], [])
        self.assertTrue(_electrically_valid(best))
        self.assertEqual(source["board"]["cuts"],
                         [{"kind": "between", "row": 0, "col": 1}])

    def test_essential_cut_between_nets_cannot_be_removed(self):
        source = project(different_nets=True)
        self.assertTrue(_electrically_valid(source))
        best, removed = remove_redundant_cuts(source, _electrically_valid)
        self.assertEqual(removed, [])
        self.assertEqual(best, source)
        without = copy.deepcopy(source)
        without["board"]["cuts"] = []
        self.assertFalse(_electrically_valid(without))

    def test_unknown_cut_type_is_not_silently_migrated(self):
        source = project()
        source["board"]["cuts"][0]["kind"] = "hole"
        with self.assertRaisesRegex(ValueError, "non-between"):
            propose_cut_change(source, random.Random(1))
        with self.assertRaisesRegex(ValueError, "non-between"):
            remove_redundant_cuts(source, _electrically_valid)

    def test_alpha_actually_attempts_cut_changes_without_claiming_record(self):
        source = project(different_nets=True)
        best, run = optimize(source, moves=50, seed=7)
        self.assertGreater(run["moves_cut_proposed"], 0)
        self.assertEqual(run["moves_proposed"],
                         run["moves_topology_proposed"]
                         + run["moves_cut_proposed"]
                         + run["moves_with_column_alternative"])
        self.assertTrue(_electrically_valid(best))
        self.assertFalse(run["record_eligible"])
        self.assertFalse(verify_layout(best)["physical_pass"])
        self.assertEqual(source["board"]["cuts"],
                         [{"kind": "between", "row": 0, "col": 1}])


if __name__ == "__main__":
    unittest.main()
