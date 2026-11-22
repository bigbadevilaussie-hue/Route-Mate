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
        (str(c.get("id")), c.get("boardPos"), c.get("rotation"),
         c.get("flexibleEndPos"), c.get("leads"))
        for c in project.get("components", []) if isinstance(c, dict)
    )
    board = project.get("board", {})
    payload = (components, board.get("cuts", []), board.get("wires", []))
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def candidate_quality(project: dict[str, Any]) -> dict[str, Any]:
    """Prefer fewer nominal contacts, then provisional quality and routing cost."""
    from .render_quality import score_render
    from geometry_sidecar import make_document, assess_saved_board

    scored = score_render(project)
    assessment = assess_saved_board(project, make_document(project))
    contacts = len(assessment.get("contact_findings", []))
    status = str(assessment.get("status", "UNVERIFIED"))
    signature = solution_signature(project)
    rank = (
        int(status == "HARD_CONFLICT"), contacts,
        -float(scored["score"]), int(scored["wires"]), int(scored["cuts"]),
        float(scored["wire_length_mm"]), signature,
    )
    return {
        "signature": signature,
        "nominal_contacts": contacts,
        "provisional_score": float(scored["score"]),
        "assumed_25d_status": status,
        "wires": int(scored["wires"]),
        "cuts": int(scored["cuts"]),
        "wire_length_mm": float(scored["wire_length_mm"]),
        "rank": rank,
        "physical_certified": False,
    }


__all__ = ["candidate_quality", "solution_signature"]
