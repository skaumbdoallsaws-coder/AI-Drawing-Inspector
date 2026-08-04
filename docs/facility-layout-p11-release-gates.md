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
| `p11-performance-budget.json` | Source-bound browser/backend budgets and named hardware |
| `p11-accessibility-evidence.json` | Source-bound automated audit and manual screen-reader status |
| `p11-visual-manifest.json` | Light/dark artifacts bound to exact frontend source hashes |
| `p11-webgl-offline-evidence.json` | Context recovery, offline, and corrupt-artifact behavior |
| `p11-feature-flag-matrix.json` | Seven planned flags and runtime wiring |
| `p11-maker-checker-evidence.json` | Pilot-mode same-maker rejection and distinct-checker apply |
| `p11-suite-matrix.json` | RBAC, IDOR, tool, stale, replay, WebGL, and accessibility suites |
| `p11-rollback-drill.json` | Byte/revision preservation across rollback states |
| `p11-licensing-inventory.json` | Vendored code, Python inventory, and industrial asset readiness |
| `p11-soak-ledger.json` | Accelerated mechanics plus a projection of the append-only runtime soak ledger |
| `p11-documentation-evidence.json` | Runbook and safety-document hashes |

## Release Interpretation

`evidenceGenerationPassed: true` means the verifier ran and its executable
checks were internally consistent. It does not mean the pilot gate is met.

`releaseGateMet: true` requires all of the following:

- Full performance protocol on named standard and minimum hardware. Each raw
  run must match the declared hardware fingerprint, and its summary is rebuilt
  from raw observations rather than trusted as an independent claim.
- Complete asset loading, runtime, route, spatial, remount, memory, and GPU
  budgets.
- Source-bound keyboard, focus, semantic, announcement, reduced-motion, and
  contrast evidence, plus the manual screen-reader review.
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
- At least `14 * 24 hours` (1,209,600 continuous elapsed seconds) and every
  self-use count in the campaign-metadata-bound soak ledger.
- No severity-one defect, data loss, unapproved write, or stale apply.

### Remount memory interpretation

The 20-remount budget uses the raw, garbage-collected
`performance.memory.usedJSHeapSize` delta from five fresh browser contexts.
There are no discarded remount warmups and no subtraction for V8 executable
code, browser-native caches, or one-time compilation. A result above 10
percent blocks release even when heap diagnostics show that canvases,
WebGL contexts, observers, and render loops are bounded.

The production Facility Layout shell uses a bounded suspend/resume lifecycle
for workflow tab changes and reserves final disposal for permanent teardown.
The raw browser artifact must prove that each suspended state detaches the
workspace DOM and pauses resize observers and animation frames, while retaining
at most one initialized workspace and one leased renderer. Resume must restore
that same workspace without duplicate canvases, observers, listeners, scenes,
or renderer leases. Final disposal must release the renderer and scene
resources. Heap snapshots and lifecycle diagnostics may explain a failure, but
they cannot replace or override the raw release measurement.

## Current Non-Negotiable Blockers

The verifier must report rather than conceal:

- Minimum reference hardware is unresolved.
- The standard-hardware browser run completed the full Section 18.3 protocol
  on 2026-08-04 with a structurally valid, hardware- and source-bound artifact.
  All ten browser budgets passed. The worst of five independent 20-cycle
  suspend/resume sequences measured 9.5711 percent raw JavaScript heap growth
  against the 10-percent limit, with one retained renderer, zero suspended DOM,
  zero active observer targets, and zero pending frames. The 2D plan workload
  recorded no main-thread long tasks after pan and zoom moved to affine layer
  transforms. The backend release microbenchmark passes every required
  deterministic slice. A separate full run is still required on the named
  minimum-hardware profile.
- The seven Facility Layout flags are runtime-wired, default off, and the
  five-stage rollout matrix is exercised through the HTTP boundary.
- The exact eight-artifact light/dark viewport matrix is complete and
  source-bound. Any bound frontend input change invalidates the matrix until
  the screenshots are recaptured.
- The automated browser accessibility audit is source-bound and green; the
  manual screen-reader audit remains pending.
- Industrial assets in the P2 pilot inventory are not public-ready.
- The direct Python dependency inventory is captured, but its machine
  assessment and human legal review remain blocked, including the PyMuPDF
  distribution path. Transitive packaged artifacts still require review.
- The real fourteen-day soak uses
  `.runtime/facility_layout/p11-real-soak-events.json`; generated release JSON
  cannot increment its counts. The campaign genesis binds its start time,
  requirements, and recursive write-capable source identity.

Do not change an evidence file manually to clear a blocker. Change the
underlying implementation or collect the missing measured evidence, then rerun
the verifier.
