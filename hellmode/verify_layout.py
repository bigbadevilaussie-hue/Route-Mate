"""Hell Mode M1 independent verification facade, preliminary status ladder.

An ELECTRICAL PASS plus STRICT 2D clearance is *not* full physical PASS:
wire diameters, 2.5D lead/body envelopes and cut-tool access remain unproven.
No output of this early M1 facade is yet eligible as a certified RECORD.
"""
from __future__ import annotations

from typing import Any

from .copper_model import reconstruct_electrical
from .strict_occupancy import audit_strict_occupancy


def verify_layout(layout: dict[str, Any], spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reconstruct independent raw geometry and classify with explicit limits.

    Caller must pass raw project JSON, not router-generated claim metadata.
    In M1 only STRICT/PASS_ONLY is implemented; other policies are deferred.
    """
    if spec is not None:
        policy = spec.get("geometry_policy", "PASS_ONLY")
        if policy != "PASS_ONLY":
            raise NotImplementedError(f"geometry policy {policy!r} not implemented")
    copper = reconstruct_electrical(layout)
    geometry = audit_strict_occupancy(
        layout["board"], pin_holes=copper["pin_holes"],
        trusted_wire_nets=copper["wire_nets"],
    )
    electrical_ok = copper["status"] == "PASS"
    strict_2d_ok = geometry["status"] == "STRICT_2D_CLEAR"
    if not electrical_ok:
        certification = "ELECTRICAL_FAIL"
    elif not strict_2d_ok:
        certification = "ELECTRICAL_ONLY"
    else:
        certification = "GRID_VERIFIED"
    reasons = [x["code"] for x in copper["errors"]]
    reasons.extend(x["code"] for x in geometry["findings"])
    if electrical_ok and strict_2d_ok:
        reasons.append("UNVERIFIED_PACKAGE_GEOMETRY")
    reasons.append("CUT_ACCESS_UNVERIFIED")
    return {
        "status": certification,
        "electrical": copper,
        "strict_occupancy": geometry,
        "reason_codes": sorted(set(reasons)),
        "cut_access": "unverified",
        "physical_pass": False,
        "record_eligible": False,
        "assumptions": [],
        "limitation": (
            "M1 facade does not yet independently certify measured 2.5D "
            "wire/body/lead clearance or cut-tool accessibility"
        ),
    }


__all__ = ["verify_layout"]
