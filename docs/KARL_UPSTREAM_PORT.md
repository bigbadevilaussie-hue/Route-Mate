# Upstream Karl solver port — provenance and scope

Development branch: `main` (direct commits; no feature branch required)

## Source of truth

**Original upstream only:** https://github.com/KarloFunke/stripboard-editor

Pinned upstream commit: `21e2373f6e1da44ce017be234b2df04f42d3af30` (2026-11-08).

Files inspected directly at upstream main on 2026-11-21:
- `src/frontend/components/stripboard/autoLayout5.ts` (blob `bc9fc8330e0ab43ca6366f65fdd92235fa6f1e94`)
- `src/frontend/components/stripboard/v5wasm/decode.c` (blob `5a30461f879953c71dfe055c086efb98dbabd45c`)
- `src/frontend/components/stripboard/layout2/boardPrice.ts` (blob `16d59dcaf5f1f447d548f6e96e8c0a6e8cdc364d`)

**Do not source the port from** `bigbadevilaussie-hue/stripboard-optimiser`: that is the user's modified fork and has different tuning.

## Initial implementation

`solve/skeleton.py` independently implements a basic two-permutation, rectangular-footprint sequence-pair decoder with longest-path compaction. It rejects invalid permutations, board overflow and conflicting fixed coordinates. It has no dependency on the existing GUI or router.

This is **not** a line-by-line port of Karl's full V5 decoder. In particular it does not yet support net-group row equalities, actual component body envelopes, rotations, edge-slide anchors, off-board terminals, copper segmentation, jumper routing, cut accessibility, simulated annealing or physical verification. No candidate produced by this primitive is a certified board.

## Agreed Quick Solve direction

- Keep Route-Mate's collector, project schema and pipeline.
- Use a shared engine and independent verifier for Quick Solve and Hell Mode.
- Electrical and applicable physical constraints are mandatory.
- Quick Solve diagonal limit: `floor(wire_count * 0.10)` in an explicitly relaxed profile; strict physical PASS still requires zero diagonal jumpers.
- Price strongly favours fewer wires and shorter wire length. Diagonals are penalised; cuts are a minor tie-breaker.
- Existing GUI lock dialog remains unchanged for now.
- Keep changes isolated on the port branch until tested and reviewed.

## Licensing

Upstream is GPL-3.0. Algorithmic inspiration is documented here; if any upstream source is copied or adapted, retain appropriate notices and comply with GPL-3.0 obligations. Attribution alone is insufficient.

## Verification status

Tests were authored, but **not executed** in this GitHub-only change. Run `python3 -m unittest tests.test_skeleton` in a local checkout (or equivalent test discovery) before integration. Do not treat this initial commit as a completed solver milestone.
