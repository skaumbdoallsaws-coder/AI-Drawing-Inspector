# Facility Layout Circulation Intent Baseline

Date: 2026-08-27

Status: Superseded by the passing G2 implementation; retained as before-state evidence

The implemented result and passing browser proof are recorded in
`docs/facility-layout-g2-circulation-report.md`.

The exact eight baseline prompts were subsequently replayed verbatim. All eight
now pass with one screenshot per prompt and machine-readable grades at
`tests/fixtures/facility_layout/knowledge_foundation/g2-circulation-baseline-replay.json`.

## Scope

This Playwright run exercised eight circulation and route prompts through the
visible Sage composer against a real unsaved G1.1 draft. The draft was a 120 x
90 m facility with eight departments, four authored rows, eight zones, and no
routes.

No production code was changed for this baseline.

## Result

The current route path is not ready for promotion. It does preserve the saved
layout and avoids unrequested geometry, but it does not bind route questions to
the active generated draft.

The central failure is context identity:

- the viewport showed the unsaved eight-zone draft with zero routes;
- generic Facility analysis tools read the saved `fl-main` reference layout;
- Sage therefore discussed departments and routes that were not visible in the
  active draft; and
- build and follow-up route requests attempted the generic preview path, which
  rejected the dirty editor with HTTP 409.

## Prompt Results

| Case | Prompt class | Visible result | Baseline grade |
|---|---|---|---|
| 01 | Complete build | HTTP 409 surfaced as `Save or discard editor changes`; no route created. | FAIL |
| 02 | Follow-up edit | Could not resolve `that aisle`; repeated the HTTP 409 response. | FAIL |
| 03 | Ambiguous build | No geometry was created, but Sage returned a generic preview failure instead of asking what kind, where, and how wide. | PARTIAL |
| 04 | Unsupported fire-code policy | No width was invented and no geometry changed, but the visible answer hid the specific missing-policy explanation. | PARTIAL |
| 05 | Read-only connectivity | Answer described the saved reference factory rather than the visible eight-zone draft. | FAIL |
| 06 | Model-authored coordinates | No geometry changed, but the visible response hid the specific coordinate-authority rejection. | PARTIAL |
| 07 | Hypothetical central aisle | Answer used the saved reference factory and introduced an unsupported 15-25% travel-reduction estimate. | FAIL |
| 08 | Negated request | No route was added, but the options described the saved reference factory. | FAIL |

## Safety And Integrity Checks

- Saved layout unchanged: PASS.
- Visible draft unchanged across all eight route turns: PASS.
- Undo restored the saved base exactly: PASS.
- Page errors: 0.
- Failed network requests: 0.
- Server 5xx responses: 0.
- Expected preview conflicts: two HTTP 409 responses.

The test process returned nonzero because its final strict console assertion
correctly treated those 409 conflicts as baseline failures. The report and all
screenshots were written before that assertion.

## Required Next Work

1. Bind every circulation read, preview, clarification, and follow-up to the
   exact active draft revision shown in the viewport.
2. Add a structured circulation-intent contract covering route purpose,
   traffic class, endpoints, required intermediate areas, width authority,
   direction, crossings, and area-accounting policy.
3. Compile that contract through deterministic aisle and route tools; Sage must
   not author coordinates.
4. Preserve specific clarification and refusal reasons in the visible answer
   instead of replacing them with a generic preview failure.
5. Bind follow-ups such as `make that aisle 5 m` to an immutable proposed-route
   identity and receipt chain.
6. Run read-only connectivity and hypothetical analysis against the same active
   draft revision, and prohibit unsupported benefit estimates.
7. Keep one cumulative unsaved diff; Save must remain a separate explicit
   approval.

## Evidence

- Machine-readable result: `runtime_logs/facility-g2-intent-baseline/result.json`
- Setup screenshot: `runtime_logs/facility-g2-intent-baseline/00-g1-setup-app.png`
- Build request: `runtime_logs/facility-g2-intent-baseline/01-build-app.png`
- Unsupported-policy answer: `runtime_logs/facility-g2-intent-baseline/04-policy-answer.png`
- Wrong-context read-only answer: `runtime_logs/facility-g2-intent-baseline/05-read-only-app.png`
- Wrong-context hypothetical answer: `runtime_logs/facility-g2-intent-baseline/07-hypothetical-answer.png`
- Negated request: `runtime_logs/facility-g2-intent-baseline/08-negated-app.png`
