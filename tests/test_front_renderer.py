"""Regression tests for the component-side renderer."""

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from render import render_front, write_front_svg
from render._front import render_front_board


class FrontRendererTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "board": {"rows": 3, "cols": 5, "cuts": [], "wires": []},
            "components": [{
                "id": "r1", "defId": "def-resistor", "label": "R<&1",
                "boardPos": {"row": 1, "col": 1}, "rotation": 0,
                "flexibleEndPos": {"row": 1, "col": 4},
            }],
            "componentDefs": [],
            "nets": [{"id": "n1", "name": "VCC", "color": "#ff0000"}],
            "netAssignments": [
                {"componentId": "r1", "pinId": "1", "netId": "n1"},
                {"componentId": "r1", "pinId": "2", "netId": "n1"},
            ],
        }

    def test_returns_component_side_svg(self):
        svg = render_front_board(self.project)
        self.assertTrue(svg.startswith('<svg '))
        self.assertIn('aria-label="Stripboard component side"', svg)
        self.assertIn("R&lt;&amp;1", svg)
        self.assertEqual(svg.count("<circle"), 17)  # 15 holes + 2 component pins

    def test_highlight_marks_only_the_selected_component(self):
        plain = render_front_board(self.project)
        highlighted = render_front_board(self.project, highlight_component_id="r1")
        self.assertNotIn('data-route-mate-highlight="1"', plain)
        self.assertIn('data-route-mate-highlight="1"', highlighted)
        self.assertIn('stroke="#f97316"', highlighted)

    def test_unknown_definition_can_be_highlighted(self):
        project = {
            "board": {"rows": 2, "cols": 2},
            "components": [{
                "id": "x1", "defId": "missing-def", "label": "X1",
                "boardPos": {"row": 0, "col": 0},
            }],
        }
        svg = render_front_board(project, highlight_component_id="x1")
        self.assertIn('stroke="#f97316"', svg)
        self.assertIn(">?</text>", svg)

    def test_pin_labels_are_opt_in(self):
        without = render_front_board(self.project)
        with_labels = render_front_board(self.project, show_pin_labels=True)
        self.assertNotIn(">1</text>", without)
        self.assertIn(">1</text>", with_labels)

    def test_unknown_definition_is_visible_as_warning_marker(self):
        project = {
            "board": {"rows": 2, "cols": 2},
            "components": [{
                "id": "x1", "defId": "missing-def", "label": "X1",
                "boardPos": {"row": 0, "col": 0},
            }],
        }
        self.assertIn(">?</text>", render_front_board(project))

    def test_invalid_board_dimensions_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, "positive integers"):
            render_front_board({"board": {"rows": 0, "cols": 5}, "components": []})

    def test_public_renderer_uses_production_bridge_and_forwards_highlight(self):
        with patch("render.render.render_project_data", return_value=("<svg production/>", "<svg copper/>", "ok")) as render:
            svg = render_front(self.project, highlight_component_id="r1")
        self.assertEqual(svg, "<svg production/>")
        render.assert_called_once_with(self.project, highlight_component_id="r1")

    def test_write_front_svg(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("render.render.render_project_data", return_value=("<svg production/>", "<svg copper/>", "ok")):
                path = write_front_svg(self.project, Path(tmp) / "preview" / "front.svg")
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), "<svg production/>")


if __name__ == "__main__":
    unittest.main()
