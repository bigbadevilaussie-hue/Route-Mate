# Collector → PREPARE / PRE-SOLVE → SOLVE: intelligence handoff

**Status:** Consolidated design notes, 2026-11-21. **No solver behaviour is implemented by this document.** The locked [Physical Model Specification](PHYSICAL_MODEL_SPEC.md) overrides any conflicting proposal.

## Existing terminology and boundaries

The documented top-level pipeline is **IN → PREPARE → SOLVE → DISPLAY** ([CLI](CLI.md), [Module I/O audit](MODULE_IO_AND_HANDOFF_AUDIT.md)). The GUI documentation uses **PRE-SOLVE** for questions and preparation before Quick Fit. PRE-SOLVE here means **analysis within the existing PREPARE-to-SOLVE handoff**, not a fifth top-level stage.

- **IN / collector:** preserve source project, component definitions, footprint overrides, pin offsets, body cells, net assignments, board dimensions, off-board status, source provenance and advisory board-size estimate.
- **PREPARE / pre-solve:** electrical sanity, user constraints and proposed *derived* routing-opportunity analysis. Distinguish source facts, computed predictions, warnings and unresolved uncertainties.
- **Sidecar:** persist structured evidence and recommendations through the existing versioned `<project>.routemate-state.json` pipeline envelope; keep the canonical project and source JSON separate. Refer to [handoff contract §5](MODULE_IO_AND_HANDOFF_AUDIT.md).
- **SOLVE:** consume valid recommendations as candidate guidance, never as permission to break locks, board bounds or physical/electrical rules; independently verify the result.

## What exists today

- `collect.py` estimates board area from per-component bounding boxes, a one-hole gap and a fixed routing-area factor (currently 3.2). This is **advisory** and is not net-aware.
- The project supplies component/pin/net information. Some body cells are pad-extents occupancy estimates, **not measured package outlines** ([Gate 1 handoff](GATE1_HANDOFF.md)).
- `solve/quick_fit.py` already evaluates net proximity, occupancy, adjacency and locks. Do not duplicate that algorithm under a new name ([Solver Differentiation](SOLVER_DIFFERENTIATION.md)).
- Pipeline contracts, adapters and a Moto run-state sidecar exist. Do not infer that every proposed finding or hint is already emitted or consumed.

## Proposed geometry-driven pre-solve recon (NOT IMPLEMENTED)

**Never branch on part names, IDs or model families.** Derive all decisions from the actual footprint and circuit graph.

For each component and candidate orientation, derive:

1. Physical pin count, connected pin count, distinct nets and per-net fanout.
2. Pin-row distribution and opposing pins on the same horizontal strip; identify different-net pairs requiring separation.
3. Candidate **between-hole** cut positions and accessibility, subject to the locked physical specification. A candidate is not a legal cut until verified.
4. Potential isolated copper runs and the lengths/landing holes accessible to connected components.
5. Body/pad occupancy and clearance uncertainty, including free vertical jumper corridors.
6. Candidate placement roles and rotations ranked by likely copper reuse, available access, and expected jumper demand.

Example, **not a hardcoded component rule**: if geometry contains two pin columns with nine paired rows, and opposing pins on each row are different nets, nine cuts *may* isolate eighteen copper segments. This is a conditional opportunity, not a guaranteed routing solution or eighteen jumper wires. Row use and cut feasibility depend on board position, actual assignments and physical access.

## Proposed sidecar record (illustrative schema, not approved contract)

Keep it as a report inside an existing PREPARE stage result; use stable component IDs and source hashes. Do **not** add a second independent sidecar:

```json
{
  "producer": "prepare.presolve",
  "component_id": "<stable-source-id>",
  "source_project_sha256": "<hash>",
  "facts": {
    "connected_pins": 18,
    "distinct_nets": 18,
    "pin_rows": 9
  },
  "hypotheses": [
    {
      "rotation": 0,
      "candidate_isolation_cuts": 9,
      "reason": "nine different-net opposing pin pairs",
      "status": "unverified"
    }
  ]
}
```

Counts above illustrate the record shape, not a universal part profile. Actual schema must be reconciled with `pipeline/contracts.py` and existing adapter semantics before implementation.

## Required acceptance tests before solver integration

- Equivalent geometry and nets produce equivalent guidance despite changed labels/part names.
- Rotations, footprint overrides, off-board leads, missing geometry and locked placements are respected.
- Predictions do not claim legal cuts, jumper paths or physical PASS without independent checks.
- Source hash changes invalidate stale recommendations.
- Compare Moto and Audio against the current baseline: legality first, then jumpers, length, diagonals, cuts and runtime.
- Never rewrite source JSON or silently change the frozen physical model.

## Open design questions

- Exact ranking/cost model and calibration are **not frozen**.
- How many placement hypotheses to retain per component is **not decided**.
- Measured body outlines and physical wire-path clearance may be unavailable; mark uncertainty rather than inventing geometry.
- Where PREPARE stores the recon report in the existing sidecar needs implementation review, not a new pipeline stage.
