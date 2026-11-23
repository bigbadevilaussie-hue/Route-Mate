"""M1 transactional candidate state: journalled reversible jumper and placement moves.

This is a search-state mechanism, NOT a router or verifier. Its hot-path
occupancy counts are independent of hellmode.strict_occupancy and are shadow-
checked by tests against recomputation from raw JSON. It never awards RECORD.
Component footprint bounds use the shared *normative geometry model*; the
independent verifier is forbidden to depend on this evaluator.

M1 tranche: replace a vertical jumper's endpoints; translate/rotate an
unlocked placed component. Rip-up/reroute, cut edits, region moves and every
remaining move variant require separate implementation and acceptance tests.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from board_geometry import BUILTIN_DEFS, component_geometry, resolve_definition
from placement_policy import is_off_board_component


Hole = tuple[int, int]


@dataclass(frozen=True)
class _Undo:
    kind: str
    index: int
    old: dict[str, Any]


class TransactionalState:
    """Private mutable candidate with single-writer transactions.

    No outside caller can edit the live project through the public API.
    Each mutation journals exactly its touched wire/component record and
    modifies only the corresponding occupancy counter deltas.
    """

    def __init__(self, project: dict[str, Any]):
        self._project = copy.deepcopy(project)
        board = self._project["board"]
        self.rows, self.cols = board["rows"], board["cols"]
        if (type(self.rows) is not int or type(self.cols) is not int
                or self.rows < 2 or self.cols < 2):
            raise ValueError("invalid fixed board dimensions")
        self._wire_index: dict[str, int] = {}
        self._component_index: dict[str, int] = {}
        self._gap: Counter[Hole] = Counter()
        self._landing: Counter[Hole] = Counter()
        self._passing: Counter[Hole] = Counter()
        self._pads: Counter[Hole] = Counter()
        self._pad_net: dict[Hole, Counter[str]] = defaultdict(Counter)
        self._component_pads: dict[str, list[tuple[int, int, str | None]]] = {}
        self._component_bodies: dict[str, tuple[Hole, ...]] = {}
        self._depths: Counter[int] = Counter()
        self.excess_gap_occupancy = 0
        self.stacked_gaps = 0
        self.shared_landing_holes = 0
        self.endpoint_on_span_holes = 0
        self.intermediate_pad_holes = 0
        self._active: Transaction | None = None
        self._definitions = dict(BUILTIN_DEFS)
        self._definitions.update({
            str(d["id"]): d for d in self._project.get("componentDefs", [])
            if isinstance(d, dict) and d.get("id")
        })
        self._assigned: dict[str, dict[str, str]] = defaultdict(dict)
        for item in self._project.get("netAssignments", []):
            key, pin = str(item["componentId"]), str(item["pinId"])
            self._assigned[key][pin] = str(item["netId"])

        for i, component in enumerate(self._project.get("components", [])):
            cid = str(component["id"])
            if cid in self._component_index:
                raise ValueError(f"duplicate component ID {cid}")
            self._component_index[cid] = i
            pads, bodies = self._component_geometry(component)
            self._component_pads[cid] = pads
            self._component_bodies[cid] = bodies
            for row, col, net in pads:
                self._bump_pad((row, col), net, 1)

        for index, wire in enumerate(board.get("wires", [])):
            ident = str(wire.get("id", f"wire[{index}]"))
            if ident in self._wire_index:
                raise ValueError(f"duplicate wire ID {ident}")
            self._wire_index[ident] = index
            self._apply_wire(wire, 1)

    def _validate_hole(self, point: Hole) -> None:
        if (not isinstance(point, tuple) or len(point) != 2
                or any(type(x) is not int for x in point)
                or not (0 <= point[0] < self.rows and 0 <= point[1] < self.cols)):
            raise ValueError(f"hole {point!r} outside fixed board")

    def _endpoints(self, wire: dict[str, Any]) -> tuple[Hole, Hole]:
        a = wire["from"]
        b = wire["to"]
        start = (a["row"], a["col"])
        stop = (b["row"], b["col"])
        self._validate_hole(start)
        self._validate_hole(stop)
        if start[1] != stop[1] or start[0] == stop[0]:
            raise ValueError("jumper must be a nonzero straight vertical span")
        return start, stop

    def _hole_flags(self, point: Hole) -> tuple[int, int, int]:
        endpoint = self._landing[point]
        interior = self._passing[point]
        pad = self._pads[point]
        return int(endpoint > 1), int(endpoint > 0 and interior > 0), int(pad > 0 and interior > 0)

    def _bump_hole(self, target: Counter[Hole], point: Hole, step: int) -> None:
        before = self._hole_flags(point)
        next_value = target[point] + step
        if next_value < 0:
            raise AssertionError("occupancy counter underflow")
        if next_value:
            target[point] = next_value
        else:
            target.pop(point, None)
        after = self._hole_flags(point)
        self.shared_landing_holes += after[0] - before[0]
        self.endpoint_on_span_holes += after[1] - before[1]
        self.intermediate_pad_holes += after[2] - before[2]

    def _bump_pad(self, point: Hole, net: str | None, step: int) -> None:
        self._bump_hole(self._pads, point, step)
        if net is not None:
            counter = self._pad_net[point]
            new_value = counter[net] + step
            if new_value < 0:
                raise AssertionError("pin-net counter underflow")
            if new_value:
                counter[net] = new_value
            else:
                counter.pop(net, None)
            if not counter:
                self._pad_net.pop(point, None)

    def _bump_gap(self, key: Hole, step: int) -> None:
        before = self._gap[key]
        after = before + step
        if after < 0:
            raise AssertionError("jumper-gap counter underflow")
        self.excess_gap_occupancy += max(0, after - 1) - max(0, before - 1)
        self.stacked_gaps += int(after > 1) - int(before > 1)
        if before:
            self._depths[before] -= 1
            if not self._depths[before]:
                del self._depths[before]
        if after:
            self._gap[key] = after
            self._depths[after] += 1
        else:
            self._gap.pop(key, None)

    def _apply_wire(self, wire: dict[str, Any], sign: int) -> None:
        a, b = self._endpoints(wire)
        low, high = sorted((a[0], b[0]))
        col = a[1]
        for row in range(low, high):
            self._bump_gap((col, row), sign)
        self._bump_hole(self._landing, a, sign)
        self._bump_hole(self._landing, b, sign)
        for row in range(low + 1, high):
            self._bump_hole(self._passing, (row, col), sign)

    def _component_geometry(
        self, component: dict[str, Any]
    ) -> tuple[list[tuple[int, int, str | None]], tuple[Hole, ...]]:
        cid = str(component["id"])
        if is_off_board_component(component):
            if component.get("boardExcluded") is True and component.get("offBoard") is not True:
                return [], ()
            pads = []
            for pin, pos in (component.get("leads") or {}).items():
                point = (pos["row"], pos["col"])
                self._validate_hole(point)
                pads.append((*point, self._assigned[cid].get(str(pin))))
            return pads, ()
        definition = resolve_definition(component, self._definitions)
        if definition is None:
            raise ValueError(f"{cid}: unknown footprint")
        pins, bodies = component_geometry(component, definition)
        pad_records: list[tuple[int, int, str | None]] = []
        defined = definition.get("pins") or []
        pin_nets = dict(self._assigned[cid])
        for index, item in enumerate(defined):
            alias = str(item.get("id"))
            pin_nets.setdefault(alias, self._assigned[cid].get(str(index + 1)))
        for pin in pins:
            point = (pin["row"], pin["col"])
            self._validate_hole(point)
            pad_records.append((*point, pin_nets.get(str(pin["id"]))))
        for point in bodies:
            self._validate_hole(point)
        return pad_records, tuple(bodies)

    def _assert_no_new_pin_short(
        self, old: list[tuple[int, int, str | None]],
        new: list[tuple[int, int, str | None]],
    ) -> None:
        affected = {(r, c) for r, c, _ in old + new}
        candidates: dict[Hole, Counter[str]] = {
            pos: self._pad_net.get(pos, Counter()).copy() for pos in affected
        }
        for row, col, net in old:
            if net is not None:
                candidates[(row, col)][net] -= 1
                if candidates[(row, col)][net] == 0:
                    del candidates[(row, col)][net]
        for row, col, net in new:
            if net is not None:
                candidates[(row, col)][net] += 1
        for point, owners in candidates.items():
            if len([net for net, count in owners.items() if count > 0]) > 1:
                raise ValueError(f"component move would share hole {point} across nets")

    @property
    def max_stack_depth(self) -> int:
        return max(self._depths, default=0)

    def metrics(self) -> dict[str, int]:
        return {
            "excess_gap_occupancy": self.excess_gap_occupancy,
            "stacked_gaps": self.stacked_gaps,
            "max_stack_depth": self.max_stack_depth,
            "shared_landing_holes": self.shared_landing_holes,
            "endpoint_on_span_holes": self.endpoint_on_span_holes,
            "intermediate_pad_holes": self.intermediate_pad_holes,
        }

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._project)

    def fingerprint(self) -> str:
        encoded = json.dumps(self._project, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def transaction(self) -> "Transaction":
        if self._active is not None:
            raise RuntimeError("another transaction is active")
        tx = Transaction(self)
        self._active = tx
        return tx


class Transaction:
    """One candidate mutation journal; rollback restores byte-equivalent data."""

    def __init__(self, state: TransactionalState):
        self._state = state
        self._undo: list[_Undo] = []
        self._closed = False
        self.dirty_holes: set[Hole] = set()
        self.dirty_gaps: set[Hole] = set()
        self.dirty_net_ids: set[str] = set()
        self.requires_full_reroute = False

    def _check_open(self) -> None:
        if self._closed or self._state._active is not self:
            raise RuntimeError("transaction already closed")

    def move_wire(self, wire_id: str, start: Hole, end: Hole) -> None:
        """Replace a jumper's straight span; electrical legality is not assumed."""
        self._check_open()
        if wire_id not in self._state._wire_index:
            raise KeyError(wire_id)
        index = self._state._wire_index[wire_id]
        old = self._state._project["board"]["wires"][index]
        new = copy.deepcopy(old)
        new["from"], new["to"] = (
            {"row": start[0], "col": start[1]},
            {"row": end[0], "col": end[1]},
        )
        old_ends = self._state._endpoints(old)
        new_ends = self._state._endpoints(new)  # validate first; no partial mutation
        for a, b in (old_ends, new_ends):
            lo, hi = sorted((a[0], b[0]))
            self.dirty_holes.update((a, b))
            self.dirty_holes.update((r, a[1]) for r in range(lo + 1, hi))
            self.dirty_gaps.update((a[1], row) for row in range(lo, hi))
        self._state._apply_wire(old, -1)
        self._state._project["board"]["wires"][index] = new
        self._state._apply_wire(new, 1)
        self._undo.append(_Undo("wire", index, copy.deepcopy(old)))
        self.requires_full_reroute = True

    def move_component(
        self, component_id: str, row: int, col: int, *,
        rotation: int | None = None,
    ) -> None:
        """Move an unlocked placed part; rigidly translate explicit flex ends."""
        self._check_open()
        if component_id not in self._state._component_index:
            raise KeyError(component_id)
        index = self._state._component_index[component_id]
        old = self._state._project["components"][index]
        if (is_off_board_component(old) or old.get("locked")
                or old.get("edge") or old.get("edgeLocked")):
            raise ValueError(f"{component_id}: component is locked or off-board")
        if type(row) is not int or type(col) is not int:
            raise ValueError("position must use integer grid coordinates")
        old_pos = old.get("boardPos")
        if not isinstance(old_pos, dict):
            raise ValueError("cannot move an unplaced component")
        new = copy.deepcopy(old)
        new["boardPos"] = {"row": row, "col": col}
        next_rot = old.get("rotation", 0) if rotation is None else rotation
        if type(next_rot) is not int or next_rot % 90:
            raise ValueError("unsupported rotation")
        new["rotation"] = next_rot % 360
        explicit_flex = old.get("flexibleEndPos")
        if isinstance(explicit_flex, dict):
            if rotation is not None and next_rot % 360 != (old.get("rotation", 0) or 0) % 360:
                raise ValueError("rotation of explicit flexible wire component not yet supported")
            new["flexibleEndPos"] = {
                "row": explicit_flex["row"] + row - old_pos["row"],
                "col": explicit_flex["col"] + col - old_pos["col"],
            }
        pads, bodies = self._state._component_geometry(new)
        prior = self._state._component_pads[component_id]
        self._state._assert_no_new_pin_short(prior, pads)
        for r, c, net in prior:
            self._state._bump_pad((r, c), net, -1)
        for r, c, net in pads:
            self._state._bump_pad((r, c), net, 1)
        self._state._component_pads[component_id] = pads
        self._state._component_bodies[component_id] = bodies
        self._state._project["components"][index] = new
        self._undo.append(_Undo("component", index, copy.deepcopy(old)))
        self.dirty_holes.update((r, c) for r, c, _ in prior + pads)
        self.dirty_net_ids.update(self._state._assigned.get(component_id, {}).values())
        self.requires_full_reroute = True

    def rollback(self) -> None:
        self._check_open()
        state = self._state
        for item in reversed(self._undo):
            if item.kind == "wire":
                current = state._project["board"]["wires"][item.index]
                state._apply_wire(current, -1)
                state._project["board"]["wires"][item.index] = item.old
                state._apply_wire(item.old, 1)
            elif item.kind == "component":
                current = state._project["components"][item.index]
                cid = str(current["id"])
                for r, c, net in state._component_pads[cid]:
                    state._bump_pad((r, c), net, -1)
                pads, bodies = state._component_geometry(item.old)
                for r, c, net in pads:
                    state._bump_pad((r, c), net, 1)
                state._component_pads[cid] = pads
                state._component_bodies[cid] = bodies
                state._project["components"][item.index] = item.old
        self._closed = True
        state._active = None

    def commit(self) -> None:
        self._check_open()
        self._closed = True
        self._state._active = None

    def __enter__(self) -> "Transaction":
        self._check_open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._closed:
            self.rollback()


__all__ = ["TransactionalState", "Transaction"]
