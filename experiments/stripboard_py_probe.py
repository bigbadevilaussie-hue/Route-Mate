#!/usr/bin/env python3
"""Run a real-fixture experiment against the upstream stripboard-py solver.

This is an adapter experiment, NOT a Route-Mate solver or a buildability verdict.
It preserves sparse body cells as individual keep-outs and transforms the current
Route-Mate footprint rotation into the solver's local coordinates. Off-board parts
are excluded; nets touching off-board pins are therefore explicitly partial.

Install the upstream MIT package first:
    python3 -m pip install "stripboard @ git+https://github.com/Stocko-2073/stripboard-py.git@346efd8425cc13cbde22ab8261df6c8cbd817973"

Run from the Route-Mate repository root:
    python3 experiments/stripboard_py_probe.py --project both --seeds 0 1 2

The script never writes to project JSON. Results are printed as JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from stripboard.router import (
        Board, ComponentInstance, ComponentType, Net, PinDef, Rect,
        PlacementOptions, RouteOptions, route,
    )
except ImportError as exc:
    raise SystemExit(
        "Missing upstream solver. Install with:\n"
        '  python3 -m pip install "stripboard @ git+https://github.com/Stocko-2073/stripboard-py.git@346efd8425cc13cbde22ab8261df6c8cbd817973"\n'
        f"Import error: {exc}"
    )

from render._geometry import BUILTIN_DEFS, resolve_definition


def rotate_point(row: int, col: int, rotation: int, max_row: int, max_col: int) -> tuple[int, int]:
    rotation %= 360
    if rotation == 90:
        return col, max_row - row
    if rotation == 180:
        return max_row - row, max_col - col
    if rotation == 270:
        return max_col - col, row
    return row, col


def load_project(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data.get("components"), list) or not isinstance(data.get("netAssignments"), list):
        raise ValueError(f"{path}: missing components/netAssignments")
    return data


def convert_project(data: dict[str, Any]) -> tuple[Board, list[ComponentInstance], list[Net], dict[str, Any]]:
    definitions = dict(BUILTIN_DEFS)
    definitions.update({str(d["id"]): d for d in data.get("componentDefs", []) if isinstance(d, dict) and "id" in d})
    on_board = [c for c in data["components"] if not c.get("offBoard", False)]
    off_board_ids = {str(c["id"]) for c in data["components"] if c.get("offBoard", False)}
    components = {str(c["id"]): c for c in on_board}

    instances: list[ComponentInstance] = []
    pin_id_map: dict[tuple[str, str], str] = {}
    geometry_errors: list[str] = []
    flexible_count = 0
    sparse_body_cells = 0

    for comp in on_board:
        cid = str(comp["id"])
        definition = resolve_definition(comp, definitions)
        if not definition:
            geometry_errors.append(f"{comp.get('label', cid)}: no resolved footprint")
            continue
        pins = definition.get("pins") or []
        body = definition.get("bodyCells") or []
        if not pins:
            geometry_errors.append(f"{comp.get('label', cid)}: footprint has no pins")
            continue

        raw_points = [
            (int(p.get("offsetRow", 0)), int(p.get("offsetCol", 0)))
            for p in pins if isinstance(p, dict)
        ] + [
            (int(p.get("row", 0)), int(p.get("col", 0)))
            for p in body if isinstance(p, dict)
        ]
        max_row = max((p[0] for p in raw_points), default=0)
        max_col = max((p[1] for p in raw_points), default=0)
        rotation = int(comp.get("rotation", 0) or 0) % 360
        transformed_pins = []
        transformed_body = []
        for p in pins:
            if not isinstance(p, dict):
                continue
            rr, cc = rotate_point(int(p.get("offsetRow", 0)), int(p.get("offsetCol", 0)),
                                  rotation, max_row, max_col)
            transformed_pins.append((str(p.get("id", "")), rr, cc))
        for cell in body:
            if isinstance(cell, dict):
                rr, cc = rotate_point(int(cell.get("row", 0)), int(cell.get("col", 0)),
                                      rotation, max_row, max_col)
                transformed_body.append((rr, cc))

        all_rows = [p[1] for p in transformed_pins] + [p[0] for p in transformed_body]
        all_cols = [p[2] for p in transformed_pins] + [p[1] for p in transformed_body]
        min_row, min_col = min(all_rows, default=0), min(all_cols, default=0)
        shifted_pins = [(pid, rr - min_row, cc - min_col) for pid, rr, cc in transformed_pins]
        shifted_body = [(rr - min_row, cc - min_col) for rr, cc in transformed_body]

        # stripboard-py requires unique local pin IDs. Route-Mate's pushbutton-like
        # footprints can expose the same logical terminal at two physical holes.
        seen: Counter[str] = Counter()
        logical_to_unique: dict[str, list[str]] = defaultdict(list)
        pin_defs = []
        for logical_id, rr, cc in shifted_pins:
            seen[logical_id] += 1
            unique_id = logical_id if seen[logical_id] == 1 else f"{logical_id}__{seen[logical_id]}"
            logical_to_unique[logical_id].append(unique_id)
            pin_defs.append(PinDef(unique_id, (cc, rr)))
        internal = tuple(frozenset(ids) for ids in logical_to_unique.values() if len(ids) > 1)

        keepouts = tuple(Rect(x, y, x, y) for y, x in shifted_body)
        ctype = ComponentType(name=cid, pins=tuple(pin_defs), keepouts=keepouts, internal=internal)
        instances.append(ComponentInstance(id=cid, type=ctype, origin=(1, 1), flipped=False, locked=False))
        for logical_id, unique_ids in logical_to_unique.items():
            pin_id_map[(cid, logical_id)] = unique_ids[0]
        flexible_count += int(bool(definition.get("flexible")))
        sparse_body_cells += len(shifted_body)

    instance_ids = {i.id for i in instances}
    nets_by_id: dict[str, set[tuple[str, str]]] = defaultdict(set)
    assignment_count = 0
    offboard_assignment_count = 0
    for a in data["netAssignments"]:
        cid = str(a.get("componentId"))
        if cid in off_board_ids:
            offboard_assignment_count += 1
            continue
        if cid not in instance_ids:
            continue
        logical_pin = str(a.get("pinId"))
        mapped = pin_id_map.get((cid, logical_pin))
        if mapped is None:
            geometry_errors.append(f"assignment references unmapped pin: {cid}/{logical_pin}")
            continue
        nets_by_id[str(a["netId"])].add((cid, mapped))
        assignment_count += 1

    net_names = {str(n["id"]): str(n.get("name", n["id"])) for n in data.get("nets", [])}
    nets = [Net(id=net_names.get(nid, nid), pins=frozenset(refs))
            for nid, refs in sorted(nets_by_id.items()) if refs]

    board_data = data.get("board", {})
    board = Board(w=int(board_data.get("cols", 0)), h=int(board_data.get("rows", 0)))
    report = {
        "source": data.get("name", "unknown"),
        "board_rows": board.h,
        "board_cols": board.w,
        "components_total": len(data["components"]),
        "components_on_board": len(on_board),
        "components_converted": len(instances),
        "components_off_board": len(off_board_ids),
        "nets_in_solver": len(nets),
        "assignments_on_board": assignment_count,
        "assignments_off_board_excluded": offboard_assignment_count,
        "flexible_footprints": flexible_count,
        "body_cells_preserved_as_single_cell_keepouts": sparse_body_cells,
        "geometry_errors": geometry_errors,
        "net_names_touching_offboard": sorted(
            net_names.get(str(a["netId"]), str(a["netId"]))
            for a in data["netAssignments"] if str(a.get("componentId")) in off_board_ids
        ),
    }
    return board, instances, nets, report


def run_one(path: Path, seed: int, iterations: int, attempts: int) -> dict[str, Any]:
    data = load_project(path)
    board, instances, nets, report = convert_project(data)
    if report["geometry_errors"]:
        return {"fixture": path.name, "seed": seed, "input": report, "error": "geometry conversion incomplete"}
    start = time.perf_counter()
    try:
        result = route(
            board, instances, nets, seed=seed,
            options=RouteOptions(
                on_infeasible="partial",
                placement=PlacementOptions(sa_iterations=iterations, brute_force_budget=25000),
                max_placement_attempts=attempts,
            ),
        )
    except Exception as exc:
        return {
            "fixture": path.name, "seed": seed, "input": report,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": round(time.perf_counter() - start, 3),
        }
    elapsed = time.perf_counter() - start
    placements = {p.instance_id: {"origin": list(p.origin), "flipped": p.flipped} for p in result.placements}
    return {
        "fixture": path.name,
        "seed": seed,
        "input": report,
        "solver": {
            "status": str(result.status),
            "ok": result.ok,
            "routed_nets": sum(n.routed for n in result.net_status),
            "total_nets_including_synthesized_singletons": len(result.net_status),
            "unrouted": [{"net": n.net_id, "reason": n.reason} for n in result.net_status if not n.routed],
            "cuts": len(result.physical_cuts),
            "jumpers": result.cost.num_jumpers,
            "cost": result.cost.total,
            "validation_ok": result.validation.ok,
            "validation": result.validation.summary(),
            "placements": placements,
        },
        "elapsed_seconds": round(elapsed, 3),
        "qualification": (
            "EXPERIMENT ONLY: off-board pins were omitted from solver nets; "
            "Route-Mate sparse body cells were preserved, but flexible footprints were "
            "represented by their declared default pin offsets. This is not an independent "
            "Route-Mate verification or a construction recommendation."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", choices=("moto", "audio", "both"), default="both")
    parser.add_argument("--seeds", nargs="+", type=int, default=[0])
    parser.add_argument("--iterations", type=int, default=1200)
    parser.add_argument("--attempts", type=int, default=4)
    args = parser.parse_args()
    names = ("moto", "audio") if args.project == "both" else (args.project,)
    results = []
    for name in names:
        path = ROOT / "benchmarks" / name / f"{name}.json"
        if not path.is_file():
            raise SystemExit(f"Fixture not found: {path}")
        for seed in args.seeds:
            print(json.dumps(run_one(path, seed, args.iterations, args.attempts), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
