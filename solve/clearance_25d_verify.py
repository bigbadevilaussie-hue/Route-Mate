"""Independent 2.5D physical clearance verdict implementation.

Does NOT use the router's classify_jumper or its gap-map decisions.
Shares only the documented outline-distance geometry primitive and tolerance;
independently applies the normative standoff, lead and thermal rules.
"""
from __future__ import annotations

from math import hypot

from .clearance_25d import EPS_MM, outline_distance


def _pt(values):
    return float(values[0]), float(values[1])


def _point_line_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    fraction = 0.0 if length2 == 0 else (
        ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2
    )
    fraction = min(1.0, max(0.0, fraction))
    return hypot(point[0] - start[0] - fraction * dx,
                 point[1] - start[1] - fraction * dy)


def verify_jumper_25d(case: dict) -> dict:
    """Evaluate geometry independently, with coded evidence per obstruction."""
    wire = case["jumper"]
    start, end = _pt(wire["from_mm"]), _pt(wire["to_mm"])
    settings = case["settings"]
    outer_radius = float(settings["wire_od_mm"]) / 2
    clearance = float(settings["min_clearance_mm"])
    z_margin = float(settings["z_margin_mm"])
    lead_margin = float(settings["lead_margin_mm"])
    lift = float(wire.get("lift_mm", 0))
    if min(outer_radius, clearance, z_margin, lead_margin, lift) < 0:
        raise ValueError("clearance dimensions must be non-negative")
    if start == end:
        return {"verdict": "FAIL_PROVEN", "findings": [
            {"verdict": "FAIL_PROVEN", "reason": "zero_length_jumper", "item": ""}]}
    findings = []

    def record(verdict, reason, item):
        findings.append({"verdict": verdict, "reason": reason, "item": str(item)})

    for hole in case.get("occupied_holes", []):
        p = _pt(hole["center_mm"])
        at_end = min(hypot(p[0] - x[0], p[1] - x[1]) for x in (start, end)) <= EPS_MM
        if at_end and hole.get("allowed_endpoint") is True:
            continue
        if _point_line_distance(p, start, end) <= EPS_MM:
            record("FAIL_PROVEN", "occupied_hole", hole.get("id", ""))

    for lead in case.get("leads", []):
        p = _pt(lead["center_mm"])
        at_end = min(hypot(p[0] - x[0], p[1] - x[1]) for x in (start, end)) <= EPS_MM
        if at_end and lead.get("allowed_endpoint") is True:
            continue
        limit = outer_radius + lead_margin + float(lead["radius_mm"])
        if _point_line_distance(p, start, end) < limit - EPS_MM:
            record("FAIL_PROVEN", "lead_clearance", lead.get("id", ""))

    for solid in case.get("body_solids", []):
        threshold = outer_radius + clearance
        if outline_distance(start, end, solid) >= threshold - EPS_MM:
            continue
        source = solid["z_min_source"]
        if source not in ("datasheet", "measured", "user_declared", "default_flush"):
            raise ValueError("unsupported standoff provenance")
        bottom = float(solid["z_min_mm"])
        top = float(solid["z_max_mm"])
        if bottom < 0 or top < bottom:
            raise ValueError("invalid solid z interval")
        name = solid.get("id", "")
        if source == "default_flush":
            record("FAIL_UNVERIFIED", "standoff_unknown", name)
        elif lift + 2 * outer_radius + z_margin <= bottom + EPS_MM:
            if source == "user_declared":
                record("CONDITIONAL", "declared_standoff", name)
        elif lift >= top + z_margin - EPS_MM:
            if source == "user_declared":
                record("CONDITIONAL", "declared_height", name)
        elif solid.get("allow_contact") is True:
            if solid.get("contact_source") not in ("datasheet", "measured", "user_declared"):
                raise ValueError("contact requires provenance")
            record("CONDITIONAL", "declared_contact", name)
        else:
            record("FAIL_PROVEN", "body_clearance", name)

    for zone in case.get("thermal_zones", []):
        if "component_temp_c" not in zone or "wire_insulation_limit_c" not in zone:
            continue
        if float(zone["component_temp_c"]) <= float(zone["wire_insulation_limit_c"]):
            continue
        if outline_distance(start, end, zone) < outer_radius + clearance - EPS_MM:
            record("FAIL_PROVEN", "thermal_keepout", zone.get("id", ""))

    ranking = ("PASS", "CONDITIONAL", "FAIL_UNVERIFIED", "FAIL_PROVEN")
    worst = max((ranking.index(f["verdict"]) for f in findings), default=0)
    return {"verdict": ranking[worst], "findings": findings}


__all__ = ["verify_jumper_25d"]
