# Assembly Knowledge Package Preparation Plan

Revision: 2

Status: Approved for P0 and P0.5 implementation after external and local code
review. P1 and later phases remain blocked until the P0.5 extraction
reconnaissance gate is complete.

Date: 2026-07-25

Related plans:

- `docs/process-map-semantic-generation-plan.md`
- `docs/process-map-agent-planning-completion-plan.md`
- `docs/process-map-spatial-intelligence-plan.md`

## 1. Objective

Build a repeatable, assembly-neutral preparation pipeline that turns source
CAD and its locally generated visual evidence into a revision-bound Assembly
Knowledge Package.

The package must give Sage enough grounded context to create a complete
process-map draft automatically while preserving a clear distinction between:

- facts extracted deterministically from CAD;
- engineering meaning inferred by AI;
- knowledge confirmed by an engineer;
- formally approved production knowledge; and
- unresolved information.

The desired user experience is:

```text
Open or import an assembly
  -> Prepare assembly knowledge
  -> InspectorPro extracts and analyzes the package
  -> AI proposes functions, interfaces, and process hints
  -> User reviews only important uncertainties
  -> InspectorPro publishes a trusted package
  -> Sage generates one complete process-map preview
  -> User approves once
```

The preparation pipeline must not create or mutate a process map. It prepares
trusted evidence for the separate Semantic Process Plan workflow.

## 2. First Reference Product

The first real-CAD fixture is:

```text
C:\Users\might\OneDrive\Desktop\Tricyle\SWPR-Tricycle.SLDASM
```

The folder was inspected on 2026-07-24 and contains:

```text
1 native SolidWorks assembly
18 native SolidWorks part files
0 nested SolidWorks assembly files
```

The source directory remains read-only and must not be renamed or modified.
The user-facing product name and canonical product ID are:

```text
Tricycle
tricycle
```

No extraction is authorized by this plan. Actual occurrence count,
configurations, mates, component paths, suppression state, and reference
resolution remain unknown until a later approved extraction step.

The Tricycle is a fixture, not a hardcoded product. Every implementation must
work through generic assembly, occurrence, evidence, and package contracts.

### 2.1 Verified extraction reality

InspectorPro currently has two different SolidWorks extraction systems:

1. The primary SolidWorks bridge add-in produces `.inspectorpkg.zip` packages
   and is orchestrated through `ai_inspector/bridge/client.py` and the Phase
   10D endpoints in `server.py`. The add-in source and its assembly package
   writer are maintained outside this repository.
2. The in-repository C# `SolidWorksExtractor` is explicitly described in
   `server.py` as the old visual-enrichment path. It does expose component
   hierarchy, `Name2`, source paths, mates, transforms, properties, geometry,
   GLB export, colorization, and named-view capture.

The current Python assembly bridge orchestration installs the unpacked package
and returns counts. It does not parse a structured assembly occurrence or mate
graph into InspectorPro.

This plan therefore does not assume either system is the canonical structured
source. P0.5 must inspect the bridge package contract and choose one authority
before P1 is estimated or implemented. A dual-path design is allowed only if:

- the bridge remains the authorization and package-ingestion boundary;
- one canonical adapter owns occurrence identity;
- legacy visual enrichment consumes that canonical identity; and
- the two paths cannot independently create conflicting product structures.

## 3. Governing Principles

### 3.1 Deterministic facts first

Use the SolidWorks API and local code for:

- source identity and revision;
- component hierarchy and occurrences;
- quantities and repeated instances;
- configurations and suppression state;
- transforms and mate definitions;
- custom properties and mass properties;
- geometry and feature summaries;
- GLB generation;
- view generation and entity-to-view identity; and
- validation and hashing.

Do not spend model tokens rediscovering facts the application can extract.

### 3.2 AI proposes engineering meaning

Use a multimodal model to propose:

- likely functional roles;
- interface meaning;
- joint or assembly archetypes;
- candidate process branches;
- candidate intermediate results;
- likely insertion or removal constraints;
- candidate assembly operations; and
- focused unresolved questions.

Model-generated statements begin as `inferred`.

### 3.3 CAD mates do not prove manufacturing order

Mates may support:

- component membership;
- geometric alignment;
- likely interface participation;
- degrees of freedom;
- adjacency and orientation; and
- candidate functional relationships.

Mates do not establish:

- installation order;
- operation sequence;
- joining method;
- tools or fixtures;
- torque;
- process duration;
- quality limits; or
- approved manufacturing intent.

### 3.4 Visuals are evidence aids, not identity authority

Rendered views help a model understand geometry and context. Every visible
object must remain bound to extracted occurrence, feature, face, or mate IDs.
Screenshots and screen coordinates are never authoritative identifiers.

### 3.5 Review by exception

The system should prepare a complete candidate package automatically. The user
reviews consequential inferred claims, conflicts, and unknowns rather than
authoring every record.

### 3.6 Cost is a deterministic policy boundary

Package preparation must estimate and enforce limits before making paid model
calls. No implementation may make one high-cost call per part per view by
default.

### 3.7 Packages are revision-bound

Any source-CAD change invalidates affected derived and inferred knowledge.
Published packages remain addressable by revision for traceability, but stale
packages cannot silently feed a current process-map proposal.

### 3.8 Canonical occurrence identity

The existing Process Map `occurrenceId` is currently derived from legacy map
node IDs. It is not a CAD component-path identity.

For newly imported CAD products, the package adapter creates:

```json
{
  "occurrenceId": "<canonical InspectorPro occurrence ID>",
  "sourceIdentity": {
    "scheme": "solidworks_component_path_v1",
    "configuration": "Default",
    "componentPath": "<normalized extracted component instance path>"
  }
}
```

`occurrenceId` remains the public identity referenced by
`product_occurrence.sourceOccurrenceId` on Process Map nodes. The
`sourceIdentity` record explains how it was derived.

Existing published product structures and process maps retain their legacy
occurrence IDs. They are never silently rewritten. Moving an existing product
to CAD-native identity requires an explicit, revisioned, one-to-one binding
asset and a migration preview. Ambiguous or incomplete bindings fail closed.

## 4. Scope

### 4.1 Included in v1

- SolidWorks assembly intake through the existing extraction path.
- Canonical source manifest and package revision.
- Stable occurrence identity.
- Component, mate, transform, property, geometry, and visual evidence.
- Presentation renders and machine-readable identity masks.
- CAD-only multimodal enrichment.
- Model-prior reasoning recorded as supporting, inferred knowledge.
- Strict evidence and claim validation.
- Visual review of uncertain claims.
- Package readiness levels.
- Trusted handoff to `process_map.evidence`.
- Hard API-call and token budgets.
- Caching and incremental reprocessing.

### 4.2 Additive later sources

- Drawings and Drawing Map evidence.
- BOM and PLM records.
- Work instructions and routings.
- ERP, MES, tool, fixture, and machine catalogs.
- Control plans, PFMEA, inspection plans, and standards.
- Approved historical process maps.

The v1 schema must accept these sources later without changing occurrence
identity.

### 4.3 Excluded from v1

- Automatic production approval.
- Invented torque, tolerances, dimensions, tools, or process settings.
- Full physics simulation.
- General-purpose collision-free robotic motion planning.
- Automatic ERP or MES writes.
- Model-generated world coordinates.
- Direct process-map mutation during preparation.
- Training a custom foundation model.
- Per-part or per-interface model calls by default.
- Multiple user-facing AI preparation modes.
- Full provider idempotency and runtime retention-policy management.

## 5. System Boundary

```text
Native CAD and optional documents
        |
        v
Source preflight and revision lock
        |
        v
Existing SolidWorks extraction
        |
        +--> Product structure and occurrence catalog
        +--> Mate and transform records
        +--> Geometry and feature summaries
        +--> GLB assets and local views
        |
        v
Deterministic evidence compiler
        |
        v
Bounded AI enrichment
        |
        v
Deterministic package validator
        |
        v
Visual review queue
        |
        v
Published Assembly Knowledge Package
        |
        v
Trusted process_map.evidence provider
        |
        v
Sage Semantic Process Plan
```

The Assembly Knowledge Preparer and Sage are separate roles even when they
use the same foundation model.

## 6. Canonical Package Layout

Recommended storage:

```text
generated/training/<productId>/assembly_knowledge/<packageId>/
  package.json
  source_manifest.json
  product_structure.json
  interface_graph.json
  geometry_summary.json
  visual_manifest.json
  functional_context.json
  process_candidates.json
  evidence_catalog.json
  unresolved.json
  review_receipt.json
  visuals/
    presentation/
    identity_masks/
    interface_crops/
```

`package.json` is the canonical index. Binary visual assets remain sidecars
referenced by hash and relative path.

### 6.1 Package identity

```json
{
  "schemaVersion": 1,
  "packageId": "akp-<stable-id>",
  "productId": "tricycle",
  "sourceRevision": "<sha256>",
  "packageRevision": "<sha256>",
  "extractorVersion": "<version>",
  "enrichmentPolicyVersion": "<version>",
  "promptVersion": "<version>",
  "modelProvider": "<provider>",
  "modelId": "<model>",
  "readiness": "planning_ready",
  "productionEligible": false
}
```

`packageRevision` is computed from canonical structured package content and
referenced asset hashes. It is not trusted from a client.

### 6.2 Knowledge status

Every semantic claim uses:

```text
derived
inferred
authored
unknown
```

Every source uses an independent authority:

```text
approved
authored
illustrative
supporting
untrusted
```

Confirming an AI proposal can make it authored. It becomes approved only
through a separate formal release decision.

### 6.3 Claim record

```json
{
  "claimId": "claim-001",
  "subjectRef": "occurrence-001",
  "predicate": "axially_locates",
  "objectRefs": ["occurrence-002"],
  "value": null,
  "knowledgeStatus": "inferred",
  "authority": "supporting",
  "evidenceRefs": [
    "mate-041",
    "feature-018",
    "view-interface-007"
  ],
  "assumptionIds": [],
  "generatedBy": {
    "kind": "model",
    "modelId": "<model>",
    "promptVersion": "<version>"
  },
  "reviewStatus": "pending"
}
```

Claim IDs are stable hashes of normalized subject, predicate, objects,
evidence fingerprint, and generation policy version. Visible labels do not
determine identity.

## 7. Stage A - Source Preflight and Revision Lock

Purpose: establish exactly what source package will be analyzed.

Use:

- local Python manifest and hashing code;
- the existing SolidWorks extraction request path for capability checks; and
- SolidWorks document metadata where available.

Preflight produces:

```text
root assembly path and hash
referenced source-file paths and hashes
active configuration
available configurations
file availability
extractor and SolidWorks versions
package size
estimated local processing work
```

Preflight must fail or require explicit policy for:

- missing referenced files;
- unresolved components;
- inaccessible OneDrive placeholders;
- configuration ambiguity;
- source changes during preparation; or
- duplicate source paths that cannot be disambiguated.

No AI calls occur during preflight.

## 8. Stage B - Deterministic CAD Extraction

Purpose: capture everything SolidWorks can state directly.

Use the canonical extraction adapter selected by P0.5. Do not choose the
bridge package, the legacy C# extractor, or a dual-path adapter before that
gate reports their actual field coverage.

Likely implementation boundary:

- the bridge remains the authorized extraction and package-ingestion path;
- a versioned adapter parses its assembly package if the required records
  exist;
- the legacy C# extractor may provide missing visual or geometry enrichment;
- exactly one adapter creates canonical occurrence and mate identities; and
- no second independent SolidWorks component graph is persisted.

Extract:

- root assembly and configuration;
- component instance path;
- source part path and source hash;
- occurrence hierarchy;
- occurrence quantity;
- resolved, lightweight, suppressed, or hidden state;
- transforms;
- mate IDs, mate types, entities, suppression, and ownership;
- custom properties;
- material and mass properties when present;
- feature and geometry summaries;
- candidate interface axes and bounds;
- assembly and part GLBs; and
- extraction findings.

Source-file hashes are produced by the local source-manifest layer unless the
selected package contract already provides verifiable content hashes.

Occurrence IDs are derived from normalized component instance paths plus
configuration identity. A repeated part file produces distinct occurrence
IDs.

SolidWorks mate display names such as `Concentric1` are aliases, not stable
identity. P1 must define and test a canonical mate identity derived from stable
occurrence identities, mate type, and normalized participating entities. If
the selected extraction package cannot provide enough entity identity, that
gap is reported rather than hidden behind the display name.

Structured assembly extraction findings are new work. They must include source
reference, configuration, suppression, identity, mate, geometry, and visual
coverage findings and must be serialized into the package.

Re-extracting unchanged source content and configuration must produce
byte-identical identity-bearing records after timestamp fields are removed.

No model calls occur during deterministic extraction.

## 9. Stage C - Visual Evidence Generation

Purpose: make spatial and functional evidence understandable to a multimodal
model and to a reviewing engineer.

### 9.1 Presentation views

Use SolidWorks COM named-view export as the primary v1 generation path. The
existing `ViewExporter.cs` implementation is the closest working precedent,
but its output and error reporting require validation before reuse.

Generate locally:

- full-assembly isometric views;
- front, top, and side assembly views;
- an opposite isometric view;
- per-part isometric and selected orthographic views;
- transparent-context views for important occurrences;
- isolated interface-pair views; and
- optional exploded or section views where locally available.

Do not generate every possible view for API submission.

### 9.2 Identity-mask views

For each important presentation view, generate an unlit identity-mask render:

- each occurrence receives a unique solid color;
- each mask color maps to one occurrence ID;
- antialiasing does not determine identity;
- camera and projection match the presentation render;
- the view manifest records visible occurrence IDs; and
- feature-level masks may be generated on demand for ambiguous interfaces.

The existing `PartColorizer.cs` cannot serve as this mask unchanged. It keys a
20-color palette by unique part filename, so repeated occurrences receive the
same color and colors repeat after the palette is exhausted.

P2 must add a separate occurrence-mask mode that:

- keys colors by canonical occurrence ID, not source filename;
- assigns a non-repeating machine color within the supported occurrence cap;
- emits a color-to-occurrence manifest;
- restores all original component appearances;
- proves repeated occurrences receive different mask identities; and
- verifies that the captured render preserves usable pixel-to-ID mapping.

Presentation coloring may remain visually optimized and part-based. Machine
identity masks are occurrence-based and must not reuse the presentation
palette as authority.

The browser Three.js viewer is not the primary v1 capture system. It remains
the review and highlighting surface in Stage G. If COM rendering cannot
produce reliable identity masks, P2 stops for a rendering spike rather than
silently moving capture into the interactive browser viewer.

### 9.3 Visual manifest

```json
{
  "viewId": "assembly-isometric-001",
  "assetHash": "<sha256>",
  "maskAssetHash": "<sha256>",
  "camera": {},
  "projection": "perspective",
  "visibleOccurrenceIds": [],
  "colorLegend": {},
  "mateIds": [],
  "featureIds": []
}
```

Visual assets are generated locally and reused. Model calls receive resized
copies or contact sheets, not original full-resolution assets by default.

## 10. Stage D - Deterministic Evidence Compilation

Purpose: build a compact, trusted input before asking AI to reason.

Compile:

- exact product structure;
- source revision;
- occurrence identities and quantities;
- mate graph;
- geometry and feature summaries;
- assembly bounds and relative transforms;
- visual evidence catalog;
- deterministic adjacency candidates;
- repeated and mirrored occurrence facts;
- available properties; and
- extraction findings.

Allowed deterministic claims include:

```text
component_membership
same_source_part
mate_relationship
concentric_alignment
coincident_alignment
relative_transform
geometry_contains_cylindrical_feature
property_value
visible_together_in_view
```

Do not compile manufacturing order from mates, proximity, or filenames.

The compiler produces an evidence fingerprint. Browser content cannot add,
replace, or suppress evidence.

## 11. Stage E - Cost-Bounded AI Enrichment

Purpose: use general model knowledge and visual reasoning to prepare a complete
candidate semantic layer.

### 11.1 V1 execution policy

V1 ships one `Economy` path only. Multiple user-facing modes, per-interface
calls, and independent critic passes are deferred until measured failures
justify them.

For an assembly with `N` occurrences:

```text
default semantic API calls: 1
hard semantic API calls: <= 2
API image attachments per call: <= 6
per-part or per-interface calls: 0
```

The optional second call is permitted only for a bounded schema correction
that receives the first response plus validation findings. It may not request
additional images or introduce new semantic content.

Therefore v1 call count is `O(1)` with respect to `N`, not `O(N)`.

### 11.2 Assembly enrichment request

Send:

- no more than six bounded contact sheets or context views;
- the compact occurrence catalog;
- quantities;
- mate-group summaries;
- available properties;
- deterministic interface candidates; and
- strict semantic instructions.

Request:

- likely occurrence functions;
- candidate functional relationships;
- natural process branches;
- candidate intermediate results;
- candidate assembly archetypes;
- likely operation families;
- assumptions; and
- unresolved questions.

The same call produces strict JSON containing:

```text
occurrence role candidates
functional relationships
joint archetype candidates
candidate process branches
candidate intermediate results
candidate operation families
assumptions
unresolved questions
evidence references
```

Do not request coordinates, route geometry, torque, dimensions, standards,
tools, process settings, or authoritative manufacturing order.

Every claim supported only by model training data cites a synthetic source:

```text
sourceType: domain_heuristic
authority: supporting
knowledgeStatus: inferred
```

This reuses the existing Process Map evidence vocabulary rather than creating
a second synonym for model-prior engineering knowledge.

### 11.3 Provider boundary

Use a configurable multimodal API provider. Interactive account subscriptions
are not part of the repeatable runtime architecture.

No reusable multimodal provider adapter currently exists. V1 builds a new,
narrow adapter supporting:

- strict structured output or validated tool input;
- image input;
- timeout and bounded retry;
- token and image usage reporting;
- provider error classification;
- model and prompt version recording; and
- one supported provider configuration at a time.

Copy the proven timeout and bounded-retry behavior from the Sage streaming
path where appropriate. Full provider idempotency, dynamic retention-policy
management, provider failover, and multi-provider optimization are deferred.
Deployment documentation must still state the selected provider's configured
data-handling policy before proprietary images are submitted.

## 12. Cost Policy

Before paid calls, show:

```text
number of planned calls
number and resolution of submitted images
estimated input and output tokens
estimated maximum cost
cache hits
changed occurrences
```

Pre-call cost estimation and authorization are new subsystems. Existing
telemetry pricing computes cost after calls and is useful as pricing-table
input, not as an authorization gate.

Required v1 limits:

```text
default calls = 1
hard calls <= 2
images per call <= 6
maximum submitted image pixels
maximum input tokens
maximum output tokens
maximum estimated cost
maximum retry cost
```

The backend stops before exceeding a limit and requests explicit
authorization. The model cannot raise its own budget.

Caching key:

```text
source revision
+ evidence fingerprint
+ image hashes
+ enrichment policy version
+ prompt version
+ model version
```

Incremental preparation reprocesses only changed occurrences and claims whose
evidence dependencies changed.

If exact provider pricing is unavailable or marked unknown, the backend cannot
claim a trustworthy dollar estimate. It must either block paid preparation or
require an explicit token-and-image budget authorization that states pricing
is unknown.

Tests never make paid model calls. Model responses are fixture-driven unless a
separate explicitly authorized evaluation is running.

## 13. Stage F - Deterministic Package Validation

Reject or report:

- unknown occurrence, mate, feature, view, source, or evidence IDs;
- duplicate identities;
- out-of-scope references;
- invalid knowledge status or authority;
- unsupported authoritative claims;
- numeric manufacturing values without exact source evidence;
- product subassemblies invented where none exist in CAD;
- manufacturing sequence asserted from mates alone;
- contradictory authored or approved claims;
- missing repeated occurrences;
- invalid process candidate topology;
- stale source revision;
- unknown schema fields; and
- non-finite geometry data.

The validator may accept inferred claims with warnings. It must never promote
them.

## 14. Stage G - Visual Review by Exception

Build a dedicated review mode using existing Three.js selection and
highlighting capabilities.

For a pending claim, show:

- isolated subject occurrence;
- related occurrence or feature;
- assembly context;
- relevant presentation view;
- highlighted interface entities;
- extracted mate and geometry evidence;
- proposed engineering meaning;
- knowledge status and authority;
- why the claim matters to process planning; and
- available actions.

Actions:

```text
Confirm
Edit
Reject
Mark unknown
Defer
```

Confirmation produces an auditable review event. It does not silently convert
the package to production-approved.

Prioritize review of:

1. claims that affect required-part coverage;
2. process-order assumptions;
3. stage-versus-junction meaning;
4. ambiguous repeated occurrences;
5. conflicting relationships;
6. safety or quality claims; and
7. unsupported numeric values.

Low-risk inferred descriptions may remain inferred without blocking a draft
process map.

## 15. Stage H - Publication and Readiness

Readiness levels:

```text
structure_ready
  Source resolved and occurrence identity complete.

function_ready
  Functional and interface context available with unresolved items reported.

planning_ready
  Sage can produce an explicitly inferred process proposal.

production_ready
  Required process knowledge and requirements have approved authority.
```

The CAD-only Tricycle target is `planning_ready`, not automatically
`production_ready`.

Publish only through the revision-aware repository:

- canonical ASCII structured data;
- atomic replace;
- source and package CAS;
- versioned backups;
- package findings;
- review receipt; and
- immutable model, prompt, and evidence fingerprints.

The JSON CAS, atomic-write, conflict, and backup patterns are directly reused
from `ai_inspector/process_map/repository.py`. Content-addressed storage and
garbage collection for binary visual sidecars are small new work and require
their own tests.

The package records both the bridge package schema/version and the canonical
adapter version. Unknown major bridge package versions fail closed. Frozen
package fixtures pin every supported bridge-to-canonical conversion so an
independently released add-in cannot silently change the meaning of a
published package.

## 16. Trusted Handoff to Sage

Add a new server-built `process_map.evidence` provider. It does not exist
today.

Register it through `_CONTEXT_FIELDS` in
`ai_inspector/prompts/context.py`, following the existing
`process_map.graph` and `process_map.state` mechanism.

This phase also strengthens the current convention-based trust boundary:

- the provider registry declares each context key's server or browser origin;
- only the server package resolver may populate `process_map.evidence`;
- browser fields with the same or trusted-looking names are ignored;
- package, source, evidence, and context fingerprints are cross-checked;
- a skill must explicitly require the trusted context key; and
- injection tests prove browser content cannot replace, add, or suppress
  package evidence.

Sage receives:

- exact scope and package identity;
- complete occurrence catalog;
- quantities and repeated occurrence identity;
- derived relationships;
- inferred and authored functional claims;
- process branch and intermediate-result candidates;
- available requirements and resources;
- assumptions, conflicts, and unresolved questions;
- view references for targeted explanation; and
- package readiness and production eligibility.

Sage does not receive authority to:

- reinterpret inferred claims as approved;
- add browser-supplied evidence;
- invent numeric requirements;
- mutate the knowledge package;
- generate spatial coordinates; or
- bypass Semantic Process Plan validation.

The final process-map proposal binding includes:

```text
sourceRevision
packageRevision
evidenceFingerprint
mapRevision
structureRevision
semanticPlanHash
```

## 17. Suggested Modules and Ownership

New backend package:

```text
ai_inspector/assembly_knowledge/
  schema.py
  manifest.py
  evidence.py
  visuals.py
  enrichment.py
  cost_policy.py
  validate.py
  repository.py
  readiness.py
```

New skill:

```text
ai_inspector/agent_skills/prepare-assembly-knowledge/
  manifest.yaml
  contract.yaml
  SKILL.md
```

The skill is preparation-only:

- it cannot mutate a process map;
- it cannot publish without deterministic validation;
- it cannot approve its own claims; and
- it cannot request unrestricted tools.

Frontend work should live in a dedicated module beside
`static/process_map_editor.js`, not add another large subsystem directly to
the existing monolith.

Reuse:

- current bridge authorization, polling, package validation, unpacking, and
  sidecar-installation orchestration;
- C# SolidWorksExtractor component, mate, geometry, GLB, coloring, and
  named-view code only after P0.5 assigns its role;
- current GLB assets and Three.js selection/highlighting for review;
- the Process Map public `occurrenceId` linkage, but not its current
  legacy-map-derived identity generation;
- `_CONTEXT_FIELDS` and skill context requirements as the starting point for a
  strengthened server-origin provider boundary;
- current canonical JSON and revision-aware repository patterns;
- current Floating UI manager where contextual review controls are needed; and
- current process-map semantic validator and Builder handoff.

## 18. Implementation Phases

### P0. Baseline and contracts

Work:

- Pin existing extraction, process-map, and visual regression bars.
- Define package, claim, source, view, finding, review, and readiness schemas.
- Add strict unknown-field rejection.
- Add synthetic fixtures without opening SolidWorks.

Exit gate:

- Canonical schema and hashing tests pass.
- No runtime behavior changes.
- No model calls.

### P0.5. Extraction reconnaissance spike

Purpose: resolve which extraction system owns canonical structured assembly
data before P1 begins.

Work:

- Obtain the bridge add-in package schema or source contract from its separate
  repository, or inspect a previously generated frozen assembly package.
- If neither exists, request separate user authorization to extract one
  non-production fixture package. This plan does not grant that authorization.
- Inventory bridge package fields against Stage B.
- Inventory the legacy C# extractor fields and stability separately.
- Decide whether v1 uses bridge-only parsing or bridge ingestion plus legacy
  enrichment.
- Define the canonical adapter and prohibit dual identity generation.
- Record bridge package version compatibility and breaking-change policy.

Artifact:

```text
docs/assembly-knowledge-extraction-reconnaissance.md
tests/fixtures/assembly_knowledge/packages/<frozen-package-version>/
```

Exit gate:

- The selected canonical extraction authority is named.
- Every required Stage B field is classified as available, derivable, missing,
  or deferred.
- Component-path and mate-entity stability risks are documented.
- The P1 estimate and file list are revised from evidence.
- No native source CAD was modified.

Go/no-go: P1, P2, and P3 do not begin until this gate passes.

### P1. Source manifest and deterministic extraction adapter

Work:

- Build source preflight and revision lock.
- Normalize the P0.5-selected extraction contract into package records.
- Reconcile canonical CAD identity with existing Process Map occurrence IDs.
- Prove stable repeated-occurrence IDs.
- Define stable mate identity or report unsupported mate-entity stability.
- Add extraction findings and stale-source detection.

Exit gate:

- Same source and configuration produce identical identity records.
- Existing legacy process maps remain byte-identical and retain their IDs.
- Missing references fail closed.
- Unknown bridge package major versions fail closed.
- Source files remain byte-identical.

### P2. Visual evidence package

Work:

- Generate presentation views through the SolidWorks COM named-view path.
- Add occurrence-keyed colorization and identity-mask rendering.
- Add view manifests and occurrence color legends.
- Build bounded contact-sheet helpers.

Exit gate:

- Every visible mask entity resolves to one occurrence.
- Two occurrences of one part file receive different mask identities.
- Mask colors do not cycle within the supported occurrence cap.
- Presentation and mask cameras match.
- Pixel-to-occurrence fidelity passes the selected COM-render validation.
- Both light and dark review UI themes remain legible.

### P3. Deterministic evidence compiler

Work:

- Compile structure, mate, geometry, property, and visual claims.
- Add evidence fingerprinting and hard budgets.
- Add CAD-only readiness findings.
- Add the new server-origin `process_map.evidence` context registration and
  browser-injection fixtures.

Exit gate:

- No manufacturing sequence is emitted.
- All claims cite known source evidence.
- Browser evidence injection is ignored.

### P4a. Cost policy and cache, no model calls

Work:

- Build pre-call token, image, retry, and cost estimation.
- Reuse telemetry pricing-table data without treating post-call telemetry as
  authorization.
- Add the explicit spend-authorization gate.
- Implement request fingerprints, cache keys, and delta invalidation.
- Prove the v1 constant-call formula with fixtures.

Exit gate:

- Paid calls cannot run without a budget decision.
- For every fixture size `N`, planned calls are one by default and never more
  than two.
- Unknown pricing cannot be presented as a trustworthy dollar estimate.
- No model calls occur in this phase.

P4a may proceed after P0 in parallel with P0.5 through P3.

### P4b. Multimodal adapter and Economy enrichment

Work:

- Build the narrow new multimodal provider adapter.
- Add strict output or tool-input validation.
- Implement one assembly enrichment call and one optional schema correction.
- Record model, prompt, usage, image, and evidence fingerprints.
- Keep `domain_heuristic` claims inferred and supporting.

Exit gate:

- Timeout and bounded retry behavior is deterministic and tested.
- The adapter cannot exceed the P4a authorization.
- Per-part and per-interface calls remain zero.
- Unsupported numeric and authoritative claims equal zero.
- Live evaluation requires separate explicit paid-call authorization.

### P5. Package validation and review UI

Work:

- Add deterministic semantic validation.
- Add prioritized review queue.
- Add 3D occurrence and interface highlighting.
- Record confirm, edit, reject, unknown, and defer receipts.

Exit gate:

- Review actions are auditable and revision-bound.
- Confirming a claim does not imply formal production approval.
- Source changes invalidate pending review safely.

### P6. Publication and Sage integration

Work:

- Publish revisioned packages.
- Add trusted `process_map.evidence`.
- Bind package revision into Semantic Process Plan preview and approval.
- Add CAD-only planning readiness behavior.

Exit gate:

- Sage can generate a complete inferred proposal from a planning-ready package.
- Stale package revisions cannot create a preview.
- Existing Builder, layout, routing, approval, and save behavior remains
  unchanged.

### P7. Evaluation and controlled rollout

Fixtures:

- Tricycle native CAD package.
- Four-cylinder engine with known functional relationships.
- Synthetic nested assembly.
- Repeated and mirrored occurrences.
- Suppressed and unresolved references.
- Ambiguous mates.
- No custom properties.
- Conflicting inferred and authored claims.
- Revision with one changed part.
- Large assembly scaling fixture.

Exit gate:

- Hard safety metrics pass.
- Average completed review actions per occurrence is at most 0.25 across the
  rollout fixture set. Exceeding this does not falsify claims; it blocks the
  review-by-exception product gate and requires redesign.
- Model calls, submitted images, tokens, and package cost are reported.
- Feature remains behind explicit preparation and AI-enrichment flags.

## 19. Evaluation Metrics

Hard metrics:

```text
Occurrence identity correctness: 100%
Repeated occurrence identity correctness: 100%
Source reference resolution: 100% before planning_ready
Unknown evidence references: 0
Unsupported authoritative claims: 0
Invented numeric manufacturing values: 0
False native subassemblies: 0
Stale-package proposals: 0
Unapproved process-map writes: 0
```

Quality metrics:

```text
Functional-role engineer acceptance rate
Interface-relationship acceptance rate
Process-branch acceptance rate
Average unresolved questions per assembly
Average completed review actions per occurrence: <= 0.25 rollout gate
Percentage of process operations accepted unchanged
Time from source preflight to planning-ready
Default AI calls per package: 1
Hard AI calls per package: <= 2
Submitted image attachments per call: <= 6
AI tokens and cost per package
Cache reuse across unchanged revisions
```

The unsupported-authoritative-claim rate is more important than fluent prose
or high numeric confidence.

## 20. Security and Data Handling

- Uploaded or extracted content cannot alter tool permissions.
- Native CAD is not sent to a model provider.
- Only selected rendered images and bounded structured evidence are sent.
- External URLs are not followed without an approved connector.
- Provider configuration determines retention and regional policy.
- Secrets never enter prompts, package artifacts, or telemetry.
- Raw proprietary procedures are not logged by default.
- Telemetry records hashes, versions, counts, timings, and finding codes rather
  than raw geometry or images.
- Preparation authorization is tied to the current user, source revision,
  package mode, provider, and cost budget.

## 21. Risks and Mitigations

### Visual plausibility mistaken for engineering truth

Mitigation: all visual and model-prior claims remain inferred unless reviewed.

### Mates mistaken for process sequence

Mitigation: deterministic validator forbids authoritative ordering claims whose
only evidence is mates, geometry, proximity, filenames, or
`domain_heuristic`.

### Cost grows with part count

Mitigation: deterministic extraction, contact sheets, branch batching,
selective interface calls, hard budgets, caching, and delta preparation.

### AI invents product subassemblies

Mitigation: product subassemblies require exact CAD occurrence evidence.
Process intermediate results use a distinct entity type.

### Repeated parts are conflated

Mitigation: component-path occurrence IDs and identity masks; part number is
never sufficient identity.

### Source revision changes during processing

Mitigation: source manifest before and after extraction and before publication.

### Review becomes another manual data-entry workflow

Mitigation: complete AI draft, prioritized exceptions, batch navigation, and
review metrics. Do not require confirmation of every low-risk inferred label.

### AI provider is unavailable

Mitigation: deterministic package may still reach `structure_ready`; AI
enrichment can resume later without re-extracting unchanged source.

### Bridge package changes independently

Mitigation: pin bridge package major version, canonical adapter version, and
frozen conversion fixtures. Unknown major versions fail closed before package
publication.

### Two extractors disagree

Mitigation: P0.5 assigns one canonical structured-data authority. Any legacy
visual-enrichment path consumes canonical occurrence bindings and cannot
publish a second component graph.

## 22. Definition of Done

The preparation system is complete when:

1. Any supported SolidWorks assembly can enter through one generic preflight.
2. Native source files remain unchanged.
3. Stable occurrences, quantities, mates, geometry, and visual evidence are
   extracted deterministically.
4. Presentation views and identity masks bind pixels to known CAD entities.
5. AI produces a complete candidate functional layer within a hard user-visible
   budget.
6. Model-prior claims remain inferred and traceable.
7. Deterministic validation rejects unsupported authority, unknown references,
   invented numeric requirements, and false product hierarchy.
8. The user reviews only prioritized uncertainties through grounded 3D
   evidence.
9. Published packages are canonical, revision-bound, and auditable.
10. A CAD-only package can reach `planning_ready` without pretending to be
    production-ready.
11. Sage receives the package through a trusted server-built provider.
12. Sage can create a complete Semantic Process Plan and ghost preview without
    manual JSON preparation.
13. Existing process-map execution, layout, routing, approval, and persistence
    regression bars remain green.

The governing boundary is:

> Deterministic systems establish what the CAD contains. AI prepares a
> complete explanation of what it probably means. Engineers resolve important
> uncertainty. Sage turns the resulting trusted package into a process.

## 23. Questions for External Review

Ask the reviewer to challenge:

1. Whether package preparation and Sage planning are separated cleanly.
2. Whether P0.5 resolves the bridge-versus-legacy extractor boundary before
   implementation is estimated.
3. Whether any model-generated statement can accidentally become authoritative.
4. Whether occurrence-aware SolidWorks COM identity masks are feasible and
   sufficient for repeated-occurrence
   grounding.
5. Whether the CAD-to-public occurrence identity reconciliation protects
   existing process maps.
6. Whether the source and package revision strategy prevents stale proposals.
7. Whether the new cost controls are enforceable outside prompts.
8. Whether the one-call Economy path is sufficient for v1.
9. Whether visual review will remain review-by-exception rather than become
   manual authoring.
10. Whether the package schema can accept drawings and ERP evidence later
   without migration of occurrence identity.
11. Whether any existing InspectorPro subsystem should be reused instead of a
   proposed new module.
12. Which phase should stop for re-evaluation before further implementation.
