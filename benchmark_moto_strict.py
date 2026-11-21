"""Reproduce strict vertical routing on the saved Moto Quick Fit placement.

Run: python3 benchmark_moto_strict.py
This diagnostic does not modify the benchmark fixture or claim measured clearance.
"""
from __future__ import annotations

import json
import copy
import argparse
from pathlib import Path

from solve.route import route_copper, _terminals
from solve.quality_audit import audit_project
from placement_policy import is_off_board_component

ROOT = Path(__file__).resolve().parent
SIDECAR = ROOT / "benchmarks/moto/moto.routemate-state.json"


def benchmark(sidecar=SIDECAR, *, route_order="alphabetical"):
    state = json.loads(Path(sidecar).read_text(encoding="utf-8"))
    stages = state["pipeline"]["stages"]
    placed = copy.deepcopy(stages["SOLVE.quick_fit"]["report"]["result"]["project"])
    # Reuse explicit pads from the saved reference board, not guessed holes.
    reference_path = ROOT / "benchmarks/moto/moto14wires30cuts.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference_by_id = {str(c.get("id")): c for c in reference["components"]
                       if isinstance(c, dict)}
    imported = []
    for component in placed.get("components", []):
        if not isinstance(component, dict) or not is_off_board_component(component):
            continue
        source = reference_by_id.get(str(component.get("id")), {})
        # Quick Fit sidecars may omit source exclusion metadata. Restore only
        # the explicit reference flag, without inventing GPS landing pads.
        if ("boardExcluded" not in component and source.get("boardExcluded") is True
                and component.get("offBoard") is not True):
            component["boardExcluded"] = True
        if not isinstance(component.get("leads"), dict) and isinstance(source.get("leads"), dict):
            component["leads"] = copy.deepcopy(source["leads"])
            imported.append(str(component.get("label") or component.get("id")))
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
            "route_order": route_order,
            "routing_status": "BLOCKED_MISSING_OFFBOARD_TERMINATIONS",
            "reference_leads_imported_for": imported,
            "missing_termination_pads": missing_leads,
            "errors": ["Saved Quick Fit fixture has no board landing holes for assigned off-board leads."],
            "electrical_status": None, "physical_status": None,
            "cuts_added": 0, "wires_added": 0,
        }
    routed = route_copper(placed, vertical_only=True, route_order=route_order)
    failed_nets = []
    for error in routed.get("errors", []):
        if error.startswith("net ") and ": " in error:
            net_id = error[4:].split(": ", 1)[0]
            if net_id not in failed_nets:
                failed_nets.append(net_id)
    failed_net_terminals = {}
    if failed_nets:
        board = placed["board"]
        terminals = _terminals(placed, int(board["rows"]), int(board["cols"]))
        for net_id in failed_nets:
            failed_net_terminals[net_id] = [
                {"row": row, "col": col, "terminal": ref}
                for row, col, net, ref in terminals if net == net_id
            ]
    report = {
        "benchmark": "moto_saved_quick_fit_strict_vertical",
        "route_order": route_order,
        "termination_source": "moto14wires30cuts.json reference fixture",
        "reference_leads_imported_for": imported,
        "routing_status": routed["status"],
        "failed_net_terminals": failed_net_terminals,
        "reachability": routed.get("reachability"),
        "obstruction": routed.get("obstruction"),
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-order", choices=("alphabetical", "constrained"),
                        default="alphabetical")
    args = parser.parse_args()
    result = benchmark(route_order=args.route_order)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["routing_status"] == "ROUTED"
                     and result["physical_status"] == "GRID_CLEARANCE_ONLY" else 1)
