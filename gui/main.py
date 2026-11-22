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

# Allow `python3 gui/main.py` to import the repository's root-level packages.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_VERSION_FILE = REPO_ROOT / "VERSION"
GUI_VERSION = (_VERSION_FILE.read_text(encoding="utf-8").strip()
               if _VERSION_FILE.is_file() else "1.38")
CODE_VERSION = GUI_VERSION

from PySide6.QtCore import Qt, QByteArray, QPoint, QThread, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFontDatabase, QPainter, QPixmap, QIcon
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QComboBox,
    QSpinBox, QSplitter, QToolBar, QVBoxLayout, QWidget, QProgressBar, QTabWidget, QFrame,
)


def audit_quick_pads(path: Path) -> dict[str, Any]:
    """Check each on-board pin and pad against saved quick.json."""
    from board_geometry import BUILTIN_DEFS, component_geometry, resolve_definition
    from placement_policy import is_off_board_component
    from solve.verify import verify_project

    project = json.loads(path.read_text(encoding="utf-8"))
    electrical = verify_project(project)
    errors = list(electrical["errors"])
    definitions = dict(BUILTIN_DEFS)
    definitions.update({str(d["id"]): d for d in project.get("componentDefs", [])
                        if isinstance(d, dict) and d.get("id")})
    assignments = {(str(a.get("componentId")), str(a.get("pinId")))
                   for a in project.get("netAssignments", []) if isinstance(a, dict)}
    rows, cols = int(project["board"]["rows"]), int(project["board"]["cols"])
    checked = 0
    skipped = 0
    for component in project.get("components", []):
        if not isinstance(component, dict):
            continue
        if is_off_board_component(component):
            label = str(component.get("label") or component.get("id"))
            if component.get("boardExcluded") is True and component.get("offBoard") is not True:
                skipped += 1
                continue
            leads = component.get("leads") or {}
            definition = resolve_definition(component, definitions)
            if not definition:
                errors.append(f"{label}: missing off-board pin definition")
                continue
            for pid in dict.fromkeys(str(p["id"]) for p in definition.get("pins", [])):
                point = leads.get(pid) if isinstance(leads, dict) else None
                if point is None:
                    errors.append(f"{label} pin {pid}: missing physical termination pad")
                    continue
                checked += 1
                row, col = int(point["row"]), int(point["col"])
                if not (0 <= row < rows and 0 <= col < cols):
                    errors.append(f"{label} pin {pid}: pad outside board at ({row}, {col})")
            continue
        label = str(component.get("label") or component.get("id"))
        if not isinstance(component.get("boardPos"), dict):
            continue
        definition = resolve_definition(component, definitions)
        if not definition:
            errors.append(f"{label}: missing footprint definition")
            continue
        try:
            pins, _ = component_geometry(component, definition)
            defined_pins = [p for p in definition.get("pins", []) if isinstance(p, dict)]
            assigned = {pid for cid, pid in assignments if cid == str(component.get("id"))}
            aliases = {str(i): str(p.get("id")) for i, p in enumerate(defined_pins, 1)}
            assigned_physical = {pid if any(str(p.get("id")) == pid for p in defined_pins)
                                 else aliases.get(pid, pid) for pid in assigned}
            for pin in pins:
                checked += 1
                pid = str(pin.get("id"))
                if pid not in assigned_physical:
                    continue  # Unconnected physical pins are allowed.
                row, col = int(pin["row"]), int(pin["col"])
                if not (0 <= row < rows and 0 <= col < cols):
                    errors.append(f"{label} pin {pid}: pad outside board at ({row}, {col})")
        except (TypeError, ValueError, KeyError) as exc:
            errors.append(f"{label}: invalid pad geometry: {exc}")
    return {"status": "FAIL" if errors else "PASS", "checked": checked,
            "off_board_skipped": skipped, "errors": errors,
            "electrical": electrical["counts"]}


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
        self.setMinimumWidth(340)
        if parent is not None:
            # Keep the prompt over the left log pane so the highlighted board
            # remains visible while the user makes the decision.
            self.move(parent.mapToGlobal(QPoint(24, 90)))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Component: {label}"))
        self.locked = QRadioButton("Fixed — keep exact position")
        self.unlocked = QRadioButton("Movable — return to Quick Solve")
        self.edge = QCheckBox("Board-edge constraint")
        self.slide = QCheckBox("May slide along this edge (keep rotation)")
        # Unlocked parts lose their old placement and return to Quick Fit.
        is_locked = bool(component.get("locked", False))
        self.locked.setChecked(is_locked)
        self.unlocked.setChecked(not is_locked)
        self.edge.setChecked(bool(component.get("edge", False)))
        self.slide.setChecked(bool(component.get("slide", False)))
        self.locked.toggled.connect(self._update_constraint_controls)
        self.unlocked.toggled.connect(self._update_constraint_controls)
        self.edge.toggled.connect(self._update_constraint_controls)
        layout.addWidget(self.locked)
        layout.addWidget(self.unlocked)
        layout.addWidget(self.edge)
        layout.addWidget(self.slide)
        hint = QLabel("Fixed = exact position. Edge + Slide = may move only along the same edge.\nMovable = auto-place while keeping all electrical connections.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._update_constraint_controls()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_constraint_controls(self):
        keep = self.locked.isChecked()
        self.edge.setEnabled(keep)
        self.slide.setEnabled(keep and self.edge.isChecked())
        if not (keep and self.edge.isChecked()):
            self.slide.setChecked(False)

    def values(self):
        return {"locked": self.locked.isChecked(),
                "edge": self.edge.isChecked() if self.locked.isChecked() else False,
                "slide": self.slide.isChecked() if self.locked.isChecked() else False,
                "reposition": self.unlocked.isChecked()}


class BoardView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing |
                            QPainter.RenderHint.TextAntialiasing |
                            QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#fafbfd")))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._renderer = None
        self._user_zoomed = False

    def fit_board(self):
        if self.scene().sceneRect().isEmpty():
            return
        self.resetTransform()
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._user_zoomed = False

    def zoom(self, factor: float):
        if self.scene().sceneRect().isEmpty():
            return
        current = self.transform().m11()
        # Bound zoom to avoid vanishing boards or enormous rasterisation.
        if 0.02 <= current * factor <= 12.0:
            self.scale(factor, factor)
            self._user_zoomed = True

    def wheelEvent(self, event):
        amount = event.angleDelta().y()
        if amount:
            self.zoom(1.2 if amount > 0 else 1 / 1.2)
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.scene() and not self.scene().sceneRect().isEmpty() and not self._user_zoomed:
            self.fit_board()

    def show_svg(self, svg: str):
        import re
        svg = re.sub(
            r"(<svg\b[^>]*>)",
            r"\1<style>text{fill:#000000!important;stroke:#fff8ed!important;"
            r"stroke-width:0.32px!important;paint-order:stroke fill!important;"
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


class WorkflowChecklist(QWidget):
    """Visual summary of recorded pipeline stages, not a physical sign-off."""

    STAGES = (
        ("COLLECT", "Project imported"),
        ("SANITY", "Netlist checked"),
        ("PRE-SOLVE", "Footprints analysed"),
        ("CONSTRAINTS", "Placement locks"),
        ("QUICK FIT", "Components placed"),
        ("ROUTING", "Copper routed"),
        ("VERIFY", "Electrical PASS"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workflowChecklist")
        self.setStyleSheet("""
            QWidget#workflowChecklist { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; }
            QLabel#workflowTitle { color: #203047; font-size: 15px; font-weight: 700; }
            QLabel#workflowPercent { color: #233e6b; font-size: 14px; font-weight: 700; }
            QProgressBar { background: #e9eef5; border: 0; border-radius: 5px; height: 8px; }
            QProgressBar::chunk { background: #19866f; border-radius: 5px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 12)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        title = QLabel("Quick Solve progress")
        title.setObjectName("workflowTitle")
        self.percent = QLabel("0%")
        self.percent.setObjectName("workflowPercent")
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.percent)
        layout.addLayout(heading)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, len(self.STAGES))
        layout.addWidget(self.bar)
        self.rows = {}
        for key, caption in self.STAGES:
            row = QHBoxLayout()
            mark = QLabel("○")
            mark.setFixedWidth(22)
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mark.setStyleSheet("font-size: 23px; color: #b8bec7;")
            label = QLabel(caption)
            label.setStyleSheet("font-size: 12px; color: #475569;")
            row.addWidget(mark)
            row.addWidget(label, 1)
            layout.addLayout(row)
            self.rows[key] = mark
        note = QLabel("Electrical completion ≠ build-ready physical clearance")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 10px; color: #697586;")
        layout.addWidget(note)
        self.reset()

    def reset(self):
        self.update_states({})

    def update_states(self, states):
        complete = 0
        for key, _ in self.STAGES:
            state = states.get(key, "pending")
            mark = self.rows[key]
            if state == "done":
                mark.setText("✓")
                mark.setStyleSheet("font-size: 19px; font-weight: bold; color: #2ebd64;")
                complete += 1
            elif state == "running":
                mark.setText("●")
                mark.setStyleSheet("font-size: 17px; color: #2673bf;")
            elif state == "failed":
                mark.setText("✕")
                mark.setStyleSheet("font-size: 19px; font-weight: bold; color: #d64545;")
            else:
                mark.setText("○")
                mark.setStyleSheet("font-size: 23px; color: #b8bec7;")
        self.bar.setValue(complete)
        self.percent.setText(f"{round(100 * complete / len(self.STAGES))}%")


class SolveWorker(QThread):
    """Run the shared solver off the Qt event loop; emit only finished results."""

    completed = Signal(object)
    crashed = Signal(str)

    def __init__(self, project: dict[str, Any], parent=None):
        super().__init__(parent)
        self.project = copy.deepcopy(project)

    def run(self):
        try:
            from solve.desktop_integration import solve_for_display
            self.completed.emit(solve_for_display(self.project, attempts=24))
        except Exception:
            self.crashed.emit(traceback.format_exc())


class RouteMateWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Route-Mate {GUI_VERSION} — Stripboard Quick Solve")
        self.resize(1560, 900)
        self.setMinimumSize(950, 600)
        self.project: dict[str, Any] | None = None
        self.project_path: Path | None = None
        self.presolve_constraints: dict[str, dict[str, bool]] = {}
        self.pipeline_run = None
        self._top_svg = None
        self._copper_svg = None
        self._board_side = "top"
        self._solver_worker = None
        self._solve_input = None
        self._solved_verified = False
        self._quick_source = None  # Locked pre-route project; never a previously solved layout.

        logo_path = REPO_ROOT / "icon" / "RouteMate-original.png"
        if logo_path.is_file():
            self.setWindowIcon(QIcon(str(logo_path)))
        toolbar = QToolBar("Main")
        toolbar.setObjectName("routeMateToolbar")
        toolbar.setStyleSheet("""
            QToolBar#routeMateToolbar { background: #17273b; border: none; padding: 9px; spacing: 8px; min-height: 54px; }
            QToolBar#routeMateToolbar QToolButton { background: #2a405a; color: white; border: 1px solid #3e5976; border-radius: 9px; padding: 9px 14px; font-weight: 600; }
            QToolBar#routeMateToolbar QToolButton:hover { background: #3a5b7c; }
            QToolBar#routeMateToolbar QToolButton:checked { background: #23966c; border-color: #35c18b; }
        """)
        brand = QWidget()
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(2, 0, 18, 0)
        brand_row.setSpacing(10)
        brand_logo = QLabel()
        if logo_path.is_file():
            logo = QPixmap(str(logo_path))
            if not logo.isNull():
                brand_logo.setPixmap(logo.scaled(44, 44, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))
        brand_row.addWidget(brand_logo)
        brand_title = QLabel("ROUTE-MATE")
        brand_title.setStyleSheet("color: white; font-size: 16px; font-weight: 800;")
        brand_row.addWidget(brand_title)
        toolbar.addWidget(brand)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.load_action = QAction("Load JSON", self)
        self.load_action.triggered.connect(self.load_json)
        toolbar.addAction(self.load_action)
        self.solve_action = QAction("Quick Solve", self)
        self.solve_action.setToolTip("Place and route while preserving fixed components")
        self.solve_action.setEnabled(False)
        self.solve_action.triggered.connect(self.solve_board)
        toolbar.addAction(self.solve_action)
        self.review_locks_action = QAction("Review Locks", self)
        self.review_locks_action.setEnabled(False)
        self.review_locks_action.setToolTip("Choose fixed and edge constraints for positioned parts")
        self.review_locks_action.triggered.connect(self.review_locks)
        toolbar.addAction(self.review_locks_action)
        self.save_solved_action = QAction("Save Solved JSON", self)
        self.save_solved_action.setEnabled(False)
        self.save_solved_action.triggered.connect(self.save_solved_json)
        toolbar.addAction(self.save_solved_action)
        pipeline_action = QAction("Pipeline State", self)
        pipeline_action.triggered.connect(self.show_pipeline_state)
        toolbar.addAction(pipeline_action)
        toolbar.addSeparator()
        self.top_action = QAction("Component side", self)
        self.top_action.setCheckable(True)
        self.top_action.setChecked(True)
        self.top_action.triggered.connect(lambda: self._switch_board_side("top"))
        toolbar.addAction(self.top_action)
        self.copper_action = QAction("Copper side (mirrored)", self)
        self.copper_action.setCheckable(True)
        self.copper_action.triggered.connect(lambda: self._switch_board_side("copper"))
        toolbar.addAction(self.copper_action)
        self.render_action = QAction("Open Solved", self)
        self.render_action.setToolTip("Preview an existing routed JSON without re-solving")
        self.render_action.triggered.connect(self.render_json)
        toolbar.addAction(self.render_action)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText("Checks, solve attempts and diagnostics appear here.")
        self.log.setStyleSheet(
            "QPlainTextEdit { background: #0f1c2b; color: #dbe7f5;"
            "border: 0; padding: 12px; font-size: 11px; }"
        )
        self.top_view = BoardView()
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(5)

        # Left: meaningful overview without a wall of test output.
        self.checklist = WorkflowChecklist()
        self.project_summary = QLabel("Open a circuit to begin")
        self.project_summary.setWordWrap(True)
        self.project_summary.setObjectName("projectSummary")
        self.solve_summary = QLabel("No board solved")
        self.solve_summary.setWordWrap(True)
        self.solve_summary.setObjectName("solveSummary")
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(8, 12, 8, 8)
        overview_layout.setSpacing(11)
        overview_layout.addWidget(self.project_summary)
        overview_layout.addWidget(self.checklist)
        overview_layout.addWidget(self.solve_summary)
        overview_layout.addStretch()
        self.sidebar_tabs = QTabWidget()
        self.sidebar_tabs.setObjectName("sidebarTabs")
        self.sidebar_tabs.addTab(overview, "Overview")
        self.sidebar_tabs.addTab(self.log, "Activity")
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 8, 2, 8)
        left_layout.addWidget(self.sidebar_tabs)
        left_panel.setMinimumWidth(245)
        left_panel.setMaximumWidth(375)
        split.addWidget(left_panel)

        # Right: prominent board canvas with a compact identity, result and
        # zoom controls; panning is available by dragging the board.
        board_panel = QWidget()
        board_layout = QVBoxLayout(board_panel)
        board_layout.setContentsMargins(8, 8, 8, 8)
        board_layout.setSpacing(7)
        board_heading = QFrame()
        board_heading.setObjectName("boardHeader")
        heading_row = QHBoxLayout(board_heading)
        heading_row.setContentsMargins(13, 8, 10, 8)
        heading_row.setSpacing(9)
        heading_text = QVBoxLayout()
        heading_text.setSpacing(2)
        self.board_project_label = QLabel("BOARD PREVIEW")
        self.board_project_label.setObjectName("boardProjectLabel")
        self.board_result_label = QLabel("Open a project to show its component layout")
        self.board_result_label.setObjectName("boardResultLabel")
        heading_text.addWidget(self.board_project_label)
        heading_text.addWidget(self.board_result_label)
        heading_row.addLayout(heading_text, 1)
        for caption, callback, tip in (
            ("−", lambda: self.top_view.zoom(1 / 1.2), "Zoom out"),
            ("+", lambda: self.top_view.zoom(1.2), "Zoom in"),
            ("Fit", self.fit_board, "Fit the complete board"),
        ):
            button = QPushButton(caption)
            button.setObjectName("boardZoomButton")
            button.setToolTip(tip)
            button.clicked.connect(callback)
            heading_row.addWidget(button)
        board_layout.addWidget(board_heading)
        board_layout.addWidget(self.top_view, 1)
        split.addWidget(board_panel)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([295, 1265])
        self.setCentralWidget(split)
        self.setStyleSheet("""
            QMainWindow { background: #eef2f7; }
            QWidget#sidebarTabs { background: #f7f9fc; }
            QTabWidget::pane { border: 1px solid #e0e7ef; border-radius: 9px;
                                background: #f7f9fc; }
            QTabBar::tab { color: #5b6c82; background: #e8eef5; padding: 9px 22px;
                           margin-right: 3px; border-radius: 7px; font-weight: 600; }
            QTabBar::tab:selected { background: white; color: #173c66; }
            QLabel#projectSummary { background: #e8f0fa; color: #1c4268;
                                    border-radius: 8px; padding: 12px;
                                    font-size: 12px; font-weight: 600; }
            QLabel#solveSummary { background: #edf3fa; color: #2e5274;
                                  border-radius: 8px; padding: 12px;
                                  font-size: 12px; }
            QFrame#boardHeader { background: white; border: 1px solid #e0e7ef;
                                  border-radius: 10px; }
            QLabel#boardProjectLabel { color: #17324f; font-size: 15px; font-weight: 800; }
            QLabel#boardResultLabel { color: #60738a; font-size: 11px; }
            QPushButton#boardZoomButton { background: #eff4fa; color: #183956;
                                         padding: 7px 11px; border: 1px solid #dbe5ef;
                                         border-radius: 6px; font-weight: 700; }
            QPushButton#boardZoomButton:hover { background: #dbe9f7; }
            QStatusBar { background: #e7eef5; color: #3f5873; font-size: 11px; }
        """)
        self.statusBar().showMessage("Ready. Load a project JSON to begin.")
        self.log_line(f"Route-Mate {GUI_VERSION} — desktop Quick Solve")
        self.log_line("Workflow: Import → Netlist → Footprints → Locks → Quick Solve → Electrical check.")
        self.log_line("Engine: locked placement + routing feedback + independent electrical and grid checks; measured cut access remains unverified.")

    def _set_board_summary(self, message: str, *, project: dict | None = None,
                           level: str = "neutral"):
        active = project if project is not None else self.project
        board = active.get("board", {}) if isinstance(active, dict) else {}
        name = self.project_path.stem if self.project_path is not None else "Untitled"
        rows, cols = board.get("rows"), board.get("cols")
        dims = f"  ·  {rows} × {cols} holes" if rows and cols else ""
        self.board_project_label.setText(f"{name.upper()}{dims}")
        self.board_result_label.setText(message)
        self.solve_summary.setText(message)
        backgrounds = {
            "neutral": ("#edf3fa", "#2e5274"),
            "working": ("#e7f1ff", "#155aa0"),
            "pass": ("#e2f4ed", "#176c51"),
            "failed": ("#fdeaea", "#ac2f3c"),
        }
        bg, fg = backgrounds.get(level, backgrounds["neutral"])
        self.solve_summary.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 8px; "
            "padding: 12px; font-size: 12px; font-weight: 600;"
        )

    def log_line(self, message: str):
        self.log.appendPlainText(message)

    def _log_handoff(self, handoff: dict[str, Any]):
        self.log_line(
            f"[HANDOFF] {handoff.get('from_stage') or 'project start'} -> "
            f"{handoff['to_module']} | project={handoff['project_sha256'][:12]} | "
            f"outstanding findings={len(handoff['findings'])}"
        )
        for finding in handoff["findings"]:
            self.log_line(
                f"[HANDOFF][{finding['severity'].upper()}] "
                f"{finding['code']}: {finding['message']}"
            )

    def show_pipeline_state(self):
        if self.pipeline_run is None:
            QMessageBox.information(self, "Pipeline State", "Load a project to start a pipeline run.")
            return
        context = self.pipeline_run.context
        lines = [
            f"Run ID: {context.run_id}",
            f"Project: {context.project_path}",
            f"Current stage: {context.current_stage or 'not started'}",
            f"Current project SHA-256: {context.project_sha256}",
            "",
            "WORKFLOW HANDOFFS",
        ]
        order = ("COLLECT", "TEST", "QUICKSOLVE", "SOLVE")
        grouped = {name: [] for name in order}
        for result in context.stages.values():
            group = result.extra.get("workflow_stage", "OTHER")
            grouped.setdefault(group, []).append(result)
        for group in order:
            lines.append(f"{group}:")
            records = grouped.get(group, [])
            if not records:
                lines.append("  NOT RUN")
            for result in records:
                lines.append(f"  {result.stage} — {result.status} — {result.module}")
                lines.append(f"    input:  {(result.input_project_sha256 or 'n/a')[:16]}")
                lines.append(f"    output: {(result.output_project_sha256 or 'n/a')[:16]}")
                if result.options.get("from_stage"):
                    lines.append(f"    received after: {result.options['from_stage']}")
                if result.options.get("upstream_finding_ids"):
                    lines.append(
                        f"    received findings: {result.options['upstream_finding_ids']}"
                    )
                if result.metrics:
                    lines.append(f"    metrics: {result.metrics}")
                if result.summary:
                    lines.append(f"    result: {result.summary}")
        lines.extend(["", f"FINDINGS ({len(context.findings)} total)"])
        if not context.findings:
            lines.append("  None")
        for finding in context.findings:
            lines.append(
                f"  [{finding.severity.upper()} / {finding.status}] "
                f"{finding.code}: {finding.message}"
            )
        dialog = QDialog(self)
        dialog.setWindowTitle("Pipeline State — Handoff Proof")
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(dialog)
        view.setReadOnly(True)
        view.setPlainText("\\n".join(lines))
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def fit_board(self):
        self.top_view.fit_board()

    def _render_component_side(
        self, project: dict[str, Any], *, highlight_component_id: str | None = None
    ) -> tuple[str, str]:
        """Render the component side, optionally highlighting the part under review."""
        from render.standalone_bridge import render_project_data

        # Both views come from the same production render pass and solved project.
        top_svg, copper_svg, _renderer_log = render_project_data(
            project, highlight_component_id=highlight_component_id
        )
        self._copper_svg = copper_svg
        return top_svg, "production standalone renderer (both board sides)"

    def render_json(self):
        """Open a board JSON and display its saved layout without running the pipeline."""
        start_dir = self.project_path.parent if self.project_path else REPO_ROOT
        filename, _ = QFileDialog.getOpenFileName(
            self, "Render Route-Mate JSON", str(start_dir),
            "Project JSON (*.json);;All files (*)",
        )
        if not filename:
            return
        path = Path(filename)
        try:
            project = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(project, dict):
                raise ValueError("Project JSON root must be an object.")
            board = project.get("board")
            if not isinstance(board, dict) or not all(
                isinstance(board.get(key), int) and board[key] > 0
                for key in ("rows", "cols")
            ):
                raise ValueError("Project JSON needs positive board.rows and board.cols.")
            if not isinstance(project.get("components"), list):
                raise ValueError("Project JSON needs a components array.")
            # Render into temporary values first; leave the existing view intact on failure.
            from render.standalone_bridge import render_project_data
            top_svg, copper_svg, _ = render_project_data(project)
            self.project = project
            self.project_path = path
            self.pipeline_run = None
            self._solved_verified = False
            self._quick_source = None
            self.solve_action.setEnabled(False)
            self.save_solved_action.setEnabled(False)
            self.checklist.reset()
            self.presolve_constraints = {}
            self._top_svg = top_svg
            self._copper_svg = copper_svg
            self._show_board(top_svg if self._board_side == "top" else copper_svg)
            self.project_summary.setText(
                f"{path.name}\n{len(project.get('components', []))} components · "
                f"{len(project.get('nets', []))} nets"
            )
            self._set_board_summary(
                "Saved layout preview · no new verification performed",
                level="neutral",
            )
            self.log_line(f"[RENDER JSON] {path}")
            self.log_line("[RENDER JSON] Displayed saved layout; no collector, tests or solver run.")
            # Historic routed JSON may be electrically sound yet contain
            # jumpers drawn directly through a capacitor or other body.
            # Never present those saved results without a safety warning.
            from solve.quick_rules import quick_audit
            try:
                audit = quick_audit(project)
            except (ValueError, TypeError, KeyError) as audit_exc:
                self.log_line(f"[RENDER JSON][UNVERIFIED] Jumper audit unavailable: {audit_exc}")
                self.statusBar().showMessage("Saved layout loaded; jumper clearance UNVERIFIED.")
            else:
                if audit["status"] == "FAIL":
                    self._set_board_summary(
                        f"UNSAFE saved layout · {len(audit['errors'])} jumper/geometry issues",
                        level="failed",
                    )
                    self.log_line(
                        f"[RENDER JSON][UNSAFE] {len(audit['errors'])} jumper geometry issue(s)."
                    )
                    for issue in audit["errors"][:25]:
                        self.log_line("[RENDER JSON][UNSAFE] " + issue)
                    self.statusBar().showMessage(
                        "UNSAFE saved layout: jumpers intersect components/pads. Re-solve original JSON."
                    )
                    QMessageBox.warning(
                        self, "Unsafe saved routing",
                        f"{len(audit['errors'])} jumper collision/geometry issue(s) found. "
                        "Do not build this saved board. Load the original circuit JSON and "
                        "run Solve Board again; see the log for details.",
                    )
                else:
                    self._set_board_summary(
                        "Saved layout · grid artwork check clear · electrical status unverified",
                        level="neutral",
                    )
                    self.log_line(
                        "[RENDER JSON] Grid artwork checks clear; measured package/cut access NOT certified."
                    )
                    self.statusBar().showMessage(
                        f"Rendered JSON: {path.name} — grid checks clear, physical certification pending."
                    )
        except Exception as exc:
            self.log_line(f"[RENDER JSON][ERROR] {type(exc).__name__}: {exc}")
            QMessageBox.warning(self, "Could not render JSON", str(exc))

    def export_board_svgs(self):
        """Refresh the current board and save both production SVG views."""
        if self.project is None:
            QMessageBox.information(self, "Render SVG", "Load a project first.")
            return
        directory = self.project_path.parent if self.project_path else REPO_ROOT
        suggested = directory / "route-mate-board.svg"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export component-side SVG", str(suggested),
            "SVG image (*.svg)",
        )
        if not filename:
            return
        output = Path(filename)
        if output.suffix.lower() != ".svg":
            output = output.with_suffix(".svg")
        copper_output = output.with_name(output.stem + "-copper.svg")
        try:
            top_svg, renderer_log = self._render_component_side(self.project)
            self._show_board(top_svg)
            output.write_text(top_svg, encoding="utf-8")
            copper_output.write_text(self._copper_svg, encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            self.log_line(f"[RENDER][ERROR] {exc}")
            QMessageBox.warning(self, "SVG export failed", str(exc))
            return
        self.log_line(f"[RENDER] Component side: {output}")
        self.log_line(f"[RENDER] Copper side: {copper_output}")
        if renderer_log:
            self.log_line("[RENDER] " + renderer_log)
        self.statusBar().showMessage(f"Exported both SVG board views to {output.parent}")

    def _switch_board_side(self, side: str):
        self._board_side = side
        self.top_action.setChecked(side == "top")
        self.copper_action.setChecked(side == "copper")
        svg = self._copper_svg if side == "copper" else self._top_svg
        if svg:
            self.top_view.show_svg(svg)
        self.statusBar().showMessage(
            "Copper side — mirrored underside; red X marks physical cuts."
            if side == "copper" else
            "Component side — transparent top view; cuts aligned to board holes."
        )

    def _show_board(self, top_svg: str):
        self._top_svg = top_svg
        self._switch_board_side(self._board_side)
        if self.project is not None:
            from solve.render_quality import score_render
            try:
                quality = score_render(self.project)
                self.log_line(
                    f"[QUALITY SCORE] {quality['score']:.1f}/100 PROVISIONAL | "
                    f"placed {quality['placed']}/{quality['placeable']} | "
                    f"cuts {quality['cuts']} | wires {quality['wires']} | "
                    f"diagonal {quality['diagonals']} | "
                    f"wire {quality['wire_length_mm']:.1f} mm | "
                    "NOT physical sign-off"
                )
            except (ValueError, TypeError, KeyError) as exc:
                self.log_line(f"[QUALITY SCORE] UNAVAILABLE: {exc}")

    def _run_tests(self):
        if getattr(sys, "frozen", False):
            self.log_line("[TEST] Skipped: running standalone application.")
            if self.pipeline_run is not None and self.project is not None:
                from pipeline import test_suite_stage_result
                handoff = self.pipeline_run.handoff(self.project, "tests.unittest")
                self._log_handoff(handoff)
                stage_result, findings = test_suite_stage_result(
                    handoff["project"], returncode=None, skipped=True
                )
                stage_result.options.update({
                    "from_stage": handoff["from_stage"],
                    "upstream_finding_ids": handoff["finding_ids"],
                })
                self._record_pipeline_result(stage_result, findings)
            return True

        self.log_line("[TEST] Running repository unittest suite...")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=Path(__file__).resolve().parent.parent,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        for line in result.stdout.splitlines():
            self.log_line("[TEST] " + line)
        self.log_line(f"[TEST] Exit code: {result.returncode}")
        if self.pipeline_run is not None and self.project is not None:
            from pipeline import test_suite_stage_result
            handoff = self.pipeline_run.handoff(self.project, "tests.unittest")
            self._log_handoff(handoff)
            stage_result, findings = test_suite_stage_result(
                handoff["project"], returncode=result.returncode, output=result.stdout
            )
            stage_result.options.update({
                "from_stage": handoff["from_stage"],
                "upstream_finding_ids": handoff["finding_ids"],
            })
            self._record_pipeline_result(stage_result, findings)
        return result.returncode == 0

    def _ask_lock_settings(self, placed: list[dict[str, Any]]):
        self.presolve_constraints = {}
        if not placed:
            self.log_line("[LOCKS] No saved positions; no existing components require lock questions.")
        else:
            self.log_line(f"[LOCKS] Asking Locked / Edge / Slide for {len(placed)} placed components.")
            for index, component in enumerate(placed, 1):
                component_id = str(component.get("id"))
                label = str(component.get("label") or component.get("id"))
                highlighted_svg, renderer_log = self._render_component_side(
                    self.project, highlight_component_id=component_id
                )
                self._show_board(highlighted_svg)
                self.statusBar().showMessage(
                    f"Reviewing component {index}/{len(placed)}: {label}"
                )
                self.log_line(f"[LOCKS] Highlighting {label} on the board ({index}/{len(placed)}).")
                if renderer_log:
                    self.log_line("[RENDER] " + renderer_log)
                dialog = LockDialog(component, index, len(placed), self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    top_svg, _ = self._render_component_side(self.project)
                    self._show_board(top_svg)
                    self.log_line("[LOCKS] Cancelled. Changes already accepted remain rendered; Quick Place not started.")
                    return

                values = dialog.values()
                self.presolve_constraints[component_id] = values
                self.log_line(
                    f"[LOCKS] {label}: Locked={values['locked']} "
                    f"Edge={values['edge']} Slide={values['slide']} "
                    f"Reposition={values['reposition']}"
                )

                # Apply each answer immediately, then redraw before asking about
                # the next component. This preserves the original interactive flow.
                if values["reposition"]:
                    # Return the part to the solver pool without excluding it,
                    # deleting its net assignments or losing its footprint.
                    component.pop("boardPos", None)
                    component.pop("flexibleEndPos", None)
                    component["locked"] = False
                    component["edge"] = False
                    component["slide"] = False
                    self.log_line(f"[PLACEMENT] {label} returned to Quick Fit placement pool.")
                else:
                    component["locked"] = True
                    component["edge"] = bool(values["edge"])
                    component["slide"] = bool(values["slide"])

                top_svg, renderer_log = self._render_component_side(self.project)
                self._show_board(top_svg)
                self.log_line(f"[RENDER] Board refreshed after {label}.")
                if renderer_log:
                    self.log_line("[RENDER] " + renderer_log)

        self.log_line(
            f"[LOCKS] Recorded {len(self.presolve_constraints)} component responses."
        )
        self._record_project_stage(
            "PREPARE.constraints", "gui.lock_dialog",
            {"constraints": copy.deepcopy(self.presolve_constraints)},
        )

        # Use approved locks as the immutable Quick Solve input.
        self._quick_source = copy.deepcopy(self.project)
        self.review_locks_action.setEnabled(True)
        self.solve_board()

    def review_locks(self):
        """Review the *input* placement, not the last solved output."""
        from placement_policy import is_off_board_component
        if self._solver_worker is not None and self._solver_worker.isRunning():
            return
        if self.project is None:
            return
        source = copy.deepcopy(self._quick_source or self.project)
        placed = [c for c in source.get("components", [])
                  if isinstance(c, dict) and isinstance(c.get("boardPos"), dict)
                  and not is_off_board_component(c)]
        if not placed:
            QMessageBox.information(
                self, "Review Locks",
                "No on-board parts have positions yet. Load a partially placed "
                "project to choose fixed anchors, or run Quick Solve first."
            )
            return
        self.project = source
        self._solved_verified = False
        self.save_solved_action.setEnabled(False)
        if self.project_path is not None:
            # Recompute input milestones for the newly reviewed source.
            self._restart_quick_pipeline(source, include_constraints=False)
        preview, _ = self._render_component_side(source)
        self._show_board(preview)
        self._ask_lock_settings(placed)

    def _restart_quick_pipeline(self, source: dict[str, Any], *, include_constraints=True):
        """Re-run lightweight input checks when repeating a Quick Solve."""
        if self.project_path is None:
            return
        from pipeline import (
            PipelineRun, electrical_sanity_stage_result,
            presolve_stage_result, project_import_stage_result,
        )
        from prepare.sanity.electrical import run_electrical_sanity
        self.pipeline_run = PipelineRun.create(self.project_path, source)
        result, findings = project_import_stage_result(source, source)
        self._record_pipeline_result(result, findings)
        sanity = run_electrical_sanity(source)
        result, findings = electrical_sanity_stage_result(source, sanity)
        self._record_pipeline_result(result, findings)
        if sanity["status"] != "PASS":
            raise ValueError("Electrical sanity failed before Quick Solve: " +
                             "; ".join(sanity.get("errors", [])[:4]))
        result, findings = presolve_stage_result(source)
        self._record_pipeline_result(result, findings)
        if include_constraints:
            self._record_project_stage(
                "PREPARE.constraints", "gui.lock_dialog",
                {"constraints": copy.deepcopy(self.presolve_constraints)},
                snapshot=source,
            )

    def solve_board(self):
        """Bounded Quick Solve from preserved input, honoring hard locks."""
        if self.project is None:
            QMessageBox.information(self, "Quick Solve", "Load a project JSON first.")
            return
        if self._solver_worker is not None and self._solver_worker.isRunning():
            self.statusBar().showMessage("Quick Solve is already running.")
            return
        source = copy.deepcopy(self._quick_source if self._quick_source is not None
                               else self.project)
        try:
            if self.pipeline_run is not None:
                from pipeline import PipelineRun, project_sha256
                current = project_sha256(source)
                if self.pipeline_run.context.project_sha256 != current:
                    # Previously completed route changed the pipeline hash.
                    # Start a fresh recorded run; do not send old wires into
                    # route_copper or turn Quick Solve into legacy rerouting.
                    self._restart_quick_pipeline(source)
                saved_run = PipelineRun.load(self.pipeline_run.state_path)
                constraints_stage = saved_run.context.stages.get("PREPARE.constraints")
                if constraints_stage is not None:
                    saved_constraints = constraints_stage.report.get("constraints")
                    if not isinstance(saved_constraints, dict):
                        raise ValueError("PREPARE.constraints sidecar report is invalid.")
                    if saved_run.context.project_sha256 != current:
                        raise ValueError("Saved constraints do not match the locked input.")
                    for component in source.get("components", []):
                        if not isinstance(component, dict):
                            continue
                        cid = str(component.get("id"))
                        if cid not in saved_constraints:
                            continue
                        flags = saved_constraints[cid]
                        if not isinstance(flags, dict):
                            raise ValueError(f"Invalid saved lock constraints for {cid}.")
                        for key in ("locked", "edge", "slide"):
                            if bool(component.get(key, False)) != bool(flags.get(key, False)):
                                raise ValueError(f"Saved {key} constraint differs for {cid}.")
                        if flags.get("reposition") and isinstance(component.get("boardPos"), dict):
                            raise ValueError(f"{cid}: repositioned component is still positioned.")
                    self.log_line(f"[QUICK SOLVE] {len(saved_constraints)} approved lock choices.")
        except (ValueError, OSError, KeyError) as exc:
            self.log_line(f"[QUICK SOLVE][BLOCKED] {exc}")
            QMessageBox.warning(self, "Quick Solve blocked", str(exc))
            self.statusBar().showMessage("Resolve locked-input conflicts before solving.")
            return

        self._quick_source = copy.deepcopy(source)
        self._solve_input = copy.deepcopy(source)
        self._solved_verified = False
        self.save_solved_action.setEnabled(False)
        self.solve_action.setEnabled(False)
        self.review_locks_action.setEnabled(False)
        self.load_action.setEnabled(False)
        self.render_action.setEnabled(False)
        self.log_line("[QUICK SOLVE] Routing-aware placement with exact locks and edge constraints...")
        self._set_board_summary("Quick Solve in progress · preserving approved locks", project=source, level="working")
        self.statusBar().showMessage("Quick Solve running — the board remains responsive.")
        self._solver_worker = SolveWorker(self._solve_input, self)
        self._solver_worker.completed.connect(self._solve_completed)
        self._solver_worker.crashed.connect(self._solve_crashed)
        self._solver_worker.finished.connect(self._solve_finished)
        self._solver_worker.start()

    def _solve_completed(self, outcome: dict[str, Any]):
        """On the GUI thread, accept only a verified board and redraw it."""
        status = outcome.get("status", "FAILED")
        self.log_line(f"[SOLVE] {status} — {outcome.get('attempts_used', 0)} placement attempt(s).")
        if status != "ROUTED":
            self._set_board_summary(
                f"{status} · no verified board found in the search budget",
                level="failed",
            )
            self.sidebar_tabs.setCurrentIndex(1)
            for error in outcome.get("errors", []):
                self.log_line("[SOLVE][ERROR] " + str(error))
            failure = outcome.get("best_failure")
            if failure:
                self.log_line(f"[SOLVE] Best failed trial: {failure}")
            if self.pipeline_run is not None and self._solve_input is not None:
                from pipeline import route_stage_result
                handoff = self.pipeline_run.handoff(self._solve_input, "solve.placement_feedback")
                rejected = {
                    "status": status, "project": handoff["project"],
                    "errors": list(outcome.get("errors", [])), "warnings": [],
                    "cuts_added": 0, "wires_added": 0, "verification": None,
                }
                stage, findings = route_stage_result(handoff["project"], rejected)
                stage.status = "failed"
                stage.options["router"] = "hole_graph"
                self._record_pipeline_result(stage, findings)
            self.statusBar().showMessage("No verified route found; original preview retained.")
            return

        solved = outcome["project"]
        placement = outcome["placement"]
        routing = outcome["routing"]
        verification = outcome["verification"]
        if self.pipeline_run is not None and self._solve_input is not None:
            from pipeline import (
                quick_fit_stage_result, route_stage_result, verification_stage_result,
            )
            place_handoff = self.pipeline_run.handoff(
                self._solve_input, "solve.placement_feedback",
            )
            self._log_handoff(place_handoff)
            place_result, findings = quick_fit_stage_result(
                place_handoff["project"], placement,
            )
            place_result.module = "solve.placement_feedback"
            place_result.options.update({
                "from_stage": place_handoff["from_stage"],
                "upstream_finding_ids": place_handoff["finding_ids"],
                "router": "hole_graph",
                "attempts_used": outcome["attempts_used"],
            })
            self._record_pipeline_result(place_result, findings)

            route_handoff = self.pipeline_run.handoff(placement["project"], "solve.hole_router")
            self._log_handoff(route_handoff)
            route_result, findings = route_stage_result(
                route_handoff["project"], routing,
            )
            route_result.module = "solve.hole_router"
            route_result.options.update({
                "from_stage": route_handoff["from_stage"],
                "upstream_finding_ids": route_handoff["finding_ids"],
                "measured_clearance_certified": False,
            })
            self._record_pipeline_result(route_result, findings)
            verify_handoff = self.pipeline_run.handoff(solved, "solve.verify")
            self._log_handoff(verify_handoff)
            verify_result, findings = verification_stage_result(
                verify_handoff["project"], verification,
            )
            verify_result.options.update({
                "from_stage": verify_handoff["from_stage"],
                "upstream_finding_ids": verify_handoff["finding_ids"],
            })
            self._record_pipeline_result(verify_result, findings)

        self.project = solved
        counts = verification["counts"]
        self._set_board_summary(
            f"Electrical PASS · {len(solved['board']['cuts'])} cuts · "
            f"{len(solved['board']['wires'])} jumpers · "
            f"{outcome['attempts_used']} placement attempt(s) · physical sign-off pending",
            level="pass",
        )
        self.sidebar_tabs.setCurrentIndex(0)
        self.log_line(
            f"[ROUTING] ROUTED: {len(solved['board']['cuts'])} cuts, "
            f"{len(solved['board']['wires'])} jumpers; "
            f"{counts['nets_checked']} nets, 0 shorts and 0 opens."
        )
        self.log_line(
            f"[VERIFY] Electrical PASS | grid jumper audit "
            f"{outcome['grid_audit']['status']} | grid physical audit "
            f"{outcome['physical_audit']['status']}."
        )
        for warning in outcome.get("warnings", []):
            self.log_line("[PHYSICAL][UNCERTIFIED] " + warning)
        self.log_line("[PHYSICAL] Measured package clearance and cut-tool access are NOT certified.")
        try:
            top_svg, renderer_log = self._render_component_side(solved)
            self._show_board(top_svg)
            self._solved_verified = True
            self.save_solved_action.setEnabled(True)
            if renderer_log:
                self.log_line("[RENDER] " + renderer_log)
            self.log_line("[RENDER] Solved component and mirrored copper sides are ready.")
            self.statusBar().showMessage(
                f"Electrical PASS — {len(solved['board']['cuts'])} cuts, "
                f"{len(solved['board']['wires'])} jumpers. Physical cut access unverified."
            )
        except Exception as exc:
            self.log_line(f"[RENDER][ERROR] Could not show solved board: {exc}")
            self.statusBar().showMessage("Solved and verified, but board rendering failed.")
            QMessageBox.warning(self, "Solved board rendering failed", str(exc))

    def _solve_crashed(self, message: str):
        self.log_line("[SOLVE][ERROR] " + message)
        self._set_board_summary("Quick Solve error — see Activity", level="failed")
        self.sidebar_tabs.setCurrentIndex(1)
        self.statusBar().showMessage("Solve error; previous preview retained.")
        QMessageBox.warning(self, "Solve failed", message.splitlines()[-1])

    def _solve_finished(self):
        self._solver_worker = None
        self._solve_input = None
        self.load_action.setEnabled(True)
        self.render_action.setEnabled(True)
        self.solve_action.setEnabled(self.project is not None)
        self.review_locks_action.setEnabled(self._quick_source is not None)

    def save_solved_json(self):
        """Save the exact verified routed project; never overwrite source."""
        if not self._solved_verified or self.project is None:
            QMessageBox.information(self, "Save Solved JSON", "Solve a board first.")
            return
        folder = self.project_path.parent if self.project_path else REPO_ROOT
        stem = self.project_path.stem if self.project_path else "board"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save verified routed board",
            str(folder / f"{stem}-autorouted.json"),
            "Project JSON (*.json)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        if self.project_path is not None and path.resolve() == self.project_path.resolve():
            QMessageBox.warning(self, "Source protected", "Choose a new file; the source JSON will not be overwritten.")
            return
        try:
            payload = json.dumps(self.project, indent=2, ensure_ascii=False) + "\n"
            temp = path.with_name(path.name + ".tmp")
            temp.write_text(payload, encoding="utf-8")
            temp.replace(path)
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        self.log_line(f"[SAVE] Verified routed board: {path}")
        self.statusBar().showMessage(f"Saved solved board: {path}")

    def _refresh_checklist(self):
        """Map actual pipeline stage names to visible milestones."""
        if self.pipeline_run is None:
            self.checklist.reset()
            return
        stage_keys = {
            "IN.project_import": "COLLECT",
            "IN.collect": "COLLECT",
            "PREPARE.electrical": "SANITY",
            "PREPARE.presolve": "PRE-SOLVE",
            "PREPARE.constraints": "CONSTRAINTS",
            "SOLVE.quick_fit": "QUICK FIT",
            "SOLVE.route": "ROUTING",
            "VERIFY.independent": "VERIFY",
        }
        states = {}
        for result in self.pipeline_run.context.stages.values():
            key = stage_keys.get(result.stage)
            if key is None:
                continue
            status = str(result.status).lower()
            if status in ("failed", "blocked", "stale", "error"):
                states[key] = "failed"
            elif status == "completed":
                report = result.report
                if result.stage in ("PREPARE.electrical", "VERIFY.independent"):
                    states[key] = "done" if report.get("status") == "PASS" else "failed"
                else:
                    states[key] = "done"
        self.checklist.update_states(states)

    def _record_pipeline_result(self, result, findings):
        if self.pipeline_run is None:
            return
        self.pipeline_run.record_stage(result, findings)
        self._refresh_checklist()
        group = result.extra.get("workflow_stage", result.stage)
        self.log_line(
            f"[PIPELINE][{group}] {result.stage}: {result.summary or result.status}; "
            f"input={str(result.input_project_sha256 or 'n/a')[:12]} "
            f"output={str(result.output_project_sha256 or 'n/a')[:12]}; "
            f"state saved to {self.pipeline_run.state_path.name}"
        )

    def _record_project_stage(self, stage: str, module: str, report: dict[str, Any],
                              *, snapshot: dict[str, Any] | None = None):
        project = self.project if snapshot is None else snapshot
        if self.pipeline_run is None or project is None:
            return
        from pipeline import StageResult, project_sha256
        current_hash = project_sha256(project)
        result = StageResult(
            stage=stage, status="completed", module=module,
            input_project_sha256=self.pipeline_run.context.project_sha256,
            output_project_sha256=current_hash,
            report=copy.deepcopy(report),
            summary=f"{stage}: recorded {len(report.get('constraints', {}))} component constraint(s).",
        )
        self._record_pipeline_result(result, [])

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
            collect_warnings = list(project.pop("_collectWarnings", []))
            for warning in collect_warnings:
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
            self.project_path = path
            from pipeline import PipelineRun, project_import_stage_result
            self.checklist.reset()
            self.pipeline_run = PipelineRun.create(
                path, source,
                sources=[{"kind": "project_json", "path": str(path.resolve())}],
            )
            import_result, import_findings = project_import_stage_result(
                source, project,
                warnings=collect_warnings,
                options=dimensions,
            )
            self._record_pipeline_result(import_result, import_findings)
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
            sanity_handoff = self.pipeline_run.handoff(project, "prepare.sanity.electrical")
            self._log_handoff(sanity_handoff)
            sanity_input = sanity_handoff["project"]
            sanity = run_electrical_sanity(sanity_input)
            from pipeline import electrical_sanity_stage_result
            sanity_result, sanity_findings = electrical_sanity_stage_result(sanity_input, sanity)
            sanity_result.options.update({
                "from_stage": sanity_handoff["from_stage"],
                "upstream_finding_ids": sanity_handoff["finding_ids"],
            })
            self._record_pipeline_result(sanity_result, sanity_findings)
            self.log_line(f"[SANITY] Electrical integrity: {sanity['status']}")
            for error in sanity["errors"]:
                self.log_line("[SANITY][ERROR] " + error)
            for warning in sanity["warnings"]:
                self.log_line("[SANITY][WARN] " + warning)
            if sanity["status"] != "PASS":
                QMessageBox.warning(self, "Collector sanity checks failed",
                                    "The project failed electrical sanity checks. See the log.")
                return

            # PRE-SOLVE is a read-only PREPARE report, persisted in the existing sidecar.
            from pipeline import presolve_stage_result
            presolve_handoff = self.pipeline_run.handoff(project, "prepare.presolve")
            self._log_handoff(presolve_handoff)
            presolve_result, presolve_findings = presolve_stage_result(presolve_handoff["project"])
            presolve_result.options.update({
                "from_stage": presolve_handoff["from_stage"],
                "upstream_finding_ids": presolve_handoff["finding_ids"],
            })
            self._record_pipeline_result(presolve_result, presolve_findings)
            candidate = presolve_result.report["board"]
            self.log_line(
                f"[PRE-SOLVE] {len(presolve_result.report['components'])} components; "
                f"placement candidate={candidate['placement_candidate_rows']} x "
                f"{candidate['placement_candidate_cols']} "
                f"({candidate['placement_candidate_status']}); "
                "physical fit NOT verified."
            )

            from placement_policy import is_off_board_component

            # Preserve and display the positions already present in the imported project.
            # Quick Fit works on a copy and must not overwrite the imported source JSON.
            components = project["components"]
            placed = [component for component in components
                      if isinstance(component.get("boardPos"), dict)
                      and not is_off_board_component(component)]
            on_board = [component for component in components
                        if not is_off_board_component(component)]
            self.log_line(
                f"[PLACEMENT] Existing layout: {len(placed)} positioned; "
                f"{len(on_board)} on-board; "
                f"{len(components) - len(on_board)} off-board/excluded."
            )
            for component in placed:
                self.log_line(
                    f"[PLACEMENT] {component.get('label') or component.get('id')}: "
                    f"boardPos={component.get('boardPos')} rotation={component.get('rotation', 0)}"
                )

            self.project = project
            self.project_path = path
            self._solved_verified = False
            self._quick_source = None
            self.solve_action.setEnabled(True)
            self.save_solved_action.setEnabled(False)
            self.project_summary.setText(
                f"{path.name}\n{len(project['components'])} components · "
                f"{len(project['nets'])} nets"
            )
            self._set_board_summary("Imported · reviewing placement constraints", project=project)
            top_svg, renderer_log = self._render_component_side(project)
            self._show_board(top_svg)
            self.log_line("[RENDER] Existing component-side layout rendered with alternating row bands.")
            if renderer_log:
                self.log_line("[RENDER] " + renderer_log)

            # Unit tests belong in CI, not on every user project import.
            self._ask_lock_settings(placed)
        except Exception as exc:
            self.log_line(f"[ERROR] {type(exc).__name__}: {exc}")
            self.log_line(traceback.format_exc())
            QMessageBox.critical(self, "Could not load project", str(exc))

    def closeEvent(self, event):
        if self._solver_worker is not None and self._solver_worker.isRunning():
            event.ignore()
            self.statusBar().showMessage("A bounded board solve is active; close after it finishes.")
            return
        event.accept()


def main():
    app = QApplication(sys.argv)
    # Use the platform-selected concrete font instead of Qt’s unresolved generic Sans-serif alias.
    app.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
    app.setApplicationName("Route-Mate")
    window = RouteMateWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())