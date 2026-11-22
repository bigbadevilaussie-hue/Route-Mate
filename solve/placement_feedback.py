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
from .render_quality import score_render


def inspect_assumed_contacts(project):
    # Lazy import breaks geometry_sidecar -> solve.clearance_25d -> solve
    # package initialisation cycle; also exposes an isolated test seam.
    from geometry_sidecar import inspect_assumed_contacts as inspect
    return inspect(project)


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
    quality_floor: float = 40.0,
    contact_warning_limit: int = 1,
    improvement_attempts: int = 3,
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
    if not 0 <= quality_floor <= 100:
        raise ValueError("quality_floor must be between 0 and 100")
    if type(contact_warning_limit) is not int or contact_warning_limit < 0:
        raise ValueError("contact_warning_limit must be a non-negative integer")
    if type(improvement_attempts) is not int or not 0 <= improvement_attempts <= 24:
        raise ValueError("improvement_attempts must be an integer between 0 and 24")

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

    # Only independently electrically verified candidates enter this pool.
    # Nominal contact count outranks provisional routing aesthetics; neither
    # is proof of physical fit. Never discard a verified baseline during retry.
    verified_best: dict[str, Any] | None = None
    verified_rank: tuple | None = None
    first_verified_variant: int | None = None

    def candidate_metrics(board: dict[str, Any]) -> dict | None:
        try:
            quality = score_render(board)
            contacts = inspect_assumed_contacts(board)
            return {
                "score": quality["score"],
                "contacts": len(contacts),
                "wires": quality["wires"],
                "cuts": quality["cuts"],
                "wire_length_mm": quality["wire_length_mm"],
            }
        except (ValueError, TypeError, KeyError, AttributeError):
            # Lightweight mocked routing fixtures may not contain collector
            # geometry. Do not invent a physical/quality rating for them.
            return None

    def success_result(routed, fit, search_variant, attempt_spacing, metrics):
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
            "selection_metrics": metrics,
            "quality_retry": {
                "triggered": False, "extra_attempts": 0,
                "quality_floor": quality_floor,
                "contact_warning_limit": contact_warning_limit,
            },
        }

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

    # Short explicit budgets retain the original per-variant relocation
    # semantics. Full GUI/benchmark budgets add a single nominal-spacing
    # scout before reverting to the proven compact search sequence.
    use_scout = body_spacing_holes > 0 and attempts >= 8
    for variant in range(attempts):
        if (verified_best is not None and first_verified_variant is not None
                and variant - first_verified_variant > improvement_attempts):
            break
        scouting = use_scout and variant == 0
        attempt_spacing = (
            body_spacing_holes if not use_scout or scouting else 0
        )
        search_variant = (
            variant if not use_scout or scouting else variant - 1
        )
        if variant == 1 and use_scout:
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
        # A nominal-spacing scout may have tried this exact placement with
        # a reduced router budget. Do not suppress the subsequent compact
        # retry, which restores the full proven routing budget.
        key = (attempt_spacing, placement_key(candidate))
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
        if not passed:
            report_progress(attempt_started)
        if passed:
            metrics = candidate_metrics(routed["project"])
            selection = success_result(
                routed, fit, search_variant, attempt_spacing, metrics,
            )
            if metrics is None:
                report_progress(attempt_started)
                return selection
            rank = (
                metrics["contacts"], -metrics["score"],
                metrics["wires"], metrics["cuts"], metrics["wire_length_mm"],
            )
            if verified_rank is None or rank < verified_rank:
                verified_rank = rank
                verified_best = selection
            if first_verified_variant is None:
                first_verified_variant = variant
            needs_improvement = (
                metrics["score"] < quality_floor
                or metrics["contacts"] > contact_warning_limit
            )
            history[-1]["quality_score"] = metrics["score"]
            history[-1]["nominal_contacts"] = metrics["contacts"]
            history[-1]["verified_fallback_retained"] = needs_improvement
            report_progress(attempt_started)
            # Already meets the quality and contact limits; no extra work.
            # An improved verified candidate can also end the retry early.
            if not needs_improvement or improvement_attempts == 0:
                break
            continue

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

    if verified_best is not None:
        output = dict(verified_best)
        output["attempts_used"] = len(history)
        output["history"] = history
        attempts_after_first = (
            len(history) - first_verified_variant - 1
            if first_verified_variant is not None else 0
        )
        output["quality_retry"] = {
            "triggered": bool(attempts_after_first),
            "extra_attempts": attempts_after_first,
            "quality_floor": quality_floor,
            "contact_warning_limit": contact_warning_limit,
            "selected_quality": (output.get("selection_metrics") or {}).get("score"),
            "selected_contacts": (output.get("selection_metrics") or {}).get("contacts"),
            "selected_variant": output["placement_variant"],
        }
        return output

    return {
        "status": "ROUTING_FAILED", "project": None,
        "attempts_used": len(history), "history": history,
        "best_failure": best,
        "errors": ["No electrically verified route found within placement budget."],
    }


__all__ = ["solve_with_feedback"]
