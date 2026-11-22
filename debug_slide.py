"""Diagnose an Edge+Slide lock by solving at successive board-edge holes.

This is a read-only diagnostic: every trial uses a fresh in-memory project copy.
"""
from __future__ import annotations

import argparse
import copy
import cProfile
import io
import json
import pstats
from time import perf_counter
from pathlib import Path

from board_geometry import BUILTIN_DEFS, resolve_definition
from placement_policy import is_off_board_component
from solve.quick_fit import _local_variant, edge_side
import solve.placement_feedback as feedback


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
    parser.add_argument("--profile", action="store_true", help="show top cumulative-time functions per scan (adds profiling overhead)")
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
    # Edge+Slide preserves the original coordinate perpendicular to its
    # selected edge, including intentional body overhang. Only the parallel
    # coordinate may vary. Electrical pins must remain inside the board.
    fixed_row = int(original["boardPos"]["row"])
    fixed_col = int(original["boardPos"]["col"])
    if side in ("left", "right"):
        if height > rows:
            parser.error("footprint is too tall to slide along this edge")
        positions = [(r - min_r, fixed_col) for r in range(rows - height + 1)]
        old_axis = fixed_row + min_r
    else:
        if width > cols:
            parser.error("footprint is too wide to slide along this edge")
        positions = [(fixed_row, c - min_c) for c in range(cols - width + 1)]
        old_axis = fixed_col + min_c
    if any(
        not (0 <= fixed_row + int(pin["row"]) < rows and
             0 <= fixed_col + int(pin["col"]) < cols)
        for pin in pins
    ):
        parser.error("saved Edge+Slide position has electrical pins outside the board")
    if not positions:
        parser.error("no positions on selected edge")
    start = max(0, min(old_axis, len(positions) - 1))
    # Start at the saved position, then alternate one hole left/right
    # (or up/down). Never visit an anchor outside the valid footprint range.
    sequence = [start]
    for distance in range(1, len(positions)):
        if start - distance >= 0:
            sequence.append(start - distance)
        if start + distance < len(positions):
            sequence.append(start + distance)
    if args.limit:
        sequence = sequence[:args.limit]
    print(f"[SLIDE] {original.get('label') or original.get('id')} side={side} rotation={rotation} "
          f"board={rows}x{cols} positions={len(positions)} testing={len(sequence)}", flush=True)
    # Diagnostic-only wrappers measure the actual solver phases without
    # changing Quick Fit or routing parameters. Restore on exit.
    phase_times = {"placement": 0.0, "hole_router": 0.0, "legacy_router": 0.0}
    original_fit = feedback.quick_fit
    original_holes = feedback.route_holes
    original_copper = feedback.route_copper

    def timed(phase, function):
        def invoke(*args, **kwargs):
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                phase_times[phase] += perf_counter() - started
        return invoke

    feedback.quick_fit = timed("placement", original_fit)
    feedback.route_holes = timed("hole_router", original_holes)
    feedback.route_copper = timed("legacy_router", original_copper)

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
        for phase in phase_times:
            phase_times[phase] = 0.0
        profiler = cProfile.Profile() if args.profile else None
        started = perf_counter()
        try:
            if profiler is not None:
                profiler.enable()
            result = feedback.solve_with_feedback(
                trial, attempts=args.attempts, clearance=args.clearance,
                quick_backtracks=0, router="hole_graph",
            )
        finally:
            if profiler is not None:
                profiler.disable()
            elapsed = perf_counter() - started
        accounted = sum(phase_times.values())
        print(
            f"  TIME total={elapsed:.3f}s placement={phase_times['placement']:.3f}s "
            f"hole_router={phase_times['hole_router']:.3f}s "
            f"legacy_router={phase_times['legacy_router']:.3f}s "
            f"other={max(0.0, elapsed - accounted):.3f}s",
            flush=True,
        )
        if profiler is not None:
            buffer = io.StringIO()
            pstats.Stats(profiler, stream=buffer).strip_dirs().sort_stats("cumulative").print_stats(12)
            print("  PROFILE top 12 by cumulative time:\\n" + buffer.getvalue(), flush=True)
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
            break
    feedback.quick_fit = original_fit
    feedback.route_holes = original_holes
    feedback.route_copper = original_copper
    print("[SLIDE] sweep finished; no files changed.", flush=True)


if __name__ == "__main__":
    main()
