# Collector geometry assumption profile v1.0

**Status:** Approved design-exploration defaults, not measured construction data.  
**Scope:** Metadata emitted by `collect.py`; does not modify the frozen physical
model v1.1, change Quick Solve decisions, or authorise assumed bodies as `PASS`.

## Data ownership

The collector is the sole producer of `physical_geometry.json` in the campaign
output directory. The manifest records its absolute path, content SHA-256,
preset version and count of unverified components.

The sidecar uses `route-mate/assumed-geometry/1.0`. All shape coordinates are
in **unrotated footprint-local millimetres**, based on 2.54 mm pitch. They are
not board coordinates, not adjusted for component rotation, flexible leads
or Edge Slide, and may not be consumed directly by the 2.5D clearance verifier.
A future placement transform must account for these before routing can use them.

Saved footprint pins, pin IDs, custom definitions and explicit `footprintOverride`
have priority over built-in logical definitions. They define the lead locations.
`bodyCells` is not a measured package envelope and is not promoted to one.

## Fixed assumptions

| Parameter | Assumed value |
|---|---:|
| Insulated jumper outside diameter | 0.90 mm |
| Minimum XY body clearance | 0.30 mm |
| Minimum vertical clearance | 0.30 mm |
| Lead cylinder radius | 0.35 mm |
| Lead clearance margin | 0.20 mm |
| Search preference extra margin | 0.00 mm |

| Body family | Default envelope | Assumed board-to-body standoff |
|---|---|---:|
| Electrolytic, small | Ø5 mm round | 1.5 mm |
| Electrolytic, medium | Ø6.3 mm round | 1.5 mm |
| Electrolytic, large | Ø10 mm round | 1.5 mm |
| Ceramic capacitor | 4 × 2.5 mm rectangle | 1.0 mm |
| Axial resistor | 6.3 × 2.5 mm rectangle | 1.0 mm |
| Axial diode / zener | 4 × 2.5 mm rectangle | 1.0 mm |
| LED | Ø5 mm round | 1.0 mm |
| TO-92 | 4.8 × 3.8 mm rectangle | 2.0 mm |
| TO-220 | 10 × 4.5 mm rectangle | 2.5 mm |

The associated package height assumptions are defined in the versioned
`collector_geometry.py` `PROFILES` table; they do not determine mounting
height. Electrolytic size class uses *capacitance only* as a heuristic:
below 47 µF = small; 47–469 µF = medium; 470 µF and above = large.
Actual diameter depends on voltage rating, case series and manufacturer.
An explicit `package: to220` / `to92` hint overrides the generic transistor family.

## Safety and unknown cases

Every generated body has provenance `assumed_standard`, a named preset version,
and status `ASSUMED_UNVERIFIED`. A conditional fit using these nominal values
is an *exploration estimate*, not `PASS`, `MEASURED` or `BUILD_READY`.
No default lead mounting geometry is sufficient to claim physical contact safety.

Unknown custom module bodies, unavailable footprints, unspecified heat zones,
cut-tool accessibility and wire-on-wire stacking are not guessed from artwork.
They remain `UNVERIFIED`. Pin-through-hole occupancy remains a hard block
irrespective of body assumptions.

A separate, versioned physical-model amendment and placement-relative
transform with independent tests are prerequisites before the solver may use
these defaults as advisory routing preferences. Router and verifier must retain
the same hard `min_clearance`, and actual measured overrides must supersede
assumptions without erasing their source.

## Change control

These values are fixed under preset `standard-through-hole-v1`. Changing
a single value requires a new preset version and tests; old sidecars remain
reproducible. Do not automatically regenerate a prior campaign's sidecar when
replaying without recording that its physical assumptions changed.
