"""Default spacing is a real placement preference, never a measured guarantee."""
from __future__ import annotations

import copy
import unittest

from collector_geometry import PITCH_MM
from geometry_sidecar import (
    _nominal_body_gap, assumed_body_pad_keepouts, inspect_assumed_contacts,
)
from solve.quick_fit import quick_fit


def capacitor(label, *, row=None, col=None, locked=False):
    part = {
        "id": label, "label": label,
        "defId": "def-cap-polarized", "value": "1000uF",
        "rotation": 0,
    }
    if row is not None:
        part["boardPos"] = {"row": row, "col": col}
    if locked:
        part["locked"] = True
    return part


def board(rows, cols, parts):
    return {
        "board": {"rows": rows, "cols": cols, "cuts": [], "wires": []},
        "components": parts, "componentDefs": [], "netAssignments": [],
    }


class DefaultBodySpacingTests(unittest.TestCase):
    def test_normal_default_enforces_one_free_hole_between_nominal_bodies(self):
        project = board(8, 18, [
            capacitor("C1", row=3, col=2, locked=True),
            capacitor("C2"),
        ])
        original = copy.deepcopy(project)
        fitted = quick_fit(project)
        self.assertEqual(fitted["status"], "PLACED", fitted.get("errors"))
        report = fitted["report"]
        self.assertEqual(report["body_spacing_requested"], 1)
        self.assertEqual(report["body_spacing_used"], 1)
        solids = assumed_body_pad_keepouts(fitted["project"])
        self.assertEqual(len(solids), 2)
        self.assertGreaterEqual(
            _nominal_body_gap(solids[0], solids[1]) + 1e-8, PITCH_MM,
            fitted["project"]["components"],
        )
        self.assertEqual(inspect_assumed_contacts(fitted["project"]), [])
        self.assertEqual(
            fitted["project"]["components"][0]["boardPos"],
            {"row": 3, "col": 2},
        )
        self.assertEqual(project, original, "Quick Fit mutated its source")

    def test_report_compact_fallback_when_one_hole_cannot_fit(self):
        project = board(2, 5, [capacitor("C1"), capacitor("C2")])
        original = copy.deepcopy(project)
        fitted = quick_fit(project)
        self.assertEqual(fitted["status"], "PLACED", fitted.get("errors"))
        self.assertEqual(fitted["report"]["body_spacing_requested"], 1)
        self.assertEqual(fitted["report"]["body_spacing_used"], 0)
        self.assertTrue(any("body spacing" in message
                            for message in fitted["warnings"]))
        self.assertEqual(project, original)

    def test_compact_mode_is_explicit_and_never_lies_about_spacing(self):
        project = board(2, 5, [capacitor("C1"), capacitor("C2")])
        fitted = quick_fit(project, body_spacing_holes=0)
        self.assertEqual(fitted["status"], "PLACED", fitted.get("errors"))
        self.assertEqual(fitted["report"]["body_spacing_requested"], 0)
        self.assertEqual(fitted["report"]["body_spacing_used"], 0)
        self.assertFalse(any("body spacing" in message
                             for message in fitted["warnings"]))

    def test_both_fixed_locks_remain_untouched_even_if_nominal_bodies_touch(self):
        project = board(2, 5, [
            capacitor("C1", row=0, col=0, locked=True),
            capacitor("C2", row=0, col=4, locked=True),
        ])
        fitted = quick_fit(project)
        self.assertEqual(fitted["status"], "PLACED", fitted.get("errors"))
        self.assertEqual(
            [p["boardPos"] for p in fitted["project"]["components"]],
            [p["boardPos"] for p in project["components"]],
        )
        self.assertGreater(fitted["report"]["nominal_contact_count"], 0)
        self.assertGreater(len(inspect_assumed_contacts(fitted["project"])), 0)

    def test_one_component_has_no_pair_to_compare_and_keeps_default(self):
        project = board(8, 18, [capacitor("C1")])
        fitted = quick_fit(project)
        self.assertEqual(fitted["status"], "PLACED", fitted.get("errors"))
        self.assertEqual(fitted["report"]["body_spacing_requested"], 1)
        self.assertEqual(fitted["report"]["body_spacing_used"], 1)
        self.assertEqual(fitted["report"]["nominal_contact_count"], 0)

    def test_invalid_spacing_is_reported(self):
        project = board(8, 18, [capacitor("C1")])
        for spacing in (-1, 3, 1.5, "1"):
            self.assertEqual(
                quick_fit(project, body_spacing_holes=spacing)["status"],
                "CONSTRAINT_CONFLICT",
            )


if __name__ == "__main__":
    unittest.main()
