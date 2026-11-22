"""Run the real desktop Quick Solve portfolio with explicit worker count.

Compare 1, 3 and 4 workers on the same board and 24 total attempt slots.
Runs are intentionally independent; no source project is ever modified.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from solve.parallel_quick import solve_parallel_for_display


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path,
                        default=ROOT / "benchmarks/moto/motomix.json")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=3)
    parser.add_argument("--attempts", type=int, default=24)
    parser.add_argument("--spacing", type=int, choices=(0, 1, 2), default=1)
    args = parser.parse_args()
    source = json.loads(args.json.read_text(encoding="utf-8"))
    started = perf_counter()
    outcome = solve_parallel_for_display(
        source, workers=args.workers, attempts=args.attempts,
        body_spacing_holes=args.spacing,
    )
    seconds = perf_counter() - started
    portfolio = outcome.get("portfolio") or {}
    selected = outcome.get("quality_selection") or {}
    summary = {
        "status": outcome["status"], "seconds": round(seconds, 2),
        "workers": portfolio.get("workers"),
        "process_ids": portfolio.get("worker_pids", []),
        "attempts_used": portfolio.get("attempts_used"),
        "attempts_budget": portfolio.get("attempts_budget"),
        "distinct_verified": portfolio.get("solutions_found"),
        "target_verified": 2,
        "quality_provisional": selected.get("provisional_score"),
        "nominal_contacts": selected.get("nominal_contacts"),
        "cuts": selected.get("cuts"),
        "wires": selected.get("wires"),
        "physical_certified": False,
    }
    print(json.dumps(summary, indent=2))
    if outcome["status"] == "ROUTED":
        verification = outcome.get("verification") or {}
        assert verification.get("status") == "PASS", verification
        assert outcome["grid_audit"]["status"] != "FAIL"
        assert outcome["physical_audit"]["status"] == "PASS"


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    main()
