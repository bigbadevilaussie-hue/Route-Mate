"""External slide-lock retry controller; Quick Fit only sees full locks."""
from __future__ import annotations

import copy
from typing import Any

from board_geometry import BUILTIN_DEFS, component_geometry, resolve_definition
from .quick_fit import quick_fit


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
