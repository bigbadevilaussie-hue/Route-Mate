import json
from pathlib import Path
import tempfile
import unittest

from pipeline import Finding, PipelineRun, StageResult, project_sha256, sidecar_path


class PipelineRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project_path = Path(self.temp.name) / "moto.json"
        self.project = {
            "board": {"rows": 24, "cols": 56},
            "components": [],
            "nets": [],
            "netAssignments": [],
        }

    def test_sidecar_path_uses_project_stem(self):
        self.assertEqual(
            sidecar_path(self.project_path),
            Path(self.temp.name) / "moto.routemate-state.json",
        )

    def test_create_records_project_hash_and_source_path(self):
        run = PipelineRun.create(
            self.project_path, self.project, run_id="test-run",
            sources=[{"kind": "project_json", "path": str(self.project_path)}],
        )
        self.assertEqual(run.context.run_id, "test-run")
        self.assertEqual(run.context.project_path, str(self.project_path))
        self.assertEqual(run.context.project_sha256, project_sha256(self.project))
        self.assertEqual(len(run.context.sources), 1)
        self.assertEqual(run.state_path, sidecar_path(self.project_path))

    def test_record_stage_persists_and_updates_current_project_hash(self):
        run = PipelineRun.create(self.project_path, self.project, run_id="test-run")
        updated = {**self.project, "components": [{"id": "R1"}]}
        output_hash = project_sha256(updated)
        result = StageResult(
            stage="SOLVE.quick_fit",
            status="completed",
            module="solve.quick_fit",
            input_project_sha256=project_sha256(self.project),
            output_project_sha256=output_hash,
            report={"status": "PLACED"},
        )
        run.record_stage(result)
        self.assertEqual(run.context.project_sha256, output_hash)
        self.assertTrue(run.state_path.is_file())
        self.assertFalse(run.state_path.with_name(run.state_path.name + ".tmp").exists())

        loaded = PipelineRun.load(run.state_path)
        self.assertEqual(loaded.context.project_sha256, output_hash)
        self.assertEqual(loaded.context.stages["SOLVE.quick_fit"].report, {"status": "PLACED"})

    def test_findings_survive_save_and_load(self):
        run = PipelineRun.create(self.project_path, self.project, run_id="test-run")
        finding = Finding(
            finding_id="PREPARE.electrical:test",
            code="electrical_sanity_warning",
            severity="warning",
            status="open",
            message="Test warning",
            producer={"stage": "PREPARE.electrical", "module": "test"},
            evidence={"source": "unit test"},
        )
        result = StageResult(
            stage="PREPARE.electrical",
            status="completed",
            module="prepare.sanity.electrical",
            input_project_sha256=run.context.project_sha256,
            output_project_sha256=run.context.project_sha256,
            finding_ids=[finding.finding_id],
        )
        run.record_stage(result, [finding])
        loaded = PipelineRun.load(run.state_path)
        self.assertEqual(len(loaded.context.findings), 1)
        self.assertEqual(loaded.context.findings[0].message, "Test warning")

    def test_handoff_carries_current_project_and_open_findings(self):
        from pipeline import make_finding_id

        run = PipelineRun.create(self.project_path, self.project, run_id="test-run")
        finding = Finding(
            finding_id="COLLECT:warning:one",
            code="collector_warning",
            severity="warning",
            status="open",
            message="Footprint warning",
            producer={"stage": "COLLECT", "module": "collect"},
        )
        result = StageResult(
            stage="IN.project_import",
            status="completed",
            module="gui.project_import",
            input_project_sha256=run.context.project_sha256,
            output_project_sha256=run.context.project_sha256,
            finding_ids=[finding.finding_id],
        )
        run.record_stage(result, [finding])

        handoff = run.handoff(self.project, "prepare.sanity.electrical")

        self.assertEqual(handoff["from_stage"], "IN.project_import")
        self.assertEqual(handoff["to_module"], "prepare.sanity.electrical")
        self.assertEqual(handoff["project"], self.project)
        self.assertEqual(handoff["finding_ids"], [finding.finding_id])
        self.assertEqual(handoff["findings"][0]["message"], "Footprint warning")

    def test_handoff_rejects_project_not_matching_latest_stage_output(self):
        run = PipelineRun.create(self.project_path, self.project, run_id="test-run")
        changed = {**self.project, "components": [{"id": "R1"}]}
        with self.assertRaisesRegex(ValueError, "stale pipeline handoff"):
            run.handoff(changed, "solve.quick_fit")

    def test_record_stage_rejects_stale_input_hash(self):
        run = PipelineRun.create(self.project_path, self.project, run_id="test-run")
        changed = {**self.project, "components": [{"id": "R1"}]}
        result = StageResult(
            stage="SOLVE.quick_fit",
            status="completed",
            module="solve.quick_fit",
            input_project_sha256=project_sha256(changed),
            output_project_sha256=project_sha256(changed),
        )
        with self.assertRaisesRegex(ValueError, "stale stage input"):
            run.record_stage(result)
        self.assertEqual(run.context.stages, {})

    def test_load_rejects_non_object_state(self):
        path = Path(self.temp.name) / "bad.json"
        path.write_text(json.dumps([]), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "root must be an object"):
            PipelineRun.load(path)


if __name__ == "__main__":
    unittest.main()
