"""Non-Qt bridge from the shared placement-feedback solver to GUI-stage outputs.

There is one solving kernel. This adapter reports the actual successful
candidate placement, the actual routed board, and independently repeated
checks. It does not modify the source project or invent a physical PASS:
measured envelopes and cut-tool access remain unverified.
"""
from __future__ import annotations

import copy
from typing import Any

from placement_policy import is_off_board_component
from .placement_feedback import solve_with_feedback
from .verify import verify_project
from .quick_rules import quick_audit
from .quality_audit import audit_project


def solve_for_display(
    project: dict[str, Any], *, attempts: int = 24,
    clearance: int = 1,
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
        quick_backtracks=0, router="hole_graph",
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
    from board_geometry import BUILTIN_DEFS, resolve_definition, component_geometry
    def edge_side(c, definitions, rows, cols):
        definition = resolve_definition(c, definitions)
        if definition is None or not isinstance(c.get("boardPos"), dict):
            return None
        pins, body = component_geometry(c, definition)
        occupied = [(int(p["row"]), int(p["col"])) for p in pins] + list(body)
        if not occupied:
            return None
        rr, cc = [p[0] for p in occupied], [p[1] for p in occupied]
        if min(rr) == 0:
            return "top"
        if max(rr) == rows - 1:
            return "bottom"
        if min(cc) == 0:
            return "left"
        if max(cc) == cols - 1:
            return "right"
        return None

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
            if edge_side(before, definitions, rows, cols) != edge_side(after, definitions, rows, cols):
                locked_errors.append(f"Sliding component {cid} left its anchored board edge.")
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
