"""M1 independent copper-island, terminal and strict-occupancy integration tests.

These are provisional verification tests. No physical PASS/BUILD_READY is
asserted until measured envelopes and cut-tool access have independent proofs.
"""
from __future__ import annotations

import ast
import copy
import json
import unittest
from pathlib import Path

from hellmode.pad_geometry import collect_pad_holes
from hellmode.copper_model import reconstruct_electrical
from hellmode.verify_layout import verify_layout


ROOT = Path(__file__).resolve().parent.parent


def pad_component(name, row, col, *, net="N"):
    return {"id": name, "defId": "single", "boardPos": {"row": row, "col": col},
            "label": name}, {"componentId": name, "pinId": "1", "netId": net}


def blank(*parts, rows=4, cols=6):
    components, assignments = zip(*parts) if parts else ((), ())
    return {
        "board": {"rows": rows, "cols": cols, "cuts": [], "wires": []},
        "componentDefs": [{"id": "single", "pins": [
            {"id": "1", "offsetRow": 0, "offsetCol": 0}], "bodyCells": []}],
        "components": list(components), "netAssignments": list(assignments),
    }


def wire(name, r0, c0, r1, c1):
    return {"id": name, "from": {"row": r0, "col": c0},
            "to": {"row": r1, "col": c1}}


def reason_set(report):
    return {x["code"] for x in report["errors"]}


class IndependentCopperM1Tests(unittest.TestCase):
    def test_motomix_raw_project_has_123_terminals_and_35_nets_without_shorts(self):
        j = json.loads((ROOT / "benchmarks/moto/motomix-autorouted.json").read_text())
        snapshot = copy.deepcopy(j)
        electrical = reconstruct_electrical(j)
        self.assertEqual(electrical["status"], "PASS", electrical["errors"])
        self.assertEqual(electrical["counts"]["terminals"], 123)
        self.assertEqual(electrical["counts"]["nets_checked"], 35)
        self.assertEqual(electrical["counts"]["wires"], 46)
        self.assertEqual(electrical["counts"]["cuts"], 57)
        self.assertEqual(electrical["counts"]["open_nets"], 0)
        self.assertEqual(electrical["counts"]["short_groups"], 0)
        self.assertEqual(len(electrical["wire_nets"]), 46)
        self.assertEqual(j, snapshot, "M1 cross-check must not mutate input")

    def test_motomix_fails_strict_policy_without_claiming_measured_collision(self):
        j = json.loads((ROOT / "benchmarks/moto/motomix-autorouted.json").read_text())
        outcome = verify_layout(j)
        self.assertEqual(outcome["electrical"]["status"], "PASS")
        self.assertEqual(outcome["status"], "ELECTRICAL_ONLY")
        self.assertIn("STACKING_VIOLATION", outcome["reason_codes"])
        self.assertFalse(outcome["physical_pass"])
        self.assertFalse(outcome["record_eligible"])
        self.assertEqual(outcome["cut_access"], "unverified")
        self.assertEqual(outcome["strict_occupancy"]["counts"]["stacked_gaps"], 51)

    def test_a_valid_2d_wire_connects_separated_copper_rows(self):
        j = blank(pad_component("A", 0, 0), pad_component("B", 2, 0))
        j["board"]["wires"] = [wire("W", 0, 1, 2, 1)]
        audit = reconstruct_electrical(j)
        self.assertEqual(audit["status"], "PASS", audit["errors"])
        self.assertEqual(audit["wire_nets"], {"W": "N"})
        out = verify_layout(j)
        self.assertEqual(out["status"], "GRID_VERIFIED")
        self.assertFalse(out["physical_pass"])
        self.assertIn("UNVERIFIED_PACKAGE_GEOMETRY", out["reason_codes"])

    def test_mutation_remove_necessary_jumper_produces_open(self):
        j = blank(pad_component("A", 0, 0), pad_component("B", 2, 0))
        j["board"]["wires"] = [wire("W", 0, 1, 2, 1)]
        self.assertEqual(reconstruct_electrical(j)["status"], "PASS")
        j["board"]["wires"] = []
        failed = reconstruct_electrical(j)
        self.assertIn("OPEN_NET", reason_set(failed))
        self.assertEqual(failed["counts"]["open_nets"], 1)

    def test_mutation_connect_two_nets_produces_short(self):
        j = blank(pad_component("A", 0, 0, net="N"),
                  pad_component("B", 2, 0, net="M"))
        j["board"]["wires"] = [wire("W", 0, 1, 2, 1)]
        out = reconstruct_electrical(j)
        self.assertIn("SHORT_NETS", reason_set(out))
        self.assertEqual(out["counts"]["short_groups"], 1)
        self.assertEqual(verify_layout(j)["status"], "ELECTRICAL_FAIL")

    def test_between_cut_opens_strip_and_two_vertical_wires_restore(self):
        j = blank(pad_component("A", 0, 0), pad_component("B", 0, 3))
        self.assertEqual(reconstruct_electrical(j)["status"], "PASS")
        j["board"]["cuts"] = [{"row": 0, "col": 1, "kind": "between"}]
        self.assertIn("OPEN_NET", reason_set(reconstruct_electrical(j)))
        j["board"]["wires"] = [wire("W1", 0, 0, 1, 0),
                               wire("W2", 0, 3, 1, 3)]
        self.assertEqual(reconstruct_electrical(j)["status"], "PASS")
        self.assertEqual(verify_layout(j)["status"], "GRID_VERIFIED")

    def test_between_cut_separates_adjacent_different_net_pins(self):
        j = blank(pad_component("A", 0, 0, net="N"),
                  pad_component("B", 0, 1, net="M"))
        self.assertIn("SHORT_NETS", reason_set(reconstruct_electrical(j)))
        j["board"]["cuts"] = [{"row": 0, "col": 0, "kind": "between"}]
        self.assertEqual(reconstruct_electrical(j)["status"], "PASS")

    def test_different_nets_same_hole_is_electrical_failure(self):
        j = blank(pad_component("A", 0, 0, net="N"),
                  pad_component("B", 0, 0, net="M"))
        self.assertIn("SHORT_NETS", reason_set(reconstruct_electrical(j)))
        self.assertIn("DIFFERENT_NET_PINS_SAME_HOLE",
                      verify_layout(j)["reason_codes"])

    def test_offboard_lead_is_reconstructed_as_terminal(self):
        j = blank(pad_component("A", 0, 0))
        j["components"].append({"id": "OFF", "offBoard": True, "boardPos": None,
                                "leads": {"1": {"row": 1, "col": 0}}})
        j["netAssignments"].append(
            {"componentId": "OFF", "pinId": "1", "netId": "N"})
        j["board"]["wires"] = [wire("W", 0, 2, 1, 2)]
        result = reconstruct_electrical(j)
        self.assertEqual(result["status"], "PASS", result["errors"])
        self.assertEqual(result["counts"]["terminals"], 2)

    def test_missing_offboard_lead_blocks_false_verification(self):
        j = blank(pad_component("A", 0, 0))
        j["components"].append({"id": "OFF", "offBoard": True, "boardPos": None})
        j["netAssignments"].append(
            {"componentId": "OFF", "pinId": "1", "netId": "N"})
        self.assertIn("BAD_TERMINAL", reason_set(reconstruct_electrical(j)))

    def test_footprint_override_pin_rotation_and_numeric_aliases(self):
        j = blank(rows=8, cols=8)
        j["componentDefs"].append({"id": "mixed", "pins": [
            {"id": "a", "offsetRow": 0, "offsetCol": 0},
            {"id": "k", "offsetRow": 0, "offsetCol": 2},
        ]})
        j["components"].append({
            "id": "D1", "defId": "mixed",
            "boardPos": {"row": 1, "col": 1}, "rotation": 90,
        })
        j["netAssignments"].extend([
            {"componentId": "D1", "pinId": "1", "netId": "N"},
            {"componentId": "D1", "pinId": "2", "netId": "M"},
        ])
        pads = collect_pad_holes(j)["terminals"]
        self.assertEqual({(p["row"], p["col"], p["net_id"]) for p in pads},
                         {(1, 1, "N"), (3, 1, "M")})
        self.assertEqual(reconstruct_electrical(j)["status"], "PASS")
        j["components"][0]["footprintOverride"] = {"pins": [
            {"id": "a", "offsetRow": 0, "offsetCol": 0},
            {"id": "k", "offsetRow": 3, "offsetCol": 0},
        ]}
        pads = collect_pad_holes(j)["terminals"]
        self.assertEqual({(p["row"], p["col"], p["net_id"]) for p in pads},
                         {(1, 4, "N"), (1, 1, "M")})

    def test_invalid_cut_kind_is_reason_coded_not_silently_ignored(self):
        j = blank(pad_component("A", 0, 0))
        j["board"]["cuts"] = [{"row": 0, "col": 1, "kind": "below"}]
        result = reconstruct_electrical(j)
        self.assertIn("UNSUPPORTED_CUT_KIND", reason_set(result))
        self.assertEqual(result["status"], "FAIL")

    def test_untrusted_serialized_wire_net_labels_are_ignored(self):
        j = blank(pad_component("A", 0, 0), pad_component("B", 2, 0))
        j["board"]["wires"] = [wire("W", 0, 1, 2, 1)]
        j["board"]["wires"][0]["netId"] = "OTHER_FAKE_NET"
        self.assertEqual(reconstruct_electrical(j)["wire_nets"], {"W": "N"})

    def test_conditional_routing_policy_is_not_implemented(self):
        j = blank(pad_component("A", 0, 0))
        with self.assertRaises(NotImplementedError):
            verify_layout(j, {"geometry_policy": "ALLOW_CONDITIONAL"})

    def test_import_graph_has_no_existing_verifier_or_router_dependencies(self):
        for name in ("pad_geometry.py", "copper_model.py", "verify_layout.py"):
            source = (ROOT / "hellmode" / name).read_text()
            tree = ast.parse(source)
            dependencies = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    dependencies.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    dependencies.append(node.module or "")
            for dependency in dependencies:
                self.assertNotIn(dependency.split(".")[0],
                                 {"solve", "board_geometry", "placement_policy",
                                  "adjacency", "tools", "pipeline",
                                  "quick_rules", "route", "verify",
                                  "hellmode_m1_spike"})


if __name__ == "__main__":
    unittest.main()
