"""Quick Fit placement acceptance tests using real benchmark projects."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from placement_policy import is_off_board_component
from render._geometry import BUILTIN_DEFS, component_geometry, resolve_definition
from solve.quick_fit import quick_fit

ROOT = Path(__file__).resolve().parents[1]


def load_project(name: str) -> dict:
    return json.loads((ROOT / "benchmarks" / name / f"{name}.json").read_text(encoding="utf-8"))


def definitions_for_test(project):
    definitions = dict(BUILTIN_DEFS)
    definitions.update({str(d["id"]): d for d in project.get("componentDefs", [])
                        if isinstance(d, dict) and d.get("id")})
    return definitions


class QuickFitPlacementTests(unittest.TestCase):
    PROJECTS = {"moto": {"placed": 32, "excluded": 12},
                "audio": {"placed": 14, "excluded": 5}}

    def _signature(self, project):
        return [(c.get("id"), c.get("boardPos"), c.get("rotation")) for c in project["components"]]

    def _assert_physical_layout(self, project):
        definitions = dict(BUILTIN_DEFS)
        definitions.update({str(d["id"]): d for d in project.get("componentDefs", [])
                            if isinstance(d, dict) and d.get("id")})
        occupied = {}
        rows, cols = project["board"]["rows"], project["board"]["cols"]
        for component in project["components"]:
            if is_off_board_component(component):
                self.assertIsNone(component.get("boardPos"), component.get("label"))
                continue
            self.assertIsInstance(component.get("boardPos"), dict, component.get("label"))
            pins, body = component_geometry(component, resolve_definition(component, definitions))
            cells = {(p["row"], p["col"]) for p in pins} | set(body)
            for row, col in cells:
                self.assertTrue(0 <= row < rows and 0 <= col < cols,
                                f"{component.get('label')} outside board at {(row, col)}")
                self.assertNotIn((row, col), occupied,
                                 f"{component.get('label')} overlaps {occupied.get((row, col))} at {(row, col)}")
                occupied[(row, col)] = component.get("label")

    def test_real_benchmarks_place_completely_and_deterministically(self):
        for name, expected in self.PROJECTS.items():
            with self.subTest(project=name):
                source = load_project(name)
                original = copy.deepcopy(source)
                first, second = quick_fit(source), quick_fit(source)
                self.assertEqual(first["status"], "PLACED", first["errors"])
                self.assertEqual(first["placed"], expected["placed"])
                self.assertEqual(first["excluded"], expected["excluded"])
                self.assertEqual(self._signature(first["project"]), self._signature(second["project"]))
                self.assertEqual(source, original, "Quick Fit must not mutate source JSON")
                self._assert_physical_layout(first["project"])
                self.assertGreater(first["report"]["net_links_scored"], 0)

    def test_q1_cannot_be_placed_through_resistor_body(self):
        project = {
            "board": {"rows": 5, "cols": 3},
            "components": [
                {"id": "R1", "label": "R1", "defId": "def-resistor", "rotation": 0},
                {"id": "Q1", "label": "Q1", "defId": "def-npn", "rotation": 0,
                 "footprintOverride": {
                     "width": 1, "height": 3,
                     "pins": [
                         {"id": "1", "name": "B", "offsetRow": 0, "offsetCol": 0},
                         {"id": "2", "name": "C", "offsetRow": 1, "offsetCol": 0},
                         {"id": "3", "name": "E", "offsetRow": 2, "offsetCol": 0},
                     ],
                     "bodyCells": [],
                 }},
            ],
            "netAssignments": [],
        }
        result = quick_fit(project, clearance=0)
        self.assertEqual(result["status"], "PLACED", result["errors"])
        resistor = next(c for c in result["project"]["components"] if c["id"] == "R1")
        transistor = next(c for c in result["project"]["components"] if c["id"] == "Q1")

        # Independent physical oracle: this resistor's four-hole lead span
        # occupies the three intermediate stripboard cells, not just pads.
        resistor_body = {
            (resistor["boardPos"]["row"] + offset, resistor["boardPos"]["col"])
            for offset in (1, 2, 3)
        }
        q_pins, q_body = component_geometry(
            transistor, resolve_definition(transistor, definitions_for_test(result["project"]))
        )
        q_cells = {(p["row"], p["col"]) for p in q_pins} | set(q_body)
        self.assertTrue(resistor_body.isdisjoint(q_cells),
                        f"Q1 overlaps R1's physical body at {resistor_body & q_cells}")

    def test_clearance_fallback_is_reported(self):
        project = {
            "board": {"rows": 1, "cols": 2},
            "componentDefs": [{"id": "pin", "width": 1, "height": 1,
                               "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
                               "bodyCells": []}],
            "components": [{"id": "A", "label": "A", "defId": "pin"},
                           {"id": "B", "label": "B", "defId": "pin"}],
            "netAssignments": [],
        }
        result = quick_fit(project, clearance=1)
        self.assertEqual(result["status"], "PLACED", result["errors"])
        self.assertEqual(result["report"]["clearance_requested"], 1)
        self.assertEqual(result["report"]["clearance_used"], 0)
        self.assertTrue(result["warnings"])

    def test_impossible_layout_has_distinct_no_fit_status(self):
        project = {
            "board": {"rows": 1, "cols": 1},
            "componentDefs": [{"id": "pin", "width": 1, "height": 1,
                               "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
                               "bodyCells": []}],
            "components": [{"id": "A", "defId": "pin"}, {"id": "B", "defId": "pin"}],
            "netAssignments": [],
        }
        self.assertEqual(quick_fit(project, clearance=0)["status"], "NO_FIT_FOUND")

    def test_locked_component_is_preserved_and_not_replaced(self):
        project = {
            "board": {"rows": 4, "cols": 6},
            "componentDefs": [{"id": "two", "width": 2, "height": 1,
                               "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0},
                                        {"id": "2", "offsetRow": 0, "offsetCol": 1}],
                               "bodyCells": []}],
            "components": [
                {"id": "fixed", "label": "Fixed", "defId": "two", "locked": True,
                 "boardPos": {"row": 2, "col": 3}},
                {"id": "free", "label": "Free", "defId": "two"},
            ],
            "netAssignments": [],
        }
        result = quick_fit(project, clearance=0)
        self.assertEqual(result["status"], "PLACED", result["errors"])
        fixed = next(c for c in result["project"]["components"] if c["id"] == "fixed")
        self.assertEqual(fixed["boardPos"], {"row": 2, "col": 3})
        free = next(c for c in result["project"]["components"] if c["id"] == "free")
        self.assertNotEqual(free["boardPos"], fixed["boardPos"])

    def test_edge_and_slide_constraints_are_not_silently_ignored(self):
        project = {
            "board": {"rows": 4, "cols": 4},
            "componentDefs": [{"id": "pin", "width": 1, "height": 1,
                               "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
                               "bodyCells": []}],
            "components": [{"id": "A", "defId": "pin", "edge": True}],
            "netAssignments": [],
        }
        self.assertEqual(quick_fit(project)["status"], "CONSTRAINT_CONFLICT")

    def test_missing_footprint_is_incomplete_geometry(self):
        project = {"board": {"rows": 4, "cols": 4},
                   "components": [{"id": "A", "label": "A", "defId": "missing"}],
                   "netAssignments": []}
        self.assertEqual(quick_fit(project)["status"], "INCOMPLETE_GEOMETRY")


    def test_horizontal_three_net_transistor_is_rejected(self):
        project = {
            "board": {"rows": 1, "cols": 3},
            "componentDefs": [{"id": "npn-horizontal", "width": 3, "height": 1,
                "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0},
                         {"id": "2", "offsetRow": 0, "offsetCol": 1},
                         {"id": "3", "offsetRow": 0, "offsetCol": 2}],
                "bodyCells": []}],
            "components": [{"id": "Q1", "label": "Q1", "defId": "npn-horizontal"}],
            "netAssignments": [{"componentId": "Q1", "pinId": "1", "netId": "B"},
                               {"componentId": "Q1", "pinId": "2", "netId": "C"},
                               {"componentId": "Q1", "pinId": "3", "netId": "E"}],
        }
        result = quick_fit(project, clearance=0)
        self.assertEqual(result["status"], "NO_FIT_FOUND", result["errors"])

    def test_vertical_three_net_transistor_can_be_placed(self):
        project = {
            "board": {"rows": 3, "cols": 1},
            "componentDefs": [{"id": "npn-vertical", "width": 1, "height": 3,
                "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0},
                         {"id": "2", "offsetRow": 1, "offsetCol": 0},
                         {"id": "3", "offsetRow": 2, "offsetCol": 0}],
                "bodyCells": []}],
            "components": [{"id": "Q1", "label": "Q1", "defId": "npn-vertical"}],
            "netAssignments": [{"componentId": "Q1", "pinId": "1", "netId": "B"},
                               {"componentId": "Q1", "pinId": "2", "netId": "C"},
                               {"componentId": "Q1", "pinId": "3", "netId": "E"}],
        }
        result = quick_fit(project, clearance=0)
        self.assertEqual(result["status"], "PLACED", result["errors"])

    def test_unlocked_offboard_saved_leads_are_reallocated(self):
        project = {
            "board": {"rows": 1, "cols": 2},
            "componentDefs": [{"id": "pin", "width": 1, "height": 1,
                "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}], "bodyCells": []}],
            "components": [
                {"id": "EXT", "label": "EXT", "defId": "pin", "offBoard": True,
                 "boardPos": None, "leads": {"1": {"row": 0, "col": 0}}},
                {"id": "A", "label": "A", "defId": "pin"},
            ],
            "netAssignments": [{"componentId": "EXT", "pinId": "1", "netId": "GND"},
                               {"componentId": "A", "pinId": "1", "netId": "VCC"}],
        }
        result = quick_fit(project, clearance=0)
        self.assertEqual(result["status"], "PLACED", result["errors"])
        external = next(c for c in result["project"]["components"] if c["id"] == "EXT")
        onboard = next(c for c in result["project"]["components"] if c["id"] == "A")
        self.assertNotEqual(external["leads"]["1"], onboard["boardPos"])

    def test_locked_offboard_saved_leads_remain_fixed(self):
        project = {
            "board": {"rows": 1, "cols": 2},
            "componentDefs": [{"id": "pin", "width": 1, "height": 1,
                "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}], "bodyCells": []}],
            "components": [
                {"id": "EXT", "label": "EXT", "defId": "pin", "offBoard": True,
                 "locked": True, "leads": {"1": {"row": 0, "col": 0}}},
                {"id": "A", "label": "A", "defId": "pin"},
            ],
            "netAssignments": [{"componentId": "EXT", "pinId": "1", "netId": "GND"},
                               {"componentId": "A", "pinId": "1", "netId": "VCC"}],
        }
        result = quick_fit(project, clearance=0)
        self.assertEqual(result["status"], "NO_FIT_FOUND", result["errors"])

if __name__ == "__main__":
    unittest.main()
