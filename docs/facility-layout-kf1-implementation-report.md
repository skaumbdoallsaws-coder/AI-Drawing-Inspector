# Facility Layout Knowledge Foundation KF1 Report

Date: 2026-08-26
Status: Complete

## Scope

KF1 establishes the canonical contracts and durable ownership needed by later
Facility Layout generation phases. It does not enable autonomous layout edits.

Implemented:

- K1 Facility domain ontology;
- K2 Sage responsibility and authority boundary;
- K3 canonical registry for all 39 UI commands and 14 agent tools;
- K4 coordinate-free Facility intent contract;
- K5 stage, substage, invalidation, cumulative proposal, save receipt, and run
  contracts;
- K7 all ten existing cell strategies plus named recipe contracts;
- exact feature-flag and effect-value compatibility;
- bounded canonical registry queries with an 8,192-byte fail-closed limit;
- Facility-scoped provider, model, and reasoning-effort resolution;
- fail-before-provider-call checks against the frozen KF0 configuration and
  live skill compatibility;
- restart-safe generation runs, session mapping, one-writer leases, revision
  compare-and-swap, expiry, tombstones, and saved receipts;
- cross-process locking with a real Windows multiprocessing contention test.

## Runtime Boundaries

- Geometry remains owned by the established planner and operation kernel.
- The model may select semantic commands but may not author coordinates.
- Generated content cannot grant human authority or save implicitly.
- One writable run may hold a layout lease; read-only runs may coexist.
- Final Save requires one explicit approval bound to the exact cumulative diff
  and valid receipt chain.
- Shared Sage environment variables remain compatibility fallbacks only.

## Verification

Focused KF0/KF1 contract and provider suite:

```text
45 passed
```

Broader memory, streaming, Facility integration, and provider suite:

```text
148 passed
```

Full Facility Layout suite:

```text
680 passed, 13 failed, 1 skipped
```

The 13 failures are exactly the release-evidence quarantines recorded in the
KF0 baseline. No new Facility failure was introduced. The affected tests are
static release receipts and product-evidence manifests, not the changed KF1
runtime surface.

Python compilation and `git diff --check` pass for the changed KF1 files.

## Time-Dependent Fixture Correction

One memory reconciliation test stored an absolute expiry of 2026-08-08. On
2026-08-26 the production repository correctly expired it before routing. The
fixture now derives its creation and expiry timestamps from current UTC time;
production expiry behavior was not weakened.

## Exit-Gate Disposition

- Command and agent-tool canonical coverage: pass.
- Deterministic owner uniqueness: pass.
- Valid, invalid, stale, unsupported, oversized, and unknown fixtures: pass.
- Ten-strategy field preservation: pass.
- Feature dependency and effect parity: pass.
- Provider/model/reasoning mismatch before provider call: pass.
- Durable run restart, lease, expiry, recovery, and multiprocessing safety:
  pass.
- Existing saved-layout readability: unchanged.

KF2 may begin against this frozen contract surface.
