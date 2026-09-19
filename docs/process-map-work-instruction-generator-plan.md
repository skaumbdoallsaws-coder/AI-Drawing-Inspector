# Process Map Work Instruction Generator

Status: revision 1 - PROPOSED IMPLEMENTATION CONTRACT (2026-07-26).

Planning only. No Work Instruction Generator code exists yet.

This plan defines a revision-bound module that compiles a validated Process Map
and Assembly Knowledge Package into an illustrated assembly work-instruction
draft, presents one complete preview, and publishes only after explicit user
approval.

The reference reviewed while preparing this plan was the 11-page Pelago bicycle
assembly instruction PDF supplied by the user. It is design inspiration only.
InspectorPro must not copy its artwork, text, branding, or exact page layout.

## 1. Product outcome

InspectorPro should be able to answer an explicit request such as:

> Generate illustrated work instructions from this approved process map.

The result should include:

- a cover and revision block;
- a component and quantity list;
- an aggregated tool and resource list;
- ordered assembly steps;
- one or more deterministic CAD-derived illustrations per step;
- parts added during the step;
- inherited assembly context;
- sourced requirements, torque values, and inspection criteria;
- clearly separated notes, cautions, and warnings;
- an end-of-process verification checklist;
- evidence and uncertainty status;
- one reviewable preview;
- one explicit approval before publication; and
- a revisioned PDF and canonical source asset after approval.

This is a compiler from trusted product and process data. It is not a generic
document-writing prompt.

## 2. Reference-manual decomposition

The reviewed Pelago manual uses a compact and effective structure:

1. Cover, scope, index, and manufacturer identity.
2. Labeled component overview.
3. Tool list and unpacking/setup instructions.
4. Numbered operations with isolated or exploded illustrations.
5. Required tools and torque values beside the applicable operation.
6. Orientation, interference, and safety notes.
7. Final setup and functional checks.
8. Completion statement and references to broader owner documentation.

The important lesson is not its visual style. The important lesson is that each
page binds five things:

```text
Process action
+ product state
+ affected components
+ requirements/resources
+ verification or warning
```

InspectorPro already represents most of those concepts. The new module must
compile them into an operator-facing document without weakening their evidence
or revision boundaries.

## 3. Governing principles

### 3.1 Meaning and rendering remain separate

The validated Semantic Process Plan determines:

- which parts are required;
- which operation is performed;
- operation order and parallel branches;
- intermediate and final results;
- tools, requirements, and checks;
- evidence status; and
- unresolved assumptions.

The deterministic illustration engine determines:

- which prepared view to use;
- which occurrences are visible;
- which are direct inputs versus inherited context;
- crop and scale;
- labels and callouts;
- page composition; and
- output image and PDF bytes.

The model must not invent final image coordinates, page coordinates, or
occurrence identities.

### 3.2 A Process Map is necessary but not automatically sufficient

Assembly structure, mates, geometry, proximity, filenames, and a clean Process
Map do not prove every manufacturing fact. In particular, they do not establish
authoritative:

- torque values;
- lubrication requirements;
- adhesives and cure times;
- machine settings;
- fastener specifications;
- insertion or removal paths;
- fixturing;
- tool access;
- safety warnings;
- inspection limits; or
- regulatory statements.

Those values may appear as authoritative only when bound to approved evidence.
Otherwise they must be omitted, marked inferred, or listed as unresolved.

### 3.3 CAD illustrations are deterministic evidence

Manufacturing illustrations must come from prepared CAD presentation assets,
identity masks, or a controlled geometry renderer. Generative image models must
not redraw, modify, or invent product geometry.

### 3.4 The interactive Assembly tab is not the automation interface

Sage and Builder must not generate a manual by switching tabs, clicking
Highlight, moving the camera, or taking browser screenshots one step at a time.

The Assembly tab remains the human review surface. The generator uses
server-side commands over trusted Assembly Knowledge assets. This avoids dirty
state prompts, tab-navigation failures, timing dependence, and hidden UI state.

### 3.5 Preview first, publish once

Generation follows:

```text
Observe saved revisions
-> compile instruction plan
-> validate semantics and evidence
-> render deterministic illustrations
-> compose temporary document
-> validate pages and bindings
-> show one complete preview
-> explicit approval
-> atomic publication
```

No partial instruction asset is published before approval.

### 3.6 The default output is an internal draft

Inferred process steps may be useful in a planning draft. They are not silently
promoted to released work instructions.

The first release supports:

- `internal_draft`;
- `reviewed`; and
- `released`.

Only an authorized user may promote a document. A released revision is
immutable; a change creates a new revision.

## 4. Verified current-state inventory

### 4.1 Reusable Process Map foundation

The repository already has:

- `ai_inspector/process_map/semantic_plan.py` for normalized semantic plans;
- `ai_inspector/process_map/builder.py` for proposal, approval, and apply
  orchestration;
- `ai_inspector/process_map/operations.py` for validated domain operations;
- `ai_inspector/process_map/repository.py` for canonical JSON, SHA-256
  revisions, CAS writes, atomic replacement, and backups;
- `ai_inspector/process_map/asset_write_policy.py` for explicit write
  authorization;
- `ai_inspector/process_map/state.py` for trusted Process Map state;
- `ai_inspector/process_map/visual_validation.py` for occurrence-level visual
  review; and
- the `generate-process-map` skill and high-level
  `build_process_map_preview` tool.

These patterns should be extended, not duplicated.

### 4.2 Reusable illustration foundation

`ai_inspector/process_map/card_previews.py` already:

- consumes hash-verified Assembly Knowledge presentation images and identity
  masks;
- selects a deterministic useful view;
- distinguishes direct and inherited occurrences;
- crops by occurrence pixels;
- produces hash-addressed preview artifacts;
- rejects unknown or invisible occurrence identities; and
- avoids model calls and map mutation.

`ai_inspector/process_map/visual_validation.py` already:

- builds cumulative assembly state per operation;
- distinguishes direct inputs, inherited inputs, and future parts;
- binds visual assets to package hashes;
- generates contact-sheet evidence;
- permits only bounded inferred corrections; and
- leaves final semantic validation deterministic.

These two modules are the immediate technical ancestors of instruction
illustrations.

### 4.3 Reusable Assembly Knowledge foundation

Prepared packages can supply:

- stable occurrence IDs;
- product hierarchy and quantities;
- source and package revisions;
- presentation views;
- occurrence identity masks;
- GLB geometry;
- mate and geometry evidence;
- custom properties;
- process candidates;
- evidence fingerprints; and
- hash-addressed assets.

The generator must require the package revision expected by the source Process
Map. It may not silently substitute a newer package.

### 4.4 Reusable document dependency

PyMuPDF is already a runtime dependency and is used to read and render PDFs.
There is no verified production HTML-to-PDF, ReportLab, WeasyPrint, or
server-side Chromium composition pipeline in this repository.

Recommended v1:

- create a fixed-layout PDF composer with PyMuPDF;
- render the generated PDF back to page images with PyMuPDF for validation and
  browser preview; and
- avoid introducing a Node or browser runtime dependency on the backend.

This is new implementation work even though the dependency already exists.

### 4.5 New subsystems

The following do not exist as complete production modules:

- Work Instruction Plan schema and validator;
- Process Map to Work Instruction compiler;
- step-illustration renderer;
- callout layout and collision validation;
- PDF composer;
- work-instruction repository and registry;
- work-instruction proposal and approval APIs;
- work-instruction Sage skill and tool;
- work-instruction preview UI; and
- released-document lifecycle.

## 5. Scope

### 5.1 Committed v1 scope

V1 produces an internal illustrated assembly draft from:

- one saved, validated Process Map revision;
- one exact product-structure revision;
- one exact Assembly Knowledge Package revision;
- existing node and route requirements;
- existing resource catalog entries; and
- trusted semantic evidence.

V1 illustrations use prepared presentation views and identity masks. They show:

- cumulative assembly context;
- parts added during the current step;
- inherited parts;
- optional future-part context;
- deterministic crops;
- occurrence labels; and
- optional simple direction or relationship arrows where supported by evidence.

### 5.2 Explicitly deferred

The following are not required for v1:

- arbitrary live GLB camera placement;
- simulated hands, tools, or operators;
- physically validated insertion trajectories;
- collision-free robot or tool motion planning;
- generated photorealistic imagery;
- free-form desktop publishing;
- multilingual release;
- audio narration;
- animated video export;
- AR instructions;
- regulatory certification;
- automatic promotion to `released`;
- authoring unsupported torque or safety values; and
- reverse-engineering a complete process from CAD during manual generation.

The Process Map generator owns process inference. The manual generator consumes
its validated result.

## 6. Terminology and authority

### 6.1 Work instruction

A revisioned operator-facing document derived from a validated process plan and
trusted evidence.

### 6.2 Instruction step

One operation or inspection with:

- a defined before state;
- direct input occurrences;
- inherited context;
- one action;
- one resulting state;
- applicable requirements and resources; and
- one or more completion checks.

Pure merge, split, and parallel junctions are topology and do not become
standalone work steps unless an authored instruction explicitly describes a
handoff or synchronization action.

### 6.3 Evidence status

Reuse the existing semantic knowledge vocabulary:

```text
authored
derived
inferred
unknown
```

Presentation rules:

- `authored`: normal instruction content with source citation.
- `derived`: normal content with structured-source citation.
- `inferred`: visible Suggested/Inferred treatment and draft-only status.
- `unknown`: omitted from procedural claims and listed under unresolved items.

### 6.4 Requirement authority

Requirements retain:

- source document ID;
- revision;
- clause or section;
- resource identity;
- knowledge status;
- evidence references; and
- source fingerprint.

Formatting a requirement into a manual never raises its authority.

## 7. Target architecture

```text
Explicit user request or ribbon command
        |
        v
Trusted work-instruction observation
        |
        v
Work Instruction Plan compiler
        |
        v
Semantic and evidence validator
        |
        v
Deterministic step illustration renderer
        |
        v
PDF composer
        |
        v
Document and visual validator
        |
        v
Temporary proposal + page previews
        |
        v
One explicit approval
        |
        v
CAS-bound atomic publication + receipt
```

The high-level Sage tool invokes this pipeline once. Sage does not receive
low-level illustration, page-placement, or filesystem tools.

## 8. Work Instruction Plan v1

### 8.1 Top-level contract

```json
{
  "schemaVersion": 1,
  "planId": "wi-plan-...",
  "document": {
    "title": "Tricycle Assembly Work Instructions",
    "documentNumber": null,
    "documentRevision": "DRAFT",
    "language": "en-US",
    "classification": "internal_draft"
  },
  "source": {
    "productId": "tricycle",
    "mapId": "default",
    "mapRevision": "sha256",
    "sourceStructureRevision": "sha256",
    "packageId": "akp-...",
    "packageRevision": "A",
    "evidenceFingerprint": "sha256"
  },
  "scope": {
    "assemblyOccurrenceId": "occ-tricycle",
    "label": "Tricycle Assembly"
  },
  "components": [],
  "resources": [],
  "sections": [],
  "steps": [],
  "finalChecks": [],
  "assumptions": [],
  "unresolvedItems": []
}
```

The browser may not author the source binding. The server derives it from the
selected saved map and package.

### 8.2 Component entry

```json
{
  "occurrenceId": "occ-front-wheel",
  "itemId": "SWPR-Tricycle_Big Wheel",
  "name": "Front Wheel",
  "quantity": 1,
  "parentOccurrenceId": "occ-front-wheel-assembly",
  "knowledgeStatus": "derived"
}
```

Repeated files remain separate occurrences. Quantity rollups are display data,
not replacement identity.

### 8.3 Resource entry

```json
{
  "resourceId": "tool-5mm-hex",
  "kind": "tool",
  "name": "5 mm hex key",
  "sourceReferenceId": "ref-tool-5mm-hex",
  "knowledgeStatus": "authored"
}
```

Resource kinds reuse the Process Map reference catalog where possible:

- tool;
- machine;
- requirement;
- standard;
- fixture;
- consumable; and
- workstation.

Adding new kinds requires coordinated schema validation across Process Map and
Work Instruction assets. Do not introduce near-synonyms in only one module.

### 8.4 Instruction step

```json
{
  "stepId": "wi-step-install-front-wheel",
  "sequence": 30,
  "sectionId": "front-wheel",
  "sourceOperationId": "op-install-front-wheel",
  "title": "Install front wheel assembly",
  "action": "Install the front wheel assembly on the fork.",
  "beforeStateOccurrenceIds": ["occ-frame", "occ-fork"],
  "directOccurrenceIds": ["occ-front-wheel", "occ-axle"],
  "afterStateOccurrenceIds": [
    "occ-frame",
    "occ-fork",
    "occ-front-wheel",
    "occ-axle"
  ],
  "inputResultIds": ["state-frame-ready"],
  "outputResultId": "state-front-wheel-installed",
  "resourceIds": ["tool-5mm-hex"],
  "requirements": [],
  "checks": [],
  "notes": [],
  "cautions": [],
  "warnings": [],
  "illustrations": [],
  "knowledgeStatus": "inferred",
  "evidence": [],
  "assumptionIds": ["assumption-front-wheel-order"]
}
```

### 8.5 Requirement entry

```json
{
  "requirementId": "req-front-axle-torque",
  "kind": "torque",
  "statement": "Tighten to 8 Nm.",
  "value": 8,
  "unit": "Nm",
  "sourceDocumentId": "WI-TRI-001",
  "sourceRevision": "A",
  "sourceSection": "4.2",
  "knowledgeStatus": "authored",
  "evidence": ["evidence-wi-tri-001-4-2"]
}
```

A numeric value without authoritative evidence fails validation. It cannot be
saved as an authoritative requirement merely because a model proposed it.

### 8.6 Illustration specification

```json
{
  "illustrationId": "ill-step-front-wheel-context",
  "kind": "assembly_context",
  "viewPolicy": "best_prepared_view",
  "beforeOccurrenceIds": ["occ-frame", "occ-fork"],
  "directOccurrenceIds": ["occ-front-wheel", "occ-axle"],
  "afterOccurrenceIds": [
    "occ-frame",
    "occ-fork",
    "occ-front-wheel",
    "occ-axle"
  ],
  "futureOccurrenceIds": [],
  "callouts": [
    {
      "occurrenceId": "occ-front-wheel",
      "label": "1"
    }
  ],
  "sourceViewId": null,
  "assetHash": null
}
```

The compiler requests illustration meaning. The renderer chooses pixels and
fills `sourceViewId` and `assetHash`.

### 8.7 Final check

```json
{
  "checkId": "check-front-wheel-rotation",
  "statement": "Verify the front wheel rotates freely.",
  "sourceOperationId": "op-final-inspection",
  "knowledgeStatus": "authored",
  "evidence": ["evidence-final-inspection"]
}
```

Generic safety checks are not inserted from model memory. They require a source
or remain suggested draft content.

## 9. Trusted observation contract

The server compiles a `work_instruction.state` context object from:

- active workflow;
- product, assembly, and package identity;
- selected map ID and revision;
- source structure revision;
- map validation findings;
- normalized semantic plan;
- nodes, operations, branches, and logical connections;
- node and route requirements;
- reference catalog;
- visual-asset availability;
- prepared views and identity-mask hashes;
- source evidence and authority;
- existing manual revisions;
- active proposal identity; and
- publication capabilities and restrictions.

The browser supplies only identity and user intent. It cannot supply trusted
graph content, visual hashes, requirements, or approval state.

Prompt-injection tests must prove that browser attachments and source-document
text cannot:

- add tools;
- change authority;
- bypass approval;
- change source revisions;
- mark inferred content authored;
- request arbitrary filesystem paths; or
- publish a document.

## 10. Deterministic Process Map compiler

### 10.1 Inputs

The compiler receives:

- a normalized, validated Semantic Process Plan;
- the exact saved Process Map;
- trusted product structure;
- reference catalog and target bindings;
- package binding; and
- user-selected document options.

It never consumes canvas coordinates as process meaning.

### 10.2 Step derivation

For each operation:

1. Resolve direct occurrence inputs.
2. Resolve predecessor operations through intermediate results.
3. Compute before-state cumulative occurrences.
4. Compute after-state cumulative occurrences.
5. Bind incoming route requirements as preconditions or handoff requirements.
6. Bind node requirements to the operation.
7. Bind outgoing route requirements as completion or transfer conditions.
8. Aggregate resources without duplicating definitions.
9. Carry knowledge status, evidence, and assumptions.
10. Generate one deterministic illustration request.

### 10.3 Junction behavior

- `parallel_and`: controls section/branch ordering; no instruction step by
  itself.
- `merge`: joins predecessor results; no manufacturing claim.
- `split`: separates downstream branches; no manufacturing claim.
- `wire_branch`: routing-only and absent from the manual.
- `operation/stage`: becomes an instruction step.

If an authored source explicitly defines a synchronization, inspection, or
handoff action, represent that as an operation rather than overloading a
junction.

### 10.4 Sections and branches

Process branches become document sections when they represent coherent
subassemblies. Parallel branches may be presented:

- as independent sections;
- in any order only when the semantic plan says order is unconstrained; or
- with explicit prerequisites when they converge.

Document order must remain a valid topological ordering of the process graph.

### 10.5 Deterministic text policy

V1 does not require an additional model call per step.

Default wording comes from:

- operation labels;
- normalized action templates;
- occurrence names;
- requirement statements;
- checks; and
- authored notes.

An optional model may improve phrasing in one bounded batch, but:

- identifiers and values are immutable;
- no new factual claim is accepted;
- output is diffed against the normalized source;
- deterministic claim validation runs afterward; and
- the deterministic wording remains the fallback.

## 11. Illustration engine v1

### 11.1 Input assets

Require hash-verified paired assets:

- presentation image;
- occurrence identity mask;
- color legend mapping mask colors to occurrence IDs; and
- camera metadata.

GLB presence alone does not satisfy v1 illustration readiness.

### 11.2 View selection

Extend the deterministic policy in `card_previews.py`:

1. Reject views where required direct occurrences have no mask pixels.
2. Score direct-occurrence visibility.
3. Score after-state visibility.
4. Penalize excessive occlusion and tiny selected area.
5. Prefer an isometric view when it remains sufficiently legible.
6. Use stable prepared-view order and view ID as final tie-breakers.

The same inputs must produce the same selected view.

### 11.3 Visual states

Use a fixed legend:

```text
Direct parts added now: orange
Inherited assembled context: cyan or neutral context tone
Future/unaffected parts: light gray or hidden
Unresolved occurrence: red review marker
```

The manual must include a legend when more than one state color appears.

### 11.4 Illustration types

V1 supports:

- `component_overview`;
- `before_state`;
- `assembly_context`;
- `after_state`;
- `detail_crop`; and
- `final_state`.

Each step requires at least `assembly_context`. A before/after pair is added
when both remain legible.

### 11.5 Cropping and scale

Reuse occurrence-mask bounds and deterministic padding. Enforce:

- minimum selected-pixel area;
- minimum rendered dimensions;
- fixed aspect-ratio slots;
- no crop outside the source image;
- enough inherited context to understand placement; and
- no enlargement beyond a configured quality threshold.

### 11.6 Callouts and collision handling

Create a small pure callout planner inspired by the Drawing Map balloon
placement system:

1. Derive occurrence anchor points from mask centroids and visible bounds.
2. Generate label candidates outside selected geometry.
3. Score leader length, crossings, image-boundary clearance, and overlap.
4. Reject label-label and label-critical-geometry collisions.
5. Use stable occurrence ID as final tie-breaker.
6. Emit a finding when no acceptable placement exists.

Callouts are never placed by model coordinates.

### 11.7 Arrows

V1 arrows may indicate:

- a source-to-target relationship already present in trusted evidence;
- a prepared explode direction; or
- a simple authored orientation requirement.

Do not infer a physically feasible insertion trajectory from a mate axis alone.
When direction is unknown, highlight the destination without an arrow.

### 11.8 Technical-illustration treatment

The first release may use clean colored CAD presentation images. A line-art
treatment similar to traditional assembly manuals is optional.

If added, it must be deterministic:

- desaturate or lighten neutral context;
- derive edges from the prepared image;
- retain exact occurrence-mask alignment;
- preserve readable highlights; and
- never use a generative image model.

### 11.9 Arbitrary GLB/explode renderer gate

Arbitrary camera, isolation, and exploded-state capture is a separate spike.

Go/no-go questions:

1. Can the packaged backend render the exact GLB deterministically?
2. Can it preserve occurrence identity at pixel level?
3. Can it run without a visible browser or UI automation?
4. Can it reproduce a view across machines?
5. Can it render before/after states without changing the live Assembly tab?
6. Can it meet the configured per-step latency and memory budget?

Until those pass, v1 uses prepared views and masks. Extracted authoritative
explode images may be consumed when already present, but their absence does not
block v1.

## 12. PDF composer

### 12.1 Canonical source

The canonical authored asset is Work Instruction Plan JSON, not the PDF. The
PDF is a deterministic artifact derived from:

- canonical plan bytes;
- illustration artifact hashes;
- template version;
- font hashes;
- branding configuration; and
- composer version.

### 12.2 Recommended implementation

Use PyMuPDF to generate fixed-layout pages:

- A4 and US Letter templates;
- embedded fonts from a controlled local set;
- deterministic margins, grids, and line heights;
- image insertion from hash-verified artifacts;
- bounded text boxes with overflow findings;
- page numbers and revision footer; and
- bookmarks/table of contents when supported.

Do not make browser print-to-PDF a production dependency in v1.

### 12.3 Page templates

Initial template set:

1. Cover and document-control page.
2. Scope, assumptions, and unresolved-items page.
3. Component overview and quantity list.
4. Tool/resource overview.
5. Full-page instruction step.
6. Two-step page for short operations.
7. Final checks and signoff.
8. Evidence/source appendix.

The composer selects only from these templates. It does not invent arbitrary
layouts.

### 12.4 Step-page hierarchy

Each step page contains:

```text
Step number and title
Assembly illustration
Parts added
Action
Tools/resources
Requirements
Completion check
Notes/cautions/warnings
Evidence/authority badge
```

No card should be nested inside another visual card. Page regions use a clear
technical-document grid.

### 12.5 Preview

After composition:

- render every PDF page to PNG with PyMuPDF;
- serve page thumbnails and full-page previews;
- allow page navigation and zoom;
- show findings beside the applicable page or step; and
- expose the source Process Map and package revisions.

## 13. Deterministic validation

### 13.1 Semantic validation

Hard failures:

- source map is unsaved, invalid, or stale;
- package or structure revision mismatch;
- missing final result;
- missing or duplicate operation IDs;
- invalid topological order;
- required occurrence omitted without reason;
- repeated occurrence conflated with another instance;
- unknown occurrence, operation, resource, or evidence reference;
- pure junction represented as manufacturing work;
- unresolved authoritative requirement conflict; or
- released output requested while inferred or unknown safety-critical content
  remains.

### 13.2 Requirement validation

Hard failures:

- numeric manufacturing value without evidence;
- authored value overwritten by inferred value;
- source revision absent for an authored document requirement;
- requirement attached to the wrong operation or route;
- unsupported unit;
- conflicting authored values; or
- warning severity raised or lowered by model text.

### 13.3 Illustration validation

Hard failures:

- source asset hash mismatch;
- requested occurrence has no identity-mask pixels;
- direct occurrence is absent from the rendered crop;
- before/after occurrence sets do not match the plan;
- callout references the wrong occurrence;
- blank or near-blank image;
- image dimensions below minimum;
- crop outside source bounds; or
- illustration generated from a different package revision.

Warnings:

- selected part is small but visible;
- inherited context is sparse;
- callout placement is crowded;
- no directional evidence exists;
- only one prepared camera view is usable; or
- an inferred step needs engineering review.

### 13.4 Document validation

Hard failures:

- PDF cannot be reopened;
- page count is zero;
- blank page other than an intentional back cover;
- text overflow or clipping;
- missing required page region;
- missing illustration artifact;
- broken internal reference;
- missing revision footer; or
- source hashes absent from document metadata.

### 13.5 Release validation

Publication as `released` additionally requires:

- no unresolved safety-critical item;
- no inferred numeric requirement;
- no unknown required tool or material;
- explicit reviewer identity;
- review timestamp;
- release note;
- valid source revisions; and
- authorized release role.

Internal drafts may carry inferred operations when visibly identified.

## 14. Proposal, approval, and persistence

### 14.1 Identity

Every manual has:

- `workInstructionId`;
- immutable product association;
- display name;
- status;
- created and updated timestamps;
- server-derived revision;
- source map ID and revision;
- source structure revision;
- package ID and revision;
- evidence fingerprint;
- template version; and
- composer version.

### 14.2 Storage

Recommended layout:

```text
generated/training/<productId>/work_instructions/
  registry.json
  <workInstructionId>/
    plan.json
    revisions/
      <revision>/
        document.pdf
        manifest.json
        pages/
        illustrations/
```

The exact final path should follow the existing generated-asset conventions,
but authority must come from an explicit registry, not directory scanning.

### 14.3 Proposal envelope

```json
{
  "proposalId": "wi-proposal-...",
  "workInstructionId": "wi-...",
  "baseRevision": null,
  "sourceMapId": "default",
  "sourceMapRevision": "sha256",
  "sourceStructureRevision": "sha256",
  "packageRevision": "A",
  "evidenceFingerprint": "sha256",
  "planHash": "sha256",
  "artifactManifestHash": "sha256",
  "pdfHash": "sha256",
  "findingSummary": {},
  "expiresAt": "ISO-8601"
}
```

The approval token binds:

- proposal ID;
- source revisions;
- plan hash;
- PDF hash;
- user and session;
- requested publication status;
- diff hash for updates; and
- idempotency key.

### 14.4 Atomic publication

Approval performs:

1. Reload current source identities.
2. Reject any stale map, structure, package, evidence, or manual revision.
3. Verify approval-token bindings.
4. Revalidate the canonical plan and artifact manifest.
5. Write all files to a temporary directory.
6. Flush and atomically promote the complete revision.
7. Update the registry pointer atomically.
8. Return a structured receipt.

Failure leaves no partial published document.

### 14.5 Receipt

```json
{
  "receiptId": "wi-receipt-...",
  "workInstructionId": "wi-...",
  "revision": "sha256",
  "status": "internal_draft",
  "sourceMapRevision": "sha256",
  "pdfHash": "sha256",
  "pageCount": 14,
  "illustrationCount": 12,
  "warningCount": 3,
  "unresolvedCount": 1
}
```

The receipt returns to Sage context and the browser.

## 15. Sage skill and tool boundary

### 15.1 New skill

Add:

```text
ai_inspector/agent_skills/generate-work-instructions/
  manifest.yaml
  contract.yaml
  SKILL.md
```

Suggested workflow:

```text
work-instruction-generation
```

The skill teaches Sage:

- what an instruction step means;
- Process Map versus document semantics;
- evidence and authority rules;
- draft versus released status;
- illustration limitations;
- unresolved-item behavior;
- one-preview/one-approval behavior; and
- the prohibition on direct UI automation.

### 15.2 High-level tool

Expose one planning tool:

```text
build_work_instruction_preview
```

Input:

```json
{
  "productId": "tricycle",
  "mapId": "default",
  "mapRevision": "sha256",
  "documentOptions": {
    "classification": "internal_draft",
    "pageSize": "letter",
    "includeEvidenceAppendix": true
  }
}
```

The tool does not accept:

- raw map JSON;
- occurrence lists from the browser;
- page coordinates;
- image pixels;
- arbitrary filesystem paths;
- authority overrides; or
- an `approve` field.

### 15.3 Tool result

Return:

- proposal ID;
- source bindings;
- page count;
- component, step, and illustration counts;
- findings;
- assumptions;
- unresolved items;
- preview URLs;
- generated artifact hashes;
- allowed next actions; and
- whether release is blocked.

Never return only `success: true`.

### 15.4 Trigger behavior

Route explicit requests such as:

- "Generate work instructions from this process map."
- "Create an illustrated assembly manual."
- "Turn this approved process into operator instructions."

Do not route:

- "Explain this process map."
- "What parts do I need?"
- "Show this assembly exploded."
- "How should I assemble this?" when the user is asking for an answer rather
  than a document.

Ambiguous requests receive one concise clarification.

## 16. APIs

Proposed API surface:

```text
GET  /api/training/work-instructions/{productId}
POST /api/training/work-instructions/{productId}/proposals
GET  /api/training/work-instruction-proposals/{proposalId}
GET  /api/training/work-instruction-proposals/{proposalId}/pages/{pageNumber}
GET  /api/training/work-instruction-proposals/{proposalId}/pdf
POST /api/training/work-instruction-proposals/{proposalId}/approve
POST /api/training/work-instruction-proposals/{proposalId}/dismiss
GET  /api/training/work-instructions/{productId}/{workInstructionId}
GET  /api/training/work-instructions/{productId}/{workInstructionId}/pdf
POST /api/training/work-instructions/{productId}/{workInstructionId}/status
```

Rules:

- proposal generation is read-only with respect to published assets;
- preview artifacts expire;
- approval is a separate authorized request;
- published GETs resolve only explicit registry entries;
- PDF and page responses use exact hashes and safe content types;
- path traversal is rejected before filesystem access; and
- source revisions are returned on every response.

## 17. User experience

### 17.1 Entry points

Two entry points invoke the same backend:

1. Sage explicit request.
2. Process Map ribbon command: `Work Instructions`.

The ribbon command opens options and then starts the same proposal pipeline. It
does not bypass validation.

### 17.2 Preview workspace

The preview includes:

- page thumbnails;
- selected full-page preview;
- document summary;
- source revision badges;
- step and occurrence coverage;
- evidence-status counts;
- warnings and unresolved items;
- `Open source process map`;
- `Regenerate`;
- `Dismiss`; and
- `Approve draft` or `Request release`.

### 17.3 Review behavior

- Opening a page does not modify the document.
- Review findings link to the exact page and step.
- Inferred content has a visible badge in the preview and document.
- Missing authoritative values display `Not provided`, not a model guess.
- Approval is disabled while hard findings or stale bindings exist.
- Dismiss deletes only temporary proposal artifacts.

### 17.4 Source changes

If the map, structure, package, or evidence changes:

- the proposal becomes stale;
- approval is disabled;
- the UI names the changed source;
- regeneration uses the current source; and
- the prior preview remains read-only only long enough for comparison.

## 18. Implementation phases

### W0. Baseline and contract freeze

Work:

- record commit SHA and dirty-worktree exclusions;
- freeze backend, node, and Playwright bars;
- add schema fixtures without runtime behavior;
- define feature and write flags; and
- approve this contract after implementation review.

Exit gate:

- no visible behavior change;
- schemas parse;
- existing bars remain unchanged; and
- implementation scope is explicitly v1 prepared-view rendering.

### W1. Work Instruction Plan and validators

Work:

- add plan schema and strict parser;
- normalize steps, resources, requirements, and evidence;
- reject unknown fields where authority is involved;
- add occurrence and topology validation;
- add hard release rules; and
- add deterministic canonical hashing.

Exit gate:

- golden linear, parallel, repeated-occurrence, and ambiguous fixtures;
- unsupported numeric requirements always fail;
- inferred process content remains draft-only; and
- no files or previews are produced.

### W2. Process Map compiler

Work:

- compile operations into steps;
- compute before/direct/after occurrence states;
- map route and node requirements;
- aggregate resources;
- turn branches into sections;
- produce final checks from authored inspection stages; and
- preserve assumptions and unresolved items.

Exit gate:

- 100% required occurrence accounting;
- valid topological document order;
- stage-versus-junction behavior pinned;
- deterministic output bytes; and
- no model call required.

### W3. Deterministic illustration renderer

Work:

- extend prepared-view and identity-mask loading;
- implement view scoring;
- render component overview and step states;
- add stable crops, labels, and legends;
- implement callout candidate scoring;
- create hash-addressed illustration manifests; and
- add pixel-level validation.

Exit gate:

- every requested direct occurrence is visibly represented;
- repeated occurrences remain distinct;
- same inputs produce byte-identical or pixel-equivalent outputs;
- no blank images;
- no callout overlap on golden fixtures; and
- source image and mask hashes are verified.

### W3.5. Arbitrary renderer spike

This phase is optional and does not block v1.

Work:

- evaluate controlled GLB rendering;
- test arbitrary isolate, before/after, and explode states;
- test headless packaging;
- measure determinism, memory, and latency; and
- write a go/no-go report.

Exit gate:

- either approve a renderer with evidence or retain prepared-view-only v1;
- no half-integrated browser automation enters production.

### W4. PDF composer and page validator

Work:

- implement PyMuPDF fixed templates;
- embed controlled fonts;
- compose cover, lists, steps, checks, and evidence appendix;
- render pages back to PNG;
- detect text overflow and blank regions;
- create PDF and page manifests; and
- add golden page fixtures.

Exit gate:

- generated PDF opens and re-renders;
- page count and hashes are deterministic;
- no text clipping on longest fixtures;
- every illustration and requirement appears on its intended page; and
- no new production runtime dependency.

### W5. Repository, proposal, and approval

Work:

- add work-instruction repository and explicit registry;
- add temporary proposal storage and expiry;
- bind all source revisions and hashes;
- reuse write-policy and approval-token patterns;
- add atomic multi-artifact publication;
- add named revision history; and
- return structured receipts.

Exit gate:

- failed publication leaves no partial asset;
- stale source always rejects;
- idempotent approval creates one revision;
- replay rejects;
- released revision is immutable; and
- rollback/revert targets a named revision.

### W6. APIs and preview UI

Work:

- add proposal, page, PDF, approval, list, and retrieval endpoints;
- add Process Map ribbon command;
- build page-thumbnail and full-page review workspace;
- show evidence and unresolved findings;
- add regeneration, dismissal, and approval;
- support light/dark app themes while keeping PDF styling fixed; and
- preserve Process Map and Assembly editor state.

Exit gate:

- opening/closing preview does not dirty the map;
- no tab-switch prompt is triggered;
- stale proposal is visibly locked;
- PDF download matches preview hash;
- keyboard and screen-reader navigation work; and
- no browser page errors.

### W7. Sage skill and trusted tool

Work:

- register workflow and skill;
- add trusted `work_instruction.state`;
- add native tool schema;
- route explicit generation requests;
- invoke one high-level preview tool;
- return proposal summary and receipt to Sage; and
- keep existing Process Map and FAI routes unchanged.

Exit gate:

- Sage can request one complete preview;
- Sage cannot publish it;
- no low-level UI or filesystem tools are exposed;
- browser-supplied source data is ignored;
- FAI and Process Map routing fixtures remain unchanged; and
- prompt-injection fixtures fail closed.

### W8. Hardening and release evaluation

Work:

- run Tricycle and synthetic fixtures;
- test large manuals;
- test package/map revision churn;
- test missing and conflicting evidence;
- test repeated occurrences and mirrored parts;
- test no-visual and partial-visual cases;
- test both page sizes;
- test accessibility and download behavior;
- measure latency and artifact size; and
- conduct engineer review on unseen assemblies.

Exit gate:

- all hard quality thresholds pass;
- internal draft is usable without editing every page;
- release blockers are explicit;
- rollback flags are proven; and
- an operator can reproduce the runbook.

## 19. Test matrix

### 19.1 Python

- strict plan schema;
- canonical hashing;
- step compiler;
- topological ordering;
- branch sectioning;
- occurrence coverage;
- repeated occurrence identity;
- node and route requirement mapping;
- evidence authority;
- numeric requirement rejection;
- illustration view selection;
- masks, crops, and direct/inherited state;
- callout collision handling;
- PDF composition;
- page overflow and blank-page detection;
- proposal binding;
- CAS publication;
- idempotency and replay;
- stale source rejection; and
- receipt contents.

### 19.2 Node/browser

- ribbon command availability;
- preview opening without map mutation;
- page navigation and zoom;
- finding-to-page navigation;
- inferred badges;
- approval gating;
- stale-state lock;
- dismissal cleanup;
- keyboard focus;
- screen-reader labels;
- PDF download;
- no orphan surfaces; and
- no page errors.

### 19.3 Golden fixtures

1. Simple linear three-step assembly.
2. Parallel branches that converge.
3. Nested subassemblies.
4. Repeated occurrences of one part file.
5. Mirrored left/right parts.
6. Authored torque and inspection requirements.
7. Missing torque and no approved procedure.
8. Conflicting authored requirements.
9. Inferred process plan.
10. No visible occurrence in one prepared view.
11. One usable view only.
12. Large 30-50 part assembly.
13. Stale package revision.
14. Tricycle assembly.

### 19.4 Visual tests

- contact sheets for every golden fixture;
- before/direct/after color correctness;
- selected-pixel thresholds;
- no blank images;
- no labels outside bounds;
- no callout overlap;
- fixed page-grid screenshots;
- longest-title and longest-requirement cases;
- A4 and Letter rendering; and
- PDF page pixel comparison with bounded anti-alias tolerance.

### 19.5 Manual engineering review

For unseen assemblies, an engineer reviews:

- process meaning;
- part membership per step;
- illustration usefulness;
- requirements and evidence;
- missing safety/manufacturing information;
- operator clarity; and
- corrections required before release.

A second model cannot be the sole release authority.

## 20. Quality thresholds

Hard thresholds:

```text
Required occurrence accounting: 100%
Occurrence identity correctness: 100%
Final result correctness: 100%
Invalid process cycles: 0
Pure junctions presented as manufacturing work: 0
Unsupported authoritative claims: 0
Invented numeric manufacturing parameters: 0
Authored values silently overwritten: 0
Unknown evidence references: 0
Illustrations with wrong highlighted occurrence: 0
Blank required illustrations: 0
Text-overflow pages: 0
Stale approvals applied: 0
Partial publications after failure: 0
```

Initial usability targets:

```text
Steps with a usable first-pass illustration: at least 95%
Draft pages requiring manual layout repair: under 5%
Average semantic corrections per step on evidence-backed fixtures: under 0.25
Approval without page-by-page layout editing: at least 90% on known fixtures
```

These usability targets may be tuned after measured pilot runs. Hard safety and
identity thresholds do not relax.

## 21. Performance and cost

### 21.1 Model cost

Default manual generation adds no one-call-per-step model pattern.

- Reuse the validated Semantic Process Plan.
- Compile text deterministically.
- Render images deterministically.
- Compose the PDF deterministically.
- Reuse cached visual-validation output when source hashes match.

An optional one-batch phrasing pass or visual review must have:

- pre-call token and price estimate;
- configured hard budget;
- cache key bound to source hashes and prompt version;
- bounded retries;
- no self-raised budget; and
- deterministic fallback.

### 21.2 Artifact limits

Define configurable caps before implementation:

- maximum steps per document;
- maximum components;
- maximum illustrations;
- maximum page count;
- maximum source image dimensions;
- maximum preview and PDF bytes; and
- proposal expiry time.

Oversized requests fail with a typed finding or require explicit scope
reduction. They do not silently drop steps.

### 21.3 Latency budget

Measure separately:

- source resolution;
- plan compilation;
- illustration rendering;
- PDF composition;
- page validation;
- optional model review; and
- publication.

The preview UI should stream phase status, not partially publish pages.

## 22. Security and data handling

- Resolve every asset beneath registered package and artifact roots.
- Reject absolute and parent-traversal paths.
- Verify every source hash before rendering.
- Never send CAD, illustrations, or instructions to a model unless the
  configured provider policy allows it.
- Record provider, model, prompt, and source hashes for any optional call.
- Keep temporary proposals out of published registries.
- Expire and delete proposal artifacts safely.
- Apply authorization separately for draft creation and release.
- Sanitize PDF metadata and filenames.
- Escape all user-authored text before composition.
- Do not execute embedded PDF, HTML, or source-document instructions.
- Treat uploaded procedures as evidence data, not tool policy.

## 23. Feature flags and rollback

Recommended flags:

```text
INSPECTORPRO_WORK_INSTRUCTIONS=0
INSPECTORPRO_WORK_INSTRUCTION_WRITES=0
INSPECTORPRO_WORK_INSTRUCTION_RELEASE=0
INSPECTORPRO_WORK_INSTRUCTION_GL_RENDERER=0
```

Behavior:

- capability flag off: no command, skill, or API route is advertised;
- write flag off: preview works but approval is disabled;
- release flag off: only internal drafts may be published;
- GL renderer flag off: prepared-view renderer remains authoritative.

Rollback never strands source maps because manuals are separate derived assets.

## 24. Tricycle first fixture

The first end-to-end fixture should be the Tricycle Assembly Knowledge Package
and its validated process map.

Expected draft:

1. Cover and revision/source block.
2. Component overview.
3. Tool/resource summary populated only from known data.
4. Sections for coherent subassembly branches.
5. One instruction step per operation stage.
6. Highlighted direct parts and inherited assembly context.
7. Final assembly view.
8. Final checks only where evidence exists.
9. Assumptions and unresolved-items appendix.

Because the current Tricycle source is CAD-first and may lack drawings or
approved work instructions:

- process order may remain inferred;
- torque, consumables, safety warnings, and inspection limits may be missing;
- those fields must not be invented;
- the output remains an internal draft; and
- the preview should make missing approval evidence obvious.

This is a feature, not a failure. It tells the user exactly what knowledge must
be added before a production release.

## 25. Acceptance criteria

The v1 module is complete when:

1. An explicit request routes to Work Instruction generation.
2. The selected saved Process Map and source revisions are resolved server-side.
3. Invalid or dirty source state is rejected before generation.
4. Every operation stage becomes one valid instruction step.
5. Pure junctions do not become fake manufacturing steps.
6. Every required occurrence is included, excluded with a reason, or unresolved.
7. Repeated occurrences remain distinct.
8. Node and route requirements appear on the correct steps.
9. Authored values are preserved.
10. Unsupported numeric values are never presented as authoritative.
11. Each required step receives a deterministic CAD-derived illustration.
12. Direct and inherited occurrence states are visually distinct.
13. Callouts reference the correct occurrences and do not overlap.
14. The PDF includes cover, components, resources, steps, and final checks.
15. The PDF reopens and every page renders nonblank.
16. The preview shows evidence, assumptions, warnings, and unresolved items.
17. Preview generation does not dirty or mutate the Process Map.
18. Dismissal publishes nothing.
19. Approval is bound to exact source and artifact hashes.
20. A stale proposal cannot be approved.
21. One approval publishes the complete draft atomically.
22. Publication returns a structured receipt to the UI and Sage.
23. Released documents require a separate authorization level.
24. Source changes mark prior manuals stale without deleting them.
25. Existing Process Map, Assembly, FAI, and Training workflows remain green.
26. No browser automation is required to generate illustrations.
27. Feature flags provide clean preview, write, release, and renderer rollback.

## 26. Recommended approval boundary

Approve W0-W4 as the first implementation contract:

```text
Plan schema
+ compiler
+ prepared-view illustrations
+ fixed-template PDF
+ deterministic validation
```

Reconfirm W5-W8 after one complete Tricycle PDF is generated from fixtures and
reviewed visually. This prevents API, skill, and publication work from
hardening a document model that has not yet produced a useful manual.

The arbitrary GLB/explode renderer remains a separate go/no-go decision. It
should improve an already useful manual generator, not become a hidden
prerequisite for delivering one.

