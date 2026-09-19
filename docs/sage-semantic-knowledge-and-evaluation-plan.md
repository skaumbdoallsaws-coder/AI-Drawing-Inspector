# Sage Semantic Knowledge and Evaluation Plan

Revision: 5

Status: Independently reviewed and ready for Phase 0 and Phase 1. Implementation
still requires explicit user authorization.

Date: 2026-08-25

## 1. Objective

Extend InspectorPro's existing assembly-knowledge system so Sage can answer
cross-workflow questions with revision-bound product meaning, not only geometry
and filenames.

The target is one reusable knowledge layer that can explain:

- what a component or feature does;
- which interfaces and occurrences it participates in;
- why a measured deviation may matter to the assembly;
- which process operations, documents, inspections, or motions are affected;
- which statements are deterministic, authored, inferred, unresolved, or stale;
- exactly which source supports each technical statement.

A separate synthetic scenario factory will expand evaluation coverage for Sage's
workflow routing, answer grounding, and action honesty. It will not become a
runtime source of product facts.

This is an extension and coverage project. InspectorPro already contains most of
the required package, evidence, review, prompt, and evaluation infrastructure.

## 2. Corrected Verified Baseline

The following inventory was rechecked against the repository on 2026-08-25.

### 2.1 Part profiles and registry coverage

`400S_Sorted_Library/parts/` contains 13 staged part directories:

- 10 have an inspection profile;
- 3 do not: `1030017`, `1040017`, and `1040018`.

There are 10 root inspection profiles:

- `100002` through `100009`;
- `1030001`;
- `1030002`.

`400S_Sorted_Library/part_number_registry.json` contains 88 assignments:

- 18 for `tricycle`;
- 70 for `MMLE-50D`.

The intersection between the 10 root profile part numbers and the 88 registry
part numbers is zero. Therefore:

- the staged-profile gap is 3, not 82;
- closing those 3 profiles does not provide MMLE coverage;
- the 70 MMLE registry assignments are not equivalent to 70 ready Profile
  Builder inputs;
- broad MMLE profile generation cannot begin until identity and source assets
  are crosswalked.

### 2.2 Existing Profile Builder boundary

`server.py` already implements `_profile_builder_*` and the Profile Builder API.
It is a real, useful part-inspection feature, but its present contract is narrow:

- it requires promoted part metadata and a drawing map;
- it drafts `part_name`, `part_description`, inspection features, evidence,
  uncertainty, review notes, and drawing-view expectations;
- `_normalize_profile_builder_draft()` does not preserve `assembly_role` or
  `assembly_context`;
- it refuses incomplete input with `profile_builder_context_incomplete`.

The richer engine-demo profiles contain `assembly_role` and `assembly_context`,
but those fields were curated outside the current builder output contract.

The Profile Builder should remain the owner of drawing and feature inspection
meaning. It should not become a second assembly-wide semantic database.

### 2.3 Existing Assembly Knowledge Package system

InspectorPro already has a revision-bound Assembly Knowledge Package in
`ai_inspector/assembly_knowledge/`, including:

- deterministic extraction and canonical occurrence identity;
- `product_structure.json`;
- `interface_graph.json`;
- `functional_context.json`;
- `process_candidates.json`;
- `evidence_catalog.json`;
- `unresolved.json`;
- package hashing and revision binding;
- strict schema validation;
- cost-controlled model enrichment;
- review queues and auditable review actions;
- stale-revision rejection;
- package APIs and runtime consumers;
- process-map and work-instruction integration;
- package evaluation fixtures and tests.

Its existing claim contract already separates:

- `knowledgeStatus`: `derived`, `inferred`, `authored`, or `unknown`;
- `authority`: `approved`, `authored`, `illustrative`, `supporting`, or
  `untrusted`;
- `reviewStatus`: `pending`, `confirmed`, `edited`, `rejected`, `unknown`, or
  `deferred`.

These fields must remain independent. Human confirmation does not automatically
turn inferred knowledge into authored knowledge or supporting evidence into an
approved engineering authority.

### 2.4 Existing synthetic MMLE authority defect

The current MMLE package contains 93 claims in `process_candidates.json`. All 93
are labeled:

```text
knowledgeStatus: authored
authority: authored
reviewStatus: confirmed
generatedBy.generatorId: mmle-synthetic-process-fixture-builder
```

Its `review_receipt.json` contains no review events. Package-level
`productionEligible: false` prevents controlled use, but the claim-level labels
overstate the authority and review history of synthetic fixture content.

This is a baseline defect to remediate, not a convention to inherit. A corrected,
superseding package revision must use `authority: illustrative`; a synthetic
claim remains `pending` unless an actual review event exists. The historical
package remains addressable for audit but must be quarantined from new runtime
retrieval.

`knowledgeStatus: authored` may remain valid for an intentionally specified
synthetic process fact, but it does not confer product authority. Status,
authority, review, and production eligibility remain separate controls.

### 2.5 Current production functional-context store

Sage does not currently retrieve assembly meaning from the Assembly Knowledge
Package. `server.py:_functional_context_for_asset()` reads through
`FunctionalRelationshipRegistry` in
`ai_inspector/product_intelligence/functional_relationships.py`, whose store is
`ai_inspector/product_intelligence/catalogs/`.

That store currently contains one catalog:

```text
100001.json
graph_id: functional-graph:100001
component types: 8
component instances: 43
interfaces: 40
external entities: 2
source evidence entries: 10
functional roles: 33 (28 component-type + 5 external-entity)
functional features: 35 (32 component-type + 3 external-entity)
semantic tags: 109 (99 component-type + 10 external-entity)
aliases: 116 (107 component-type + 9 external-entity)
```

It supplies the engine demo with mobility, functional roles, functional
features, interfaces, and the part allowlist used by Sage actions. MMLE-50D has
no equivalent functional catalog.

The Assembly Knowledge Package's generic claim schema can encode new predicates,
but it has no dedicated `mobility`, alias, or semantic-tag field. A migration
that merely copies these values into free-form claim text would preserve bytes
while losing lookup behavior. Phase 1 therefore requires a typed predicate and
index design plus field-level migration coverage before any dual-read parity
claim is meaningful.

Therefore the Assembly Knowledge Package is the correct target architecture,
not the current runtime source. Phase 5 is a store migration with a compatibility
window, not merely a retrieval extension. The existing catalog cannot be
silently abandoned or allowed to become a permanent third semantic authority.

### 2.6 MMLE knowledge is fragmented, not absent

MMLE-50D already has meaningful information distributed across:

- CAD extraction and occurrence geometry;
- `documentation_assembly_registry.json` manual groups;
- operations-manual source and evidence registers;
- the synthetic process-map package;
- work-instruction stages and source references;
- parts-manual catalog and nomenclature work;
- generated Assembly Knowledge Package artifacts.

The problem is that this information is workflow-specific, inconsistently
identified, and not all compiled into one queryable entity graph. The plan must
reuse and reconcile it before asking a model to generate new meaning.

The currently generated MMLE package proves the container and revision machinery
exist. It already includes product structure, interfaces, geometry, evidence,
visuals, unresolved records, and 93 process claims. Its
`functional_context.json` contains no claims, and the authority defect in 2.4
prevents treating the process claims as reviewed product knowledge. It is a
substantial structural and planning fixture, but reusable functional coverage is
not complete.

### 2.7 Facility semantics already derive process relationships

`ai_inspector/facility_layout/semantic_model.py` already composes authored
process-map precedence, process bindings, placements, and zone IDs into
revision-bound derived relationships. This plan will test and consume that
implementation. It will not schedule a duplicate "derive zone flow" feature.

Hierarchy resolution, ambiguous nested workcells, and stale bindings still need
coverage tests before facility semantics are considered complete.

### 2.8 Existing evaluation and prompt infrastructure

InspectorPro already provides:

- versioned prompt modules in `ai_inspector/prompts/`;
- versioned skills and deterministic skill schemas;
- semantic-route fixtures in `tests/fixtures/skill_route_cases.json`;
- `tests/eval_skill_route_shadow.py`;
- browser action receipts and authorization checks;
- workflow-specific deterministic tests.

The new scenario factory must extend these contracts rather than introduce a
parallel evaluation runner.

### 2.9 Old fine-tuning project boundary

The inspected Mechanical Engineer Expert project is useful as a warning and as a
source of batch-generation ideas, not as importable training data. Its current
corpus has no source provenance, contains exact duplicate-question leakage across
splits, and uses random row splitting. After JSON decoding, 1,130 of 1,625 rows
in `engineering_finetune_data.jsonl` contain control characters other than line
feeds: tabs, form feeds, carriage returns, or backspaces. The raw JSONL bytes do
not contain those literal control bytes; JSON escape decoding exposes the
corruption, consistent with TeX-like backslash sequences being interpreted as
JSON escapes. Its generator also appends output without a reliable idempotent
resume contract.

No old JSONL row enters InspectorPro. Any useful mechanics, such as bounded batch
generation or checkpointing, must be reimplemented behind InspectorPro's current
schemas, provenance, deduplication, and validation gates.

## 3. Decisions

### 3.1 Canonical runtime container

The Assembly Knowledge Package is the target canonical reusable semantic
container. Today, Sage's primary functional-context path reads the separate
`FunctionalRelationshipRegistry` catalog described in 2.5.

Inspection profiles, documentation evidence, process packages, work
instructions, and facility semantic maps are source systems or compiled views.
They may feed the package through typed adapters, but none independently
overrides CAD identity, geometry, approved specifications, or package revision.

Migration rules are:

1. adapt the current `100001` functional catalog into the package contract;
2. shadow-read the catalog and package for a fixed parity suite;
3. preserve the catalog as a compatibility fallback until parity gates pass;
4. switch Sage and the functional-relationship endpoints to one package-backed
   provider;
5. retire `catalogs/100001.json` as a runtime authority while retaining its
   source revision for audit and migration tests.

### 3.2 Two separate workstreams

#### Workstream A: Runtime semantic knowledge

Purpose: improve Sage's product understanding in live workflows.

Output: revision-bound claims, relationships, evidence, unknowns, review
receipts, and a bounded retrieval API.

#### Workstream B: Synthetic scenario and evaluation factory

Purpose: generate broad, safe test coverage for routing, answers, citations,
permissions, and UI actions.

Output: candidate and curated evaluation cases.

Synthetic scenarios never enter runtime product retrieval and never authorize a
technical claim or action.

### 3.3 Fine-tuning boundary

Do not fine-tune product facts, engineering values, assembly relationships,
permissions, or release decisions. Those must remain retrieved, cited,
revision-bound, and replaceable.

A later behavior-only fine-tune may be considered for stable response style,
such as the inverted-pyramid answer format, only after prompt and retrieval
evaluation shows a persistent format problem. Training examples must remain
synthetic or licensed and must not encode real product conclusions as reusable
facts.

### 3.4 Review boundary for the current prototype

The founder may review and confirm claims for prototype demonstrations. That
review may set `reviewStatus` to `confirmed` or `edited`, but it must not:

- set `authority` to `approved` without an approved source and authorized role;
- set `productionEligible` to true;
- mark a package `production_ready`;
- imply manufacturing, safety, or quality approval.

Prototype packages remain `illustrative` or `supporting` and visibly non-release.
These rules require writer-side and retrieval-side validation; policy text alone
is insufficient.

## 4. Scope

### 4.1 Included

- Canonical crosswalk between registry parts, source paths, part definitions,
  component occurrences, interfaces, profiles, process operations, and source
  documents.
- Typed adapters from existing InspectorPro knowledge sources into the Assembly
  Knowledge Package.
- Migration of `FunctionalRelationshipRegistry` catalogs into the package-backed
  provider, with measured compatibility and explicit retirement criteria.
- Deterministic derivation before model inference.
- A bounded MMLE pilot focused on high-value entities and interfaces.
- Review-by-exception using the existing package review system.
- Runtime retrieval through the existing functional-context path.
- Cross-workflow evaluation and provenance checks.
- Synthetic scenario generation with deterministic validation and explicit
  promotion into a curated gold set.
- Revision invalidation, source hashing, conflict handling, and diagnostics.
- Claim-authority write guards and package-readiness retrieval gates.

### 4.2 Excluded

- Blindly generating one profile for all 70 MMLE registry assignments.
- Treating generic fastener instances as 70 separate semantic authoring tasks.
- Importing the old Mechanical Engineer Expert dataset or generator unchanged.
- Fine-tuning factual knowledge.
- Replacing deterministic CAD, mate, measurement, routing, or authorization
  logic with model output.
- Treating an LLM's confidence as evidence.
- Allowing generated scenarios to become product knowledge.
- Creating a second semantic database beside the Assembly Knowledge Package.
- Removing the current functional catalog before migration parity is proven.

## 5. Knowledge Model

### 5.1 Entity coverage

The shared layer must be able to reference:

- product and assembly;
- subassembly;
- part definition;
- component occurrence;
- physical or functional interface;
- inspectable feature;
- motion group;
- process operation or stage;
- facility zone or workcell;
- source document and exact source location.

Not every entity needs a narrative profile. A record is useful only if it answers
a real workflow question better than deterministic source data alone.

### 5.2 Source precedence

When claims conflict, use this order:

1. approved product-specific engineering source;
2. authored product-specific source awaiting formal approval;
3. deterministic CAD or application-derived fact;
4. approved reusable company standard within its applicability;
5. manufacturer documentation within the confirmed configuration;
6. supporting or illustrative process/documentation source;
7. model inference;
8. unknown.

A lower tier never silently overwrites a higher tier. Conflicts remain explicit.

### 5.3 Claim requirements

Every reusable semantic claim must carry the existing Assembly Knowledge fields
and resolve all references:

- stable `claimId`;
- `subjectRef` and optional `objectRefs`;
- predicate and structured value;
- `knowledgeStatus`;
- `authority`;
- one or more `evidenceRefs`, or an explicit unknown/assumption;
- generator identity and version;
- `reviewStatus`;
- package and source revision through its containing documents.

Approved numerical engineering values require an approved evidence source.
Geometry-derived relationships may be `derived`, but their interpretation may
still be `inferred`.

### 5.4 Class semantics versus product semantics

Reusable class semantics are appropriate for generic objects such as:

- a washer distributing bearing load;
- a retaining ring occupying a groove;
- a fastener participating in a clamped joint.

Class semantics must not supply product-specific torque, orientation,
criticality, sequence, load, material, or acceptance criteria. Those require
product evidence. This avoids paying to author nearly identical narratives for
every standard-library occurrence.

### 5.5 Authority translation and promotion

The functional catalog and continuity-memory subsystems use authority values that
are not members of the Assembly Knowledge Package `AUTHORITIES` enum. Phase 1
must define and test an explicit translation. The initial conservative mapping
is:

| Existing value | Package knowledge status | Package authority |
| --- | --- | --- |
| `cad_structure` | `derived` | `supporting` |
| `cad_constraint` | `derived` | `supporting` |
| `curated_profile` | `authored` | `supporting` |
| `validated_motion` | `derived` | `supporting` |
| `reviewed_inference` | `inferred` | `supporting` |
| `untrusted_continuity` | not adapted | not adapted |

No translation grants `approved`. `curated_profile` may become `authored`
authority only when its evidence identifies an authenticated authored source.
`reviewed_inference` remains inferred even after review.

`untrusted_continuity` belongs to the continuity-memory envelope, not the
product-evidence system. It is explicitly excluded from package adapters. It may
help maintain conversational continuity, but it never becomes a product claim,
evidence source, or alias.

Writer-side rules must enforce:

- `authority: approved` requires an approved evidence source plus an authorized
  approval event;
- `authority: authored` requires an authored source or authenticated user event;
- a fixture builder or model cannot confer either authority by assignment;
- synthetic evidence forces `authority: illustrative`,
  `productionEligible: false`, and non-production retrieval;
- review confirmation does not alter knowledge status or evidence authority.

### 5.6 Typed predicate and lookup contract

The Assembly Knowledge Package schema intentionally allows open predicate IDs.
Phase 1 must add a versioned predicate registry at the adapter and retrieval
layer so openness does not become unstructured free-form storage.

Every registered predicate defines:

- allowed subject and object entity kinds;
- a strict value schema and cardinality;
- whether the value is searchable, displayable, or both;
- normalization and case rules;
- permitted knowledge status and authority combinations;
- evidence requirements;
- conflict and supersession behavior;
- retrieval and prompt-rendering behavior.

The `100001` migration must explicitly represent:

- component type and component instance identity;
- mobility;
- functional roles;
- functional features;
- semantic tags;
- aliases;
- interfaces and interface evidence;
- external entities;
- coverage and uncovered instances.

Component instances map to package occurrences and interfaces map to the
interface graph. Roles, features, mobility, tags, and aliases use registered
typed predicates or a versioned dedicated index when claim representation would
lose behavior. External entities require an explicit representation decision;
they cannot be flattened into narrative. Coverage remains a computed package
diagnostic rather than a semantic claim.

Alias lookup is a first-class migration requirement. All source aliases remain
bound to one canonical entity and package revision, are indexed separately from
display nomenclature, and never override the canonical part or occurrence ID.

## 6. MMLE Pilot Selection

Do not select entities by registry count alone. Rank candidates using a recorded
score:

- repeated use in current demos and workflows;
- safety or quality consequence;
- interface centrality in the assembly graph;
- role in motion or assembly sequence;
- unresolved terminology or configuration conflict;
- reuse across FAI, training, documentation, process maps, and revision impact.

The first pilot should cover approximately:

- 12 to 20 high-value part definitions or subassemblies;
- 6 to 10 key interfaces;
- the relevant motion groups;
- 5 to 8 process operations already represented in the MMLE process package.

The review unit is a claim, not an entity. The pilot is capped at 60 proposed
claims, with a target range of 30 to 60 and a maximum founder review budget of
8 hours. If the selected entities produce more than 60 claims, lower-ranked
claims are deferred rather than silently accepted.

The total human-review budget for the complete pilot is 17 hours:

| Review activity | Maximum |
| --- | ---: |
| Phase 0: 35 baseline query cases | 2.5 hours |
| Phase 4: up to 60 semantic claims | 8 hours |
| Phase 5: blinded rescoring of the 15-query semantic subset | 1.5 hours |
| Phase 6: 48 curated gold scenarios | 5 hours |

The same artifact may be reused across phases and is reviewed once; later runs
record a new execution result, not a duplicate review artifact. The 40 held-out
paraphrase cases required for catalog migration are included in the 48 Phase 6
gold scenarios. A review ledger records artifact ID, reviewer, decision,
minutes, and every phase that consumes it. If cumulative review exceeds 17
hours, the pilot returns to scope selection.

Candidate domains are the lift mechanism, hydraulic cylinder, hydraulic power
pack, battery/control assembly, caster/brake assemblies, platform, and base
frame. The Phase 0 crosswalk, not this document, chooses exact part numbers.

Each selected entity must end with one of these outcomes:

- source-backed role and relationship claims;
- a reusable class-semantic binding;
- an explicit unresolved question;
- an explicit determination that no added semantic narrative is useful.

## 7. Implementation Phases

### Phase 0: Canonical inventory and baseline

No model calls.

#### Work

1. Build a read-only inventory of registry assignments, staged part assets,
   inspection profiles, assembly-package entities, MMLE occurrences, manual
   groups, process operations, source documents, and the current
   `FunctionalRelationshipRegistry` catalog.
2. Create a crosswalk keyed by canonical product, part definition, source path,
   and occurrence identity.
3. Classify every MMLE registry row as `resolved`, `class_semantic`,
   `ambiguous`, or `missing`.
4. Record duplicate source paths, repeated occurrences, aliases, internal CAD
   names, and nomenclature mappings.
5. Capture a baseline query set across FAI, training, drawing release, revision
   comparison, process maps, documentation, and facility layout.
6. Record current answer quality, citation coverage, route selection, latency,
   and unsupported-claim count.
7. Treat the three staged parts missing profiles as a separate library hygiene
   task; do not confuse them with MMLE coverage.
8. Audit all existing package claims for generator, knowledge status, authority,
   review status, review events, evidence authority, and production eligibility.
9. Create a corrected, superseding MMLE package revision in which the 93
   synthetic process claims use `authority: illustrative`; set review status to
   `pending` unless a real review event is recorded. Quarantine the historical
   revision from new retrieval without deleting it. Recompute readiness from the
   corrected claims and accept a readiness downgrade rather than preserving
   `planning_ready` through false confirmation.
10. Baseline `100001` against its current functional catalog and MMLE against its
    current no-catalog state. Do not use the curated engine graph as MMLE's
    baseline.
11. Freeze a semantic-dependent subset of at least 15 same-product queries
    before implementation. It must contain at least six human-reviewed baseline
    failures, retain all baseline passes, and record selection rationale so
    cases cannot be substituted after results are known.

#### Deliverables

- `docs/semantic-knowledge/coverage-baseline.json`
- `docs/semantic-knowledge/mmle-entity-crosswalk.json`
- `docs/semantic-knowledge/baseline-query-set.json`
- `docs/semantic-knowledge/authority-audit.json`
- `docs/semantic-knowledge/review-ledger.json`
- a short baseline report with generated timestamp and source hashes

The initial baseline query set must contain at least 35 reviewed cases, with at
least five per target workflow and coverage of both answer-only and action-taking
requests.

#### Exit gate

- `unclassifiedRegistryCount` equals zero.
- Every pilot candidate resolves to stable source and package identities.
- Every ambiguous row has `selectedBinding: null`, at least one recorded
  candidate or missing-evidence reason, and no generated package binding.
- The current functional catalog is inventoried as a runtime store.
- The corrected MMLE revision has zero synthetic claims with authority other
  than `illustrative`, zero false review confirmations, and remains
  `productionEligible: false`.
- The baseline is reproducible. Source CAD, registries, current catalogs, and
  historical package revisions remain unmodified; remediation creates a new
  superseding package revision.
- The frozen semantic-dependent subset contains at least 15 cases and at least
  six reviewed baseline failures, with no post-baseline case substitution.
- Phase 0 review time is recorded in the shared ledger and does not exceed 2.5
  hours.

### Phase 1: Contract and adapter freeze

No new standalone semantic schema.

#### Work

1. Confirm the existing Assembly Knowledge Package can represent the required
   roles, relationships, interfaces, operations, evidence, and unknowns.
2. Add a schema field only when a demonstrated pilot query cannot be represented
   without loss. Any change requires a version and migration test.
3. Produce a field-level migration matrix and versioned predicate/index design
   for the current functional catalog before writing its adapter. The matrix
   must cover top-level component types, component instances, interfaces,
   external entities, source evidence, and coverage, plus nested mobility,
   functional roles, functional features, semantic tags, and aliases. Every
   source field must map to a typed package representation, a computed
   diagnostic, or an explicit unsupported/blocking disposition; free-form
   narrative flattening is not an acceptable mapping for behavior-bearing
   fields.
4. Define alias and paraphrase lookup behavior. Source aliases remain searchable
   identifiers bound to canonical entities, never canonical identity
   replacements. The migration test design must include every catalog alias and
   semantic tag plus held-out paraphrases that were not used to implement the
   adapter.
5. Define deterministic adapters for:
   - CAD extraction and registry identities;
   - inspection-profile feature evidence;
   - `FunctionalRelationshipRegistry` catalogs;
   - documentation source/evidence claims;
   - MMLE process-map operations;
   - work-instruction evidence and open findings;
   - existing facility semantic relationships.
6. Define conflict, precedence, revision, and stale-source behavior.
7. Define bounded retrieval output for Sage rather than dumping a full package
   into every prompt. The pilot default is at most 12 claims and 6,000 rendered
   characters per turn; truncation preserves conflicts and unknowns before
   lower-priority narrative.
8. Implement the authority translation and promotion rules in 5.5.
9. Define retrieval eligibility by use:
   - controlled/released use requires the configured controlled readiness and
     `productionEligible: true`;
   - prototype/draft use may read `illustrative` or `supporting` claims only
     through an explicit prototype mode and must expose that status to Sage;
   - quarantined, rejected, unknown, wrong-product, and stale claims are never
     returned as usable facts.
10. Define the compatibility-provider contract used during catalog migration.

#### Deliverables

- adapter contracts and schemas
- source precedence policy
- authority translation and promotion policy
- runtime retrieval eligibility policy
- versioned predicate/index registry
- functional-catalog field migration matrix
- alias, semantic-tag, and held-out paraphrase parity fixtures
- cross-reference validator
- migration tests if the package schema changes

#### Exit gate

- All adapter outputs validate under the Assembly Knowledge Package schema.
- Every non-unknown claim resolves to evidence.
- No adapter can overwrite CAD identity or an approved source silently.
- Negative tests prove that fixture builders, models, and unauthenticated review
  actions cannot emit `authority: approved` or unsupported `authority: authored`.
- Synthetic claims cannot pass production retrieval, even when a malformed
  source file marks them confirmed.
- Every legacy authority value maps explicitly or fails closed.
- The field migration matrix accounts for every source catalog field and records
  zero silent or free-form lossy mappings.
- The parity contract directly covers all 116 current source aliases, all 109
  semantic tags, and at least 40 independently reviewed held-out paraphrases,
  with at least four paraphrases for each of the eight component types and two
  external entities.
- Current package fixtures remain backward compatible.
- Retrieval contract tests enforce the 12-claim and 6,000-character defaults.

### Phase 2: Deterministic MMLE compilation

Use existing data before inference.

#### Work

1. Compile product structure, manual groups, mates, repeated occurrences,
   motion groups, process bindings, and known document claims into one MMLE
   package revision.
2. Normalize aliases without destroying original source names.
3. Bind source locations and hashes.
4. Emit conflicts where current, legacy, CAD, and synthetic demonstration
   sources disagree.
5. Bind generic parts to safe class semantics where appropriate.
6. Emit unresolved records for every pilot question that deterministic evidence
   cannot answer.
7. Add a read-only package retrieval probe that executes the pilot identity,
   relationship, operation, conflict, and unknown queries without involving
   Sage or changing the production provider.

#### Exit gate

- The package answers identity and relationship queries without model inference.
- Derived claims are byte-stable for identical inputs.
- Every conflict and missing source remains visible.
- Synthetic process knowledge remains `illustrative` and
  `productionEligible: false`.
- The read-only probe matches the expected entity and evidence IDs for 100% of
  non-ambiguous deterministic pilot queries. Every query on an explicit
  ambiguity allowlist returns its expected ambiguous or unknown result without
  guessing a binding. Any other mismatch blocks enrichment.

### Phase 3: Targeted semantic enrichment

Use the existing Assembly Knowledge enrichment path, not a new batch script.

#### Work

1. Run enrichment only for the selected pilot entities and unresolved
   relationships.
2. Ask for occurrence roles, functional relationships, joint archetypes,
   operation families, assumptions, and focused unresolved questions.
3. Require references to known occurrence, interface, and evidence IDs.
4. Reject unknown IDs, stale source revisions, unsupported values, and output
   outside the strict schema.
5. Cache by package revision, evidence fingerprint, model, and prompt version.
6. Keep inspection-feature drafting in the existing Profile Builder; adapt its
   results into the package rather than broadening it into an assembly planner.
7. Enforce the existing `economy-v1` contract unless a separately reviewed
   contract supersedes it: at most 2 provider calls, 6 images per call,
   15,000,000 submitted image pixels, 24,000 input tokens per call, 6,000 output
   tokens per call, USD 0.50 estimated cost, USD 0.50 retry cost, and explicit
   approval.

#### Exit gate

- Every model claim starts `inferred` and `pending`.
- No model claim can introduce torque, tolerance, safety procedure, load,
  material, or disposition without source evidence.
- Re-running identical inputs is cacheable and does not append duplicates.
- The complete pilot contains no more than 60 claims requiring review.
- The `economy-v1` limits above are present in the authorization receipt and are
  rejected deterministically when exceeded.

### Phase 4: Review by exception

Reuse `ai_inspector/assembly_knowledge/review.py` and its revision checks.

#### Work

1. Prioritize review by safety/quality impact, interface centrality, conflict,
   and workflow reuse.
2. Present the claim, entities, evidence, visual context, assumptions, and the
   consequence of accepting it.
3. Support confirm, edit, reject, mark unknown, and defer.
4. Require a new review when a bound source or package revision changes.
5. Record prototype reviewer identity and timestamp without granting controlled
   authority.

A claim is high-impact when any of the following is true:

- it concerns personnel safety, stored energy, motion, collision, or a hazard
  control;
- it influences inspection acceptance, disposition, quality release, or
  controlled publication;
- it contains or governs a numerical engineering value, material, procedure,
  tool, torque, tolerance, test limit, or acceptance criterion;
- it changes an interface, assembly sequence dependency, or motion relationship
  used by three or more target workflows;
- it conflicts with another source or would change an authorized action.

#### Exit gate

- `pendingHighImpactClaimCount` equals zero; every high-impact claim is
  confirmed, edited, rejected, marked unknown, or explicitly deferred.
- Review actions are auditable and stale actions fail closed.
- Total claims requiring review do not exceed 60, and recorded founder review
  time does not exceed 8 hours. Exceeding either limit returns the pilot to scope
  selection rather than auto-confirming the remainder.
- The pilot remains non-production and cannot be represented as approved.

### Phase 5: Runtime store migration and workflow integration

Migrate the existing functional-context path from the catalog store to one
package-backed provider.

#### Work

1. Introduce a package-backed functional-context provider that retrieves
   relevant claims by active product, entity, feature, interface, workflow, and
   revision.
2. Adapt `catalogs/100001.json` into the package contract and shadow-read both
   stores for the fixed `100001` parity suite, following the Phase 1 field
   migration matrix and predicate/index registry.
3. Keep the current catalog as a read-only fallback during the compatibility
   window. Record which provider answered every request.
4. Switch `_functional_context_for_asset()`,
   `_enrich_agent_functional_context()`, and the functional-relationship API
   endpoints to the shared provider only after parity passes.
5. Replace FAI-only direct profile enrichment with the shared provider where
   practical, retaining a bounded compatibility fallback during rollout.
6. Enforce the retrieval eligibility policy from Phase 1 before claims enter
   agent context. Package presence alone is not eligibility.
7. Preserve context-budget accounting and include retrieval diagnostics.
8. Attach concise source references suitable for chat citation.
9. Expose explicit unknowns, conflicts, package readiness, production
   eligibility, and staleness to Sage.
10. Add workflow-specific use rules:
   - FAI: explain assembly impact without inventing severity or disposition;
   - Training: explain roles and nominal motion, clearly labeled as such;
   - Drawing Release: rank missing controls by evidenced function and interface;
   - Revision Compare: report affected interfaces and workflows, not only deltas;
   - Process Map: explain predecessor and subassembly rationale;
   - Documentation: reuse approved evidence and preserve release gates;
   - Facility Layout: consume existing derived zone/process relationships.
11. Retire `catalogs/100001.json` as a runtime authority only when:
   - all 8 component types, 43 component instances, 40 interfaces, 2 external
     entities, 10 evidence entries, 33 functional roles, 35 functional
     features, 109 semantic tags, 116 aliases, every component-type mobility
     value, and both external-entity presence values are represented without
     silent loss, while coverage metrics are recomputed and match the source
     catalog;
   - the fixed parity suite passes at 100%;
   - all 116 aliases resolve to the same canonical entities as the catalog, all
     109 semantic tags remain queryable, and all 40 held-out paraphrase cases
     return the reviewed canonical or ambiguous result;
   - no target workflow loses a supported answer or part allowlist entry;
   - all production endpoints use the package-backed provider;
   - rollback to the last catalog-backed build has been exercised.
   Retain the catalog as a migration fixture and historical source, not a live
   authority.

#### Exit gate

- Retrieval never returns claims from the wrong product or stale revision.
- Controlled retrieval returns no package with `productionEligible: false`.
- Prototype retrieval returns illustrative/supporting claims only when explicit
  prototype mode is active and includes that status in diagnostics.
- Source references resolve.
- Unsupported-claim rate on the pilot query set is zero.
- Action claims remain receipt-grounded.
- The `100001` catalog/package parity suite passes at 100% before catalog
  retirement, including 116 of 116 alias lookups, 109 of 109 semantic-tag checks,
  and 40 of 40 held-out paraphrase cases.
- On the frozen semantic-dependent subset of at least 15 cases, at least six
  baseline-failing cases now pass, with no previously passing reviewed gold case
  becoming a failure.
- Retrieved context respects the 12-claim and 6,000-character limits, and local
  provider retrieval p95 is no more than 50 ms on the recorded pilot hardware.
- Phase 5 blinded rescoring time is recorded in the shared review ledger and
  does not exceed 1.5 hours.

### Phase 6: Synthetic scenario factory

This phase may run in parallel with Phases 2 through 4 after Phase 1 freezes the
contracts.

#### Work

1. Define a scenario schema with:
   - scenario ID and lineage;
   - workflow and user intent;
   - synthetic context and entity references;
   - expected route, skills, permissions, and actions;
   - required evidence and citations;
   - forbidden claims and forbidden actions;
   - expected execution-receipt constraints;
   - difficulty and coverage tags.
2. Generate candidates from templates plus bounded linguistic variation.
3. Validate every entity reference, numeric calculation, route, permission, and
   expected action deterministically.
4. Deduplicate exact and near-duplicate cases.
5. Split by scenario family, template lineage, and product family to prevent
   train/evaluation leakage.
6. Store candidates under `.runtime` until explicit human promotion.
7. Promote only reviewed cases into the existing test fixtures.
8. Keep source generation idempotent; never append blindly to a gold file.
9. Include 40 independently reviewed catalog-migration paraphrase cases within
   the 48-case gold set: at least four for each of the eight component types and
   two external entities. Keep their wording and lineage hidden from adapter
   implementation, while validating their expected canonical or ambiguous
   results against reviewed catalog behavior.
10. Treat those migration paraphrases as evaluation-only transformations of
    reviewed catalog queries. They may test real catalog retrieval, but they
    never become runtime claims or teach product facts to a model.

#### First coverage target

- At least 100 validated candidate cases across the seven target workflows.
- At least 48 independently reviewed gold cases.
- Include normal, ambiguous, missing-evidence, stale-revision, conflict,
  unauthorized-action, failed-action, and multi-turn continuation cases.
- The 48 Phase 6 gold cases are additive to the 35 Phase 0 baseline cases. The
  combined reviewed corpus, not the eight non-migration Phase 6 cases alone,
  owns cross-workflow coverage.

#### Exit gate

- Zero unresolved references.
- Zero exact duplicate prompts in the curated set.
- Zero lineage leakage across evaluation partitions.
- Authorization and action-receipt expectations pass deterministic validation.
- No real product fact is learned from a synthetic scenario.
- The curated set includes all 40 held-out migration paraphrase cases, and Phase
  6 review time is recorded in the shared ledger and does not exceed 5 hours.

### Phase 7: Evaluation and release gate

#### Metrics

- workflow and skill selection accuracy;
- grounded conclusion accuracy;
- citation validity and source-location resolution;
- unsupported technical claim rate;
- stale-revision refusal rate;
- conflict disclosure rate;
- action authorization accuracy;
- receipt-grounded action-report accuracy;
- clarification quality for ambiguous targets;
- context size, latency, model cost, and cache hit rate.

For the semantic-dependent query subset, `grounded-answer correctness` is a
binary case score. A case passes only when the conclusion matches the reviewed
gold answer, every cited evidence reference resolves, required uncertainty or
conflict is disclosed, and no forbidden claim or action appears.

#### Required thresholds for pilot enablement

- 100% valid source references.
- 0 unsupported numerical engineering claims.
- 100% rejection of stale or wrong-product knowledge.
- 100% authorization accuracy for write actions.
- 100% honesty about failed or unexecuted viewport actions.
- No regression below existing semantic-router gates.
- At least six of the frozen 15 or more semantic-dependent queries that failed
  at baseline now pass human review.
- No previously passing reviewed gold case becomes a failure, and every existing
  semantic-router metric remains at or above its registered threshold.
- Local package-provider retrieval p95 no greater than 50 ms on the recorded
  pilot hardware.
- The shared review ledger remains within the 17-hour total pilot budget; Phase
  7 reuses recorded judgments unless an additional review is explicitly logged
  within that cap.

LLM judging may supplement review, but deterministic checks and human-reviewed
gold cases own the release decision.

### Phase 8: Coverage expansion and optional behavior tuning

Expand based on measured failures, not raw part count.

1. Add entities that repeatedly cause unanswered or weak queries.
2. Add class semantics for repeated standard components.
3. Add product-specific profiles only where class semantics are insufficient.
4. Validate facility hierarchy and nested-zone cases against the existing
   semantic map before adding inferred facility narratives.
5. Add authored narratives only where derived facts do not answer the query.
6. Revisit a behavior-only fine-tune only if prompt modules and retrieval cannot
   meet a stable style metric at acceptable context cost.

## 8. Dependency and Parallelization Map

Critical path:

```text
Phase 0 inventory and crosswalk
  -> Phase 1 contract and adapter freeze
  -> Phase 2 deterministic MMLE package
  -> Phase 3 targeted enrichment
  -> Phase 4 review
  -> Phase 5 runtime integration
  -> Phase 7 pilot gate
```

Parallel work after Phase 1:

```text
Phase 2-4 runtime knowledge
  ||
Phase 6 synthetic scenario factory
  ||
facility hierarchy regression coverage
```

The scenario factory must not define the runtime knowledge schema. Both consume
the frozen contracts from Phase 1.

## 9. Review Ownership

### Prototype

- AI drafts and validates structure.
- The founder reviews high-impact claims and may confirm them for a clearly
  labeled prototype.
- InspectorPro retains `productionEligible: false` and no controlled authority.

### Future controlled use

- Design Engineering: function, interfaces, specifications, revision impact.
- Manufacturing Engineering: sequence, operations, tooling, accessibility.
- Quality: inspection rationale, acceptance criteria, disposition policy.
- EHS or Safety: safety controls and procedures.
- Technical Publications: terminology and customer-facing use.
- Document Control: approval, effectivity, release, and supersession.

The system must record the role and source authority. A generic confirmation
button cannot confer every authority.

## 10. Initial File Map

Reuse first:

- `ai_inspector/assembly_knowledge/`
- `ai_inspector/product_intelligence/functional_relationships.py`
- `ai_inspector/product_intelligence/catalogs/100001.json`
- `ai_inspector/prompts/`
- `ai_inspector/agent_skills/`
- `ai_inspector/facility_layout/semantic_model.py`
- `tests/fixtures/skill_route_cases.json`
- `tests/eval_skill_route_shadow.py`
- `server.py` functional-context and agent-context integration

Expected new planning and fixture locations:

- `docs/semantic-knowledge/coverage-baseline.json`
- `docs/semantic-knowledge/mmle-entity-crosswalk.json`
- `docs/semantic-knowledge/baseline-query-set.json`
- `docs/semantic-knowledge/review-ledger.json`
- `tests/fixtures/semantic_knowledge/`
- a bounded scenario-generation tool under `tools/`

Do not create a new top-level runtime database or import the old fine-tuning
project's JSONL corpus.

## 11. Risks and Controls

### Identity mismatch

Risk: registry part number, filename, CAD occurrence, and document term refer to
different things.

Control: Phase 0 crosswalk, canonical occurrence identity, explicit ambiguous
state, and no fuzzy auto-binding into approved knowledge.

### Inferred intent presented as fact

Risk: geometry supports a mechanism, but not why the designer chose it.

Control: keep `knowledgeStatus: inferred`, cite assumptions, and never upgrade
authority through confirmation alone.

### Reviewed text becomes stale

Risk: CAD or source changes while a narrative remains readable.

Control: package revision binding, source hashes, stale retrieval refusal, and
review invalidation.

### Duplicate sources of truth

Risk: the live functional catalog, inspection profiles, documentation claims,
and package claims diverge.

Control: typed adapters compile into the Assembly Knowledge Package; the
functional catalog follows a measured migration and retirement path; source
systems remain addressable and are not copied as uncontrolled prose.

### Canonical-query parity hides lookup regressions

Risk: migrated canonical queries pass while aliases, semantic tags, or unseen
user paraphrases stop resolving.

Control: a field-level migration matrix, first-class alias indexing, exhaustive
alias and semantic-tag checks, 40 held-out reviewed paraphrases, and catalog
retirement blocked until every lookup gate passes.

### Authority escalation

Risk: a fixture builder, model, or unauthenticated writer labels a claim
`authored` or `approved` and bypasses the intended review boundary.

Control: evidence-aware writer guards, authenticated review events, negative
tests, synthetic-authority restrictions, and retrieval eligibility checks.

### Synthetic contamination

Risk: an illustrative scenario or synthetic MMLE instruction is treated as an
approved product fact.

Control: separate stores, explicit `illustrative` authority,
`productionEligible: false`, and runtime retrieval exclusion unless the active
workflow explicitly requests prototype evidence.

### Review overload

Risk: generation is cheap but review becomes unbounded.

Control: high-value pilot selection, class semantics, review by impact, the
shared 17-hour review ledger and phase caps, and coverage expansion driven by
measured query failures.

### Self-validating evaluation

Risk: the same model invents a scenario and declares its own answer correct.

Control: deterministic validators, independent human promotion, lineage-aware
splits, and gold cases that are not approved by the generator.

## 12. Definition of Pilot Success

The pilot succeeds when:

1. MMLE identity is crosswalked without silent guesses.
2. A revision-bound package compiles existing MMLE knowledge before inference.
3. The current `100001` catalog reaches 100% parity through the package-backed
   provider before it is retired as a runtime authority, including aliases,
   semantic tags, held-out paraphrases, instances, interfaces, and external
   entities.
4. At least six of the frozen semantic-dependent queries that failed at baseline
   pass after migration, with no baseline pass regressing.
5. Every technical conclusion is cited, bounded, or explicitly unknown.
6. No product-specific value is supplied from model memory or class semantics.
7. Inferred claims are reviewable and stale claims fail closed.
8. Synthetic claims cannot acquire controlled authority through a generator or
   malformed review label.
9. Synthetic cases expand coverage without entering runtime knowledge.
10. Existing workflow routing, authorization, and action receipts do not
    regress.
11. The package remains clearly prototype-only until real authorities approve
    it.
12. Human review stays within the shared 17-hour pilot budget and every judgment
    is traceable in the review ledger.

## 13. Independent Review Requested

The reviewer should validate this plan read-only and answer:

1. Are the corrected inventory counts and overlap claims reproducible?
2. Does the plan reuse the Assembly Knowledge Package rather than duplicate it?
3. Does the catalog-to-package migration preserve the current `100001` runtime
   behavior, including alias and paraphrase lookup, and define a safe retirement
   boundary?
4. Are inspection profiles assigned an appropriate, bounded role?
5. Is the MMLE crosswalk a sufficient prerequisite before enrichment?
6. Are deterministic, authored, inferred, reviewed, and approved states kept
   distinct?
7. Are the phase dependencies and parallel work correctly ordered?
8. Are the exit gates for each phase measurable?
9. Is the 30-to-60-claim pilot small enough for its 8-hour claim-review cap, and
   is the complete 17-hour review budget realistic for a solo reviewer?
10. Can a solo prototype reviewer follow the plan without accidentally granting
   controlled authority?
11. Are the runtime knowledge and synthetic evaluation stores sufficiently
    separated?
12. Are package readiness, production eligibility, and claim authority enforced
    before retrieval?
13. Does any existing InspectorPro subsystem make a proposed task redundant?
14. What P0, P1, or P2 corrections are required before coding?
15. Does the predicate/index design preserve every catalog field without turning
    aliases, tags, instances, interfaces, or external entities into unsearchable
    narrative claims?
