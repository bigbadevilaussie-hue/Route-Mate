# HELLMODE.md v0.1 -> v0.2 Amendments

Resolves the four open architectural decisions plus the hard-coded baseline finding. Milestone order (M1 to M7) and Quick Solve isolation are unchanged. Each amendment says which section it replaces or extends.

| # | Decision | Affects |
|---|---|---|
| A1 | PASS-only geometry for v1; conditional routing deferred to a new M8 | §8, §14 |
| A2 | Shared routing/electrical APIs, independent verifier is final authority; heavy-fail policy | §0.2, §4.4a |
| A3 | Baseline and regression defined on unsolved inputs; baseline measured, never hard-coded | §13.1, §17, §3 |
| A4 | Wall-clock precedence, budget scaling, two reproducibility contracts | §3, §7, §10 |
| A5 | Frozen M1 acceptance tests | §13, §14 |

---

## A1. Geometry policy: PASS-only in v1

**Decision:** Hell Mode v1 accepts only unconditional geometry `PASS`. Conditional routing is a separate later milestone.

**Rationale:** the current 2.5D router already blocks `CONDITIONAL`, `FAIL_UNVERIFIED` and `FAIL_PROVEN`. A search cannot produce a `CONDITIONAL` record if its router never emits one. Building conditional routing inside the search engine would couple two unfinished things.

**Replace §8 result classes with:**

| Class | Requirements |
|---|---|
| `RECORD` | Passes the electrical check, and every jumper and keepout check is unconditional `PASS`. Lowest score tuple among such layouts. |
| `BUILD_READY` | `RECORD` plus cut access verified. While no cut-access verifier exists this is never granted, and results carry `cut_access: unverified`. |

**Add setting:** `geometry_policy`, default and only v1 value `"PASS_ONLY"`. The value `"ALLOW_CONDITIONAL"` is reserved and must raise a clear "not implemented" error.

**Behaviour under PASS_ONLY:**

- The router treats `CONDITIONAL`, `FAIL_UNVERIFIED` and `FAIL_PROVEN` as blocked.
- The verifier still reports the full four-verdict vocabulary, so reports stay honest (an unknown-standoff block shows as `FAIL_UNVERIFIED`, not as a collision).
- A candidate whose verifier report contains anything other than `PASS` is ineligible as a result.

**Add milestone M8 (after M7, order of M1 to M7 unchanged): conditional routing mode.**

Prerequisites:

1. The router can emit `CONDITIONAL` with an explicit assumption list (declared standoff, `allow_contact`).
2. The verifier returns the same assumptions for each `CONDITIONAL`.
3. Golden fixtures G04 and G07 pass in both implementations.
4. `run.json` gains an `assumptions` array, and reports list every assumption a record depends on.

Then `geometry_policy = "ALLOW_CONDITIONAL"` may be enabled, with `CONDITIONAL` records reported separately from `PASS`-only records.

---

## A2. Shared core versus independent verifier

**Decision:** Hell Mode reuses Quick Solve's placement, routing and electrical APIs. The geometry verifier remains an independent implementation and the final authority on eligibility.

**Replace §0 rule 2 with:**

> **Shared core.** Hell Mode and Quick Solve share the placement model, the routing API, the electrical-check API, the normative physical-model constants, and the golden fixtures. They do **not** share geometry-verifier code. Hell Mode calls the verifier only through its public entry point `verify_layout(layout, spec) -> report`. The verifier must not import router internals, and the router must not import verifier internals. An import-graph test enforces this (M1-7).

"One shared core" and "independent verifier" are consistent: the shared parts are the inputs both sides must agree on, and the independent part is the check on the output.

**Replace §4.4a heavy-failure handling with:**

When a move would become a candidate's new best and the heavy verifier rejects it:

1. **Ineligibility.** The state is never recorded as a best, and it is written to `rejected.json` with reason codes.
2. **Revert.** The move is undone in the active annealing state using its undo record. A state the final authority rejects is not a valid place to continue from, and keeping it would make later "bests" inherit the failure and re-trigger heavy checks.
3. **Tabu.** The rejected state hash is blocked for the next `tabu_moves` (default 2,000) so the search does not immediately re-propose it.
4. **Classify** the failure:
   - `ROUTER_VERIFIER_DISAGREEMENT`: the failing rule is one the router claims to enforce. This is a bug in one implementation. Save a repro (input hash, settings, seed, move index, state), and fail the run under `--paranoid` and in CI. In a normal run, log it and continue.
   - `HEAVY_ONLY_REJECT`: the failing rule is verifier-only (full electrical, cut access heuristics). This is expected behaviour, counted but not an error.
5. **Circuit breaker.** After 20 consecutive heavy rejects on one candidate, run the heavy verifier on every accepted improving move for that candidate (not just would-be bests) and log `cheap_tier_too_permissive` in the report. If it continues, retire the candidate.

Answer to the explicit question: **both**. Discard eligibility, and undo the move in the active state.

---

## A3. Baseline and regression fixtures

**Decision:** regression is defined on original **unsolved** circuit JSON plus fixed locks and seeds. Historical solved exports are tested separately. The baseline is always measured.

**Correction:** v0.1 §13.1 listed `audio10wires38cuts.json` and `moto14wires30cuts.json` as Quick Solve regression inputs. Those are routed exports, not valid inputs for a fresh Quick Solve. That was an error in v0.1.

**Replace §13 test 1 with two fixture sets:**

**Set U, unsolved regression (Quick Solve isolation):**

- `fixtures/unsolved/<circuit>.json`, plus a locks file and a fixed seed per circuit, in a manifest.
- A pinned snapshot `baseline_snapshot/<circuit>.quick_solve.json` generated from the **pre-merge** commit. The manifest records that commit SHA and the Quick Solve version.
- Test: post-merge Quick Solve on the same inputs produces a byte-identical output (or identical canonical hash).
- Snapshots are replaced only in a dedicated commit that states why Quick Solve behaviour intentionally changed.

**Set H, historical solved exports (compatibility only):**

- `audio10wires38cuts.json`, `moto14wires30cuts.json`, `moto1_solved.json`, and any other saved exports.
- Tests: loads without error, round-trips through save, geometry verifier runs and returns a reason-coded report.
- No wire or cut counts are asserted. Expected geometry verdicts are frozen only after measured footprint overrides exist (as planned for the Audio W4/W6/W8 and Moto W0/W3/W8/W9/W13 flags). Until then the test is "report is produced and reason-coded".

**Baseline measurement (replaces any hard-coded baseline):**

- At run start, Hell Mode runs the **current** Quick Solve on the loaded circuit with the same locks and a fixed seed.
- It stores `baseline` in `run.json`: score tuple, Quick Solve version, git SHA, seed, wall time, verifier report summary.
- If Quick Solve yields no verified layout, `baseline` is `null`, the GUI says "no baseline", and the run proceeds.
- **Inject the baseline layout into the candidate pool** (seed index `-1`), so the final result is never worse than the baseline by construction. The report states `improved`, `equal` or `no improvement` against it.

**Replace §17 (Definition of done) with:**

> On `moto.json`, a Hell preset run on 3 workers finishes within the time budget, produces a layout that passes the electrical check and has unconditional `PASS` geometry, has a score tuple strictly better than the **measured** Quick Solve baseline recorded in `run.json`, saves a replayable `run.json`, and leaves Quick Solve output unchanged against its pinned snapshot. If no strict improvement is found, the run reports `no improvement` and the investigation (not the label) is the deliverable.

The numbers 38 wires / 48 cuts must not appear in code, tests or acceptance criteria. They were an observation from one Quick Solve screenshot.

---

## A4. Performance budgets and reproducibility

**Decision:** the wall-clock budget always takes precedence. Stage budgets scale to fit it. Two explicit reproducibility contracts.

**Planned work check:** the default stages total roughly 23M attempted moves. At 60,000 moves/s aggregate that is about 6.4 minutes of pure move processing, before routing overhead, verification, checkpoints and coordination. A 10-minute budget is therefore tight and must not assume the plan fits.

### Work units and checkpoints

- All work is expressed as **chunks** of fixed move counts (default 5,000). Time is checked only at chunk boundaries.
- Each worker returns its candidate state at every chunk boundary. The coordinator checkpoints at **stage boundaries** (always) and every `checkpoint_chunks` chunks (default 20).
- Stage boundaries are **barriers**: all candidates in a stage finish their stage budget (or are retired by their own plateau rule) before promotion decisions.

### Budget scaling (time-budgeted runs)

1. Reserve time for Stage 5 final verification and file writes: `reserve = max(10 s, 5% of the time budget)`.
2. Measure aggregate throughput during a short calibration at the start of Stage 1.
3. Compute `scale = clamp((time_budget - reserve) * throughput_total / planned_moves, 0.05, 1.0)`.
4. Multiply per-stage move counts (and the Stage 1 seed count, rounded) by `scale`.
5. Store the resolved budgets in `run.json` as `resolved_budget`.

Suggested wall-time shares: Stage 1 10%, Stage 2 25%, Stage 3 45%, Stage 4 15%, Stage 5 reserve. If the deadline is reached mid-stage, finish the current chunk and jump straight to Stage 5 with the best verified state.

### Plateau and reallocation

To keep iteration-budgeted runs scheduling-independent:

- Per-candidate plateau stops depend only on that candidate's own move counts.
- Freed budget is **not** reallocated mid-stage. It is spent at the next stage boundary (for example by funding extra Stage 4 restarts), in a deterministic order.
- `global_plateau_minutes` and the Stop button are wall-clock features and apply to time-budgeted runs only.

### Two reproducibility contracts

| Run type | Guarantee |
|---|---|
| **Iteration-budgeted** (move budgets only, no wall-clock stop) | Identical output for identical `(input, locks, settings, master seed)` regardless of worker count and scheduling. Required by M4 test 2. |
| **Time-budgeted** (wall-clock stop, Stop button, global plateau) | Reproducible only under identical scheduling conditions. **But** every such run records its realised work log (`resolved_budget` plus per-candidate stop chunk) in `run.json`, so it can be **replayed exactly as an iteration-budgeted run** and reproduce the same result on any worker count. |

Merge order for results is always sorted by `(score_tuple, seed_index)`, never by completion order.

---

## A5. Frozen M1 acceptance tests

M1 is "profile plus incremental evaluator". M1 is accepted only when all of these pass:

| ID | Test |
|---|---|
| M1-1 | Set U unsolved Quick Solve regression against pinned snapshots (A3), at least Moto and Audio. |
| M1-2 | Set H historical exports load, round-trip, and produce a reason-coded verifier report. |
| M1-3 | `--paranoid` run of 200k moves per move type on two circuits: incremental state equals full recompute, zero mismatches. |
| M1-4 | Every move type is reversible: apply then undo returns an identical state hash. |
| M1-5 | Locked components never move across 1M random moves. |
| M1-6 | Profiling report produced: time breakdown (move gen, route, score, verify, I/O), full-recompute moves/s versus incremental moves/s on the same machine. Soft gate: incremental at least 5x faster per worker. If missed, the report must explain which cost dominates. |
| M1-7 | Import-graph test: the verifier does not import router internals and the router does not import verifier internals (A2). |
| M1-8 | Golden geometry fixtures G01 to G07, the G03a/G03b split, and the two boundary cases pass in router and verifier **independently**. Under `PASS_ONLY`, router expectation for `CONDITIONAL` cases (G04) is "blocked", while the verifier reports `CONDITIONAL`. G07 expects `FAIL_UNVERIFIED` in the verifier and "blocked" in the router. |

Nothing in M2 to M7 starts until M1-1 through M1-8 are green, with the M1-6 speed gate allowed to pass on a written explanation.
