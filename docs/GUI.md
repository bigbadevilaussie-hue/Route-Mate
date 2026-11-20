# Route-Mate desktop GUI

> **Physical-routing authority:** [Physical Model Specification v1.0](PHYSICAL_MODEL_SPEC.md) is the sole source of truth for cuts, jumper geometry, physical accessibility and acceptance. GUI behaviour must not imply that the legacy v1.21 electrical-only route is physically buildable. Keep electrical and physical results distinct; a solution is accepted only when both pass.

See [Documentation map](README.md) and [PRE-SOLVE intelligence handoff](PRE_SOLVE.md) for the existing preparation terminology and sidecar boundary.

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
- [x] GUI invokes shared Quick Fit, legacy v1.21 endpoint routing and electrical connectivity verification only.
- [ ] Replace legacy endpoint-link preview with physical jumper-path display and copper-side between-hole cut artwork, only after the frozen router/verifier gates pass.
- [ ] Display separate electrical and physical verification reports; never label electrical-only success as physically routed/buildable.
- [ ] Selection and lock/edge-anchor overlays.
- [x] macOS PyInstaller standalone bundle built and exercised on the development iMac (v1.26); clean-machine test still outstanding.
- [ ] Windows standalone build and clean-machine test.
