"""Nominal component body envelopes are pad-access keepouts, not certified dimensions."""
import copy
import unittest

from solve.quick_fit import _allocate_offboard_pads
from geometry_sidecar import (
    assumed_body_pad_keepouts, assumed_pad_body_intersection,
)
from board_geometry import BUILTIN_DEFS


def project(locked=False):
    connector = {
        "id": "J", "label": "External pad", "defId": "def-connector-1",
        "offBoard": True, "leads": {"1": {"row": 4, "col": 5}} if locked else {},
        "locked": locked,
    }
    return {
        "board": {"rows": 12, "cols": 12},
        "components": [
            {
                "id": "C", "label": "C1", "defId": "def-cap-polarized",
                "boardPos": {"row": 4, "col": 4},
                "rotation": 0, "value": "1000uF",
            },
            connector,
        ],
        "componentDefs": [], "netAssignments": [],
    }


class NominalPadAccessTests(unittest.TestCase):
    def test_allocated_external_pad_not_hidden_under_capacitor_body(self):
        source = project()
        original = copy.deepcopy(source)
        pin_nets = {("C", "1"): "N", ("J", "1"): "N"}
        assigned = _allocate_offboard_pads(
            source, BUILTIN_DEFS, pin_nets, 12, 12,
        )
        self.assertEqual(assigned, 1)
        pad = source["components"][1]["leads"]["1"]
        solids = assumed_body_pad_keepouts(source)
        self.assertEqual(len(solids), 1)
        self.assertEqual(solids[0]["shape"], "circle")
        self.assertEqual(solids[0]["label"], "C1")
        self.assertIsNone(assumed_pad_body_intersection(
            pad["row"], pad["col"], solids,
        ), pad)
        self.assertNotEqual(source["components"][1]["leads"],
                            original["components"][1]["leads"])

    def test_fixed_external_pad_under_nominal_body_is_rejected(self):
        source = project(locked=True)
        with self.assertRaisesRegex(ValueError, "assumed body clearance of C1"):
            _allocate_offboard_pads(
                source, BUILTIN_DEFS,
                {("C", "1"): "N", ("J", "1"): "N"}, 12, 12,
            )


if __name__ == "__main__":
    unittest.main()
