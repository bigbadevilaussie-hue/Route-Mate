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
