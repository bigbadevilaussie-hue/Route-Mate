"""Persistent collector geometry sidecar and independently checked 2.5D WR regressions."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from geometry_sidecar import assess_saved_board, load_or_create, sidecar_path

ROOT = Path(__file__).resolve().parent.parent


class SavedWitnessSidecarTests(unittest.TestCase):
    def witness(self, name):
        return json.loads((ROOT / "benchmarks" / name /
                           (("audio10wires38cuts.json" if name == "audio"
                             else "moto14wires30cuts.json"))).read_text(encoding="utf-8"))

    def test_audio_collector_sidecar_assesses_all_saved_jumpers(self):
        board = self.witness("audio")
        original = copy.deepcopy(board)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "audio.json"
            first = load_or_create(board, path)
            self.assertTrue(sidecar_path(path).exists())
            self.assertEqual(first, load_or_create(board, path))
            report = assess_saved_board(board, first)
            wires = {item["id"]: item for item in report["wire_results"]}
            self.assertEqual(len(wires), len(board["board"]["wires"]))
            for wire_id in ("w4", "w6", "w8"):
                self.assertEqual(wires[wire_id]["verdict"], "CONDITIONAL",
                                 wires[wire_id])
            self.assertFalse(report["physical_signoff"])
            self.assertEqual(report["status"], "ASSUMED_CLEARANCE_PASS", report)
            self.assertEqual(report["unknown_bodies"], [])
            self.assertEqual(report["counts"]["FAIL_PROVEN"], 0)
            self.assertEqual(report["counts"]["FAIL_UNVERIFIED"], 0)
            self.assertEqual(original, board)

    def test_moto_independent_checks_use_same_collector_sidecar(self):
        board = self.witness("moto")
        with tempfile.TemporaryDirectory() as d:
            document = load_or_create(board, Path(d) / "moto.json")
            result = assess_saved_board(board, document)
        self.assertEqual(len(result["wire_results"]), 14)
        self.assertEqual(result["profile"], "standard-through-hole-v2")
        self.assertEqual(result["status"], "ASSUMED_CLEARANCE_PASS", result)
        self.assertEqual(result["unknown_bodies"], [])
        self.assertEqual(result["counts"]["FAIL_PROVEN"], 0)
        self.assertEqual(result["counts"]["FAIL_UNVERIFIED"], 0)
        self.assertFalse(result["physical_signoff"])

    def test_stale_project_rebuilds_sidecar_and_old_snapshot_rejected(self):
        board = self.witness("audio")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "audio.json"
            old = load_or_create(board, path)
            changed = copy.deepcopy(board)
            cap = next(p for p in changed["components"] if p.get("label") == "C4")
            cap["value"] = "470µF"
            with self.assertRaisesRegex(ValueError, "snapshot"):
                assess_saved_board(changed, old)
            updated = load_or_create(changed, path)
            self.assertNotEqual(old["project_sha256"], updated["project_sha256"])
            self.assertNotEqual(old["geometry_sha256"], updated["geometry_sha256"])
            cap_entry = next(p for p in updated["geometry"]["components"]
                             if p.get("label") == "C4")
            self.assertEqual(cap_entry["profile"], "electrolytic_large")
            self.assertEqual(updated, json.loads(sidecar_path(path).read_text()))

    def test_corrupted_geometry_is_not_accepted(self):
        board = self.witness("audio")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "audio.json"
            doc = load_or_create(board, path)
            damaged = copy.deepcopy(doc)
            damaged["geometry"]["clearance_assumptions"]["wire_od_mm"] = 0.0
            with self.assertRaisesRegex(ValueError, "integrity"):
                assess_saved_board(board, damaged)
            sidecar_path(path).write_text(json.dumps(damaged))
            repaired = load_or_create(board, path)
            self.assertEqual(repaired, doc)


if __name__ == "__main__":
    unittest.main()
