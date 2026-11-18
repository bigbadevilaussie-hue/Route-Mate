"""Bridge to the parity-tested standalone stripboard renderer.

The renderer is fetched as a sparse checkout of the upstream project on first use.
Only the compiled standalone renderer is checked out; no React frontend is needed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


UPSTREAM = "https://github.com/bigbadevilaussie-hue/stripboard-optimiser.git"
CACHE = Path.home() / ".cache" / "route-mate" / "stripboard-optimiser"
SPARSE_PATH = "src/frontend/standalone-renderer/dist"
CLI = CACHE / SPARSE_PATH / "standalone-renderer" / "cli.js"



def add_alternating_row_bands(svg: str, rows: int, *, pitch: float = 30.0, origin: float = 60.0) -> str:
    """Add subtle alternating row bands behind the production SVG artwork."""
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
            '<rect x="{0:g}" y="{1:g}" width="{2:g}" height="{3:g}" fill="#f1f3f5" opacity="0.72" data-route-mate-row-band="1"/>'.format(
                x, band_y, width, pitch
            )
        )
    insertion = "".join(bands)
    return re.sub(r'(<svg\b[^>]*>)', lambda m: m.group(1) + insertion, svg, count=1)


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
            raise RuntimeError("Could not fetch production renderer:\n" + result.stdout)
    result = _run(["git", "sparse-checkout", "set", SPARSE_PATH], cwd=CACHE)
    if result.returncode:
        raise RuntimeError("Could not prepare production renderer:\n" + result.stdout)
    if not CLI.is_file():
        raise RuntimeError(f"Production renderer CLI is missing: {CLI}")
    return CLI


def render_project(project_path: Path, output_dir: Path) -> tuple[str, str, str]:
    cli = ensure_renderer()
    output_dir.mkdir(parents=True, exist_ok=True)
    result = _run([
        "node", str(cli), str(project_path), "--output", str(output_dir),
    ])
    if result.returncode:
        raise RuntimeError("Production renderer failed:\n" + result.stdout)
    top = output_dir / "board-top.svg"
    copper = output_dir / "board-copper.svg"
    if not top.is_file() or not copper.is_file():
        raise RuntimeError("Production renderer did not produce both board SVGs.")
    return top.read_text(encoding="utf-8"), copper.read_text(encoding="utf-8"), result.stdout.strip()
