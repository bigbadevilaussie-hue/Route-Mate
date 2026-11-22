# Physical model amendment v1.1 — explicit insulated-wire 2.5D clearance

**Status:** User-authorised amendment to `PHYSICAL_MODEL_SPEC.md` v1.0.  
**Scope:** Jumper/body geometry only. All copper, between-hole cut, net,
fixed-lock, edge-slide and independent-verification requirements remain in force.

## Contract and units

Coordinates are millimetres; board holes lie at
`(x_mm, y_mm) = (2.54 * col, 2.54 * row)`. The board top is `z=0`.
Jumper geometry consists of a straight centreline and insulation outer
diameter (`wire_od_mm`). Its nominal z range is
`[lift_mm, lift_mm + wire_od_mm]`, with zero lift by default.
No new allowed jumper directions or multiple-leg geometries are introduced.

Every footprint separates:

1. **Leads/pads:** occupied board holes and explicitly measured/declared
   exposed/formed lead solids. An intermediate occupied mounting hole is a
   proven hard failure; an expressly allowed endpoint landing is different.
   Exposed conductor/lead proximity is subject to explicit lead radius/margin.
2. **Body solids:** true circular, rectangular or polygonal XY outline and
   explicit `z_min_mm` / `z_max_mm`, with `z_min_source` of
   `measured`, `datasheet`, `user_declared` or `default_flush`.
   `default_flush` means unknown standoff and *does not prove contact*.
3. **Artwork:** text, courtyard, symbols and display silhouettes. Never a
   hard obstruction for routing or independent physical verification.

The project-supplied geometry must be explicit and complete for any opt-in
2.5D-routing mode. Missing values must not be silently filled from the
rendered artwork, guessed resistor/capacitor dimensions, or physical assumptions.

## Clearance

The same hard `min_clearance_mm` applies to the router and verifier.
Optional `search_preference_margin` changes only ranking, not legality.
The router must not shrink the verifier's accepted solution space.

For each body:
- If true XY distance from jumper centreline to body outline is at least
  `wire_od_mm/2 + min_clearance_mm`, the body is clear.
- Otherwise, if `lift_mm + wire_od_mm + z_margin_mm <= z_min_mm`
  and `z_min_source` proves/declares that height, the wire clears underneath.
- A `user_declared` standoff or explicit `allow_contact` with
  `contact_source` requires a CONDITIONAL finding, not silent PASS.
- A known overlap against a measured/datasheet body and absent permitted
  contact is `FAIL_PROVEN`.
- Unknown standoff that prevents proof of under-body clearance is
  `FAIL_UNVERIFIED`, not a claimed collision.

Comparison boundary is inclusive: exactly at minimum clearance passes.
Numerical tolerance is fixed at **1e-9 mm** for fixture parity; no default
negative margin is permitted.

Bare wire and exposed lead clearance remain hard checks. Wire-on-wire
overlaps and z-stacking require explicit future geometry and cannot silently
receive a PASS. Heat keepouts are *advisory unless grounded by supplied
temperature/dissipation limits*.

## Decision codes

- `PASS`: supported by explicitly supplied geometric inputs.
- `CONDITIONAL`: depends on declared installation standoff/contact.
- `FAIL_UNVERIFIED`: insufficient physical evidence, conservatively blocked.
- `FAIL_PROVEN`: supported geometric/electrical obstruction.

Search must not certify a conditional or unknown-clearance route as an
unqualified physically verified layout. Electrical verification stays
independent. Cut-tool access and measured construction clearance remain
uncertified unless separately established.

## Source data and migration

The experimental project extension is `physicalClearance` with explicit
`settings`, `body_solids`, `leads`, and a `complete` declaration.
These fields are **absolute board coordinates in mm**, not screen pixels,
and must be preserved as user-supplied metadata. The first opt-in integration
requires **every on-board component to be positioned and locked**, because
absolute shapes cannot follow Quick Fit moves or Edge Slide positions.
Auto-placement with 2.5D clearance remains blocked until footprint-relative
transforms (including rotation and flexible two-lead geometry) are implemented.
The golden evaluator itself accepts standalone hypothetical geometry fixtures.

Legacy projects without this extension keep the existing conservative
verification behaviour until the compatibility migration is proven.
Do not invent diameters or standoffs for saved Moto and Audio fixtures.

## Golden tests

`tests/fixtures/clearance_25d_golden.json` is the executable
normative fixture set for G01–G11 including G03a/G03b/G03c and G08
exact-boundary/just-inside checks. The historical Audio/Moto project files
are characterization cases only, not pre-certified physical PASS boards.

The router and independent physical verifier must implement this contract
independently and be compared against the same fixture set. The helper
reference evaluator is **not** an independent certification implementation.

This amendment changes only the wire-clearance provisions of v1.0 sections
3.4 and 10 (which had deferred insulated-wire routing). Unrelated provisions
of the locked specification are unchanged.
