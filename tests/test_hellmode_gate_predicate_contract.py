"""Documentation contract only: physical verifiers are NOT implemented here."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from hellmode.search_state import CertifiedRecord
from hellmode.copper_model import reconstruct_electrical


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/fixtures/hellmode_gate_predicates.json"


class PhysicalGateContractTests(unittest.TestCase):
    def test_predicate_fixtures_cover_each_tier_and_gate(self):
        content = json.loads(FIXTURE.read_text())
        self.assertEqual(content["tolerance_mm"], 1e-9)
        cases = content["cases"]
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        self.assertGreaterEqual(len(cases), 9)
        for predicate in ("jumper_body_clearance", "cut_access"):
            tiers = {c["expected"] for c in cases if c["predicate"] == predicate}
            self.assertTrue({"PASS", "FAIL_PROVEN", "FAIL_UNVERIFIED"} <= tiers)

    def test_cut_access_never_silently_passes_unapproved_preassembly(self):
        cases = json.loads(FIXTURE.read_text())["cases"]
        for case in cases:
            inputs = case["inputs"]
            if (case["predicate"] == "cut_access"
                    and inputs.get("assembly_policy") == "pre_assembly"
                    and not inputs.get("assembly_policy_approved", False)):
                self.assertNotEqual(case["expected"], "PASS")

    def test_fixtures_are_not_being_mistaken_for_executable_certification(self):
        document = (ROOT / "docs/HELLMODE_ACCEPTANCE_PREDICATES.md").read_text()
        self.assertIn("not", document.lower())
        self.assertIn("independent", document.lower())
        self.assertIn("cut", document.lower())
        self.assertIn("clearance", document.lower())


if __name__ == "__main__":
    unittest.main()
