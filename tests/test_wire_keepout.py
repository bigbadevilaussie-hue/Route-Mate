"""Regression tests for component-artwork wire crossings missed by bodyCells."""
from __future__ import annotations

import copy
import unittest

from solve.wire_keepout import vertical_gap_keepouts, wire_keepout_errors
from solve.quick_rules import quick_audit


def part(label, definition, row, col):
    return {"id": label, "label": label, "defId": definition,
            "boardPos": {"row": row, "col": col}, "rotation": 0}


def tiny(*components, wire_from, wire_to):
    return {
        "board": {
            "rows": 12, "cols": 25, "cuts": [],
            "wires": [{"id": "W-TEST", "from": wire_from, "to": wire_to}],
        },
        "componentDefs": [],
        "components": list(components),
        "netAssignments": [],
    }


class WireKeepoutTests(unittest.TestCase):
    def test_electrolytic_capacitor_can_is_not_empty_geometry(self):
        # Reproduces MOTO C1: a drawn ~2-hole-radius can, but builtin
        # def-cap-polarized had ZERO bodyCells and allowed W005 through it.
        project = tiny(part("C1", "def-cap-polarized", 2, 12),
                       wire_from={"row": 2, "col": 12},
                       wire_to={"row": 5, "col": 12})
        self.assertIn((2, 12), vertical_gap_keepouts(project, 12, 25))
        self.assertTrue(any("C1" in error for error in wire_keepout_errors(project)))
        self.assertEqual(quick_audit(project)["status"], "FAIL")

    def test_nearby_wire_at_clear_column_is_accepted(self):
        project = tiny(part("C1", "def-cap-polarized", 2, 12),
                       wire_from={"row": 2, "col": 15},
                       wire_to={"row": 5, "col": 15})
        self.assertEqual(wire_keepout_errors(project), [])
        self.assertNotEqual(quick_audit(project)["status"], "FAIL")

    def test_transistor_with_no_body_cells_still_blocks_wire(self):
        project = tiny(part("Q1", "def-npn", 5, 12),
                       wire_from={"row": 4, "col": 12},
                       wire_to={"row": 9, "col": 12})
        self.assertTrue(any("Q1" in error for error in wire_keepout_errors(project)))
        self.assertEqual(quick_audit(project)["status"], "FAIL")

    def test_diodes_and_resistors_remain_blocked(self):
        for definition in ("def-resistor", "def-diode", "def-zener"):
            with self.subTest(definition=definition):
                project = tiny(part("D1", definition, 2, 10),
                               wire_from={"row": 1, "col": 10},
                               wire_to={"row": 9, "col": 10})
                self.assertTrue(wire_keepout_errors(project))

    def test_intermediate_pin_hole_blocks_jumper(self):
        project = tiny(part("J1", "def-connector-2", 5, 12),
                       wire_from={"row": 3, "col": 12},
                       wire_to={"row": 8, "col": 12})
        self.assertTrue(any("intermediate component pin" in e
                            for e in wire_keepout_errors(project)))
        self.assertEqual(quick_audit(project)["status"], "FAIL")

    def test_all_physical_pads_are_known_to_router(self):
        """Even an unassigned connector pin must not become a wire passage."""
        from solve.hole_router import _static
        project = tiny(part("J1", "def-connector-2", 5, 12),
                       wire_from={"row": 2, "col": 12},
                       wire_to={"row": 8, "col": 12})
        rows, cols, bodies, pin_net, nets, vreach = _static(project)
        self.assertEqual(pin_net[5 * cols + 12], "__UNASSIGNED_PAD__")
        self.assertTrue(any("intermediate component pin" in e
                            for e in wire_keepout_errors(project)))

    def test_routing_never_modifies_source(self):
        project = tiny(part("C1", "def-cap-polarized", 2, 12),
                       wire_from={"row": 2, "col": 12},
                       wire_to={"row": 5, "col": 12})
        snapshot = copy.deepcopy(project)
        wire_keepout_errors(project)
        self.assertEqual(project, snapshot)


if __name__ == "__main__":
    unittest.main()
