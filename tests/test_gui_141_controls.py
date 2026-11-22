"""Headless GUI regressions for Route-Mate 1.41 controls and progress."""
from __future__ import annotations

import importlib.util
import os
import unittest
from time import perf_counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HAS_QT = importlib.util.find_spec("PySide6") is not None

if HAS_QT:
    from PySide6.QtWidgets import QApplication, QPushButton
    from gui.main import BoardView, RouteMateWindow, SpacingDialog

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" '
       'height="100"><rect width="200" height="100"/></svg>')


@unittest.skipUnless(HAS_QT, "PySide6 is unavailable")
class Gui141ControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_spacing_dialog_has_three_supported_modes(self):
        dialog = SpacingDialog(selected=2)
        try:
            self.assertEqual(dialog.value(), 2)
            self.assertEqual(dialog.choice.count(), 3)
            for index in (0, 1, 2):
                dialog.choice.setCurrentIndex(index)
                self.assertEqual(dialog.value(), index)
        finally:
            dialog.close()

    def test_svg_reuse_and_no_zoom_buttons(self):
        window = RouteMateWindow()
        try:
            view = window.top_view
            view.show_svg(SVG)
            previous = view._renderer
            view.show_svg(SVG)
            self.assertIs(view._renderer, previous)
            labels = [b.text() for b in window.findChildren(QPushButton)]
            self.assertIn("Fit", labels)
            self.assertNotIn("+", labels)
            self.assertNotIn("−", labels)
        finally:
            window.close()

    def test_probe_selects_four_and_parallel_progress_shows_candidate_count(self):
        window = RouteMateWindow()
        try:
            window._speed_probe_completed({
                "recommended_workers": 4, "logical_cpus": 4,
                "timings": {1: 5.0, 2: 3.0, 3: 2.0, 4: 1.5},
            })
            self.assertEqual(window._recommended_workers, 4)
            window._solve_started = perf_counter() - 4.0
            window._solve_attempted({
                "mode": "parallel", "worker": 2, "workers": 4,
                "completed": 6, "budget": 24, "seconds": 0.7,
                "solutions_found": 1,
                "last": {"placement": "PLACED", "routing": "ROUTED"},
            })
            self.assertEqual(window.solve_progress.value(), 6)
            self.assertIn("1 / 2", window.solve_activity.text())
            self.assertIn("Estimated remaining:", window.solve_eta.text())
            self.assertIn("4 CPU processes", window.statusBar().currentMessage())
        finally:
            window._solve_started = None
            window.close()


if __name__ == "__main__":
    unittest.main()
