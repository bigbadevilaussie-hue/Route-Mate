# Route-Mate

Stripboard placement, copper-cut and jumper-routing software for real, buildable hobby projects.

Route-Mate uses Karl's Circuit Designer exports as input. The schematic editor stays Karl's; Route-Mate handles the physical board.

## What works today

- Import and normalise project data; run electrical sanity checks.
- Desktop GUI (PySide6), board dimensions and component-side preview.
- PRE-SOLVE: read-only footprint topology and orientation analysis, including dual-row detection, body-obstructed vertical jumper columns and lower-bound copper isolation cuts. These are hints, not routing certification.
- Quick Fit: deterministic net-aware component placement, including fixed-position locks. Since v1.36 its scoring also considers PRE-SOLVE-derived jumper-lane obstruction and minimum strip-cut estimates after net distance.
- First-pass copper routing: cuts and jumper connections, followed by independent **electrical connectivity** verification.
- Benchmarks and automated tests.
- Live Quick Solve attempt progress, worker count, estimated time remaining and a stable SVG board view without scroll-wheel zoom.

**Not finished:** hard edge-anchor/slide enforcement, physical jumper-path and component-body clearance verification, cut/solder access checks, complete build instructions and Hell Mode optimisation. An electrical PASS is **not** a physically buildable-board PASS. Do not treat the current Quick Fit/router as a final construction verifier.

## Current development status (2026-11-23)

- **Version:** `1.44` (`VERSION` file). GUI Quick Solve asks for Off/Normal/Wider body spacing, uses three or four independent OS worker processes when the CPU supports them, partitions the same 24 attempt slots across processes and searches for up to two distinct independently checked layouts. Only verified routes compete: fewer nominal contact warnings, then higher provisional 0–100 score and routing complexity. If the best still scores below 40/100 or has more than one nominal contact warning, it continues searching within the same fixed budget. The program reports if fewer than two are found. Version 1.42 also prioritises nominal body clearance before net-distance attraction in placement, screens movable package silhouettes against board-edge overhang, and ranks verified candidates by edge overhang and part/pad contact risk. Version 1.43 responds to measured slow 3-process MOTOMIX runs: a near-tie 3/4-worker probe chooses four processes; one worker preserves original full-budget compact baselines while other workers genuinely pursue selected Normal/Wider spacing, or run additional compact variants with a 180,000-expansion routing cap. The global 24-attempt cap is unchanged. Unmet spacing is explicitly reported, not described as physical PASS. Source projects and fixed locks remain intact; measured physical clearance remains uncertified.
- **1.44 quality feedback:** On a poorly spaced electrically verified board, remaining placement attempts target the exact movable components named by nominal contact or board-overhang diagnostics, rather than arbitrary component IDs. Fixed locks stay immutable, rerouting remains independently verified, and the prior verified board remains the fallback. All verified candidates now have inspectable quality summaries in GUI Activity. This does not guarantee a contact-free MOTOMIX result or measured physical clearance.
- **Validation:** user-reported local iMac run: `python3 -m unittest discover -s tests -p "test_*.py" -v` — **213 tests, OK**, 7.545 seconds. This is not a CI verification or proof of physical buildability. The default `python3 -m unittest discover -v` found zero tests; explicitly specify `-s tests`.
- **Moto ESP32:** the custom 6×9 footprint has 18 pins in two columns and 36 interior body cells. PRE-SOLVE detects its dual-row topology and reports four body-obstructed vertical jumper columns at 0°. This is generic footprint analysis, not a special-case rotation ban.
- **Still missing:** Quick Fit hints are soft scoring only. The router does not yet guarantee whole-path top-side jumper/body clearance, alternative legal routing or independent physical PASS. Under-board copper and top-side jumper geometry must remain distinct. Unknown measured package envelopes and access dimensions cannot be inferred from logical body cells.
- **Next engineering milestone:** inspect and complete the required physical-geometry/clearance prerequisites, enforce full-path jumper legality in routing, then independently verify and regression-test ESP32 and other footprints. Preserve the implementation gate order in the locked physical model; do not label electrical PASS as physical PASS.

## Run

```bash
python3 -m pip install -r requirements-gui.txt
python3 run_gui.py
```

Run the tests:

```bash
python3 -m unittest discover -s tests
```

## Non-negotiable rules

- The real board dimensions are hard limits. Never silently resize or crop beyond them.
- Fixed-position and edge locks must be **hard constraints**, not scoring penalties. Unsupported edge/slide behaviour must be reported, not faked.
- Preserve source identifiers and report unknown or conflicting electrical/footprint information.
- Keep electrical correctness and physical buildability separate; never claim a physical PASS without physical verification.
- Quick Solve is for fast, valid results; Hell Mode is for deeper optimisation. Neither may bypass hard constraints.
- CLI and GUI must share the same engine and verification rules.

Project working rules: [ASSISTANT_RULES.md](ASSISTANT_RULES.md) and [NICKS_RULES.md](NICKS_RULES.md).

## Karl's renderer — credit and licence

**Credit: Karlo Funke (Karl), Stripboard Editor / Stripboard Optimiser.**

- Original project: https://github.com/KarloFunke/stripboard-editor
- Route-Mate's renderer source: https://github.com/bigbadevilaussie-hue/stripboard-optimiser
- Licence: **GNU General Public License, version 3 (GPL-3.0)** — [licence text](licenses/GPL-3.0.txt).

Route-Mate's production board preview calls the standalone renderer from the Stripboard Optimiser fork through `render/standalone_bridge.py`. The renderer and any reused GPL-covered source retain their applicable copyright, attribution and licence obligations. This acknowledgement does **not** imply Karl endorses Route-Mate. Attribution alone does not replace GPL compliance; distribution of covered code or combined derivative work must satisfy the licence's requirements.

We study useful solver algorithms, but Karl's original implementation, the modified fork and Route-Mate's own solver are distinct. No claim is made that Karl's solver enforces Route-Mate's hard physical constraints.

## Solver architecture

**One shared engine, two search modes:** Quick Solve finds a verified legal layout quickly; Hell Mode searches harder for a better verified layout, using Quick Solve's result as a starting point when available. Both use the same hard constraints and independent electrical/physical verifier. A Quick Solve failure is not proof of impossibility. Karl's solver algorithms are studied and adapted, not adopted as Route-Mate's legality rules. See [Solver Architecture Decision](docs/SOLVER_ARCHITECTURE_DECISION.md).

## Reference documentation

**Documentation authority:** [locked physical model](docs/PHYSICAL_MODEL_SPEC.md) → [solver architecture](docs/SOLVER_ARCHITECTURE_DECISION.md) → [pipeline/PRE-SOLVE handoff](docs/MODULE_IO_AND_HANDOFF_AUDIT.md). Historical audits are snapshots, not current implementation proof.


- [Physical model and implementation gates](docs/PHYSICAL_MODEL_SPEC.md)
- [Current implementation handoff](docs/GATE1_HANDOFF.md)
- [CLI input contract](docs/CLI.md)
- [GUI architecture](docs/GUI.md)
- [Benchmarks](benchmarks/)

The physical-model specification is the authoritative design target. **A documented requirement is not proof it has been implemented.**
