"""Renderer-independent logical geometry for the stripboard grid.

Coordinates are expressed in normalized hole-pitch units:
- x increases with board columns (left to right);
- y increases with board rows (top to bottom);
- hole centres have integer coordinates;
- a between-hole cut lies halfway between adjacent columns.

These values are NOT millimetres, screen pixels, component dimensions, or
clearance measurements. This module deliberately defines no physical envelope.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


Hole = tuple[int, int]  # (row, column)


@dataclass(frozen=True, slots=True)
class GridPoint:
    """Exact point in normalized hole-pitch coordinates (x=column, y=row)."""

    x: Fraction
    y: Fraction


@dataclass(frozen=True, slots=True)
class GridSegment:
    """Straight segment between two logical board points."""

    start: GridPoint
    end: GridPoint


@dataclass(frozen=True, slots=True)
class BoardGrid:
    """Logical coordinate frame for a rectangular stripboard."""

    rows: int
    cols: int

    def __post_init__(self) -> None:
        if type(self.rows) is not int or self.rows < 1:
            raise ValueError("rows must be a positive integer")
        if type(self.cols) is not int or self.cols < 1:
            raise ValueError("cols must be a positive integer")

    def contains_hole(self, row: int, col: int) -> bool:
        """Return whether (row, col) identifies an existing board hole."""
        return (
            type(row) is int and type(col) is int
            and 0 <= row < self.rows and 0 <= col < self.cols
        )

    def hole_center(self, row: int, col: int) -> GridPoint:
        """Return the normalized centre coordinate of a board hole."""
        self._require_hole((row, col), "hole")
        return GridPoint(Fraction(col), Fraction(row))

    def between_cut_center(self, row: int, left_col: int) -> GridPoint:
        """Return the centre of the gap between (row,left_col) and its right neighbour."""
        if type(row) is not int or not 0 <= row < self.rows:
            raise ValueError(f"cut row {row!r} is outside the board")
        if type(left_col) is not int or not 0 <= left_col < self.cols - 1:
            raise ValueError(
                f"between-cut column {left_col!r} has no adjacent hole to its right"
            )
        return GridPoint(Fraction(2 * left_col + 1, 2), Fraction(row))

    def jumper_segment(self, start: Hole, end: Hole) -> GridSegment:
        """Return one legal logical jumper segment between two vertical-aligned holes."""
        self._require_hole(start, "jumper start")
        self._require_hole(end, "jumper end")
        start_row, start_col = start
        end_row, end_col = end
        if start_col != end_col:
            raise ValueError("jumper endpoints must share one column")
        if start_row == end_row:
            raise ValueError("jumper endpoints must be on different rows")
        return GridSegment(
            self.hole_center(start_row, start_col),
            self.hole_center(end_row, end_col),
        )

    def _require_hole(self, point: Hole, context: str) -> None:
        if (
            not isinstance(point, tuple) or len(point) != 2
            or not self.contains_hole(point[0], point[1])
        ):
            raise ValueError(f"{context} {point!r} is not a board hole")


__all__ = ["BoardGrid", "GridPoint", "GridSegment", "Hole"]
