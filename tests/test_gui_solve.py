"""Headless Qt smoke test of the real GUI solve-and-display handoff.

Runs only if PySide6 is installed. The production renderer call is mocked
because these tests verify Qt plumbing, not the separate Node SVG renderer.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import tempfile
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HAS_QT = importlib.util.find_spec("PySide6") is not None

if HAS_QT:
    from PySide6.QtWidgets import QApplication
    from gui.main import RouteMateWindow

ROOT = Path(__file__).resolve().parent.parent
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="160" viewBox="0 0 240 160"><rect width="240" height="160" fill="#eee"/></svg>'


@unittest.skipUnless(HAS_QT, "PySide6 not available in this environment")
class GuiSolveSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_gui_uses_collector_geometry_profile_and_records_pipeline_handoff(self):
        """Shared assumptions must reach GUI pipeline without entering solver input."""
        from collector_geometry import build_assumed_geometry
        fixture = json.loads((ROOT / "benchmarks/audio/audio10wires38cuts.json").read_text())
        original = copy.deepcopy(fixture)
        stage = SimpleNamespace(report={}, options={})
        window = RouteMateWindow()
        try:
            built = window._record_assumed_geometry(fixture, stage=stage)
            self.assertEqual(built, build_assumed_geometry(fixture))
            self.assertEqual(stage.report["assumed_geometry"], built)
            self.assertEqual(stage.options["geometry_status"], "ASSUMED_UNVERIFIED")
            self.assertEqual(stage.options["geometry_preset"], "standard-through-hole-v2")
            parts = {p["label"]: p for p in built["components"]}
            self.assertEqual(parts["C4"]["profile"], "electrolytic_small")
            self.assertEqual(parts["C7"]["profile"], "electrolytic_small")
            self.assertEqual(parts["C4"]["body_solids"][0]["radius_mm"], 2.5)
            self.assertNotIn("physicalClearance", fixture)
            self.assertEqual(fixture, original)
        finally:
            window.close()

    def test_new_project_picker_uses_user_folder_not_app_bundle(self):
        from gui.main import default_project_directory
        window = RouteMateWindow()
        try:
            with patch("gui.main.QFileDialog.getOpenFileName", return_value=("", "")) as pick:
                window.load_json()
                self.assertEqual(pick.call_args.args[2], str(default_project_directory()))
            with patch("gui.main.QFileDialog.getOpenFileName", return_value=("", "")) as pick:
                window.render_json()
                self.assertEqual(pick.call_args.args[2], str(default_project_directory()))
        finally:
            window.close()

    def test_workflow_reaches_100_only_after_real_electrical_check(self):
        window = RouteMateWindow()
        try:
            stages = {}
            for name in (
                "IN.project_import", "PREPARE.electrical", "PREPARE.presolve",
                "PREPARE.constraints", "SOLVE.quick_fit",
                "SOLVE.route", "VERIFY.independent",
            ):
                report = {"status": "PASS"} if name in (
                    "PREPARE.electrical", "VERIFY.independent") else {}
                stages[name] = SimpleNamespace(stage=name, status="completed", report=report)
            window.pipeline_run = SimpleNamespace(context=SimpleNamespace(stages=stages))
            window._refresh_checklist()
            self.assertEqual(window.checklist.percent.text(), "100%")
            self.assertEqual(window.checklist.bar.value(), 7)
            stages["PREPARE.electrical"].report["status"] = "FAIL"
            window._refresh_checklist()
            self.assertEqual(window.checklist.percent.text(), "86%")
            self.assertEqual(window.checklist.rows["SANITY"].text(), "✕")
        finally:
            window.close()

    def test_review_locks_from_solved_layout_freezes_selected_components(self):
        """Review Locks must use displayed positions and discard old routing."""
        source = {
            "board": {"rows": 6, "cols": 10, "cuts": [], "wires": []},
            "componentDefs": [{
                "id": "one", "width": 1, "height": 1,
                "pins": [{"id": "1", "offsetRow": 0, "offsetCol": 0}],
                "bodyCells": [],
            }],
            "components": [
                {"id": "KEEP", "label": "Keep", "defId": "one",
                 "boardPos": {"row": 1, "col": 2}},
                {"id": "MOVE", "label": "Move", "defId": "one",
                 "boardPos": {"row": 3, "col": 6}},
            ],
            "nets": [], "netAssignments": [],
        }
        current = copy.deepcopy(source)
        current["board"]["wires"] = [{
            "id": "OLD", "from": {"row": 0, "col": 0},
            "to": {"row": 2, "col": 0},
        }]
        original_unplaced = copy.deepcopy(source)
        for part in original_unplaced["components"]:
            part.pop("boardPos")
        window = RouteMateWindow()
        window.project = current
        window._quick_source = original_unplaced
        window._solved_verified = True
        accepted = {
            "KEEP": {"locked": True, "edge": False, "slide": False, "reposition": False},
            "MOVE": {"locked": False, "edge": False, "slide": False, "reposition": True},
        }
        try:
            with patch("gui.main.LockDialog") as dialog:
                dialog.return_value.exec.return_value = 1
                dialog.return_value.values.side_effect = [accepted["KEEP"], accepted["MOVE"]]
                with patch.object(window, "_render_component_side", return_value=(SVG, "")) as render:
                    with patch.object(window, "solve_board") as solve:
                        window.review_locks()
            solve.assert_called_once()
            self.assertEqual(dialog.call_count, 2)
            highlighted = [call.kwargs.get("highlight_component_id")
                           for call in render.call_args_list if "highlight_component_id" in call.kwargs]
            self.assertEqual(highlighted, ["KEEP", "MOVE"])
            fixed = {c["id"]: c for c in window._quick_source["components"]}
            self.assertEqual(fixed["KEEP"]["boardPos"], {"row": 1, "col": 2})
            self.assertTrue(fixed["KEEP"]["locked"])
            self.assertNotIn("boardPos", fixed["MOVE"])
            self.assertEqual(window._quick_source["board"]["wires"], [])
            self.assertEqual(window._quick_source["board"]["cuts"], [])
            self.assertEqual(current["board"]["wires"][0]["id"], "OLD")
        finally:
            window.close()

    def test_per_component_review_preserves_edge_slide_choice(self):
        project = {
            "board": {"rows": 6, "cols": 10, "cuts": [], "wires": []},
            "components": [
                {"id": "EDGE", "label": "Edge", "boardPos": {"row": 0, "col": 3}},
            ],
            "nets": [], "netAssignments": [],
        }
        window = RouteMateWindow()
        window.project = project
        try:
            choice = {"locked": True, "edge": True, "slide": True, "reposition": False}
            with patch("gui.main.LockDialog") as dialog:
                dialog.return_value.exec.return_value = 1
                dialog.return_value.values.return_value = choice
                with patch.object(window, "_render_component_side", return_value=(SVG, "")):
                    with patch.object(window, "solve_board") as solve:
                        window._ask_lock_settings(project["components"])
            solve.assert_called_once()
            part = window._quick_source["components"][0]
            self.assertEqual(part["boardPos"], {"row": 0, "col": 3})
            self.assertTrue(part["locked"])
            self.assertTrue(part["edge"])
            self.assertTrue(part["slide"])
            self.assertEqual(window.presolve_constraints["EDGE"], choice)
        finally:
            window.close()

    def test_repeat_quick_solve_uses_locked_input_not_old_routed_output(self):
        project = json.loads((ROOT / "benchmarks/moto/moto.json").read_text())
        locked = next(c for c in project["components"]
                      if c.get("defId") == "def-connector-2")
        locked["boardPos"] = {"row": 0, "col": 1}
        locked["locked"] = True
        old = copy.deepcopy(project)
        old["board"]["wires"] = [{
            "id": "OLD", "from": {"row": 2, "col": 0},
            "to": {"row": 4, "col": 0},
        }]
        calls = []
        class Event:
            def connect(self, callback):
                pass
        class Worker:
            def __init__(self, source, parent=None):
                calls.append(copy.deepcopy(source))
                self.completed = Event()
                self.crashed = Event()
                self.attempted = Event()
                self.finished = Event()
            def isRunning(self):
                return True
            def start(self):
                pass
        window = RouteMateWindow()
        window.project = old
        window._quick_source = copy.deepcopy(project)
        window.pipeline_run = None
        try:
            with patch("gui.main.SolveWorker", Worker):
                window.solve_board()
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["board"]["wires"], [])
            self.assertEqual(calls[0]["board"]["cuts"], [])
            preserved = next(c for c in calls[0]["components"] if c["id"] == locked["id"])
            self.assertEqual(preserved["boardPos"], locked["boardPos"])
            self.assertTrue(preserved["locked"])
            self.assertIn("Quick Solve", window.board_result_label.text())
        finally:
            window._solver_worker = None
            window.close()

    def test_saved_wr_gui_renders_using_persisted_2_5d_sidecar(self):
        """Both reference layouts exercise real GUI preview + independent 2.5D."""
        from geometry_sidecar import sidecar_path
        for filename in ("benchmarks/audio/audio10wires38cuts.json",
                         "benchmarks/moto/moto14wires30cuts.json"):
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as temp:
                    source = ROOT / filename
                    path = Path(temp) / source.name
                    path.write_bytes(source.read_bytes())
                    window = RouteMateWindow()
                    try:
                        with patch("gui.main.QFileDialog.getOpenFileName",
                                   return_value=(str(path), "Project JSON (*.json)")):
                            with patch("render.standalone_bridge.render_project_data",
                                       return_value=(SVG, SVG, "test")):
                                with patch("gui.main.QMessageBox.warning") as warning:
                                    window.render_json()
                        self.assertFalse(warning.called, "Valid assumed WR should not show legacy warning popup")
                        log = window.log.toPlainText()
                        self.assertIn("[2.5D][ASSUMED_CLEARANCE_PASS]", log)
                        self.assertIn("[RENDER JSON][ELECTRICAL][PASS]", log)
                        self.assertIn("[RENDER JSON][ASSUMED_PASS]", log)
                        self.assertIn("source=" + str(sidecar_path(path)), log)
                        self.assertTrue(sidecar_path(path).exists())
                        sidecar = json.loads(sidecar_path(path).read_text())
                        self.assertEqual(sidecar["geometry"]["preset"],
                                         "standard-through-hole-v2")
                        self.assertNotIn("physicalClearance", window.project)
                        self.assertFalse(window._solved_verified)
                        self.assertFalse(window.save_solved_action.isEnabled())
                    finally:
                        window.close()

    def test_old_obstructed_saved_board_is_flagged_unsafe(self):
        """Render JSON must not silently endorse the old cap-crossing board."""
        layout = {
            "board": {
                "rows": 12, "cols": 25, "cuts": [],
                "wires": [{
                    "id": "W-OLD",
                    "from": {"row": 2, "col": 12},
                    "to": {"row": 5, "col": 12},
                }],
            },
            "componentDefs": [],
            "components": [{
                "id": "C1", "label": "C1", "defId": "def-cap-polarized",
                "boardPos": {"row": 2, "col": 12}, "rotation": 0,
            }],
            "nets": [], "netAssignments": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old-moto-unsafe.json"
            path.write_text(json.dumps(layout))
            window = RouteMateWindow()
            try:
                with patch("gui.main.QFileDialog.getOpenFileName",
                           return_value=(str(path), "Project JSON (*.json)")):
                    with patch("render.standalone_bridge.render_project_data",
                               return_value=(SVG, SVG, "test")):
                        with patch("gui.main.QMessageBox.warning") as popup:
                            window.render_json()
                self.assertTrue(popup.called)
                self.assertIn("[RENDER JSON][UNSAFE]", window.log.toPlainText())
                self.assertFalse(window.save_solved_action.isEnabled())
            finally:
                window.close()

    def test_artwork_only_overlap_is_unverified_not_proven_unsafe(self):
        layout = {
            "board": {"rows": 12, "cols": 25, "cuts": [], "wires": [{
                "id": "W-ART",
                "from": {"row": 0, "col": 13},
                "to": {"row": 6, "col": 13},
            }]},
            "componentDefs": [],
            "components": [{
                "id": "C1", "label": "C1", "defId": "def-cap-polarized",
                "boardPos": {"row": 2, "col": 12},
            }],
            "nets": [], "netAssignments": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "artwork-only.json"
            path.write_text(json.dumps(layout))
            window = RouteMateWindow()
            try:
                with patch("gui.main.QFileDialog.getOpenFileName",
                           return_value=(str(path), "Project JSON (*.json)")):
                    with patch("render.standalone_bridge.render_project_data",
                               return_value=(SVG, SVG, "test")):
                        with patch("gui.main.QMessageBox.warning") as warning:
                            window.render_json()
                self.assertFalse(warning.called)
                self.assertIn("[RENDER JSON][ARTWORK_ONLY]", window.log.toPlainText())
                self.assertIn("[RENDER JSON][ASSUMED_PASS]", window.log.toPlainText())
                self.assertNotIn("[RENDER JSON][UNSAFE]", window.log.toPlainText())
                self.assertFalse(window.save_solved_action.isEnabled())
            finally:
                window.close()

    def test_attempt_eta_uses_measured_seconds_and_remaining_budget(self):
        window = RouteMateWindow()
        try:
            window._solve_attempted({
                "completed": 1, "budget": 4, "seconds": 2.0,
                "last": {"placement": "PLACED", "routing": "ROUTING_FAILED"},
            })
            self.assertIn("up to ~6s", window.statusBar().currentMessage())
            window._solve_attempted({
                "completed": 2, "budget": 4, "seconds": 4.0,
                "last": {"placement": "PLACED", "routing": "ROUTING_FAILED"},
            })
            self.assertIn("up to ~6s", window.statusBar().currentMessage())
            self.assertIn("[SOLVE][ATTEMPT 2/4]", window.log.toPlainText())
        finally:
            window.close()

    def test_moto_worker_updates_both_board_sides(self):
        window = RouteMateWindow()
        window.project = json.loads((ROOT / "benchmarks/moto/moto.json").read_text(encoding="utf-8"))
        window.project_path = ROOT / "benchmarks/moto/moto.json"
        window.solve_action.setEnabled(True)
        try:
            with patch.object(window, "_render_component_side",
                              side_effect=lambda project: (
                                  setattr(window, "_copper_svg", SVG) or SVG,
                                  "headless test renderer",
                              )):
                window.solve_board()
                self.assertFalse(window.solve_action.isEnabled())
                deadline = time.monotonic() + 40
                while window._solver_worker is not None and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.01)
                self.app.processEvents()
            self.assertIsNone(window._solver_worker, "worker failed to finish in 40 seconds")
            self.assertTrue(window._solved_verified, window.log.toPlainText()[-3000:])
            self.assertTrue(window.save_solved_action.isEnabled())
            self.assertTrue(window.solve_action.isEnabled())
            self.assertGreater(len(window.project["board"]["cuts"]), 0)
            self.assertGreater(len(window.project["board"]["wires"]), 0)
            self.assertEqual(window._top_svg, SVG)
            self.assertEqual(window._copper_svg, SVG)
            window._switch_board_side("copper")
            self.assertTrue(window.copper_action.isChecked())
            window._switch_board_side("top")
            self.assertTrue(window.top_action.isChecked())
        finally:
            if window._solver_worker is None:
                window.close()


if __name__ == "__main__":
    unittest.main()
