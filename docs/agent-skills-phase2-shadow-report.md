# Agent Skills Phase 2 Shadow Report

Date: 2026-07-10

## Scope

Phase 2 adds semantic workflow and skill classification for Sage in shadow mode only. The route is not used for prompt construction, response generation, tool selection, or viewport execution.

The router receives:

- the exact user message and up to four recent turns
- compact live context and target identifiers
- active workflow state when present
- registered workflow and skill metadata only

Full `SKILL.md` bodies are not included.

## Safety Contract

- Unknown workflow, skill, target, effect, and context IDs fail validation.
- Unavailable skills cannot be selected.
- Declared skill dependencies are added deterministically; conflicts and post-expansion over-budget routes fail validation.
- Read-only speech acts cannot request writes.
- Model-requested effects remain unauthorized until independent deterministic gates approve them.
- Browser authorization and suppression remain the final authority.
- Shadow results carry `used_for_prompt: false` and `used_for_execution: false`.
- Telemetry stores route identifiers and metrics, not raw prompts or model responses.

## Acceptance Fixture

The committed fixture contains 25 synthetic cases covering:

- FAI assessment, disposition, assembly impact, and motion explanation
- commands versus questions using nearly identical motion wording
- typos and awkward grammar
- FAI table edits
- whole-assembly viewport commands outside the FAI workflow
- unavailable FAI context
- multi-turn `show it` continuation

Predeclared thresholds:

| Metric | Threshold | Result |
| --- | ---: | ---: |
| Valid-route rate | 90% | 92% |
| Workflow accuracy | 90% | 100% |
| Speech-act accuracy | 85% | 100% |
| Viewport-effect accuracy | 100% | 100% |
| Asset-effect accuracy | 100% | 100% |
| Skill accuracy | 85% | 100% |

Accuracy metrics are calculated over schema-valid routes. Availability is measured separately by valid-route rate because timeout or invalid output uses the unchanged production fallback.

## Provider Measurements

Final fresh-cache run, model `claude-haiku-4-5`, one worker, 4,750 ms timeout:

- 25 cases
- 23 valid routes
- 1 provider timeout
- 1 schema-invalid route
- successful latency p50: 2,473 ms
- successful latency p95: 3,307 ms
- successful input tokens p50/p95: 1,919 / 1,928
- successful output tokens p50/p95: 283 / 329

Evaluation artifacts now record per-case `failure.reason` and a `failure_counts` rollup, so provider availability failures such as timeouts remain distinct from route-quality failures such as schema-invalid output.

Parallel evaluation caused provider queuing without improving the local single-user product. Phase 2 therefore uses one nonblocking shadow worker and a three-turn bounded admission limit. The timeout was not increased.

## Regression Results

- Phase 2 routing unit suite: 13/13
- Combined Python regression suites: 133/133
- Frozen browser authorization/mapping suite: 115/115
- Shadow-enabled live FAI-to-motion workflow: 32/32

The live flow verified read-only FAI impact questions, explicit affected-motion playback at 30 RPM, additive crankshaft visibility without stopping motion, and complete viewport restoration.

## Operational State

`INSPECTORPRO_SKILLS_SHADOW` defaults to off. Enabling it starts telemetry-only Sage classification. `INSPECTORPRO_SKILLS_ENABLED` remains off for production chat; selected skills do not enter the main prompt until the Phase 3 vertical slice is explicitly enabled and verified.
