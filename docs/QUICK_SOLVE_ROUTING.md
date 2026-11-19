# First-pass copper routing

## Purpose

`solve.route.route_copper(project)` is the first working copper-routing stage after component placement. It accepts a placed project, adds strip cuts and jumper connections, and runs the independent `solve.verify.verify_project` verifier before reporting success.

It is a deterministic first pass, not the final physical stripboard router.

## Current algorithm

1. Resolve every assigned on-board pin through the shared footprint geometry. Off-board components contribute a physical terminal only when the project contains a saved lead-hole coordinate.
2. Reject different nets assigned to the same physical hole. A cut cannot separate two terminals sharing one hole.
3. Examine assigned terminals along each horizontal strip. Where consecutive terminal groups belong to different nets, add a `between` cut unless existing cuts already isolate the groups.
4. Build the resulting copper connectivity groups, including existing manual jumpers.
5. Reject any existing jumper/copper group that still joins different nets.
6. For each net split across multiple copper groups, add a deterministic Manhattan minimum spanning tree of jumper wires. Existing cuts and wires are retained.
7. Run the independent copper verifier. Return `ROUTED` only when verification is `PASS`. Failed attempts return the original project unchanged.

New jumper IDs use the `RM-W###` prefix and avoid IDs already present in the project.

## Supported physical model

- Horizontal continuous strip copper.
- `between` cuts, which sever the link between a hole and the next hole to its right.
- `hole` cuts, which isolate one hole from both horizontal neighbours.
- Jumper wires represented by `from` and `to` board-hole coordinates.
- Saved physical lead coordinates for off-board components.

Vertical `below` cuts are rejected because the current verifier does not model patterned vertical copper.

## Known limitations — do not treat ROUTED as construction approval

The current model verifies electrical connectivity and shorts only. It does not yet check:

- jumper wire body paths, crossings or physical length;
- wire insulation, soldering access or whether a jumper can pass under/around components;
- cut-tool access or whether a component body obstructs drilling;
- wire-to-component clearance or jumper endpoint accessibility;
- preferred-board-size optimisation or minimisation of cut/jumper count;
- hard edge anchors and sliding placement constraints.

The router currently chooses the left boundary after the preceding terminal group when a new cut is required. It uses a Manhattan minimum spanning tree to reduce total endpoint-to-endpoint distance, but does not perform geometric path routing. The generated jumper line is a logical electrical connection, not a proven physical wire path.

The GUI runs the router after a successful Quick Fit. Its current component-side SVG preview draws jumper connections as straight lines but does not draw strip cuts; route counts and verifier results are written to the log. These straight lines are not a physical path solution.

## Test

Run:

~~~bash
python3 -m unittest discover -s tests -p 'test_route.py' -v
~~~

The tests cover strip separation, adjacent different-net pins, same-net jumper creation, interleaved nets, preservation of manual routing, detection of existing jumper shorts, deterministic output and source-project immutability.
