"""Regression tests for Karl solved-export footprint import."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from collect import normalise_like_gui, validate_project
from prepare.sanity.electrical import run_electrical_sanity


ROOT = Path(__file__).resolve().parents[1]


def load_solved_moto() -> dict:
    path = ROOT / "benchmarks" / "moto" / "moto14wires30cuts.json"
    return json.loads(path.read_text(encoding="utf-8"))


class SolvedExportImportTests(unittest.TestCase):
    def test_karl_symbolic_pin_export_passes_after_validation(self):
        project = load_solved_moto()
        aliases = {
            "def-diode": ("a", "k"),
            "def-zener": ("a", "k"),
            "def-led": ("a", "k"),
            "def-cap-polarized": ("+", "-"),
            "def-npn": ("b", "c", "e"),
            "def-pnp": ("b", "c", "e"),
            "def-pmos": ("g", "d", "s"),
            "def-nmos": ("g", "d", "s"),
        }
        for definition in project.get("componentDefs", []):
            sequence = aliases.get(str(definition.get("id")))
            if sequence:
                for pin, pin_id in zip(definition.get("pins", []), sequence):
                    pin["id"] = pin_id

        before = run_electrical_sanity(project)
        self.assertEqual(before["status"], "FAIL")
        self.assertTrue(any("unknown footprint pin" in error
                            for error in before["errors"]))

        validate_project(project)
        after = run_electrical_sanity(project)
        self.assertEqual(after["status"], "PASS", after["errors"])

    def test_alias_normalisation_preserves_saved_geometry_and_pin_names(self):
        project = {
            "components": [], "nets": [], "netAssignments": [],
            "board": {},
            "componentDefs": [
                {
                    "id": "def-diode", "width": 2, "height": 1,
                    "pins": [
                        {"id": "a", "name": "A", "offsetRow": 0, "offsetCol": 0},
                        {"id": "k", "name": "K", "offsetRow": 0, "offsetCol": 1},
                    ],
                    "bodyCells": [{"row": 0, "col": 2}],
                },
                {
                    "id": "def-npn", "width": 2, "height": 2,
                    "pins": [
                        {"id": "b", "name": "B", "offsetRow": 0, "offsetCol": 0},
                        {"id": "c", "name": "C", "offsetRow": 1, "offsetCol": 0},
                        {"id": "e", "name": "E", "offsetRow": 1, "offsetCol": 1},
                    ],
                    "bodyCells": [],
                },
            ],
        }
        before_geometry = copy.deepcopy([
            (d["width"], d["height"], d["bodyCells"],
             [(p["name"], p["offsetRow"], p["offsetCol"]) for p in d["pins"]])
            for d in project["componentDefs"]
        ])
        validate_project(project)
        self.assertEqual(
            [[p["id"] for p in d["pins"]] for d in project["componentDefs"]],
            [["1", "2"], ["1", "2", "3"]],
        )
        after_geometry = [
            (d["width"], d["height"], d["bodyCells"],
             [(p["name"], p["offsetRow"], p["offsetCol"]) for p in d["pins"]])
            for d in project["componentDefs"]
        ]
        self.assertEqual(after_geometry, before_geometry)

    def test_pushbutton_four_physical_pins_are_not_collapsed(self):
        project = {
            "components": [], "nets": [], "netAssignments": [],
            "board": {},
            "componentDefs": [{
                "id": "def-pushbutton",
                "pins": [{"id": str(i), "name": str(i),
                          "offsetRow": (i - 1) // 2, "offsetCol": (i - 1) % 2}
                         for i in range(1, 5)],
            }],
        }
        validate_project(project)
        self.assertEqual(
            [p["id"] for p in project["componentDefs"][0]["pins"]],
            ["1", "2", "3", "4"],
        )

    def test_unrecognised_builtin_alias_is_not_guessed(self):
        project = {
            "components": [], "nets": [], "netAssignments": [],
            "board": {},
            "componentDefs": [{
                "id": "def-diode",
                "pins": [{"id": "anode"}, {"id": "cathode"}],
            }],
        }
        validate_project(project)
        self.assertEqual(
            [p["id"] for p in project["componentDefs"][0]["pins"]],
            ["anode", "cathode"],
        )
        self.assertTrue(any("unrecognised saved pin IDs" in warning
                            for warning in project.get("_collectWarnings", [])))

    def test_normalisation_keeps_saved_builtin_geometry(self):
        project = {
            "components": [], "nets": [], "netAssignments": [],
            "board": {},
            "componentDefs": [
                {"id": "def-diode", "width": 2, "height": 1,
                 "pins": [{"id": "1"}, {"id": "2"}]},
                {"id": "custom-part", "width": 1, "height": 2,
                 "pins": [{"id": "A"}, {"id": "B"}]},
            ],
        }
        normalise_like_gui(project)
        self.assertEqual(
            [d["id"] for d in project["componentDefs"]],
            ["def-diode", "custom-part"],
        )


if __name__ == "__main__":
    unittest.main()
