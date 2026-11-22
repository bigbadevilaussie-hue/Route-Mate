# 2.5D source-provenance amendment v1.2 — standard assumptions

**Scope:** One additional physical-source provenance value used by GUI
diagnostics of saved WR layouts and solved-board reports. This augments,
rather than replaces, physical model amendment v1.1. All electrical checks,
occupied pad constraints, locked-board requirements and verified construction
requirements remain authoritative.

## New source value: `assumed_standard`

A component body with `z_min_source: "assumed_standard"` is derived from
collector-generated `standard-through-hole-v1` default geometry stored in
an integrity-bound sidecar. It is not a measured, datasheet-proven or
individual user-declared installation dimension. Both independent 2.5D
implementations shall preserve this source exactly.

When a jumper XY envelope approaches an assumed body:

- If it clears *underneath* nominal standoff (including wire OD and z margin),
  verdict is `CONDITIONAL`, reason `assumed_standoff`.
- If it clears *above* the nominal body, verdict is `CONDITIONAL`,
  reason `assumed_height`.
- If the nominal body appears to obstruct the wire, verdict is
  `FAIL_UNVERIFIED`, reason `assumed_body_conflict`, **not**
  `FAIL_PROVEN`.
- If the wire clears the body in XY, there is no body finding; complete
  physical clearance still cannot be claimed because inputs are assumed.

For existing measured/datasheet/user-declared/default-flush sources, all
v1.1 verdicts and hard conditions are unchanged.

The ordinary hard routing path continues to reject both CONDITIONAL and
FAIL_UNVERIFIED gaps. The optional saved-board diagnostic can display
conditional engineering-estimate clearance, but cannot claim a physical
PASS or remove independent electrical/pad/cut-access checks.

No source string may be rewritten to `user_declared` or `measured` merely
to obtain a better verdict. All reference WR files remain historical tests
rather than hard-coded package exceptions.
