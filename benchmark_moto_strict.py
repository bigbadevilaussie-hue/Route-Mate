"""Reproduce strict vertical routing on the saved Moto Quick Fit placement.

Run: python3 benchmark_moto_strict.py
This diagnostic does not modify the benchmark fixture or claim measured clearance.
"""
from __future__ import annotations

import json
import copy
import argparse
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from solve.route import route_copper, _terminals
from solve.quality_audit import audit_project
from placement_policy import is_off_board_component
from solve.quick_fit import quick_fit

ROOT = Path(__file__).resolve().parent
SIDECAR = ROOT / "benchmarks/moto/moto.routemate-state.json"


def benchmark(sidecar=SIDECAR, *, route_order="alphabetical", fresh_pads=False, placement_variant=0):
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
        if not fresh_pads and not isinstance(component.get("leads"), dict) and isinstance(source.get("leads"), dict):
            component["leads"] = copy.deepcopy(source["leads"])
            imported.append(str(component.get("label") or component.get("id")))
    if fresh_pads:
        # Re-run Quick Fit on the saved placement to exercise current external
        # pad allocation. Unlocked external leads are discarded and reallocated.
        fit = quick_fit(placed, placement_variant=placement_variant)
        if fit["status"] != "PLACED":
            return {
                "benchmark": "moto_fresh_offboard_pads_strict_vertical",
                "route_order": route_order,
                "routing_status": "BLOCKED_QUICK_FIT",
                "errors": fit["errors"], "warnings": fit.get("warnings", []),
                "electrical_status": None, "physical_status": None,
                "cuts_added": 0, "wires_added": 0,
            }
        placed = fit["project"]
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
            "benchmark": ("moto_fresh_offboard_pads_strict_vertical" if fresh_pads
                          else "moto_saved_quick_fit_strict_vertical"),
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
        "placement_variant": placement_variant if fresh_pads else None,
        "termination_source": ("current Quick Fit allocation" if fresh_pads
                               else "moto14wires30cuts.json reference fixture"),
        "reference_leads_imported_for": imported,
        "routing_status": routed["status"],
        "failed_net_terminals": failed_net_terminals,
        "reachability": routed.get("reachability"),
        "obstruction": routed.get("obstruction"),
        "cut_segmentation": routed.get("cut_segmentation"),
        "cut_feasibility": routed.get("cut_feasibility"),
        "multi_cut_feasibility": routed.get("multi_cut_feasibility"),
        "bidirectional_cut_feasibility": routed.get("bidirectional_cut_feasibility"),
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



def _run_variant(job):
    variant, route_order, fresh_pads = job
    started = time.perf_counter()
    try:
        report = benchmark(route_order=route_order, fresh_pads=fresh_pads,
                           placement_variant=variant)
    except Exception as exc:
        report = {"routing_status": "EXCEPTION", "physical_status": None,
                  "errors": [f"{type(exc).__name__}: {exc}"]}
    return variant, report, time.perf_counter() - started


def _line(variant, report, elapsed, count, total):
    reach = report.get("reachability") or {}
    error = (report.get("errors") or [""])[0]
    return (f"[{count:03d}/{total:03d}] variant={variant:03d} "
            f"status={report['routing_status']} "
            f"reach={reach.get('status', '-')} "
            f"cuts={report.get('cuts_added', 0)} wires={report.get('wires_added', 0)} "
            f"time={elapsed:.2f}s" + (f" error={error[:160]}" if error else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-order", choices=("alphabetical", "constrained"),
                        default="alphabetical")
    parser.add_argument("--placement-attempts", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--fresh-pads", action="store_true")
    parser.add_argument("--json", action="store_true",
                        help="Full diagnostic JSON, single attempt only")
    args = parser.parse_args()
    if not 1 <= args.placement_attempts <= 100:
        parser.error("--placement-attempts must be between 1 and 100")
    if not 1 <= args.workers <= 32:
        parser.error("--workers must be between 1 and 32")
    if args.placement_attempts > 1 and not args.fresh_pads:
        parser.error("multiple attempts require --fresh-pads")
    if args.json and args.placement_attempts != 1:
        parser.error("--json requires one attempt")

    started = time.perf_counter()
    jobs = [(v, args.route_order, args.fresh_pads)
            for v in range(args.placement_attempts)]
    attempts, successful = [], []
    if args.workers == 1 or len(jobs) == 1:
        for job in jobs:
            variant, report, elapsed = _run_variant(job)
            attempts.append((variant, report, elapsed))
            if not args.json:
                print(_line(variant, report, elapsed, len(attempts), len(jobs)), flush=True)
            if report["routing_status"] == "ROUTED" and report.get("physical_status") == "GRID_CLEARANCE_ONLY":
                successful.append(variant)
                break
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(_run_variant, job) for job in jobs]
            for future in as_completed(futures):
                variant, report, elapsed = future.result()
                attempts.append((variant, report, elapsed))
                print(_line(variant, report, elapsed, len(attempts), len(jobs)), flush=True)
                if report["routing_status"] == "ROUTED" and report.get("physical_status") == "GRID_CLEARANCE_ONLY":
                    successful.append(variant)
                    for pending in futures:
                        pending.cancel()
                    break
    if args.json:
        result = attempts[0][1]
        result["placement_attempts"] = [
            {"placement_variant": v, "routing_status": r["routing_status"],
             "physical_status": r.get("physical_status"), "errors": r.get("errors", [])}
            for v, r, _ in attempts
        ]
        print(json.dumps(result, indent=2))
    else:
        print(f"SUMMARY attempts={len(attempts)} successes={len(successful)} "
              f"wall_time={time.perf_counter()-started:.2f}s "
              f"workers={min(args.workers, len(jobs))}", flush=True)
    raise SystemExit(0 if successful else 1)
