"""Reproduce strict vertical routing on the saved Moto Quick Fit placement.

Run: python3 benchmark_moto_strict.py
This diagnostic does not modify the benchmark fixture or claim measured clearance.
"""
from __future__ import annotations

import json
from pathlib import Path

from solve.route import route_copper
from solve.quality_audit import audit_project
from placement_policy import is_off_board_component

ROOT = Path(__file__).resolve().parent
SIDECAR = ROOT / "benchmarks/moto/moto.routemate-state.json"


def benchmark(sidecar=SIDECAR):
    state = json.loads(Path(sidecar).read_text(encoding="utf-8"))
    stages = state["pipeline"]["stages"]
    placed = stages["SOLVE.quick_fit"]["report"]["result"]["project"]
    missing_leads = []
    components = {str(c.get("id")): c for c in placed.get("components", [])
                  if isinstance(c, dict)}
    for assignment in placed.get("netAssignments", []):
        component = components.get(str(assignment.get("componentId")))
        if not component or not is_off_board_component(component):
            continue
        if component.get("boardExcluded") is True and component.get("offBoard") is not True:
            continue
        pin = str(assignment.get("pinId"))
        leads = component.get("leads")
        if not isinstance(leads, dict) or leads.get(pin) is None:
            missing_leads.append(f"{component.get('label') or component.get('id')} pin {pin}")
    if missing_leads:
        return {
            "benchmark": "moto_saved_quick_fit_strict_vertical",
            "routing_status": "BLOCKED_MISSING_OFFBOARD_TERMINATIONS",
            "missing_termination_pads": missing_leads,
            "errors": ["Saved Quick Fit fixture has no board landing holes for assigned off-board leads."],
            "electrical_status": None, "physical_status": None,
            "cuts_added": 0, "wires_added": 0,
        }
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
