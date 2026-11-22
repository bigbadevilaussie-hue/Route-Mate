"""Stop and Exit are cooperative, prompt and never publish a partial board."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from solve.placement_feedback import solve_with_feedback
from solve.desktop_integration import solve_for_display


def fixture():
    return {
        "board": {"rows": 3, "cols": 6, "cuts": [], "wires": []},
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


class CooperativeCancelTests(unittest.TestCase):
    def test_plain_feedback_cancels_before_starting_fit(self):
        project = fixture()
        with patch("solve.placement_feedback.quick_fit") as fit:
            result = solve_with_feedback(project, attempts=24, cancelled=lambda: True)
        self.assertEqual(result["status"], "CANCELLED")
        self.assertIsNone(result["project"])
        self.assertEqual(result["attempts_used"], 0)
        fit.assert_not_called()

    def test_slide_cancel_does_not_try_remaining_positions(self):
        project = fixture()
        original = copy.deepcopy(project)
        cancel = {"yes": False}
        visited = []
        def one(trial, **kwargs):
            visited.append(trial["components"][0]["boardPos"]["col"])
            cancel["yes"] = True
            return {
                "status": "ROUTING_FAILED", "project": None,
                "errors": ["current position did not route"],
                "history": [{"placement": "PLACED",
                             "routing": "ROUTING_FAILED"}],
            }
        with patch("solve.desktop_integration._solve_one_position", side_effect=one):
            output = solve_for_display(project, cancelled=lambda: cancel["yes"])
        self.assertEqual(visited, [2])
        self.assertEqual(output["status"], "CANCELLED")
        self.assertIsNone(output["project"])
        self.assertEqual(output["slide_search"]["positions_total"], 6)
        self.assertEqual(output["slide_search"]["positions_checked"], 0)
        self.assertEqual(project, original)

    def test_feedback_discards_route_even_if_it_races_cancel(self):
        project = fixture()
        project["components"][0].update(locked=False, edge=False, slide=False)
        cancellation = {"requested": False}
        def quick_fit(trial, **kwargs):
            return {"status": "PLACED", "project": copy.deepcopy(trial)}
        def router(trial, **kwargs):
            cancellation["requested"] = True
            return {
                "status": "ROUTED", "project": copy.deepcopy(trial),
                "verification": {"status": "PASS"},
            }
        with patch("solve.placement_feedback.quick_fit", side_effect=quick_fit), \
             patch("solve.placement_feedback.route_holes", side_effect=router):
            output = solve_with_feedback(
                project, attempts=2, cancelled=lambda: cancellation["requested"],
            )
        self.assertEqual(output["status"], "CANCELLED")
        self.assertIsNone(output["project"])
        self.assertEqual(output["history"], [])


if __name__ == "__main__":
    unittest.main()
