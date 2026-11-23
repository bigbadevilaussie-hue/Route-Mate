"""Whole-net jumpers rip-up/rebuild for Hell Mode exploratory routing.

Unlike one-/two-jumper rebridging, this operator can replace an entire net's
jumper tree. It searches cut-defined copper-island paths through clean
vertical slots, including unassigned copper islands as Steiner waypoints.

NO verifier imports. Every candidate is untrusted until the caller applies
independent electrical and STRICT-2D checks. We do not claim body clearance,
measured 2.5D evidence, cut-tool access, RECORD or BUILD_READY.
"""
from __future__ import annotations

import copy
import hashlib
import heapq
import random
from collections import Counter, defaultdict
from typing import Any, Callable, Mapping

from .topology_moves import StripSegments
from .conflict_repair import _score


def _occupied(wires: list[dict[str, Any]], pads: list[dict[str, Any]]):
    """Rebuild fast hard 2D occupancy masks from other-net wires."""
    gap, landing, interior = set(), set(), set()
    for w in wires:
        a, b = w["from"], w["to"]
        if a["col"] != b["col"] or a["row"] == b["row"]:
            raise ValueError("net rip-up requires vertical nonzero jumpers")
        col = a["col"]
        lo, hi = sorted((a["row"], b["row"]))
        gap.update((col, row) for row in range(lo, hi))
        landing.add((col, lo))
        landing.add((col, hi))
        interior.update((col, row) for row in range(lo + 1, hi))
    pads_by_hole: dict[tuple[int, int], list[str | None]] = defaultdict(list)
    for p in pads:
        pads_by_hole[(p["col"], p["row"])].append(p.get("net_id"))
    return gap, landing, interior, pads_by_hole


def _is_clear(
    a_row: int, b_row: int, col: int, net: str,
    gap: set[tuple[int, int]],
    landing: set[tuple[int, int]],
    interior: set[tuple[int, int]],
    pads: Mapping[tuple[int, int], list[str | None]],
    *,
    allow_stack_penalty: bool = False,
) -> bool:
    if a_row == b_row:
        return False
    low, high = sorted((a_row, b_row))
    if not allow_stack_penalty and any(
        (col, row) in gap for row in range(low, high)
    ):
        return False
    if any((col, row) in landing or (col, row) in interior
           for row in (a_row, b_row)):
        return False
    if any((col, row) in landing for row in range(low + 1, high)):
        return False
    if any((col, row) in pads for row in range(low + 1, high)):
        return False
    for row in (a_row, b_row):
        owners = pads.get((col, row), ())
        if owners and any(owner != net for owner in owners):
            return False
    return True


def rebuild_one_net(
    project: dict[str, Any],
    target_net: str,
    *,
    pads: list[dict[str, Any]],
    wire_nets: Mapping[str, str],
    seed: int = 1,
    max_additional_wires: int = 4,
    allow_new_net_wires: bool = False,
    allow_stack_penalty: bool = False,
) -> dict[str, Any] | None:
    """Find a nonstacking replacement for ALL jumpers on a named net.

    Returns a pure project candidate (or None if the greedy tree fails).
    Other-net wires/cuts/placements remain untouched. Default output has
    STRICT 2D clean new spans. In exploratory allow_stack_penalty mode,
    gap crossings are charged a heavy weight rather than excluded, but
    prohibited pin pass-through and jumper landing conflicts stay blocked.
    These candidates are NEVER certified by the router.
    """
    original_board = project["board"]
    model = StripSegments(original_board)
    old_ids = [
        w["id"] for w in original_board["wires"]
        if wire_nets.get(w["id"]) == target_net
    ]
    if not old_ids and not allow_new_net_wires:
        return None
    others = [
        w for w in original_board["wires"] if w["id"] not in old_ids
    ]
    gap, landing, interior, pads_by_hole = _occupied(others, pads)
    rng = random.Random(seed)

    # Cut-islands owned by each net: never attach a new endpoint to an
    # island containing another net's terminal, even if the physical
    # destination hole itself is empty.
    segment_nets: dict[int, set[str]] = defaultdict(set)
    for pad in pads:
        if pad.get("net_id") is not None:
            idx = model.island(pad)
            segment_nets[idx].add(pad["net_id"])
    for wire in others:
        net = wire_nets.get(wire["id"])
        if net is not None:
            segment_nets[model.island(wire["from"])].add(net)
            segment_nets[model.island(wire["to"])].add(net)

    # Account for paths through all existing other-net connections.
    parent = list(range(len(model.segments)))
    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(i: int, j: int) -> None:
        i, j = find(i), find(j)
        if i != j:
            parent[max(i, j)] = min(i, j)
    for wire in others:
        union(model.island(wire["from"]), model.island(wire["to"]))
    groups: dict[int, set[str]] = defaultdict(set)
    for sid, ownership in segment_nets.items():
        groups[find(sid)].update(ownership)
    allowed = {
        sid for sid in range(len(model.segments))
        if not groups[find(sid)] or groups[find(sid)] == {target_net}
    }
    terminals = {
        model.island(pad) for pad in pads
        if pad.get("net_id") == target_net
    }
    if not terminals or not terminals <= allowed:
        return None

    # Build strict 2D clear vertical candidate edges from holes, not
    # router-provided wire/net labels. Candidate scan ~24*24*56, cheap
    # compared with independent full electrical verification.
    edges: dict[int, list[tuple[float, int, int, int]]] = defaultdict(list)
    for col in range(model.cols):
        for low in range(model.rows):
            sid = model.hole_segment[low][col]
            if sid not in allowed:
                continue
            for high in range(low + 1, model.rows):
                tid = model.hole_segment[high][col]
                if tid not in allowed or find(sid) == find(tid):
                    continue
                if not _is_clear(
                    low, high, col, target_net,
                    gap, landing, interior, pads_by_hole,
                    allow_stack_penalty=allow_stack_penalty,
                ):
                    continue
                overlap = sum(
                    (col, row) in gap for row in range(low, high)
                ) if allow_stack_penalty else 0
                # Number of wires first, then length, with seeded jitter
                # to explore multiple electrically equivalent trees.
                weight = (
                    200.0 + 2.0 * (high - low)
                    + rng.random() * 70 + 450.0 * overlap
                )
                edges[sid].append((weight, tid, col, high))
                edges[tid].append((weight, sid, col, low))

    # Each group is a node in the network. Merge aliases (other-net wires)
    # for path computation; no target nets are joined to foreign groups.
    group_edges: dict[int, list[tuple[float, int, int, int, int]]] = defaultdict(list)
    for sid, candidates in edges.items():
        for weight, tid, col, to_row in candidates:
            a, b = find(sid), find(tid)
            if a == b:
                continue
            # sid's row is always the endpoint row for this edge.
            group_edges[a].append((
                weight, b, model.segments[sid].row, to_row, col
            ))
    target_groups = {find(sid) for sid in terminals}
    if len(target_groups) == 1:
        result = copy.deepcopy(project)
        result["board"]["wires"] = others
        return result

    connected = {min(target_groups)}
    rebuilt: list[dict[str, Any]] = []
    used_ids = {w["id"] for w in others}
    max_total = len(old_ids) + max_additional_wires
    while not target_groups <= connected:
        # Dijkstra from the current connected tree to a disconnected
        # terminal group. Other unowned copper segments are Steiner nodes.
        frontier = [(0.0, node) for node in sorted(connected)]
        heapq.heapify(frontier)
        best_dist = {node: 0.0 for node in connected}
        predecessor: dict[int, tuple[int, int, int, int]] = {}
        endpoint: int | None = None
        while frontier:
            distance, here = heapq.heappop(frontier)
            if distance > best_dist.get(here, float("inf")) + 1e-9:
                continue
            if here in target_groups and here not in connected:
                endpoint = here
                break
            for cost, nxt, r1, r2, col in group_edges[here]:
                if nxt in connected:
                    continue
                if not _is_clear(
                    r1, r2, col, target_net,
                    gap, landing, interior, pads_by_hole,
                    allow_stack_penalty=allow_stack_penalty,
                ):
                    continue
                trial = distance + cost
                if trial + 1e-9 < best_dist.get(nxt, float("inf")):
                    best_dist[nxt] = trial
                    predecessor[nxt] = (here, r1, r2, col)
                    heapq.heappush(frontier, (trial, nxt))
        if endpoint is None:
            return None
        route: list[tuple[int, int, int, int]] = []
        node = endpoint
        while node not in connected:
            if node not in predecessor:
                return None
            earlier, r1, r2, col = predecessor[node]
            route.append((r1, r2, col, node))
            node = earlier
        route.reverse()
        if len(rebuilt) + len(route) > max_total:
            return None
        for r1, r2, col, node in route:
            if not _is_clear(
                r1, r2, col, target_net,
                gap, landing, interior, pads_by_hole,
                allow_stack_penalty=allow_stack_penalty,
            ):
                return None
            index = len(rebuilt)
            if index < len(old_ids):
                ident = old_ids[index]
            else:
                if old_ids:
                    name_base = f"{old_ids[0]}-R{index + 1}"
                else:
                    digest = hashlib.sha256(
                        target_net.encode("utf-8")
                    ).hexdigest()[:12]
                    name_base = f"HM-NET-{digest}-R{index + 1}"
                ident = name_base
                suffix = 1
                while ident in used_ids:
                    ident = f"{name_base}-{suffix}"
                    suffix += 1
            used_ids.add(ident)
            rebuilt.append({
                "id": ident,
                "from": {"row": r1, "col": col},
                "to": {"row": r2, "col": col},
            })
            low, high = sorted((r1, r2))
            gap.update((col, row) for row in range(low, high))
            landing.add((col, low))
            landing.add((col, high))
            interior.update((col, row) for row in range(low + 1, high))
            connected.add(node)
    result = copy.deepcopy(project)
    result["board"]["wires"] = others + rebuilt
    return result


def ripup_repair(
    project: dict[str, Any],
    *,
    pads: list[dict[str, Any]],
    wire_nets: Mapping[str, str],
    electrical_check: Callable[[dict[str, Any]], bool],
    attempts: int = 20,
    seed: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Try whole-net rip-up and accept strictly better verified candidates."""
    if type(attempts) is not int or attempts < 0:
        raise ValueError("attempts must be nonnegative integer")
    if not electrical_check(project):
        raise ValueError("rip-up requires an electrically verified baseline")
    work = copy.deepcopy(project)
    rng = random.Random(seed)
    verified = 0
    improved = 0
    proposed = 0
    chosen_nets: list[str] = []

    for _ in range(attempts):
        metric, per_wire = _score(
            work["board"]["wires"], pads, dict(wire_nets)
        )
        wire_badness: Counter[str] = Counter()
        for wid, value in per_wire.items():
            net = wire_nets.get(wid)
            if net:
                wire_badness[net] += value
        if not wire_badness:
            break
        ranked_nets = sorted(
            wire_badness, key=lambda n: (-wire_badness[n], n)
        )
        # Prefer top congested nets, but sample enough to escape local traps.
        net = ranked_nets[rng.randrange(min(5, len(ranked_nets)))]
        candidate = rebuild_one_net(
            work, net, pads=pads, wire_nets=wire_nets,
            seed=rng.randrange(2**31), max_additional_wires=3,
        )
        if candidate is None or candidate == work:
            continue
        proposed += 1
        c_owners = dict(wire_nets)
        previous_ids = {w["id"] for w in work["board"]["wires"]}
        for w in candidate["board"]["wires"]:
            if w["id"] not in previous_ids:
                c_owners[w["id"]] = net
        new_metric, _ = _score(
            candidate["board"]["wires"], pads, c_owners
        )
        key = lambda s: (
            s.excess, s.illegal_holes, s.wire_count, s.total_length_holes
        )
        if key(new_metric) >= key(metric):
            continue
        if not electrical_check(candidate):
            continue
        verified += 1
        work = candidate
        wire_nets = {
            w["id"]: c_owners[w["id"]]
            for w in candidate["board"]["wires"] if w["id"] in c_owners
        }
        improved += 1
        chosen_nets.append(net)
    final, _ = _score(work["board"]["wires"], pads, dict(wire_nets))
    return work, {
        "proposals": proposed,
        "electrical_checks_passed": verified,
        "whole_net_reroutes_accepted": improved,
        "accepted_nets": chosen_nets,
        "remaining_excess": final.excess,
        "remaining_illegal_holes": final.illegal_holes,
        "physical_pass": False,
        "record_eligible": False,
    }


__all__ = ["rebuild_one_net", "ripup_repair"]
