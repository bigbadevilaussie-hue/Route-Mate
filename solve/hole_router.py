"""Negotiated-congestion hole-graph stripboard router.

Unlike the original greedy copper-island router, this treats each hole as an
individually claimable resource, adds jumper edges, reroutes congested nets and
derives cuts from the finished ownership labels. The independent project
verifier, quick geometry audit and physical grid audit decide acceptance.

Currently operates on clean routing (no pre-existing cuts/wires). Use the
original route_copper to preserve partial/manual routing on populated boards.
All budgets are deterministic expansion/iteration limits; no unbounded BFS.
"""
from __future__ import annotations

import copy
import heapq
from collections import Counter, defaultdict
from typing import Any

from board_geometry import BUILTIN_DEFS, component_geometry, resolve_definition
from placement_policy import is_off_board_component
from .route import _terminals
from .verify import verify_project
from .quick_rules import quick_audit
from .quality_audit import audit_project
from .wire_keepout import vertical_gap_keepouts


def _result(status: str, source: Any, errors: list[str], **extra) -> dict[str, Any]:
    return {
        "status": status, "project": copy.deepcopy(source), "errors": errors,
        "warnings": [], "cuts_added": 0, "wires_added": 0,
        "verification": None, **extra,
    }


def _static(project: dict) -> tuple[int, int, set[int], dict[int, str], dict[str, list[int]], dict[int, tuple[tuple[int, int], ...]]]:
    board = project["board"]
    rows, cols = board["rows"], board["cols"]
    if type(rows) is not int or type(cols) is not int or rows < 1 or cols < 2:
        raise ValueError("board rows and cols must be positive (cols >= 2)")
    if rows * cols > 12000:
        raise ValueError("board exceeds 12000 hole search limit")
    records = _terminals(project, rows, cols)
    pin_net: dict[int, str] = {}
    nets: dict[str, set[int]] = defaultdict(set)
    for row, col, net, ref in records:
        hole = row * cols + col
        if hole in pin_net and pin_net[hole] != net:
            raise ValueError(f"different nets share hole {(row, col)}: {pin_net[hole]} and {net} ({ref})")
        pin_net[hole] = net
        nets[net].add(hole)
    definitions = dict(BUILTIN_DEFS)
    definitions.update({
        str(d["id"]): d for d in project.get("componentDefs", [])
        if isinstance(d, dict) and d.get("id")
    })
    bodies: set[int] = set()
    # Keep ALL physical pads in the graph, including unassigned connector
    # pins and saved off-board leads. _terminals() intentionally lists only
    # assigned pins; previously a wire could run across an unassigned pad,
    # then fail the independent physical audit after routing had converged.
    unconnected_pad = "__UNASSIGNED_PAD__"
    for c in project.get("components", []):
        if not isinstance(c, dict):
            continue
        if is_off_board_component(c):
            if c.get("boardExcluded") is True and c.get("offBoard") is not True:
                continue
            for point in (c.get("leads") or {}).values():
                if isinstance(point, dict):
                    row, col = int(point["row"]), int(point["col"])
                    if 0 <= row < rows and 0 <= col < cols:
                        pin_net.setdefault(row * cols + col, unconnected_pad)
            continue
        if not isinstance(c.get("boardPos"), dict):
            continue
        definition = resolve_definition(c, definitions)
        if definition is None:
            raise ValueError(f"{c.get('label') or c.get('id')}: no footprint definition")
        all_pins, body_cells = component_geometry(c, definition)
        for pin in all_pins:
            row, col = int(pin["row"]), int(pin["col"])
            if 0 <= row < rows and 0 <= col < cols:
                pin_net.setdefault(row * cols + col, unconnected_pad)
        for row, col in body_cells:
            if 0 <= row < rows and 0 <= col < cols:
                bodies.add(row * cols + col)

    # The footprint bodyCells are NOT sufficient to describe drawn parts:
    # electrolytic capacitor cans and transistor bodies may have none.
    # A vertical jumper is legal only when EVERY crossed *gap* is clear.
    # Shared with independent quick_audit, so the graph and the checker
    # cannot silently disagree about an artwork obstruction.
    forbidden = vertical_gap_keepouts(project, rows, cols)
    vreach: dict[int, tuple[tuple[int, int], ...]] = {}
    for col in range(cols):
        start = 0
        for row in range(rows):
            if row != rows - 1 and (row, col) not in forbidden:
                continue
            # Connected run of clear vertical gaps, inclusive endpoints.
            for r in range(start, row + 1):
                hole = r * cols + col
                vreach[hole] = tuple(
                    (rr * cols + col, abs(rr-r))
                    for rr in range(start, row + 1) if rr != r
                )
            start = row + 1
    return rows, cols, bodies, pin_net, {n: sorted(s) for n, s in nets.items()}, vreach


def _route_net(
    net: str,
    terminals: list[int],
    rows: int,
    cols: int,
    pin_net: dict[int, str],
    vreach: dict[int, tuple[tuple[int, int], ...]],
    claims: dict[int, set[str]],
    endpoints: dict[int, set[str]],
    historical: dict[int, float],
    present: float,
    expansions_left: list[int],
) -> tuple[dict | None, str | None]:
    nodes = {terminals[0]}
    tree = {terminals[0]}
    ends: set[int] = set()
    wires: list[tuple[int, int]] = []
    remaining = set(terminals[1:])
    while remaining:
        # State low bit indicates arrival by a jumper: immediately chaining
        # jumper-to-jumper is forbidden. Every existing endpoint seeds flagged.
        seeds = {hole * 2 + int(hole in ends) for hole in tree}
        heap = [(0.0, state) for state in sorted(seeds)]
        heapq.heapify(heap)
        distance = {state: 0.0 for state in seeds}
        predecessor: dict[int, tuple[int, bool]] = {}
        hit = None
        while heap:
            cost, state = heapq.heappop(heap)
            if cost > distance.get(state, float("inf")):
                continue
            expansions_left[0] -= 1
            if expansions_left[0] < 0:
                return None, "EXPANSION_BUDGET"
            hole, arrived_by_jump = divmod(state, 2)
            if hole in remaining:
                hit = state
                break
            row, col = divmod(hole, cols)
            neighbours = []
            if col:
                neighbours.append((hole - 1, False, 0))
            if col + 1 < cols:
                neighbours.append((hole + 1, False, 0))
            if not arrived_by_jump and hole not in ends:
                neighbours.extend((target, True, length) for target, length in vreach.get(hole, ())
                                  if target not in ends)
            for other, jump, length in neighbours:
                if other in pin_net and pin_net[other] != net:
                    continue
                if jump:
                    # Also exclude wires that traverse *intermediate* pad holes,
                    # not merely incompatible jumper endpoints.
                    arow, brow = sorted((row, other // cols))
                    if any((rr * cols + col) in pin_net
                           for rr in range(arow + 1, brow)):
                        continue
                foreign = len(claims.get(other, set()) - {net})
                step = 1.0 + present * foreign + historical.get(other, 0.0)
                if jump:
                    # Penalize expensive long wires and shared endpoint claims.
                    conflicts = len(endpoints.get(other, set()) - {net})
                    conflicts += len(endpoints.get(hole, set()) - {net})
                    step += 8.0 + 0.25 * length + present * 4.0 * conflicts
                next_state = 2 * other + int(jump)
                candidate = cost + step
                if candidate < distance.get(next_state, float("inf")):
                    distance[next_state] = candidate
                    predecessor[next_state] = (state, jump)
                    heapq.heappush(heap, (candidate, next_state))
        if hit is None:
            return None, "UNREACHABLE"
        cursor = hit
        path_nodes = {cursor // 2}
        path_wires = []
        while cursor not in seeds:
            if cursor not in predecessor:
                return None, "BROKEN_PREDECESSOR"
            previous, jump = predecessor[cursor]
            source, target = previous // 2, cursor // 2
            path_nodes.add(source)
            if jump:
                if source in ends or target in ends:
                    return None, "DUPLICATE_ENDPOINT"
                path_wires.append((source, target))
            cursor = previous
        for source, target in path_wires:
            ends.update((source, target))
        wires.extend(path_wires)
        nodes.update(path_nodes)
        tree.update(path_nodes)
        remaining.difference_update(tree)
    return {"nodes": nodes, "ends": ends, "wires": wires}, None


def _derive(rows: int, cols: int, trees: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    labels: dict[int, str] = {}
    for net, tree in trees.items():
        for hole in tree["nodes"]:
            other = labels.get(hole)
            if other is not None and other != net:
                raise ValueError(f"overlapping net ownership: {other} and {net}")
            labels[hole] = net
    cuts = []
    for row in range(rows):
        anchors = [(col, labels[row * cols + col]) for col in range(cols)
                   if row * cols + col in labels]
        for (left, one), (right, two) in zip(anchors, anchors[1:]):
            if one != two:
                # One boundary per net-label change; do not fragment free tails.
                cuts.append({"row": row, "col": left, "kind": "between"})
    pairs = sorted((min(a, b), max(a, b)) for tree in trees.values() for a, b in tree["wires"])
    wires = [
        {"id": f"RM-W{i:03d}",
         "from": {"row": a // cols, "col": a % cols},
         "to": {"row": b // cols, "col": b % cols}}
        for i, (a, b) in enumerate(pairs, 1)
    ]
    return cuts, wires


def route_holes(
    project: Any,
    *,
    iterations: int = 24,
    expansion_budget: int = 600000,
) -> dict[str, Any]:
    """Route a clean placed board with negotiated hole ownership.

    A ROUTED status is issued only after independent electrical, quick-geometry,
    and physical grid audits. Physical-envelope and tool-access certification
    require measurements and remain explicitly unverified.
    """
    if not (1 <= iterations <= 100):
        raise ValueError("iterations must be between 1 and 100")
    if not (1000 <= expansion_budget <= 10000000):
        raise ValueError("expansion_budget must be between 1000 and 10000000")
    if not isinstance(project, dict) or not isinstance(project.get("board"), dict):
        return _result("INVALID_INPUT", project, ["project must contain a board"])
    board = project["board"]
    # Never erase manual routing. The original router remains responsible
    # for incremental routing, until a fixed-resource graph is implemented.
    if board.get("cuts") or board.get("wires"):
        return _result("FIXED_ROUTING_UNSUPPORTED", project, [
            "hole-graph routing requires empty cuts/wires; use route_copper for pre-routed boards"
        ])
    try:
        rows, cols, bodies, pin_net, nets, vreach = _static(project)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return _result("INVALID_INPUT", project, [str(exc)])

    # At most 24 iterations of total rip-up and reroute, not 24 costly
    # independent router invocations. Every net remains deterministically ordered.
    names = sorted(nets, key=lambda n: (-len(nets[n]), n))
    claim: dict[int, set[str]] = defaultdict(set)
    used_ends: dict[int, set[str]] = defaultdict(set)
    history: dict[int, float] = defaultdict(float)
    trees: dict[str, dict] = {}
    present = 0.6
    budget = [expansion_budget]
    over: list[int] = []
    shared_ends: list[int] = []
    first_failure = None
    for attempt in range(iterations):
        failed = False
        for net in names:
            previous = trees.get(net)
            if previous:
                for hole in previous["nodes"]:
                    claim[hole].discard(net)
                for hole in previous["ends"]:
                    used_ends[hole].discard(net)
            routed, reason = _route_net(
                net, nets[net], rows, cols, pin_net, vreach, claim,
                used_ends, history, present, budget,
            )
            if routed is None:
                failed = True
                first_failure = {"net": net, "reason": reason}
                # Restore the old route before reporting failure.
                if previous:
                    for hole in previous["nodes"]:
                        claim[hole].add(net)
                    for hole in previous["ends"]:
                        used_ends[hole].add(net)
                break
            trees[net] = routed
            for hole in routed["nodes"]:
                claim[hole].add(net)
            for hole in routed["ends"]:
                used_ends[hole].add(net)
        if failed:
            break
        over = sorted(hole for hole, owners in claim.items() if len(owners) > 1)
        shared_ends = sorted(hole for hole, owners in used_ends.items() if len(owners) > 1)
        if not over and not shared_ends:
            try:
                cuts, wires = _derive(rows, cols, trees)
                output = copy.deepcopy(project)
                output["board"]["cuts"] = cuts
                output["board"]["wires"] = wires
                electrical = verify_project(output)
                quick = quick_audit(output)
                physical = audit_project(output)
            except (ValueError, KeyError, TypeError) as exc:
                return _result("VERIFICATION_FAILED", project, [str(exc)])
            if (electrical["status"] == "PASS"
                    and quick["status"] != "FAIL"
                    and physical["status"] == "PASS"):
                return {
                    "status": "ROUTED", "project": output, "errors": [],
                    "warnings": [
                        "Measured jumper envelopes and cut-tool accessibility are not verified."
                    ], "cuts_added": len(cuts), "wires_added": len(wires),
                    "verification": electrical, "quick_audit": quick,
                    "physical_audit": physical,
                    "hole_search": {
                        "iterations": attempt + 1,
                        "expansions": expansion_budget - budget[0],
                        "congested_holes": 0,
                    },
                }
            return {
                **_result("VERIFICATION_FAILED", project,
                          electrical.get("errors", []) + quick.get("errors", [])
                          + physical.get("errors", [])
                          + physical.get("physical_jumper_audit", {}).get("errors", [])),
                "verification": electrical, "quick_audit": quick, "physical_audit": physical,
                "hole_search": {"iterations": attempt + 1, "expansions": expansion_budget - budget[0]},
            }
        for hole in set(over + shared_ends):
            history[hole] += 0.5
        present = min(present * 1.4, 128.0)
        # Nets causing most conflict go first next iteration, stable order.
        names = sorted(nets, key=lambda n: (
            -sum(hole in trees[n]["nodes"] for hole in over) if n in trees else 0,
            -len(nets[n]), n,
        ))
    diagnostic = {
        "iterations": attempt + 1,
        "expansions": expansion_budget - budget[0],
        "budget_exhausted": budget[0] < 0,
        "first_failure": first_failure,
        "overused_holes": [
            {"row": h // cols, "col": h % cols, "nets": sorted(claim[h])}
            for h in over[:24]
        ],
        "shared_endpoints": [
            {"row": h // cols, "col": h % cols} for h in shared_ends[:24]
        ],
    }
    error = ("net " + first_failure["net"] + ": " + first_failure["reason"]
             if first_failure else "Negotiated congestion did not converge within iteration budget.")
    return _result("BUDGET_EXHAUSTED", project, [error], hole_search=diagnostic)


__all__ = ["route_holes"]
