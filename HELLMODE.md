# Route-Mate Hell Mode: Implementation Spec

**Status:** implementation spec v0.2 — M1 acceptance tests frozen; Route-Mate 1.38+
**Audience:** the implementing engineer (ChatGPT / Codex)
**Goal:** a separate, long-running search mode that minimises wires, then cuts, then wire length, on any circuit, with no reference record to chase. Every run races against its own Quick Solve baseline.

---

## 0. Ground rules (read first)

1. **Quick Solve must not change behaviour.** It works. Hell Mode is a new GUI section and a new module. If a change to shared code alters Quick Solve output for the same input and seed, that is a regression.
2. **Shared core.** Hell Mode and Quick Solve share the placement model, the routing API, the electrical-check API, the normative physical-model constants, and the golden fixtures. They do **not** share geometry-verifier code. Hell Mode calls the verifier only through its public entry point `verify_layout(layout, spec) -> report`. The verifier must not import router internals, and the router must not import verifier internals. An import-graph test enforces this (M1-7).
3. **A result only counts if it is verified.** A layout with fewer wires that fails the electrical check or the geometry verifier is a number, not a record. Reports must separate `RECORD` from `BUILD_READY` (section 8).
4. **Determinism.** Iteration-budgeted runs reproduce identical output for identical input, locks, settings and seed regardless of worker count. Time-budgeted runs record realised work for deterministic iteration-budgeted replay. Every worker gets its own RNG seeded from `(master_seed, stage, seed_index)`.
5. **Versioned physical model.** The approved v1.1 amendment `docs/PHYSICAL_MODEL_25D_AMENDMENT.md` is referenced by `docs/PHYSICAL_MODEL_SPEC.md`. Hell Mode records its actual physical-model and verifier versions; it does not infer missing dimensions or certify unverified cut access.

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

- Only **verified** layouts are comparable (section 8).
- Keep the existing 0-100 quality score as a display value only. It hides whether a change removed a wire, so the search must not optimise it.
- Also compute a **continuous surrogate** for guiding moves inside the search (section 4.3), since a tuple is too flat to climb. The surrogate is internal and never reported as the result.

Normalised metrics for cross-board comparison (report only):

- `wires_per_net = wires / nets`
- `wires_per_component = wires / components`

---

## 3. Pipeline

```
Stage 0  Baseline        Current Quick Solve once -> measured baseline, injected as seed -1
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
- The user can **extend** a finished run (continue from the saved state) if the improvement curve was still dropping.

---

### Time budgeting and reproducibility — v0.2

the default stages total roughly 23M attempted moves. At 60,000 moves/s aggregate that is about 6.4 minutes of pure move processing, before routing overhead, verification, checkpoints and coordination. A 10-minute budget is therefore tight and must not assume the plan fits.

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

## 4. Search engine

### 4.1 State

A candidate is: component placements (position, rotation, side if applicable), plus a routing (strip segments, cuts, jumpers). Locked components (from the Locks step) are immutable and must never be moved by any move.

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

Move selection: weighted random, weights adaptive (section 4.5). Every move must be **reversible** (store an undo record) so rejection is O(touched), not O(board).

### 4.3 Acceptance

Simulated annealing on the continuous surrogate:

```
surrogate = W_WIRE*wires + W_CUT*cuts + W_LEN*length_mm + W_UNROUTED*unrouted_pins + W_PEN*constraint_penalty
```

- Suggested starting weights: `W_WIRE=100, W_CUT=10, W_LEN=0.1, W_UNROUTED=1000, W_PEN=500`. Make them configurable. The ordering (wire >> cut >> length) matters more than exact values.
- Accept a worsening move with probability `exp(-delta / T)`.
- Temperature: geometric cooling per candidate, `T0` calibrated so roughly 30% of worsening moves are accepted at the start, `T_end` near zero. Expose `T0`, `T_end`, cooling schedule.
- Always track the best **tuple score** seen separately from the current state.
- Infeasible states (electrical fail, locked component moved, overlap) are rejected outright. They are never accepted at any temperature, or only through an explicit penalty term if a relaxed mode is enabled (off by default).

### 4.4 Incremental evaluation (the main speedup)

Per move, recompute only what changed:

- Maintain per-net cost caches (wires, cuts, length). A move invalidates only nets with a pin on a moved component, plus nets whose route used moved geometry.
- Maintain an occupancy grid (holes used by leads, jumpers, strip cuts). Update by delta.
- Maintain a spatial index for keepout/clearance queries so a move checks only nearby objects.
- Cache route results keyed by `(net_id, pin_positions_hash, occupancy_region_hash)`.
- Provide a debug flag `--paranoid` that, every N moves, does a **full** recompute and asserts equality with the incremental state. Run this in tests. Incremental drift is the classic bug in this kind of code.

### 4.4a Two-tier checking

| Tier | When | What |
|---|---|---|
| Cheap | every move | electrical connectivity of touched nets, hole occupancy, wire/cut/length counters |
| Heavy | only when a move would become a new per-candidate best, and in Stage 5 | full geometry verifier (2.5D keepouts), cut-access heuristics, full electrical check |

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
2. Add incremental evaluation (4.4). Expect 5 to 20x.
3. Move the heavy verifier out of the inner loop (4.4a).
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

Result classes:

| Class | Requirements |
|---|---|
| Class | Requirements |
|---|---|
| `RECORD` | Passes the electrical check, and every jumper and keepout check is unconditional `PASS`. Lowest score tuple among such layouts. |
| `BUILD_READY` | `RECORD` plus cut access verified. While no cut-access verifier exists this is never granted, and results carry `cut_access: unverified`. |

`geometry_policy`, default and only v1 value `"PASS_ONLY"`. The value `"ALLOW_CONDITIONAL"` is reserved and must raise a clear "not implemented" error.

**Behaviour under PASS_ONLY:**

- The router treats `CONDITIONAL`, `FAIL_UNVERIFIED` and `FAIL_PROVEN` as blocked.
- The verifier still reports the full four-verdict vocabulary, so reports stay honest (an unknown-standoff block shows as `FAIL_UNVERIFIED`, not as a collision).
- A candidate whose verifier report contains anything other than `PASS` is ineligible as a result. 

A fewer-wire layout that fails verification is stored under `rejected_candidates` with reasons, never presented as the result.

Run report must state:

- the measured baseline (or `no baseline`) versus the final score, with `improved`, `equal`, or `no improvement` status
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

Auto-save on every new global best, atomically (write temp file, then rename).

Files, next to the input JSON, in a folder `<name>_hellmode/`:

```
run.json                  settings, versions, master seed, timeline, summary
best_solved.json          current global best, normal Route-Mate solved JSON
candidates/seed_<i>.json  top candidates per stage (compact)
history.csv               one row per new best: time, stage, seed, wires, cuts, length, moves_total
rejected.json             heavy-verifier rejects with reason codes
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
- **Inject the baseline layout into the candidate pool** (seed index `-1`), so the final result is never worse than the baseline by construction. The report states `improved`, `equal` or `no improvement` against it.

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

Nothing in M2 to M7 starts until M1-1 through M1-8 are green, with M1-6 allowed to pass only on a written speed explanation.

---

## 14. Milestones

| M | Deliverable | Done when |
|---|---|---|
| 1 | Profile + incremental evaluator | moves/s measured, `--paranoid` passes |
| 2 | Move set, undo, SA acceptance, single-worker Stage 3 | beats Quick Solve baseline on `moto.json` |
| 3 | Pipeline stages 1 to 5, halving, plateau, diversity | full run completes, report generated |
| 4 | Multi-process workers + determinism | tests 2 and 7 pass |
| 5 | Checkpointing, resume, history | tests 9 passes |
| 6 | GUI section + live panel | Start/Stop/Extend work, UI never blocks |
| 7 | Tuning: adaptive weights, reheat, lower bound | measurable gain logged vs M3 |
| 8 | Conditional routing (deferred beyond v1) | router/verifier assumptions agree; G04/G07 pass; report records assumptions |

Ship after each milestone behind a feature flag. Do not start M2 until M1-1 through M1-8 pass. Do not start M6 before M4 is stable.

### M8 prerequisites — conditional routing

1. The router can emit `CONDITIONAL` with an explicit assumption list (declared standoff, `allow_contact`).
2. The verifier returns the same assumptions for each `CONDITIONAL`.
3. Golden fixtures G04 and G07 pass in both implementations.
4. `run.json` gains an `assumptions` array, and reports list every assumption a record depends on.

Then `geometry_policy = "ALLOW_CONDITIONAL"` may be enabled, with `CONDITIONAL` records reported separately from `PASS`-only records.

Then `geometry_policy = "ALLOW_CONDITIONAL"` may be enabled, with conditional records distinguished from PASS-only records.

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

On `moto.json`, a Hell preset run on 3 workers finishes within the time budget, produces a layout that passes the electrical check and has unconditional `PASS` geometry, has a score tuple strictly better than the **measured** Quick Solve baseline recorded in `run.json`, saves a replayable `run.json`, and leaves Quick Solve output unchanged against its pinned snapshot. If no strict improvement is found, the run reports `no improvement` and the investigation (not the label) is the deliverable.

Historical numeric baselines are descriptive only; no fixed wire/cut counts may be used as code, test or acceptance targets.
