# Route-Mate

An independent stripboard placement, routing and optimisation engine.

Route-Mate uses Karl's existing project JSON as an input format, but owns the solver and validation logic. It is not a fork of the existing GUI solver.

## Core principles

- **Hard board constraints:** locked dimensions are absolute limits. A candidate outside the permitted rows or columns is invalid, not merely expensive.
- **Separate optimisation stages:** parse and validate the circuit, place components, route connections, then score and verify the result.
- **Electrical design-rule checks:** electrical faults cannot be traded away for a lower routing score.
- **Reproducible experiments:** every run records its input, configuration, seed, search limits, metrics and result.
- **Interoperable output:** preserve the source JSON model and export layouts in a compatible form wherever the schema permits.

## Planned architecture

1. **Input adapter** — parse Karl-compatible JSON into an internal circuit model; retain unknown source fields for round-trip compatibility.
2. **Board model** — represent copper strips, holes, cuts, component footprints, wires and board boundaries.
3. **Connectivity model** — represent nets and pin-to-net membership independently of physical placement.
4. **Placement engine** — search legal component positions while enforcing hard dimensions and footprint constraints.
5. **Routing engine** — connect pins on the same net while respecting cuts, copper continuity, wire geometry and crossing rules.
6. **Electrical DRC** — detect shorts, unintended net joins, open required pins, polarity errors and other checks supported by the available component metadata.
7. **Scoring and experiments** — configurable optimisation objectives, deterministic seeds, move/iteration limits, batch sweeps and machine-readable result logs.
8. **JSON exporter** — emit compatible project/layout JSON without silently discarding source data.

## Electrical checks

DRC results are classified separately from optimisation scores:

- **Errors:** electrically invalid candidates; reject them.
- **Warnings:** suspicious or potentially unsafe designs; report them and optionally apply a configurable penalty.
- **Advisories:** good-practice suggestions; report without automatically rejecting.

Checks must be evidence-based. For example, an LED current-limiting resistor check needs LED and supply information; capacitor voltage-rating checks need component ratings. If required metadata is absent, report the check as unknown rather than guessing.

## Development milestones

- [ ] Inspect and document the real input JSON schema using a representative project.
- [ ] Build the input adapter and round-trip tests.
- [ ] Implement board geometry and hard-constraint validation.
- [ ] Implement connectivity and electrical net validation.
- [ ] Implement a first legal placement and routing baseline.
- [ ] Add optimisation, deterministic experiments and result reporting.
- [ ] Add compatible JSON export and regression tests.

## Initial reference experiment

The first reference case is the Moto GPS off-board project:

- Input file: `moto_gps_offboard.json`
- Board: 24 rows × 56 columns
- Rows and columns are locked
- Historical target to investigate: 14 wires / 30 cuts

The 14-wire / 30-cut figure is a target for reproduction, not a result currently guaranteed by Route-Mate.

## Development policy

Do not import the legacy solver as the Route-Mate engine. Reuse the JSON format and verified domain knowledge, and implement the board model, hard constraints, optimisation and DRC as independent, testable modules.
