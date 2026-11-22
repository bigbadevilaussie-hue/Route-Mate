"""Archive historical Moto artwork findings without treating them as proof of contact."""
import json
import unittest
from pathlib import Path

from solve.wire_keepout import wire_keepout_errors


ROOT = Path(__file__).resolve().parent.parent


class SavedMotoGeometryBaselineTests(unittest.TestCase):
    def test_old_moto_reports_artwork_warnings_with_provenance_unknown(self):
        path = ROOT / "benchmarks/moto/moto14wires30cuts.json"
        project = json.loads(path.read_text(encoding="utf-8"))
        errors = wire_keepout_errors(project)
        self.assertTrue(
            any("w8: jumper crosses component artwork/keepout: Q1" in x for x in errors),
            errors,
        )
        self.assertTrue(
            any("w9: jumper crosses component artwork/keepout: 12v Mosfet" in x for x in errors),
            errors,
        )
        # Existing archived artwork-only flags are NOT pre-certified obstructions.
        # Do not rewrite the original project data to satisfy these warnings.


if __name__ == "__main__":
    unittest.main()
