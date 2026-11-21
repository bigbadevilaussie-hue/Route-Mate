"""Bounded transactional cut search around the strict copper router.

No speculative cut is applied to the caller's project. Every accepted result
must pass the independent electrical verifier.
"""
from __future__ import annotations

import copy
import sys
import time
from itertools import combinations

from .route import route_copper
from .island_graph import route_with_island_graph
from .verify import verify_project


def route_transactionally(project, *, max_trials=None, max_extra_cuts=None,
                          max_seconds=None,
                          route_order="constrained", verbose=False):
    """Try baseline, then bounded speculative cuts; commit only verified routes.

    Candidate generation uses the failed router's read-only cut diagnostics.
    This is a bounded search layer, not a complete connectivity-repair solver.
    """
    if any(value is not None and value < 0 for value in (max_trials, max_extra_cuts, max_seconds)):
        raise ValueError("search budgets must be nonnegative")
    started = time.monotonic()
    def log(message):
        if verbose:
            print(f"[route {time.monotonic() - started:.1f}s] {message}",
                  file=sys.stderr, flush=True)
    log("starting strict baseline")
    baseline = route_copper(project, vertical_only=True, route_order=route_order)
    if baseline["status"] == "ROUTED":
        log("baseline routed")
        return {**baseline, "transactional": {
            "trials": 0, "extra_cuts": [], "status": "VERIFIED",
        }}

    log("baseline failed; trying island graph")
    graph_result = None
    # Try coordinated copper-island chains before speculative cut reruns.
    # The graph solver works on a private copy and returns only verified boards.
    if isinstance(project, dict) and isinstance(project.get("board"), dict) and (
        "rows" in project["board"] and "cols" in project["board"]
    ):
        graph_result = route_with_island_graph(project, trace=log if verbose else None)
        if graph_result["status"] != "ROUTED":
            alternate = route_with_island_graph(project, reverse_nets=True, trace=log if verbose else None)
            if alternate["status"] == "ROUTED":
                graph_result = alternate
            else:
                graph_result = {**graph_result, "alternate_failure": {
                    key: value for key, value in alternate.items()
                    if key in ("status", "reason", "net_id", "chains", "reachable_islands")
                }}
        if graph_result["status"] == "ROUTED":
            return {**graph_result, "transactional": {
                "trials": 0, "extra_cuts": [], "status": "VERIFIED",
                "strategy": "island_graph",
            }}

    diagnostic = baseline.get("cut_feasibility") or {}
    bidirectional = baseline.get("bidirectional_cut_feasibility") or {}
    candidates = {}
    for item in diagnostic.get("sample_candidates", []):
        cut = item.get("cut", {})
        if cut.get("kind") == "between":
            candidates[(cut["row"], cut["col"])] = cut
    for item in bidirectional.get("destination_samples", []):
        cut = item.get("cut", {})
        if cut.get("kind") == "between":
            candidates[(cut["row"], cut["col"])] = cut

    existing = {
        (cut.get("row"), cut.get("col"))
        for cut in (project.get("board", {}).get("cuts") or [])
        if cut.get("kind", "between") == "between"
    }
    options = [candidates[key] for key in sorted(candidates) if key not in existing]
    attempts = 0
    log(f"searching {len(options)} candidate cuts")
    for count in range(1, min(max_extra_cuts if max_extra_cuts is not None else len(options), len(options)) + 1):
        for proposed in combinations(options, count):
            if ((max_trials is not None and attempts >= max_trials) or
                    (max_seconds is not None and time.monotonic() - started >= max_seconds)):
                break
            attempts += 1
            log(f"trial {attempts}: {count} cuts " +
                str([(c["row"], c["col"]) for c in proposed]))
            trial = copy.deepcopy(project)
            trial["board"].setdefault("cuts", []).extend(copy.deepcopy(proposed))
            result = route_copper(trial, vertical_only=True, route_order=route_order)
            if result["status"] != "ROUTED":
                log("strict route failed; trying graph")
                # Try a coordinated bridge after the speculative cut.
                if "rows" in trial["board"] and "cols" in trial["board"]:
                    graph_trial = route_with_island_graph(trial, trace=log if verbose else None)
                    if graph_trial["status"] != "ROUTED":
                        graph_trial = route_with_island_graph(trial, reverse_nets=True, trace=log if verbose else None)
                    if graph_trial["status"] == "ROUTED":
                        result = graph_trial
                    else:
                        continue
                else:
                    continue
            verification = verify_project(result["project"])
            if verification["status"] != "PASS":
                log("independent verification failed")
                continue
            return {**result, "transactional": {
                "trials": attempts, "extra_cuts": list(proposed),
                "status": "VERIFIED",
            }}
        if ((max_trials is not None and attempts >= max_trials) or
                (max_seconds is not None and time.monotonic() - started >= max_seconds)):
            break
    log(f"search exhausted after {attempts} trials")
    return {**baseline, "transactional": {
        "trials": attempts, "candidate_cuts": len(options),
        "max_trials": max_trials, "max_extra_cuts": max_extra_cuts,
        "max_seconds": max_seconds, "elapsed_seconds": round(time.monotonic() - started, 2),
        "status": "NO_VERIFIED_ROUTE",
        "graph_failure": None if graph_result is None else {
            key: value for key, value in graph_result.items()
            if key in ("status", "reason", "net_id", "chains", "verification", "alternate_failure", "reachable_islands")
        },
        "scope": "exhaustive diagnostic cut combinations when budgets are unset; not a complete board solver",
    }}


__all__ = ["route_transactionally"]
