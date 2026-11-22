# Route-Mate Physical Model Specification

**Version:** 1.0 (base), amended by v1.1 for insulated-wire geometry  
**Status:** LOCKED — DESIGN FREEZE; see [approved v1.1 amendment](PHYSICAL_MODEL_25D_AMENDMENT.md)  
**Authority:** Normative single source of truth for physical stripboard behaviour.

> **Implementation hold:** Do not extend or optimise the v1.21 endpoint/Manhattan router. Do not implement against older routing assumptions. Any code, test, GUI status, renderer or documentation that conflicts with this specification is superseded and must be brought into line.

This specification locks the physical model and the order of work. It does not claim that the current executable implements the model.

## 1. Board orientation and copper

- Copper strips run **horizontally**: constant row, varying column.
- Columns increase left to right.
- Rows increase top to bottom. The numeric direction is fixed here for consistency.
- Each horizontal strip is continuous until interrupted by a cut.
- Jumper direction is vertical: constant column, varying row.

This coordinate convention is a Route-Mate board-model rule, not a screen-rendering inference.

## 2. Cuts

### 2.1 Allowed cut type in the initial physical model

- **Between-hole cuts only.**
- A cut is located in the gap between two adjacent holes on the same strip (same row, consecutive columns).
- Hole cuts are deferred and are not part of the initial physical-routing model.

### 2.2 Cut semantics

- A between-hole cut permanently breaks copper continuity between its two neighbouring holes.
- The strip is divided into independent copper runs.
- Both endpoint holes remain available as holes; the copper connection between them is severed.

### 2.3 Cut accessibility — hard constraint

A cut is legal only when it is physically accessible:

- Sufficient clear space must exist above the strip for a knife or cut tool to reach the gap.
- No component body may block the vertical approach path to the cut location.
- The independent physical verifier must reject inaccessible cuts.

Accessibility is a legality test, not an optimisation penalty. The exact clearance geometry must be defined and tested before implementation relies on it; until then, the solver must not claim physical verification PASS for cut accessibility.

> **Amendment v1.1:** For insulated-wire mode, the explicit 2.5D clearance contract in [PHYSICAL_MODEL_25D_AMENDMENT.md](PHYSICAL_MODEL_25D_AMENDMENT.md) supersedes the 2D body-intersection rule in §3.4 and the deferral of insulated-wire mode in §10. All other hard requirements remain in force.

## 3. Jumpers

### 3.1 Direction

- Jumpers run perpendicular to the copper strips.
- With horizontal copper, jumpers run vertically: same column, different rows.
- Diagonal jumpers are never permitted.
- Horizontal jumpers, running along a copper strip, are never permitted.

### 3.2 Connection model

A legal connection uses this pattern only:

```text
Copper run A  →  single perpendicular jumper  →  Copper run B
```

- The jumper bridges two different copper runs.
- Existing copper provides travel along each run on either side of the jumper.
- The jumper itself is one straight segment.
- Multi-segment jumpers, dog-legs and intermediate landing points are not allowed in this model.

### 3.3 Jumper representation

A jumper is defined by:

- Start hole: (row, column).
- End hole: (row, column).
- Both holes share the same column.
- The physical wire body occupies the space between those two holes.

### 3.4 Jumper physical constraints

- The jumper body must not intersect a component body.
- Jumper crossings or shared physical space are prohibited in uninsulated-wire mode.
- Both endpoints must be valid holes, unoccupied unless deliberately used as jumper landing points, and physically accessible.
- A route must account for the whole jumper body, not merely its endpoints.

## 4. Adjacent different-net pins — LOCKED

### 4.1 Same-hole different nets

- Always a hard electrical failure.
- Never permitted. A cut cannot separate two nets sharing one physical hole.

### 4.2 Adjacent different-net pins

Adjacent holes on the same strip belonging to different nets are allowed only when all conditions hold:

1. A between-hole cut fully isolates the two nets electrically.
2. The cut is physically accessible under §2.3.
3. The independent verifier confirms that the nets remain electrically isolated after the cut.

If any condition fails, the arrangement is a hard failure.

This is a hard physical/electrical constraint, not a soft placement score preference. Quick Fit must not reject every adjacent different-net pair automatically; it must allow the arrangement only when a legal isolating cut can be established.

## 5. Verification responsibilities

Verification produces two distinct reports.

### 5.1 Electrical verification

- Every net's required terminals are connected.
- Different nets are not shorted together.
- Same-hole different-net conflicts are detected.
- Adjacent different-net pins are accepted only when a valid isolating cut exists.

### 5.2 Physical verification

- Every cut is accessible.
- Every jumper is perpendicular to the copper strips.
- Diagonal and horizontal jumpers are rejected.
- Jumper bodies do not intersect component bodies.
- Prohibited jumper crossings/shared physical space are rejected.
- Jumper endpoints are valid, available and accessible.

A solution is accepted only when **both electrical and physical verification pass**.

The router must not be the authority that certifies its own output. The independent verifier has final authority and must derive its checks from the resulting physical layout, not trust router claims.

## 6. Required routing pipeline

These are separate logical stages with explicit outputs:

1. **Component placement** — legal positions and orientations, respecting body clearance, locks, edge anchors and the adjacent-pin rule.
2. **Copper segmentation** — determine the complete set of required between-hole cuts and derive the resulting copper runs.
3. **Jumper routing** — connect the resulting same-net copper runs using only legal single-segment perpendicular jumpers.
4. **Independent verification** — run electrical and physical verification separately; accept only if both pass.

Do not collapse segmentation, jumper routing and verification into one endpoint-to-endpoint algorithm.

## 7. Explicitly forbidden

- Diagonal jumpers.
- Horizontal jumpers along copper.
- Multi-leg or dog-leg jumpers.
- Manhattan endpoint distance as a substitute for physical path geometry.
- Treating an inaccessible cut as valid.
- Treating a component-body obstruction as a score penalty.
- Softening any hard constraint into a score penalty.
- Claiming a solution is buildable based only on electrical connectivity.

## 8. Optimisation order

1. Find a candidate that passes both electrical and physical verification.
2. Only after legality is established, optimise secondary costs such as jumper count, total jumper length, cut count, route reuse and board size.

Correctness is never traded for a better score. No genetic algorithm, broad search expansion or cost tuning is authorised as part of the first physical-routing increment.

## 9. Implementation roadmap — the way forward

The following order is mandatory. Complete and test each gate before proceeding.

### Gate 0 — repository and legacy audit

- Treat v1.21 as the legacy baseline, not as the physical-routing foundation.
- Identify every caller, data structure, test and GUI display that assumes endpoint-only jumpers or hole cuts.
- Preserve source project JSON, identifiers, off-board component policy and existing manual data.
- Record legacy behaviour separately; do not silently reinterpret old results as physically verified.

### Gate 1 — geometry and occupancy contract

Before writing the router, define and test:
- row/column-to-physical-axis mapping;
- board hole centres and between-hole cut coordinates;
- component-body occupied geometry and the cut-tool approach region;
- jumper body geometry and endpoint occupancy/accessibility;
- jumper-to-jumper collision/crossing semantics.

The cut-tool clearance and physical body geometry must be explicit, deterministic and covered by tests. Do not guess dimensions from a screen rendering.

### Gate 2 — copper-run model

- Apply supported between-hole cuts to each horizontal strip.
- Produce deterministic, separately identifiable continuous copper runs.
- Associate holes, terminals and nets with their runs.
- Ensure each cut divides exactly the intended strip connection.
- Add tests for no cuts, one cut, multiple cuts and cuts adjacent to terminals.

### Gate 3 — one legal jumper bridge

- Connect two distinct same-net copper runs using one vertical jumper.
- Select valid endpoint holes in the same column.
- Represent the complete occupied wire body.
- Reject invalid endpoints, component-body intersections and jumper conflicts.
- Do not add dog-legs, horizontal/diagonal wires or intermediate jumper landing points.

### Gate 4 — independent verification

- Implement electrical connectivity verification against the cut/run/jumper result.
- Implement physical verification independently of router decisions.
- Include cut accessibility, jumper orientation, body interference, crossing and endpoint checks.
- Demonstrate that electrically connected but physically invalid examples fail physical verification.
- A final result is accepted only when both reports pass.

### Gate 5 — regression and measurement

Use the existing Moto fixture at `benchmarks/moto/moto14wires30cuts.json` where applicable. Preserve its historical legacy test expectation; add new tests for the frozen physical model rather than rewriting history to make the new model appear to pass.

Record at least:
- copper runs and terminals per net;
- required cuts and optional cuts, if optional cuts are later introduced;
- jumper count and physical length;
- cut accessibility failures;
- jumper crossings and component-body conflicts;
- electrical result and physical result separately.

Historical counts (including v1.21's 50 cuts / 38 jumpers and the legacy 30 cuts / 14 wires) are comparison data, not correctness targets.

### Gate 6 — placement and GUI integration

Only after the physical router and independent verifier pass their tests:
- make placement aware of whether adjacent different-net pins can be isolated by an accessible cut;
- connect the shared solver pipeline to the GUI;
- report electrical and physical outcomes separately;
- never display electrical-only success as ROUTED/buildable;
- add physical cut and jumper views that accurately represent the resulting build.

Do not redesign the GUI as part of the routing foundation.

## 10. Explicitly out of scope until separately approved

- Hole cuts.
- Diagonal, horizontal or multi-leg jumper modes.
- Insulated-wire crossing mode.
- Genetic algorithms or large-scale stochastic search.
- Cost tuning and broad placement-score redesign.
- New placement optimisation beyond what is required to enforce the locked hard constraints.
- GUI redesign.
- Changes to source project JSON or off-board component policy.

Any change to this specification requires an explicit design discussion and a versioned amendment. Code, tests or documentation must not silently change the frozen physical rules.

**End of specification.**
