# Route-Mate rendering package

The package owns board-preview rendering code. Application code should import
only the public API from `render/render.py` (or `from render import render_front`).

## Current scope

- Fast component-side SVG preview.
- Board hole field, placed component outlines, pins, labels and jumper wires.
- Net colours where the project JSON identifies the pin nets.
- Off-board parent footprints are not drawn on the board; saved virtual lead-pad positions are deferred.
- Custom project definitions and the common built-in footprints used by the
  Moto/Audio benchmark projects.
- No third-party runtime dependencies; rendering is pure Python and returns an
  SVG string.

The front preview is intended to be regenerated during PREPARE / Quick Set.
It does not run placement, routing, connectivity reconstruction or validation.

## Renderer speed measurements

The WR and Audio fixtures were each rendered 200 times after one warm-up call.
Timing used `time.perf_counter_ns()` around `render_front(project)`.

| Fixture | Average | Median | Minimum | Maximum | SVG output |
|---|---:|---:|---:|---:|---:|
| WR — `benchmarks/moto/moto14wires30cuts.json` | 3.152 ms | 3.100 ms | 2.965 ms | 3.971 ms | 138,093 bytes |
| Audio — `benchmarks/audio/audio10wires38cuts.json` | 3.093 ms | 3.041 ms | 2.893 ms | 4.017 ms | 131,327 bytes |

These are measurements from the user's iMac run. They measure SVG string generation only. They exclude file I/O, SVG parsing/display, rasterisation and GUI interaction. They are a useful baseline for these two fixtures, not a cross-machine guarantee.

The next performance check should measure SVG scene loading and interaction in the desktop GUI. The current generation times do not justify renderer optimisation on their own.

## Deliberately deferred

- Copper-side view, strip segments and cut marks: final-stage renderer only.
- Schematic renderer: optional later addition.
- Detailed physical package artwork and exact visual parity with the legacy
  React renderer: the current Python renderer uses lightweight top-view
  silhouettes for speed.

## Public API

```python
from render import render_front, write_front_svg

svg = render_front(project)
write_front_svg(project, "results/front-preview.svg")
```

`render_front()` returns SVG text and does not write files. Optional arguments:

- `show_labels=True`
- `show_pin_labels=False`
- `scale=1.0`

The package has no application `main.py` integration yet: this repository
currently contains the collector and PREPARE checks, but no GUI/application
entry point. When the main application is added, it should call
`render_front(project)`; it should not import the private modules.

## Module layout

- `render.py`: stable public API and optional SVG file output.
- `_front.py`: fast component-side SVG assembly.
- `_geometry.py`: footprint lookup, rotation and pin/body coordinate mapping.

Private modules are intentionally hidden behind the public API. The copper-side
and schematic renderers can be added under this directory without changing the
application call site.

## GUI integration

The selected desktop GUI stack is PySide6 + Qt Widgets + QGraphicsView.
QtSvg should display the SVG output in the board scene. Keep selection and
highlighting as independent scene overlays so selection changes do not require
a complete board re-render. See [GUI architecture](../docs/GUI.md).

## Source acknowledgement

Footprint rotation and component geometry conventions are based on the GPL-3.0
Stripboard Optimiser implementation by Karlo Funke:
https://github.com/KarloFunke/stripboard-editor

The current Python renderer is a lightweight independent implementation, not a
byte-for-byte port of the legacy SVG renderer. See the repository's
`licenses/GPL-3.0.txt` for the applicable licence text.


## Production renderer deployment (consolidated)


Route-Mate uses the standalone production renderer from
`bigbadevilaussie-hue/stripboard-optimiser`, not the earlier simplified Python
prototype in this repository.

On first project load, Route-Mate performs a sparse Git checkout of
`src/frontend/standalone-renderer/dist` into:

`~/.cache/route-mate/stripboard-optimiser`

This downloads only the compiled standalone renderer path. It does not install
or run React, Next.js, a browser, or the full frontend. Git and Node.js must be
installed and available on PATH. Subsequent renders use the cached checkout.

The GUI presents both outputs from the same renderer invocation in separate tabs:
- Component side: `board-top.svg`
- Copper side: `board-copper.svg`

Route-Mate adds subtle alternating row bands to the component-side SVG and
1-based coordinate rulers to both board-side SVGs. Column labels align with hole
centres across the top; row labels align down the left. The copper-side column
labels run in mirrored visual order. These overlays do not change upstream board
geometry. The toolbar can export either displayed side as an SVG file. PNG/JPG export and interactive
component selection/highlighting are not implemented yet.

The upstream renderer README documents parity against its original React
renderer, including exact full-SVG matches for the 24x56 Moto fixture with
32 placed components, 14 wires and 30 cuts. Route-Mate delegates rendering to
that implementation rather than maintaining a second geometry/artwork engine.
