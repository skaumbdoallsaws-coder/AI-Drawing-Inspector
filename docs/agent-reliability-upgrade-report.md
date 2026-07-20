# Agent Reliability Upgrade Report

Status: implemented for the Sage supplier FAI workflow.

## Already Present Before This Upgrade

- Hybrid semantic routing with deterministic eligibility validation.
- Permanent server and browser authorization gates for side effects.
- Separate synthetic router evaluation and shadow routing.
- Provider-native tools on compiled skill turns.
- Browser action validation, execution receipts, and workflow-state continuity.
- Prompt module versioning, prompt hashes, context accounting, and explicit trust boundaries.
- Deterministic FAI response grounding and unsupported-claim cleanup.

## Added In This Upgrade

### Executable Skill Contracts

Every production skill now has a separate, versioned contract declaring:

- supported intents
- required evidence
- forbidden context
- side-effect policy
- output format and sentence limit
- missing-context behavior
- contradictory-context behavior
- compatible model family
- evaluation suite
- context-token budget and priority order

Production compilation fails closed when a selected skill lacks a contract. Activated skill manifests and skill bodies remain unchanged; policy metadata can evolve independently.

### Deterministic Contract Composition

When multiple skills are selected, code resolves one composition policy before prompting:

- the primary skill controls answer format
- the strictest contradiction behavior wins
- side effects remain prohibited by default
- explicit-request tool requirements are combined
- required evidence and forbidden context are unioned

This removes prompt-order dependence between skill instructions.

### Context Consistency And Provenance

The context compiler now:

- computes missing tolerance limits from nominal and tolerances
- computes deviation from nominal, tolerance direction, and exact exceedance
- classifies supported internal- and external-diameter fit direction
- leaves non-fit geometry unclassified instead of guessing
- detects status contradictions and conflicting duplicate FAI rows
- detects inspected-part, revision, and configuration mismatches
- flags missing required context and duplicate mate records
- records observed facts, product requirements, calculated facts, and engineering inferences separately

Full provenance is stored in the runtime audit trace rather than added to the model prompt. The model receives only enriched evidence and concise conflict diagnostics.

### Context Budgets

Selected skill contracts determine the context budget. Optional providers are removed in reverse priority when needed. Required evidence is never removed to satisfy a budget; an unavoidable over-budget condition is reported explicitly.

### Layered Evaluation

Evaluation now separates:

- workflow routing
- skill recall
- skill precision
- structural selection validity
- compilation-plan correctness
- context inclusion and exclusion
- tool exposure
- deterministic engineering calculations
- context conflict handling

The new geometry suite includes generic oversized and undersized bores and shafts, plus a non-fit positional characteristic, so the checks do not depend on the piston example.

### Tool-Protocol Isolation

Compiled turns use `anthropic_native_tools_v1`. Textual action markers and custom tool blocks are ignored as executable actions on compiled turns, even if a model emits them. Legacy parsing remains isolated to explicit legacy routes.

## Deliberately Deferred

The following recommendations remain separate implementation projects:

- Workspace and viewport state-version checks on every browser action.
- Idempotency and rollback semantics across multi-action browser transactions.
- Optional second-model verification for high-risk disposition or physical-action recommendations.
- Broader unseen-assembly and drawing evaluation datasets.
- Migration of non-FAI workflows away from the legacy prompt architecture.

These changes touch execution semantics, latency, or product breadth and should each have an independent checkpoint and live acceptance suite.
