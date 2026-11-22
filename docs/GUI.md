# Route-Mate desktop GUI

> **Physical-routing authority:** [Physical Model Specification v1.0](PHYSICAL_MODEL_SPEC.md) is the sole source of truth for cuts, jumper geometry, physical accessibility and acceptance. GUI behaviour must not imply that the legacy v1.21 electrical-only route is physically buildable. Keep electrical and physical results distinct; a solution is accepted only when both pass.

See [Documentation map](../README.md) and [PRE-SOLVE intelligence handoff](MODULE_IO_AND_HANDOFF_AUDIT.md) for the existing preparation terminology and sidecar boundary.

## Route-Mate 1.41 — CPU portfolio and clearer solve feedback

**Current implementation on `main`.** The Qt solve coordinator runs a
`ProcessPoolExecutor` using spawned operating-system processes, not CPU-bound
Python threads. The startup speed probe informs a 3–4 process policy when
hardware permits; machines with fewer than three logical CPUs use what exists.
Worker count changes latency but does **not** increase the 24-placement-attempt
Quick Solve budget. Each worker owns a deterministic disjoint variant range.
The coordinator keeps Qt responsive and propagates cooperative Stop requests.

After loading the JSON and choosing the physical board dimensions, a separate
dialog asks for **Off (0)**, **Normal (1)** or **Wider (2)** free-hole nominal
spacing. The choice is kept outside the imported circuit JSON. It is an
advisory body-spacing preference, **not** evidence of measured clearance, and
the solver can report a compact routing fallback. Fixed locks and the actual
board envelope remain hard constraints.

A process searches for up to two distinct, independently checked candidates
within its assigned budget. Across workers the coordinator de-duplicates
signatures and prefers fewer assumed contact warnings, then better provisional
0–100 quality, then routing costs. **Two candidates are a search target, not a
guarantee:** if only one verified layout is found, it is retained and the GUI
reports that limitation. If the best reaches two candidates but has a provisional
score below 40/100 or more than one nominal contact, the remaining assigned
attempt slots are used to seek improvement (no budget increase). A routing result is rechecked by the desktop adapter
with electrical, grid and jumper audits; the GUI never describes an electrical
PASS as a measured physical PASS.

The Overview panel shows live worker/attempt details, elapsed duration,
estimated remaining time based on completed work, and candidate count.
The estimate is provisional, not a deadline; a candidate can end the
search early. SVG wheel zoom and the +/− magnification controls are disabled.
The **Fit** control and board panning remain. Qt SVG renderers are cached for
the two most recent board images to avoid unnecessary reparsing.

Run `python3 -m unittest discover -s tests -p 'test_*.py' -v` and
`python3 run_gui.py` to validate on the iMac. The historical 1.38 section
below describes previous behaviour, not the current process model.

## Route-Mate 1.38 — Quick Solve and desktop refresh

**Historical implementation note (prior to 1.41).** The desktop reads
its version from the repository `VERSION` file so the title bar and engine
version cannot silently drift.

- **Quick Solve** uses the existing routing-feedback engine and independently
  checked hole-graph router. It starts from an immutable *approved locked
  input*, never from the previously routed output. Repeating a solve creates
  a fresh sidecar run with new input checks rather than accidentally using
  the legacy incremental router.
- **Review Locks** opens a single table of positioned on-board parts. From
  either an imported layout or a successful solved board, choose **Auto-place**,
  **Fixed at current position**, **Fixed on this edge**, or **Slide along current
  edge**. This preserves net assignments and existing footprint definitions.
  The slider keeps the original side and rotation; all other fixed parts retain
  their exact board position. Invalid/missing anchors cause explicit failure,
  not silent relocation. Unlocking removes the old position before solving.
- Fixed-position preservation is checked again after solving. A solver result
  that shifts an absolute lock or moves an edge slider to another side is
  rejected and cannot be exported as a verified board.
- **Overview** shows seven actual project stages: import, netlist, footprints,
  locks, placement, routing and independent electrical verification. The former
  88% display was due to checking the wrong stage name for electrical sanity.
  Repository unit tests are CI/developer work, not a project-solving milestone
  and are no longer launched on every JSON import.
- **Activity** holds detailed logs and failures. The larger board canvas
  supports scroll-wheel zoom, click-and-drag panning, and +/−/Fit controls.
  Board summary distinguishes electrical PASS from pending real-world cut
  access and package measurements.
- **Open Solved** previews a previously saved routed JSON and flags outdated
  layouts failing jumper checks; use **Load JSON** for a new solve. **Save Solved
  JSON** never overwrites the imported source without selecting a different
  filename.

`VERSION` is now `1.38`. Existing frozen macOS application bundles are not
updated by a Git pull; launch the source GUI with `python3 run_gui.py`
until packaging is rebuilt.

## Solver mode decision

The GUI will expose Quick Solve and Hell Mode as **two modes of the same shared solver**, not separate engines. Both must use identical hard constraints and independent electrical/physical verification. Quick Solve failure means no verified candidate found within its budget, not proven impossibility. Hell Mode may refine a verified Quick Solve result. This is future behaviour, not a claim of current implementation. See [Solver Architecture Decision](SOLVER_ARCHITECTURE_DECISION.md); the locked [Physical Model Specification](PHYSICAL_MODEL_SPEC.md) takes precedence.

## Decision

**Selected stack: PySide6 + Qt Widgets + QGraphicsView.**

- Qt Widgets provides the desktop application shell and conventional controls.
- QGraphicsView provides the interactive stripboard viewport.
- QtSvg displays the SVG produced by the existing Python front renderer.
- Python remains responsible for project processing, validation, rendering and solving.
- PyInstaller is the selected starting point for standalone packaging.

QML is not part of the selected Route-Mate GUI architecture. This is a deliberate choice to use Qt Widgets for the application interface rather than introduce a second UI language.

## Application boundary

The GUI is a client of Route-Mate's Python packages, not a second implementation of the engine.

It must:

- load and save the canonical Route-Mate project;
- call the same collector, sanity checks and solver interfaces used by the CLI;
- display findings and results without changing their meaning;
- pass component locks, edge anchors, board dimensions and checking preferences into the shared project model;
- preserve source identifiers and project data;
- avoid implementing its own electrical or physical legality rules.

The GUI must not become a replacement schematic editor. Karl's Circuit Designer remains the circuit-design front end.

## Verified hole-graph solver wired to the desktop GUI (development branch)

The current `main` GUI uses the same Python
`solve_with_feedback` engine as the AUDIO and MOTO command-line benchmarks.
It does **not** run the legacy `route_copper(vertical_only=True)` on fresh
projects. The original router is retained as a fallback for inputs with manual
cuts/wires.

Workflow:

1. **Load JSON** → normalise, collect board dimensions, run sanity and
   the existing source-mode tests; show the initial layout and ask any saved
   component lock questions.
2. After those decisions, **Solve Board** runs placement feedback and
   negotiated-congestion hole routing from a Qt coordinator and OS processes, keeping the board
   preview and GUI event loop responsive. It respects fixed component positions.
3. Only a candidate passing `verify_project`, `quick_audit` and
   `audit_project` is displayed. The independent electrical result and
   **grid-level** physical/geometry statuses are logged separately.
4. **Component side** / **Copper side (mirrored)** switch between two SVG views
   generated from the *same* solved project by the existing production
   renderer. No new renderer geometry is implemented in the GUI.
5. **Save Solved JSON** exports the verified routed project without overwriting
   the imported source. **Render JSON** can display a previously exported
   AUDIO/MOTO board without solving it again.

The GUI records actual successful placement, routing and verification in its
existing pipeline sidecar. A failed search leaves the previous board preview
intact. UI status never promises measured component-body envelopes,
cut-tool accessibility, or buildability: these remain outside current grid
verification. The historical status and packaging sections below describe
earlier releases, not a macOS runtime check of this new GUI wiring.

## Jumper-to-component obstruction correction (development branch, 2026-11-22)

The previous MOTO board showed long vertical jumpers passing through the
drawn capacitor and other components. The original footprint `bodyCells`
do not represent the complete component artwork: electrolytic cans,
ceramic capacitors, LEDs and three-pin transistors may have no body
occupancy at all.

The shared `solve/wire_keepout.py` now provides conservative graphic
envelopes at board-hole scale, plus the existing declared body cells.
`solve/hole_router.py` excludes **complete jumper spans** crossing these
shapes. `solve/quick_rules.py` independently rejects any routed jumper
crossing component artwork or an intermediate component/connector pad.
All physical pads, including unassigned external leads, participate in
jumper clearance; copper strips may still run under electrically floating
pins. Placement adds extra copper escape space on boards containing
transistor packages rather than routing through their middle pins.

A route remains subject to independent electrical verification and
grid-level collision checks before appearing in the GUI. **These are
drawing-derived conservative keepouts, not measured package dimensions
or guaranteed real-world insulation/clearance.** The frozen physical
specification still requires measured envelopes, jumper diameter,
cut-tool access and certified physical verification before declaring a
board buildable.

## Board display

The existing public renderer API is:

```python
from render import render_front

svg = render_front(project)
```

The renderer returns SVG text and does not perform file I/O. The current front renderer is intended for PREPARE / placement previews; it is not a placement solver, route planner, connectivity verifier or copper-side renderer. Copper routing and verification live in the separate shared solve.route and solve.verify modules.

QtSvg is available in the checked Fan-Mate environment. The GUI can place the SVG into a QGraphicsScene using Qt's SVG graphics support and show that scene through QGraphicsView.

### Separate static board and interaction overlays

Keep the rendered board as a stable visual layer. Component selection, lock/edge-anchor highlighting and other transient interaction states should be separate scene items or overlays.

Changing the selected component should update the overlay, not regenerate the complete SVG. Regenerate the board only when underlying project geometry or rendered content changes.

The front renderer's public API should remain the boundary; GUI code should not import its private modules.

The current straight-line jumper preview is a legacy logical-link display, not a buildable wire route. The frozen model requires horizontal copper runs segmented by accessible between-hole cuts and single vertical jumper bridges. Diagonal, horizontal and multi-leg jumpers are prohibited. Component-side jumper artwork and copper-side cut artwork must eventually be separate, correctly oriented views. Follow [Physical Model Specification v1.0](PHYSICAL_MODEL_SPEC.md); the research document is background only.

## Suggested application structure

This is an implementation guide, not a claim that these files already exist.

- **Main window:** project lifecycle, menus, toolbars, workflow navigation and status.
- **Workflow panels:** IN, PREPARE, SOLVE and DISPLAY controls and reports.
- **Board view:** QGraphicsView scene containing the rendered SVG and independent interaction overlays.
- **Application/controller layer:** translates GUI actions into calls to Route-Mate Python packages and updates the view from returned project/report data.
- **Engine packages:** remain independent of Qt so CLI tests and future non-GUI use do not require a GUI runtime.

Long-running solve work must not block the GUI event loop. The current deterministic Quick Fit and first-pass copper router are invoked synchronously after PRE-SOLVE lock questions; this is acceptable only as a temporary small-fixture integration. A full Quick Fit / Quick Solve must run through an appropriate worker/task boundary and deliver progress/results back to the GUI thread.

## Cross-platform packaging

Target operating systems:

- macOS
- Windows

Use PyInstaller as the initial packaging tool. Build and test a native package on each target operating system; do not assume a macOS build can produce the Windows application or vice versa.

Packaging acceptance should include:

1. launch on a clean target machine without a separately installed Python;
2. verify Qt platform plugins and SVG support are included;
3. open a real Moto and Audio project;
4. display the board and exercise zoom/pan and component selection;
5. verify project loading, saving and file-dialog behaviour;
6. verify logs and error reporting are usable outside a development terminal.

See [macOS standalone build and toolchain](STANDALONE_MACOS.md) for the v1.26 PyInstaller build procedure and the successful development-iMac runtime test. A clean-machine test and Windows package are still outstanding.

## Toolchain evidence

Checked in the existing Fan-Mate virtual environment on the iMac:

| Item | Observed result |
|---|---|
| Python | 3.13.16 |
| PySide6 | Installed |
| Qt runtime | 6.12.0 |
| QtSvg import | Successful |
| QGraphicsView import | Successful |
| PyInstaller | Installed |
| PyQt5 / PyQt6 | Not installed |
| Nuitka | Not installed |
| pytest in this environment | Not installed |

These checks establish that the existing environment has the core Qt display and packaging tools. They do not establish the PySide6 package version, a Route-Mate-specific environment, successful PyInstaller packaging, or a working Windows build.

Create a dedicated Route-Mate virtual environment when GUI implementation begins. Reuse the verified toolchain versions deliberately; do not modify or repurpose Fan-Mate's environment.

## Renderer performance evidence

The user ran 200 timed calls to `render_front(project)` per fixture after one warm-up call, using `time.perf_counter_ns()`. The measurements are SVG generation only; they exclude file writing, SVG display, rasterisation and GUI interaction.

| Fixture | Average | Median | Minimum | Maximum | SVG output |
|---|---:|---:|---:|---:|---:|
| WR — `moto14wires30cuts.json` | 3.152 ms | 3.100 ms | 2.965 ms | 3.971 ms | 138,093 bytes |
| Audio — `audio10wires38cuts.json` | 3.093 ms | 3.041 ms | 2.893 ms | 4.017 ms | 131,327 bytes |

The two measured fixtures have similar SVG-generation times, approximately 3.1 ms median. This is evidence that Python SVG generation is not currently the obvious GUI performance bottleneck for these inputs. It is not a measurement of display latency or a cross-machine performance guarantee.

The next useful display benchmark is GUI-side: initial SVG scene load, zoom/pan responsiveness, and selection-overlay update latency.

## Current status

- [x] GUI technology selected.
- [x] Existing front SVG renderer available.
- [x] QtSvg and QGraphicsView imports smoke-tested in the Fan-Mate environment.
- [x] WR and Audio SVG-generation timings recorded.
- [ ] Dedicated Route-Mate GUI environment.
- [x] Early main window and QGraphicsView component-side board integration.
- [x] Development GUI invokes shared routing-feedback placement and verified hole-graph routing from a worker; keeps legacy routing for manually routed boards.
- [x] Existing production renderer shows both board sides from the automatically routed project, including vertical jumper segments and between-hole cuts at grid level.
- [ ] Certify measured component envelopes, jumper clearances and cut-tool accessibility; grid-only audits are not full physical sign-off.
- [ ] Display separate electrical and physical verification reports; never label electrical-only success as physically routed/buildable.
- [ ] Selection and lock/edge-anchor overlays.
- [x] macOS PyInstaller standalone bundle built and exercised on the development iMac (v1.26); clean-machine test still outstanding.
- [ ] Windows standalone build and clean-machine test.
