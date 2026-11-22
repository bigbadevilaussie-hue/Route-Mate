# Route-Mate Hell Mode: Implementation Spec

**Status:** proposal v0.1, for implementation against Route-Mate 1.38+
**Audience:** the implementing engineer (ChatGPT / Codex)
**Goal:** a separate, long-running search mode that minimises wires, then cuts, then wire length, on any circuit, with no reference record to chase. Every run races against its own Quick Solve baseline.

---

## 0. Ground rules (read first)

1. **Quick Solve must not change behaviour.** It works. Hell Mode is a new GUI section and a new module. If a change to shared code alters Quick Solve output for the same input and seed, that is a regression.
2. **One shared core.** Hell Mode calls the same placement, router, electrical check and geometry verifier as Quick Solve. No private copy of geometry rules. If the rules live in two places, they will drift and records will not reproduce.
3. **A result only counts if it is verified.** A layout with fewer wires that fails the electrical check or the geometry verifier is a number, not a record. Reports must separate `RECORD` from `BUILD_READY` (section 8).
4. **Deterministic.** Same input JSON + same seed + same settings = same output, regardless of worker count. Every worker gets its own RNG seeded from `(master_seed, stage, seed_index)`.
5. **Do not edit specs silently.** The 2.5D keepout model (leads / body solids / artwork, z-gate then exact XY distance, provenance-tagged standoff) needs a versioned amendment to `docs/PHYSICAL_MODEL_SPEC.md` before Hell Mode depends on it. Until that lands, Hell Mode uses whatever verifier Quick Solve uses and records the verifier version in the output.

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
Stage 0  Baseline        Quick Solve once -> baseline score to beat
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
- **Plateau stop per candidate:** kill a candidate if there is no improvement in `plateau_moves` (default 50,000 in Stage 3, 10,000 in Stage 2). Reallocate its remaining budget to candidates still improving.
- **Global stop:** whichever comes first of (a) time budget, (b) iteration budget, (c) global plateau (no new best across all workers for `global_plateau_minutes`, default 5), (d) user presses Stop. Stop must always keep and save the best.
- **No target number.** There is no "stop at 25 wires". Optional user target is allowed, but the default is plateau-based.
- The user can **extend** a finished run (continue from the saved state) if the improvement curve was still dropping.

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

If the heavy check rejects a would-be best, discard it, record a `heavy_reject` counter with reason code, and continue from the previous best. Do not let heavy rejects silently bias the search: log them so we can see if the cheap tier is too permissive.

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
- Determinism: results must not depend on which worker ran which seed or on completion order. Sort merged results by `(score_tuple, seed_index)`.
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
| `RECORD` | Lowest score tuple among layouts that pass the electrical check and have no `FAIL_*` geometry verdicts. `CONDITIONAL` allowed, listed. |
| `BUILD_READY` | `RECORD` requirements plus no `CONDITIONAL` verdicts and cut access verified (when a cut-access verifier exists; otherwise flagged `cut_access: unverified`). |

A fewer-wire layout that fails verification is stored under `rejected_candidates` with reasons, never presented as the result.

Run report must state:

- baseline (Quick Solve) score vs final score, e.g. "improved from 38 wires / 48 cuts to X / Y"
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

`run.json` must contain enough to **replay** a result: input hash, settings, master seed, seed index, stage, move count, verifier version.

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

1. **Quick Solve regression:** same output before and after the Hell Mode merge, for `moto.json`, `audio10wires38cuts.json`, `moto14wires30cuts.json`, with fixed seeds.
2. **Determinism:** same seed gives byte-identical `best_solved.json` with 1 worker and with 3 workers.
3. **Incremental vs full:** `--paranoid` run of 200k moves, zero mismatches.
4. **Locks:** locked components never move across 1M random moves.
5. **Move reversibility:** apply move then undo returns the exact prior state (hash compare), for every move type.
6. **Verifier gate:** inject a candidate that has fewer wires but a known geometry failure; it must land in `rejected.json`, not `best_solved.json`.
7. **Halving logic:** with synthetic scores, the right candidates survive each stage and budget is reallocated on plateau.
8. **Diversity:** duplicate candidates are collapsed; `min_distance` relaxes and logs when needed.
9. **Stop and resume:** Stop mid-run keeps the best; resume continues from the checkpoint.
10. **Golden geometry fixtures** (shared with the verifier): G01 to G07, G03a/G03b split, plus boundary cases exactly at and just inside `min_clearance` with a stated floating-point tolerance. Hell Mode must not accept anything these fixtures reject.

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

Ship after each milestone behind a feature flag. Do not start M6 before M4 is stable.

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

Hell Mode is done when, on `moto.json`, a Hell preset run on 3 workers finishes in about 10 minutes or less, produces a layout that passes the electrical check and the geometry verifier, beats the Quick Solve baseline (38 wires / 48 cuts) on the tuple score, saves a replayable `run.json`, and Quick Solve output is unchanged.
