# Gate 1 Implementation Handoff

**Status date:** 2026-11-19  
**Branch:** `gate1-geometry-contract`  
**Last verified branch HEAD before this handoff:** `8e7811f73d2be1ff3a7b1c2d213f6d32c2f0d04f`  
**Physical model authority:** [PHYSICAL_MODEL_SPEC.md](PHYSICAL_MODEL_SPEC.md) — LOCKED. This handoff records implementation status; it does not amend the specification.

## Later solver architecture decision (not Gate 1 authorisation)

[Solver Architecture Decision](SOLVER_ARCHITECTURE_DECISION.md) establishes one shared solver engine with Quick Solve and Hell Mode as separate search strategies, plus shared hard constraints and independent electrical/physical verification. Karl's exact decoder, copper grouping and annealing are research candidates. **This does not authorise skipping Gate 1 or changing the locked physical specification.** This handoff's branch, test counts and status are historical snapshots; verify current repository state before acting.

## Start here — instructions for the next AI session

1. Read [NICKS_RULES.md](../NICKS_RULES.md) and [ASSISTANT_RULES.md](../ASSISTANT_RULES.md).
2. Read this file, then read [PHYSICAL_MODEL_SPEC.md](PHYSICAL_MODEL_SPEC.md) in full.
3. Check the actual branch and working tree before changing anything:
   ```bash
   git status --short --branch
   git log -5 --oneline
   ```
4. Inspect `physical_geometry.py`, `board_geometry.py`, `tests/test_physical_geometry.py`, and the Moto sidecar at `benchmarks/moto/moto.routemate-state.json`.
5. Continue Gate 1 only. Do not start Gate 2/3, do not extend `solve/route.py`, and do not touch the renderer.

Do not assume this document is more current than the branch. If branch HEAD differs, inspect the intervening commits and reconcile the handoff before coding.

## What has actually been implemented

New module: `physical_geometry.py`.

It provides exact rational conversion from logical board coordinates to millimetres:

- `HOLE_PITCH_MM = Fraction(127, 50)` — exactly 2.54 mm (0.1 inch).
- `PhysicalPoint`, `PhysicalSegment`, and `PhysicalCell` immutable data types.
- `to_physical()`.
- `physical_hole_center()`.
- `physical_between_cut_center()`.
- `physical_jumper_segment()` — delegates legality/orientation to `BoardGrid.jumper_segment()`.
- `physical_component_body()` — maps the saved logical body occupancy returned by `component_geometry()` into square pitch-sized cells in mm.

The conversion layer uses `Fraction`, avoiding floating-point rounding in the geometry foundation. Rotation and flexible-endpoint placement are delegated to the existing shared `board_geometry.component_geometry()` transform.

### Important geometry limitation

`bodyCells` are logical occupancy cells, not measured component-package outlines. `physical_component_body()` maps each occupied grid cell to a 2.54 mm square centred on its hole. This is a deterministic occupancy approximation only. It does **not** establish actual package body width, height, lead shape, overhang, tool clearance, or soldering clearance.

Do not describe this as a complete physical component envelope. Do not infer missing package dimensions from labels or generic package strings. Use explicit footprint/package measurements only when the source data actually provides them; otherwise preserve the distinction between known occupancy and unknown physical envelope.

## Tests and verified result

New test file: `tests/test_physical_geometry.py`.

It contains seven tests covering:

1. Exact 2.54 mm pitch.
2. Hole-centre conversion.
3. Between-hole cut centre and half-pitch spacing.
4. Vertical jumper segment and physical length.
5. Rejection of diagonal jumper endpoints.
6. Saved component body occupancy and rotation.
7. Flexible component body following saved endpoint geometry.

**User ran and reported both commands on the local iMac:**

```bash
python3 -m unittest tests.test_physical_geometry -v
# Ran 7 tests — OK

python3 -m unittest discover -s tests -v
# Ran 153 tests — OK
```

The full-suite result is user-reported terminal output, not a CI run performed by the assistant. At that point: 153 tests, 0 failures. Re-run after any subsequent code changes.

## Gate 1 status — not complete

The coordinate-conversion/occupancy foundation is implemented and tested. Gate 1 still needs the actual physical clearance model and checks.

Remaining Gate 1 work:

- Define and implement cut-tool approach/access geometry as a hard legality constraint.
- Define and implement jumper-body geometry/clearance, including collision checks against component occupancy and other jumpers.
- Resolve what physical component-envelope data is available versus unknown. The current square-cell mapping is not a measured package outline.
- Define endpoint access/landing legality and any required clearances without weakening the locked specification.
- Add focused unit tests for each hard constraint, including boundary and collision cases.
- Keep the physical checks independent of the legacy electrical verifier; never report physical PASS when a required physical dimension/clearance is unknown or unchecked.

Before implementing clearances, inspect the exact locked specification sections and actual source data. Do not invent tool dimensions or safety margins. If a required physical dimension is not specified by the project/source, identify the missing input and establish an explicit, reviewed model rather than silently choosing a value.

## Gate sequence — do not skip

The locked specification requires this order:

- **Gate 0:** legacy repository/data audit — recorded in [GATE_0_AUDIT.md](GATE_0_AUDIT.md).
- **Gate 1:** geometry/occupancy contract, cut access, jumper-body geometry. Current progress is only the coordinate/occupancy foundation described above.
- **Gate 2:** split horizontal copper into distinct runs using between-hole cuts.
- **Gate 3:** route single straight vertical jumpers between same-net runs.
- **Gate 4:** independent electrical and physical verification.
- **Gate 5:** regression and reproducible measurement.
- **Gate 6:** placement and GUI integration.

Do not start Gate 2 or Gate 3 until Gate 1 is complete and its tests pass.

## Source/data facts already checked

The collector and Moto sidecar have already been inspected. Do not repeat old assumptions that the sidecar lacks component definitions or instance geometry.

- `collect.py` preserves project `componentDefs`, merges KiCad footprint/module information from supported inputs, parses pad positions in mm, converts pad spacing using 2.54 mm pitch, and creates pin offsets plus `bodyCells`.
- The collector's `bodyCells` are generated occupancy bounds based on pad extents; the collector does not extract a measured package-body outline from KiCad artwork.
- The Moto sidecar embeds solved project data under `pipeline.stages.SOLVE.quick_fit.report.result.project` and `SOLVE.route.report.result.project`.
- The Moto solved project contains 44 components, 35 nets and 123 assignments. It includes custom component definitions and per-instance footprint overrides. Some instances have useful saved dimensions/occupancy; many generic built-ins do not have sufficient package geometry for a measured envelope.
- Inspect the live sidecar and definitions directly before making decisions. Do not treat this inventory as a substitute for source inspection.

## Protected areas and explicit exclusions

- **Renderer:** leave it alone. The user confirmed the renderer is visually correct; the latest renderer correction is commit `e211368a65f52124e91b3e55968aae996c0cb5aa`. No renderer changes are part of Gate 1.
- **Legacy router:** do not extend or optimise `solve/route.py`. Its Manhattan endpoint links are legacy electrical routing, not physical wire paths.
- **Locked specification:** do not edit or reinterpret `docs/PHYSICAL_MODEL_SPEC.md` without explicit approval.
- **GUI:** no GUI redesign or integration during Gate 1.
- **Existing electrical behaviour:** do not change it as a shortcut to physical routing.
- **No false PASS:** electrical connectivity PASS is not physical buildability PASS.

## Immediate next engineering task

Continue Gate 1 by designing the cut-access and jumper-body clearance model against the locked specification and the actual board/component data. First inspect the current geometry APIs and test conventions. Propose exact geometric primitives and boundary semantics in code/tests; do not guess unspecified physical dimensions. Keep changes narrow and add tests before integrating the checks into any solver.

## Local test commands

```bash
cd ~/Desktop/Route-Mate
git pull
python3 -m unittest tests.test_physical_geometry -v
python3 -m unittest discover -s tests -v
```

Expected at this handoff point: 7 focused tests and 153 total tests pass. A later branch may have more tests; trust actual output, not these historical counts.
