"""Read-only M1 occupancy characterisation. NOT the Hell Mode verifier.

Deliberately imports neither the Route-Mate router nor verifier and never
mutates a project. Electrical net ownership, package envelopes and cut
accessibility are explicitly outside this diagnostic's scope.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def inspect_spans(board: dict[str, Any]) -> dict[str, Any]:
    """Count shared vertical jumper gaps and related 2D overlaps.

    Coordinates are zero-based; gap (column,row) lies between row and row+1.
    The report is about geometric projection only. It does NOT infer shorts.
    """
    rows, cols = board["rows"], board["cols"]
    if type(rows) is not int or type(cols) is not int or rows < 2 or cols < 1:
        raise ValueError("invalid board dimensions")
    spans: list[tuple[str, int, int, int]] = []
    by_gap: dict[tuple[int, int], list[str]] = defaultdict(list)
    endpoints: dict[tuple[int, int], list[str]] = defaultdict(list)
    for index, wire in enumerate(board.get("wires", [])):
        name = str(wire.get("id", f"wire[{index}]"))
        start, stop = wire["from"], wire["to"]
        r0, c0 = start["row"], start["col"]
        r1, c1 = stop["row"], stop["col"]
        if not all(type(x) is int for x in (r0, c0, r1, c1)):
            raise ValueError(f"{name}: non-integer endpoint")
        if not (0 <= r0 < rows and 0 <= r1 < rows
                and 0 <= c0 < cols and 0 <= c1 < cols):
            raise ValueError(f"{name}: endpoint outside board")
        if c0 != c1 or r0 == r1:
            raise ValueError(f"{name}: expected nonzero straight vertical span")
        lo, hi = sorted((r0, r1))
        spans.append((name, c0, lo, hi))
        endpoints[(c0, r0)].append(name)
        endpoints[(c1, r1)].append(name)
        for row in range(lo, hi):
            by_gap[(c0, row)].append(name)

    pairs = 0
    identical = contained = partial = 0
    for i, (_, col_a, lo_a, hi_a) in enumerate(spans):
        for _, col_b, lo_b, hi_b in spans[i + 1:]:
            if col_a != col_b or max(lo_a, lo_b) >= min(hi_a, hi_b):
                continue
            pairs += 1
            if (lo_a, hi_a) == (lo_b, hi_b):
                identical += 1
            elif ((lo_a <= lo_b and hi_a >= hi_b)
                  or (lo_b <= lo_a and hi_b >= hi_a)):
                contained += 1
            else:
                partial += 1

    histogram = Counter(len(owners) for owners in by_gap.values())
    extra = sum(len(owners) - 1 for owners in by_gap.values()
                if len(owners) > 1)
    shared_endpoints = sum(len(owners) * (len(owners) - 1) // 2
                           for owners in endpoints.values())
    max_depth = max((len(x) for x in by_gap.values()), default=0)
    deepest = sorted(
        ({"column": col, "gap_row": row, "ids": sorted(ids)}
         for (col, row), ids in by_gap.items() if len(ids) == max_depth),
        key=lambda x: (x["column"], x["gap_row"]),
    )
    return {
        "wires": len(spans),
        "overlap_pairs": pairs,
        "identical_pairs": identical,
        "contained_pairs": contained,
        "partial_pairs": partial,
        "stacked_gaps": sum(len(owners) > 1 for owners in by_gap.values()),
        "excess_gap_occupancy": extra,
        "max_stack_depth": max_depth,
        "shared_endpoint_pairs": shared_endpoints,
        "depth_histogram": {str(key): histogram[key] for key in sorted(histogram)},
        "max_depth_gaps": deepest,
        "note": "2D projection only; does not determine net ownership, shorts, clearance or buildability",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    source = json.loads(args.project.read_text(encoding="utf-8"))
    print(json.dumps(inspect_spans(source["board"]), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
