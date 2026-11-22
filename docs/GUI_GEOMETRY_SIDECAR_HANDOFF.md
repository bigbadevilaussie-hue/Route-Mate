# GUI geometry sidecar handoff — diagnostic mode v1

The project-specific GUI geometry sidecar is named
`<project-stem>.routemate-geometry.json`. It is a versioned, checksum-bound
wrapper around the **exact** `build_assumed_geometry()` output from
`collector_geometry.py`. No second package geometry table or WR-specific
exception is permitted.

For collector campaigns (`<out>/projects/<id>.json`), the GUI loader first
reads the existing `<out>/physical_geometry.json`, verifies its SHA-256 against
`manifest.json`, and compares its contents with the collector profile for
the project. Invalid/stale geometry is rejected, not trusted.

For standalone saved boards, if an exact matching GUI sidecar is not present,
the GUI computes it using the same collector profile and persists it.
Project SHA-256, geometry SHA-256, source preset/version and provenance are
recorded. The original project JSON is never modified.

## Physical evaluation

Saved-layout preview transforms each available assumed body solid from
footprint-local coordinates to the solved board using **actual pin positions**,
including rotation and flexible two-lead endpoints. Both separate
`classify_jumper()` and `verify_jumper_25d()` implementations evaluate
each jumper; a disagreement is an error.

The GUI reports per-wire outcomes, coverage gaps and the assumption preset.
Legacy artwork warnings are retained as **separate** evidence: visual
silhouettes are not promoted to measured body collisions. Actual pad
occupancy, shared jumper landings, wire interactions, and cut access are still
subject to their own independent checks and are not proved by this sidecar.

**This diagnostic integration is not automatic 2.5D Quick Solve routing.**
Quick Solve retains the existing independently checked hole router and hard
grid/pad constraints. The GUI also records a diagnostic 2.5D result for its
solved placement, and writes a matching sidecar when saving the solved JSON.

`ASSUMED_CLEARANCE_PASS` means all *modelled* shapes cleared the supplied
nominal dimensions; it never means construction-certified. Missing custom
body solids produce `UNVERIFIED` and presumed clashes produce
`ASSUMED_CONFLICT`. Any independent physical sign-off requires actual
package/installation evidence. The model does not silently upgrade assumed
height to `measured` or `datasheet`.

The saved Audio/Moto reference boards are diagnostic regression fixtures,
not hard-coded clearance exceptions or automatically certified build designs.
