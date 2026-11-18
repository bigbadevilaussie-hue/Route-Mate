"""Route-Mate desktop GUI: collect, sanity-check, render, then gather PRE-SOLVE locks."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

GUI_VERSION = "1.05"
CODE_VERSION = "1.05"

from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QAction, QBrush, QColor, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QComboBox,
    QSpinBox, QSplitter, QTabWidget, QToolBar, QVBoxLayout, QWidget,
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
        self.rows_mode = self._mode(board.get("wantedRowsMode", "fixed"))
        self.cols_mode = self._mode(board.get("wantedColsMode", "fixed"))
        form.addRow("Actual physical rows:", self.actual_rows)
        form.addRow("Actual physical columns:", self.actual_cols)
        rows_box = QWidget()
        rows_layout = QHBoxLayout(rows_box)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.addWidget(self.preferred_rows)
        rows_layout.addWidget(self.rows_mode)
        cols_box = QWidget()
        cols_layout = QHBoxLayout(cols_box)
        cols_layout.setContentsMargins(0, 0, 0, 0)
        cols_layout.addWidget(self.preferred_cols)
        cols_layout.addWidget(self.cols_mode)
        form.addRow("Preferred rows:", rows_box)
        form.addRow("Preferred columns:", cols_box)
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

    @staticmethod
    def _mode(value):
        widget = QComboBox()
        widget.addItem("Fixed", "fixed")
        widget.addItem("Max", "max")
        index = widget.findData(value if value in ("fixed", "max") else "fixed")
        widget.setCurrentIndex(max(0, index))
        return widget

    def values(self):
        return {
            "actualRows": self.actual_rows.value(),
            "actualCols": self.actual_cols.value(),
            "wantedRows": self.preferred_rows.value(),
            "wantedCols": self.preferred_cols.value(),
            "wantedRowsMode": self.rows_mode.currentData(),
            "wantedColsMode": self.cols_mode.currentData(),
        }


class LockDialog(QDialog):
    """Collect PRE-SOLVE constraints for one already-placed component."""
    def __init__(self, component: dict[str, Any], index: int, total: int, parent=None):
        super().__init__(parent)
        label = str(component.get("label") or component.get("name") or component.get("id"))
        self.setWindowTitle(f"PRE-SOLVE constraints ({index}/{total})")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Component: {label}"))
        self.locked = QRadioButton("Locked — keep on board")
        self.unlocked = QRadioButton("Unlocked — remove from board")
        self.edge = QCheckBox("Edge constrained")
        self.slide = QCheckBox("May slide along edge")
        # Locked/unlocked are mutually exclusive; edge and slide remain independent.
        is_locked = bool(component.get("locked", False))
        self.locked.setChecked(is_locked)
        self.unlocked.setChecked(not is_locked)
        self.edge.setChecked(False)
        self.slide.setChecked(False)
        self.locked.toggled.connect(self._update_constraint_controls)
        self.unlocked.toggled.connect(self._update_constraint_controls)
        layout.addWidget(self.locked)
        layout.addWidget(self.unlocked)
        layout.addWidget(self.edge)
        layout.addWidget(self.slide)
        layout.addWidget(QLabel("Unlocked components are excluded from the refreshed board preview."))
        self._update_constraint_controls()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_constraint_controls(self):
        keep = self.locked.isChecked()
        self.edge.setEnabled(keep)
        self.slide.setEnabled(keep)

    def values(self):
        return {"locked": self.locked.isChecked(),
                "edge": self.edge.isChecked() if self.locked.isChecked() else False,
                "slide": self.slide.isChecked() if self.locked.isChecked() else False,
                "remove": self.unlocked.isChecked()}


class BoardView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing |
                            QPainter.RenderHint.TextAntialiasing |
                            QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#f2f2f2")))
        # Fixed view: no mouse-wheel zoom, panning, or visible scrollbars.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._renderer = None

    def fit_board(self):
        self.resetTransform()
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.scene() and not self.scene().sceneRect().isEmpty():
            self.fit_board()

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
        # Give the 24 x 56 board most of the window and keep it fully fitted.
        self.resize(1600, 950)
        self.setMinimumSize(1000, 650)
        self.project: dict[str, Any] | None = None
        self.project_path: Path | None = None
        self.presolve_constraints: dict[str, dict[str, bool]] = {}

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        load_action = QAction("Load JSON", self)
        load_action.triggered.connect(self.load_json)
        toolbar.addAction(load_action)
        export_top_action = QAction("Export top SVG", self)
        export_top_action.triggered.connect(lambda: self.export_svg("top"))
        toolbar.addAction(export_top_action)
        export_copper_action = QAction("Export copper SVG", self)
        export_copper_action.triggered.connect(lambda: self.export_svg("copper"))
        toolbar.addAction(export_copper_action)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText("Route-Mate running log")
        self.top_view = BoardView()
        self.copper_view = BoardView()
        self.board_tabs = QTabWidget()
        self.board_tabs.addTab(self.top_view, "Component side")
        self.board_tabs.addTab(self.copper_view, "Copper side")
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.log)
        split.addWidget(self.board_tabs)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([320, 1280])
        self.setCentralWidget(split)
        self.statusBar().showMessage("Ready. Load a project JSON to begin.")
        self.log_line(f"Route-Mate GUI v{GUI_VERSION} | Code v{CODE_VERSION}")
        self.log_line("Workflow: collect → sanity checks → dual-side render → tests → PRE-SOLVE locks.")
        self.log_line("PRE-SOLVE itself is not implemented; the GUI stops after collecting lock settings.")

    def log_line(self, message: str):
        self.log.appendPlainText(message)

    def fit_board(self):
        self.board_view.fit_board()

    def _render_component_side(self, project: dict[str, Any]) -> tuple[str, str]:
        """Render the production component-side artwork without exposing copper view."""
        from render.standalone_bridge import render_project

        with tempfile.TemporaryDirectory(prefix="route-mate-render-") as temp:
            temp_dir = Path(temp)
            project_file = temp_dir / "project.json"
            output_dir = temp_dir / "output"
            project_file.write_text(
                json.dumps(project, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            top_svg, _copper_svg, renderer_log = render_project(project_file, output_dir)
        return top_svg, renderer_log

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
                f"Locked={values['locked']} Edge={values['edge']} Slide={values['slide']} "
                f"Remove={values['remove']}"
            )
        removed = []
        for component in placed:
            values = self.presolve_constraints.get(str(component.get("id")), {})
            if values.get("remove"):
                component["boardExcluded"] = True
                component.pop("boardPos", None)
                component.pop("flexibleEndPos", None)
                removed.append(str(component.get("label") or component.get("id")))
        svg, renderer_log = self._render_component_side(self.project)
        self.board_view.show_svg(svg)
        self.log_line("[RENDER] Production component-side SVG refreshed.")
        if renderer_log:
            self.log_line("[RENDER] " + renderer_log)
        self.log_line(f"[RENDER] Board refreshed after lock collection; removed {len(removed)} unlocked parts.")
        for label in removed:
            self.log_line(f"[RENDER] Removed from board: {label}")
        self.log_line("[STOP] Lock settings collected and board refreshed. PRE-SOLVE is not implemented; stopped here.")
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
            for warning in project.pop("_collectWarnings", []):
                self.log_line("[COLLECT][WARN] " + warning)
            board_dialog = BoardSizeDialog(project.get("board", {}), self)
            if board_dialog.exec() != QDialog.DialogCode.Accepted:
                self.log_line("[COLLECT] Board dimensions cancelled; project not advanced.")
                return
            dimensions = board_dialog.values()
            if dimensions["wantedRowsMode"] == "fixed" and dimensions["wantedRows"] > dimensions["actualRows"]:
                raise ValueError("Fixed preferred rows cannot exceed actual physical rows.")
            if dimensions["wantedColsMode"] == "fixed" and dimensions["wantedCols"] > dimensions["actualCols"]:
                raise ValueError("Fixed preferred columns cannot exceed actual physical columns.")
            project["board"].update(dimensions)
            project["board"]["rows"] = dimensions["actualRows"]
            project["board"]["cols"] = dimensions["actualCols"]
            self.log_line(
                f"[COLLECT] Actual board {dimensions['actualRows']} x {dimensions['actualCols']}; "
                f"preferred rows {dimensions['wantedRows']} ({dimensions['wantedRowsMode']}), "
                f"columns {dimensions['wantedCols']} ({dimensions['wantedColsMode']})."
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

            # Use the production renderer for its complete board artwork.
            # The copper SVG is generated by the bridge but deliberately not displayed.
            svg, renderer_log = self._render_component_side(project)
            self.board_view.show_svg(svg)
            self.log_line("[RENDER] Production component-side SVG rendered. Copper side is disabled.")
            if renderer_log:
                self.log_line("[RENDER] " + renderer_log)

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
