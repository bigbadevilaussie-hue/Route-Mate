"""Physical coordinates derived from Route-Mate's exact logical board geometry.

The saved project geometry remains authoritative for component pin/body occupancy.
This module only converts normalized hole-pitch coordinates into millimetres;
it does not infer component dimensions or clearances from artwork or labels.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from board_geometry import BoardGrid, GridPoint, component_geometry

# Standard stripboard pitch: exactly 0.1 inch = 2.54 mm.
HOLE_PITCH_MM = Fraction(127, 50)
HALF_PITCH_MM = HOLE_PITCH_MM / 2


@dataclass(frozen=True, slots=True)
class PhysicalPoint:
    """Exact physical coordinate in millimetres."""

    x_mm: Fraction
    y_mm: Fraction


@dataclass(frozen=True, slots=True)
class PhysicalSegment:
    """Straight physical segment in millimetres."""

    start: PhysicalPoint
    end: PhysicalPoint


@dataclass(frozen=True, slots=True)
class PhysicalCell:
    """Square occupancy cell centred on a board hole, in millimetres."""

    row: int
    col: int
    left_mm: Fraction
    top_mm: Fraction
    right_mm: Fraction
    bottom_mm: Fraction


def to_physical(point: GridPoint) -> PhysicalPoint:
    """Convert an exact normalized grid point to millimetres."""
    return PhysicalPoint(point.x * HOLE_PITCH_MM, point.y * HOLE_PITCH_MM)


def physical_hole_center(grid: BoardGrid, row: int, col: int) -> PhysicalPoint:
    """Return the physical centre of a board hole."""
    return to_physical(grid.hole_center(row, col))


def physical_between_cut_center(
    grid: BoardGrid, row: int, left_col: int
) -> PhysicalPoint:
    """Return the physical centre of the gap for a between-hole cut."""
    return to_physical(grid.between_cut_center(row, left_col))


def physical_jumper_segment(
    grid: BoardGrid, start: tuple[int, int], end: tuple[int, int]
) -> PhysicalSegment:
    """Return one legal vertical jumper segment in physical coordinates."""
    segment = grid.jumper_segment(start, end)
    return PhysicalSegment(to_physical(segment.start), to_physical(segment.end))


def physical_component_body(
    component: dict[str, Any], definition: dict[str, Any]
) -> list[PhysicalCell]:
    """Map saved bodyCells/footprintOverride occupancy to physical cell squares.

    This deliberately uses component_geometry(), so rotations and flexible
    two-lead endpoints follow the same authoritative project geometry as the
    solver. A body cell is one pitch-square occupancy cell, not a claim about
    the component's measured outer package dimensions.
    """
    _, body_points = component_geometry(component, definition)
    cells = []
    for row, col in body_points:
        x = Fraction(col) * HOLE_PITCH_MM
        y = Fraction(row) * HOLE_PITCH_MM
        cells.append(PhysicalCell(
            row=row,
            col=col,
            left_mm=x - HALF_PITCH_MM,
            top_mm=y - HALF_PITCH_MM,
            right_mm=x + HALF_PITCH_MM,
            bottom_mm=y + HALF_PITCH_MM,
        ))
    return cells


__all__ = [
    "HOLE_PITCH_MM",
    "HALF_PITCH_MM",
    "PhysicalPoint",
    "PhysicalSegment",
    "PhysicalCell",
    "to_physical",
    "physical_hole_center",
    "physical_between_cut_center",
    "physical_jumper_segment",
    "physical_component_body",
]
