"""Headless Qt smoke test of the real GUI solve-and-display handoff.

Runs only if PySide6 is installed. The production renderer call is mocked
because these tests verify Qt plumbing, not the separate Node SVG renderer.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import time
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
