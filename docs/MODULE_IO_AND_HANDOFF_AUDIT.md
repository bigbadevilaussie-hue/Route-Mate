# Route-Mate Module I/O and Pipeline Handoff Audit

> **HISTORICAL AUDIT WITH APPENDED IMPLEMENTATION UPDATES:** Early gap statements describe the audited branch, not necessarily current `main`. The sidecar/handoff design in §5 remains the reference contract; see [Documentation map](README.md) and [PRE-SOLVE handoff](PRE_SOLVE.md). Check live code for implementation status.

**Audit target:** `gate1-geometry-contract`  
**Audit basis:** source inspection of every production Python module in the branch, plus the current README, CLI/GUI documentation, Gate 0 audit and locked Physical Model Specification.  
**Purpose:** document what modules actually consume and return today, identify where findings are lost, and define a practical shared storage/handoff contract.  
**Status:** source audit plus initial contract implementation. The contract types and unit tests now exist on this branch; existing processing modules are not yet adapted to use them, and no project format or solver behaviour has been changed.

## 1. Executive finding

Route-Mate already has the intended IN → PREPARE → SOLVE → DISPLAY workflow. The README explicitly says each stage passes a defined project model to the next, and that GUI and CLI use the same engine and result model.

The current implementation does not yet provide that end-to-end handoff.

Most modules accept a plain project dictionary and return either:
- a modified/copied project dictionary;
- a separate report dictionary;
- a list of strings; or
- a low-level geometry value.

There was no common stage-result type or persistent findings collection. The first implementation increment now adds shared contract records in `pipeline/contracts.py`, but existing modules and the GUI are not yet adapted to use them. Findings therefore remain ephemeral in the current end-to-end workflow. Consequently, downstream modules often receive the project but not the reasoning, warnings, rejected alternatives or unresolved questions discovered upstream.

**Recommendation:** retain the existing canonical project dictionary as the authoritative circuit/layout data, and add a separate Route-Mate run-state envelope around it. Pass a typed stage result between modules and persist that envelope as a sidecar state file. Do not put Route-Mate workflow metadata into Karl's source JSON or invent another board-dimension source.

## 1.1 Implementation progress

The first contract increment has been added on `gate1-geometry-contract`:

- `pipeline/contracts.py`: `PipelineContext`, `StageResult`, `Finding`, deterministic project SHA-256 and stable finding-ID helpers.
- `pipeline/__init__.py`: public exports for those contract types.
- `tests/test_pipeline_contracts.py`: tests for hashing, stable identity, validation, JSON round trips, unknown-field preservation and non-destructive finding hand-off.

This is a data-contract foundation only. It does not yet wrap collector/sanity/solver/router/verifier outputs, persist a sidecar, or change GUI/CLI orchestration. Existing callers still use their original return shapes until the next integration increment.

## 2. Existing workflow and actual module inventory

The production Python files in this branch are:

- Root: `collect.py`, `adjacency.py`, `board_geometry.py`, `placement_policy.py`
- PREPARE: `prepare/sanity/electrical.py`
- SOLVE: `solve/quick_fit.py`, `solve/quick_place.py`, `solve/route.py`, `solve/verify.py`
- DISPLAY: `render/render.py`, `render/_front.py`, `render/standalone_bridge.py`
- GUI/entry points: `gui/main.py`, `run_gui.py`

`render/_geometry.py` is now a compatibility re-export of shared geometry, not an independent geometry implementation. Package `__init__.py` files expose imports but do not implement a processing stage.

Tests and benchmark JSON/netlist files are inputs/fixtures, not pipeline modules.

## 3. Module-by-module I/O audit

### 3.1 IN — `collect.py`

**Inputs**
- Required Karl/Stripboard Editor project JSON.
- Optional KiCad `.net` file.
- Optional KiCad `.pretty` directory, ZIP, or `.kicad_mod` file.
- Explicit actual board rows/columns and preferred rows/columns with fixed/max modes.
- Project ID and output directory.

**Processing**
- Validates the project root and required arrays/board object.
- Canonicalises a limited set of known legacy built-in pin IDs. This mutates the supplied dictionary.
- Applies GUI-like defaults for definitions, schematic rotation, net labels, schematic wires, wiring mode, cuts and wires. This also mutates the supplied dictionary.
- Parses optional KiCad module pads and user labels into discrete grid footprints; merges definitions by component-label/filename matching.
- Checks optional .net node-record count against JSON pin-assignment count. This CLI check is a count check, not the full connectivity-partition comparison.
- Computes board estimate, netlist hash, layout hash and campaign index data.
- Copies input source files into the campaign source directory.

**Outputs**
- Mutated/normalised project JSON at `projects/<id>.json`.
- `index.json` campaign summary.
- `manifest.json` containing source paths/hashes, board settings, counts, board estimate, warnings and connectivity policy.
- Copies of supplied source files.
- Console summary and warnings.

**Findings currently produced**
- String warnings for known pin-ID normalisation, ambiguous footprint filename matches, unsupported footprint source, unresolved definitions, estimated board-fit concerns and some footprint short conditions.
- Some facts are represented as summary counts rather than component-addressable findings.

**Handoff gaps**
- Warnings are strings, not structured records with stable IDs, subject IDs, severity, evidence and resolution state.
- The CLI persists a manifest, but the GUI does not use the CLI collector pipeline; it calls only `validate_project` and performs its own board-size dialog.
- The collector's mutating normalisation and the GUI's copy-based load path are different entry paths.
- A board estimate and a selected physical board are distinct facts; the estimate must never overwrite the actual board dimensions.
- Source hashes are recorded in the CLI manifest but are not carried into later solver/render reports.

### 3.2 PREPARE — `prepare/sanity/electrical.py`

**Inputs**
- Canonical project dictionary.
- Optional KiCad netlist text.

**Processing**
- Checks project collection shape, component/net IDs, duplicate IDs, assignment references, duplicate/multi-net pin assignments and footprint pin references.
- If .net text is supplied, maps component labels to IDs and compares JSON and netlist connectivity partitions.

**Outputs**
- Report dictionary: `status`, `errors`, `warnings`, `counts`, and `netlist_checked`.

**Handoff gaps**
- The report is separate from the project and has no common schema with collector warnings or solver reports.
- It is not attached to a shared pipeline state or persisted by the GUI.
- The GUI logs the report and stops on FAIL, but does not retain the PASS report for SOLVE or DISPLAY.
- A report does not currently identify the exact source artifact/hash it checked.

### 3.3 Shared geometry — `board_geometry.py`

**Inputs**
- Board row/column dimensions and integer hole coordinates for `BoardGrid`.
- Component dictionaries and resolved footprint definitions for `component_geometry`.
- Component/definition data for `resolve_definition`.

**Outputs**
- Exact normalized logical points and segments.
- Absolute pin records and discrete body-cell coordinates.
- Built-in definitions and rotation/definition helpers.

**Handoff gaps**
- This is a useful shared calculation library, not a project-stage processor. It does not return findings or provenance.
- Coordinates are normalized in hole-pitch units; they are not measured millimetres or physical body envelopes.
- It must not become a second source of board dimensions. The board dimensions remain those already present in the collected project.
- Physical envelopes and access geometry remain unresolved under Gate 1.

### 3.4 Shared pin conflict analysis — `adjacency.py`

**Inputs**
- Iterable pin records in the module's tuple contract: row, column, net and reference.
- For candidate checking, a candidate pin iterable and an existing hole-index dictionary.

**Outputs**
- Lists of conflict dictionaries describing same-hole and adjacent-hole different-net conflicts.
- `hole_index` produces a hole-to-pin index.

**Handoff gaps**
- Results are transient helper output. Callers decide whether to reject, report or resolve them.
- The conflict records are not added to a persistent project findings collection.
- The helper detects adjacency; it does not establish whether an accessible isolating cut makes the adjacency legal under the frozen model.

### 3.5 Shared placement policy — `placement_policy.py`

**Inputs**
- One component dictionary.

**Outputs**
- Boolean indicating whether the component is excluded from component-body placement under the current off-board/board-excluded/GPS policy.

**Handoff gaps**
- The boolean deliberately compresses several source semantics. Downstream users must preserve the distinction between explicit off-board components with saved leads and components excluded from board placement.
- It provides no explanation or finding object. Callers needing an audit trail must record why a component was excluded.

### 3.6 SOLVE — `solve/quick_fit.py`

**Inputs**
- Project dictionary.
- Optional integer logical-cell clearance (default 1).

**Processing**
- Deep-copies the input.
- Resolves definitions, pins, assignments and off-board saved leads.
- Places on-board components using deterministic net-aware scoring and discrete occupancy.
- Rejects unsupported edge-anchor/sliding constraints and reports geometry/constraint failures.

**Outputs**
- Result dictionary containing status, project, errors, warnings, placed count and excluded count. Success returns the placed project and placement metrics including the selected clearance/score information.

**Handoff gaps**
- The project and report are coupled in one ad hoc dictionary, unlike PREPARE's separate report.
- Rejected candidate positions and their reasons are not exposed as a durable findings/diagnostics artifact.
- Logical clearance is a cell count, not measured physical clearance.
- The current algorithm does not implement the frozen cut-aware adjacent-pin rule or hard edge/slide constraints.
- The GUI logs warnings/errors but does not retain a structured placement report.

### 3.7 SOLVE — `solve/quick_place.py`

**Inputs**
- Project dictionary.

**Processing**
- Deep-copies the project.
- Uses resolved discrete footprints and first-fit placement, preserving locked positioned parts and placing other included components largest-first.

**Outputs**
- Result dictionary with status, project, errors and placed count.

**Handoff gaps**
- It is a separate legacy placement engine with a different result shape from Quick Fit.
- It does not return a structured findings report or reusable placement diagnostics.
- The GUI currently uses Quick Fit, not Quick Place.
- It should remain explicitly identified as a legacy/alternative placement path until its intended role is decided; do not merge its semantics into Quick Fit silently.

### 3.8 SOLVE — `solve/route.py`

**Inputs**
- Placed project dictionary, including board dimensions, component definitions/positions, net assignments, off-board leads, existing cuts and wires.

**Processing**
- Deep-copies the project.
- Resolves physical terminal holes.
- Detects different-net terminals sharing one hole.
- Adds between-hole cuts where required by its legacy copper partitioning.
- Groups copper and connects same-net groups using a deterministic Manhattan minimum spanning tree of endpoint links.
- Calls `solve.verify.verify_project`.

**Outputs**
- Result dictionary containing status, project, errors, warnings, counts of added cuts/wires and nested verification report.

**Handoff gaps**
- The output status `ROUTED` means the legacy electrical verifier passed, not that physical routing is legal.
- Warnings explicitly state that wire paths, crossings, body clearance, soldering access and cut access are not modelled.
- The nested verification report is not a physical verification report.
- The route result does not provide a first-class copper segmentation/run model or physical wire-body geometry.
- This implementation is legacy only under the locked Physical Model Specification and must not be represented as physically buildable.

### 3.9 SOLVE — `solve/verify.py`

**Inputs**
- Project dictionary with board dimensions, components, assignments, cuts and wires.

**Processing**
- Builds a union-find connectivity model over board holes.
- Applies between-hole and legacy hole cuts; rejects unsupported `below` cuts.
- Joins jumper endpoints electrically.
- Resolves on-board pads and off-board saved lead coordinates.
- Checks net connectivity, shorts/opens and adjacency conflicts.

**Outputs**
- Independent electrical connectivity report with status, errors, warnings and counts.

**Handoff gaps**
- Despite the historical module name and some documentation language, it is not the independent physical verifier required by the frozen specification.
- It accepts legacy hole cuts and treats a wire as a direct endpoint union; it does not inspect physical path, body, crossing, cut access or endpoint access.
- It must be reported as electrical verification only until a separate physical verifier exists.
- Its report is nested in route output but is not independently retained by the GUI.

### 3.10 DISPLAY — `render/render.py` and `render/_front.py`

**Inputs**
- Project dictionary.
- Rendering options: labels, pin labels and scale.

**Processing**
- Resolves definitions, board dimensions, component positions, nets and existing endpoint wires.
- Generates a component-side SVG string.

**Outputs**
- SVG text; the public writer optionally writes the SVG and returns its path.

**Handoff gaps**
- Renderer output is visual output, not a solver result or validation report.
- It receives no structured findings, so it cannot display upstream warnings/diagnostics except those encoded in the project itself.
- The current front renderer draws jumper endpoints as straight SVG lines and does not draw cuts or copper-side physical geometry.
- Rendering must never upgrade an electrical PASS to a physical PASS.

### 3.11 DISPLAY — `render/standalone_bridge.py`

**Inputs**
- Project JSON path and output directory.
- External production renderer checkout/runtime.

**Outputs**
- Top-side SVG text, copper-side SVG text and renderer console log.

**Handoff gaps**
- It is a rendering bridge, not a pipeline stage. It consumes a file path rather than the shared in-memory project/result model.
- It returns no structured report or findings and does not establish physical validity.
- Renderer dependency/version and input hash should be captured in the run provenance when this bridge is used.

### 3.12 GUI and entry points — `gui/main.py`, `run_gui.py`

**Inputs**
- GUI opens a project JSON file.
- User supplies actual and preferred board dimensions through a dialog.
- User supplies per-component lock/edge/slide/remove answers.
- GUI invokes collector validation, electrical sanity, tests, renderer, Quick Fit and legacy copper routing.

**Outputs**
- In-memory `self.project`.
- SVG displayed in the board view.
- Text log, message boxes and status-bar messages.

**Observed handoff**
- Collector validation warnings are popped from the project and logged.
- Electrical sanity report is logged, then discarded.
- Lock answers are written directly into component dictionaries.
- Quick Fit returns a project and report; report details are logged.
- The placed project is passed to `route_copper`.
- Routing report is logged; the returned project is used for rendering.
- Renderer receives the project, not the upstream reports/findings.

**Handoff gaps**
- The GUI is currently the orchestration layer, but its pipeline state is only an in-memory project dictionary plus transient local variables.
- Findings are converted to log strings rather than passed to the next module.
- The project is not saved as a persistent run with stage reports, source hashes and findings history.
- GUI workflow is not currently using the CLI collector's manifest/index/source-copy output.
- GUI and CLI therefore do not yet share one complete orchestration/result contract, even though they share several processing functions.

## 4. Cross-cutting problems

1. **Shared result contract is partially integrated.** Contract adapters now wrap the existing collector manifest/index and electrical sanity report. The legacy stage APIs and algorithms remain unchanged; GUI/CLI orchestration and the remaining SOLVE/DISPLAY adapters are still outstanding.
2. **Findings are retained by the new adapters, but not yet by the live workflow.** Collector warnings and electrical sanity errors/warnings can now be converted to stable Finding records and StageResult references; repeated identical source messages remain separate findings. The GUI/CLI does not yet call these adapters or persist the ledger.
3. **No provenance chain.** Derived geometry, selected constraints and reports do not consistently identify the input hash, producing module/version or source evidence.
4. **No distinction between facts and interpretations.** For example, an off-board boolean can hide whether saved physical leads exist.
5. **No stage snapshots.** It is difficult to inspect exactly what PREPARE or SOLVE received and produced.
6. **No stable finding lifecycle.** A later stage cannot explicitly resolve, supersede or invalidate an earlier finding.
7. **Two entry paths.** CLI collection writes a campaign project and manifest; GUI loads JSON directly and runs only part of that path.
8. **Project data and run metadata are mixed inconsistently.** Some functions mutate dictionaries, others deep-copy them, while reports sit outside the project.
9. **Legacy status ambiguity.** `ROUTED` and `verify_project` can be read as physical success even though they establish electrical connectivity only.

## 5. Proposed storage and handoff design

### 5.1 Keep the source/canonical project separate from pipeline state

Do not rewrite Karl's source JSON to store Route-Mate findings. Do not add a second board-size configuration.

Use two persisted files per Route-Mate project/run:

- **Project file:** the canonical project dictionary already consumed by existing modules. It contains board dimensions, components, definitions, assignments, cuts, wires and layout state.
- **Run-state sidecar:** `<project-name>.routemate-state.json`. It contains source provenance, stage results, findings, artifacts and the current pipeline status.

The sidecar references the canonical project by relative path and SHA-256. If the project changes, the sidecar must mark downstream stages stale rather than silently reuse old results.

The existing collector `manifest.json` can be migrated/represented as the IN-stage provenance record; it should not become a competing project model.

### 5.2 One shared in-memory pipeline envelope

Introduce a small shared contract module (proposed name: `pipeline/contracts.py`) with three principal records:

- `PipelineContext`: run identity, source provenance, canonical project reference/data, stage history, findings ledger and artifacts.
- `StageResult`: stage name, status, input project hash, output project hash, project delta or output project, findings, metrics and artifact references.
- `Finding`: stable finding ID, code, severity, status, message, subject references, location, evidence/provenance, producer stage and optional resolution/supersession reference.

A stage should receive the current context/project plus its explicit options and return a StageResult. The orchestrator applies the result, appends findings and makes the updated context available to the next stage. Modules should not reach backwards into GUI state or write directly into another module's private data.

### 5.3 Finding record

Recommended minimum shape:

```json
{
  "finding_id": "prepare:unknown-footprint:<component-id>",
  "code": "unknown_footprint",
  "severity": "warning",
  "status": "open",
  "message": "Component footprint definition is unresolved.",
  "producer": {
    "stage": "prepare",
    "module": "prepare.sanity.electrical",
    "version": "..."
  },
  "subjects": [
    {"type": "component", "id": "<stable-component-id>"}
  ],
  "location": null,
  "evidence": {
    "field": "defId",
    "value": "<source-def-id>"
  },
  "resolution": null
}
```

Use stable source IDs, not labels, as primary references. Labels are display text and may not be unique. Findings should have a machine-readable code and severity; the message is for people. Keep evidence concise and structured.

Suggested severities: `info`, `warning`, `error`, `blocker`.

Suggested statuses: `open`, `acknowledged`, `resolved`, `superseded`.

A later stage may resolve a finding only by recording evidence and the resolving stage. It must not delete the original finding. If new evidence invalidates a prior conclusion, mark it superseded and link the replacement.

### 5.4 Stage result record

Recommended shape:

```json
{
  "stage": "solve.placement",
  "status": "completed",
  "input_project_sha256": "...",
  "output_project_sha256": "...",
  "started_at": "...",
  "completed_at": "...",
  "module": "solve.quick_fit",
  "module_version": "...",
  "options": {"clearance_holes": 1},
  "metrics": {"placed": 33, "excluded": 11},
  "findings": ["<finding-id>"],
  "artifacts": [],
  "summary": "Placement completed."
}
```

Use stage statuses that do not conflate execution and correctness, for example: `not_run`, `running`, `completed`, `failed`, `blocked`, `stale`. The stage's domain result (such as electrical PASS/FAIL) belongs in a separate report field or finding set.

### 5.5 Sidecar layout

A sidecar should be self-describing and versioned:

```json
{
  "schema": "route-mate-run-state",
  "schema_version": 1,
  "run_id": "...",
  "project": {
    "path": "project.json",
    "sha256": "..."
  },
  "sources": [],
  "pipeline": {
    "current_stage": "prepare",
    "stages": {},
    "findings": [],
    "artifacts": []
  }
}
```

Persist stage output project snapshots only where useful. The canonical project remains the current working project; stage records retain hashes and reports. For reproducibility/debugging, retain the original imported project and a snapshot after each stage that materially changes placement/cuts/wires. Avoid duplicating large unchanged project data at every helper call.

Write state atomically (temporary file then rename), validate the schema version on load, and never silently discard unknown sidecar fields. Store relative paths where possible. Keep original source files and their hashes in the provenance section.

### 5.6 What is passed forward

| Handoff | Project data passed | Findings/reports passed |
|---|---|---|
| IN → PREPARE | Validated canonical project, board dimensions, source IDs, definitions, assignments, saved positions, cuts/wires, off-board flags/leads | Source hashes, import/normalisation warnings, missing/ambiguous definitions, netlist comparison, board estimate and its assumptions |
| PREPARE → SOLVE | Same project plus explicitly accepted user constraints and resolved geometry references | Electrical sanity report, unresolved pin/footprint issues, geometry findings, adjacency findings, constraints not supported |
| Placement → copper segmentation | Placed project and stable component/pin coordinates | Placement status/metrics, occupancy/conflict findings, locked/excluded component decisions, unresolved placement constraints |
| Segmentation → jumper routing | Explicit copper runs, cut records and terminal-to-run mapping | Cut decisions, isolated runs, cut conflicts/access findings and provenance |
| Jumper routing → independent verification | Full candidate layout including complete jumper geometry and cuts | Router decisions and candidate diagnostics; verifier must independently recompute legality |
| Verification → DISPLAY | Verified candidate project and separate electrical/physical reports | All open/resolved findings, exact locations, severity, evidence and final acceptance decision |
| DISPLAY → saved project/run | Project plus visual/build artifacts | Renderer version/options, artifact paths/hashes and the exact project hash rendered |

### 5.7 Do not build a message bus

This is a single-user desktop/CLI application, not a distributed service. Do not add Kafka, Redis, a database server or an asynchronous event bus for this problem.

Use:
- ordinary Python dataclasses (or equivalent typed records) in memory;
- one explicit orchestrator to call stages in order;
- JSON serialization for the sidecar and machine-readable reports;
- immutable/copy-on-write project transitions at stage boundaries;
- stable finding IDs and project hashes to detect stale results.

This gives every module the same findings and project context without coupling modules to each other.

## 6. Migration plan — small, testable increments

1. **Freeze this audit as the baseline.** No solver behaviour change.
2. **Define and test the contract types.** Round-trip JSON tests, stable IDs, severity/status validation, unknown-field policy and project hash tests.
3. **Wrap existing outputs.** Collector and electrical sanity adapters are implemented. Quick Fit, Quick Place, route and independent verification adapters are now also implemented, with adapter-level regression tests. No underlying algorithm is changed.
4. **Add the pipeline orchestrator.** One shared path used by CLI and GUI; GUI becomes a client of it.
5. **Persist/load the sidecar.** Atomic writes, source/project hash validation, stale-stage propagation and recovery tests.
6. **Connect DISPLAY.** Renderer receives the project plus a read-only findings/report view; it must not change result status.
7. **Only then deepen Gate 1 physical geometry and subsequent physical routing gates.** The handoff work does not waive the physical-model freeze or its unresolved measurement blockers.

## 7. Acceptance tests for the handoff system

- A collector warning is still present after PREPARE, SOLVE and DISPLAY.
- A downstream stage can add a finding without deleting upstream findings.
- A finding can be resolved/superseded with an audit trail, not erased.
- Stable component/net IDs survive every stage and sidecar round trip.
- Board dimensions come from the collected project/user-selected actual board and remain unchanged unless an explicit board-edit action occurs.
- A project hash change marks dependent stage results stale.
- GUI and CLI produce the same stage results for the same inputs/options.
- A failed/blocked stage prevents dependent stages from running but preserves its report and the last valid project snapshot.
- Electrical PASS remains distinct from physical PASS; legacy router output cannot satisfy physical acceptance.
- Renderer output records which project hash and options it rendered.
- Saving/reloading the run preserves findings, reports, provenance and project state.

## 8. Scope and limitations of this audit

This is a source-level audit of the current branch and its documented public workflow. It is not a claim that every possible runtime path, third-party renderer implementation, or external Karl export variant has been exercised. The current unit-test suite establishes regression coverage for implemented behaviour; it does not prove the proposed pipeline contract exists.

### 8.1 Implementation progress — IN, PREPARE and SOLVE adapters\n\nThe first output adapters now exist in `pipeline/adapters.py`:\n\n- `collector_stage_result()` wraps the canonical collected project, existing manifest and index entry. It carries collector warnings as stable warning findings, captures board options and collection metrics, retains the original manifest/index in the report, and records the output project hash. The source-project hash is recorded only when the caller supplies the parsed source project; it is not guessed from the manifest's raw-file hash.\n- `electrical_sanity_stage_result()` wraps the existing electrical sanity report. Each error/warning becomes a stable finding. The original PASS/FAIL report is retained, while the StageResult execution status is completed for either domain outcome. Input/output hashes are the same because this stage does not modify the project.\n- Both adapters return a StageResult plus Finding records. They do not mutate the project or alter the existing collector/sanity functions. `pipeline/__init__.py` exports both adapters.\n- `tests/test_pipeline_adapters.py` covers report retention, stable/deduplicated finding IDs, hashes, PASS/FAIL distinction and hand-off into PipelineContext.\n\nThe SOLVE/verification adapters now cover:
- `quick_fit_stage_result()`: placement counts, requested clearance and original Quick Fit report, warnings/errors, and input/output project hashes.
- `quick_place_stage_result()`: placement counts and the original first-fit result, including its PASS/FAIL domain status.
- `route_stage_result()`: cuts/wires added, routing warnings/errors, the complete route result and nested verifier report.
- `verification_stage_result()`: independent verifier PASS/FAIL, counts, warnings/errors, with identical input/output project hashes because verification is read-only.

All adapters use a completed StageResult to mean the function returned a result; domain PASS/FAIL remains inside the retained report. Errors and warnings become separate findings. Repeated identical messages are retained as distinct findings with deterministic occurrence-based IDs.

The shared run-state layer is now implemented in `pipeline/orchestrator.py`:
- `PipelineRun.create()` starts a run from a source project and records its SHA-256 and provenance.
- `PipelineRun.record_stage()` appends a StageResult and its findings, advances the current project hash to the stage output hash, and persists by default.
- `PipelineRun.load()` validates and restores a sidecar.
- `PipelineRun.save()` writes the sidecar through a temporary file and atomic rename.
- `sidecar_path()` uses the sibling name `<project-stem>.routemate-state.json`.
- The canonical project JSON is never rewritten by the run-state layer.

The GUI is now connected to this shared state:
- JSON validation and explicit board sizing are recorded as `IN.project_import`. This is intentionally separate from `collector_stage_result()`: the GUI import path does not create the collector manifest/index, so it does not fabricate those artifacts.
- Electrical sanity is recorded as `PREPARE.electrical`, including findings even when the domain result is FAIL.
- User lock/remove/edge/slide responses are recorded as `PREPARE.constraints`.
- Quick Fit, copper routing and the route's verifier report are recorded through their existing adapters.
- Each recorded stage saves the sidecar. The GUI log reports the sidecar filename.
- Existing GUI interaction order and solver calls remain unchanged. Unsupported edge/slide constraints still stop Quick Fit as before.

The collector CLI remains a standalone IN command; there is not yet a complete shared CLI workflow. DISPLAY artifact integration and stale-stage propagation remain future work. Test execution remains the user's local verification step.
