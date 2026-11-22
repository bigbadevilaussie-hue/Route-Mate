"""Reproducible comparison of independently verified Quick Solve candidates.

The heuristic and 2.5D measurements rank candidates; neither certifies
physical buildability. Hard electrical and grid checks happen before calling.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def solution_signature(project: dict[str, Any]) -> str:
    components = sorted(
        ((str(c.get("id")), c.get("boardPos"), c.get("rotation"),
          c.get("flexibleEndPos"), c.get("leads"))
         for c in project.get("components", []) if isinstance(c, dict)),
        key=lambda row: row[0],
    )
    board = project.get("board", {})
    cuts = sorted(
        (int(c.get("row", -1)), int(c.get("col", -1)),
         str(c.get("kind", "")))
        for c in board.get("cuts", []) if isinstance(c, dict)
    )
    wires = sorted(
        tuple(sorted((
            (int(w["from"]["row"]), int(w["from"]["col"])),
            (int(w["to"]["row"]), int(w["to"]["col"])),
        )))
        for w in board.get("wires", []) if isinstance(w, dict)
        and isinstance(w.get("from"), dict) and isinstance(w.get("to"), dict)
    )
    # Different generated IDs/order do not make the same physical layout new.
    payload = (components, cuts, wires)
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def candidate_quality(project: dict[str, Any], *,
                      audit_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prefer fewer nominal contacts, then provisional quality and routing cost."""
    from .render_quality import score_render
    from geometry_sidecar import make_document, assess_saved_board

    scored = score_render(project, audit_report=audit_report)
    diagnostic = None
    contact_component_ids: list[str] = []
    try:
        assessment = assess_saved_board(project, make_document(project))
        findings = assessment.get("contact_findings", [])
        contacts = len(findings)
        contact_component_ids = sorted({
            str(cid) for finding in findings
            for cid in finding.get("component_ids", [])
        })
        status = str(assessment.get("status", "UNVERIFIED"))
    except (KeyError, ValueError, TypeError) as exc:
        # Never turn absent advisory geometry into a zero-warning result.
        contacts, status = 1000000, "UNVERIFIED"
        diagnostic = str(exc)
    from collector_geometry import PITCH_MM
    from geometry_sidecar import assumed_body_pad_keepouts
    from .quick_fit import _nominal_body_overhangs_board
    board = project.get("board", {})
    crossing_solids = [
        solid for solid in assumed_body_pad_keepouts(project)
        if _nominal_body_overhangs_board(
            solid, int(board["rows"]), int(board["cols"]), PITCH_MM
        )
    ]
    overhangs = [str(solid.get("label") or solid.get("id"))
                 for solid in crossing_solids]
    overhang_ids = [str(solid["id"]) for solid in crossing_solids]
    signature = solution_signature(project)
    rank = (
        int(status == "HARD_CONFLICT"), len(overhangs), contacts,
        -float(scored["score"]), int(scored["wires"]), int(scored["cuts"]),
        float(scored["wire_length_mm"]), signature,
    )
    return {
        "signature": signature,
        "nominal_contacts": contacts,
        "nominal_contact_component_ids": contact_component_ids,
        "nominal_board_overhangs": overhangs,
        "nominal_board_overhang_ids": overhang_ids,
        "provisional_score": float(scored["score"]),
        "assumed_25d_status": status,
        "wires": int(scored["wires"]),
        "cuts": int(scored["cuts"]),
        "wire_length_mm": float(scored["wire_length_mm"]),
        "rank": rank,
        "physical_certified": False,
        "quality_diagnostic": diagnostic,
    }


__all__ = ["candidate_quality", "solution_signature"]
