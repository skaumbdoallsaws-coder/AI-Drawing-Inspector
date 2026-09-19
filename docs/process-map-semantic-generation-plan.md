# Process Map Semantic Generation Plan

Revision: 1

Status: Foundation architecture contract. The runtime foundation through blank-map preview and position ownership was implemented by 2026-07-23. Remaining evidence and model-quality work is governed by `docs/process-map-agent-planning-completion-plan.md`. Front Wheel examples in this document remain historical fixtures; the primary real-CAD milestone is the Tricycle assembly defined in revision 2 of the completion plan.

Date: 2026-07-22

## 1. Purpose

Part 1 demonstrates that a user can build a process map manually with targeted help from Sage:

1. Ask Sage which product occurrences are required for a subassembly.
2. Highlight those occurrences in the structure tree.
3. Drag the required component cards into the canvas.
4. Add operation/stage and routing junction nodes.
5. Connect, arrange, route, review, and save the map.

Part 2 should demonstrate a materially different capability:

> The user names an assembly scope, Sage drafts the manufacturing meaning of the process, and InspectorPro produces one grounded, spatially valid process-map proposal that the user can approve once.

The model must not invent screen coordinates, write directly to the saved map, or present inferred manufacturing knowledge as established fact.

## 2. Product Outcome

The primary Part 2 command is:

```text
Generate a process map for the Front Wheel & Brake assembly.
```

The expected workflow is:

1. InspectorPro resolves the requested occurrence from the complete product structure, whether or not it is already on the canvas.
2. The backend assembles trusted product and process evidence for that exact occurrence and revision.
3. Sage returns a declarative Semantic Process Plan with required occurrences, operations, intermediate results, precedence, branches, assumptions, and provenance.
4. A deterministic validator rejects missing components, unsupported authoritative claims, invalid topology, and invented manufacturing parameters.
5. Builder compiles the validated plan into a temporary map transaction.
6. Existing deterministic arrangement, routing, and spatial diagnostics calculate world coordinates and connection routes.
7. The application presents one complete ghost preview with a concise semantic and spatial summary.
8. The user approves once or dismisses the proposal.
9. Approval applies the entire map atomically through the existing revision-aware Builder gate.

No nodes, edges, groups, references, or process properties are saved before approval.

## 3. Binding Architecture Decisions

These decisions prevent this feature from duplicating or weakening systems that already exist.

### 3.1 Sage owns meaning, deterministic code owns geometry

Sage may decide:

- Which operation is being proposed.
- Which occurrences are consumed by an operation.
- Which intermediate result an operation produces.
- Which branches can proceed in parallel.
- Which precedence relationships are authored, derived, inferred, or unresolved.
- Semantic layout preferences such as branch, stage, above, below, and primary flow.

Sage may not decide:

- Final `x` or `y` coordinates.
- SVG paths or bend points.
- Canvas pan, zoom, or fit values.
- Collision offsets.
- Exact group rectangle geometry.
- Whether a stale proposal may still be applied.

### 3.2 Product structure is not manufacturing sequence

Assembly membership, BOM hierarchy, mates, geometry, and functional relationships can support a process proposal. They do not, by themselves, prove manufacturing order.

The system must distinguish:

```text
Derived: The two brake rotors belong to this subassembly.
Inferred: Install the rotors after mounting the tire.
Authored: The approved work instruction specifies that order.
Unknown: Available evidence does not establish the order.
```

### 3.3 Complete occurrence identity is mandatory

All component references use stable `occurrenceId` values. Part numbers alone are insufficient because the same item can occur more than once or in different assembly locations.

### 3.4 Intermediate results remain semantic in v1

V1 does not introduce another canvas node kind solely for intermediate assembly states. An intermediate result is declared in the semantic plan and compiled into the producing operation/stage metadata. The stage card can display a short result label such as `Produces: Wheel core`.

If later user testing proves that intermediate-result cards need independent lifecycle, selection, references, or connections, they can become a separate node kind in a later schema revision.

### 3.5 One proposal, one approval, one atomic write

The user does not approve dozens of low-level Builder operations. The complete semantic and spatial result is reviewed as one proposal. The approval token binds the exact plan, map revision, product-structure revision, evidence fingerprint, compiled diff, user, session, and idempotency key.

### 3.6 No arbitrary numeric confidence in v1

V1 uses evidence status and explicit assumptions instead of an uncalibrated confidence percentage. Numeric confidence can be added only after it has a tested interpretation.

### 3.7 Blank-map generation is the first supported write mode

The first release generates into a new or empty map. It does not silently merge into a partially authored map. Partial-map completion and preservation of manual layout are a later phase with separate acceptance criteria.

### 3.8 No new layout engine is required

Use the existing layered arrangement, spatial diagnostics, candidate placement, automatic routing, ghost preview, and fit-to-view systems. ELK, Dagre, or a backend Node.js runtime are not prerequisites for this feature.

## 4. Existing Foundation to Reuse

The implementation should extend these current capabilities rather than recreate them:

- Placement-map schema v3 with product-occurrence, process-step, and junction nodes.
- Stable map identity, source-structure revision, map revision, atomic writes, and conflict handling.
- Existing process operations for placement, steps, junctions, connections, groups, properties, references, routing, movement, and deletion.
- Builder dry-run proposals, exact diffs, approval tokens, idempotency, CAS apply, backups, and receipts.
- Deterministic layered arrangement and world-coordinate geometry.
- Spatial diagnostics for overlaps, clearances, crossings, backward flow, groups, and bounds.
- Automatic connection routing and route fingerprints.
- Managed ghost-node and ghost-wire proposal preview in the process-map editor.
- Existing Floating UI proposal controls.
- Analyze-process-map for read-only questions and required-parts highlighting.
- Native structured tool calls and server-side tool validation.

The new feature is primarily a semantic planning, evidence, validation, and orchestration layer.

## 5. Target Architecture

```text
User generation request
        |
Deterministic scope resolver
        |
Trusted evidence-pack compiler
        |
Sage generate-process-map skill
        |
Semantic Process Plan v1
        |
Semantic schema + deterministic validators
        |
Semantic compiler to temporary placement map
        |
Existing Builder operation handlers
        |
Existing arrangement + routing + spatial diagnostics
        |
Bound semantic/spatial proposal
        |
Complete ghost preview + assumptions summary
        |
One explicit user approval
        |
Revision-aware atomic apply + receipt
```

The browser sends identity and the user's request. It does not send a trusted evidence digest or an authoritative semantic plan.

## 6. Semantic Process Plan v1

### 6.1 Top-level shape

```json
{
  "schemaVersion": 1,
  "planId": "semantic-plan-...",
  "identity": {
    "productId": "racing-bike",
    "mapId": "pm-...",
    "baseRevision": "...",
    "sourceStructureRevision": "...",
    "evidenceFingerprint": "..."
  },
  "scope": {},
  "requiredOccurrences": [],
  "processSteps": [],
  "intermediateResults": [],
  "junctions": [],
  "precedence": [],
  "branches": [],
  "layoutHints": [],
  "evidenceCatalog": [],
  "assumptions": [],
  "unresolvedQuestions": [],
  "coverage": {}
}
```

The schema is strict. Unknown fields are rejected in v1 so malformed model output cannot silently influence compilation.

### 6.2 Identity

Identity is supplied and verified by the server:

```json
{
  "productId": "racing-bike",
  "mapId": "default",
  "baseRevision": "sha256-map-revision",
  "sourceStructureRevision": "sha256-structure-revision",
  "evidenceFingerprint": "sha256-trusted-evidence"
}
```

The model cannot alter these fields. A mismatch rejects the proposal before compilation.

### 6.3 Scope

```json
{
  "assemblyOccurrenceId": "L1-001-02",
  "label": "Front Wheel & Brake",
  "finalOutputOccurrenceId": "L1-001-02",
  "requestType": "generate_complete_process_map"
}
```

Scope resolution occurs against the complete immutable product structure, not only placed canvas nodes.

### 6.4 Required occurrences

Every descendant leaf occurrence must be accounted for exactly once:

```json
{
  "occurrenceId": "L1-001-02-003",
  "itemId": "RB-...",
  "label": "Front Brake Rotor A",
  "role": "input",
  "coverageStatus": "included",
  "reason": null
}
```

Allowed `coverageStatus` values:

- `included`
- `excluded`
- `unresolved`

An excluded occurrence requires a reason and supporting evidence. The model may not omit an occurrence merely because it does not understand its role.

### 6.5 Process steps

```json
{
  "stepId": "step-install-rotors",
  "processType": "operation",
  "label": "Install brake rotors",
  "description": "Install both brake rotors onto the prepared wheel core.",
  "inputs": [
    {"refType": "intermediateResult", "ref": "state-wheel-core"},
    {"refType": "occurrence", "ref": "L1-001-02-003"},
    {"refType": "occurrence", "ref": "L1-001-02-004"}
  ],
  "output": {
    "refType": "intermediateResult",
    "ref": "state-rotor-equipped-wheel"
  },
  "branchId": "wheel-core",
  "stageIndex": 2,
  "knowledgeStatus": "inferred",
  "evidenceRefs": ["evidence-structure-001"],
  "assumptionRefs": ["assumption-rotor-order"],
  "properties": {}
}
```

`processType` uses the existing process-step vocabulary:

- `operation`
- `inspection`
- `decision`
- `input`
- `output`

Manufacturing properties are optional and evidence-gated. The plan must not invent duration, torque, tools, machines, fasteners, consumables, inspection limits, standards, or acceptance criteria.

### 6.6 Intermediate results

```json
{
  "resultId": "state-wheel-core",
  "label": "Wheel core",
  "producedBy": "step-mount-tire",
  "consumedBy": ["step-install-rotors"]
}
```

An intermediate result is semantic state, not a product-structure occurrence and not a standalone canvas card in v1.

### 6.7 Junctions

Junctions describe topology only:

```json
{
  "junctionId": "junction-parallel-preparation",
  "junctionType": "parallel",
  "label": "Parallel preparation"
}
```

The compiler uses only junction types supported by the current schema. A physical join, transformation, fastening, inspection, or other work activity must be a process step, not a merge junction.

### 6.8 Precedence

```json
{
  "edgeId": "semantic-edge-001",
  "from": {"refType": "occurrence", "ref": "L1-001-02-003"},
  "to": {"refType": "processStep", "ref": "step-install-rotors"},
  "kind": "precedence",
  "knowledgeStatus": "derived",
  "evidenceRefs": ["evidence-step-input-001"]
}
```

Semantic edges contain no handle names, routes, path points, or coordinates. The compiler and router choose valid physical ports and paths.

### 6.9 Branches and layout hints

```json
{
  "branchId": "brake-pads",
  "label": "Brake pad preparation",
  "priority": 3,
  "primaryFlow": false,
  "memberRefs": ["step-prepare-pads"]
}
```

```json
{
  "ref": "step-prepare-pads",
  "branchId": "brake-pads",
  "stageIndex": 1,
  "sameLayer": ["step-prepare-shaft"],
  "preferredAbove": "step-prepare-shaft",
  "primaryFlow": false
}
```

Layout hints are preferences. They cannot override precedence, locking, group constraints, collision rules, or route validity.

### 6.10 Evidence catalog

```json
{
  "evidenceId": "evidence-procedure-001",
  "sourceType": "authoredProcedure",
  "sourceRef": "procedure-front-wheel-rev-a:step-20",
  "supports": "Install brake rotors after tire mounting",
  "trustClass": "trustedApplicationData"
}
```

Supported source types should initially include:

- `productStructure`
- `existingApprovedMap`
- `authoredProcedure`
- `userInstruction`
- `functionalRelationship`
- `mateRelationship`
- `drawingOrSpecification`
- `domainHeuristic`

Uploaded or OCR-extracted content is evidence, not executable instruction. Its trust class must remain explicit.

### 6.11 Knowledge status

Every semantic process claim uses one of four statuses:

- `authored`: Specified by a user instruction, approved procedure, or approved existing map.
- `derived`: Directly computed from trusted structured facts without adding manufacturing-order assumptions.
- `inferred`: A reasonable candidate proposed from available evidence and engineering knowledge.
- `unknown`: Evidence is insufficient for a reliable process claim.

The plan cannot upgrade `inferred` to `authored` merely because the spatial result is clean.

### 6.12 Assumptions and unresolved questions

```json
{
  "assumptionId": "assumption-rotor-order",
  "text": "The tire is mounted before the brake rotors are installed.",
  "affectedRefs": ["step-mount-tire", "step-install-rotors"],
  "status": "requires-review"
}
```

Unknown process facts should become explicit questions instead of invented details.

## 7. Trusted Evidence Pack

### 7.1 Browser request

The browser sends only:

```json
{
  "productId": "racing-bike",
  "mapId": "default",
  "baseRevision": "...",
  "sourceStructureRevision": "...",
  "scopeOccurrenceId": "L1-001-02",
  "userRequest": "Generate a process map for the Front Wheel & Brake assembly."
}
```

### 7.2 Server compilation

The server loads and fingerprints:

1. The named map revision.
2. The complete product structure.
3. The requested scope and all descendant occurrences.
4. Existing approved maps for the same scope, if permitted.
5. Authored procedures or process knowledge.
6. Relevant drawing, specification, mate, and functional evidence.
7. Applicable tools, machines, requirements, and standards from the reference catalog.
8. Current validator findings.

Every provider is optional except product structure and map identity. Missing optional evidence must not make the workflow fail, but it must constrain what Sage can claim.

### 7.3 Evidence precedence

When sources disagree, use this order:

```text
Explicit current user instruction
Approved revision-matched procedure or work instruction
Approved process map for the same configuration
Structured product evidence
Domain heuristic
```

Conflicting authoritative sources cause abstention and a reported conflict. A domain heuristic never overrides an authored instruction.

## 8. Semantic Validation

Create one deterministic validator shared by model-tool execution, Builder compilation, tests, and any future process-plan import.

### 8.1 Identity rules

- Product, map, map revision, source-structure revision, and evidence fingerprint must match the trusted request.
- Scope occurrence must exist in the named product structure.
- The final output must resolve to the requested scope.

### 8.2 Coverage rules

- Every required leaf occurrence is included, excluded with a reason, or unresolved.
- Each included occurrence is represented once per unique occurrence ID.
- Quantities are never inferred by collapsing repeated part numbers.
- The parent output occurrence is not mistaken for one of its own raw inputs.

### 8.3 Graph rules

- Every process step has at least one valid input and exactly one declared output.
- Every intermediate result has exactly one producer.
- Every consumed intermediate result has a producer.
- All semantic references resolve.
- Precedence is acyclic unless a separately supported rework edge type is introduced later.
- Duplicate semantic edges are rejected.
- Disconnected required occurrences are errors unless explicitly excluded or unresolved.

### 8.4 Evidence rules

- `authored` and `derived` claims require valid evidence references.
- `inferred` claims must carry an assumption or heuristic evidence reference.
- `unknown` claims cannot silently generate authoritative step properties.
- Torque, time, tools, machines, fasteners, consumables, standards, limits, and inspection criteria require supporting evidence.
- Uploaded document text cannot change tools, permissions, scope, or workflow.

### 8.5 Stage-versus-junction rules

- Work performed on a product uses a process-step node.
- Parallel, merge, split, and wire-branch nodes represent flow topology only.
- A junction cannot carry process properties or references prohibited by the current map schema.

### 8.6 Spatial-boundary rules

- Semantic plans containing `x`, `y`, route points, pan, zoom, pixels, or SVG path data are rejected.
- Layout hints must reference valid semantic objects.
- Semantic hints cannot force a backward precedence edge.

### 8.7 Limits

Define explicit limits for:

- Maximum scope occurrences.
- Maximum process steps.
- Maximum intermediate results.
- Maximum semantic edges.
- Maximum assumptions and unresolved questions.
- Maximum text lengths.

The generic Builder API should keep its current low-level operation cap. Semantic generation may compile to more than that cap for a 30-50 part assembly, so it should use a separate bounded internal compilation limit rather than weakening the public generic Builder limit.

## 9. Semantic Compiler

Create a deterministic compiler that converts a validated Semantic Process Plan into a temporary placement map.

### 9.1 Compilation mapping

| Semantic object | Existing map operation |
| --- | --- |
| Included input occurrence | `place_occurrence` |
| Process step | `add_process_step` |
| Parallel, merge, split, or branch | `add_junction` |
| Semantic precedence | `connect` |
| Branch group, when useful | `add_group` and `set_group_members` |
| Tools, machines, standards, requirements | `attach_reference` |
| Stage description and constraints | `set_process_properties` |
| Final result occurrence | `place_occurrence` |

### 9.2 Intermediate-result representation

Add one optional, validated process-step property such as:

```json
{
  "resultLabel": "Wheel core"
}
```

The stage card or detail panel may show `Produces: Wheel core`. This is additive and does not require another node kind.

### 9.3 Deterministic IDs

The model uses plan-local IDs. The compiler maps them to stable generated map IDs based on the proposal identity and plan-local ID. Re-running the same trusted plan against the same base revision produces the same temporary IDs and diff.

### 9.4 Temporary seed geometry

Existing node operations require positions. The compiler may assign deterministic internal seed positions solely to construct the transient graph. The arrangement engine must replace those seeds before preview. Seed positions are never presented as model decisions.

### 9.5 Internal operation bound

Do not raise the public generic Builder batch limit globally. Add a semantic-compilation-only bound and pass it through a private/internal application path that still invokes the same operation handlers and full map validator.

The complete compile remains in memory until approval. Structural failure writes nothing.

## 10. Deterministic Arrangement and Routing

After semantic compilation:

1. Build the transient graph.
2. Assign ranks from actual precedence.
3. Use branch and stage hints as ordering preferences.
4. Arrange left to right.
5. Place parallel branches in stable vertical lanes.
6. Respect group membership.
7. Choose orientation and port order using current geometry rules.
8. Route all new connections using the existing automatic router.
9. Run spatial diagnostics.
10. Retry bounded alternative orderings when diagnostics exceed thresholds.
11. Fit the camera without rewriting world coordinates.

Required preview quality for a blank-map proposal:

- Zero card overlaps.
- Zero nodes outside map bounds.
- Zero backward precedence edges.
- Zero edge paths through card interiors.
- No invalid group/header intersections.
- Minimal avoidable crossings.
- Stable output for the same inputs and engine versions.

The semantic score and spatial score remain separate in the proposal summary.

## 11. Position Ownership

Position ownership is useful but should not block blank-map v1.

Add a later additive state:

```text
auto    Deterministic layout may reposition the object.
manual  A user moved it; preserve it as a strong constraint.
locked  Never move it automatically.
```

Compatibility policy:

- Newly generated nodes start as `auto`.
- User drag changes `auto` to `manual`.
- Existing persisted unlocked nodes migrate conservatively to `manual`.
- Existing `locked: true` maps to `locked`.
- Current lock UI and validation continue to work during migration.
- Fit-to-view changes only the camera.

Partial-map generation must not begin until this ownership behavior is implemented and tested.

## 12. Sage Skill and Routing

### 12.1 New skill

Create a separate `generate-process-map` skill. Do not overload the read-only `analyze-process-map` skill.

Suggested contract:

```yaml
skill_id: sage.process_map.generate
workflow: process-map-generation
mode: training
required_context:
  - process_map.semantic_evidence
allowed_tools:
  - propose_complete_process_map
side_effect_policy:
  default: proposal_only
```

### 12.2 Tool boundary

Expose one native structured tool:

```text
propose_complete_process_map
```

Its arguments contain identity, scope, and the Semantic Process Plan. They do not contain coordinates or raw Builder operations.

The tool:

1. Verifies identity.
2. Validates the semantic plan.
3. Compiles it into a temporary map.
4. Arranges and routes it.
5. Runs full semantic, schema, and spatial validation.
6. Stores a bound proposal.
7. Returns a proposal receipt and preview summary.

The tool does not save the map.

### 12.3 Routing rules

- Explicit generation verbs route to `process-map-generation`.
- Questions about existing flow route to `process-map-analysis`.
- Required-parts questions continue to use tree highlighting unless the user explicitly asks to generate a map.
- Informational questions receive no write or proposal tool.
- Ambiguous requests ask one concise clarification.
- Existing FAI workflows and compiled prompts must remain unchanged.

## 13. Proposal and Authorization Binding

Extend the current Builder proposal record with:

```json
{
  "proposalType": "semantic_process_map",
  "semanticPlanHash": "...",
  "evidenceFingerprint": "...",
  "sourceStructureRevision": "...",
  "compiledDiffHash": "...",
  "spatialFingerprint": "...",
  "spatialEngineVersion": "...",
  "routerVersion": "..."
}
```

Approval must bind:

- Product ID.
- Map ID.
- Base map revision.
- Source-structure revision.
- Evidence fingerprint.
- Semantic plan hash.
- Exact compiled diff hash.
- Spatial fingerprint and engine versions.
- User and session.
- Idempotency key.

At apply time, reload and revalidate every binding. Any mismatch rejects the operation and leaves the map unchanged.

## 14. User Experience

### 14.1 Entry point

Support both:

- A Sage chat request: `Generate a process map for Front Wheel & Brake.`
- A `Generate Process Map` ribbon command that asks the user to select a structure scope.

The ribbon command should invoke the same agent workflow rather than a separate implementation.

### 14.2 Save and map-state guard

V1 behavior:

- The target map must be empty.
- Dirty state must be saved or discarded before generation.
- If the current map is not empty, offer `Create new map for proposal` or cancel.
- Never erase or merge into an authored map implicitly.

### 14.3 Preview

Render one managed preview using the existing ghost-node and ghost-wire layers.

Preview styling:

- Proposed product occurrences use the existing ghost-card treatment.
- Proposed operation/stage nodes show their labels and result labels.
- Inferred stages have a subtle `Suggested` badge or dashed accent.
- Authored or derived stages use the normal preview treatment.
- Assumption details appear in the review panel, not as large canvas text.
- Unsupported or unresolved items block approval or appear as explicit warnings according to policy.

### 14.4 Review summary

Example:

```text
Front Wheel & Brake proposal

8 of 8 required occurrences included
5 operation stages
2 parallel branches
2 authored or derived steps
3 inferred steps
1 assumption requiring review
0 unresolved occurrences
0 overlaps
0 backward connections
1 avoidable crossing
```

Primary commands:

- `Approve map`
- `Dismiss`
- `Regenerate`
- `Review assumptions`

Approval is disabled when structural errors, unresolved required occurrences, stale revisions, or invalid unsupported claims exist.

### 14.5 Apply receipt

After approval, show what actually happened:

```text
Process map created
9 product occurrences, 5 stages, 2 junctions, and 16 connections added.
Revision: <short revision>
```

One Undo action should restore the prior empty map.

## 15. Implementation Phases

Use `S` prefixes to avoid confusion with the completed spatial phases.

### S0. Preserve the manual Part 1 baseline

Purpose: keep the recording workflow stable before adding autonomous generation.

Work:

- Record the manual Part 1 demo.
- Save the exact demo map and product-structure revisions used.
- Capture current test counts and screenshots in both themes.
- Tag or commit the stable baseline with unrelated work excluded.
- Document the manual demo steps and expected Sage required-parts response.

Exit gate:

- Part 1 video is complete.
- The manual workflow can be reproduced from a clean map.
- No Semantic Process Plan runtime code has landed.

Estimated effort: 0.5 day after recording.

### S1. Semantic schema and validator

Purpose: make process meaning executable and testable before involving a model.

Work:

- Add the Semantic Process Plan v1 typed schema.
- Add deterministic semantic validation and typed findings.
- Add evidence-status and provenance rules.
- Add occurrence-coverage computation.
- Add `resultLabel` to supported process-step properties.
- Add golden fixtures for linear, parallel, nested, repeated, ambiguous, and procedure-backed assemblies.

Artifacts:

- `ai_inspector/process_map/semantic_plan.py`
- `tests/test_process_map_semantic_plan.py`
- `tests/fixtures/process_map_semantic/`

Exit gate:

- Validator catches every rule in Section 8.
- Unsupported authoritative claims and invented numeric properties are rejected.
- Existing map-schema and Builder tests remain unchanged.

Estimated effort: 2-3 focused days.

### S2. Trusted evidence pack and shadow Sage planning

Purpose: prove Sage can produce useful semantic plans without writing or previewing maps.

Work:

- Add deterministic scope resolution against the complete product structure.
- Add trusted evidence-pack providers and fingerprinting.
- Create `generate-process-map` skill and workflow.
- Register the new route and one proposal-only tool contract.
- Run model-generated plans in shadow mode only.
- Store the plan, validation findings, token counts, and provenance for evaluation.
- Add an approved process-knowledge fixture for the Front Wheel & Brake demo rather than hardcoding the expected answer in the prompt.

Artifacts:

- New skill package.
- Evidence-pack module.
- Routing fixtures.
- Shadow semantic-plan evaluation fixtures and reports.

Exit gate:

- Full occurrence coverage on known fixtures.
- Zero unsupported authoritative claims.
- Existing analyze-process-map and FAI routes remain isolated.
- No map proposal or map write is possible yet.

Estimated effort: 3-5 focused days.

Decision gate:

Review real generated plans before authorizing compilation work. If Sage cannot reliably distinguish authored, derived, inferred, and unknown claims, improve the evidence contract and evals rather than compensating in layout code.

### S3. Deterministic semantic compiler

Purpose: convert valid meaning into a valid transient map without frontend work.

Work:

- Add deterministic semantic-plan-to-map compilation.
- Reuse existing operation handlers and full map validation.
- Add stable plan-local to map-ID mapping.
- Add bounded internal operation capacity for semantic compilation.
- Compile intermediate results into stage `resultLabel` metadata.
- Produce an exact temporary diff without writing.

Artifacts:

- `ai_inspector/process_map/semantic_compile.py`
- `tests/test_process_map_semantic_compile.py`

Exit gate:

- Same plan and base revision produce identical map bytes and diff hash.
- Failed compilation never writes.
- Every required occurrence, step, junction, edge, group, reference, and property maps correctly.
- Public low-level Builder operation limits are unchanged.

Estimated effort: 3-4 focused days.

### S4. Spatial composition and bound Builder proposal

Purpose: turn the transient semantic graph into one reviewable spatial proposal.

Work:

- Run existing layered arrangement over the transient graph.
- Apply branch/stage hints as ordering preferences.
- Route every new connection.
- Run spatial diagnostics and bounded retries.
- Extend proposal storage and approval binding with semantic and evidence hashes.
- Add stale-evidence and stale-structure rejection.

Artifacts:

- Semantic proposal endpoint/tool executor.
- Proposal-binding and stale-state tests.
- Golden spatial previews for semantic fixtures.

Exit gate:

- Blank-map proposals have no overlaps, backward edges, or paths through cards.
- Semantic and spatial findings remain separately reported.
- Approval token binds the exact semantic and spatial result.
- No frontend apply path exists until server tests pass.

Estimated effort: 3-4 focused days.

### S5. Complete ghost preview and atomic apply

Purpose: deliver the first usable Part 2 workflow on blank maps.

Work:

- Add the Generate Process Map entry point.
- Reuse managed ghost preview infrastructure.
- Add semantic summary and assumptions review.
- Add approve, dismiss, and regenerate actions.
- Apply through the existing Builder approval and CAS gate.
- Add one-step undo and save/reload verification.
- Gate everything behind a dedicated feature flag.

Feature flag:

```text
INSPECTORPRO_PROCESS_MAP_SEMANTIC_GENERATION
```

Exit gate:

- One request produces one complete preview.
- Dismiss makes no map change.
- One approval applies the exact preview atomically.
- One undo restores the empty map.
- Save/reopen restores the generated map exactly.
- Part 1 manual behavior remains unchanged with the flag off.

Estimated effort: 3-5 focused days.

Decision gate:

Run the Front Wheel & Brake workflow and at least five unseen assemblies. Promote only if semantic evidence quality and user correction burden meet Section 17.

### S6. Position ownership and partial-map completion

Purpose: let generation cooperate with user-authored content safely.

Work:

- Add `auto`, `manual`, and `locked` ownership behavior.
- Mark generated objects `auto` and user-dragged objects `manual`.
- Preserve manual positions as strong constraints.
- Preserve locked positions as hard constraints.
- Detect and reuse existing occurrence cards and compatible stages.
- Preview only the proposed additions and required moves.
- Require explicit `Complete current map` wording for partial-map generation.

Exit gate:

- No duplicate product occurrence is added.
- Locked content never moves.
- Manual content moves only when explicitly reviewed in the diff.
- Existing edges and groups are preserved unless the exact diff says otherwise.
- Partial generation remains one atomic approval.

Estimated effort: 4-6 focused days.

### S7. Evaluation, soak, and default-on decision

Purpose: establish that the feature is dependable beyond the demo assembly.

Work:

- Run semantic and spatial fixture suites.
- Run adversarial trust-boundary tests.
- Run unseen product structures and process procedures.
- Conduct a self-use soak on real maps.
- Record user corrections and regeneration reasons.
- Compare generated maps with an engineer-authored reference.
- Measure latency, tokens, proposal size, and approval outcomes.
- Decide whether the feature remains beta, becomes opt-in, or defaults on.

Exit gate:

- All hard quality thresholds pass.
- No unauthorized or partial writes occur.
- No prompt-injected evidence changes tools, scope, or permissions.
- The manual workflow remains available as a fallback.

Estimated effort: 3-5 focused days plus soak time.

## 16. Evaluation Fixtures

Include at least:

1. Simple linear assembly.
2. Parallel branches that converge.
3. Nested subassemblies.
4. Repeated occurrences of one part number.
5. Mirrored left/right components.
6. Shared fasteners across multiple operations.
7. Authored procedure with exact order.
8. No process-order evidence.
9. Conflicting procedure and user instruction.
10. Ambiguous order with multiple valid proposals.
11. Large 30-50 occurrence assembly.
12. Partial map with manual nodes.
13. Partial map with locked nodes.
14. Revision that adds or removes components.
15. Uploaded document containing prompt-injection text.

The Front Wheel & Brake fixture should include all eight real occurrences and an authored, revisioned process-knowledge artifact for the demonstration. The fixture must be data, not wording embedded in the Sage prompt.

## 17. Quality Metrics and Thresholds

### 17.1 Deterministic semantic metrics

- Required occurrence coverage: 100%.
- Unique occurrence identity correctness: 100%.
- Final-result correctness: 100%.
- Dangling semantic references: 0.
- Invalid cycles: 0.
- Unsupported authoritative manufacturing claims: 0.
- Invented numeric manufacturing parameters: 0.
- Incorrect stage-versus-junction usage on labeled fixtures: 0.
- Evidence-label accuracy on golden fixtures: 100%.

### 17.2 Spatial metrics

- Node overlap: 0.
- Node out of bounds: 0.
- Backward precedence edges: 0.
- Routed edge through card interior: 0.
- Invalid group intersection: 0.
- Avoidable crossings: below fixture-specific threshold.
- Deterministic output for identical inputs: 100%.

### 17.3 Product metrics during soak

- Approval without semantic edit.
- Number of assumptions reviewed.
- User correction count per generated map.
- Regeneration count and reason.
- Time from request to usable map.
- Percentage of inferred versus authored steps.
- Dismissal rate.

Do not treat a high approval rate as proof of engineering correctness without reference-map or engineer review.

## 18. Test Strategy

### 18.1 Python

- Semantic schema and validator matrix.
- Evidence-pack determinism and fingerprinting.
- Trusted-context injection rejection.
- Compiler determinism and complete occurrence coverage.
- Generic Builder cap remains enforced.
- Semantic internal bound enforced.
- Dry-run never writes.
- Failed compile never writes.
- Proposal hash and approval-token binding.
- Stale map, structure, or evidence rejection.
- Idempotent apply.
- One-step revert and backup behavior.
- Router isolation for FAI, analysis, required-parts, and generation.

### 18.2 Node harness

- Preview-state lifecycle.
- Semantic status rendering.
- Assumption-summary behavior.
- One active proposal surface.
- Dismiss leaves map fingerprint unchanged.
- Approve dispatches one bound proposal ID.
- Generated `auto` ownership and user-drag transition to `manual` in S6.

### 18.3 Playwright

- Empty map -> generation request -> complete preview.
- Front Wheel scope resolves from the full tree when absent from canvas.
- Preview contains all required cards, stages, junctions, and wires.
- Inferred stages are visibly distinguished.
- Assumptions panel is keyboard accessible.
- Dismiss leaves the map empty.
- Approve applies once.
- Undo returns to empty map in one action.
- Save/reload is exact.
- Stale revision invalidates an open preview.
- Tab switch and editor destroy leave no preview residue.
- Both themes.
- No page or console errors.
- Flag off preserves the current manual workflow.
- Partial-map request is rejected or redirected to a new map before S6.

### 18.4 Model evaluation

- Use shadow runs before enabling preview.
- Evaluate known and unseen assemblies.
- Separate scope-resolution, occurrence-coverage, semantic correctness, evidence classification, and language quality.
- Record exact expected Semantic Process Plan properties, not only whether the final prose sounds plausible.
- Use a model verifier only for high-risk or conflicting plans, not every simple case.

## 19. Current Regression Bars

At S0, recapture and pin the exact baseline. The most recently reported process-map bars are:

```text
Backend process-map suite: 174 passed
Editor node harness: 71/71
Spatial JS harness: 43/43
Floating-surface harness: 14/14
Process-map Playwright smoke: 182/182
Legacy Training: 15 passed / 8 known fixture failures
```

The implementation must add tests rather than weaken, delete, or rewrite existing assertions to force a pass. The eight known legacy failures must retain the same documented causes unless repaired in a separately scoped change.

## 20. Security and Trust Boundaries

- The browser cannot supply trusted evidence or replace the server evidence pack.
- Uploaded documents cannot expose tools or change authorization.
- The model receives no direct file-write tool.
- The generation tool creates a proposal, not a saved mutation.
- Approval is tied to the current user/session and exact proposal.
- Every map write uses the current CAS and atomic repository path.
- Model-generated IDs and references are resolved against known entities.
- Secrets and external URLs never enter the semantic plan.
- Raw customer geometry should not be copied into telemetry or model-eval artifacts by default.

## 21. Observability

Record:

- Workflow and skill versions.
- Model and prompt-module versions.
- Plan schema version.
- Map, structure, evidence, and plan hashes.
- Semantic validation finding codes.
- Counts by knowledge status.
- Compiled object counts.
- Spatial diagnostics aggregates.
- Proposal, approval, dismissal, and apply outcomes.
- Router, model, compiler, layout, and total latency.
- Input and output tokens.

Do not log full proprietary procedures, raw CAD geometry, or user-authored notes unless an explicit debugging mode permits it.

## 22. Failure Behavior

| Failure | Behavior |
| --- | --- |
| Scope not found | Ask one concise clarification and show matching scopes. |
| Scope absent from canvas | Continue; the full product structure is authoritative for scope existence. |
| Missing process evidence | Produce a clearly inferred minimal proposal or ask targeted questions. |
| Required occurrence unresolved | Block approval and identify it. |
| Conflicting authoritative evidence | Abstain and show the conflict. |
| Unsupported torque/tool/time claim | Reject the claim during semantic validation. |
| Semantic cycle | Reject before compilation. |
| Spatial threshold failure | Retry bounded alternatives, then return a reviewable failure without writing. |
| Stale map/structure/evidence | Invalidate preview and require regeneration. |
| Model timeout | Leave the map unchanged and offer retry. |
| Builder apply conflict | Keep the proposal closed and show reload/regenerate options. |

## 23. Risks and Mitigations

### Risk: A plausible map is mistaken for an approved process

Mitigation: Persistent authored/derived/inferred/unknown status, visible assumptions, and no promotion based on layout quality.

### Risk: Product structure is used as sequence proof

Mitigation: Deterministic evidence rules and fixtures with no process-order evidence.

### Risk: The model omits inconvenient components

Mitigation: Server-derived complete occurrence inventory and 100% coverage validation.

### Risk: Large plans exceed Builder operation limits

Mitigation: Separate bounded internal semantic compilation path; keep the generic public limit unchanged.

### Risk: Autonomous generation damages an authored map

Mitigation: Blank-map-only v1, one atomic proposal, explicit partial-map phase later.

### Risk: Preview differs from applied result

Mitigation: Bind semantic hash, exact diff hash, spatial fingerprint, revisions, and engine versions in the approval token; revalidate at apply.

### Risk: Demo quality is achieved by prompt hardcoding

Mitigation: Store approved process knowledge as revisioned evidence and run unseen-assembly evaluations.

### Risk: A clean layout hides semantic uncertainty

Mitigation: Separate semantic and spatial summaries and scores.

### Risk: Position ownership creates dual-state drift with `locked`

Mitigation: Add one compatibility helper and migrate through a dedicated S6 checkpoint, not ad hoc conditionals.

## 24. Rollback

The entire autonomous generation capability is behind:

```text
INSPECTORPRO_PROCESS_MAP_SEMANTIC_GENERATION
```

With the flag off:

- Sage required-parts highlighting remains available.
- Manual tree drag/drop remains available.
- Manual stage, junction, group, connection, arrangement, and routing behavior remains available.
- Existing Builder and spatial tools remain unchanged.
- No new semantic proposal endpoint or tool is exposed to the model.
- Persisted v1 maps remain readable because new process properties are additive.

No rollback may strand a partially applied map because semantic generation writes only through the existing atomic apply path.

## 25. First Demonstration Contract

The first complete autonomous demo should be intentionally narrow:

```text
User: Generate a process map for the Front Wheel & Brake assembly.
```

Expected result:

1. Scope resolves to the exact Front Wheel & Brake occurrence from the full structure tree.
2. All eight required leaf occurrences are included once.
3. The final Front Wheel & Brake subassembly appears as the output.
4. Meaningful operations are represented by stage nodes.
5. Parallel work uses branches or parallel junctions only where semantically appropriate.
6. Unsupported torque, duration, tooling, and standards are omitted.
7. Authored steps cite the approved process fixture.
8. Inferred steps are visibly marked and summarized as assumptions.
9. The layout is left-to-right, collision-free, and routed cleanly.
10. One preview is shown and one approval creates the entire map.

This demonstration should not claim that every manufacturing process can be inferred from CAD alone. It should show that InspectorPro combines product structure, available process evidence, engineering reasoning, deterministic validation, and layout automation into a reviewable proposal.

## 26. Definition of Done

Part 2 is complete when:

1. A user can request a complete map for a named assembly scope in plain language.
2. Scope resolution uses the complete product structure, independent of current canvas placement.
3. Every required occurrence is accounted for by stable occurrence ID.
4. Sage produces a strict, provenance-aware Semantic Process Plan with no coordinates.
5. Unsupported authoritative claims and invented manufacturing parameters are blocked deterministically.
6. Builder compiles the plan into one temporary transaction using existing map operations.
7. Existing arrangement and routing systems produce a clean complete ghost preview.
8. Semantic uncertainty and spatial quality are reported separately.
9. Dismissal changes nothing.
10. One explicit approval applies exactly the reviewed proposal atomically.
11. Stale map, product structure, or evidence prevents application.
12. Undo, save, reload, backups, conflicts, and receipts work as they do for manual maps.
13. The manual Part 1 workflow remains fully usable with the feature disabled.
14. The Front Wheel fixture and unseen assembly evaluations meet the thresholds in Section 17.

## 27. Recommended Delivery Boundary

Treat S0-S5 as the committed v1 scope after the manual recording. This delivers complete generation into a blank map.

Treat S6-S7 as a second approval boundary. Partial-map completion and automatic/manual position ownership should proceed only after blank-map generation proves semantically useful on real fixtures.

Expected focused engineering effort for S1-S5: approximately 14-21 days, excluding model-evaluation iteration. S6-S7 add approximately 7-11 focused days plus soak time.

The governing principle is:

> Sage decides what the proposed process means. Deterministic InspectorPro systems decide whether it is supported, where it goes, how it connects, and whether it is safe to apply.
