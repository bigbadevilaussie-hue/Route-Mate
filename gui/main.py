"""Route-Mate desktop GUI: project log on the left, rendered board on the right."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QAction, QBrush, QColor, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QToolBar,
)


class BoardView(QGraphicsView):
    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setBackgroundBrush(QBrush(QColor("#20252b")))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def show_svg(self, svg: str) -> None:
        scene = self.scene()
        scene.clear()
        item = QGraphicsSvgItem()
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")), item)
        if not renderer.isValid():
            raise ValueError("The board renderer produced invalid SVG.")
        item.setSharedRenderer(renderer)
        scene.addItem(item)
        scene.setSceneRect(item.boundingRect())
        self.resetTransform()
        self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class RouteMateWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Route-Mate")
        self.resize(1500, 900)
        self.project: dict[str, Any] | None = None
        self.project_path: Path | None = None

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        load_action = QAction("Load JSON", self)
        load_action.triggered.connect(self.load_json)
        toolbar.addAction(load_action)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText("Route-Mate running log")
        self.board = BoardView()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.log)
        splitter.addWidget(self.board)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([390, 1110])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage("Ready. Load a project JSON to begin.")
        self.log_line("Route-Mate ready.")
        self.log_line("Load a project JSON to render its current board.")

    def log_line(self, message: str) -> None:
        self.log.appendPlainText(message)

    def load_json(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Route-Mate project",
            str(self.project_path.parent if self.project_path else Path.home()),
            "Project JSON (*.json);;All files (*)",
        )
        if not filename:
            return
        path = Path(filename)
        self.log_line("")
        self.log_line(f"--- LOAD PROJECT: {path.name} ---")
        try:
            project = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(project, dict):
                raise ValueError("The project JSON root must be an object.")
            from render import render_front

            svg = render_front(project)
            self.board.show_svg(svg)
        except Exception as exc:
            self.log_line(f"[ERROR] {type(exc).__name__}: {exc}")
            QMessageBox.critical(self, "Could not load project", str(exc))
            return

        self.project = project
        self.project_path = path
        board = project.get("board", {})
        components = project.get("components", [])
        placed = sum(c.get("boardPos") is not None for c in components)
        offboard = sum(bool(c.get("offBoard")) for c in components)
        self.log_line(f"[PROJECT] {project.get('name', path.stem)}")
        self.log_line(
            f"[BOARD] {board.get('rows', '?')} Rows x "
            f"{board.get('cols', '?')} Cols"
        )
        self.log_line(f"[INFO] Components: {len(components)}")
        self.log_line(f"[INFO] Placed: {placed}")
        self.log_line(f"[INFO] Off-board: {offboard}")
        self.log_line("[RENDER] Current board rendered.")
        self.statusBar().showMessage(f"Loaded {path.name}")

    def closeEvent(self, event) -> None:  # noqa: N802
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Route-Mate")
    window = RouteMateWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
