"""Regression tests for the component-side renderer."""

import tempfile
import unittest
from pathlib import Path

from render import render_front, write_front_svg


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
        svg = render_front(self.project)
        self.assertTrue(svg.startswith('<svg '))
        self.assertIn('aria-label="Stripboard component side"', svg)
        self.assertIn("R&lt;&amp;1", svg)
        self.assertEqual(svg.count("<circle"), 17)  # 15 holes + 2 component pins

    def test_pin_labels_are_opt_in(self):
        without = render_front(self.project)
        with_labels = render_front(self.project, show_pin_labels=True)
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
        self.assertIn(">?</text>", render_front(project))

    def test_invalid_board_dimensions_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, "positive integers"):
            render_front({"board": {"rows": 0, "cols": 5}, "components": []})

    def test_write_front_svg(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_front_svg(self.project, Path(tmp) / "preview" / "front.svg")
            self.assertTrue(path.is_file())
            self.assertTrue(path.read_text(encoding="utf-8").startswith("<svg "))


if __name__ == "__main__":
    unittest.main()
