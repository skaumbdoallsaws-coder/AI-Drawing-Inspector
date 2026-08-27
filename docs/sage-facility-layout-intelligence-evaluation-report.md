# Sage Facility Layout Intelligence - Evaluation Report

Generated: 2026-08-12

## Verdict

The Facility Layout semantic intelligence implementation passes its expanded
frozen deterministic gate, its read-only smoke against the saved 827-placement
facility, and one source-bound real-provider observe-then-synthesize shadow
case. The saved layout remained byte- and revision-identical throughout every
evaluation and provider call.

This is approval for controlled testing of the implemented semantic slice. It
is not a claim that every future natural-language paraphrase, regulatory
question, or production-capacity question is solved.

## Evidence

| Gate | Result | Evidence SHA-256 |
| --- | ---: | --- |
| Frozen deterministic contract | 94/94 checks; 12/12 gates; 71 intent cases | `05c4762f6a95fabeb606ea27f76ccfb5f109bd3c156a79e4b921075293346d43` |
| Saved-layout semantic smoke | 10/10 assertions | `2cf65142bec45a4cdcc896336cc1cddb7a4f4c3fe6185eb415178b18f038b2f3` |
| Real Anthropic provider shadow | 11/11 assertions | `c41e17b2819ca59d7c1781581b78ee52af209b0b913ec6d4e2cc9b6b312ae912` |
| Final changed-surface Python | 162/162 tests | command output |
| Facility browser contracts | 250/250 checks | command output |
| Viewport safety and rich-chat browser contracts | 157/157 checks | command output |
| Final rich-chat browser smoke | 17/17 checks; 0 page errors | `680b636b1cd63525936fa109c192662ff31891d397f0e5cc1e1ea7905a5ec829` |
| Full Facility Python surface | 647 passed, 12 failed, 1 skipped | command output |

Artifacts:

- `runtime_logs/sage_facility_layout_intelligence_evaluation.json`
- `runtime_logs/sage_facility_layout_live_semantic_smoke.json`
- `runtime_logs/sage_facility_layout_provider_shadow.json`
- `runtime_logs/chat_streaming_smoke.json`

Every source binding embedded in the deterministic and provider artifacts was
re-hashed after the final run: 45 bindings, **0 mismatches**. Provider keys were
blank for all deterministic and Python suites; the final bounded provider
shadow made four accounted Anthropic calls after those suites completed.

## Saved Layout

The live smoke used the current saved Facility Layout:

- placements: 827
- authored zones: 45
- parent departments: 6
- floor markings: 50
- routes: 8
- catalog assets: 148
- asset operational-role types: 13

Before and after each semantic smoke and provider request, SHA-256/revision:

`8551e0b324df6dc17413d0ef8b6ad7f3bab438ba8558dc00320149bf7f855aa0`

The bytes, file timestamp, repository revision, and trusted-context revision
all remained unchanged.

Before the final run, the local host performed one explicit canonical-storage
upgrade because the older saved file contained 21 floating-point serialization
residues. Parsed content was unchanged. The exact prior 446,281-byte payload is
preserved as immutable revision
`feac74d38aeb284a3c9067c60abcca9cea53756240ccb937997bb0a95effd3a5`;
the canonical current payload is 446,024 bytes. Repository tests prove
registry-last atomicity, historical revision access, idempotence, and exact
rollback after an injected registry-write failure.

## Real Provider Trace

The shadow prompt compared Assembly Cell A01 and A02 using metrics that are not
present in the bounded default digest. Sage therefore had to request current
authority rather than answer from a placement-count summary.

Observed sequence:

1. Semantic router selected the read-only Facility workflow.
2. Sage called `inspect_facility_semantics` and
   `analyze_facility_spatial`.
3. The server executed both against revision `8551e0b3...`.
4. The tools returned 12,688 and 596 bounded bytes, respectively.
5. Sage returned a structured table bound to the two zone IDs.
6. Both rows reported 62.32 square meters with `derived` area evidence,
   preserved `derived` physical-footprint evidence, and retained authored
   `create_cell_group` provenance while stating that the original strategy
   was not persisted.
7. Required clearance models remained explicitly missing rather than being
   reported as zero or silently substituted.
8. No browser mutation tool was returned.

Provider accounting: one router call plus three answer-provider calls. The
application received one HTTP request.

## Implemented Contract

- Facility hierarchy and semantic types for departments, cells, lines, support
  areas, placements, routes, floor markings, and process relationships.
- Semantic registries for the private asset catalog, Facility commands, and ten
  manufacturing-cell strategies.
- Evidence vocabulary: `authored`, `derived`, `inferred`, and `unknown`.
- Exact polygon/union area, footprint, reserved-area, free-space, contiguous
  region, route, protected-area, edge-clearance, and bounded fit analysis.
- Geometry-derived route topology and crossing analysis independent of stored
  graph components, plus route width and department-access measurements.
- Authored functional sides for machines and cells, with measured service,
  gate, load/unload, and keep-clear access reports that separate missing
  metadata from measured results.
- Layout and pattern provenance, current-layout classification, operator-travel
  comparison, cell-alternative simulation, reusable-module fit, 2D/3D transform
  consistency, and drone-collider clearance analysis.
- Metric fidelity: counts cannot silently substitute for area, density, free
  space, spatial capacity, or production capacity.
- Revision-bound read tools with bounded calls, rounds, and result bytes.
- Provider observe-then-synthesize loop and deterministic table-grounding gate.
- Column-aware evidence and provenance grounding: observed `derived` evidence
  cannot be downgraded to `unknown`, observed `unknown` cannot be upgraded,
  and authored creation commands cannot be omitted from provenance columns.
- One bounded presentation correction; repeated unsupported metrics fail closed.
- Runtime-enforced read-only/preview/commit separation, explicit spatial intent
  taxonomy, exact-move routing, and saved-layout mutation checks.
- Human entity resolution for names such as `Doosan DBC130 II`, `same
  workbench`, current cell modules, selections, and follow-up references.
- Pending-operation continuity so short confirmations such as `yes` resume the
  prior bounded Facility analysis instead of losing conversational scope.
- Read-only Facility clarification remains inside the semantic analysis
  workflow, with preview, move, commit, and viewport tools still excluded;
  unresolved generation remains fail-closed.
- Chat-feedback telemetry stores only bounded rating/linkage aggregates and
  persists no response or correction text in the telemetry database.
- Persisted layout/pattern provenance for newly authored operations; legacy
  provenance is reported as unavailable rather than guessed.

The final server trace contained no `route_needs_clarification` fallback,
semantic-route fallback, feedback-telemetry construction error, traceback, or
application error during the provider and rich-chat smokes.

## Full-Suite Qualification

The full Facility Python run is not globally green: 12 tests fail because old
checked-in release/accessibility/performance artifacts are bound to earlier
source hashes or build identity. The failures are confined to:

- accessibility raw/summary evidence
- P4 renderer evidence
- P5 authoring/product evidence
- P6, P8, and P9 product evidence
- P11 visual/consolidated release evidence
- accelerated-soak real-build identity
- backend and release performance source bindings

No semantic, geometry, provider-loop, repository, product-boundary,
mutation-safety, or current browser-contract test failed. Historical release
evidence was intentionally not
regenerated because doing so would assert that unrelated visual and performance
certification was rerun when it was not.

## Claim Limits

The evaluation does not prove:

- correct tool choice for every possible future paraphrase
- regulatory compliance without loaded, reviewed site policy
- production throughput without cycle time, uptime, staffing, and shift data
- direct Sage execution of UI-only commands that remain fail-closed
- elapsed-duration soak behavior
- broad pilot answer quality beyond the one real-provider shadow case

Those remain pilot-evaluation and future-work surfaces, not hidden passes.
