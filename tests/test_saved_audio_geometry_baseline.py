"""Characterize historical AUDIO artwork overlaps before changing routing policy.

The legacy saved board is not a certified physical route. This regression
documents that the current two-dimensional capacitor keepout rejects three
jumpers, and distinguishes these warnings from intermediate-pad collisions.
"""
import json
import unittest
from pathlib import Path

from solve.wire_keepout import wire_keepout_errors


FIXTURE = Path(__file__).resolve().parent.parent / "benchmarks/audio/audio10wires38cuts.json"


class SavedAudioGeometryBaselineTests(unittest.TestCase):
    def test_saved_audio_capacitor_artwork_warnings_are_not_pad_warnings(self):
        project = json.loads(FIXTURE.read_text(encoding="utf-8"))
        errors = wire_keepout_errors(project)
        artwork = [error for error in errors if "artwork/keepout" in error]
        pins = [error for error in errors if "intermediate component pin/pad" in error]

        self.assertEqual(
            artwork,
            [
                "w4: jumper crosses component artwork/keepout: C4",
                "w6: jumper crosses component artwork/keepout: C4",
                "w8: jumper crosses component artwork/keepout: C7",
            ],
        )
        self.assertEqual(pins, [])
        # This fixture pins down present behaviour, NOT a claim that the
        # construction is safe. Artwork overlaps require a physical policy
        # separate from exposed-pad collisions and actual wire clearance.


if __name__ == "__main__":
    unittest.main()
