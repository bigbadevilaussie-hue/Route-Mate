"""Reproducible STRICT 2D congestion and exact fixed-span feasibility diagnosis.

Usage:
    python -m hellmode.diagnostic --input /tmp/route-mate-hellmode-alpha/best_electrical.json

Scope of proof: fixed board, component positions, copper cuts, jumper IDs,
AND each jumper's endpoint rows and original copper-island memberships.
Only the jumper column may change. This is deliberately NARROWER than
whole-net rerouting, cut recomputation or component moves.

A Hall-deficient row gap is a rigorous impossibility witness under this
scope. A global exact backtracker is attempted only if there is no local
witness. If its deterministic node budget expires, status is UNKNOWN, never
UNSAT. The diagnostic NEVER certifies physical clearance or cut access.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from .copper_model import reconstruct_electrical
from .strict_occupancy import audit_strict_occupancy
from .topology_moves import StripSegments


def _match(wire_ids: list[str], options: dict[str, tuple[int, ...]]) -> dict[int, str]:
    """Maximum cardinality bipartite matching: columns -> jumper ID.

    Exact finite augmenting-path method; deterministic lexicographic order.
    """
    chosen: dict[int, str] = {}

    def augment(wid: str, seen: set[int]) -> bool:
        for col in options[wid]:
            if col in seen:
                continue
            seen.add(col)
            owner = chosen.get(col)
            if owner is None or augment(owner, seen):
                chosen[col] = wid
                return True
        return False

    for wid in sorted(wire_ids, key=lambda w: (len(options[w]), w)):
        augment(wid, set())
    return chosen


def _hall_witness(
    wires: list[str], options: dict[str, tuple[int, ...]],
    matching: dict[int, str],
) -> dict[str, Any] | None:
    """Alternating-forest Hall subset, nonempty iff matching not perfect."""
    matched = set(matching.values())
    unmatched = sorted(set(wires) - matched)
    if not unmatched:
        return None
    reached_wires = set(unmatched)
    reached_cols: set[int] = set()
    queue = deque(unmatched)
    while queue:
        wid = queue.popleft()
        for col in options[wid]:
            if col in reached_cols:
                continue
            reached_cols.add(col)
            owner = matching.get(col)
            if owner is not None and owner not in reached_wires:
                reached_wires.add(owner)
                queue.append(owner)
    neighbourhood = sorted({
        col for wid in reached_wires for col in options[wid]
    })
    witness_ids = sorted(reached_wires)
    assert len(witness_ids) > len(neighbourhood), (
        "deficient matching must yield Hall subset"
    )
    return {
        "jumper_ids": witness_ids,
        "eligible_columns": neighbourhood,
        "jumper_count": len(witness_ids),
        "column_count": len(neighbourhood),
        "minimum_collision_deficit": len(witness_ids) - len(neighbourhood),
    }


def _clusters(
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Both spatial 8-neighbour groups and shared-wire conflict components."""
    cells = {
        (f["col"], f["gap_row"]): f
        for f in findings if f["code"] == "STACKING_VIOLATION"
    }
    remain = set(cells)
    spatial = []
    while remain:
        origin = min(remain)
        remain.remove(origin)
        stack = [origin]
        cluster = []
        while stack:
            here = stack.pop()
            cluster.append(here)
            col, row = here
            neighbours = [
                (col + dc, row + dr)
                for dc in (-1, 0, 1) for dr in (-1, 0, 1)
                if (dc, dr) != (0, 0)
            ]
            for neighbor in neighbours:
                if neighbor in remain:
                    remain.remove(neighbor)
                    stack.append(neighbor)
        ids = sorted({
            wid for key in cluster for wid in cells[key]["wires"]
        })
        spatial.append({
            "count": len(cluster),
            "excess": sum(cells[key]["depth"] - 1 for key in cluster),
            "max_depth": max(cells[key]["depth"] for key in cluster),
            "columns": [min(k[0] for k in cluster), max(k[0] for k in cluster)],
            "gap_rows": [min(k[1] for k in cluster), max(k[1] for k in cluster)],
            "wire_ids": ids,
        })
    spatial.sort(key=lambda c: (-c["excess"], -c["count"],
                                c["columns"], c["gap_rows"]))

    adjacency: dict[str, set[str]] = defaultdict(set)
    for f in cells.values():
        owners = f["wires"]
        for wid in owners:
            adjacency[wid].update(set(owners) - {wid})
    remaining = set(adjacency)
    wire_clusters = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        stack = [start]
        group = {start}
        while stack:
            for other in sorted(adjacency[stack.pop()] & remaining):
                remaining.remove(other)
                group.add(other)
                stack.append(other)
        covered = [
            f for f in cells.values() if set(f["wires"]) & group
        ]
        wire_clusters.append({
            "jumper_count": len(group),
            "wire_ids": sorted(group),
            "excess": sum(f["depth"] - 1 for f in covered),
            "overoccupied_gap_cells": len(covered),
        })
    wire_clusters.sort(key=lambda c: (-c["excess"], c["wire_ids"]))
    total = sum(c["excess"] for c in spatial)
    return {
        "spatial": spatial,
        "wire_conflict": wire_clusters,
        "spatial_cluster_count": len(spatial),
        "wire_cluster_count": len(wire_clusters),
        "largest_spatial_share": round(
            spatial[0]["excess"] / total, 6
        ) if total else 0,
        "largest_wire_conflict_share": round(
            wire_clusters[0]["excess"] / total, 6
        ) if total else 0,
    }


def _domains(
    board: dict[str, Any], pads: list[dict[str, Any]],
    wire_nets: dict[str, str],
) -> tuple[dict[str, tuple[int, ...]], dict[str, tuple[int, int]], dict[str, Any]]:
    """Allowed columns consistent with fixed endpoint copper strips and pads.

    Candidate pad holes are not assumed occupied by the original jumper
    while evaluating an alternative column. Body/lead clearance requiring
    real measured geometry is out-of-scope and can only shrink domains.
    """
    model = StripSegments(board)
    by_row_col: dict[tuple[int, int], list[str | None]] = defaultdict(list)
    for pad in pads:
        by_row_col[(pad["row"], pad["col"])].append(pad.get("net_id"))
    domains = {}
    spans = {}
    domain_info = {}
    for wire in board["wires"]:
        ident = wire["id"]
        a, b = wire["from"], wire["to"]
        lo, hi = sorted((a["row"], b["row"]))
        if not lo < hi:
            raise ValueError(f"{ident}: zero-length jumper")
        spans[ident] = (lo, hi)
        net = wire_nets.get(ident)
        if not net:
            raise ValueError(f"{ident}: independent net ownership unavailable")
        left = model.segments[model.island(a)]
        right = model.segments[model.island(b)]
        candidate_columns = range(max(left.left, right.left),
                                  min(left.right, right.right) + 1)
        allowed = []
        for col in candidate_columns:
            if any((r, col) in by_row_col
                   for r in range(lo + 1, hi)):
                continue
            if any(
                any(owner is None or owner != net
                    for owner in by_row_col.get((r, col), ()))
                for r in (lo, hi)
            ):
                continue
            allowed.append(col)
        domains[ident] = tuple(allowed)
        domain_info[ident] = {
            "rows": [lo, hi],
            "original_col": a["col"],
            "cut_compatible_columns": [max(left.left, right.left),
                                       min(left.right, right.right)],
            "strict_pad_eligible_columns": list(allowed),
            "assigned_net": net,
        }
    return domains, spans, domain_info


def _exact_coloring(
    domains: dict[str, tuple[int, ...]],
    spans: dict[str, tuple[int, int]],
    *,
    node_limit: int,
) -> dict[str, Any]:
    """Exact finite DFS with forward-checking, deterministic budget.

    For two jumpers with overlapping closed row intervals the same column
    causes shared-gap, shared-landing or endpoint-on-span collision.
    """
    if type(node_limit) is not int or node_limit <= 0:
        raise ValueError("node_limit must be positive integer")
    names = sorted(domains)
    neighbors = {
        wid: {
            other for other in names if other != wid
            and max(spans[wid][0], spans[other][0])
            <= min(spans[wid][1], spans[other][1])
        } for wid in names
    }
    possible = {name: set(domains[name]) for name in names}
    assignment: dict[str, int] = {}
    visits = 0
    budget_exhausted = False

    def search() -> bool:
        nonlocal visits, budget_exhausted
        if len(assignment) == len(names):
            return True
        if visits >= node_limit:
            budget_exhausted = True
            return False
        visits += 1
        unassigned = (name for name in names if name not in assignment)
        name = min(
            unassigned, key=lambda w: (
                len(possible[w]), -len(neighbors[w]), w
            )
        )
        if not possible[name]:
            return False
        # Least-constraining value first increases likelihood of a witness.
        def value_key(col: int):
            demand = sum(col in possible[n] for n in neighbors[name]
                         if n not in assignment)
            return demand, col
        for col in sorted(possible[name], key=value_key):
            if any(assignment.get(n) == col for n in neighbors[name]):
                continue
            assignment[name] = col
            removed = []
            impossible = False
            for other in neighbors[name]:
                if other not in assignment and col in possible[other]:
                    possible[other].remove(col)
                    removed.append(other)
                    if not possible[other]:
                        impossible = True
                        break
            if not impossible and search():
                return True
            for other in removed:
                possible[other].add(col)
            del assignment[name]
            if budget_exhausted:
                return False
        return False

    is_sat = search()
    return {
        "status": (
            "SAT_EXACT" if is_sat else
            "UNKNOWN_NODE_LIMIT" if budget_exhausted else
            "UNSAT_EXACT"
        ),
        "nodes_visited": visits,
        "node_limit": node_limit,
        "column_assignment": dict(sorted(assignment.items())) if is_sat else None,
        "scope": "fixed cuts, placement, endpoint rows, jumper identities, copper memberships",
    }


def diagnose(
    project: dict[str, Any],
    *,
    node_limit: int = 150000,
) -> dict[str, Any]:
    """Report observed clusters, per-gap Hall bounds and exact CSP outcome."""
    electrical = reconstruct_electrical(project)
    if electrical["status"] != "PASS":
        raise ValueError(
            "diagnostic needs independently electrically verified input: "
            + str(electrical["errors"][:5])
        )
    strict = audit_strict_occupancy(
        project["board"],
        pin_holes=electrical["pin_holes"],
        trusted_wire_nets=electrical["wire_nets"],
    )
    gaps = [f for f in strict["findings"]
            if f["code"] == "STACKING_VIOLATION"]
    domain, spans, info = _domains(
        project["board"], electrical["pin_holes"], electrical["wire_nets"],
    )
    rows = project["board"]["rows"]
    gap_bounds = []
    hall_witnesses = []
    for row in range(rows - 1):
        active = sorted([
            wid for wid, (low, high) in spans.items()
            if low <= row < high
        ])
        if not active:
            continue
        options = {wid: domain[wid] for wid in active}
        match = _match(active, options)
        hall = _hall_witness(active, options, match)
        observed = sum(f["depth"] - 1 for f in gaps
                       if f["gap_row"] == row)
        eligible_union = sorted(set().union(*(options.values())))
        data = {
            "row_gap": row,
            "active_jumpers": len(active),
            "active_ids": active,
            "eligible_column_union": eligible_union,
            "eligible_column_count": len(eligible_union),
            "maximum_distinct_column_matching": len(match),
            "minimum_collision_deficit": len(active) - len(match),
            "observed_excess": observed,
        }
        if hall:
            data["hall_witness"] = hall
            hall_witnesses.append({"row_gap": row, **hall})
        gap_bounds.append(data)

    empty_domains = [wid for wid, choices in domain.items() if not choices]
    if hall_witnesses:
        exact = {
            "status": "UNSAT_PROVED_BY_HALL_GAP",
            "reason": (
                "A set of fixed row-span jumpers competing for a single "
                "row gap has fewer admissible distinct columns than wires. "
                "No global assignment of the fixed spans can satisfy STRICT."
            ),
            "nodes_visited": 0,
            "node_limit": node_limit,
            "column_assignment": None,
        }
    else:
        exact = _exact_coloring(domain, spans, node_limit=node_limit)
        if exact["status"] == "SAT_EXACT":
            # Verify the *actual* reassigned project independently: a
            # mathematical CSP SAT does not by itself award certification.
            import copy
            candidate = copy.deepcopy(project)
            for wire in candidate["board"]["wires"]:
                col = exact["column_assignment"][wire["id"]]
                wire["from"]["col"] = col
                wire["to"]["col"] = col
            verify = reconstruct_electrical(candidate)
            occupancy = audit_strict_occupancy(
                candidate["board"], pin_holes=verify["pin_holes"],
                trusted_wire_nets=verify["wire_nets"],
            )
            if verify["status"] != "PASS" or occupancy["status"] != "STRICT_2D_CLEAR":
                exact["status"] = "SAT_REJECTED_BY_INDEPENDENT_VERIFIER"
                exact["verifier_errors"] = verify["errors"][:10]
                exact["strict_findings"] = occupancy["findings"][:10]

    clusters = _clusters(gaps)
    return {
        "input_electrical_pass": True,
        "scope": (
            "fixed component placement, fixed cuts, fixed endpoints' ROWS, "
            "fixed jumper count and independent original copper-island "
            "ownership; only each jumper's COLUMN may change"
        ),
        "counts": {
            "jumpers": len(project["board"]["wires"]),
            "cuts": len(project["board"].get("cuts", [])),
            "observed_excess_gap_occupancy":
                strict["counts"]["excess_gap_occupancy"],
            "observed_stacked_gap_cells":
                strict["counts"]["stacked_gaps"],
            "observed_max_depth": strict["counts"]["max_stack_depth"],
            "other_illegal_hole_counts": {
                key: strict["counts"][key]
                for key in (
                    "shared_landing_holes",
                    "endpoint_on_span_holes",
                    "intermediate_pad_holes",
                    "landing_net_conflicts",
                    "landing_net_unverified",
                )
            },
            "wires_with_zero_eligible_columns": len(empty_domains),
        },
        "clusters": clusters,
        "empty_domain_wire_ids": empty_domains,
        "hall_infeasible_row_gaps": [
            x["row_gap"] for x in gap_bounds
            if x["minimum_collision_deficit"] > 0
        ],
        "minimum_per_gap_deficit": max(
            (x["minimum_collision_deficit"] for x in gap_bounds), default=0
        ),
        "row_gap_bounds": gap_bounds,
        "hall_witnesses": hall_witnesses,
        "jumper_domains": info,
        "exact_global_fixed_span_assignment": exact,
        "limitations": [
            "Lower bounds and exact status apply ONLY to fixed endpoint rows and fixed cuts.",
            "A component move, cut change, or a differently connected jumper tree may escape this proof.",
            "Pad and cut compatibility are necessary constraints, not measured package/2.5D clearance.",
            "No physical PASS, cut accessibility or BUILD_READY is established.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--node-limit", type=int, default=150000)
    opts = parser.parse_args()
    project = json.loads(opts.input.read_text(encoding="utf-8"))
    result = diagnose(project, node_limit=opts.node_limit)
    if opts.out:
        opts.out.parent.mkdir(parents=True, exist_ok=True)
        opts.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    counts, cluster = result["counts"], result["clusters"]
    print("HELL MODE FIXED-SPAN DIAGNOSTIC (no physical certification)")
    print(f"  Jumpers/cuts: {counts['jumpers']}/{counts['cuts']}")
    print(f"  Stacked cells/excess: {counts['observed_stacked_gap_cells']}/{counts['observed_excess_gap_occupancy']}")
    print(f"  Spatial clusters: {cluster['spatial_cluster_count']}; largest carries {cluster['largest_spatial_share']*100:.1f}% of excess")
    print(f"  Shared-wire clusters: {cluster['wire_cluster_count']}; largest carries {cluster['largest_wire_conflict_share']*100:.1f}% of excess")
    print(f"  Exact fixed-span column assignment: {result['exact_global_fixed_span_assignment']['status']}")
    print(f"  Provably deficient row gaps: {result['hall_infeasible_row_gaps']}")
    for idx, item in enumerate(cluster["spatial"][:5], 1):
        print(f"  Spatial #{idx}: excess={item['excess']}, cols={item['columns']}, gap_rows={item['gap_rows']}, jumper_ids={item['wire_ids']}")
    for item in result["row_gap_bounds"]:
        if item["minimum_collision_deficit"]:
            print(f"  GAP {item['row_gap']}: jumpers={item['active_jumpers']}, maximum_distinct_columns={item['maximum_distinct_column_matching']}, provable_deficit={item['minimum_collision_deficit']}")
            print(f"    Hall subset: {item['hall_witness']}")
    if opts.out:
        print(f"  Full report: {opts.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
