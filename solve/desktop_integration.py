"""Non-Qt bridge from the shared placement-feedback solver to GUI-stage outputs.

There is one solving kernel. This adapter reports the actual successful
candidate placement, the actual routed board, and independently repeated
checks. It does not modify the source project or invent a physical PASS:
measured envelopes and cut-tool access remain unverified.
"""
from __future__ import annotations

import copy
from typing import Any, Callable

from placement_policy import is_off_board_component
from .placement_feedback import solve_with_feedback
from .verify import verify_project
from .quick_rules import quick_audit
from .quality_audit import audit_project


def solve_for_display(
    project: dict[str, Any], *, attempts: int = 24,
    clearance: int = 1,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Return verified solved board plus stage-adapter-compatible reports.

    On failure no project is returned as solved; GUI must retain its preview.
    Existing cuts and wires are preserved in the placement stage and passed
    to the shared feedback solver, which falls back to the legacy router
    rather than deleting them.
    """
    source = copy.deepcopy(project)
    outcome = solve_with_feedback(
        source, attempts=attempts, clearance=clearance,
        quick_backtracks=0, router="hole_graph", progress=progress,
    )
    if outcome["status"] != "ROUTED" or not isinstance(outcome.get("project"), dict):
        return {
            "status": outcome["status"],
            "errors": list(outcome.get("errors", [])),
            "history": outcome.get("history", []),
            "attempts_used": outcome.get("attempts_used", 0),
            "best_failure": outcome.get("best_failure"),
            "project": None,
        }

    solved = outcome["project"]
    # Treat locks as hard engine constraints, even if a future placement
    # strategy mistakenly alters them. Sliding edge anchors are permitted
    # to move *only along their original edge*, without rotation.
    from board_geometry import BUILTIN_DEFS, resolve_definition
    from .quick_fit import edge_side

    previous = {str(c.get("id")): c for c in source.get("components", [])
                if isinstance(c, dict)}
    current = {str(c.get("id")): c for c in solved.get("components", [])
               if isinstance(c, dict)}
    definitions = dict(BUILTIN_DEFS)
    definitions.update({str(d["id"]): d for d in source.get("componentDefs", [])
                        if isinstance(d, dict) and d.get("id")})
    rows, cols = int(source["board"]["rows"]), int(source["board"]["cols"])
    locked_errors = []
    for cid, before in previous.items():
        if before.get("locked") is not True:
            continue
        after = current.get(cid)
        if after is None:
            locked_errors.append(f"Locked component {cid} is missing.")
            continue
        if before.get("offBoard"):
            if before.get("leads") != after.get("leads"):
                locked_errors.append(f"Locked external leads moved for {cid}.")
            continue
        for field in ("rotation", "defId", "footprintOverride"):
            if before.get(field) != after.get(field):
                locked_errors.append(f"Locked component {cid} changed {field}.")
        if before.get("edge") and before.get("slide"):
            definition = resolve_definition(before, definitions)
            if definition is None:
                locked_errors.append(f"Sliding component {cid} has no footprint definition.")
            else:
                try:
                    original_side = edge_side(before, definition, rows, cols)
                    final_side = edge_side(after, definition, rows, cols)
                    if original_side != final_side:
                        locked_errors.append(f"Sliding component {cid} left its anchored board edge.")
                except (KeyError, TypeError, ValueError) as exc:
                    locked_errors.append(f"Sliding component {cid} has invalid geometry: {exc}")
        else:
            if before.get("boardPos") != after.get("boardPos"):
                locked_errors.append(f"Locked component {cid} changed board position.")
            if before.get("flexibleEndPos") != after.get("flexibleEndPos"):
                locked_errors.append(f"Locked component {cid} changed its endpoint.")
    if locked_errors:
        return {
            "status": "LOCK_CONSTRAINT_FAILED", "project": None,
            "errors": locked_errors, "history": outcome.get("history", []),
            "attempts_used": outcome.get("attempts_used", 0),
        }
    electrical = verify_project(solved)
    grid = quick_audit(solved)
    physical = audit_project(solved)
    errors = (list(electrical.get("errors", []))
              + list(grid.get("errors", []))
              + list(physical.get("errors", []))
              + list(physical.get("physical_jumper_audit", {}).get("errors", [])))
    if (electrical["status"] != "PASS" or grid["status"] == "FAIL"
            or physical["status"] != "PASS"):
        return {
            "status": "VERIFICATION_FAILED", "project": None,
            "errors": errors or ["Independent route checks did not pass."],
            "history": outcome.get("history", []),
            "attempts_used": outcome.get("attempts_used", 0),
            "verification": electrical, "grid_audit": grid,
            "physical_audit": physical,
        }

    # This is the actual accepted component placement and off-board pad
    # allocation, before the router modified its strips/jumpers.
    placed = copy.deepcopy(solved)
    placed["board"]["cuts"] = copy.deepcopy(source["board"].get("cuts", []))
    placed["board"]["wires"] = copy.deepcopy(source["board"].get("wires", []))
    components = [c for c in placed["components"] if isinstance(c, dict)]
    placement = {
        "status": "PLACED",
        "project": placed,
        "placed": sum(
            not is_off_board_component(c) and isinstance(c.get("boardPos"), dict)
            for c in components
        ),
        "excluded": sum(is_off_board_component(c) for c in components),
        "errors": [], "warnings": [],
        "report": {
            "search": "routing-feedback placement",
            "placement_variant": outcome["placement_variant"],
            "attempts_used": outcome["attempts_used"],
            "clearance_requested": clearance,
        },
    }
    routing = {
        "status": "ROUTED",
        "project": solved,
        "verification": electrical,
        "errors": [],
        "warnings": list(outcome.get("warnings", [])),
        "cuts_added": len(solved["board"]["cuts"]) - len(placed["board"]["cuts"]),
        "wires_added": len(solved["board"]["wires"]) - len(placed["board"]["wires"]),
        "grid_audit": grid, "physical_audit": physical,
    }
    return {
        "status": "ROUTED",
        "project": solved, "placement": placement, "routing": routing,
        "verification": electrical, "grid_audit": grid,
        "physical_audit": physical,
        "history": outcome.get("history", []),
        "placement_variant": outcome["placement_variant"],
        "attempts_used": outcome["attempts_used"],
        "warnings": routing["warnings"],
    }


__all__ = ["solve_for_display"]
