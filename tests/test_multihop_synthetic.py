"""Regression coverage for bounded vertical multi-island routing."""
import unittest

from solve.route import route_copper
from solve.verify import verify_project


CHAIN_ONLY = [(0, 2), (1, 1), (1, 4), (2, 3), (2, 7), (3, 4), (4, 6)]
BANDED = [(row, col) for row in range(5) for col in (2, 6)]


def project(cuts, extra_components=(), extra_assign=()):
    return {
        "board": {
            "rows": 5, "cols": 10, "wires": [],
            "cuts": [
                {"row": row, "col": col, "kind": "between"}
                for row, col in cuts
            ],
        },
        "componentDefs": [],
        "components": [
            {"id": "T1", "label": "T1", "defId": "def-connector-1",
             "boardPos": {"row": 0, "col": 0}, "rotation": 0},
            {"id": "T2", "label": "T2", "defId": "def-connector-1",
             "boardPos": {"row": 4, "col": 9}, "rotation": 0},
            *extra_components,
        ],
        "netAssignments": [
            {"componentId": "T1", "pinId": "1", "netId": "N"},
            {"componentId": "T2", "pinId": "1", "netId": "N"},
            *extra_assign,
        ],
    }


class MultiHop(unittest.TestCase):
    def test_three_jumper_chain_is_routed(self):
        result = route_copper(project(CHAIN_ONLY), vertical_only=True)
        self.assertEqual(result["status"], "ROUTED", result["errors"])
        self.assertEqual(result["wires_added"], 3)
        self.assertEqual(verify_project(result["project"])["status"], "PASS")
        for wire in result["project"]["board"]["wires"]:
            self.assertEqual(wire["from"]["col"], wire["to"]["col"])

    def test_diagnostic_and_router_agree(self):
        result = route_copper(project(CHAIN_ONLY), vertical_only=True)
        self.assertFalse(
            result["status"] == "ROUTING_FAILED"
            and result.get("reachability", {}).get("status") == "CHAIN_FOUND"
        )

    def test_one_bridge_still_routes(self):
        cuts = [cut for cut in CHAIN_ONLY if cut != (3, 4)]
        result = route_copper(project(cuts), vertical_only=True)
        self.assertEqual(
            (result["status"], result["wires_added"]), ("ROUTED", 2)
        )

    def test_no_chain_stays_failed(self):
        result = route_copper(project(BANDED), vertical_only=True)
        self.assertEqual(result["status"], "ROUTING_FAILED")
        self.assertEqual(result["reachability"]["status"], "NO_CHAIN_FOUND")

    def test_shared_intermediate_island_is_a_short(self):
        p = project(
            CHAIN_ONLY,
            [{"id": "M1", "label": "M1", "defId": "def-connector-1",
              "boardPos": {"row": 3, "col": 0}, "rotation": 0}],
            [{"componentId": "M1", "pinId": "1", "netId": "M"}],
        )
        p["board"]["wires"] = [
            {"id": "a", "from": {"row": 0, "col": 2}, "to": {"row": 1, "col": 2}},
            {"id": "b", "from": {"row": 1, "col": 3}, "to": {"row": 0, "col": 3}},
            {"id": "c", "from": {"row": 0, "col": 7}, "to": {"row": 4, "col": 7}},
            {"id": "d", "from": {"row": 3, "col": 2}, "to": {"row": 1, "col": 2}},
        ]
        verification = verify_project(p)
        self.assertEqual(verification["status"], "FAIL")
        self.assertGreaterEqual(verification["counts"]["short_groups"], 1)


if __name__ == "__main__":
    unittest.main()
