"""Experimental Hell Mode search moves for between-hole strip cuts.

These moves never establish electrical correctness themselves. Every output
must be passed through two independent electrical checks before acceptance.
No cut is claimed tool-accessible. Board dimensions and component locks are
untouched. No original project is mutated.
"""
from __future__ import annotations

import copy
import random
from typing import Any


def _between_positions(board: dict[str, Any]) -> set[tuple[int, int]]:
    rows, cols = board["rows"], board["cols"]
    positions = set()
    for i, cut in enumerate(board.get("cuts", [])):
        if cut.get("kind", "between") != "between":
            raise ValueError(f"cut[{i}]: non-between cuts require a different model")
        row, col = cut["row"], cut["col"]
        if (type(row) is not int or type(col) is not int
                or not (0 <= row < rows and 0 <= col < cols - 1)):
            raise ValueError(f"cut[{i}]: outside board")
        if (row, col) in positions:
            raise ValueError(f"cut[{i}]: duplicate cut location")
        positions.add((row, col))
    return positions


def propose_cut_change(
    project: dict[str, Any],
    rng: random.Random,
    *, max_radius: int = 3,
) -> tuple[dict[str, Any], str] | None:
    """Propose a reversible-by-copy cut removal/translation for exploration.

    Moves include removal, horizontal shift and shifting a cut to an adjacent
    row. They may create shorts or opens. The caller MUST reject such states
    through full independent electrical verification before considering them.
    """
    board = project["board"]
    cuts = board.get("cuts", [])
    if not cuts:
        return None
    if max_radius < 1:
        raise ValueError("max_radius must be positive")
    positions = _between_positions(board)
    idx = rng.randrange(len(cuts))
    cut = cuts[idx]
    old = (cut["row"], cut["col"])
    rows, cols = board["rows"], board["cols"]
    actions: list[tuple[str, tuple[int, int] | None]] = [("cut_remove", None)]
    for offset in range(-max_radius, max_radius + 1):
        if offset == 0:
            continue
        col = old[1] + offset
        if 0 <= col < cols - 1 and (old[0], col) not in positions:
            actions.append(("cut_shift", (old[0], col)))
    for diff in (-1, 1):
        row = old[0] + diff
        if 0 <= row < rows and (row, old[1]) not in positions:
            actions.append(("cut_row_change", (row, old[1])))
    if not actions:
        return None
    kind, replacement = rng.choice(actions)
    candidate = copy.deepcopy(project)
    if replacement is None:
        del candidate["board"]["cuts"][idx]
    else:
        candidate["board"]["cuts"][idx]["row"] = replacement[0]
        candidate["board"]["cuts"][idx]["col"] = replacement[1]
    return candidate, kind


def remove_redundant_cuts(
    project: dict[str, Any], electrical_check,
) -> tuple[dict[str, Any], list[tuple[int, int]]]:
    """Greedily delete individually redundant cuts, re-verifying each step.

    A candidate cut is removed only if both electrical verifiers accept the
    *complete* project after removal. The caller supplies the dual checker.
    """
    state = copy.deepcopy(project)
    _between_positions(state["board"])
    removed: list[tuple[int, int]] = []
    index = 0
    while index < len(state["board"]["cuts"]):
        cut = state["board"]["cuts"][index]
        trial = copy.deepcopy(state)
        trial["board"]["cuts"].pop(index)
        if electrical_check(trial):
            removed.append((cut["row"], cut["col"]))
            state = trial
        else:
            index += 1
    return state, removed


__all__ = ["propose_cut_change", "remove_redundant_cuts"]
