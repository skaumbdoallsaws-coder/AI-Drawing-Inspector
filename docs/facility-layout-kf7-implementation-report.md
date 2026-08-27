# Facility Layout KF7 Implementation Report

Date: 2026-08-26

Status: Complete

## Scope

KF7 extends the existing Facility intelligence evaluator with the knowledge
foundation, trace, and G1 generation contracts. It does not create a parallel
evaluation harness or call a provider during deterministic qualification.

## Qualification Result

`sage_facility_layout_knowledge_foundation_final.json` reports:

- 118 of 118 checks passed;
- 16 of 16 gates passed;
- 71 regression-visible conversation cases retained;
- 20 of 20 new held-out command-family cases passed;
- zero critical failures;
- zero provider or network calls.

The effective deterministic configuration is Anthropic with
`claude-sonnet-4-5-20250929`, sourced from the frozen built-in Facility
default. API credentials are not recorded.

## Evaluated Boundaries

- Canonical command and agent-tool coverage.
- Stage selection and dependency order.
- Coordinate-free intent and deterministic geometry ownership.
- Forbidden action and implicit-save rejection.
- Revision, dirty-state, authorization, invalidation, and receipt handling.
- Run-store restart, expiry, concurrency, and save recovery.
- Ten-strategy and recipe contract parity.
- Stage-context and response budgets.
- Newly held-out paraphrases and existing regression-visible cases.
- G1 production-tool markers and response size.

## Broad Regression Audit

The broad Facility selection produced 739 passing tests, 14 failures, and one
skip before the final KF0 snapshot correction. Thirteen failures exactly match
the frozen KF0 release-evidence quarantine. The remaining failure was a test
that incorrectly expected the live tool registry to remain at the historical
KF0 count of 14 after G1 added one production tool.

The corrected test now preserves both facts: the immutable KF0 crosswalk has
14 tools, while the live post-G1 registry has exactly 15. The corrected KF0
suite passes 6 of 6. No new functional Facility regression remains.

The 13 quarantined items continue to block a legacy full-release claim. They
are stale source-bound captures, elapsed-soak, licensing, and derived release
records; they do not intersect the knowledge-foundation or G1 runtime surface.

## Claim Boundary

This qualification proves deterministic contracts, retrieval, geometry,
receipts, persistence boundaries, and G1 browser behavior. It does not claim
regulatory compliance, production capacity, arbitrary future provider prose
quality, or elapsed-duration soak behavior.

## Exit Gates

- Canonical and enabled-command coverage: PASS.
- Forbidden and unauthorized action rejection: PASS.
- Held-out top-level family accuracy: 100%.
- Stage ordering and stale-chain rejection: PASS.
- Effective provider/model configuration enforcement: PASS.
- Saved reference layout unchanged by evaluation: PASS.
- No unresolved P0 or P1 in the enabled G1 capability: PASS.
