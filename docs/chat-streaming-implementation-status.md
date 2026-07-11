# Chat Streaming Implementation Status

Status: implemented for the Sage, Iris, and Scout main chat paths; structured
task surfaces remain in the next rollout slice.

This document records the code that landed from revision 2 of
`docs/chat-streaming-implementation-plan.md`. It distinguishes the completed
main-chat slice from later rollout surfaces so the product does not imply that
every model endpoint streams yet.

## Completed Scope

- `POST /api/agent/chat/v2/stream` provides SSE-over-POST for Sage and Iris.
- Scout's existing `POST /api/agent/chat/stream` keeps its search-browser
  events and now streams provider text deltas plus a final cleaned response
  when the shared allowlist includes `scout`.
- The legacy `POST /api/agent/chat` endpoint remains available and is the
  fallback when streaming is disabled or fails before visible text.
- Provider generation uses `AsyncAnthropic.messages.stream` on the streaming
  path and `AsyncAnthropic.messages.create` on the legacy path.
- The browser shows a provisional assistant bubble while deltas arrive. Only
  the authoritative terminal result is persisted, allowed to execute tools,
  and allowed to advance workflow state.
- The directive firewall suppresses partial, malformed, mixed-case, and
  whitespace-variant tool directives from the viewport. Actions run only
  after the terminal result has passed the existing guardrails.
- Report/FAI turns use sentence-buffered display and the shared FAI sentence
  cleaner. The bubble remains in its Generating state through final
  reconciliation, so a final safety correction is visible as completion,
  not an unexplained mid-answer rewrite.
- A direct explanatory FAI question about affected motion is answered from
  the loaded motion package's declared affected group. It names the group and
  related parts without changing the viewport; a separate explicit show/play
  request remains required to highlight or animate it.
- Stop cancels the current request, removes its provisional output, and leaves
  no persisted message, workflow-state update, or executed action. A failure
  after visible text provides manual Retry rather than silently changing to
  legacy mode.
- Agent sessions retain isolated in-memory streaming state. Pending messages
  are omitted from history and persisted state, so refresh does not restore a
  half-answer.
- Telemetry records first-token, first-cleaned-sentence, stream, pipeline,
  and final-reconciliation timings.

## Flags

All flags default to off. Controlled local rollout uses:

```text
INSPECTORPRO_CHAT_STREAMING=1
INSPECTORPRO_STREAMING_AGENTS=sage,iris,scout
INSPECTORPRO_STREAMING_HIGH_RISK_MODES=1
```

Streaming does not alter the independent skills rollout flags.

## Verification

The implementation has passed:

- 156 pytest checks across telemetry, streaming-backend, and semantic-region
  suites; 109 direct Python regression checks across skills, FAI, routing,
  workflow state, authorization, and classifier suites; and the standalone
  streaming-firewall suite.
- 147 browser/runtime checks, including directive filtering, stale SSE events,
  receipts, workflow persistence, and frontend stream contracts.
- Live Playwright streaming smoke tests for incremental text, final commit,
  cancellation, hidden directives, and history integrity.
- Existing live FAI-motion and Phase 5 workflow-continuity smokes through the
  streaming endpoint, with all actions delayed until terminal commit.

Measured local provider timings over 32 completed streams were approximately:

| Metric | p50 | p95 |
| --- | ---: | ---: |
| First token | 1.57 s | 2.83 s |
| First cleaned FAI sentence | 2.78 s | 8.95 s |
| Provider stream duration | 2.99 s | n/a |
| Final pipeline | 9 ms | 18 ms |

The plan's aspirational sub-500 ms first-token target is not met by the
current provider. The UI nevertheless gives immediate routing/generating
status and renders the answer progressively once generation begins. Further
provider/model optimization is a separate performance effort, not a reason to
weaken the authoritative final-commit contract.

## Deferred Surfaces

The following remain intentionally outside this checkpoint:

- Guided narration and voice synthesis.
- Batch endpoints for summaries, FAI verdicts/fill, and profile generation.
- Mid-stream reconnect/resume and retaining partial text after cancellation.
- Native provider tool-use migration.

They should adopt the same provisional-display and authoritative-commit model
when migrated.
