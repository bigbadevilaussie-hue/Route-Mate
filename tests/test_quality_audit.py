"""Tests for the routed solve measurement audit."""
import unittest

from solve.quality_audit import audit_project


def sample_project():
    return {
        "name": "sample",
        "board": {
            "rows": 8,
            "cols": 10,
            "cuts": [{"row": 1, "col": 2}, {"row": 3, "col": 4}],
            "wires": [
                {"id": "V1", "from": {"row": 0, "col": 1},
                 "to": {"row": 3, "col": 1}},
                {"id": "D1", "from": {"row": 1, "col": 1},
                 "to": {"row": 4, "col": 5}},
            ],
        },
    }


class QualityAuditTests(unittest.TestCase):
    def test_counts_match_expected(self):
        report = audit_project(sample_project(), expected_cuts=2, expected_wires=2)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["counts"]["cuts"]["matches"])
        self.assertTrue(report["counts"]["wires"]["matches"])

    def test_count_mismatch_fails(self):
        report = audit_project(sample_project(), expected_cuts=3, expected_wires=2)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["counts"]["cuts"]["difference"], -1)

    def test_diagonal_is_reported(self):
        report = audit_project(sample_project())
        self.assertEqual(report["jumper_audit"]["diagonal_count"], 1)
        self.assertEqual(report["jumper_audit"]["diagonals"][0]["id"], "D1")

    def test_lengths_use_euclidean_hole_pitch(self):
        report = audit_project(sample_project())
        lengths = {item["id"]: item["length_hole_pitches"]
                   for item in report["jumper_audit"]["lengths"]}
        self.assertEqual(lengths["V1"], 3.0)
        self.assertEqual(lengths["D1"], 5.0)
        self.assertEqual(report["jumper_audit"]["total_length_hole_pitches"], 8.0)

    def test_out_of_board_endpoint_is_reported(self):
        data = sample_project()
        data["board"]["wires"][0]["to"] = {"row": 99, "col": 1}
        report = audit_project(data)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["jumper_audit"]["invalid_records"], 1)

    def test_malformed_cut_collection_is_rejected(self):
        data = sample_project()
        data["board"]["cuts"] = {}
        with self.assertRaisesRegex(ValueError, "board.cuts must be a list"):
            audit_project(data)


if __name__ == "__main__":
    unittest.main()
