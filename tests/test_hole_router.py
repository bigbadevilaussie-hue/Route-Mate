"""Real routing regressions using Karl's AUDIO feasibility witness."""
from __future__ import annotations
import copy
import json
import unittest
from pathlib import Path

from solve.hole_router import route_holes
from solve.verify import verify_project
from solve.quick_rules import quick_audit
from solve.quality_audit import audit_project

ROOT = Path(__file__).resolve().parent.parent
WITNESS = ROOT / "benchmarks/audio/audio10wires38cuts.json"


class HoleRouterTests(unittest.TestCase):
    def witness(self):
        project = json.loads(WITNESS.read_text(encoding="utf-8"))
        project["board"]["cuts"] = []
        project["board"]["wires"] = []
        return project

    def test_audio_witness_routes_with_all_existing_oracles(self):
        original = self.witness()
        snapshot = copy.deepcopy(original)
        result = route_holes(original, iterations=12)
        self.assertEqual(result["status"], "ROUTED",
                         f"{result['status']}: {result.get('errors')} {result.get('hole_search')}")
        self.assertEqual(original, snapshot, "router must never mutate input")
        self.assertEqual(result["verification"]["status"], "PASS")
        self.assertEqual(verify_project(result["project"])["status"], "PASS")
        self.assertNotEqual(quick_audit(result["project"])["status"], "FAIL")
        self.assertEqual(audit_project(result["project"])["status"], "PASS")
        self.assertGreaterEqual(result["wires_added"], 1)
        self.assertGreaterEqual(result["cuts_added"], 1)

    def test_audio_witness_is_deterministic(self):
        placed = self.witness()
        a = route_holes(placed, iterations=12)
        b = route_holes(placed, iterations=12)
        self.assertEqual(a["status"], "ROUTED", a.get("errors"))
        self.assertEqual(b["status"], "ROUTED", b.get("errors"))
        self.assertEqual(a["project"]["board"], b["project"]["board"])

    def test_does_not_erase_manual_routing(self):
        placed = self.witness()
        placed["board"]["cuts"] = [{"row": 0, "col": 0, "kind": "between"}]
        snapshot = copy.deepcopy(placed)
        result = route_holes(placed)
        self.assertEqual(result["status"], "FIXED_ROUTING_UNSUPPORTED")
        self.assertEqual(result["project"], snapshot)
        self.assertEqual(placed, snapshot)

    def test_same_net_pin_can_host_jumper_landing(self):
        """Pin-bank escapes must not be excluded from vertical graph edges."""
        tiny = {
            "board": {"rows": 4, "cols": 5, "cuts": [], "wires": []},
            "componentDefs": [{
                "id": "one", "width": 1, "height": 1,
                "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
                "bodyCells": [],
            }],
            "components": [
                {"id": "A", "defId": "one", "boardPos": {"row": 0, "col": 0}},
                {"id": "B", "defId": "one", "boardPos": {"row": 2, "col": 0}},
                {"id": "C", "defId": "one", "boardPos": {"row": 0, "col": 1}},
                {"id": "D", "defId": "one", "boardPos": {"row": 2, "col": 1}},
            ],
            "netAssignments": [
                {"componentId": "A", "pinId": "1", "netId": "BUS"},
                {"componentId": "B", "pinId": "1", "netId": "BUS"},
                {"componentId": "C", "pinId": "1", "netId": "X"},
                {"componentId": "D", "pinId": "1", "netId": "Y"},
            ],
        }
        result = route_holes(tiny, iterations=4)
        self.assertEqual(result["status"], "ROUTED", result.get("errors"))
        self.assertEqual(verify_project(result["project"])["status"], "PASS")
        self.assertTrue(any(
            {tuple(w[p][k] for k in ("row", "col")) for p in ("from", "to")}
            == {(0, 0), (2, 0)}
            for w in result["project"]["board"]["wires"]
        ))


    def test_shared_hole_different_nets_is_invalid(self):
        placed = self.witness()
        first = placed["netAssignments"][0]
        second = next(x for x in placed["netAssignments"] if x["netId"] != first["netId"])
        # Artificial same-net terminal reference collision does not suffice;
        # a deterministic one-hole conflict is tested directly via a tiny model.
        tiny = {
            "board": {"rows": 3, "cols": 6, "cuts": [], "wires": []},
            "componentDefs": [{
                "id": "one", "width": 1, "height": 1,
                "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}], "bodyCells": [],
            }],
            "components": [
                {"id": "A", "defId": "one", "boardPos": {"row": 0, "col": 0}},
                {"id": "B", "defId": "one", "boardPos": {"row": 0, "col": 0}},
            ],
            "netAssignments": [
                {"componentId": "A", "pinId": "1", "netId": "N1"},
                {"componentId": "B", "pinId": "1", "netId": "N2"},
            ],
        }
        result = route_holes(tiny)
        self.assertEqual(result["status"], "INVALID_INPUT")
        self.assertIn("different nets share hole", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
