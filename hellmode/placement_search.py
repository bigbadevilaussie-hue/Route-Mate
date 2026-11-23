"""Hell Mode alpha: movable-component relocation with affected-net rebuilding.

This is a *candidate generator*. It uses the shared normative component
footprint/lock model and independent pad/electrical/score callbacks supplied
by the caller, but imports no independent verifier implementation itself.

One transaction relocates the component without touching Quick Solve.
All nets attached to the moved component are then completely rebuilt using
the existing strip-island router. The invalid intermediate layout is never
emitted or accepted: only a completed, dual-electrical-verified candidate
can compete for the exploratory best. No 2.5D or cut-access PASS is claimed.
"""
from __future__ import annotations

import copy
import random
from collections import Counter, defaultdict
from typing import Any, Callable, Mapping

from placement_policy import is_off_board_component
from .incremental_state import TransactionalState
from .net_ripup import rebuild_one_net
from .conflict_repair import _score


Project = dict[str, Any]
PadReader = Callable[[Project], dict[str, Any]]
ElectricalCheck = Callable[[Project], bool]
MetricReader = Callable[[Project], dict[str, Any]]
QualityKey = Callable[[dict[str, Any]], tuple]


def _eligible(component: dict[str, Any]) -> bool:
    return (
        isinstance(component.get("boardPos"), dict)
        and not is_off_board_component(component)
        and not any(component.get(flag) for flag in (
            "locked", "edge", "edgeLocked", "slide"
        ))
    )


def _no_footprint_overlap(
    state: TransactionalState, moved_id: str,
) -> bool:
    """Hard 2D pad/body exclusion for the newly moved package.

    The physical 2.5D verifier remains separate. New pads may not occupy
    another component's hole or body cell, regardless of net ownership.
    """
    own_pad = {
        (row, col) for row, col, _ in state._component_pads[moved_id]
    }
    own_body = set(state._component_bodies[moved_id])
    if own_pad & own_body:
        return False
    for cid, pads in state._component_pads.items():
        if cid == moved_id:
            continue
        pad_holes = {(row, col) for row, col, _ in pads}
        body = set(state._component_bodies[cid])
        if own_pad & (pad_holes | body):
            return False
        if own_body & (pad_holes | body):
            return False
    return True


def move_and_rebuild(
    source: Project,
    component_id: str,
    row: int,
    col: int,
    *,
    wire_nets: Mapping[str, str],
    pad_reader: PadReader,
    electrical_check: ElectricalCheck,
    seed: int = 1,
    max_extra_wires: int = 4,
) -> Project | None:
    """Try one *atomic* placement+multi-net repair; None means veto.

    A pad may move across copper islands; the electrical state is allowed
    to be temporarily open while rebuilding every affected net. Foreign
    nets are never re-labelled; final correctness is independently proven.
    """
    if not electrical_check(source):
        raise ValueError("relocation requires a verified electrical baseline")
    components = {
        str(c["id"]): c for c in source.get("components", [])
        if isinstance(c, dict) and c.get("id") is not None
    }
    original = components.get(component_id)
    if original is None:
        raise KeyError(component_id)
    if not _eligible(original):
        return None
    assigned = {
        str(a["netId"]) for a in source.get("netAssignments", [])
        if str(a.get("componentId")) == component_id
        and a.get("netId") is not None
    }
    if not assigned:
        return None

    # Use a transactional state to keep the initial source immutable.
    state = TransactionalState(source)
    with state.transaction() as tx:
        try:
            tx.move_component(component_id, row, col)
        except ValueError:
            return None
        if not _no_footprint_overlap(state, component_id):
            return None
        moved = state.snapshot()
        # Automatic rollback; partial moved states are not persisted.

    new_pad_state = pad_reader(moved)
    if new_pad_state.get("errors"):
        return None
    pads = new_pad_state["pads"]
    if not isinstance(pads, list):
        return None

    working = moved
    ownership = dict(wire_nets)
    # Rebuild each affected net. A zero-wire net can acquire a new bridge
    # when a terminal is shifted onto a different copper row.
    for order, net in enumerate(sorted(assigned)):
        old_wires = working["board"].get("wires", [])
        candidate = rebuild_one_net(
            working, net, pads=pads, wire_nets=ownership,
            seed=seed + order * 104729,
            max_additional_wires=max_extra_wires,
            allow_new_net_wires=True,
        )
        if candidate is None:
            # Do not accept a half-rebuilt intermediate layout.
            return None
        previous_ids = {w["id"] for w in old_wires}
        next_ownership = {}
        for w in candidate["board"]["wires"]:
            wid = w["id"]
            if wid not in previous_ids:
                next_ownership[wid] = net
            elif wid in ownership:
                next_ownership[wid] = ownership[wid]
            else:
                return None  # missing ownership is not a free permission
        ownership = next_ownership
        working = candidate

    if not electrical_check(working):
        return None
    # Hard invariants: preserve all board dimensions, cuts, and every other
    # component byte-for-byte, including locks, offboard leads and packages.
    for field in ("rows", "cols", "cuts"):
        if working["board"][field] != source["board"][field]:
            return None
    for c in working["components"]:
        if c["id"] != component_id and c != components[c["id"]]:
            return None
    return working


def search_component_moves(
    source: Project,
    *,
    wire_nets: Mapping[str, str],
    pad_reader: PadReader,
    electrical_check: ElectricalCheck,
    metric_reader: MetricReader,
    quality_key: QualityKey,
    attempts: int = 24,
    seed: int = 1,
) -> tuple[Project, dict[str, Any]]:
    """Search placements and output only strictly better electrical candidates."""
    if type(attempts) is not int or attempts < 0:
        raise ValueError("attempts must be a nonnegative integer")
    if not electrical_check(source):
        raise ValueError("component search requires electrical PASS baseline")
    rng = random.Random(seed)
    baseline = metric_reader(source)
    winner = copy.deepcopy(source)
    best_key = quality_key(baseline)
    proof = {
        "attempts": 0,
        "successful_rebuilds": 0,
        "independently_verified_moves": 0,
        "accepted_component_moves": 0,
        "attempted_component_ids": [],
        "accepted_moves": [],
        "record_eligible": False,
        "physical_pass": False,
    }
    if attempts == 0:
        return winner, proof

    pad_state = pad_reader(source)
    if pad_state.get("errors"):
        return winner, proof

    # Prioritise movable components electrically attached to the most
    # congested wires. This changes the *electrical topology* without
    # moving an unrelated part simply because it has empty space.
    _, by_wire = _score(
        source["board"]["wires"], pad_state["pads"], dict(wire_nets)
    )
    by_net: Counter[str] = Counter()
    for wid, penalty in by_wire.items():
        net = wire_nets.get(wid)
        if net is not None:
            by_net[net] += penalty
    part_nets: dict[str, set[str]] = defaultdict(set)
    for assignment in source.get("netAssignments", []):
        if assignment.get("netId") is not None:
            part_nets[str(assignment["componentId"])].add(
                str(assignment["netId"])
            )
    eligible = [
        c for c in source.get("components", [])
        if _eligible(c) and part_nets.get(str(c["id"]))
    ]
    eligible.sort(key=lambda component: (
        -sum(by_net[n] for n in part_nets[str(component["id"])]),
        str(component["id"]),
    ))
    eligible = eligible[:20]
    if not eligible:
        return winner, proof

    # Each individual proposal begins from the *same* independently
    # verified input; the search does not silently retain partial moves.
    offsets = [
        (dr, dc)
        for dr in range(-3, 4)
        for dc in range(-3, 4)
        if (dr, dc) != (0, 0) and abs(dr) + abs(dc) <= 4
    ]
    proposals = []
    for c in eligible:
        r, col = c["boardPos"]["row"], c["boardPos"]["col"]
        for dr, dc in offsets:
            proposals.append((str(c["id"]), r + dr, col + dc))
    rng.shuffle(proposals)
    # Combine randomized diversity with a predictable bound.
    for cid, row, col in proposals[:attempts]:
        proof["attempts"] += 1
        proof["attempted_component_ids"].append(cid)
        candidate = move_and_rebuild(
            source, cid, row, col,
            wire_nets=wire_nets, pad_reader=pad_reader,
            electrical_check=electrical_check,
            seed=rng.randrange(2**31),
        )
        if candidate is None:
            continue
        proof["successful_rebuilds"] += 1
        metrics = metric_reader(candidate)
        if not metrics["electrical_pass"]:
            continue
        proof["independently_verified_moves"] += 1
        key = quality_key(metrics)
        if key < best_key:
            winner = candidate
            best_key = key
            proof["accepted_component_moves"] += 1
            proof["accepted_moves"].append({
                "component_id": cid,
                "boardPos": {"row": row, "col": col},
                "wires": metrics["wires"],
                "excess_gap_occupancy": metrics["excess_gap_occupancy"],
            })
    return winner, proof


__all__ = ["move_and_rebuild", "search_component_moves"]
