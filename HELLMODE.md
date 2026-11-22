# Route-Mate Hell Mode: Implementation Spec

**Status:** implementation spec v0.3 — M1 scope and 12 acceptance gates defined; **not implemented**; Route-Mate 1.44 benchmark evidence
**Audience:** the implementing engineer (ChatGPT / Codex)
**Goal:** a separate, long-running search mode that minimises wires, then cuts, then wire length, on any circuit, with no reference record to chase. Every run races against its own Quick Solve baseline.

---

## 0. Ground rules (read first)

1. **Quick Solve must not change behaviour.** It works. Hell Mode is a new GUI section and a new module. If a change to shared code alters Quick Solve output for the same input and seed, that is a regression.
2. **Shared core.** Hell Mode and Quick Solve share the placement model, the routing API, the electrical-check API, the normative physical-model constants, and the golden fixtures. They do **not** share geometry-verifier code. Hell Mode calls the verifier only through its public entry point `verify_layout(layout, spec) -> report`. The verifier must not import router internals, and the router must not import verifier internals. An import-graph test enforces this (M1-7).
3. **A result only counts if it passes its stated eligibility gate.** A layout with fewer wires that fails electrical or independent geometry checks is not a `RECORD`. The electrical Quick Solve baseline may be retained without promotion; certification scope and cut access must be explicit (section 8).
4. **Determinism.** Iteration-budgeted runs reproduce identical output for identical input, locks, settings and seed regardless of worker count. Time-budgeted runs record realised work for deterministic iteration-budgeted replay. Every worker gets its own RNG seeded from `(master_seed, stage, seed_index)`.
5. **Versioned physical model.** The **LOCKED**, normative `docs/PHYSICAL_MODEL_SPEC.md` and approved `docs/PHYSICAL_MODEL_25D_AMENDMENT.md` outrank this implementation plan. No speculative assumed package dimensions or unknown standoffs become measured physical PASS; no claim of verified cut access without an actual cut-access verifier. This document does not amend the locked physical spec.
6. **Main branch only.** Make isolated, tested, reproducible milestones directly on `main` after checking the working tree; never overwrite user-owned local files. This v0.3 update is documentation only.

---

## 1. Background: the pipeline this replaces

Manual process that produced a world record on a previous solver:

- 2,000 seeds, fast pass, keep the top 10
- 500,000 moves on each of the top 10
- Total: over 30 minutes

That shape (wide cheap sweep, then deep refinement of survivors) is correct. Hell Mode keeps it and makes it faster and more systematic.

Measured throughput: 10 x 500k = 5M moves in about 1,800 s, roughly **2,800 moves/s**. That is slow for a move-based search and implies full re-evaluation per move. Section 5 fixes that.

**Targets (on a 44-component, 35-net board like `moto.json`, 3 workers):**

| Metric | Old | Hell Mode target |
|---|---|---|
| Wall time for equivalent search | 30+ min | 10 min or less |
| Moves/s per worker | ~2,800 (single) | 20,000+ |
| Result quality | WR-class | equal or better |

If the targets are missed, ship anyway but report the achieved numbers.

---

## 2. Objective

Lexicographic, never blended, for ranking inside the search:

```
score = (wires, cuts, total_wire_length_mm)   # lower is better, compare as a tuple
```

- Only layouts passing the **same declared verification and certification tier** are comparable as records (section 8). Compare an ELECTRICAL_ONLY Quick Solve baseline separately; an eligible record may require more wires than an uncertified baseline.
- Keep the existing 0-100 quality score as a display value only. It hides whether a change removed a wire, so the search must not optimise it.
- Also compute a **continuous surrogate** for guiding exploratory moves (section 4.3), including strict jumper-occupancy excess and maximum depth. Penalty-reduced-but-ineligible states may guide search, but may never enter the verified-record checkpoint. The surrogate is internal and is never the final objective.

Normalised metrics for cross-board comparison (report only):

- `wires_per_net = wires / nets`
- `wires_per_component = wires / components`

---

## 3. Pipeline

```
Stage 0  Baseline        Current Quick Solve once -> independently classify; seed -1 is exploratory unless eligible
Stage 1  Sweep           N1 seeds, short budget each, cheap eval only
Stage 2  Halving         keep top fraction, longer budget, repeat
Stage 3  Deep refine     top K distinct layouts, long budget, plateau stop
Stage 4  Reheat          restarts from the best with large moves
Stage 5  Final verify    full verifier on the winner and runners-up
```

### Default budgets (all configurable)

| Stage | Candidates in | Moves each | Keep |
|---|---|---|---|
| 1 Sweep | 2,000 seeds | 5,000 | top 200 |
| 2a Halving | 200 | 20,000 | top 50 |
| 2b Halving | 50 | 60,000 | top 15 (after dedupe, section 6) |
| 3 Deep | 10 distinct | up to 500,000, plateau stop | top 3 |
| 4 Reheat | best 1 to 3 | 20 restarts x 50,000 | best 1 |
| 5 Final verify | best 3 | n/a | verified winner |

Rules:

- **Successive halving:** a seed that is mediocre at 20k moves rarely wins at 500k, so stop paying for it.
- **Plateau stop per candidate:** retire a candidate after `plateau_moves` without improvement (default 50,000 in Stage 3, 10,000 in Stage 2). Freed budget is spent at the next stage boundary in deterministic order, never mid-stage.
- **Global stop:** time-budgeted runs honour the wall-clock deadline, global plateau and Stop at chunk boundaries, then proceed to Stage 5 and preserve the best verified result. Iteration-budgeted runs use deterministic move and plateau limits, not wall-clock stop conditions.
- **No target number.** There is no "stop at 25 wires". Optional user target is allowed, but the default is plateau-based.
- **Fixed board geometry.** Preserve actual rows, columns, copper orientation, hole origin, cut semantics, fixed/edge locks and existing manual constraints. Hell Mode never silently resizes the board.
- **No-record path.** If no strict-policy record is found, preserve the original Quick Solve baseline unchanged with its actual certification label and reason codes. Do not write it as a certified `best_solved.json`.
- The user can **extend** a finished run (continue from the saved state) if the improvement curve was still dropping.

---

### Time budgeting and reproducibility — v0.3

the default stages total roughly 23M attempted moves. At 60,000 moves/s aggregate that is about 6.4 minutes of pure move processing, before routing overhead, verification, checkpoints and coordination. A 10-minute budget is therefore tight and must not assume the plan fits.

### Work units and checkpoints

- All work is expressed as **chunks** of fixed move counts (default 5,000). Time is checked only at chunk boundaries.
- Each worker returns its candidate state at every chunk boundary. The coordinator checkpoints at **stage boundaries** (always) and every `checkpoint_chunks` chunks (default 20).
- Stage boundaries are **barriers**: all candidates in a stage finish their stage budget (or are retired by their own plateau rule) before promotion decisions.

### Budget scaling (time-budgeted runs)

1. **The user time budget covers everything:** Stage 0 Quick Solve baseline, startup/calibration, search, independent Stage 5 verification and atomic checkpoint writing. Measure and display each portion separately. Reserve `max(10 s, 5% of the time budget, 2 * measured_final_verification_time)` after a safe measurement; if the baseline alone consumes the deadline, report that honestly and return the classified baseline, not a false RECORD.
2. Measure aggregate throughput during a short calibration at the start of Stage 1.
3. Compute `scale = clamp((time_budget - reserve) * throughput_total / planned_moves, 0.05, 1.0)`.
4. Multiply per-stage move counts (and the Stage 1 seed count, rounded) by `scale`.
5. Store the resolved budgets and actual baseline/verification/checkpoint costs in `run.json` as `resolved_budget` and a timing breakdown. The target of 20,000 moves/s per worker is a hypothesis until M1 profiling measures it.

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

## 4. Search engine

### 4.1 State

A candidate is: component placements (position and permitted rotation; side only when expressly supported), plus routing (horizontal copper ownership, between-hole cuts and straight vertical jumper spans). **Board dimensions, hole origin, copper orientation, locked components, edge-lock rules and fixed off-board leads are hard invariants.** Out-of-bounds moves are rejected rather than repaired; no automatic resizing. An electrically valid layout can still be a physically ineligible *search state*.

### 4.2 Move set

Small moves (high frequency):

- shift a component by 1 hole in a row/column
- rotate a component by 90 degrees (where the footprint allows)
- swap two components of identical footprint class
- nudge a jumper endpoint to an alternative equivalent hole on the same net

Medium moves:

- swap two components of different footprint (only if both fit in each other's slots)
- move a component to a random legal position
- re-route one net (rip-up and re-route)
- re-route the k nets touching a moved component

Large moves (used in reheat, and rarely in the main loop):

- flip or translate a whole block of related components
- mirror a sub-region
- swap two rows' worth of components

Move selection: weighted random, weights adaptive (section 4.5). Every move must be **reversible** via a transactional journal: `begin -> apply -> evaluate -> commit | rollback`, storing old/new occupancy and routing of affected nets. M1 implements the move primitives, inverses, occupancy and differential test harness; M2 implements simulated-annealing selection, temperatures and acceptance policy. No forbidden rotation, edge violation or off-board part movement is made legal by a penalty.

### 4.3 Acceptance

Simulated annealing on the continuous surrogate:

```
surrogate = W_WIRE*wires + W_CUT*cuts + W_LEN*length_mm + W_UNROUTED*unrouted_pins + W_PEN*constraint_penalty + W_STACK*excess_gap_occupancy + W_DEPTH*max_stack_depth + W_HOLE*illegal_hole_conflicts
```

- Suggested starting weights: `W_WIRE=100, W_CUT=10, W_LEN=0.1, W_UNROUTED=1000, W_PEN=500`. Make them configurable. The ordering (wire >> cut >> length) matters more than exact values.
- Accept a worsening move with probability `exp(-delta / T)`.
- Temperature: geometric cooling per candidate, `T0` calibrated so roughly 30% of worsening moves are accepted at the start, `T_end` near zero. Expose `T0`, `T_end`, cooling schedule.
- Always track the best **tuple score** seen separately from the current state.
- **Hard-reject** different-net terminal conflicts/shorts, changed hard locks, unsupported rotations and out-of-board geometry. Allow temporarily *unrouted* or strictly stacked exploratory states with explicit penalties so annealing can escape the current illegal Quick Solve baseline. Neither is a result, a global best, nor a verified-record checkpoint. A strict-policy `RECORD` requires zero gap excess, no illegal hole sharing/pass-through, and independent full verification.

### 4.4 Incremental evaluation (the main speedup)

Per move, recompute only what changed:

- Maintain per-net cost caches (wires, cuts, length) and **per-(column, inter-hole-gap) occupancy counters** plus independent hole-landing counters. Every move journals `(cell, old, new)` and its prior routes, with exact rollback.
- A placement or routing move dirties the **union** of (1) nets on moved pins, (2) nets with routes/corridors/cuts in the old and new footprint plus clearance halo, and (3) nets sharing affected horizontal copper strip segments. Over-invalidate when uncertain.
- Maintain spatial indices for nearby lead, body, strip and jumper conflicts. Cache routing only with hashes covering touched terminal positions, copper ownership and relevant occupancy regions; hash collisions must not affect correctness.
- **Routing is order-dependent.** Do not require incremental and full reroute to produce byte-identical paths. Require every incremental candidate's occupancy, cost and electrical state to be internally consistent; rebuild any prospective RECORD from a clean input, then re-verify independently. For identical explicit geometry, the shadow full recomputation *must* agree on counters and a canonical occupancy hash.
- Provide `--paranoid`: shadow full recompute every move in M1 tests, configurable interval in production, zero occupancy/cost discrepancies. A failed comparison is a real bug, not an optimisation metric. Use a transactional journal `begin -> apply -> evaluate -> commit | rollback`.

### 4.4a Two-tier checking

| Tier | When | What |
|---|---|---|
| Cheap | every move | hard invariants, dirty-net electrical consistency, hole/corridor counters, excess gap occupancy, max depth, wires/cuts/length |
| Heavy | before recording any newly eligible candidate best, and in Stage 5 | independent re-derived electrical/net/strip ownership, strict hole-and-gap occupancy, supported 2.5D envelope checks, reported cut access; rebuilt routes when required |

When a move would become a candidate's new best and the heavy verifier rejects it:

1. **Ineligibility.** The state is never recorded as a best, and it is written to `rejected.json` with reason codes.
2. **Revert.** The move is undone in the active annealing state using its undo record. A state the final authority rejects is not a valid place to continue from, and keeping it would make later "bests" inherit the failure and re-trigger heavy checks.
3. **Tabu.** The rejected state hash is blocked for the next `tabu_moves` (default 2,000) so the search does not immediately re-propose it.
4. **Classify** the failure:
   - `ROUTER_VERIFIER_DISAGREEMENT`: the failing rule is one the router claims to enforce. This is a bug in one implementation. Save a repro (input hash, settings, seed, move index, state), and fail the run under `--paranoid` and in CI. In a normal run, log it and continue.
   - `HEAVY_ONLY_REJECT`: the failing rule is verifier-only (full electrical, cut access heuristics). This is expected behaviour, counted but not an error.
5. **Circuit breaker.** After 20 consecutive heavy rejects on one candidate, run the heavy verifier on every accepted improving move for that candidate (not just would-be bests) and log `cheap_tier_too_permissive` in the report. If it continues, retire the candidate.

Answer to the explicit question: **both**. Discard eligibility, and undo the move in the active state.

### 4.5 Adaptive move weights

Track per move type: attempts, accepts, improvements. Periodically (every ~5,000 moves) shift weight toward move types with higher improvement-per-second. Keep a floor weight (e.g. 2%) on every type so nothing starves. Log the weights in the run report.

---

## 5. Performance plan

Do these in order, measuring after each:

1. Profile a Stage 1 run. Record moves/s and a time breakdown (move gen, route, score, verify, I/O).
2. Add incremental evaluation (4.4), measuring full and incremental moves/s on the same hardware; **5x is a soft M1 target, not a promised speedup**.
3. Move the heavy verifier out of the inner loop (4.4a) without ever promoting unverified candidates.
4. Parallelise across workers (section 7).
5. Only then consider micro-optimisation (numpy vectorisation, numba, native extension).

Report moves/s per worker in the GUI live panel. If a stage is below target, the report should say which cost dominates.

---

## 6. Diversity (so the top 10 are really 10)

Near-identical layouts waste deep-refinement runs. Before Stage 3 (and Stage 2b):

- Compute a **placement distance** between two candidates: sum over non-locked components of Manhattan hole distance (plus a penalty for rotation difference), normalised by component count.
- Greedy select: take the best candidate, then repeatedly add the next best whose distance to every already selected candidate is >= `min_distance` (default 1.5 holes average). If fewer than K remain, relax `min_distance` stepwise and log it.
- Record in the output which candidates were dropped as duplicates.

---

## 7. Parallelism

- Worker count default = the value recommended by the startup speed probe (currently 3 on the dev machine). User-overridable. Never exceed physical cores minus one without an explicit override.
- Use **processes**, not threads (CPU-bound Python). Each worker is independent: it gets `(input_json, settings, seed, budget)` and returns `(best_state, stats)`.
- Coordinator is single-threaded: schedules work, merges results, writes checkpoints, updates the GUI queue. Workers never write the shared checkpoint.
- Determinism: iteration-budgeted results are independent of worker scheduling; sort merged results by `(score_tuple, seed_index)`. Time-budgeted runs log realised work for replay.
- Cancellation: workers poll a shared stop flag every ~1,000 moves and return their best so far.
- Avoid shipping huge state over IPC. Send compact encoded placements and recompute routing in the worker where needed.

---

## 8. Verification and reporting

Verdict vocabulary (aligned with the 2.5D model discussion):

- `PASS`: geometry clearance established.
- `CONDITIONAL`: passes only because of a recorded assumption (declared standoff, `allow_contact`). Assumptions listed in the report.
- `FAIL_PROVEN`: known conflict (lead conflict, body overlap with known flush seating, occupied hole pass-through, thermal limit with grounded data).
- `FAIL_UNVERIFIED`: insufficient evidence to permit routing (e.g. unknown standoff). Blocked, but not reported as a confirmed collision.

Router and verifier enforce the **same** `min_clearance`. Any extra router conservatism is a separate `search_preference_margin` used for cost shaping or tie-breaking only, never as a hard reject.

**Certification is multidimensional.** Report `electrical`, `grid`, `jumper_geometry`, `cut_access`, `assumptions`, and reason codes separately. Display ladder: `ELECTRICAL_ONLY -> GRID_VERIFIED -> JUMPER_GEOMETRY_PASS`; **do not call the last tier an unqualified physical PASS** while cut access or measured package data is unknown. `PHYSICAL_PASS` as a complete-board claim requires the normative physical checks, including cut accessibility.

| Class | Requirements |
|---|---|
| `ELECTRICAL_ONLY` | Electrically verified, but strict geometry failed or remains unverified; list reasons, including any `STACKING_VIOLATION`. |
| `GRID_VERIFIED` | Electrical and grid checks passed, but full physical-jumper geometry is not established. |
| `RECORD` | Unconditional independent electrical and **jumper/lead/body/occupancy geometry** PASS, including STRICT gap/hole rules, with explicitly scoped `cut_access` (often `unverified`); lowest `(wires, cuts, length)` among equally eligible records. Never describe this as a fully build-ready or unqualified physical PASS. |
| `BUILD_READY` | `RECORD` **plus independently verified cut-tool accessibility** and any other mandatory physical checks. While no cut-access verifier exists this is never granted. |

`PHYSICAL_PASS_WITH_ASSUMPTIONS` is **reserved**, not implemented in v1; it cannot masquerade as unconditional PASS. Candidate records with missing full footprint/body/standoff evidence remain ineligible under PASS_ONLY. A `RECORD` may cost more wires than an uncertified baseline; comparison must acknowledge certification tiers.

`geometry_policy`, default and only v1 value `"PASS_ONLY"`. The value `"ALLOW_CONDITIONAL"` is reserved and must raise a clear "not implemented" error.

**Behaviour under PASS_ONLY:**

- The router treats `CONDITIONAL`, `FAIL_UNVERIFIED` and `FAIL_PROVEN` as blocked.
- The verifier still reports the full four-verdict vocabulary, so reports stay honest (an unknown-standoff block shows as `FAIL_UNVERIFIED`, not as a collision).
- A candidate whose *required independent verification* has anything other than unconditional `PASS`, or nonzero STRICT occupancy violations, is ineligible as a `RECORD`. Report `FAIL_PROVEN` versus `FAIL_UNVERIFIED` distinctly; unknown dimensions are not evidence of a collision.

A fewer-wire layout that fails verification is stored under `rejected_candidates` with reasons, never presented as the result.

Run report must state:

- the measured and classified baseline (or `no baseline`) versus the best **same-certification** result (`improved`, `equal`, or `no improvement`). If a higher-certification `RECORD` has a worse numeric tuple than an ELECTRICAL_ONLY baseline, say so explicitly; never claim numerical dominance across tiers.
- strict-policy `STACKING_VIOLATION` details: affected gap count, *excess occupancy*, maximum stack depth, hole conflicts and illustrative wire IDs. Pair count is diagnostic only; it is **not** a search objective.
- normalised metrics
- verifier version and physical-model spec version
- any `CONDITIONAL` assumptions and any `cut_access: unverified` flag

---

## 9. Lower bound (optional but valuable)

Cheap estimate of the minimum wires for a given placement, so we know how much headroom is left:

- For each net, count connected components of its pins under strip-only connectivity (pins sharing a strip segment with no forced cut between them). A net with `c` components needs at least `c - 1` wires.
- Sum over nets. Report `wire_lower_bound` for the best placement and the gap to the achieved wires.

This is a bound for a given placement, not a global minimum, so label it that way. If the gap is zero, stop early for that candidate.

---

## 10. Checkpointing and file formats

Auto-save **only independently verified eligible `RECORD` improvements** to `best_solved.json`, atomically (write temporary file, then rename). Search-state and diagnostic checkpoints may contain ineligible candidates, **clearly flagged as search states**, never as records; preserve an ELECTRICAL_ONLY fallback separately.

Files, next to the input JSON, in a folder `<name>_hellmode/`:

```
run.json                  settings, baseline status, versions, master seed, reason codes, timeline, summary
baseline_solved.json      unmodified Quick Solve baseline if one exists; never a RECORD by implication
best_solved.json          only a verified eligible RECORD; absent when no RECORD exists
candidates/seed_<i>.json  stage search-state checkpoints, explicitly marked ineligible until verified
history.csv               one row per verified new RECORD: time, stage, seed, wires, cuts, length, moves_total
rejected.json             independently rejected would-be records, with reason codes
```

`best_solved.json` must load in the existing Load JSON / Open Solved flow with no changes to the loader. Extra Hell Mode data goes under a namespaced key (`"hellmode": {...}`) that older versions ignore.

`run.json` must contain enough to **replay** a result: input hash, settings, master seed, seed index, stage, move count, verifier version, physical-model spec version, measured Quick Solve baseline, `resolved_budget`, and for time-budgeted runs each candidate's realised stop chunk.

Resume: a run can restart from `run.json` plus candidate files and continue from the last completed stage boundary (mid-stage resume is optional).

---

## 11. GUI

New top-level section (e.g. a **Hell Mode** tab or button beside Quick Solve). Do not clutter the Quick Solve screen.

Controls:

- Input: current loaded circuit (read-only display of components/nets)
- Preset: `Fast`, `Standard`, `Hell` (budget presets from the table in section 3)
- Worker count (default from probe), master seed (blank = random, shown after start)
- Time budget, global plateau minutes
- Objective order (fixed: wires, cuts, length; shown, not editable in v1)
- Start, Pause, Stop (Stop keeps best), Extend

Live panel:

- Current stage and progress bar (candidates remaining, moves done)
- Best so far: wires, cuts, length, and the delta vs the Quick Solve baseline
- Moves/s per worker and total
- Moves since last improvement; time since last improvement
- Improvement curve (best wires over time)
- Verifier status of the current best: `RECORD` / `BUILD_READY`, any `CONDITIONAL` or `cut_access: unverified`
- Button: "Show best on board" (renders without stopping the run)

Show the history table of bests. Never block the UI thread: all search work in worker processes, GUI polls a queue.

---

## 12. CLI (for testing and batch runs)

```
routemate hellmode <input.json> [--preset hell] [--workers 3] [--seed 123]
                   [--time-budget 600] [--global-plateau-min 5]
                   [--out-dir <dir>] [--resume <run.json>] [--paranoid]
```

Exit code 0 on completion with a verified result, non-zero if no verified layout was produced. Print a one-screen summary at the end.

---

## 13. Tests (write these before the search code)

1. **Quick Solve regression:** compare unsolved Set U inputs to snapshots pinned from the pre-merge SHA; historical solved exports are Set H compatibility tests only.
2. **Determinism:** iteration-budgeted runs with the same seed give byte-identical `best_solved.json` with 1 worker and with 3 workers.
3. **Incremental vs full:** `--paranoid` run of 200k moves, zero mismatches.
4. **Locks:** locked components never move across 1M random moves.
5. **Move reversibility:** apply move then undo returns the exact prior state (hash compare), for every move type.
6. **Verifier gate:** inject a candidate that has fewer wires but a known geometry failure; it must land in `rejected.json`, not `best_solved.json`.
7. **Halving logic:** with synthetic scores, the right candidates survive each stage and freed plateau budget is reallocated deterministically at the next stage boundary.
8. **Diversity:** duplicate candidates are collapsed; `min_distance` relaxes and logs when needed.
9. **Stop and resume:** Stop mid-run keeps the best; resume continues from the checkpoint.
10. **Golden geometry fixtures** (shared with the verifier): G01 to G07, G03a/G03b split, plus boundary cases exactly at and just inside `min_clearance` with a stated floating-point tolerance. Hell Mode must not accept anything these fixtures reject.

---

### Set U / Set H regression and measured baseline — v0.2

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
- **Inject the classified baseline as exploratory seed `-1`.** It joins the eligible RECORD set **only if** it passes the identical STRICT independent verification gate. Preserve an ineligible electrical baseline unchanged for fallback, never promoting it as a RECORD. The promise is: never worse than the baseline *among equal-certification layouts*; where no RECORD exists, return the baseline labelled `ELECTRICAL_ONLY` with reasons.

### Frozen M1 acceptance tests

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

### Added frozen M1 acceptance gates — v0.3

| ID | Test |
|---|---|
| M1-9 | Independent, fixture-driven STRICT jumper occupancy verifier: identical/contained/partial spans, endpoint-on-span, end-to-end shared hole, same-net and different-net variants, separate columns and adjacent columns, intermediate component-pin holes, permitted explicitly same-net endpoint landings, illegal different-net shared landings, and different-net wire-body overlap. Verify exact gap/hole counters, reasons, and conductor-clearance dimensions when provided. |
| M1-10 | MOTOMIX **characterisation golden** against `benchmarks/moto/motomix-autorouted.json` on pinned SHA: 46 jumpers, 57 between cuts, 33 different-net span-overlap pairs, 51 affected unit gaps, 95 excess occupied unit gaps, maximum depth 7; seven known cluster IDs. Independent implementation and standalone spike must agree, without sharing occupancy helpers. Report ELECTRICAL_ONLY/GRID_VERIFIED as appropriate, `STACKING_VIOLATION`, and `cut_access: unverified`. |
| M1-11 | Fixed-placement/fixed-cut/fixed-endpoint-row legalisation infeasibility witness: seven distinct-net intervals all traverse gap `(col=2, rows=8..9)` in the baseline; each compatible column lies within `{0,1,2,3,4}` under unchanged cut segmentation. Verify pigeonhole impossibility and exit the cheap legaliser without claiming success. Pin/body keepouts may reduce domains further. |
| M1-12 | Reason-coded status ladder, verified/uncertified baseline separation, no-record fallback, no ineligible `best_solved.json`, injected stack/open mutations, fixed dimensions and immutable locks. An independently rejected candidate with fewer wires cannot become RECORD. |

**M1 implementation order:** (1) pin pre-Hell Set U snapshots on the last uncontaminated `main` SHA and commit immutable expected hashes; (2) build standalone diagnostic occupancy spike + golden JSON and synthetic fixtures; (3) implement verifier facade with separate, independently re-derived strips, net ownership, pin holes and jumpers; (4) implement minimal placement/reroute/undo primitives and delta counters; (5) shadow tests, profiling, and CI; (6) only after every gate passes implement M2 simulated annealing. M1 move primitives are mechanism, not the M2 search policy.

Nothing in M2 to M7 starts until **M1-1 through M1-12** are green, with M1-6 allowed to pass only on a written measured-speed explanation. The frozen M1-1..M1-8 v0.2 checks remain in scope, expanded—not silently waived—by v0.3 tests below. A design spike does not count as a passing executable CI test.

---

## 14. Milestones

| M | Deliverable | Done when |
|---|---|---|
| 1 | **Independent STRICT verifier + minimal reversible move primitives + transactional incremental state + profiling** | M1-1..M1-12 all pass; no Quick Solve behavioural changes; shadow recomputation and infeasibility fixtures proven |
| 2 | SA acceptance, legalising/rerouting moves, single-worker deep refinement | reports true record eligibility, improvement or truthful no-record outcome; cannot promote stacked baseline |
| 3 | Pipeline stages 0–5, halving, plateau, diversity and deterministic post-pass | full run completes and verified comparison report produced |
| 4 | Multi-process workers + deterministic merge/replay | identical iteration-budget outputs for 1 versus 3 workers; budget fairness verified |
| 5 | Atomic record checkpoints, diagnostic state checkpoints, Stop/resume/extend, history | only certified records enter best_solved.json; no-record fallback survives Stop and resume |
| 6 | Dedicated Hell Mode GUI and matching CLI live panel | Start/Stop/Extend work, status/reasons visible, GUI remains responsive |
| 7 | Tuning, reheat, adaptive weights, lower bound, optional sequential redundancy cleanup | measured gains against same verified reference tier; no hard-coded MOTOMIX optimum |
| 8 | Explicit conditional geometry policy (deferred beyond v1) | router/verifier assumptions match; scoped results distinct from unconditional RECORD |

Ship after each milestone behind a feature flag. Do not start M2 until M1-1 through M1-12 pass. Do not start M6 before M4 is stable. No Quick Solve kernel changes are authorised as a shortcut.

### M8 prerequisites — conditional routing

1. The router can emit `CONDITIONAL` with an explicit assumption list (declared standoff, `allow_contact`).
2. The verifier returns the same assumptions for each `CONDITIONAL`.
3. Golden fixtures G04 and G07 pass in both implementations.
4. `run.json` gains an `assumptions` array, and reports list every assumption a record depends on.

Then `geometry_policy = "ALLOW_CONDITIONAL"` may be enabled, with `CONDITIONAL` records reported separately from `PASS`-only records.

---

## 15. Open questions (decide, document, move on)

1. Is cut access verifiable yet? If not, `BUILD_READY` can never be fully true and must show `cut_access: unverified`.
2. Which footprints may rotate or flip? Needs a per-footprint flag.
3. Should components on the copper side or off-board (headers, connectors) be movable? Default: no, treat as locked unless flagged.
4. Do any nets have routing constraints (power width, keep-apart, short-as-possible)? If yes, add them to the constraint penalty and the heavy verifier.
5. Pick the final default weights after the first tuning pass (milestone 7), and record them in the spec.

---

## 16. Non-goals for v1

- No machine-learned move proposals.
- No multi-objective Pareto front in the GUI.
- No automatic component footprint correction.
- No change to the Quick Solve algorithm.

---

## 17. Definition of done

On `moto.json` and a second independent circuit, a Hell preset run with the recorded worker/seed/budget settings finishes or stops cleanly within its **total** time budget, preserves Quick Solve golden output, writes a replayable `run.json`, and either (a) produces an independent-verifier-eligible strict-policy `RECORD` ranked by `(wires, cuts, length)` against peers at the same certification tier, or (b) reports `no RECORD found` and returns the **unchanged, honestly classified** Quick Solve electrical baseline. A strict record may be numerically worse than an uncertified baseline; that is reported, not concealed. Strict numeric improvement is a tuning goal, not a licence to bypass hard physical rules or invent geometry.

Historical numeric baselines are descriptive only; no fixed wire/cut counts may be used as code, test or acceptance targets.

---

## 18. v0.3 STRICT occupancy contract, feasibility evidence and implementation decisions

### 18.1 Authoritative constraints and proof scope

- The locked physical spec and approved 2.5D amendment remain normative. v0.3 adds Hell Mode's **conservative STRICT search/record eligibility policy**, not a new allowed wire direction or unsupported measured stack model.
- Copper is horizontal and between-hole cuts split a strip into independently owned horizontal intervals. A jumper is exactly one vertical segment. The 24 × 56 MOTOMIX board means **24 rows and 56 columns**, not 24 routing columns. Each reassigned jumper's two endpoints must remain in the *same original copper-connected intervals* under any frozen-cut-only legalisation experiment.
- **No short is inferred from insulated wires' overlapping XY projections alone.** Overlap without verified separation is a STRICT physical-eligibility veto, not proof of an electrical short. Only independently re-derived copper/pad connectivity determines shorts/opens.

### 18.2 Per-gap and per-hole STRICT rule

- Use integer counter `gap_occupancy[col, row]` for every elementary vertical gap between `(row,col)` and `(row+1,col)` crossed by jumper centreline, plus `hole_occupancy[row,col]` tagged as component pin/lead, jumper landing or wire pass-through. Both same-net and different-net jumper segments are counted; no unconditional same-net exemption.
- **STRICT** forbids two jumpers in the same vertical gap, two jumper landings in one hole, and one jumper passing through the landing hole of another jumper. Also reject jumper body over an intermediate occupied component-pin/lead hole. Two spans touching end-to-end at a hole conflict. A jumper **endpoint** coincident with an assigned component pad may be legal *only* as a verified intentional same-net landing under the project's endpoint/lead-access rule. Do not globally prohibit all pad endpoints: MOTOMIX already uses such landings.
- Adjacent columns and disjoint holes/gaps have no logical occupancy conflict; independently check actual measured wire diameter, lead envelope and required lateral clearance before declaring unconditional physical clearance. Cross-net crossing and stacking are not automatically permitted by insulation; a future explicitly modelled conditional 2.5D policy is deferred to M8.
- Hole sharing between different-net component pins is a hard electrical failure. An intermediate pin pass-through is a STRICT physical failure even when the wire is insulated; no invented jumper height makes an unmeasured installation PASS.
- Derive `excess_gap_occupancy = sum(max(0, count-1))` over unit gaps, `stacked_gap_count = count(gaps where occupancy > 1)`, and `max_stack_depth = max(count)`; track separate illegal hole conflicts. Use excess and depth as incrementally updated search penalties; **not the quadratic overlapping-pair count**. RECORD requires excess=0, max depth<=1, zero illegal holes and unconditional independent verifier clearance.
- Suggested reason codes: `STACKING_VIOLATION`, `JUMPER_SHARED_HOLE`, `JUMPER_ENDPOINT_ON_SPAN`, `INTERMEDIATE_PAD_PASS_THROUGH`, `DIFFERENT_NET_PIN_CONFLICT`, `JUMPER_BODY_CLEARANCE_UNVERIFIED`, `CUT_ACCESS_UNVERIFIED`, `UNVERIFIED_PACKAGE_GEOMETRY`, and `LEGALISATION_INFEASIBLE`. Never reclassify unknown evidence as proven collision.

### 18.3 MOTOMIX M1 evidence — independent test fixture needed

Input: committed `benchmarks/moto/motomix-autorouted.json` from the Route-Mate 1.44 run; 44 components, 35 nets, 24 rows, 56 columns, **46 jumper records and 57 cuts**. Preliminary stand-alone diagnostic analysis (not yet committed as a test and **not** an independent replacement for production electrical verification) found:

| Observation | Value |
|---|---:|
| Different-net collinear span-overlap pairs | 33 |
| Same-net collinear span-overlap pairs | 0 |
| Distinct overoccupied unit gaps | 51 |
| Excess gap occupancy | **95** |
| Maximum depth on one unit gap | **7** |
| Identical spans | 0 |
| Shared jumper endpoint pairs | 0 |
| Overlapping row spans: contained / partial | 14 / 19 |

Seven jumper IDs crossing the `(col=2, rows=8..9)` unit gap (all coordinates **zero-based**): `RM-W002`, `RM-W007`, `RM-W010`, `RM-W016`, `RM-W025`, `RM-W031`, `RM-W032`. These belong to distinct nets under the current saved copper segmentation; their ownership must be independently reproduced by M1's new verifier. The 33-pair count is descriptive only; the **95 excess occupied gaps** is the meaningful linear congestion measure.

### 18.4 Fixed-cut, fixed-endpoint-row column-only feasibility spike

- Freeze **all component positions, all 57 cuts, all 46 jumpers' endpoint rows**, all net assignments and the board size. For each jumper, enumerate columns where each new endpoint remains connected through the corresponding **same horizontal copper segment** as its old endpoint. This is only a *necessary* feasibility condition; component-pin occupancy, body clearance and other landing rules may reduce available columns.
- In the critical seven-jumper cluster, the union of cut-compatible columns is `{0,1,2,3,4}` (5 columns). Every interval crosses the same row-gap. STRICT requires **7 distinct columns** for those intervals. Since 7 > 5, **no strict non-stacked reassignment of these fixed 46 row spans exists**, even before extra pin/body constraints. This is a pigeonhole infeasibility witness, not a heuristic failure.
- Consequence: **column-only legalisation is a fast subroutine with an infeasibility exit, not the full Hell Mode router**. A complete solver must be able to change jumper endpoints/route topology, recompute cuts and, where allowed, move unlocked components while preserving electrical correctness and locks. Do not turn this proof into a claim that *all* legal MOTOMIX placements are impossible.
- Four jumpers (`RM-W014`, `RM-W015`, `RM-W036`, `RM-W038`) appeared **individually** electrically removable in the diagnostic union-find model, with the first two touching stacked gaps. Combined removal, independent verifier equivalence, and physical legality remain **unproven**. Treat any deterministic cleanup as a separately verified, greedy-sequential post-pass (M3/M7), never as the primary stacking fix.

### 18.5 Independent verifier and exploratory state invariants

- Introduce a stable verifier facade `verify_layout(layout, spec) -> report` that derives copper segments, net ownership, all assigned and unassigned pad holes, jumper intervals and lead clearances from **raw source**. The facade may orchestrate existing independent verifier implementations but must not trust router/incremental caches, reported net ownership or input-output quality claims.
- Add import-graph tests: neither independent verifier nor its occupancy implementation may import the Hell Mode router, optimiser or incremental evaluator, and the router may not import verifier internals. Share only normative immutable constants and agreed input schema/golden fixtures, **not** the occupancy algorithm under test.
- A delta move's dirty set includes moved component-pin nets, nets touching old/new footprint + clearance halo, and every net with strip ownership/cut effects on the affected horizontal run(s). Use journalled `begin -> apply -> evaluate -> commit | rollback`, with an independently recomputed shadow occupancy hash, hole/gap counters, connected-net validity and cost totals.
- The full rerouter can make different routing choices based on net order. Shadow equality therefore applies to recomputation of the **same explicit candidate**; a clean rebuilt candidate need only be independently valid and cost-consistent, not wire-for-wire identical to a partial reroute. Every would-be RECORD is rebuilt/rerouted as needed and independently checked before promotion.
- Preserve the user's sourced original unsolved JSON and baseline. Iteration-budgeted runs are scheduling-independent; time-limited runs write resolved work for replay. Document measured limits; **do not claim the 10-minute or 20,000 moves/s targets until the actual benchmark confirms them**.

### 18.6 Next implementation work (not yet completed)

1. Commit a **read-only, deterministic standalone M1 occupancy/column-domain spike script**, frozen MOTOMIX expectation JSON, and synthetic pass/fail layouts. Validate exact measured counters against a second independent occupancy implementation. No Quick Solve changes.
2. Implement the independent STRICT verifier facade, reason-code/status outputs, pad/landing exceptions, import-graph tests and baseline-ineligible fallback; do not claim any benchmark's physical clearance without explicit inputs.
3. Implement transactional minimal move primitives, inverse operations, delta occupancy/strip ownership, canonical full recompute and paranoid differential checks. Run the frozen 200k-per-move-type and 1M-lock M1 tests.
4. Profile full versus incremental moves on the same hardware, publish actual measured throughput and breakdown, finish M1-1..M1-12 and get them green in CI. Only then start M2's single-worker annealing/search strategy.
5. Continue M3–M7 by the table in section 14: wide cheap sweep, halving, deep refine, reroute/reheat, deterministic multiprocessing, recovery, dedicated GUI and verified cleanup. Keep fixed board/locks invariant, no hardcoded MOTOMIX numeric targets, and compare only like-certified RECORDs.

**Known limitation:** The diagnostic evidence is grounded in the saved 1.44 layout and the previously reported connectivity model. Independent fixture code, a fresh verified electrical run, the physical landing model and M1 CI acceptance tests remain implementation tasks. The phrase `M1 spike complete` never means that M1 acceptance has passed.

---
