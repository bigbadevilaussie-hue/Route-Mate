"""Golden 2.5D clearance contract tests (millimetres, explicit geometry)."""
import json
import unittest
from pathlib import Path

from solve.clearance_25d import classify_jumper, outline_distance
from solve.clearance_25d_verify import verify_jumper_25d

FIXTURES = Path(__file__).parent / "fixtures" / "clearance_25d_golden.json"


class Clearance25DGoldenTests(unittest.TestCase):
    def test_golden_contract(self):
        cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 12)
        for case in cases:
            with self.subTest(case=case["id"]):
                original = json.dumps(case, sort_keys=True)
                actual = classify_jumper(case)
                self.assertEqual(actual["verdict"], case["expected"], actual)
                independent = verify_jumper_25d(case)
                self.assertEqual(independent["verdict"], case["expected"], independent)
                self.assertEqual(independent["findings"], actual["findings"])
                self.assertEqual(json.dumps(case, sort_keys=True), original)

    def test_unknown_standoff_not_reported_as_proven_collision(self):
        case = next(x for x in json.loads(FIXTURES.read_text())["cases"]
                    if x["id"] == "G07_unknown_standoff")
        result = classify_jumper(case)
        self.assertEqual(result["verdict"], "FAIL_UNVERIFIED")
        self.assertEqual(result["findings"][0]["reason"], "standoff_unknown")

    def test_clearance_boundary_is_inclusive(self):
        cases = {x["id"]: x for x in json.loads(FIXTURES.read_text())["cases"]}
        self.assertEqual(classify_jumper(cases["G08a_exact_clearance"])["verdict"], "PASS")
        self.assertEqual(classify_jumper(cases["G08b_inside_clearance"])["verdict"], "FAIL_PROVEN")

    def test_missing_dimensions_are_not_guessed(self):
        cases = json.loads(FIXTURES.read_text())["cases"]
        case = dict(cases[1])
        case["settings"] = dict(case["settings"])
        del case["settings"]["wire_od_mm"]
        with self.assertRaises(KeyError):
            classify_jumper(case)


if __name__ == "__main__":
    unittest.main()
