# Stripboard design research and routing direction

> **Authority notice:** This is background research, not the normative solver specification. The physical rules are frozen in [Physical Model Specification v1.0](PHYSICAL_MODEL_SPEC.md). If any statement or earlier proposed step below conflicts with that specification, the specification wins. In particular, older suggestions to defer cut-access verification or to retain hole cuts in the initial model are superseded. Follow the specification's implementation gates; do not treat this document's former §10/§11 plan as current.

## Karl solver research and architectural decision

The [Solver Architecture Decision](SOLVER_ARCHITECTURE_DECISION.md) records which ideas from Karlo Funke's Stripboard Editor are candidates for adaptation: sequence-pair skeletons, exact decoding, weighted union-find, longest-path compaction, copper grouping, Prim-style jumper connection, cut repair, obstacle geometry, annealing and reproducible multi-seed search. Route-Mate must enforce hard constraints before ranking layouts; Karl's cost penalties are not automatically legality rules. Quick Solve and Hell Mode will share one engine and independent verifier. These are planned directions, not implemented capabilities; the locked physical specification takes precedence.

## Purpose

This document records the stripboard construction findings that should guide Route-Mate's next routing stage. It distinguishes established construction principles and external software behaviour from Route-Mate's current implementation.

The most important correction to the v1.21 routing model is:

**A stripboard connection is not an arbitrary straight line between two holes. Copper strips are existing conductors. Cuts divide those conductors into usable electrical runs. Jumper wires bridge between runs.**

For the basic L-shaped connection discussed for Route-Mate, one leg is existing copper along a strip and the other leg is a jumper crossing the strips at right angles. The jumper is not two diagonal/Manhattan wire legs. Diagonal jumper geometry is prohibited.

## 1. Physical stripboard model

A standard stripboard has a regular hole grid, commonly on 2.54 mm (0.1 inch) pitch, with parallel copper strips on the underside. The holes along an uncut strip are electrically common. Components and jumper wires are fitted on the plain/component side; their leads pass through holes and are soldered to the copper on the underside.

The exact strip orientation is a board-model property. Some references and software use horizontal strips, others rotate the board in their coordinate system. Route-Mate must define its own orientation explicitly and consistently; it must not infer physical direction from a screen drawing.

Consequences for the solver:

- A continuous copper strip is already a conductor and should be represented as a connected path.
- Adjacent strips are not connected unless a component lead or jumper connects them.
- A component's physical pins occupy holes and connect to the copper run at those holes.
- The copper topology changes when cuts are introduced.
- A route must be evaluated against the actual copper segmentation created by those cuts.

## 2. Cuts create independent copper runs

A cut breaks continuity along a copper strip so that separate sections can carry different nets.

Common cut styles include:

- **Cut at a hole (via cut):** copper around the selected hole is removed. The hole is no longer available as an ordinary connection point.
- **Cut between holes:** copper is severed between adjacent holes. Both endpoint holes remain available.

The exact cut representation supported by a particular board and Route-Mate's project schema must be checked before implementation. Do not assume every cut style is physically or electrically interchangeable.

Important consequences:

- Cuts are part of the routing solution, not merely post-processing decoration.
- Different-net terminals on one unbroken copper run must be isolated.
- A cut can make one physical strip available as multiple independent runs.
- The verifier must build connectivity from actual cut locations, not from endpoint shortcuts.
- Cut locations must be shown clearly in the copper-side output.

Construction guidance recommends making track cuts before wiring and soldering, because solder can obstruct the cutting operation and make cuts harder to execute.

## 3. Copper and jumper geometry

The working Striprouter reference describes a two-layer routing model:

- One layer carries horizontal connections.
- The other layer carries vertical connections.
- Copper tracks are the pre-existing strip direction.
- Jumper wires cross the tracks at right angles.
- Wires must not overlap one another.

The coordinate orientation used by that reference is a software convention; Route-Mate should map the same physical rule onto its own board coordinates.

For Route-Mate, the basic connection primitive is therefore:

1. Travel along a continuous copper run.
2. Where the target is on another run, bridge between runs with a jumper perpendicular to the strips.
3. Continue along the destination copper run if the net requires it.

This is the physical meaning of the L-shaped connection: **one leg is copper; the other leg is a jumper**. It is not an L made from two jumper-wire legs.

Hard physical rules:

- Diagonal jumper wires are not permitted.
- Jumper wires cross copper strips at right angles.
- Jumper wires must not overlap/cross other jumper wires under the uninsulated-wire model.
- Jumper paths must avoid component bodies and other physical obstructions.
- The two solder endpoints must be accessible.
- Any alternate use of insulated crossing wires must be an explicit construction mode, not silently assumed.

Do not treat a direct endpoint-to-endpoint line as a physical wire path unless it matches the permitted jumper geometry.

## 4. Routing costs and optimisation

Striprouter exposes separate costs for physical resources. This is a useful model for Route-Mate, although the initial implementation should prioritise correctness before tuning cost values.

| Resource | Meaning | Design implication |
|---|---|---|
| Strip segment | Use of one adjacent section of existing copper | Usually low cost; it is already present, though long copper can add resistance/capacitance |
| Wire segment | Use of a jumper segment | Cost reflects added wire |
| Via / jumper endpoint | A wire entering/leaving a hole and being soldered | Represents endpoint and soldering effort |
| Cut at a hole | Copper removed around a hole | Makes that hole unavailable; often easier to locate but sacrifices the hole |
| Cut between holes | Copper severed between holes | Preserves both endpoint holes but can be harder to cut accurately |
| Route reuse | Reuse of an existing same-net path | Usually strongly preferred over duplicating a connection |

The costs are relative. A design can trade off copper length, jumper length, solder points, cut count and board area. A cut may be mandatory to separate different nets; other cuts are optional choices that can allow a shorter or more convenient route.

A notable Striprouter implementation detail is that wire/strip/via route costs are accumulated during routing, while the minimum required copper cuts are determined after the route has been formed and then added to the layout cost. This is a candidate approach for Route-Mate, not a requirement to copy without testing.

Route-Mate should report the raw counts and objective components separately. A single opaque score is not sufficient for comparing layouts.

## 5. Net reuse and route ordering

Striprouter uses existing same-net routes as opportunities for indirect connection and route reuse. If a net already reaches an intermediate terminal or copper section, later connections can reuse that path instead of creating a duplicate jumper.

It also searches route orderings rather than assuming one fixed order is best. Its documented approach combines topological ordering with a genetic algorithm, and uses uniform-cost search to find routes under the two-layer geometry restrictions.

Implications for Route-Mate:

- Build connectivity for each net, not independent pin-to-pin wires only.
- Reuse same-net copper runs and already-routed bridges.
- Avoid creating duplicate jumpers when an existing same-net path already connects the required terminals.
- Route order can affect the quality and feasibility of later connections.
- Placement and routing interact: component locations can create or remove useful copper paths and jumper corridors.

The external algorithm is a reference for study, not a mandate to copy its search strategy or claim equivalent performance.

## 6. Components and physical access

Component placement determines which holes are occupied, which copper runs are useful, and where jumper paths can physically pass.

A valid electrical route may still be unbuildable if:

- a jumper crosses a component body;
- a jumper collides with another jumper;
- a wire endpoint is inaccessible;
- a cut is obstructed by a component or solder joint;
- the selected hole is occupied or unavailable;
- the layout leaves no practical route corridor.

Unused or electrically irrelevant pins may sometimes be treated as "don't care" by an optimiser, allowing otherwise unused copper segments to be reused. Route-Mate must only do this when the input model explicitly establishes that a pin is electrically irrelevant or physically unused. It must not infer this from missing net data.

## 7. Construction output

A useful stripboard build output separates the two physical sides:

- **Component side:** component positions, jumper-wire locations and endpoints.
- **Copper side:** copper strips, cut locations and relevant solder-pad positions, mirrored consistently relative to the component side.

Striprouter generates separate wire and cut SVGs and documents printing them at 1:1 scale. This is a useful output concept for Route-Mate. Any print workflow must preserve exact physical dimensions and orientation; a visually correct preview is not proof of scale accuracy.

Construction sequence from the reference:

1. Mark and make the copper cuts.
2. Check the cuts.
3. Install components and jumper wires.
4. Solder and inspect connections.

## 8. What the external references establish

### Roger Dahl — Striprouter C++ (working reference)

https://github.com/rogerdahl/striprouter-cpp

The project describes a stripboard autorouter with non-overlapping wires crossing tracks at right angles, separate cut and wire output layers, resource costs, route reuse, and a two-layer search model. It documents strip, wire, via, cut-via, cut-between and reuse costs, plus a topological-order/genetic-algorithm search and uniform-cost routing.

The companion Rust repository, https://github.com/rogerdahl/striprouter, explicitly says that repository is under development and not yet usable, and points to the C++ repository as the working version. Route-Mate research should use the C++ repository as the primary implementation reference.

### Stripboard construction reference

https://www.sciencedirect.com/topics/engineering/stripboard

This reference describes parallel copper tracks, components mounted across tracks, cuts to isolate connection nodes, and wire links soldered to the tracks. It also notes the practical risk of solder bridges/whiskers and dry joints.

### CQ-TV 208, November 2004

https://batc.org.uk/wp-content/uploads/cq-tv208.pdf

The article describes laying out critical ICs first, adding wire links and track-cut marks, checking clashes, and marking cuts at holes in its illustrated method. It is a practical construction reference, not a universal rule that all stripboard cuts must be at holes.

### VeroRoute

https://sourceforge.net/projects/veroroute/

VeroRoute is another relevant cross-platform veroboard/perfboard/PCB layout tool. Its published feature description includes interactive autorouting, connectivity visualisation, short/open checks, netlist import and 1:1 PDF output. It is a useful comparison for user workflow and verification, but its routing model should not be assumed identical to Striprouter's.

## 9. Route-Mate v1.21: current state versus target

Current v1.21 behaviour:

- Partitions horizontal copper strips with between-cuts where the current algorithm detects different-net terminal groups.
- Builds copper connectivity groups using the supported cut and jumper model.
- Connects same-net copper groups using a deterministic Manhattan minimum spanning tree over jumper endpoints.
- Runs an independent electrical copper-connectivity verifier.
- Returns the original project unchanged when routing fails.
- GUI preview draws jumper endpoints as direct straight lines and does not draw strip cuts.

Not implemented:

- A jumper path model constrained to the direction perpendicular to the copper strips.
- Copper-run traversal as a first-class route path.
- A physical route made from a copper leg plus a jumper leg.
- Jumper overlap/crossing checks.
- Component-body and solder-access clearance checks.
- Cut access checks.
- Route reuse/cost optimisation across a complete physical path model.
- Copper-side cut artwork or separate 1:1 wire/cut build sheets.

Therefore, ROUTED currently means the supported electrical connectivity model passed. It does not mean the layout is physically buildable or approved for construction.

## 10. Current implementation direction

The former step-by-step proposal and acceptance list in this document are superseded by the locked [Physical Model Specification v1.0](PHYSICAL_MODEL_SPEC.md). That specification is now the sole implementation plan and acceptance authority.

The implementation order is fixed: audit legacy assumptions; define/test geometry and occupancy; model copper runs after between-hole cuts; prove one legal vertical jumper bridge; implement independent electrical and physical verification; run regression measurements; only then integrate placement and GUI behaviour.

Do not copy the v1.21 Manhattan endpoint router forward as the physical routing foundation. Historical v1.21 and legacy benchmark counts are comparison data only, not acceptance targets.


## Legacy v1.21 router baseline (historical; not physical approval)

`solve.route.route_copper(project)` resolves assigned terminals and saved off-board leads, rejects different nets at the same hole, cuts between conflicting horizontal terminal groups, preserves manual cuts/wires, builds copper connectivity groups, connects split same-net groups with deterministic Manhattan minimum-spanning-tree **endpoint** wires (`RM-W###`), then calls the independent **electrical** verifier. `ROUTED` only means electrical PASS: wire bodies, crossings, component clearance, cut/solder access and construction quality are not verified. The legacy model accepts hole cuts; these are forbidden in the locked initial physical model. The router must be replaced, not extended. Regression command: `python3 -m unittest discover -s tests -p 'test_route.py' -v`. See the [locked physical gates](PHYSICAL_MODEL_SPEC.md).
