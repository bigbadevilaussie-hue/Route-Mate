"""Route-Mate desktop GUI: collect, sanity-check, render, then gather PRE-SOLVE locks."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

GUI_VERSION = "1.01"
CODE_VERSION = "1.02"

from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QAction, QBrush, QColor, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QSplitter, QToolBar, QVBoxLayout, QWidget,
)


class BoardSizeDialog(QDialog):
    """Collect physical and preferred dimensions without changing the source file."""
    def __init__(self, board: dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Board dimensions")
        self.setModal(True)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.actual_rows = self._spin(board.get("actualRows", board.get("rows", 24)))
        self.actual_cols = self._spin(board.get("actualCols", board.get("cols", 56)))
        self.preferred_rows = self._spin(board.get("wantedRows", board.get("rows", 24)))
        self.preferred_cols = self._spin(board.get("wantedCols", board.get("cols", 56)))
        form.addRow("Actual physical rows:", self.actual_rows)
        form.addRow("Actual physical columns:", self.actual_cols)
        form.addRow("Preferred rows:", self.preferred_rows)
        form.addRow("Preferred columns:", self.preferred_cols)
        layout.addLayout(form)
        layout.addWidget(QLabel("Preferred dimensions are separate from the physical board limits."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _spin(value):
        widget = QSpinBox()
        widget.setRange(1, 500)
        try:
            widget.setValue(int(value))
        except (TypeError, ValueError):
            widget.setValue(24)
        return widget

    def values(self):
        return {
            "actualRows": self.actual_rows.value(),
            "actualCols": self.actual_cols.value(),
            "wantedRows": self.preferred_rows.value(),
            "wantedCols": self.preferred_cols.value(),
        }


class LockDialog(QDialog):
    """Collect PRE-SOLVE constraints for one already-placed component."""
    def __init__(self, component: dict[str, Any], index: int, total: int, parent=None):
        super().__init__(parent)
        label = str(component.get("label") or component.get("name") or component.get("id"))
        self.setWindowTitle(f"PRE-SOLVE constraints ({index}/{total})")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Component: {label}"))
        self.locked = QCheckBox("Locked")
        self.edge = QCheckBox("Edge constrained")
        self.slide = QCheckBox("May slide along edge")
        # Existing explicit locked state is shown; edge/slide remain independent.
        self.locked.setChecked(bool(component.get("locked", False)))
        self.edge.setChecked(bool(component.get("edge", False)))
        self.slide.setChecked(bool(component.get("slide", False)))
        layout.addWidget(self.locked)
        layout.addWidget(self.edge)
        layout.addWidget(self.slide)
        layout.addWidget(QLabel("These answers are held in this GUI session for PRE-SOLVE."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Next | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {"locked": self.locked.isChecked(),
                "edge": self.edge.isChecked(),
                "slide": self.slide.isChecked()}


class BoardView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing |
                            QPainter.RenderHint.TextAntialiasing |
                            QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#f2f2f2")))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._renderer = None

    def fit_board(self):
        self.resetTransform()
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        self.scale(1.25 if event.angleDelta().y() > 0 else 0.8,
                   1.25 if event.angleDelta().y() > 0 else 0.8)
        event.accept()

    def show_svg(self, svg: str):
        import re
        svg = re.sub(
            r"(<svg\b[^>]*>)",
            r"\1<style>text{fill:#000000!important;stroke:#f3e5bf!important;"
            r"stroke-width:0.55px!important;paint-order:stroke fill!important;"
            r"stroke-linejoin:round!important;font-weight:700!important;opacity:1!important;}"
            r"tspan{fill:#000000!important;stroke:#f3e5bf!important;"
            r"stroke-width:0.55px!important;font-weight:700!important;opacity:1!important;}</style>",
            svg, count=1,
        )
        scene = self.scene()
        scene.clear()
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if not renderer.isValid():
            raise ValueError("Component-side renderer produced invalid SVG.")
        item = QGraphicsSvgItem()
        item.setSharedRenderer(renderer)
        scene.addItem(item)
        self._renderer = renderer
        scene.setSceneRect(item.boundingRect())
        self.fit_board()


class RouteMateWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Route-Mate GUI v{GUI_VERSION} (Code v{CODE_VERSION})")
        # 24 x 56 board proportions, with a useful log pane.
        self.resize(1420, 900)
        self.setMinimumSize(1100, 720)
        self.project: dict[str, Any] | None = None
        self.project_path: Path | None = None
        self.presolve_constraints: dict[str, dict[str, bool]] = {}

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        load_action = QAction("Load JSON", self)
        load_action.triggered.connect(self.load_json)
        toolbar.addAction(load_action)
        fit_action = QAction("Fit board", self)
        fit_action.triggered.connect(self.fit_board)
        toolbar.addAction(fit_action)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText("Route-Mate running log")
        self.board_view = BoardView()
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.log)
        split.addWidget(self.board_view)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([360, 1060])
        self.setCentralWidget(split)
        self.statusBar().showMessage("Ready. Load a project JSON to begin.")
        self.log_line(f"Route-Mate GUI v{GUI_VERSION} | Code v{CODE_VERSION}")
        self.log_line("Workflow: collect → sanity checks → component-side render → tests → PRE-SOLVE locks.")
        self.log_line("PRE-SOLVE itself is not implemented; the GUI stops after collecting lock settings.")

    def log_line(self, message: str):
        self.log.appendPlainText(message)

    def fit_board(self):
        self.board_view.fit_board()

    def _run_tests(self):
        self.log_line("[TEST] Running repository unittest suite...")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=Path(__file__).resolve().parent.parent,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        for line in result.stdout.splitlines():
            self.log_line("[TEST] " + line)
        self.log_line(f"[TEST] Exit code: {result.returncode}")
        return result.returncode == 0

    def _ask_lock_settings(self, placed: list[dict[str, Any]]):
        self.presolve_constraints = {}
        if not placed:
            self.log_line("[LOCKS] No components have saved board positions.")
            return
        self.log_line(f"[LOCKS] Asking Locked / Edge / Slide for {len(placed)} placed components.")
        for index, component in enumerate(placed, 1):
            dialog = LockDialog(component, index, len(placed), self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.log_line("[LOCKS] Cancelled. PRE-SOLVE hand-off not completed.")
                return
            self.presolve_constraints[str(component.get("id"))] = dialog.values()
            values = self.presolve_constraints[str(component.get("id"))]
            self.log_line(
                f"[LOCKS] {component.get('label') or component.get('id')}: "
                f"Locked={values['locked']} Edge={values['edge']} Slide={values['slide']}"
            )
        self.log_line("[STOP] Lock settings collected. PRE-SOLVE is not implemented; stopped here.")
        self.statusBar().showMessage("Ready for PRE-SOLVE implementation — workflow stopped.")

    def load_json(self):
        app_dir = Path(__file__).resolve().parent.parent
        start_dir = self.project_path.parent if self.project_path else app_dir
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load Route-Mate project", str(start_dir),
            "Project JSON (*.json);;All files (*)",
        )
        if not filename:
            return
        path = Path(filename)
        self.log_line("")
        self.log_line(f"--- LOAD PROJECT: {path.name} ---")
        try:
            source = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(source, dict):
                raise ValueError("Project JSON root must be an object.")

            # Collector validation and explicit board-size collection.
            from collect import validate_project
            project = validate_project(copy.deepcopy(source))
            board_dialog = BoardSizeDialog(project.get("board", {}), self)
            if board_dialog.exec() != QDialog.DialogCode.Accepted:
                self.log_line("[COLLECT] Board dimensions cancelled; project not advanced.")
                return
            dimensions = board_dialog.values()
            if dimensions["wantedRows"] > dimensions["actualRows"]:
                raise ValueError("Preferred rows cannot exceed actual physical rows.")
            if dimensions["wantedCols"] > dimensions["actualCols"]:
                raise ValueError("Preferred columns cannot exceed actual physical columns.")
            project["board"].update(dimensions)
            project["board"]["rows"] = dimensions["actualRows"]
            project["board"]["cols"] = dimensions["actualCols"]
            project["board"]["wantedRowsMode"] = "fixed"
            project["board"]["wantedColsMode"] = "fixed"
            self.log_line(
                f"[COLLECT] Actual board {dimensions['actualRows']} x {dimensions['actualCols']}; "
                f"preferred {dimensions['wantedRows']} x {dimensions['wantedCols']} (fixed)."
            )
            self.log_line(
                f"[COLLECT] Components={len(project['components'])}, Nets={len(project['nets'])}, "
                f"Assignments={len(project['netAssignments'])}"
            )

            from prepare.sanity.electrical import run_electrical_sanity
            sanity = run_electrical_sanity(project)
            self.log_line(f"[SANITY] Electrical integrity: {sanity['status']}")
            for error in sanity["errors"]:
                self.log_line("[SANITY][ERROR] " + error)
            for warning in sanity["warnings"]:
                self.log_line("[SANITY][WARN] " + warning)
            if sanity["status"] != "PASS":
                QMessageBox.warning(self, "Collector sanity checks failed",
                                    "The project failed electrical sanity checks. See the log.")
                return

            # Render only the component side using the native Route-Mate renderer.
            from render import render_front
            svg = render_front(project)
            self.board_view.show_svg(svg)
            self.log_line("[RENDER] Component side rendered. Copper side is disabled.")

            tests_passed = self._run_tests()
            if not tests_passed:
                QMessageBox.warning(self, "Tests failed",
                                    "Repository tests failed. See the log; lock questions were not started.")
                return

            components = project["components"]
            placed = [c for c in components
                      if c.get("boardPos") is not None and not c.get("offBoard")
                      and not c.get("boardExcluded")]
            on_board = [c for c in components
                        if not c.get("offBoard") and not c.get("boardExcluded")]
            self.log_line(f"[PLACEMENT] On-board components={len(on_board)}; already placed={len(placed)}.")
            if placed:
                for component in placed:
                    self.log_line(
                        f"[PLACEMENT] {component.get('label') or component.get('id')}: "
                        f"boardPos={component.get('boardPos')}"
                    )
            else:
                self.log_line("[PLACEMENT] No parts currently have boardPos placements.")

            self.project = project
            self.project_path = path
            self._ask_lock_settings(placed)
            if not placed:
                self.log_line("[STOP] No placed components to ask lock settings for. PRE-SOLVE is not implemented.")
                self.statusBar().showMessage("Loaded and checked — stopped before PRE-SOLVE.")
        except Exception as exc:
            self.log_line(f"[ERROR] {type(exc).__name__}: {exc}")
            self.log_line(traceback.format_exc())
            QMessageBox.critical(self, "Could not load project", str(exc))

    def closeEvent(self, event):
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Route-Mate")
    window = RouteMateWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
