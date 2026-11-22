"""Bridge to the parity-tested standalone stripboard production renderer.

The production renderer is the single source of board artwork for the GUI.
It is fetched as a sparse checkout of the upstream project on first use.
Route-Mate's mounting policy is applied before production rendering.
"""
from __future__ import annotations

import json
import shutil
import sys
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
    match = re.search(r'<svg\b[^>]*\bviewBox="([^"]+)"', svg)
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
            f'<rect x="{x:g}" y="{band_y:g}" width="{width:g}" height="{pitch:g}" '
            'fill="#f1f3f5" opacity="0.72" data-route-mate-row-band="1"/>'
        )
    insertion = "".join(bands)
    return re.sub(r'(<svg\b[^>]*>)', lambda m: m.group(1) + insertion, svg, count=1)


def add_board_coordinate_labels(
    svg: str, rows: int, cols: int, *,
    pitch: float = HOLE_PITCH, origin: float = HOLE_ORIGIN,
    mirrored: bool = False,
) -> str:
    """Add unobtrusive 1-based row and column labels aligned to board holes."""
    import re

    if type(rows) is not int or rows < 1:
        raise ValueError("rows must be a positive integer")
    if type(cols) is not int or cols < 1:
        raise ValueError("cols must be a positive integer")
    if pitch <= 0:
        raise ValueError("pitch must be positive")
    if not re.search(r'<svg\b[^>]*\bviewBox="[^"]+"', svg):
        raise ValueError("Renderer SVG has no viewBox")

    # The production renderer's R0·C0 caption is superseded by these rulers.
    svg = re.sub(
        r'<text\b[^>]*>[^<]*R0·C0[^<]*</text>', "", svg, count=1
    )
    labels = []
    label_y = origin - 22
    for col in range(cols):
        visual_col = cols - 1 - col if mirrored else col
        number = col + 1
        x = origin + visual_col * pitch
        labels.append(
            f'<text x="{x:g}" y="{label_y:g}" text-anchor="middle" '
            'font-family="sans-serif" font-size="10" font-weight="400" '
            'fill="#555" data-route-mate-column="' + str(number) + '">'
            + str(number) + '</text>'
        )
    label_x = origin - 22
    for row in range(rows):
        y = origin + row * pitch + 3
        number = row + 1
        labels.append(
            f'<text x="{label_x:g}" y="{y:g}" text-anchor="end" '
            'font-family="sans-serif" font-size="10" font-weight="400" '
            'fill="#555" data-route-mate-row="' + str(number) + '">'
            + str(number) + '</text>'
        )
    return re.sub(r'</svg\s*>', "".join(labels) + '</svg>', svg, count=1)



def add_offboard_terminals(svg: str, project: dict[str, Any]) -> str:
    """Draw selectable-style ring terminals at the allocated off-board holes."""
    import re
    from html import escape
    from placement_policy import is_off_board_component

    marks = []
    for component in project.get("components", []):
        if not isinstance(component, dict) or not is_off_board_component(component):
            continue
        if component.get("boardExcluded") is True and component.get("offBoard") is not True:
            continue
        label = str(component.get("label") or component.get("id"))
        for pin, point in (component.get("leads") or {}).items():
            row, col = int(point["row"]), int(point["col"])
            x = HOLE_ORIGIN + col * HOLE_PITCH
            y = HOLE_ORIGIN + row * HOLE_PITCH
            name = escape(f"{label} {pin}")
            marks.append(
                f'<g data-route-mate-terminal="{escape(str(component.get("id")))}" '
                f'data-pin="{escape(str(pin))}" data-row="{row}" data-col="{col}">'
                f'<circle cx="{x:g}" cy="{y:g}" r="11" fill="#ffffff" '
                f'fill-opacity="0.9" stroke="#dc5555" stroke-width="4"/>'
                f'<circle cx="{x:g}" cy="{y:g}" r="4.5" fill="#b32828"/>'
                f'<text x="{x:g}" y="{y-15:g}" text-anchor="middle" '
                f'font-family="sans-serif" font-size="11" font-weight="600" '
                f'fill="#222">{name}</text></g>'
            )
    return re.sub(r'</svg\s*>', lambda m: ''.join(marks) + m.group(0), svg, count=1)


def add_top_side_cuts(svg: str, project: dict[str, Any]) -> str:
    """Mark routed copper cuts on the component-side preview at their exact locations.

    These are reference markers: cuts are physically made on the copper side.
    Coordinates are zero-based in project JSON and use the production hole grid.
    """
    import re
    from html import escape

    board = project.get("board", {})
    rows, cols = int(board.get("rows", 0)), int(board.get("cols", 0))
    cuts = board.get("cuts", [])
    if not isinstance(cuts, list) or not cuts:
        return svg
    marks = []
    for index, cut in enumerate(cuts, 1):
        if not isinstance(cut, dict):
            continue
        row, col = cut.get("row"), cut.get("col")
        if type(row) is not int or type(col) is not int:
            continue
        kind = cut.get("kind", "between")
        if not (0 <= row < rows and 0 <= col < cols):
            continue
        if kind == "between":
            if col >= cols - 1:
                continue
            x = HOLE_ORIGIN + (col + 0.5) * HOLE_PITCH
        elif kind == "hole":
            x = HOLE_ORIGIN + col * HOLE_PITCH
        else:
            continue
        y = HOLE_ORIGIN + row * HOLE_PITCH
        # Match the copper-side cut symbol: a plain red X, no surrounding circle.
        marks.append(
            f'<g data-route-mate-cut="{index}" data-cut-row="{row}" '
            f'data-cut-col="{col}" data-cut-kind="{escape(str(kind))}">'
            f'<path d="M {x-7:g} {y-7:g} L {x+7:g} {y+7:g} '
            f'M {x+7:g} {y-7:g} L {x-7:g} {y+7:g}" '
            f'stroke="#ff2424" stroke-width="4" stroke-linecap="round"/>'
            '</g>'
        )
    return re.sub(r'</svg\s*>', lambda m: ''.join(marks) + m.group(0), svg, count=1)


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
    return re.sub(r'</svg\s*>', overlay + '</svg>', svg, count=1)


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=str(cwd) if cwd else None, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )


def _bundled_runtime() -> tuple[Path, Path] | None:
    """Use the included standalone renderer and Node when PyInstaller-frozen."""
    if not getattr(sys, "frozen", False):
        return None
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    node = root / "renderer-runtime" / "node"
    cli = root / "renderer-runtime" / "standalone-renderer" / "cli.js"
    if not node.is_file() or not cli.is_file():
        raise RuntimeError("Standalone app is missing its bundled Node.js renderer.")
    return node, cli


def ensure_renderer() -> Path:
    bundled = _bundled_runtime()
    if bundled is not None:
        return bundled[1]
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
            raise RuntimeError("Could not fetch production renderer:\n" + result.stdout)
    result = _run(["git", "sparse-checkout", "set", SPARSE_PATH], cwd=CACHE)
    if result.returncode:
        raise RuntimeError("Could not prepare production renderer:\n" + result.stdout)
    if not CLI.is_file():
        raise RuntimeError(f"Production renderer CLI is missing: {CLI}")
    return CLI


def _renderer_input(project: dict[str, Any]) -> dict[str, Any]:
    """Copy the project and remove components not mounted on the stripboard."""
    from placement_policy import is_off_board_component

    render_project = dict(project)
    components = project.get("components", [])
    if isinstance(components, list):
        render_project["components"] = [
            component for component in components
            if not is_off_board_component(component)
        ]
    return render_project


def render_project(
    project_path: Path, output_dir: Path, *,
    highlight_component_id: str | None = None,
) -> tuple[str, str, str]:
    """Render both production board sides and return top SVG, copper SVG and log."""
    cli = ensure_renderer()
    source_project = json.loads(project_path.read_text(encoding="utf-8"))
    project = _renderer_input(source_project)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Never rewrite the caller's project file: the production renderer receives
    # a temporary copy with Route-Mate's off-board mounting policy applied.
    with tempfile.TemporaryDirectory(prefix="route-mate-render-input-") as tmp:
        render_input = Path(tmp) / "project.json"
        render_input.write_text(
            json.dumps(project, ensure_ascii=False), encoding="utf-8"
        )
        runtime = _bundled_runtime()
        node = str(runtime[0]) if runtime else "node"
        result = _run([
            node, str(cli), str(render_input), "--output", str(output_dir),
        ])
    if result.returncode:
        raise RuntimeError("Production renderer failed:\n" + result.stdout)
    top = output_dir / "board-top.svg"
    copper = output_dir / "board-copper.svg"
    if not top.is_file() or not copper.is_file():
        raise RuntimeError("Production renderer did not produce both board SVGs.")

    rows = int(project["board"]["rows"])
    cols = int(project["board"]["cols"])
    top_svg = add_alternating_row_bands(top.read_text(encoding="utf-8"), rows)
    top_svg = add_top_side_cuts(top_svg, project)
    top_svg = add_offboard_terminals(top_svg, source_project)
    top_svg = add_component_highlight(top_svg, project, highlight_component_id)
    top_svg = add_board_coordinate_labels(top_svg, rows, cols)
    copper_svg = add_board_coordinate_labels(
        copper.read_text(encoding="utf-8"), rows, cols, mirrored=True
    )
    return top_svg, copper_svg, result.stdout.strip()


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
