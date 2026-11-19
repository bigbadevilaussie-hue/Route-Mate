import tempfile
import unittest
from pathlib import Path

from pipeline import PipelineRun, project_import_stage_result, project_sha256


class ProjectImportAdapterTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "board": {"rows": 10, "cols": 20},
            "components": [{"id": "R1"}],
            "nets": [],
            "netAssignments": [],
        }
        self.project = {
            **self.source,
            "board": {
                "rows": 24, "cols": 56,
                "actualRows": 24, "actualCols": 56,
                "wantedRows": 24, "wantedCols": 56,
                "wantedRowsMode": "fixed", "wantedColsMode": "max",
            },
        }

    def test_import_captures_source_and_validated_project_hashes(self):
        result, findings = project_import_stage_result(
            self.source, self.project,
            options={"actual_rows": 24, "actual_cols": 56},
        )
        self.assertEqual(result.stage, "IN.project_import")
        self.assertEqual(result.input_project_sha256, project_sha256(self.source))
        self.assertEqual(result.output_project_sha256, project_sha256(self.project))
        self.assertEqual(result.metrics["components"], 1)
        self.assertEqual(findings, [])

    def test_import_warnings_become_findings(self):
        result, findings = project_import_stage_result(
            self.source, self.project,
            warnings=["Unresolved component definition"],
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(result.finding_ids, [findings[0].finding_id])
        self.assertEqual(findings[0].severity, "warning")
        self.assertEqual(findings[0].producer["module"], "gui.project_import")


    def test_import_result_can_be_persisted_in_shared_run_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moto.json"
            run = PipelineRun.create(path, self.source, run_id="gui-import-test")
            result, findings = project_import_stage_result(self.source, self.project)
            run.record_stage(result, findings)
            loaded = PipelineRun.load(run.state_path)
            self.assertEqual(loaded.context.current_stage, "IN.project_import")
            self.assertEqual(
                loaded.context.project_sha256, project_sha256(self.project)
            )


if __name__ == "__main__":
    unittest.main()
