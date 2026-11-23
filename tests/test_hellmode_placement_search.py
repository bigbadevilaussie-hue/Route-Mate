"""Hell Mode component relocation with real net rebuilding and hard locks.

The move is exploratory/electrical-only. No footprint measured clearance or
cut accessibility can be awarded by these tests.
"""
from __future__ import annotations

import ast
import copy
import json
import unittest
from pathlib import Path

from hellmode.placement_search import (
    _eligible, move_and_rebuild, search_component_moves,
)
from hellmode.pad_geometry import collect_pad_holes
from hellmode.copper_model import reconstruct_electrical
from hellmode.strict_occupancy import audit_strict_occupancy
from hellmode.demo import (
    _electrically_valid, _priority, report_metrics, optimize,
)

ROOT = Path(__file__).resolve().parents[1]


def small(*, has_wire=True):
    return {
        "board": {
            "rows": 5, "cols": 8, "cuts": [], "wires": (
                [{"id": "J", "from": {"row": 0, "col": 1},
                  "to": {"row": 2, "col": 1}}] if has_wire else []
            ),
        },
        "componentDefs": [{
            "id": "single",
            "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
            "bodyCells": [],
        }],
        "components": [
            {"id": "A", "defId": "single", "locked": True,
             "boardPos": {"row": 0, "col": 0}},
            {"id": "B", "defId": "single",
             "boardPos": {"row": 2 if has_wire else 0, "col": 0 if has_wire else 2}},
        ],
        "netAssignments": [
            {"componentId": "A", "pinId": "1", "netId": "N"},
            {"componentId": "B", "pinId": "1", "netId": "N"},
        ],
    }


def multinet():
    return {
        "board": {
            "rows": 4, "cols": 8, "cuts": [
                {"row": 0, "col": 1, "kind": "between"},
                {"row": 2, "col": 2, "kind": "between"},
            ], "wires": [],
        },
        "componentDefs": [{
            "id": "single",
            "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
        }, {
            "id": "dual",
            "pins": [
                {"id": "1", "offsetRow": 0, "offsetCol": 0},
                {"id": "2", "offsetRow": 0, "offsetCol": 2},
            ],
        }],
        "components": [
            {"id": "AN", "defId": "single",
             "boardPos": {"row": 0, "col": 0}, "locked": True},
            {"id": "BM", "defId": "single",
             "boardPos": {"row": 0, "col": 4}, "locked": True},
            {"id": "U", "defId": "dual",
             "boardPos": {"row": 0, "col": 1}},
        ],
        "netAssignments": [
            {"componentId": "AN", "pinId": "1", "netId": "N"},
            {"componentId": "BM", "pinId": "1", "netId": "M"},
            {"componentId": "U", "pinId": "1", "netId": "N"},
            {"componentId": "U", "pinId": "2", "netId": "M"},
        ],
    }


def move(project, cid, row, col, *, seed=1):
    baseline = reconstruct_electrical(project)
    return move_and_rebuild(
        project, cid, row, col,
        wire_nets=baseline["wire_nets"],
        pad_reader=collect_pad_holes,
        electrical_check=_electrically_valid,
        seed=seed,
    )


class ComponentPlacementM1Tests(unittest.TestCase):
    def test_move_to_same_copper_row_removes_now_redundant_jumper(self):
        source = small()
        original = copy.deepcopy(source)
        self.assertTrue(_electrically_valid(source))
        result = move(source, "B", 0, 5)
        self.assertIsNotNone(result)
        self.assertEqual(result["board"]["wires"], [])
        self.assertEqual(result["components"][0], source["components"][0])
        self.assertEqual(result["board"]["cuts"], source["board"]["cuts"])
        self.assertEqual(source, original)
        self.assertEqual(reconstruct_electrical(result)["status"], "PASS")
        self.assertEqual(audit_strict_occupancy(result["board"])["counts"][
            "excess_gap_occupancy"], 0)

    def test_move_from_same_row_to_new_row_creates_real_jumper(self):
        source = small(has_wire=False)
        self.assertTrue(_electrically_valid(source))
        result = move(source, "B", 2, 3)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["board"]["wires"]), 1)
        self.assertTrue(result["board"]["wires"][0]["id"].startswith("HM-NET-"))
        self.assertTrue(_electrically_valid(result))
        self.assertEqual(len(source["board"]["wires"]), 0)

    def test_multi_pin_component_move_rebuilds_both_affected_nets(self):
        source = multinet()
        self.assertTrue(_electrically_valid(source))
        original = copy.deepcopy(source)
        result = move(source, "U", 2, 1)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["board"]["wires"]), 2)
        self.assertEqual(set(reconstruct_electrical(result)["wire_nets"].values()),
                         {"N", "M"})
        self.assertTrue(_electrically_valid(result))
        self.assertEqual(original, source)

    def test_movement_rejected_when_two_nets_share_new_copper_strip(self):
        source = multinet()
        trial = move(source, "U", 1, 1)
        # Row 1 has no isolating cut for U's N/M pins.
        self.assertIsNone(trial)
        self.assertTrue(_electrically_valid(source))

    def test_locked_edge_offboard_and_slide_component_are_immutable(self):
        source = small()
        for flags in ({"locked": True}, {"edge": True},
                      {"edgeLocked": True}, {"slide": {"axis": "row"}},
                      {"offBoard": True}):
            with self.subTest(flags=flags):
                trial = copy.deepcopy(source)
                trial["components"][1].update(flags)
                self.assertFalse(_eligible(trial["components"][1]))
                unchanged = copy.deepcopy(trial)
                self.assertIsNone(move(trial, "B", 0, 5))
                self.assertEqual(trial, unchanged)

    def test_colliding_pad_or_out_of_bounds_move_does_not_corrupt_source(self):
        source = small()
        pristine = copy.deepcopy(source)
        self.assertIsNone(move(source, "B", 0, 0))
        self.assertIsNone(move(source, "B", 5, 0))
        self.assertEqual(source, pristine)

    def test_search_finds_real_electrical_improvement_and_is_deterministic(self):
        source = small()
        baseline = reconstruct_electrical(source)
        kwargs = dict(
            wire_nets=baseline["wire_nets"],
            pad_reader=collect_pad_holes,
            electrical_check=_electrically_valid,
            metric_reader=report_metrics,
            quality_key=_priority,
            attempts=60,
            seed=7,
        )
        one, stats_one = search_component_moves(source, **kwargs)
        two, stats_two = search_component_moves(source, **kwargs)
        self.assertEqual(one, two)
        self.assertEqual(stats_one, stats_two)
        self.assertGreater(stats_one["accepted_component_moves"], 0)
        self.assertLess(one["board"]["wires"].__len__(),
                        source["board"]["wires"].__len__())
        self.assertTrue(_electrically_valid(one))
        self.assertFalse(stats_one["record_eligible"])
        self.assertEqual(one["components"][0], source["components"][0])

    def test_motomix_search_preserves_locked_positions_cut_count_and_dimensions(self):
        source = json.loads(
            (ROOT / "benchmarks/moto/motomix-autorouted.json").read_text()
        )
        original = copy.deepcopy(source)
        result, manifest = optimize(source, moves=3, seed=2)
        self.assertEqual(source, original)
        self.assertEqual((result["board"]["rows"], result["board"]["cols"]), (24, 56))
        self.assertIn("component_search", manifest)
        self.assertTrue(_electrically_valid(result))
        original_by_id = {c["id"]: c for c in source["components"]}
        for component in result["components"]:
            old = original_by_id[component["id"]]
            if old.get("locked") or old.get("edge") or old.get("offBoard"):
                self.assertEqual(component, old)
        self.assertFalse(manifest["record_eligible"])

    def test_search_has_no_dependency_on_independent_verifier_internals(self):
        source = (ROOT / "hellmode/placement_search.py").read_text()
        imports = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        for dependency in (
            "copper_model", "pad_geometry", "strict_occupancy",
            "verify_layout", "solve", "route",
        ):
            self.assertNotIn(dependency, imports)


if __name__ == "__main__":
    unittest.main()
