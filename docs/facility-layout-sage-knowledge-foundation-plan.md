# Sage Facility Layout Knowledge Foundation Plan

Status: Revision 4; KF0 through KF4 implemented and verified on 2026-08-26

## 1. Objective

Create the complete knowledge and execution foundation that lets a user work at
the level of manufacturing intent:

```text
user intent
  -> Sage resolves meaning and constraints
  -> Sage selects semantic Facility Layout capabilities
  -> deterministic InspectorPro tools calculate and validate geometry
  -> the viewport shows the work live
  -> execution receipts prove what changed
  -> the user reviews and saves the resulting revision
```

Sage must not become a second geometry engine, imitate mouse clicks, invent
clearances, or write directly into layout storage. The persisted Facility Layout
document, deterministic operation kernel, spatial validators, and revision
service remain authoritative.

The first executable capability after the core foundation is qualified will be:

> From an empty layout, create a facility of any supported size and unit, then
> divide it into the requested number of correctly labeled departments using
> the user's requested proportions, arrangement, orientation, and adjacency.

"Any" means within explicit product bounds and operation budgets. It does not
mean unbounded geometry or an unlimited number of entities.

## 2. Existing Foundation Verified In The Repository

The implementation must extend these existing capabilities rather than create
parallel versions:

1. `ai_inspector/facility_layout/operations.py`
   - immutable, deterministic, all-or-nothing operation batches;
   - stable operation receipts and exact diffs;
   - zone, placement, route, aisle, utility, process-binding, plan-setting, and
     clear-layout operations;
   - a maximum batch of 500 operations.
2. `ai_inspector/facility_layout/plan_settings.py`
   - facility width and depth from 0.5 m through 10,000 m;
   - authoritative plan boundary and metric storage;
   - grid and major-grid validation.
3. `ai_inspector/facility_layout/semantic_model.py`
   - `FACILITY_COMMAND_SEMANTICS` for the current UI vocabulary;
   - `CELL_LAYOUT_STRATEGIES` for ten cell forms;
   - authored, derived, inferred, and unknown evidence states;
   - exact area, hierarchy, route, fit, clearance, access, provenance, and
     module-fit analysis.
4. `static/index.html`
   - the current ribbon command IDs, labels, icons, titles, and handlers.
5. `static/facility_layout_patterns.js`
   - deterministic implementations for line, L, U, grid, parallel,
     serpentine, loop, spine, herringbone, and cluster arrangements;
   - linear, circular, perimeter, mirror, swap, stack, and surface operations.
6. `ai_inspector/facility_layout/semantic_plan.py` and `planner.py`
   - coordinate-free semantic intent compiled into deterministic placement and
     route alternatives;
   - raw model-authored geometry and approval claims rejected;
   - preview artifacts remain separate from saved layouts.
7. `ai_inspector/facility_layout/agent_runtime.py` and `orchestration.py`
   - bounded, revision-bound Sage reads;
   - exact-move and whole-layout preview boundaries;
   - tool-call, response-size, elapsed-time, and repair budgets;
   - the current shared Sage default is
     `claude-sonnet-4-5-20250929`, but Facility Layout and other Sage paths read
     the same `INSPECTORPRO_SAGE_ANTHROPIC_MODEL` override; Facility model
     isolation is not currently enforced.
8. `ai_inspector/facility_layout/feature_flags.py`
   - the existing ordered capability ladder: `viewer_v2`, `asset_library`,
     `manual_edit`, `constraints`, `routing`, `agent_preview`, and
     `agent_write`;
   - dependency enforcement that prevents agent writes before the read,
     manual-edit, constraint, route, and preview surfaces are available.
9. `ai_inspector/facility_layout/observation.py`, `fit_analysis.py`,
   `chat_intent.py`, and `chat_context.py`
   - bounded observation and agent tool schemas;
   - physical asset-fit analysis;
   - intent classification, entity resolution, and revision-bound context.
10. `ai_inspector/facility_layout/authority_repository.py`
    - authority and review records that must remain separate from geometric
      feasibility and model confidence.
11. `ai_inspector/facility_layout/intelligence_evaluation.py`
    - the existing deterministic and provider-shadow evaluation harness;
    - 71 existing intent cases and twelve established gates that must be
      reused as regression evidence, not relabeled as new held-out evidence.
12. `ai_inspector/agent_skills/generate-facility-layout/`
    - a hierarchical macro-to-micro planning procedure;
    - read, preview, evidence, and commit separation;
    - a current `compatible_models` declaration for the `claude-sonnet` family,
      which must be revised explicitly rather than inferred from another
      workflow's model setting.
13. Existing tests and evaluation evidence
   - deterministic semantic, spatial, routing, operation, service, browser,
     agent-runtime, and provider-loop coverage;
   - a saved 827-placement reference facility with six parent departments;
   - a historical report recording 647 passed, 12 failed, and 1 skipped, which
     is stale relative to later source changes and therefore cannot serve as
     the implementation baseline without a fresh run and disposition.

## 3. Gaps This Plan Must Close

1. The UI command definitions and Python semantic command definitions are
   separate sources that can drift.
2. Current command knowledge is descriptive but does not consistently include
   full inputs, defaults, prohibited uses, failure codes, downstream tools,
   receipts, or deterministic handler ownership.
3. Most UI authoring commands remain `ui_only`; Sage can read, preview an exact
   move, or request one whole-layout preview, but it cannot yet orchestrate the
   complete semantic command set stage by stage.
4. Semantic Plan v1 focuses on resources and zones inside an existing plan. It
   does not provide a general facility-envelope and arbitrary department
   partition contract.
5. The current generation skill requires one complete preview and explicitly
   avoids incremental construction. The desired product requires resumable,
   visible, stage-based execution without reverting to click simulation.
6. Ten cell strategies are documented and implemented in the browser, but the
   server-side bounded alternative analyzer currently compares only line, L,
   and U arrangements.
7. Existing cell placement uses physical footprints and preferred gaps, but
   many assets still lack authoritative load, unload, operator, service,
   maintenance, utility, swept-envelope, or clearance interfaces.
8. The recovered manual build is not yet represented as structured intent,
   tool-choice, receipt, and validation examples.
9. There is no frozen staged evaluation proving that Sage selects the correct
   deterministic capability for broad paraphrases and refuses incorrect ones.
10. Current runtime limits constrain the proposed stage executor: ten tool calls
    per turn, 16,384 response bytes, a 12,000 `bytes4` estimated-token context
    limit, 300/600-second cursor/turn lifetimes, 500-operation batches, and 500
    planned instances.
11. The existing evaluation harness already covers much of the proposed test
    surface. Building a parallel harness would fragment release evidence.
12. The current preview guarantee binds one exact diff and its dependencies to
    one later approval. A multi-stage draft needs an equivalent cumulative
    approval contract, not ten unrelated approvals or commits.
13. The existing cell-strategy records already contain thirteen useful fields.
    The missing knowledge is concentrated in four field groups: space model,
    interfaces, access assumptions, and result metrics.
14. Facility evaluation does not have workflow-scoped provider, model, or
    OpenAI reasoning-effort settings, and the skill's `compatible_models`
    declaration is parsed but not enforced against the effective provider
    model.
15. Context size currently uses the `bytes4` estimate
    `ceil(canonical_bytes / 4)`, not a model tokenizer. A nominal token limit
    must not be described as exact.
16. `FacilityPendingOperationStore` is a 30-minute in-memory follow-up cache,
    not a restart-safe home for durable generation runs or receipt chains.

## 4. Runtime Budgets And Execution Invariants

The knowledge foundation must fit the running system rather than assume an
unbounded agent loop. The initial implementation retains these current limits:

| Constraint | Current limit | Foundation rule |
| --- | ---: | --- |
| Agent tool calls | 10 per turn | A durable run may span turns; no turn exceeds ten calls. |
| Tool response | 16,384 bytes | Every observation, registry slice, and receipt response remains below this bound. |
| Skill context | 12,000 `bytes4-v1` estimated tokens | New context packages target at most 9,600 estimated tokens, preserving 20% headroom below the hard limit. |
| Cursor lifetime | 300 seconds | Cursors paginate bounded reads; they are never resume tokens. |
| Turn lifetime | 600 seconds | Durable run and stage receipts survive conversational turn expiry. |
| Operation batch | 500 operations | Every atomic draft transaction remains at or below the kernel cap. |
| Planned instances | 500 instances | Larger logical stages are deterministically partitioned. |

Implementation decisions:

1. An `authorized_draft_run` has a durable run ID, workspace/layout scope, user
   scope, base revision, effective provider/model/reasoning configuration,
   intent hash, dependency fingerprint, ordered stage graph, and current resume
   point.
2. A persistent server-authoritative `FacilityGenerationRunRepository` in
   `ai_inspector/facility_layout/generation_run_repository.py`, backed by the
   configured Facility workspace storage, owns generation runs and receipt
   chains and the session-to-active-run mapping.
3. A stage may span more than one conversational turn. Progress is recovered
   from the run repository, never from replayed prose or an expired cursor. A
   server-side coordinator schedules at most one next bounded turn only while
   the explicitly authorized run is eligible to continue; blocked, cancelled,
   expired, or budget-exhausted runs never self-advance.
4. A stage-specific command/strategy slice is limited to 8,192 canonical JSON
   bytes. Under the current `bytes4-v1` estimator this reports at most 2,048
   estimated tokens, so there is no separate 2,500-token slice limit. Every
   artifact records canonical bytes, estimator ID, and estimated tokens. The
   assembled context targets at most 9,600 estimated tokens and fails closed
   above the existing 12,000 estimated-token hard limit. Every tool response
   remains below 16,384 bytes.
5. A logical stage requiring more than 500 operations is split into ordered
   provisional substages. Each substage is independently validated and
   reversible, but the chain is not persistable until all required substages
   are valid.
6. The 827-placement reference factory is therefore never represented as one
   oversized operation batch. Its bounded substage receipts form one ordered
   draft chain.
7. Final Save presents one cumulative diff from the saved base revision to the
   current draft, bound to the complete ordered receipt chain and dependency
   fingerprint. The user approves that cumulative diff once.
8. If an upstream dependency changes, affected receipts remain immutable but
   become superseded or stale, all dependent stages become invalid, and Save is
   blocked until the affected chain is rerun and valid.
9. The repository performs one atomic persistence step after approval. No
   provisional stage, timeout, retry, or partial chain may persist implicitly.
10. Multiple sessions may hold read-only preview runs, but only one writable
    run lease may exist for a layout. Lease acquisition and update are guarded
    by an `O_CREAT | O_EXCL` lockfile or equivalent OS-level cross-process
    single-writer primitive. After acquiring the lock, the repository reloads
    lease state and performs a revision compare-and-swap before atomic replace.
    Lock metadata carries an owner token; normal release occurs in `finally`,
    and bounded stale-lock recovery is explicit and tested. A competing edit or
    save makes the older run stale; generated drafts are never merged
    automatically.
11. `FacilityPendingOperationStore` keeps its existing 1,800-second TTL only
    for legacy read-only follow-ups. Generation session-to-run resolution lives
    in the durable repository and is worker-independent. Unsaved generation
    runs expire after 24 hours without activity; transient draft payloads are
    garbage-collected and a minimal terminal tombstone is retained for 30 days.
    Receipt chains bound to a saved revision follow that revision's retention.
12. Every baseline, provider-shadow, and generated run asserts its effective
    provider, model, and reasoning effort against the KF0-frozen configuration
    before the first model call. A model mismatch fails with
    `facility_model_mismatch`; any other provider configuration mismatch fails
    with `facility_provider_config_mismatch`. Recording a mismatch is not
    sufficient.

All limits and slice sizes require boundary tests in the first schema/compiler
milestones. Raising a budget requires a measured, reviewed contract change; it
is not an implementation convenience.

## 5. Non-Negotiable Ownership Boundaries

### Sage owns

- intent interpretation;
- scope and entity resolution;
- separation of hard constraints, preferences, and assumptions;
- semantic tool selection;
- stage and dependency planning;
- choosing among deterministically feasible alternatives;
- concise progress and blocker reporting;
- asking for a human decision when no valid interpretation remains.

### Deterministic InspectorPro code owns

- unit conversion;
- coordinates and transforms;
- polygon construction and partitioning;
- footprint, clearance, route, and containment geometry;
- pattern member placement;
- cell-layout feasibility and scoring metrics;
- collision and boundary validation;
- operation batches, diffs, undo, preview, and save receipts;
- revision, authorization, and stale-state checks.

### The user owns

- business intent and priorities;
- authored dimensions, process sequence, quantities, and adjacency requests;
- acceptance of disclosed assumptions and tradeoffs;
- explicit authorization to save a revision;
- approval of safety, compliance, and production engineering evidence.

## 6. Required Knowledge Artifacts

### K1. Facility Domain Ontology

Define canonical entities and relationships:

- facility envelope and coordinate frame;
- department and nested subzone;
- route and aisle;
- manufacturing cell and cell member;
- asset definition and placement occurrence;
- floor marking;
- utility network;
- process binding and flow;
- physical, access, service, safety, and expansion constraints;
- preview, unsaved draft, saved revision, and execution receipt.

Every entity must have stable identity, parentage, evidence status, lifecycle,
and allowed relationships. A label cannot substitute for entity type or
containment.

### K2. Sage Responsibility Contract

Document and enforce:

- what Sage may decide;
- what Sage must inspect before deciding;
- when defaults are allowed;
- when clarification is required;
- what Sage may preview or mutate;
- what requires explicit save authorization;
- what Sage must never claim without a receipt;
- how Sage reports assumptions, infeasibility, and unsupported policy.

### K3. Canonical Facility Tool Registry

Replace duplicated semantic command definitions with one versioned registry
consumed by both the browser and server. Presentation-only properties may stay
in the UI, but command identity and behavior must share one contract.

Each command record must contain:

```text
commandId
label
semanticIntent
correctUseCases[]
incorrectUseCases[]
supportedStages[]
entityScope
effect: read | viewport | draft_edit | persistent_save | viewport_capture
requiredContext[]
inputSchema
defaultPolicy
preconditions[]
deterministicOwner
validationRules[]
failureCodes[]
receiptShape
undoSemantics
compatibleNextCommands[]
incompatibleCommands[]
agentAvailability
uiCommandId
```

`effect` uses the existing runtime vocabulary exactly. Preview eligibility is
represented by `agentAvailability`, preconditions, and the feature-flag
capability chain; it is not a fabricated effect value.

The registry must support deterministic queries by stage, capability, entity
scope, and command ID. Sage receives a bounded slice satisfying the limits in
Section 4, never the full serialized registry.

The registry must cover the complete current command surface, including Assets,
Select, Pan, zone tools, Aisle, Floor Marking, arrangement, positioning,
patterns, cell creation, stacking, surface placement, history, Fit, Auto
Arrange, Save, 3D navigation, and recording.

Low-level storage operations such as `add_zone` and `move_placement` remain
private implementation details. Sage selects semantic commands, not mutation
kernel handlers.

### K4. Facility Intent Contract

Create a coordinate-free, versioned intent schema containing:

- greenfield, brownfield, or scoped-modification mode;
- requested facility dimensions and source unit;
- requested origin/orientation convention;
- department names, semantic types, quantities, proportions, minimums, and
  maximums;
- requested bands, rows, columns, adjacency, separation, and flow direction;
- circulation, cell, resource, staging, marking, utility, and expansion intent;
- hard constraints, preferences, assumptions, and unresolved items;
- source revisions and authority bindings;
- requested execution mode and save policy.

The model may provide semantic relationships and source units. It may not
provide world coordinates, transforms, screen positions, or generated safety
requirements.

### K5. Facility Stage And Dependency Model

Define the generation stages as typed nodes in a resumable dependency graph:

1. facility envelope and plan settings;
2. macro departments;
3. primary circulation and crossings;
4. department subdivisions;
5. department resources and staging;
6. seed manufacturing cells;
7. repeated cells, rows, and modules;
8. floor communication and support details;
9. full deterministic validation;
10. review and explicit save.

Each stage records inputs, dependent stages, selected semantic commands,
preview ID, operation receipts, validation result, affected stable IDs,
assumptions, unresolved findings, and status. A failed stage must be resumable
without replaying successful unrelated stages.

Stage receipts are provisional draft evidence. A durable run additionally
records workspace/layout/user scope, base revision, effective provider, model,
reasoning effort, intent hash, ordered receipt chain, invalidation edges,
writable lease, activity/expiry timestamps, cumulative diff hash, and save
eligibility. One final proposal binds the complete valid chain to the exact
cumulative diff approved by the user.

### K6. Asset Planning Semantics

For every planning-ready asset, distinguish known from unknown:

- revision-bound physical footprint and height;
- mobility and allowed support relationships;
- authored front, operator, load, unload, input, output, and service sides;
- maintenance and door/drawer access envelopes;
- known swept or operating envelope;
- authored clearance records and policy source;
- utility interfaces;
- stack and support-surface compatibility;
- permitted zone roles and process capabilities;
- planning-readiness status and unresolved evidence.

Generic class knowledge may suggest alternatives but cannot promote unknown
interfaces or clearances into authored fact.

### K7. Cell Strategy And Recipe Registry

Retain the ten geometric strategies:

- line;
- L;
- U and inverted U;
- grid;
- parallel;
- serpentine;
- loop;
- spine and branch;
- herringbone;
- cluster.

Represent named manufacturing concepts such as guarded robot cell, assembly
cell, straight assembly line, kitting island, inspection station, packaging
station, rack row, and equipment-parking module as recipes composed from the
strategies and semantic tools. They are not additional geometry engines.

The existing strategy records already define thirteen fields, including
advantages, avoid conditions, best-fit cases, semantic intent, required inputs,
tradeoffs, validators, variants, and evidence qualification. Extend that
contract rather than rewriting it. The required additions are four structured
field groups: space model, interfaces, access assumptions, and result metrics.

Each recipe composes registered strategies and tools and defines its required
evidence, process fit, variants, prohibited conditions, and deterministic
validators. Recipes cannot bypass strategy feasibility or introduce another
placement engine.

### K8. Cell Feasibility Contract

Generalize the server-side feasibility analyzer to all ten strategies. The
line/L/U vocabulary currently appears in `semantic_model.py`, the agent-facing
tool-schema enum in `observation.py`, and the runtime default in
`agent_runtime.py`; all three surfaces plus browser strategy IDs must migrate
together under exact parity tests. Inputs:

- exact target-zone polygon;
- exact physical footprints;
- authoritative clearance and access envelopes when available;
- process order and material endpoints when authored;
- operator count and interfaces;
- route connections and protected areas;
- locked/manual members;
- expansion preference.

Outputs must rank only feasible candidates and state exact blockers for rejected
candidates. Useful metrics include required width/depth, physical footprint,
envelope area, minimum physical gap, contiguous free area, route connectivity,
operator-travel proxy, total movement, access status, clearance evidence
completeness, and expansion reserve. Throughput, ergonomics, and compliance
remain unknown unless supported by separate evidence.

### K9. Planning Recipes And Gold Execution Traces

Convert the recovered 827-placement manual build into structured records:

```text
user intent
trusted starting state
resolved entities
selected semantic command
command parameters or semantic constraints
expected deterministic operation family
execution receipt
resulting state summary
validation result
correction or next dependency
```

Do not train Sage to memorize the factory coordinates. Derive variants with
different dimensions, labels, counts, orientations, department ordering, and
available assets. Include negative examples that show why a tempting tool is
wrong.

### K10. Sage Facility Layout Skill And Context Package

Update the existing generation skill so it receives bounded, revision-bound:

- current facility digest;
- supported command registry slice;
- relevant cell strategy and recipe slice;
- current plan-stage status;
- target department or cell context;
- required asset and policy evidence;
- prior execution receipts and unresolved findings.

Do not inject the complete tool registry or full 827-placement layout on every
turn. Retrieve the stage-appropriate slice by stable IDs and capability tags.
The compiler must reject any slice above 8,192 canonical bytes and report which
capability set caused the overflow. It also records the `bytes4-v1` estimate;
that estimate is diagnostic and does not replace the authoritative byte cap.

## 7. Implementation Milestones

### KF0. Freeze A Fresh Baseline And Decisions

Deliverables:

- rerun the current Facility Layout Python, browser, saved-layout, runtime, and
  `intelligence_evaluation.py` suites against the current source tree;
- record source, fixture, command-registry, and saved-reference-layout hashes;
- disposition every historical or current failure as fixed or explicitly
  quarantined with test ID, owner, reason, source hash, expiry condition, and
  evidence that it does not intersect the changed surface;
- exact crosswalk among all 39 semantic commands, ribbon IDs, workspace
  handlers, operation-kernel handlers, agent tools, effects, feature flags, and
  current tests;
- capability-gap matrix against K1-K10;
- frozen stage taxonomy, authority policy, runtime budgets, and default policy;
- inventory of the existing 71 evaluation cases, marking all of them as
  regression-visible rather than held out;
- freeze the Facility-scoped configuration names under the existing
  `INSPECTORPRO_FACILITY_LAYOUT_*` prefix;
- record and assert the exact effective provider, model, reasoning effort, and
  configuration source used by every baseline run;
- record `bytes4-v1`, its formula, canonical byte count, estimated-token count,
  and the 20% context-headroom policy in every budget artifact.

Gate G1 bounds to freeze here:

- facility dimensions: existing 0.5 m through 10,000 m per axis;
- source units: m, mm, ft, and in, normalized deterministically to meters;
- department count: 1 through 50;
- explicit proportions override defaults;
- labels-only requests use equal-area partitioning and disclose the assumption;
- no expansion reserve, corridor, or safety separation is invented unless the
  user requests it or authoritative policy supplies it;
- final Save remains a separate explicit user command.

Exit gates:

- the fresh baseline report contains no unexplained failures;
- every changed-surface suite is green;
- every quarantine record satisfies the required fields and is excluded from
  claiming changed-surface regression safety;
- every current command, agent tool, effect, and capability flag is classified;
- all decisions and hashes are machine-readable.

### KF1. Canonical Schemas And Registries

Implement versioned contracts for K1-K5 and K7. Add compatibility adapters for
the existing Python constants and UI definitions during migration; do not break
saved-layout readability.

This milestone also:

- uses the five real effect values: `read`, `viewport`, `draft_edit`,
  `persistent_save`, and `viewport_capture`;
- maps command availability to the existing feature-flag dependency ladder;
- adds Facility-scoped provider configuration using
  `INSPECTORPRO_FACILITY_LAYOUT_SAGE_PROVIDER`,
  `INSPECTORPRO_FACILITY_LAYOUT_SAGE_ANTHROPIC_MODEL`,
  `INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_MODEL`, and
  `INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_REASONING_EFFORT`, retaining shared
  Sage settings only as explicit compatibility fallbacks;
- validates the effective Facility model against both the KF0-frozen model and
  the skill's `compatible_models` contract before a provider call;
- extends the existing thirteen-field cell-strategy records with only the four
  missing field groups;
- defines durable run, stage, substage, invalidation, cumulative proposal, and
  final save-receipt schemas;
- defines `FacilityGenerationRunRepository`, durable session-to-run mapping,
  cross-process single-writer lock, writable-run lease, revision
  compare-and-swap, 24-hour idle expiry, 30-day tombstone, and saved-receipt
  retention contracts without changing the legacy follow-up store;
- defines bounded registry queries and canonical serialization for size tests.

Exit gates:

- 100% of current ribbon and agent-exposed command IDs resolve to one canonical
  contract;
- no semantic command has two deterministic owners;
- schema fixtures cover valid, invalid, stale, unsupported, oversized, and
  unknown cases;
- all ten existing cell strategies migrate without losing their current fields;
- feature-flag dependencies and effect values match the runtime exactly;
- a provider, model, reasoning-effort, or skill-compatibility mismatch fails
  before the first Facility provider call;
- run-store schema, session mapping, lease, expiry, restart, orphan-lock
  recovery, and synchronized multi-process concurrency fixtures pass;
- existing saved layouts require no migration merely to remain readable.

### KF2. Tool-Knowledge Compiler

Generate stage-specific Sage tool knowledge and UI metadata from the canonical
registry. Add deterministic stage, capability, compatibility, prerequisite,
prohibition, and follow-up queries.

Exit gates:

- Sage can retrieve an explanation of every command's intent, required state,
  deterministic owner, and limits;
- every command has at least one correct-use and one prohibited-use case;
- every mutating command names its preview, validation, receipt, and undo path;
- registry-to-UI and registry-to-agent parity is exact;
- every frozen stage slice is at most 8,192 canonical bytes and therefore at
  most 2,048 `bytes4-v1` estimated tokens;
- boundary tests prove complete skill contexts and tool responses remain within
  the 9,600 estimated-token target, 12,000 estimated-token hard limit, and
  16,384-byte response limit;
- overflow fails closed with a diagnostic rather than truncating semantics.

### KF3. Asset And Zone Semantic Readiness

Normalize K6 fields for the asset library and zone vocabulary. Produce planning
readiness reports rather than silently filling missing interfaces. This work may
run in parallel after KF1 and gates asset-placement capabilities, not G1.

Exit gates:

- every planning asset has a revision-bound footprint or is unavailable;
- every directional interface reports authored, derived, inferred, or unknown;
- no inferred side or clearance satisfies a hard placement rule;
- zone labels remain user-authored while semantic roles remain typed;
- bounded fit queries reuse `fit_analysis.py` and do not duplicate its logic.

### KF4. Complete Cell Intelligence

Extend K7 and K8 across all ten existing strategies and named recipes. Add the
four missing field groups and generalize deterministic candidate analysis. Do
not rewrite the existing strategy knowledge or create another geometry engine.

The line/L/U expansion must update, in one compatibility change:

- `_CELL_COMPARISON_STRATEGIES` in `semantic_model.py`;
- the agent tool-schema strategy enum in `observation.py`;
- the runtime default and validation in `agent_runtime.py`;
- browser strategy IDs and shared fixture parity.

Exit gates:

- all ten strategies have deterministic valid and invalid fixtures;
- candidates never overlap physical geometry or leave the target zone;
- authored clearance envelopes are enforced and missing evidence stays visible;
- locked and manual placements are preserved;
- server, agent schema, runtime, and browser classifications agree for shared
  fixtures;
- named recipes compile only into registered semantic commands;
- this milestone qualifies capability rollout stage 5 and does not block G1.

### KF5. Stage Planner And Resumable Execution Contract

Implement K4, K5, and durable run/receipt handling while retaining
coordinate-free planning and explicit final save authorization.
`FacilityGenerationRunRepository` is the authoritative restart-safe home for
run state, receipts, and generation session-to-run resolution.
`FacilityPendingOperationStore` remains limited to legacy read-only follow-ups.

Execution modes:

- `preview_only`: calculate and display without changing the draft;
- `guided_draft`: the user accepts each stage into the unsaved draft;
- `authorized_draft_run`: one explicit request authorizes eligible stages to
  update the unsaved draft across bounded turns, stopping on ambiguity, stale
  state, budget exhaustion, or deterministic failure;
- `save`: a separate command that presents and persists one cumulative diff.

The executor uses the current capability ladder. Preview requires
`agent_preview`; agent-authored draft changes require `agent_write`, whose
existing dependencies enforce viewer, library, manual edit, constraints,
routing, and preview readiness.

At a bounded-turn boundary, the server coordinator reads the durable run,
revalidates its writable lease, base/draft revisions, provider/model/reasoning
configuration, remaining budgets, and next eligible stage, then enqueues
exactly one continuation. Model text cannot enqueue itself. Cancellation,
expiry, conflict, ambiguity, or any failed invariant stops continuation and
requires an explicit user action.

Exit gates:

- no turn exceeds ten tool calls and every durable run resumes after turn or
  cursor expiry using run and receipt state;
- a process restart preserves an eligible run and its exact resume point;
- the legacy 1,800-second follow-up TTL, 24-hour run expiry, 30-day tombstone,
  durable generation-session mapping, and saved-receipt retention policies pass
  clock-controlled and restart tests;
- concurrent preview runs are allowed, synchronized processes prove exactly one
  writable lease can be acquired, and revision compare-and-swap makes an older
  writer stale without auto-merging;
- only the server coordinator can advance an authorized run across turns, one
  bounded continuation at a time;
- each atomic substage contains at most 500 operations and planned instances;
- completed unrelated stages are not replayed after a failure;
- dependency changes supersede affected receipts and invalidate descendants;
- failures preserve prior valid draft results and report an exact blocker;
- final Save presents one cumulative diff bound to the complete valid receipt
  chain, and one explicit approval binds that exact diff;
- any invalid, missing, stale, or superseded receipt blocks Save;
- final persistence is atomic and no stage saves implicitly.

### KF6. Gold Traces, Retrieval, And Evaluation Extensions

Implement K9 and K10 by extending the existing evaluation system rather than
creating a parallel harness.

Deliverables:

- classify and retain all 71 existing cases as regression-visible cases;
- convert the recovered manual build into positive, negative, correction, and
  live-modification traces without preserving its literal coordinates;
- after KF1 freezes contracts, create a new versioned held-out set whose prompts
  and hashes were not used to author command rules;
- freeze a small G1-specific held-out subset early enough to qualify the first
  proof while broader route, asset, pattern, and cell traces continue in
  parallel;
- extend `intelligence_evaluation.py` and its report schema rather than forking
  provider, intent, or gate logic;
- record and assert the exact effective provider, model, reasoning effort, and
  configuration source in deterministic baselines and every provider-shadow
  run;
- retrieve only bounded, revision-bound, stage-specific context.

Exit gates:

- examples teach semantics and sequencing, not final coordinates;
- each example binds to a deterministic expected command family and result;
- no existing regression-visible case is presented as held out;
- held-out authorship, freeze date, version, and content hash are recorded;
- large-layout prompts remain within all Section 4 budgets;
- synthetic examples are illustrative and never production evidence.

### KF7. Core And Expanded Foundation Evaluation

Run two qualification tracks through the existing harness.

Core qualification covers the command registry, bounded retrieval, intent
contract, stage executor, cumulative approval, and facility/department command
families required by G1. It can finish while KF3, KF4, and the broader KF6 trace
set continue in parallel.

Expanded qualification adds asset readiness, all ten cell strategies, recipes,
and the later capability families before those capabilities are enabled.

Required suites:

1. command recognition and prohibited-use tests;
2. stage selection and dependency-order tests;
3. facility, department, route, marking, pattern, and cell entity resolution;
4. cell-strategy recommendation and feasibility tests;
5. ambiguity and conflicting-constraint tests;
6. stale revision, dirty editor, authorization, invalidation, and missing
   evidence tests;
7. paraphrase and follow-up continuity tests;
8. no-coordinate, no-click-simulation, and no-implicit-save tests;
9. budget, TTL resume, operation-splitting, rollback, and cumulative-diff tests;
10. run-store restart, expiry, concurrency, and continuation tests;
11. provider shadow with the saved reference facility unchanged.

Qualification gates:

- 100% canonical command-registry coverage;
- 100% rejection of forbidden or unauthorized actions;
- 100% deterministic feasibility agreement for every enabled strategy fixture;
- at least 95% correct top-level command family on the new held-out intent set,
  with every miss reviewed;
- 100% correct stage ordering on frozen dependency cases;
- 100% budget-boundary and stale-chain rejection;
- 100% effective provider/model/reasoning configuration and incompatible-skill
  rejection before provider execution;
- no saved-layout byte or revision change during shadow evaluation;
- the fresh KF0 regression baseline remains green or validly quarantined;
- no unresolved P0 or P1 finding in the capability being enabled.

The current shared Sage defaults, global overrides, Facility-scoped overrides,
and final effective provider/model/reasoning configuration are all reported.
Evaluation asserts the effective configuration against the KF0-frozen value;
a global model or reasoning-effort change cannot silently produce
comparable-looking Facility evidence.

### Gate G1. First Executable Proof: Facility And Departments

G1 depends on KF0, KF1, KF2, KF5, the G1 slice of KF6, and KF7 core
qualification. It does not depend on completed asset enrichment or full cell
qualification. However, the entity, tool, strategy, and evidence contracts for
those later capabilities are already frozen by KF1.

Add only the capabilities needed to create an empty facility envelope and macro
departments. Do not add aisles, assets, cells, or markings in this gate.

Semantic actions:

- inspect current layout, feature capabilities, and dirty state;
- set plan dimensions and normalize source units;
- request a rectangular or supported polygon facility boundary;
- partition usable area using explicit proportions, bands, rows, columns,
  orientation, and adjacency;
- create exact labels and semantic department types;
- validate containment, overlap, area allocation, label identity, and requested
  relationships;
- display the bounded stages live and retain an unsaved draft;
- produce the ordered stage receipt chain and cumulative diff;
- save only after explicit approval of that cumulative diff.

The partition solver, not Sage, calculates polygons and coordinates.

Exit gates:

- exact normalized facility dimensions and units;
- exact requested department count and labels;
- all department polygons inside the facility with zero overlap;
- requested proportions within a frozen tolerance;
- requested orientation, bands, and adjacency satisfied or explicitly blocked;
- no unrequested corridor or expansion area;
- Undo returns to the exact empty-layout base state, including a split substage
  chain when applicable;
- save/reopen preserves identical dimensions, labels, hierarchy, and geometry;
- light/dark 2D and 3D browser evidence shows the same world state;
- randomized tests cover 1-50 departments across supported size ranges;
- every G1 production case completes within one ten-call turn; a separate
  synthetic fixture proves multi-turn continuation for later rollout stages;
- the full run respects call, response, context, TTL, and operation budgets.

## 8. Stage-By-Stage Capability Rollout

Enable later stages only after the prior stage passes its frozen gate:

1. facility envelope and departments;
2. semantic aisles, pedestrian paths, crossings, and route connectivity;
3. nested department subdivisions;
4. asset search, placement, orientation, access, and staging;
5. seed manufacturing-cell feasibility and creation;
6. patterns, reusable modules, and complete-cell replication;
7. floor communication, support details, and utilities where supported;
8. full-factory generation from an empty layout;
9. live department and cell modifications with dependency-aware reflow;
10. performance, soak, accessibility, and release qualification.

Each stage gets its own intent suite, deterministic fixtures, browser test,
saved-state test, undo test, stale-state test, and provider shadow before the
next stage begins.

This rollout reuses the existing feature-flag ladder rather than inventing a
second one. Read-only and manual capabilities retain their present dependencies;
agent preview is enabled only under `agent_preview`, and any Sage-authored draft
change is enabled only under `agent_write`. A capability gate may add a narrower
sub-feature flag, but it cannot bypass that ordered chain.

KF3 qualifies the asset-dependent parts of stage 4. KF4 qualifies stage 5 and
the strategy-dependent parts of stages 6, 8, and 9. The expanded KF6/KF7 cases
qualify each command family before its flag is enabled.

## 9. First Executable Test Matrix

1. `300 x 200 ft`, four equal departments, exact labels.
2. `100 x 80 m`, six departments with explicit percentages.
3. Seven arbitrary department names in two user-requested bands.
4. Five departments flowing west to east with explicit adjacency.
5. One irregular department plus rectangular neighbors.
6. Rename one department without changing its geometry.
7. Resize one department and deterministically reflow only affected neighbors.
8. Add a department while preserving locked departments.
9. Remove an unreferenced department; reject removal when live references exist.
10. Conflicting percentages, impossible minimum sizes, duplicate labels, and
    contradictory adjacency that require clarification rather than guessing.
11. Unit-equivalent prompts that produce byte-equivalent normalized geometry.
12. Restart, resume from the stage receipt, explicitly save, and reopen.
13. Change the shared Sage model or OpenAI reasoning effort after KF0 and verify
    Facility evaluation fails before a provider call unless the frozen
    Facility-scoped configuration remains effective.
14. Start concurrent preview runs, use synchronized processes to prove exactly
    one writable lease is acquired, then verify a competing saved revision
    makes the original writable run stale.

## 10. Dependencies And Parallel Work

Foundation dependency graph:

```text
KF0 -> KF1 -> KF2 -> KF5 ---------------------> KF7 core -> Gate G1
       |                 ^                         ^
       |                 |                         |
       +-> KF6 G1 held-out and retrieval slice ---+
       |
       +-> KF3 asset readiness -----------> rollout stage 4+
       |
       +-> KF4 cell intelligence ---------> rollout stage 5+
       |
       +-> KF6 expanded traces -> KF7 expanded -> later rollout gates
```

Parallel work after KF1:

- asset and zone readiness can proceed with cell-intelligence fixtures;
- G1 held-out cases and gold-trace extraction can proceed while KF2 and KF5 are
  implemented, provided their hashes are frozen before rule tuning;
- broader evaluation fixtures can be authored against frozen schemas before
  later Sage capabilities are enabled;
- browser parity tests can proceed while server feasibility expands.

All domain, tool, strategy, evidence, and receipt contract shapes are frozen in
KF1 so Sage has one coherent knowledge model before G1. Full asset enrichment,
ten-strategy feasibility qualification, and broad trace coverage are not
geometrically required to draw macro departments, so they do not block G1.
They remain required for the complete foundation and block the capability
stages that consume them.

## 11. Principal Risks And Controls

1. Duplicate command truth
   - control: one registry and exact parity tests.
2. Sage becoming a geometry engine
   - control: reject coordinates and require semantic planner compilation.
3. Stagewise execution bypassing current preview safety
   - control: bounded provisional transactions, an immutable ordered receipt
     chain, one cumulative diff, and one explicit approval before atomic Save.
4. Cell feasibility overstating incomplete asset knowledge
   - control: physical feasibility, access evidence, and compliance remain
     separate statuses.
5. Memorizing the reference factory
   - control: held-out dimensions, labels, counts, orderings, and negative cases.
6. Hidden downstream breakage during live changes
   - control: dependency invalidation, affected-scope preview, and rerun of
     connected route/cell validators.
7. Large-factory latency or memory regression
   - control: bounded region retrieval, staged transactions, operation budgets,
     reference-layout benchmarks, and resumability.
8. User intent being silently defaulted
   - control: frozen default policy and explicit assumption reporting.
9. Runtime budgets being exceeded by a complete factory
   - control: bounded registry slices, durable multi-turn runs, <=500-operation
     substages, explicit diagnostics, and no partial persistence.
10. Stale or non-green evidence being treated as a baseline
    - control: fresh KF0 execution and machine-readable disposition of every
      failure before changed-surface work begins.
11. Existing evaluation cases leaking into the held-out score
    - control: classify all 71 current cases as regression-visible and freeze a
      separately hashed set after the canonical contracts are fixed.
12. A global Sage provider, model, or reasoning-effort override silently
    invalidating Facility evidence
    - control: `INSPECTORPRO_FACILITY_LAYOUT_SAGE_*` configuration, skill
      compatibility enforcement, effective-configuration fingerprints, and
      fail-before-call KF0/KF7 assertions.
13. A heuristic token count being treated as exact
    - control: canonical bytes remain authoritative for registry slices;
      `bytes4-v1` is named as an estimate with 20% context headroom.
14. Abandoned or competing durable runs corrupting draft ownership
    - control: persistent run repository, durable session mapping,
      cross-process single-writer lock, one writable lease per layout, revision
      compare-and-swap, explicit expiry/GC, and no automatic merge.

## 12. Definition Of Knowledge-Foundation Complete

The knowledge foundation is complete when:

- Sage and the UI consume one canonical Facility command vocabulary;
- Sage can state the purpose, inputs, limits, dependencies, and undo behavior of
  every available tool;
- all facility entities and lifecycle states have stable typed meaning;
- all ten cell strategies and named recipes have machine-readable knowledge;
- deterministic feasibility owns geometry and reports evidence completeness;
- the stage graph is resumable and receipt-bound;
- one cumulative approval preserves the current exact-diff safety guarantee;
- the manual reference build exists as structured, generalized gold traces;
- held-out intent tests meet the frozen selection and safety gates;
- the saved reference layout remains unchanged during foundation evaluation;
- the fresh regression baseline has no unexplained failures;
- all runtime slice, call, response, TTL, and operation budgets pass their
  boundary tests;
- effective provider/model/reasoning identity and skill compatibility are
  asserted before every evaluated or authorized Facility provider call;
- durable-run restart, expiry, garbage collection, lease contention, and
  continuation behavior pass deterministic and multi-process tests;
- budget artifacts distinguish canonical bytes from `bytes4-v1` estimates and
  preserve the 20% context reserve;
- G1 has passed without adding new architecture or duplicating domain rules;
- KF3, KF4, and expanded KF6/KF7 have qualified the later asset and cell
  capability families they gate.

Gate G1 provides a deliberately narrow first user-facing proof while the
expanded foundation proceeds to its own qualification:

> The user specifies facility size, units, department count, labels, and layout
> intent. Sage understands the request, selects the correct deterministic tools,
> builds the facility and departments live, validates the result, and leaves a
> reversible unsaved draft whose cumulative diff can be explicitly approved.
