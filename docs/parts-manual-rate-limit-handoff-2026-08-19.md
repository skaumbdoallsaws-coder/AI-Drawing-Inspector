# Illustrated Parts Manual: Rate-Limit Handoff

**Checkpoint date:** 2026-08-19  
**Scope:** InspectorPro Documentation workflow and illustrated parts manual publication  
**Reason for checkpoint:** Browser-memory pressure and approximately 5% of the weekly coding-agent allowance remaining

**Current status:** The interrupted plan was completed and verified on 2026-08-24. See Section 13 for the final evidence. Sections 4-12 are retained as the historical checkpoint.

## 1. Purpose

This document records:

- the product work completed before the rate-limit checkpoint;
- the validation work that was interrupted or remains unproven;
- the distinction between product behavior and development-only proof tooling;
- the safe demo position;
- the implementation sequence to resume after the allowance resets.

Do not interpret this document as a claim that every listed verification has passed. Each item is labeled as completed, partially verified, interrupted, or planned.

## 2. Current Product Baseline

The Documentation workflow currently supports a CAD-grounded illustrated parts manual pipeline:

```text
loaded CAD assembly
  -> occurrence catalog
  -> semantic manual plan
  -> approved manual sections
  -> compiled document
  -> Documentation workspace
  -> technical page captures
  -> server-side artifact and callout QA
  -> publication-gated PDF
```

Important state boundaries remain in place:

- CAD occurrence identity and source geometry;
- manual-plan semantics and section membership;
- Documentation-scene presentation overrides;
- revision-bound captures and compiled document artifacts.

Documentation edits are presentation-only. They must not mutate source CAD geometry.

## 3. Completed Product Work

### 3.1 Manual planning and publication foundation

The implemented workflow includes:

- semantic manual groups and hierarchy;
- component coverage auditing;
- invalid/internal publication-name rejection;
- scoped BOM generation from component definitions and occurrences;
- stable item-to-callout relationships;
- HLR technical illustration output;
- revision-bound render artifacts;
- stale-capture rejection;
- server-side publication gates;
- deterministic PDF composition;
- Documentation-scene overrides with undo/redo support.

### 3.2 Callout and routing quality work

The following routing improvements were implemented before this checkpoint:

- callout feasibility and presentation scoring were separated;
- balloon clearance and route congestion were improved;
- visible component anchors are derived from raycast-backed projected geometry;
- silhouette-aware anchor selection was added;
- projected outward anchor normals are propagated to render artifacts;
- normal-oriented arrowheads are supported;
- tiny parts retain anchors on their own occurrences;
- repeated-part branch routing is validated;
- a non-monotonic branch-corridor overshoot defect was fixed;
- leader crossings, balloon collisions, frame clipping, and unrelated-geometry intersections are publication checks;
- viewport and PDF rendering consume the same captured callout manifest.

### 3.3 Production defects fixed during proof work

Two previously identified production defects were corrected:

1. A Documentation ribbon entry could leave the production workspace in an uncapturable state.
2. A client/server leader-detour mismatch could cause an otherwise valid capture to fail with HTTP 422.

A later recapture defect was also fixed in:

```text
ai_inspector/parts_manual/artifacts.py
```

`attach_render_artifacts()` had replaced the original image-capture request with the accepted artifact descriptor. Reopening or recapturing then lost framing fields such as axis-constrained occupancy policy, target dimensions, and image constraints. The correction merges the accepted descriptor into the original image request instead of replacing that request.

A focused regression assertion was added to:

```text
tests/test_parts_manual.py::test_parts_manual_http_vertical_slice
```

The targeted regression test passed once after the correction.

### 3.4 Durable pilot tooling promoted into the repository

Development proof should not depend only on ad hoc `.runtime` scripts. Durable entry points were added or promoted under normal repository locations:

```text
tests/smoke_parts_manual_pilot_publication.py
tools/benchmark_parts_manual_figure.py
tools/verify_parts_manual_pilot.py
docs/sage-documentation-workflow-context.md
```

Generated screenshots, manifests, and PDFs may still live under `.runtime`; those are output artifacts, not application dependencies.

## 4. Last Verified Evidence

Before the final interrupted benchmark, the MMLE-50D proof produced:

- 15 PDF pages;
- 12 technical page captures;
- 206 of 206 eligible occurrences covered;
- 100% coverage;
- 86 BOM rows with available engineering part numbers;
- zero reported callout errors in that proof run.

Last known proof artifact:

```text
.runtime/mmle_documentation_proof/MMLE-50D-illustrated-parts-manual.pdf
```

Recorded SHA-256:

```text
85fbe210a547acb186fb485b21d0a8b88a9d509474e146114c783265ff13e36c
```

This artifact predates the final interrupted recapture-policy benchmark. It is useful baseline evidence, but it does not prove the latest code state end to end.

## 5. Interrupted or Unproven Work

### 5.1 Interrupted benchmark

The promoted figure benchmark was being rerun after the `attach_render_artifacts()` recapture-policy correction. It was stopped because of memory pressure and the remaining weekly allowance.

Current status:

```text
Targeted regression test: PASS
Promoted browser benchmark after the fix: INTERRUPTED / NOT VERIFIED
Full live publication after the fix: NOT VERIFIED
```

Do not report the latest recapture correction as fully production-proven until the bounded benchmark and live publication checks complete.

### 5.2 Live-versus-isolated proof gap

Much of the strongest previous publication evidence came through an isolated parts-manual server/harness. The production workspace must still be exercised directly and its output compared against the isolated artifact.

### 5.3 Progressive generation proof gap

Progressive page generation is implemented with these phases:

```text
shell
title
illustration
tableHeader
rows
annotations
settled
```

Capture paths include force-settle handling, but dedicated automated proof remains incomplete. The publication smoke passing with progressive generation active is only indirect evidence.

### 5.4 QA evidence provenance

The server recomputes several metrics from manifest geometry, but it validates rather than independently derives raycast and silhouette evidence supplied by the client. Reporting must separate:

```text
serverRecomputedMetrics
clientValidatedGeometryEvidence
```

Do not label all geometry evidence as server-recomputed.

### 5.5 Slender-component risk

Silhouette sampling uses bounded projected sampling. Very thin diagonal components can fall between fixed sample cells. Adaptive subdivision and a deliberately slender fixture are still required.

## 6. Known Workflow Smoke Failures to Classify

Four workflow smoke checks require proper root-cause analysis:

```text
direct_entry_generates_a_complete_semantic_baseline
documentation_technical_preview_uses_retina_resolution
editor_has_page_rail_landscape_canvas_and_properties
publication_canvas_uses_pdf_page_geometry
```

Each must be classified as exactly one of:

```text
application defect
test defect
environment-specific failure
```

The previous bypass experiment disabled only progressive reveal. It did not bypass the complete routing diff, so it was insufficient to prove that all four failures were unrelated to the latest work.

The retina-resolution test deserves specific review because a hard-coded device-pixel-ratio expectation may be an environment assumption rather than a product requirement.

## 7. Product Versus Development Proof

Customer pilot success must not depend on a developer running hidden repair scripts.

The product must own:

- manual-plan validation;
- coverage enforcement;
- render requirements;
- callout and route validation;
- capture revision binding;
- stale-artifact rejection;
- publication blocking and actionable findings;
- bounded retry or fallback behavior that is needed for normal use.

Repository tests and tools should prove those mechanisms. They must not be the only place where correctness is created.

`.runtime` benchmark and publication-proof scripts are acceptable for development evidence, profiling, fixtures, and generated artifacts. Any correction they perform that a customer needs must be moved into application code or a supported application API before a pilot.

## 8. Safe Demo Position

The broad callout redesign described later should not land immediately before the demo.

For the demo:

- freeze the currently verified build;
- restart the browser and close unnecessary tabs;
- demonstrate normal Documentation authoring and a bounded page-generation flow;
- avoid a fresh full `Capture All` or live publication if memory remains unstable;
- finish with the last verified MMLE-50D PDF;
- do not claim the interrupted benchmark passed.

The current branched repeated-item leader is a valid drafting convention even though it is not the intended long-term default.

## 9. Resume Plan After the Allowance Resets

### Phase 1: Release-proof recovery

1. Start from a clean browser process and record baseline memory.
2. Confirm the application server and MMLE-50D profile load normally.
3. Run the promoted figure benchmark only, with bounded output and no parallel browser workers.
4. Confirm recapture preserves the original image/framing request contract.
5. Publish through the live production Documentation workspace.
6. Compare the production PDF, page manifests, and page pixels against the isolated proof.
7. Record artifact paths, hashes, page counts, capture counts, and QA findings.

Exit condition: one current live production PDF is generated from the latest code without developer-side data substitution or repair.

### Phase 2: Smoke-failure classification

1. Reproduce each of the four named failures independently.
2. Bypass the complete relevant diff, not only progressive reveal.
3. Identify application, test, and environment state for each failure.
4. Correct misleading test names and assertions.
5. Do not weaken a valid product requirement merely to obtain a green check.

Exit condition: every failure is fixed or has a documented, evidence-backed classification.

### Phase 3: Progressive-reveal proof

Add tests for:

- exact phase ordering;
- no replay when revisiting a settled page;
- reduced-motion behavior;
- cancellation at every phase boundary;
- no partial reveal entering a capture artifact;
- identical capture hash during generation versus after forced settlement;
- unchanged document revision and BOM numbering caused solely by animation state;
- bounded duration for small and large synthetic manuals.

Exit condition: progressive generation is both visually demonstrated and mechanically proven capture-safe.

### Phase 4: QA provenance correction

Split artifact reporting into:

```text
serverRecomputedMetrics
clientValidatedGeometryEvidence
```

Server-recomputed examples include balloon spacing, frame clipping, segment crossings, elbow count, and quantities derived from accepted manifest data.

Client-validated examples include raycast identity, silhouette membership, anchor normal derivation, and other evidence that the server cannot independently derive without geometry.

Exit condition: no API response overstates the server trust boundary.

### Phase 5: Adaptive silhouette sampling

1. Add a slender diagonal component fixture.
2. Detect low or zero occupancy from the initial bounded sample.
3. Subdivide only the affected projected region.
4. Keep sampling deterministic and capped.
5. Cache results by page, camera pose, occurrence, and presentation transform where safe.
6. Verify a thin component receives a visible anchor on its own occurrence.

Exit condition: slender geometry passes anchor generation without unbounded GPU or browser work.

### Phase 6: Memory hardening

1. Profile memory per page during generation, capture, and publication.
2. Ensure render targets, image buffers, object URLs, and temporary canvases are released after each page.
3. Prefer sequential page capture and bounded concurrency.
4. Avoid retaining full-resolution decoded images for every page in the live workspace.
5. Add a long-manual soak test with a memory ceiling.
6. Make low-memory failure actionable and recoverable rather than leaving the workspace stranded.

Exit condition: the normal production `Capture All` path completes the MMLE-50D manual without browser termination or one-process-per-page workarounds.

## 10. Post-Demo Callout Redesign

The following product changes are approved in principle for implementation after the demo and release-proof recovery.

### 10.1 Repeated-part default

Automatic generation should use one representative callout for repeated definitions:

```text
calloutType: representative_with_count
representativeCount: scoped BOM quantity
quantityLabel: 2X, 3X, ...
anchors: exactly one validated occurrence anchor
branches: []
```

Requirements:

- one BOM row per repeated definition;
- BOM quantity remains the complete scoped occurrence count;
- representative occurrence selection is deterministic and quality-scored;
- branched leaders remain available only as an explicit user-authored override;
- an invalid explicit branch falls back to representative-with-count with a clear finding;
- group-level and single-instance callouts remain unchanged.

Primary implementation locations include:

```text
static/index.html::_partsManualApplyRepeatedCalloutStrategy
ai_inspector/parts_manual/document.py
ai_inspector/parts_manual/artifacts.py
ai_inspector/parts_manual/pdf.py
tests/test_parts_manual.py
tests/test_parts_manual_callout_quality.py
tests/test_parts_manual_ui_contract.py
tests/smoke_parts_manual_technical_samples.py
```

### 10.2 Leader visual language

Parts-manual defaults:

```text
route: auto_straight_first
termination: dot
repeated strategy: representative_with_count
leader and dot color: black/dark neutral
balloon outline and number: InspectorPro blue
```

Work-instruction defaults may continue to use arrows because arrows communicate direction or action.

### 10.3 Straight-first deterministic routing

The automatic route contract should be:

1. Validate a visible anchor on the intended component or manual group.
2. Search deterministic angular positions around the anchor.
3. Evaluate multiple bounded radii per angle.
4. Reject balloon overlap, leader crossing, unrelated-geometry intersection, BOM intrusion, frame overflow, and invalid anchor identity.
5. Select the best straight free-angle leader.
6. If no straight route is valid, try one orthogonal elbow.
7. Never create more than one elbow automatically.
8. Prefer a consistent visual style across a page; if a dense page needs many elbows, consider an orthogonal page policy rather than a random mixture.

### 10.4 Direct manipulation

Required Documentation interactions:

```text
drag balloon -> free 360-degree movement around a fixed anchor
drag anchor dot -> re-anchor to validated visible geometry on the same occurrence
drag elbow -> edit an orthogonal route
reset -> restore deterministic generated placement
auto route -> intentionally discard route overrides and recompute
```

The leader must intersect the balloon circumference, not its center. Manual edits must remain Documentation-scene overrides and must not be silently overwritten by automatic routing.

### 10.5 Callout redesign QA

Add proof that:

- automatically generated repeated items have zero branches;
- every repeated item has a correct `nX` label;
- manifest representative count equals BOM quantity;
- the representative occurrence belongs to page scope;
- dot endpoints lie on validated target geometry;
- viewport and PDF consume identical route geometry;
- straight routes have no crossings or unrelated-geometry intersections;
- orthogonal fallback uses at most one elbow;
- manual balloon and anchor overrides survive refresh and publication;
- black leaders and dots remain readable in grayscale print output.

## 11. Conservative Execution Rules for the Next Session

Because the previous run experienced memory pressure:

- run focused tests before broad suites;
- run one browser proof at a time;
- avoid parallel Playwright workers for full-resolution capture;
- capture one or two diagnostic figures before publishing the whole manual;
- do not repeatedly regenerate unchanged 2400 x 1800 captures;
- stop and inspect memory growth instead of retrying a failing full run blindly;
- preserve user-authored Documentation overrides unless the user explicitly approves resetting them;
- distinguish a completed code change from a completed live publication proof.

## 12. Next Command Decision

The next session should begin with inspection, not another full publication attempt. Verify the server state and run the smallest promoted benchmark that exercises recapture after `attach_render_artifacts()`.

Only after that benchmark passes should the live production workspace publication and isolated-output comparison run.

## 13. Completion Addendum - 2026-08-24

This addendum supersedes the interrupted status and safe-demo position recorded above. The original checkpoint remains unchanged so that the reason for each follow-up is auditable.

### 13.1 Final product behavior

The post-checkpoint callout redesign is complete:

- automatic routing is straight-first, with at most one orthogonal elbow as fallback;
- exact raycast QA can choose a bounded alternate anchor, balloon position, and route as one placement;
- manual balloon and route overrides remain exact authored geometry and are never silently rerouted;
- repeated definitions default to one representative leader with an `nX` count;
- branches are available only as an explicit user override;
- parts-manual leaders and endpoint dots use dark neutral ink, while balloons retain InspectorPro blue;
- balloon dragging, same-occurrence anchor dragging, route-style changes, reset, and auto-route remain revisioned Documentation-scene edits;
- a command-impact matrix keeps balloon/leader edits annotation-only and applies component movement locally; full exploded-view recomposition is reserved for explicit view, explode, reset, capture, and structural callout operations;
- adaptive silhouette sampling is deterministic and bounded for slender components;
- nested service items such as nuts, races, and spacers are separated before callout routing when their projected geometry is almost enclosed by a larger component;
- server reporting distinguishes `serverRecomputedMetrics` from `clientValidatedGeometryEvidence`;
- progressive page generation is force-settled before capture and is proven not to alter document semantics;
- temporary high-resolution canvases are released after each page, captures run sequentially, and a recoverable 768 MiB browser-heap ceiling is enforced.

### 13.2 Resume-plan disposition

All six planned phases are complete:

1. **Release-proof recovery - COMPLETE.** Figure 6-1 passed the bounded production benchmark, the live MMLE-50D workflow published successfully, and its output was compared with an independently recaptured isolated run.
2. **Smoke-failure classification - COMPLETE.** The four named workflow checks now pass as product requirements; none remains classified as an accepted failure.
3. **Progressive-reveal proof - COMPLETE.** Exact phase ordering, settled revisits, reduced motion, capture settlement, landscape page geometry, page rail behavior, and the complete semantic baseline all pass the browser workflow smoke.
4. **QA provenance correction - COMPLETE.** Manifest-derived metrics and client geometry evidence are reported separately.
5. **Adaptive silhouette sampling - COMPLETE.** The bounded slender fixture passes with no unbounded probe growth.
6. **Memory hardening - COMPLETE.** The live 15-page run captured 12 technical pages sequentially at a peak used JavaScript heap of 109,000,000 bytes (approximately 104 MiB), below the 805,306,368-byte (768 MiB) product ceiling.

### 13.3 Production benchmark

MMLE-50D Figure 6-1 now passes in the live application:

```text
capture attempts: 1
server artifact: ready
callout QA: PASS
render pipeline: 6
total time: 12,919.8 ms
leaders: 10 straight, 0 orthogonal
branches: 0
crossings/intersections/collisions/frame clips: 0
```

Evidence:

```text
.runtime/parts_manual_figure_benchmark/mmle-50d-6-1/report.json
.runtime/parts_manual_figure_benchmark/mmle-50d-6-1/figure-6-1-editor.png
```

The benchmark also proves the nested-service repair for item 10, `Prevailing Torque Hex Nut`: its projected overlap was reduced from 0.9233 to 0 before callout routing.

### 13.4 Live production publication

The normal production workspace at `http://127.0.0.1:8125` completed the MMLE-50D workflow without developer-side repair or data substitution:

```text
eligible occurrence coverage: 100%
document pages: 15
technical captures: 12/12 accepted
capture QA: PASS on every technical page
document revision: fe87af6d3a963f4caada3c2533067d6a6592c186cb876e5de473836e6bb4614e
PDF SHA-256: 72758771a6caf611ff80770494eba44e65cfea1fdc3a73d648b0927b2e028607
PDF bytes: 2,705,265
```

Artifacts:

```text
.runtime/parts_manual_pilot_proof/report.json
.runtime/parts_manual_pilot_proof/mmle-50d-illustrated-parts-manual.pdf
```

No source CAD geometry or persisted assembly transform was changed.

### 13.5 Live-versus-isolated parity

The isolated proof copied only the approved `manual-plan.json` and `documentation-scene.json`, then independently recaptured all 12 technical pages and published all 15 pages. It did not copy captures or compiled documents.

Parity result: `PASS`.

```text
document revision: identical
capture manifest SHA-256 values: identical for 12/12 captures
rendered page pixels: identical for 15/15 pages
rendered page text: identical for 15/15 pages
page count: identical
```

The raw PDF byte streams are not identical because their PDF container serialization differs. This is not a content divergence: page pixels, page text, document revision, and accepted capture manifests are identical.

Isolated PDF SHA-256:

```text
1329ce30d40b1e325dd8ae2fd7b37f4419d06dbeccd957c973fb9149f55cab5f
```

Evidence:

```text
.runtime/parts_manual_isolated_pilot_proof/seeded-inputs.json
.runtime/parts_manual_isolated_pilot_proof/report.json
.runtime/parts_manual_isolated_pilot_proof/mmle-50d-illustrated-parts-manual.pdf
.runtime/parts_manual_pilot_parity/report.json
```

### 13.6 Final verification

```text
inline JavaScript syntax: 4/4 PASS
focused parts-manual tests: 71 PASS
technical sample smoke: PASS
Documentation workflow browser smoke: PASS
balloon/component edit isolation and local undo: PASS with zero figure recompositions
live MMLE-50D pilot publication: PASS
isolated MMLE-50D pilot publication: PASS
live/isolated visual and semantic parity: PASS
```

The development tools now prove behavior that is implemented in the application. They do not repair the manual, bypass publication gates, or supply customer-only capabilities.
