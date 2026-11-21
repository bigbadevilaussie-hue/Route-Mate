"""Bounded routing-aware placement search.

Searches complete component placements, and accepts one only after electrical
routing verification. Never modifies the input project or locked components.
"""
from __future__ import annotations

import copy
from typing import Any

from .quick_fit import quick_fit
from .route import route_copper


def solve_with_feedback(
    project: dict[str, Any],
    *,
    attempts: int = 24,
    clearance: int = 1,
    route_order: str = "constrained",
    quick_backtracks: int = 2,
) -> dict[str, Any]:
    """Try diversified placements and route each one.

    A failed routing attempt is discarded, not committed. A successful result
    is independently electrically verified by route_copper. Physical jumper
    clearance remains a separate audit.
    """
    if not isinstance(project, dict):
        raise ValueError("project must be an object")
    if not 1 <= attempts <= 100:
        raise ValueError("attempts must be between 1 and 100")
    if not 0 <= quick_backtracks <= 32:
        raise ValueError("quick_backtracks must be between 0 and 32")

    history: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    best_rank: tuple[int, int, int] | None = None

    for variant in range(attempts):
        fit = quick_fit(project, clearance=clearance, placement_variant=variant)
        if fit["status"] != "PLACED":
            history.append({
                "variant": variant, "placement": fit["status"],
                "routing": "NOT_ATTEMPTED",
                "error": (fit.get("errors") or [None])[0],
            })
            continue

        candidate = copy.deepcopy(fit["project"])
        candidate.setdefault("board", {})["cuts"] = copy.deepcopy(
            project.get("board", {}).get("cuts", [])
        )
        candidate["board"]["wires"] = copy.deepcopy(
            project.get("board", {}).get("wires", [])
        )
        routed = route_copper(
            candidate, quick_mode=True, vertical_only=False,
            route_order=route_order, quick_backtracks=quick_backtracks,
        )
        passed = (routed["status"] == "ROUTED"
                  and (routed.get("verification") or {}).get("status") == "PASS")
        history.append({
            "variant": variant, "placement": "PLACED",
            "routing": routed["status"],
            "cuts": routed.get("cuts_added", 0),
            "wires": routed.get("wires_added", 0),
            "error": (routed.get("errors") or [None])[0],
        })
        if passed:
            return {
                "status": "ROUTED", "project": routed["project"],
                "verification": routed["verification"],
                "placement_variant": variant,
                "attempts_used": len(history), "history": history,
                "warnings": routed.get("warnings", []),
            }

        # Keep a compact failure summary, never a huge partial project dump.
        rank = (
            len(routed.get("errors") or []),
            routed.get("wires_added", 0),
            routed.get("cuts_added", 0),
        )
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = history[-1]

    return {
        "status": "ROUTING_FAILED", "project": None,
        "attempts_used": len(history), "history": history,
        "best_failure": best,
        "errors": ["No electrically verified route found within placement budget."],
    }


__all__ = ["solve_with_feedback"]
