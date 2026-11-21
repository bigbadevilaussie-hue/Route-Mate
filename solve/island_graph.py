"""Read-only copper-island graph for diagnosing strict vertical routing.

Nodes are copper-connected islands. Edges are grid-clear vertical jumpers.
No cuts or jumpers are installed; this is a search primitive, not a router.
"""
from __future__ import annotations

import copy
from collections import defaultdict, deque

from board_geometry import BUILTIN_DEFS, BoardGrid, resolve_definition
from physical_geometry import (
    physical_component_body, physical_jumper_segment, jumper_intersects_component,
)
from placement_policy import is_off_board_component
from .route import _copper_groups, _routing_sets, _terminals
from .verify import verify_project


def find_vertical_chain(project, net_id, *, max_edges=None):
    """Return a shortest-hop island chain or a structured obstruction result.

    Existing copper and jumpers are represented exactly as supplied. Terminal
    islands owned by another net are forbidden as intermediate nodes. This
    does not synthesize new cuts or certify measured physical clearances.
    """
    board = project["board"]
    rows, cols = int(board["rows"]), int(board["cols"])
    records = _terminals(project, rows, cols)
    _cuts, _wires, boundaries, isolated, checked_wires = _routing_sets(board, rows, cols)
    groups = _copper_groups(rows, cols, boundaries, isolated, checked_wires)
    owners = defaultdict(set)
    terminals = defaultdict(set)
    for row, col, net, _ref in records:
        root = groups.find((row, col))
        owners[root].add(net)
        terminals[net].add(root)
    if net_id not in terminals:
        return {"status": "UNKNOWN_NET", "net_id": net_id}
    if any(len(value) > 1 for value in owners.values()):
        return {"status": "EXISTING_SHORT", "net_id": net_id}
    targets = sorted(terminals[net_id])
    if len(targets) < 2:
        return {"status": "ALREADY_CONNECTED", "net_id": net_id, "chain": []}

    definitions = dict(BUILTIN_DEFS)
    definitions.update({
        str(item["id"]): item for item in project.get("componentDefs", [])
        if isinstance(item, dict) and item.get("id")
    })
    bodies = []
    for component in project.get("components", []):
        if not isinstance(component, dict) or is_off_board_component(component):
            continue
        if not isinstance(component.get("boardPos"), dict):
            continue
        definition = resolve_definition(component, definitions)
        if definition is not None:
            bodies.extend(physical_component_body(component, definition))
    grid = BoardGrid(rows, cols)

    # Each hole has one island; compare only holes sharing a column.
    by_column = defaultdict(list)
    for row in range(rows):
        for col in range(cols):
            root = groups.find((row, col))
            if not owners[root] or owners[root] == {net_id}:
                by_column[col].append((row, root))
    adjacency = defaultdict(list)
    seen = set()
    for col, entries in by_column.items():
        for i, (row_a, root_a) in enumerate(entries):
            for row_b, root_b in entries[i + 1:]:
                if root_a == root_b:
                    continue
                key = (min(root_a, root_b), max(root_a, root_b), col)
                if key in seen:
                    continue
                start, end = (row_a, col), (row_b, col)
                segment = physical_jumper_segment(grid, start, end)
                if jumper_intersects_component(segment, bodies):
                    continue
                seen.add(key)
                adjacency[root_a].append((root_b, start, end))
                adjacency[root_b].append((root_a, end, start))
    for edges in adjacency.values():
        edges.sort(key=lambda edge: (abs(edge[1][0] - edge[2][0]), edge))

    # Multi-source BFS connects the first terminal island to any other.
    source = targets[0]
    destination_roots = set(targets[1:])
    queue = deque([source])
    previous = {source: None}
    found = None
    while queue:
        root = queue.popleft()
        if root in destination_roots:
            found = root
            break
        depth = 0
        cursor = root
        while previous[cursor] is not None:
            depth += 1
            cursor = previous[cursor][0]
        if max_edges is not None and depth >= max_edges:
            continue
        for neighbor, start, end in adjacency[root]:
            if neighbor in previous:
                continue
            previous[neighbor] = (root, start, end)
            queue.append(neighbor)
    if found is None:
        return {
            "status": "NO_CHAIN_WITHIN_BUDGET", "net_id": net_id,
            "reachable_islands": len(previous), "max_edges": max_edges,
            "target_islands": len(targets),
        }
    chain = []
    cursor = found
    while previous[cursor] is not None:
        parent, start, end = previous[cursor]
        chain.append({
            "from": {"row": start[0], "col": start[1]},
            "to": {"row": end[0], "col": end[1]},
        })
        cursor = parent
    chain.reverse()
    return {
        "status": "CHAIN_FOUND", "net_id": net_id,
        "chain": chain, "target_islands": len(targets),
        "scope": "read-only; grid body clearance, not full physical verification",
    }

def route_with_island_graph(project, *, max_edges=None, max_chains=None):
    """Attempt a complete route by repeatedly joining terminal islands.

    All changes are private until independent verification passes. This
    intentionally avoids modifying or replacing existing manual routing.
    """
    trial = copy.deepcopy(project)
    board = trial.get("board")
    if not isinstance(board, dict) or "rows" not in board or "cols" not in board:
        return {"status": "GRAPH_FAILED", "reason": "missing board dimensions"}
    rows, cols = int(board["rows"]), int(board["cols"])
    records = _terminals(trial, rows, cols)
    _cuts, _wires, boundaries, isolated, _checked = _routing_sets(board, rows, cols)
    by_row = defaultdict(lambda: defaultdict(set))
    for row, col, net, _ref in records:
        by_row[row][col].add(net)
    added_cuts = []
    for row, positions in sorted(by_row.items()):
        ordered = sorted(positions)
        for left, right in zip(ordered, ordered[1:]):
            if positions[left] == positions[right]:
                continue
            if any((row, c) in boundaries for c in range(left, right)):
                continue
            if any((row, c) in isolated for c in range(left, right + 1)):
                continue
            cut = {"row": row, "col": left, "kind": "between"}
            added_cuts.append(cut)
            boundaries.add((row, left))
    board.setdefault("cuts", []).extend(added_cuts)
    board.setdefault("wires", [])
    nets = sorted({net for _row, _col, net, _ref in records})
    chains = 0
    for net in nets:
        while True:
            step = find_vertical_chain(trial, net, max_edges=max_edges)
            if step["status"] == "ALREADY_CONNECTED":
                break
            if step["status"] != "CHAIN_FOUND":
                return {"status": "GRAPH_FAILED", "reason": step["status"],
                        "net_id": net, "chains": chains}
            if max_chains is not None and chains >= max_chains:
                return {"status": "GRAPH_FAILED", "reason": "chain budget exceeded",
                        "net_id": net, "chains": chains}
            board["wires"].extend(step["chain"])
            chains += 1
    verification = verify_project(trial)
    if verification["status"] != "PASS":
        return {"status": "GRAPH_FAILED", "reason": "verification failed",
                "verification": verification, "chains": chains}
    return {"status": "ROUTED", "project": trial, "verification": verification,
            "cuts_added": len(added_cuts),
            "wires_added": len(board["wires"]) - len(project["board"].get("wires") or []),
            "graph": {"chains": chains, "max_edges": max_edges}}


__all__ = ["find_vertical_chain", "route_with_island_graph"]
