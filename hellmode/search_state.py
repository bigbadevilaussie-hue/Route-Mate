"""Hell Mode v0.3 search-state / verified-record type barrier and cut derivation.

This module is a PRE-CONSTRUCTION FOUNDATION, not an enabled new solver.

- Cut locations are derived from horizontal strip-owner transitions, with
  per-wire net ownership explicitly supplied by the search state.
- Incomplete electrical states get an integer union-find gradient, rather
  than being incorrectly named "failed certified results".
- SearchState and CertifiedRecord are different types. Only the latter can
  emit a RECORD, and its factory always calls the public independent
  verify_layout entry point before creating one.

No wire/body 2.5D or cut-tool accessibility proof is invented. The current
independent facade awards no certified records; this is intentional.

CUTS ARE NOT A UNIQUE FUNCTION OF PLACEMENT + ASSIGNMENTS ALONE. Jumper
endpoint ownership and valid alternative strip boundaries also matter.
The deterministic derivation below chooses one minimal transition cut per
adjacent different-owner anchor pair and preserves an existing cut when
one is already in the allowed interval. The resulting raw candidate
must still be independently checked before ever becoming a RECORD.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping

from .incremental_state import TransactionalState
from .topology_moves import StripSegments
from .conflict_repair import _score


@dataclass(frozen=True, slots=True)
class InfeasibilityPenalty:
    """Search guidance, NEVER electrical or physical certification."""

    disconnected_group_excess: int
    disconnected_net_count: int
    short_group_excess: int
    illegal_2d_holes: int
    excess_gap_occupancy: int
    max_stack_depth: int
    cut_count: int
    wire_length_holes: int

    @property
    def objective(self) -> tuple[int, ...]:
        """Lexicographic exploration objective.

        Short groups are hard vetoes for normal annealing. The remaining
        entries provide a gradient for temporarily open/stacked states.
        Annealing may accept equal/worse temporary proposals; this tuple
        is NOT itself a verified-record promotion criterion.
        """
        return (
            self.short_group_excess,
            self.disconnected_group_excess,
            self.illegal_2d_holes,
            self.excess_gap_occupancy,
            self.max_stack_depth,
            self.cut_count,
            self.wire_length_holes,
        )

    @property
    def search_electrical_open(self) -> bool:
        return self.disconnected_group_excess > 0

    @property
    def strict_2d_penalty_zero(self) -> bool:
        return not (
            self.disconnected_group_excess
            or self.short_group_excess
            or self.illegal_2d_holes
            or self.excess_gap_occupancy
            or self.max_stack_depth > 1
        )


def _search_pads(state: TransactionalState) -> list[dict[str, Any]]:
    """Search-side footprint pads, independent of verifier pin resolver."""
    return [
        {"row": row, "col": col, "net_id": net}
        for padlist in state._component_pads.values()
        for row, col, net in padlist
    ]


def _required_owners(
    state: TransactionalState,
    wire_nets: Mapping[str, str],
) -> dict[int, dict[int, str]]:
    """Collect placed terminal and jumper endpoint owner anchors per row."""
    board = state._project["board"]
    if set(wire_nets) != {w["id"] for w in board.get("wires", [])}:
        raise ValueError("net ownership must cover every current jumper exactly")
    anchor: dict[int, dict[int, str]] = defaultdict(dict)

    def put(row: int, col: int, net: str) -> None:
        if not net:
            raise ValueError("empty or unknown copper owner")
        existing = anchor[row].get(col)
        if existing is not None and existing != net:
            raise ValueError(
                f"different-net terminals share hole ({row},{col}); "
                "no between-hole cut can resolve it"
            )
        anchor[row][col] = net

    for pads in state._component_pads.values():
        for row, col, net in pads:
            if net is not None:
                put(row, col, str(net))
    for wire in board.get("wires", []):
        net = wire_nets[wire["id"]]
        for endpoint in (wire["from"], wire["to"]):
            put(endpoint["row"], endpoint["col"], str(net))
    return anchor


def derive_required_cuts(
    project: dict[str, Any],
    wire_nets: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recompute cuts deterministically from current physical owner anchors.

    *Not* a proof of electrical or physical correctness. Existing cuts are
    preferred when one falls between different-net neighbouring anchors.
    Unneeded existing cuts are removed. No free-standing cut search dimension.
    """
    source = copy.deepcopy(project)
    state = TransactionalState(source)
    owners = _required_owners(state, wire_nets)
    old: dict[tuple[int, int], dict[str, Any]] = {}
    for cut in source["board"].get("cuts", []):
        if cut.get("kind", "between") != "between":
            raise ValueError("cut derivation only supports between-hole cuts")
        key = (cut["row"], cut["col"])
        if key in old:
            raise ValueError("duplicate original cut")
        old[key] = copy.deepcopy(cut)

    selected: dict[tuple[int, int], dict[str, Any]] = {}
    for row, by_col in sorted(owners.items()):
        anchors = sorted(by_col.items())
        for (left, left_net), (right, right_net) in zip(
            anchors, anchors[1:]
        ):
            if left_net == right_net:
                continue
            if left >= right:
                raise AssertionError("anchors are not strictly ordered")
            # Any boundary [left, right) electrically isolates these
            # adjacent nets on the horizontal strip. Prefer retaining
            # a known cut, else create the central deterministic one.
            mid = (left + right - 1) // 2
            options = sorted(
                (c for (r, c) in old if r == row and left <= c < right),
                key=lambda col: (abs(col - mid), col),
            )
            col = options[0] if options else mid
            key = (row, col)
            selected[key] = copy.deepcopy(old.get(key, {
                "row": row, "col": col, "kind": "between",
            }))
    result = copy.deepcopy(source)
    result["board"]["cuts"] = [
        selected[k] for k in sorted(selected)
    ]
    return result, {
        "cuts_before": len(source["board"].get("cuts", [])),
        "cuts_derived": len(selected),
        "cuts_kept_from_input": len(set(selected) & set(old)),
        "cuts_added": len(set(selected) - set(old)),
        "cuts_removed": len(set(old) - set(selected)),
        "source": "placed terminals + search jumper-endpoint net ownership",
        "electrical_certification": "UNVERIFIED",
        "physical_certification": "UNVERIFIED",
    }


def grade_search_state(
    project: dict[str, Any],
    wire_nets: Mapping[str, str],
) -> InfeasibilityPenalty:
    """Full recomputation of a SEARCH gradient, independent of verifier.

    Unlike a bool electrical check, this counts how many disconnected
    components remain within each net, using the current copper strips
    and vertical jumper bridges. It also reports cross-net shorts as a
    separate hard-veto count (never a licence to promote a record).
    """
    candidate = TransactionalState(project)
    board = candidate._project["board"]
    # Scoring must tolerate temporarily shorted physical holes so the
    # short penalty remains observable. Cut derivation, by contrast, fails
    # closed on such a hole because no strip cut can ever repair it.
    if set(wire_nets) != {w["id"] for w in board.get("wires", [])}:
        raise ValueError("net ownership must cover every current jumper exactly")
    strips = StripSegments(board)
    parent = list(range(len(strips.segments)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def unite(a: int, b: int) -> None:
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for wire in board.get("wires", []):
        unite(strips.island(wire["from"]), strips.island(wire["to"]))

    roots_by_net: dict[str, set[int]] = defaultdict(set)
    nets_by_root: dict[int, set[str]] = defaultdict(set)
    pads = _search_pads(candidate)
    for pad in pads:
        net = pad["net_id"]
        if net is None:
            continue
        root = find(strips.island(pad))
        roots_by_net[net].add(root)
        nets_by_root[root].add(net)

    open_excess = sum(max(0, len(roots) - 1)
                      for roots in roots_by_net.values())
    open_nets = sum(len(roots) > 1 for roots in roots_by_net.values())
    short_excess = sum(max(0, len(nets) - 1)
                       for nets in nets_by_root.values())

    geometry, _ = _score(board.get("wires", []), pads, dict(wire_nets))
    max_stack = candidate.max_stack_depth
    return InfeasibilityPenalty(
        disconnected_group_excess=open_excess,
        disconnected_net_count=open_nets,
        short_group_excess=short_excess,
        illegal_2d_holes=geometry.illegal_holes,
        excess_gap_occupancy=geometry.excess,
        max_stack_depth=max_stack,
        cut_count=len(board.get("cuts", [])),
        wire_length_holes=geometry.total_length_holes,
    )


@dataclass(frozen=True, slots=True, init=False)
class SearchState:
    """Incomplete or penalised candidate. No RECORD serialization exists."""

    _canonical_json: str
    wire_net_ownership: tuple[tuple[str, str], ...]
    penalty: InfeasibilityPenalty

    @classmethod
    def from_candidate(
        cls, project: dict[str, Any], wire_nets: Mapping[str, str],
        *, derive_cuts: bool = False,
    ) -> "SearchState":
        raw = copy.deepcopy(project)
        if derive_cuts:
            raw, _ = derive_required_cuts(raw, wire_nets)
        grade = grade_search_state(raw, wire_nets)
        instance = object.__new__(cls)
        object.__setattr__(
            instance, "_canonical_json",
            json.dumps(raw, sort_keys=True, separators=(",", ":")),
        )
        object.__setattr__(
            instance, "wire_net_ownership",
            tuple(sorted((str(k), str(v)) for k, v in wire_nets.items())),
        )
        object.__setattr__(instance, "penalty", grade)
        return instance

    def raw_candidate(self) -> dict[str, Any]:
        return json.loads(self._canonical_json)

    def fingerprint(self) -> str:
        return hashlib.sha256(self._canonical_json.encode()).hexdigest()

    def to_record(self) -> dict[str, Any]:
        raise RuntimeError(
            "SEARCH_STATE cannot become RECORD; use independently "
            "verified CertifiedRecord.from_project"
        )


@dataclass(frozen=True, slots=True, init=False)
class CertifiedRecord:
    """Record type with one factory guarded by independent verifier.

    This class cannot be constructed from a SearchState merely by score
    threshold. The independent verifier must explicitly grant record
    eligibility and the record tier; the current verifier grants neither.
    """

    _canonical_json: str
    _verifier_status: str

    @classmethod
    def from_project(
        cls, project: dict[str, Any], spec: dict | None = None,
    ) -> "CertifiedRecord":
        # Import ONLY the PUBLIC independent verifier entry point here.
        from .verify_layout import verify_layout

        report = verify_layout(copy.deepcopy(project), spec)
        if (
            report.get("record_eligible") is not True
            or report.get("status") not in {"RECORD", "BUILD_READY"}
            or not report.get("electrical", {}).get("status") == "PASS"
        ):
            raise ValueError(
                "independent verifier withheld RECORD; "
                "cannot serialise an exploratory search state"
            )
        instance = object.__new__(cls)
        object.__setattr__(
            instance, "_canonical_json",
            json.dumps(project, sort_keys=True, separators=(",", ":")),
        )
        object.__setattr__(instance, "_verifier_status", report["status"])
        return instance

    def to_record(self) -> dict[str, Any]:
        return json.loads(self._canonical_json)

    @property
    def verifier_status(self) -> str:
        return self._verifier_status


__all__ = [
    "InfeasibilityPenalty", "SearchState", "CertifiedRecord",
    "grade_search_state", "derive_required_cuts",
]
