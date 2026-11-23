"""Independent raw-project pin/landing reconstruction for Hell Mode M1.

No imports from renderer, router or existing electrical/physical verifier.
Footprint rules are implemented separately to catch shared-model mistakes.
This does NOT establish component body clearance or measured wire geometry.
"""
from __future__ import annotations

from typing import Any


_OFFBOARD_ID = "custom-fd3b91be-3685-42db-acae-7e2ab9735565"
_TWO_PIN_SPACING = {
    "def-resistor": 4, "def-capacitor": 1, "def-cap-polarized": 1,
    "def-led": 1, "def-diode": 3, "def-zener": 3,
    "def-inductor": 4, "def-fuse": 5, "def-switch": 3,
}


def _builtin(def_id: str) -> dict[str, Any] | None:
    if def_id in _TWO_PIN_SPACING:
        spacing = _TWO_PIN_SPACING[def_id]
        return {
            "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0},
                     {"id": "2", "offsetRow": spacing, "offsetCol": 0}],
            "bodyCells": [], "flexible": def_id != "def-switch",
        }
    if def_id in ("def-npn", "def-pmos", "def-generic-3pin-compact"):
        return {"pins": [
            {"id": str(i + 1), "offsetRow": i, "offsetCol": 0}
            for i in range(3)], "bodyCells": []}
    if def_id == "def-generic-3pin-spaced":
        return {"pins": [
            {"id": str(i + 1), "offsetRow": i * 2, "offsetCol": 0}
            for i in range(3)], "bodyCells": []}
    if def_id == "def-pushbutton":
        return {
            "pins": [
                {"id": "1", "offsetRow": 0, "offsetCol": 0},
                {"id": "1", "offsetRow": 0, "offsetCol": 3},
                {"id": "2", "offsetRow": 2, "offsetCol": 0},
                {"id": "2", "offsetRow": 2, "offsetCol": 3},
            ],
            "bodyCells": [{"row": 1, "col": 3}],
        }
    if def_id == "def-555":
        count = 8
    elif def_id.startswith("def-ic-dip") and def_id[10:].isdigit():
        count = int(def_id[10:])
    else:
        count = None
    if count is not None and count % 2 == 0 and 4 <= count <= 40:
        side = count // 2
        pins = [{"id": str(i + 1), "offsetRow": i, "offsetCol": 0}
                for i in range(side)]
        pins.extend(
            {"id": str(side + i + 1), "offsetRow": side - 1 - i,
             "offsetCol": 3} for i in range(side))
        return {"pins": pins, "bodyCells": [
            {"row": side - 1, "col": 2}]}
    if def_id.startswith("def-connector-") and def_id[14:].isdigit():
        n = int(def_id[14:])
        if 1 <= n <= 20:
            return {"pins": [
                {"id": str(i + 1), "offsetRow": i, "offsetCol": 0}
                for i in range(n)], "bodyCells": []}
    if def_id.startswith("def-generic-2pin-") and def_id.endswith("h"):
        try:
            distance = int(def_id[len("def-generic-2pin-"):-1]) - 1
        except ValueError:
            return None
        if distance + 1 in (2, 3, 4, 5, 7):
            return {"pins": [
                {"id": "1", "offsetRow": 0, "offsetCol": 0},
                {"id": "2", "offsetRow": distance, "offsetCol": 0}],
                "bodyCells": []}
    return None


def _coordinate(value: Any, ref: str, rows: int, cols: int) -> tuple[int, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{ref}: missing coordinate object")
    row, col = value.get("row"), value.get("col")
    if type(row) is not int or type(col) is not int:
        raise ValueError(f"{ref}: row/col must be integers")
    if not (0 <= row < rows and 0 <= col < cols):
        raise ValueError(f"{ref}: hole ({row},{col}) outside board")
    return row, col


def _physical_pins(component: dict, definition: dict) -> list[dict]:
    pins = definition.get("pins") or []
    if not isinstance(pins, list) or not pins:
        raise ValueError("footprint has no pins")
    base = component.get("boardPos")
    if not isinstance(base, dict):
        raise ValueError("component is not placed")
    row, col = base.get("row"), base.get("col")
    if type(row) is not int or type(col) is not int:
        raise ValueError("boardPos requires integer coordinates")
    if len(pins) == 2 and (
        definition.get("flexible") or isinstance(component.get("flexibleEndPos"), dict)
    ):
        end = component.get("flexibleEndPos")
        if end is None:
            end = {"row": row + int(pins[1].get("offsetRow", 0)),
                   "col": col + int(pins[1].get("offsetCol", 0))}
        if not isinstance(end, dict):
            raise ValueError("flexibleEndPos must be an object")
        return [
            {"id": str(pins[0]["id"]), "row": row, "col": col},
            {"id": str(pins[1]["id"]), "row": end.get("row"), "col": end.get("col")},
        ]

    body = definition.get("bodyCells") or []
    offsets = [(int(p.get("offsetRow", 0)), int(p.get("offsetCol", 0)))
               for p in pins]
    offsets.extend((int(p.get("row", 0)), int(p.get("col", 0)))
                   for p in body)
    high_row = max((r for r, c in offsets), default=0)
    high_col = max((c for r, c in offsets), default=0)
    rotation = int(component.get("rotation", 0) or 0) % 360
    if rotation not in (0, 90, 180, 270):
        raise ValueError(f"unsupported rotation {rotation}")

    out = []
    for p in pins:
        dr = int(p.get("offsetRow", 0))
        dc = int(p.get("offsetCol", 0))
        if rotation == 90:
            dr, dc = dc, high_row - dr
        elif rotation == 180:
            dr, dc = high_row - dr, high_col - dc
        elif rotation == 270:
            dr, dc = high_col - dc, dr
        out.append({"id": str(p["id"]), "row": row + dr, "col": col + dc})
    return out


def collect_pad_holes(project: dict[str, Any]) -> dict[str, Any]:
    """Return all physical pads and assigned terminals from the raw input.

    offBoard leads are explicit termination pads, except boardExcluded-only
    components, which represent deliberately non-mounted items.
    """
    board = project["board"]
    rows, cols = board["rows"], board["cols"]
    definitions = {
        str(x["id"]): x for x in project.get("componentDefs", [])
        if isinstance(x, dict) and x.get("id")
    }
    components = {
        str(x["id"]): x for x in project.get("components", [])
        if isinstance(x, dict) and x.get("id") is not None
    }
    assignments: dict[tuple[str, str], str] = {}
    errors: list[str] = []
    for index, x in enumerate(project.get("netAssignments", [])):
        if not isinstance(x, dict) or not all(
            x.get(k) is not None for k in ("componentId", "pinId", "netId")
        ):
            errors.append(f"assignment[{index}]: missing componentId/pinId/netId")
            continue
        key = str(x["componentId"]), str(x["pinId"])
        if key in assignments:
            errors.append(f"duplicate assignment {key}")
        elif key[0] not in components:
            errors.append(f"unknown component {key[0]}")
        else:
            assignments[key] = str(x["netId"])

    pads: list[dict[str, Any]] = []
    visited: set[tuple[str, str]] = set()
    for cid, component in components.items():
        label = str(component.get("label") or cid)
        offboard = (component.get("offBoard") is True
                    or component.get("boardExcluded") is True
                    or str(component.get("defId") or component.get("componentDefId"))
                    == _OFFBOARD_ID)
        if component.get("boardExcluded") is True and component.get("offBoard") is not True:
            continue
        if offboard:
            leads = component.get("leads") or {}
            for (aid, pid), net in assignments.items():
                if aid != cid:
                    continue
                if pid not in leads:
                    errors.append(f"{label}.{pid}: missing offboard termination pad")
                    continue
                try:
                    r, c = _coordinate(leads[pid], label + "." + pid, rows, cols)
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                pads.append({"row": r, "col": c, "net_id": net,
                             "ref": f"{label}.{pid}"})
                visited.add((cid, pid))
            for pid, point in leads.items():
                if (cid, str(pid)) in visited:
                    continue
                try:
                    r, c = _coordinate(point, label + "." + str(pid), rows, cols)
                    pads.append({"row": r, "col": c, "net_id": None,
                                 "ref": f"{label}.{pid}"})
                except ValueError as exc:
                    errors.append(str(exc))
            continue

        def_id = str(component.get("defId") or component.get("componentDefId") or "")
        base = definitions.get(def_id) or _builtin(def_id)
        override = component.get("footprintOverride")
        if not isinstance(base, dict) and isinstance(override, dict):
            base = override
        if not isinstance(base, dict):
            errors.append(f"{label}: unknown footprint {def_id}")
            continue
        definition = dict(base)
        if isinstance(override, dict):
            for key in ("pins", "bodyCells", "width", "height"):
                if key in override:
                    definition[key] = override[key]
        try:
            points = _physical_pins(component, definition)
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(f"{label}: {exc}")
            continue
        pin_defs = definition["pins"]
        for (aid, pid), net in assignments.items():
            if aid != cid:
                continue
            equivalent_id = pid
            if not any(p["id"] == equivalent_id for p in points) and pid.isdecimal():
                ordinal = int(pid) - 1
                if 0 <= ordinal < len(pin_defs):
                    equivalent_id = str(pin_defs[ordinal].get("id"))
            if not any(p["id"] == equivalent_id for p in points):
                errors.append(f"{label}.{pid}: assigned pin absent from footprint")
            else:
                visited.add((cid, pid))
        assigned_by_pin: dict[str, str] = {}
        for (aid, pid), net in assignments.items():
            if aid != cid or (cid, pid) not in visited:
                continue
            equivalent_id = pid
            if not any(p["id"] == equivalent_id for p in points) and pid.isdecimal():
                equivalent_id = str(pin_defs[int(pid) - 1].get("id"))
            if equivalent_id in assigned_by_pin and assigned_by_pin[equivalent_id] != net:
                errors.append(f"{label}: contradictory aliases for pin {equivalent_id}")
            assigned_by_pin[equivalent_id] = net
        for item in points:
            try:
                r, c = _coordinate(item, label + "." + item["id"], rows, cols)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            pads.append({
                "row": r, "col": c, "net_id": assigned_by_pin.get(item["id"]),
                "ref": f"{label}.{item['id']}",
            })
    return {
        "pads": pads,
        "terminals": [p for p in pads if p["net_id"] is not None],
        "errors": errors,
    }


__all__ = ["collect_pad_holes"]
