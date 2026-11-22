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


def _solve_one_position(
    project: dict[str, Any], *, attempts: int = 24,
    clearance: int = 1,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
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
        cancelled=cancelled,
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


def solve_for_display(
    project: dict[str, Any], *, attempts: int = 24,
    clearance: int = 1,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """GUI solve: try all Edge+Slide positions, stopping at first verified fit.

    Generic 24-variant feedback remains available for non-sliding projects.
    A selected Edge+Slide anchor is not a random placement variant: its
    physical edge positions are an explicit finite search space.
    """
    from itertools import product
    from math import prod
    from time import perf_counter
    from .slide_fit import edge_slide_positions

    def was_cancelled():
        return cancelled is not None and cancelled()

    def stopped(checked: int, total: int | None = None, summary: str = ""):
        output = {
            "status": "CANCELLED", "project": None,
            "attempts_used": checked, "history": [],
            "errors": ["Quick Solve stopped by user."],
        }
        if total is not None:
            output["slide_search"] = {
                "components": summary, "positions_checked": checked,
                "positions_total": total,
            }
        return output

    if was_cancelled():
        return stopped(0)

    try:
        sliders = edge_slide_positions(project)
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "status": "CONSTRAINT_CONFLICT", "project": None,
            "attempts_used": 0, "history": [], "errors": [str(exc)],
        }
    if not sliders:
        return _solve_one_position(
            project, attempts=attempts, clearance=clearance, progress=progress,
            cancelled=cancelled,
        )

    total = prod(len(s["positions"]) for s in sliders)
    summary = ", ".join(
        f"{s['label']} ({s['edge']}: {len(s['positions'])} positions)"
        for s in sliders
    )
    if total == 0:
        return {
            "status": "CONSTRAINT_CONFLICT", "project": None,
            "attempts_used": 0, "history": [],
            "errors": [f"Edge+Slide cannot fit: {summary}. "
                       "The footprint has no legal position on its selected edge."],
            "slide_search": {"components": summary, "positions_checked": 0,
                             "positions_total": total},
        }

    history = []
    placements_fitted = 0
    last_detail = None
    # Each edge position receives the ordinary Quick Solve placement budget.
    # The search still stops on its first independently verified route.
    total_variant_budget = total * attempts
    variants_checked = 0
    for index, combo in enumerate(product(*(s["positions"] for s in sliders)), 1):
        if was_cancelled():
            response = stopped(index - 1, total, summary)
            response["history"] = history
            return response
        started = perf_counter()
        trial = copy.deepcopy(project)
        by_id = {
            str(p.get("id")): p for p in trial.get("components", [])
            if isinstance(p, dict)
        }
        anchors = {}
        for slider, selected in zip(sliders, combo):
            target = by_id[slider["id"]]
            previous = target["boardPos"]
            original_end = target.get("flexibleEndPos")
            if isinstance(original_end, dict):
                dr = selected["row"] - int(previous["row"])
                dc = selected["col"] - int(previous["col"])
                target["flexibleEndPos"] = {
                    "row": int(original_end["row"]) + dr,
                    "col": int(original_end["col"]) + dc,
                }
            target["boardPos"] = dict(selected)
            # Freeze THIS position only. Quick Fit must not silently slide
            # it again; all other genuine locks remain unchanged.
            target["locked"] = True
            target["edge"] = True
            target["slide"] = False
            anchors[slider["label"]] = dict(selected)

        # A full normal Quick Solve budget for EACH edge position. A progress
        # callback reports the actual variant index inside this edge position.
        # The original project and its lock metadata are never mutated.
        def variant_progress(update):
            if progress is not None:
                progress({
                    **update,
                    "mode": "edge_slide_variant",
                    "completed": (index - 1) * attempts + update["completed"],
                    "budget": total_variant_budget,
                    "position_index": index,
                    "positions_total": total,
                    "variant_index": update["completed"],
                    "variants_per_position": attempts,
                    "slide_positions": dict(anchors),
                })

        result = _solve_one_position(
            trial, attempts=attempts, clearance=clearance,
            progress=variant_progress, cancelled=cancelled,
        )
        variants_checked += result.get("attempts_used", len(result.get("history") or []))
        if result["status"] == "CANCELLED" or was_cancelled():
            response = stopped(index - 1, total, summary)
            response["history"] = history
            return response
        sub = result.get("history") or []
        detail = sub[-1] if sub else {}
        fit = detail.get("placement", result["status"])
        route = detail.get("routing", result["status"])
        if fit == "PLACED" or result["status"] == "ROUTED":
            placements_fitted += 1
        last_detail = (result.get("errors") or [detail.get("error") or "not routed"])[0]
        entry = {
            "variant": index - 1,
            "placement": fit,
            "routing": route,
            "slide_positions": anchors,
            "variants_checked": result.get("attempts_used", len(sub)),
            "error": last_detail if result["status"] != "ROUTED" else None,
        }
        history.append(entry)
        if progress is not None:
            progress({
                "completed": index, "budget": total,
                "seconds": perf_counter() - started,
                "last": dict(entry), "mode": "edge_slide",
                "variants_checked": variants_checked,
                "variants_budget": total_variant_budget,
            })
        if result["status"] == "ROUTED":
            # Restore the requested sliding-lock metadata on the actual
            # verified layout, including both GUI stage copies.
            for stage in (
                result.get("project"),
                (result.get("placement") or {}).get("project"),
                (result.get("routing") or {}).get("project"),
            ):
                if not isinstance(stage, dict):
                    continue
                selected_parts = {
                    str(p.get("id")): p for p in stage.get("components", [])
                    if isinstance(p, dict)
                }
                for slider in sliders:
                    selected_parts[slider["id"]]["locked"] = True
                    selected_parts[slider["id"]]["edge"] = True
                    selected_parts[slider["id"]]["slide"] = True
            result["attempts_used"] = variants_checked
            result["history"] = history
            result["slide_search"] = {
                "components": summary, "positions_checked": index,
                "positions_total": total, "selected": anchors,
                "variants_checked": variants_checked,
                "variants_budget": total_variant_budget,
                "variants_per_position": attempts,
            }
            return result

    # No false 'part cannot physically fit' claim when placement did fit
    # and only routing failed; preserve both counts and actionable reason.
    if placements_fitted:
        message = (
            f"Edge+Slide {summary}: placement fitted at "
            f"{placements_fitted}/{total} position(s), but no electrically "
            f"verified route was found after checking all {total} positions "
            f"and {variants_checked} placement attempts. "
            f"Last routing issue: {last_detail}"
        )
    else:
        message = (
            f"Edge+Slide {summary}: cannot fit the edge component(s) "
            f"at any of the {total} legal position combination(s) "
            f"after {variants_checked} placement attempts. "
            f"Last placement issue: {last_detail}"
        )
    return {
        "status": "ROUTING_FAILED" if placements_fitted else "NO_FIT_FOUND",
        "project": None, "attempts_used": variants_checked, "history": history,
        "errors": [message],
        "best_failure": history[-1] if history else None,
        "slide_search": {
            "components": summary, "positions_checked": total,
            "positions_total": total, "placements_fitted": placements_fitted,
            "variants_checked": variants_checked,
            "variants_budget": total_variant_budget,
            "variants_per_position": attempts,
        },
    }


__all__ = ["solve_for_display"]
