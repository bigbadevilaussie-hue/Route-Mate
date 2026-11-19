"""Tests for SOLVE and independent-verifier pipeline adapters."""
from __future__ import annotations

import copy
import unittest

from pipeline.adapters import (
    quick_fit_stage_result,
    quick_place_stage_result,
    route_stage_result,
    verification_stage_result,
)
from pipeline.contracts import PipelineContext, project_sha256


class SolvePipelineAdapterTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "board": {"rows": 24, "cols": 56, "cuts": [], "wires": []},
            "components": [{"id": "R1", "label": "R1"}],
            "nets": [{"id": "N1"}],
            "netAssignments": [],
            "componentDefs": [],
        }

    def test_quick_fit_preserves_report_errors_warnings_and_project_hashes(self):
        output_project = copy.deepcopy(self.project)
        output_project["components"][0]["boardPos"] = {"row": 2, "col": 3}
        output = {
            "status": "PLACED", "project": output_project, "errors": [],
            "warnings": ["clearance reduced"],
            "placed": 1, "excluded": 0,
            "report": {
                "board": {"rows": 24, "cols": 56},
                "clearance_requested": 1, "clearance_used": 0,
                "net_distance_score": 0, "net_links_scored": 0,
                "search": "deterministic greedy net-aware placement",
            },
        }

        result, findings = quick_fit_stage_result(self.project, output)

        self.assertEqual(result.stage, "SOLVE.quick_fit")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.input_project_sha256, project_sha256(self.project))
        self.assertEqual(result.output_project_sha256, project_sha256(output_project))
        self.assertEqual(result.report["result"], output)
        self.assertEqual(result.metrics["placed"], 1)
        self.assertEqual([item.severity for item in findings], ["warning"])

    def test_quick_place_failure_is_retained_as_domain_status(self):
        output = {
            "status": "FAIL", "project": copy.deepcopy(self.project),
            "errors": ["R1: no footprint definition"], "placed": 0, "excluded": 0,
        }

        result, findings = quick_place_stage_result(self.project, output)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.report["status"], "FAIL")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "error")

    def test_route_retains_nested_verification_and_route_warnings(self):
        verification = {
            "status": "PASS", "errors": [], "warnings": [],
            "counts": {"holes": 1344, "cuts": 1, "wires": 2},
        }
        output = {
            "status": "ROUTED", "project": copy.deepcopy(self.project),
            "errors": [], "warnings": ["wire body not modelled"],
            "cuts_added": 1, "wires_added": 2,
            "verification": verification,
        }

        result, findings = route_stage_result(self.project, output)

        self.assertEqual(result.stage, "SOLVE.route")
        self.assertEqual(result.report["verification"], verification)
        self.assertEqual(result.metrics["cuts_added"], 1)
        self.assertEqual(result.metrics["wires_added"], 2)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "warning")

    def test_route_failure_preserves_original_project_hash_and_errors(self):
        output = {
            "status": "ROUTING_FAILED", "project": copy.deepcopy(self.project),
            "errors": ["different nets share hole (0, 0)"],
            "warnings": [], "cuts_added": 0, "wires_added": 0,
            "verification": None,
        }

        result, findings = route_stage_result(self.project, output)

        self.assertEqual(result.output_project_sha256, result.input_project_sha256)
        self.assertEqual(result.report["result"]["status"], "ROUTING_FAILED")
        self.assertEqual(findings[0].severity, "error")

    def test_verifier_report_is_separate_and_does_not_change_project(self):
        report = {
            "status": "FAIL", "errors": ["open net N1"],
            "warnings": ["no physical wire path validation"],
            "counts": {"holes": 1344, "cuts": 0, "wires": 0,
                       "on_board_terminals": 2, "nets_checked": 1,
                       "short_groups": 0, "open_nets": 1,
                       "adjacency_conflicts": 0},
        }

        result, findings = verification_stage_result(self.project, report)

        self.assertEqual(result.stage, "VERIFY.independent")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.report, report)
        self.assertEqual(result.input_project_sha256, result.output_project_sha256)
        self.assertEqual([item.severity for item in findings], ["error", "warning"])

    def test_solve_and_verify_findings_accumulate_in_pipeline_context(self):
        fit_output = {
            "status": "NO_FIT_FOUND", "project": copy.deepcopy(self.project),
            "errors": ["no placement found"], "warnings": [],
            "placed": 0, "excluded": 0, "report": {"note": "not proof of impossibility"},
        }
        fit_result, fit_findings = quick_fit_stage_result(self.project, fit_output)
        verify_report = {
            "status": "FAIL", "errors": ["open net N1"], "warnings": [],
            "counts": {"holes": 1344, "cuts": 0, "wires": 0},
        }
        verify_result, verify_findings = verification_stage_result(self.project, verify_report)
        context = PipelineContext(
            run_id="solve-handoff-test",
            project_path="project.json",
            project_sha256=project_sha256(self.project),
        )

        context.record_stage(fit_result, fit_findings)
        context.record_stage(verify_result, verify_findings)

        self.assertEqual(len(context.findings), 2)
        self.assertEqual(context.current_stage, "VERIFY.independent")
        self.assertEqual(context.stages["SOLVE.quick_fit"].report["result"]["status"],
                         "NO_FIT_FOUND")
        self.assertEqual(context.stages["VERIFY.independent"].report["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
