"""Standalone STRICT jumper hole-and-gap occupancy checker.

M1 geometry primitive, intentionally independent of Quick Solve, the router,
the earlier diagnostic spike, and the electrical verifier. An approved pad
landing is not inferred from a wire label: trusted wire-to-net ownership must
be supplied by the future independent verify_layout facade.

This checker proves neither measured 2.5D body clearance nor cut-tool access.
It never claims BUILD_READY or full physical PASS.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping


def _hole(point: Any, *, rows: int, cols: int, context: str) -> tuple[int, int]:
    if not isinstance(point, dict):
        raise ValueError(f"{context}: missing row/col object")
    r, c = point.get("row"), point.get("col")
    if type(r) is not int or type(c) is not int:
        raise ValueError(f"{context}: row/col must be integers")
    if not (0 <= r < rows and 0 <= c < cols):
        raise ValueError(f"{context}: hole ({r},{c}) outside board")
    return r, c


def audit_strict_occupancy(
    board: Mapping[str, Any],
    *,
    pin_holes: list[dict[str, Any]] | None = None,
    trusted_wire_nets: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Independent 2D centreline occupancy check, with optional pin evidence.

    pin_holes must be independently reconstructed from the raw project and
    contain {row, col, net_id, ref}. Missing net_id means unassigned pad.
    trusted_wire_nets must likewise be independently reconstructed from
    copper segments and assigned terminals, never read from a wire's own
    untrusted net/color/label field. No supplied evidence means UNCERTIFIED.
    """
    if not isinstance(board, Mapping):
        raise ValueError("board must be a mapping")
    rows, cols = board.get("rows"), board.get("cols")
    if type(rows) is not int or type(cols) is not int or rows < 2 or cols < 1:
        raise ValueError("board needs at least 2 rows and 1 column")
    wires = board.get("wires", [])
    if not isinstance(wires, list):
        raise ValueError("board.wires must be a list")

    gaps: dict[tuple[int, int], list[str]] = defaultdict(list)
    landings: dict[tuple[int, int], list[str]] = defaultdict(list)
    intermediate: dict[tuple[int, int], list[str]] = defaultdict(list)
    seen_ids: set[str] = set()
    for index, w in enumerate(wires):
        if not isinstance(w, dict):
            raise ValueError(f"wire[{index}] must be an object")
        ident = w.get("id", f"wire[{index}]")
        if not isinstance(ident, str) or not ident or ident in seen_ids:
            raise ValueError(f"wire[{index}]: empty or duplicate wire id")
        seen_ids.add(ident)
        a = _hole(w.get("from"), rows=rows, cols=cols, context=f"{ident}.from")
        b = _hole(w.get("to"), rows=rows, cols=cols, context=f"{ident}.to")
        if a[1] != b[1] or a[0] == b[0]:
            raise ValueError(f"{ident}: jumper must be straight vertical and nonzero")
        lo, hi = sorted((a[0], b[0]))
        for gap in range(lo, hi):
            gaps[(a[1], gap)].append(ident)
        landings[(a[1], a[0])].append(ident)
        landings[(b[1], b[0])].append(ident)
        for row in range(lo + 1, hi):
            intermediate[(a[1], row)].append(ident)

    findings: list[dict[str, Any]] = []
    stacked = 0
    excess = 0
    max_depth = 0
    pair_ids: set[tuple[str, str]] = set()
    for (col, row), owners in sorted(gaps.items()):
        depth = len(owners)
        max_depth = max(max_depth, depth)
        if depth <= 1:
            continue
        stacked += 1
        excess += depth - 1
        ordered = sorted(owners)
        findings.append({
            "code": "STACKING_VIOLATION", "col": col, "gap_row": row,
            "depth": depth, "wires": ordered,
        })
        for i, first in enumerate(ordered):
            for second in ordered[i + 1:]:
                pair_ids.add((first, second))

    shared_landings = 0
    endpoint_on_span = 0
    for (col, row), ids in sorted(landings.items()):
        if len(ids) > 1:
            shared_landings += 1
            findings.append({
                "code": "JUMPER_SHARED_HOLE", "row": row, "col": col,
                "wires": sorted(ids),
            })
        inside = sorted(set(intermediate.get((col, row), ())) - set(ids))
        if inside:
            endpoint_on_span += 1
            findings.append({
                "code": "JUMPER_ENDPOINT_ON_SPAN", "row": row, "col": col,
                "endpoint_wires": sorted(ids), "interior_wires": inside,
            })

    occupied: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    if pin_holes is not None:
        if not isinstance(pin_holes, list):
            raise ValueError("pin_holes must be a list")
        for index, pad in enumerate(pin_holes):
            pos = _hole(pad, rows=rows, cols=cols, context=f"pin_holes[{index}]")
            occupied[(pos[1], pos[0])].append(pad)
    pin_pass_through = 0
    landing_net_conflicts = 0
    landing_net_unverified = 0
    pad_pin_conflicts = 0
    for (col, row), pads in sorted(occupied.items()):
        known_nets = {str(p.get("net_id")) for p in pads if p.get("net_id") is not None}
        if len(known_nets) > 1:
            pad_pin_conflicts += 1
            findings.append({
                "code": "DIFFERENT_NET_PINS_SAME_HOLE",
                "row": row, "col": col, "nets": sorted(known_nets),
            })
        if (col, row) in intermediate:
            pin_pass_through += 1
            findings.append({
                "code": "INTERMEDIATE_PAD_PASS_THROUGH", "row": row, "col": col,
                "wires": sorted(intermediate[(col, row)]),
                "pads": [str(p.get("ref", "?")) for p in pads],
            })
        for wire_id in landings.get((col, row), []):
            net = (trusted_wire_nets or {}).get(wire_id)
            if (not net or any(p.get("net_id") is None for p in pads)):
                landing_net_unverified += 1
                findings.append({
                    "code": "PIN_LANDING_NET_UNVERIFIED", "row": row, "col": col,
                    "wire": wire_id, "pads": [str(p.get("ref", "?")) for p in pads],
                })
            elif any(str(p.get("net_id")) != str(net) for p in pads):
                landing_net_conflicts += 1
                findings.append({
                    "code": "JUMPER_LANDING_DIFFERENT_NET", "row": row, "col": col,
                    "wire": wire_id, "wire_net": str(net),
                    "pad_nets": sorted(known_nets),
                })
    findings.sort(key=lambda x: (
        x.get("col", -1), x.get("gap_row", x.get("row", -1)), x["code"]
    ))
    return {
        "status": "STRICT_OCCUPANCY_VIOLATION" if findings else "STRICT_2D_CLEAR",
        "counts": {
            "wires": len(wires),
            "overlap_pairs": len(pair_ids),
            "stacked_gaps": stacked,
            "excess_gap_occupancy": excess,
            "max_stack_depth": max_depth,
            "shared_landing_holes": shared_landings,
            "endpoint_on_span_holes": endpoint_on_span,
            "intermediate_pad_holes": pin_pass_through,
            "landing_net_conflicts": landing_net_conflicts,
            "landing_net_unverified": landing_net_unverified,
            "different_net_pad_holes": pad_pin_conflicts,
        },
        "findings": findings,
        "pad_evidence": "SUPPLIED" if pin_holes is not None else "NOT_SUPPLIED",
        "wire_net_evidence": (
            "SUPPLIED" if trusted_wire_nets is not None else "NOT_SUPPLIED"
        ),
        "physical_pass": False,
        "cut_access": "unverified",
        "limitations": [
            "2D hole/gap occupancy only, not full independent electrical verification",
            "caller-supplied net and pad evidence is not independently rederived here",
            "measured wire/body/lead envelopes and cut-tool access unverified",
        ],
    }


__all__ = ["audit_strict_occupancy"]
