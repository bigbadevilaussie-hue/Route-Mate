"""M1 provisional transactional move/undo and occupancy shadow tests.

These verify mechanics, not solver quality, electrical rerouting, or RECORD
eligibility. Full move-family 200k/paranoid and 1M lock gates remain pending.
"""
from __future__ import annotations

import copy
import json
import random
import unittest
from pathlib import Path

from hellmode.incremental_state import TransactionalState
from hellmode.pad_geometry import collect_pad_holes
from hellmode.strict_occupancy import audit_strict_occupancy


ROOT = Path(__file__).resolve().parent.parent


def tiny():
    return {
        "board": {"rows": 8, "cols": 10, "cuts": [],
                  "wires": [
                      {"id": "J1", "from": {"row": 0, "col": 4},
                       "to": {"row": 5, "col": 4}},
                      {"id": "J2", "from": {"row": 2, "col": 4},
                       "to": {"row": 6, "col": 4}},
                  ]},
        "componentDefs": [
            {"id": "single", "pins": [
                {"id": "1", "offsetRow": 0, "offsetCol": 0}],
             "bodyCells": []},
        ],
        "components": [
            {"id": "A", "defId": "single", "boardPos": {"row": 0, "col": 0}},
            {"id": "B", "defId": "single", "boardPos": {"row": 3, "col": 1}},
            {"id": "LOCK", "defId": "single", "locked": True,
             "boardPos": {"row": 6, "col": 9}},
            {"id": "EDGE", "defId": "single", "edge": True,
             "boardPos": {"row": 1, "col": 0}},
            {"id": "OFF", "offBoard": True, "boardPos": None,
             "leads": {"1": {"row": 7, "col": 0}}},
        ],
        "netAssignments": [
            {"componentId": "A", "pinId": "1", "netId": "N"},
            {"componentId": "B", "pinId": "1", "netId": "M"},
            {"componentId": "LOCK", "pinId": "1", "netId": "K"},
            {"componentId": "EDGE", "pinId": "1", "netId": "E"},
            {"componentId": "OFF", "pinId": "1", "netId": "OFFNET"},
        ],
    }


def shadow(state):
    project = state.snapshot()
    pads = collect_pad_holes(project)
    if pads["errors"]:
        raise AssertionError(pads["errors"])
    independent = audit_strict_occupancy(project["board"], pin_holes=pads["pads"])
    expected = independent["counts"]
    observed = state.metrics()
    keys = (
        "excess_gap_occupancy", "stacked_gaps", "max_stack_depth",
        "shared_landing_holes", "endpoint_on_span_holes",
        "intermediate_pad_holes",
    )
    for key in keys:
        if expected[key] != observed[key]:
            raise AssertionError(f"{key}: independent={expected[key]} delta={observed[key]}")
    return observed


class TransactionalM1Tests(unittest.TestCase):
    def test_motomix_initial_counters_match_independent_shadow(self):
        project = json.loads((ROOT / "benchmarks/moto/motomix-autorouted.json").read_text())
        original = copy.deepcopy(project)
        state = TransactionalState(project)
        self.assertEqual((state.rows, state.cols), (24, 56))
        self.assertEqual(state.excess_gap_occupancy, 95)
        self.assertEqual(state.stacked_gaps, 51)
        self.assertEqual(state.max_stack_depth, 7)
        shadow(state)
        self.assertEqual(project, original)

    def test_jumper_move_and_rollback_restore_exact_hash_and_counters(self):
        state = TransactionalState(tiny())
        before = state.fingerprint()
        original_metrics = shadow(state)
        tx = state.transaction()
        tx.move_wire("J1", (0, 7), (5, 7))
        self.assertNotEqual(state.fingerprint(), before)
        self.assertTrue(tx.requires_full_reroute)
        self.assertIn((7, 1), tx.dirty_gaps)
        shadow(state)
        tx.rollback()
        self.assertEqual(state.fingerprint(), before)
        self.assertEqual(state.metrics(), original_metrics)
        shadow(state)

    def test_component_shift_journals_pads_and_rollback_restores(self):
        state = TransactionalState(tiny())
        original = state.fingerprint()
        tx = state.transaction()
        tx.move_component("B", 5, 3)
        self.assertIn("M", tx.dirty_net_ids)
        self.assertIn((3, 1), tx.dirty_holes)
        self.assertIn((5, 3), tx.dirty_holes)
        shadow(state)
        tx.rollback()
        self.assertEqual(state.fingerprint(), original)
        shadow(state)

    def test_multiple_wire_and_component_edits_reverse_in_exact_order(self):
        state = TransactionalState(tiny())
        baseline = state.fingerprint()
        tx = state.transaction()
        tx.move_wire("J1", (0, 6), (6, 6))
        tx.move_component("B", 5, 2)
        tx.move_wire("J2", (1, 6), (7, 6))
        tx.move_component("B", 2, 2)
        shadow(state)
        tx.rollback()
        self.assertEqual(state.fingerprint(), baseline)
        shadow(state)

    def test_commit_persists_and_context_rolls_back_if_no_commit(self):
        state = TransactionalState(tiny())
        before = state.fingerprint()
        with state.transaction() as tx:
            tx.move_wire("J1", (0, 6), (5, 6))
            tx.commit()
        after = state.fingerprint()
        self.assertNotEqual(after, before)
        with state.transaction() as tx:
            tx.move_wire("J1", (0, 7), (5, 7))
        self.assertEqual(state.fingerprint(), after)
        shadow(state)

    def test_context_exception_automatically_rolls_back(self):
        state = TransactionalState(tiny())
        before = state.fingerprint()
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with state.transaction() as tx:
                tx.move_component("B", 4, 4)
                raise RuntimeError("abort")
        self.assertEqual(state.fingerprint(), before)
        shadow(state)

    def test_nested_or_reused_transaction_not_allowed(self):
        state = TransactionalState(tiny())
        tx = state.transaction()
        with self.assertRaises(RuntimeError):
            state.transaction()
        tx.commit()
        with self.assertRaises(RuntimeError):
            tx.move_wire("J1", (0, 2), (5, 2))
        with self.assertRaises(RuntimeError):
            tx.rollback()
        with state.transaction() as tx2:
            tx2.move_wire("J1", (0, 2), (5, 2))
        shadow(state)

    def test_invalid_wire_moves_leave_state_unmodified(self):
        state = TransactionalState(tiny())
        baseline = state.fingerprint()
        tx = state.transaction()
        for a, b in [
            ((0, 0), (2, 1)), ((0, 0), (0, 0)),
            ((0, 10), (2, 10)), ((-1, 0), (1, 0)),
        ]:
            with self.subTest(a=a, b=b):
                with self.assertRaises(ValueError):
                    tx.move_wire("J1", a, b)
                self.assertEqual(state.fingerprint(), baseline)
        tx.rollback()
        shadow(state)

    def test_hard_locked_edge_and_offboard_parts_never_move(self):
        state = TransactionalState(tiny())
        before = state.fingerprint()
        tx = state.transaction()
        for cid in ("LOCK", "EDGE", "OFF"):
            with self.subTest(cid=cid), self.assertRaises(ValueError):
                tx.move_component(cid, 4, 2)
        self.assertEqual(state.fingerprint(), before)
        tx.rollback()

    def test_component_outside_board_and_bad_rotation_are_rejected(self):
        state = TransactionalState(tiny())
        before = state.fingerprint()
        with state.transaction() as tx:
            with self.assertRaises(ValueError):
                tx.move_component("B", 8, 1)
            with self.assertRaises(ValueError):
                tx.move_component("B", 0, 0, rotation=45)
            self.assertEqual(state.fingerprint(), before)

    def test_component_move_cannot_place_different_nets_in_same_hole(self):
        state = TransactionalState(tiny())
        before = state.fingerprint()
        tx = state.transaction()
        with self.assertRaises(ValueError):
            tx.move_component("B", 0, 0)  # A.1 and B.1 are different nets
        self.assertEqual(state.fingerprint(), before)
        tx.rollback()
        shadow(state)

    def test_flexible_part_footprint_moves_with_explicit_end(self):
        data = tiny()
        data["components"].append({
            "id": "R1", "defId": "def-resistor",
            "boardPos": {"row": 1, "col": 7},
            "flexibleEndPos": {"row": 4, "col": 7},
        })
        state = TransactionalState(data)
        with state.transaction() as tx:
            tx.move_component("R1", 2, 8)
            part = next(x for x in state.snapshot()["components"] if x["id"] == "R1")
            self.assertEqual(part["flexibleEndPos"], {"row": 5, "col": 8})
            with self.assertRaises(ValueError):
                tx.move_component("R1", 2, 8, rotation=90)
            tx.commit()
        shadow(state)

    def test_wire_move_incrementally_changes_hole_collision_metrics(self):
        data = tiny()
        data["components"].append({
            "id": "PIN", "defId": "single",
            "boardPos": {"row": 3, "col": 4},
        })
        state = TransactionalState(data)
        self.assertGreater(state.intermediate_pad_holes, 0)
        before = shadow(state)
        with state.transaction() as tx:
            tx.move_wire("J1", (0, 6), (5, 6))
            shadow(state)
            tx.rollback()
        self.assertEqual(state.metrics(), before)

    def test_deterministic_mutation_stress_5000_operations_zero_shadow_drift(self):
        rng = random.Random(1337)
        state = TransactionalState(tiny())
        baseline = state.fingerprint()
        for index in range(5000):
            with state.transaction() as tx:
                if rng.randrange(3) == 0:
                    r = rng.randrange(8)
                    c = rng.randrange(10)
                    try:
                        tx.move_component("B", r, c)
                    except ValueError:
                        # Hard terminal conflicts remain rejected search proposals.
                        pass
                else:
                    a, b = sorted(rng.sample(range(8), 2))
                    col = rng.randrange(10)
                    tx.move_wire(rng.choice(("J1", "J2")),
                                 (a, col), (b, col))
                if index % 3 == 0:
                    tx.commit()
            if index % 10 == 0:
                shadow(state)
        shadow(state)
        self.assertNotEqual(state.fingerprint(), baseline)

    def test_readonly_project_snapshot_cannot_mutate_live_state(self):
        state = TransactionalState(tiny())
        original = state.fingerprint()
        altered = state.snapshot()
        altered["board"]["wires"].clear()
        altered["components"][0]["boardPos"]["row"] = 7
        self.assertEqual(state.fingerprint(), original)
        shadow(state)


if __name__ == "__main__":
    unittest.main()
