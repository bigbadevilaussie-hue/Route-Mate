# Route-Mate

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
- A component may be fully position-locked, initially placed but movable, unplaced, or edge-locked.
- Edge locking is available only for components whose footprint supports edge mounting.
- Edge lock selects top, bottom, left or right. The component must physically meet that edge; it may be fixed there or slide along it.
- Fully locked means exact position and orientation. Edge-sliding means fixed to the selected edge but free to move along it.
- These constraints belong to the shared engine and apply equally to CLI and GUI.

## Checks and skill level

Keep electrical correctness separate from construction quality.

- Definite shorts, unintended net joins, required open connections and verified polarity faults are hard failures.
- Warnings and good-practice advice must be evidence-based. Missing metadata means **unknown**, not an invented fault.
- Construction checks can assess jumper crossings/interference, track lengths, cut access, soldering access, spacing and capacitor placement where the circuit data supports the advice.
- The user chooses an electrical-check strictness from **Don't care** through **Critical**. This changes advisory/reporting behaviour, never makes a definite electrical short legal.
- Skill level (Beginner, Intermediate, Advanced, Expert) changes the amount and style of explanation, not the underlying electrical truth.

Route-Mate is for hobbyists building one-off stripboard projects. It should help people make a sound, buildable board without imposing irrelevant professional-PCB rules.

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

The CLI contract and workflow are being documented before implementation. A documented option is a design contract, not a claim that the executable already supports it.

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
