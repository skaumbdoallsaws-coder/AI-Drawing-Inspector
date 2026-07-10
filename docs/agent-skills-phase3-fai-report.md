# Agent Skills Phase 3 FAI Report

Date: 2026-07-10

## Scope

Phase 3 implements the first production-capable skills slice for Sage:

- `assess-fai-characteristic`
- `recommend-fai-disposition`
- `reason-about-part-features`
- `reason-about-assembly-context`
- `trace-assembly-impact`
- `reason-about-motion`
- `control-cad-viewport`

The slice covers the supplier FAI workflow from measured-characteristic assessment through assembly impact, supported motion explanation, and an explicitly requested viewport visualization.

## Runtime Path

When `INSPECTORPRO_SKILLS_ENABLED=1`, Sage first receives a semantic route built from registered metadata and compact live context. Deterministic validation then:

1. rejects unknown workflows, skills, context IDs, targets, and effects
2. resolves declared dependencies and conflicts
3. canonicalizes redundant route metadata from typed intents
4. independently authorizes requested writes from the raw user message
5. selects one primary and at most three supporting skills

An accepted FAI route replaces the monolithic Sage system prompt with a compact core, workflow selection, selected skill bodies, and the selected skills' allowed tools. The legacy prompt remains the fallback for missing, invalid, unavailable, low-confidence, asset-write, system-write, and out-of-slice routes.

## Registered Executors

Phase 3 adds fixed, data-driven recipes rather than a general workflow graph engine:

- `show-resolved-motion-group`
- `highlight-resolved-motion-group`
- `highlight-resolved-parts`
- `highlight-resolved-features`

The recipes consume only validated IDs from live context. They do not contain engine part numbers or demo-specific targets. Existing display, rotation, and motion state is preserved unless the requested effect owns that state.

## Safety Contract

- Classifier output requests side effects but never authorizes them.
- Read-only questions and explanations cannot change the viewport.
- Server authorization and browser suppression remain independent final vetoes.
- Unknown or unavailable targets fail closed.
- FAI claims remain scoped to measured evidence and the inspected instance.
- Asset writes continue through the legacy deterministic path in this phase.
- Execution failures retain the legacy fallback; the model cannot bypass registered executor validation.

## Verification

- Skill runtime: 8/8
- Semantic routing: 17/17
- Phase 3 prompt and executor tests: 4/4
- Combined frozen Python regression: 141/141
- Browser authorization and mapping: 115/115
- Controlled live FAI-to-motion Playwright workflow: 32/32

The live workflow verified:

- assembly-impact and affected-motion questions stayed on the Report tab with no motion or highlights
- `show the affected motion` switched to Assembly, highlighted the resolved semantic motion group, and started package playback at 30 RPM
- `bring the crankshaft` added the crankshaft without stopping motion or clearing prior highlights
- `bring everything back` cleared highlights and restored hidden parts while preserving motion

The final clean semantic evaluation passed all 25 synthetic cases. Route availability, workflow accuracy, speech-act accuracy, viewport-effect accuracy, asset-effect accuracy, skill recall, skill precision, clarification accuracy, and continuity accuracy were all 100%. Skill recall allows relevant supporting skills beyond the minimum expected set; the separate precision check requires every proposed skill to be eligible for the selected workflow, unique, and within the one-primary-plus-three-supporting cap.

The earlier HTTP 400 burst was transient and account-side. Later minimal and full-route calls succeeded with the same request shape. Provider failures now log and return a short sanitized reason alongside the exception type; API keys and authorization tokens are redacted and the reason is length-limited.

## Operational State

`INSPECTORPRO_SKILLS_ENABLED` and `INSPECTORPRO_SKILLS_SHADOW` both default to off. Phase 3 is suitable for controlled activation and rollback testing, but not yet for always-on production use. The serial router still has a measured multi-second latency cost and must be optimized and remeasured before normal activation.

The next implementation phase is formal tool policy and browser execution receipts.
