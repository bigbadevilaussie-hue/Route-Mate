"""Focused tests for the read-only copper-island graph."""
import unittest
from unittest.mock import patch

from solve.island_graph import find_vertical_chain, route_with_island_graph


class IslandGraphTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "board": {"rows": 3, "cols": 3, "cuts": [
                {"row": 0, "col": 0, "kind": "between"},
                {"row": 2, "col": 1, "kind": "between"},
            ], "wires": []},
            "components": [], "netAssignments": [],
        }
        self.records = [(0, 0, "signal", "A"), (2, 2, "signal", "B")]

    @patch("solve.island_graph._terminals")
    def test_finds_two_jumper_bridge_without_mutation(self, terminals):
        terminals.return_value = self.records
        before = repr(self.project)
        result = find_vertical_chain(self.project, "signal")
        self.assertEqual(result["status"], "CHAIN_FOUND")
        self.assertEqual(len(result["chain"]), 2)
        self.assertEqual(repr(self.project), before)
        self.assertTrue(all(
            wire["from"]["col"] == wire["to"]["col"]
            for wire in result["chain"]
        ))

    @patch("solve.island_graph._terminals")
    def test_budget_prevents_two_hop_chain(self, terminals):
        terminals.return_value = self.records
        result = find_vertical_chain(self.project, "signal", max_edges=1)
        self.assertEqual(result["status"], "NO_CHAIN_WITHIN_BUDGET")

    @patch("solve.island_graph._terminals")
    def test_rejects_other_net_terminal_island(self, terminals):
        terminals.return_value = self.records + [(1, 1, "other", "C")]
        result = find_vertical_chain(self.project, "signal")
        self.assertEqual(result["status"], "CHAIN_FOUND")
        self.assertTrue(all(
            not (wire["from"] == {"row": 1, "col": 1}
                 or wire["to"] == {"row": 1, "col": 1})
            for wire in result["chain"]
        ))

    @patch("solve.island_graph.verify_project")
    @patch("solve.island_graph._terminals")
    def test_graph_router_commits_verified_multi_hop_chain(self, terminals, verifier):
        terminals.return_value = self.records
        verifier.return_value = {"status": "PASS"}
        before = repr(self.project)
        result = route_with_island_graph(self.project)
        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["wires_added"], 2)
        self.assertEqual(repr(self.project), before)

    @patch("solve.island_graph.verify_project")
    @patch("solve.island_graph._terminals")
    def test_graph_router_rejects_failed_verification(self, terminals, verifier):
        terminals.return_value = self.records
        verifier.return_value = {"status": "FAIL", "errors": ["short"]}
        before = repr(self.project)
        result = route_with_island_graph(self.project)
        self.assertEqual(result["status"], "GRAPH_FAILED")
        self.assertEqual(repr(self.project), before)


if __name__ == "__main__":
    unittest.main()
