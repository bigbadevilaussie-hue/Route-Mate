"""Tests for shared stripboard electrical-adjacency checks."""
import copy
import unittest
from adjacency import adjacency_conflicts, candidate_conflicts, hole_index

def old_helper(pins):
    by_row = {}
    for row, col, net in pins:
        by_row.setdefault(row, {})[col] = net
    return [(row, col) for row, cols in by_row.items()
            for col, net in cols.items()
            if col + 1 in cols and cols[col + 1] != net]

class AdjacencyTests(unittest.TestCase):
    def test_old_helper_loses_a_pin_when_two_share_a_hole(self):
        self.assertEqual(old_helper([(0, 3, "A"), (0, 3, "B")]), [])
        self.assertEqual(len(adjacency_conflicts([(0, 3, "A", "X.1"),
                                                  (0, 3, "B", "Y.1")])), 1)

    def test_same_hole_different_nets(self):
        (conflict,) = adjacency_conflicts([(2, 5, "A", "X.1"),
                                           (2, 5, "B", "Y.1")])
        self.assertEqual((conflict["kind"], conflict["row"], conflict["cols"]),
                         ("same_hole", 2, (5, 5)))

    def test_same_hole_same_net_is_not_a_conflict(self):
        self.assertEqual(adjacency_conflicts([(2, 5, "A", "X.1"),
                                              (2, 5, "A", "Y.1")]), [])

    def test_horizontal_three_pin_part_with_three_nets(self):
        pins = [(4, 10, "B", "Q1.1"), (4, 11, "C", "Q1.2"),
                (4, 12, "E", "Q1.3")]
        self.assertEqual([c["cols"] for c in adjacency_conflicts(pins)],
                         [(10, 11), (11, 12)])

    def test_vertical_three_pin_part_is_clean(self):
        pins = [(4, 10, "B", "Q1.1"), (5, 10, "C", "Q1.2"),
                (6, 10, "E", "Q1.3")]
        self.assertEqual(adjacency_conflicts(pins), [])

    def test_one_free_hole_between_is_allowed(self):
        self.assertEqual(adjacency_conflicts([(1, 3, "A", "X.1"),
                                              (1, 5, "B", "Y.1")]), [])

    def test_same_net_neighbours_are_allowed(self):
        self.assertEqual(adjacency_conflicts([(1, 3, "A", "X.1"),
                                              (1, 4, "A", "Y.1")]), [])

    def test_unassigned_pins_are_ignored(self):
        self.assertEqual(adjacency_conflicts([(1, 3, "A", "X.1"),
                                              (1, 4, None, "Y.1")]), [])

    def test_candidate_against_placed_component(self):
        placed = hole_index([(7, 20, "GND", "R1.2")])
        self.assertEqual([c["kind"] for c in candidate_conflicts(
            [(7, 21, "VCC", "Q1.1")], placed)], ["adjacent"])
        self.assertEqual(candidate_conflicts([(7, 21, "GND", "Q1.1")], placed), [])
        self.assertEqual(candidate_conflicts([(7, 22, "VCC", "Q1.1")], placed), [])

    def test_candidate_pins_against_each_other_and_placed_is_unchanged(self):
        placed = hole_index([(0, 0, "A", "R.1")])
        before = copy.deepcopy(dict(placed))
        out = candidate_conflicts([(3, 3, "B", "Q.1"),
                                   (3, 4, "C", "Q.2")], placed)
        self.assertEqual(len(out), 1)
        self.assertEqual(dict(placed), before)

    def test_candidate_and_full_check_agree(self):
        placed_pins = [(1, 1, "A", "R.1"), (1, 9, "B", "R.2")]
        candidate = [(1, 2, "C", "Q.1"), (1, 8, "B", "Q.2"),
                     (1, 10, "D", "Q.3")]
        full = {(c["kind"], c["row"], c["cols"])
                for c in adjacency_conflicts(placed_pins + candidate)}
        incremental = {(c["kind"], c["row"], c["cols"])
                       for c in candidate_conflicts(candidate, hole_index(placed_pins))}
        self.assertEqual(full, incremental)

if __name__ == "__main__":
    unittest.main()
