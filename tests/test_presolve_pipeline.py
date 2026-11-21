"""PRE-SOLVE pipeline integration and sidecar round-trip."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline import PipelineRun, presolve_stage_result


ROOT = Path(__file__).resolve().parents[1]


class PresolvePipelineTests(unittest.TestCase):
    def test_moto_and_audio_stage_report_and_sidecar(self):
        for name in ("moto", "audio"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                project = json.loads((ROOT / "benchmarks" / name / (name + ".json")).read_text())
                path = Path(temp) / (name + ".json")
                run = PipelineRun.create(path, project)
                stage, findings = presolve_stage_result(project)
                self.assertEqual(stage.stage, "PREPARE.presolve")
                self.assertEqual(stage.input_project_sha256, stage.output_project_sha256)
                self.assertEqual(len(stage.report["components"]), len(project["components"]))
                run.record_stage(stage, findings)
                loaded = PipelineRun.load(run.state_path)
                self.assertEqual(loaded.context.project_sha256, stage.output_project_sha256)
                self.assertIn("PREPARE.presolve", loaded.context.stages)
                handoff = loaded.handoff(project, "solve.quick_fit")
                self.assertEqual(handoff["project"], project)

    def test_stale_stage_rejected(self):
        project = {"board": {"rows": 1, "cols": 1}, "components": [], "componentDefs": [],
                   "nets": [], "netAssignments": []}
        run = PipelineRun.create("fixture.json", project)
        stage, findings = presolve_stage_result(project)
        changed = {**project, "board": {"rows": 2, "cols": 1}}
        stale = PipelineRun.create("fixture.json", changed)
        with self.assertRaises(ValueError):
            stale.record_stage(stage, findings, save=False)


if __name__ == "__main__":
    unittest.main()
