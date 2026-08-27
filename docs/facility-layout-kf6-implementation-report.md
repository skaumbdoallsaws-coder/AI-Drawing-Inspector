# Facility Layout KF6 Implementation Report

Date: 2026-08-26

Status: Complete

## Scope

KF6 adds versioned execution traces, newly frozen held-out intent cases, and
bounded stage-specific retrieval to the existing Facility intelligence
evaluation system. The examples teach command meaning and sequencing; they do
not preserve the coordinates of the manually authored reference facility.

## Implemented

- `gold-execution-traces-v1.json` contains 17 generalized traces covering
  positive, negative, correction, and live-modification behavior.
- Trace validation rejects literal world geometry so examples cannot become a
  hidden reference-layout template.
- Each trace binds an intent, stage, deterministic command family, expected
  result, prohibited behavior, and illustrative evidence boundary.
- `held-out-intent-cases-v1.json` contains 20 newly authored cases: 16 for G1
  and four for expanded route, resource, cell, and floor-communication
  capabilities.
- Held-out metadata records authorship, freeze time, version, content hash, and
  the canonical contract revision
  `2e89470341090643fa2242aad0ec8e57f6627ff35c87f799c1daa481957e7415`.
- All 71 established intent cases remain classified as regression-visible and
  are never represented as held out.
- Stage retrieval is revision-bound and fail-closed at 8,192 canonical bytes.
  The largest current trace slice is 3,187 bytes.
- Trace and held-out content hashes are validated before evaluation.
- Synthetic traces carry illustrative authority only and cannot become
  controlled product or safety evidence.

## Evidence Sets

- Gold trace set: `facility-gold-execution-traces-v1`, version 1.0.0.
- Gold trace hash:
  `547d5f97cfbf4f9382d2590aee08d8d92daa72010a8e2b86a4289fd45377db36`.
- Held-out set: `facility-held-out-intent-v1`, version 1.0.0.
- Held-out content hash:
  `03fc56b99fb8135da05d1450ee5b94342b0131e13c0909f4f1b349a29025d083`.

## Verification

- All 20 held-out cases select the expected top-level command family: PASS.
- All ten stage-specific retrieval slices remain below 8,192 bytes: PASS.
- Literal-coordinate, content-hash, overflow, held-out-separation, and
  synthetic-authority negative tests: PASS.
- Evaluation performs zero provider calls.

## Exit Gates

- Examples teach semantics, not final coordinates: PASS.
- Every example has a deterministic expected family and result: PASS.
- Regression-visible and held-out sets remain disjoint: PASS.
- Held-out provenance and hashes are frozen: PASS.
- Retrieval is bounded and revision-bound: PASS.
- Synthetic examples cannot establish production authority: PASS.
