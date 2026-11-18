"""Electrical-adjacency checks shared by placement and verification.

Different-net pins cannot share a hole or occupy neighbouring holes on one
continuous strip. The caller decides whether an adjacent pair is rejected or
resolved with a between-hole cut.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Iterable

Pin = tuple[int, int, str | None, str]

def hole_index(pins: Iterable[Pin]) -> dict[tuple[int, int], list[tuple[str, str]]]:
    """Map each hole to every assigned (net, reference) pin at that hole."""
    holes: dict[tuple[int, int], list[tuple[str, str]]] = defaultdict(list)
    for row, col, net, ref in pins:
        if net is not None:
            holes[(int(row), int(col))].append((str(net), str(ref)))
    return holes

def _conflicts_at(hole, holes) -> list[dict]:
    row, col = hole
    found = []
    here = holes.get(hole, [])
    for index, (net_a, ref_a) in enumerate(here):
        for net_b, ref_b in here[index + 1:]:
            if net_a != net_b:
                found.append({"kind": "same_hole", "row": row, "cols": (col, col),
                              "nets": tuple(sorted((net_a, net_b))),
                              "refs": tuple(sorted((ref_a, ref_b)))})
    for net_a, ref_a in here:
        for net_b, ref_b in holes.get((row, col + 1), []):
            if net_a != net_b:
                found.append({"kind": "adjacent", "row": row, "cols": (col, col + 1),
                              "nets": tuple(sorted((net_a, net_b))),
                              "refs": tuple(sorted((ref_a, ref_b)))})
    return found

def adjacency_conflicts(pins: Iterable[Pin]) -> list[dict]:
    """Return all same-hole and adjacent-hole different-net pin pairs."""
    holes = hole_index(pins)
    out = []
    for hole in sorted(holes):
        out.extend(_conflicts_at(hole, holes))
    return out

def candidate_conflicts(candidate: Iterable[Pin], placed: dict) -> list[dict]:
    """Return conflicts a candidate creates against placed pins and itself."""
    merged = {hole: list(items) for hole, items in placed.items()}
    touched = set()
    for row, col, net, ref in candidate:
        if net is None:
            continue
        row, col = int(row), int(col)
        merged.setdefault((row, col), []).append((str(net), str(ref)))
        touched.update({(row, col - 1), (row, col), (row, col + 1)})
    out = []
    for hole in sorted(touched):
        if hole in merged:
            out.extend(_conflicts_at(hole, merged))
    seen, unique = set(), []
    for item in out:
        key = (item["kind"], item["row"], item["cols"], item["nets"], item["refs"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique

__all__ = ["adjacency_conflicts", "candidate_conflicts", "hole_index"]
