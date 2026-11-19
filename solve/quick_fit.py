"""Deterministic net-aware component placement for Route-Mate."""
from __future__ import annotations

import copy
from typing import Any

from adjacency import adjacency_conflicts, candidate_conflicts, hole_index
from placement_policy import is_off_board_component
from board_geometry import BUILTIN_DEFS, component_geometry, resolve_definition

_ROTATIONS = (0, 90, 180, 270)


def _expanded(cells: set[tuple[int, int]], clearance: int) -> set[tuple[int, int]]:
    return {
        (row + dr, col + dc)
        for row, col in cells
        for dr in range(-clearance, clearance + 1)
        for dc in range(-clearance, clearance + 1)
    }


def _local_variant(component: dict, definition: dict, rotation: int):
    probe = dict(component)
    probe["boardPos"] = {"row": 0, "col": 0}
    probe["rotation"] = rotation
    probe.pop("flexibleEndPos", None)
    pins, body = component_geometry(probe, definition)
    cells = {(int(p["row"]), int(p["col"])) for p in pins}
    cells.update((int(r), int(c)) for r, c in body)
    if not cells:
        raise ValueError("footprint has no physical cells")
    min_r = min(r for r, _ in cells)
    min_c = min(c for _, c in cells)
    max_r = max(r for r, _ in cells)
    max_c = max(c for _, c in cells)
    height, width = int(definition.get("height", 0)), int(definition.get("width", 0))
    if height < 1 or width < 1:
        raise ValueError("footprint dimensions must be positive integers")
    if rotation in (90, 270):
        height, width = width, height
    height = max(height, max_r + 1) - min_r
    width = max(width, max_c + 1) - min_c
    if height < 1 or width < 1:
        raise ValueError("invalid rotated footprint bounds")
    return cells, pins, min_r, min_c, height, width


def _failure(status: str, project: dict, errors: list[str]) -> dict[str, Any]:
    return {
        "status": status, "project": project, "errors": errors, "warnings": [],
        "placed": 0,
        "excluded": sum(1 for c in project.get("components", [])
                        if isinstance(c, dict) and is_off_board_component(c)),
    }


def _offboard_lead_records(component: dict, pin_nets: dict) -> list[tuple[int, int, str, str]]:
    """Resolve saved off-board lead holes into assigned physical pin records."""
    cid = str(component.get("id"))
    label = str(component.get("label") or cid)
    leads = component.get("leads")
    if not isinstance(leads, dict):
        return []
    records = []
    for pin_id, point in leads.items():
        net = pin_nets.get((cid, str(pin_id)))
        if net is None:
            continue
        if not isinstance(point, dict) or type(point.get("row")) is not int or type(point.get("col")) is not int:
            raise ValueError(f"{label} lead {pin_id}: invalid saved lead coordinate")
        records.append((point["row"], point["col"], net, f"{label}.{pin_id}"))
    return records


def _attempt(project, rows, cols, clearance, definitions, pending, pin_nets):
    result = copy.deepcopy(project)
    components = result["components"]
    by_id = {str(c.get("id")): c for c in components if isinstance(c, dict)}
    occupied: set[tuple[int, int]] = set()
    blocked: set[tuple[int, int]] = set()
    net_points: dict[str, list[tuple[int, int]]] = {}
    initial_pin_records: list[tuple[int, int, str, str]] = []
    centres: list[tuple[int, int]] = []
    net_score = links_scored = 0
    errors = []

    for component in components:
        if not isinstance(component, dict):
            continue
        if is_off_board_component(component):
            try:
                lead_records = _offboard_lead_records(component, pin_nets)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            for row, col, net, ref in lead_records:
                if not (0 <= row < rows and 0 <= col < cols):
                    errors.append(f"{ref}: lead hole {(row, col)} outside board")
                    continue
                initial_pin_records.append((row, col, net, ref))
                occupied.add((row, col))
                blocked.add((row, col))
                net_points.setdefault(net, []).append((row, col))
            continue
        if component.get("locked") is not True:
            continue
        label = str(component.get("label") or component.get("id") or "unnamed")
        if not isinstance(component.get("boardPos"), dict):
            errors.append(f"{label}: position-locked component has no board position")
            continue
        if component.get("edge") or component.get("slide"):
            errors.append(f"{label}: edge-anchor/sliding constraints are not yet supported")
            continue
        definition = resolve_definition(component, definitions)
        if definition is None:
            errors.append(f"{label}: no footprint definition")
            continue
        try:
            pins, body = component_geometry(component, definition)
            cells = {(int(p["row"]), int(p["col"])) for p in pins}
            cells.update((int(r), int(c)) for r, c in body)
            if not cells:
                raise ValueError("footprint has no physical cells")
            if any(not (0 <= r < rows and 0 <= c < cols) for r, c in cells):
                errors.append(f"{label}: locked footprint has pads/body outside the board")
                continue
            if occupied.intersection(cells):
                errors.append(f"{label}: locked footprint overlaps another locked footprint")
                continue
            occupied.update(cells)
            blocked.update(_expanded(cells, clearance))
            pos = component["boardPos"]
            h, w = int(definition.get("height", 1)), int(definition.get("width", 1))
            if int(component.get("rotation", 0) or 0) % 360 in (90, 270):
                h, w = w, h
            centres.append((2 * int(pos.get("row", 0)) + h - 1,
                            2 * int(pos.get("col", 0)) + w - 1))
            cid = str(component.get("id"))
            for pin in pins:
                nid = pin_nets.get((cid, str(pin.get("id"))))
                if nid is not None:
                    row, col = int(pin["row"]), int(pin["col"])
                    initial_pin_records.append((row, col, nid, f"{label}.{pin.get('id')}"))
                    net_points.setdefault(nid, []).append((row, col))
        except (TypeError, ValueError, KeyError) as exc:
            errors.append(f"{label}: invalid locked footprint: {exc}")
    if errors:
        return None, errors, net_score, links_scored

    placed_holes = hole_index(initial_pin_records)
    initial_conflicts = adjacency_conflicts(initial_pin_records)
    if initial_conflicts:
        errors.extend(
            f"{item['kind']} different-net pin conflict at row {item['row']} "
            f"columns {item['cols']}: {item['refs'][0]} ({item['nets'][0]}) / "
            f"{item['refs'][1]} ({item['nets'][1]})"
            for item in initial_conflicts
        )
        return None, errors, net_score, links_scored

    ordered = sorted(pending, key=lambda x: (
        -x["area"], -x["degree"], x["label"].casefold(), x["id"]
    ))
    for item in ordered:
        component = by_id[item["id"]]
        found = None
        try:
            current = int(component.get("rotation", 0) or 0) % 360
        except (TypeError, ValueError):
            current = 0
        if current not in _ROTATIONS:
            current = 0
        # Flexible two-lead parts use an explicit endpoint model; the shared
        # geometry helper does not rotate that model, so keep their saved angle.
        flexible = bool(item["definition"].get("flexible")) or (
            len(item["definition"].get("pins", [])) == 2
            and isinstance(component.get("flexibleEndPos"), dict)
        )
        rotations = [current] if flexible else (
            [current] + [r for r in _ROTATIONS if r != current]
        )

        for rotation_index, rotation in enumerate(rotations):
            try:
                shape, local_pins, min_r, min_c, height, width = _local_variant(
                    component, item["definition"], rotation
                )
            except (TypeError, ValueError, KeyError) as exc:
                errors.append(f"{item['label']}: invalid footprint geometry: {exc}")
                break
            if height > rows or width > cols:
                continue
            for top in range(rows - height + 1):
                for left in range(cols - width + 1):
                    origin_r, origin_c = top - min_r, left - min_c
                    cells = {(origin_r + r, origin_c + c) for r, c in shape}
                    if blocked.intersection(cells):
                        continue
                    pins = [{
                        "id": str(p.get("id", "")),
                        "row": origin_r + int(p["row"]),
                        "col": origin_c + int(p["col"]),
                    } for p in local_pins]
                    pin_records = []
                    for pin in pins:
                        nid = pin_nets.get((item["id"], pin["id"]))
                        if nid is not None:
                            pin_records.append((pin["row"], pin["col"], nid,
                                                f"{item['label']}.{pin['id']}"))
                    if candidate_conflicts(pin_records, placed_holes):
                        continue

                    candidate_net_score = candidate_links = 0
                    for pin in pins:
                        nid = pin_nets.get((item["id"], pin["id"]))
                        prior = net_points.get(nid, []) if nid else []
                        if prior:
                            distance = min(abs(pin["row"] - r) + abs(pin["col"] - c)
                                           for r, c in prior)
                            candidate_net_score += distance
                            candidate_links += 1
                    centre_r2, centre_c2 = 2 * top + height - 1, 2 * left + width - 1
                    if centres:
                        n = len(centres)
                        compact = (abs(centre_r2 * n - sum(p[0] for p in centres))
                                   + abs(centre_c2 * n - sum(p[1] for p in centres)))
                    else:
                        compact = abs(centre_r2 - (rows - 1)) + abs(centre_c2 - (cols - 1))
                    score = (
                        candidate_net_score, compact,
                        abs(centre_r2 - (rows - 1)) + abs(centre_c2 - (cols - 1)),
                        top, left, rotation_index,
                    )
                    if found is None or score < found["score"]:
                        found = {
                            "score": score, "row": origin_r, "col": origin_c,
                            "rotation": rotation, "cells": cells, "pins": pins,
                            "pin_records": pin_records,
                            "centre": (centre_r2, centre_c2),
                            "net_score": candidate_net_score, "links": candidate_links,
                        }
        if found is None:
            if not errors:
                errors.append(
                    f"{item['label']}: no placement found on {rows}x{cols} board "
                    f"with {clearance}-hole clearance"
                )
            return None, errors, net_score, links_scored
        component["boardPos"] = {"row": found["row"], "col": found["col"]}
        component["rotation"] = found["rotation"]
        component.pop("flexibleEndPos", None)
        occupied.update(found["cells"])
        blocked.update(_expanded(found["cells"], clearance))
        for row, col, net, ref in found["pin_records"]:
            placed_holes.setdefault((row, col), []).append((net, ref))
        centres.append(found["centre"])
        net_score += found["net_score"]
        links_scored += found["links"]
        for pin in found["pins"]:
            nid = pin_nets.get((item["id"], pin["id"]))
            if nid:
                net_points.setdefault(nid, []).append((pin["row"], pin["col"]))
    return result, [], net_score, links_scored


def quick_fit(project: dict[str, Any], clearance: int = 1) -> dict[str, Any]:
    """Place components with deterministic net-aware scoring; never mutate input."""
    source = copy.deepcopy(project) if isinstance(project, dict) else {}
    if not isinstance(project, dict):
        return _failure("INCOMPLETE_GEOMETRY", source, ["project root must be an object"])
    board, components = source.get("board"), source.get("components")
    if not isinstance(board, dict) or not isinstance(components, list):
        return _failure("INCOMPLETE_GEOMETRY", source,
                        ["project needs a board object and components array"])
    if type(clearance) is not int or clearance < 0:
        return _failure("CONSTRAINT_CONFLICT", source,
                        ["clearance must be a non-negative integer"])
    try:
        rows, cols = int(board["rows"]), int(board["cols"])
        if rows < 1 or cols < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return _failure("CONSTRAINT_CONFLICT", source,
                        ["board rows and cols must be positive integers"])

    definitions = dict(BUILTIN_DEFS)
    definitions.update({str(d["id"]): d for d in source.get("componentDefs", [])
                        if isinstance(d, dict) and d.get("id")})
    component_by_id = {str(c.get("id")): c for c in components
                       if isinstance(c, dict) and c.get("id")}
    pending, geometry_errors = [], []
    for component in components:
        if not isinstance(component, dict) or is_off_board_component(component):
            continue
        label, cid = str(component.get("label") or component.get("id") or "unnamed"), str(component.get("id") or "")
        definition = resolve_definition(component, definitions)
        if definition is None:
            geometry_errors.append(f"{label}: no footprint definition")
            continue
        try:
            width, height = definition.get("width"), definition.get("height")
            if type(width) is not int or type(height) is not int or width < 1 or height < 1:
                raise ValueError("footprint width and height must be positive integers")
            if not isinstance(definition.get("pins"), list) or not definition["pins"]:
                raise ValueError("footprint has no pin geometry")
            _local_variant(component, definition, 0)
        except (TypeError, ValueError, KeyError) as exc:
            geometry_errors.append(f"{label}: {exc}")
            continue
        if component.get("edge") or component.get("slide"):
            geometry_errors.append(f"{label}: edge-anchor/sliding constraints are not yet supported")
            continue
        # Already-positioned locked parts are fixed obstacles, not candidates.
        if component.get("locked") is True and isinstance(component.get("boardPos"), dict):
            continue
        pending.append({
            "id": cid, "label": label, "definition": definition,
            "area": width * height, "degree": 0,
        })
    if geometry_errors:
        status = ("CONSTRAINT_CONFLICT" if any("edge-anchor/sliding" in e
                  for e in geometry_errors) else "INCOMPLETE_GEOMETRY")
        return _failure(status, source, geometry_errors)

    assignments = source.get("netAssignments")
    if not isinstance(assignments, list):
        return _failure("INCOMPLETE_GEOMETRY", source,
                        ["project netAssignments must be an array for net-aware placement"])
    pending_by_id = {item["id"]: item for item in pending}
    pin_ids = {}
    for cid, component in component_by_id.items():
        definition = resolve_definition(component, definitions)
        if definition:
            pin_ids[cid] = {str(p.get("id")) for p in definition.get("pins", [])
                            if isinstance(p, dict)}
    pin_nets, net_degrees = {}, {}
    for index, assignment in enumerate(assignments):
        if not isinstance(assignment, dict):
            return _failure("INCOMPLETE_GEOMETRY", source,
                            [f"netAssignments[{index}] must be an object"])
        cid, pid, nid = (str(assignment.get(k, "")) for k in
                         ("componentId", "pinId", "netId"))
        if cid not in component_by_id:
            return _failure("INCOMPLETE_GEOMETRY", source,
                            [f"netAssignments[{index}] references unknown component {cid!r}"])
        if pid not in pin_ids.get(cid, set()):
            return _failure("INCOMPLETE_GEOMETRY", source,
                            [f"netAssignments[{index}] references missing pin {cid}.{pid}"])
        if (cid, pid) in pin_nets and pin_nets[(cid, pid)] != nid:
            return _failure("INCOMPLETE_GEOMETRY", source,
                            [f"component {cid} pin {pid} is assigned to multiple nets"])
        pin_nets[(cid, pid)] = nid
        if cid in pending_by_id:
            net_degrees[nid] = net_degrees.get(nid, 0) + 1
            pending_by_id[cid]["degree"] += 1

    requested, last_errors = clearance, []
    for used in range(requested, -1, -1):
        placed_project, errors, net_score, links = _attempt(
            source, rows, cols, used, definitions, pending, pin_nets
        )
        if placed_project is None:
            last_errors = errors
            continue
        placed = sum(1 for c in placed_project["components"]
                     if isinstance(c, dict) and not is_off_board_component(c)
                     and isinstance(c.get("boardPos"), dict))
        excluded = sum(1 for c in placed_project["components"]
                       if isinstance(c, dict) and is_off_board_component(c))
        warnings = []
        if used < requested:
            warnings.append(
                f"requested {requested}-hole clearance could not fit all components; "
                f"complete placement used {used}-hole clearance"
            )
        return {
            "status": "PLACED", "project": placed_project, "errors": [],
            "warnings": warnings, "placed": placed, "excluded": excluded,
            "report": {
                "board": {"rows": rows, "cols": cols},
                "clearance_requested": requested, "clearance_used": used,
                "net_distance_score": net_score, "net_links_scored": links,
                "search": "deterministic greedy net-aware placement",
            },
        }
    result = _failure("NO_FIT_FOUND", source,
                      last_errors or [f"no complete placement found on {rows}x{cols} board"])
    result["report"] = {
        "board": {"rows": rows, "cols": cols},
        "clearance_requested": requested,
        "search": "deterministic greedy net-aware placement",
        "note": "NO_FIT_FOUND is not proof that the board is physically impossible",
    }
    return result


__all__ = ["quick_fit"]
