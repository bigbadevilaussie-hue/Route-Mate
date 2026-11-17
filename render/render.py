"""Public renderer API used by the Route-Mate application.

The main application should import this module, not the private rendering
implementation. The front renderer returns SVG text and performs no file I/O
unless write_front_svg() is explicitly called.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._front import render_front_board


def render_front(
    project: dict[str, Any],
    *,
    show_labels: bool = True,
    show_pin_labels: bool = False,
    scale: float = 1.0,
) -> str:
    """Return a fast component-side SVG preview for a Route-Mate project."""
    return render_front_board(
        project,
        show_labels=show_labels,
        show_pin_labels=show_pin_labels,
        scale=scale,
    )


def render_front_svg(
    project: dict[str, Any],
    *,
    show_labels: bool = True,
    show_pin_labels: bool = False,
    scale: float = 1.0,
) -> str:
    """Explicitly named alias for render_front()."""
    return render_front(
        project,
        show_labels=show_labels,
        show_pin_labels=show_pin_labels,
        scale=scale,
    )


def write_front_svg(
    project: dict[str, Any],
    destination: str | Path,
    *,
    show_labels: bool = True,
    show_pin_labels: bool = False,
    scale: float = 1.0,
) -> Path:
    """Render and write one component-side SVG file."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_front(
            project,
            show_labels=show_labels,
            show_pin_labels=show_pin_labels,
            scale=scale,
        ),
        encoding="utf-8",
    )
    return path
