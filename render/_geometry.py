"""Small, dependency-free footprint geometry helpers used by the front renderer."""

from __future__ import annotations

from typing import Any


def _pin(pin_id: str, name: str, row: int, col: int) -> dict[str, Any]:
    return {"id": pin_id, "name": name, "offsetRow": row, "offsetCol": col}


def _inline(pin_count: int, step: int = 1, *, flexible: bool = False) -> dict[str, Any]:
    return {
        "width": 1,
        "height": (pin_count - 1) * step + 1,
        "flexible": flexible,
        "pins": [_pin(str(i + 1), str(i + 1), i * step, 0) for i in range(pin_count)],
        "bodyCells": [
            {"row": row, "col": 0}
            for row in range(1, (pin_count - 1) * step)
            if row % step
        ],
    }


def _dip(pin_count: int) -> dict[str, Any]:
    side = pin_count // 2
    pins = [_pin(str(i + 1), str(i + 1), i, 0) for i in range(side)]
    pins += [
        _pin(str(side + i + 1), str(side + i + 1), side - 1 - i, 3)
        for i in range(side)
    ]
    return {
        "width": 4, "height": side, "pins": pins,
        "bodyCells": [
            {"row": row, "col": col}
            for row in range(side) for col in (1, 2)
        ],
    }


def _builtins() -> dict[str, dict[str, Any]]:
    """The common built-in footprints used by the legacy project format.

    Custom definitions from project JSON always take precedence. This compact
    registry covers the standard parts used by the Moto and Audio benchmarks.
    """
    result: dict[str, dict[str, Any]] = {}
    for part_id, step, flexible in (
        ("def-resistor", 4, True),
        ("def-capacitor", 1, True),
        ("def-cap-polarized", 1, True),
        ("def-led", 1, True),
        ("def-diode", 3, True),
        ("def-zener", 3, True),
        ("def-inductor", 4, True),
        ("def-fuse", 5, True),
        ("def-switch", 3, False),
    ):
        result[part_id] = _inline(2, step, flexible=flexible)
    result["def-npn"] = {
        **_inline(3), "category": "semiconductor",
        "pins": [_pin("1", "B", 0, 0), _pin("2", "C", 1, 0), _pin("3", "E", 2, 0)],
    }
    result["def-pmos"] = {
        **_inline(3), "category": "semiconductor",
        "pins": [_pin("1", "G", 0, 0), _pin("2", "D", 1, 0), _pin("3", "S", 2, 0)],
    }
    result["def-pushbutton"] = {
        "width": 4, "height": 3,
        "pins": [
            _pin("1", "1", 0, 0), _pin("1", "1", 0, 3),
            _pin("2", "2", 2, 0), _pin("2", "2", 2, 3),
        ],
        "bodyCells": [
            {"row": 0, "col": 1}, {"row": 0, "col": 2},
            {"row": 1, "col": 0}, {"row": 1, "col": 1},
            {"row": 1, "col": 2}, {"row": 1, "col": 3},
            {"row": 2, "col": 1}, {"row": 2, "col": 2},
        ],
    }
    result["def-555"] = _dip(8)
    for count in (4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40):
        result[f"def-ic-dip{count}"] = _dip(count)
    for count in range(1, 21):
        result[f"def-connector-{count}"] = _inline(count)
    for spacing in (2, 3, 4, 5, 7):
        result[f"def-generic-2pin-{spacing}h"] = _inline(2, spacing - 1)
    result["def-generic-3pin-compact"] = _inline(3)
    result["def-generic-3pin-spaced"] = _inline(3, 2)
    return result


BUILTIN_DEFS = _builtins()


def resolve_definition(component: dict[str, Any], definitions: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Resolve project definition, including a component-specific footprint override."""
    base = definitions.get(str(component.get("defId") or component.get("componentDefId") or ""))
    override = component.get("footprintOverride")
    if base is None and isinstance(override, dict):
        base = override
    if base is None:
        return None
    result = dict(base)
    if isinstance(override, dict):
        for key in ("width", "height", "pins", "bodyCells"):
            if key in override:
                result[key] = override[key]
    return result


def rotate_offset(row: int, col: int, rotation: int, max_row: int, max_col: int) -> tuple[int, int]:
    rotation %= 360
    if rotation == 90:
        return col, max_row - row
    if rotation == 180:
        return max_row - row, max_col - col
    if rotation == 270:
        return max_col - col, row
    return row, col


def component_geometry(
    component: dict[str, Any], definition: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[tuple[int, int]]]:
    """Return absolute pin records and body-cell coordinates."""
    pos = component.get("boardPos")
    if not isinstance(pos, dict):
        return [], []
    base_row, base_col = int(pos.get("row", 0)), int(pos.get("col", 0))
    pins = definition.get("pins") or []
    body = definition.get("bodyCells") or []
    points = [
        (int(p.get("offsetRow", 0)), int(p.get("offsetCol", 0)))
        for p in pins if isinstance(p, dict)
    ] + [
        (int(p.get("row", 0)), int(p.get("col", 0)))
        for p in body if isinstance(p, dict)
    ]
    max_row = max((p[0] for p in points), default=0)
    max_col = max((p[1] for p in points), default=0)
    rotation = int(component.get("rotation", 0) or 0) % 360

    if definition.get("flexible") and len(pins) >= 2:
        end = component.get("flexibleEndPos")
        if not isinstance(end, dict):
            dr, dc = rotate_offset(
                int(pins[1].get("offsetRow", 1)),
                int(pins[1].get("offsetCol", 0)),
                rotation, max_row, max_col,
            )
            end = {"row": base_row + dr, "col": base_col + dc}
        pin_points = [
            {"id": str(pins[0].get("id", "1")), "name": str(pins[0].get("name", "1")),
             "row": base_row, "col": base_col},
            {"id": str(pins[1].get("id", "2")), "name": str(pins[1].get("name", "2")),
             "row": int(end.get("row", base_row)), "col": int(end.get("col", base_col))},
        ]
        return pin_points, []

    pin_points = []
    for pin in pins:
        if not isinstance(pin, dict):
            continue
        row, col = rotate_offset(
            int(pin.get("offsetRow", 0)), int(pin.get("offsetCol", 0)),
            rotation, max_row, max_col,
        )
        pin_points.append({
            "id": str(pin.get("id", "")), "name": str(pin.get("name", "")),
            "row": base_row + row, "col": base_col + col,
        })
    body_points = []
    for cell in body:
        if not isinstance(cell, dict):
            continue
        row, col = rotate_offset(
            int(cell.get("row", 0)), int(cell.get("col", 0)),
            rotation, max_row, max_col,
        )
        body_points.append((base_row + row, base_col + col))
    return pin_points, body_points
