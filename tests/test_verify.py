"""Tests for the independent stripboard connectivity verifier."""
from __future__ import annotations

import copy
import unittest

from solve.verify import verify_project
from collect import validate_project
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def project():
    return {
        "board": {"rows": 2, "cols": 5, "cuts": [], "wires": []},
        "components": [
            {"id": "A", "label": "A", "defId": "two", "boardPos": {"row": 0, "col": 0}},
            {"id": "B", "label": "B", "defId": "two", "boardPos": {"row": 1, "col": 0}},
        ],
        "componentDefs": [{
            "id": "two", "pins": [
                {"id": "1", "offsetRow": 0, "offsetCol": 0},
                {"id": "2", "offsetRow": 0, "offsetCol": 2},
            ], "bodyCells": [],
        }],
        "nets": [{"id": "N"}, {"id": "M"}],
        "netAssignments": [
            {"componentId": "A", "pinId": "1", "netId": "N"},
            {"componentId": "A", "pinId": "2", "netId": "N"},
            {"componentId": "B", "pinId": "1", "netId": "M"},
        ],
    }


class VerifyTests(unittest.TestCase):
    def test_legacy_moto_layout_rejects_agm_terminal_outside_board(self):
        path = ROOT / "benchmarks" / "moto" / "moto14wires30cuts.json"
        data = validate_project(json.loads(path.read_text(encoding="utf-8")))
        report = verify_project(data)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(
            any("AGM -in pin 2" in error and "outside board" in error
                for error in report["errors"]),
            report["errors"],
        )

    def test_continuous_strip_connects_same_net(self):
        report = verify_project(project())
        self.assertEqual(report["status"], "PASS", report["errors"])

    def test_component_does_not_join_its_own_pins(self):
        data = project()
        data["netAssignments"][1]["netId"] = "M"
        report = verify_project(data)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("open net M" in error for error in report["errors"]))

    def test_editor_v4_between_cut_interrupts_only_the_link(self):
        data = project()
        data["board"]["cuts"] = [{"row": 0, "col": 1, "kind": "between"}]
        report = verify_project(data)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("open net N" in error for error in report["errors"]))
        self.assertEqual(report["counts"]["cuts"], 1)

    def test_cut_without_kind_defaults_to_between(self):
        data = project()
        data["board"]["cuts"] = [{"row": 0, "col": 1}]
        report = verify_project(data)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("open net N" in error for error in report["errors"]))

    def test_below_cut_is_explicitly_unsupported_without_pattern_model(self):
        data = project()
        data["board"]["cuts"] = [{"row": 0, "col": 1, "kind": "below"}]
        report = verify_project(data)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("requires patterned-board" in error for error in report["errors"]))

    def test_real_editor_cut_export_is_accepted_as_a_between_cut(self):
        path = ROOT / "test-fixtures" / "editor-exports" / "cut.json"
        data = validate_project(json.loads(path.read_text(encoding="utf-8")))
        report = verify_project(data)
        self.assertEqual(report["counts"]["cuts"], 1)
        self.assertEqual(report["status"], "PASS", report["errors"])
        self.assertTrue(report["warnings"])

    def test_cut_hole_interrupts_strip(self):
        data = project()
        data["board"]["cuts"] = [{"row": 0, "col": 1, "kind": "hole"}]
        report = verify_project(data)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("open net N" in error for error in report["errors"]))

    def test_jumper_restores_connection_across_cut(self):
        data = project()
        data["board"]["cuts"] = [{"row": 0, "col": 1, "kind": "hole"}]
        data["board"]["wires"] = [{
            "id": "W1", "from": {"row": 0, "col": 0},
            "to": {"row": 0, "col": 2},
        }]
        report = verify_project(data)
        self.assertEqual(report["status"], "PASS", report["errors"])

    def test_different_nets_on_same_copper_are_short(self):
        data = project()
        data["netAssignments"][1]["netId"] = "M"
        data["components"][1]["boardPos"] = {"row": 0, "col": 2}
        data["netAssignments"][2]["netId"] = "M"
        report = verify_project(data)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("short at copper group" in error for error in report["errors"]))

    def test_offboard_assignments_are_not_physical_terminals(self):
        data = project()
        data["components"][1]["offBoard"] = True
        data["components"][1]["boardPos"] = None
        report = verify_project(data)
        self.assertEqual(report["status"], "PASS", report["errors"])
        self.assertEqual(report["counts"]["on_board_terminals"], 2)

    def test_wire_outside_board_is_rejected(self):
        data = project()
        data["board"]["wires"] = [{
            "from": {"row": 0, "col": 0}, "to": {"row": 9, "col": 0},
        }]
        report = verify_project(data)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("outside board" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
