# Operations Manual System Contract

## 1. Architectural Decision

Use one CAD-grounded **Documentation Workspace** with a document-type registry.

```text
Documentation Workspace
  shared page rail, canvas, ribbon, inspector, status bar
  shared selection, transforms, themes, page masters, undo/redo
  shared CAD scene, capture, artifacts, revision binding

DocumentTypeDefinition
  parts_manual
  operations_and_maintenance_manual
  work_instructions
  inspection_sheet
```

Each type supplies its own planner, content schema, section recipes, default masters, validation policy, and exporters. This avoids separate editors while preventing parts-manual assumptions from becoming universal document behavior.

## 2. Current Code Reuse and Required Separation

| Current area | Reuse | Required change |
| --- | --- | --- |
| `ai_inspector/parts_manual/catalog.py` | Occurrence/definition identity and scoped component data | Move reusable identity types behind a neutral documentation/product-context boundary |
| `parts_manual/documentation.py` | Scene revisions, commands, undo/redo, page elements, themes/templates | Generalize names and add semantic document-block objects; do not clone command history |
| `parts_manual/document.py` | Deterministic compilation and revision hashing pattern | Keep parts-manual compiler; extract common document envelope, then add an operations compiler |
| `parts_manual/artifacts.py` | Revision-bound image/manifest storage and technical capture QA | Generalize artifact types and add procedure/safety/page-region checks |
| `parts_manual/pdf.py` | PDF composition concepts and accepted-artifact consumption | Add a document-type renderer or common renderer primitives; do not force landscape/BOM templates |
| `parts_manual/layout.py` | Fixed-rectangle constants/helpers only | Do not treat it as a flow engine. Build a new deterministic landscape flow/pagination service and reuse only low-level geometry helpers where valid |
| `static/index.html` Documentation UI | Page rail, authoring canvas, activity glow, scene commands, capture, sequential reveal | Generalize renderer from parts-publication pages to semantic content blocks; preserve settled-capture guards |
| Sage parts-manual skill/workflow | Revision discipline, explicit approvals, end-to-end publication pattern | Add a separate operations-manual skill and hard tool policy; no generic "documentation" mutation tool |

The existing page-element text cap, shape list, and parts-manual-specific page masters are insufficient for long operations content. Do not work around that by painting paragraphs into images.

## 3. Document Type Registry

Proposed contract:

```typescript
type DocumentTypeId =
  | "parts_manual"
  | "operations_and_maintenance_manual"
  | "work_instructions"
  | "inspection_sheet";

type DocumentTypeDefinition = {
  id: DocumentTypeId;
  displayName: string;
  planner: string;
  compiler: string;
  validators: string[];
  pageMasters: string[];
  supportedBlockTypes: string[];
  exporters: Array<"pdf" | "docx">;
  sageSkillId: string;
};
```

The workflow selector chooses a document type. The ribbon remains contextual to the selected document and object.

## 4. Core Domain Model

### 4.1 Product configuration

```typescript
type ProductConfiguration = {
  configurationId: string;
  productModel: string;
  assemblyAssetId: string;
  sourceRevision: string;
  serialRange?: { from?: string; to?: string };
  buildDateRange?: { from?: string; to?: string };
  market: string[];
  language: string;
  effectivityStatus: "unknown" | "draft" | "approved";
  approvals: ApprovalReceipt[];
};
```

### 4.2 Source and evidence

```typescript
type SourceRecord = {
  sourceId: string;
  kind: string;
  authority: EvidenceClass;
  title: string;
  url?: string;
  localAssetId?: string;
  sha256?: string;
  versionOrDate?: string;
  accessedAt: string;
  license: string;
  allowedUse: string[];
  forbiddenUse: string[];
};

type EvidenceClaim = {
  claimId: string;
  productConfigurationId: string;
  category: string;
  statement: string;
  structuredValue?: unknown;
  evidenceClass: EvidenceClass;
  sourceIds: string[];
  sourceLocations?: Array<{ sourceId: string; page?: number; anchor?: string }>;
  status:
    | "approved"
    | "approved_for_draft"
    | "review_required"
    | "conflicted"
    | "blocked"
    | "rejected";
  conflictIds: string[];
  approvalIds: string[];
};
```

The generation model receives claim summaries and permitted source snippets, not unrestricted source dumps.

### 4.3 Operations manual plan

```typescript
type OperationsManualPlan = {
  manualId: string;
  documentType: "operations_and_maintenance_manual";
  productConfigurationId: string;
  sourceRevision: string;
  evidenceRevision: string;
  revision: string;
  status: "proposed" | "approved" | "generating" | "review" | "approved_for_publication";
  title: string;
  documentNumber?: string;
  documentRevision?: string;
  sections: OperationsSectionPlan[];
  unresolvedFindings: Finding[];
  approvalIds: string[];
};

type OperationsSectionPlan = {
  sectionId: string;
  recipeId: string;
  title: string;
  audienceRoles: string[];
  requiredClaimIds: string[];
  optionalClaimIds: string[];
  blocks: ContentBlockPlan[];
  figureRequests: FigureRequest[];
  unresolvedFindings: Finding[];
  status: "ready" | "needs_review" | "blocked";
};
```

### 4.4 Semantic content blocks

```typescript
type ContentBlock =
  | HeadingBlock
  | ParagraphBlock
  | ListBlock
  | SafetyMessageBlock
  | ProcedureBlock
  | FigureBlock
  | SpecificationTableBlock
  | MaintenanceTableBlock
  | TroubleshootingTableBlock
  | ChecklistBlock
  | SourceNoteBlock
  | RevisionTableBlock
  | ApprovalTableBlock
  | RecordTableBlock;

type ContentBlockBase = {
  blockId: string;
  blockType: string;
  evidenceClaimIds: string[];
  approvalState: "draft" | "review" | "approved";
  audienceRoles: string[];
  readingOrder: number;
  localStyleOverride?: object;
};
```

LLM output is validated structured content. The LLM does not choose page coordinates, fonts, signal colors, or capture pixels.

### 4.5 Safety message

```typescript
type SafetyMessageBlock = ContentBlockBase & {
  blockType: "safety_message";
  hazardId: string;
  signalWord: "DANGER" | "WARNING" | "CAUTION" | "NOTICE";
  symbolIds: string[];
  hazard: string;
  consequence?: string;
  avoidance: string[];
  role?: string;
  standardReviewId: string;
};
```

The schema requires separate message elements so validation can detect an attractive but incomplete warning.

### 4.6 Flow layout and pagination

Long-form operations content requires a new deterministic layout service in slice 1:

```text
ordered semantic blocks
  -> style-resolved paragraphs/tables/figures
  -> line and row fragments
  -> page-break constraints
  -> 16:9 landscape pages
  -> destinations/TOC/cross-reference map
```

Minimum contract:

- actual line breaking and paragraph reflow at the resolved font metrics;
- widow/orphan limits and `keepWithNext` for headings/captions;
- `keepTogether` with an explicit override when a block cannot fit a page;
- repeated table headers, deterministic row splitting, and continuation labels;
- figure/caption anchoring with fallback to the next page rather than shrinking prose to illegibility;
- footnote/source-note and cross-reference destinations resolved after pagination;
- deterministic tie-breaking and byte-stable layout inputs;
- overflow findings instead of silent clipping or unbounded font shrinking.

The first executable test is a synthetic 60-page text/table document. It must pass before MMLE prose is used to claim a successful vertical slice.

### 4.7 CAD feature traceability for figures

A figure that names, captions, calls out, or illustrates a product feature must carry the feature claim ID and a verified mapping to one or more occurrences in the bound CAD source revision. `needs_review` is insufficient when no target exists: the request is `blocked`. This applies to advertised safety features even when the prose claim itself is current OEM evidence.

For the MMLE prototype, maintenance safety bars, the maintenance isolator, and the emergency relief valve have no approved occurrence mapping. A generically named `BATTERY SWITCH` cannot be silently promoted to the isolator.

## 5. Revision Model

```text
sourceRevision
  CAD/profile/configuration identity

evidenceRevision
  source register + evidence claims + conflicts + approvals

planRevision
  approved sections, recipes, claims, figures, and block plan

documentationSceneRevision
  page/object placement, theme, local text edits, figure/camera overrides

documentRevision
  deterministic hash of all publication inputs

artifactRevision
  accepted captures and exports bound to documentRevision
```

An internal asset revision is not a product or controlled-document revision. Registry value `A` may participate in `sourceRevision` identity only when labeled as internal; it must not populate cover/header/footer `Revision` fields. Controlled revision fields require provenance from an approved product/document-control source or remain omitted/`Not specified` according to the page master.

Any semantic edit changes `planRevision`. Any approved content edit or presentation edit changes `documentRevision`. Previously captured technical pages become stale and must be recaptured.

PDF and DOCX must report the same `documentRevision`. If either output contains externally modified content, it is not a controlled sibling artifact.

## 6. Orchestration State Machine

```text
EMPTY
  -> RESEARCHING
  -> PLAN_PROPOSED
  -> PLAN_APPROVED
  -> GENERATING
  -> REVIEW_REQUIRED
  -> CONTENT_APPROVED
  -> CAPTURING
  -> VALIDATING
  -> READY_TO_PUBLISH
  -> PUBLISHING
  -> PUBLISHED
```

Failure states preserve the last authoritative revision and specific findings. `PUBLISHED` is reached only after the live publication endpoint returns accepted artifacts.

## 7. Intent and Tool Policy

Classify before exposing tools:

| Intent | Allowed actions | Mutates |
| --- | --- | ---: |
| `inspect_sources` | inspect source/evidence/configuration/findings | No |
| `propose_manual` | build a read-only plan and coverage report | No |
| `approve_plan` | apply explicit candidate approvals atomically | Yes, semantic |
| `generate_draft` | compile approved plan and create baseline pages | Yes, document |
| `edit_content` | edit a named semantic block with evidence checks | Yes, semantic |
| `edit_composition` | move/style figures, blocks, annotations, and page objects | Yes, presentation |
| `capture` | create accepted revision-bound figure/page artifacts | Yes, artifact |
| `validate` | run evidence/content/layout/publication audits | No |
| `publish` | generate controlled PDF/DOCX from current approved revision | Yes, release artifact |

A model in `inspect_sources` or `propose_manual` cannot see publication or mutation tools. `generate_draft` cannot approve unresolved safety claims. `publish` cannot bypass validation.

## 8. Proposed Sage Tool Surface

### Read-only

- `inspect_operations_manual_context`
- `inspect_source_register`
- `inspect_evidence_findings`
- `propose_operations_manual_plan`
- `validate_operations_manual`

### Semantic writes

- `approve_operations_manual_plan`
- `edit_operations_manual_block`
- `resolve_evidence_finding`

These require exact target identity and explicit current-turn authorization. Safety/effectivity resolution also requires the user's authorized role and an approval receipt.

### Presentation and generation

- `generate_operations_manual_draft`
- existing shared Documentation composition commands
- `capture_operations_manual_figure`
- `capture_operations_manual_pages`
- `publish_operations_manual`

### End-to-end command

`generate_and_publish_operations_manual` may exist only as an orchestrator over the same public contracts. It must pause at every required human approval and may return a draft PDF only when release approvals are absent. It cannot contain private repair logic unavailable to the live application.

## 9. End-to-End Operational Plan

For a request such as `Build the MMLE-50D operations manual from the approved source pack`:

1. resolve loaded assembly and configuration;
2. load source/evidence registers and verify hashes/access;
3. audit required evidence by recipe;
4. propose section and figure plan with ready/review/blocked counts;
5. display unresolved conflicts; obtain explicit plan approval;
6. create a blank operations-manual Documentation scene;
7. generate one section/page at a time from approved claims;
8. issue CAD figure requests and wait for accepted captures;
9. compile blocks/tables/figures into the deterministic document;
10. expose the completed draft for user editing;
11. revalidate after every semantic or presentation change;
12. capture stale pages one at a time;
13. run content, safety, figure, layout, accessibility, PDF, and DOCX audits;
14. publish controlled PDF and editable DOCX only at the allowed release state;
15. return artifact links, hashes, revisions, coverage, and remaining findings.

Read-only narrowing and evidence retrieval never require repeated user approval. Semantic approvals and release actions do.

## 10. Progressive Generation Contract

Progress is an ephemeral presentation layer over real state transitions.

```typescript
type GenerationPhase =
  | "shell"
  | "planning"
  | "text"
  | "figure_request"
  | "figure_capture"
  | "table_rows"
  | "safety_annotations"
  | "settled";
```

Rules:

- page shells appear sequentially; the next page is inserted only after the current page reaches a terminal state;
- text streams into a temporary view but persists only as a complete validated block;
- table rows reveal in bounded batches, not character-by-character;
- figure phase waits on actual browser render/capture readiness, with timeout and explicit failure;
- Sage activity glow surrounds only the live viewport and is absent from publication surfaces, thumbnails, captures, and exports;
- completed pages do not replay on revisit;
- `prefers-reduced-motion` renders directly to settled state;
- capture functions force a settled render and reject capture during an unresolved generation transaction;
- cancellation leaves prior pages settled and rolls back the current incomplete block/page transaction;
- animation state never enters `documentRevision`.

## 11. Browser/CAD Execution Boundary

Browser responsibilities:

- load stable occurrence/component identity;
- isolate semantic groups/occurrences;
- apply documentation-only transforms and explosions;
- choose approved camera/display style;
- render neutral or HLR technical figures;
- raycast/validate annotation anchors;
- capture high-resolution image and manifest;
- release GPU/bitmap resources after each page.

Server responsibilities:

- source/evidence/plan repositories and revisions;
- structured-content validation;
- deterministic compilation/pagination;
- artifact validation and revision binding;
- PDF and DOCX generation;
- publication policy and receipts.

The server must recompute all metrics possible from the artifact manifest and clearly label geometry facts it can only validate as client-supplied evidence.

## 12. Memory and Capture Discipline

The prior parts-manual work exposed browser memory pressure. Operations manuals add long text and more pages, so V1 must:

- capture one technical page/figure at a time;
- limit concurrency to one WebGL capture and one image encode;
- dispose render targets, cloned materials, ImageBitmaps, canvases, object URLs, and page thumbnails after use;
- virtualize the page rail and lazily render off-screen previews;
- store accepted artifacts outside browser memory;
- resume capture from the first missing/stale page after a process restart;
- record per-page memory before/after, capture duration, and artifact bytes;
- fail gracefully before browser termination when a configured memory budget is exceeded.

`Capture All` is an orchestrated loop, not simultaneous capture.

## 13. PDF/DOCX Compilation

```text
CompiledDocument
  -> PDF renderer -> controlled PDF + manifest + hash
  -> DOCX renderer -> editable working copy + manifest + hash
```

Both exporters consume:

- the same ordered semantic blocks;
- the same approved text;
- the same tables and item identity;
- the same accepted figures;
- the same document metadata and revision;
- format-specific pagination only.

The DOCX may repaginate in Word, so cross-references should use headings/bookmarks rather than hard-coded page text where possible. The controlled PDF remains the page-authoritative release.

## 14. Runtime Versus Test Harness

Every capability needed for a customer pilot belongs in production code:

| Capability | Must exist in live app | Test/proof role |
| --- | ---: | --- |
| source/evidence audit | Yes | assert findings and policy |
| plan completeness/conflict gate | Yes | fixtures exercise failures |
| figure capture and QA | Yes | browser smoke reproduces it |
| memory-bounded capture loop | Yes | benchmark measures it |
| PDF/DOCX compiler | Yes | artifact diff/open tests |
| publication gate | Yes, server-side | bypass tests prove it cannot be skipped |
| repair/reset commands | Yes, public command contracts | tests may call same APIs only |
| `.runtime` scripts | No dependency | evidence collection and regression proof only |

No smoke script may patch the production plan store, substitute hidden metadata, or generate a better artifact than the live workflow can produce.

## 15. Proposed Module Boundaries

```text
ai_inspector/documentation/
  registry.py
  schema.py
  scene.py
  commands.py
  compiler.py
  artifacts.py
  publication.py

ai_inspector/operations_manual/
  schema.py
  sources.py
  evidence.py
  repository.py
  recipes.py
  planner.py
  writer.py
  figures.py
  quality.py
  document.py
  pdf.py
  docx.py

ai_inspector/agent_skills/publish-operations-manual/
ai_inspector/agent_workflows/operations-manual-publication/
```

This is the target dependency direction. It does not require moving the mature parts-manual code before the first operations prototype; adapters can establish the boundary incrementally.
