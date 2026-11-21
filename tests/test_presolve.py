"""PRE-SOLVE schema and board-sizing evidence regression tests."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prepare.presolve import analyse_project

ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / "benchmarks" / name / (name + ".json")).read_text())


class PresolveTests(unittest.TestCase):
    def test_moto_audio_uniform_schema_and_locked_board(self):
        for name, expected in (("moto", 44), ("audio", 19)):
            with self.subTest(name=name):
                source = fixture(name)
                before = copy.deepcopy(source)
                result = analyse_project(source)
                self.assertEqual(source, before)
                self.assertEqual(len(result["components"]), expected)
                self.assertEqual(len({r["component_id"] for r in result["components"]}), expected)
                self.assertTrue(result["board"]["locked_rows"])
                self.assertTrue(result["board"]["locked_cols"])
                self.assertEqual((result["board"]["source_rows"], result["board"]["source_cols"]), (24, 56))
                self.assertIsNone(result["board"]["recommended_rows"])
                self.assertIsNone(result["board"]["recommended_cols"])
                self.assertFalse(result["board"]["physical_fit_verified"])
                self.assertEqual(len({tuple(sorted(r.keys())) for r in result["components"]}), 1)

    def test_moto_esp32_dual_row_topology_and_rotation_hints(self):
        report = analyse_project(fixture("moto"))
        esp = next(c for c in report["components"] if c["definition_id"] ==
                   "custom-8b627b44-80a5-45f9-8b8a-5217d839af73")
        orientations = {o["rotation"]: o["routing_intelligence"]
                        for o in esp["geometry"]["orientations"]}
        self.assertEqual(set(orientations), {0, 90, 180, 270})
        self.assertEqual(orientations[0]["topology"], "dual_row_module")
        self.assertEqual(orientations[0]["pin_columns"], [0, 5])
        self.assertEqual(orientations[0]["body_cell_count"], 36)
        self.assertEqual(orientations[0]["vertical_jumper_obstructed_columns"], [1, 2, 3, 4])
        self.assertEqual(orientations[90]["topology"], "other")
        self.assertEqual(orientations[90]["vertical_jumper_obstructed_columns"], list(range(9)))
        self.assertEqual(orientations[0]["routing_feasibility"], "unverified")

    def test_deterministic(self):
        project = fixture("audio")
        self.assertEqual(analyse_project(project), analyse_project(project))

    def test_same_row_different_nets_are_unverified_cut_opportunities(self):
        project = {
            "board": {"rows": 3, "cols": 8, "lockedRows": True, "lockedCols": True},
            "components": [{"id": "x", "defId": "custom", "boardPos": None}],
            "componentDefs": [{
                "id": "custom", "width": 4, "height": 1,
                "pins": [
                    {"id": "1", "offsetRow": 0, "offsetCol": 0},
                    {"id": "2", "offsetRow": 0, "offsetCol": 3},
                ], "bodyCells": [],
            }],
            "nets": [{"id": "a"}, {"id": "b"}],
            "netAssignments": [
                {"componentId": "x", "pinId": "1", "netId": "a"},
                {"componentId": "x", "pinId": "2", "netId": "b"},
            ],
        }
        result = analyse_project(project)
        zero = next(o for o in result["components"][0]["geometry"]["orientations"] if o["rotation"] == 0)
        self.assertEqual(zero["different_net_pairs"][0]["possible_cut_gaps"], [0, 1, 2])
        self.assertFalse(zero["different_net_pairs"][0]["verified"])
        self.assertEqual(result["board"]["recommendation_status"], "requires_physical_routing_verification")

    def test_renaming_component_label_does_not_change_geometry_or_nets(self):
        project = fixture("moto")
        a = analyse_project(project)
        project["components"][0]["label"] = "renamed"
        b = analyse_project(project)
        self.assertEqual(a["components"], b["components"])
        self.assertNotEqual(a["source_project_sha256"], b["source_project_sha256"])

    def test_unlocked_board_finds_no_padding_placement_candidate(self):
        project = {
            "board": {"rows": 10, "cols": 10, "lockedRows": False, "lockedCols": False},
            "components": [{"id": "a", "defId": "tiny"}, {"id": "b", "defId": "tiny"}],
            "componentDefs": [{"id": "tiny", "width": 1, "height": 1,
                               "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
                               "bodyCells": []}],
            "nets": [], "netAssignments": [],
        }
        result = analyse_project(project)["board"]
        self.assertEqual(result["placement_candidate_status"], "placement_only_candidate")
        self.assertEqual(result["placement_candidate_rows"] * result["placement_candidate_cols"], 2)
        self.assertIsNone(result["recommended_rows"])
        self.assertFalse(result["physical_fit_verified"])

    def test_one_locked_axis_is_preserved(self):
        project = {
            "board": {"rows": 1, "cols": 20, "lockedRows": True, "lockedCols": False},
            "components": [{"id": "a", "defId": "tiny"}, {"id": "b", "defId": "tiny"}],
            "componentDefs": [{"id": "tiny", "width": 1, "height": 1,
                               "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
                               "bodyCells": []}],
            "nets": [], "netAssignments": [],
        }
        result = analyse_project(project)["board"]
        self.assertEqual(result["placement_candidate_rows"], 1)
        self.assertEqual(result["placement_candidate_cols"], 2)

    def test_missing_definition_is_reported_without_discarding_component(self):
        project = fixture("audio")
        project["components"][0]["defId"] = "does-not-exist"
        result = analyse_project(project)
        record = result["components"][0]
        self.assertFalse(record["geometry"]["resolved"])
        self.assertIn("unresolved_footprint", record["warnings"])


if __name__ == "__main__":
    unittest.main()
