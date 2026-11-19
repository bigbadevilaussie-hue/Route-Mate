# Route-Mate

> **DESIGN FREEZE — authoritative physical model:** [PHYSICAL_MODEL_SPEC.md](docs/PHYSICAL_MODEL_SPEC.md) is the single source of truth. It supersedes older routing assumptions and implementation plans. v1.21 is a legacy electrical-routing baseline, not a physically verified router. Do not extend its Manhattan endpoint algorithm. The frozen model requires horizontal copper, between-hole cuts only, single vertical jumpers, accessible cuts, and independent electrical **and** physical verification. The implementation gates and exclusions are defined in the specification. The expanded [Gate 0 repository audit](docs/GATE_0_AUDIT.md) records verified legacy behaviour and remaining compatibility checks.

An independent stripboard placement, routing and optimisation engine.

Karl's Circuit Designer remains the circuit-design front end. Route-Mate takes Karl's exported project data and owns the physical stripboard problem: component placement, strip cuts, jumper routing, construction checks, optimisation and build output. Route-Mate is not a replacement for Karl's schematic editor and is not a re-skinned copy of the legacy GUI solver.

## The workflow

1. **IN** — collect the files exported by Karl.
2. **PREPARE** — validate and understand the circuit, select the real board, set component placement constraints and checking preferences.
3. **SOLVE** — search legal placements, cuts and jumpers; optimise and independently verify candidates.
4. **DISPLAY** — show the board, cuts, jumpers, component positions, reports and practical build instructions.

These are software boundaries, not just menu labels. Each stage passes a defined Route-Mate project model to the next.

## Input files

A Karl export supplies two selectable export formats:

- **Project JSON** — the structured project data.
- **KiCad netlist (.net)** — the electrical connectivity export.

The export also supplies **kicad.mod**, containing module/footprint information. Route-Mate's input stage must accept the JSON, netlist and module data together, preserve source identifiers, and report missing or conflicting information rather than silently guessing.

The files are complementary. Their exact field authority must be established by inspecting real exports and documenting the schema; do not assume one file contains everything.

See [CLI input contract](docs/CLI.md).

## Board and placement rules

- **Physical board dimensions are mandatory before solving.** They describe the actual purchased stripboard and are absolute upper limits.
- **Preferred finished dimensions are optional.** They are a target for a smaller cut-down board, not permission to exceed the physical board.
- Never crop a solved layout blindly. The final dimensions must preserve all components, cuts, copper connections and jumpers.
- A component may be fully position-locked, initially placed but movable, unplaced, or anchored to a specific board edge.
- Edge anchoring is a hard constraint: the component must remain on its assigned edge. It may slide along that edge unless separately position-locked; it must never migrate to another edge or into the board interior.
- Exact position/orientation locking is independent of edge anchoring. An edge-anchored component is not automatically position-locked.
- Footprints may intentionally overhang the board where their mechanical function requires it (for example, a USB socket passing through an enclosure panel). Validate electrical pads and mounting geometry using their own rules; do not automatically reject a footprint merely because its body extends beyond the board.
- If an assigned edge cannot be satisfied, the placement is invalid. Never soften or silently discard the edge requirement.
- These constraints belong to the shared engine and apply equally to CLI and GUI.

## Checks and skill level

Keep electrical correctness separate from construction quality.

- Definite shorts, unintended net joins, required open connections and verified polarity faults are hard failures.
- Warnings and good-practice advice must be evidence-based. Missing metadata means **unknown**, not an invented fault.
- Construction checks can assess jumper crossings/interference, track lengths, cut access, soldering access, spacing and capacitor placement where the circuit data supports the advice.
- The user chooses an electrical-check strictness from **Don't care** through **Critical**. This changes advisory/reporting behaviour, never makes a definite electrical short legal.
- Skill level (Beginner, Intermediate, Advanced, Expert) changes the amount and style of explanation, not the underlying electrical truth.

Route-Mate is for hobbyists building one-off stripboard projects. It should help people make a sound, buildable board without imposing irrelevant professional-PCB rules.

## GUI architecture

**Implemented GUI: PySide6 with Qt Widgets and QGraphicsView.** The repository now contains an early-stage desktop GUI in `gui/main.py`.

The current GUI can:

- open a Karl/Route-Mate project JSON file;
- collect actual physical and preferred board dimensions;
- run collector validation and Electrical Sanity checks;
- preserve and render the component positions already present in the project using the public front renderer, with alternating row guides;
- run the repository's unittest suite during project loading;
- collect preliminary Locked / Unlocked, Edge and Slide settings for already-positioned components;
- invoke the shared deterministic net-aware `solve.quick_fit` engine after supported constraints;
- run the first-pass `solve.route_copper` router and independent copper-connectivity verification after a successful placement.

The GUI invokes **Quick Fit**, a deterministic greedy net-aware placement engine. It uses net assignments to score candidate positions, honours position-locked components, prevents physical overlap and reports any clearance reduction. After successful placement, it invokes the first-pass copper router. The router partitions horizontal strips with between-cuts, adds jumpers to reconnect same-net copper groups, preserves existing manual cuts/wires and accepts a result only when the independent copper verifier passes. Hard edge-anchor and sliding constraints are not implemented yet; if selected, the GUI stops without changing the layout.

**The GUI is not yet a complete stripboard design application.** Hard edge-anchor/sliding support, interactive component selection/highlighting, jumper path/crossing checks, cut-access checks, routing optimisation, full physical/construction verification and final build output are not implemented. The current router verifies electrical copper connectivity only; it does not prove that jumper bodies or cuts are physically accessible.

The GUI is a presentation and workflow layer. It must call the shared Route-Mate Python packages and consume the same project/result model as the CLI. It must not duplicate electrical checks, placement rules, routing or solver logic.

The component-side board is displayed through the front-side SVG renderer. Interactive selection/highlighting and independent interaction overlays remain future work.

See [GUI architecture and build notes](docs/GUI.md).

## Search fairness and performance

**Fairness means fixed work, not fixed time.**

- A candidate evaluation is one complete, defined decode-and-score workload.
- A solve uses a recorded input hash, engine version, seed list, per-seed evaluation budget, phase schedule, move set and ranking rules.
- Stop at the evaluation budget, never at a wall-clock timeout.
- More CPU cores may reduce waiting time; they must not silently increase the search budget.
- Parallelise independent seeds first and merge results deterministically.
- Prefer integer-first metrics and deterministic tie-breaking. Verify cross-platform reproducibility with tests; do not claim it before proving it.
- The independent verifier has final authority over physical and electrical legality.

The intended architecture is a deterministic Rust evaluation kernel, a Python CLI/orchestration layer initially, an independent verifier, and an optional WASM build of the same kernel for browser use. WASM is a distribution target, not a second solver.

## Development status

Route-Mate is under active development. The repository currently contains:

- a project collector and normalisation layer;
- the Electrical Sanity package;
- a front-side SVG board renderer;
- an early-stage PySide6 desktop GUI (`gui/main.py`);
- a deterministic net-aware placement module (`solve/quick_fit.py`) plus the earlier first-fit baseline (`solve/quick_place.py`);
- a legacy first-pass deterministic copper router (`solve/route.py`) and electrical copper-connectivity verifier (`solve/verify.py`), neither of which implements the frozen physical model;
- benchmark fixtures and automated tests for the implemented modules.

The desktop GUI is real but incomplete. It handles project loading, board-dimension entry, collector/electrical checks, component-side rendering, a repository test run, preliminary placement-lock questions, Quick Fit placement and first-pass copper routing with independent connectivity verification. The component-side preview draws jumper connections as straight lines but does not yet draw strip cuts.

Quick Fit is an initial deterministic greedy net-aware component placer, not a complete solver. It does not yet enforce hard edge anchors/sliding. The v1.21 first-pass router places cuts and uses a deterministic Manhattan minimum spanning tree of endpoint links. This is legacy behaviour only and conflicts with the frozen physical model in important respects: it supports assumptions beyond the initial between-hole-only model and does not represent/verify physical jumper paths or cut accessibility. Do not extend it. Replace it in the ordered gates in [PHYSICAL_MODEL_SPEC.md](docs/PHYSICAL_MODEL_SPEC.md).

The locked physical construction rules and implementation sequence are defined only in [Physical Model Specification v1.0](docs/PHYSICAL_MODEL_SPEC.md). The [stripboard design research](docs/STRIPBOARD_DESIGN_RESEARCH.md) is background/reference material, not a competing specification. The current v1.21 Manhattan endpoint connections are legacy electrical links only, not physical wire paths.

There is no packaged macOS or Windows desktop application yet. The GUI runs from the development environment; standalone packaging and clean-machine testing remain outstanding.

A documented feature, target behaviour or architecture decision is not proof that the executable already implements it. The sections below distinguish current implementation from intended behaviour.

## Development rules

- Preserve original source data and identifiers.
- Never turn hard physical constraints into soft score penalties.
- Never silently invent missing electrical or footprint information.
- Keep CLI and GUI on the same engine and validation rules.
- Reuse proven work where its licence permits, with attribution.
- Keep experiments reproducible and retain benchmark inputs/results.
- Make the cleverness live inside the software; keep the user's workflow understandable.

## Benchmarks

Benchmark inputs and known reference results live under [benchmarks](benchmarks/). A historical result is a target for reproduction, not a Route-Mate achievement until the current engine independently reproduces and verifies it.
