"""Bounded Quick Solve portfolio invariants and two-candidate selection."""
from __future__ import annotations

import copy
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from solve.parallel_quick import choose_workers, partition_attempts, _process_job
from solve.solution_quality import solution_signature, candidate_quality
from solve.placement_feedback import solve_with_feedback, quality_repair_targets


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

    def test_contact_and_board_edge_feedback_targets_only_movable_parts(self):
        placed = {
            "components": [
                {"id": "F1", "locked": True, "boardPos": {"row": 0, "col": 0}},
                {"id": "C1", "boardPos": {"row": 1, "col": 7}},
                {"id": "MPU", "boardPos": {"row": 1, "col": 2}},
                {"id": "MOSFET", "boardPos": {"row": 1, "col": 5}},
            ],
        }
        quality = {
            "nominal_board_overhang_ids": ["C1", "F1"],
            "nominal_contact_component_ids": ["MPU", "MOSFET", "F1"],
        }
        self.assertEqual(
            quality_repair_targets(placed, quality, {"F1": True}),
            ["C1", "MPU", "MOSFET"],
        )
        self.assertEqual(
            quality_repair_targets(placed, quality, {"F1": True, "C1": True}),
            ["MPU", "MOSFET"],
        )

    def test_verified_contact_warning_relocates_actual_offending_part(self):
        original = {
            "board": {"rows": 5, "cols": 10, "cuts": [], "wires": []},
            "components": [
                {"id": "F1", "locked": True, "boardPos": {"row": 0, "col": 0}},
                {"id": "C1", "boardPos": {"row": 1, "col": 9}},
                {"id": "MPU", "boardPos": {"row": 2, "col": 3}},
            ],
            "netAssignments": [],
        }
        moved = copy.deepcopy(original)
        moved["components"][1]["boardPos"] = {"row": 1, "col": 6}
        with ExitStack() as stack:
            fit = stack.enter_context(patch("solve.placement_feedback.quick_fit"))
            router = stack.enter_context(patch("solve.placement_feedback.route_holes"))
            stack.enter_context(patch("solve.verify.verify_project",
                                      return_value={"status": "PASS"}))
            stack.enter_context(patch("solve.quick_rules.quick_audit",
                                      return_value={"status": "PASS"}))
            stack.enter_context(patch("solve.quality_audit.audit_project",
                                      return_value={"status": "PASS"}))
            quality = stack.enter_context(
                patch("solve.solution_quality.candidate_quality")
            )
            fit.side_effect = [
                {"status": "PLACED", "project": copy.deepcopy(original)},
                {"status": "PLACED", "project": copy.deepcopy(original)},
                {"status": "PLACED", "project": copy.deepcopy(moved)},
            ]
            router.side_effect = [
                {"status": "BUDGET_EXHAUSTED", "errors": ["no route"]},
                {"status": "ROUTED", "project": copy.deepcopy(original),
                 "verification": {"status": "PASS"}},
                {"status": "ROUTED", "project": copy.deepcopy(moved),
                 "verification": {"status": "PASS"}},
            ]
            quality.side_effect = [
                {"signature": "bad", "rank": (1,), "provisional_score": 34.3,
                 "nominal_contacts": 4, "nominal_board_overhangs": ["C1"],
                 "nominal_board_overhang_ids": ["C1"],
                 "nominal_contact_component_ids": ["MPU"]},
                {"signature": "good", "rank": (0,), "provisional_score": 65.0,
                 "nominal_contacts": 0, "nominal_board_overhangs": [],
                 "nominal_board_overhang_ids": [],
                 "nominal_contact_component_ids": []},
            ]
            result = solve_with_feedback(
                original, attempts=3, body_spacing_holes=1, solutions_target=2
            )
        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["solutions_found"], 2)
        self.assertEqual(result["project"]["components"][1]["boardPos"],
                         {"row": 1, "col": 6})
        self.assertEqual(result["attempts_used"], 3)
        self.assertEqual(result["history"][2]["repair_target"], "C1")
        retry_input = fit.call_args_list[2].args[0]["components"]
        self.assertNotIn("boardPos", retry_input[1])
        self.assertTrue(retry_input[0]["locked"])
        self.assertTrue(retry_input[2]["locked"])
        self.assertEqual(fit.call_args_list[2].kwargs["body_spacing_holes"], 1)
        self.assertEqual(router.call_args_list[2].kwargs["expansion_budget"],
                         600000)
        self.assertEqual(original["components"][1]["boardPos"], {"row": 1, "col": 9})

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
        # On the user's near-tied startup probe 3=0.27, 4=0.29,
        # pick four real CPU processes to reduce expensive-tail latency.
        self.assertEqual(choose_workers(3, 4, {3: 0.27, 4: 0.29}), 4)
        self.assertEqual(choose_workers(3, 4, {3: 0.27, 4: 0.50}), 3)

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
        self.assertEqual(solve.call_args.kwargs["hole_expansion_budget"], 180000)
        self.assertNotIn("prefer_spacing_variants", solve.call_args.kwargs)
        # For spacing OFF there is no scout, hence no shift.
        with patch("solve.desktop_integration.solve_for_display",
                   return_value={"status": "ROUTING_FAILED"}) as compact:
            _process_job(layout(1), 6, 12, 0, 3, Queue(), Flag())
        self.assertEqual(compact.call_args.kwargs["variant_offset"], 12)
        self.assertEqual(solve.call_args.kwargs["solutions_target"], 2)

    def test_parallel_worker_actually_explores_selected_spacing(self):
        class Queue:
            def put(self, value):
                pass
        class Flag:
            def is_set(self):
                return False
        # With 3 workers, worker 2 explores Normal/Wider; worker 3
        # remains a bounded compact fallback. Four workers have two
        # spacing explorers; first worker preserves full-budget compact.
        for total, index, spaced, bounded in (
            (3, 0, False, False),
            (3, 1, True, True),
            (3, 2, False, True),
            (4, 2, True, True),
            (4, 3, False, True),
        ):
            with self.subTest(workers=total, index=index):
                with patch("solve.desktop_integration.solve_for_display",
                           return_value={"status": "ROUTING_FAILED"}) as solve:
                    _process_job(layout(1), 6, index * 6, 2, index,
                                 Queue(), Flag(), worker_count=total)
                options = solve.call_args.kwargs
                self.assertEqual(options.get("prefer_spacing_variants", False),
                                 spaced)
                self.assertEqual(options.get("hole_expansion_budget", 600000),
                                 180000 if bounded else 600000)

    def test_requested_spacing_can_be_used_across_entire_variant_range(self):
        with patch("solve.placement_feedback.quick_fit") as fit:
            fit.return_value = {"status": "NO_FIT_FOUND", "errors": ["no fit"]}
            out = solve_with_feedback(
                layout(1), attempts=3, variant_offset=8,
                body_spacing_holes=2, solutions_target=2,
                prefer_spacing_variants=True,
            )
        self.assertEqual(out["status"], "ROUTING_FAILED")
        self.assertEqual([call.kwargs["body_spacing_holes"]
                          for call in fit.call_args_list], [2, 2, 2])
        self.assertEqual([call.kwargs["placement_variant"]
                          for call in fit.call_args_list], [8, 9, 10])

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
