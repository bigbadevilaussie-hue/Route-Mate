"""Assumption provenance is not a measured or user-declared 2.5D PASS."""
import copy
import unittest

from solve.clearance_25d import classify_jumper
from solve.clearance_25d_verify import verify_jumper_25d


class AssumedStandardProvenanceTests(unittest.TestCase):
    def case(self, bottom):
        return {
            "jumper": {"from_mm": [0, 0], "to_mm": [0, 10]},
            "settings": {
                "wire_od_mm": 0.9, "min_clearance_mm": 0.3,
                "z_margin_mm": 0.3, "lead_margin_mm": 0.2,
            },
            "body_solids": [{
                "id": "CAP", "shape": "circle", "center_mm": [0, 5],
                "radius_mm": 2.5,
                "z_min_source": "assumed_standard",
                "z_min_mm": bottom, "z_max_mm": bottom + 8,
            }],
            "leads": [],
        }

    def check_both(self, case, expected, reason):
        first = classify_jumper(case)
        second = verify_jumper_25d(case)
        self.assertEqual(first["verdict"], expected)
        self.assertEqual(second["verdict"], expected)
        self.assertEqual(first["findings"], second["findings"])
        self.assertEqual(first["findings"][0]["reason"], reason)

    def test_assumed_under_body_pass_is_conditional(self):
        self.check_both(self.case(1.5), "CONDITIONAL", "assumed_standoff")

    def test_assumed_overlap_is_not_proven_collision(self):
        self.check_both(self.case(0.5), "FAIL_UNVERIFIED", "assumed_body_conflict")

    def test_measured_same_geometry_remains_proven(self):
        case = self.case(0.5)
        case["body_solids"][0]["z_min_source"] = "measured"
        self.check_both(case, "FAIL_PROVEN", "body_clearance")

    def test_no_mutation(self):
        case = self.case(1.5)
        before = copy.deepcopy(case)
        self.check_both(case, "CONDITIONAL", "assumed_standoff")
        self.assertEqual(case, before)


if __name__ == "__main__":
    unittest.main()
