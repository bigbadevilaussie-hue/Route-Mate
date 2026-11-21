"""Regression tests for bounded transactional routing."""
import copy
import unittest
from unittest.mock import patch

from solve.transactional_route import route_transactionally


class TransactionalRouteTests(unittest.TestCase):
    def setUp(self):
        self.project = {"board": {"cuts": [], "wires": []}}
        self.failure = {
            "status": "ROUTING_FAILED",
            "cut_feasibility": {"sample_candidates": [
                {"cut": {"row": 0, "col": 2, "kind": "between"}},
            ]},
            "bidirectional_cut_feasibility": {"destination_samples": []},
        }

    @patch("solve.transactional_route.verify_project")
    @patch("solve.transactional_route.route_copper")
    def test_commits_only_independently_verified_result(self, router, verifier):
        routed = {"status": "ROUTED", "project": {"board": {"cuts": [
            {"row": 0, "col": 2, "kind": "between"}]}}}
        router.side_effect = [self.failure, routed]
        verifier.return_value = {"status": "PASS"}
        original = copy.deepcopy(self.project)
        result = route_transactionally(self.project)
        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["transactional"]["trials"], 1)
        self.assertEqual(self.project, original)
        self.assertEqual(router.call_args_list[1].args[0]["board"]["cuts"][0]["col"], 2)

    @patch("solve.transactional_route.verify_project")
    @patch("solve.transactional_route.route_copper")
    def test_rejects_failed_independent_verification(self, router, verifier):
        router.side_effect = [self.failure, {
            "status": "ROUTED", "project": self.project}]
        verifier.return_value = {"status": "FAIL", "errors": ["short"]}
        result = route_transactionally(self.project)
        self.assertEqual(result["status"], "ROUTING_FAILED")
        self.assertEqual(result["transactional"]["status"], "NO_VERIFIED_ROUTE")
        self.assertEqual(self.project["board"]["cuts"], [])

    @patch("solve.transactional_route.route_copper")
    def test_zero_budget_preserves_baseline(self, router):
        router.return_value = self.failure
        result = route_transactionally(self.project, max_trials=0)
        self.assertEqual(result["transactional"]["trials"], 0)
        self.assertEqual(router.call_count, 1)


if __name__ == "__main__":
    unittest.main()
