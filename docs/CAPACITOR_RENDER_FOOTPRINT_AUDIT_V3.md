# Capacitor source-to-render audit — collector standard-through-hole-v3

## Provenance and tested fixtures

MOTOMIX and AUDIO project JSON data were traced through effective pin footprints, chosen renderer package, nominal collector body, hash-bound geometry sidecar, 2.5D and contact checks, and the real production Node SVG. All geometry dimensions below are **assumptions**, not measured hardware.

| Fixture | Parts | Type and value | Nominal SVG |
|---|---|---|---|
| MOTOMIX | C3, C4 | nonpolarized 15 pF ceramic | disc edge silhouette, 3 × 1.8 mm |
| MOTOMIX | C2, C5 | nonpolarized 100 nF ceramic | disc edge silhouette, 5 × 2.4 mm |
| MOTOMIX | C1 | polarized 1000 µF | electrolytic round can Ø10 mm |
| MOTOMIX | C6 | polarized 470 µF | electrolytic round can Ø10 mm |
| AUDIO | C1, C3, C6 | nonpolarized 0.1 µF ceramic | disc edge silhouette, 5 × 2.4 mm |
| AUDIO | C2, C4, C7 | polarized 10 µF | electrolytic round can Ø5 mm |

Live production SVG checks in tools/audit_capacitor_renderer.py compare rendered body shape and dimensions with the collector and sidecar for every capacitor in these fixtures.

## Defects found and corrections

1. Package type drift: the v2 collector ignored manually selected cap-ceramic, cap-film and cap-elko packages, although the production renderer honoured them. The new capacitor_contract.py centralises capacitance parsing, default and explicit package selections, and nominal dimensions. Collector v3 records the resolved render_package in the checksum-bound sidecar.
2. Renderer version drift: non-frozen Python runs previously reused whichever upstream compiled renderer was cached locally. The bridge now pins the verified stripboard-optimiser commit 7477431ff3939c4a51026852e4390d44299151c1 and refreshes stale caches, or reports failure rather than rendering from an unverified version. Frozen app bundles use their separate packaged runtime.
3. C4 misleading label: MOTOMIX stores a C4 boardLabelOffset of approximately -34.3 pixels. It can position the text C4 inside a nearby C1 electrolytic can. The render-only annotation overlap check moves only the displayed label and logs a CAPACITOR/LABEL correction. It does not move a component, lead, solder pad, rotation, or source JSON field.
4. Contact evidence gap: the old 2.5D sidecar checked jumper paths but not nominal body-to-body touch or another component's pin/termination pad under a body. inspect_assumed_contacts now reports body_body, pad_body and external_pad_body with IDs, labels, pad coordinates and nominal gaps; it does not label assumptions as measured physical collisions.
5. Red warnings: the real top and mirrored copper SVGs now overlay dashed red outlines on implicated nominal body shapes and red rings on implicated pad holes. The Activity log records CONTACT/ASSUMED_RISK and the solved summary distinguishes these findings from electrical PASS.
6. External termination pad allocation already avoids nominal body-envelope obstructions; the new render warnings also expose contacts in previously saved placements.

## Engineering limitations

- Footprint pins and electrical net identity remain authoritative. Nominal package bodies come from value/package drawing presets, not component-specific datasheets.
- A selected electrolytic package on a nonpolarized symbol, or nonpolarized package on a polarized symbol, is preserved and explicitly warned about. The audit never silently rewrites user electrical choices.
- A red ASSUMED contact is not a proven short, solderability failure, or verified mechanical collision. Board-edge overhang, measured standoff, actual part envelopes and cut-tool access remain uncertified.
- Copper-net electrical PASS and measured physical sign-off are separate.
- render/_front.py is a legacy unit-test helper. All real GUI previews and exports use the production renderer in render/standalone_bridge.py.

## Re-run checks

    python -m unittest tests.test_capacitor_render_contract tests.test_nominal_pad_access tests.test_geometry_sidecar_integration -v
    python tools/audit_capacitor_renderer.py benchmarks/moto/motomix.json
    python tools/audit_capacitor_renderer.py benchmarks/audio/audio.json

The GitHub routing-regression workflow runs the real renderer checks alongside electrical and GUI tests.
