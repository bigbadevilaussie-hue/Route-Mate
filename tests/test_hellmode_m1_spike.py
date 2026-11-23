"""M1 read-only characterisation — NOT a physical or electrical verifier.

The golden counts are frozen observations from MotoMix 1.44. A later fully
independent verifier must reproduce them without calling this spike code.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from tools.hellmode_m1_spike import inspect_spans


ROOT = Path(__file__).resolve().parent.parent
MOTOMIX = ROOT / "benchmarks/moto/motomix-autorouted.json"
MOTOMIX_GIT_BLOB = "0f0afe86bc3f4cfabc38f826d072d57eefbc49d8"
CLUSTER = {
    "RM-W002", "RM-W007", "RM-W010", "RM-W016",
    "RM-W025", "RM-W031", "RM-W032",
}


def wire(name, first, second):
    return {
        "id": name,
        "from": {"row": first[0], "col": first[1]},
        "to": {"row": second[0], "col": second[1]},
    }


def measure(*wires):
    return inspect_spans({"rows": 6, "cols": 5, "wires": list(wires)})


class M1DiagnosticSpikeTests(unittest.TestCase):
    def test_golden_motomix_144_projection_is_frozen(self):
        data = MOTOMIX.read_bytes()
        git_blob = hashlib.sha1(
            f"blob {len(data)}\\0".replace("\\0", "\0").encode() + data
        ).hexdigest()
        self.assertEqual(git_blob, MOTOMIX_GIT_BLOB,
                         "MOTOMIX fixture changed: regenerate expectations explicitly")
        project = json.loads(data)
        self.assertEqual((project["board"]["rows"], project["board"]["cols"]),
                         (24, 56))
        self.assertEqual(len(project["board"]["cuts"]), 57)
        result = inspect_spans(project["board"])
        self.assertEqual(result["wires"], 46)
        self.assertEqual(result["overlap_pairs"], 33)
        self.assertEqual(result["identical_pairs"], 0)
        self.assertEqual(result["contained_pairs"], 14)
        self.assertEqual(result["partial_pairs"], 19)
        self.assertEqual(result["stacked_gaps"], 51)
        self.assertEqual(result["excess_gap_occupancy"], 95)
        self.assertEqual(result["max_stack_depth"], 7)
        self.assertEqual(result["shared_endpoint_pairs"], 0)
        self.assertEqual(
            [(item["column"], item["gap_row"])
             for item in result["max_depth_gaps"]],
            [(2, 8), (2, 9), (2, 10), (2, 11)],
        )
        for item in result["max_depth_gaps"]:
            self.assertEqual(set(item["ids"]), CLUSTER)
        self.assertIn("does not determine net ownership", result["note"])

    def test_identical_spans_contribute_one_pair_and_four_excess_gaps(self):
        result = measure(wire("A", (0, 1), (4, 1)),
                         wire("B", (4, 1), (0, 1)))
        self.assertEqual(result["overlap_pairs"], 1)
        self.assertEqual(result["identical_pairs"], 1)
        self.assertEqual(result["excess_gap_occupancy"], 4)
        self.assertEqual(result["shared_endpoint_pairs"], 2)

    def test_contained_and_partial_spans_are_not_confused(self):
        contained = measure(wire("A", (0, 1), (5, 1)),
                            wire("B", (2, 1), (4, 1)))
        self.assertEqual(contained["contained_pairs"], 1)
        self.assertEqual(contained["excess_gap_occupancy"], 2)
        partial = measure(wire("A", (0, 1), (3, 1)),
                          wire("B", (2, 1), (5, 1)))
        self.assertEqual(partial["partial_pairs"], 1)
        self.assertEqual(partial["excess_gap_occupancy"], 1)

    def test_end_to_end_shared_endpoint_is_not_counted_as_shared_gap(self):
        result = measure(wire("A", (0, 1), (3, 1)),
                         wire("B", (3, 1), (5, 1)))
        self.assertEqual(result["overlap_pairs"], 0)
        self.assertEqual(result["excess_gap_occupancy"], 0)
        self.assertEqual(result["shared_endpoint_pairs"], 1)

    def test_different_columns_have_no_shared_gap(self):
        result = measure(wire("A", (0, 1), (5, 1)),
                         wire("B", (0, 2), (5, 2)))
        self.assertEqual(result["overlap_pairs"], 0)
        self.assertEqual(result["stacked_gaps"], 0)
        self.assertEqual(result["shared_endpoint_pairs"], 0)

    def test_rejects_diagonal_zero_length_and_outside_board(self):
        for segment in (((0, 0), (1, 1)),
                        ((2, 1), (2, 1)),
                        ((0, 1), (6, 1))):
            with self.subTest(segment=segment):
                with self.assertRaises(ValueError):
                    measure(wire("BAD", *segment))


if __name__ == "__main__":
    unittest.main()
