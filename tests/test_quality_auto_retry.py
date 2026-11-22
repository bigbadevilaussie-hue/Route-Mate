"""Automatic quality/contact retries retain the strongest verified route."""
import copy
import unittest
from unittest.mock import patch

from solve.placement_feedback import solve_with_feedback


def fixture():
    return {"board": {"rows": 4, "cols": 8, "cuts": [], "wires": []},
            "components": [], "componentDefs": [], "netAssignments": []}


def verified(index):
    project = fixture()
    project["name"] = f"verified-{index}"
    project["board"]["cuts"] = [{"id": str(i)} for i in range(index)]
    return {"status": "ROUTED", "project": project,
            "verification": {"status": "PASS"}, "warnings": []}


def placement(_source, **kwargs):
    output = fixture()
    variant = kwargs.get("placement_variant", 0)
    output["name"] = f"placement-{variant}"
    output["components"] = [{"id": "X", "boardPos": {"row": 0, "col": variant}}]
    return {"status": "PLACED", "project": output,
            "report": {"body_spacing_used": kwargs.get("body_spacing_holes", 1)}}


class AutoRetryQualityTests(unittest.TestCase):
    @patch("solve.placement_feedback.inspect_assumed_contacts")
    @patch("solve.placement_feedback.score_render")
    @patch("solve.placement_feedback.route_holes")
    @patch("solve.placement_feedback.quick_fit", side_effect=placement)
    def test_low_score_and_contacts_retries_and_selects_better_verified(
            self, fit, route, score, contacts):
        route.side_effect = [verified(1), verified(2), verified(3)]
        score.side_effect = [
            {"score": 30.3, "wires": 48, "cuts": 61, "wire_length_mm": 825.5},
            {"score": 45.0, "wires": 40, "cuts": 50, "wire_length_mm": 700.0},
            {"score": 80.0, "wires": 20, "cuts": 30, "wire_length_mm": 500.0},
        ]
        contacts.side_effect = [[{}] * 4, [{}] * 2, []]
        events = []
        source = fixture()
        baseline = copy.deepcopy(source)
        result = solve_with_feedback(
            source, attempts=3, body_spacing_holes=0,
            quality_floor=40, contact_warning_limit=1,
            improvement_attempts=2, progress=events.append,
        )
        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["project"]["name"], "verified-3")
        self.assertEqual(result["selection_metrics"]["contacts"], 0)
        self.assertEqual(result["quality_retry"]["extra_attempts"], 2)
        self.assertTrue(result["quality_retry"]["triggered"])
        self.assertEqual([x["last"]["quality_score"] for x in events],
                         [30.3, 45.0, 80.0])
        self.assertEqual(source, baseline)

    @patch("solve.placement_feedback.inspect_assumed_contacts", return_value=[])
    @patch("solve.placement_feedback.score_render", return_value={
        "score": 82, "wires": 10, "cuts": 12, "wire_length_mm": 100,
    })
    @patch("solve.placement_feedback.route_holes", return_value=verified(1))
    @patch("solve.placement_feedback.quick_fit", side_effect=placement)
    def test_good_first_route_stops_immediately(self, fit, route, score, contacts):
        result = solve_with_feedback(
            fixture(), attempts=24, body_spacing_holes=0,
        )
        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["attempts_used"], 1)
        self.assertFalse(result["quality_retry"]["triggered"])
        route.assert_called_once()

    @patch("solve.placement_feedback.inspect_assumed_contacts")
    @patch("solve.placement_feedback.score_render")
    @patch("solve.placement_feedback.route_holes")
    @patch("solve.placement_feedback.quick_fit", side_effect=placement)
    def test_failed_retry_keeps_baseline_and_caps_extra_attempts(
            self, fit, route, score, contacts):
        route.side_effect = [
            verified(1),
            {"status": "ROUTING_FAILED", "errors": ["blocked"]},
            {"status": "ROUTING_FAILED", "errors": ["blocked"]},
        ]
        score.return_value = {
            "score": 30.3, "wires": 48, "cuts": 61, "wire_length_mm": 825.5,
        }
        contacts.return_value = [{}] * 4
        result = solve_with_feedback(
            fixture(), attempts=24, body_spacing_holes=0,
            improvement_attempts=2,
        )
        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["project"]["name"], "verified-1")
        self.assertEqual(result["attempts_used"], 3)
        self.assertEqual(result["quality_retry"]["extra_attempts"], 2)

    @patch("solve.placement_feedback.inspect_assumed_contacts")
    @patch("solve.placement_feedback.score_render")
    @patch("solve.placement_feedback.route_holes")
    @patch("solve.placement_feedback.quick_fit", side_effect=placement)
    def test_fewer_nominal_contacts_outranks_provisional_score(
            self, fit, route, score, contacts):
        route.side_effect = [verified(1), verified(2), verified(3)]
        score.side_effect = [
            {"score": 30, "wires": 48, "cuts": 61, "wire_length_mm": 800},
            {"score": 38, "wires": 42, "cuts": 59, "wire_length_mm": 720},
            {"score": 34, "wires": 44, "cuts": 60, "wire_length_mm": 730},
        ]
        contacts.side_effect = [[{}] * 4, [{}] * 3, []]
        result = solve_with_feedback(
            fixture(), attempts=3, body_spacing_holes=0,
            improvement_attempts=2,
        )
        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["project"]["name"], "verified-3")
        self.assertEqual(result["selection_metrics"]["contacts"], 0)

    def test_invalid_quality_controls_rejected(self):
        for arg in (
            {"quality_floor": -1},
            {"quality_floor": 120},
            {"contact_warning_limit": -1},
            {"improvement_attempts": 25},
        ):
            with self.subTest(arg=arg), self.assertRaises(ValueError):
                solve_with_feedback(fixture(), **arg)


if __name__ == "__main__":
    unittest.main()
