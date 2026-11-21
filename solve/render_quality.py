"""Deterministic, provisional render quality indicator; not a physical sign-off."""
from __future__ import annotations

from typing import Any

from placement_policy import is_off_board_component
from solve.quality_audit import audit_project


def score_render(project: dict[str, Any]) -> dict[str, Any]:
    """Score layout completeness and routing cost, exposing every penalty.

    A heuristic comparison metric, NOT proof of electrical/physical correctness.
    """
    report = audit_project(project)
    board = project["board"]
    components = [c for c in project.get("components", []) if isinstance(c, dict)
                  and not is_off_board_component(c)]
    placed = sum(isinstance(c.get("boardPos"), dict) for c in components)
    missing = len(components) - placed
    cuts = report["counts"]["cuts"]["actual"]
    wires = report["counts"]["wires"]["actual"]
    diagonals = report["jumper_audit"]["diagonal_count"]
    length_mm = report["jumper_audit"]["total_length_hole_pitches"] * 2.54
    # Relative heuristic costs; do not imply a calibrated manufacturing score.
    penalties = {
        "unplaced_components": 15 * missing,
        "invalid_wires": 20 * report["jumper_audit"]["invalid_records"],
        "diagonal_wires": 10 * diagonals,
        "cuts": 0.4 * cuts,
        "wires": 0.6 * wires,
        "wire_length": 0.02 * length_mm,
    }
    score = round(max(0.0, 100.0 - sum(penalties.values())), 1)
    return {
        "score": score, "out_of": 100, "classification": "PROVISIONAL",
        "routed": bool(cuts or wires), "placed": placed, "placeable": len(components),
        "cuts": cuts, "wires": wires, "diagonals": diagonals,
        "wire_length_mm": round(length_mm, 1), "penalties": penalties,
        "audit_errors": report["errors"],
        "note": "Heuristic only; electrical and physical verification required.",
    }
