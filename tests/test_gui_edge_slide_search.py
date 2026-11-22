"""GUI Edge+Slide enumerates true edge positions, stops on success, diagnoses failures."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from solve.slide_fit import edge_slide_positions
from solve.desktop_integration import solve_for_display


def fixture(cols=5):
    return {
        "board": {"rows": 3, "cols": cols, "cuts": [], "wires": []},
        "componentDefs": [{
            "id": "pad", "width": 1, "height": 1,
            "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
            "bodyCells": [],
        }],
        "components": [{
            "id": "USB", "label": "USB", "defId": "pad",
            "boardPos": {"row": 0, "col": 2},
            "rotation": 0, "locked": True, "edge": True, "slide": True,
        }],
        "netAssignments": [],
    }


def failed(trial, **kwargs):
    return {
        "status": "ROUTING_FAILED", "project": None,
        "attempts_used": kwargs["attempts"],
        "errors": ["no route"], "history": [
            {"placement": "PLACED", "routing": "ROUTING_FAILED",
             "error": "no route"},
        ],
    }


class EdgeSlideGuiSearchTests(unittest.TestCase):
    def test_all_edge_positions_are_unique_and_nearest_hint_first(self):
        source = fixture()
        before = copy.deepcopy(source)
        anchors = edge_slide_positions(source)
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["edge"], "top")
        self.assertEqual(
            [pos["col"] for pos in anchors[0]["positions"]],
            [2, 1, 3, 0, 4],
        )
        self.assertEqual(source, before)

    def test_stop_immediately_at_first_verified_success(self):
        source = fixture()
        original = copy.deepcopy(source)
        visited = []
        emitted = []

        def fake_solve(trial, *, attempts, clearance, progress=None, cancelled=None):
            self.assertEqual(attempts, 24)
            self.assertFalse(trial["components"][0]["slide"])
            position = trial["components"][0]["boardPos"]["col"]
            visited.append(position)
            if position != 3:
                return failed(trial)
            return {
                "status": "ROUTED", "project": copy.deepcopy(trial),
                "attempts_used": 1,
                "placement": {"status": "PLACED", "project": copy.deepcopy(trial)},
                "routing": {"status": "ROUTED", "project": copy.deepcopy(trial)},
                "history": [{"placement": "PLACED", "routing": "ROUTED"}],
            }

        with patch("solve.desktop_integration._solve_one_position",
                   side_effect=fake_solve):
            result = solve_for_display(source, progress=emitted.append)

        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(visited, [2, 1, 3])
        self.assertEqual([p["completed"] for p in emitted], [1, 2, 3])
        self.assertTrue(all(p["budget"] == 5 for p in emitted))
        self.assertEqual(result["slide_search"]["positions_checked"], 3)
        self.assertEqual(result["slide_search"]["positions_total"], 5)
        self.assertEqual(result["slide_search"]["variants_per_position"], 24)
        self.assertEqual(result["slide_search"]["variants_budget"], 120)
        self.assertEqual(result["slide_search"]["variants_checked"], 49)
        for project in (result["project"], result["placement"]["project"],
                        result["routing"]["project"]):
            part = project["components"][0]
            self.assertEqual(part["boardPos"], {"row": 0, "col": 3})
            self.assertTrue(part["slide"])
            self.assertTrue(part["edge"])
            self.assertTrue(part["locked"])
        self.assertEqual(source, original)

    def test_no_fit_reports_edge_part_and_all_positions_checked(self):
        source = fixture()
        progress = []
        def unfit(trial, **kwargs):
            return {
                "status": "NO_FIT_FOUND", "project": None,
                "attempts_used": kwargs["attempts"],
                "errors": ["other locked part obstructs placement"],
                "history": [{"placement": "NO_FIT_FOUND", "routing": "NOT_ATTEMPTED"}],
            }
        with patch("solve.desktop_integration._solve_one_position",
                   side_effect=unfit) as run:
            result = solve_for_display(source, progress=progress.append)
        self.assertEqual(run.call_count, 5)
        self.assertEqual(result["status"], "NO_FIT_FOUND")
        self.assertEqual(result["attempts_used"], 120)
        self.assertIn("USB (top: 5 positions)", result["errors"][0])
        self.assertIn("cannot fit", result["errors"][0])
        self.assertEqual(progress[-1]["completed"], 5)

    def test_route_failure_is_not_misreported_as_placement_failure(self):
        with patch("solve.desktop_integration._solve_one_position",
                   side_effect=failed) as run:
            result = solve_for_display(fixture())
        self.assertEqual(run.call_count, 5)
        self.assertEqual(result["status"], "ROUTING_FAILED")
        self.assertEqual(result["attempts_used"], 120)
        self.assertIn("placement fitted at 5/5", result["errors"][0])
        self.assertIn("no electrically verified route", result["errors"][0])
        self.assertNotIn("cannot fit the edge", result["errors"][0])

    def test_all_24_variants_are_progressed_within_each_edge_position(self):
        updates = []
        visited = []

        def simulate(trial, *, attempts, clearance, progress=None, cancelled=None):
            self.assertEqual(attempts, 24)
            col = trial["components"][0]["boardPos"]["col"]
            visited.append(col)
            for i in range(1, attempts + 1):
                progress({
                    "completed": i, "budget": attempts, "seconds": 0.0,
                    "last": {"placement": "PLACED", "routing": "ROUTING_FAILED"},
                })
            return {
                "status": "ROUTING_FAILED", "project": None,
                "attempts_used": attempts,
                "errors": ["no route"],
                "history": [{"placement": "PLACED", "routing": "ROUTING_FAILED"}],
            }

        with patch("solve.desktop_integration._solve_one_position",
                   side_effect=simulate):
            result = solve_for_display(fixture(cols=3), progress=updates.append)
        self.assertEqual(visited, [2, 1, 0])
        variants = [event for event in updates
                    if event.get("mode") == "edge_slide_variant"]
        self.assertEqual(len(variants), 72)
        self.assertEqual([event["completed"] for event in variants],
                         list(range(1, 73)))
        self.assertTrue(all(event["budget"] == 72 for event in variants))
        self.assertEqual(result["slide_search"]["variants_checked"], 72)

    def test_multiple_sliders_cover_product_then_stop(self):
        source = fixture(cols=3)
        source["components"][0]["boardPos"] = {"row": 0, "col": 1}
        second = copy.deepcopy(source["components"][0])
        second.update(id="B", label="B",
                      boardPos={"row": 2, "col": 1})
        source["components"].append(second)
        # Two independent 3-position top/bottom locks = nine combinations.
        self.assertEqual(
            [(s["edge"], len(s["positions"]))
             for s in edge_slide_positions(source)],
            [("top", 3), ("bottom", 3)],
        )
        with patch("solve.desktop_integration._solve_one_position",
                   side_effect=failed) as run:
            result = solve_for_display(source)
        self.assertEqual(run.call_count, 9)
        self.assertEqual(result["attempts_used"], 216)


if __name__ == "__main__":
    unittest.main()
