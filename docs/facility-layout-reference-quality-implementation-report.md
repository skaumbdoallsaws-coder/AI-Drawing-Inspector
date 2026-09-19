# Facility Layout Reference-Quality Implementation Report

Date: 2026-08-30

Status: **IMPLEMENTED AS AN UNSAVED PROTOTYPE / NOT RELEASED**

This report records the completed RQ0-RQ8 implementation for deterministic,
reference-quality Facility Layout generation. It does not grant manufacturing,
safety, regulatory, capacity, production, or controlled-release authority.

## Phase Status

| Phase | Result | Implemented outcome |
| --- | --- | --- |
| RQ0 - Freeze The Gold Benchmark And Honest Baseline | Complete | The archived manual reference is characterized as 45 zones, 8 routes, 827 placements, and 50 floor markings. Derived hierarchy, support dependencies, contact classes, source bindings, and unresolved review state are explicit. |
| RQ1 - Facility Program Contract And Lossless Compiler | Complete | A revision-bound, coordinate-free `FacilityProgram` compiles planning intent into an immutable deterministic operation plan. It supports multiple resource and cell families without becoming a second saved-layout source of truth. |
| RQ2 - Factory-Scale Incremental Execution | Complete | Durable stage receipts, restart-safe continuation, dependency-ordered placement batches, cumulative proposal validation, stale-base checks, and exact Undo are implemented. More than 500 placements are split without breaking one draft transaction. |
| RQ3 - Deterministic Industrial Placement Patterns | Complete | Rack banks, machine rows, guarded robot cells, work areas, parking arrays, support attachments, and other reference patterns compile deterministically from semantic parameters. |
| RQ4 - Multiple Cell Families And Repeated Modules | Complete | Multiple seed families and target groups resolve in a deterministic order. Replication preserves family identity and unrelated families remain byte-identical during local changes. |
| RQ5 - Complete Route Network And Floor Communication | Complete | Primary and local circulation, crossings, directional arrows, keep-clear areas, parking boxes, and route/cell/asset anchored markings are generated as separate deterministic stages. |
| RQ6 - Facility Planning Knowledge For Novel Factories | Complete | The MMLE-50D Facility Planning Package binds process, department, route, resource, cell, and floor-communication intent to evidence. Unsupported planning, safety, or regulatory claims remain prototype-only or blocked. |
| RQ7 - Conversational Orchestration And Visual Presentation | Complete | Sage can invoke the trusted package, present one cumulative unsaved draft, control Plan/3D layers, and apply a bounded local resource-batch amendment without replaying unrelated stages. |
| RQ8 - Reference-Quality Evaluation And Promotion | Complete for prototype | Level A exact reconstruction, Level B generalization, browser proof, performance gates, and regression tests pass. Human review and controlled-release gates remain separate and pending. |

## Level A Result

The trusted MMLE-50D package produces one valid unsaved draft with:

| Object | Exact count |
| --- | ---: |
| Macro departments | 6 |
| Total areas | 45 |
| Routes | 8 |
| Placements | 827 |
| Floor markings | 50 |
| Replicated cells | 26 |
| Deterministic stages | 10 |
| Stage receipts before local amendment | 11 |

The live browser run verified:

- the saved layout remained unchanged;
- Plan and 3D used the same authoritative world state;
- Plan layer controls hid and restored all 8 routes without changing draft bytes;
- Plan overview label overlap area was 0;
- 3D fit occupied 66.65% of the limiting viewport dimension;
- exact Undo restored the blank base;
- console errors, page errors, failed requests, and server 5xx responses were all zero.

## Conversational Amendment Proof

The same Sage conversation then requested:

> Reduce the raw material rack batch to 89. Keep every other area, route,
> marking, and resource unchanged. Keep the complete result unsaved.

The product-wired FacilityProgram amendment produced:

| Check | Result |
| --- | --- |
| Target batch | `raw-material-racks` |
| Target quantity | 90 to 89 |
| Total placements | 827 to 826 |
| Amendment receipts | 1 |
| Zones, routes, and markings | Byte-identical |
| Unrelated placements | Byte-identical |
| Saved layout | Unchanged |
| Undo | Exact blank-base restoration |

The original program remains immutable. The amendment is an immutable,
sequence-checked artifact that produces a new effective program revision and
one cumulative draft proposal. Model-authored coordinates are not accepted.

## Level B Result

The held-out deterministic benchmark passed 6 of 6 cases at revision
`623bde7674567ae5824b4ffb1d7e61742b8972d9a633354ffd8366eaf9d62153`:

| Case | Key coverage | Result |
| --- | --- | --- |
| Guard-dense | 180 guarded placements | Pass |
| Zero-guard | 44 placements with no guarding | Pass |
| Over-500 | 600 placements in 2 batches | Pass |
| Loop topology | 4-route loop | Pass |
| Mixed families | Multiple resource and cell families | Pass |
| Infeasible negative | Fails closed with `facility_program_resource_set_unplaceable` | Pass |

Every positive case remained unsaved and restored its exact base with Undo.

## Performance

The frozen reference benchmark uses 20 measured runs after one discarded
warmup on the recorded Windows 11 machine profile:

| Gate | p95 | Limit | Result |
| --- | ---: | ---: | --- |
| First macro preview | 2.8231 ms | 10,000 ms | Pass |
| Full reference generation | 26,878.5015 ms | 90,000 ms | Pass |
| Local resource amendment | 8,456.8434 ms | 10,000 ms | Pass |

The refreshed G7 runtime qualification also passed every numeric budget. Its
observed full-factory p95 was 4,637.965 ms and Undo p95 was 377.665 ms. That
qualification still correctly reports `controlledReleaseGateMet: false`
because the literal 14-day elapsed soak has not been completed against this
unchanged build.

## Verification

Final non-quarantined verification:

- Python: **917 passed, 1 skipped** across 60 isolated Facility modules.
- JavaScript: **261 passed** across 11 app, editor, session, workspace, 3D,
  transport, pattern, recorder, and static-contract suites.
- G7 visual parity: **8 of 8 passed** across desktop/mobile, light/dark, and
  Plan/3D.
- G7 performance and accelerated-soak mechanics: passed; controlled release
  remains blocked as described above.
- Live Playwright generation plus amendment: passed against a fresh server.

The one skipped Python check is the opt-in wall-clock spatial benchmark. The
separate frozen RQ8 and G7 performance qualifications were executed and passed.

The KF0 baseline intentionally quarantines 13 legacy P4-P11 release-evidence
checks whose source hashes predate the current Facility implementation. They
cover old browser captures, accessibility evidence, licensing inventory,
release performance, and elapsed-soak evidence. They were not relabeled as
passes or refreshed by editing hashes; each retains its recorded owner, reason,
and expiry condition in `tools/build_facility_layout_kf0_baseline.py`.

## Evidence

- Browser evidence: `tests/fixtures/facility_layout/reference_quality/browser-evidence.json`
- Browser evidence SHA-256: `279cc62a8845021195914a7689ec0201882c9daeec6134916ebe0f6fc53100ca`
- Local-amendment screenshot: `tests/fixtures/facility_layout/reference_quality/browser/06-mmle-reference-quality-local-amendment.png`
- Performance evidence: `tests/fixtures/facility_layout/reference_quality/performance-evaluation.json`
- Level B evidence: `tests/fixtures/facility_layout/reference_quality/level-b-evaluation.json`
- Reference manifest: `tests/fixtures/facility_layout/reference_quality/reference-manifest-v1.json`
- Review receipt: `tests/fixtures/facility_layout/reference_quality/reference-review-receipt-v1.json`

## Authority Boundary

The named review receipt remains:

- approver: Shadrack, InspectorPro product owner;
- review status: `pending`;
- approval eligible: `true`;
- approval requested: `false`;
- unresolved count: `0`;
- boundary: prototype benchmark reconstruction only.

No model, compiler, test, or benchmark granted human authority automatically.
The generated layout is a validated prototype draft, not a production facility
design or a controlled release.

## Runtime

The verified app is running at `http://127.0.0.1:8141/` from one server worker.
The authoritative blank saved layout remained byte-identical with SHA-256:

`54cee1725b4a2103b00f4b2f98ca66a8e31245383a9291be953968bd10f85a4c`
