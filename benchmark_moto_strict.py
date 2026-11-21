"""Reproduce strict vertical routing on the saved Moto Quick Fit placement.

Run: python3 benchmark_moto_strict.py
This diagnostic does not modify the benchmark fixture or claim measured clearance.
"""
from __future__ import annotations

import json
from pathlib import Path

from solve.route import route_copper
from solve.quality_audit import audit_project

ROOT = Path(__file__).resolve().parent
SIDECAR = ROOT / "benchmarks/moto/moto.routemate-state.json"


def benchmark(sidecar=SIDECAR):
    state = json.loads(Path(sidecar).read_text(encoding="utf-8"))
    stages = state["pipeline"]["stages"]
    placed = stages["SOLVE.quick_fit"]["report"]["result"]["project"]
    routed = route_copper(placed, vertical_only=True)
    report = {
        "benchmark": "moto_saved_quick_fit_strict_vertical",
        "routing_status": routed["status"],
        "cuts_added": routed["cuts_added"],
        "wires_added": routed["wires_added"],
        "errors": routed["errors"],
        "warnings": routed["warnings"],
        "electrical_status": (routed.get("verification") or {}).get("status"),
        "physical_status": None,
        "physical_errors": [],
    }
    if routed["status"] == "ROUTED":
        audit = audit_project(routed["project"])
        report["physical_status"] = audit["physical_jumper_audit"]["status"]
        report["physical_errors"] = audit["physical_jumper_audit"]["errors"]
    return report


if __name__ == "__main__":
    result = benchmark()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["routing_status"] == "ROUTED"
                     and result["physical_status"] == "GRID_CLEARANCE_ONLY" else 1)
