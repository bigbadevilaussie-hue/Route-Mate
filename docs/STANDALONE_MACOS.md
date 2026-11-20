# macOS standalone build

## Status

**macOS standalone packaging has been built and exercised successfully on the Route-Mate development iMac.** The tested artifact is a PyInstaller windowed application bundle:

`/tmp/routemate-build/dist/Route-Mate.app`

This is a bundled desktop application, not a single-file executable. The build includes the Python runtime and application dependencies; a separate Python installation is not required to launch the bundle.

This test does **not** establish clean-machine compatibility, code-signing/notarisation for distribution, or a Windows build.

## Toolchain used

| Item | Observed value |
|---|---|
| Host | macOS Sonoma on iMac14,2 |
| Python | 3.13.16 |
| PyInstaller | 6.22.3 |
| GUI framework | PySide6 (project requirement: `PySide6>=6.7,<7`) |
| Entry point | `run_gui.py` |
| App name | `Route-Mate` |
| macOS icon | `icon/RouteMate.icns` |
| Tested application version | 1.26 |

The project GUI dependencies are listed in `requirements-gui.txt`. The versions above are the observed build environment, not a claim that every permitted PySide6 version has been tested.

## Build command

Run from the repository root. The icon path is deliberately absolute because PyInstaller resolves icon paths relative to its generated spec location when `--specpath` points elsewhere.

```bash
cd ~/Desktop/Route-Mate

python3 -m PyInstaller --clean --noconfirm --windowed \
  --name Route-Mate \
  --icon "$PWD/icon/RouteMate.icns" \
  --paths . \
  --distpath /tmp/routemate-build/dist \
  --workpath /tmp/routemate-build/work \
  --specpath /tmp/routemate-build \
  run_gui.py
```

Successful build output:

```text
Build complete! The results are available in: /tmp/routemate-build/dist
```

Launch the bundle:

```bash
open /tmp/routemate-build/dist/Route-Mate.app
```

The build and work directories are outside the repository. For builds placed inside the repository, `.gitignore` excludes root-level `/build/` and `/dist/`.

## Frozen-app test-runner behaviour

When a project is loaded, the development GUI runs the repository unittest suite through:

```python
[sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
```

In a PyInstaller frozen application, `sys.executable` refers to the packaged application executable. Starting that command as a subprocess launched another GUI instance instead of a Python test runner.

The GUI now checks `getattr(sys, "frozen", False)` in `_run_tests()`. In a frozen build it logs:

```text
[TEST] Skipped: running standalone application.
```

and returns success to allow the application workflow to continue. In normal source/development mode, the repository unittest suite still runs as before.

**Implication:** the standalone app does not execute the repository test suite at project-load time. Run tests separately in the development environment before packaging.

## Runtime verification performed

The v1.26 standalone bundle was launched and used to load `moto.json`. The captured application log showed:

- project import: 44 components, 0 warnings;
- Electrical Sanity: PASS, 0 errors and 0 warnings;
- existing component-side layout rendered with alternating row bands;
- frozen-app test runner skipped with the expected message;
- Quick Fit: 32 components placed, 12 off-board/excluded;
- first-pass copper routing: 50 cuts and 38 jumper wires added;
- independent copper verification: PASS, 35 nets checked;
- updated component-side and board-side production renders completed.

This verifies the tested workflow on the development iMac. It is not a physical-buildability certification. The same run explicitly warned that jumper wire paths, crossings, body clearance, soldering access, cut access and component-body interference are not yet modelled/checked. Hard edge anchors and sliding are also not implemented. See the physical model specification and current GUI status for those limitations.

## Repeatable release checklist

- [ ] Confirm the intended version in `VERSION`, `GUI_VERSION` and `CODE_VERSION`.
- [ ] Run the repository test suite in the source/development environment.
- [ ] Build using the command above.
- [ ] Launch the resulting `.app`.
- [ ] Load representative Moto and Audio projects.
- [ ] Confirm there is no second GUI instance when a project is loaded.
- [ ] Confirm project loading, validation, rendering and file dialogs work.
- [ ] Review the application log for missing resources or plugin errors.
- [ ] Test on a clean macOS machine without the development Python environment.
- [ ] Decide and document signing/notarisation requirements before distributing outside the development machine.

## Not yet verified

- Clean-machine macOS installation/launch.
- macOS signing and notarisation for distribution.
- Windows packaging and runtime.
- Installation/update/uninstall workflow.
- Whether every optional project/resource path is bundled correctly for projects beyond the tested Moto fixture.
