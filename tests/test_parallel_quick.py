"""Bounded Quick Solve portfolio invariants and two-candidate selection."""
from __future__ import annotations

import copy
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from solve.parallel_quick import choose_workers, partition_attempts, _process_job
from solve.solution_quality import solution_signature, candidate_quality
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

    def test_overhanging_cap_is_ranked_below_inside_board_layout(self):
        source = layout(1)
        scored = {
            "score": 43.3, "wires": 10, "cuts": 10,
            "wire_length_mm": 20.0,
        }
        with ExitStack() as stack:
            stack.enter_context(patch(
                "solve.render_quality.score_render", return_value=scored
            ))
            stack.enter_context(patch(
                "geometry_sidecar.make_document", return_value={}
            ))
            stack.enter_context(patch(
                "geometry_sidecar.assess_saved_board",
                return_value={"status": "ASSUMED_CLEARANCE_PASS",
                              "contact_findings": []},
            ))
            stack.enter_context(patch(
                "geometry_sidecar.assumed_body_pad_keepouts",
                return_value=[{"id": "C1", "label": "C1",
                               "shape": "circle", "center_mm": [0.0, 0.0],
                               "radius_mm": 2.0}],
            ))
            with patch("solve.quick_fit._nominal_body_overhangs_board",
                       return_value=False):
                clean = candidate_quality(source)
            with patch("solve.quick_fit._nominal_body_overhangs_board",
                       return_value=True):
                protruding = candidate_quality(source)
        self.assertLess(clean["rank"], protruding["rank"])
        self.assertEqual(protruding["nominal_board_overhangs"], ["C1"])
        self.assertEqual(clean["nominal_board_overhangs"], [])

    def test_route_fingerprint_ignores_generated_wire_ids(self):
        a = layout(1)
        a["board"]["wires"] = [{
            "id": "RM-W001", "from": {"row": 0, "col": 2},
            "to": {"row": 2, "col": 2},
        }]
        b = copy.deepcopy(a)
        b["board"]["wires"][0]["id"] = "RM-W999"
        self.assertEqual(solution_signature(a), solution_signature(b))
        b["board"]["wires"][0]["to"]["col"] = 3
        self.assertNotEqual(solution_signature(a), solution_signature(b))

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
        self.assertEqual(solve.call_args.kwargs["variant_offset"], 11)
        self.assertEqual(solve.call_args.kwargs["body_spacing_holes"], 2)
        # For spacing OFF there is no scout, hence no shift.
        with patch("solve.desktop_integration.solve_for_display",
                   return_value={"status": "ROUTING_FAILED"}) as compact:
            _process_job(layout(1), 6, 12, 0, 3, Queue(), Flag())
        self.assertEqual(compact.call_args.kwargs["variant_offset"], 12)
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
        with patch("solve.placement_feedback.quick_fit") as fit, \
             patch("solve.placement_feedback.route_holes") as route, \
             patch("solve.verify.verify_project", return_value={"status": "PASS"}), \
             patch("solve.quick_rules.quick_audit", return_value={"status": "PASS"}), \
             patch("solve.quality_audit.audit_project", return_value={"status": "PASS"}), \
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
            quality.side_effect = lambda project, **kwargs: {
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

    def test_low_quality_two_results_trigger_bounded_third_attempt(self):
        with ExitStack() as stack:
            fit = stack.enter_context(patch("solve.placement_feedback.quick_fit"))
            route = stack.enter_context(patch("solve.placement_feedback.route_holes"))
            stack.enter_context(patch("solve.verify.verify_project",
                                      return_value={"status": "PASS"}))
            stack.enter_context(patch("solve.quick_rules.quick_audit",
                                      return_value={"status": "PASS"}))
            stack.enter_context(patch("solve.quality_audit.audit_project",
                                      return_value={"status": "PASS"}))
            quality = stack.enter_context(patch("solve.solution_quality.candidate_quality"))
            fit.side_effect = [{"status": "PLACED", "project": layout(i)}
                               for i in (1, 2, 3)]
            route.side_effect = [
                {"status": "ROUTED", "project": layout(i),
                 "verification": {"status": "PASS"}} for i in (1, 2, 3)
            ]
            quality.side_effect = lambda project, **kwargs: (
                lambda col: {
                    "signature": str(col), "rank": (4 - col,),
                    "nominal_contacts": 3 - col,
                    "provisional_score": 30.0 if col < 3 else 60.0,
                }
            )(project["components"][0]["boardPos"]["col"])
            result = solve_with_feedback(layout(0), attempts=3,
                                         body_spacing_holes=0, solutions_target=2)
        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["solutions_found"], 3)
        self.assertEqual(result["attempts_used"], 3)
        self.assertEqual(result["project"]["components"][0]["boardPos"]["col"], 3)

    def test_if_only_one_solution_exists_it_is_retained(self):
        with patch("solve.placement_feedback.quick_fit") as fit, \
             patch("solve.placement_feedback.route_holes") as route, \
             patch("solve.verify.verify_project", return_value={"status": "PASS"}), \
             patch("solve.quick_rules.quick_audit", return_value={"status": "PASS"}), \
             patch("solve.quality_audit.audit_project", return_value={"status": "PASS"}), \
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
