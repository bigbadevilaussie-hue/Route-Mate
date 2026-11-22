"""Desktop bridge regression: real solver output, safety and pipeline inputs."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from solve.desktop_integration import solve_for_display
from solve.verify import verify_project
from solve.quick_rules import quick_audit
from solve.quality_audit import audit_project

ROOT = Path(__file__).resolve().parent.parent


class DesktopIntegrationTests(unittest.TestCase):
    def test_moto_produces_stage_compatible_verified_board(self):
        source = json.loads((ROOT / "benchmarks/moto/moto.json").read_text())
        untouched = copy.deepcopy(source)
        result = solve_for_display(source, attempts=8)
        self.assertEqual(result["status"], "ROUTED", result.get("errors"))
        self.assertEqual(source, untouched)
        self.assertEqual(result["placement"]["status"], "PLACED")
        self.assertEqual(result["routing"]["status"], "ROUTED")
        self.assertEqual(result["verification"]["status"], "PASS")
        self.assertEqual(verify_project(result["project"])["status"], "PASS")
        self.assertNotEqual(quick_audit(result["project"])["status"], "FAIL")
        self.assertEqual(audit_project(result["project"])["status"], "PASS")
        self.assertEqual(result["placement"]["project"]["board"]["cuts"], [])
        self.assertEqual(result["placement"]["project"]["board"]["wires"], [])
        self.assertGreater(len(result["project"]["board"]["cuts"]), 0)
        self.assertGreater(len(result["project"]["board"]["wires"]), 0)

    def test_raw_audio_project_is_displayable(self):
        source = json.loads((ROOT / "benchmarks/audio/audio.json").read_text())
        self.assertFalse(any(c.get("boardPos") for c in source["components"]))
        result = solve_for_display(source, attempts=8)
        self.assertEqual(result["status"], "ROUTED", result.get("errors"))
        self.assertEqual(result["verification"]["status"], "PASS")
        self.assertNotEqual(result["grid_audit"]["status"], "FAIL")
        self.assertEqual(result["physical_audit"]["status"], "PASS")
        self.assertGreater(len(result["project"]["board"]["wires"]), 0)

    def test_failed_solve_is_never_returned_as_displayable_board(self):
        source = {"board": {"rows": 2, "cols": 3}, "components": []}
        outcome = {"status": "ROUTING_FAILED", "project": None,
                   "errors": ["no legal route"], "attempts_used": 1}
        with patch("solve.desktop_integration.solve_with_feedback", return_value=outcome):
            result = solve_for_display(source)
        self.assertEqual(result["status"], "ROUTING_FAILED")
        self.assertIsNone(result["project"])

    def test_independent_verifier_can_veto_solver(self):
        source = {"board": {"rows": 2, "cols": 3, "cuts": [], "wires": []},
                  "components": [], "netAssignments": []}
        proposed = {"status": "ROUTED", "project": copy.deepcopy(source),
                    "placement_variant": 0, "attempts_used": 1}
        with patch("solve.desktop_integration.solve_with_feedback", return_value=proposed):
            with patch("solve.desktop_integration.verify_project",
                       return_value={"status": "FAIL", "errors": ["short"]}):
                with patch("solve.desktop_integration.quick_audit",
                           return_value={"status": "GRID_CLEARANCE_ONLY", "errors": []}):
                    with patch("solve.desktop_integration.audit_project",
                               return_value={"status": "PASS", "errors": [],
                                             "physical_jumper_audit": {"errors": []}}):
                        result = solve_for_display(source)
        self.assertEqual(result["status"], "VERIFICATION_FAILED")
        self.assertEqual(result["errors"], ["short"])
        self.assertIsNone(result["project"])


if __name__ == "__main__":
    unittest.main()
