"""Deterministic sequence-pair placement skeleton (initial Python port).

Algorithmic reference: upstream KarloFunke/stripboard-editor, main,
src/frontend/components/stripboard/autoLayout5.ts and v5wasm/decode.c,
inspected 2026-11-21. This is a new Python implementation, not a copy
of the upstream source. It is NOT the full V5 row-group decoder, router,
or a physical verifier.

A sequence pair determines the relative position of non-overlapping
rectangular footprints. Two positive permutations mean 'left of';
positive/negative inversion means 'above'. Longest-path compaction
provides a deterministic legal packing when feasible.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Tile:
    id: str
    rows: int
    cols: int

    def __post_init__(self) -> None:
        if not self.id or self.rows < 1 or self.cols < 1:
            raise ValueError("tile needs an id and positive dimensions")


@dataclass(frozen=True)
class Placement:
    row: int
    col: int


def decode_sequence_pair(
    tiles: Sequence[Tile],
    positive: Sequence[str],
    negative: Sequence[str],
    *,
    board_rows: int,
    board_cols: int,
    clearance: int = 0,
    fixed: Mapping[str, Placement] | None = None,
) -> dict[str, Placement] | None:
    """Decode a rectangle skeleton, or return None if infeasible.

    The fixed coordinates are hard constraints: compaction may not move
    them. A None result means this skeleton failed, NOT that the board
    is globally impossible. All rectangles must fit entirely on board.
    """
    if board_rows < 1 or board_cols < 1 or clearance < 0:
        raise ValueError("invalid board dimensions or clearance")
    by_id = {t.id: t for t in tiles}
    ids = set(by_id)
    if len(ids) != len(tiles) or set(positive) != ids or set(negative) != ids:
        raise ValueError("sequence pair must contain each unique tile exactly once")
    if len(positive) != len(ids) or len(negative) != len(ids):
        raise ValueError("sequence pair contains duplicates")
    fixed = dict(fixed or {})
    if not set(fixed).issubset(ids):
        raise ValueError("fixed placement references unknown tile")
    p = {key: i for i, key in enumerate(positive)}
    n = {key: i for i, key in enumerate(negative)}
    # Directed acyclic graphs of relative x and y constraints.
    x_edges: dict[str, list[tuple[str, int]]] = {key: [] for key in ids}
    y_edges: dict[str, list[tuple[str, int]]] = {key: [] for key in ids}
    for i, a in enumerate(positive):
        for b in positive[i + 1:]:
            if n[a] < n[b]:
                x_edges[a].append((b, by_id[a].cols + clearance))
            else:
                y_edges[a].append((b, by_id[a].rows + clearance))

    def compact(edges: dict[str, list[tuple[str, int]]], size: str, limit: int) -> dict[str, int] | None:
        # The y graph also follows the positive sequence: all edges point
        # forward, regardless of the negative-sequence ordering.
        coords = {key: 0 for key in ids}
        axis = "col" if size == "cols" else "row"
        for a in positive:
            locked = fixed.get(a)
            if locked is not None:
                target = getattr(locked, axis)
                if target < coords[a]:
                    return None
                coords[a] = target
            if coords[a] < 0 or coords[a] + getattr(by_id[a], size) > limit:
                return None
            for b, distance in edges[a]:
                coords[b] = max(coords[b], coords[a] + distance)
        return coords

    xs = compact(x_edges, "cols", board_cols)
    ys = compact(y_edges, "rows", board_rows)
    if xs is None or ys is None:
        return None
    return {key: Placement(row=ys[key], col=xs[key]) for key in positive}


__all__ = ["Tile", "Placement", "decode_sequence_pair"]
