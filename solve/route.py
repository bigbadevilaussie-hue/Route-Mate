"""Deterministic first-pass stripboard copper router.

This router handles horizontal strip copper, between/hole cuts and jumper
wires. It preserves existing manual routing and verifies the completed model.
It does not yet model the physical path or crossing of jumper wire bodies.
"""
from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any

from placement_policy import is_off_board_component
from board_geometry import BUILTIN_DEFS, component_geometry, resolve_definition
from .verify import verify_project


class _UnionFind:
    def __init__(self):
        self.parent: dict[tuple[int, int], tuple[int, int]] = {}

    def find(self, point: tuple[int, int]) -> tuple[int, int]:
        self.parent.setdefault(point, point)
        root = point
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[point] != point:
            parent = self.parent[point]
            self.parent[point] = root
            point = parent
        return root

    def union(self, left: tuple[int, int], right: tuple[int, int]) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def _coordinate(value: Any, context: str) -> tuple[int, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{context}: coordinate must be an object")
    row, col = value.get("row"), value.get("col")
    if type(row) is not int or type(col) is not int:
        raise ValueError(f"{context}: coordinate needs integer row and col")
    return row, col


def _terminals(project: dict, rows: int, cols: int) -> list[tuple[int, int, str, str]]:
    components = project.get("components")
    assignments = project.get("netAssignments")
    if not isinstance(components, list) or not isinstance(assignments, list):
        raise ValueError("project needs components and netAssignments")

    definitions = dict(BUILTIN_DEFS)
    definitions.update({
        str(item.get("id")): item
        for item in (project.get("componentDefs") or [])
        if isinstance(item, dict) and item.get("id")
    })
    by_id = {
        str(item.get("id")): item
        for item in components
        if isinstance(item, dict) and item.get("id") is not None
    }
    pin_cache: dict[str, list[dict]] = {}
    records: list[tuple[int, int, str, str]] = []
    seen_assignments: set[tuple[str, str]] = set()

    for index, assignment in enumerate(assignments):
        if not isinstance(assignment, dict):
            raise ValueError(f"netAssignments[{index}] must be an object")
        cid = str(assignment.get("componentId", ""))
        pid = str(assignment.get("pinId", ""))
        nid = str(assignment.get("netId", ""))
        if not cid or not pid or not nid:
            raise ValueError(f"netAssignments[{index}] needs componentId, pinId and netId")
        terminal_id = (cid, pid)
        if terminal_id in seen_assignments:
            raise ValueError(f"duplicate physical assignment for {cid} pin {pid}")
        seen_assignments.add(terminal_id)

        component = by_id.get(cid)
        if component is None:
            raise ValueError(f"assignment[{index}] references unknown component {cid!r}")
        label = str(component.get("label") or cid)

        if is_off_board_component(component):
            leads = component.get("leads")
            lead = leads.get(pid) if isinstance(leads, dict) else None
            if lead is None:
                continue
            points = [_coordinate(lead, f"{label} lead {pid}")]
        else:
            if not isinstance(component.get("boardPos"), dict):
                raise ValueError(f"{label}: assigned terminal has no board position")
            if cid not in pin_cache:
                definition = resolve_definition(component, definitions)
                if definition is None:
                    raise ValueError(f"{label}: no footprint definition")
                pins, _body = component_geometry(component, definition)
                pin_cache[cid] = pins
            matches = [pin for pin in pin_cache[cid] if str(pin.get("id")) == pid]
            if not matches:
                raise ValueError(f"{label}: pin {pid!r} has no physical pads")
            points = [(int(pin["row"]), int(pin["col"])) for pin in matches]

        for pad_index, (row, col) in enumerate(points, 1):
            if not (0 <= row < rows and 0 <= col < cols):
                raise ValueError(f"{label} pin {pid}: hole {(row, col)} outside board")
            ref = f"{label}.{pid}" if len(points) == 1 else f"{label}.{pid}[{pad_index}]"
            records.append((row, col, nid, ref))
    if not records:
        raise ValueError("no assigned physical terminals are available to route")
    return records


def _routing_sets(board: dict, rows: int, cols: int):
    cuts = board.get("cuts") or []
    wires = board.get("wires") or []
    if not isinstance(cuts, list):
        raise ValueError("board.cuts must be a list")
    if not isinstance(wires, list):
        raise ValueError("board.wires must be a list")

    boundaries: set[tuple[int, int]] = set()
    isolated: set[tuple[int, int]] = set()
    for index, cut in enumerate(cuts):
        if not isinstance(cut, dict):
            raise ValueError(f"cut[{index}] must be an object")
        point = _coordinate(cut, f"cut[{index}]")
        kind = cut.get("kind", "between")
        if kind == "below":
            raise ValueError(
                f"cut[{index}]: vertical below cuts are not supported on plain stripboard"
            )
        if kind not in ("between", "hole"):
            raise ValueError(f"cut[{index}]: unsupported cut kind {kind!r}")
        row, col = point
        if not (0 <= row < rows and 0 <= col < cols):
            raise ValueError(f"cut[{index}]: outside board at {point}")
        if kind == "between":
            if col >= cols - 1:
                raise ValueError(f"cut[{index}]: between cut has no hole to its right")
            boundaries.add(point)
        else:
            isolated.add(point)

    checked_wires: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for index, wire in enumerate(wires):
        if not isinstance(wire, dict):
            raise ValueError(f"wire[{index}] must be an object")
        start = _coordinate(wire.get("from"), f"wire[{index}].from")
        end = _coordinate(wire.get("to"), f"wire[{index}].to")
        for point in (start, end):
            if not (0 <= point[0] < rows and 0 <= point[1] < cols):
                raise ValueError(f"wire[{index}]: endpoint {point} outside board")
        checked_wires.append((start, end))
    return cuts, wires, boundaries, isolated, checked_wires


def _copper_groups(
    rows: int,
    cols: int,
    boundaries: set[tuple[int, int]],
    isolated: set[tuple[int, int]],
    wires: list[tuple[tuple[int, int], tuple[int, int]]],
) -> _UnionFind:
    groups = _UnionFind()
    for row in range(rows):
        for col in range(cols):
            groups.find((row, col))
    for row in range(rows):
        for col in range(cols - 1):
            left, right = (row, col), (row, col + 1)
            if (row, col) not in boundaries and left not in isolated and right not in isolated:
                groups.union(left, right)
    for start, end in wires:
        groups.union(start, end)
    return groups


def _new_wire_id(existing: list[dict], serial: int) -> tuple[str, int]:
    used = {str(item.get("id")) for item in existing if isinstance(item, dict) and item.get("id") is not None}
    while f"RM-W{serial:03d}" in used:
        serial += 1
    return f"RM-W{serial:03d}", serial + 1


def route_copper(project: Any) -> dict[str, Any]:
    """Add cuts and jumpers to a placed project, then run the independent verifier.

    Existing cuts and wires are preserved. The source project is never mutated.
    Returns ROUTED only when solve.verify.verify_project reports PASS.
    """
    if not isinstance(project, dict):
        return {
            "status": "INVALID_INPUT", "project": copy.deepcopy(project),
            "errors": ["project root must be an object"], "warnings": [],
            "cuts_added": 0, "wires_added": 0, "verification": None,
        }

    result = copy.deepcopy(project)
    board = result.get("board")
    if not isinstance(board, dict):
        return {
            "status": "INVALID_INPUT", "project": result,
            "errors": ["project needs a board object"], "warnings": [],
            "cuts_added": 0, "wires_added": 0, "verification": None,
        }

    try:
        rows, cols = int(board["rows"]), int(board["cols"])
        if rows < 1 or cols < 1:
            raise ValueError
        records = _terminals(result, rows, cols)
        cuts, wires, boundaries, isolated, checked_wires = _routing_sets(board, rows, cols)
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "status": "INVALID_INPUT", "project": copy.deepcopy(project),
            "errors": [str(exc)], "warnings": [],
            "cuts_added": 0, "wires_added": 0, "verification": None,
        }

    # A single physical hole cannot carry two different nets. No cut can
    # separate two terminals soldered into the same hole.
    nets_by_hole: dict[tuple[int, int], set[str]] = defaultdict(set)
    refs_by_hole: dict[tuple[int, int], list[str]] = defaultdict(list)
    for row, col, net, ref in records:
        nets_by_hole[(row, col)].add(net)
        refs_by_hole[(row, col)].append(ref)
    collisions = [
        (point, sorted(nets), refs_by_hole[point])
        for point, nets in nets_by_hole.items() if len(nets) > 1
    ]
    if collisions:
        errors = [
            f"different nets share hole {point}: {', '.join(refs)} ({', '.join(nets)})"
            for point, nets, refs in sorted(collisions)
        ]
        return {
            "status": "ROUTING_FAILED", "project": copy.deepcopy(project),
            "errors": errors, "warnings": [],
            "cuts_added": 0, "wires_added": 0, "verification": None,
        }

    # Partition each strip wherever consecutive assigned terminal groups
    # belong to different nets. Reuse any existing cut that already separates
    # the two terminal positions.
    by_row: dict[int, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row, col, net, _ref in records:
        by_row[row][col].add(net)

    new_cuts: list[dict[str, Any]] = []
    for row in sorted(by_row):
        positions = sorted(by_row[row])
        for left_col, right_col in zip(positions, positions[1:]):
            left_nets = by_row[row][left_col]
            right_nets = by_row[row][right_col]
            if left_nets == right_nets:
                continue
            already_separated = (
                any((row, boundary) in boundaries
                    for boundary in range(left_col, right_col))
                or any((row, col) in isolated
                       for col in range(left_col, right_col + 1))
            )
            if not already_separated:
                cut = {"row": row, "col": left_col, "kind": "between"}
                new_cuts.append(cut)
                boundaries.add((row, left_col))

    all_cuts = cuts + new_cuts
    groups = _copper_groups(rows, cols, boundaries, isolated, checked_wires)

    # Existing jumpers may already connect some same-net strip segments.
    # They may not connect different nets; cuts cannot repair a jumper short.
    nets_by_group: dict[tuple[int, int], set[str]] = defaultdict(set)
    terminals_by_net: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for row, col, net, _ref in records:
        root = groups.find((row, col))
        nets_by_group[root].add(net)
        terminals_by_net[net].append((row, col))
    shorts = [(root, sorted(nets)) for root, nets in nets_by_group.items() if len(nets) > 1]
    if shorts:
        errors = [
            f"existing copper still shorts different nets at group {root}: {', '.join(nets)}"
            for root, nets in sorted(shorts)
        ]
        return {
            "status": "ROUTING_FAILED", "project": copy.deepcopy(project),
            "errors": errors, "warnings": [],
            "cuts_added": len(new_cuts), "wires_added": 0, "verification": None,
        }

    # For each net, connect its remaining copper groups with a deterministic
    # Manhattan minimum spanning tree. Wire bodies/crossings are not yet modeled.
    wires_added: list[dict[str, Any]] = []
    serial = 1
    for net in sorted(terminals_by_net):
        representatives: dict[tuple[int, int], tuple[int, int]] = {}
        for point in sorted(set(terminals_by_net[net])):
            root = groups.find(point)
            representatives[root] = min(point, representatives.get(root, point))
        points = sorted(representatives.values())
        if len(points) < 2:
            continue

        connected = {0}
        remaining = set(range(1, len(points)))
        while remaining:
            candidates = []
            for left_index in sorted(connected):
                left = points[left_index]
                for right_index in sorted(remaining):
                    right = points[right_index]
                    distance = abs(left[0] - right[0]) + abs(left[1] - right[1])
                    candidates.append((distance, left, right, left_index, right_index))
            _distance, start, end, _left_index, chosen = min(candidates)
            wire_id, serial = _new_wire_id(wires + wires_added, serial)
            wire = {
                "id": wire_id,
                "from": {"row": start[0], "col": start[1]},
                "to": {"row": end[0], "col": end[1]},
            }
            wires_added.append(wire)
            groups.union(start, end)
            connected.add(chosen)
            remaining.remove(chosen)

    board["cuts"] = all_cuts
    board["wires"] = wires + wires_added
    verification = verify_project(result)
    if verification["status"] != "PASS":
        return {
            "status": "ROUTING_FAILED", "project": copy.deepcopy(project),
            "errors": list(verification["errors"]), "warnings": list(verification["warnings"]),
            "cuts_added": len(new_cuts), "wires_added": len(wires_added),
            "verification": verification,
        }

    warnings = [
        "Jumper wire paths, crossings, body clearance and soldering access are not yet modelled.",
        "Cut access and component-body interference are not yet checked.",
    ]
    return {
        "status": "ROUTED", "project": result, "errors": [],
        "warnings": warnings, "cuts_added": len(new_cuts),
        "wires_added": len(wires_added), "verification": verification,
    }


__all__ = ["route_copper"]
