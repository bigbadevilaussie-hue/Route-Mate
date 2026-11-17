# Quick Fit test decision

## Decision

Use the real, unplaced Moto and Audio benchmark projects as the first Quick Fit acceptance inputs:

| Input | Components | On-board | Off-board | Assignments | Board |
|---|---:|---:|---:|---:|---|
| Moto | 44 | 33 | 11 | 123 | 24 x 56, both dimensions locked |
| Audio | 19 | 14 | 5 | 85 | 24 x 56, both dimensions locked |

These are the repository fixtures at `benchmarks/moto/moto.json` and
`benchmarks/audio/audio.json`. They have no saved component positions, so
they are suitable placement inputs rather than already-placed results.

## Stage 1 — source geometry gate (implemented)

Run:

```bash
python3 -m unittest tests.test_quick_fit_geometry -v
```

The tests check:

1. The fixture counts, locked board dimensions and unplaced starting state.
2. Every on-board component resolves to a project custom definition, a
   component override or the renderer's built-in footprint registry.
3. Footprint dimensions are positive and all pin/body coordinates are inside
   their declared footprint.
4. A body cell cannot occupy the same footprint coordinate as an electrical
   pad; two physical pads cannot occupy the same coordinate.
5. Every JSON net assignment references a pin that exists in the resolved
   footprint, including off-board component pins.
6. The row/column rotation transform is reversible on rectangular footprints.

This gate tests actual repository geometry, not assumed 1x2 resistor/capacitor
rectangles. Flexible lead-span parts remain flexible; their pin spacing is not
converted into a rigid body rectangle.

## Stage 2 — Quick Fit placement acceptance (blocked until placer exists)

Quick Fit must produce a separate provisional result without mutating the
source fixture. For each input:

- Place all 33 Moto / 14 Audio on-board components.
- Do not place off-board components on the board.
- Allocate no virtual off-board lead pads in this first placement test; that is
  a separate physical breakout feature.
- Honour the locked 24 x 56 board. Do not crop it or enlarge it.
- Resolve every footprint using the same geometry resolver used by the
  renderer and later Quick Solve.
- Keep every electrical pad on a real board hole. A body may use non-hole
  cells only where its footprint definition explicitly describes them.
- Reject physical overlap between distinct components.
- Keep one-hole clearance as a configurable placement preference, not as an
  electrical legality rule. Report when a complete placement requires less
  than the requested clearance; never silently reduce it.
- Preserve component identity, pin IDs, net assignments and original project
  data. Return placements separately or on a deep copy.
- Be deterministic: identical input and settings must produce identical
  positions, rotations and report.
- Report `PLACED`, `INCOMPLETE_GEOMETRY`, `CONSTRAINT_CONFLICT` or
  `NO_FIT_FOUND` distinctly. A greedy search failure is not proof that the
  board is physically impossible.

Acceptance requires zero overlaps, zero out-of-bounds pads/body cells, all
on-board components placed, no off-board parent placement, and identical
results on repeated runs. This is a placement test only: it does not claim
electrical connectivity, strip-cut legality or jumper routability. Those are
Quick Solve and independent-verifier responsibilities.

## Current status

- [x] Real Moto and Audio source fixtures selected.
- [x] Source geometry regression test added.
- [ ] Execute the new tests in the user's Route-Mate environment.
- [ ] Implement Quick Fit placement engine.
- [ ] Add Stage 2 placement acceptance tests after the engine exists.
- [ ] Run Quick Solve and independent verification separately.
