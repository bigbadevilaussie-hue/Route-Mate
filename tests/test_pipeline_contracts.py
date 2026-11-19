"""Tests for the shared Route-Mate pipeline hand-off contracts."""
from __future__ import annotations

import copy
import unittest

from pipeline.contracts import (
    Finding,
    PipelineContext,
    StageResult,
    make_finding_id,
    project_sha256,
)


def finding(*, message="Footprint unresolved", status="open"):
    producer = {"stage": "prepare", "module": "prepare.sanity.electrical"}
    subjects = [{"type": "component", "id": "R12"}]
    location = {"row": 8, "col": 21}
    return Finding(
        finding_id=make_finding_id("prepare", "unknown_footprint", subjects, location),
        code="unknown_footprint",
        severity="warning",
        status=status,
        message=message,
        producer=producer,
        subjects=subjects,
        location=location,
        evidence={"field": "defId", "value": "custom-unknown"},
    )


def context():
    return PipelineContext(
        run_id="run-test-001",
        project_path="projects/moto.json",
        project_sha256=project_sha256({"board": {"rows": 24, "cols": 56}}),
        sources=[{"kind": "project_json", "sha256": "source-hash"}],
    )


class ProjectHashTests(unittest.TestCase):
    def test_hash_is_independent_of_dictionary_insertion_order(self):
        left = {"board": {"rows": 24, "cols": 56}, "components": []}
        right = {"components": [], "board": {"cols": 56, "rows": 24}}
        self.assertEqual(project_sha256(left), project_sha256(right))

    def test_hash_changes_when_project_data_changes(self):
        left = {"board": {"rows": 24, "cols": 56}}
        right = {"board": {"rows": 24, "cols": 55}}
        self.assertNotEqual(project_sha256(left), project_sha256(right))

    def test_hash_rejects_non_json_values_and_nan(self):
        with self.assertRaisesRegex(ValueError, "JSON-compatible"):
            project_sha256({"bad": object()})
        with self.assertRaisesRegex(ValueError, "JSON-compatible"):
            project_sha256({"bad": float("nan")})


class FindingTests(unittest.TestCase):
    def test_finding_id_is_stable_and_does_not_depend_on_message(self):
        first = finding(message="First wording")
        second = finding(message="Updated wording")
        self.assertEqual(first.finding_id, second.finding_id)

    def test_finding_round_trip_preserves_unknown_fields(self):
        data = finding().to_dict()
        data["future_finding_field"] = {"kept": True}
        restored = Finding.from_dict(data)
        self.assertEqual(restored.to_dict()["future_finding_field"], {"kept": True})

    def test_invalid_severity_and_status_are_rejected(self):
        data = finding().to_dict()
        data["severity"] = "fatal-ish"
        with self.assertRaisesRegex(ValueError, "severity"):
            Finding.from_dict(data)
        data = finding().to_dict()
        data["status"] = "deleted"
        with self.assertRaisesRegex(ValueError, "status"):
            Finding.from_dict(data)


class StageResultTests(unittest.TestCase):
    def test_stage_result_round_trip_preserves_report_and_unknown_fields(self):
        result = StageResult(
            stage="prepare",
            status="completed",
            module="prepare.sanity.electrical",
            input_project_sha256="input-hash",
            output_project_sha256="output-hash",
            metrics={"components": 33},
            report={"status": "PASS", "errors": [], "warnings": []},
            summary="Electrical sanity passed.",
        )
        data = result.to_dict()
        data["future_stage_field"] = "preserve"
        restored = StageResult.from_dict(data)
        self.assertEqual(restored.report["status"], "PASS")
        self.assertEqual(restored.to_dict()["future_stage_field"], "preserve")

    def test_invalid_stage_status_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "stage status"):
            StageResult(stage="prepare", status="PASS", module="prepare.check")


class PipelineContextTests(unittest.TestCase):
    def test_context_round_trip_preserves_nested_unknown_fields(self):
        data = context().to_dict()
        data["future_top_level"] = {"kept": 1}
        data["project"]["future_project_field"] = "kept"
        data["pipeline"]["future_pipeline_field"] = ["kept"]
        restored = PipelineContext.from_dict(data)
        round_trip = restored.to_dict()
        self.assertEqual(round_trip["future_top_level"], {"kept": 1})
        self.assertEqual(round_trip["project"]["future_project_field"], "kept")
        self.assertEqual(round_trip["pipeline"]["future_pipeline_field"], ["kept"])

    def test_add_findings_appends_and_does_not_duplicate_identical_record(self):
        state = context()
        item = finding()
        state.add_findings([item])
        state.add_findings([copy.deepcopy(item)])
        self.assertEqual(len(state.findings), 1)

    def test_conflicting_duplicate_finding_id_is_rejected(self):
        state = context()
        state.add_findings([finding()])
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            state.add_findings([finding(message="Conflicting content")])
        self.assertEqual(len(state.findings), 1)

    def test_stage_handoff_carries_findings_forward(self):
        state = context()
        item = finding()
        result = StageResult(
            stage="prepare",
            status="completed",
            module="prepare.sanity.electrical",
            finding_ids=[item.finding_id],
        )
        state.record_stage(result, [item])
        self.assertEqual(state.current_stage, "prepare")
        self.assertEqual(state.stages["prepare"], result)
        self.assertEqual(state.findings, [item])

    def test_stage_cannot_reference_missing_finding(self):
        state = context()
        result = StageResult(
            stage="solve",
            status="blocked",
            module="solve.quick_fit",
            finding_ids=["missing-finding"],
        )
        with self.assertRaisesRegex(ValueError, "unknown finding IDs"):
            state.record_stage(result)
        self.assertEqual(state.findings, [])
        self.assertEqual(state.stages, {})
        self.assertIsNone(state.current_stage)

    def test_run_state_schema_version_is_checked(self):
        data = context().to_dict()
        data["schema_version"] = 999
        with self.assertRaisesRegex(ValueError, "schema version"):
            PipelineContext.from_dict(data)

    def test_json_round_trip_is_serializable(self):
        state = context()
        state.record_stage(
            StageResult(stage="collect", status="completed", module="collect"),
        )
        import json
        encoded = json.dumps(state.to_dict(), sort_keys=True)
        restored = PipelineContext.from_dict(json.loads(encoded))
        self.assertEqual(restored.to_dict(), state.to_dict())


if __name__ == "__main__":
    unittest.main()
