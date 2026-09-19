# Acceptance and Release Gates

## 1. Principle

Publication is a server-enforced state transition, not a UI button outcome. A polished page cannot compensate for unresolved evidence, and a complete evidence record cannot compensate for unreadable figures.

## 2. Hard Publication Failures

Block controlled publication when any condition is true:

- source hash or required source is missing, changed, inaccessible, or unregistered;
- product configuration/effectivity is absent for a release requiring it;
- a factual block has no evidence claim or uses a forbidden evidence class;
- an unresolved conflict affects the section;
- required engineering, safety, technical-publications, or product approval is missing;
- a safety message lacks hazard, consequence where required, avoidance, severity approval, or licensed symbol mapping;
- a procedure lacks prerequisite, role, action sequence, expected result, or hazard coverage;
- operator content contains a qualified-maintenance action;
- required section or figure coverage is incomplete;
- a figure is stale, failed, clipped, too low resolution, contains unrelated geometry/UI, or is bound to another revision;
- TOC, cross-reference, figure/table number, bookmark, or page destination is broken;
- PDF and DOCX are compiled from different semantic revisions;
- a certification, part number, contact, unit, limit, interval, fluid, torque, pressure, or compliance claim is unsupported;
- a generation/reveal phase or Sage activity overlay is visible in an accepted capture;
- PDF/DOCX export fails format validation or cannot be reopened;
- a runtime publication gate can be bypassed by calling a lower-level endpoint.
- a repository source lacks a recorded SHA-256 or its current bytes do not match;
- the active PDF renderer has no approved license-disposition receipt;
- an internal asset revision is emitted as an OEM or controlled-document revision;
- a figure caption/callout names a feature without a verified occurrence mapping in the bound CAD source;
- a required standards edition or safety-symbol asset lacks named review and license approval.

For the MMLE-50D proof of concept, a `draft` PDF/DOCX may be generated while blocker findings remain. It must be marked `DRAFT`, show approval status in document control, and cannot produce an `approved` publication receipt.

## 3. Source and Evidence Tests

### Unit/contract tests

- validate `source-register.json` and `evidence-register.json` against schemas;
- verify unique source/claim/conflict IDs;
- verify local source hashes and reject silent source replacement;
- require non-null SHA-256 for every repository-local `canonicalLocation`;
- require each standard to carry edition-review status and reject `verified_current` without named reviewer/date;
- require each software dependency to carry an exact version and machine-checkable license disposition;
- verify every claim references existing sources/conflicts/approvals;
- verify authority and allowed/forbidden-use policy;
- verify conflict resolution never deletes dissenting source evidence;
- verify current/legacy evidence cannot be merged without an explicit resolution record;
- verify CAD-only evidence cannot satisfy operational-limit or safety-procedure requirements;
- verify unavailable values remain `UNKNOWN` or `Not specified`.

### Prototype acceptance

- 100% of generated factual blocks map to at least one claim;
- 0 blocked/rejected claims appear as executable instructions;
- 0 OEM part-number claims use InspectorPro library IDs;
- `CONFLICT-001`, `002`, `003`, `004`, `007`, `008`, and `009` remain visible release blockers until resolved.

## 4. Plan and Content Tests

- required recipe sections exist exactly once unless a recipe explicitly allows continuation pages;
- every section declares audience, required claims, figures, status, and findings;
- blocked sections render as review findings, not authoritative prose;
- heading hierarchy has no skipped levels and produces deterministic TOC entries;
- numbering for sections, procedures, figures, tables, and cross-references is stable after layout changes;
- each procedure step has one primary action;
- prerequisites precede actions and verification follows them;
- approved terminology is consistent across prose, figures, tables, and parts references;
- unit conversions are deterministic and tolerance/rounding policy is explicit;
- normalized source similarity flags 12 or more consecutive matching words or 80 substantially matching characters;
- no external source contributes more than 25 verbatim words without a rights/quotation approval receipt;
- regeneration with identical inputs is byte-stable at the semantic-document level.

## 5. Safety Tests

- every safety block maps to a hazard/risk record and approval;
- signal-word severity is authored/approved, not LLM-selected;
- safety panel contains hazard, consequence as applicable, and avoidance;
- symbol ID resolves to an approved licensed asset;
- safety-symbol register status is `approved`, has no missing requirements, and every symbol asset hash/license/approval resolves;
- signal word remains legible in color, grayscale, and text extraction;
- color contrast and non-color cues meet WCAG 2.2 Level AA for the workspace/electronic presentation;
- no safety instruction appears after the action that exposes the hazard;
- no site-specific LOTO steps are generated without customer-approved procedure data;
- no CE/compliance mark is rendered without configuration-specific evidence.

## 6. CAD Figure Tests

### Identity and scope

- every target occurrence/group exists in the bound source revision;
- `isolate_scope` and `context_scope` contain at least one manual group or occurrence;
- every named product feature has a claim ID and a verified occurrence mapping; missing mapping is `blocked`, not `needs_review`;
- isolation contains all required and no unrelated visible occurrences;
- documentation transforms do not modify source CAD transforms;
- figure ID, source revision, scope, camera, style, and explosion are in the manifest.

### Render quality

- accepted capture meets requested pixel dimensions and effective placed DPI;
- neutral or HLR style matches the figure request;
- background, UI exclusion, selection exclusion, and activity-glow exclusion pass pixel/DOM checks;
- visible-geometry bounds are inside the requested safe area;
- no component needed by the caption/callouts is clipped or invisible;
- occupancy and ink thresholds are figure-type specific, with an explicit slender-part path;
- hazard overlays and motion arrows remain separate annotation layers;
- figure caption, legend, callout identity, and alt text agree.

### Viewport/output parity

- the editor, stored capture, PDF, and DOCX use the same accepted image/annotation manifest;
- normalized landmark/callout positions differ by no more than the documented tolerance;
- renderers do not recompute callout or overlay geometry independently.

## 7. Progressive Generation and UI Tests

- a new operations manual opens with an empty page rail and blank page surface;
- page creation order matches the approved plan;
- event order is `shell -> planning -> text -> figure_request/capture as needed -> table_rows -> safety_annotations -> settled`;
- a page is never reported complete before all required blocks have settled;
- text stream produces the exact committed block text;
- table reveal never changes row identity/order or final content;
- figure phase waits for actual accepted capture or reports failure;
- completed-page revisit emits no reveal events;
- reduced-motion mode skips animation and reaches identical final DOM/content;
- cancellation rolls back only the current incomplete transaction and leaves prior pages settled;
- capture during generation is refused or forced to the canonical settled render;
- settled capture hash matches capture after generation;
- rail thumbnails display the actual settled pages and update after accepted edits;
- activity glow has `pointer-events: none`, stays aligned, pauses when idle, and never enters thumbnails/captures/exports.

## 8. PDF Acceptance

- opens without repair in at least two independent viewers;
- SHA-256, bytes, page count, document revision, and generation timestamp are recorded;
- title, author/producer policy, subject, keywords, and document identifiers are correct;
- bookmarks and links resolve;
- TOC page references match actual destinations;
- text is selectable/searchable and no hidden stray text exists;
- tables remain vector/text, not screenshots;
- figures meet placed-resolution requirements;
- fonts are embedded or use an approved portable strategy;
- every embedded font file/version/hash/license is registered and glyph coverage passes;
- print at 100% on Letter without clipping;
- reading order, headings, table headers, alt text, language, and metadata pass PDF/UA-2 (`ISO 14289-2:2024`) validation and named accessibility review before a conformance claim is made;
- no blank, duplicate, partially rendered, or stale page exists;
- PyMuPDF/renderer license disposition is approved and receipt-bound before any customer pilot; unresolved AGPL/commercial choice blocks the entry to PDF implementation, not only publication.

## 9. DOCX Acceptance

- generated from the same `documentRevision` and accepted figures as the PDF;
- `python-docx` 1.2.0 (or an approved replacement) is pinned, hash-locked, and has an approved dependency/license receipt before the DOCX track begins;
- package validates as OOXML and opens without repair in supported Microsoft Word and LibreOffice versions;
- named styles, heading outline, lists, tables, captions, cross-references, headers/footers, and section breaks are present;
- core reading order does not depend on fragile floating anchors;
- editable text is real text; figures are replaceable images with captions/alt text;
- the visible uncontrolled-working-copy banner is present;
- custom/core properties include document identity and InspectorPro revision;
- opening and saving in Word does not corrupt the document;
- external edit changes the file hash and invalidates controlled-publication status;
- PDF and DOCX semantic block census is identical, allowing only documented pagination differences.

## 10. Performance and Memory Acceptance

Initial pilot benchmark profile and provisional budgets are based on the independent MMLE recapture evidence: Windows x64/Chromium on the current demo workstation, 12 sequential pages, approximately 64.8 MB stable JS heap, and browser RSS increasing from approximately 750 MB to 1156 MB with decelerating growth. Every run must record OS/build, browser/version, GPU, installed RAM, viewport, source/model hash, and renderer build; missing profile data invalidates the benchmark.

Provisional entry budgets, subject to revision only through an approved benchmark receipt:

- 12-page MMLE run: post-GC JS heap <= 96 MB; browser RSS <= 1.5 GB; no crash/restart;
- final four pages of that run: net RSS growth <= 128 MB and JS-heap slope <= 1 MB/page after warm-up;
- 30-figure stress run: browser RSS <= 2.0 GB, one WebGL capture at a time, recoverable stop before budget breach;
- synthetic 60-page text/table run: post-GC JS heap <= 128 MB, browser RSS <= 1.5 GB, no blank/duplicate page and no page-size collapse;
- after closing the document and forcing the production cleanup path: JS heap returns within 20% of its pre-generation baseline and browser RSS within 25% or 256 MB, whichever allowance is larger.

At minimum:

- one WebGL capture at a time;
- page rail virtualization for long manuals;
- memory returns within the numeric tolerances above after capture batches and document close;
- no monotonic GPU/heap growth across 30 sequential captures;
- failed/restarted capture resumes from the first missing or stale artifact;
- a synthetic 60-page text/table manual completes without page-size collapse;
- a 30-figure capture run completes without browser termination;
- per-page duration, peak heap, GPU-resource count where measurable, artifact size, and retry count are recorded;
- a memory-budget breach produces a recoverable finding rather than a dead browser.

## 11. Sage/Orchestration Acceptance

- intent classification occurs before tool exposure;
- read-only proposal tools cannot mutate scene, plan, or artifacts;
- blocked evidence prevents section completion despite model confidence;
- exact target resolution rejects ambiguity;
- write commands require explicit current-turn authorization and current revision;
- `409` conflict refreshes state and does not blindly replay;
- pending approvals/clarifications survive a short follow-up such as `yes`;
- tool-result-too-large automatically narrows/batches read-only requests;
- no private repair/test tool is required to complete the live workflow;
- end-to-end command reports proposed, approved, generated, captured, validated, and published as distinct states;
- Sage returns actual artifact links/hashes only from successful live publication results.

## 12. Live Production Proof

Before pilot signoff, run the workflow through the production app and store a proof bundle outside the application dependency path:

```text
operations_manual_publication_proof/
  request.json
  source-register.json
  evidence-register.json
  approved-plan.json
  compiled-document.json
  scene.json
  capture-manifests/
  page-images/
  operations-manual.pdf
  operations-manual.docx
  validation-report.json
  publication-receipt.json
  memory-trace.json
  screenshots/
```

The proof harness may observe and assert the live APIs. It may not swap stores, patch evidence, inject hidden captures, relax policy, or produce artifacts through a path unavailable to customers.

## 13. Release Classification

### P0

- unsupported safety/operating claim published;
- wrong product/configuration or stale revision;
- publication gate bypass;
- source CAD mutated by documentation actions;
- PDF/DOCX mismatch in approved content;
- partial/transient render published.

### P1

- missing required section/figure or broken cross-reference;
- unreadable/misidentified technical figure;
- role boundary violation;
- uncontrolled external edit represented as controlled;
- production workflow depends on test-only repair/data.

### P2

- non-blocking layout/readability/accessibility defect;
- inefficient regeneration or recoverable memory issue;
- incomplete evidence display that does not alter publication outcome.

No open P0 or P1 is acceptable for a customer pilot. P2 findings require an explicit disposition.
