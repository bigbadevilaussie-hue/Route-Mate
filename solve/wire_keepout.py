"""Component-side jumper keepouts shared by routing and independent auditing.

Footprint bodyCells are NOT a complete component-body description. Several
built-in parts (notably electrolytic capacitors and transistors) have no
bodyCells despite production artwork visibly covering multiple board holes.
This module supplements them with conservative *artwork* keepouts, expressed
in board-hole pitches. It does not claim measured package envelopes, wire
diameter clearance or cut-tool accessibility.
"""
from __future__ import annotations

from collections import defaultdict
from fractions import Fraction as F
from typing import Any

from board_geometry import BUILTIN_DEFS, component_geometry, resolve_definition
from placement_policy import is_off_board_component



def _physical_contract(project: dict) -> dict | None:
    """Use 2.5D geometry only when dimensions are explicitly declared complete."""
    config = project.get("physicalClearance")
    if config is None:
        return None
    if not isinstance(config, dict) or config.get("complete") is not True:
        raise ValueError("physicalClearance requires an explicit complete=true declaration")
    if not isinstance(config.get("settings"), dict):
        raise ValueError("physicalClearance.settings must specify physical dimensions in mm")
    for name in ("body_solids", "leads"):
        if not isinstance(config.get(name), list):
            raise ValueError(f"physicalClearance.{name} must be a list (explicitly empty if none)")
    return config


def _physical_gap_keepouts(project: dict, rows: int, cols: int, config: dict
                          ) -> dict[tuple[int, int], set[str]]:
    """Router 2.5D body-gap policy; explicit physical metadata only.

    A gap is an elementary edge, not a jumper landing. Lead and pad access
    are checked separately by the router's terminal graph and full-wire audit.
    CONDITIONAL remains blocked pending a separately designed conditional
    solve/report mode.
    """
    from .clearance_25d import classify_jumper
    bad: dict[tuple[int, int], set[str]] = defaultdict(set)
    for col in range(cols):
        for row in range(rows - 1):
            case = {
                "jumper": {
                    "from_mm": [2.54 * col, 2.54 * row],
                    "to_mm": [2.54 * col, 2.54 * (row + 1)],
                },
                "settings": config["settings"],
                "body_solids": config["body_solids"],
                "leads": [],  # Endpoint/lead legality must use full jumper endpoints.
                "thermal_zones": config.get("thermal_zones", []),
            }
            verdict = classify_jumper(case)
            if verdict["verdict"] != "PASS":
                bad[(row, col)].update(
                    finding["item"] or finding["reason"]
                    for finding in verdict["findings"]
                )
    return bad



def component_keepouts(project: dict) -> list[dict[str, Any]]:
    """Collect occupancy squares and artwork-envelope shapes for each component."""
    definitions = dict(BUILTIN_DEFS)
    definitions.update({
        str(d["id"]): d for d in project.get("componentDefs", [])
        if isinstance(d, dict) and d.get("id")
    })
    shapes = []
    for part in project.get("components", []):
        if not isinstance(part, dict) or is_off_board_component(part):
            continue
        if not isinstance(part.get("boardPos"), dict):
            continue
        definition = resolve_definition(part, definitions)
        if definition is None:
            raise ValueError(f"{part.get('label') or part.get('id')}: missing footprint")
        pins, body = component_geometry(part, definition)
        name = str(part.get("label") or part.get("id") or "unnamed")
        for row, col in body:
            shapes.append({
                "label": name, "kind": "square",
                "row": F(row), "col": F(col), "half": F(1, 2),
            })
        if not pins:
            continue
        pin_rows = [int(p["row"]) for p in pins]
        pin_cols = [int(p["col"]) for p in pins]
        centre_r = F(min(pin_rows) + max(pin_rows), 2)
        centre_c = F(min(pin_cols) + max(pin_cols), 2)
        part_type = str(part.get("defId") or part.get("componentDefId") or "")
        if part_type == "def-cap-polarized":
            # Production SVG: circle radius 5 at scale 11.811, 30px per
            # hole: approximately 1.97 hole pitches, centred between pads.
            # A 2-pitch radius avoids a wire drawn through the capacitor can.
            shapes.append({
                "label": name, "kind": "circle",
                "row": centre_r, "col": centre_c, "radius2": F(4),
            })
        elif part_type == "def-capacitor":
            # Ceramic artwork is a rounded rectangle centred between leads,
            # approximately 0.5 pitches across, 1 pitch along its pin axis.
            span_r = max(pin_rows) - min(pin_rows)
            span_c = max(pin_cols) - min(pin_cols)
            shapes.append({
                "label": name, "kind": "rect",
                "r0": F(min(pin_rows)) - (F(1, 2) if span_r else F(1, 2)),
                "r1": F(max(pin_rows)) + F(1, 2),
                "c0": F(min(pin_cols)) - F(1, 2),
                "c1": F(max(pin_cols)) + F(1, 2),
            })
        elif part_type in {"def-npn", "def-pmos"}:
            # Three-pin transistor graphic without bodyCells: conservatively
            # reserve a 1.25-pitch radius about its middle pin.
            shapes.append({
                "label": name, "kind": "circle",
                "row": centre_r, "col": centre_c, "radius2": F(25, 16),
            })
        elif part_type == "def-led":
            shapes.append({
                "label": name, "kind": "circle",
                "row": centre_r, "col": centre_c, "radius2": F(1),
            })
    return shapes


def _hits_gap(shape: dict, row: int, col: int) -> bool:
    """Does the vertical jumper segment (row,col)->(row+1,col) meet shape?"""
    y0, y1, x = F(row), F(row+1), F(col)
    kind = shape["kind"]
    if kind == "square":
        return (abs(x - shape["col"]) <= shape["half"]
                and y0 <= shape["row"] + shape["half"]
                and y1 >= shape["row"] - shape["half"])
    if kind == "rect":
        return (shape["c0"] <= x <= shape["c1"]
                and y0 <= shape["r1"] and y1 >= shape["r0"])
    # Circle: squared closest distance to a vertical gap.
    delta_x = x - shape["col"]
    nearest_y = min(max(shape["row"], y0), y1)
    return delta_x * delta_x + (nearest_y - shape["row"])**2 <= shape["radius2"]


def vertical_gap_keepouts(project: dict, rows: int, cols: int) -> dict[tuple[int, int], set[str]]:
    """Map forbidden (row above gap, column) to obstructing component labels."""
    physical = _physical_contract(project)
    if physical is not None:
        return _physical_gap_keepouts(project, rows, cols, physical)
    bad: dict[tuple[int, int], set[str]] = defaultdict(set)
    shapes = component_keepouts(project)
    for shape in shapes:
        for col in range(cols):
            for row in range(rows-1):
                if _hits_gap(shape, row, col):
                    bad[(row, col)].add(shape["label"])
    return bad


def wire_keepout_errors(project: dict) -> list[str]:
    """Reject routed wire centreline intersections with any component artwork."""
    board = project["board"]
    rows, cols = int(board["rows"]), int(board["cols"])
    physical = _physical_contract(project)
    forbidden = {} if physical is not None else vertical_gap_keepouts(project, rows, cols)
    definitions = dict(BUILTIN_DEFS)
    definitions.update({
        str(d["id"]): d for d in project.get("componentDefs", [])
        if isinstance(d, dict) and d.get("id")
    })
    pin_holes: dict[tuple[int, int], set[str]] = defaultdict(set)
    for part in project.get("components", []):
        if not isinstance(part, dict):
            continue
        label = str(part.get("label") or part.get("id") or "unnamed")
        if is_off_board_component(part):
            if part.get("boardExcluded") is True and part.get("offBoard") is not True:
                continue
            for point in (part.get("leads") or {}).values():
                if isinstance(point, dict) and "row" in point and "col" in point:
                    pin_holes[(int(point["row"]), int(point["col"]))].add(label)
        elif isinstance(part.get("boardPos"), dict):
            definition = resolve_definition(part, definitions)
            if definition:
                pins, _ = component_geometry(part, definition)
                for pin in pins:
                    pin_holes[(int(pin["row"]), int(pin["col"]))].add(label)
    errors = []
    for i, wire in enumerate(board.get("wires", [])):
        a, b = wire.get("from", {}), wire.get("to", {})
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        r0, c0 = a.get("row"), a.get("col")
        r1, c1 = b.get("row"), b.get("col")
        if any(type(v) is not int for v in (r0, c0, r1, c1)):
            continue
        if c0 != c1 or r0 == r1:
            continue  # Other geometric invalidities handled by quick_audit.
        if physical is not None:
            from .clearance_25d_verify import verify_jumper_25d
            case = {
                "jumper": {
                    "from_mm": [c0 * 2.54, r0 * 2.54],
                    "to_mm": [c1 * 2.54, r1 * 2.54],
                },
                "settings": physical["settings"],
                "body_solids": physical["body_solids"],
                "leads": physical["leads"],
                "thermal_zones": physical.get("thermal_zones", []),
            }
            result = verify_jumper_25d(case)
            for finding in result["findings"]:
                # Do not certify user-declared clearance as unconditional PASS.
                if finding["verdict"] != "PASS":
                    errors.append(
                        f"{wire.get('id', i)}: {finding['verdict']}: "
                        f"{finding['reason']}: {finding['item']}"
                    )
        else:
            hit = set()
            for r in range(min(r0, r1), max(r0, r1)):
                hit.update(forbidden.get((r, c0), ()))
            if hit:
                errors.append(
                    f"{wire.get('id', i)}: jumper crosses component artwork/keepout: "
                    + ", ".join(sorted(hit))
                )
        intermediate_pins = set()
        for row in range(min(r0, r1) + 1, max(r0, r1)):
            intermediate_pins.update(pin_holes.get((row, c0), ()))
        if intermediate_pins:
            errors.append(
                f"{wire.get('id', i)}: jumper passes through intermediate component "
                "pin/pad holes: " + ", ".join(sorted(intermediate_pins))
            )
    return errors


__all__ = ["component_keepouts", "vertical_gap_keepouts", "wire_keepout_errors"]
