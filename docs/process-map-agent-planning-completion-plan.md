# Process Map Agent Planning Completion Plan

Revision: 2

Status: Ready for review. This is a planning contract only.

Date: 2026-07-24

Related architecture contract:
`docs/process-map-semantic-generation-plan.md`

Assembly preparation prerequisite:
`docs/assembly-knowledge-package-preparation-plan.md`

## 1. Objective

Complete the semantic planning layer until this statement is true:

> Given an exact assembly scope and the available trusted process evidence,
> Sage produces one complete, provenance-aware Semantic Process Plan that
> passes deterministic validation before InspectorPro creates any preview.

This plan starts from the runtime foundation already implemented on
2026-07-23. It does not rebuild Builder, layout, routing, preview, approval,
revision control, or persistence.

## 2. Verified Starting Point

The following capabilities already exist:

- Placement-map schema v3 with product-occurrence, process-step, and junction
  nodes.
- `positionMode: auto | manual | locked`.
- Revision-aware map and product-structure loading.
- Trusted `process_map.graph` and `process_map.state` context.
- A `generate-process-map` Sage skill and `process-map-generation` workflow.
- A single high-level `build_process_map_preview` tool.
- Semantic Process Plan validation and deterministic compilation.
- Deterministic IDs, world-coordinate placement, orthogonal routing, spatial
  diagnostics, and complete ghost preview.
- Exact-diff approval, CAS apply, atomic persistence, undo, and canonical
  Builder receipts.
- Server-side rejection of browser-supplied graph, state, proposal, and receipt
  authority.

Verified regression bars at the start of this plan:

```text
Process-map Python suite: 188 passed
Process-map editor harness: 72/72
Process-map spatial harness: 44/44
Floating-surface harness: 14/14
Process-map Playwright smoke: 189/189
Syntax and git diff audit: clean
```

### 2.1 Primary reference product

The primary implementation and demonstration target is now the Tricycle
assembly supplied at:

```text
C:\Users\might\OneDrive\Desktop\Tricyle\SWPR-Tricycle.SLDASM
```

The source package was inspected on 2026-07-24 and contains one native
SolidWorks assembly plus 18 native SolidWorks part files. The misspelled
source-folder name remains untouched; the InspectorPro product ID and
user-facing name are `tricycle` and `Tricycle`.

This is a stronger primary reference than the racing-bike fixture because it
has native source CAD. It also appears suitable for repeated-occurrence and
parallel-branch evaluation through wheels, grips, pedals, caps, and spacers.

The source package contains no nested `.SLDASM` files. The first product
structure will therefore be a root assembly with part occurrences. Semantic
intermediate results and process branches may be created by the process plan,
but the importer and Sage must not invent product subassemblies that do not
exist in the source CAD.

Exact occurrence counts, component paths, quantities, suppression state,
mates, and native occurrence IDs remain unknown until extraction. This plan
does not assign them by filename or guess them from the 18 unique part files.
The source directory is read-only input; imported artifacts belong under
`generated/training/tricycle/`.

The racing-bike and Front Wheel assets remain useful deterministic regression
fixtures. They are no longer the primary real-CAD milestone or evidence source.

## 3. Remaining Gaps

The execution machinery is ahead of the planning quality. The remaining gaps
are:

1. Sage receives product structure and map state, but no dedicated trusted
   manufacturing-evidence pack.
2. The provider tool schema constrains the outer tool arguments but leaves the
   nested `semantic_plan` object structurally broad.
3. Backend semantic validation is strong on graph meaning, but it does not yet
   reject every unknown field at every schema level.
4. Evidence records are syntactically checked, but their `sourceRef` values are
   not resolved against a server-built evidence catalog.
5. Edge and precedence evidence is not fully preserved. The current compiler
   marks generated connections as inferred even when an authoritative source
   establishes the relationship.
6. The Tricycle source CAD has not yet been extracted into a revisioned
   product structure, stable occurrence catalog, and visual package.
7. No shadow evaluation currently measures real Sage-generated Semantic
   Process Plans.
8. There are deterministic plan tests, but not the required model fixtures for
   linear, parallel, nested, repeated, ambiguous, conflicting, and no-evidence
   cases.
9. The proposal binding contains the plan, operation, map, and structure
   hashes, but no independent trusted evidence-pack fingerprint.
10. The existing feature can create a preview as soon as a syntactically valid
    tool call arrives. It needs an explicit planning-quality gate first.

## 4. Scope

### 4.1 Included

- Exact assembly/subassembly scope resolution.
- Trusted process-evidence compilation.
- Native occurrence identity normalization.
- A strict provider and backend Semantic Process Plan schema.
- Evidence-reference validation.
- Process-step, intermediate-result, branch, junction, and precedence
  planning.
- Model shadow runs and structured evaluation.
- A validated-plan envelope bound to map, structure, and evidence revisions.
- Handoff of only a validated plan to the existing preview compiler.

### 4.2 Excluded

- Partial-map completion or merge into authored maps.
- New layout or routing algorithms.
- Direct ERP, MES, PLM, or work-instruction connectors.
- Automatic approval or automatic persistence.
- Production certification of illustrative process data.
- Model-generated coordinates, ports, waypoints, or Builder operations.
- A second user-facing planning tool.
- Redesign of the Process Map editor.

The first supported target remains an empty map.

## 5. Target Planning Pipeline

```text
User generation request
        |
Deterministic workflow and scope resolution
        |
Revision-bound Process Map Environment Contract
        |
Trusted scoped Process Evidence Pack
        |
Sage generate-process-map skill
        |
Strict Semantic Process Plan candidate
        |
JSON-shape validation
        |
Evidence and semantic validation
        |
Planning quality gate
        |
Validated Semantic Plan Envelope
        |
Existing preview compiler, layout, routing, and approval pipeline
```

The milestone governed by this document ends at the Validated Semantic Plan
Envelope. The existing preview system consumes that envelope next.

## 6. Trusted Process Evidence Pack v1

Add one server-generated context provider:

```text
process_map.evidence
```

The browser may name the current map and revision. It may not provide,
supplement, or override this evidence pack.

### 6.1 Shape

```json
{
  "schemaVersion": 1,
  "identity": {
    "productId": "tricycle",
    "mapId": "default",
    "mapRevision": "sha256",
    "structureRevision": "sha256",
    "scopeOccurrenceId": "<extracted-root-occurrence-id>",
    "evidenceFingerprint": "sha256"
  },
  "scope": {
    "occurrenceId": "<extracted-root-occurrence-id>",
    "name": "Tricycle",
    "kind": "assembly"
  },
  "occurrences": [],
  "sources": [],
  "claims": [],
  "resources": [],
  "conflicts": [],
  "unresolved": [],
  "policy": {
    "assemblyStructureProvesMembershipOnly": true,
    "manufacturingOrderRequiresProcessEvidence": true,
    "illustrativeSourcesAreNotProductionApproved": true
  }
}
```

### 6.2 Occurrence records

Include only the requested scope, its ancestors needed for identity, and its
descendants:

```json
{
  "occurrenceId": "<extracted-component-path-id>",
  "parentOccurrenceId": "<extracted-root-occurrence-id>",
  "itemId": "<source-part-identity>",
  "name": "SWPR-Tricycle_Big Wheel",
  "kind": "part",
  "quantity": 1,
  "suggestedBuildOrder": 102.01
}
```

`suggestedBuildOrder` is supporting evidence, not authoritative process order.

### 6.3 Source records

Each evidence source declares both provenance and authority:

```json
{
  "sourceId": "process-source:tricycle-assembly-process-v1:A",
  "sourceType": "process_knowledge",
  "revision": "A",
  "contentHash": "sha256",
  "authority": "authored",
  "trusted": true,
  "title": "Tricycle Final Assembly Process"
}
```

Allowed authority values:

```text
approved       Approved procedure, work instruction, or reviewed process map.
authored       User-authored source whose approval status is not asserted.
illustrative   Demonstration or training source; never production-approved.
supporting     Product structure, mate, geometry, naming, or heuristic evidence.
untrusted      Uploaded or external content that may be cited but cannot set policy.
```

Authority and knowledge status remain separate:

- `authored` knowledge status means the plan faithfully reflects a source.
- Source authority determines whether that source is approved, illustrative,
  supporting, or untrusted.

### 6.4 Claim records

Convert source content into bounded structured claims:

```json
{
  "claimId": "claim:tricycle:operation-001",
  "sourceId": "process-source:tricycle-assembly-process-v1:A",
  "claimType": "operation_definition",
  "subjectRef": "operation-001",
  "objectRefs": [
    "<extracted-occurrence-id-a>",
    "<extracted-occurrence-id-b>"
  ],
  "value": "<reviewed operation label>",
  "authority": "authored"
}
```

Initial claim types:

```text
component_membership
operation_definition
operation_consumes
operation_produces
precedes
parallel_with
requires_resource
requirement
suggested_order
```

The model cites claim IDs. It does not cite arbitrary filenames or invent
source references.

### 6.5 Determinism and budget

- Canonical ASCII JSON determines `evidenceFingerprint`.
- Scope filtering occurs before token budgeting.
- Exact IDs, source revisions, authority, claims, and conflicts are never
  summarized away.
- Long notes may be bounded or summarized with their source hash retained.
- If required claims cannot fit the evidence budget, planning fails with
  `process_evidence_budget_exceeded`; it does not silently omit claims.
- Initial evidence-pack target: no more than 3,000 estimated tokens for the
  extracted Tricycle scope.

## 7. Tricycle Intake and Evidence Authoring

The native source package is:

```text
C:\Users\might\OneDrive\Desktop\Tricyle\
```

It contains one `SWPR-Tricycle.SLDASM` and 18 referenced `.SLDPRT` files. It
does not yet contain an InspectorPro product structure or an authoritative
manufacturing sequence.

### 7.1 CAD intake

Run the existing SolidWorks extraction path against a read-only copy or direct
read of the source package. Produce:

```text
generated/training/tricycle/tricycle_product_structure.json
generated/training/tricycle/assembly_extracts/
generated/training/tricycle/assembly_glb/
generated/training/tricycle/part_glb/
generated/training/tricycle/part_previews/
generated/training/tricycle/source_manifest.json
```

The source manifest must record:

```text
root assembly path and content hash
referenced component paths and content hashes
configuration
extraction tool version
extraction timestamp
unresolved, suppressed, lightweight, or missing references
```

Occurrence identity must be derived from the extracted assembly component
instance path, not only from filename or part number. Repeated instances of one
part file must receive separate stable occurrence IDs. Re-extracting identical
source content and configuration must produce the same IDs.

Extraction fails closed for the planning milestone when:

- a referenced component is missing or unresolved;
- two occurrences receive the same identity;
- a component path cannot be tied to a source part;
- the root assembly or configuration changes during extraction; or
- the structure and visual package do not share one source revision.

### 7.2 Process-knowledge source

CAD structure, transforms, geometry, and mates may support membership,
orientation, contact, and likely grouping. They do not prove manufacturing
order.

Create a separate reviewed artifact:

```text
generated/training/tricycle/process_knowledge/
  tricycle-final-assembly-process-v1.json
```

The artifact must bind every occurrence-bearing input to an extracted native
occurrence ID and define:

```text
operations and intermediate results
precedence and parallel branches
consumed and produced entities
resources and requirements when known
evidence and assumptions
revision and source authority
```

Likely visual branches suggested by filenames include chassis/steps, front
fork and wheel, rear wheels, steering/handlebars, and seat/final assembly.
These are candidate authoring aids only. They do not enter the trusted evidence
pack until reviewed and written into the process-knowledge artifact.

Until an engineer marks the source approved, use `authority: authored` or
`authority: illustrative` and set `productionEligible: false`. Code changes
cannot promote it to an approved work instruction.

### 7.3 Regression role of the racing bike

Keep:

```text
generated/training/racing-bike/process_knowledge/front-wheel-process-demo.json
```

as an illustrative deterministic fixture for compatibility, metadata, and
spatial regression tests. It must not be used to claim that the primary
real-CAD milestone passed.

## 8. Strict Semantic Process Plan Contract

Keep the current model-facing concepts:

```text
schemaVersion
planId
scope
requiredOccurrences
operations
intermediateResults
junctions
branches
layoutHints
evidence
assumptions
unresolvedQuestions
```

### 8.1 One shared schema

Create one schema function used by:

1. The provider-native `build_process_map_preview` tool definition.
2. Backend structural validation.
3. Golden fixture validation.
4. The shadow evaluation harness.

The nested `semantic_plan` object must no longer be an unconstrained object.

Every object uses `additionalProperties: false`. Add explicit:

- maximum string lengths,
- maximum array lengths,
- enumerations,
- required fields,
- stable identifier patterns,
- relationship metadata,
- and no spatial fields.

### 8.2 Evidence references

Every semantic claim cites one or more evidence-pack claim IDs:

```json
{
  "sourceType": "process_knowledge",
  "sourceRef": "claim:front-wheel:op-mount-tire",
  "supports": "candidate-operation"
}
```

Validation must confirm:

- `sourceRef` exists in the current evidence pack.
- Its source type and authority match the claim.
- The claim supports the referenced operation or relationship.
- An illustrative source cannot make the plan production-eligible.
- Supporting product evidence cannot make manufacturing order authoritative.
- Untrusted content cannot change scope, tools, permissions, or authority.

Add `process_knowledge` to the supported semantic evidence source types. A
claim derived from a nested standard or work instruction may use that narrower
source type only when the pack contains the corresponding registered source.

### 8.3 Relationship provenance

Preserve evidence for generated connections instead of marking every edge with
a generic planner heuristic.

Extend operation and junction endpoint relationships with:

```text
knowledgeStatus
evidence
assumptionIds
```

The compiler copies this metadata onto the resulting precedence edge.

There must be one semantic owner for each relationship. Do not maintain an
independent, contradictory edge list and operation-input list.

### 8.4 Required semantic rules

The validator must enforce:

- The scope matches the server-resolved assembly occurrence.
- Every descendant leaf occurrence appears exactly once.
- No occurrence outside the scope is included.
- Exactly one operation produces the requested final subassembly.
- Every intermediate result has exactly one producer.
- Every consumed intermediate result has a producer.
- Every relationship resolves to known semantic entities.
- The semantic graph is acyclic.
- Junctions carry topology only.
- Physical joining or transformation uses an operation/stage.
- Authored and derived claims have valid evidence.
- Inferred claims have evidence or a declared assumption.
- Unknown claims do not silently become operations.
- Manufacturing numeric values require suitable source authority.
- Conflicting authoritative evidence blocks the plan.
- Unknown fields and spatial fields are rejected.

## 9. Validated Semantic Plan Envelope

The model returns only the plan candidate. The server creates the envelope:

```json
{
  "schemaVersion": 1,
  "identity": {
    "productId": "tricycle",
    "mapId": "default",
    "baseRevision": "sha256",
    "structureRevision": "sha256",
    "scopeOccurrenceId": "<extracted-root-occurrence-id>",
    "evidenceFingerprint": "sha256"
  },
  "plan": {},
  "planHash": "sha256",
  "findings": [],
  "metrics": {
    "requiredOccurrenceCoverage": 1.0,
    "unsupportedAuthoritativeClaimCount": 0,
    "unresolvedCount": 0
  },
  "sourceAuthorityCounts": {},
  "productionEligible": false
}
```

The existing preview proposal binding must include
`evidenceFingerprint`. Any change to the map, structure, scope, or evidence
invalidates the handoff.

## 10. Planner Execution Policy

### 10.1 Normal request

```text
Generate a process map for the Tricycle assembly.
```

Execution:

1. Route to `process-map-generation`.
2. Deterministically resolve exactly one assembly/subassembly scope. Part
   occurrences are not valid complete-map generation scopes in v1.
3. Verify empty, saved, non-conflicted map state.
4. Compile the evidence pack from current server assets.
5. Compile the skill with `process_map.state` and
   `process_map.evidence`.
6. Expose only `build_process_map_preview`.
7. Receive one Semantic Process Plan candidate.
8. Validate shape, evidence, semantics, and quality.
9. Produce a Validated Semantic Plan Envelope.
10. Only then pass it to the existing preview compiler.

### 10.2 Invalid first plan

The first implementation does not silently repair semantic meaning.

- Schema-only formatting errors may receive one bounded correction attempt
  after shadow evaluation proves the behavior reliable.
- Evidence conflicts, unsupported claims, missing scope, or ambiguous meaning
  must fail closed.
- Before a repair loop is enabled, an invalid plan produces no preview and a
  concise failure summary.

Decision gate:

> Add one model correction pass only if first-pass structural validity remains
> below the target after the schema and skill are improved.

### 10.3 No process-order evidence

The planner may produce a minimal inferred proposal only when:

- every operation is marked `inferred`,
- every operation cites supporting evidence or an explicit assumption,
- no unsupported numeric manufacturing values are present,
- and the response clearly states that manufacturing order requires review.

It must never convert `suggestedBuildOrder`, BOM order, or mate structure into
an authored process sequence.

## 11. Implementation Phases

### G0. Reconcile and freeze the planning boundary

Purpose: establish the exact current baseline and prevent duplicate work.

Work:

- Mark the original semantic-generation plan as foundation architecture.
- Pin the regression bars listed in Section 2.
- Keep semantic generation opt-in during model-quality work.
- Record the current provider, model, skill version, and prompt hash in eval
  artifacts.

Exit gate:

- No runtime behavior changes.
- Existing 188/72/44/14/189 bars remain green.

Estimated effort: 0.5 day.

### G1. Strict schema and evidence-reference validation

Purpose: make every model output structurally exact before adding evidence.

Work:

- Add the shared nested JSON schema.
- Reject unknown fields at all levels.
- Add bounded relationship provenance.
- Validate every evidence reference against an injected claim index.
- Preserve relationship evidence on compiled edges.
- Add typed finding codes for every rejection.

Primary files:

```text
ai_inspector/process_map/semantic_plan.py
ai_inspector/process_map/schema_v3.py
tests/test_process_map_semantic_plan.py
```

Exit gate:

- Provider schema and backend validator accept and reject the same fixtures.
- Unknown and spatial fields always fail.
- No connection loses its semantic evidence classification.
- Existing deterministic compiler fixtures remain stable or migrate through an
  explicit fixture revision.

Estimated effort: 1-2 focused days.

### G2. Tricycle intake and trusted scoped evidence-pack compiler

Purpose: give Sage manufacturing evidence rather than expecting it to infer
process truth from map structure.

The generic intake, visual evidence, AI enrichment, cost, review, and package
publication work is governed by
`docs/assembly-knowledge-package-preparation-plan.md`. This phase consumes that
published package rather than implementing a Tricycle-only preparation path.
Its P0.5 extraction-reconnaissance gate must pass before this phase estimates
or implements CAD intake.

Work:

- Add `ai_inspector/process_map/evidence.py`.
- Compile scope-limited occurrence, source, claim, resource, conflict, and
  unresolved records.
- Add canonical hashing and hard token budgeting.
- Extract the Tricycle assembly into a revisioned product structure, stable
  occurrence catalog, source manifest, and visual package.
- Author and review the versioned Tricycle process-knowledge source separately
  from CAD-derived evidence.
- Bind every occurrence-bearing process claim to extracted native occurrence
  IDs.
- Add `process_map.evidence` to the context-provider registry.
- Version the generation skill to require `process_map.state` and
  `process_map.evidence`. The broad graph remains available to deterministic
  routing and scope resolution but is not duplicated in the final planning
  prompt.
- Build evidence only after deterministic scope resolution.
- Ignore all browser-supplied evidence content.

Primary files:

```text
ai_inspector/process_map/evidence.py
ai_inspector/prompts/context.py
ai_inspector/agent_skills/generate-process-map/manifest.yaml
ai_inspector/agent_skills/generate-process-map/contract.yaml
ai_inspector/agent_skills/generate-process-map/SKILL.md
generated/training/tricycle/tricycle_product_structure.json
generated/training/tricycle/source_manifest.json
generated/training/tricycle/process_knowledge/tricycle-final-assembly-process-v1.json
server.py
tests/test_process_map_evidence.py
```

Exit gate:

- Same assets and revisions produce byte-identical packs and fingerprints.
- Every Tricycle source component resolves to stable native occurrences without
  runtime label matching.
- Repeated source-part instances retain distinct occurrence identities and
  correct quantities.
- The source manifest reports no unresolved component references.
- Missing, duplicate, ambiguous, and out-of-scope bindings fail closed.
- Browser evidence injection is ignored.
- The pack remains within budget without dropping required claims.

Estimated effort: 3-5 focused days, including extraction and engineering
review of the initial process source.

### G3. Reference plans and semantic evaluation fixtures

Purpose: define what a good plan means before tuning the model.

Fixtures:

1. Linear two-part assembly.
2. Parallel branches that converge.
3. Nested subassemblies.
4. Repeated occurrences of one part number.
5. Mirrored left/right components.
6. Authored procedure with exact order.
7. No process-order evidence.
8. Conflicting procedure and user statement.
9. Ambiguous sequence with multiple valid answers.
10. Prompt-injection content inside an uploaded source.
11. Tricycle with the complete extracted occurrence set and reviewed expected
    process invariants.
12. Large 30-50 occurrence assembly.

Each fixture stores expected invariants, not only one exact prose answer:

```text
required occurrence set
final result
required/forbidden operations
allowed ordering alternatives
expected evidence classes
expected assumptions
forbidden manufacturing claims
expected unresolved items
stage-versus-junction expectations
```

Primary artifacts:

```text
tests/fixtures/process_map_semantic_generation/
tests/test_process_map_evidence.py
tests/test_process_map_semantic_plan.py
```

Exit gate:

- Deterministic fixtures cover every hard validator rule.
- Tricycle reference invariants reflect the reviewed process source, not
  filenames, CAD mates, or prompt wording.
- No fixture requires one arbitrary layout or sentence formulation.

Estimated effort: 1-2 focused days.

### G4. Shadow Sage planning harness

Purpose: measure actual model planning without creating previews or writes.

Work:

- Add `tests/eval_process_map_semantic_generation.py`.
- Use the production skill, prompt compiler, context compiler, provider adapter,
  and native tool schema.
- Intercept the tool call before proposal execution.
- Validate the returned plan against the exact evidence pack.
- Record hashes, counts, finding codes, latency, and token usage.
- Do not store full proprietary source text by default.
- Run known fixtures and unseen structures separately.

Shadow artifact:

```json
{
  "caseId": "front-wheel-authored-illustrative",
  "provider": "configured-provider",
  "model": "configured-model",
  "skillVersion": "1.1.0",
  "promptHash": "sha256",
  "evidenceFingerprint": "sha256",
  "planHash": "sha256",
  "valid": true,
  "metrics": {},
  "findingCodes": []
}
```

Exit gate:

- Shadow mode cannot create a Builder proposal or write a map.
- Provider failures are reported separately from semantic failures.
- Repeated runs retain occurrence identity and evidence safety.
- FAI and read-only Process Map routes remain unchanged.

Estimated effort: 2-3 focused days.

### G5. Skill refinement and quality gate

Purpose: make first-pass model output dependable enough to hand to preview.

Work:

- Refine the Environment Contract using observed failures.
- Keep examples synthetic; do not embed Tricycle answers in the skill.
- Tighten the tool description where model errors cluster.
- Add one correction-pass experiment only if first-pass structural validity
  remains below threshold.
- Re-run known and unseen evaluations after every prompt or schema revision.
- Freeze a skill version only after all hard thresholds pass.

Hard thresholds:

```text
Required occurrence coverage: 100%
Native occurrence identity correctness: 100%
Final-result correctness: 100%
Dangling semantic references: 0
Invalid semantic cycles: 0
Unsupported authoritative claims: 0
Invented numeric manufacturing parameters: 0
Unknown evidence references: 0
Prompt-injection policy changes: 0
Incorrect stage-versus-junction use on labeled fixtures: 0
```

Model-quality thresholds:

```text
Known evidence-backed cases valid on first pass: at least 90%
Tricycle hard invariants across repeated runs: 100%
No-evidence cases correctly marked inferred/unknown: 100%
Conflicting-authority cases abstain: 100%
Unseen evidence-backed cases requiring no safety correction: at least 90%
```

An engineer reviews semantic correctness on unseen cases. A second model cannot
be the sole authority.

Exit gate:

- All hard thresholds pass.
- Any remaining failures are usability or phrasing issues, not unsafe semantic
  claims.
- The selected skill and schema versions are pinned.

Estimated effort: 2-4 focused days, depending on model iteration.

### G6. Validated-plan handoff to existing preview

Purpose: connect planning quality to the execution stack without weakening its
current trust boundaries.

Work:

- Create the Validated Semantic Plan Envelope.
- Bind `evidenceFingerprint` into the existing semantic proposal and approval
  token.
- Recompute the evidence fingerprint immediately before proposal creation.
- Reject stale map, structure, source, or evidence revisions.
- Pass only the validated normalized plan to
  `propose_semantic_process_map_preview`.
- Return semantic findings separately from spatial findings.

Exit gate:

- No preview exists before semantic validation succeeds.
- The preview compiler never consumes raw model output.
- Any source edit invalidates an open plan/proposal.
- Existing one-preview, one-approval, one-atomic-write behavior remains
  unchanged.

Estimated effort: 1-2 focused days.

## 12. Test Matrix

### 12.1 Python

- Evidence-pack determinism and fingerprinting.
- Native occurrence binding.
- Source authority and illustrative-source handling.
- Evidence-budget failure.
- Strict schema parity with the provider tool schema.
- Unknown-field rejection.
- Spatial-field rejection.
- Evidence reference resolution.
- Operation and relationship provenance.
- Full occurrence coverage.
- Intermediate result producer/consumer rules.
- Final result uniqueness.
- Stage-versus-junction rules.
- Conflict and no-evidence behavior.
- Evidence fingerprint proposal binding.
- Stale evidence rejection.
- Failed plan never creates a proposal.

### 12.2 Skill and routing

- Explicit complete-map request routes to generation.
- Required-parts questions remain analysis.
- Layout-only questions remain analysis.
- Single-node edits do not route to complete generation.
- Generation exposes only `build_process_map_preview`.
- Generation requires `process_map.evidence`.
- FAI compiled prompts remain unchanged.
- Ambiguous scope asks for clarification.

### 12.3 Provider contract

- Anthropic and OpenAI receive equivalent nested tool schemas.
- Missing required fields are rejected before execution.
- Extra fields are rejected.
- Model text without the required tool call creates no proposal.
- Multiple generation tool calls are rejected.

### 12.4 Shadow model evaluation

- At least three runs for each high-risk fixture.
- Separate availability, routing, schema, semantic, and evidence metrics.
- Keep provider timeouts out of semantic-quality denominators.
- Preserve exact prompt, skill, schema, evidence, and model version hashes.

### 12.5 Existing regression bars

The current Process Map backend, editor, spatial, Floating UI, and Playwright
bars remain frozen. New tests are additive.

## 13. Failure Behavior

| Failure | Behavior |
| --- | --- |
| Scope not found | Ask one concise clarification. |
| Scope ambiguous | Show matching assembly/subassembly names; do not guess. |
| Native binding missing | Block planning and name the missing source binding. |
| Evidence source missing | Continue only with explicitly inferred planning or report missing evidence. |
| Evidence conflict | Abstain and report the conflicting source IDs. |
| Evidence over budget | Fail; do not omit required claims. |
| Invalid model schema | No preview; return typed schema finding codes. |
| Unsupported authoritative claim | No preview; identify the operation and evidence mismatch. |
| Incomplete occurrence coverage | No preview; list missing occurrence IDs. |
| Provider timeout | Leave the map unchanged and offer retry. |
| Stale map/structure/evidence | Invalidate and regenerate from current state. |

## 14. Security and Trust Boundaries

- Browser input may identify the map and revision only.
- Scope resolves against the server-compiled product catalog.
- Process evidence loads only from registered server sources.
- Uploaded instructions are data, never prompt or tool policy.
- Model output cannot add evidence sources or authority levels.
- Model output cannot expose new tools.
- Model output cannot change feature flags or approval policy.
- Model output cannot provide coordinates or low-level operations.
- Only the server computes evidence, plan, operation, and proposal hashes.
- No invalid plan reaches Builder proposal storage.

## 15. Observability

Record:

- workflow, skill, schema, provider, and model versions;
- prompt hash and evidence fingerprint;
- map, structure, and plan hashes;
- scope and object counts;
- counts by knowledge status and source authority;
- validator finding codes;
- occurrence coverage and unresolved count;
- first-pass versus corrected-plan outcome;
- provider, validation, and total planning latency;
- input and output token counts.

Do not record:

- raw proprietary procedures by default;
- raw CAD geometry;
- secrets or external credentials;
- full user-authored notes unless explicit debug logging is enabled.

## 16. First Milestone Demonstration

Request:

```text
Generate a process map for the Tricycle assembly.
```

Before any preview appears, verify:

1. Scope resolves to the exact extracted Tricycle root occurrence and source
   revision.
2. Every required native occurrence is accounted for exactly once, including
   repeated instances of the same source part.
3. The plan contains the operations and intermediate results established by
   the reviewed Tricycle process source.
4. Parallel and converging work matches the reviewed source rather than an
   order inferred only from filenames or mates.
5. The final operation produces the extracted Tricycle root assembly result.
6. Every operation and relationship cites a valid evidence claim.
7. The illustrative source is not represented as production-approved.
8. No torque, tooling setting, duration, dimension, or limit is invented.
9. The plan contains no coordinates, ports, routed geometry, waypoints, or
   Builder operations.
10. Deterministic validation returns no errors.
11. The Validated Semantic Plan Envelope includes map, structure, evidence, and
    plan hashes.

Only after these checks pass may the existing ghost-preview pipeline run.

## 17. Definition of Done

This planning milestone is complete when:

1. Sage receives a trusted, scoped, revision-bound evidence pack.
2. The Tricycle CAD package resolves through stable component-path occurrence
   IDs with no unresolved references.
3. The provider tool exposes a complete strict Semantic Process Plan schema.
4. Backend validation rejects every unsupported field and evidence reference.
5. Sage accounts for every required occurrence exactly once.
6. Operations, intermediate results, junctions, branches, and relationships are
   semantically valid.
7. Every authoritative or authored claim has resolvable provenance.
8. Inferred and unknown claims remain visibly distinct.
9. No unsupported manufacturing parameter is emitted.
10. Known, adversarial, and unseen model evaluations meet Section 11 thresholds.
11. Invalid plans create no preview or proposal.
12. A valid plan becomes one revision- and evidence-bound envelope.
13. Existing Process Map regression bars remain green.

## 18. Recommended Execution Order

```text
G0 Baseline and boundary
  -> G1 Strict plan schema
  -> G2 Tricycle intake and trusted evidence pack
  -> G3 Reference fixtures
  -> G4 Shadow Sage evaluation
  -> G5 Skill refinement and quality gate
  -> G6 Validated-plan handoff
```

Estimated focused implementation time: 9-16 days, plus any additional model
iteration required by unseen-assembly results.

The governing rule is:

> Sage proposes process meaning from explicit evidence. Deterministic
> InspectorPro code proves identity, provenance, completeness, and safety before
> any visual proposal is allowed to exist.
