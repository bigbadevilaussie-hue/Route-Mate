"""Tests for the renderer-independent normalized board coordinate frame."""
from __future__ import annotations

import unittest
from fractions import Fraction

from board_geometry import (BoardGrid, GridPoint, BUILTIN_DEFS, component_geometry, resolve_definition, rotate_offset)
from render._geometry import component_geometry as renderer_component_geometry


class BoardGridTests(unittest.TestCase):
    def test_rows_and_columns_define_the_locked_axes(self):
        grid = BoardGrid(rows=24, cols=56)
        self.assertEqual(grid.hole_center(0, 0), GridPoint(Fraction(0), Fraction(0)))
        self.assertEqual(grid.hole_center(3, 7), GridPoint(Fraction(7), Fraction(3)))
        self.assertEqual(grid.hole_center(23, 55), GridPoint(Fraction(55), Fraction(23)))

    def test_between_cut_is_exactly_halfway_between_adjacent_holes(self):
        grid = BoardGrid(rows=4, cols=6)
        cut = grid.between_cut_center(2, 3)
        self.assertEqual(cut.x, Fraction(7, 2))
        self.assertEqual(cut.y, Fraction(2))
        self.assertEqual(cut.x - grid.hole_center(2, 3).x, Fraction(1, 2))
        self.assertEqual(grid.hole_center(2, 4).x - cut.x, Fraction(1, 2))

    def test_jumper_segment_is_vertical_and_uses_hole_centres(self):
        grid = BoardGrid(rows=5, cols=8)
        segment = grid.jumper_segment((0, 6), (4, 6))
        self.assertEqual(segment.start, GridPoint(Fraction(6), Fraction(0)))
        self.assertEqual(segment.end, GridPoint(Fraction(6), Fraction(4)))
        self.assertEqual(segment.start.x, segment.end.x)
        self.assertNotEqual(segment.start.y, segment.end.y)

    def test_rejects_non_vertical_or_zero_length_jumpers(self):
        grid = BoardGrid(rows=5, cols=8)
        with self.assertRaisesRegex(ValueError, "share one column"):
            grid.jumper_segment((0, 2), (4, 3))
        with self.assertRaisesRegex(ValueError, "different rows"):
            grid.jumper_segment((2, 3), (2, 3))

    def test_rejects_invalid_board_dimensions(self):
        for rows, cols in ((0, 4), (4, 0), (-1, 4), (True, 4), (4, 2.5)):
            with self.subTest(rows=rows, cols=cols):
                with self.assertRaises(ValueError):
                    BoardGrid(rows, cols)

    def test_rejects_out_of_board_holes_and_cut_gaps(self):
        grid = BoardGrid(rows=3, cols=4)
        with self.assertRaisesRegex(ValueError, "not a board hole"):
            grid.hole_center(3, 0)
        with self.assertRaisesRegex(ValueError, "not a board hole"):
            grid.jumper_segment((0, 0), (3, 0))
        with self.assertRaisesRegex(ValueError, "outside the board"):
            grid.between_cut_center(3, 0)
        with self.assertRaisesRegex(ValueError, "no adjacent hole"):
            grid.between_cut_center(1, 3)

    def test_last_valid_between_cut_is_before_last_column(self):
        grid = BoardGrid(rows=1, cols=4)
        self.assertEqual(grid.between_cut_center(0, 2).x, Fraction(5, 2))


    def test_footprint_geometry_is_shared_with_renderer_compatibility_layer(self):
        self.assertIs(component_geometry, renderer_component_geometry)

    def test_component_pins_and_body_cells_map_to_board_holes(self):
        component = {
            "id": "Q1", "defId": "custom-q1",
            "boardPos": {"row": 8, "col": 12}, "rotation": 0,
        }
        definition = {
            "width": 2, "height": 3,
            "pins": [
                {"id": "1", "name": "B", "offsetRow": 0, "offsetCol": 0},
                {"id": "2", "name": "C", "offsetRow": 1, "offsetCol": 0},
                {"id": "3", "name": "E", "offsetRow": 2, "offsetCol": 0},
            ],
            "bodyCells": [{"row": 1, "col": 1}],
        }
        pins, body = component_geometry(component, definition)
        self.assertEqual([(p["row"], p["col"]) for p in pins],
                         [(8, 12), (9, 12), (10, 12)])
        self.assertEqual(body, [(9, 13)])

    def test_footprint_override_replaces_only_supported_geometry_fields(self):
        component = {
            "defId": "test-base",
            "boardPos": {"row": 2, "col": 3},
            "footprintOverride": {
                "width": 2, "height": 1,
                "pins": [{"id": "A", "name": "A", "offsetRow": 0, "offsetCol": 1}],
                "bodyCells": [],
            },
        }
        definitions = {
            "test-base": {
                "width": 1, "height": 2, "category": "test",
                "pins": [{"id": "A", "name": "A", "offsetRow": 1, "offsetCol": 0}],
                "bodyCells": [{"row": 0, "col": 0}],
            }
        }
        resolved = resolve_definition(component, definitions)
        self.assertEqual((resolved["width"], resolved["height"]), (2, 1))
        self.assertEqual(resolved["category"], "test")
        pins, body = component_geometry(component, resolved)
        self.assertEqual([(p["row"], p["col"]) for p in pins], [(2, 4)])
        self.assertEqual(body, [])

    def test_flexible_end_maps_body_occupancy_between_saved_leads(self):
        component = {
            "boardPos": {"row": 4, "col": 7},
            "flexibleEndPos": {"row": 8, "col": 15},
        }
        definition = {
            "flexible": True,
            "pins": [
                {"id": "1", "offsetRow": 0, "offsetCol": 0},
                {"id": "2", "offsetRow": 4, "offsetCol": 0},
            ],
            "bodyCells": [{"row": 1, "col": 0}, {"row": 2, "col": 0}, {"row": 3, "col": 0}],
        }
        pins, body = component_geometry(component, definition)
        self.assertEqual([(p["row"], p["col"]) for p in pins], [(4, 7), (8, 15)])
        self.assertEqual(body, [(5, 9), (6, 11), (7, 13)])

    def test_rotation_transforms_pin_and_body_cells_consistently(self):
        component = {
            "boardPos": {"row": 10, "col": 20}, "rotation": 90,
        }
        definition = {
            "width": 2, "height": 3,
            "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0},
                     {"id": "2", "offsetRow": 2, "offsetCol": 1}],
            "bodyCells": [{"row": 1, "col": 0}],
        }
        pins, body = component_geometry(component, definition)
        self.assertEqual([(p["row"], p["col"]) for p in pins], [(10, 22), (11, 20)])
        self.assertEqual(body, [(10, 21)])


if __name__ == "__main__":
    unittest.main()
