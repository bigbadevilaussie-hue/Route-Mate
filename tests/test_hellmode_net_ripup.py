"""Whole-net rerouting: 2D collision repair while protecting circuit nets.

The test contract is ELECTRICAL_ONLY, never a physical build-ready record.
"""
from __future__ import annotations

import ast
import copy
import json
import unittest
from pathlib import Path

from hellmode.net_ripup import rebuild_one_net, ripup_repair, _is_clear
from hellmode.demo import _electrically_valid, optimize
from hellmode.copper_model import reconstruct_electrical
from hellmode.strict_occupancy import audit_strict_occupancy


ROOT = Path(__file__).resolve().parent.parent


def compact_fixture():
    # Three terminal-bearing copper runs, two overlapped same-net bridges.
    # A whole-net rebuild can span rows 0/2/4 without shared vertical gaps.
    return {
        "board": {
            "rows": 5, "cols": 8, "cuts": [],
            "wires": [
                {"id": "N-W1", "from": {"row": 0, "col": 1},
                 "to": {"row": 4, "col": 1}},
                {"id": "N-W2", "from": {"row": 0, "col": 1},
                 "to": {"row": 2, "col": 1}},
            ],
        },
        "componentDefs": [
            {"id": "pad", "pins": [
                {"id": "1", "offsetRow": 0, "offsetCol": 0}],
             "bodyCells": []},
        ],
        "components": [
            {"id": "P0", "defId": "pad", "boardPos": {"row": 0, "col": 0}},
            {"id": "P2", "defId": "pad", "boardPos": {"row": 2, "col": 0}},
            {"id": "P4", "defId": "pad", "boardPos": {"row": 4, "col": 0}},
        ],
        "netAssignments": [
            {"componentId": "P0", "pinId": "1", "netId": "N"},
            {"componentId": "P2", "pinId": "1", "netId": "N"},
            {"componentId": "P4", "pinId": "1", "netId": "N"},
        ],
    }


class WholeNetRipupTests(unittest.TestCase):
    def test_reroute_all_essential_islands_while_removing_stacks(self):
        project = compact_fixture()
        original = copy.deepcopy(project)
        self.assertTrue(_electrically_valid(project))
        before = reconstruct_electrical(project)
        self.assertEqual(before["wire_nets"], {"N-W1": "N", "N-W2": "N"})
        self.assertGreater(
            audit_strict_occupancy(project["board"])["counts"]["excess_gap_occupancy"], 0
        )
        result = rebuild_one_net(
            project, "N", pads=before["pin_holes"],
            wire_nets=before["wire_nets"], seed=17,
        )
        self.assertIsNotNone(result)
        self.assertTrue(_electrically_valid(result))
        independent = reconstruct_electrical(result)
        geometry = audit_strict_occupancy(
            result["board"],
            pin_holes=independent["pin_holes"],
            trusted_wire_nets=independent["wire_nets"],
        )
        for key in (
            "excess_gap_occupancy", "shared_landing_holes",
            "endpoint_on_span_holes", "intermediate_pad_holes",
            "landing_net_conflicts", "landing_net_unverified",
        ):
            self.assertEqual(geometry["counts"][key], 0, (key, geometry["findings"]))
        self.assertEqual(project, original)

    def test_full_net_ripup_search_accepts_verifiable_improvement(self):
        source = compact_fixture()
        before = reconstruct_electrical(source)
        candidate, result = ripup_repair(
            source, pads=before["pin_holes"],
            wire_nets=before["wire_nets"],
            electrical_check=_electrically_valid,
            attempts=12, seed=8,
        )
        self.assertTrue(_electrically_valid(candidate))
        self.assertGreater(result["whole_net_reroutes_accepted"], 0)
        self.assertEqual(result["remaining_excess"], 0)
        self.assertFalse(result["physical_pass"])
        self.assertFalse(result["record_eligible"])

    def test_foreign_net_pads_and_copper_are_never_joined(self):
        source = compact_fixture()
        source["components"].append({
            "id": "M", "defId": "pad", "boardPos": {"row": 1, "col": 3}
        })
        source["netAssignments"].append({
            "componentId": "M", "pinId": "1", "netId": "M"
        })
        self.assertTrue(_electrically_valid(source))
        graph = reconstruct_electrical(source)
        result = rebuild_one_net(
            source, "N", pads=graph["pin_holes"],
            wire_nets=graph["wire_nets"], seed=1
        )
        self.assertIsNotNone(result)
        proof = reconstruct_electrical(result)
        self.assertEqual(proof["status"], "PASS", proof["errors"])
        self.assertEqual(proof["counts"]["short_groups"], 0)

    def test_temporary_gap_overlap_is_search_only_not_new_landing_permission(self):
        gap = {(1, 0), (1, 1)}
        self.assertFalse(_is_clear(
            0, 3, 1, "N", gap, set(), set(), {}
        ))
        self.assertTrue(_is_clear(
            0, 3, 1, "N", gap, set(), set(), {},
            allow_stack_penalty=True,
        ))
        # Even in exploration, a shared endpoint and an occupied
        # intermediate pad stay forbidden.
        self.assertFalse(_is_clear(
            0, 3, 1, "N", gap, {(1, 3)}, set(), {},
            allow_stack_penalty=True,
        ))
        self.assertFalse(_is_clear(
            0, 3, 1, "N", gap, set(), set(),
            {(1, 2): ["N"]}, allow_stack_penalty=True,
        ))

    def test_missing_wire_net_and_unknown_net_never_silently_rewrite(self):
        source = compact_fixture()
        graph = reconstruct_electrical(source)
        for name in ("NO_SUCH_NET", "N"):
            with self.subTest(name=name):
                result = rebuild_one_net(
                    source, name, pads=graph["pin_holes"],
                    wire_nets={}, seed=1
                )
                self.assertIsNone(result)

    def test_original_motomix_footprint_cuts_and_parts_stay_immutable(self):
        source = json.loads(
            (ROOT / "benchmarks/moto/motomix-autorouted.json").read_text()
        )
        original = copy.deepcopy(source)
        graph = reconstruct_electrical(source)
        congested = "N"
        # Pick the owner with the largest summed stacked-span depth.
        from collections import Counter
        gap = Counter()
        for w in source["board"]["wires"]:
            col = w["from"]["col"]
            for row in range(w["from"]["row"], w["to"]["row"]):
                gap[(col, row)] += 1
        contribution = Counter()
        for w in source["board"]["wires"]:
            col = w["from"]["col"]
            contribution[graph["wire_nets"][w["id"]]] += sum(
                max(0, gap[(col, row)] - 1)
                for row in range(w["from"]["row"], w["to"]["row"])
            )
        congested = contribution.most_common(1)[0][0]
        proposal = rebuild_one_net(
            source, congested, pads=graph["pin_holes"],
            wire_nets=graph["wire_nets"], seed=24
        )
        if proposal is not None:
            self.assertEqual(proposal["board"]["rows"], source["board"]["rows"])
            self.assertEqual(proposal["board"]["cols"], source["board"]["cols"])
            self.assertEqual(proposal["board"]["cuts"], source["board"]["cuts"])
            self.assertEqual(proposal["components"], source["components"])
            self.assertTrue(_electrically_valid(proposal))
        self.assertEqual(source, original)

    def test_alpha_reports_whole_net_attempt_without_physical_claim(self):
        source = compact_fixture()
        out, manifest = optimize(source, moves=12, seed=7)
        self.assertTrue(_electrically_valid(out))
        self.assertIn("whole_net_ripup", manifest)
        self.assertFalse(manifest["record_eligible"])
        self.assertFalse(manifest["whole_net_ripup"]["record_eligible"])

    def test_search_import_graph_is_separate_from_independent_verification(self):
        tree = ast.parse((ROOT / "hellmode/net_ripup.py").read_text())
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        for forbidden in (
            "copper_model", "strict_occupancy", "pad_geometry", "verify_layout",
            "solve", "board_geometry",
        ):
            self.assertNotIn(forbidden, imported)


if __name__ == "__main__":
    unittest.main()
