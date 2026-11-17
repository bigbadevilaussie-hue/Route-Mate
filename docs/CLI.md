# Route-Mate CLI — agreed input contract

This document locks the user-facing input decisions agreed during product design. It is a contract for implementation; it does not claim that every switch is implemented yet.

## Human workflow

The CLI follows the same four stages as the GUI:

- IN
- PREPARE
- SOLVE
- DISPLAY

The user should not need to understand solver internals to start a project.

## IN — source files

Karl's Circuit Designer export provides:

| Input | Purpose | Requirement |
|---|---|---|
| Project JSON | Structured circuit/project data | Required |
| Netlist (.net) | Electrical connectivity | Required for the agreed full import |
| kicad.mod | Module/footprint definitions | Required where the exported project references it |

The CLI should accept the three paths explicitly. It must not require the user to rename the source files to fixed names. The importer must retain source IDs and unknown fields for round-trip safety.

Illustrative command shape (final spelling may be adjusted before implementation):

    route-mate prepare --json path/to/project.json --net path/to/project.net --mod path/to/kicad.mod

If a source is missing, malformed or inconsistent, stop with a useful error identifying the file and problem. Do not silently substitute guessed data.

### Collector board-size estimate

The collector writes an advisory board estimate to `index.json` and `manifest.json`, and prints tight and roomy suggestions. It uses known per-part dimensions, a one-hole spacing allowance and a routing-area factor. Component footprint overrides and project custom definitions take precedence over built-in size estimates. Rotated parts have their dimensions swapped where appropriate.

The estimate excludes components marked `offBoard` or `boardExcluded` from physical board area without removing their electrical data. Unknown footprint sizes use a visible 2×2 fallback and are listed in `unknown_size_parts`; they are not presented as known geometry.

This is a starting-size suggestion only. It never supplies or changes the mandatory physical board dimensions, and it is not a placement-feasibility proof.

## PREPARE — physical board

**Required:** actual physical board rows and columns. These are the dimensions of the board the user bought and are absolute solver limits.

Illustrative options:

    --board-rows 24
    --board-cols 56

**Optional:** preferred finished rows and columns. These express the user's preferred cut-down size. They may be smaller than the physical board; they can never enlarge the physical limits.

    --preferred-rows 24
    --preferred-cols 46

The solver may exceed the preferred size if necessary, but never the physical size. If it proposes a smaller finished board, all components, cuts, strips and jumpers must remain valid after the cut-down.

## PREPARE — component placement constraints

The shared project model must support these states:

| State | Meaning |
|---|---|
| Unplaced | Solver chooses position and orientation |
| Placed, movable | Supplied position is a starting point; solver may move it |
| Fully locked | Exact position and orientation cannot change |
| Edge-locked, sliding | Must physically touch a selected edge; may slide along it |
| Edge-locked, fixed | Must touch the selected edge and retain its exact position |

Edge lock sides: top, bottom, left, right.

Edge locking is offered only when the footprint/component is edge-mountable. The footprint boundary—not merely its origin—must meet the assigned board edge. Orientation and board-boundary legality still apply.

The CLI must be able to express per-component constraints without making them GUI-only settings. The exact syntax for naming individual components should follow stable source IDs from the imported project.

### Edge anchoring is a hard constraint

An edge-mounted connector is not the same thing as a position-locked component. These are independent constraints:

- **Required edge:** the specific edge the component is assigned to (top, bottom, left or right). This is a hard constraint. The solver must never move the component to another edge or into the board interior.
- **Sliding along that edge:** allowed unless the component is also position-locked. The solver may change its position along the assigned edge while keeping it on that same edge.
- **Exact placement lock:** a separate user-controlled constraint that preserves the exact position and orientation. Edge anchoring alone does not imply this lock.
- **Footprint overhang:** permitted where the component is designed to protrude beyond the board, such as a socket passing through an enclosure panel. Electrical pads and the footprint's mounting geometry must still satisfy their own explicit legality rules; do not assume the entire body must fit inside the board.
- **Unsatisfied edge constraint:** means no valid placement/solution. Never silently relax the edge requirement, substitute another edge, or convert it into a soft score penalty.

The edge is determined by the component's intended/current edge assignment, not whichever edge happens to be easiest for the solver. For example, the Moto-Mate USB module is assigned to the front edge so its USB socket can pass through the front panel. It may slide left or right along that front edge, but moving it to a side/rear edge or into the board interior is invalid. Its edge assignment does not, by itself, lock its exact position.

Audio-Mate and Moto-Mate both demonstrate that external connectors and controls commonly need deliberate edge access. Treat edge anchoring as a core stripboard placement capability, not an exceptional workaround.

## PREPARE — checks and user experience

Electrical-check strictness: **Don't care → Critical**.

Skill level: **Beginner / Intermediate / Advanced / Expert**.

These are separate settings:

- Check strictness controls how advisory findings are surfaced and how configurable warnings affect candidate preference.
- Skill level controls explanation depth and construction guidance.
- Neither setting can waive a proven short, unintended net join or other definite electrical failure.

Construction-quality checks are distinct from electrical correctness. Track length, jumper crossings, access to cuts/solder joints, spacing and capacitor placement should be assessed only when the relevant geometry and component data are available.

## SOLVE — fair work budget

The fair solve path is evaluation-budget based, not time based.

- Work unit: one complete decode + score of one candidate under the versioned evaluator contract.
- Fixed seed list and per-seed evaluation budget.
- Fixed phase schedule, move catalogue, acceptance rules and deterministic ranking.
- Parallelism across independent seeds by default.
- Core count does not increase the number of evaluations.
- Wall-clock limits may exist only as an explicit user-abort/safety mechanism; they must not define the advertised optimisation opportunity.

A run records its manifest, including input hash, engine version, seeds, budgets, phase costs, configuration and result metrics.

## DISPLAY

The result must make the physical build understandable:

- component positions and orientations
- board dimensions and any proposed cut-down
- strip cuts
- jumper endpoints and routes
- electrical and construction-check results
- reproducibility manifest and benchmark metrics

The CLI should support machine-readable output as well as a concise human summary. The GUI must consume the same result model.

## Not locked yet

Do not invent final switch names for per-component lock files, check presets or solve profiles until their data model and user interaction are implemented. The option categories and behaviour above are the agreed contract; the illustrative command shape is not a promise of a finished executable.
