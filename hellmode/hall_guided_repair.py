"""Hall-guided, bounded conflict-group rerouting for Hell Mode alpha.

Targets the actual spatially clustered violating jumpers, rather than
resampling unrelated random wires. Each candidate replaces two bridges at
once. Candidates can be graded with incomplete net groups, but only an
independently electrically verified *improved* result can be returned as a
new best. Original board, cuts, other components and Quick Solve are untouched.

This is experimental routing, NOT STRICT 2.5D or RECORD certification.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Callable

from .conflict_repair import _score
from .diagnostic import diagnose
from .search_state import derive_required_cuts, grade_search_state
from .topology_moves import StripSegments


@dataclass(frozen=True)
class _Change:
    wire_id: str
    replacement: dict[str, Any]


def _pair_replace(
    project: dict[str, Any], first: _Change, second: _Change,
) -> dict[str, Any]:
    ids = {first.wire_id, second.wire_id}
    if len(ids) != 2:
        raise ValueError("a pair must replace two distinct jumpers")
    candidate = copy.deepcopy(project)
    original = candidate["board"]["wires"]
    if sum(w["id"] in ids for w in original) != 2:
        raise ValueError("pair of jumper identifiers missing/duplicated")
    candidate["board"]["wires"] = [
        w for w in original if w["id"] not in ids
    ] + [copy.deepcopy(first.replacement), copy.deepcopy(second.replacement)]
    return candidate


def repair_hall_clusters(
    source: dict[str, Any],
    *,
    wire_nets: dict[str, str],
    pads: list[dict[str, Any]],
    electrical_check: Callable[[dict[str, Any]], bool],
    metric_reader: Callable[[dict[str, Any]], dict[str, Any]],
    quality_key: Callable[[dict[str, Any]], tuple],
    seed: int = 1,
    candidates_per_wire: int = 64,
    max_pair_trials: int = 2500,
    max_electrical_checks: int = 30,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Proof-directed paired wire changes with deterministic resource budgets.

    Search may grade penalised electrical states. Full verifier work is
    restricted to the *best candidates* and never permits a SEARCH_STATE
    to bypass the record barrier. Return the old board if no verified
    improvement exists. Cut derivation is attempted after the pair changes;
    both cut-frozen and rederived candidates are considered.
    """
    if not electrical_check(source):
        raise ValueError("repair requires a verified initial project")
    if (type(candidates_per_wire) is not int
            or type(max_pair_trials) is not int
            or type(max_electrical_checks) is not int
            or min(candidates_per_wire, max_pair_trials,
                   max_electrical_checks) <= 0):
        raise ValueError("search budgets must be positive integers")
    baseline = metric_reader(source)
    best = copy.deepcopy(source)
    best_key = quality_key(baseline)
    diagnosis = diagnose(source, node_limit=1000)
    cluster = diagnosis["clusters"]["spatial"]
    report = {
        "initial_excess": baseline["excess_gap_occupancy"],
        "spatial_clusters": diagnosis["clusters"]["spatial_cluster_count"],
        "target_wire_groups": [x["wire_ids"] for x in cluster],
        "trials_scored": 0,
        "gradient_feasible_proposals": 0,
        "independent_electrical_checks": 0,
        "derived_cut_proposals": 0,
        "verified_improvements": 0,
        "best_excess": baseline["excess_gap_occupancy"],
        "record_eligible": False,
        "physical_pass": False,
    }
    if not cluster:
        return best, report

    rng = random.Random(seed)
    strips = StripSegments(source["board"])
    pools: dict[str, list[_Change]] = {}
    for group in cluster:
        for wid in group["wire_ids"]:
            if wid in pools:
                continue
            replacements, essential = strips.candidate_bridges(
                source["board"], wid, allow_detour=False,
                rng=rng, max_candidates=candidates_per_wire,
            )
            if not essential:
                pools[wid] = []
            else:
                pools[wid] = [
                    _Change(wid, p[0]) for p in replacements if len(p) == 1
                ]

    # Each group is a complete spatial target. Add a Hall-witness neighbour
    # when the visible overlap has only one problematic jumper, but never
    # broaden to the whole board if the two clusters are already known.
    pairs = []
    seen_pairs = set()
    for group in cluster:
        ids = list(group["wire_ids"])
        for a, b in combinations(sorted(ids), 2):
            if (a, b) not in seen_pairs:
                seen_pairs.add((a, b))
                pairs.append((a, b))
    if not pairs:
        return best, report

    # Phase 1: grade pair candidates WITHOUT proving them electrically.
    # Retain the lowest graded proposal per variation; search states may
    # be incomplete, but only a new verified best is exported.
    ranked: list[tuple[tuple, int, dict[str, Any], str]] = []
    inspected = 0
    for first_id, second_id in pairs:
        for first in pools[first_id]:
            for second in pools[second_id]:
                if inspected >= max_pair_trials:
                    break
                inspected += 1
                candidate = _pair_replace(source, first, second)
                try:
                    surrogate = grade_search_state(candidate, wire_nets)
                except ValueError:
                    continue
                # Shorts are vetoed, opens get a steep gradient, and
                # zero-open layouts are still ranked for strict geometry.
                if surrogate.short_group_excess:
                    continue
                report["gradient_feasible_proposals"] += 1
                rank = (
                    surrogate.disconnected_group_excess * 2000
                    + surrogate.illegal_2d_holes * 100
                    + surrogate.excess_gap_occupancy * 20
                    + surrogate.max_stack_depth * 4
                    + surrogate.cut_count,
                    surrogate.objective,
                )
                ranked.append((rank, inspected, candidate, "fixed_cuts"))
                if inspected % 5 == 0:
                    try:
                        derived, _ = derive_required_cuts(candidate, wire_nets)
                        derived_score = grade_search_state(derived, wire_nets)
                    except ValueError:
                        continue
                    if derived_score.short_group_excess:
                        continue
                    report["derived_cut_proposals"] += 1
                    derived_rank = (
                        derived_score.disconnected_group_excess * 2000
                        + derived_score.illegal_2d_holes * 100
                        + derived_score.excess_gap_occupancy * 20
                        + derived_score.max_stack_depth * 4
                        + derived_score.cut_count,
                        derived_score.objective,
                    )
                    ranked.append((
                        derived_rank, inspected, derived, "derived_cuts",
                    ))
            if inspected >= max_pair_trials:
                break
        if inspected >= max_pair_trials:
            break

    report["trials_scored"] = inspected
    ranked.sort(key=lambda item: (item[0], item[1]))
    seen = set()
    for _, _, candidate, mode in ranked:
        if report["independent_electrical_checks"] >= max_electrical_checks:
            break
        # Deduplicate candidate routings across equivalent proposal paths.
        from hashlib import sha256
        import json
        fingerprint = sha256(json.dumps(
            candidate["board"], sort_keys=True
        ).encode()).hexdigest()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        grade = grade_search_state(candidate, wire_nets)
        # Unconnected states are search-only; they cannot be promoted.
        if grade.disconnected_group_excess or grade.short_group_excess:
            continue
        # Cheap occupancy gate before running both independent electrical
        # reconstructions; no need to check a provably worse result.
        cheap, _ = _score(candidate["board"]["wires"], pads, wire_nets)
        if cheap.excess > baseline["excess_gap_occupancy"]:
            continue
        report["independent_electrical_checks"] += 1
        if not electrical_check(candidate):
            continue
        metrics = metric_reader(candidate)
        if quality_key(metrics) < best_key:
            best, best_key = candidate, quality_key(metrics)
            report["verified_improvements"] += 1
            report["best_excess"] = metrics["excess_gap_occupancy"]
            report["winning_move_mode"] = mode
    return best, report


__all__ = ["repair_hall_clusters"]
