"""Regression checks for provisional render scoring."""
import unittest

from solve.render_quality import score_render


class RenderQualityTests(unittest.TestCase):
    def test_empty_board_is_scored_and_provisional(self):
        project = {"board": {"rows": 4, "cols": 5, "cuts": [], "wires": []},
                   "components": []}
        result = score_render(project)
        self.assertEqual(result["score"], 100.0)
        self.assertEqual(result["classification"], "PROVISIONAL")
        self.assertFalse(result["routed"])

    def test_unplaced_component_reduces_score(self):
        project = {"board": {"rows": 4, "cols": 5}, "components": [{"id": "R1"}]}
        self.assertEqual(score_render(project)["score"], 85.0)

    def test_diagonal_wire_is_penalised(self):
        project = {"board": {"rows": 4, "cols": 5, "wires": [
            {"id": "W1", "from": {"row": 0, "col": 0},
             "to": {"row": 1, "col": 1}}]}, "components": []}
        result = score_render(project)
        self.assertEqual(result["diagonals"], 1)
        self.assertLess(result["score"], 90)


if __name__ == "__main__":
    unittest.main()
