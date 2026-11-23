"""Hell Mode clustered-net compound repair: rip up nets, derive cuts, reroute.

The affected nets are selected from *observed* stacked-gap conflict
components, not from a random board-wide set. Each candidate transaction:

1. removes ALL jumper bridges on the affected nets at once;
2. deterministically derives separating strip cuts from placed terminals and
   endpoints of the surviving unaffected nets;
3. rebuilds all affected net trees in a seeded order, allowing new endpoint
   rows/columns, and may derive cuts a second time;
4. accepts ONLY independently electrically verified complete candidates.

Incomplete intermediate states are search-private and never exported as
RECORD; this operator remains experimental ELECTRICAL_ONLY routing.
"""
from __future__ import annotations

import copy
import random
from typing import Any, Callable

from .diagnostic import diagnose
from .net_ripup import rebuild_one_net
from .search_state import derive_required_cuts, grade_search_state


def rebuild_conflicting_nets(
    source: dict[str, Any],
    *,
    wire_nets: dict[str, str],
    pads: list[dict[str, Any]],
    electrical_check: Callable[[dict[str, Any]], bool],
    metric_reader: Callable[[dict[str, Any]], dict[str, Any]],
    quality_key: Callable[[dict[str, Any]], tuple],
    seed: int = 1,
    variants_per_cluster: int = 8,
    max_extra_wires: int = 6,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild clustered nets as one compound transaction with a capped budget."""
    if type(variants_per_cluster) is not int or variants_per_cluster < 1:
        raise ValueError("variants_per_cluster must be a positive integer")
    if type(max_extra_wires) is not int or max_extra_wires < 0:
        raise ValueError("max_extra_wires must be a nonnegative integer")
    if not electrical_check(source):
        raise ValueError("cluster repair requires verified electrical baseline")
    baseline = metric_reader(source)
    best = copy.deepcopy(source)
    best_key = quality_key(baseline)
    diagnostic = diagnose(source, node_limit=1000)
    clusters = diagnostic["clusters"]["wire_conflict"]
    rng = random.Random(seed)
    report = {
        "initial_excess": baseline["excess_gap_occupancy"],
        "clusters": len(clusters),
        "cluster_nets": [],
        "whole_group_trials": 0,
        "cut_derivations": 0,
        "completed_reroutes": 0,
        "independent_electrical_checks": 0,
        "accepted_improvements": 0,
        "best_excess": baseline["excess_gap_occupancy"],
        "physical_pass": False,
        "record_eligible": False,
    }
    known_ids = {w["id"] for w in source["board"]["wires"]}
    if known_ids != set(wire_nets):
        raise ValueError("every input wire needs independently reconstructed net ownership")
    for cluster in clusters:
        nets = sorted({
            wire_nets[wid] for wid in cluster["wire_ids"]
        })
        report["cluster_nets"].append(nets)
        if not nets:
            continue
        for variant in range(variants_per_cluster):
            report["whole_group_trials"] += 1
            candidate = copy.deepcopy(source)
            candidate["board"]["wires"] = [
                w for w in source["board"]["wires"]
                if wire_nets[w["id"]] not in nets
            ]
            owner = {
                w["id"]: wire_nets[w["id"]]
                for w in candidate["board"]["wires"]
            }
            if variant % 2 == 0:
                try:
                    candidate, _ = derive_required_cuts(candidate, owner)
                    report["cut_derivations"] += 1
                except ValueError:
                    continue
            order = list(nets)
            if variant % 3 == 1:
                order.reverse()
            elif variant % 3 == 2:
                rng.shuffle(order)
            failed = False
            for net in order:
                original_ids = {
                    w["id"] for w in candidate["board"]["wires"]
                }
                rebuilt = rebuild_one_net(
                    candidate,
                    net,
                    pads=pads,
                    wire_nets=owner,
                    allow_new_net_wires=True,
                    allow_stack_penalty=(variant % 3 == 2),
                    max_additional_wires=max_extra_wires,
                    seed=rng.randrange(2**31),
                )
                if rebuilt is None:
                    failed = True
                    break
                for w in rebuilt["board"]["wires"]:
                    if w["id"] not in original_ids:
                        owner[w["id"]] = net
                candidate = rebuilt
            if failed:
                continue
            if variant % 3 != 1:
                try:
                    candidate, _ = derive_required_cuts(candidate, owner)
                    report["cut_derivations"] += 1
                except ValueError:
                    continue
            report["completed_reroutes"] += 1
            try:
                grade = grade_search_state(candidate, owner)
            except ValueError:
                continue
            # Incomplete and shorted states supply search guidance only.
            # Independently certify only complete, short-free candidates.
            if grade.disconnected_group_excess or grade.short_group_excess:
                continue
            if (grade.excess_gap_occupancy >
                    baseline["excess_gap_occupancy"]):
                continue
            report["independent_electrical_checks"] += 1
            if not electrical_check(candidate):
                continue
            metrics = metric_reader(candidate)
            if quality_key(metrics) < best_key:
                best = candidate
                best_key = quality_key(metrics)
                report["accepted_improvements"] += 1
                report["best_excess"] = metrics["excess_gap_occupancy"]
                report["winning_cluster_nets"] = nets
                report["winning_variant"] = variant
    return best, report


__all__ = ["rebuild_conflicting_nets"]
