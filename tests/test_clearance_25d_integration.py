"""Explicit 2.5D policy integration: router gaps and independent audits.

Legacy projects retain their previous behaviour. No dimensions are inferred.
"""
import copy
import unittest

from solve.wire_keepout import vertical_gap_keepouts, wire_keepout_errors
from solve.quick_rules import quick_audit
from solve.quality_audit import audit_project


def sample():
    col = 13
    return {
        "board": {"rows": 10, "cols": 20, "cuts": [], "wires": [{
            "id": "W", "from": {"row": 0, "col": col},
            "to": {"row": 6, "col": col}
        }]},
        "components": [{
            "id": "C1", "label": "C1", "defId": "def-cap-polarized",
            "boardPos": {"row": 2, "col": 12}, "rotation": 0,
        }],
        "componentDefs": [],
        "netAssignments": [],
        "physicalClearance": {
            "complete": True,
            "settings": {
                "wire_od_mm": 1.0,
                "min_clearance_mm": 0.3,
                "z_margin_mm": 0.3,
                "lead_margin_mm": 0.3,
            },
            "body_solids": [{
                "id": "C1",
                "shape": "circle",
                "center_mm": [col * 2.54, 3 * 2.54],
                "radius_mm": 2.0,
                "z_min_mm": 2.5,
                "z_max_mm": 10,
                "z_min_source": "measured",
            }],
            "leads": [],
        },
    }


class ExplicitClearanceTests(unittest.TestCase):
    def test_measured_under_body_passes_without_artwork_veto(self):
        project = sample()
        self.assertEqual(wire_keepout_errors(project), [])
        self.assertNotIn((2, 13), vertical_gap_keepouts(project, 10, 20))
        self.assertNotEqual(quick_audit(project)["status"], "FAIL")
        self.assertEqual(audit_project(project)["status"], "PASS")

    def test_unknown_standoff_is_rejected_but_not_called_collision(self):
        project = sample()
        solid = project["physicalClearance"]["body_solids"][0]
        solid.update(z_min_mm=0, z_min_source="default_flush")
        errors = wire_keepout_errors(project)
        self.assertTrue(any("FAIL_UNVERIFIED: standoff_unknown" in x for x in errors))
        self.assertIn((2, 13), vertical_gap_keepouts(project, 10, 20))
        self.assertEqual(quick_audit(project)["status"], "FAIL")
        self.assertEqual(audit_project(project)["status"], "FAIL")

    def test_router_graph_admits_measured_gap_but_blocks_unknown(self):
        from solve.hole_router import _static
        project = sample()
        _, cols, _, _, _, reachable = _static(project)
        self.assertIn((3 * cols + 13, 1), reachable[2 * cols + 13])
        project["physicalClearance"]["body_solids"][0].update(
            z_min_mm=0, z_min_source="default_flush"
        )
        _, cols, _, _, _, reachable = _static(project)
        self.assertNotIn((3 * cols + 13, 1), reachable[2 * cols + 13])

    def test_declaration_is_required_before_disabling_legacy_checks(self):
        project = sample()
        del project["physicalClearance"]["complete"]
        with self.assertRaisesRegex(ValueError, "complete=true"):
            wire_keepout_errors(project)

    def test_legacy_mode_remains_conservative(self):
        project = sample()
        del project["physicalClearance"]
        self.assertTrue(any("C1" in x for x in wire_keepout_errors(project)))
        self.assertIn((2, 13), vertical_gap_keepouts(project, 10, 20))

    def test_no_mutation(self):
        project = sample()
        before = copy.deepcopy(project)
        wire_keepout_errors(project)
        self.assertEqual(project, before)


if __name__ == "__main__":
    unittest.main()
