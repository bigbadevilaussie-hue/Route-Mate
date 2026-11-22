"""Diagnose an Edge+Slide lock by solving at successive board-edge holes.

This is a read-only diagnostic: every trial uses a fresh in-memory project copy.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from board_geometry import BUILTIN_DEFS, resolve_definition
from placement_policy import is_off_board_component
from solve.quick_fit import _local_variant, edge_side
from solve.placement_feedback import solve_with_feedback


def load_project(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("pipeline"), dict):
        return data

    # Sidecars contain only provenance, reports and lock choices. The
    # canonical project itself lives in the referenced JSON file.
    sources = data.get("sources", [])
    reference = next(
        (item.get("path") for item in sources
         if isinstance(item, dict) and item.get("kind") == "project_json"
         and isinstance(item.get("path"), str)),
        data.get("project", {}).get("path"),
    )
    if not isinstance(reference, str) or not reference:
        raise ValueError("state file has no source project path")
    source_path = Path(reference)
    if not source_path.is_absolute():
        source_path = path.parent / source_path
    from collect import validate_project
    project = validate_project(json.loads(source_path.read_text(encoding="utf-8")))
    project.pop("_collectWarnings", None)

    stages = data["pipeline"].get("stages", {})
    import_options = stages.get("IN.project_import", {}).get("options", {})
    if import_options:
        board = project["board"]
        board.update(import_options)
        board["rows"] = int(import_options.get("actualRows", board["rows"]))
        board["cols"] = int(import_options.get("actualCols", board["cols"]))

    constraints = stages.get("PREPARE.constraints", {}).get("report", {}).get("constraints")
    if not isinstance(constraints, dict):
        raise ValueError("state file has no PREPARE.constraints lock choices")
    by_id = {
        str(c.get("id")): c for c in project.get("components", [])
        if isinstance(c, dict)
    }
    for cid, flags in constraints.items():
        if cid not in by_id or not isinstance(flags, dict):
            raise ValueError(f"invalid saved constraint for {cid}")
        component = by_id[cid]
        if flags.get("reposition"):
            component.pop("boardPos", None)
            component.pop("flexibleEndPos", None)
            component["locked"] = component["edge"] = component["slide"] = False
        else:
            component["locked"] = bool(flags.get("locked"))
            component["edge"] = bool(flags.get("edge"))
            component["slide"] = bool(flags.get("slide"))
    return project


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep one Edge+Slide component one hole per solve")
    parser.add_argument("--json", required=True, type=Path, help="project JSON or saved .routemate-state.json")
    parser.add_argument("--component", required=True, help="component ID or exact label")
    parser.add_argument("--limit", type=int, default=8, help="maximum positions to try (0 = all; default 8)")
    parser.add_argument("--attempts", type=int, default=1, help="placement variants per fixed position")
    parser.add_argument("--clearance", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="print positions without solving")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    project = load_project(args.json)
    board = project["board"]
    rows, cols = int(board["rows"]), int(board["cols"])
    parts = [
        c for c in project["components"]
        if isinstance(c, dict) and not is_off_board_component(c)
        and (str(c.get("id")) == args.component or str(c.get("label")) == args.component)
    ]
    if len(parts) != 1:
        parser.error(f"expected exactly one component matching {args.component!r}; found {len(parts)}")
    original = parts[0]
    if not (original.get("locked") is True and original.get("edge") and original.get("slide")):
        parser.error("component must currently have Locked + Edge + Slide enabled")
    if not isinstance(original.get("boardPos"), dict):
        parser.error("slide component has no boardPos")
    definitions = dict(BUILTIN_DEFS)
    definitions.update({
        str(d["id"]): d for d in project.get("componentDefs", [])
        if isinstance(d, dict) and d.get("id")
    })
    definition = resolve_definition(original, definitions)
    if definition is None:
        parser.error("component has no footprint definition")
    side = edge_side(original, definition, rows, cols)
    rotation = int(original.get("rotation", 0) or 0) % 360
    cells, pins, min_r, min_c, height, width = _local_variant(original, definition, rotation)
    if height > rows or width > cols:
        parser.error("footprint cannot fit entirely on the board; this diagnostic requires on-board cells")
    # Align the whole footprint to the chosen board edge. Each successive
    # trial changes only its free (row or column) coordinate by exactly 1.
    if side in ("left", "right"):
        fixed = -min_c if side == "left" else cols - width - min_c
        positions = [(r - min_r, fixed) for r in range(rows - height + 1)]
        old_axis = int(original["boardPos"]["row"]) + min_r
    else:
        fixed = -min_r if side == "top" else rows - height - min_r
        positions = [(fixed, c - min_c) for c in range(cols - width + 1)]
        old_axis = int(original["boardPos"]["col"]) + min_c
    if not positions:
        parser.error("no positions on selected edge")
    start = max(0, min(old_axis, len(positions) - 1))
    # Start near saved position, step forwards one hole at a time, then
    # restart at the opposite end to cover remaining positions.
    sequence = list(range(start, len(positions))) + list(range(0, start))
    if args.limit:
        sequence = sequence[:args.limit]
    print(f"[SLIDE] {original.get('label') or original.get('id')} side={side} rotation={rotation} "
          f"board={rows}x{cols} positions={len(positions)} testing={len(sequence)}", flush=True)
    for i, index in enumerate(sequence, 1):
        row, col = positions[index]
        trial = copy.deepcopy(project)
        target = next(c for c in trial["components"] if isinstance(c, dict) and str(c.get("id")) == str(original.get("id")))
        target["boardPos"] = {"row": row, "col": col}
        # Temporarily fix this one candidate; never alter other locks.
        target["locked"], target["edge"], target["slide"] = True, True, False
        tag = f"[SLIDE {i}/{len(sequence)}] {side} row={row} col={col}"
        print(tag + " LOCK -> SOLVE", flush=True)
        if args.dry_run:
            continue
        result = solve_with_feedback(
            trial, attempts=args.attempts, clearance=args.clearance,
            quick_backtracks=0, router="hole_graph",
        )
        history = result.get("history", [])
        for h in history:
            print("  placement={placement} routing={routing} cuts={cuts} wires={wires} error={error}".format(
                placement=h.get("placement"), routing=h.get("routing"),
                cuts=h.get("cuts", 0), wires=h.get("wires", 0),
                error=h.get("error") or "-",
            ), flush=True)
        print(tag + f" RESULT={result['status']}", flush=True)
        if result["status"] == "ROUTED":
            print("[SLIDE] electrical route found; sweep stopped. Nothing written.", flush=True)
            return
    print("[SLIDE] sweep finished; no files changed.", flush=True)


if __name__ == "__main__":
    main()
