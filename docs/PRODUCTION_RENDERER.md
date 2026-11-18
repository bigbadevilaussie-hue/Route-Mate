# Production board renderer

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

Route-Mate adds subtle alternating row bands behind both SVGs without changing
the upstream renderer's component, pin, copper, wire or cut geometry. The toolbar
can export either displayed side as an SVG file. PNG/JPG export and interactive
component selection/highlighting are not implemented yet.

The upstream renderer README documents parity against its original React
renderer, including exact full-SVG matches for the 24x56 Moto fixture with
32 placed components, 14 wires and 30 cuts. Route-Mate delegates rendering to
that implementation rather than maintaining a second geometry/artwork engine.
