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

The GUI presents both outputs from the same renderer invocation:
- Component side: `board-top.svg`
- Copper side: `board-copper.svg`

The upstream renderer README documents parity against its original React
renderer, including exact full-SVG matches for the 24x56 Moto fixture with
32 placed components, 14 wires and 30 cuts. Route-Mate delegates rendering to
that implementation rather than maintaining a second geometry/artwork engine.
