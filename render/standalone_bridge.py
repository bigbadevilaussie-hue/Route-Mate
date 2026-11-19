"""Bridge to the parity-tested standalone stripboard production renderer.

The production renderer is the single source of board artwork for the GUI.
It is fetched as a sparse checkout of the upstream project on first use.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


UPSTREAM = "https://github.com/bigbadevilaussie-hue/stripboard-optimiser.git"
CACHE = Path.home() / ".cache" / "route-mate" / "stripboard-optimiser"
SPARSE_PATH = "src/frontend/standalone-renderer/dist"
CLI = CACHE / SPARSE_PATH / "standalone-renderer" / "cli.js"
HOLE_PITCH = 30.0
HOLE_ORIGIN = 60.0


def add_alternating_row_bands(
    svg: str, rows: int, *, pitch: float = HOLE_PITCH, origin: float = HOLE_ORIGIN
) -> str:
    """Add alternating row bands behind the production SVG artwork."""
    import re

    if type(rows) is not int or rows < 1:
        raise ValueError("rows must be a positive integer")
    match = re.search(r'<svg\\b[^>]*\\bviewBox="([^"]+)"', svg)
    if not match:
        raise ValueError("Renderer SVG has no viewBox")
    values = [float(value) for value in match.group(1).replace(",", " ").split()]
    if len(values) != 4:
        raise ValueError("Renderer SVG has an invalid viewBox")
    x, _y, width, _height = values
    bands = []
    for row in range(rows):
        if row % 2 == 0:
            continue
        band_y = origin + row * pitch - pitch / 2
        bands.append(
            '<rect x="{0:g}" y="{1:g}" width="{2:g}" height="{3:g}" '
            'fill="#f1f3f5" opacity="0.72" data-route-mate-row-band="1"/>'.format(
                x, band_y, width
            )
        )
    insertion = "".join(bands)
    return re.sub(r'(<svg\\b[^>]*>)', lambda m: m.group(1) + insertion, svg, count=1)


def add_component_highlight(
    svg: str, project: dict[str, Any], component_id: str | None
) -> str:
    """Overlay a selection outline using the shared board-footprint geometry."""
    if component_id is None:
        return svg

    import re
    from board_geometry import BUILTIN_DEFS, component_geometry, resolve_definition

    component = next(
        (item for item in project.get("components", [])
         if isinstance(item, dict) and str(item.get("id")) == str(component_id)),
        None,
    )
    if component is None or not isinstance(component.get("boardPos"), dict):
        return svg

    definitions = dict(BUILTIN_DEFS)
    for definition in project.get("componentDefs", []):
        if isinstance(definition, dict) and definition.get("id"):
            definitions[str(definition["id"])] = definition
    definition = resolve_definition(component, definitions)

    if definition:
        pins, body_cells = component_geometry(component, definition)
        points = [(int(pin["row"]), int(pin["col"])) for pin in pins]
        points.extend((int(row), int(col)) for row, col in body_cells)
    else:
        pos = component["boardPos"]
        points = [(int(pos.get("row", 0)), int(pos.get("col", 0)))]

    if not points:
        return svg

    min_row = min(row for row, _ in points)
    max_row = max(row for row, _ in points)
    min_col = min(col for _, col in points)
    max_col = max(col for _, col in points)
    pad = 17.0
    x = HOLE_ORIGIN + min_col * HOLE_PITCH - pad
    y = HOLE_ORIGIN + min_row * HOLE_PITCH - pad
    width = (max_col - min_col) * HOLE_PITCH + pad * 2
    height = (max_row - min_row) * HOLE_PITCH + pad * 2
    overlay = (
        f'<rect x="{x:g}" y="{y:g}" width="{width:g}" height="{height:g}" '
        'rx="8" fill="#f59e0b" fill-opacity="0.12" stroke="#f97316" '
        'stroke-width="3.5" stroke-dasharray="7 4" '
        'data-route-mate-highlight="1"/>'
    )
    return re.sub(r'</svg\\s*>', overlay + '</svg>', svg, count=1)


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=str(cwd) if cwd else None, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )


def ensure_renderer() -> Path:
    if not shutil.which("git"):
        raise RuntimeError("Git is required to install the production stripboard renderer.")
    if not shutil.which("node"):
        raise RuntimeError("Node.js is required to run the production stripboard renderer.")

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not (CACHE / ".git").is_dir():
        result = _run([
            "git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
            UPSTREAM, str(CACHE),
        ])
        if result.returncode:
            raise RuntimeError("Could not fetch production renderer:\\n" + result.stdout)
    result = _run(["git", "sparse-checkout", "set", SPARSE_PATH], cwd=CACHE)
    if result.returncode:
        raise RuntimeError("Could not prepare production renderer:\\n" + result.stdout)
    if not CLI.is_file():
        raise RuntimeError(f"Production renderer CLI is missing: {CLI}")
    return CLI


def render_project(
    project_path: Path, output_dir: Path, *,
    highlight_component_id: str | None = None,
) -> tuple[str, str, str]:
    """Render both production board sides and return top SVG, copper SVG and log."""
    cli = ensure_renderer()
    output_dir.mkdir(parents=True, exist_ok=True)
    result = _run([
        "node", str(cli), str(project_path), "--output", str(output_dir),
    ])
    if result.returncode:
        raise RuntimeError("Production renderer failed:\\n" + result.stdout)
    top = output_dir / "board-top.svg"
    copper = output_dir / "board-copper.svg"
    if not top.is_file() or not copper.is_file():
        raise RuntimeError("Production renderer did not produce both board SVGs.")

    project = json.loads(project_path.read_text(encoding="utf-8"))
    top_svg = add_alternating_row_bands(
        top.read_text(encoding="utf-8"), int(project["board"]["rows"])
    )
    top_svg = add_component_highlight(top_svg, project, highlight_component_id)
    return top_svg, copper.read_text(encoding="utf-8"), result.stdout.strip()


def render_project_data(
    project: dict[str, Any], *, highlight_component_id: str | None = None
) -> tuple[str, str, str]:
    """Render an in-memory project through the production renderer."""
    with tempfile.TemporaryDirectory(prefix="route-mate-render-") as tmp:
        root = Path(tmp)
        project_path = root / "project.json"
        project_path.write_text(
            json.dumps(project, ensure_ascii=False), encoding="utf-8"
        )
        return render_project(
            project_path, root / "output",
            highlight_component_id=highlight_component_id,
        )
