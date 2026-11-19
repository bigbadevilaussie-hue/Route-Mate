# First-pass copper routing

## Purpose

solve.route.route_copper(project) is the first working copper-routing stage after component placement. It accepts a placed project, adds strip cuts and jumper connections, and runs the independent solve.verify.verify_project verifier before reporting success.

It is a deterministic first pass, not the final physical stripboard router.

The construction model and next implementation plan are documented in [Stripboard design research and routing direction](STRIPBOARD_DESIGN_RESEARCH.md).

## Current algorithm (v1.21)

1. Resolve every assigned on-board pin through the shared footprint geometry. Off-board components contribute a physical terminal only when the project contains a saved lead-hole coordinate.
2. Reject different nets assigned to the same physical hole. A cut cannot separate two terminals sharing one hole.
3. Examine assigned terminals along each horizontal strip. Where consecutive terminal groups belong to different nets, add a between cut unless existing cuts already isolate the groups.
4. Build the resulting copper connectivity groups, including existing manual jumpers.
5. Reject any existing jumper/copper group that still joins different nets.
6. For each net split across multiple copper groups, add a deterministic Manhattan minimum spanning tree of jumper wires. Existing cuts and wires are retained.
7. Run the independent copper verifier. Return ROUTED only when verification is PASS. Failed attempts return the original project unchanged.

New jumper IDs use the RM-W### prefix and avoid IDs already present in the project.

## Supported electrical model

- Horizontal continuous strip copper.
- between cuts, which sever the link between a hole and the next hole to its right.
- hole cuts, which isolate one hole from both horizontal neighbours.
- Jumper wires represented by from and to board-hole coordinates.
- Saved physical lead coordinates for off-board components.

Vertical below cuts are rejected because the current verifier does not model patterned vertical copper.

This is the currently implemented connectivity model. It is not a complete physical construction model.

## Critical physical construction rules

The physical stripboard model must treat copper and jumpers as different resources:

- Copper strips are existing conductors.
- Cuts split strips into independent copper runs.
- A jumper bridges separate copper runs belonging to the same net.
- The basic L-shaped connection consists of one copper leg and one jumper leg. It is not two jumper-wire legs.
- Jumper wires cross copper strips at right angles.
- Diagonal jumpers are prohibited.
- Under the uninsulated-wire construction mode, jumper wires must not overlap or cross one another.
- Jumper paths must not pass through component bodies, and endpoints must be physically accessible.

The strip axis must be defined by the Route-Mate board coordinate convention. Do not assume the horizontal/vertical convention used by another application is identical to Route-Mate's row/column convention.

## Known limitations — do not treat ROUTED as construction approval

The current model verifies electrical connectivity and shorts only. It does not yet check:

- copper-run traversal as an explicit physical route;
- jumper path geometry, perpendicularity, crossings or physical length;
- wire insulation, soldering access or whether a jumper can pass around components;
- cut-tool access or whether a component body obstructs cutting;
- wire-to-component clearance or jumper endpoint accessibility;
- preferred-board-size optimisation or minimisation of cut/jumper count;
- hard edge anchors and sliding placement constraints.

The router currently chooses the left boundary after the preceding terminal group when a new cut is required. It uses a Manhattan minimum spanning tree to reduce total endpoint-to-endpoint distance, but does not perform geometric path routing. The generated jumper line is a logical electrical connection, not a proven physical wire path.

The GUI runs the router after a successful Quick Fit. Its current component-side SVG preview draws jumper connections as direct straight lines but does not draw strip cuts. These lines are not physical jumper paths.

## Next implementation step

Do not extend the current Manhattan endpoint router by merely banning diagonal lines or by splitting a diagonal into two jumper legs.

The next step is a small physical-routing foundation:

1. Define and test the actual copper-strip axis and perpendicular jumper axis in Route-Mate coordinates.
2. Build explicit copper runs after applying cuts.
3. Add one legal bridge operation between two same-net copper runs: one jumper segment perpendicular to the strips, joining legal holes.
4. Store/check the jumper's occupied physical path, not just its endpoints.
5. Add independent physical checks for diagonal/non-perpendicular jumpers, jumper crossings, component-body obstruction and inaccessible endpoints.
6. Keep electrical connectivity PASS and physical construction PASS as separate results.

Start with a deterministic single-bridge model and tests. Do not add genetic search, cost tuning, new placement scoring or broad optimisation in this increment.

Use benchmarks/moto14wires30cuts.json as the reference fixture. Preserve its existing historical test expectation; add separate physical-route assertions. Record copper runs, forced/optional cuts, jumper count/length, crossings/body conflicts and both verifier outcomes. The known v1.21 Moto result (50 cuts / 38 jumpers) can be compared with the legacy reference (30 cuts / 14 wires), but counts alone do not prove quality or correctness.

## External routing references

- [Roger Dahl — Striprouter C++](https://github.com/rogerdahl/striprouter-cpp): working reference for right-angle, non-overlapping wire routing, two routing layers, strip/wire/via/cut/reuse costs, route reuse, separate wire/cut output and route-order search.
- [Striprouter Rust repository](https://github.com/rogerdahl/striprouter): explicitly marked by its author as under development and not yet usable; it points to the C++ repository as the working version.
- [Stripboard construction overview](https://www.sciencedirect.com/topics/engineering/stripboard): copper tracks, track cuts, wire links and practical soldering faults.
- [CQ-TV 208 stripboard construction article](https://batc.org.uk/wp-content/uploads/cq-tv208.pdf): practical layout planning, critical components first, track-cut marking and clash checking.
- [VeroRoute](https://sourceforge.net/projects/veroroute/): comparison tool for interactive veroboard/perfboard routing, connectivity checks and 1:1 output. Its internal routing model should not be assumed identical to Striprouter's.

## Test

Run:

~~~bash
python3 -m unittest discover -s tests -p 'test_route.py' -v
~~~

The current tests cover strip separation, adjacent different-net pins, same-net jumper creation, interleaved nets, preservation of manual routing, detection of existing jumper shorts, deterministic output and source-project immutability.
