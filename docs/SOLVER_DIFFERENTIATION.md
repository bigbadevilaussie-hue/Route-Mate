# Route-Mate solver direction — not a Python clone of Karl

Decision: 2026-11-21. Develop on `main`. Original reference is
`KarloFunke/stripboard-editor` at commit
`21e2373f6e1da44ce017be234b2df04f42d3af30`, **not**
`bigbadevilaussie-hue/stripboard-optimiser` (the user's tuned fork).

## Design objective

Maximise **verified board quality per CPU-second** on identical hardware and
equivalent constraints, rather than imitating Karl's moves/effort slider or
translating his full TypeScript/C decoder into Python.

## Existing Route-Mate intelligence to preserve

`solve/quick_fit.py` already scores candidate component placements by
distance to pins of connected nets, checks footprint occupancy and pin
adjacency, and handles locked components. Do **not** reimplement this logic
blindly as a second 'net-aware' module. `solve/skeleton.py` is an isolated
sequence-pair experiment, **not** the production solver or an agreed mandate
to port the entire Karl V5 decoder.

## Solver plan

1. **Measure first:** establish repeatable Moto baseline (runtime, wires,
   length, diagonals, cuts, legality), including the current Route-Mate
   baseline. Compare with original upstream Karl only when equivalent
   inputs, routing constraints and hardware can be established.
2. **Build a verified candidate evaluator:** use existing physical geometry,
   legal copper segmentation and independent electrical/physical checks.
   Reject illegal candidates rather than letting soft penalties certify them.
3. **Targeted moves:** identify nets responsible for excess jumpers and
   propose pin-row alignment, component swaps, cluster shifts and local
   rotation; maintain hard locks and board bounds.
4. **Incremental invalidation:** cache local footprint and net data; recompute
   affected nets where sound, and always run full independent verification
   before accepting an output.
5. **Search strategy:** deterministic, bounded Quick Solve first; reuse
   the same primitives in multi-seed, deeper Hell Mode. Keep a fallback
   exploration mechanism so guided moves do not trap search prematurely.
6. **Profile before native optimisation:** Python orchestrates search; move
   expensive, proven hot loops into compiled code only when benchmarks
   demonstrate benefit. No unsupported claims of speedups.

## Optimisation contract

Legality precedes ranking. Among legal candidates prioritise jumper count,
total wire length, and diagonal count; cuts are a minor tiebreaker. A few
shorter wires can sometimes justify an extra jumper depending on calibrated
weights. No final weights are frozen.

Quick Solve's relaxed profile permits at most
`floor(0.10 * number_of_wires)` diagonals; this is not strict physical PASS.
Hell Mode's target is zero diagonals. Strict physical specification remains
unchanged. Independent verification must distinguish profiles explicitly.

## Next implementation gate

Before integrating `solve/skeleton.py` into Quick Solve, demonstrate that
its proposed placements improve the existing `quick_fit.py` baseline on
a legal, routed and verified candidate. A skeleton-only rectangle packing
score is **not** a proxy for routing quality.

Karl receives full credit for original algorithmic ideas. Respect GPL-3.0
for any adapted source code; attribution alone is insufficient.
