"""Deterministic net-aware component placement for Route-Mate."""
from __future__ import annotations

import copy
import hashlib
from typing import Any

from adjacency import adjacency_conflicts, candidate_conflicts, hole_index
from placement_policy import is_off_board_component
from board_geometry import BUILTIN_DEFS, component_geometry, resolve_definition
from prepare.presolve import _orientation_intelligence

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
    saved_end = component.get("flexibleEndPos")
    if isinstance(saved_end, dict) and isinstance(component.get("boardPos"), dict):
        origin = component["boardPos"]
        probe["flexibleEndPos"] = {
            "row": int(saved_end["row"]) - int(origin["row"]),
            "col": int(saved_end["col"]) - int(origin["col"]),
        }
    else:
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


def _variant_rank(variant, *parts):
    """Stable seeded tie-break; independent of Python's randomized hash."""
    payload = "|".join(map(str, (variant, *parts))).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def _attempt(project, rows, cols, clearance, definitions, pending, pin_nets, placement_variant=0, forbidden_anchors=None):
    result = copy.deepcopy(project)
    components = result["components"]
    by_id = {str(c.get("id")): c for c in components if isinstance(c, dict)}
    occupied: set[tuple[int, int]] = set()
    blocked: set[tuple[int, int]] = set()
    net_points: dict[str, list[tuple[int, int]]] = {}
    initial_pin_records: list[tuple[int, int, str, str]] = []
    # A board with three-pin transistor packages benefits from reserving
    # a second copper escape hole: without one the middle pads get trapped.
    # Only placement choices change; electrical legality remains unchanged.
    protect_transistor_escapes = any(
        isinstance(part, dict)
        and str(part.get("defId")) in {"def-npn", "def-pmos"}
        and not is_off_board_component(part)
        for part in components
    )
    centres: list[tuple[int, int]] = []
    centre_row_sum = centre_col_sum = 0
    net_score = links_scored = 0
    errors = []

    for component in components:
        if not isinstance(component, dict):
            continue
        if is_off_board_component(component):
            if component.get("locked") is not True:
                continue  # Saved external pads are hints, not fixed placement constraints.
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
        # An edge-sliding lock is a hard edge constraint, not a fixed hole.
        # It will be placed as a movable candidate restricted to its
        # original side, with the original rotation and original nets.
        if component.get("edge") and component.get("slide") and isinstance(component.get("boardPos"), dict):
            continue
        label = str(component.get("label") or component.get("id") or "unnamed")
        if not isinstance(component.get("boardPos"), dict):
            errors.append(f"{label}: position-locked component has no board position")
            continue
        # A positioned locked part is immovable, regardless of its edge/slide
        # metadata. Validate and reserve its physical footprint below.
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
            # Edge-locked bodies may overhang; electrical pins must stay on board.
            pin_cells = {(int(p["row"]), int(p["col"])) for p in pins}
            if any(not (0 <= r < rows and 0 <= c < cols) for r, c in pin_cells):
                errors.append(f"{label}: locked footprint has pins outside the board")
                continue
            if not component.get("edge") and any(
                not (0 <= r < rows and 0 <= c < cols) for r, c in cells
            ):
                errors.append(f"{label}: locked footprint has pads/body outside the board")
                continue
            if component.get("edge") and not (
                min(r for r, c in cells) <= 0
                or max(r for r, c in cells) >= rows - 1
                or min(c for r, c in cells) <= 0
                or max(c for r, c in cells) >= cols - 1
            ):
                errors.append(f"{label}: fixed edge anchor does not touch any board edge")
                continue
            cells = {(r, c) for r, c in cells if 0 <= r < rows and 0 <= c < cols}
            if occupied.intersection(cells):
                errors.append(f"{label}: locked footprint overlaps another locked footprint")
                continue
            occupied.update(cells)
            blocked.update(_expanded(cells, clearance))
            pos = component["boardPos"]
            h, w = int(definition.get("height", 1)), int(definition.get("width", 1))
            if int(component.get("rotation", 0) or 0) % 360 in (90, 270):
                h, w = w, h
            centre = (2 * int(pos.get("row", 0)) + h - 1,
                      2 * int(pos.get("col", 0)) + w - 1)
            centres.append(centre)
            centre_row_sum += centre[0]
            centre_col_sum += centre[1]
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

    # Experimental strip-first variant: reserve one copper row per net where possible.
    strip_first = placement_variant in (99, 100)
    # Variant 100 preserves periodic full-width copper bus rows for routing.
    # Locked components remain authoritative; only movable parts avoid them.
    corridor_rows = set(range(3, rows - 2, 6)) if placement_variant == 100 else set()
    corridor_rows.difference_update(r for r, _ in occupied)
    net_rows = {}
    row_owners = {}
    for net, points in net_points.items():
        for row, _ in points:
            if row not in row_owners or row_owners[row] == net:
                net_rows.setdefault(net, row)
                row_owners[row] = net
                break

    ordered = sorted(pending, key=lambda x: (
        -x["degree"], -x["area"], x["label"].casefold(), x["id"]
    ))
    if placement_variant:
        # Alternative greedy order changes component positions, not router cuts.
        ordered = sorted(pending, key=lambda x: (
            -x["degree"], -x["area"], x["label"].casefold(), x["id"]
        ))
    if placement_variant >= 2:
        # Deterministic diversified greedy orders, not 98 repetitions of
        # the two baseline variants. Preserve the baseline scoring for 0/1.
        ordered = sorted(pending, key=lambda x: (
            -(x["degree"] if placement_variant % 2 else x["area"]),
            _variant_rank(placement_variant, "order", x["id"]),
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
        rotations = [current] if flexible or item["slide_side"] else (
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
            # Opposed multi-row pin banks must have a copper escape lane
            # outside their pins, rather than sitting flush against an edge.
            cols_for_row = {}
            rows_for_col = {}
            for pad in local_pins:
                pr, pc = int(pad["row"]), int(pad["col"])
                cols_for_row.setdefault(pr, set()).add(pc)
                rows_for_col.setdefault(pc, set()).add(pr)
            reserve_x = width >= 3 and sum(len(v) > 1 for v in cols_for_row.values()) >= 3
            reserve_y = height >= 3 and sum(len(v) > 1 for v in rows_for_col.values()) >= 3
            pin_min_c = min(int(p["col"]) for p in local_pins)
            pin_max_c = max(int(p["col"]) for p in local_pins)
            pin_min_r = min(int(p["row"]) for p in local_pins)
            pin_max_r = max(int(p["row"]) for p in local_pins)
            intelligence = _orientation_intelligence(
                local_pins, sorted(shape - {(int(p["row"]), int(p["col"])) for p in local_pins}),
                {pid: net for (cid, pid), net in pin_nets.items() if cid == item["id"]},
            )
            # Prefer fewer body-obstructed vertical jumper lanes and fewer
            # mandatory strip isolations only after electrical net distance.
            routing_cost = (len(intelligence["vertical_jumper_obstructed_columns"]),
                            intelligence["strip_cut_lower_bound"])
            for top in range(rows - height + 1):
                for left in range(cols - width + 1):
                    origin_r, origin_c = top - min_r, left - min_c
                    side = item["slide_side"]
                    if side is not None and not (
                        (side == "top" and top == 0)
                        or (side == "bottom" and top + height == rows)
                        or (side == "left" and left == 0)
                        or (side == "right" and left + width == cols)
                    ):
                        continue
                    if component.get("edge") and side is None and not (
                        top == 0 or left == 0
                        or top + height == rows or left + width == cols
                    ):
                        continue
                    if forbidden_anchors and (origin_r, origin_c, rotation) in forbidden_anchors.get(item["id"], ()):
                        continue
                    if reserve_x and (origin_c + pin_min_c < 2 or origin_c + pin_max_c >= cols - 2):
                        continue
                    if reserve_y and (origin_r + pin_min_r < 2 or origin_r + pin_max_r >= rows - 2):
                        continue
                    cells = {(origin_r + r, origin_c + c) for r, c in shape}
                    if blocked.intersection(cells):
                        continue
                    corridor_cost = sum(1 for r, _ in cells if r in corridor_rows)
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
                    # For boards containing three-pin transistors, prefer
                    # wider pin spacing throughout: copper escape lanes around
                    # their middle pins are readily trapped by later parts.
                    # This is a search constraint, not an electrical rule.
                    if protect_transistor_escapes and any(
                        existing_net != net
                        for row, col, net, _ref in pin_records
                        for dc in (-2, 2)
                        for existing_net, _existing_ref
                        in placed_holes.get((row, col + dc), ())
                    ):
                        continue

                    candidate_net_score = candidate_links = 0
                    same_strip_links = 0
                    shared_column_links = 0
                    for pin in pins:
                        nid = pin_nets.get((item["id"], pin["id"]))
                        prior = net_points.get(nid, []) if nid else []
                        if prior:
                            distance = min(abs(pin["row"] - r) + abs(pin["col"] - c)
                                           for r, c in prior)
                            candidate_net_score += distance
                            candidate_links += 1
                            if any(pin["row"] == r for r, c in prior):
                                same_strip_links += 1
                            if any(pin["col"] == c for r, c in prior):
                                shared_column_links += 1
                    centre_r2, centre_c2 = 2 * top + height - 1, 2 * left + width - 1
                    if centres:
                        n = len(centres)
                        compact = (abs(centre_r2 * n - centre_row_sum)
                                   + abs(centre_c2 * n - centre_col_sum))
                    else:
                        compact = abs(centre_r2 - (rows - 1)) + abs(centre_c2 - (cols - 1))
                    # Stripboard topology matters more than Euclidean closeness:
                    # same-row pins may share copper; same-column pins admit a
                    # direct vertical jumper (subject to subsequent clearance).
                    # Keep clearance and different-net adjacency as hard checks.
                    topology_score = (-same_strip_links, -shared_column_links,
                                      candidate_net_score, routing_cost, compact)
                    score = (
                        (routing_cost, topology_score) if placement_variant == 1
                        else (corridor_cost, topology_score) if placement_variant == 100
                        else topology_score,
                        abs(centre_r2 - (rows - 1)) + abs(centre_c2 - (cols - 1)),
                        (_variant_rank(placement_variant, item["id"], top, left, rotation)
                         if placement_variant >= 2 else top),
                        left, rotation_index,
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
        original_pos = component.get("boardPos")
        original_end = component.get("flexibleEndPos")
        component["boardPos"] = {"row": found["row"], "col": found["col"]}
        component["rotation"] = found["rotation"]
        if isinstance(original_pos, dict) and isinstance(original_end, dict):
            component["flexibleEndPos"] = {
                "row": found["row"] + int(original_end["row"]) - int(original_pos["row"]),
                "col": found["col"] + int(original_end["col"]) - int(original_pos["col"]),
            }
        else:
            component.pop("flexibleEndPos", None)
        occupied.update(found["cells"])
        blocked.update(_expanded(found["cells"], clearance))
        for row, col, net, ref in found["pin_records"]:
            placed_holes.setdefault((row, col), []).append((net, ref))
        centres.append(found["centre"])
        centre_row_sum += found["centre"][0]
        centre_col_sum += found["centre"][1]
        net_score += found["net_score"]
        links_scored += found["links"]
        for pin in found["pins"]:
            nid = pin_nets.get((item["id"], pin["id"]))
            if nid:
                net_points.setdefault(nid, []).append((pin["row"], pin["col"]))
    return result, [], net_score, links_scored



def _allocate_offboard_pads(project, definitions, pin_nets, rows, cols):
    """Allocate real board holes to external pins, without placing their bodies."""
    components = project["components"]
    used, net_holes, row_nets = set(), {}, {}
    for component in components:
        if not isinstance(component, dict):
            continue
        cid = str(component.get("id"))
        if is_off_board_component(component):
            if component.get("locked") is not True:
                component["leads"] = {}  # Reallocate all unlocked external pads each solve.
                continue
            for pid, point in (component.get("leads") or {}).items():
                hole = (int(point["row"]), int(point["col"]))
                if not (0 <= hole[0] < rows and 0 <= hole[1] < cols) or hole in used:
                    raise ValueError(f"{component.get('label', cid)} lead {pid}: invalid or duplicate board hole")
                used.add(hole)
                net = pin_nets.get((cid, str(pid)))
                if net:
                    net_holes.setdefault(net, []).append(hole)
                    row_nets.setdefault(hole[0], {})[hole[1]] = net
            continue
        if not isinstance(component.get("boardPos"), dict):
            continue
        definition = resolve_definition(component, definitions)
        if definition is None:
            continue
        pins, body = component_geometry(component, definition)
        used.update((int(p["row"]), int(p["col"])) for p in pins)
        used.update((int(r), int(c)) for r, c in body)
        for pin in pins:
            net = pin_nets.get((cid, str(pin["id"])))
            if net:
                hole = (int(pin["row"]), int(pin["col"]))
                net_holes.setdefault(net, []).append(hole)
                row_nets.setdefault(hole[0], {})[hole[1]] = net

    placed = 0
    for component in components:
        if not isinstance(component, dict) or not is_off_board_component(component):
            continue
        if component.get("boardExcluded") is True and component.get("offBoard") is not True:
            continue
        cid = str(component.get("id"))
        definition = resolve_definition(component, definitions)
        if definition is None:
            raise ValueError(f"{component.get('label', cid)}: no pin definition")
        leads = component.setdefault("leads", {})
        if not isinstance(leads, dict):
            raise ValueError(f"{component.get('label', cid)}: invalid leads")
        pin_ids = list(dict.fromkeys(str(p["id"]) for p in definition.get("pins", [])))
        for pid in pin_ids:
            if pid in leads:
                continue
            net = pin_nets.get((cid, pid))
            anchors = net_holes.get(net, []) if net else []
            group = [(int(p["row"]), int(p["col"])) for p in leads.values()]
            best = None
            for row in range(rows):
                for col in range(cols):
                    if (row, col) in used:
                        continue
                    neighbors = row_nets.get(row, {})
                    if net and any(neighbors.get(c) not in (None, net)
                                   for c in (col - 1, col, col + 1)):
                        continue
                    if not net and any(c in neighbors for c in (col - 1, col, col + 1)):
                        continue
                    same_row = 0 if any(row == r for r, _ in anchors) else 1
                    distance = min((abs(row-r)+abs(col-c) for r,c in anchors), default=0)
                    group_distance = min((abs(row-r)+abs(col-c) for r,c in group), default=0)
                    edge_distance = min(col, cols-1-col)
                    score = (same_row, distance, group_distance, edge_distance, row, col)
                    if best is None or score < best[0]:
                        best = (score, row, col)
            if best is None:
                raise ValueError(f"{component.get('label', cid)} pin {pid}: no free termination hole")
            _, row, col = best
            leads[pid] = {"row": row, "col": col}
            used.add((row, col))
            placed += 1
            if net:
                net_holes.setdefault(net, []).append((row, col))
                row_nets.setdefault(row, {})[col] = net
    return placed


def quick_fit(project: dict[str, Any], clearance: int = 1, *, placement_variant: int = 0, forbidden_anchors=None) -> dict[str, Any]:
    """Place components with deterministic net-aware scoring; never mutate input."""
    source = copy.deepcopy(project) if isinstance(project, dict) else {}
    if not isinstance(project, dict):
        return _failure("INCOMPLETE_GEOMETRY", source, ["project root must be an object"])
    board, components = source.get("board"), source.get("components")
    if not isinstance(board, dict) or not isinstance(components, list):
        return _failure("INCOMPLETE_GEOMETRY", source,
                        ["project needs a board object and components array"])
    if type(placement_variant) is not int or placement_variant < 0:
        return _failure("CONSTRAINT_CONFLICT", source,
                        ["placement_variant must be a non-negative integer"])
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
        # Locked + edge + slide means the original edge is retained but
        # position along that edge may change. A fixed lock without slide
        # remains an exact, immutable placement. Edge-only movable parts
        # are restricted to one of the four board edges.
        if component.get("slide") and not (
            component.get("locked") is True and isinstance(component.get("boardPos"), dict)
        ):
            geometry_errors.append(f"{label}: slide requires a positioned, locked anchor")
            continue
        if component.get("locked") is True and not isinstance(component.get("boardPos"), dict):
            geometry_errors.append(f"{label}: locked component has no boardPos")
            continue
        slide_side = None
        if component.get("locked") and component.get("slide") and component.get("edge"):
            pos = component["boardPos"]
            rotation = int(component.get("rotation", 0) or 0) % 360
            try:
                cells, _pins, _r, _c, _h, _w = _local_variant(component, definition, rotation)
                rr = [int(pos["row"]) + r for r, _ in cells]
                cc = [int(pos["col"]) + c for _, c in cells]
                if min(rr) == 0:
                    slide_side = "top"
                elif max(rr) == rows - 1:
                    slide_side = "bottom"
                elif min(cc) == 0:
                    slide_side = "left"
                elif max(cc) == cols - 1:
                    slide_side = "right"
            except (KeyError, ValueError, TypeError):
                pass
            if slide_side is None:
                geometry_errors.append(f"{label}: sliding anchor must already touch a board edge")
                continue
        # Already-positioned absolute locks remain fixed obstacles.
        if component.get("locked") is True and not (
            component.get("slide") and component.get("edge")
        ):
            continue
        pending.append({
            "id": cid, "label": label, "definition": definition,
            "area": width * height, "degree": 0, "slide_side": slide_side,
        })
    if geometry_errors:
        status = ("CONSTRAINT_CONFLICT" if any(
            phrase in error
            for error in geometry_errors
            for phrase in ("slide requires", "sliding anchor", "locked component")
        ) else "INCOMPLETE_GEOMETRY")
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
    # WR electrical assignments may use ordinal 1/2 for named a/k or +/- pads.
    # Normalise before placement and external termination-pad allocation.
    pin_aliases = {}
    for cid, component in component_by_id.items():
        definition = resolve_definition(component, definitions)
        if definition:
            pins = [p for p in definition.get("pins", []) if isinstance(p, dict)]
            pin_aliases[cid] = {str(i): str(p["id"]) for i, p in enumerate(pins, 1)}
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
            pid = pin_aliases.get(cid, {}).get(pid, pid)
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
            source, rows, cols, used, definitions, pending, pin_nets, placement_variant, forbidden_anchors
        )
        if placed_project is None:
            last_errors = errors
            continue
        try:
            termination_pads = _allocate_offboard_pads(
                placed_project, definitions, pin_nets, rows, cols
            )
        except (ValueError, TypeError, KeyError) as exc:
            last_errors = [str(exc)]
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
                "off_board_pads_allocated": termination_pads,
                "search": "deterministic greedy net-aware placement",
                "placement_variant": placement_variant,
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
