"""Independent stripboard connectivity verifier.

The verifier models only copper connectivity: horizontal strip links, drilled
cut holes, and jumper wires. Component pins are terminals, never internal
connections through a component.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from render._geometry import component_geometry, resolve_definition


class _UnionFind:
    def __init__(self):
        self.parent: dict[tuple[int, int], tuple[int, int]] = {}

    def add(self, item):
        self.parent.setdefault(item, item)

    def find(self, item):
        self.add(item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != item:
            parent = self.parent[item]
            self.parent[item] = root
            item = parent
        return root

    def union(self, left, right):
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def _coord(value: Any, context: str) -> tuple[int, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{context}: coordinate must be an object")
    row, col = value.get("row"), value.get("col")
    if type(row) is not int or type(col) is not int:
        raise ValueError(f"{context}: coordinate needs integer row and col")
    return row, col


def verify_project(project: Any) -> dict[str, Any]:
    """Check whether physical copper connects exactly the assigned on-board nets.

    A cut with kind="between" (also the v4 default when kind is absent)
    severs the link between col and col+1. A kind="hole" cut isolates that
    hole from both neighbours. Vertical "below" cuts require patterned-board
    copper, which this verifier does not yet model.
    """
    errors: list[str] = []
    warnings: list[str] = []
    counts = {"holes": 0, "cuts": 0, "wires": 0, "on_board_terminals": 0,
              "nets_checked": 0, "short_groups": 0, "open_nets": 0}
    if not isinstance(project, dict):
        return {"status": "FAIL", "errors": ["project root must be an object"],
                "warnings": [], "counts": counts}
    board = project.get("board")
    components = project.get("components")
    assignments = project.get("netAssignments")
    if not isinstance(board, dict) or not isinstance(components, list) or not isinstance(assignments, list):
        return {"status": "FAIL", "errors": ["project needs board, components and netAssignments"],
                "warnings": [], "counts": counts}
    try:
        rows, cols = int(board["rows"]), int(board["cols"])
        if rows < 1 or cols < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return {"status": "FAIL", "errors": ["board rows and cols must be positive integers"],
                "warnings": [], "counts": counts}

    uf = _UnionFind()
    counts["holes"] = rows * cols
    for row in range(rows):
        for col in range(cols):
            uf.add((row, col))

    cut_holes: set[tuple[int, int]] = set()
    cut_boundaries: set[tuple[int, int]] = set()
    raw_cuts = board.get("cuts") or []
    if not isinstance(raw_cuts, list):
        errors.append("board.cuts must be a list")
        raw_cuts = []
    for index, cut in enumerate(raw_cuts):
        try:
            point = _coord(cut, f"cut[{index}]")
            kind = cut.get("kind", "between")
            if kind not in ("between", "hole", "below"):
                errors.append(f"cut[{index}]: unsupported cut kind {kind!r}")
                continue
            if not (0 <= point[0] < rows and 0 <= point[1] < cols):
                errors.append(f"cut[{index}]: outside board at {point}")
                continue
            if kind == "below":
                errors.append(
                    f"cut[{index}]: kind 'below' requires patterned-board "
                    "vertical copper, which the verifier does not yet model"
                )
                continue
            if kind == "between":
                if point[1] >= cols - 1:
                    errors.append(
                        f"cut[{index}]: between cut at {point} has no hole to its right"
                    )
                    continue
                cut_boundaries.add(point)
            else:
                cut_holes.add(point)
        except (ValueError, AttributeError) as exc:
            errors.append(str(exc))
    counts["cuts"] = len(cut_holes) + len(cut_boundaries)

    # A between cut severs one link; a drilled hole isolates that hole.
    for row in range(rows):
        for col in range(cols - 1):
            left, right = (row, col), (row, col + 1)
            if (row, col) not in cut_boundaries and left not in cut_holes and right not in cut_holes:
                uf.union(left, right)

    raw_wires = board.get("wires")
    if raw_wires is None:
        raw_wires = []
    if not isinstance(raw_wires, list):
        errors.append("board.wires must be a list")
        raw_wires = []
    for index, wire in enumerate(raw_wires):
        try:
            start = _coord(wire.get("from"), f"wire[{index}].from")
            end = _coord(wire.get("to"), f"wire[{index}].to")
            for point in (start, end):
                if not (0 <= point[0] < rows and 0 <= point[1] < cols):
                    raise ValueError(f"wire[{index}]: endpoint {point} outside board")
            uf.union(start, end)
            counts["wires"] += 1
        except (ValueError, AttributeError) as exc:
            errors.append(str(exc))

    definitions = {
        str(d.get("id")): d for d in (project.get("componentDefs") or [])
        if isinstance(d, dict) and d.get("id")
    }
    component_by_id = {str(c.get("id")): c for c in components
                       if isinstance(c, dict) and c.get("id")}
    net_by_terminal: dict[tuple[str, str], str] = {}
    terminals_by_net: dict[str, list[tuple[int, int, str]]] = defaultdict(list)

    for index, assignment in enumerate(assignments):
        if not isinstance(assignment, dict):
            errors.append(f"netAssignments[{index}] must be an object")
            continue
        cid, pid, nid = (str(assignment.get(k, "")) for k in ("componentId", "pinId", "netId"))
        component = component_by_id.get(cid)
        if component is None:
            errors.append(f"assignment[{index}] references unknown component {cid!r}")
            continue
        if component.get("offBoard") is True or component.get("boardExcluded") is True:
            continue
        if not isinstance(component.get("boardPos"), dict):
            errors.append(f"{component.get('label') or cid}: assigned terminal has no board position")
            continue
        definition = resolve_definition(component, definitions)
        if not definition:
            errors.append(f"{component.get('label') or cid}: no footprint definition for physical pin lookup")
            continue
        try:
            pins, _body = component_geometry(component, definition)
        except (TypeError, ValueError, KeyError) as exc:
            errors.append(f"{component.get('label') or cid}: invalid footprint geometry: {exc}")
            continue
        matches = [pin for pin in pins if str(pin.get("id")) == pid]
        if len(matches) != 1:
            errors.append(f"{component.get('label') or cid}: pin {pid!r} resolves to {len(matches)} physical pins")
            continue
        point = (int(matches[0]["row"]), int(matches[0]["col"]))
        if not (0 <= point[0] < rows and 0 <= point[1] < cols):
            errors.append(f"{component.get('label') or cid} pin {pid}: hole {point} outside board")
            continue
        terminal = (cid, pid)
        if terminal in net_by_terminal:
            errors.append(f"duplicate physical assignment for {cid} pin {pid}")
            continue
        net_by_terminal[terminal] = nid
        terminals_by_net[nid].append((point[0], point[1], f"{component.get('label') or cid}.{pid}"))
        counts["on_board_terminals"] += 1

    # A copper-connected group containing terminals assigned to different nets is a short.
    group_nets: dict[Any, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for nid, terminals in terminals_by_net.items():
        for row, col, label in terminals:
            group_nets[uf.find((row, col))][nid].append(label)
    for root, net_members in group_nets.items():
        if len(net_members) > 1:
            counts["short_groups"] += 1
            detail = "; ".join(f"{net}: {', '.join(labels)}"
                               for net, labels in sorted(net_members.items()))
            errors.append(f"short at copper group {root}: {detail}")

    # A net is open if its assigned on-board terminals occupy multiple copper groups.
    for nid, terminals in sorted(terminals_by_net.items()):
        roots = {uf.find((row, col)) for row, col, _label in terminals}
        if len(roots) > 1:
            counts["open_nets"] += 1
            detail = ", ".join(label for _row, _col, label in terminals)
            errors.append(f"open net {nid}: {len(roots)} disconnected copper groups ({detail})")
    counts["nets_checked"] = len(terminals_by_net)

    if not terminals_by_net:
        warnings.append("no assigned on-board terminals were available to verify")
    return {"status": "FAIL" if errors else "PASS", "errors": errors,
            "warnings": warnings, "counts": counts}


__all__ = ["verify_project"]
