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

GUI_VERSION = "1.34"
CODE_VERSION = "1.34"

from PySide6.QtCore import Qt, QByteArray, QPoint
from PySide6.QtGui import QAction, QBrush, QColor, QFontDatabase, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QComboBox,
    QSpinBox, QSplitter, QToolBar, QVBoxLayout, QWidget,
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
        self.locked = QRadioButton("Locked — keep on board")
        self.unlocked = QRadioButton("Unlocked — return to placement pool")
        self.edge = QCheckBox("Edge constrained")
        self.slide = QCheckBox("May slide along edge")
        # Unlocked parts lose their old placement and return to Quick Fit.
        is_locked = bool(component.get("locked", False))
        self.locked.setChecked(is_locked)
        self.unlocked.setChecked(not is_locked)
        self.edge.setChecked(bool(component.get("edge", False)))
        self.slide.setChecked(bool(component.get("slide", False)))
        self.locked.toggled.connect(self._update_constraint_controls)
        self.unlocked.toggled.connect(self._update_constraint_controls)
        layout.addWidget(self.locked)
        layout.addWidget(self.unlocked)
        layout.addWidget(self.edge)
        layout.addWidget(self.slide)
        layout.addWidget(QLabel("Unlocked components are repositioned by Quick Fit."))
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
                "reposition": self.unlocked.isChecked()}


class BoardView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing |
                            QPainter.RenderHint.TextAntialiasing |
                            QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#f2f2f2")))
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
        self.resize(1600, 760)
        self.setMinimumSize(1000, 600)
        self.project: dict[str, Any] | None = None
        self.project_path: Path | None = None
        self.presolve_constraints: dict[str, dict[str, bool]] = {}
        self.pipeline_run = None
        self._top_svg = None
        self._copper_svg = None
        self._board_side = "top"

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        load_action = QAction("Load JSON", self)
        load_action.triggered.connect(self.load_json)
        toolbar.addAction(load_action)
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
        render_action = QAction("Render JSON", self)
        render_action.triggered.connect(self.render_json)
        toolbar.addAction(render_action)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText("Route-Mate running log")
        self.top_view = BoardView()
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.log)
        split.addWidget(self.top_view)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([320, 1280])
        self.setCentralWidget(split)
        self.statusBar().showMessage("Ready. Load a project JSON to begin.")
        self.log_line(f"Route-Mate GUI v{GUI_VERSION} | Code v{CODE_VERSION}")
        self.log_line("Workflow: COLLECT → TEST → QUICKSOLVE → SOLVE. Pipeline State shows stage reports, project hashes and findings handed forward.")
        self.log_line("Solver available: deterministic greedy Quick Fit plus first-pass strip copper routing. Hard edge anchors and sliding are not implemented.")

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
            self.presolve_constraints = {}
            self._top_svg = top_svg
            self._copper_svg = copper_svg
            self._show_board(top_svg if self._board_side == "top" else copper_svg)
            self.log_line(f"[RENDER JSON] {path}")
            self.log_line("[RENDER JSON] Displayed saved layout; no collector, tests or solver run.")
            self.statusBar().showMessage(f"Rendered JSON: {path.name}")
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

        # Locked, positioned parts (including edge/slide-labelled anchors)
        # are fixed obstacles; proceed directly to Quick Fit.
        self.log_line("[QUICK FIT] Running shared deterministic net-aware placement engine...")
        from pipeline import quick_fit_stage_result
        from solve import quick_fit
        # Read the persisted PREPARE decisions back from disk before placement.
        # This makes the saved sidecar an audited input rather than a write-only log.
        from pipeline import PipelineRun, project_sha256
        saved_run = PipelineRun.load(self.pipeline_run.state_path)
        saved_constraints_stage = saved_run.context.stages.get("PREPARE.constraints")
        if saved_constraints_stage is None or not isinstance(saved_constraints_stage.report, dict):
            raise ValueError("QUICKSOLVE requires saved PREPARE.constraints in the sidecar")
        saved_constraints = saved_constraints_stage.report.get("constraints")
        if not isinstance(saved_constraints, dict):
            raise ValueError("QUICKSOLVE sidecar lock constraints are missing or invalid")
        if saved_run.context.project_sha256 != project_sha256(self.project):
            raise ValueError("QUICKSOLVE sidecar project hash does not match the current project")
        for component in self.project.get("components", []):
            if not isinstance(component, dict):
                continue
            cid = str(component.get("id"))
            if cid not in saved_constraints:
                continue
            flags = saved_constraints[cid]
            if not isinstance(flags, dict):
                raise ValueError(f"QUICKSOLVE invalid saved lock settings for {cid}")
            for key in ("locked", "edge", "slide"):
                expected = bool(flags.get(key, False))
                if bool(component.get(key, False)) != expected:
                    raise ValueError(f"QUICKSOLVE saved {key} disagrees with project for {cid}")
            if flags.get("reposition") and isinstance(component.get("boardPos"), dict):
                raise ValueError(f"QUICKSOLVE {cid} was returned to placement pool but still positioned")
        self.log_line(f"[QUICK FIT] Read and verified {len(saved_constraints)} lock decisions from sidecar.")
        quick_fit_handoff = self.pipeline_run.handoff(self.project, "solve.quick_fit")
        self._log_handoff(quick_fit_handoff)
        quick_fit_input = quick_fit_handoff["project"]
        result = quick_fit(quick_fit_input)
        stage_result, findings = quick_fit_stage_result(quick_fit_input, result)
        stage_result.options.update({
            "from_stage": quick_fit_handoff["from_stage"],
            "upstream_finding_ids": quick_fit_handoff["finding_ids"],
        })
        self._record_pipeline_result(stage_result, findings)
        for error in result.get("errors", []):
            self.log_line("[QUICK FIT][ERROR] " + str(error))
        for warning in result.get("warnings", []):
            self.log_line("[QUICK FIT][WARNING] " + str(warning))
        if result.get("status") != "PLACED":
            self.log_line(
                f"[QUICK FIT] {result.get('status', 'FAIL')}: "
                f"{result.get('placed', 0)} components placed; current edited preview retained."
            )
            QMessageBox.warning(
                self, "Quick Fit incomplete",
                 "Quick Fit could not place every included component. "
                "The latest board preview, including removals, remains displayed. See the log."
            )
            self.statusBar().showMessage("Quick Fit incomplete — latest preview retained.")
            return

        self.project = result["project"]
        from pipeline import route_stage_result, verification_stage_result
        from solve import route_copper
        route_handoff = self.pipeline_run.handoff(self.project, "solve.route")
        self._log_handoff(route_handoff)
        route_input = route_handoff["project"]
        routing = route_copper(route_input)
        route_result, route_findings = route_stage_result(route_input, routing)
        route_result.options.update({
            "from_stage": route_handoff["from_stage"],
            "upstream_finding_ids": route_handoff["finding_ids"],
        })
        self._record_pipeline_result(route_result, route_findings)
        verification = routing.get("verification")
        if isinstance(verification, dict) and verification.get("status") in {"PASS", "FAIL"}:
            verify_handoff = self.pipeline_run.handoff(
                routing.get("project", route_input), "solve.verify"
            )
            self._log_handoff(verify_handoff)
            verify_result, verify_findings = verification_stage_result(
                verify_handoff["project"], verification
            )
            verify_result.options.update({
                "from_stage": verify_handoff["from_stage"],
                "upstream_finding_ids": verify_handoff["finding_ids"],
            })
            self._record_pipeline_result(verify_result, verify_findings)
        for error in routing.get("errors", []):
            self.log_line("[ROUTING][ERROR] " + str(error))
        for warning in routing.get("warnings", []):
            self.log_line("[ROUTING][WARNING] " + str(warning))
        routed = routing.get("status") == "ROUTED"
        if routed:
            self.project = routing["project"]
            report = routing["verification"]
            self.log_line(
                f"[ROUTING] ROUTED — added {routing['cuts_added']} cuts and "
                f"{routing['wires_added']} jumpers; copper verification PASS "
                f"({report['counts']['nets_checked']} nets checked)."
            )
        else:
            self.log_line(
                f"[ROUTING] {routing.get('status', 'FAILED')} — placement retained; "
                "no partial routing changes applied."
            )
        # Jumper length is the minimum straight-line distance at 2.54 mm pitch.
        wire_lengths = []
        for wire in self.project.get("board", {}).get("wires", []):
            try:
                a, b = wire["from"], wire["to"]
                dr = int(a["row"]) - int(b["row"])
                dc = int(a["col"]) - int(b["col"])
                wire_lengths.append((dr * dr + dc * dc) ** 0.5 * 2.54)
            except (KeyError, TypeError, ValueError):
                self.log_line("[DIAGNOSTICS][ERROR] Invalid jumper endpoints")
        cuts_total = len(self.project.get("board", {}).get("cuts", []))
        self.log_line(
            f"[DIAGNOSTICS] {len(wire_lengths)} jumper wires; {cuts_total} cuts; "
            f"total straight-line wire length {sum(wire_lengths):.1f} mm; "
            f"longest {max(wire_lengths, default=0):.1f} mm."
        )
        self.log_line("[DIAGNOSTICS] Wire lengths are minimum straight-line estimates, not assembly allowances.")
        for index, length in enumerate(wire_lengths, 1):
            self.log_line(f"[DIAGNOSTICS] W{index:03d}: {length:.1f} mm")
        # Reuse the independent jumper audit rather than silently folding
        # diagonal jumpers into the total wire count.
        from solve.quality_audit import audit_project
        jumper_report = audit_project(self.project)
        jumper_audit = jumper_report["jumper_audit"]
        diagonal_count = jumper_audit["diagonal_count"]
        self.log_line(
            f"[DIAGNOSTICS] Jumper orientation: {len(wire_lengths)} total; "
            f"{diagonal_count} diagonal; "
            f"{len(wire_lengths) - diagonal_count} non-diagonal."
        )
        for wire in jumper_audit["diagonals"]:
            self.log_line(
                f"[DIAGNOSTICS][DIAGONAL] {wire['id']}: "
                f"({wire['from']['row']}, {wire['from']['col']}) -> "
                f"({wire['to']['row']}, {wire['to']['col']}); "
                f"{wire['length_hole_pitches'] * 2.54:.1f} mm."
            )
        for issue in jumper_report["errors"]:
            self.log_line("[DIAGNOSTICS][ERROR] " + issue)
        # Always export the exact project used for the rendered Quick Fit board.
        # The file is overwritten on each successful placement run.
        quick_path = (self.project_path.parent if self.project_path else REPO_ROOT) / "quick.json"
        try:
            temp_path = quick_path.with_name("quick.json.tmp")
            temp_path.write_text(json.dumps(self.project, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            temp_path.replace(quick_path)
            self.log_line(f"[QUICK FIT] Saved rendered board JSON: {quick_path}")
        except OSError as exc:
            self.log_line(f"[QUICK FIT][ERROR] Could not save quick.json: {exc}")
            QMessageBox.warning(self, "Quick JSON export failed", str(exc))
        top_svg, renderer_log = self._render_component_side(self.project)
        self._show_board(top_svg)
        if quick_path.is_file():
            try:
                audit = audit_quick_pads(quick_path)
                self.log_line(
                    f"[QUALITY] {audit['status']} — {audit['checked']} physical pins/pads checked; "
                    f"{audit['off_board_skipped']} excluded components skipped; "
                    f"{len(audit['errors'])} errors."
                )
                for issue in audit["errors"]:
                    self.log_line("[QUALITY][ERROR] " + issue)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.log_line(f"[QUALITY][ERROR] Could not audit quick.json: {exc}")
        self.log_line(
            f"[QUICK FIT] PLACED — {result['placed']} components placed; "
            f"{result.get('excluded', 0)} off-board/excluded."
        )
        self.log_line("[RENDER] Updated component-side placement displayed.")
        self.log_line("[RENDER] Production renderer generated component artwork and both board-side SVGs.")
        if renderer_log:
            self.log_line("[RENDER] " + renderer_log)
        self.statusBar().showMessage(
            "Quick Fit and copper connectivity verified." if routed
            else "Quick Fit complete; copper routing needs attention."
        )

    def _record_pipeline_result(self, result, findings):
        if self.pipeline_run is None:
            return
        self.pipeline_run.record_stage(result, findings)
        group = result.extra.get("workflow_stage", result.stage)
        self.log_line(
            f"[PIPELINE][{group}] {result.stage}: {result.summary or result.status}; "
            f"input={str(result.input_project_sha256 or 'n/a')[:12]} "
            f"output={str(result.output_project_sha256 or 'n/a')[:12]}; "
            f"state saved to {self.pipeline_run.state_path.name}"
        )

    def _record_project_stage(self, stage: str, module: str, report: dict[str, Any]):
        if self.pipeline_run is None or self.project is None:
            return
        from pipeline import StageResult, project_sha256
        current_hash = project_sha256(self.project)
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
            top_svg, renderer_log = self._render_component_side(project)
            self._show_board(top_svg)
            self.log_line("[RENDER] Existing component-side layout rendered with alternating row bands.")
            if renderer_log:
                self.log_line("[RENDER] " + renderer_log)

            tests_passed = self._run_tests()
            if not tests_passed:
                QMessageBox.warning(self, "Tests failed",
                                    "Repository tests failed. The existing board remains displayed; lock questions were not started.")
                return

            self._ask_lock_settings(placed)
        except Exception as exc:
            self.log_line(f"[ERROR] {type(exc).__name__}: {exc}")
            self.log_line(traceback.format_exc())
            QMessageBox.critical(self, "Could not load project", str(exc))

    def closeEvent(self, event):
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