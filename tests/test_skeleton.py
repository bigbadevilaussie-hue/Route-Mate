"""Contract tests for the initial upstream-inspired skeleton decoder."""
import unittest

from solve.skeleton import Placement, Tile, decode_sequence_pair


class SkeletonTests(unittest.TestCase):
    def setUp(self):
        self.tiles = [Tile("A", 2, 3), Tile("B", 2, 2)]

    def decode(self, positive, negative, **kwargs):
        return decode_sequence_pair(
            self.tiles, positive, negative,
            board_rows=6, board_cols=8, **kwargs
        )

    def test_horizontal_order(self):
        self.assertEqual(self.decode(["A", "B"], ["A", "B"]),
                         {"A": Placement(0, 0), "B": Placement(0, 3)})

    def test_vertical_order(self):
        self.assertEqual(self.decode(["A", "B"], ["B", "A"]),
                         {"A": Placement(0, 0), "B": Placement(2, 0)})

    def test_clearance(self):
        self.assertEqual(self.decode(["A", "B"], ["A", "B"], clearance=1)["B"].col, 4)

    def test_hard_lock(self):
        result = self.decode(["A", "B"], ["A", "B"], fixed={"A": Placement(1, 2)})
        self.assertEqual(result["A"], Placement(1, 2))
        self.assertEqual(result["B"], Placement(0, 5))

    def test_conflicting_lock_rejected(self):
        self.assertIsNone(self.decode(
            ["A", "B"], ["A", "B"],
            fixed={"A": Placement(0, 4), "B": Placement(0, 1)}
        ))

    def test_board_bounds_rejected(self):
        self.assertIsNone(decode_sequence_pair(
            self.tiles, ["A", "B"], ["A", "B"], board_rows=6, board_cols=4
        ))

    def test_invalid_permutation(self):
        with self.assertRaises(ValueError):
            self.decode(["A", "A"], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
