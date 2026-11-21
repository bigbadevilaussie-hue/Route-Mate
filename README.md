# Route-Mate

Stripboard placement, copper-cut and jumper-routing software for real, buildable hobby projects.

Route-Mate uses Karl's Circuit Designer exports as input. The schematic editor stays Karl's; Route-Mate handles the physical board.

## What works today

- Import and normalise project data; run electrical sanity checks.
- Desktop GUI (PySide6), board dimensions and component-side preview.
- Quick Fit: deterministic net-aware component placement, including fixed-position locks.
- First-pass copper routing: cuts and jumper connections, followed by independent **electrical connectivity** verification.
- Benchmarks and automated tests.

**Not finished:** hard edge-anchor/slide enforcement, physical jumper-path and component-body clearance verification, cut/solder access checks, complete build instructions and Hell Mode optimisation. An electrical PASS is **not** a physically buildable-board PASS. Do not treat the current Quick Fit/router as a final construction verifier.

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
