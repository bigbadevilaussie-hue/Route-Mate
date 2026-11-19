"""Tests for adapters that preserve IN/PREPARE reports in pipeline records."""
from __future__ import annotations

import copy
import unittest

from pipeline.adapters import (
    collector_stage_result,
    electrical_sanity_stage_result,
)
from pipeline.contracts import PipelineContext, project_sha256
from prepare.sanity.electrical import run_electrical_sanity


class PipelineAdapterTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "components": [{"id": "C1", "label": "R1", "defId": "def-resistor"}],
            "nets": [{"id": "N1"}],
            "netAssignments": [{"componentId": "C1", "pinId": "1", "netId": "N1"}],
            "componentDefs": [],
            "board": {"rows": 24, "cols": 56, "cuts": [], "wires": []},
        }

    def test_collector_adapter_preserves_manifest_index_and_warning(self):
        source = copy.deepcopy(self.project)
        manifest = {
            "component_count": 1,
            "json_pin_assignments": 1,
            "actual_board": {"rows": 24, "cols": 56},
            "wanted_board": {"rows": {"mode": "fixed", "value": 24}},
            "warnings": ["one collector warning"],
            "campaign_project": "campaign-input/projects/1.json",
        }
        index = {"id": 1, "parts": 1, "rows": 24, "cols": 56}

        result, findings = collector_stage_result(
            self.project, manifest, index, source_project=source
        )

        self.assertEqual(result.stage, "IN.collect")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.input_project_sha256, project_sha256(source))
        self.assertEqual(result.output_project_sha256, project_sha256(self.project))
        self.assertEqual(result.report["manifest"], manifest)
        self.assertEqual(result.report["index_entry"], index)
        self.assertEqual(result.metrics["components"], 1)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "warning")
        self.assertEqual(result.finding_ids, [findings[0].finding_id])

    def test_collector_preserves_repeated_messages_with_stable_distinct_ids(self):
        manifest = {"warnings": ["same warning", "same warning"]}
        first, first_findings = collector_stage_result(self.project, manifest)
        second, second_findings = collector_stage_result(self.project, manifest)

        self.assertEqual(len(first_findings), 2)
        self.assertNotEqual(first_findings[0].finding_id, first_findings[1].finding_id)
        self.assertEqual(
            [item.finding_id for item in first_findings],
            [item.finding_id for item in second_findings],
        )
        self.assertEqual(first.finding_ids, second.finding_ids)

    def test_collector_does_not_claim_source_hash_when_not_supplied(self):
        result, _ = collector_stage_result(self.project, {"warnings": []})
        self.assertIsNone(result.input_project_sha256)
        self.assertEqual(result.output_project_sha256, project_sha256(self.project))

    def test_electrical_pass_is_retained_as_completed_stage(self):
        report = run_electrical_sanity(self.project)
        result, findings = electrical_sanity_stage_result(self.project, report)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.report["status"], "PASS")
        self.assertEqual(result.input_project_sha256, result.output_project_sha256)
        self.assertEqual(findings, [])
        self.assertEqual(result.finding_ids, [])

    def test_electrical_fail_is_domain_failure_not_stage_execution_failure(self):
        invalid = copy.deepcopy(self.project)
        invalid["netAssignments"][0]["componentId"] = "missing"
        report = run_electrical_sanity(invalid)
        result, findings = electrical_sanity_stage_result(invalid, report)

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.report["status"], "FAIL")
        self.assertTrue(findings)
        self.assertTrue(all(item.severity == "error" for item in findings))
        self.assertEqual(result.finding_ids, [item.finding_id for item in findings])

    def test_prepare_findings_can_be_handed_forward_without_losing_report(self):
        invalid = copy.deepcopy(self.project)
        invalid["netAssignments"][0]["componentId"] = "missing"
        report = run_electrical_sanity(invalid)
        result, findings = electrical_sanity_stage_result(invalid, report)
        context = PipelineContext(
            run_id="test-run",
            project_path="project.json",
            project_sha256=result.output_project_sha256,
        )

        context.record_stage(result, findings)

        self.assertEqual(context.current_stage, "PREPARE.electrical")
        self.assertEqual(context.stages["PREPARE.electrical"].report["status"], "FAIL")
        self.assertEqual(
            [item.finding_id for item in context.findings], result.finding_ids
        )


if __name__ == "__main__":
    unittest.main()
