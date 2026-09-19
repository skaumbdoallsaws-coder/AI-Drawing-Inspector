# Facility Layout Reference-Quality Generation Plan

Date: 2026-08-29

Status: Revision 2 proposed after independent review; no implementation authorized by this plan

Working name: RQ0-RQ8

## Revision 2 Review-Condition Closure

| Independent-review condition | Revision 2 disposition |
|---|---|
| Lift both 480-placement caps | RQ1 raises the full-factory and G6 copied-placement caps to 900, retains 500-item substages, and adds 899/900/901 plus byte-budget gates. |
| Add placement dependency ordering | RQ2 adds a support/attachment DAG, topological batching, prerequisite-bound receipts, reverse rollback order, and cycle/missing-support failures. |
| Freeze the performance machine and p95 sample | Section 5.1 pins the machine, one-worker conditions, recorded runtime hashes, one discarded warmup, 20 measured runs, and nearest-rank p95. |
| Name the reconstruction approver | RQ0 names Shadrack as prototype benchmark approver and defines a revision-bound receipt without granting manufacturing or production authority. |

Additional review findings are also incorporated: a 100-item non-final build
batch floor, canonicalization cost work, a marking-array pattern, explicit
contact classes, guard-run patterns, deterministic multi-family ordering,
primary-route immutability, pinned visual-CI surfaces, stronger RQ6 planning
inputs, five composed held-out factories, and one infeasible negative control.

## 1. Objective

Make Sage capable of producing a complete, credible factory layout of the same
class as the manually built reference factory, while preserving the existing
authority boundary:

```text
user and approved company knowledge express intent
  -> Sage resolves and structures the intent
  -> deterministic InspectorPro tools calculate geometry
  -> deterministic validators prove the result
  -> the user reviews one cumulative unsaved draft
  -> Save requires separate explicit approval
```

The target is not a structurally valid but sparse diagram. The target is a
readable, populated, internally consistent factory plan with departments,
circulation, local work areas, realistic asset groupings, repeated cells,
floor communication, and useful Plan and 3D presentation.

The implementation must remain general. The archived factory is the first gold
benchmark, not a source of hard-coded coordinates, labels, asset IDs, or special
branches.

## 2. Why The Current Result Is Not Acceptable

### 2.1 Measured comparison

| Surface | Manual reference | Staged Sage proof |
|---|---:|---:|
| Zones | 45 | 45 |
| Routes | 8 | 4 |
| Placements | 827 | 54 |
| Floor markings | 50 | 0 |
| Conversation turns | Not applicable | 32 |
| Successful live generation time | Not measured | 367.37 seconds |

The equal zone count concealed the actual quality gap. The staged proof passed
structural checks while omitting most of the content that makes the reference
look and function like a factory.

The manual placement inventory also explains the visual difference. It
contains, among other resources:

- 456 machine-guard panels;
- 138 pallet racks;
- 44 pallets;
- 36 assembly workbenches;
- 20 operator figures;
- 13 lift tables;
- 12 robots;
- 12 robot tooling plates;
- 14 CNC mills and lathes; and
- inspection, maintenance, handling, packaging, and storage equipment.

Its 50 floor markings include 30 parking boxes, 12 keep-clear areas, six
direction arrows, and two crosswalks. The staged proof generated none of this
floor communication.

### 2.2 Root causes

1. **The acceptance gate measured validity, not reference quality.** Counts,
   IDs, containment, Save, and Undo passed even though the result was sparse
   and visually poor.
2. **The full-factory semantic contract is too narrow.** It permits at most 480
   requested assets, G6 independently limits copied placements to 480, and the
   contract currently carries one `seed_cell` and one `cell_replication`
   family. One replication family can fan out to several targets, but multiple
   distinct families cannot coexist in one program.
3. **Conversational G4 amendments replay cumulative placement work.** Each new
   request appends to the prior request list, removes prior generated G4
   placements, recompiles the complete list, invalidates downstream stages,
   and replays them. The observed high-density run reached 147 placements but
   individual turns grew toward the 180-second browser limit.
4. **Per-apply validation also scales with the complete layout.** The current
   apply path compares canonical bytes before and after an operation batch,
   causing two full canonicalize-and-validate passes. Measured 100-item batches
   rose from 1.6 ms/item on an empty layout to 41.3 ms/item near 800
   placements. Removing request replay alone will not meet the amendment
   target.
5. **The engine lacks factory-scale placement recipes.** Repeating one generic
   asset-fit command cannot efficiently express rack banks, guarded robot
   cells, machine rows, parking areas, inspection stations, or packaging
   islands.
6. **G5 and G6 do not yet express multiple independent cell families in one
   program.** A factory needs several seed cells and several distinct
   replication families, not one global seed and one global family.
7. **Primary circulation is only part of the route system.** The reference also
   contains machining cross aisles, internal material aisles, and a service
   aisle that depend on local asset geometry.
8. **Floor communication is absent from full-factory intent.** Parking boxes,
   arrows, crosswalks, and keep-clear areas must be planned and validated as
   first-class entities.
9. **Presentation does not scale with layout density.** Labels overlap in Plan,
   the 3D fit leaves the factory too small, and visual hierarchy does not adapt
   to zoom or hierarchy depth.
10. **The archived manual layout is geometry-rich but semantically incomplete.**
    Its zones are flat rather than carrying the generated G3 parent hierarchy,
    and none of its 827 manually placed assets carries target-area metadata.
    Every benchmark hierarchy and target binding will therefore be derived and
    human-approved rather than copied from authored archive metadata.

## 3. Product Boundary

### 3.1 Sage owns

- understanding the user's factory-planning intent;
- identifying missing decisions that materially affect the plan;
- selecting applicable reviewed factory and cell recipes;
- resolving semantic department, route, asset, and process references;
- creating a coordinate-free Facility Program;
- explaining assumptions, alternatives, unresolved evidence, and validation
  results; and
- translating later user changes into localized semantic amendments.

### 3.2 Deterministic InspectorPro tools own

- coordinates, polygons, route points, transforms, rotations, and stable IDs;
- unit normalization and exact area closure;
- hierarchy, adjacency, containment, and overlap checks;
- catalog identity and exact asset-revision resolution;
- packing, pattern geometry, collision checks, and route obstruction checks;
- cell comparison, module replication, and local reflow;
- floor-marking geometry;
- presentation layout, label collision resolution, and camera fitting;
- operation batching, persistence, receipts, Save, and Undo; and
- every pass/fail result used to promote the draft.

### 3.3 Required refusals

The feature must continue to refuse or ask when a request depends on:

- model-authored coordinates;
- invented regulatory, fire, egress, accessibility, or OSHA values;
- unsupported vehicle or equipment clearances;
- invented production volumes, takt, staffing, or equipment quantities;
- unsupported claims of safety, compliance, capacity, or optimality;
- ambiguous catalog identities; or
- silent asset substitution or count reduction when a requested set does not
  fit.

## 4. Canonical Facility Program

Introduce one revision-bound, coordinate-free `FacilityProgram` as the input
to factory-scale generation. It should compile into existing G1-G6 operations
where those contracts are sufficient and into new deterministic pattern and
presentation operations where they are not.

`FacilityProgram` is a compiler input and immutable run artifact. It may be
persisted for audit, replay, and receipt binding, but it is never the source of
truth for a saved layout and can never override the authoritative layout
document. The layout repository remains the only source of truth for saved
geometry.

Minimum sections:

```text
identity
authority_and_mode
facility_envelope
macro_departments[]
area_hierarchy[]
flow_requirements[]
route_network[]
resource_batches[]
cell_recipes[]
module_families[]
floor_communication[]
presentation_intent
unresolved_requirements[]
```

### 4.1 Resource batch

Each resource batch should carry only semantic and evidence-bound inputs:

```text
batch_id
exact_catalog_identity
quantity
target_area
placement_pattern
semantic_orientation
resource_role
authored_spacing_or_null
ordering_or_grouping
required_relationships[]
placement_dependencies[]
evidence_refs[]
```

No coordinate or transform field is permitted in the model-facing schema.
`placement_dependencies` expresses relational requirements such as one asset
being attached to or supported by another exact member. It never carries the
resulting transform.

### 4.2 Cell recipe

Support multiple recipes in one factory:

```text
recipe_id
target_area
member_batches[]
candidate_strategies[]
selected_strategy_or_objective
authored_spacing_or_null
process_order_or_null
interfaces[]
evidence_refs[]
```

### 4.3 Module family

Support multiple independent replication families:

```text
family_id
source_recipe_or_cell
target_areas[]
allowed_transform_mode
preserve_source
conformance_requirements[]
```

Initial production scope should retain exact translation. Rotation, mirroring,
or reflow must be separate, explicitly authorized deterministic modes.

### 4.4 Floor communication

Represent parking boxes, crosswalks, arrows, lane boundaries, keep-clear areas,
and similar markings as semantic templates bound to routes, areas, or exact
assets. Dimensions must come from the user or an approved policy. The system
must not infer regulatory meaning from a visual marking.

Add a coordinate-free marking-array pattern with an anchor relationship,
count, row/column structure, authored pitch, and semantic orientation. The
deterministic renderer computes each marking position. This is required for
the reference's 30 parking boxes and avoids exposing coordinates to Sage.

### 4.5 Authority modes

Keep three modes visibly distinct:

1. `reference_reproduction`: compile a reviewed Facility Program to verify
   deterministic fidelity. No model interpretation is required.
2. `intent_driven_prototype`: Sage drafts a Facility Program from user intent
   and available product/process knowledge. Unsupported planning inputs remain
   findings or explicit prototype assumptions.
3. `edit_current_draft`: apply a localized semantic change to the active
   receipt chain without rebuilding unrelated scopes.

## 5. Execution Architecture

The user should not have to issue 32 carefully phrased prompts. One complete
request should create one durable program and one internal dependency graph.
InspectorPro should execute it in bounded deterministic substages and expose
progressive checkpoints.

Recommended dependency graph:

```text
facility envelope
  -> macro departments
  -> primary circulation
  -> area hierarchy
  -> resource groups and seed cells
  -> repeated modules
  -> local circulation
  -> floor communication
  -> presentation plan
  -> whole-factory validation
  -> one cumulative review and Save decision
```

Local circulation must follow asset and cell composition when its geometry
depends on those resources. Primary circulation can remain earlier.

Local reflow may not move or recreate a primary route. A requested change that
cannot satisfy that invariant must return a named conflict or explicitly ask
the user for authority to amend the primary route.

Every compiled plan must be immutable and restart-safe. Substages remain under
the existing 500-operation and 500-planned-instance limits. More than 500 total
entities is allowed only by bounded internal substages, never by silently
dropping content.

### 5.1 Frozen performance machine and measurement protocol

The initial numeric gates are bound to this reference machine:

- OS: Microsoft Windows 11 Home, version 10.0.26200, build 26200;
- CPU: 13th Gen Intel Core i7-1355U;
- cores: 10 physical, 12 logical processors;
- RAM: 16,849,256,448 bytes;
- Python: 3.14.0;
- server mode: one local Facility server worker; and
- power state: AC power with no intentional competing benchmark workload.

Every performance artifact must additionally record the InspectorPro source
revision, configuration revision, Playwright version, Chromium executable
revision and checksum, asset-catalog revision, and process count. A changed
profile starts a new baseline rather than being compared silently.

Each p95 gate uses one discarded warmup followed by 20 measured runs. The
artifact retains all raw timings and uses the nearest-rank p95. Deterministic
engine time and provider/network time are reported separately. The 90-second
reference gate applies to browser-visible deterministic execution of a frozen
Facility Program, not to variable provider latency.

For full construction, every non-final placement substage must contain between
100 and 500 planned instances. The final remainder may contain fewer than 100,
and a smaller dependency-atomic group is allowed only when the receipt names
why it cannot be combined safely. Local amendments are not padded with no-op
placements; they use scoped validation and the separate 10-second gate.

## 6. Implementation Phases

Use the `RQ` namespace to avoid collision with the already shipped G1-G7 and
KF0-KF7 programs.

### RQ0 - Freeze The Gold Benchmark And Honest Baseline

Tasks:

1. Keep `fl-reference-manual-20260812` immutable and retain the blank `fl-main`
   default.
2. Create a machine-readable reference manifest containing all 45 zones, eight
   routes, 827 placements, 50 markings, exact catalog revisions, and current
   validation findings.
3. Derive candidate parent-child area relationships and placement-to-area
   bindings from geometry. Mark them `derived`, never `authored`.
4. Review and approve the intended hierarchy, target-area bindings, asset
   groupings, route roles, repeated cell families, and intentional contacts or
   overlaps.
5. Capture canonical Plan and 3D images at fixed desktop viewports.
6. Record the current staged proof as the failing baseline rather than a
   success artifact.
7. Measure the archive's contact set and classify every allowed relation as
   panel abutment, supported/surface-attached asset, operator/work-envelope
   containment, or another explicitly named class. Unclassified overlap is a
   finding, not an automatic allowance.

The named RQ0 prototype benchmark approver is **Shadrack, acting as InspectorPro
product owner**. This approval freezes a reconstruction benchmark only. It is
not manufacturing-engineering, safety, compliance, or production approval.
Approval must be captured in a revision-bound review receipt with reviewer
identity, timestamp, source archive revision, manifest revision, every accepted
derived relationship, every allowed contact class, and all unresolved items.

Exit gate:

- every reference entity appears exactly once in the manifest;
- every derived hierarchy and target-area binding is reviewed against spatial
  containment, asset purpose, route access, and repeated-cell membership;
- ambiguous derived relationships remain unresolved and block gold-manifest
  approval rather than being guessed;
- the named approver and review receipt are present;
- the contact/overlap allowlist contains a reason and relationship for every
  accepted exception;
- archive bytes and revision remain unchanged;
- baseline score names the missing 4 routes, 773 placements, and 50 markings;
- no visual-quality score is inferred from structural validity.

### RQ1 - Facility Program Contract And Lossless Compiler

Tasks:

1. Define the closed `FacilityProgram` schema and authority vocabulary.
2. Replace singular seed/replication fields with arrays of cell recipes and
   module families.
3. Add resource batches, local routes, floor communication, and presentation
   intent.
4. Resolve exact catalog IDs and revisions server-side.
5. Compile to a deterministic operation-plan artifact before modifying a
   draft.
6. Preserve existing G1-G7 adapters; do not create a parallel layout store.
7. Add a reference-manifest adapter used only by
   `reference_reproduction` mode.
8. Raise `FULL_FACTORY_MAX_TOTAL_ASSET_QUANTITY` and
   `G6_MAXIMUM_COPIED_PLACEMENTS` from 480 to **900**. Keep individual
   operation and planned-instance substages capped at 500.
9. Keep the model-facing intent compact: quantities and recipe references are
   batched rather than expanded into per-instance objects. A provider tool
   response remains within 16,384 bytes; runtime semantic slices remain within
   8,192 bytes and the 9,600 estimated-token assembled-context target. Larger
   resolved programs live in revision-bound server artifacts and are retrieved
   by stage, never injected whole into model context.

Exit gate:

- the reviewed reference manifest can be represented without free-form
  flattening or hidden coordinates in the model-facing contract;
- unknown fields fail closed;
- both 480-placement constants are reconciled at 900 and boundary tests cover
  899, 900, and 901 placements;
- the 900-placement program passes model-response, stage-slice, and persisted-
  artifact byte-budget tests without truncation;
- every technical dimension has user, catalog, or policy provenance;
- serialization stays within the runtime byte budget through staged slices,
  not by truncation;
- reference-specific labels and IDs do not appear in generic compiler logic.

### RQ2 - Factory-Scale Incremental Execution

Tasks:

1. Stop replaying all prior G4 requests for every conversational amendment.
2. Compile a complete resource stage once, grouped by target area and
   dependency.
3. Add append-only or localized replacement semantics for one resource batch.
4. Use the existing spatial index for collision candidates rather than
   repeated whole-layout pair scans.
5. Cache exact-revision catalog footprints and target-area free-space models
   for one immutable program revision.
6. Split 827+ placements and downstream operations into restart-safe batches
   under the 500-item limits.
7. Preserve one cumulative diff, one Save boundary, and one exact Undo.
8. Build a placement dependency DAG from support, surface-attachment, and
   other exact member relationships. Topologically order placements before
   batching; missing supports and cycles block compilation.
9. Bind every substage receipt to its prerequisite receipt IDs. Resume may
   execute a dependent batch only after all support batches are complete and
   revision-matched. Deletion or rollback follows reverse dependency order.
10. Cache the canonical before revision, avoid duplicate whole-layout
    canonicalization in one apply, and use dependency-scoped validation for
    intermediate local changes followed by one complete final validation.
11. Publish the measured cost curve for supported batch sizes and enforce the
    100-item non-final construction floor from Section 5.1.

Exit gate on the frozen reference machine:

- first macro preview at or below 10 seconds p95;
- complete 45-zone, 8-route, 827-placement, 50-marking deterministic draft at
  or below 90 seconds p95;
- one localized batch amendment at or below 10 seconds p95;
- no substage exceeds either 500-item limit;
- all 12 known reference surface attachments are ordered after their supports;
- dependency cycles, missing supports, and resume-before-prerequisite cases
  fail closed;
- every non-final full-build placement batch contains 100-500 instances unless
  a dependency-atomic exception is named in its receipt;
- no O(n-squared) replay growth in the measured asset-density sweep;
- restart resumes at the next unfinished substage without replaying completed
  work.

### RQ3 - Deterministic Industrial Placement Patterns

Add reusable pattern solvers for the high-density structures visible in the
reference factory:

- pallet-rack banks and finished-goods rows;
- machine rows and machine islands;
- guard-run and guarded-enclosure patterns with explicit panel-abutment rules;
- guarded robot cells composed from a guard enclosure and exact internal
  resources;
- assembly benches and operator positions;
- inspection stations;
- packaging islands;
- parking and staging areas; and
- maintenance and utility groups.

Each pattern must define required inputs, supported orientations, fit
constraints, stable ordering, output metrics, and explicit failure reasons.
Patterns may optimize a stated geometric objective such as smallest envelope
or shortest internal centerline. They must not claim safety, throughput, or
operational optimality.

Exit gate:

- all 827 reference placements compile through generic patterns or explicit
  reviewed singleton batches;
- requested quantities and exact revisions are preserved;
- every placement has one target-area binding;
- no silent partial batch succeeds;
- containment and collision rules pass, except reviewed intentional contacts
  represented explicitly;
- at least three held-out factory variants use the same pattern code without
  reference-specific branches.
- guard-run coverage includes one dense enclosure, one open-sided enclosure,
  and one zero-guard negative-control factory.

### RQ4 - Multiple Cell Families And Repeated Modules

Tasks:

1. Support multiple independent G5 cell recipes in one generation run.
2. Support multiple G6 module families without superseding prior families.
3. Allow one family to include guarding, tooling, operators, and local
   markings where those are explicit recipe members.
4. Preserve exact relative geometry, revisions, relationships, and target
   identities.
5. Report source/replica conformance and drift.
6. Keep occupied-target replacement and transform variants out of scope until
   separately qualified.
7. Resolve family dependencies first, then use stable `family_id` order. Two
   families that target overlapping areas fail with a named conflict unless
   the program explicitly declares them composable and their member scopes are
   deterministically disjoint. Last-writer-wins behavior is forbidden.

Exit gate:

- all twelve robot cells and all assembly, inspection, packaging, and storage
  families in the reviewed reference program are created in one run;
- adding or changing one family leaves unrelated families byte-identical;
- replicated assets receive new stable identities while retaining exact
  catalog revisions;
- family conformance is deterministic and revision-bound.
- repeated runs use the same family order, and overlapping-family fixtures
  either prove disjoint composition or fail without mutation.

### RQ5 - Complete Route Network And Floor Communication

Tasks:

1. Separate primary interdepartment routes from local department/cell routes.
2. Generate local routes after resource geometry is known.
3. Preserve route names, kinds, widths, directionality, and bindings.
4. Detect asset, guard, protected-area, shell, and route conflicts.
5. Generate authored marking templates at derived route, parking, cell, or
   equipment relationships.
6. Validate route reachability, crossings, dead ends, marking coverage, and
   revision consistency without making safety or capacity claims.
7. Implement marking arrays for repeated parking boxes, arrows, and other
   authored patterns using relational anchors, exact count, authored pitch,
   and semantic orientation.
8. Enforce byte identity for primary routes during local route and marking
   reflow.

Exit gate:

- the reference program produces eight routes and 50 markings with exact
  semantic identities and approved dimensions;
- all required department and cell destinations are reachable as authored;
- route and marking geometry avoids unapproved obstructions;
- missing width, clearance, vehicle, or policy evidence asks or refuses rather
  than inventing a value;
- local route changes preserve unaffected departments, cells, and primary
  routes byte for byte.

### RQ6 - Facility Planning Knowledge For Novel Factories

Reproducing a reviewed program proves execution, not planning intelligence.
Novel factory generation needs a revision-bound Facility Planning Package.

Minimum inputs:

- process steps and precedence;
- department or station ownership;
- equipment requirements and exact catalog candidates;
- quantities or the authored demand/cycle-time data used to calculate them;
- material and WIP classes;
- storage and staging requirements;
- staffing or operator-station requirements;
- approved clearance and route policies when available;
- utilities, service access, floor loading, and anchoring evidence when
  available; and
- uncertainty, source provenance, and review status.

Realistic intent-driven generation additionally requires process routing,
relative production volume or authored takt, asset-to-process capability
mapping, and explicit adjacency/separation requirements. If any required input
is absent, Sage may reproduce a reviewed recipe or produce a visibly labelled
prototype with findings; it may not describe the result as a realistic
production plan.

Use the existing MMLE-50D synthetic process package for prototype evaluation,
but label all synthetic planning facts as illustrative and
`productionEligible: false`. Sage may propose a prototype from reviewed
synthetic facts; it may not promote them to production authority.

Exit gate:

- Sage can state which planning inputs caused every department, resource batch,
  route, and cell recipe;
- missing equipment counts or policy values produce findings rather than
  generic defaults;
- a changed process step invalidates only affected planning and layout scopes;
- the same planner produces materially different valid programs for at least
  three different process packages.

### RQ7 - Conversational Orchestration And Visual Presentation

Conversational tasks:

1. Accept one complete request or build a complete request through concise
   clarification turns.
2. Parse once into a Facility Program, then let server-owned continuation
   execute deterministic stages. Model text cannot enqueue itself.
3. Show progressive checkpoints: macro plan, circulation, populated cells, and
   final review.
4. Support unpredictable follow-ups such as rename, resize, add/remove batch,
   change cell strategy, relocate a route semantically, or lock an area.
5. Recompute only the smallest dependency scope and explain what changed.

Presentation tasks:

1. Add deterministic label collision management.
2. Use semantic zoom: macro labels at overview, child/cell labels when zoomed,
   and asset labels only on selection or sufficient scale.
3. Keep labels inside available zones where possible; otherwise use bounded
   leaders or suppress lower-priority labels.
4. Add route, marking, zone, cell, and asset layer controls.
5. Fit Plan and 3D cameras to occupied content with stable margins.
6. Ensure assets remain visually inspectable in 3D through suitable camera,
   LOD, contrast, and floor opacity.
7. Keep the chat panel from obscuring the primary proof capture.

Visual CI uses these pinned surfaces:

- 1920 x 1080 desktop, device scale factor 1;
- 1440 x 960 desktop, device scale factor 1; and
- 390 x 844 narrow viewport, device scale factor 1, with overview labels
  intentionally reduced by semantic zoom.

The selected UI font must be bundled locally and checksum-pinned; visual gates
may not depend on a network font fetch. Tests capture fit-to-content overview,
2x detail, and 4x detail zoom states. A label-label intersection area greater
than 1 CSS pixel is a failure for labels that the semantic-zoom policy says
must be visible. Suppressed lower-priority labels are recorded and tested,
not treated as zero-size successes.

Exit gate:

- one user request can reach a final draft without 32 user-authored turns;
- one provider intent pass plus deterministic continuation is the normal path;
- no label-label overlap under the pinned viewport, font, and zoom definition;
- lower hierarchy labels appear at the correct zoom without shifting geometry;
- Plan and 3D show the same entity IDs and revision;
- the occupied factory fills 65-90% of the available proof viewport in both
  views;
- follow-up edits meet the RQ2 localized latency budget.

### RQ8 - Reference-Quality Evaluation And Promotion

Build a two-level benchmark.

#### Level A: Reference reproduction

The reviewed reference Facility Program must produce:

- 45 zones;
- eight routes;
- 827 placements;
- 50 floor markings;
- exact requested catalog revisions and quantities;
- reviewed hierarchy and target-area assignments;
- deterministic validation with no concealed partial result;
- readable Plan and 3D captures; and
- one unsaved cumulative draft with exact Undo.

Level A grades against the human-approved RQ0 reconstruction manifest, not
against semantic metadata that already existed in the archive. The archive is
authoritative for geometry and entity content; Shadrack's revision-bound RQ0
receipt is authoritative only for the derived hierarchy, target-area bindings,
module-family interpretation, and allowed-contact classes used by this
prototype benchmark.

Exact coordinate equality is required only in `reference_reproduction` mode.
Intent-driven generation is judged by constraints and quality metrics, not by
pixel-copying the manual layout.

#### Level B: Generalization

Use at least five held-out factory programs that differ in envelope, process
flow, department count, density, cell families, route topology, and asset mix.
The set must include a guard-dense factory, a factory with no guarding, a
factory exceeding 500 placements, a loop- or spine-route topology, and a
factory with several differently sized cell families. These may share other
traits but must be separate frozen programs. Add one infeasible negative
control that must fail cleanly without count reduction or degraded output.
None may reuse the reference labels as an implementation shortcut.

#### Promotion thresholds

| Metric | Required |
|---|---:|
| Requested entity count and identity | 100% |
| Exact catalog-revision binding | 100% |
| Required hierarchy and target bindings | 100% |
| Unapproved overlap or containment violations | 0 |
| Required route reachability | 100% |
| Unsupported safety/compliance/capacity claims | 0 |
| Silent asset reduction or substitution | 0 |
| Label overlaps at pinned viewports/zooms | 0 |
| Plan/3D entity and revision parity | 100% |
| Full reference generation p95 | <= 90 seconds |
| Local amendment p95 | <= 10 seconds |
| Saved-layout mutation before approval | 0 |
| One Undo restores exact base | 100% |

Automatic failure conditions:

- reference-specific hard-coding in generic planners;
- any model-authored coordinate entering authoritative geometry;
- invented regulatory, safety, capacity, or planning values;
- a partial asset batch represented as complete;
- a screenshot that is structurally correct but visibly sparse, unreadable, or
  incorrectly framed;
- hidden failed stages or unresolved blocking findings;
- automatic Save or automatic grant of human authority; or
- passing only the reference case while failing held-out programs.

## 7. Milestones And Ordering

### Milestone 1: Engine proof

RQ0 -> RQ1 -> RQ2 -> RQ3 -> RQ4 -> RQ5

Compile the reviewed reference program directly, without an LLM. Do not proceed
to claims about Sage's planning intelligence until the deterministic engine can
produce a credible reference-scale factory within the latency budget.

### Milestone 2: Sage proof

RQ6 -> conversational portion of RQ7

Demonstrate that Sage can create or amend the same coordinate-free Facility
Program from user intent and reviewed planning knowledge.

### Milestone 3: Product proof

Presentation portion of RQ7 -> RQ8

Prove visual quality, generalization, performance, revision safety, Save, Undo,
and authority handling in production-browser runs.

RQ7 presentation work can begin in parallel after the RQ1 program and RQ0
visual baselines are frozen. It must not be used to disguise missing factory
content.

RQ3 and RQ5 fixture and contract authoring may begin after RQ1 freezes the
schema. Their execution integration must wait for RQ2. RQ4 implementation must
also wait for RQ2 because family behavior depends on the new incremental
execution substrate. RQ6 knowledge authoring may proceed independently but
does not gate Milestone 1. Level B fixtures may be drafted early; their hashes
must be frozen before RQ6 or provider tuning uses them.

## 8. Required Evidence Per Phase

Every phase must publish:

- the exact source and configuration revision;
- deterministic unit tests and property tests;
- positive, ambiguous, contradictory, and unauthorized cases;
- immutable operation and validation receipts;
- before/after entity counts and identities;
- latency and memory measurements where applicable;
- saved-state and one-Undo proof;
- production-browser screenshots when a visual surface changes; and
- an explicit list of unresolved limitations.

Provider evaluation must use held-out paraphrases not used to author parser
rules. A provider shadow may propose intent but cannot write, approve, or save.

## 9. What Not To Do

- Do not solve this by adding more few-shot examples to the system prompt.
- Do not encode the manual factory as a special prompt or code branch.
- Do not use the model to emit 827 transforms.
- Do not require the user to issue one prompt per asset group.
- Do not raise count limits without fixing cumulative replay and batching.
- Do not call a layout complete because entity validation passed.
- Do not use decorative duplicate assets merely to make the viewport look
  full.
- Do not infer production quantities, safety clearance, or route adequacy from
  the reference appearance.

## 10. Review Questions For Claude

1. Is `FacilityProgram` the correct canonical boundary, or should an existing
   contract be extended instead?
2. Can all behavior-bearing content in the reference be represented without
   exposing coordinates to Sage?
3. Is the proposed split between primary and local circulation correct?
4. Should floor communication be its own deterministic stage or part of local
   circulation and cell recipes?
5. Is the G4 replay diagnosis complete, and what data structure best supports
   localized amendments without creating a second source of truth?
6. Are multi-cell recipe arrays and multiple module families sufficient to
   eliminate the singular G5/G6 limitation?
7. Are the 90-second full-reference and 10-second local-edit p95 targets
   realistic on the frozen machine?
8. Which reference contacts or overlaps require explicit policy before zero-
   overlap can be an honest gate?
9. Are the label-overlap, semantic-zoom, and occupied-viewport thresholds
   deterministic enough for CI?
10. Does RQ6 require additional authored planning inputs before Sage can claim
    to generate a realistic factory rather than reproduce a reviewed recipe?
11. Do the five required held-out factories plus the infeasible negative
    control adequately detect reference-specific overfitting?
12. Which phases can safely run in parallel without weakening the Milestone 1
    engine-first gate?

## 11. Definition Of Done

This effort is complete only when a user can describe a factory at the level of
intent, Sage can resolve that request into a traceable coordinate-free program,
InspectorPro can generate a dense and readable reference-quality unsaved draft
within the performance budget, and every entity and claim can be traced to
user input, approved knowledge, an exact catalog revision, or a disclosed
prototype assumption.

The result must remain fluid under later instructions. A valid follow-up should
change only the affected dependency scope, preserve unrelated identities and
geometry, regenerate the presentation, and return a new cumulative review diff
without requiring the user to reconstruct the factory from the beginning.
