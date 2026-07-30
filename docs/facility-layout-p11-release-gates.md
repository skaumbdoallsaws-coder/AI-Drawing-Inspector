# Facility Layout P11 Release Gates

## Evidence Command

```powershell
python tools/verify_facility_layout_p11.py --run-suite-matrix
```

Use `--require-release-ready` in a release pipeline. It returns a non-zero exit
status while any literal or technical release gate remains open.

## Generated Evidence

All generated files live under:

```text
tests/fixtures/facility_layout/release/
```

| Evidence | Purpose |
| --- | --- |
| `p11-release-evidence.json` | Consolidated verdict and blockers |
| `p11-performance-budget.json` | Named-hardware metrics and missing budgets |
| `p11-accessibility-evidence.json` | Static ARIA/CSS contract and manual audit status |
| `p11-visual-manifest.json` | Light/dark artifacts bound to exact frontend source hashes |
| `p11-webgl-offline-evidence.json` | Context recovery, offline, and corrupt-artifact behavior |
| `p11-feature-flag-matrix.json` | Seven planned flags and runtime wiring |
| `p11-maker-checker-evidence.json` | Pilot-mode same-maker rejection and distinct-checker apply |
| `p11-suite-matrix.json` | RBAC, IDOR, tool, stale, replay, WebGL, and accessibility suites |
| `p11-rollback-drill.json` | Byte/revision preservation across rollback states |
| `p11-licensing-inventory.json` | Vendored code and industrial asset readiness |
| `p11-soak-ledger.json` | Accelerated mechanics plus literal elapsed soak |
| `p11-documentation-evidence.json` | Runbook and safety-document hashes |

## Release Interpretation

`evidenceGenerationPassed: true` means the verifier ran and its executable
checks were internally consistent. It does not mean the pilot gate is met.

`releaseGateMet: true` requires all of the following:

- Full performance protocol on named standard and minimum hardware.
- Complete asset loading, runtime, route, spatial, remount, memory, and GPU
  budgets.
- Manual keyboard, screen-reader, and contrast accessibility review.
- Required light/dark screenshot matrix at all named viewports.
- Exact SHA-256 binding to the facility shell, workspace, renderer, session,
  transport, Three.js runtime, and capture protocol that produced the matrix.
- WebGL recovery and offline/corrupt behavioral suites.
- Runtime-wired and exercised feature-flag combinations.
- Complete RBAC, IDOR, tool authorization, stale, exact-diff, replay, and
  receipt suites.
- Pilot mode enabled with `require_distinct_approver=true`, same-maker
  approval rejected before authority transfer, and a distinct checker
  completing the receipt-backed apply through the product host's authenticated
  bearer-principal ingress. Invalid or missing bearer identities return 401,
  startup fails closed without distinct configured identities, and bootstrap
  reports the authenticated principal. The default single-user local demo may
  keep this option disabled only when bound to loopback.
- Data-preserving rollback controlled by the actual flags.
- Cleared redistribution rights for pilot assets and dependency license review.
- Fourteen real elapsed days and every self-use count in the soak ledger.
- No severity-one defect, data loss, unapproved write, or stale apply.

## Current Non-Negotiable Blockers

The verifier must report rather than conceal:

- Minimum reference hardware is unresolved.
- The renderer benchmark now completes five 60-second measured runs per
  renderer/scenario, but it covers the placement layer rather than every
  release layer.
- The seven Facility Layout flags are runtime-wired, default off, and the
  five-stage rollout matrix is exercised through the HTTP boundary.
- The exact eight-artifact light/dark viewport matrix is complete and
  source-bound. Any bound frontend input change invalidates the matrix until
  the screenshots are recaptured.
- Human accessibility audits are pending.
- Industrial assets in the P2 pilot inventory are not public-ready.
- The exact packaged Python dependency set, including PyMuPDF distribution
  terms, still needs distribution review.
- The real fourteen-day soak remains time-bound.

Do not change an evidence file manually to clear a blocker. Change the
underlying implementation or collect the missing measured evidence, then rerun
the verifier.
