"""Tests for deterministic first-pass stripboard copper routing."""
from __future__ import annotations

import copy
import unittest

from solve.route import route_copper
from solve.verify import verify_project


def make_project(terminals, rows=3, cols=8, cuts=None, wires=None):
    components = []
    assignments = []
    for index, (row, col, net) in enumerate(terminals):
        cid = f"C{index}"
        components.append({
            "id": cid, "label": cid, "defId": "single",
            "boardPos": {"row": row, "col": col},
        })
        assignments.append({"componentId": cid, "pinId": "1", "netId": net})
    return {
        "board": {
            "rows": rows, "cols": cols,
            "cuts": copy.deepcopy(cuts or []),
            "wires": copy.deepcopy(wires or []),
        },
        "components": components,
        "componentDefs": [{
            "id": "single",
            "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
            "bodyCells": [],
        }],
        "nets": [{"id": net} for net in sorted({item[2] for item in terminals})],
        "netAssignments": assignments,
    }


class RouteCopperTests(unittest.TestCase):
    def test_different_nets_on_one_strip_get_a_between_cut(self):
        data = make_project([(0, 1, "A"), (0, 5, "B")])
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["cuts_added"], 1)
        self.assertEqual(result["wires_added"], 0)
        self.assertEqual(result["project"]["board"]["cuts"],
                         [{"row": 0, "col": 1, "kind": "between"}])
        self.assertEqual(verify_project(result["project"])["status"], "PASS")

    def test_same_net_across_rows_gets_a_jumper(self):
        data = make_project([(0, 1, "A"), (2, 6, "A")])
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["cuts_added"], 0)
        self.assertEqual(result["wires_added"], 1)
        self.assertEqual(verify_project(result["project"])["status"], "PASS")

    def test_interleaved_nets_are_cut_and_rejoined(self):
        data = make_project([(0, 0, "A"), (0, 2, "B"), (0, 4, "A")])
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["cuts_added"], 2)
        self.assertEqual(result["wires_added"], 1)
        self.assertEqual(verify_project(result["project"])["status"], "PASS")

    def test_adjacent_different_net_pins_are_separated(self):
        data = make_project([(1, 3, "A"), (1, 4, "B")])
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["project"]["board"]["cuts"],
                         [{"row": 1, "col": 3, "kind": "between"}])
        self.assertEqual(result["verification"]["counts"]["adjacency_conflicts"], 0)

    def test_different_nets_in_same_hole_are_unroutable(self):
        data = make_project([(0, 2, "A"), (0, 2, "B")])
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTING_FAILED")
        self.assertTrue(any("share hole" in error for error in result["errors"]))
        self.assertEqual(data["board"]["cuts"], [])

    def test_existing_manual_cuts_and_wires_are_preserved(self):
        cuts = [{"row": 0, "col": 2, "kind": "hole"}]
        wires = [{
            "id": "manual-1",
            "from": {"row": 0, "col": 2},
            "to": {"row": 2, "col": 2},
        }]
        data = make_project([(0, 2, "A"), (2, 2, "A")], cuts=cuts, wires=wires)
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["project"]["board"]["cuts"], cuts)
        self.assertEqual(result["project"]["board"]["wires"][0], wires[0])
        self.assertEqual(result["wires_added"], 0)

    def test_existing_jumper_short_is_not_hidden_by_more_cuts(self):
        data = make_project(
            [(0, 1, "A"), (0, 5, "B")],
            wires=[{
                "id": "manual-short",
                "from": {"row": 0, "col": 1},
                "to": {"row": 0, "col": 5},
            }],
        )
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTING_FAILED")
        self.assertTrue(any("shorts different nets" in error for error in result["errors"]))
        self.assertEqual(data["board"]["wires"][0]["id"], "manual-short")

    def test_reuses_copper_holes_for_short_vertical_jumper(self):
        data = make_project([(0, 0, "A"), (2, 7, "A")], rows=3, cols=8)
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["wires_added"], 1)
        wire = result["project"]["board"]["wires"][0]
        self.assertEqual(wire["from"]["col"], wire["to"]["col"])
        self.assertEqual(abs(wire["from"]["row"] - wire["to"]["row"]), 2)
        self.assertEqual(verify_project(result["project"])["status"], "PASS")

    def test_existing_cut_limits_reusable_copper(self):
        data = make_project(
            [(0, 0, "A"), (2, 7, "A"), (0, 7, "B")],
            rows=3, cols=8,
        )
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(verify_project(result["project"])["status"], "PASS")
        wire = result["project"]["board"]["wires"][0]
        self.assertNotEqual(wire["from"], {"row": 0, "col": 7})

    def test_three_separate_copper_islands_reuse_merged_endpoints(self):
        data = make_project(
            [(0, 0, "A"), (2, 7, "A"), (4, 3, "A")],
            rows=5, cols=8,
        )
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["wires_added"], 2)
        self.assertEqual(verify_project(result["project"])["status"], "PASS")
        self.assertEqual(
            result["project"]["board"],
            route_copper(data)["project"]["board"],
        )

    def test_nearest_island_search_preserves_vertical_tie_break(self):
        # Two full strips: all same-column jumpers have equal minimum
        # Manhattan length, so the deterministic lowest column wins.
        data = make_project([(0, 7, "A"), (3, 0, "A")], rows=4, cols=8)
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        wire = result["project"]["board"]["wires"][0]
        self.assertEqual(wire["from"], {"row": 0, "col": 0})
        self.assertEqual(wire["to"], {"row": 3, "col": 0})
        self.assertEqual(verify_project(result["project"])["status"], "PASS")

    def test_vertical_only_routes_full_strips_without_diagonals(self):
        data = make_project([(0, 1, "A"), (2, 6, "A")])
        result = route_copper(data, vertical_only=True)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["wires_added"], 1)
        wire = result["project"]["board"]["wires"][0]
        self.assertEqual(wire["from"]["col"], wire["to"]["col"])
        self.assertEqual(verify_project(result["project"])["status"], "PASS")

    def test_vertical_only_fails_cleanly_when_copper_columns_do_not_overlap(self):
        data = make_project(
            [(0, 0, "A"), (0, 1, "B"), (1, 6, "C"), (1, 7, "A")],
            rows=2, cols=8,
        )
        original = copy.deepcopy(data)
        result = route_copper(data, vertical_only=True)
        self.assertEqual(result["status"], "ROUTING_FAILED")
        self.assertIn("same-column", result["errors"][0])
        self.assertEqual(result["project"], original)
        self.assertEqual(data, original)

    def test_constrained_route_order_prioritizes_more_islands(self):
        data = make_project(
            [(0, 0, "A"), (1, 0, "A"),
             (2, 0, "B"), (3, 0, "B"), (4, 0, "B")],
            rows=5, cols=5,
        )
        result = route_copper(data, route_order="constrained")
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["wires_added"], 3)
        first = result["project"]["board"]["wires"][0]
        self.assertEqual({first["from"]["row"], first["to"]["row"]},
                         {2, 3})
        self.assertEqual(verify_project(result["project"])["status"], "PASS")
        self.assertEqual(data["board"]["wires"], [])

    def test_vertical_router_avoids_body_blocked_column(self):
        data = make_project([(0, 0, "A"), (4, 7, "A")], rows=5, cols=8)
        data["componentDefs"].append({
            "id": "blocker", "pins": [],
            "bodyCells": [{"row": 0, "col": 0}],
        })
        data["components"].append({
            "id": "BLOCK", "label": "BLOCK", "defId": "blocker",
            "boardPos": {"row": 2, "col": 0},
        })
        result = route_copper(data, vertical_only=True)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        wire = result["project"]["board"]["wires"][0]
        self.assertNotEqual(wire["from"]["col"], 0)
        self.assertEqual(wire["from"]["col"], wire["to"]["col"])

    def test_vertical_router_rejects_all_blocked_columns_without_mutation(self):
        data = make_project([(0, 0, "A"), (2, 3, "A")], rows=3, cols=4)
        data["componentDefs"].append({
            "id": "wall", "pins": [],
            "bodyCells": [{"row": 0, "col": col} for col in range(4)],
        })
        data["components"].append({
            "id": "WALL", "label": "WALL", "defId": "wall",
            "boardPos": {"row": 1, "col": 0},
        })
        original = copy.deepcopy(data)
        result = route_copper(data, vertical_only=True)
        self.assertEqual(result["status"], "ROUTING_FAILED")
        self.assertEqual(result["project"], original)
        self.assertEqual(data, original)

    def test_vertical_router_rejects_manual_body_crossing(self):
        data = make_project([(0, 1, "A"), (2, 1, "A")], rows=3, cols=4,
                            wires=[{"id": "manual", "from": {"row": 0, "col": 1},
                                    "to": {"row": 2, "col": 1}}])
        data["componentDefs"].append({
            "id": "blocker", "pins": [],
            "bodyCells": [{"row": 0, "col": 0}],
        })
        data["components"].append({
            "id": "BLOCK", "defId": "blocker",
            "boardPos": {"row": 1, "col": 1},
        })
        result = route_copper(data, vertical_only=True)
        self.assertEqual(result["status"], "ROUTING_FAILED")
        self.assertIn("existing wire", result["errors"][0])

    def test_unknown_route_order_is_rejected(self):
        with self.assertRaises(ValueError):
            route_copper(make_project([(0, 0, "A")]), route_order="random")

    def test_router_does_not_mutate_source_project(self):
        data = make_project([(0, 0, "A"), (1, 3, "A")])
        before = copy.deepcopy(data)
        route_copper(data)
        self.assertEqual(data, before)

    def test_router_is_deterministic(self):
        data = make_project([(0, 0, "A"), (0, 2, "B"), (0, 4, "A"), (2, 7, "B")])
        first = route_copper(data)
        second = route_copper(data)
        self.assertEqual(first["status"], "ROUTED", first["errors"])
        self.assertEqual(first["project"]["board"], second["project"]["board"])

    def test_builtin_footprint_geometry_is_resolved(self):
        data = {
            "board": {"rows": 4, "cols": 8, "cuts": [], "wires": []},
            "components": [
                {"id": "A", "label": "A", "defId": "def-npn",
                 "boardPos": {"row": 0, "col": 0}},
                {"id": "B", "label": "B", "defId": "def-npn",
                 "boardPos": {"row": 2, "col": 4}},
            ],
            "nets": [{"id": "N"}],
            "netAssignments": [
                {"componentId": "A", "pinId": "1", "netId": "N"},
                {"componentId": "B", "pinId": "1", "netId": "N"},
            ],
        }
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["wires_added"], 1)
        self.assertEqual(verify_project(result["project"])["status"], "PASS")

    def test_multi_pad_logical_pins_expand_to_physical_holes(self):
        data = {
            "board": {"rows": 4, "cols": 8, "cuts": [], "wires": []},
            "components": [{
                "id": "SW1", "label": "Wake", "defId": "def-pushbutton",
                "boardPos": {"row": 0, "col": 0},
            }],
            "nets": [{"id": "A"}, {"id": "B"}],
            "netAssignments": [
                {"componentId": "SW1", "pinId": "1", "netId": "A"},
                {"componentId": "SW1", "pinId": "2", "netId": "B"},
            ],
        }
        result = route_copper(data)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["verification"]["counts"]["on_board_terminals"], 4)
        self.assertEqual(result["cuts_added"], 0)
        self.assertEqual(result["wires_added"], 0)

    def test_no_physical_terminals_is_not_reported_as_routed(self):
        data = make_project([])
        result = route_copper(data)
        self.assertEqual(result["status"], "INVALID_INPUT")
        self.assertTrue(any("no assigned physical terminals" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
