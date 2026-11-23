"""Hell Mode alpha topology mutation proposals (fixed cuts and placement).

Unlike column-only legalisation, this code can replace a bridge with a jumper
between different endpoint ROWS, or use two jumpers through an unused
horizontal copper island. Proposals are untrusted exploratory moves: the
independent electrical and geometry checks still decide validity.

Intentionally no imports from any verifier or geometry certification module.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any
import random


@dataclass(frozen=True)
class Segment:
    index: int
    row: int
    left: int
    right: int


class _Components:
    def __init__(self, n: int):
        self.root = list(range(n))

    def find(self, index: int) -> int:
        while self.root[index] != index:
            self.root[index] = self.root[self.root[index]]
            index = self.root[index]
        return index

    def link(self, a: int, b: int) -> None:
        a, b = self.find(a), self.find(b)
        if a != b:
            self.root[max(a, b)] = min(a, b)


class StripSegments:
    """Independent *routing proposal* strip decomposition.

    This copy intentionally does not share implementation with the
    authoritative independent graph in copper_model.py. No hole cuts, board
    resizing, multi-segment wires or diagonal jumpers are proposed.
    """

    def __init__(self, board: dict[str, Any]):
        rows, cols = board["rows"], board["cols"]
        if (type(rows) is not int or type(cols) is not int
                or rows < 2 or cols < 2):
            raise ValueError("invalid fixed board dimensions")
        self.rows, self.cols = rows, cols
        cuts: dict[int, set[int]] = defaultdict(set)
        for cut in board.get("cuts", []):
            if cut.get("kind", "between") != "between":
                raise ValueError("topology alpha requires only between-hole cuts")
            r, c = cut["row"], cut["col"]
            if (type(r) is not int or type(c) is not int or
                    not (0 <= r < rows and 0 <= c < cols - 1)):
                raise ValueError("bad cut coordinate")
            cuts[r].add(c)
        self.hole_segment: list[list[int]] = [[] for _ in range(rows)]
        self.segments: list[Segment] = []
        for row in range(rows):
            left = 0
            for col in range(cols):
                if col in cuts[row] or col == cols - 1:
                    idx = len(self.segments)
                    self.segments.append(Segment(idx, row, left, col))
                    self.hole_segment[row].extend([idx] * (col - left + 1))
                    left = col + 1

    def island(self, point: dict[str, int]) -> int:
        r, c = point["row"], point["col"]
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            raise ValueError("wire endpoint outside board")
        return self.hole_segment[r][c]

    def _without_wire(
        self, wires: list[dict], excluded: str
    ) -> _Components:
        uf = _Components(len(self.segments))
        for wire in wires:
            if wire["id"] == excluded:
                continue
            uf.link(self.island(wire["from"]), self.island(wire["to"]))
        return uf

    def candidate_bridges(
        self, board: dict, wire_id: str, *, allow_detour: bool,
        rng: random.Random | None = None, max_candidates: int = 80,
    ) -> tuple[list[tuple[dict, ...]], bool]:
        """Reservoir-sample 1- or 2-wire bridges preserving connectivity.

        A 2-wire detour passes through an *unused, unconnected* strip island,
        so it cannot short another net. Final proof comes from verification.
        Return (candidate replacement tuples, original-wire-is-bridge).
        """
        wires = board.get("wires", [])
        selected = next((w for w in wires if w["id"] == wire_id), None)
        if selected is None:
            raise KeyError(wire_id)
        uf = self._without_wire(wires, wire_id)
        left = uf.find(self.island(selected["from"]))
        right = uf.find(self.island(selected["to"]))
        if left == right:
            return [], False

        by_root: dict[int, list[Segment]] = defaultdict(list)
        for segment in self.segments:
            by_root[uf.find(segment.index)].append(segment)
        randomizer = rng if rng is not None else random.Random(0)
        singles: list[tuple[dict, ...]] = []
        detours: list[tuple[dict, ...]] = []
        seen_single = seen_detour = 0

        def offer(proposal: tuple[dict, ...], *, detour: bool = False) -> None:
            nonlocal seen_single, seen_detour
            bucket = detours if detour else singles
            if detour:
                seen_detour += 1
                count = seen_detour
            else:
                seen_single += 1
                count = seen_single
            if len(bucket) < max_candidates:
                bucket.append(proposal)
            else:
                pos = randomizer.randrange(count)
                if pos < max_candidates:
                    bucket[pos] = proposal

        original = (
            selected["from"]["row"], selected["from"]["col"],
            selected["to"]["row"], selected["to"]["col"],
        )

        def jumper(name: str, a: Segment, b: Segment, col: int) -> dict:
            return {
                "id": name,
                "from": {"row": a.row, "col": col},
                "to": {"row": b.row, "col": col},
            }

        # Change both endpoint rows and the column while joining the SAME
        # components of the original strip-level electrical graph.
        for a in by_root[left]:
            for b in by_root[right]:
                if a.row == b.row:
                    continue
                lower = max(a.left, b.left)
                upper = min(a.right, b.right)
                for col in range(lower, upper + 1):
                    probe = (a.row, col, b.row, col)
                    reverse = (b.row, col, a.row, col)
                    if probe == original or reverse == original:
                        continue
                    offer((jumper(wire_id, a, b, col),))

        if not allow_detour:
            return singles, True

        # A detour replaces one jumper with two. It can cross distinct columns
        # on a common unused copper strip and therefore overcome the fixed-
        # span/column pigeonhole obstruction. It is not necessarily cheaper.
        degree: dict[int, int] = defaultdict(int)
        for wire in wires:
            if wire["id"] == wire_id:
                continue
            degree[self.island(wire["from"])] += 1
            degree[self.island(wire["to"])] += 1
        free = [s for s in self.segments
                if uf.find(s.index) not in (left, right)
                and degree[s.index] == 0]
        # Don't enumerate every pair of landing columns on every unused strip;
        # choose endpoints near existing jumper columns and segment boundaries.
        old_midpoint = (selected["from"]["row"] + selected["to"]["row"]) / 2
        free = sorted(free, key=lambda s: (
            abs(s.row - old_midpoint), s.index
        ))[:12]
        source_segments = by_root[left][:16]
        target_segments = by_root[right][:16]
        for mid in free:
            for a in source_segments:
                if a.row == mid.row:
                    continue
                ac_left, ac_right = max(a.left, mid.left), min(a.right, mid.right)
                if ac_left > ac_right:
                    continue
                for b in target_segments:
                    if b.row == mid.row:
                        continue
                    bc_left, bc_right = max(b.left, mid.left), min(b.right, mid.right)
                    if bc_left > bc_right:
                        continue
                    ac = {ac_left, ac_right, min(max(original[1], ac_left), ac_right)}
                    bc = {bc_left, bc_right, min(max(original[3], bc_left), bc_right)}
                    for col_a in sorted(ac):
                        for col_b in sorted(bc):
                            if col_a == col_b:
                                # Keeping separate intermediate landing holes
                                # avoids prohibited two-jumper shared endpoints.
                                continue
                            first = jumper(wire_id, a, mid, col_a)
                            second = jumper(wire_id + "-D", mid, b, col_b)
                            offer((first, second), detour=True)
        return singles + detours, True


def topology_proposal(
    project: dict[str, Any], rng: random.Random, *,
    detour: bool = True, samples: int = 10,
) -> tuple[str, tuple[dict, ...]] | None:
    """Pick one topology-changing replacement from a bounded candidate pool.

    Experimental proposal only; verifier must approve after application.
    """
    board = project["board"]
    if any(c.get("kind", "between") != "between" for c in board.get("cuts", [])):
        return None
    wires = board.get("wires", [])
    if not wires:
        return None
    segments = StripSegments(board)
    order = [w["id"] for w in wires]
    rng.shuffle(order)
    existing = set(order)
    for wire_id in order[:min(len(order), 6)]:
        proposed, is_bridge = segments.candidate_bridges(
            board, wire_id, allow_detour=detour, rng=rng
        )
        if not is_bridge or not proposed:
            continue
        feasible = [p for p in proposed
                    if len(p) == 1 or all(
                        replacement["id"] not in existing
                        for replacement in p[1:]
                    )]
        if not feasible:
            continue
        # 3:1 preference for a single-wire reroute to limit wire inflation.
        single = [p for p in feasible if len(p) == 1]
        multi = [p for p in feasible if len(p) == 2]
        choices = single if single and (not multi or rng.randrange(4)) else multi
        return wire_id, rng.choice(choices)
    return None


def apply_topology_proposal(
    project: dict[str, Any], replace_id: str, wires: tuple[dict, ...],
) -> dict[str, Any]:
    """Pure replacement; does NOT imply electrical or physical validity."""
    import copy

    result = copy.deepcopy(project)
    original = result["board"]["wires"]
    if sum(w["id"] == replace_id for w in original) != 1:
        raise ValueError("source jumper missing or duplicated")
    unchanged = [w for w in original if w["id"] != replace_id]
    ids = [w["id"] for w in unchanged] + [w["id"] for w in wires]
    if len(ids) != len(set(ids)):
        raise ValueError("proposal introduces duplicate jumper id")
    result["board"]["wires"] = unchanged + copy.deepcopy(list(wires))
    return result


__all__ = [
    "StripSegments", "topology_proposal", "apply_topology_proposal",
]
