# Sage Facility Lab Mode Experiment Plan

Date: 2026-09-02

Status: Deferred architecture experiment; not implemented or production-qualified

Backlog owner: `FLI-032`

## 1. Objective

Evaluate a model-first Facility Layout agent that can understand broad natural
language, inspect the current workspace, select existing semantic tools, execute
multiple reversible steps, and repair its plan after deterministic tool errors.

The experiment is intended to determine whether Sage can become as fluid with
paraphrases and follow-up requests as a general tool-using agent without weakening
InspectorPro's geometry, evidence, persistence, or approval boundaries.

## 2. Core Decision

"Zero restriction" applies to language understanding and reversible planning,
not to irreversible effects or claims:

```text
unrestricted user language
  -> current workspace observation
  -> model-authored semantic intent and plan
  -> searchable Facility tool selection
  -> deterministic tool execution
  -> validation and model repair
  -> one unsaved cumulative draft
  -> explicit user approval before Save
```

The model may choose and combine supported tools without first matching a
feature-specific phrase template. Deterministic InspectorPro code continues to
own coordinates, geometry, entity identity, validation, evidence status, and
persistence.

## 3. Motivation

The existing deterministic kernels, draft model, receipts, validation, Undo,
and explicit Save boundary are valuable and remain in place. The experiment
targets the rigid language layer that has accumulated around them.

Observed failure mode:

```text
user sentence
  -> feature-specific keyword or regular-expression match
  -> narrow request schema
  -> one command or not_applicable
```

Semantically equivalent requests can therefore take different paths when a
particular verb or expected phrase is absent. Lab Mode replaces that primary
route with semantic planning while retaining deterministic guards at the action
boundary.

## 4. Lab Mode Boundaries

Lab Mode must:

- run behind an explicit development-only feature flag;
- operate on an isolated unsaved draft;
- observe the current layout, selection, active draft, and relevant revisions;
- retrieve only the tool contracts relevant to the current task;
- allow multi-step observe, plan, act, validate, and repair cycles;
- retain exact tool inputs, outputs, errors, assumptions, and receipts in a trace;
- preserve bounded calls, elapsed time, response size, and context;
- ask a question only when an ambiguity materially changes the result;
- require explicit approval before Save; and
- leave the established production Sage path available for A/B comparison.

Lab Mode must not:

- write directly to Facility Layout storage;
- treat a build request as approval to Save;
- let model text grant itself authority;
- bypass deterministic schemas or validators;
- present inferred policy, safety, compliance, capacity, or performance as fact;
- imitate pointer events when a semantic tool exists;
- execute arbitrary repository code as part of Facility authoring; or
- silently continue after a stale revision or exhausted budget.

## 5. Semantic Planning Contract

The model-facing intermediate representation should describe meaning rather
than geometry. At minimum it records:

- user goal and requested outcome;
- referenced entities and unresolved references;
- ordered and unordered constraints;
- explicit dimensions, quantities, units, and provenance;
- relationships such as containment, adjacency, sequence, and preservation;
- assumptions that are permitted and assumptions that require confirmation;
- entities and geometry that must remain unchanged;
- proposed semantic tool steps and expected postconditions;
- current authority level; and
- success, clarification, refusal, and repair conditions.

Different wording with the same meaning must compile to the same normalized
intent. The language layer must not require command words such as `route`,
`divide`, or `place` when the requested outcome is otherwise clear.

## 6. Experiment Phases

### LAB0. Freeze The Comparison Baseline

- Select representative successful, paraphrased, ambiguous, contradictory, and
  follow-up prompts from the existing G1 through navigation evaluations.
- Record current production-router outcomes, tool calls, latency, clarification
  rate, draft changes, and saved-layout hashes.
- Keep these cases fixed during the initial experiment.

Exit evidence: reproducible current-path baseline and frozen evaluation hashes.

### LAB1. Add The Model-First Harness

- Add a development-only Lab Mode entry point without removing current parsers.
- Supply a compact revision-bound workspace observation.
- Let the model produce the semantic planning contract through strict structured
  output.
- Expose tool search followed by the smallest relevant contract slice.
- Return every deterministic tool result to the model so it can continue,
  clarify, repair, or stop.
- Persist the run and completed-step receipts so a bounded run can span turns.

Exit evidence: one model-first run can inspect, plan, call tools, repair one
recoverable failure, and return an unsaved validated draft.

### LAB2. Prove One Vertical Workflow

Use a narrow but multi-step Facility workflow that exercises references and
follow-ups. The initial candidate is:

1. create or reshape a facility envelope and departments;
2. add or amend circulation;
3. place supported assets or bind an existing moving actor; and
4. process an unpredictable follow-up that changes an earlier constraint.

The model chooses semantic steps. Existing deterministic engines calculate and
validate all geometry. Undo must restore the exact base, and Save remains a
separate explicit action.

Exit evidence: browser-visible end-to-end completion without phrase-specific
Lab Mode routing rules.

### LAB3. Evaluate Fluidity And Control

- Run the frozen LAB0 cases through both production Sage and Lab Mode.
- Add held-out paraphrases written after the Lab Mode prompt and tools are frozen.
- Include pronouns, corrections, reordered clauses, omitted command verbs,
  interruptions, and valid cross-feature requests.
- Grade semantic intent, entity grounding, tool choice, completed outcome,
  clarification quality, repair behavior, saved-state integrity, and latency.
- Treat unsupported claims, unauthorized Save, invalid geometry, or hidden
  partial completion as automatic failures.

Exit evidence: Lab Mode demonstrates a material intent-success improvement with
no regression in geometry validity, authority, Undo, or saved-state protection.

### LAB4. Decide Whether To Expand

If LAB3 passes, progressively migrate Facility domains from feature-specific
primary parsers to the shared semantic planner. Existing parsers may remain as
fast paths or deterministic guards only when they produce behavior equivalent
to the shared intent contract.

If LAB3 does not pass, retain the production path and use the traces to identify
whether the limiting factor is context, tool design, model configuration,
grounding, planning, or repair.

## 7. Initial Scope And Estimate

Expected effort, subject to LAB0 repository verification:

| Scope | Estimate |
| --- | ---: |
| One workflow harness skeleton | 1-2 engineering days |
| Usable cross-feature prototype | 3-5 engineering days |
| Resumability, broad evaluations, and UI hardening | 1-2 weeks |

This is an A/B experiment, not a replacement migration. It should reuse the
existing observation, tool registry, deterministic kernels, draft execution,
validation, receipts, and browser presentation.

## 8. Success Criteria

The experiment succeeds only if it shows all of the following:

- semantically equivalent prompts converge on equivalent normalized intent;
- valid unexpected wording does not depend on adding another phrase handler;
- multi-step and follow-up requests complete through bounded tool orchestration;
- recoverable deterministic failures cause a repair or a precise question;
- material ambiguity causes no draft mutation;
- every generated geometry change comes from deterministic tools;
- no model output grants authority, evidence, or approval;
- the saved layout remains unchanged until a separate explicit Save;
- one Undo restores the exact base draft; and
- traces make every model decision and tool effect reviewable.

## 9. Deferred Decisions

Before implementation begins, freeze:

- the development feature-flag and endpoint names;
- effective provider, model, and reasoning settings for A/B runs;
- per-turn and whole-run call, time, context, and repair budgets;
- the exact semantic-plan schema;
- run persistence and expiry behavior;
- whether Lab Mode may use only Facility semantic tools or a separate sandboxed
  calculation tool as well; and
- the numeric LAB3 promotion threshold after the LAB0 baseline is measured.

## 10. Resume Point

When this work resumes, begin with LAB0. Do not delete or weaken existing intent
parsers first. Freeze the comparison corpus, confirm current runtime budgets,
then implement the smallest feature-flagged vertical slice and evaluate it
against the unchanged production path.
