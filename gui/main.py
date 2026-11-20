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

GUI_VERSION = "1.26"
CODE_VERSION = "1.26"

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
        self.unlocked = QRadioButton("Unlocked — remove from board")
        self.edge = QCheckBox("Edge constrained")
        self.slide = QCheckBox("May slide along edge")
        # Preserve the established GUI meaning: unlocked parts are removed
        # from the board preview; edge/slide apply only to retained parts.
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

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        load_action = QAction("Load JSON", self)
        load_action.triggered.connect(self.load_json)
        toolbar.addAction(load_action)
        pipeline_action = QAction("Pipeline State", self)
        pipeline_action.triggered.connect(self.show_pipeline_state)
        toolbar.addAction(pipeline_action)

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
        self.log_line("Workflow: collect → electrical sanity → render existing layout → tests → constraints → Quick Fit → copper route/verify → updated render.")
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
        from render import render_front

        # render_front is the public production-renderer API. It supplies the
        # parity-tested artwork, row bands and optional review highlight.
        top_svg = render_front(project, highlight_component_id=highlight_component_id)
        return top_svg, "production standalone renderer"

    def _show_board(self, top_svg: str):
        self.top_view.show_svg(top_svg)

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
                    f"Remove={values['remove']}"
                )

                # Apply each answer immediately, then redraw before asking about
                # the next component. This preserves the original interactive flow.
                if values["remove"]:
                    component["boardExcluded"] = True
                    component.pop("boardPos", None)
                    component.pop("flexibleEndPos", None)
                    component.pop("locked", None)
                    component.pop("edge", None)
                    component.pop("slide", None)
                    self.log_line(f"[PLACEMENT] Removed {label} from the board.")
                else:
                    component["locked"] = bool(values["locked"])
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

        # Quick Fit follows the established prompt/remove/render flow.
        # Do not pass unsupported edge/slide constraints to Quick Fit.
        unsupported = [
            component for component in placed
            if not component.get("boardExcluded")
            and not component.get("offBoard")
            and (
                self.presolve_constraints.get(str(component.get("id")), {}).get("edge")
                or self.presolve_constraints.get(str(component.get("id")), {}).get("slide")
            )
        ]
        if unsupported:
            labels = ", ".join(str(c.get("label") or c.get("id")) for c in unsupported)
            self.log_line(
                "[QUICK FIT] Not started: Quick Fit does not yet implement "
                f"hard edge anchors/sliding ({labels}). The latest board preview is retained."
            )
            self.statusBar().showMessage("Constraints collected; edge/slide solver support is pending.")
            return

        self.log_line("[QUICK FIT] Running shared deterministic net-aware placement engine...")
        from pipeline import quick_fit_stage_result
        from solve import quick_fit
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
        top_svg, renderer_log = self._render_component_side(self.project)
        self._show_board(top_svg)
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
        self.log_line(
            f"[PIPELINE] {result.stage}: {result.summary or result.status}; "
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