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
