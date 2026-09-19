# Sage Memory Phase 1 - P1.4 Verification Report

Date: 2026-08-06

## Verdict

P1.4 is complete as an architecture checkpoint. Sage now receives a bounded,
server-owned continuity projection instead of trusting full browser history.
Structured summaries are durable, provenance-bound, incrementally refreshed,
and guarded by explicit soft and hard staleness rules. Action turns fail closed
when continuity cannot be refreshed safely.

## Implemented

- Added the strict `sage-continuity-summary-1.0` schema and validator.
- Required source turn IDs for every retained claim, decision, assumption,
  correction, question, entity, evidence reference, and objective.
- Kept all continuity decisions at `conversation_only` authority.
- Added deterministic complete-turn selection with six-turn and token limits.
- Added durable summary jobs, leases, retries, restart recovery, revision CAS,
  and previous-summary retention on invalid or failed output.
- Added one pinned provider-neutral summary adapter for Anthropic or OpenAI,
  with bounded timeout and no silent provider fallback.
- Added explicit fresh, soft-stale, hard-stale, degraded, and stateless modes.
- Added the bounded synchronous refresh required before soft-stale preview or
  action turns and fail-closed behavior after refresh failure.
- Added optional conservative stateless fallback for independent read-only
  questions; it remains disabled by default.
- Replaced browser-supplied full history in enforce mode with durable recent
  committed turns and a separately delimited untrusted continuity summary.
- Added the 600-token cross-agent projection bound before routing or model use.
- Added continuity mode, staleness, unsummarized counts, and warnings to memory
  response metadata and persisted route metadata.
- Added HTTP mapping for typed continuity failures.

## Exit-Gate Evidence

- A 100-turn fixture exposes the omitted range and sends no more than the
  configured complete-turn history budget.
- A correction to 30 mm supersedes, but does not erase, the prior 32 mm claim.
- Strict validation rejects missing provenance and elevated authority.
- Failed summary generation retains current authoritative application state and
  the last valid summary.
- Twenty unsummarized turns are reported as hard-stale rather than hidden behind
  a six-turn recent window.
- Soft-stale action turns perform one bounded refresh; sustained failure blocks
  routing and tool execution.
- The actual chat endpoint ignores forged browser history, supplies the last six
  durable turns, and injects the validated summary through a separate internal
  context boundary.
- The same bounded role/content sequence is rendered into OpenAI Responses input
  without reintroducing omitted or forged history.
- Oversized cross-agent context receives HTTP 422 before the model is called.
- Historical image payloads are not part of durable recent-history projection.

## Verification

```text
Memory Phase 1 focused regression: 38 passed
Continuity-specific suite: 6 passed
Server memory integration suite: 7 passed
Python compilation: clean
```

Pytest reports the existing workspace cache warning because `.pytest_cache`
cannot create one Windows path that already exists as a file. Test execution is
unaffected.

## P1.5 Boundary

P1.4 controls continuity but does not yet build the complete deterministic
Memory Envelope. P1.5 must merge current trusted provider state, bounded
continuity, selected skill context, workflow state, receipts, capabilities, and
restrictions under explicit authority boundaries. It must persist a canonical
manifest containing hashes and token accounting without raw images or secrets.
