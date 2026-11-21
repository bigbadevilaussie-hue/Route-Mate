"""Bounded transactional cut search around the strict copper router.

No speculative cut is applied to the caller's project. Every accepted result
must pass the independent electrical verifier.
"""
from __future__ import annotations

import copy
import time
from itertools import combinations

from .route import route_copper
from .verify import verify_project


def route_transactionally(project, *, max_trials=3, max_extra_cuts=1,
                          max_seconds=30,
                          route_order="constrained"):
    """Try baseline, then bounded speculative cuts; commit only verified routes.

    Candidate generation uses the failed router's read-only cut diagnostics.
    This is a bounded search layer, not a complete connectivity-repair solver.
    """
    if max_trials < 0 or max_extra_cuts < 0 or max_seconds < 0:
        raise ValueError("search budgets must be nonnegative")
    started = time.monotonic()
    baseline = route_copper(project, vertical_only=True, route_order=route_order)
    if baseline["status"] == "ROUTED":
        return {**baseline, "transactional": {
            "trials": 0, "extra_cuts": [], "status": "VERIFIED",
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
    for count in range(1, min(max_extra_cuts, len(options)) + 1):
        for proposed in combinations(options, count):
            if attempts >= max_trials or time.monotonic() - started >= max_seconds:
                break
            attempts += 1
            trial = copy.deepcopy(project)
            trial["board"].setdefault("cuts", []).extend(copy.deepcopy(proposed))
            result = route_copper(trial, vertical_only=True, route_order=route_order)
            if result["status"] != "ROUTED":
                continue
            verification = verify_project(result["project"])
            if verification["status"] != "PASS":
                continue
            return {**result, "transactional": {
                "trials": attempts, "extra_cuts": list(proposed),
                "status": "VERIFIED",
            }}
        if attempts >= max_trials or time.monotonic() - started >= max_seconds:
            break
    return {**baseline, "transactional": {
        "trials": attempts, "candidate_cuts": len(options),
        "max_trials": max_trials, "max_extra_cuts": max_extra_cuts,
        "max_seconds": max_seconds, "elapsed_seconds": round(time.monotonic() - started, 2),
        "status": "NO_VERIFIED_ROUTE",
        "scope": "bounded cut combinations; existing strict router performs jumper search",
    }}


__all__ = ["route_transactionally"]
