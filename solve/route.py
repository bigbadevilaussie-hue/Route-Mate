"""Deterministic first-pass stripboard copper router.

This router handles horizontal strip copper, between/hole cuts and jumper
wires. It preserves existing manual routing and verifies the completed model.
It does not yet model the physical path or crossing of jumper wire bodies.
"""
from __future__ import annotations

import copy
from bisect import bisect_left
from collections import defaultdict
from typing import Any

from placement_policy import is_off_board_component
from board_geometry import BUILTIN_DEFS, BoardGrid, component_geometry, resolve_definition
from physical_geometry import physical_component_body, physical_jumper_segment, jumper_intersects_component
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
            if component.get("boardExcluded") is True and component.get("offBoard") is not True:
                continue
            leads = component.get("leads")
            lead = leads.get(pid) if isinstance(leads, dict) else None
            if lead is None:
                raise ValueError(f"{label} pin {pid}: missing off-board termination pad")
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
            if not matches and pid.isdecimal():
                definition = resolve_definition(component, definitions)
                defined_pins = definition.get("pins", []) if definition else []
                index = int(pid) - 1
                if 0 <= index < len(defined_pins):
                    alias = str(defined_pins[index].get("id"))
                    matches = [pin for pin in pin_cache[cid] if str(pin.get("id")) == alias]
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


def route_copper(project: Any, *, vertical_only: bool = False,
                 route_order: str = "alphabetical") -> dict[str, Any]:
    """Add cuts and jumpers to a placed project, then run the independent verifier.

    Existing cuts and wires are preserved. The source project is never mutated.
    Returns ROUTED only when solve.verify.verify_project reports PASS.\n    vertical_only requires every new jumper to share a column; it is not\n    a substitute for physical clearance or accessibility verification.
    """
    if route_order not in ("alphabetical", "constrained"):
        raise ValueError("route_order must be alphabetical or constrained")
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

    # Physical grid occupancy is authoritative for jumper centreline screening.
    # Measured wire/package clearance is a separate, unresolved requirement.
    grid = BoardGrid(rows, cols)
    bodies = []
    definitions = dict(BUILTIN_DEFS)
    definitions.update({str(d["id"]): d for d in result.get("componentDefs", [])
                        if isinstance(d, dict) and d.get("id")})
    for component in result.get("components", []):
        if not isinstance(component, dict) or is_off_board_component(component):
            continue
        if not isinstance(component.get("boardPos"), dict):
            continue
        definition = resolve_definition(component, definitions)
        if definition is None:
            continue
        bodies.extend(physical_component_body(component, definition))

    def legal_vertical(start, end):
        if start[1] != end[1] or start == end:
            return False
        segment = physical_jumper_segment(grid, start, end)
        return not jumper_intersects_component(segment, bodies)

    if vertical_only:
        for index, (start, end) in enumerate(checked_wires):
            if not legal_vertical(start, end):
                return {
                    "status": "ROUTING_FAILED", "project": copy.deepcopy(project),
                    "errors": [f"existing wire[{index}] is not a clear vertical jumper"],
                    "warnings": [], "cuts_added": 0, "wires_added": 0,
                    "verification": None,
                }

    # Dahl-inspired copper reuse, with indexed nearest-hole search.
    # Row-sorted copper islands avoid quadratic all-hole-pairs enumeration.
    # These links are still electrical candidates, not physical clearance PASS.
    wires_added: list[dict[str, Any]] = []
    serial = 1
    holes_by_root: dict[tuple[int, int], dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in range(rows):
        for col in range(cols):
            holes_by_root[groups.find((row, col))][row].append(col)

    def nearest_link(left_rows, right_rows):
        best = None
        for lr, left_cols in left_rows.items():
            for rr, right_cols in right_rows.items():
                row_cost = abs(lr - rr)
                # Manhattan distance cannot be smaller than the row gap.
                # Prune only strictly worse rows: equal-distance routes
                # still need the vertical/coordinate tie-breaks.
                if best is not None and row_cost > best[0]:
                    continue
                for lc in left_cols:
                    if vertical_only:
                        index = bisect_left(right_cols, lc)
                        candidates = (index,) if index < len(right_cols) and right_cols[index] == lc else ()
                    else:
                        index = bisect_left(right_cols, lc)
                        candidates = (index - 1, index)
                    # Nearest columns on either side suffice for minimum
                    # Manhattan distance, including deterministic tie-breaks.
                    for pos in candidates:
                        if 0 <= pos < len(right_cols):
                            rc = right_cols[pos]
                            if vertical_only and not legal_vertical((lr, lc), (rr, rc)):
                                continue
                            candidate = (
                                row_cost + abs(lc - rc), int(lc != rc),
                                (lr, lc), (rr, rc),
                            )
                            if best is None or candidate < best:
                                best = candidate
        return best

    # A low-cost alternative to genetic route-order search: tackle nets
    # requiring the most distinct copper-island connections first.
    # This changes wire insertion order, not the electrical netlist.
    net_roots = {
        net: sorted({groups.find(point) for point in points})
        for net, points in terminals_by_net.items()
    }
    if route_order == "constrained":
        net_order = sorted(net_roots, key=lambda net: (-len(net_roots[net]), net))
    else:
        net_order = sorted(net_roots)
    # Unassigned copper strips can act as two-jumper vertical bridges.
    # Reserve a bridge for one net only; never reuse it for another net.
    reserved_bridges: set[tuple[int, int]] = set()
    for net in net_order:
        roots = net_roots[net]
        if len(roots) < 2:
            continue
        # Keep one growing connected island; merging into a previously
        # selected root without this invariant could lose its endpoint list.
        connected_rows = {
            row: list(columns)
            for row, columns in holes_by_root[roots[0]].items()
        }
        remaining = set(roots[1:])
        while remaining:
            best_choice = None
            for root in sorted(remaining):
                candidate = nearest_link(connected_rows, holes_by_root[root])
                if candidate is not None:
                    choice = (*candidate, root)
                    if best_choice is None or choice < best_choice:
                        best_choice = choice
            if best_choice is None and vertical_only:
                # Find an electrically unassigned copper island that overlaps
                # both sides in different columns. Two vertical jumpers can
                # use its horizontal copper as a bridge without diagonal wire.
                bridge_choice = None
                for bridge_root, bridge_rows in holes_by_root.items():
                    if (bridge_root in reserved_bridges
                            or nets_by_group.get(bridge_root)
                            or bridge_root in roots):
                        continue
                    first = nearest_link(connected_rows, bridge_rows)
                    if first is None:
                        continue
                    for target in sorted(remaining):
                        second = nearest_link(bridge_rows, holes_by_root[target])
                        if second is None:
                            continue
                        choice = (first[0] + second[0], first, second,
                                  bridge_root, target)
                        if bridge_choice is None or choice < bridge_choice:
                            bridge_choice = choice
                if bridge_choice is not None:
                    _cost, first, second, bridge_root, target = bridge_choice
                    for link in (first, second):
                        _distance, _diagonal, start, end = link
                        wire_id, serial = _new_wire_id(wires + wires_added, serial)
                        wires_added.append({
                            "id": wire_id,
                            "from": {"row": start[0], "col": start[1]},
                            "to": {"row": end[0], "col": end[1]},
                        })
                        groups.union(start, end)
                    reserved_bridges.add(bridge_root)
                    for merged_root in (bridge_root, target):
                        for row, columns in holes_by_root[merged_root].items():
                            connected_rows.setdefault(row, []).extend(columns)
                            connected_rows[row].sort()
                    remaining.remove(target)
                    continue
            if best_choice is None:
                # Diagnostic only: breadth-first search over unassigned copper
                # islands, using the same body-clear vertical-link predicate.
                # This does not reserve copper, add wires, or certify clearance.
                from collections import deque
                available = {
                    root: island_rows
                    for root, island_rows in holes_by_root.items()
                    if root not in reserved_bridges
                    and (root in remaining or not nets_by_group.get(root))
                    and root not in roots[:1]
                }
                queue = deque([None])
                predecessor = {None: None}
                edge_to = {}
                reached_target = None
                while queue and reached_target is None:
                    current = queue.popleft()
                    source_rows = connected_rows if current is None else available[current]
                    for candidate_root in sorted(available):
                        if candidate_root in predecessor:
                            continue
                        link = nearest_link(source_rows, available[candidate_root])
                        if link is None:
                            continue
                        predecessor[candidate_root] = current
                        edge_to[candidate_root] = link
                        if candidate_root in remaining:
                            reached_target = candidate_root
                            break
                        queue.append(candidate_root)
                chain = []
                if reached_target is not None:
                    cursor = reached_target
                    while cursor is not None:
                        link = edge_to[cursor]
                        chain.append({
                            "from": {"row": link[2][0], "col": link[2][1]},
                            "to": {"row": link[3][0], "col": link[3][1]},
                            "distance_hole_pitches": link[0],
                        })
                        cursor = predecessor[cursor]
                    chain.reverse()
                reachability = {
                    "status": "CHAIN_FOUND" if chain else "NO_CHAIN_FOUND",
                    "net_id": net,
                    "candidate_islands": len(available),
                    "reachable_islands": len(predecessor) - 1,
                    "remaining_target_islands": len(remaining),
                    "example_vertical_chain": chain,
                    "scope": "grid body-occupancy only; excludes other-net and reserved islands",
                }
                # Classify first-hop obstructions without relaxing routing.
                # All candidates share a column; other-net copper is only
                # inspected, never treated as available to this net.
                source_holes = sorted({
                    (row, col) for row, columns in connected_rows.items()
                    for col in columns
                })
                source_set = set(source_holes)
                blockers = []
                seen_pairs = set()
                counts = {
                    "no_other_island_in_column": 0,
                    "body_blocked": 0,
                    "other_net_copper": 0,
                    "reserved_bridge": 0,
                    "same_net_target": 0,
                    "unused_copper": 0,
                }
                for start in source_holes:
                    other_holes = [
                        (row, start[1]) for row in range(rows)
                        if row != start[0] and (row, start[1]) not in source_set
                    ]
                    if not other_holes:
                        counts["no_other_island_in_column"] += 1
                    for end in other_holes:
                        root = groups.find(end)
                        # Ignore other holes belonging to the growing island.
                        if root in roots and root not in remaining:
                            continue
                        key = (start, end)
                        if key in seen_pairs:
                            continue
                        seen_pairs.add(key)
                        if not legal_vertical(start, end):
                            reason = "body_blocked"
                        elif root in reserved_bridges:
                            reason = "reserved_bridge"
                        elif nets_by_group.get(root) and root not in remaining:
                            reason = "other_net_copper"
                        elif root in remaining:
                            reason = "same_net_target"
                        else:
                            reason = "unused_copper"
                        counts[reason] += 1
                        if len(blockers) < 16:
                            blockers.append({
                                "from": {"row": start[0], "col": start[1]},
                                "to": {"row": end[0], "col": end[1]},
                                "reason": reason,
                                "assigned_nets": sorted(nets_by_group.get(root, ())),
                            })
                obstruction = {
                    "first_hop_counts": counts,
                    "sample_candidates": blockers,
                    "source_hole_count": len(source_holes),
                    "scope": "diagnostic only; grid centreline and copper ownership",
                }
                # Report the exact strip runs behind other-net first hops.
                # A run with assigned terminals cannot be donated to this
                # net without cuts isolating a terminal-free sub-run.
                source_columns = sorted({col for _, col in source_holes})
                strip_runs = []
                for row in range(rows):
                    run_start = 0
                    for boundary_col in range(cols):
                        if boundary_col != cols - 1 and (row, boundary_col) not in boundaries:
                            continue
                        run_end = boundary_col
                        if run_start <= run_end and row not in connected_rows:
                            overlaps = [col for col in source_columns
                                        if run_start <= col <= run_end]
                            if overlaps:
                                assigned = sorted(
                                    (col, sorted(nets))
                                    for col, nets in by_row.get(row, {}).items()
                                    if run_start <= col <= run_end
                                )
                                if assigned:
                                    strip_runs.append({
                                        "row": row,
                                        "start_col": run_start,
                                        "end_col": run_end,
                                        "source_columns_in_run": overlaps,
                                        "terminals": [
                                            {"col": col, "nets": nets}
                                            for col, nets in assigned
                                        ],
                                        "existing_left_cut": run_start > 0 and
                                            (row, run_start - 1) in boundaries,
                                        "existing_right_cut": run_end < cols - 1 and
                                            (row, run_end) in boundaries,
                                    })
                        run_start = boundary_col + 1
                cut_segmentation = {
                    "status": "DIAGNOSTIC_ONLY",
                    "source_columns": source_columns,
                    "occupied_runs_crossing_source_columns": len(strip_runs),
                    "sample_runs": strip_runs[:24],
                    "truncated": len(strip_runs) > 24,
                    "note": "Terminal-bearing runs need additional between-hole cuts to free copper; no legal alternative cut layout has been proven.",
                }
                # Read-only single-cut feasibility: split a terminal-free
                # left prefix off an occupied strip. Rebuild copper groups
                # with the proposed between-hole cut to check ownership,
                # including connectivity through existing jumpers.
                cut_candidates = []
                for run in strip_runs:
                    row = run["row"]
                    first_terminal = min(t["col"] for t in run["terminals"])
                    cut_col = first_terminal - 1
                    if not (run["start_col"] <= cut_col < run["end_col"]):
                        continue
                    if (row, cut_col) in boundaries:
                        continue
                    candidate_cols = [
                        col for col in source_columns
                        if run["start_col"] <= col <= cut_col
                        and (row, col) not in isolated
                    ]
                    if not candidate_cols:
                        continue
                    trial_boundaries = boundaries | {(row, cut_col)}
                    trial_groups = _copper_groups(
                        rows, cols, trial_boundaries, isolated, checked_wires
                    )
                    trial_owners = defaultdict(set)
                    for tr, tc, tnet, _ in records:
                        trial_owners[trial_groups.find((tr, tc))].add(tnet)
                    free_cols = [
                        col for col in candidate_cols
                        if not trial_owners[trial_groups.find((row, col))]
                    ]
                    if not free_cols:
                        continue
                    trial_rows = {row: free_cols}
                    first_link = nearest_link(connected_rows, trial_rows)
                    if first_link is None:
                        continue
                    second_links = [
                        nearest_link(trial_rows, holes_by_root[target])
                        for target in sorted(remaining)
                    ]
                    second_link = min((link for link in second_links if link is not None),
                                      default=None)
                    cut_candidates.append({
                        "cut": {"row": row, "col": cut_col, "kind": "between"},
                        "free_columns": free_cols,
                        "first_jumper": {
                            "from": {"row": first_link[2][0], "col": first_link[2][1]},
                            "to": {"row": first_link[3][0], "col": first_link[3][1]},
                        },
                        "second_jumper_to_remaining_net": None if second_link is None else {
                            "from": {"row": second_link[2][0], "col": second_link[2][1]},
                            "to": {"row": second_link[3][0], "col": second_link[3][1]},
                        },
                    })
                cut_feasibility = {
                    "status": "CANDIDATES_FOUND" if cut_candidates else "NO_SINGLE_CUT_CANDIDATE",
                    "candidate_count": len(cut_candidates),
                    "sample_candidates": cut_candidates[:12],
                    "truncated": len(cut_candidates) > 12,
                    "scope": "read-only, single between-hole cut; grid centreline only; no cut accessibility, measured clearance or full-board verification",
                }
                # Bounded two-cut feasibility. Recompute ownership after BOTH
                # cuts, then search source -> freed strips -> target. This is
                # deliberately diagnostic: no cuts or wires are installed.
                from itertools import combinations
                pair_results = []
                checked_pairs = 0
                max_pairs = 300
                for first_cut, second_cut in combinations(cut_candidates, 2):
                    if checked_pairs >= max_pairs:
                        break
                    checked_pairs += 1
                    pair_cuts = [first_cut["cut"], second_cut["cut"]]
                    trial_boundaries = boundaries | {
                        (cut["row"], cut["col"]) for cut in pair_cuts
                    }
                    trial_groups = _copper_groups(
                        rows, cols, trial_boundaries, isolated, checked_wires
                    )
                    owners = defaultdict(set)
                    for tr, tc, tnet, _ in records:
                        owners[trial_groups.find((tr, tc))].add(tnet)
                    if any(len(nets) > 1 for nets in owners.values()):
                        continue
                    # A proposed cut may not sever copper joining existing
                    # same-net terminals, even if it frees an empty prefix.
                    baseline_to_trial = defaultdict(set)
                    for tr, tc, _tnet, _ in records:
                        baseline_to_trial[groups.find((tr, tc))].add(
                            trial_groups.find((tr, tc))
                        )
                    if any(len(parts) > 1 for parts in baseline_to_trial.values()):
                        continue
                    freed = {}
                    for candidate in (first_cut, second_cut):
                        row = candidate["cut"]["row"]
                        for col in candidate["free_columns"]:
                            root = trial_groups.find((row, col))
                            if not owners[root]:
                                freed.setdefault(root, defaultdict(list))[row].append(col)
                    freed_rows = [
                        {row: sorted(set(cols)) for row, cols in island.items()}
                        for _root, island in sorted(freed.items())
                    ]
                    for i, first_rows in enumerate(freed_rows):
                        source_link = nearest_link(connected_rows, first_rows)
                        if source_link is None:
                            continue
                        for j, second_rows in enumerate(freed_rows):
                            if i == j:
                                continue
                            middle_link = nearest_link(first_rows, second_rows)
                            if middle_link is None:
                                continue
                            for target in sorted(remaining):
                                target_link = nearest_link(
                                    second_rows, holes_by_root[target]
                                )
                                if target_link is None:
                                    continue
                                links = (source_link, middle_link, target_link)
                                pair_results.append({
                                    "cuts": pair_cuts,
                                    "target_root": list(target),
                                    "jumpers": [
                                        {
                                            "from": {"row": link[2][0], "col": link[2][1]},
                                            "to": {"row": link[3][0], "col": link[3][1]},
                                        } for link in links
                                    ],
                                })
                                break
                            if pair_results:
                                break
                        if pair_results:
                            break
                    if pair_results:
                        break
                multi_cut_feasibility = {
                    "status": "CHAIN_FOUND" if pair_results else "NO_TWO_CUT_CHAIN_FOUND",
                    "pairs_checked": checked_pairs,
                    "pair_budget": max_pairs,
                    "example_chains": pair_results[:3],
                    "scope": "read-only, up to two prefix-isolating cuts and three grid-clear vertical jumpers; not exhaustive; no measured clearance or full-board verification",
                }
                # Diagnose the obstruction; another placement may still route.
                connected_columns = sorted({
                    col for columns in connected_rows.values() for col in columns
                })
                stranded_columns = sorted({
                    col for root in remaining
                    for columns in holes_by_root[root].values()
                    for col in columns
                })
                shared_columns = sorted(set(connected_columns) & set(stranded_columns))
                if vertical_only:
                    detail = (
                        f"no body-clear same-column jumper connects remaining copper islands; "
                        f"connected columns={connected_columns}; "
                        f"remaining columns={stranded_columns}; "
                        f"shared columns={shared_columns}; "
                        f"remaining islands={len(remaining)}"
                    )
                else:
                    detail = "no jumper connects remaining copper islands"
                return {
                    "status": "ROUTING_FAILED", "project": copy.deepcopy(project),
                    "errors": [f"net {net}: {detail}"],
                    "warnings": [], "cuts_added": 0, "wires_added": 0,
                    "verification": None,
                    "reachability": reachability,
                    "obstruction": obstruction,
                    "cut_segmentation": cut_segmentation,
                    "cut_feasibility": cut_feasibility,
                    "multi_cut_feasibility": multi_cut_feasibility,
                }
            _distance, _diagonal, start, end, chosen = best_choice
            wire_id, serial = _new_wire_id(wires + wires_added, serial)
            wires_added.append({
                "id": wire_id,
                "from": {"row": start[0], "col": start[1]},
                "to": {"row": end[0], "col": end[1]},
            })
            groups.union(start, end)
            for row, columns in holes_by_root[chosen].items():
                connected_rows.setdefault(row, []).extend(columns)
                connected_rows[row].sort()
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
        "Measured wire envelopes, jumper crossings and soldering access are not yet verified.",
        "Cut access and measured component-body overhang are not yet checked.",
    ]
    return {
        "status": "ROUTED", "project": result, "errors": [],
        "warnings": warnings, "cuts_added": len(new_cuts),
        "wires_added": len(wires_added), "verification": verification,
    }


__all__ = ["route_copper"]
