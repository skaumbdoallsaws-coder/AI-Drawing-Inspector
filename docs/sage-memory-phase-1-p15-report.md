# Sage Memory Phase 1 - P1.5 Verification Report

Date: 2026-08-07

## Verdict

P1.5 is complete as an architecture checkpoint. Every memory-enabled Sage turn
now receives a deterministic, authority-separated Memory Envelope. The server
persists a non-secret context manifest before the answer provider runs and
finalizes its revision barrier before the terminal response is released.

## Implemented

- Added the versioned `sage-memory-envelope-1.0` contract and deterministic
  canonical builder.
- Added fixed section allocations and hard total and required-provider budget
  enforcement.
- Added per-provider origin, requester, requirement, inclusion, source ID,
  source revision, token estimate, payload hash, and omission accounting.
- Kept server-origin current state inside trusted observations and rendered
  browser-origin context through a separately labelled untrusted boundary.
- Restricted `approvedSourceDecisions` to explicit structured decisions from
  trusted providers; assistant prose and generic receipts cannot be promoted.
- Added workflow state, bounded receipts, selected skills, capabilities, and
  restrictions to the envelope without giving them application-state authority.
- Added pre-call context-manifest persistence with a reserved manifest ID.
- Added terminal manifest finalization for matched, effect-committed,
  revision-advanced, and CAS-conflict outcomes.
- Added an admin-only, principal-scoped manifest inspection endpoint that does
  not expose raw prompts or provider payloads.
- Added response metadata for envelope schema, provider count, token estimate,
  omissions, manifest ID, and canonical envelope hash.
- Changed required prompt context that cannot fit its budget from a warning to
  a typed fail-closed error.
- Allowed a null continuity summary for an initial turn rather than fabricating
  summary provenance or revision metadata.

## Exit-Gate Evidence

- Identical inputs produce identical canonical bytes and envelope hashes.
- Every included provider records origin, reason, revision metadata, hash, and
  token count; excluded providers record an omission reason.
- Required context that remains over budget receives a typed HTTP 422 before a
  model call.
- Trusted and browser-origin context compile into separate prompt sections.
- A forged browser provider cannot enter `observations.trustedContext`.
- A context-manifest row exists before the answer provider executes.
- The finalized persisted manifest contains the terminal revision-barrier
  outcome and resulting revision-vector hash.
- Secret-like fields and raw image or PDF payloads are rejected and are absent
  from context manifests.
- Retry replay returns the original envelope and manifest identity without a
  second provider invocation.

## Verification

```text
Memory Envelope and turn lifecycle: 10 passed
Server and SQLite integration: 15 passed
Context authority and budget compiler: 8 passed
Prompt compiler regression: 7 passed
Frozen Phase 1 contract suite: 11 passed
Server memory integration rerun: 8 passed
Python compilation: clean
```

Pytest reports the existing workspace cache warning because `.pytest_cache`
cannot create one Windows path that already exists as a file. Test execution is
unaffected.

The local performance targets remain informative until P1.8 pins the reference
workstation fixture required by the plan. They are not used to weaken or expand
the P1.5 exit gate.

## P1.6 Boundary

P1.5 records revisions but does not yet reconcile every scope and dependency
change before envelope construction. P1.6 must run the closed invalidation
dispatcher, revalidate referents and workflow stage, invalidate stale previews
and approval tokens, mark stale evidence references, and expose the resulting
reconciliation event in both the response and context manifest.
