# Documentation map — Route-Mate

**Maintained index (2026-11-21).** Start here rather than treating every historical audit as a current instruction. This index does not amend the locked physical model.

## Authority and reading order

1. [Physical Model Specification](PHYSICAL_MODEL_SPEC.md) — **LOCKED normative rules** for copper, cuts, jumpers, legality and implementation gates. No other document overrides it.
2. [Solver Architecture Decision](SOLVER_ARCHITECTURE_DECISION.md) — approved direction for one engine, Quick Solve and Hell Mode; not a claim of implementation.
3. [Solver Differentiation](SOLVER_DIFFERENTIATION.md) — 2026-11-21 optimisation/search direction; legality before cost.
4. [Collector, PREPARE and pre-solve intelligence](PRE_SOLVE.md) — consolidated terminology, existing data and proposed recon handoff; proposals are not implemented features.
5. [CLI contract](CLI.md) and [GUI design](GUI.md) — intended user interfaces; check source for implemented features.
6. [README](../README.md) — current high-level entry point and run instructions.

## Implementation reference

- [Module I/O and Handoff Audit](MODULE_IO_AND_HANDOFF_AUDIT.md) — sidecar schema, findings and stage handoff; **historical audit with appended progress**, not a current live-code inventory.
- [Gate 1 Handoff](GATE1_HANDOFF.md) — **historical branch/commit/test snapshot** dated 2026-11-19. Verify HEAD and tests; do not treat its historical test counts as current.
- [Gate 0 Audit](GATE_0_AUDIT.md) — historical audit and migration constraints.
- [Quick Fit acceptance](QUICK_FIT_TEST.md) and [Quick Solve routing](QUICK_SOLVE_ROUTING.md) — baseline and legacy limitations, not physical approval.
- [Stripboard design research](STRIPBOARD_DESIGN_RESEARCH.md) and [Karl upstream port](KARL_UPSTREAM_PORT.md) — research/provenance, subordinate to the physical specification.
- [Data inventory](route_mate_data_inventory.md) — fixture snapshot; check current project files before quoting counts.

## Display and operations

- [Production renderer](PRODUCTION_RENDERER.md), [Rendering package](../render/README.md), [GUI](GUI.md).
- [Standalone macOS](STANDALONE_MACOS.md) and [iMac terminal notes](IMAC_TERMINAL.md).

## Working rules and legal

- [Assistant working rules](../ASSISTANT_RULES.md) and [Nick's rules](../NICKS_RULES.md).
- [GPL-3.0](../licenses/GPL-3.0.txt) and Karl attribution in the [README](../README.md).

## Reconciliation rules

- **Design requirement ≠ implemented feature.** Read current code and tests for current status.
- **Electrical PASS ≠ physical buildability PASS.**
- **PRE-SOLVE** is existing project terminology around preparation before solving; it is **not** an authorised new top-level pipeline stage. The established stages are **IN → PREPARE → SOLVE → DISPLAY**.
- The **run-state sidecar** is the existing `<project>.routemate-state.json` contract; do not invent a competing intelligence file.
- Historical snapshots are retained for provenance, not duplicated as live requirements.
- The locked physical specification must only be amended explicitly and with a versioned decision.
