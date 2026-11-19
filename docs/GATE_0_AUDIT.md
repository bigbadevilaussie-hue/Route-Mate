# Gate 0 — Repository and Legacy Audit

**Baseline:** Route-Mate v1.21, with the physical-model design freeze in `docs/PHYSICAL_MODEL_SPEC.md` v1.0.  
**Status:** Expanded audit recorded; follow-up compatibility checks remain open.  
**Purpose:** Record verified legacy behaviour and identify the additional checks required before Gate 0 can be signed off. This document does not amend the locked physical model.

## 1. Verified legacy findings

These findings are based on direct inspection of the repository source, not archive-manifest inference.

### 1.1 Legacy copper router — `solve/route.py`

- Resolves assigned physical terminals from component footprint geometry and saved off-board leads.
- Rejects different nets assigned to the same physical hole.
- Adds between-hole cuts between consecutive terminal positions on a strip when their net sets differ.
- Preserves existing cuts and wires in its result.
- Connects remaining same-net copper groups using a deterministic Manhattan minimum-spanning-tree calculation.
- Stores each generated jumper as only its two endpoint holes; it does not store or validate the physical wire body/path.
- Runs the legacy electrical verifier after generating cuts and wires.
- Its `ROUTED` result is not proof of physical buildability. The returned warnings explicitly say wire paths, crossings, body clearance, soldering access, cut access and component-body interference are not modelled.

**Disposition:** Legacy baseline only. Do not extend this algorithm into the frozen physical router.

### 1.2 Legacy verifier — `solve/verify.py`

- Models horizontal copper connectivity, between-hole cuts, drilled-hole cuts and jumper endpoint unions.
- A wire electrically joins its two endpoint holes without validating the intervening path.
- It checks electrical shorts, opens and adjacency conflicts.
- It does not independently verify physical jumper orientation, body clearance, crossings, cut-tool access or endpoint access.
- It accepts legacy hole cuts, although hole cuts are outside the initial frozen physical model.

**Disposition:** Retain useful electrical behaviour only where compatible with the frozen model. Add a separate physical verifier; legacy electrical PASS must never mean physically buildable.

### 1.3 Placement and adjacency

- `solve/quick_fit.py` rejects different-net adjacency conflicts for already locked pins and rejects candidate placements that create adjacency conflicts. It therefore cannot currently accept an adjacent different-net pair merely because a legal between-hole cut could isolate it.
- `adjacency.py` reports same-hole and adjacent-hole different-net conflicts. The caller decides how to resolve or reject them.
- `solve/quick_place.py` performs deterministic first-fit placement using discrete pad/body cells. It does not perform physical cut-tool or jumper routing checks.
- Both placement implementations use `render/_geometry.py` for footprint geometry.
- `quick_fit.py` explicitly reports edge-anchor/sliding constraints as unsupported.
- The inspected placement code uses board row/column dimensions but does not enforce the source board's `lockedRows` / `lockedCols` flags as a placement constraint.

**Disposition:** Quick Fit and Quick Place are legacy placement foundations, not physical-model-compliant placement engines. The locked adjacent-pin rule must be implemented only with a proven isolating cut and independent verification.

### 1.4 Footprint geometry

- `render/_geometry.py` resolves built-in and project-defined footprints, applies footprint overrides, rotates discrete row/column offsets, and returns absolute pin coordinates plus discrete body-cell coordinates.
- Its flexible two-pin handling honours `flexibleEndPos` and maps declared body cells along the lead axis where applicable.
- This is a discrete board-cell occupancy model. It does not define measured component-body outlines, height, cut-tool envelopes, jumper wire cross-sections or physical access clearances.
- Solver modules import geometry from the renderer package, coupling solver geometry to a renderer-owned module.

**Disposition:** Preserve existing source-footprint interpretation while defining a renderer-independent board coordinate contract. Do not treat display artwork or cell occupancy as measured physical clearance.

### 1.5 Off-board policy

- `placement_policy.is_off_board_component()` treats either `offBoard: true` or `boardExcluded: true` as excluded from component placement, and also recognises the known Moto GPS definition ID when the source omits the explicit flag.
- `quick_fit.py` can use saved `leads` coordinates for off-board assigned terminals.
- `solve/verify.py` also uses saved off-board leads for electrical terminal locations; an off-board pin without a saved lead is not placed on the board.
- GPS identity exclusion and explicit `offBoard` are therefore not interchangeable data semantics, even though the placement policy excludes both from component-body placement.
- `quick_place.py` excludes these components from placement and does not itself create or route lead geometry.

**Disposition:** Preserve the distinction between remotely mounted components with explicit board leads and components excluded from board placement/routing. Audit each consumer separately; do not change source JSON or the established GPS policy as part of Gate 1.

### 1.6 Input preservation and collection

- `route_copper()` and `quick_fit()` work on deep copies rather than mutating the supplied project object.
- `collect.validate_project()` canonicalises a known set of legacy built-in pin IDs in place. It preserves pin names and geometry during that specific conversion; it is not a general immutable parser.
- `normalise_like_gui()` and the layout-hash/round-trip paths must be treated as separate compatibility surfaces. Their full unknown-field preservation contract remains a Gate 0 follow-up item.
- Existing cut and wire objects are preserved by the legacy router before it appends generated objects, but this does not make legacy hole cuts valid in the new physical model.

**Disposition:** Add explicit deep-copy/non-mutation and round-trip preservation tests for solver entry points and collection/import paths. Keep legacy fixture interpretation separate from new physical acceptance fixtures.

### 1.7 GUI and renderer

- `render/_front.py` is a component-side preview and draws stored jumper endpoints as direct SVG lines; it does not render the physical cut geometry.
- `render/standalone_bridge.py` invokes the upstream production renderer and produces separate top/copper SVGs. Its display coordinates and SVG dimensions are not physical clearance measurements.
- `gui/main.py` calls the legacy placement/routing flow and presents legacy routing status. Its success wording must be separated from electrical and physical verification outcomes before the new physical solver is integrated.
- CLI, public renderer and standalone-renderer call paths require a complete status audit so no path reports electrical-only success as physically buildable.

**Disposition:** No GUI redesign in Gate 1. Gate 6 must show electrical and physical outcomes separately.

## 2. Additional Gate 0 coverage required

The independent review correctly identified areas not sufficiently covered in the first audit. These are now explicit follow-up checks:

1. **Off-board leads versus board-excluded components:** inspect every consumer and add tests for `offBoard: true` with lead coordinates, `boardExcluded: true`, the GPS identity exception, and missing leads.
2. **Flexible-end geometry:** test how `flexibleEndPos` changes both pads and body occupancy, including its interaction with saved rotations and placement locks.
3. **Quick Place and board locks:** audit `lockedRows`, `lockedCols`, component `locked`, edge anchors and sliding constraints. Do not infer enforcement from GUI controls or JSON fields.
4. **Collection and round-trip preservation:** test IDs, defIds, net IDs, footprint overrides, labels, schematic/display metadata, manual cuts/wires, off-board leads and unknown fields. Distinguish documented normalisation from destructive mutation.
5. **Electrical verification coverage:** inventory tests for multiple pads sharing one net, duplicate assignments, floating/single-terminal nets, off-board leads, board-excluded components, shorts, opens and cuts.
6. **All user-facing result paths:** audit GUI, CLI, public renderer and standalone bridge for status labels and any implication that rendering or electrical PASS proves buildability.
7. **Moto legacy cut semantics:** the fixture contains 30 legacy cuts and 14 vertical endpoint wires. Preserve it as a legacy/import regression fixture. Verify the exact cut-kind encoding in the fixture and tests before describing those cuts; do not use it as a new-model positive fixture. Add a dedicated between-hole-cut physical fixture.

## 3. Replacement boundaries

- Retain electrical connectivity concepts only where they can be expressed using the frozen between-hole cut and jumper model.
- Build an independent physical verifier whose checks derive from the resulting layout, not from router assertions.
- Replace the endpoint/MST router; do not retrofit physical claims onto endpoint-only jumpers.
- Keep legacy tests as legacy regression tests. A green legacy test suite is not evidence of physical-model compliance.
- Retain existing placement code only as a starting point. It is not sufficient until cut accessibility, jumper clearance and the locked adjacent-pin rule are enforced.
- A shared geometry module must define coordinate semantics, not guessed physical dimensions. Renderer SVG geometry is never the source of physical measurements.

## 4. Gate 1 entry conditions

Gate 1 begins with a renderer-independent coordinate contract and tests for:

- horizontal strip axis and row/column orientation;
- hole-centre coordinates in normalized hole-pitch units;
- between-hole cut-gap coordinates;
- vertical jumper alignment and endpoint validation.

The following remain **unresolved blockers** for physical verification and must not be guessed:

- physical cut-tool clearance envelope and approach region;
- physical component-body outlines/heights and how footprint body cells map to them;
- jumper wire body width/height and end-bend/lead-drop envelope;
- jumper landing-hole legality, including component-lead occupancy;
- whether separate jumpers may share a column when their spans do not overlap;
- exact crossing/near-clearance rules;
- edge access and the implications of locked board dimensions.

Normalized coordinates are a mathematical board frame only. They are not millimetres, renderer pixels, or proof of physical clearance.

## 5. Gate status

- **Gate 0:** audit expanded; follow-up coverage in §2 remains open until tests and call-path checks are completed.
- **Gate 1:** coordinate-frame implementation and tests may proceed. Physical envelopes and occupancy/accessibility rules remain blocked pending explicit definitions.
- **No router, physical verifier, placement-policy or GUI behaviour is authorised by this audit update alone.**

This document records the repository baseline and implementation boundaries. The normative physical rules remain in `docs/PHYSICAL_MODEL_SPEC.md` v1.0.
