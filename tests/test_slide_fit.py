"""External slide-lock retry tests."""
import copy
import unittest

from solve.slide_fit import slide_fit


def project(rows=3, cols=5, start=(0, 2), blocker=(0, 2)):
    parts = [
        {"id": "slide", "defId": "pin", "boardPos": {"row": start[0], "col": start[1]},
         "locked": True, "slide": True},
        {"id": "block", "defId": "pin", "boardPos": {"row": blocker[0], "col": blocker[1]},
         "locked": True},
    ]
    return {
        "board": {"rows": rows, "cols": cols, "cuts": [], "wires": []},
        "components": parts,
        "componentDefs": [{"id": "pin", "width": 1, "height": 1,
                           "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
                           "bodyCells": []}],
        "netAssignments": [],
    }


class SlideFitTests(unittest.TestCase):
    def test_top_edge_moves_left_after_full_lock_collision(self):
        source = project()
        original = copy.deepcopy(source)
        result = slide_fit(source, "slide", "top", clearance=0)
        self.assertEqual(result["status"], "PLACED", result["errors"])
        self.assertEqual(result["positions_tried"], [2, 1])
        self.assertEqual(result["project"]["components"][0]["boardPos"],
                         {"row": 0, "col": 1})
        self.assertEqual(source, original)

    def test_left_edge_moves_up_without_changing_column(self):
        source = project(start=(2, 0), blocker=(2, 0))
        result = slide_fit(source, "slide", "left", clearance=0)
        self.assertEqual(result["status"], "PLACED", result["errors"])
        self.assertEqual(result["positions_tried"], [2, 1])
        self.assertEqual(result["project"]["components"][0]["boardPos"],
                         {"row": 1, "col": 0})

    def test_exhausts_positions_without_mutating_source(self):
        source = project(rows=1, cols=1, start=(0, 0), blocker=(0, 0))
        original = copy.deepcopy(source)
        result = slide_fit(source, "slide", "top", clearance=0)
        self.assertEqual(result["status"], "NO_FIT_FOUND")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["positions_tried"], [0])
        self.assertEqual(source, original)

    def test_rejects_missing_slide_flag(self):
        source = project()
        source["components"][0]["slide"] = False
        with self.assertRaises(ValueError):
            slide_fit(source, "slide", "top")
