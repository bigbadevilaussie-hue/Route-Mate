"""Route-Mate desktop GUI: project log on the left, production board views on the right."""
from __future__ import annotations
import json,re,sys,tempfile
from pathlib import Path
from typing import Any
from PySide6.QtCore import Qt,QByteArray
from PySide6.QtGui import QAction,QBrush,QColor,QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QApplication,QFileDialog,QGraphicsScene,QGraphicsView,QMainWindow,QMessageBox,QPlainTextEdit,QSplitter,QTabWidget,QToolBar

class BoardView(QGraphicsView):
    def __init__(self):
        super().__init__(); self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing|QPainter.RenderHint.TextAntialiasing|QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#f2f2f2"))); self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse); self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._renderer=None
    def fit_board(self):
        self.resetTransform()
        self.fitInView(self.scene().sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)
    def wheelEvent(self,event):
        if event.angleDelta().y() > 0: factor=1.25
        else: factor=0.8
        self.scale(factor,factor)
        event.accept()
    def show_svg(self,svg:str):
        # Darken SVG labels for readability on the light desktop canvas.
        svg=re.sub(r"(<svg\b[^>]*>)",r"\1<style>text{fill:#000000!important;stroke:#f3e5bf!important;stroke-width:0.55px!important;paint-order:stroke fill!important;stroke-linejoin:round!important;font-weight:700!important;opacity:1!important;} tspan{fill:#000000!important;stroke:#f3e5bf!important;stroke-width:0.55px!important;font-weight:700!important;opacity:1!important;}</style>",svg,count=1)
        scene=self.scene(); scene.clear(); data=QByteArray(svg.encode("utf-8"))
        renderer=QSvgRenderer(data)
        if not renderer.isValid(): raise ValueError("Production renderer produced invalid SVG.")
        item=QGraphicsSvgItem()
        item.setSharedRenderer(renderer)
        scene.addItem(item)
        self._renderer=renderer
        scene.setSceneRect(item.boundingRect())
        self.fit_board()

class RouteMateWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Route-Mate"); self.resize(1500,900)
        self.project:dict[str,Any]|None=None; self.project_path:Path|None=None
        toolbar=QToolBar("Main"); toolbar.setMovable(False); self.addToolBar(toolbar)
        action=QAction("Load JSON",self); action.triggered.connect(self.load_json); toolbar.addAction(action)
        fit_action=QAction("Fit board",self); fit_action.triggered.connect(self.fit_current_board); toolbar.addAction(fit_action)
        self.log=QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(5000); self.log.setPlaceholderText("Route-Mate running log")
        self.top_view=BoardView(); self.copper_view=BoardView(); self.views=QTabWidget()
        self.views.addTab(self.top_view,"Component side"); self.views.addTab(self.copper_view,"Copper side")
        split=QSplitter(Qt.Orientation.Horizontal); split.addWidget(self.log); split.addWidget(self.views)
        split.setStretchFactor(0,0); split.setStretchFactor(1,1); split.setSizes([390,1110]); self.setCentralWidget(split)
        self.statusBar().showMessage("Ready. Load a project JSON to begin.")
        self.log_line("Route-Mate ready."); self.log_line("Load a project JSON to render its current board.")
        self.log_line("Renderer: upstream production standalone renderer.")
    def log_line(self,message:str): self.log.appendPlainText(message)
    def fit_current_board(self):
        view=self.top_view if self.views.currentWidget() is self.top_view else self.copper_view
        view.fit_board()
    def load_json(self):
        filename,_=QFileDialog.getOpenFileName(self,"Load Route-Mate project",str(self.project_path.parent if self.project_path else Path.home()),"Project JSON (*.json);;All files (*)")
        if not filename:return
        path=Path(filename); self.log_line(""); self.log_line(f"--- LOAD PROJECT: {path.name} ---")
        try:
            project=json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(project,dict): raise ValueError("Project JSON root must be an object.")
            from render.standalone_bridge import render_project
            output=Path(tempfile.mkdtemp(prefix="route-mate-render-"))
            top,copper,report=render_project(path,output)
            self.top_view.show_svg(top); self.copper_view.show_svg(copper)
        except Exception as exc:
            self.log_line(f"[ERROR] {type(exc).__name__}: {exc}"); QMessageBox.critical(self,"Could not render project",str(exc)); return
        self.project=project; self.project_path=path
        board=project.get("board",{}); comps=project.get("components",[])
        self.log_line(f"[PROJECT] {project.get('name',path.stem)}")
        self.log_line(f"[BOARD] {board.get('rows','?')} Rows x {board.get('cols','?')} Cols")
        self.log_line(f"[INFO] Components: {len(comps)}")
        self.log_line(f"[INFO] Placed: {sum(c.get('boardPos') is not None for c in comps)}")
        self.log_line(f"[INFO] Off-board: {sum(bool(c.get('offBoard')) for c in comps)}")
        for line in report.splitlines(): self.log_line(f"[RENDER] {line}")
        self.log_line("[RENDER] Production component-side and copper-side SVGs loaded.")
        self.statusBar().showMessage(f"Loaded {path.name}")
    def closeEvent(self,event): event.accept()
def main():
    app=QApplication(sys.argv); app.setApplicationName("Route-Mate")
    window=RouteMateWindow(); window.show(); return app.exec()
if __name__=="__main__": raise SystemExit(main())
