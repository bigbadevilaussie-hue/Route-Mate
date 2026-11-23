"""Runnable Hell Mode alpha: electrically verified, topology-changing search.

This is an EXPERIMENTAL CLI, not a finished Hell Mode GUI or certifier.
It can change jumper endpoint rows, rebridge nets through other copper islands,
replace a jumper with two via an unowned strip, and explore changes to copper
cuts. Component placement and independently certified 2.5D geometry are not
implemented. Quick Solve is never modified.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .incremental_state import TransactionalState
from .copper_model import reconstruct_electrical
from .verify_layout import verify_layout
from .topology_moves import topology_proposal, apply_topology_proposal
from .cut_moves import propose_cut_change, remove_redundant_cuts
from .conflict_repair import repair_conflicts
from .net_ripup import ripup_repair


PITCH_MM = 2.54


def wire_length_mm(project: dict[str, Any]) -> float:
    return round(sum(
        math.hypot(w["to"]["row"] - w["from"]["row"],
                   w["to"]["col"] - w["from"]["col"]) * PITCH_MM
        for w in project["board"].get("wires", [])
    ), 6)


def report_metrics(project: dict[str, Any]) -> dict[str, Any]:
    result = verify_layout(project)
    grid = result["strict_occupancy"]["counts"]
    return {
        "certification": result["status"],
        "electrical_pass": result["electrical"]["status"] == "PASS",
        "wires": len(project["board"].get("wires", [])),
        "cuts": len(project["board"].get("cuts", [])),
        "wire_length_mm": wire_length_mm(project),
        "stacked_gaps": grid["stacked_gaps"],
        "excess_gap_occupancy": grid["excess_gap_occupancy"],
        "max_stack_depth": grid["max_stack_depth"],
        "shared_holes": grid["shared_landing_holes"],
        "endpoint_on_span_holes": grid["endpoint_on_span_holes"],
        "pad_pass_through": grid["intermediate_pad_holes"],
        "pin_landing_conflicts": grid["landing_net_conflicts"]
            + grid["landing_net_unverified"],
        "reason_codes": result["reason_codes"],
        "record_eligible": result["record_eligible"],
        "physical_pass": result["physical_pass"],
        "cut_access": result["cut_access"],
    }


def _priority(m: dict[str, Any]) -> tuple:
    """Exploratory score only. NOT the tuple used for a certified RECORD."""
    return (
        m["excess_gap_occupancy"],
        m["shared_holes"] + m["endpoint_on_span_holes"]
            + m["pad_pass_through"] + m["pin_landing_conflicts"],
        m["wires"], m["cuts"], m["wire_length_mm"],
    )


def _energy(m: dict[str, Any]) -> float:
    return (
        10000 * m["excess_gap_occupancy"]
        + 2000 * (m["shared_holes"] + m["endpoint_on_span_holes"]
                  + m["pad_pass_through"] + m["pin_landing_conflicts"])
        + 100 * m["wires"] + 10 * m["cuts"]
        + m["wire_length_mm"] / 10
    )


def _same_copper_columns(
    board: dict[str, Any], row: int, col: int
) -> set[int]:
    """Cut-frozen row-domain enumeration; only between-hole cuts supported."""
    n = board["cols"]
    if not (0 <= col < n and 0 <= row < board["rows"]):
        return set()
    cuts = {(c["row"], c["col"]) for c in board.get("cuts", [])
            if c.get("kind", "between") == "between"}
    left = col
    while left > 0 and (row, left - 1) not in cuts:
        left -= 1
    right = col
    while right < n - 1 and (row, right) not in cuts:
        right += 1
    return set(range(left, right + 1))


def _relocate_candidate(
    project: dict[str, Any], rng: random.Random
) -> tuple[str, tuple[int, int], tuple[int, int]] | None:
    wires = project["board"].get("wires", [])
    if not wires:
        return None
    wire = rng.choice(wires)
    a, b = wire["from"], wire["to"]
    domains = _same_copper_columns(project["board"], a["row"], a["col"])
    domains &= _same_copper_columns(project["board"], b["row"], b["col"])
    domains.discard(a["col"])
    if not domains:
        return None
    col = rng.choice(sorted(domains))
    return wire["id"], (a["row"], col), (b["row"], col)


def _electrically_valid(project: dict[str, Any]) -> bool:
    # The new independent segment-graph must agree with the existing
    # non-router independent checker, with no physically unverified claims.
    from solve.verify import verify_project

    graph = reconstruct_electrical(project)
    if graph["status"] != "PASS":
        return False
    return verify_project(project)["status"] == "PASS"


def _prune_redundant(
    project: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Deterministically remove one wire at a time; verify after each deletion."""
    state = copy.deepcopy(project)
    removed = []
    for wire in list(state["board"]["wires"]):
        candidate = copy.deepcopy(state)
        candidate["board"]["wires"] = [
            w for w in candidate["board"]["wires"] if w["id"] != wire["id"]
        ]
        if _electrically_valid(candidate):
            state = candidate
            removed.append(wire["id"])
    return state, removed


def optimize(
    source: dict[str, Any], *, moves: int = 300, seed: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run a bounded, deterministic actual optimisation pass.

    Improvement is within the electrically verified exploratory tier;
    baseline never becomes a false full physical RECORD.
    """
    if moves < 0 or type(moves) is not int:
        raise ValueError("moves must be a nonnegative integer")
    original = copy.deepcopy(source)
    if not _electrically_valid(original):
        raise ValueError("saved baseline must independently pass electrical checks")
    rng = random.Random(seed)
    first = report_metrics(original)
    if not first["electrical_pass"]:
        raise ValueError("independent electrical model rejected baseline")

    current, removed = _prune_redundant(original)
    # A cut can be unnecessary *after* electrically redundant wires are
    # removed. Every deletion is independently checked, never assumed safe.
    current, removed_cuts = remove_redundant_cuts(
        current, _electrically_valid
    )
    best = copy.deepcopy(current)
    best_m = report_metrics(best)
    current_m = best_m
    history = [{"move": 0, "kind": "prune", **best_m}]
    attempts = accepted = rejected_electrical = no_alternative = 0
    topology_attempts = topology_accepted = detour_accepted = 0
    cut_attempts = cut_accepted = 0
    improvements = 0
    for index in range(1, moves + 1):
        candidate = None
        kind = "column"
        action = rng.randrange(5)
        if action == 0:
            cut_proposal = propose_cut_change(current, rng)
            if cut_proposal is not None:
                candidate, kind = cut_proposal
                cut_attempts += 1
        if candidate is None and action in (1, 2, 3):
            # Bridge net islands through changed row endpoints or a new
            # intermediate strip. All proposed changes remain subject to
            # both independent electrical validation implementations.
            proposal = topology_proposal(
                current, rng, detour=(rng.randrange(4) == 0)
            )
            if proposal is not None:
                replace_id, replacements = proposal
                candidate = apply_topology_proposal(
                    current, replace_id, replacements
                )
                kind = "detour" if len(replacements) == 2 else "rebridge"
                topology_attempts += 1
        if candidate is None:
            choice = _relocate_candidate(current, rng)
            if choice is None:
                no_alternative += 1
                continue
            wid, start, stop = choice
            # The M1 transactional primitive is still exercised for
            # same-span column proposals and must revert on context exit.
            txstate = TransactionalState(current)
            with txstate.transaction() as tx:
                tx.move_wire(wid, start, stop)
                candidate = txstate.snapshot()
        attempts += 1
        if not _electrically_valid(candidate):
            rejected_electrical += 1
            continue
        metrics = report_metrics(candidate)
        progress = (index - 1) / max(1, moves)
        temperature = max(1.0, 700.0 * (1.0 - progress))
        difference = _energy(metrics) - _energy(current_m)
        take = difference <= 0 or rng.random() < math.exp(
            -min(700.0, difference / temperature)
        )
        if take:
            current = candidate
            current_m = metrics
            accepted += 1
            if kind.startswith("cut_"):
                cut_accepted += 1
            elif kind != "column":
                topology_accepted += 1
                if kind == "detour":
                    detour_accepted += 1
            if _priority(metrics) < _priority(best_m):
                best = copy.deepcopy(candidate)
                best_m = metrics
                improvements += 1
                history.append({"move": index, "kind": kind, **best_m})

    # A bounded conflict-directed last pass searches topology alternatives
    # for wires actually occupying stacked gaps or illegal holes. This is
    # still an ELECTRICAL_ONLY exploratory search; the final state must
    # independently pass both electrical verifiers to be output.
    verified = reconstruct_electrical(best)
    repaired, repair = repair_conflicts(
        best, pads=verified["pin_holes"],
        wire_nets=verified["wire_nets"],
        electrical_check=_electrically_valid,
        seed=seed, rounds=10, candidates_per_wire=64,
    )
    repaired_m = report_metrics(repaired)
    repair["adopted"] = _priority(repaired_m) < _priority(best_m)
    if repair["adopted"]:
        best, best_m = repaired, repaired_m
        improvements += 1
        history.append({
            "move": moves, "kind": "conflict_repair", **best_m,
        })

    # Wider neighborhood: discard and rebuild all jumper bridges of an
    # electrically owned net, using clean nonstacking vertical paths through
    # original cut-defined copper islands. The operator is untrusted; its
    # candidates must pass both independent electrical checkers.
    for_ripup = reconstruct_electrical(best)
    rebuilt, reroute = ripup_repair(
        best, pads=for_ripup["pin_holes"],
        wire_nets=for_ripup["wire_nets"],
        electrical_check=_electrically_valid,
        attempts=min(10, max(2, moves // 25)),
        seed=seed + 104729,
    )
    reroute_m = report_metrics(rebuilt)
    reroute["adopted"] = _priority(reroute_m) < _priority(best_m)
    if reroute["adopted"]:
        best, best_m = rebuilt, reroute_m
        improvements += 1
        history.append({
            "move": moves, "kind": "whole_net_ripup", **best_m,
        })

    manifest = {
        "mode": "HELL_MODE_ALPHA_ELECTRICAL_ONLY",
        "seed": seed, "moves_requested": moves,
        "moves_proposed": attempts,
        "moves_topology_proposed": topology_attempts,
        "moves_topology_accepted": topology_accepted,
        "moves_two_wire_detours_accepted": detour_accepted,
        "moves_cut_proposed": cut_attempts,
        "moves_cut_accepted": cut_accepted,
        "conflict_repair": repair,
        "whole_net_ripup": reroute,
        "moves_with_column_alternative": attempts - topology_attempts - cut_attempts,
        "moves_accepted": accepted,
        "moves_electrically_rejected": rejected_electrical,
        "moves_without_alternative": no_alternative,
        "improvements": improvements,
        "redundant_wires_removed": removed,
        "redundant_cuts_removed": removed_cuts,
        "baseline": first, "best_exploratory": best_m,
        "baseline_preserved": True,
        "record_eligible": False,
        "physical_pass": False,
        "cut_access": "unverified",
        "note": (
            "Experimental deterministic annealing, one-wire topology "
            "rebridges (including changed endpoint rows), two-wire "
            "detours via unused strip islands, whole-net strip-island "
            "tree rebuilds, and electrically verified between-hole cut "
            "relocation/removal. Component placement stays fixed. "
            "No physical RECORD or BUILD_READY is claimed."
        ),
        "history": history,
    }
    return best, manifest


def optimize_portfolio(
    source: dict[str, Any], *, moves: int, seed: int, seeds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministic, fixed-effort independent restarts of the real search.

    Best-effort pilot of Hell Mode's broad search; not M4 multiprocessing
    or M1 deterministic full-solver acceptance. Score only within the same
    uncertified, electrically verified exploratory tier.
    """
    if type(seeds) is not int or seeds < 1:
        raise ValueError("seeds must be a positive integer")
    summaries = []
    winner = None
    winner_report = None
    winning_key = None
    for offset in range(seeds):
        actual_seed = seed + offset
        candidate, report = optimize(source, moves=moves, seed=actual_seed)
        m = report["best_exploratory"]
        key = (_priority(m), actual_seed)
        summaries.append({
            "seed": actual_seed,
            "wires": m["wires"],
            "cuts": m["cuts"],
            "excess_gap_occupancy": m["excess_gap_occupancy"],
            "max_stack_depth": m["max_stack_depth"],
            "moves_requested": moves,
            "moves_proposed": report["moves_proposed"],
            "moves_cut_accepted": report["moves_cut_accepted"],
            "moves_topology_accepted": report["moves_topology_accepted"],
        })
        if winning_key is None or key < winning_key:
            winner, winner_report, winning_key = (
                candidate, report, key
            )
    assert winner_report is not None and winner is not None
    winner_report["portfolio"] = {
        "start_seed": seed,
        "seeds_tested": seeds,
        "moves_per_seed": moves,
        "total_moves_requested": moves * seeds,
        "winning_seed": winner_report["seed"],
        "seeds": summaries,
    }
    return winner, winner_report


def run_files(
    input_path: Path, output_dir: Path, *, moves: int, seed: int, seeds: int = 1,
) -> dict:
    src = json.loads(input_path.read_text(encoding="utf-8"))
    best, manifest = optimize_portfolio(src, moves=moves, seed=seed, seeds=seeds)
    manifest["source"] = str(input_path)
    manifest["source_sha256"] = hashlib.sha256(
        input_path.read_bytes()
    ).hexdigest()
    manifest["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, body in (
        ("baseline_solved.json", src),
        ("best_electrical.json", best),
        ("run.json", manifest),
    ):
        target = output_dir / name
        target.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    with (output_dir / "history.csv").open("w", newline="", encoding="utf-8") as file:
        rows = manifest["history"]
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        for event in rows:
            writer.writerow(event)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=Path("benchmarks/moto/motomix-autorouted.json"))
    parser.add_argument("--out", type=Path, default=Path("/tmp/route-mate-hellmode-alpha"))
    parser.add_argument("--moves", type=int, default=300)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--seeds", type=int, default=1,
        help="independent deterministic search restarts; each gets --moves",
    )
    opts = parser.parse_args()
    report = run_files(
        opts.input, opts.out, moves=opts.moves, seed=opts.seed,
        seeds=opts.seeds,
    )
    before, after = report["baseline"], report["best_exploratory"]
    print(f"HELL MODE ALPHA — electrical-only search; {opts.seeds} seeds x {opts.moves} moves")
    print(f"  Winning seed: {report['portfolio']['winning_seed']}")
    print(f"  Verified redundant wires removed: {len(report['redundant_wires_removed'])}")
    print(f"  Search proposals/accepted: {report['moves_proposed']}/{report['moves_accepted']}")
    print(f"  Topology rebridges proposed/accepted: {report['moves_topology_proposed']}/{report['moves_topology_accepted']}")
    print(f"  Two-wire detours accepted: {report['moves_two_wire_detours_accepted']}")
    print(f"  Cut changes proposed/accepted: {report['moves_cut_proposed']}/{report['moves_cut_accepted']}")
    fix = report["conflict_repair"]
    print(f"  Conflict-directed repairs accepted: {fix['accepted_rebridges']} "
          f"(coordinated={fix['paired_rebridges_accepted']}, adopted={fix['adopted']})")
    net = report["whole_net_ripup"]
    print(f"  Whole-net reroutes accepted: {net['whole_net_reroutes_accepted']} "
          f"(adopted={net['adopted']})")
    print(f"  Jumper count: {before['wires']} -> {after['wires']}")
    print(f"  Cut count: {before['cuts']} -> {after['cuts']}")
    print(f"  Excess stacked gaps: {before['excess_gap_occupancy']} -> {after['excess_gap_occupancy']}")
    print(f"  Physical certification: NOT AVAILABLE (cut access and 2.5D unverified)")
    print(f"  Output: {opts.out}/run.json, best_electrical.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
