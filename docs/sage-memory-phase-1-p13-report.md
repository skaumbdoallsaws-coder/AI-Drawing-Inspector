# Sage Memory Phase 1 - P1.3 Verification Report

Date: 2026-08-06

## Verdict

P1.3 is complete as an architecture checkpoint. Conversation turns now have a
durable, idempotent lifecycle that persists pending state before execution,
binds terminal responses to SQLite commit, rejects stale action revisions, and
passes trusted source revisions into existing Builder CAS paths. The browser is
not switched to server-backed conversation IDs by default; that remains P1.7.

## Implemented

- Added durable conversation create, list, restore, and soft-delete endpoints.
- Extended chat requests with conversation, agent-session, client-turn, memory
  schema, request-hash, semantic-target, and action-parameter identity fields.
- Added deterministic request identity validation against server-resolved scope.
- Persisted pending turns before provider or deterministic execution.
- Added read-only, preview, and action/write classification.
- Added in-flight retry attachment, committed-result replay, cancellation, and
  terminal stale-pending recovery without replaying effects.
- Added the frozen pending-turn revision barrier and retained repository CAS as
  the authoritative guard against the final check-to-commit race.
- Bound Process Map and Facility Layout preview tool calls to the exact trusted
  scope and base revision used during planning.
- Added browser-side scope rejection and propagation of the authorized revision
  into Process Map and Facility Layout Builder requests.
- Persisted source/current/result revision vectors, barrier outcomes, route and
  model metadata, receipts, and a lifecycle context manifest.
- Released streaming terminal events only after the canonical turn is committed.
- Kept memory `off` mode on the legacy path without opening the SQLite database.

## Exit-Gate Evidence

- A retry with the same client-turn ID and request hash returns the prior
  canonical result without provider or tool re-execution.
- Reusing a client-turn ID for a different request returns 409.
- Preview/action drift before execution returns
  `revision_advanced_during_turn` with no released tool bundle.
- Builder receives the server-authorized base revision, so a later race is
  rejected by existing CAS rather than trusted browser state.
- A successful effect receipt is committed even if unrelated state advances
  afterward, preventing a false failure and duplicate retry.
- Interrupted/cancelled and orphaned pending turns become terminal without
  silently replaying an action.
- Restored conversation history contains only committed user/assistant messages.
- Raw image data and provider secrets are not persisted in lifecycle metadata.

## Verification

```text
P1.3 lifecycle and server suites: 10 passed
Process Map editor: 83/83 passed
Facility Layout app: 5/5 passed
Chat frontend contract: 13/13 passed
Inline browser scripts: 4/4 syntax-clean
Python compilation: clean
git diff --check: clean (existing server.py CRLF conversion warning only)
```

Pytest reports the existing workspace cache warning because `.pytest_cache`
cannot create one Windows path that already exists as a file. Test execution is
unaffected.

## P1.4 Boundary

P1.3 intentionally does not decide which committed history is sent to a model.
P1.4 must add the validated structured continuity summary, bounded recent-turn
selection, summary staleness guards, and provider-neutral history projection.
Action turns must fail closed when continuity becomes too stale to summarize.
