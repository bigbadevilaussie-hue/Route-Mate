"""Quick Fit source-geometry acceptance tests.

These tests deliberately stop before placement and routing: the repository has
no Quick Fit engine yet. They prove that the real Moto and Audio inputs have
complete, internally valid footprint geometry for a future placer to consume.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from render._geometry import BUILTIN_DEFS, component_geometry, resolve_definition, rotate_offset


ROOT = Path(__file__).resolve().parents[1]


def load_project(name: str) -> dict:
    path = ROOT / "benchmarks" / name / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def definitions_for(project: dict) -> dict:
    definitions = dict(BUILTIN_DEFS)
    for definition in project.get("componentDefs", []):
        if isinstance(definition, dict) and definition.get("id"):
            definitions[str(definition["id"])] = definition
    return definitions


def on_board(component: dict) -> bool:
    return not component.get("offBoard") and not component.get("boardExcluded")


class QuickFitSourceGeometryTests(unittest.TestCase):
    PROJECTS = {
        "moto": {"components": 44, "on_board": 33, "assignments": 123},
        "audio": {"components": 19, "on_board": 14, "assignments": 85},
    }

    def test_real_inputs_have_expected_scope_and_locked_board(self):
        for name, expected in self.PROJECTS.items():
            with self.subTest(project=name):
                project = load_project(name)
                board = project["board"]
                self.assertEqual((board["rows"], board["cols"]), (24, 56))
                self.assertTrue(board.get("lockedRows"))
                self.assertTrue(board.get("lockedCols"))
                self.assertEqual(len(project["components"]), expected["components"])
                self.assertEqual(sum(on_board(c) for c in project["components"]),
                                 expected["on_board"])
                self.assertEqual(len(project["netAssignments"]), expected["assignments"])
                self.assertTrue(all(c.get("boardPos") is None
                                    for c in project["components"]),
                                "source fixtures must remain unplaced inputs")

    def test_every_on_board_component_resolves_real_geometry(self):
        for name in self.PROJECTS:
            with self.subTest(project=name):
                project = load_project(name)
                definitions = definitions_for(project)
                missing = []
                for component in project["components"]:
                    if on_board(component) and not resolve_definition(component, definitions):
                        missing.append(component.get("label") or component.get("id"))
                self.assertEqual(missing, [], f"unresolved on-board footprints: {missing}")

    def test_every_definition_has_valid_dimensions_and_in_bounds_geometry(self):
        for name in self.PROJECTS:
            with self.subTest(project=name):
                project = load_project(name)
                definitions = definitions_for(project)
                for component in project["components"]:
                    if not on_board(component):
                        continue
                    label = component.get("label") or component.get("id")
                    definition = resolve_definition(component, definitions)
                    self.assertIsNotNone(definition, label)
                    width, height = definition.get("width"), definition.get("height")
                    self.assertIsInstance(width, int, label)
                    self.assertIsInstance(height, int, label)
                    self.assertGreater(width, 0, label)
                    self.assertGreater(height, 0, label)

                    pins = definition.get("pins")
                    body = definition.get("bodyCells", [])
                    self.assertIsInstance(pins, list, label)
                    self.assertGreaterEqual(len(pins), 2, label)
                    self.assertIsInstance(body, list, label)

                    occupied = set()
                    for pin in pins:
                        self.assertIsInstance(pin, dict, label)
                        point = (pin.get("offsetRow"), pin.get("offsetCol"))
                        self.assertTrue(all(isinstance(v, int) for v in point),
                                        f"{label}: invalid pin coordinate {point}")
                        row, col = point
                        self.assertTrue(0 <= row < height and 0 <= col < width,
                                        f"{label}: pin {pin.get('id')} outside {width}x{height}")
                        self.assertNotIn(point, occupied,
                                         f"{label}: two physical pads occupy {point}")
                        occupied.add(point)

                    for cell in body:
                        self.assertIsInstance(cell, dict, label)
                        point = (cell.get("row"), cell.get("col"))
                        self.assertTrue(all(isinstance(v, int) for v in point),
                                        f"{label}: invalid body coordinate {point}")
                        row, col = point
                        self.assertTrue(0 <= row < height and 0 <= col < width,
                                        f"{label}: body cell outside {width}x{height}")
                        self.assertNotIn(point, occupied,
                                         f"{label}: body cell overlaps a pad at {point}")
                        occupied.add(point)

    def test_every_net_assignment_references_a_real_footprint_pin(self):
        for name in self.PROJECTS:
            with self.subTest(project=name):
                project = load_project(name)
                definitions = definitions_for(project)
                components = {str(c.get("id")): c for c in project["components"]}
                errors = []
                for assignment in project["netAssignments"]:
                    component = components.get(str(assignment.get("componentId")))
                    if component is None:
                        errors.append(f"unknown component {assignment.get('componentId')}")
                        continue
                    definition = resolve_definition(component, definitions)
                    if definition is None:
                        errors.append(f"{component.get('label')}: missing definition")
                        continue
                    pin_ids = {str(pin.get("id")) for pin in definition.get("pins", [])
                               if isinstance(pin, dict)}
                    if str(assignment.get("pinId")) not in pin_ids:
                        errors.append(
                            f"{component.get('label')}: assignment to absent pin "
                            f"{assignment.get('pinId')!r}"
                        )
                self.assertEqual(errors, [], "\\n".join(errors))

    def test_saved_two_pin_geometry_honours_solver_flexible_end(self):
        component = {
            "id": "R1",
            "defId": "def-resistor",
            "boardPos": {"row": 4, "col": 7},
            "rotation": 0,
            "flexibleEndPos": {"row": 9, "col": 13},
        }
        # Deliberately omit the flexible flag, as Karl's saved definitions do.
        saved_definition = {
            "width": 2, "height": 1,
            "pins": [
                {"id": "1", "name": "1", "offsetRow": 0, "offsetCol": 0},
                {"id": "2", "name": "2", "offsetRow": 0, "offsetCol": 1},
            ],
            "bodyCells": [],
        }
        pins, body = component_geometry(component, saved_definition)
        self.assertEqual(
            [(pin["id"], pin["row"], pin["col"]) for pin in pins],
            [("1", 4, 7), ("2", 9, 13)],
        )
        self.assertEqual(body, [])

    def test_rotation_is_reversible_for_rectangular_footprints(self):
        # Coordinates use row/column extents: height-1 and width-1.
        for height in range(1, 10):
            for width in range(1, 10):
                for row in range(height):
                    for col in range(width):
                        r90, c90 = rotate_offset(row, col, 90, height - 1, width - 1)
                        restored = rotate_offset(r90, c90, 270, width - 1, height - 1)
                        self.assertEqual(restored, (row, col))
                        r180, c180 = rotate_offset(row, col, 180, height - 1, width - 1)
                        restored = rotate_offset(r180, c180, 180, height - 1, width - 1)
                        self.assertEqual(restored, (row, col))


if __name__ == "__main__":
    unittest.main()
