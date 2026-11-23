"""Independent strip-island graph and wire-net ownership for Hell Mode M1.

Uses copper *segments* as graph vertices instead of copying the existing
per-hole union-find verifier. Re-derives all pad positions from raw components
through Hell Mode's separately implemented footprint resolver.

This is an electrical-only graph: insulated collinear jumper spans DO NOT
short electrically unless their endpoints join the same copper. Geometry
eligibility is independently checked in strict_occupancy.py.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .pad_geometry import collect_pad_holes


class _Graph:
    def __init__(self, n: int) -> None:
        self.root = list(range(n))

    def find(self, x: int) -> int:
        while x != self.root[x]:
            self.root[x] = self.root[self.root[x]]
            x = self.root[x]
        return x

    def link(self, a: int, b: int) -> None:
        x, y = self.find(a), self.find(b)
        if x != y:
            self.root[max(x, y)] = min(x, y)


def _coordinate(value: Any, rows: int, cols: int, context: str) -> tuple[int, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{context}: coordinate object required")
    r, c = value.get("row"), value.get("col")
    if type(r) is not int or type(c) is not int:
        raise ValueError(f"{context}: integer row/col required")
    if not (0 <= r < rows and 0 <= c < cols):
        raise ValueError(f"{context}: outside board")
    return r, c


def reconstruct_electrical(project: dict[str, Any]) -> dict[str, Any]:
    """Analyse raw project, returning reason-coded graph and jumper net map.

    This routine does not import solve.verify, the router, or the M1 spike.
    It does not certify the physical path, wire clearance, or cut access.
    """
    if not isinstance(project, dict) or not isinstance(project.get("board"), dict):
        raise ValueError("project.board required")
    board = project["board"]
    rows, cols = board.get("rows"), board.get("cols")
    if type(rows) is not int or type(cols) is not int or rows < 1 or cols < 2:
        raise ValueError("board requires positive integer rows and cols >= 2")
    raw_cuts, raw_wires = board.get("cuts") or [], board.get("wires") or []
    if not isinstance(raw_cuts, list) or not isinstance(raw_wires, list):
        raise ValueError("board cuts and wires must be lists")

    errors: list[dict[str, Any]] = []
    boundaries: set[tuple[int, int]] = set()
    for i, cut in enumerate(raw_cuts):
        try:
            r, c = _coordinate(cut, rows, cols, f"cut[{i}]")
            if cut.get("kind", "between") != "between":
                errors.append({
                    "code": "UNSUPPORTED_CUT_KIND", "index": i,
                    "kind": cut.get("kind"),
                })
            elif c == cols - 1:
                errors.append({"code": "CUT_OUTSIDE_STRIP", "index": i})
            else:
                boundaries.add((r, c))
        except (ValueError, AttributeError) as exc:
            errors.append({"code": "BAD_CUT", "index": i, "detail": str(exc)})

    # Unlike per-hole union-find, assign a single vertex to each continuous
    # horizontal copper island: changing a cut changes the vertices directly.
    hole_island: list[list[int]] = []
    next_island = 0
    for row in range(rows):
        strip: list[int] = []
        for col in range(cols):
            if col == 0 or (row, col - 1) in boundaries:
                next_island += 1
            strip.append(next_island - 1)
        hole_island.append(strip)
    graph = _Graph(next_island)

    wire_endpoints: dict[str, tuple[int, int]] = {}
    for index, wire in enumerate(raw_wires):
        if not isinstance(wire, dict):
            errors.append({"code": "BAD_WIRE", "index": index})
            continue
        ident = wire.get("id", f"wire[{index}]")
        if not isinstance(ident, str) or not ident or ident in wire_endpoints:
            errors.append({"code": "DUPLICATE_OR_BAD_WIRE_ID", "index": index})
            continue
        try:
            a = _coordinate(wire.get("from"), rows, cols, ident + ".from")
            b = _coordinate(wire.get("to"), rows, cols, ident + ".to")
        except ValueError as exc:
            errors.append({"code": "BAD_WIRE_ENDPOINT", "wire": ident,
                           "detail": str(exc)})
            continue
        # Electrical graph does not validate direction; STRICT geometry does.
        x, y = hole_island[a[0]][a[1]], hole_island[b[0]][b[1]]
        graph.link(x, y)
        wire_endpoints[ident] = (x, y)

    pad_state = collect_pad_holes(project)
    for issue in pad_state["errors"]:
        errors.append({"code": "BAD_TERMINAL", "detail": issue})
    terminals = pad_state["terminals"]
    net_groups: dict[str, set[int]] = defaultdict(set)
    root_owners: dict[int, set[str]] = defaultdict(set)
    for pad in terminals:
        island = hole_island[pad["row"]][pad["col"]]
        root = graph.find(island)
        net = str(pad["net_id"])
        net_groups[net].add(root)
        root_owners[root].add(net)

    open_nets: list[str] = []
    for net, groups in sorted(net_groups.items()):
        if len(groups) > 1:
            open_nets.append(net)
            errors.append({"code": "OPEN_NET", "net": net, "islands": len(groups)})

    short_groups: list[list[str]] = []
    for root, owners in sorted(root_owners.items()):
        if len(owners) > 1:
            short_groups.append(sorted(owners))
            errors.append({
                "code": "SHORT_NETS", "nets": sorted(owners), "island": root,
            })

    wire_nets: dict[str, str] = {}
    unowned_wires: list[str] = []
    for ident, (island, _) in wire_endpoints.items():
        owners = root_owners.get(graph.find(island), set())
        if len(owners) == 1:
            wire_nets[ident] = next(iter(owners))
        elif not owners:
            unowned_wires.append(ident)

    return {
        "status": "PASS" if not errors and terminals else "FAIL",
        "errors": errors,
        "counts": {
            "rows": rows, "cols": cols, "copper_islands": next_island,
            "cuts": len(boundaries), "wires": len(wire_endpoints),
            "terminals": len(terminals), "pad_holes": len(pad_state["pads"]),
            "nets_checked": len(net_groups), "open_nets": len(open_nets),
            "short_groups": len(short_groups),
        },
        "pin_holes": pad_state["pads"],
        "wire_nets": wire_nets,
        "unowned_wires": unowned_wires,
        "cut_access": "unverified",
        "physical_pass": False,
    }


__all__ = ["reconstruct_electrical"]
