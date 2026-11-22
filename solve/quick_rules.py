"""Quick Mode jumper geometry: grid-centreline checks, not measured clearance."""
from __future__ import annotations

from fractions import Fraction
from physical_geometry import (
    PhysicalPoint, PhysicalSegment, HOLE_PITCH_MM,
    physical_segments_intersect, jumper_intersects_component,
)


def segment(a, b):
    return PhysicalSegment(
        PhysicalPoint(Fraction(a[1]) * HOLE_PITCH_MM, Fraction(a[0]) * HOLE_PITCH_MM),
        PhysicalPoint(Fraction(b[1]) * HOLE_PITCH_MM, Fraction(b[0]) * HOLE_PITCH_MM),
    )


def collinear(a, b, c, d):
    def cross(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return cross(a, b, c) == 0 and cross(a, b, d) == 0


def quick_wire_error(a, b, bodies, existing):
    """Allow collinear stacking, prohibit transverse crossing and shared landing holes."""
    if a == b:
        return "zero-length jumper"
    candidate = segment(a, b)
    if jumper_intersects_component(candidate, bodies):
        return "crosses component body occupancy"
    for c, d in existing:
        if a in (c, d) or b in (c, d):
            return "shared jumper endpoint hole"
        if physical_segments_intersect(candidate, segment(c, d)) and not collinear(a, b, c, d):
            return "crosses another jumper"
    return None


def quick_audit(project):
    from board_geometry import BUILTIN_DEFS, resolve_definition
    from physical_geometry import physical_component_body
    from placement_policy import is_off_board_component
    defs = dict(BUILTIN_DEFS)
    defs.update({str(d["id"]): d for d in project.get("componentDefs", [])
                 if isinstance(d, dict) and d.get("id")})
    bodies = []
    for component in project.get("components", []):
        if not isinstance(component, dict) or is_off_board_component(component):
            continue
        if not isinstance(component.get("boardPos"), dict):
            continue
        definition = resolve_definition(component, defs)
        if definition is not None:
            bodies.extend(physical_component_body(component, definition))
    seen, errors = [], []
    wires = project.get("board", {}).get("wires", [])
    diagonal = 0
    for i, wire in enumerate(wires):
        a = (wire["from"]["row"], wire["from"]["col"])
        b = (wire["to"]["row"], wire["to"]["col"])
        diagonal += int(a[0] != b[0] and a[1] != b[1])
        err = quick_wire_error(a, b, bodies, seen)
        if err:
            errors.append(f'{wire.get("id", i)}: {err}')
        seen.append((a, b))
    # Independent cross-check using the same conservative artwork keepouts
    # that the router should have excluded before choosing any jumper.
    from .wire_keepout import wire_keepout_errors
    errors.extend(wire_keepout_errors(project))
    if diagonal * 10 > len(wires):
        errors.append(f"diagonal quota exceeded: {diagonal}/{len(wires)} (maximum 10%)")
    return {"status": "FAIL" if errors else "GRID_CLEARANCE_ONLY",
            "errors": errors, "diagonals": diagonal,
            "wires": len(wires), "measured_envelope_verified": False}
