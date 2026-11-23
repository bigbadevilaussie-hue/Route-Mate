"""Runnable Hell Mode alpha: electrical-only route improvement on a solved board.

This intentionally tests a REAL search loop rather than claiming M1/M2 are
finished. No GUI, component placement, cut/topology edits, or physical
record certification yet. Quick Solve is never modified or invoked.
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
    best = copy.deepcopy(current)
    best_m = report_metrics(best)
    current_m = best_m
    history = [{"move": 0, "kind": "prune", **best_m}]
    attempts = accepted = rejected_electrical = no_alternative = 0
    improvements = 0
    for index in range(1, moves + 1):
        choice = _relocate_candidate(current, rng)
        if choice is None:
            no_alternative += 1
            continue
        wid, start, stop = choice
        attempts += 1
        # The transactional engine applies counter deltas and rolls back;
        # verification is always re-derived from a fresh project snapshot.
        txstate = TransactionalState(current)
        with txstate.transaction() as tx:
            tx.move_wire(wid, start, stop)
            candidate = txstate.snapshot()
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
                tx.commit()
                current = candidate
                current_m = metrics
                accepted += 1
                if _priority(metrics) < _priority(best_m):
                    best = copy.deepcopy(candidate)
                    best_m = metrics
                    improvements += 1
                    history.append({"move": index, "kind": "route", **best_m})

    manifest = {
        "mode": "HELL_MODE_ALPHA_ELECTRICAL_ONLY",
        "seed": seed, "moves_requested": moves,
        "moves_with_column_alternative": attempts,
        "moves_accepted": accepted,
        "moves_electrically_rejected": rejected_electrical,
        "moves_without_alternative": no_alternative,
        "improvements": improvements,
        "redundant_wires_removed": removed,
        "baseline": first, "best_exploratory": best_m,
        "baseline_preserved": True,
        "record_eligible": False,
        "physical_pass": False,
        "cut_access": "unverified",
        "note": (
            "Search is real but limited to verified redundant-wire pruning "
            "and cut-frozen same-row-span column relocation; fixed cuts and "
            "end rows cannot solve all MOTOMIX stacking. No physical RECORD "
            "or BUILD_READY is claimed."
        ),
        "history": history,
    }
    return best, manifest


def run_files(input_path: Path, output_dir: Path, *, moves: int, seed: int) -> dict:
    src = json.loads(input_path.read_text(encoding="utf-8"))
    best, manifest = optimize(src, moves=moves, seed=seed)
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
    opts = parser.parse_args()
    report = run_files(opts.input, opts.out, moves=opts.moves, seed=opts.seed)
    before, after = report["baseline"], report["best_exploratory"]
    print(f"HELL MODE ALPHA — experimental electrical-only search, seed={opts.seed}")
    print(f"  Verified redundant wires removed: {len(report['redundant_wires_removed'])}")
    print(f"  Search proposals/accepted: {report['moves_with_column_alternative']}/{report['moves_accepted']}")
    print(f"  Jumper count: {before['wires']} -> {after['wires']}")
    print(f"  Excess stacked gaps: {before['excess_gap_occupancy']} -> {after['excess_gap_occupancy']}")
    print(f"  Physical certification: NOT AVAILABLE (cut access and 2.5D unverified)")
    print(f"  Output: {opts.out}/run.json, best_electrical.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
