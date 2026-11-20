#!/usr/bin/env python3
"""Compare routing orders on exactly the same placed Route-Mate project."""
from __future__ import annotations

import argparse
import copy
import json
import math
import time
from pathlib import Path

from solve.quick_fit import quick_fit
from solve.route import route_copper


def metrics(result, elapsed):
    board = result["project"].get("board", {})
    wires = board.get("wires", [])
    length = 0.0
    diagonals = 0
    for wire in wires:
        a, b = wire.get("from"), wire.get("to")
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        dr = abs(a["row"] - b["row"])
        dc = abs(a["col"] - b["col"])
        length += math.hypot(dr, dc)
        diagonals += int(dr != 0 and dc != 0)
    verification = result.get("verification") or {}
    return {
        "status": result["status"],
        "electrical": verification.get("status", "NOT_VERIFIED"),
        "jumpers": len(wires),
        "jumpers_added": result.get("wires_added"),
        "cuts": len(board.get("cuts", [])),
        "diagonals": diagonals,
        "length_holes": round(length, 3),
        "length_mm_at_2_54_pitch": round(length * 2.54, 2),
        "runtime_s": round(elapsed, 4),
        "errors": result.get("errors", [])[:5],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Collected project JSON (or already placed project)")
    parser.add_argument("--clearance", type=int, default=1)
    parser.add_argument("--vertical-only", action="store_true")
    parser.add_argument("--placed", action="store_true", help="Input already contains final board positions")
    parser.add_argument("--output", type=Path, help="Write results as JSON")
    args = parser.parse_args()
    source = json.loads(args.project.read_text())
    if args.placed:
        placed = copy.deepcopy(source)
        placement = {"status": "INPUT_ALREADY_PLACED"}
    else:
        placement = quick_fit(source, clearance=args.clearance)
        if placement["status"] != "PLACED":
            print(json.dumps({"placement_status": placement["status"],
                              "errors": placement.get("errors", [])}, indent=2))
            raise SystemExit(2)
        placed = placement["project"]
    results = {}
    for order in ("alphabetical", "constrained"):
        start = time.perf_counter()
        outcome = route_copper(placed, vertical_only=args.vertical_only,
                               route_order=order)
        results[order] = metrics(outcome, time.perf_counter() - start)
    report = {
        "input": str(args.project),
        "placement_status": placement["status"],
        "vertical_only": args.vertical_only,
        "comparison": results,
        "note": "Electrical PASS does not establish strict physical buildability.",
    }
    print(json.dumps(report, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
