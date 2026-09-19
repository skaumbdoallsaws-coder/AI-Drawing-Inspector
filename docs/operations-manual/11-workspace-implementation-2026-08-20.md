# Operations Manual Workspace Implementation

Date: 2026-08-20  
Implemented state: expanded draft authoring and export workflow  
Review workflow: ready  
Controlled publication: pending recorded manufacturer and compliance approvals  
Draft review output: available as marked PDF and editable DOCX

## Delivered Boundary

InspectorPro hosts Operations and Maintenance Manuals as a document type in the
same Documentation workspace used by Illustrated Parts Manuals. The shared
editor owns the page rail, 16:9 landscape canvas, selection inspector, themes, page
objects, scene commands, undo/redo, CAD viewport, and progressive generation.
Operations-specific code owns evidence, original content blocks, flowing
pagination, figure requests, draft exports, and release policy.

The implemented MMLE-50D draft contains 40 landscape pages generated from
17 content sections:

1. About This Manual;
2. Safety;
3. Product Overview;
4. Specifications;
5. Controls and Indicators;
6. Receiving and Initial Setup;
7. Pre-Use Inspection;
8. Operating Instructions;
9. Moving and Positioning;
10. Charging;
11. Cleaning and Storage;
12. Maintenance;
13. Technical Reference;
14. Troubleshooting;
15. Inspection and Maintenance Records;
16. Service and Parts Support;
17. Sources and Review Status.

The compiler produces a cover, document-control material, a generated table of
contents, long-form prose, compact engineering tables, stepwise procedures,
colored danger/warning/caution/note panels, role boundaries, maintenance and
inspection records, eight scoped CAD technical figures, and a source/review
matrix. The cover plus the eight technical figures are captured at print
resolution in Hidden Lines Removed style.

Safety, charging, maintenance, and troubleshooting content is present for
draft review, visibly marked, and evidence-qualified. The review workflow is
not blocked. Controlled release remains a separate pending approval state until
the prerequisites in the evidence register are complete.

## Runtime Components

| Component | Responsibility |
| --- | --- |
| `ai_inspector/documentation/registry.py` | Shared document-type registry and capability declaration |
| `ai_inspector/operations_manual/evidence.py` | Reviewed source/claim snapshot and release findings |
| `ai_inspector/operations_manual/content.py` | Evidence-aware MMLE-50D draft sections, procedures, tables, notes, and figure definitions |
| `ai_inspector/operations_manual/flow.py` | Deterministic 16:9 landscape flowing text/table pagination with bounds checks |
| `ai_inspector/operations_manual/document.py` | Evidence-backed semantic compiler and revision-bound figure requests |
| `ai_inspector/operations_manual/artifacts.py` | Revision-bound high-resolution PNG capture storage and validation |
| `ai_inspector/operations_manual/exports.py` | Watermarked PDF and editable uncontrolled DOCX generation from one document revision |
| `ai_inspector/parts_manual/documentation.py` | Reused scene commands, presentation overrides, history, theme, page objects, and explicit stale-scene rebaseline |
| `static/index.html` | Blank workspace, page-by-page reveal, landscape rendering, Fit Page/Fit Width modes, editing, thumbnails, live CAD capture, and export UI |
| `server.py` | Public draft, scene, command, render, export, release-gate, and Sage tool contracts |

## Public Application API

```text
GET  /api/documentation/types
GET  /api/operations-manual/{assembly}
POST /api/operations-manual/{assembly}/generate?rebaseline=true
GET  /api/operations-manual/{assembly}/documentation-scene
POST /api/operations-manual/{assembly}/documentation-scene/commands
POST /api/operations-manual/{assembly}/documentation-scene/undo
POST /api/operations-manual/{assembly}/documentation-scene/redo
GET  /api/operations-manual/{assembly}/document
POST /api/operations-manual/{assembly}/document/{pageId}/render
GET  /api/operations-manual/{assembly}/renders/{documentRevision}/{pageId}
POST /api/operations-manual/{assembly}/pdf
GET  /api/operations-manual/{assembly}/pdf/{documentRevision}
GET  /api/operations-manual/{assembly}/docx/{documentRevision}
```

`POST .../pdf` is the draft export orchestration endpoint. It requires all
revision-bound figure captures, then generates both outputs from the same
compiled document model:

- a PDF marked `DRAFT`;
- an editable DOCX marked `DRAFT`.

This endpoint does not bypass the controlled-release gate. Its result explicitly
reports `controlledRelease: false` and carries the unresolved release findings.

## User and Sage Lifecycle

Entering Operations Manual opens a blank 16:9 landscape page and an empty page rail.
The user may choose **Generate Manual**, or Sage may call
`generate_operations_manual_draft`. Both paths use the same application
generator and browser capture implementation:

```text
blank workspace
  -> bind CAD source and reviewed evidence
  -> compile semantic blocks
  -> paginate 16:9 landscape pages
  -> reveal shell/title/illustration/table/rows/annotations
  -> settle each page
  -> capture required HLR figures at print resolution
  -> validate and bind captures to the exact document revision
  -> export review PDF and editable DOCX
```

The Sage tool completes at `review_exported`.
Its receipt includes page
count, accepted/required captures, source/evidence/plan/scene/document revisions,
review status, controlled-release prerequisite count, and application artifact records
for both draft PDF and DOCX artifacts. It never reports a controlled publication.

## Proof

Automated contracts:

```text
tests/test_operations_manual_workspace.py
tests/test_operations_manual_precoding_contracts.py
tests/test_parts_manual.py
tests/test_parts_manual_ui_contract.py
tests/test_documentation_library_assembly.py
tests/test_agent_skill_routing.py
tests/test_agent_skill_runtime.py
tests/test_agent_workflow_state.py
```

The live production-workspace verifier is:

```text
tools/verify_operations_manual_prototype.py
```

It opens the real application on port 8125, invokes the registered Sage tool,
waits for progressive page generation, verifies page and capture counts,
downloads the resulting PDF and DOCX through public artifact endpoints,
rasterizes representative pages, and records browser/API failures. Evidence is
stored under `.runtime/operations_manual_proof/`.

The current proof target is:

- 40 landscape pages;
- 17 semantic sections;
- 9/9 accepted HLR captures (cover plus eight scoped figures);
- at least 4,000 extractable PDF words;
- a valid editable DOCX ZIP package;
- no browser page errors or unexpected HTTP failures.

The flow fixture also exercises at least 60 deterministic text/table pages and
asserts that no content block crosses the landscape content bounds.

## Draft Versus Controlled Release

The expanded draft deliberately unblocks review output without weakening
the controlled-document contract. Draft outputs are suitable for product
demonstration and content/layout review. They are not approved operating
instructions and must not be used in the field.

Controlled release still requires:

- named engineering, safety, product, publications, quality, accessibility,
  and legal approvals;
- licensed standards editions and approved safety-symbol assets;
- exact modeled-configuration/effectivity evidence;
- traceable CAD mappings for advertised safety bars, maintenance isolator, and
  emergency relief valve;
- approval of operating, charging, parking, isolation, inspection, maintenance,
  troubleshooting, and service content;
- final accessibility, font-embedding, PDF-library licensing, and long-manual
  memory qualification.

Those findings remain first-class release-gate records. The draft path does
not remove, downgrade, or silently bypass them.
