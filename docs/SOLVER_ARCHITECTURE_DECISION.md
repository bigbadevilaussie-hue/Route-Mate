# Solver Architecture Decision — Quick Solve and Hell Mode

**Status:** Approved design direction, not implemented capability.
**Authority:** [PHYSICAL_MODEL_SPEC.md](PHYSICAL_MODEL_SPEC.md) remains LOCKED and overrides this document. Do not skip its implementation gates.

## One engine, two search modes

- **Quick Solve:** fast deterministic bounded search for a candidate that passes independent electrical AND physical verification. If none is found, report *not found within budget*, never proven impossible.
- **Hell Mode:** deeper optimisation over the same model, constraints and routing primitives. Start from a verified Quick Solve result when available; continue exploring even if Quick Solve found none.
- **Shared:** board geometry, component and edge locks, cut legality, copper connectivity, jumper geometry, scoring, project data and independent electrical/physical verifier.
- **Hard constraints are not cost penalties.** No out-of-board placement, displaced hard locks, inaccessible cuts, forbidden jumper directions, body crossings, wire interference or electrical faults can be legalised by a good score.
- **Rank legal solutions only:** feasibility first; then transparent board area, jumper count, wire length, cuts and construction quality. Record input hash, seed, evaluation budget, engine version and results.

## Karl's algorithms to study and adapt

Reference: [Karlo Funke's Stripboard Editor](https://github.com/KarloFunke/stripboard-editor) and the [modified Stripboard Optimiser fork](https://github.com/bigbadevilaussie-hue/stripboard-optimiser).

| Technique | Route-Mate improvement |
|---|---|
| Discrete skeleton and sequence-pair placement | Efficient arrangement search with hard physical feasibility |
| Exact decoder, weighted union-find and difference constraints | Solve relative pin/group positions while enforcing locks and bounds |
| Longest-path compaction | Fit legal components within purchased board dimensions |
| Net grouping and copper segmentation | Reuse copper without shorts or inaccessible cuts |
| Prim-style free-hole jumper connection | Only legal straight vertical jumpers, full-body clearance checked |
| Obstacle geometry and wire-mess scoring | Reject forbidden collisions instead of merely penalising them |
| Cut relocation, slant repair, targeted completion repair | Only transformations consistent with locked between-hole cuts and vertical wires |
| Simulated annealing and move operators | Hell Mode search, not Quick Solve's deterministic fast path |
| Multi-seed portfolios and board cost breakdown | Fixed evaluation budgets, reproducible ranking, transparent metrics |
| Native C/WASM evaluation kernel | Possible speed-up with one shared algorithm, not diverging solvers |

**Research candidates, not commitments to copy source code.** Karl's edge/size preferences and wire-mess costs are not substitutes for Route-Mate hard constraints. Reported WR-input and soft-lock failures require separate verification; they are not established by this document.

## Implementation order

1. Complete the locked physical-model gates and independent electrical/physical verification.
2. Build a constraint-aware placement decoder and legal copper segmentation.
3. Implement obstacle-aware routing under the locked vertical-jumper model.
4. Integrate Quick Solve on the shared engine.
5. Add Hell Mode annealing, targeted repair and multi-seed optimisation.
6. Benchmark reproducibly against real circuit fixtures.

Do not extend the legacy Manhattan endpoint router. Its electrical PASS is not proof of physical buildability.

## Licence and credit

Karl's renderer is credited in the [README](../README.md). GPL-3.0 text is at [licenses/GPL-3.0.txt](../licenses/GPL-3.0.txt). Studying general algorithmic ideas is distinct from copying GPL-covered code; any reused covered implementation must comply with its licence, not merely provide attribution.


## Measured optimisation direction (decision 2026-11-21)


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


## Original Karl reference and skeleton status

Original upstream only: https://github.com/KarloFunke/stripboard-editor at commit `21e2373f6e1da44ce017be234b2df04f42d3af30` (2026-11-08); **not** the user's tuned `bigbadevilaussie-hue/stripboard-optimiser` fork. Inspected upstream files: `src/frontend/components/stripboard/autoLayout5.ts` (blob `bc9fc8330e0ab43ca6366f65fdd92235fa6f1e94`), `src/frontend/components/stripboard/v5wasm/decode.c` (`5a30461f879953c71dfe055c086efb98dbabd45c`), `src/frontend/components/stripboard/layout2/boardPrice.ts` (`16d59dcaf5f1f447d548f6e96e8c0a6e8cdc364d`). `solve/skeleton.py` is an isolated two-permutation rectangle decoder with longest-path compaction, not a full Karl V5 port: no net-row equalities, body envelopes, edge slides, copper, jumper paths or physical verification. Initial skeleton tests were authored but not executed in that GitHub-only change; verify locally. GPL-3.0 compliance is required for adapted source, not just credit.
