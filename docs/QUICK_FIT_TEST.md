# Quick Fit placement acceptance

## Decision

Use the real, unplaced Moto and Audio benchmark projects as the first Quick Fit
acceptance inputs. Both source boards are locked at 24 x 56.

| Input | Components | Placeable by shared policy | Excluded | Assignments |
|---|---:|---:|---:|---:|
| Moto | 44 | 32 | 12 | 123 |
| Audio | 19 | 14 | 5 | 85 |

The Moto JSON marks 33 components as on-board, but the shared
placement_policy.py also classifies the known NEO-6M GPS definition as
off-board because the export omits its offBoard flag. Quick Fit must use that
shared policy and leave the GPS parent off the stripboard. The source JSON is
not rewritten.

The fixtures are benchmarks/moto/moto.json and benchmarks/audio/audio.json.
They have no saved component positions.

## Stage 1 — source geometry gate

Run:

~~~bash
python3 -m unittest discover -s tests -p 'test_quick_fit_geometry.py' -v
~~~

The tests check:

1. Fixture counts, locked board dimensions and unplaced starting state.
2. Every placeable component resolves to a project definition, component
   override or renderer built-in footprint.
3. Footprint dimensions are positive and all pin/body coordinates are inside
   their declared footprint.
4. Body cells do not overlap electrical pads; physical pads do not overlap.
5. Every JSON net assignment references an existing footprint pin, including
   off-board component pins.
6. Rotation transforms are reversible for rectangular footprints.

Flexible lead-span parts remain flexible; their pin spacing is not converted
into a rigid body rectangle.

## Stage 2 — Quick Fit placement acceptance

Implemented in solve/quick_fit.py. Run:

~~~bash
python3 -m unittest discover -s tests -p 'test_quick_fit.py' -v
~~~

Quick Fit must:

- Place all 32 Moto / 14 Audio placeable components.
- Leave all 12 Moto / 5 Audio excluded components off-board.
- Honour the locked 24 x 56 board; never crop or enlarge it.
- Use the same geometry resolver as the renderer.
- Keep every electrical pad and declared body cell on a real board hole.
- Reject physical overlap between distinct components.
- Use one-hole clearance as a configurable preference. If a complete layout
  needs less clearance, report the actual clearance used; never reduce it
  silently.
- Preserve component identity, pin IDs, net assignments and source data.
- Be deterministic for identical inputs and settings.
- Return one of PLACED, INCOMPLETE_GEOMETRY, CONSTRAINT_CONFLICT or
  NO_FIT_FOUND. A greedy search failure is not proof the board is impossible.

The initial engine uses deterministic greedy net-aware placement scoring.
Its report records the clearance requested/used and net-distance score.
This is a placement result only; it does not claim copper connectivity,
strip-cut legality or jumper routability. Those remain Quick Solve and
independent-verifier responsibilities.

## Remaining work

- [x] Real Moto and Audio source fixtures selected.
- [x] Source geometry regression test.
- [x] Initial deterministic net-aware Quick Fit placer.
- [x] Stage 2 placement acceptance tests.
- [ ] Execute the tests in the user's Route-Mate environment.
- [ ] Add hard edge-anchor and slide placement constraints.
- [ ] Run Quick Solve and independent verification separately.
