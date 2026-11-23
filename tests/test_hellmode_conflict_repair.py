"""STRICT 2D conflict-directed repair proves real independent outcomes.

Repair is not a full physical certifier and never awards RECORD.
"""
from __future__ import annotations

import ast
import copy
import json
import random
import unittest
from pathlib import Path

from hellmode.conflict_repair import (
    repair_conflicts, _score, _paired_rebridge_candidates,
)
from hellmode.topology_moves import StripSegments
from hellmode.copper_model import reconstruct_electrical
from hellmode.strict_occupancy import audit_strict_occupancy
from hellmode.demo import optimize, _electrically_valid


ROOT = Path(__file__).resolve().parent.parent


def crossing():
    return {
        "board": {"rows": 5, "cols": 6, "cuts": [], "wires": [
            {"id": "N-wire", "from": {"row": 0, "col": 1},
             "to": {"row": 3, "col": 1}},
            {"id": "M-wire", "from": {"row": 1, "col": 1},
             "to": {"row": 4, "col": 1}},
        ]},
        "componentDefs": [{"id": "pad", "pins": [
            {"id": "1", "offsetRow": 0, "offsetCol": 0}], "bodyCells": []}],
        "components": [
            {"id": "N1", "defId": "pad", "boardPos": {"row": 0, "col": 0}},
            {"id": "N2", "defId": "pad", "boardPos": {"row": 3, "col": 0}},
            {"id": "M1", "defId": "pad", "boardPos": {"row": 1, "col": 0}},
            {"id": "M2", "defId": "pad", "boardPos": {"row": 4, "col": 0}},
        ],
        "netAssignments": [
            {"componentId": "N1", "pinId": "1", "netId": "N"},
            {"componentId": "N2", "pinId": "1", "netId": "N"},
            {"componentId": "M1", "pinId": "1", "netId": "M"},
            {"componentId": "M2", "pinId": "1", "netId": "M"},
        ],
    }


def repair(project, rounds=6):
    independent = reconstruct_electrical(project)
    return repair_conflicts(
        project, pads=independent["pin_holes"],
        wire_nets=independent["wire_nets"],
        electrical_check=_electrically_valid,
        rounds=rounds, seed=2, candidates_per_wire=40,
    )


class ConflictDirectedRepairTests(unittest.TestCase):
    def test_two_essential_different_net_wires_are_physically_unstacked(self):
        starting = crossing()
        pristine = copy.deepcopy(starting)
        self.assertTrue(_electrically_valid(starting))
        first = audit_strict_occupancy(starting["board"])
        self.assertGreater(first["counts"]["excess_gap_occupancy"], 0)
        final, summary = repair(starting)
        self.assertEqual(starting, pristine)
        self.assertGreater(summary["accepted_rebridges"], 0)
        self.assertEqual(summary["final_excess"], 0)
        self.assertEqual(summary["final_illegal_holes"], 0)
        self.assertTrue(_electrically_valid(final))
        check = audit_strict_occupancy(
            final["board"], pin_holes=reconstruct_electrical(final)["pin_holes"],
            trusted_wire_nets=reconstruct_electrical(final)["wire_nets"]
        )
        self.assertEqual(check["counts"]["excess_gap_occupancy"], 0)
        self.assertEqual(check["counts"]["shared_landing_holes"], 0)
        self.assertEqual(check["counts"]["intermediate_pad_holes"], 0)
        self.assertFalse(summary["physically_certified"])

    def test_coordinated_pair_candidates_preserve_both_nets(self):
        source = crossing()
        proof = reconstruct_electrical(source)
        pads, owners = proof["pin_holes"], proof["wire_nets"]
        old, _ = _score(source["board"]["wires"], pads, owners)
        model = StripSegments(source["board"])
        ranked, scanned = _paired_rebridge_candidates(
            source["board"], model, ["N-wire", "M-wire"],
            old, pads, owners, random.Random(15), 30,
        )
        self.assertGreater(scanned, 0)
        self.assertTrue(ranked)
        chosen = None
        for _, first, second, replacements, predicted in ranked:
            trial = copy.deepcopy(source)
            trial["board"]["wires"] = [
                w for w in trial["board"]["wires"]
                if w["id"] not in (first, second)
            ] + list(replacements)
            if _electrically_valid(trial):
                chosen = trial
                self.assertLess(predicted.objective[:3], old.objective[:3])
                break
        self.assertIsNotNone(chosen)
        self.assertEqual(reconstruct_electrical(chosen)["counts"]["short_groups"], 0)
        self.assertEqual(source, crossing())

    def test_no_mutation_when_zero_repair_rounds(self):
        project = crossing()
        repaired, summary = repair(project, rounds=0)
        self.assertEqual(repaired, project)
        self.assertEqual(summary["accepted_rebridges"], 0)
        self.assertEqual(summary["initial_excess"], summary["final_excess"])

    def test_rejects_invalid_electrical_start(self):
        project = crossing()
        project["board"]["wires"].clear()
        with self.assertRaisesRegex(ValueError, "verified electrical"):
            repair(project)

    def test_repair_output_is_deterministic(self):
        project = crossing()
        a, run_a = repair(project)
        b, run_b = repair(project)
        self.assertEqual(a, b)
        self.assertEqual(run_a, run_b)

    def test_motomix_repair_is_safe_exploratory_only(self):
        source = json.loads(
            (ROOT / "benchmarks/moto/motomix-autorouted.json").read_text()
        )
        initial = audit_strict_occupancy(source["board"])
        repaired, run = repair(source, rounds=2)
        report = reconstruct_electrical(repaired)
        self.assertEqual(report["status"], "PASS", report["errors"])
        self.assertLessEqual(
            run["final_excess"],
            initial["counts"]["excess_gap_occupancy"]
        )
        self.assertFalse(run["physically_certified"])

    def test_alpha_includes_actual_conflict_repair_results(self):
        result, summary = optimize(crossing(), moves=12, seed=6)
        self.assertIn("conflict_repair", summary)
        self.assertTrue(_electrically_valid(result))
        self.assertFalse(summary["record_eligible"])
        self.assertFalse(summary["physical_pass"])

    def test_search_module_cannot_import_electrical_or_physical_certifier(self):
        source = (ROOT / "hellmode/conflict_repair.py").read_text()
        tree = ast.parse(source)
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
        forbidden = {"copper_model", "strict_occupancy", "verify_layout",
                     "solve", "board_geometry", "pad_geometry"}
        self.assertFalse(set(modules) & forbidden)


if __name__ == "__main__":
    unittest.main()
