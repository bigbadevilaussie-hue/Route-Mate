# Assistant Working Rules — Route-Mate

These are project-specific rules for the assistant contributing to Route-Mate.

## The five project rules

1. **Steal with pride.** Reuse proven algorithms and code when the licence permits. Preserve attribution and comply with licence obligations.
2. **Overengineer for no reason because it's cool.** Explore ambitious and clever approaches. Keep unnecessary complexity inside the engineering, not in the user's workflow.
3. **Fun.** Keep the work engaging. Deliver working experiments instead of endless architecture speeches.
4. **Why? Why not?** Investigate unusual ideas before dismissing them. Explain real technical limits, not personal preference.
5. **Never ever do the easy way.** Prefer the robust, well-engineered solution over a shortcut that creates hidden debt. This does not mean making the interface difficult or adding complexity without benefit.

## Product boundaries

- Karl's Circuit Designer is the circuit-design front end and remains part of the workflow.
- Route-Mate owns physical stripboard placement, cuts, jumper routing, optimisation, verification and construction output.
- Do not turn Route-Mate into a replacement schematic editor or a cosmetic clone of Karl's GUI.
- Build for hobbyists making one-off stripboard projects, across beginner to expert skill levels.
- Keep electrical correctness separate from construction-quality advice.

## Engineering rules

- Physical board dimensions are mandatory hard limits; preferred finished dimensions are optional targets.
- Component locks and edge locks are engine-level constraints, not GUI decorations.
- The independent verifier decides whether a candidate is physically and electrically legal.
- Fairness means fixed, versioned work budgets and seed lists, never time-based search depth.
- CPU cores may reduce latency but must not silently increase optimisation opportunity.
- Use the same solver kernel for native and optional WASM builds; do not maintain a second browser-only algorithm.
- Reproduce results from a recorded manifest.
- Treat all benchmark claims as unproven until the current engine reproduces and verifies them.
- Inspect upstream source and licences before reusing code. Do not assume a licence from a repository name or a previous summary.
- Preserve source files and identifiers; report ambiguity instead of guessing.

## Communication rules

- Be direct, technically precise and honest.
- Separate confirmed decisions from proposals and implementation status.
- Do not claim code, tests, commits or pushes that did not happen.
- Avoid long explanations unless Nick asks for the long version.
- Make progress tangible. Keep it fun.

## Physical routing handoff

- For current physical-routing implementation status, read [docs/GATE1_HANDOFF.md](docs/GATE1_HANDOFF.md) before coding. It records the verified Gate 1 baseline, known limitations, next task and protected areas.
- [docs/PHYSICAL_MODEL_SPEC.md](docs/PHYSICAL_MODEL_SPEC.md) remains LOCKED and is the normative source. The handoff is status documentation only; it does not supersede or amend the specification.
- Confirm the live branch, HEAD and working tree before relying on a handoff snapshot. Re-run tests after code changes; never present a user-reported test run as an assistant-run or CI result.
