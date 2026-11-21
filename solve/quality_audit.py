"""Audit a routed Route-Mate project without assigning a quality score.

Jumper length is measured in board-hole pitches using Euclidean distance.
The audit deliberately reports measurements only; it does not rank a solve.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any
from board_geometry import BUILTIN_DEFS, BoardGrid, resolve_definition
from physical_geometry import physical_component_body, physical_jumper_segment, jumper_intersects_component
from placement_policy import is_off_board_component


def _point(value: Any, label: str, rows: int, cols: int) -> tuple[int, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{label}: endpoint must be an object")
    row, col = value.get("row"), value.get("col")
    if type(row) is not int or type(col) is not int:
        raise ValueError(f"{label}: row and col must be integers")
    if not (0 <= row < rows and 0 <= col < cols):
        raise ValueError(f"{label}: ({row}, {col}) is outside {rows}x{cols} board")
    return row, col


def audit_project(project: Any, expected_cuts: int | None = None,
                  expected_wires: int | None = None) -> dict[str, Any]:
    """Return count checks, diagonal jumper details and per-jumper lengths."""
    if not isinstance(project, dict):
        raise ValueError("project root must be an object")
    board = project.get("board")
    if not isinstance(board, dict):
        raise ValueError("project must contain a board object")
    rows, cols = board.get("rows"), board.get("cols")
    if type(rows) is not int or type(cols) is not int or rows < 1 or cols < 1:
        raise ValueError("board rows and cols must be positive integers")

    cuts = board.get("cuts", [])
    wires = board.get("wires", [])
    if not isinstance(cuts, list):
        raise ValueError("board.cuts must be a list")
    if not isinstance(wires, list):
        raise ValueError("board.wires must be a list")

    count_checks = {
        "cuts": {"actual": len(cuts), "expected": expected_cuts},
        "wires": {"actual": len(wires), "expected": expected_wires},
    }
    for item in count_checks.values():
        item["matches"] = item["expected"] is None or item["actual"] == item["expected"]
        item["difference"] = (
            None if item["expected"] is None else item["actual"] - item["expected"]
        )

    definitions = dict(BUILTIN_DEFS)
    definitions.update({str(d["id"]): d for d in project.get("componentDefs", [])
                        if isinstance(d, dict) and d.get("id")})
    bodies = []
    for component in project.get("components", []):
        if not isinstance(component, dict) or is_off_board_component(component):
            continue
        if not isinstance(component.get("boardPos"), dict):
            continue
        definition = resolve_definition(component, definitions)
        if definition is not None:
            cells = physical_component_body(component, definition)
            if cells:
                bodies.append((str(component.get("label") or component.get("id")), cells))
    grid = BoardGrid(rows, cols)
    physical_errors = []
    jumper_lengths = []
    diagonals = []
    errors = []
    for index, wire in enumerate(wires):
        wire_id = str(wire.get("id", f"wire[{index}]")) if isinstance(wire, dict) else f"wire[{index}]"
        try:
            if not isinstance(wire, dict):
                raise ValueError("wire record must be an object")
            start = _point(wire.get("from"), f"{wire_id}.from", rows, cols)
            end = _point(wire.get("to"), f"{wire_id}.to", rows, cols)
            dr, dc = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dr, dc)
            record = {
                "id": wire_id,
                "from": {"row": start[0], "col": start[1]},
                "to": {"row": end[0], "col": end[1]},
                "row_delta": dr,
                "col_delta": dc,
                "length_hole_pitches": round(length, 6),
                "diagonal": dr != 0 and dc != 0,
            }
            if start[1] != end[1] or start[0] == end[0]:
                physical_errors.append(f"{wire_id}: not a straight vertical jumper")
            else:
                segment = physical_jumper_segment(grid, start, end)
                for label, cells in bodies:
                    if jumper_intersects_component(segment, cells):
                        physical_errors.append(f"{wire_id}: crosses {label} body occupancy")
            jumper_lengths.append(record)
            if record["diagonal"]:
                diagonals.append(record)
        except ValueError as exc:
            errors.append(str(exc))

    lengths = [item["length_hole_pitches"] for item in jumper_lengths]
    total_length = round(sum(lengths), 6)
    report = {
        "project": project.get("name", "unnamed project"),
        "board": {"rows": rows, "cols": cols},
        "counts": count_checks,
        "jumper_audit": {
            "valid_records": len(jumper_lengths),
            "invalid_records": len(errors),
            "diagonal_count": len(diagonals),
            "diagonals": diagonals,
            "length_unit": "board-hole pitches",
            "lengths": jumper_lengths,
            "total_length_hole_pitches": total_length,
            "shortest": min(lengths) if lengths else None,
            "longest": max(lengths) if lengths else None,
            "average": round(total_length / len(lengths), 6) if lengths else None,
        },
        "physical_jumper_audit": {
            "status": "FAIL" if physical_errors else "GRID_CLEARANCE_ONLY",
            "errors": physical_errors,
            "measured_envelope_verified": False,
        },
        "errors": errors,
    }
    report["status"] = (
        "FAIL" if errors or physical_errors or not all(v["matches"] for v in count_checks.values())
        else "PASS"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="routed Route-Mate project JSON")
    parser.add_argument("--expect-cuts", type=int)
    parser.add_argument("--expect-wires", type=int)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    try:
        project = json.loads(args.project.read_text(encoding="utf-8"))
        report = audit_project(project, args.expect_cuts, args.expect_wires)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Audit error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['project']}: {report['status']}")
        for name, item in report["counts"].items():
            expected = "not supplied" if item["expected"] is None else item["expected"]
            print(f"  {name}: {item['actual']} (expected {expected})")
        ja = report["jumper_audit"]
        print(f"  diagonals: {ja['diagonal_count']}")
        print(f"  total jumper length: {ja['total_length_hole_pitches']} hole pitches")
        for wire in ja["lengths"]:
            flag = " DIAGONAL" if wire["diagonal"] else ""
            print(f"  {wire['id']}: {wire['length_hole_pitches']} pitches{flag}")
        for error in report["errors"] + report["physical_jumper_audit"]["errors"]:
            print(f"  ERROR: {error}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
