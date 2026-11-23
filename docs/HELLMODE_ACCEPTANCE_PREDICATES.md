# Hell Mode acceptance gates — candidate scope (v0.1)

**Status:** implementation contract, **not** a change to the locked
[physical specification](PHYSICAL_MODEL_SPEC.md) or the approved
[2.5D jumper geometry amendment](PHYSICAL_MODEL_25D_AMENDMENT.md).

The normative documents outrank this note. The acceptance predicates
below are fail-closed *definitions for subsequent independent verification*,
not declarations that the verifier currently implements them.

## A. Separation of search and certification

A SEARCH_STATE may have disconnected terminal groups and penalised,
overlapping insulated jumper projections. Its penalty is integer-valued:
short components (hard veto for ordinary annealing), the sum of
`max(0, distinct_components_for_net - 1)` over nets, illegal hole conflicts,
excess vertical-gap occupancy, max stack depth, derived cut count, then
wire length. Annealing may temporarily accept an equal or inferior score
for exploration. Such states are **not serialisable as RECORD**.

A RECORD must be constructed only after *fresh independent recomputation*
of actual copper, jumper and pad geometry. A zero search surrogate penalty
is insufficient. In current Route-Mate the record factory fails closed:
the existing verifier does not yet grant RECORD.

## B. Derived between-hole cuts

For each horizontal copper row, collect owner anchors from placed terminals
and owned jumper landings. Insert a separating cut between adjacent
anchors with different net ownership; reuse an existing cut in that
interval when possible. Extra cuts are removed and counted as a cost,
not randomly searched as independent moves. A fixed row with two
different-net leads in the same hole is unrecoverable by a cut.

**Important qualification:** placement and logical net assignments alone
do not uniquely determine cut coordinates. Jumper landings and their net
ownership are part of the routing topology, and there may be several
equally legal separating gaps between anchors. The derived layout is
therefore a **proposal**, checked independently later. It is not a
certificate, a proof of minimal cuts over all layouts, or a substitute
for a cut-tool accessibility check.

## C. Jumper/body/lead clearance predicate

Inputs (mm) must be explicit and provenance-graded as in physical model
v1.1: true body solids, exposed leads, component standoff, jumper
diameter, lift, and required lateral/z clearances.

- **PASS:** all intermediate pad/lead holes and wire-body/lead distances
  are independently verified using complete sufficient geometry and
  the v1.1 inclusive `1e-9 mm` comparison tolerance.
- **FAIL_PROVEN:** confirmed intervening pad hole, forbidden wire
  stacking/shared landing, or measured/datasheet geometry proving a
  prohibited clearance violation.
- **FAIL_UNVERIFIED:** missing measured/declared values prevent
  independent proof; never substitute a rendered body silhouette or
  a guessed capacitor/resistor standoff.
- **CONDITIONAL:** the approved v1.1 scenario depends on expressly
  user-declared installation standoff/contact, rather than unqualified
  measured proof.

Unknown or conditional results never produce an unconditional physical
PASS. The STRICT gap/hole checks are an additional hard precondition.

## D. Between-hole cut-tool accessibility predicate

The locked physical spec §2.3 requires a tool approach path from above,
not merely an electrically placed cut. The assembly policy to be evaluated
must be explicit; until a new assembly-policy amendment is approved,
**assembled_vertical** is the conservative interpretation. A proposed
`pre_assembly` workflow is **not** silently treated as satisfying the
locked post-placement accessibility rule.

Required evidence includes a cut position, configured cutting-tool
swept-envelope and safety margin, ordered part/body/lead solids,
their coordinates and measured or declared heights, plus a specified
cutting operation stage. A complete independent test of the swept
volume against physical obstructions is necessary.

- **PASS:** fully defined and verified unobstructed path under a
  normative/approved assembly policy.
- **FAIL_PROVEN:** known body/lead intersects a defined required tool
  path; or a cut is at an invalid between-hole coordinate.
- **FAIL_UNVERIFIED:** missing tool swept envelope, assembly order,
  body height/position or lead clearance cannot prove accessibility.
- **CONDITIONAL:** explicitly approved but not independently proven
  assembly-stage assumptions; cannot be promoted to BUILD_READY.

No current saved MOTO or AUDIO layout has such complete cut-access
evidence; `cut_access: unverified` must remain explicit.

## E. Golden predicate cases

See `tests/fixtures/hellmode_gate_predicates.json` for contract-level
examples, deliberately *not* presented as passing executable physical
verifier tests. A separate independent verifier implementation must
be tested against those cases and the normative G01–G11 v1.1 fixtures
before any physical RECORD or BUILD_READY milestone is claimed.

## F. Diagnostic gate before compound routing

`python -m hellmode.diagnostic --input <best_electrical.json>` reports:

1. Clustered vs scattered occupied gap cells.
2. A per-row-gap maximum bipartite matching of fixed-span jumpers to
   admissible columns and a Hall witness of any proven local deficiency.
3. An exact full fixed-span column CSP result, attempted only if no
   local Hall contradiction exists. Node-budget exhaustion yields
   `UNKNOWN_NODE_LIMIT`, never `UNSAT`.

A Hall witness applies **only** with frozen component positions, cuts,
jumper endpoint rows and original copper-island memberships. It never
rules out changed topology or a component move. This proof scope
must accompany every diagnostic result.
