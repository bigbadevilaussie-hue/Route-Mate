"""Broad-phase optimisation must reproduce the old exhaustive geometry exactly."""
from __future__ import annotations

import json
import random
import unittest
from collections import defaultdict
from fractions import Fraction as F
from pathlib import Path

from solve.wire_keepout import (
    _candidate_gaps, _hits_gap, component_keepouts, vertical_gap_keepouts,
)

ROOT = Path(__file__).resolve().parent.parent


def old_exhaustive(shapes, rows, cols):
    bad = defaultdict(set)
    for shape in shapes:
        for col in range(cols):
            for row in range(rows - 1):
                if _hits_gap(shape, row, col):
                    bad[(row, col)].add(shape["label"])
    return dict(bad)


class BroadPhaseKeepoutParityTests(unittest.TestCase):
    def assert_shape_equivalent(self, shapes, rows, cols):
        for shape in shapes:
            with self.subTest(shape=shape, rows=rows, cols=cols):
                observed = {
                    cell for cell in _candidate_gaps(shape, rows, cols)
                    if _hits_gap(shape, *cell)
                }
                expected = {
                    (row, col) for col in range(cols) for row in range(rows - 1)
                    if _hits_gap(shape, row, col)
                }
                self.assertEqual(observed, expected)

    def test_edge_and_fractional_boundaries(self):
        shapes = []
        for row in (F(-4), F(0), F(1, 2), F(5), F(10), F(14)):
            for col in (F(-3), F(0), F(3, 2), F(8), F(16)):
                shapes.extend([
                    {"kind": "square", "label": "S", "row": row,
                     "col": col, "half": F(1, 2)},
                    {"kind": "rect", "label": "R", "r0": row - F(1, 2),
                     "r1": row + F(3, 2), "c0": col - F(1, 2),
                     "c1": col + F(1, 2)},
                    {"kind": "circle", "label": "C", "row": row,
                     "col": col, "radius2": F(25, 16)},
                    {"kind": "circle", "label": "C", "row": row,
                     "col": col, "radius2": F(4)},
                ])
        self.assert_shape_equivalent(shapes, 12, 13)

    def test_randomised_exact_equivalence(self):
        rng = random.Random(23140)
        shapes = []
        for i in range(100):
            row = F(rng.randrange(-10, 80), 2)
            col = F(rng.randrange(-10, 100), 2)
            if i % 3 == 0:
                shapes.append({"kind": "square", "label": str(i),
                               "row": row, "col": col, "half": F(1, 2)})
            elif i % 3 == 1:
                shapes.append({"kind": "rect", "label": str(i),
                               "r0": row, "r1": row + F(5, 2),
                               "c0": col - F(3, 2), "c1": col + F(1, 2)})
            else:
                shapes.append({"kind": "circle", "label": str(i),
                               "row": row, "col": col,
                               "radius2": F(rng.choice((0, 1, 4, 25, 100)), 16)})
        self.assert_shape_equivalent(shapes, 35, 45)

    def test_saved_audio_moto_exactly_equal_to_old_scan(self):
        # Historical solved exports exercise real footprint overrides,
        # rotated footprints, flexible leads and many body cells.
        sources = (
            "benchmarks/audio/audio10wires38cuts.json",
            "benchmarks/moto/moto14wires30cuts.json",
        )
        for filename in sources:
            with self.subTest(filename=filename):
                project = json.loads((ROOT / filename).read_text(encoding="utf-8"))
                rows, cols = int(project["board"]["rows"]), int(project["board"]["cols"])
                shapes = component_keepouts(project)
                expected = old_exhaustive(shapes, rows, cols)
                actual = dict(vertical_gap_keepouts(project, rows, cols))
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
