"""Tests for recording the GUI's repository test stage in the sidecar."""
from __future__ import annotations

import unittest

from pipeline.adapters import test_suite_stage_result
from pipeline.contracts import project_sha256


class RepositoryTestStageAdapterTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "board": {"rows": 24, "cols": 56},
            "components": [{"id": "R1"}],
            "nets": [],
            "netAssignments": [],
        }

    def test_passed_test_run_is_recorded_against_project_snapshot(self):
        result, findings = test_suite_stage_result(
            self.project, returncode=0, output="Ran 12 tests in 0.4s\\n\\nOK"
        )
        self.assertEqual(result.stage, "TEST.repository")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.extra["workflow_stage"], "TEST")
        self.assertEqual(result.input_project_sha256, project_sha256(self.project))
        self.assertEqual(result.output_project_sha256, project_sha256(self.project))
        self.assertEqual(result.report["status"], "PASS")
        self.assertEqual(findings, [])

    def test_failed_test_run_creates_error_finding(self):
        result, findings = test_suite_stage_result(
            self.project, returncode=1, output="FAILED (failures=1)"
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.report["status"], "FAIL")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "error")
        self.assertEqual(result.finding_ids, [findings[0].finding_id])

    def test_frozen_application_records_test_as_not_run(self):
        result, findings = test_suite_stage_result(
            self.project, returncode=None, skipped=True
        )
        self.assertEqual(result.status, "not_run")
        self.assertEqual(result.report["status"], "SKIPPED")
        self.assertTrue(result.report["skipped"])
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
