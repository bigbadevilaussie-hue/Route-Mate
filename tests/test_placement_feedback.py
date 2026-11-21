"""Regression tests for routing-aware placement feedback."""
import copy
import unittest
from unittest.mock import patch

from solve.placement_feedback import solve_with_feedback


class PlacementFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.source = {"board": {"rows": 4, "cols": 8, "cuts": [], "wires": []}, "components": []}

    @patch("solve.placement_feedback.route_copper")
    @patch("solve.placement_feedback.quick_fit")
    def test_retries_failed_route_then_accepts_verified_route(self, fit, route):
        fit.side_effect = [
            {"status": "PLACED", "project": copy.deepcopy(self.source)},
            {"status": "PLACED", "project": copy.deepcopy(self.source)},
        ]
        route.side_effect = [
            {"status": "ROUTING_FAILED", "errors": ["net A: blocked"], "cuts_added": 0, "wires_added": 0},
            {"status": "ROUTED", "project": copy.deepcopy(self.source),
             "verification": {"status": "PASS"}, "warnings": []},
        ]
        result = solve_with_feedback(self.source, attempts=2)
        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["placement_variant"], 1)
        self.assertEqual(route.call_count, 2)
        self.assertEqual(self.source["board"]["wires"], [])

    @patch("solve.placement_feedback.route_copper")
    @patch("solve.placement_feedback.quick_fit")
    def test_rejects_unverified_route(self, fit, route):
        fit.return_value = {"status": "PLACED", "project": copy.deepcopy(self.source)}
        route.return_value = {"status": "ROUTED", "project": copy.deepcopy(self.source),
                              "verification": {"status": "FAIL"}, "errors": ["short"]}
        result = solve_with_feedback(self.source, attempts=1)
        self.assertEqual(result["status"], "ROUTING_FAILED")

    @patch("solve.placement_feedback.route_copper")
    @patch("solve.placement_feedback.quick_fit")
    def test_does_not_route_failed_placement(self, fit, route):
        fit.return_value = {"status": "NO_FIT_FOUND", "errors": ["no fit"]}
        result = solve_with_feedback(self.source, attempts=3)
        self.assertEqual(result["status"], "ROUTING_FAILED")
        route.assert_not_called()


if __name__ == "__main__":
    unittest.main()
