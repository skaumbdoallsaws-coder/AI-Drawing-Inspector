# Facility Layout KF0 Baseline Report

Generated: 2026-08-26T22:22:28Z

## Verdict

KF0 baseline accepted. Current semantic, saved-layout, browser, and agent behavior is green. The historical release evidence remains explicitly blocked and is not being used to claim current release readiness.

## Fresh Results

| Surface | Result |
| --- | --- |
| Deterministic intelligence | 102/102 checks; 12 gates; 71 cases; 0 provider calls |
| Saved reference layout | 10/10 assertions; 827 placements; bytes unchanged |
| Facility browser JavaScript | 250/250 tests |
| Focused agent/provider Python | 85 passed, 0 failed |
| Full Facility Python | 656 passed, 13 quarantined failures, 1 skipped |

## Failure Disposition

All 13 failures have machine-readable dispositions. Ten are stale source-bound captures; the remaining records are licensing, elapsed-soak, and derived release gates. Every quarantine blocks a Facility release claim, but none intersects the KF0 contract/tooling changed surface.

The baseline contains zero unexplained failures. Quarantine details, owners, source hashes, and expiry conditions are in `facility-layout-kf0-baseline-manifest.json`.

## Frozen Surface

- 39 semantic UI commands: 32 ribbon and 7 non-ribbon.
- Effects: 28 draft edits, 8 viewport, 1 read, 1 persistent save, and 1 viewport capture.
- 14 agent tools with one deterministic owner each.
- 7 ordered feature capabilities and dependencies.
- 71 existing evaluation cases classified as regression-visible, never held out.
- 10 generation stages and the G1 bounds/defaults frozen.
- Facility baseline provider/model frozen as Anthropic / `claude-sonnet-4-5-20250929`; no provider calls were made by deterministic baseline runs.

## Artifacts

- `facility-layout-kf0-command-crosswalk.json`
- `facility-layout-kf0-decisions.json`
- `facility-layout-kf0-capability-gaps.json`
- `facility-layout-kf0-baseline-manifest.json`

These are historical baseline records. Later milestones may change source hashes, but must preserve or explicitly migrate the frozen semantic IDs, effects, authority boundaries, and evaluation cases.
