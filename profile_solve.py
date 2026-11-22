#!/usr/bin/env python3
"""Profile real Audio/Moto Quick Solve without changing solver behaviour.

Runs the same solve_for_display(..., attempts=8) integration workload on
fresh projects. Records cumulative per-stage timings and cProfile hot spots.

Usage:
    python3 profile_solve.py
    python3 profile_solve.py --board audio --top 35
    python3 profile_solve.py --board moto --repeat 2

Reports are written to profile_results/ (JSON + text + .pstats), which is
excluded by .gitignore. Use regular test suite to confirm correctness.
"""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import pstats
import time
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import solve.desktop_integration as desktop
import solve.placement_feedback as feedback
import solve.hole_router as hole

ROOT = Path(__file__).resolve().parent
BENCHMARKS = {"audio": ROOT / "benchmarks/audio/audio.json",
              "moto": ROOT / "benchmarks/moto/moto.json"}


def _digest(board):
    data = json.dumps(board, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def profile_one(board, repeat_index, out_dir, top):
    project = json.loads(BENCHMARKS[board].read_text(encoding="utf-8"))
    original_hash = _digest(project)
    stats = defaultdict(lambda: {"calls": 0, "seconds": 0.0})
    events = []

    def timed(label, function):
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                stats[label]["calls"] += 1
                stats[label]["seconds"] += elapsed
                events.append({"stage": label, "seconds": round(elapsed, 6)})
        return wrapper

    # Patch the *bound reference used by the caller*, preserving original
    # functions and results. A router call contains its own verification;
    # therefore stage sums are not intended to add to total wall time.
    targets = (
        (feedback, "quick_fit", "placement.quick_fit"),
        (feedback, "route_holes", "routing.route_holes"),
        (feedback, "route_copper", "routing.route_copper_legacy"),
        (hole, "_static", "routing.build_hole_graph"),
        (hole, "_route_net", "routing.search_net"),
        (hole, "verify_project", "routing.electrical_verify"),
        (hole, "quick_audit", "routing.grid_audit"),
        (hole, "audit_project", "routing.physical_audit"),
        (desktop, "verify_project", "bridge.electrical_verify"),
        (desktop, "quick_audit", "bridge.grid_audit"),
        (desktop, "audit_project", "bridge.physical_audit"),
    )
    with ExitStack() as patches:
        for module, attribute, label in targets:
            patches.enter_context(patch.object(module, attribute,
                                               timed(label, getattr(module, attribute))))
        profile = cProfile.Profile()
        wall_start = time.perf_counter()
        profile.enable()
        try:
            result = desktop.solve_for_display(project, attempts=8)
        finally:
            profile.disable()
        wall = time.perf_counter() - wall_start

    if _digest(project) != original_hash:
        raise RuntimeError("PROFILER ERROR: solver mutated source project")

    board_obj = result.get("project")
    summary = {
        "board": board, "run": repeat_index, "attempts_requested": 8,
        "attempts_used": result.get("attempts_used"),
        "status": result.get("status"),
        "verification": (result.get("verification") or {}).get("status"),
        "elapsed_seconds": round(wall, 6),
        "input_sha256": original_hash,
        "solved_board_sha256": _digest(board_obj) if board_obj else None,
        "wires": len(board_obj["board"].get("wires", [])) if board_obj else None,
        "cuts": len(board_obj["board"].get("cuts", [])) if board_obj else None,
        "history": result.get("history", []),
        "stages": {name: {"calls": value["calls"],
                          "seconds": round(value["seconds"], 6)}
                   for name, value in sorted(stats.items())},
        "stage_events": events,
        "stage_times_overlap": True,
    }
    stem = f"{board}_run{repeat_index}"
    raw_path = out_dir / f"{stem}.pstats"
    profile.dump_stats(str(raw_path))
    sink = io.StringIO()
    p = pstats.Stats(profile, stream=sink).strip_dirs().sort_stats("cumulative")
    p.print_stats(top)
    (out_dir / f"{stem}_hotspots.txt").write_text(sink.getvalue(), encoding="utf-8")
    (out_dir / f"{stem}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", choices=("audio", "moto", "both"), default="both")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--top", type=int, default=35)
    parser.add_argument("--out", type=Path, default=Path("profile_results"))
    args = parser.parse_args()
    if args.repeat < 1 or args.top < 1:
        parser.error("--repeat and --top must be positive")
    args.out.mkdir(parents=True, exist_ok=True)
    boards = BENCHMARKS if args.board == "both" else {args.board: BENCHMARKS[args.board]}
    all_results = []
    for name in boards:
        for number in range(1, args.repeat + 1):
            print(f"\n=== {name.upper()} run {number} ===", flush=True)
            result = profile_one(name, number, args.out, args.top)
            all_results.append(result)
            print(f"Status: {result['status']} | verified: {result['verification']} "
                  f"| attempts: {result['attempts_used']} "
                  f"| wall: {result['elapsed_seconds']:.3f}s")
            print("STAGE TIMINGS (inclusive; nested times overlap)")
            for stage, value in sorted(result["stages"].items(),
                                       key=lambda item: -item[1]["seconds"]):
                print(f"  {value['seconds']:9.3f}s  {value['calls']:5d} calls  {stage}")
            print(f"Full cProfile hotspots: {args.out / (name + '_run' + str(number) + '_hotspots.txt')}")
    (args.out / "summary.json").write_text(
        json.dumps(all_results, indent=2) + "\n", encoding="utf-8")
    if any(r["status"] != "ROUTED" or r["verification"] != "PASS"
           for r in all_results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
