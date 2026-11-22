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
