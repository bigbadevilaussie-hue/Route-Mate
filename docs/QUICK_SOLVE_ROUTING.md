# First-pass copper routing

> **LEGACY IMPLEMENTATION — DESIGN FROZEN AGAINST EXTENSION.** This document describes v1.21 behaviour for audit and regression purposes. It is not the current physical routing design. The sole normative source and implementation plan is [Physical Model Specification v1.0](PHYSICAL_MODEL_SPEC.md). Do not add features to the Manhattan endpoint router; replace its physical assumptions by following the specification's gates.

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

## Replacement plan — follow the locked specification

The previous next-step proposal is superseded. Implementation must follow [PHYSICAL_MODEL_SPEC.md](PHYSICAL_MODEL_SPEC.md), in order:

1. Audit all v1.21 endpoint-only jumper and hole-cut assumptions.
2. Define and test board axes, cut-tool clearance, component occupancy, jumper body geometry and endpoint access.
3. Build explicit copper runs using between-hole cuts only.
4. Prove one legal same-column vertical jumper bridge between two same-net runs.
5. Independently verify electrical connectivity and all physical constraints, including cut accessibility.
6. Add regression tests and report electrical and physical outcomes separately.
7. Only after those gates pass, integrate the new rules into placement and GUI status/display.

No Manhattan endpoint-distance routing, diagonal/horizontal/dog-leg wires, hole cuts in the initial model, cost tuning or broad search expansion. A result is accepted only when both independent verification reports pass. See the specification for exact definitions and acceptance criteria.

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
