"""External slide-lock retry controller; Quick Fit only sees full locks."""
from __future__ import annotations

import copy
from typing import Any

from board_geometry import BUILTIN_DEFS, component_geometry, resolve_definition
from .quick_fit import quick_fit


def edge_slide_positions(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate EVERY legal edge-parallel anchor for each Edge+Slide lock.

    Uses the same rotated footprint bounds and edge selection as Quick Fit.
    The perpendicular coordinate is fixed ON the selected board edge. The
    parallel axis is scanned once per position, nearest saved hint first.
    No heuristic placement-variant budget may truncate this list.
    """
    from .quick_fit import _local_variant, edge_side
    from placement_policy import is_off_board_component

    board = project["board"]
    rows, cols = int(board["rows"]), int(board["cols"])
    defs = dict(BUILTIN_DEFS)
    defs.update({str(d["id"]): d for d in project.get("componentDefs", [])
                 if isinstance(d, dict) and d.get("id")})
    result = []
    for part in project.get("components", []):
        if not isinstance(part, dict) or is_off_board_component(part):
            continue
        if not (part.get("locked") is True and part.get("edge") is True
                and part.get("slide") is True):
            continue
        name = str(part.get("label") or part.get("id"))
        pos = part.get("boardPos")
        if not isinstance(pos, dict):
            raise ValueError(f"{name}: Edge+Slide requires an original board position")
        definition = resolve_definition(part, defs)
        if definition is None:
            raise ValueError(f"{name}: Edge+Slide footprint not defined")
        side = edge_side(part, definition, rows, cols)
        rotation = int(part.get("rotation", 0) or 0) % 360
        _cells, _pins, min_r, min_c, height, width = _local_variant(
            part, definition, rotation
        )
        if height > rows or width > cols:
            candidates = []
        elif side in ("top", "bottom"):
            top = 0 if side == "top" else rows - height
            candidates = [
                {"row": top - min_r, "col": left - min_c}
                for left in range(cols - width + 1)
            ]
        else:
            left = 0 if side == "left" else cols - width
            candidates = [
                {"row": top - min_r, "col": left - min_c}
                for top in range(rows - height + 1)
            ]
        axis = "col" if side in ("top", "bottom") else "row"
        # Original position first, then nearest neighbours. Preserve all
        # possible positions without duplicates, including both boundaries.
        candidates.sort(key=lambda p: (
            abs(p[axis] - int(pos[axis])), p[axis]
        ))
        result.append({
            "id": str(part["id"]), "label": name, "edge": side,
            "rotation": rotation, "original": copy.deepcopy(pos),
            "positions": candidates,
        })
    return result


def slide_fit(project: dict[str, Any], component_id: str, edge: str,
              clearance: int = 1) -> dict[str, Any]:
    """Try each in-bounds edge-parallel position as a temporary full lock.

    Starts at the saved position, searches decreasing coordinates first, then
    wraps to the opposite end. This is a single-component bounded controller;
    it does not change the underlying placement algorithm or GUI.
    """
    source = copy.deepcopy(project)
    if edge not in ("top", "bottom", "left", "right"):
        raise ValueError("edge must be top, bottom, left or right")
    board = source.get("board", {})
    components = source.get("components", [])
    matches = [c for c in components if isinstance(c, dict)
               and str(c.get("id")) == str(component_id)]
    if len(matches) != 1 or not isinstance(matches[0].get("boardPos"), dict):
        raise ValueError("slide component must have a unique ID and saved boardPos")
    component = matches[0]
    if component.get("locked") is not True or not component.get("slide"):
        raise ValueError("slide component must have locked=True and slide enabled")
    pos = component["boardPos"]
    if type(pos.get("row")) is not int or type(pos.get("col")) is not int:
        raise ValueError("slide anchor needs integer row and col")
    rows, cols = board["rows"], board["cols"]
    definitions = dict(BUILTIN_DEFS)
    definitions.update({str(d["id"]): d for d in source.get("componentDefs", [])
                        if isinstance(d, dict) and d.get("id")})
    definition = resolve_definition(component, definitions)
    if definition is None:
        raise ValueError("slide component has no footprint definition")
    pins, body = component_geometry(component, definition)
    cells = [(int(p["row"]), int(p["col"])) for p in pins]
    cells.extend((int(r), int(c)) for r, c in body)
    if not cells:
        raise ValueError("slide component has no physical cells")
    original = pos["col"] if edge in ("top", "bottom") else pos["row"]
    axis = 1 if edge in ("top", "bottom") else 0
    limit = cols if axis == 1 else rows
    offsets = [point[axis] - original for point in cells]
    low, high = -min(offsets), limit - 1 - max(offsets)
    if low > high:
        return {"status": "NO_FIT_FOUND", "project": source,
                "errors": ["slide footprint cannot fit on the selected axis"],
                "warnings": [], "attempts": 0, "positions_tried": []}
    positions = ([original] if low <= original <= high else [])
    positions += [p for p in range(min(original - 1, high), low - 1, -1)
                  if p not in positions]
    positions += [p for p in range(high, max(original, low - 1), -1)
                  if p not in positions]
    positions += [p for p in range(low, high + 1) if p not in positions]
    tried = []
    for coordinate in positions:
        trial = copy.deepcopy(source)
        target = next(c for c in trial["components"]
                      if isinstance(c, dict) and str(c.get("id")) == str(component_id))
        target["boardPos"]["col" if axis == 1 else "row"] = coordinate
        # Quick Fit already accepts locked slide metadata as an immovable part.
        result = quick_fit(trial, clearance=clearance)
        tried.append(coordinate)
        if result["status"] == "PLACED":
            result["attempts"] = len(tried)
            result["positions_tried"] = tried
            return result
        if result["status"] not in ("NO_FIT_FOUND", "CONSTRAINT_CONFLICT"):
            return {**result, "attempts": len(tried), "positions_tried": tried}
    return {"status": "NO_FIT_FOUND", "project": source,
            "errors": [f"{component_id}: no placement found at any legal slide position"],
            "warnings": [], "attempts": len(tried), "positions_tried": tried}
