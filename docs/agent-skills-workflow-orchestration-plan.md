# InspectorPro Skills and Workflow Orchestration Plan

## Status

Implementation plan, revision 8. Phase 0 through Phase 5 are implemented as of 2026-07-10. The current implementation provides measured baselines, shared authorization fixtures, strict versioned skill/workflow registries, prompt-section accounting, seven v1 skill packages, selected-skill prompt assembly, registered FAI executor recipes, feature flags, gated internal test endpoints, a validated semantic router, a typed UI-action contract, browser postcondition receipts, receipt-grounded same-turn status, and bounded multi-turn workflow continuity with refresh and asset reconciliation. Production skills remain off by default; normal activation is still pending router-latency optimization.

## Purpose

InspectorPro has reached the point where a single permanent system prompt cannot safely carry every workflow, tool rule, mode restriction, example, and engineering policy. The prompt is becoming expensive, difficult to test, and vulnerable to conflicts as Drawing, 3D Model, Assembly, FAI, motion, training, plant-process, facility-layout, and Builder capabilities expand.

The target architecture keeps the LLM as the semantic brain while moving reusable procedures into selectively loaded skills and keeping execution under deterministic control.

The central rule is:

> The LLM interprets meaning and proposes a workflow and requested effects. Deterministic code establishes what is possible, independently authorizes side effects, validates every selected skill and tool, executes typed operations, and verifies the result.

This is a hybrid system from the first release. Semantic routing is never keyword-only. Deterministic authorization gates remain permanent safety vetoes for side-effecting actions; they do not choose the engineering workflow or skills.

## Decisions

1. A workflow, skill, tool, and agent are separate concepts.
2. Every natural-language turn goes through semantic intent classification unless it is an internal system event.
3. The active tab is useful evidence, but it does not determine intent by itself.
4. A small, fast LLM identifies the workflow, speech act, targets, requested effects, and candidate skills.
5. Deterministic code filters impossible candidates before classification and validates the classifier output afterward.
6. The main agent may compose multiple skills in one turn.
7. Skills describe procedures and declare allowed tools, but they neither authorize nor execute tools directly.
8. Tool execution is governed by a typed registry, permission policy, preconditions, and postcondition checks.
9. Viewport state is persistent. No skill or tool may clear, stop, hide, or restore unrelated state unless the user requested that effect.
10. Visible responses must be grounded in execution receipts. The agent must not claim that an action occurred when it did not.
11. Existing mode contracts, the viewport intent classifier, UI actions, and legacy resolvers remain available during migration.
12. The first production slice is the FAI-to-assembly-impact-to-motion workflow because it exercises explanation, engineering reasoning, cross-tab context, multi-skill composition, and viewport actions.
13. Classifier output can request a side effect but can never authorize one. Independent deterministic authorization is required regardless of classifier confidence.
14. Browser-side suppression and action-strip gates remain the final veto for frontend viewport actions after the skill migration.

## Vocabulary

### Agent

The conversational LLM that understands the user's goal, reasons from selected evidence, combines skills, and explains the result. Sage, Iris, Scout, and Builder can have different permissions and skill catalogs.

### Workflow

A stateful engineering objective that can span multiple turns and stages. A workflow answers: "What job is the user trying to complete?"

Examples:

- inspect a released drawing
- complete and disposition an FAI
- understand the assembly impact of a deviation
- demonstrate the affected mechanism motion
- compare revisions
- conduct an assembly-training walkthrough
- evaluate a facility route and capacity trade-off
- intake a new part or assembly into the library
- edit a process map with Builder

A workflow is not the same as a tab. The user may be in Report / FAI mode and ask an assembly-impact question, or remain in Assembly mode while asking about a drawing characteristic.

### Skill

A selectively loaded package of procedural knowledge and guardrails. A skill answers: "How should the agent reason or act for this part of the job?"

Examples:

- assess an FAI characteristic
- trace a deviation into assembly context
- reason about mates and neighboring parts
- select an applicable motion group
- control the CAD viewport
- compute and explain a facility route
- edit and validate a process-map graph

Skills are composable. One turn may use one primary skill and several supporting skills.

### Tool

A deterministic capability with a typed input and observable result. A tool answers: "What operation can the system perform?"

Examples:

- read FAI rows
- calculate tolerance status
- resolve a characteristic to a CAD feature
- resolve assembly neighbors or motion groups
- set part highlighting
- play a motion package
- calculate a facility route
- validate and write a process-map JSON file

The same tool may be used by several skills. Tool code does not live inside prompt text.

### Context provider

A deterministic reader that produces a compact, typed slice of live state for a selected skill. Context providers keep irrelevant application state out of the prompt.

Examples:

- active part and revision
- visible feature groups
- FAI failed rows
- assembly part legend and mates
- available motion packages and groups
- viewport highlights, hidden parts, rotation, and playback state
- facility zones, endpoints, routes, and capacities

## Architecture

```text
User message
  |
  v
Normalize live app context and current workflow state
  |
  v
Deterministic candidate filter
  - agent permissions
  - active assets and tabs
  - available drawing / FAI / assembly / motion / facility data
  - enabled skill and workflow versions
  |
  v
Small semantic LLM router
  - speech act
  - workflow candidates
  - intent and targets
  - requested viewport/file effects
  - candidate skills and confidence
  |
  v
Deterministic route validator
  - schema and enum validation
  - target IDs exist
  - required context exists
  - skills are compatible and permitted
  - classifier-requested effects are separated from authorization
  - permanent raw-message side-effect gate independently authorizes or vetoes writes
  |
  v
Skill composer and prompt builder
  - core agent contract
  - active workflow stage
  - selected SKILL.md bodies
  - only required context slices
  - only allowed tool schemas
  |
  v
Main reasoning agent
  - answer directly, ask a clarification, or request a registered v1 executor
  |
  v
Deterministic tool-policy engine
  - allow-list intersection
  - registered executor and ordered-action validation
  - argument and state validation
  - conflict and persistence rules
  - confirmation gates for risky changes
  |
  v
Tool executor -> execution receipts -> postcondition verifier
  |
  v
V1 deterministic receipt-grounded status + updated workflow state
```

## What Remains From the Current System

The following working pieces should be evolved, not replaced:

- `MODE_CONTRACTS` remains the source of active-mode boundaries during migration.
- `classify_viewport_intent()` becomes the first specialized semantic route and action-intent implementation.
- `_validate_viewport_intent()` is the model for deterministic validation of all future route outputs.
- The frontend `ui_actions` registry remains the typed execution surface for viewport actions.
- Existing feature, part, FAI, motion, facility, and training context builders become context providers.
- Existing regex resolvers remain a temporary semantic/action fallback when classification is unavailable or invalid; their use should be measured and reduced.
- `_messageExplicitlyRequestsViewportChange()`, `_shouldSuppressImplicitFaiViewportActions()`, and `_stripUnrequestedMotionPlayback()` are permanent deterministic authorization/suppression gates, not legacy semantic resolvers.
- Backend policy validation occurs before actions are returned, and the frontend authorization/suppression gates retain final-veto precedence immediately before browser execution.
- Existing execution-honesty checks remain and are generalized into execution receipts.
- Synthetic non-engine fixtures remain mandatory to prove that routing is data-driven.

The current viewport classifier runs concurrently with the main LLM. The general skill router cannot do that because its output determines which skill instructions and tool schemas the main LLM receives. The route call must complete first, with a strict latency budget and graceful fallback.

### Router latency policy

Phase 0 measured 136 successful `viewport_intent` calls: p50 `2,014.7 ms`, p95 `3,150.2 ms`, and p99 `5,826.9 ms`. A `2,000 ms` serial timeout would have rejected 72/136 calls (`52.9%`), so that target is not viable for the current classifier. Phase 2 shadow evaluation uses a measured `4,750 ms` budget (1.5 x p95, rounded up); serial production routing remains unapproved until the route is optimized and remeasured. Timeout always selects the legacy prompt path.

Latency mitigations for v1:

- keep router metadata and context digests small
- use one semantic route call rather than separate workflow and skill classifier calls
- precompute deterministic candidate catalogs while the user is typing or while context changes
- cache only exact normalized-message + workflow-state + context-fingerprint matches
- allow deterministic fast paths for internal UI events and explicit UI controls, not for unconstrained natural-language follow-ups
- record total turn tokens and latency, including the router call

A broad rule such as "short follow-up with no action verb reuses the previous route" is intentionally not adopted. A short read-only question can still change from FAI disposition to material, drawing, assembly, or process reasoning and therefore still needs semantic classification.

## Hybrid Classification

### 1. Deterministic candidate generation

This phase does not infer semantic meaning. It only removes impossible routes and supplies useful priors.

Inputs:

- selected agent and permission scope
- active tab and subtab
- current part, drawing, assembly, FAI table, process map, or facility package
- available motion packages
- current workflow session, stage, and unresolved references
- viewport state
- enabled workflow and skill versions

Examples:

- If no motion package is bound, the router may still select the registered `reason-about-motion` skill to explain the request, but the `show-resolved-motion-group` executor is unavailable and cannot execute.
- If no FAI table exists, FAI disposition skills are not executable.
- Sage may read product data and control the viewport but cannot edit source files.
- Builder may receive editing skills that Sage never sees.

The output is a compact catalog of eligible and unavailable workflows/skills. Unavailable candidates are retained only when needed to explain a limitation accurately.

### 2. Semantic LLM routing

A small, fast model receives:

- the exact user message, including typos
- recent referents needed for phrases such as "show it" or "bring that back"
- a compact live-state digest
- candidate workflow and skill metadata only, not full skill bodies
- active workflow state

It returns strict JSON. A proposed v1 schema is:

```json
{
  "speech_act": "question|explain|analyze|command|edit|compare|navigate|clarify",
  "primary_workflow": "supplier-fai-disposition",
  "continue_existing_workflow": true,
  "workflow_confidence": 0.93,
  "intents": [
    {
      "kind": "explain_assembly_impact",
      "targets": [
        {
          "kind": "fai_characteristic",
          "id": "5",
          "label": "failed pin bore"
        }
      ],
      "requested_effects": [],
      "confidence": 0.95
    }
  ],
  "skill_candidates": [
    {"id": "assess-fai-characteristic", "role": "primary", "confidence": 0.97},
    {"id": "trace-assembly-impact", "role": "support", "confidence": 0.91}
  ],
  "context_requirements": ["fai.failed_rows", "assembly.mates", "part.feature_map"],
  "requested_side_effects": {
    "viewport_write": false,
    "asset_write": false,
    "system_write": false
  },
  "needs_clarification": false,
  "clarification_question": null
}
```

The classifier decides semantics. It must tolerate spelling mistakes, awkward phrasing, and references to earlier turns. Keyword rules do not determine the route.

### 3. Deterministic route validation

The validator accepts only registered IDs and valid schema values. It then verifies:

- the primary workflow exists and is enabled
- selected skills exist, are versioned, and are allowed for the active agent
- required assets and context providers are available
- part numbers, characteristic numbers, feature IDs, node IDs, and motion-group IDs exist in current data
- the skill count is within limits and declared skill dependencies are registered and acyclic
- the selected skills are mutually compatible
- classifier-requested effects are compatible with the speech act and agent role
- every `viewport_write`, `asset_write`, or `system_write` passes an independent deterministic authorization check against the raw message, regardless of router confidence
- the browser's permanent `_messageExplicitlyRequestsViewportChange()` gate (or its tested successor) positively authorizes frontend viewport writes; classifier JSON alone is never sufficient
- `_shouldSuppressImplicitFaiViewportActions()` and `_stripUnrequestedMotionPlayback()` retain final-veto precedence over model/classifier action proposals
- file-changing or destructive effects have required approval

The validator never replaces an unknown ID with a convenient default. A failed target match produces either a read-only answer about the limitation or a clarification question.

The action gate is conservative but should not be brittle. Its successor may use deterministic normalization, typo-tolerant matching for a bounded action vocabulary, command grammar, and explicit UI state. If authorization remains uncertain, it asks for clarification instead of executing. This gate is an authorization mechanism, not the semantic workflow router.

### 4. Confidence and fallback policy

- High confidence and valid route: load the selected skills.
- Medium confidence with no side effect: allow read-only reasoning and state the uncertainty when material.
- Medium confidence with a side effect: ask a clarification or require confirmation.
- Low confidence, invalid JSON, timeout, or model outage: use the legacy mode prompt and existing resolvers.
- Destructive or file-writing operations never fall back to regex execution.
- A legacy or model-emitted `ui_actions` block still passes the permanent frontend authorization/suppression gates before execution.
- The fallback path is logged so it can be measured and reduced over time.

### 5. Existing workflow continuity

The router reclassifies every turn, but a current workflow supplies strong context for pronouns and follow-ups.

Example:

```text
Turn 1: What is the assembly impact of failed characteristic 5?
Workflow: supplier-fai-disposition / stage: assembly_impact

Turn 2: What motion will be affected?
Same workflow / stage: motion_explanation / no viewport side effect

Turn 3: Show it in motion.
Same workflow / stage: motion_visualization / viewport side effect authorized
```

The active tab is a prior, not an override. The words and workflow history still determine the route.

## Workflow Model

Each workflow has a manifest and a small state machine.

```yaml
id: supplier-fai-disposition
version: 1.0.0
agents: [sage]
entry_signals:
  - supplier inspection or first-article question
  - measured value, failed characteristic, or disposition request
required_assets:
  - fai_table
optional_assets:
  - drawing
  - part_model
  - parent_assembly
  - motion_package
stages:
  - identify_characteristic
  - evaluate_result
  - explain_part_function
  - trace_assembly_impact
  - visualize_affected_context
  - recommend_disposition
completion:
  - failed characteristic and evidence are identified
  - disposition wording is grounded
  - requested visualization, if any, has an execution receipt
```

Workflow state should be stored server-side per chat/session:

```json
{
  "workflow_id": "supplier-fai-disposition",
  "version": "1.0.0",
  "stage": "trace_assembly_impact",
  "objective": "Disposition failed characteristic 5",
  "entities": {
    "part_number": "100006",
    "characteristic_numbers": ["5"],
    "assembly_part_number": "100001"
  },
  "evidence_refs": ["fai:100006:A:5", "feature:100006:pin_bores"],
  "last_execution_receipts": [],
  "pending_clarification": null
}
```

The workflow state must not copy large arrays. It stores identifiers that context providers resolve fresh each turn.

### Workflow-state lifecycle and reconciliation

- Key semantic workflow state by chat/session ID, not by browser tab.
- Include an asset/context fingerprint containing active part, revision, assembly, FAI revision, and relevant package versions.
- On page refresh, the frontend resends its live viewport state and asset fingerprint. If the fingerprint still matches, semantic workflow state may resume.
- If the asset fingerprint changes, invalidate stale entity/evidence references and reclassify instead of silently resuming.
- Frontend viewport state is authoritative for motion, highlights, hidden parts, opacity, camera rotation, and active tab. Conflicting stale server state always loses.
- Browser-born execution receipts travel back on the next request inside the existing viewport/context attachment and are then recorded in server workflow state.
- Apply a configurable inactivity expiry to workflow state and report expiration in telemetry. Expiration must not alter the current viewport.
- Closing a tab or refreshing never replays prior side effects automatically.

## Skill Package Contract

InspectorPro skills should use progressive disclosure: small metadata is always available to the router, while full instructions and references load only after selection.

Proposed structure:

```text
ai_inspector/agent_skills/
  assess-fai-characteristic/
    manifest.yaml
    SKILL.md
    references/
      disposition-policy.md
    schemas/
      output.schema.json
    tests/
      cases.yaml
```

`manifest.yaml` is machine-readable runtime metadata:

```yaml
id: assess-fai-characteristic
version: 1.0.0
description: Evaluate one or more FAI rows and explain status and disposition from computed limits.
agents: [sage]
workflows: [supplier-fai-disposition, inspection-report-review]
modes: [report_fai, report, drawing, assembly]
requires_context:
  - fai.characteristics
optional_context:
  - drawing.dimensions
  - part.feature_map
allowed_tools:
  - get_fai_characteristics
  - compute_fai_status
side_effects: none
composable_with:
  - trace-assembly-impact
  - control-cad-viewport
evidence_policy: computed_fields_only
```

`SKILL.md` contains only non-obvious procedural guidance:

- evidence priority
- reasoning sequence
- required distinctions
- grounded wording rules
- when to ask a clarification
- how to interpret tool results
- output expectations

Detailed standards, schemas, and company policies stay in `references/` and load only when required. Repeated or fragile calculations belong in deterministic scripts/tools, not prose.

### Skill boundaries

A skill must not contain:

- hard-coded demo part numbers or assembly IDs
- executable UI action handlers
- global agent identity text
- unrelated mode instructions
- duplicated tool schemas
- large product-data dumps
- instructions to bypass permissions or validators
- non-ASCII source text: v1 skill manifests, `SKILL.md` files, schemas, and references are ASCII-only, enforced by an encoding test before activation

### Skill composition rules

- Load one primary skill and no more than three supporting skills in a normal turn.
- Larger workflows load skills by stage rather than loading the entire workflow at once.
- Dependencies declared in manifests are added deterministically.
- Conflicting skills are rejected before prompt assembly.
- The main agent may request exactly one additional registered skill if it discovers a gap. The runtime validates and loads it in a second pass; the model can never self-load an unregistered skill.

## Initial Skill Catalog

### First production slice

1. `assess-fai-characteristic`
   - Use computed nominal, limits, direction, and out-of-tolerance amount.
   - Never invent measurements, lot actions, or catastrophic effects.

2. `recommend-fai-disposition`
   - Distinguish pass, pending, reject/escalate, rework evidence, and accept-as-is evidence.
   - Separate measured fact from conditional engineering impact.

3. `reason-about-part-features`
   - Use inspection profiles, semantic features, drawing locations, and exact feature highlights.

4. `reason-about-assembly-context`
   - Use parts, instances, mates, neighbors, functions, and current assembly state.

5. `trace-assembly-impact`
   - Join a failed characteristic to its feature, mating parts, affected instance, and relevant motion group.
   - Scope one inspected part to one affected instance unless evidence proves a broader lot/assembly condition.

6. `reason-about-motion`
   - Explain motion-package facts and semantic motion groups.
   - Keep visualization RPM separate from operating-speed claims.

7. `control-cad-viewport`
   - Translate an explicit display request into highlight, hide/show, transparency, rotation, or motion actions.
   - Preserve unrelated viewport state.

### Next read/reasoning skills

8. `inspect-drawing`
9. `compare-part-revisions`
10. `compare-assembly-revisions`
11. `guide-assembly-training`
12. `explain-plant-process`
13. `analyze-facility-layout`
14. `compute-facility-route`
15. `compute-facility-capacity`
16. `summarize-inspection-report`
17. `coach-product-sales`

### Builder-only skills

18. `edit-process-map`
19. `edit-training-procedure`
20. `build-inspection-profile`
21. `intake-library-part`
22. `intake-library-assembly`
23. `validate-engineering-asset`
24. `edit-agent-contract`

Builder skills follow the permissions and runtime plan in `docs/builder-agent-plan.md`.

## Tool Registry and Policy

The tool registry is global. Skills reference tools by ID; they do not copy the implementation or schema.

Every tool needs a specification similar to:

```yaml
id: play_motion
handler: frontend.ui_actions.play_motion
category: viewport_write
args_schema: schemas/play_motion.schema.json
agents: [sage]
reversible: true
idempotent: false
requires:
  - active_assembly
  - bound_motion_package
effects:
  - viewport.motion_playing
preserves:
  - viewport.highlights
  - viewport.hidden_parts
postconditions:
  - motion_playing_is_true
  - active_motion_id_matches_request
```

Tool categories:

- `context_read`: fetch typed facts; no visible side effect
- `compute`: deterministic calculations; no visible side effect
- `viewport_write`: reversible UI state change
- `asset_write`: structured file change
- `system_write`: code, prompt, deployment, or environment change

The allowed tool set for a turn is the intersection of:

```text
agent permissions
AND workflow permissions
AND selected-skill allow lists
AND live asset availability
AND user authorization
```

### Execution rules

- Validate arguments against JSON Schema.
- Resolve identifiers from live context; never fuzzy-bind at execution time.
- Run independent read/compute tools in parallel.
- In v1, invoke only registered, ordered executor recipes. Do not accept an arbitrary model-authored dependency graph.
- Apply the recipe's viewport writes in declared order.
- Require approval for asset writes according to Builder policy.
- Refuse conflicting effects instead of choosing silently.
- Preserve all state not named by the requested effect.
- Return a structured receipt for every call.
- Introduce topological planning, dynamic result references, and cycle rejection only after a migrated workflow demonstrates that fixed executors are insufficient.

Example receipt:

```json
{
  "tool_call_id": "call-42",
  "tool_id": "play_motion",
  "status": "succeeded",
  "requested_args": {"motion_id": "engine4cyl_crank_cycle", "rpm": 30},
  "applied_args": {"motion_id": "engine4cyl_crank_cycle", "rpm": 30},
  "before": {"motion_playing": false},
  "after": {"motion_playing": true, "motion_rpm": 30},
  "evidence": ["motion-package:engine4cyl_crank_cycle@1"],
  "error": null
}
```

## Multi-Skill Planning and Execution

The LLM should choose and combine skills. Deterministic code should not predetermine skill selection from keywords. For v1, execution is deliberately simpler than skill selection: selected skills may use only registered, data-driven executor recipes.

For a multi-skill turn:

1. The semantic router proposes a primary workflow and skill candidates.
2. The validator removes invalid or unavailable candidates and adds declared dependencies.
3. The main agent receives the selected skills and only the executors allowed by those skills.
4. For a read-only turn, context providers and compute tools supply evidence and the main agent answers without viewport effects.
5. For an action turn, the route/main agent requests a registered executor with typed inputs.
6. The policy engine independently authorizes the requested effects and validates the executor inputs.
7. The executor resolves current data and emits a short ordered action bundle.
8. The permanent frontend vetoes run immediately before browser actions execute.
9. Postconditions are verified and receipts are produced.
10. V1 appends or substitutes deterministic status text from those receipts; it does not make a second LLM call.

Example: "Show the affected motion."

```text
Workflow: supplier-fai-disposition
Skills:
  trace-assembly-impact
    -> reason-about-motion
      -> control-cad-viewport

Registered executor: show-resolved-motion-group
  input source: current failed characteristic / routed target
  deterministic resolution: characteristic -> feature -> assembly impact -> motion group
  ordered actions: set_part_highlight, play_motion
```

Example: "What motion will be affected?"

```text
Workflow: supplier-fai-disposition
Skills:
  trace-assembly-impact
  reason-about-motion

Tools:
  read/resolve tools only

Viewport effects: none
```

The difference is the classified speech act and requested effects, not the appearance of the word "motion".

### Post-v1 general planner

A model-authored typed plan with `depends_on`, dynamic result references, topological ordering, and cycle rejection is deferred. It should be introduced when facility routing, Builder, or another migrated workflow has a demonstrated need that cannot be expressed as a small registered executor. The skill manifests and tool registry remain compatible with that future layer.

### Receipt and response timing

Viewport receipts are born in the browser after the main response has already been generated. V1 therefore uses the same honesty pattern that works today:

1. The server returns response prose plus an authorized action bundle.
2. The frontend runs its final vetoes, executes the actions, and creates receipts from live before/after state.
3. Deterministic code appends or substitutes a receipt-grounded status line in the visible turn.
4. The frontend includes recent receipts in the next turn's `viewport_context` attachment.
5. The server reconciles them into workflow state, with frontend live state taking precedence.

A second model reasoning round over receipts belongs to a later streaming/session endpoint. It is not part of v1 because it would add latency without improving the short action confirmations.

## Prompt Construction

The permanent prompt should shrink to:

- agent identity and role
- evidence hierarchy and non-invention rule
- concise tool-use protocol
- execution-honesty rule
- permission and safety boundaries
- instruction that active workflow/skill/context blocks are authoritative for this turn

Per-turn prompt assembly should then add:

1. minimal active-mode fence
2. workflow objective and current stage
3. selected skill bodies
4. required references only
5. compact live context slices requested by those skills
6. allowed tool schemas only
7. recent conversation and resolved referents

The current long `MODE_CONTRACTS` entries should migrate gradually:

- FAI measurement and disposition rules -> FAI skills
- assembly/mate reasoning -> assembly-context skill
- motion rules -> motion skill
- highlight/hide/rotate persistence -> viewport-control skill and tool policy
- facility route/capacity rules -> facility skills
- training narration rules -> training skills

Mode contracts remain as short cross-mode fences so a part-only summary does not accidentally become an assembly explanation.

## V1 Vertical Slice

### Scope

Implement skills and workflow orchestration for Sage across:

- Report / FAI
- Drawing context needed by FAI
- 3D part feature context
- Assembly context
- Motion explanation and playback
- Viewport highlight/show/hide/restore composition

Do not migrate all agents or every mode at once.

### V1 workflow

`supplier-fai-disposition` with these stages:

1. identify the inspected characteristic
2. evaluate nominal, limits, measurement, direction, and exceedance
3. explain the feature's role on the part
4. trace the affected mating parts and assembly instance
5. explain the relevant motion without changing the viewport
6. visualize the affected motion only when explicitly requested
7. recommend reject/escalate, rework, accept-as-is, or pending based on available evidence

### V1 skills

- `assess-fai-characteristic`
- `recommend-fai-disposition`
- `reason-about-part-features`
- `reason-about-assembly-context`
- `trace-assembly-impact`
- `reason-about-motion`
- `control-cad-viewport`

### V1 compatibility behavior

- Run the new router in shadow mode first.
- Compare its route with current classifier/resolver behavior without changing the UI.
- Enable selected-skill prompt assembly behind a feature flag.
- Keep the existing viewport classifier as an action-intent fallback.
- Keep legacy prompts and resolvers available for instant rollback.

## Proposed Code Layout

```text
ai_inspector/
  agent_runtime/
    context_catalog.py
    route_classifier.py
    route_schema.py
    route_validator.py
    workflow_registry.py
    workflow_state.py
    skill_registry.py
    skill_loader.py
    prompt_builder.py
    executor_registry.py
    action_bundle_schema.py
    tool_registry.py
    tool_policy.py
    tool_executor.py
    execution_receipts.py
    telemetry.py
  agent_skills/
    assess-fai-characteristic/
    recommend-fai-disposition/
    reason-about-part-features/
    reason-about-assembly-context/
    trace-assembly-impact/
    reason-about-motion/
    control-cad-viewport/
  agent_workflows/
    supplier-fai-disposition.yaml
```

Server integration:

- `/api/agent/chat` normalizes context as it does today.
- The route classifier runs before construction of the main-agent prompt.
- The prompt builder loads only validated skills and tool schemas.
- The main model returns prose and/or a request for a registered v1 executor.
- Server-side read/compute tools run directly.
- Frontend viewport tools continue through `ui_actions` in v1.
- The frontend records execution receipts, uses them for deterministic same-turn status text, and sends them back in the next `viewport_context` attachment.

Longer term, a session endpoint can support multiple tool rounds and stream receipts, but v1 does not require a full Builder-style runtime.

## API Contracts

Internal routing result:

```json
{
  "route_version": 1,
  "workflow": {"id": "supplier-fai-disposition", "stage": "motion_visualization"},
  "speech_act": "command",
  "skills": [
    {"id": "trace-assembly-impact", "version": "1.0.0", "role": "support"},
    {"id": "reason-about-motion", "version": "1.0.0", "role": "primary"},
    {"id": "control-cad-viewport", "version": "1.0.0", "role": "support"}
  ],
  "requested_effects": ["highlight_parts", "play_motion"],
  "confidence": 0.94,
  "fallback": false
}
```

V1 registered executor request:

```json
{
  "executor": "show-resolved-motion-group",
  "inputs": {
    "target_ref": "current_failed_characteristic",
    "highlight_mode": "replace",
    "rpm": 30
  },
  "requested_effects": ["highlight_parts", "play_motion"]
}
```

The executor resolves all current IDs from validated context and returns a short ordered `ui_actions` bundle. No part number, motion-group ID, or demo assembly is embedded in the executor. Dynamic model-authored dependency graphs are post-v1.

## Test Strategy

### Skill tests

Each skill ships with cases that verify:

- correct evidence use
- prohibited claims
- required tool use or non-use
- missing-context behavior
- compatibility with supporting skills

### Router tests

Build a paraphrase and typo suite covering:

- direct commands
- explanation questions
- state questions
- follow-up pronouns
- multi-intent turns
- cross-tab questions
- unavailable capabilities
- low-confidence clarification

The classifier evaluation set should include engine, gearbox, pump, and facility fixtures. No test suite may rely only on the piston demo.

Bootstrap the first labeled route/authorization set from the current message cases in `tests/test_viewport_intent_mapping.js`. At the time of this revision that suite has 75 passing checks covering apply/suppress behavior, typo phrasing, whole-assembly motion, composition, and execution honesty.

Move the shared authorization cases into a neutral fixture such as `tests/fixtures/viewport_authorization_cases.json`. The server-side raw-message gate and the browser-side gate must consume the same labeled vectors, and a parity test must fail if their allow/veto decisions diverge. Do not maintain separate hand-written rule suites for the two implementations.

### Required FAI/motion acceptance cases

1. "What is the impact on the assembly of the failed dimension?"
   - grounded prose
   - no highlight, tab switch, or motion

2. "What motion will be affected?"
   - identifies the relevant motion in prose
   - no viewport change

3. "Show the affected motion."
   - selects the context-resolved group
   - highlights the affected parts
   - starts the bound motion package
   - confirms only after postconditions pass

4. "Show the pin joint."
   - highlights only
   - does not start motion

5. "Show me how this assembly moves."
   - plays whole-assembly motion
   - does not replace the viewport with a small subgroup

6. "Bring the crankshaft as well."
   - adds the crankshaft to the current view
   - preserves running motion

7. "Hide the lower block."
   - hides only the lower block
   - preserves highlights, rotation, and motion

8. "Bring everything back."
   - restores hidden parts and clears selection-only highlighting
   - behavior is verified from live state

9. Typo and awkward wording variants of every case.

10. The same semantic cases on a synthetic gearbox with different IDs.

### Required FAI prose-grounding cases

Freeze `tests/test_fai_response_grounding.py` as part of the migration bar. It currently verifies nine cases, including these observed failure classes:

- use exact computed measured, nominal, limits, direction, and out-of-tolerance amount
- do not issue `scrap` or catastrophic `jam`/`seize` claims without supporting evidence or an explicit user request
- do not invent tooling drift, lot checks, containment, or process-control directives
- scope one failed inspected part to one affected instance unless multiple failures are actually present
- preserve supported numeric facts while removing unsupported claims
- add the failed-row numeric grounding prefix when model prose omits the values

### Deterministic policy tests

- unknown skill/tool/target rejection
- tool allow-list intersection
- unavailable motion package rejection
- write approval gates
- permanent explicit-action authorization and FAI suppression vetoes
- registered-executor allow-list and ordered-action validation
- state-persistence invariants
- postcondition failure and honest response
- classifier timeout and legacy fallback
- post-v1 only: general dependency ordering and cycle rejection

### Browser tests

Use Playwright to assert live tab, viewport, motion, highlight, hidden-part, and response state. Screenshots are supporting evidence; numerical state assertions remain authoritative.

## Telemetry

Record one trace per turn:

- message and anonymized session ID
- active mode, available assets, and workflow state
- candidate workflows/skills
- semantic router output and latency
- validation removals or rejections
- selected skill versions
- prompt token count by section
- router input/output token count and main-agent input/output token count
- requested effects versus deterministically authorized effects
- selected executor and proposed action bundle
- execution receipts and postcondition results
- frontend authorization/suppression vetoes
- fallback path
- final response source and total latency

Primary metrics:

- workflow classification accuracy
- skill precision/recall on the evaluation set
- clarification rate
- invalid tool proposal rate
- tool execution failure rate
- false action-claim rate
- fallback rate
- total tokens per turn, including the router call
- router p50/p95 latency and total-turn p50/p95 latency
- state-persistence regressions

## Rollout Phases

### Phase 0 - Baseline and contracts

- Measure current prompt tokens by mode and agent.
- Measure current `viewport_intent` classifier p50/p95 latency and token use from `record_anthropic_call` telemetry.
- Inventory all existing tools, context blocks, mode rules, and legacy markers.
- Create schemas for route, skill manifest, workflow manifest, registered-executor request, action bundle, and receipt.
- Freeze the current FAI/motion Playwright flow as a regression suite.
- Freeze `tests/test_viewport_intent_mapping.js` and `tests/test_fai_response_grounding.py` as explicit migration bars.

Exit gate: current behavior is reproducible and measured.

### Phase 1 - Skill runtime without behavior change

- Build skill/workflow registries and validators.
- Add prompt-section accounting.
- Load a selected skill in a test endpoint while keeping production prompts unchanged.
- Add feature flags:
  - `INSPECTORPRO_SKILLS_ENABLED`
  - `INSPECTORPRO_SKILLS_SHADOW`
  - `INSPECTORPRO_SKILL_ROUTER_MODEL`

Implementation checkpoint (2026-07-10):

- Added strict ASCII-only YAML/Markdown package loading with duplicate-key rejection, exact schema keys, numeric SemVer resolution, known-agent/mode/tool checks, cross-reference validation, dependency-cycle detection, conflict checks, and one-primary-plus-three-supporting selection limits.
- Added `supplier-fai-disposition@1.0.0` and the inactive `assess-fai-characteristic@1.0.0` package as the first validated catalog entries.
- Added deterministic prompt-section character, byte, line, approximate-token, and SHA-256 accounting. The internal Sage/report-FAI composition measured 35,525 characters total; the isolated first skill contributes approximately 388 tokens.
- Added gated `/api/internal/agent-skills/status` and `/api/internal/agent-skills/test-compose` endpoints. Both report `production_chat_integration: false`; the production `/api/agent/chat` path has no skill-runtime call site.
- All three feature flags default off. Manifests can be inspected in enabled/shadow mode without changing user-facing behavior.

Exit gate: manifests validate, versioning works, and no user-facing behavior changes.

### Phase 2 - Semantic route in shadow mode

- Generalize the viewport classifier schema into workflow + skill routing.
- Run it for Sage turns without using its output.
- Compare routes against labeled evaluation cases and current behavior.
- Tune skill descriptions and examples, not keyword lists.
- Use the measured `4,750 ms` timeout for Phase 2 shadow evaluation only; optimize and remeasure before approving any serial production timeout. Timeout uses the legacy path.
- Cache only an exact normalized-message + workflow-state + context-fingerprint match.

Implementation checkpoint (2026-07-10):

- Added deterministic eligible/unavailable candidate generation from registered workflow/skill metadata plus live asset, mode, context-provider, and target availability. Full skill bodies never enter the router prompt.
- Added a strict route schema and validator for speech act, workflow, skills, targets, context requirements, requested effects, and clarification state. Unknown IDs, unavailable skills, read-only writes, and invented context IDs fail closed. Redundant side-effect category flags are canonicalized from typed effects before permanent raw-message authorization and browser vetoes run.
- Added a privacy-safe exact-match cache keyed by a SHA-256 of normalized message, recent/workflow state, and the full context/catalog fingerprint. No raw message is stored in cache keys or telemetry.
- Added a Sage-only, queue-bounded, single-worker shadow submission after context normalization. It is never awaited and its result has no call site into production prompts, responses, tools, or frontend actions.
- Kept the measured 4,750 ms provider timeout. A fresh-cache 25-case synthetic evaluation produced 92% valid routes; one call timed out and one response failed schema validation and therefore fell back. Across validated routes, workflow, speech-act, viewport-effect, asset-effect, and skill accuracy were all 100%.
- Successful shadow calls in the final acceptance run measured p50 2,473 ms and p95 3,307 ms, with input-token p50/p95 1,919/1,928 and output-token p50/p95 283/329.
- The complete shadow-enabled FAI-to-motion Playwright regression passed 32/32, confirming no user-facing behavior change.

Exit gate: agreed route-quality threshold is met on paraphrases, typos, and synthetic fixtures.

### Phase 3 - FAI vertical slice

- Implement the seven v1 skills.
- Move relevant FAI, assembly, motion, and viewport instructions from the monolithic prompt into skills.
- Use selected-skill prompt assembly for the `supplier-fai-disposition` workflow.
- Add registered, data-driven executor recipes for the v1 action combinations; do not build the general dependency-graph planner yet.
- Keep the permanent browser authorization and suppression vetoes active after classifier mapping.
- Keep legacy fallback enabled.

Implementation checkpoint (2026-07-10):

- Added all seven v1 packages: FAI assessment, disposition, semantic part-feature reasoning, assembly-context reasoning, assembly-impact tracing, motion reasoning, and CAD viewport control. Manifests are versioned, ASCII-only, mode/workflow scoped, and validated against Sage's actual tool catalog.
- Added serial production routing behind `INSPECTORPRO_SKILLS_ENABLED`. Accepted routes replace the monolithic Sage prompt with a compact core, the selected workflow, only the selected skill bodies, and only tools allowed by those skills. Missing, invalid, low-confidence, write-category, or out-of-slice routes use the unchanged legacy path.
- Added registered, data-driven executor recipes for resolved motion-group playback, motion-group highlighting, part highlighting, and feature highlighting. Executors consume validated live IDs only and preserve unrelated display, motion, and rotation state.
- Kept independent server authorization and browser-side vetoes permanent. Classifier side-effect labels are requests only; explanation questions remain read-only even when they mention motion or affected parts.
- Hardened route validation for classifier inconsistencies by deriving side-effect categories from typed effects, clamping clarification text, and normalizing redundant primary-role labels. Unknown IDs, unavailable skills, unsafe writes, and invalid targets still fail closed.
- The controlled Phase 3 live workflow passed 32/32 checks. It verified read-only FAI impact and motion questions, explicit affected-motion playback at 30 RPM, additive crankshaft visibility without stopping motion, and full viewport restoration. The frozen offline bars passed 141/141 Python checks and 115/115 browser authorization/mapping checks. A final clean 25-case semantic evaluation passed every case with 100% route availability, effect accuracy, skill recall, and skill precision.
- Added privacy-safe provider-error diagnostics for routing failures. Logs and evaluation artifacts retain a short sanitized reason with the exception type while redacting credentials and excluding prompts and model responses.
- Production activation remains off by default. The current serial router uses the measured 4,750 ms fallback budget for controlled testing only; latency optimization and remeasurement remain required before always-on rollout.

Exit gate: all required acceptance cases pass offline and live.

### Phase 4 - Tool policy and receipts

- Implemented a shared ASCII-only `ui-action-contract-v1.json` covering all 21 existing assembly, motion, display, rotation, navigation, and compare actions. Both the server guardrail and browser runtime validate the same action fields, types, ranges, workspaces, action IDs, bundle size, and conflicts.
- Added action-level browser receipts with requested and applied arguments, before/after state, evidence, duration, error, and status. A successful receipt requires both successful dispatch and a verified postcondition.
- Added explicit preservation contracts. Highlight, display, motion, and rotation domains cannot change as an unrelated side effect. Natural crank-angle progression is excluded from preservation comparisons while motion is running.
- Added deterministic same-turn receipt status. Successful actions are described only from successful receipts; failed or rejected action bundles replace affirmative model prose with a failure status. No second LLM response pass was added.
- Added bounded in-memory receipt history and a pending queue. Browser-born receipts are attached to the next `viewport_context`, sanitized server-side, exposed to the router as compact prior-turn facts, and acknowledged only after a successful server response. Current viewport state remains authoritative when it differs from a prior receipt.
- Added Assembly-scene readiness as a precondition for part highlight/display actions. This fixed a live ordering defect where a highlight requested from the Report tab materialized during the following motion action and falsely appeared as unrelated state mutation.
- Verification passed 149/149 frozen and Phase 4 Python tests, 115/115 browser authorization/mapping checks, 8/8 browser receipt-runtime checks, four embedded-script syntax checks, a 9/9 live two-turn receipt smoke, and the full 32/32 FAI-to-motion workflow. The numeric-grounding backstop now accepts the production JSON-row support format as well as rendered `[FAIL]` context lines, so failed-row quantification no longer depends on model wording.

Exit gate: no action is claimed without a successful receipt.

### Phase 5 - Multi-turn workflow state

- Implemented a strict workflow-state contract carrying workflow stage, objective, entities, evidence references, semantic referents, milestones, bounded receipts, asset fingerprint, revision, and expiry.
- Added separate bounded TTL/LRU production and shadow stores keyed by a stable browser chat-session ID. Shadow state cannot leak into production continuity.
- Added deterministic continuation-target resolution against current live IDs. `Show it`, `Bring that back`, and additive named-part commands now compose with the semantic router without replaying prior effects.
- Extended registered executors for hide, reveal, restore, and clear-highlight behavior while preserving unrelated motion, display, highlight, and rotation domains.
- Added idempotent receipt reconciliation. A multi-effect visualization succeeds only when every required browser action has a successful receipt.
- Added completion and narrow explicit-abandonment rules.
- Added browser persistence for semantic state only. Refresh does not replay viewport effects; matching assets resume, changed assets invalidate stale references, and configurable inactivity expiry changes no viewport state.
- Verification passed 164/164 Python checks, 135/135 browser/runtime checks, a 27-case semantic evaluation with 100% workflow/effect/skill/continuation accuracy, and a 22/22 live continuity smoke.

Exit gate: follow-up behavior remains correct across tab changes and session turns.

### Phase 6 - Migrate remaining Sage/Iris workflows

- Drawing inspection
- part-feature reasoning
- revision comparison
- assembly training
- plant-process explanation
- facility routing/capacity/layout
- report summarization

Migrate one workflow at a time with shadow comparison and rollback.

### Phase 7 - Builder integration

- Give Builder a separate permissioned skill catalog.
- Add skill/workflow editing through Builder with diffs, schema validation, evaluation tests, versioning, and approval before activation.
- Do not let an edited skill grant itself new tools or permissions.

Exit gate: authorized users can revise behavior without modifying the monolithic server prompt and without bypassing policy.

## Security and Governance

- Skills and workflows are versioned, immutable after activation, and auditable.
- Customer-authored skills may reference only tools granted by administrator policy.
- A skill update cannot expand its own permission scope.
- Source-code, shell, deployment, and prompt-editing tools remain Builder owner-mode capabilities.
- Every asset/system write has a preview, approval record, diff, validator result, and rollback artifact.
- Retrieved company standards are evidence sources, not executable instructions.
- User-supplied asset text, including drawing notes, FAI descriptions, BOM descriptions, profile prose, and extracted metadata, is untrusted data. Delimit, length-limit, and sanitize it before prompt injection; never let it define tools, permissions, or system instructions.
- Tool output is treated as untrusted structured data until schema validation succeeds.

## Definition of Done for V1

V1 is complete when:

- Sage routes the FAI vertical slice through versioned workflow and skill packages.
- Natural-language paraphrases and misspellings are handled by the semantic classifier.
- Deterministic validation prevents unknown targets, unavailable tools, and unauthorized effects, with permanent browser-side final vetoes for viewport actions.
- Explanation questions never change the viewport.
- Explicit visualization commands execute the correct combination of highlight and motion tools.
- Multi-skill turns preserve existing viewport state unless the user asks to change it.
- The visible response reflects execution receipts.
- Total token use, including the router call, is measured and is lower than the equivalent monolithic-prompt path.
- All unit, classifier, policy, synthetic-fixture, and Playwright acceptance tests pass.
- A feature flag can restore the legacy path without reverting code.

## Resolved Review Decisions

1. Keep the first workflow narrow and name it `supplier-fai-disposition`. Generalize to nonconformance disposition only after another validated workflow requires it.
2. Allow the main agent to request exactly one additional skill, validated and loaded in a second pass.
3. Limit a normal turn to one primary plus three supporting skills.
4. Phase 0 measured classifier p50 `2,014.7 ms` and p95 `3,150.2 ms`; a two-second timeout is rejected. Use `4,750 ms` for shadow evaluation, retain legacy fallback, and do not approve serial production routing until optimization and remeasurement.
5. Keep viewport actions frontend-executed in v1. Generate browser receipts and deterministic same-turn status text; return receipts to the server on the next context attachment.
6. Activate skill/workflow changes through code review initially. Builder-managed activation remains Phase 7.
