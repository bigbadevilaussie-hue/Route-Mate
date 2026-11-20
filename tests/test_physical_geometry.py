"""Tests for exact physical coordinates and saved component occupancy."""
from __future__ import annotations

import unittest
from fractions import Fraction

from board_geometry import BoardGrid
from physical_geometry import (
    HOLE_PITCH_MM,
    PhysicalPoint,
    physical_between_cut_center,
    physical_component_body,
    physical_hole_center,
    physical_jumper_segment,
    jumper_intersects_component,
    jumpers_intersect,
    physical_segment_intersects_cell,
    PhysicalCell,
    PhysicalSegment,
)


class PhysicalGeometryTests(unittest.TestCase):
    def setUp(self):
        self.grid = BoardGrid(rows=24, cols=56)

    def test_pitch_is_exactly_254_hundredths_mm(self):
        self.assertEqual(HOLE_PITCH_MM, Fraction(254, 100))

    def test_hole_centres_convert_to_mm(self):
        self.assertEqual(
            physical_hole_center(self.grid, 3, 7),
            PhysicalPoint(Fraction(1778, 100), Fraction(762, 100)),
        )

    def test_between_hole_cut_is_half_pitch_from_both_holes(self):
        cut = physical_between_cut_center(self.grid, 2, 3)
        self.assertEqual(cut.x_mm, Fraction(889, 100))
        self.assertEqual(cut.y_mm, Fraction(508, 100))
        self.assertEqual(
            cut.x_mm - physical_hole_center(self.grid, 2, 3).x_mm,
            HOLE_PITCH_MM / 2,
        )
        self.assertEqual(
            physical_hole_center(self.grid, 2, 4).x_mm - cut.x_mm,
            HOLE_PITCH_MM / 2,
        )

    def test_jumper_is_vertical_and_physical_length_matches_row_pitch(self):
        jumper = physical_jumper_segment(self.grid, (1, 9), (6, 9))
        self.assertEqual(jumper.start.x_mm, jumper.end.x_mm)
        self.assertEqual(jumper.end.y_mm - jumper.start.y_mm, 5 * HOLE_PITCH_MM)

    def test_jumper_rejects_diagonal_endpoints(self):
        with self.assertRaisesRegex(ValueError, "share one column"):
            physical_jumper_segment(self.grid, (1, 9), (6, 10))

    def test_component_body_uses_saved_occupancy_and_rotation(self):
        component = {
            "boardPos": {"row": 10, "col": 20},
            "rotation": 90,
        }
        definition = {
            "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
            "bodyCells": [{"row": 1, "col": 0}],
        }
        cells = physical_component_body(component, definition)
        self.assertEqual(len(cells), 1)
        cell = cells[0]
        self.assertEqual((cell.row, cell.col), (10, 20))
        self.assertEqual(cell.left_mm, Fraction(4953, 100))
        self.assertEqual(cell.right_mm, Fraction(5207, 100))
        self.assertEqual(cell.top_mm, Fraction(2413, 100))
        self.assertEqual(cell.bottom_mm, Fraction(2667, 100))

    def test_flexible_component_body_follows_saved_endpoint(self):
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
            "bodyCells": [
                {"row": 1, "col": 0},
                {"row": 2, "col": 0},
                {"row": 3, "col": 0},
            ],
        }
        cells = physical_component_body(component, definition)
        self.assertEqual([(c.row, c.col) for c in cells], [(5, 9), (6, 11), (7, 13)])


    def test_jumper_intersects_component_occupancy(self):
        jumper = physical_jumper_segment(self.grid, (1, 9), (6, 9))
        cell = PhysicalCell(3, 9,
            9 * HOLE_PITCH_MM - HOLE_PITCH_MM / 2,
            3 * HOLE_PITCH_MM - HOLE_PITCH_MM / 2,
            9 * HOLE_PITCH_MM + HOLE_PITCH_MM / 2,
            3 * HOLE_PITCH_MM + HOLE_PITCH_MM / 2)
        self.assertTrue(physical_segment_intersects_cell(jumper, cell))
        self.assertTrue(jumper_intersects_component(jumper, [cell]))

    def test_jumper_clear_of_component_occupancy(self):
        jumper = physical_jumper_segment(self.grid, (1, 9), (6, 9))
        cell = PhysicalCell(3, 11,
            11 * HOLE_PITCH_MM - HOLE_PITCH_MM / 2,
            3 * HOLE_PITCH_MM - HOLE_PITCH_MM / 2,
            11 * HOLE_PITCH_MM + HOLE_PITCH_MM / 2,
            3 * HOLE_PITCH_MM + HOLE_PITCH_MM / 2)
        self.assertFalse(jumper_intersects_component(jumper, [cell]))

    def test_jumper_crossing_overlap_and_separation(self):
        vertical = PhysicalSegment(PhysicalPoint(Fraction(0), Fraction(0)),
                                   PhysicalPoint(Fraction(0), Fraction(10)))
        crossing = PhysicalSegment(PhysicalPoint(Fraction(-2), Fraction(5)),
                                   PhysicalPoint(Fraction(2), Fraction(5)))
        overlap = PhysicalSegment(PhysicalPoint(Fraction(0), Fraction(4)),
                                  PhysicalPoint(Fraction(0), Fraction(8)))
        separate = PhysicalSegment(PhysicalPoint(Fraction(2), Fraction(0)),
                                   PhysicalPoint(Fraction(2), Fraction(10)))
        self.assertTrue(jumpers_intersect(vertical, crossing))
        self.assertTrue(jumpers_intersect(vertical, overlap))
        self.assertFalse(jumpers_intersect(vertical, separate))

    def test_boundary_touch_is_component_intersection(self):
        segment = PhysicalSegment(PhysicalPoint(Fraction(0), Fraction(0)),
                                  PhysicalPoint(Fraction(0), Fraction(4)))
        cell = PhysicalCell(1, 0, Fraction(0), Fraction(1), Fraction(2), Fraction(3))
        self.assertTrue(physical_segment_intersects_cell(segment, cell))


if __name__ == "__main__":
    unittest.main()
