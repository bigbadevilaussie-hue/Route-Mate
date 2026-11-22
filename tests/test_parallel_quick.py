"""Bounded Quick Solve portfolio invariants and two-candidate selection."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from solve.parallel_quick import choose_workers, partition_attempts, _process_job
from solve.placement_feedback import solve_with_feedback


def layout(col: int):
    return {
        "board": {"rows": 4, "cols": 8, "cuts": [], "wires": []},
        "components": [{"id": "R1", "boardPos": {"row": 1, "col": col}}],
        "nets": [], "netAssignments": [],
    }


class PortfolioPolicyTests(unittest.TestCase):
    def test_split_has_fixed_nonoverlapping_24_attempt_budget(self):
        for workers, expected in (
            (1, [(0, 24)]),
            (3, [(0, 8), (8, 8), (16, 8)]),
            (4, [(0, 6), (6, 6), (12, 6), (18, 6)]),
        ):
            plan = partition_attempts(24, workers)
            self.assertEqual(plan, expected)
            indices = [i for offset, size in plan
                       for i in range(offset, offset + size)]
            self.assertEqual(indices, list(range(24)))

    def test_probe_policy_uses_three_or_four_where_cpu_allows(self):
        self.assertEqual(choose_workers(1, 4), 3)
        self.assertEqual(choose_workers(4, 4), 4)
        self.assertEqual(choose_workers(4, 3), 3)
        self.assertEqual(choose_workers(3, 2), 2)

    def test_worker_uses_real_shared_solver_entry_point(self):
        calls = []
        class Queue:
            def put(self, value):
                calls.append(value)
        class Flag:
            def is_set(self):
                return False
        with patch("solve.desktop_integration.solve_for_display",
                   return_value={"status": "ROUTING_FAILED"}) as solve:
            _process_job(layout(1), 6, 12, 2, 3, Queue(), Flag())
        self.assertEqual(solve.call_args.kwargs["attempts"], 6)
        self.assertEqual(solve.call_args.kwargs["variant_offset"], 12)
        self.assertEqual(solve.call_args.kwargs["body_spacing_holes"], 2)
        self.assertEqual(solve.call_args.kwargs["solutions_target"], 2)

    def test_variant_offset_is_passed_into_quick_fit(self):
        with patch("solve.placement_feedback.quick_fit") as fit:
            fit.return_value = {"status": "NO_FIT_FOUND", "errors": ["no fit"]}
            result = solve_with_feedback(layout(1), attempts=2,
                                         variant_offset=17, solutions_target=2)
        self.assertEqual(result["status"], "ROUTING_FAILED")
        self.assertEqual([c.kwargs["placement_variant"] for c in fit.call_args_list],
                         [17, 18])
        self.assertEqual(len(result["history"]), 2)

    def test_two_verified_distinct_results_choose_fewer_contacts(self):
        first, second = layout(1), layout(3)
        with patch("solve.placement_feedback.quick_fit") as fit, \\
             patch("solve.placement_feedback.route_holes") as route, \\
             patch("solve.verify.verify_project", return_value={"status": "PASS"}), \\
             patch("solve.quick_rules.quick_audit", return_value={"status": "PASS"}), \\
             patch("solve.quality_audit.audit_project", return_value={"status": "PASS"}), \\
             patch("solve.solution_quality.candidate_quality") as quality:
            fit.side_effect = [
                {"status": "PLACED", "project": copy.deepcopy(first)},
                {"status": "PLACED", "project": copy.deepcopy(second)},
            ]
            route.side_effect = [
                {"status": "ROUTED", "project": copy.deepcopy(first),
                 "verification": {"status": "PASS"}},
                {"status": "ROUTED", "project": copy.deepcopy(second),
                 "verification": {"status": "PASS"}},
            ]
            quality.side_effect = lambda project: {
                "signature": str(project["components"][0]["boardPos"]["col"]),
                "rank": (2,) if project["components"][0]["boardPos"]["col"] == 1 else (0,),
            }
            result = solve_with_feedback(layout(0), attempts=2,
                                         body_spacing_holes=0, solutions_target=2)
        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["solutions_found"], 2)
        self.assertEqual(result["placement_variant"], 1)
        self.assertEqual(result["project"]["components"][0]["boardPos"]["col"], 3)
        self.assertEqual(result["attempts_used"], 2)

    def test_if_only_one_solution_exists_it_is_retained(self):
        with patch("solve.placement_feedback.quick_fit") as fit, \\
             patch("solve.placement_feedback.route_holes") as route, \\
             patch("solve.verify.verify_project", return_value={"status": "PASS"}), \\
             patch("solve.quick_rules.quick_audit", return_value={"status": "PASS"}), \\
             patch("solve.quality_audit.audit_project", return_value={"status": "PASS"}), \\
             patch("solve.solution_quality.candidate_quality",
                   return_value={"signature": "one", "rank": (0,)}):
            fit.side_effect = [
                {"status": "PLACED", "project": layout(1)},
                {"status": "NO_FIT_FOUND", "errors": ["not fit"]},
            ]
            route.return_value = {"status": "ROUTED", "project": layout(1),
                                  "verification": {"status": "PASS"}}
            result = solve_with_feedback(layout(0), attempts=2,
                                         body_spacing_holes=0, solutions_target=2)
        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["solutions_found"], 1)
        self.assertEqual(result["attempts_used"], 2)


if __name__ == "__main__":
    unittest.main()
