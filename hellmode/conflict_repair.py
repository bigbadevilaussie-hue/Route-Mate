"""Conflict-directed 2D jumper repair search for Hell Mode alpha.

This is a routing-proposal engine. It does not import the independent electrical,
pin-geometry, strict-occupancy, or physical verifier modules. Scoring is based
on a separately implemented sparse 2D hole/gap occupancy model.

Every accepted reroute must be rechecked by the caller's *independent* dual
electrical verification. No physical pass/RECORD is asserted or implied.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable
import math
import random

from .topology_moves import StripSegments, apply_topology_proposal


@dataclass(frozen=True)
class RepairScore:
    excess: int
    shared_landing_holes: int
    endpoint_on_span_holes: int
    intermediate_pad_holes: int
    conflicting_pad_landings: int
    wire_count: int
    total_length_holes: int

    @property
    def illegal_holes(self) -> int:
        return (self.shared_landing_holes + self.endpoint_on_span_holes
                + self.intermediate_pad_holes + self.conflicting_pad_landings)

    @property
    def objective(self) -> tuple[int, int, int, int, int]:
        # One illegal hole veto counts at least as heavily as a modest
        # congestion improvement; all illegal geometry must eventually reach 0.
        return (
            8 * self.illegal_holes + self.excess,
            self.illegal_holes,
            self.excess,
            self.wire_count,
            self.total_length_holes,
        )


def _occupancies(
    wires: list[dict[str, Any]],
) -> tuple[Counter, Counter, Counter, dict[str, Counter]]:
    gap: Counter[tuple[int, int]] = Counter()
    end: Counter[tuple[int, int]] = Counter()
    middle: Counter[tuple[int, int]] = Counter()
    wire_gaps: dict[str, Counter] = {}
    for w in wires:
        a, b = w["from"], w["to"]
        if a["col"] != b["col"] or a["row"] == b["row"]:
            raise ValueError("strict repair only accepts vertical, nonzero jumper spans")
        lo, hi = sorted((a["row"], b["row"]))
        col = a["col"]
        keys = Counter((col, row) for row in range(lo, hi))
        gap.update(keys)
        end[(col, lo)] += 1
        end[(col, hi)] += 1
        for row in range(lo + 1, hi):
            middle[(col, row)] += 1
        wire_gaps[w["id"]] = keys
    return gap, end, middle, wire_gaps


def _score(
    wires: list[dict[str, Any]],
    pads: list[dict[str, Any]],
    ownership: dict[str, str],
) -> tuple[RepairScore, dict[str, int]]:
    gaps, landings, through, contributions = _occupancies(wires)
    pad_by_hole: dict[tuple[int, int], list[str | None]] = defaultdict(list)
    for pad in pads:
        pad_by_hole[(pad["col"], pad["row"])].append(pad.get("net_id"))
    pad_landing_conflicts = 0
    for w in wires:
        net = ownership.get(w["id"])
        for point in (w["from"], w["to"]):
            occupied = pad_by_hole.get((point["col"], point["row"]), ())
            if occupied and (net is None or any(x is None or x != net for x in occupied)):
                pad_landing_conflicts += 1
    shared = sum(1 for n in landings.values() if n > 1)
    endpoint_on_span = sum(
        1 for key in landings if through.get(key, 0) > 0
    )
    pass_pin = sum(
        1 for key in through if key in pad_by_hole
    )
    excess = sum(max(0, n - 1) for n in gaps.values())
    length = sum(abs(w["to"]["row"] - w["from"]["row"]) for w in wires)
    badness = {
        wid: sum(max(0, gaps[key] - 1) for key in crossed)
        for wid, crossed in contributions.items()
    }
    for w in wires:
        ident = w["id"]
        col = w["from"]["col"]
        lo, hi = sorted((w["from"]["row"], w["to"]["row"]))
        for row in (lo, hi):
            key = (col, row)
            if landings.get(key, 0) > 1 or through.get(key, 0) > 0:
                badness[ident] += 8
            pad_nets = pad_by_hole.get(key, ())
            if pad_nets and (ownership.get(ident) is None or any(
                x is None or x != ownership[ident] for x in pad_nets
            )):
                badness[ident] += 8
        if any((col, row) in pad_by_hole for row in range(lo + 1, hi)):
            badness[ident] += 8
    return RepairScore(
        excess=excess,
        shared_landing_holes=shared,
        endpoint_on_span_holes=endpoint_on_span,
        intermediate_pad_holes=pass_pin,
        conflicting_pad_landings=pad_landing_conflicts,
        wire_count=len(wires),
        total_length_holes=length,
    ), badness


def _paired_rebridge_candidates(
    board: dict[str, Any],
    model: StripSegments,
    target_ids: list[str],
    current: RepairScore,
    pads: list[dict[str, Any]],
    wire_nets: dict[str, str],
    rng: random.Random,
    samples: int,
) -> tuple[list[tuple[tuple, str, str, tuple[dict, dict], RepairScore]], int]:
    """Explore bounded simultaneous two-jumper topology changes.

    A two-jumper change may improve 2D packing when neither jumper has an
    individually improving rebridge. Nothing in the generator is trusted as
    electrical proof: the caller must validate the complete resulting board.
    """
    import itertools

    proposals = {}
    for wid in target_ids[:7]:
        candidates, essential = model.candidate_bridges(
            board, wid, allow_detour=False,
            max_candidates=min(samples, 32), rng=rng,
        )
        if essential:
            proposals[wid] = [p[0] for p in candidates if len(p) == 1]
    ranked = []
    evaluated = 0
    for a, b in itertools.combinations(sorted(proposals), 2):
        base = [w for w in board["wires"] if w["id"] not in (a, b)]
        for new_a in proposals[a]:
            for new_b in proposals[b]:
                if new_a["id"] == new_b["id"]:
                    continue
                trial_wires = base + [new_a, new_b]
                try:
                    score, _ = _score(trial_wires, pads, wire_nets)
                except ValueError:
                    continue
                evaluated += 1
                if score.objective[:3] < current.objective[:3]:
                    ranked.append((
                        score.objective, a, b, (new_a, new_b), score
                    ))
    ranked.sort(key=lambda item: (
        item[0], item[1], item[2],
        tuple((p["from"]["row"], p["from"]["col"],
               p["to"]["row"]) for p in item[3]),
    ))
    return ranked[:35], evaluated


def repair_conflicts(
    project: dict[str, Any],
    *,
    pads: list[dict[str, Any]],
    wire_nets: dict[str, str],
    electrical_check: Callable[[dict[str, Any]], bool],
    rounds: int = 6,
    candidates_per_wire: int = 80,
    seed: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Try conflict-directed topology reroutes, strictly decreasing 2D errors.

    All moves are whole-project copy-on-write; failed proposals never
    mutate the incoming project. Candidate ranking uses the private
    surrogate; each candidate to be ACCEPTED first passes electrical_check.
    An accepted candidate may remain strictly illegal; it is NOT a RECORD.
    """
    if type(rounds) is not int or rounds < 0:
        raise ValueError("rounds must be nonnegative integer")
    if type(candidates_per_wire) is not int or candidates_per_wire < 1:
        raise ValueError("candidates_per_wire must be positive integer")
    if not electrical_check(project):
        raise ValueError("repair requires a verified electrical starting point")
    import copy
    working = copy.deepcopy(project)
    rng = random.Random(seed)
    initial, _ = _score(working["board"]["wires"], pads, wire_nets)
    current = initial
    attempted = considered = committed = rejected_electrical = 0
    paired_accepted = 0
    history = []
    for round_no in range(rounds):
        board = working["board"]
        model = StripSegments(board)
        score, contributions = _score(board["wires"], pads, wire_nets)
        if score.excess == 0 and score.illegal_holes == 0:
            break
        target_ids = [
            wid for wid, value in sorted(
                contributions.items(), key=lambda x: (-x[1], x[0])
            ) if value > 0
        ]
        if not target_ids:
            break
        ranked: list[tuple[tuple, str, tuple[dict, ...], RepairScore]] = []
        for wire_id in target_ids[:24]:
            suggestions, essential = model.candidate_bridges(
                board, wire_id, allow_detour=(round_no % 3 == 2),
                max_candidates=candidates_per_wire, rng=rng,
            )
            if not essential:
                continue
            for replacement in suggestions:
                if len(replacement) == 2 and any(
                    extra["id"] in contributions for extra in replacement[1:]
                ):
                    continue
                new_wires = [
                    w for w in board["wires"] if w["id"] != wire_id
                ] + list(replacement)
                candidate_owners = dict(wire_nets)
                if len(replacement) == 2:
                    candidate_owners[replacement[1]["id"]] = wire_nets.get(wire_id, "")
                try:
                    proposed_score, _ = _score(
                        new_wires, pads, candidate_owners
                    )
                except ValueError:
                    continue
                considered += 1
                if proposed_score.objective[:3] >= current.objective[:3]:
                    continue
                # Stable ranking first (no false proxy for verified status).
                ranked.append((
                    proposed_score.objective,
                    wire_id,
                    replacement,
                    proposed_score,
                ))
        ranked.sort(key=lambda x: (x[0], x[1],
                                  tuple((w["from"]["row"],
                                         w["from"]["col"],
                                         w["to"]["row"]) for w in x[2])))
        change_made = False
        for _, wire_id, replacement, predicted in ranked[:40]:
            attempted += 1
            proposal = apply_topology_proposal(
                working, wire_id, replacement
            )
            if not electrical_check(proposal):
                rejected_electrical += 1
                continue
            # Independent verifier must be the acceptance authority for
            # electrical validity. The 2D surrogate remains a search guide.
            working = proposal
            if len(replacement) == 2:
                wire_nets = dict(wire_nets)
                wire_nets[replacement[1]["id"]] = wire_nets[wire_id]
            current = predicted
            committed += 1
            history.append({
                "round": round_no + 1,
                "changed_wire": wire_id,
                "replacement_wires": len(replacement),
                "excess_gap_occupancy": current.excess,
                "illegal_holes": current.illegal_holes,
            })
            change_made = True
            break
        if not change_made:
            # Coordinated repair can escape a single-wire local packing
            # minimum. It changes two independent bridge endpoints at once.
            paired, evaluated = _paired_rebridge_candidates(
                board, model, target_ids, current, pads, wire_nets, rng,
                candidates_per_wire,
            )
            considered += evaluated
            for _, first, second, replacements, predicted in paired:
                attempted += 1
                import copy
                trial = copy.deepcopy(working)
                trial["board"]["wires"] = [
                    w for w in board["wires"] if w["id"] not in (first, second)
                ] + [copy.deepcopy(w) for w in replacements]
                if not electrical_check(trial):
                    rejected_electrical += 1
                    continue
                working = trial
                current = predicted
                committed += 1
                paired_accepted += 1
                history.append({
                    "round": round_no + 1,
                    "changed_wire": f"{first}+{second}",
                    "replacement_wires": 2,
                    "excess_gap_occupancy": current.excess,
                    "illegal_holes": current.illegal_holes,
                })
                change_made = True
                break
        if not change_made:
            break
    return working, {
        "attempted_electrical_proofs": attempted,
        "scored_proposals": considered,
        "accepted_rebridges": committed,
        "paired_rebridges_accepted": paired_accepted,
        "electrically_rejected": rejected_electrical,
        "initial_excess": initial.excess,
        "final_excess": current.excess,
        "initial_illegal_holes": initial.illegal_holes,
        "final_illegal_holes": current.illegal_holes,
        "history": history,
        "physically_certified": False,
    }


__all__ = ["repair_conflicts", "RepairScore"]
