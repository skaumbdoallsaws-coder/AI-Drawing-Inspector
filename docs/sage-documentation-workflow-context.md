# InspectorPro Documentation Workflow: Sage Environment and Tool-Orchestration Context

## Purpose

This document is an implementation-grounded context package for an agent that will write Sage's Documentation system prompt. It is **not** the system prompt itself.

The core operating statement is:

> We are working inside the InspectorPro application. Sage does not manipulate files, CAD geometry, or a PDF directly. InspectorPro makes revision-bound API calls and invokes in-app tools to inspect state, build the manual plan, edit the Documentation scene, capture technical illustrations, validate the result, and publish the PDF.

The system prompt must describe Sage as an in-product orchestration agent. It must not describe Sage as a shell agent, a generic browser agent, or an unconstrained CAD automation agent.

## Product Objective

The Documentation workflow turns a loaded CAD assembly into a reviewable and publishable illustrated parts manual:

```text
Loaded CAD assembly
  -> occurrence catalog
  -> evidence-backed manual structure proposal
  -> approved Manual Assembly Hierarchy
  -> deterministic document model
  -> AI baseline in the Documentation Workspace
  -> human/Sage presentation overrides
  -> high-resolution technical page captures
  -> server-side render and callout QA
  -> publication-gated PDF
```

The intended user experience is:

```text
Open assembly
  -> choose Workflows > Documentation
  -> InspectorPro generates or loads the baseline manual
  -> review the proposed functional groups
  -> approve the semantic structure
  -> edit pages in the Documentation Workspace
  -> capture current technical figures
  -> publish the validated PDF
```

The workspace is a CAD-grounded technical authoring environment. It resembles a presentation editor in interaction style, but its figures, components, BOM rows, balloons, leaders, and groups retain engineering identity.

## Runtime Environment

### Application context

Sage runs inside the live InspectorPro web application. The relevant environment contains:

- the currently loaded assembly and its assembly number;
- a browser-resident 3D assembly scene;
- stable component occurrence IDs and definition IDs;
- current selection and active Documentation page;
- the current manual-plan revision;
- the current Documentation-scene revision;
- the current compiled-document revision;
- the InspectorPro API on the same application origin;
- an in-app Documentation Workspace with page rail, canvas, ribbon, inspector, and status bar.

The browser client is responsible for operations that require the live 3D scene, including isolation, exploded presentation, camera framing, Hidden Lines Removed rendering, projected-geometry raycasts, callout routing, and PNG capture.

The server is responsible for semantic state, validation, revision control, persistent command history, deterministic document compilation, render-artifact QA, and PDF composition.

### Technical implementation

The current implementation is primarily located in:

| Layer | Implementation |
| --- | --- |
| Application/API host | `server.py` (FastAPI) |
| Browser workspace and tool executor | `static/index.html` |
| Assembly occurrence catalog and scoped BOM | `ai_inspector/parts_manual/catalog.py` |
| Manual-plan schema | `ai_inspector/parts_manual/schema.py` |
| Manual-plan persistence and atomic mutations | `ai_inspector/parts_manual/repository.py` |
| Evidence-backed group planner | `ai_inspector/parts_manual/planner.py` |
| Publication-plan quality gates | `ai_inspector/parts_manual/quality.py` |
| Documentation scene and command history | `ai_inspector/parts_manual/documentation.py` |
| Deterministic document compiler | `ai_inspector/parts_manual/document.py` |
| Render and callout artifact QA | `ai_inspector/parts_manual/artifacts.py` |
| PDF composition | `ai_inspector/parts_manual/pdf.py` |
| Publication layout contract | `ai_inspector/parts_manual/layout.py` |

### Important environment boundary

Sage is not given unrestricted access to every API or UI command. There are three distinct capability layers:

1. **Sage-exposed tools**: tool calls the model can currently request.
2. **InspectorPro application APIs**: endpoints the browser uses to complete the workflow.
3. **Browser-only scene operations**: rendering and geometry-aware work that must execute against the loaded client-side 3D scene.

A system prompt cannot make an application API callable if no Sage tool wraps it. Missing wrappers must be implemented in orchestration code rather than described as if they already exist.

## Source-of-Truth Model

### 1. CAD assembly and occurrence catalog

The loaded assembly is compiled into an occurrence catalog. Each active component has, where available:

- `occurrenceId`: identity of this exact assembly instance;
- `definitionId`: identity shared by repeated instances of the same part definition;
- `parentOccurrenceId`;
- `kind`: `part` or `subassembly`;
- engineering part number and its source;
- customer-facing description and its source;
- suppression state;
- hierarchy and assembly metadata.

Repeated components share a `definitionId` but have different `occurrenceId` values. BOM quantity is derived from occurrences grouped by definition.

CAD filenames are fallback identity evidence, not trusted engineering part numbers. If a trusted part number is unavailable, the publication data must say `Not specified`; Sage must not fabricate one.

### 2. Manual plan

The manual plan owns product/document semantics:

- functional manual sections and hierarchy;
- section names;
- exact component occurrence membership;
- source classification (`manual`, `cad_hierarchy`, `process_map`, or `inferred`);
- confidence and evidence;
- process-operation references;
- page order and inclusion;
- stable BOM item assignments;
- initial visualization preferences.

The manual plan, not the current rendered image, is the source of truth for which components belong on a page.

### 3. Documentation scene

The Documentation scene owns presentation only:

- figure, group, and component presentation transforms;
- camera and explosion overrides;
- balloon positions;
- leader routing/anchor/end-condition overrides;
- page-element placement and size;
- inserted text, images, and shapes;
- theme and page-master overrides;
- replayable command history and undo/redo cursor.

Documentation transforms never modify source CAD geometry or persisted assembly transforms.

### 4. Compiled document

The deterministic compiler combines:

```text
manual plan
+ occurrence catalog
+ assembly metadata
+ Documentation scene
= document model
```

The document model creates these page types as needed:

- cover;
- document information and revision;
- table of contents;
- complete-assembly/group-index figure;
- manual-section figure and BOM;
- continuation parts-list page for a large BOM;
- part-number index.

### 5. Render artifacts and PDF

The browser captures current technical figures as PNG images plus a structured balloon manifest. The server validates both and binds accepted artifacts to the exact document revision. The PDF renderer consumes the document model and accepted artifacts; it does not rediscover product semantics.

## Revision and Concurrency Contract

Four revisions matter:

| Revision | Meaning |
| --- | --- |
| `sourceRevision` | Current assembly/catalog source state |
| manual-plan `revision` | Current semantic manual hierarchy |
| Documentation-scene `revision` | Current presentation command history |
| `documentRevision` | Hash of the complete compiled publication state |

Every mutation uses optimistic concurrency:

1. Read the current state.
2. Send the current base revision with the requested change.
3. Consume the revision returned by the successful call.
4. Never issue a second write using the previous revision.

A `409` response means the state changed. Sage must refresh, reassess the request against the current state, and retry only when the original user intent remains valid. It must not blindly replay a stale mutation.

Any Documentation command changes the Documentation-scene revision and therefore changes the compiled document revision. Page captures associated with an older document revision are stale for publication. Required technical pages must be captured for the current document revision before PDF generation.

## Manual Planning Workflow

### Stage 1: inspect current state

Read the current manual workspace state:

```http
GET /api/parts-manual/{assembly_number}
```

The response includes:

- assembly identity;
- `sourceRevision`;
- current manual plan and its `revision`;
- selectable active part occurrences;
- `sourceCurrent`;
- publication-readiness audit.

### Stage 2: compile a proposal

Generate an evidence-backed, read-only proposal:

```http
GET /api/parts-manual/{assembly_number}/proposal
```

The planner uses the strongest available evidence in this order:

1. explicit CAD subassembly hierarchy;
2. process-map component/operation relationships when no useful CAD hierarchy exists;
3. metadata/name inference for uncovered components.

Candidate sections include source, confidence, evidence, occurrence membership, conflicts, and status. Candidate statuses include `ready`, `already_authored`, and `conflict`.

Proposal generation does not approve or save groups.

### Stage 3: user review and approval

Approval is a separate, explicit mutation:

```http
POST /api/parts-manual/{assembly_number}/proposals/{proposal_revision}/approve
```

Body:

```json
{
  "baseRevision": "current manual-plan revision",
  "sourceRevision": "current assembly source revision",
  "candidateIds": ["candidate-..."]
}
```

Only conflict-free, ready candidates can be approved. Selected candidates are applied in one validated atomic plan revision.

Sage must not interpret proposal generation as approval. Approval requires a user authorization state or an orchestration policy that explicitly grants it.

### Stage 4: manual corrections

The app can create, update, and remove sections directly:

| Endpoint | Description |
| --- | --- |
| `POST /api/parts-manual/{assembly}/sections` | Create a named section from exact occurrence IDs |
| `PATCH /api/parts-manual/{assembly}/sections/{section_id}` | Update membership, hierarchy, name, inclusion, order, evidence, or visualization |
| `POST /api/parts-manual/{assembly}/sections/{section_id}/delete` | Delete a section using current source and base revisions |
| `GET /api/parts-manual/{assembly}/sections/{section_id}/bom` | Return the deterministic BOM scoped to that section |

These APIs exist in the application but are **not currently exposed as direct Sage tools**.

## Documentation Authoring Workflow

### Stage 1: load the scene and document

```http
GET /api/parts-manual/{assembly_number}/documentation-scene
```

The response includes:

- current scene and revision;
- `canUndo` and `canRedo` state;
- compiled current document;
- valid editable target IDs by page and target type.

Editable target types include:

- `figure`;
- `manual_group`;
- `occurrence`;
- `balloon`;
- `leader`;
- `page_element`;
- `document_object`;
- `document_theme`;
- `selection` for multi-object arrangements.

### Stage 2: issue one presentation command

```http
POST /api/parts-manual/{assembly_number}/documentation-scene/commands
```

Every command carries:

```json
{
  "baseRevision": "current Documentation-scene revision",
  "sourceRevision": "current source revision",
  "manualPlanRevision": "current manual-plan revision",
  "operation": "...",
  "pageId": "page-...",
  "targetType": "...",
  "targetId": "...",
  "actor": "sage"
}
```

The response returns the persisted command, updated scene, updated scene revision, rebuilt document, and refreshed editable targets.

### Supported Documentation-scene operations

| Operation | Purpose |
| --- | --- |
| `translate` | Move a figure, group, occurrence, balloon, leader corridor, page element, or document object |
| `rotate` | Rotate CAD presentation targets or document objects without changing CAD |
| `resize` | Resize publication/page elements or inserted document objects |
| `arrange` | Apply validated align/distribute translations to a multi-object selection |
| `adjust_explode` | Increase or decrease figure explosion spacing |
| `set_view` | Set deterministic figure camera to isometric, front, top, or right |
| `set_anchor` | Set a leader anchor side: center, left, right, top, or bottom |
| `set_end_condition` | Set a leader target marker: arrow, dot, or none |
| `clear_callouts` | Remove the active callout collection for one technical page |
| `add_callout` | Add one definition/group callout and regenerate item numbering/BOM data |
| `remove_callout` | Remove one callout and deterministically renumber the remainder |
| `restore_callouts` | Remove manual callout overrides and restore generated callouts |
| `add_object` | Insert a managed text, image, or shape object |
| `remove_object` | Remove an inserted document object |
| `update_text` | Change text on a supported page element or text object |
| `update_style` | Apply validated local formatting overrides |
| `set_theme` | Apply a complete validated company theme |
| `apply_template` | Apply a validated theme and page-master set |
| `reset` | Reset one target to its generated baseline |
| `reset_page` | Clear presentation overrides for one page |

### Undo and redo

```http
POST /api/parts-manual/{assembly_number}/documentation-scene/undo
POST /api/parts-manual/{assembly_number}/documentation-scene/redo
```

Both require current source, manual-plan, and Documentation-scene revisions. Human and Sage edits share the same command history.

### Callout and BOM behavior

Callouts and BOM rows remain one semantic object chain:

```text
BOM definition/item
  -> all matching component occurrences on the page
  -> validated projected anchor(s)
  -> leader route and branches
  -> one item balloon
```

When a callout is added to a manual-section page:

1. InspectorPro resolves the selected occurrence.
2. It finds its stable `definitionId`.
3. It includes every matching visible occurrence of that definition in page scope.
4. It derives part number, description, and quantity from the scoped BOM.
5. It appends one callout/BOM item.
6. It renumbers all active items sequentially.

Therefore repeated instances remain one BOM row and one item number. The illustration may use branched leaders or a representative-with-count strategy.

Clearing callouts also clears the manual callout-driven table for that page. Publication remains blocked until the required semantic definitions/groups are represented again or generated callouts are restored.

## Current Sage-Exposed Tools

The following three tools are exposed to Sage for this workflow.

### `propose_parts_manual_structure`

**Mutability:** read-only.

**Arguments:** none.

**Use when:** the user asks to suggest, plan, organize, build, or generate the illustrated-parts-manual structure.

**Behavior:**

- verifies a loaded assembly exists;
- opens the Illustrated Parts Manual workspace;
- invokes the read-only proposal API;
- displays the proposal in the app;
- returns summary counts.

**Current tool result:**

```json
{
  "ok": true,
  "readOnly": true,
  "proposalRevision": "...",
  "candidateCount": 3,
  "readyCount": 3,
  "conflictCount": 0,
  "unassignedCount": 0
}
```

**Hard limits:** it does not approve groups, edit CAD, capture pages, or generate a PDF. The current wrapper returns summary counts rather than the complete candidate payload.

### `edit_parts_manual_composition`

**Mutability:** writes Documentation presentation overrides only.

**Use when:** the current user turn explicitly requests a concrete Documentation edit.

**Hard boundary:** it never changes source CAD geometry, assembly identity, manual-group membership, or source BOM identity.

#### Public operations

| Operation | Required intent/arguments |
| --- | --- |
| `translate` | `page`, `target_type`, `target`, `direction`, optional `amount` |
| `rotate` | page and CAD target; optional `axis`; signed `degrees` |
| `align` | page, target type, at least two exact `targets`, `alignment` |
| `distribute` | page, target type, at least three exact `targets`, `distribution` |
| `resize` | page element target plus `width_delta` and/or `height_delta` |
| `adjust_explode` | figure target plus signed `explode_delta` |
| `set_view` | figure target plus `view` (`isometric`, `front`, `top`, or `right`) |
| `set_anchor` | leader target plus `anchor_side` |
| `set_end_condition` | leader target plus `end_condition` (`arrow`, `dot`, or `none`) |
| `clear_callouts` | figure/page target |
| `add_callout` | exact component occurrence or manual-group target |
| `remove_callout` | balloon or leader target |
| `restore_callouts` | figure/page target |
| `reset` | one exact target |
| `reset_page` | figure/page target |
| `undo` | no target required |
| `redo` | no target required |

#### Target resolution

The browser resolves pages by exactly one of:

- page ID;
- figure number, such as `2-1` or `Figure 2-1`;
- exact figure title.

It resolves targets by exact stable ID, visible name, or visible detail text, optionally constrained by `target_type`. Ambiguous or missing targets fail; Sage must not guess.

#### Coordinate behavior

- Figure/group/component movement uses model/camera-plane units.
- Balloon, leader, and page-element movement uses normalized page fractions.
- A default amount of `0.05` is used when omitted.
- Leader translation moves the route corridor along its valid routing axis.
- Presentation rotation defaults to the Y axis when omitted.

#### Tool result

A successful edit returns `ok`, operation, resolved page/target identity, and the new `documentationSceneRevision`. Undo and redo return the new revision as well.

### `generate_and_publish_parts_manual`

**Mutability:** runtime-gated semantic approval, render-artifact writes, and PDF publication. It never changes source CAD geometry.

**Use when:** the current turn explicitly asks to publish/export the PDF or requests the complete end-to-end illustrated-parts-manual result. Plain structure generation remains proposal-only.

**Arguments:**

| Argument | Values | Meaning |
| --- | --- | --- |
| `approval_mode` | `use_approved_structure`, `approve_trusted_ready_candidates` | Preserve the existing publishable structure, or permit tightly gated approval of a complete trusted proposal |
| `layout_mode` | `preserve_current`, `generate_baseline_if_missing` | Preserve authored composition and optionally create missing deterministic baseline presentation |
| `open_pdf` | boolean | Open the immutable published artifact in InspectorPro |

The browser executes one bounded state machine:

```text
inspect current state
  -> preserve a publishable plan or evaluate a proposal
  -> approve only zero-conflict, 100%-coverage, trusted candidates
  -> compile the current Documentation scene
  -> validate plan and callout identity
  -> capture every required HLR figure with bounded retries
  -> re-read and validate current revision-bound artifacts
  -> publish the PDF
  -> optionally open the immutable artifact in InspectorPro
```

Auto-approval stops at `stage: awaiting_review` unless all configured gates pass. It never replaces an existing publishable hierarchy merely because a new proposal is available.

A successful result has `ok: true`, `stage: published`, stage receipts, persisted-change flags, coverage, section and capture counts, plan/callout audits, exact revisions, and a PDF object containing URL, SHA-256, byte size, and page count. This result is the only basis for a Sage publication claim.

## Application APIs Not Yet Exposed as Sage Tools

The InspectorPro application performs the following lower-level operations. Sage does not call these APIs individually; the end-to-end publication tool wraps the required subset as one permissioned workflow:

| Capability | Existing API |
| --- | --- |
| Read complete current manual state | `GET /api/parts-manual/{assembly}` |
| Read full proposal details | `GET /api/parts-manual/{assembly}/proposal` |
| Approve selected proposal candidates | `POST .../proposals/{revision}/approve` |
| Create/update/delete manual sections | section APIs |
| Read a scoped section BOM | section BOM API |
| Read complete Documentation scene | Documentation-scene GET |
| Insert/edit text, images, shapes, themes | generic Documentation command API |
| Upload PNG/JPEG document assets | documentation-assets API |
| List and save company templates | template APIs |
| Compile/read current document model | document GET |
| Capture/upload a technical page | page-render POST, driven by browser scene |
| Publish PDF | PDF POST |
| Retrieve immutable render/PDF artifacts | render/document GET endpoints |

The system prompt must not tell Sage to call these directly. Structure proposal, presentation editing, and complete publication must use the three exposed tools above.

## Assets, Themes, and Templates

### Managed image assets

```http
POST /api/parts-manual/{assembly_number}/documentation-assets
```

Accepted inputs are PNG or JPEG, between 1 byte and 5 MB. Assets are content-addressed by SHA-256 and returned with a managed same-origin URL.

### Document objects

The Documentation scene supports:

- `text`;
- `image`;
- `shape`.

Supported shape types currently include:

- rectangle;
- ellipse;
- arrow;
- revision cloud;
- detail box.

Objects use normalized page frames and retain IDs, source (`user`, `template`, or `sage`), lock state, style reference, and local style overrides.

### Formatting

Validated formatting includes:

- supported font family and size;
- font weight/style/underline;
- text alignment;
- text, fill, and outline colors;
- line width;
- opacity.

### Themes and page masters

The scene contains a company theme with brand colors, typography, table style, annotation colors, and optional managed logo. Page masters assign header/footer behavior to cover, technical, and reference page types.

```http
GET /api/documentation/templates
POST /api/parts-manual/{assembly_number}/documentation-template
```

Template saving is revision-bound and stores theme/page-master state, not assembly-specific CAD composition.

## Technical Illustration Capture

### Why capture runs in the app

The browser has the authoritative live 3D scene and component mapping needed to:

- isolate the exact page occurrences;
- apply the current exploded/presentation transforms;
- choose the publication camera;
- fit visible geometry;
- render Hidden Lines Removed line art;
- raycast visible geometry for callout anchors;
- route leaders around projected component geometry;
- build the balloon proof manifest.

The server cannot replace this with a generic screenshot operation.

### Capture API

```http
POST /api/parts-manual/{assembly_number}/document/{page_id}/render
```

Multipart fields:

- `file`: PNG capture;
- `documentRevision`;
- `manualPlanRevision`;
- `sourceRevision`;
- `balloons`: JSON balloon/callout proof manifest.

The browser normally captures all pages with a `renderRequest`. Non-technical front matter without a `renderRequest` is composed directly by the PDF renderer.

### Render requirements

The current technical render contract requires, per page request:

- PNG output;
- at least 2400 x 1800 pixels;
- white technical background;
- Hidden Lines Removed for technical figures by default;
- no shaded or colored model pixels in HLR output;
- framing/occupancy within the page's requested bounds;
- no clipping;
- current revision binding.

The page's `renderRequest.image` is authoritative for exact occupancy and aspect-ratio requirements. Sage must not substitute a generic quality threshold.

### Callout QA

For technical pages, server validation requires:

- one callout identity for every expected BOM/group-index item;
- correct definition/group occurrence membership;
- a visible geometry anchor established by frontmost camera raycast;
- endpoint located inside the intended projected target bounds;
- exactly one primary anchor;
- bounded orthogonal leader routing;
- visible leader length;
- no leader/leader crossings;
- no unrelated geometry intersections;
- correct repeated-part strategy and quantity;
- group-level anchors for complete-assembly group callouts;
- authored endpoint condition honored.

Failed render or callout QA returns `422` and the artifact is not accepted.

## PDF Publication

### Compile current document

```http
GET /api/parts-manual/{assembly_number}/document
```

This validates the manual plan and returns the current deterministic document model plus any current revision-matching render artifacts.

### Publish

```http
POST /api/parts-manual/{assembly_number}/pdf
```

Body:

```json
{
  "documentRevision": "current document revision",
  "manualPlanRevision": "current manual-plan revision",
  "sourceRevision": "current assembly source revision"
}
```

PDF publication is blocked when:

- the semantic plan is not publishable;
- source, plan, scene, or document revisions are stale;
- a required technical page has no current accepted render;
- render quality failed;
- balloon/BOM mapping is incomplete;
- callout routing/anchor QA failed;
- table of contents or page metadata is inconsistent.

Successful publication returns an immutable artifact descriptor and download URL:

```http
GET /api/parts-manual/{assembly_number}/documents/{document_revision}/pdf
```

Sage must report publication success only after the PDF endpoint returns success. Opening the workspace, generating a proposal, compiling a document, or capturing a page is not equivalent to publishing a PDF.

## Publication Plan Quality Gates

Before document compilation, InspectorPro audits the manual plan. Publication requires:

- 100% of eligible serviceable occurrences assigned or explicitly excluded;
- no unexplained unassigned occurrences;
- no invalid duplicate assignments between unrelated sections;
- customer-facing functional section names;
- no internal, smoke-test, temporary, CAD-file, or generic `body/group` names;
- no ordinary single-part page unless explicitly authorized;
- acceptable functional-group quality;
- valid hierarchy, occurrence identity, item assignments, and visualization values.

The exact audit response is authoritative. Sage must not declare a plan complete from visual appearance or section count alone.

## Action and Permission Policy

### Read-only actions

The following are read-only:

- inspect current state;
- inspect publication readiness;
- generate a structure proposal;
- inspect a scoped BOM;
- inspect the current document/scene;
- explain validation failures;
- recommend presentation changes without applying them.

### Semantic mutations

The following change the manual's product/document semantics and require explicit approval:

- approve proposal candidates;
- create, update, delete, include, or exclude sections;
- change section occurrence membership;
- change stable item assignments;
- change document control intended for release.

### Presentation mutations

Documentation composition edits change publication presentation only. They are allowed only when the current user turn explicitly requests the edit. Generic verbs such as `show`, `use`, `set`, or `make` must not be treated as sufficient authorization unless the complete sentence unambiguously requests a Documentation mutation.

### Publication side effects

Page capture creates revision-bound render artifacts. PDF generation creates a release artifact. The orchestration layer should require an explicit publish instruction or an approved workflow state before invoking PDF generation.

### Runtime enforcement

Safety must not rely only on prompt wording. The orchestrator must enforce:

- tool allowlists by intent;
- read-only versus write mode;
- explicit approval for semantic changes and publication;
- revision checks;
- exact target resolution;
- atomic mutations;
- server-side QA;
- command receipts and failure propagation.

## Failure Handling

### Common failures

| Status/error | Required behavior |
| --- | --- |
| `404` / not found | Report missing assembly, scene, asset, render, or PDF; do not fabricate it |
| `409 parts_manual_revision_conflict` | Refresh manual state and reassess |
| `409 parts_manual_source_conflict` | Stop; the CAD/catalog source changed |
| `409 documentation_scene_revision_conflict` | Reload the scene before another edit |
| `409 documentation_scene_binding_conflict` | Stop; scene is bound to stale source or plan |
| `409 parts_manual_proposal_conflict` | Generate a fresh proposal |
| `422 parts_manual_validation` | Report plan findings and correct the semantic plan |
| `422 documentation_scene_validation` | Correct command parameters/target type |
| `422 parts_manual_render_artifact` | Correct capture, framing, HLR, anchor, or routing defects |
| `422 parts_manual_pdf` | Capture current pages or resolve publication QA findings |

Sage must never continue as though a failed call succeeded. It should preserve the last known authoritative state, report the failed stage, and either re-read/replan or identify the user decision required.

## Evidence Discipline

Use these evidence classes when explaining the workflow:

| Class | Meaning |
| --- | --- |
| `AUTHORED` | User/CAD/process-map/manual-plan data explicitly supplies it |
| `DERIVED` | InspectorPro deterministically calculated it |
| `INFERRED` | Planner or Sage inferred it from names/relationships |
| `UNKNOWN` | Available state does not support it |

Examples:

- exact occurrence membership in an approved section: `AUTHORED`;
- BOM quantity from matching occurrences: `DERIVED`;
- a metadata-only candidate group name: `INFERRED`;
- missing engineering part number: `UNKNOWN`.

Sage should prefer authored and derived evidence. It must state confidence and limitations for inferred groups and must not replace unknown engineering metadata with invented values.

## Current End-to-End Orchestration Sequence

The app-level workflow should follow this sequence:

```text
1. Resolve loaded assembly.
2. GET current manual state.
3. If structure is missing or user requests a new proposal:
     GET proposal.
4. Display candidates and validation state.
5. Wait for explicit approval when semantic changes are required.
6. POST approved candidates or section corrections.
7. GET Documentation scene and compiled document.
8. Apply explicitly requested presentation commands one at a time.
9. After each command, consume the returned revisions/document.
10. Capture every current renderable page in the browser.
11. POST each PNG plus balloon proof manifest.
12. GET current document and confirm all required artifacts are accepted.
13. Confirm publication readiness.
14. POST PDF generation with exact current revisions.
15. Return the artifact URL and concise QA summary.
```

Do not skip directly from proposal to PDF. Do not treat a visual preview as a committed semantic plan. Do not publish stale page captures after an edit.

## Remaining Capability Boundaries

The core end-to-end publication gap is closed by `generate_and_publish_parts_manual`. Its deterministic runtime owns state inspection, guarded approval, compilation, capture, validation, and publication; the model does not reproduce domain logic.

Granular semantic section CRUD, standalone inspection of full candidate payloads, and Sage-authored text/image/theme operations remain intentionally outside the public tool surface. Users perform those review and authoring operations in the Documentation Workspace. Future tools may expose them only with equally narrow contracts and runtime authorization.

## Guidance for the System-Prompt Author

The resulting Sage system prompt should:

- state that Sage works inside InspectorPro;
- state that Sage orchestrates application tools through API-backed calls;
- require inspection before mutation;
- distinguish semantic planning, presentation editing, capture, validation, and publication;
- use only tools actually exposed at runtime;
- require exact page and target resolution;
- preserve revision state between calls;
- require explicit approval for semantic structure and publication;
- treat proposal generation as read-only;
- state that Documentation transforms never alter CAD;
- require deterministic BOM and quantity data;
- require server validation before measurable/publication claims;
- stop on tool failure or stale state;
- never fabricate part numbers, groups, renders, validation results, or PDF URLs;
- report what was completed, what remains, and which revision/artifact proves completion.

The prompt should not:

- instruct Sage to click through arbitrary UI controls;
- expose internal hashes as ordinary user input requirements;
- claim Sage can call unwrapped APIs;
- let Sage approve its own semantic proposal without authorization;
- let Sage publish without current render artifacts and QA;
- conflate moving a Documentation component with moving source CAD;
- treat an on-screen preview as a published document;
- use generic confidence language in place of deterministic validation.

## Expected Completion Response

When the workflow succeeds, Sage should report a concise result such as:

```text
The illustrated parts manual was published from the current assembly, manual-plan,
and Documentation-scene revisions.

Coverage: 100%
Manual sections: 3
Technical page captures: 5/5 passed
Callout/BOM audit: PASS
PDF: [artifact link]

No source CAD geometry was changed.
```

When only a proposal or edit was completed, Sage must say so explicitly and must not imply that a PDF was published.

## Verification References

The implemented workflow is exercised by:

- `tests/test_parts_manual.py`
- `tests/test_parts_manual_ui_contract.py`
- `tests/smoke_parts_manual_planner.py`
- `tests/smoke_parts_manual_documentation_workflow.py`
- `tests/smoke_parts_manual_documentation_workspace.py`
- `tests/smoke_parts_manual_documentation_arrange.py`
- `tests/smoke_parts_manual_documentation_callouts.py`
- `tests/smoke_parts_manual_documentation_branding.py`
- `tests/smoke_parts_manual_technical_samples.py`
- `tests/smoke_parts_manual_publication.py`
- `tests/smoke_parts_manual_sage_publication.py`
- `tests/smoke_parts_manual_pilot_publication.py`

Pilot diagnostics and the release gate are source controlled:

- `tools/benchmark_parts_manual_figure.py`
- `tools/verify_parts_manual_pilot.py`

Run the complete pilot gate while the live app is available on port 8125:

```powershell
python tools\verify_parts_manual_pilot.py --assembly MMLE-50D
```

To diagnose one figure through the real browser capture and server-validation
path:

```powershell
python tools\benchmark_parts_manual_figure.py 3-1 --assembly MMLE-50D
```

The Sage publication proof writes:

- `.runtime/parts_manual_sage_publication_proof/report.json`
- `.runtime/parts_manual_sage_publication_proof/sage_tricycle_illustrated_parts_manual.pdf`
- `.runtime/parts_manual_sage_publication_proof/published_pdf_open_in_inspectorpro.png`

These tests are the implementation-level reference for whether a proposed Sage prompt matches the application's actual behavior.

The scripts under `tests/` and `tools/` do not supply production behavior or
repair publication output. They exercise the same application-owned routing,
visibility repair, capture, QA, and publication gates used by customers. Only
their generated reports, screenshots, and PDFs are written under `.runtime`.
