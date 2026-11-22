"""Bounded routing-aware placement search.

Searches complete component placements, and accepts one only after electrical
routing verification. Never modifies the input project or locked components.
"""
from __future__ import annotations

import copy
from time import perf_counter
from typing import Any, Callable

from .quick_fit import is_off_board_component

from .quick_fit import quick_fit
from .route import route_copper
from .hole_router import route_holes


def solve_with_feedback(
    project: dict[str, Any],
    *,
    attempts: int = 24,
    clearance: int = 1,
    body_spacing_holes: int = 1,
    route_order: str = "constrained",
    quick_backtracks: int = 2,
    router: str = "hole_graph",
    hole_iterations: int = 24,
    hole_expansion_budget: int = 600000,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
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
    if router not in ("hole_graph", "legacy"):
        raise ValueError("router must be hole_graph or legacy")

    history: list[dict[str, Any]] = []
    repairs = []
    seen = set()
    original_locked = {
        str(c.get("id")): c.get("locked") is True
        for c in project.get("components", [])
        if isinstance(c, dict)
    }

    def placement_key(candidate):
        return tuple(sorted(
            (str(c.get("id")), repr(c.get("boardPos")), repr(c.get("rotation")))
            for c in candidate.get("components", [])
            if isinstance(c, dict) and not is_off_board_component(c)
        ))

    def relocation(candidate, target, variant, spacing):
        trial = copy.deepcopy(candidate)
        prior = next(
            (c for c in candidate.get("components", [])
             if isinstance(c, dict) and str(c.get("id")) == target), {}
        )
        pos = prior.get("boardPos")
        forbidden = {}
        if isinstance(pos, dict):
            forbidden[target] = {
                (int(pos["row"]), int(pos["col"]), int(prior.get("rotation") or 0))
            }
        for c in trial.get("components", []):
            if not isinstance(c, dict) or is_off_board_component(c):
                continue
            if str(c.get("id")) == target:
                c.pop("boardPos", None)
                c["locked"] = False
            else:
                c["locked"] = True
        fit = quick_fit(trial, clearance=clearance, placement_variant=variant,
                        forbidden_anchors=forbidden,
                        body_spacing_holes=spacing)
        if fit.get("status") != "PLACED":
            return None
        result = fit["project"]
        for c in result.get("components", []):
            if isinstance(c, dict) and str(c.get("id")) in original_locked:
                if original_locked[str(c.get("id"))]:
                    c["locked"] = True
                else:
                    c.pop("locked", None)
        fit["project"] = result
        return fit

    best: dict[str, Any] | None = None
    best_rank: tuple[int, int, int] | None = None

    def stopped():
        return {
            "status": "CANCELLED", "project": None,
            "attempts_used": len(history), "history": history,
            "errors": ["Quick Solve stopped by user."],
        }

    # Report completed attempts; never present these as guaranteed ETA.
    def report_progress(started: float) -> None:
        if progress is not None:
            progress({
                "completed": len(history),
                "budget": attempts,
                "seconds": perf_counter() - started,
                "last": dict(history[-1]),
            })

    for variant in range(attempts):
        # First candidate uses one-hole nominal body spacing. If it cannot
        # yield a verified route, resume the ORIGINAL compact feedback
        # sequence from variant 0, with its own relocation queue. This
        # preserves proven AUDIO/MOTO routing behaviour within 24 attempts.
        scouting = body_spacing_holes > 0 and variant == 0
        attempt_spacing = body_spacing_holes if scouting else 0
        search_variant = (
            variant if body_spacing_holes == 0 or scouting else variant - 1
        )
        if variant == 1 and body_spacing_holes > 0:
            repairs.clear()
        if cancelled is not None and cancelled():
            return stopped()
        attempt_started = perf_counter()
        if repairs:
            previous, target = repairs.pop(0)
            repaired = relocation(previous, target, search_variant, attempt_spacing)
            fit = repaired if repaired else {"status": "NO_FIT_FOUND", "errors": ["relocation failed"]}
        else:
            fit = quick_fit(
                project, clearance=clearance, placement_variant=search_variant,
                body_spacing_holes=attempt_spacing,
            )
        if cancelled is not None and cancelled():
            return stopped()
        if fit["status"] != "PLACED":
            history.append({
                "variant": variant, "body_spacing_preference": attempt_spacing,
                "placement": fit["status"],
                "routing": "NOT_ATTEMPTED",
                "error": (fit.get("errors") or [None])[0],
            })
            report_progress(attempt_started)
            continue

        candidate = copy.deepcopy(fit["project"])
        key = placement_key(candidate)
        if key in seen:
            history.append({"variant": variant, "body_spacing_preference": attempt_spacing,
                            "placement": "DUPLICATE", "routing": "NOT_ATTEMPTED"})
            report_progress(attempt_started)
            continue
        seen.add(key)
        candidate.setdefault("board", {})["cuts"] = copy.deepcopy(
            project.get("board", {}).get("cuts", [])
        )
        candidate["board"]["wires"] = copy.deepcopy(
            project.get("board", {}).get("wires", [])
        )
        if router == "hole_graph" and not (candidate["board"].get("cuts") or candidate["board"].get("wires")):
            routed = route_holes(
                candidate, iterations=(min(hole_iterations, 12)
                                       if attempt_spacing else hole_iterations),
                expansion_budget=(min(hole_expansion_budget, 180000)
                                  if attempt_spacing else hole_expansion_budget),
                cancelled=cancelled,
            )
        else:
            # Never discard existing manual cuts or wires.
            routed = route_copper(
                candidate, quick_mode=True, vertical_only=False,
                route_order=route_order, quick_backtracks=quick_backtracks,
                cancelled=cancelled,
            )
        if routed["status"] == "CANCELLED" or (
            cancelled is not None and cancelled()
        ):
            return stopped()
        passed = (routed["status"] == "ROUTED"
                  and (routed.get("verification") or {}).get("status") == "PASS")
        history.append({
            "variant": variant, "placement": "PLACED",
            "body_spacing_preference": attempt_spacing,
            "routing": routed["status"],
            "hole_search": routed.get("hole_search"),
            "cuts": routed.get("cuts_added", 0),
            "wires": routed.get("wires_added", 0),
            "error": (routed.get("errors") or [None])[0],
        })
        report_progress(attempt_started)
        if passed:
            placement_report = dict(fit.get("report", {}))
            placement_report["body_spacing_requested"] = body_spacing_holes
            placement_report["body_spacing_preference"] = attempt_spacing
            warnings = list(fit.get("warnings", [])) + list(
                routed.get("warnings", [])
            )
            if attempt_spacing < body_spacing_holes:
                warnings.append(
                    "The one-hole nominal body-spacing preference did not "
                    "produce the selected electrically verified route; "
                    "a compact placement was used instead. Actual package "
                    "dimensions remain unmeasured."
                )
            return {
                "status": "ROUTED", "project": routed["project"],
                "verification": routed["verification"],
                "placement_variant": search_variant,
                "placement_report": placement_report,
                "attempts_used": len(history), "history": history,
                "warnings": warnings,
            }

        # Prioritize movable components attached to nets mentioned by router errors.
        errors = routed.get("errors") or []
        failed = {e[4:].split(": ", 1)[0] for e in errors if isinstance(e, str) and e.startswith("net ") and ": " in e}
        relevant = {str(a.get("componentId")) for a in candidate.get("netAssignments", []) if isinstance(a, dict) and str(a.get("netId")) in failed}
        movable = [str(c.get("id")) for c in candidate.get("components", []) if isinstance(c, dict) and not is_off_board_component(c) and not original_locked.get(str(c.get("id")), False)]
        movable.sort(key=lambda cid: (cid not in relevant, cid))
        for cid in movable[:4]:
            repairs.append((candidate, cid))

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
