# InspectorPro Chat Streaming - Implementation Plan

Status: approved for implementation (revision 2, incorporates architecture review corrections).
Date: 2026-07-11

Principle: streamed text improves perceived latency; only the finalized response
and validated browser receipts have authority. Streaming is a provisional
display layer over the existing complete-response pipeline and must not weaken
any deterministic gate, cleaner, executor, or receipt contract.

## 1. Current-State Inventory (verified)

Model call sites (all `client.messages.create`, none provider-streaming today):

| Site | Function / endpoint | Role |
| --- | --- | --- |
| server.py:19302 | `agent_chat` -> POST /api/agent/chat (18650) | Main chat target (Sage/Iris). Sync call inside async def: blocks the event loop (pre-existing defect, fixed by this work). |
| server.py:20228/20327 | `agent_chat_stream` -> POST /api/agent/chat/stream (20067) | Scout SSE. Phase events only; provider call non-streaming. Untouched until Phase 6. |
| server.py:18613 | `classify_viewport_intent` | Concurrent Haiku classifier (legacy path). |
| ai_inspector/agent_skills/shadow.py | `classify_shadow_route` | Serial router on skill turns. |
| server.py:10368 | `_generate_profile_builder_draft` | Roadmap Phase 8. |
| server.py:10656 | `_generate_training_narration` (10690) | Roadmap Phase 6/8. |
| server.py:14065 | /api/agent/suggestions | Not a streaming target. |
| server.py:20408/20512/20625 | summarize / fai-verdicts / fai-agent-fill | Roadmap Phase 8 (required for "every model answer"). |

Structured directives embedded in answer text (parsed post-hoc today):
`<tool_calls>` JSON (parse: server.py:15045; guardrails: 15003; legacy mirror:
15068); `[UI_ACTIONS]...[/UI_ACTIONS]` JSON; line markers HIGHLIGHT_PARTS:,
HIGHLIGHT_FEATURES:, HIGHLIGHT_DIMS:, COMPARE_FEATURES:, FAI_FILL:, FAI_TOL:,
EXPLODE_LEVEL, CAMERA_FOCUS, SHOW_GEOMETRY_DIFF, RUN_INSPECTION; walkthrough
narration segments. Skill path adds registered executor bundles
(`plan_registered_executor` + `merge_executor_tool_calls`), `skill_execution`,
`skill_runtime`, `viewport_intent`, workflow-state mirror, browser receipts
(static/ui_action_runtime.js + static/contracts/ui-action-contract-v1.json).

Post-processing order in `agent_chat` (whole-answer assumptions):
text assembly (~19325) -> marker/tool extraction -> FAI cleaner
`_clean_report_fai_response` (19349-19366; NOT prefix-stable: numeric grounding
prefix needs the whole-answer digit check; leading Accept->Reject flip rewrites
the first word from later content) -> `_clean_agent_response` mojibake repair
(16784) -> guardrails -> executor merge -> result JSON consumed by the frontend
at index.html:49504-49620.

Frontend:
- SSE-over-fetch consumer already exists (index.html:50061-50120, Scout).
- Provisional streaming bubble already exists: `createPlantWalkStreamingMessage`
  (45608) - one assistant message, `setText`, bubble-only rerender via
  `formatMessageText` (45497, escape-first, partial-markdown safe), `finish()`.
  Currently driven by a client-side typewriter (21197+), not provider deltas.
- Sessions: `chatSessionId` (Phase 5), `session.waiting` send lock,
  `requestId/turnId` stale guards (50048), `scheduleAgentStateSave()`.
- Scroll is unconditionally forced to bottom (42075, 45598, ...). No
  near-bottom check today.

Telemetry: `record_anthropic_call(model, response, latency_ms, status,
errorType, route, workflow, agentType)`; telemetry_events has no first-token
column (additive migration required).

SDK: anthropic 0.75.0. `AsyncAnthropic().messages.stream` VERIFIED available.

## 2. Architecture: provisional deltas, authoritative commit

```
client POST /api/agent/chat/v2/stream
  status: routing                (serial router when SKILLS_ENABLED)
  response_started               (route decided, prompt assembled)
  AsyncAnthropic messages.stream (async for; no worker thread, no queue)
      raw deltas -> StreamDirectiveFilter (marker firewall)
                 -> mode policy (raw | sentence-buffered)
                 -> text_delta events (confirmed-safe prose only)
      directive bytes -> buffered; surfaced only as tool_block_* signals
  [generation ends] -> EXISTING pipeline verbatim:
      parse_tool_calls -> guardrails -> executor merge ->
      _clean_report_fai_response -> _clean_agent_response -> result{}
  response_completed { final: legacy result JSON, usage, timings }
client: bubble stays in "Generating" state until commit; commit replaces
provisional text with final.response; only then dispatch final.tool_calls
through the unchanged browser pipeline (gates, suppression, receipts,
deterministic honesty status).
```

Transport: SSE framing over fetch POST (same as Scout: StreamingResponse,
text/event-stream, X-Accel-Buffering: no; client getReader/TextDecoder loop).
EventSource rejected (GET-only; cannot carry inspection_context). WebSockets
rejected (no bidirectional need; cancel = AbortController abort).

Provider invocation: AsyncAnthropic async streaming is the PRIMARY design -
no queue, no thread cancellation, no thread leakage, and it removes the
event-loop blocking defect. A sync-SDK worker-thread bridge is the FALLBACK
only; if used it must have a bounded asyncio.Queue (backpressure via blocking
put with timeout) and a cancellation Event checked between deltas so a
disconnected browser never leaves a provider thread running.

## 3. Stream Event Contract v1

Envelope on every event: `v:1, event, response_id, seq (monotonic from 0), ts`.
Client discards `seq <= lastSeq` or stale `response_id`.

| event | fields | semantics |
| --- | --- | --- |
| response_started | chat_session_id, message_id (client-echoed), agent_type, mode, routing {path, workflow?, skills?, fallback_reason?} | once, before any text |
| status | phase: routing/context/generating/executing/finalizing, detail? | safe operational status only; never chain-of-thought |
| text_delta | text | append-only confirmed-safe prose |
| tool_block_started | kind: tool_calls/ui_actions/line_marker, marker? | no payload |
| tool_block_completed | kind, count | |
| action_bundle_validated | source: skill_executor/model/legacy_mirror | informational; bundle rides in final |
| workflow_state | state (compact mirror) | emitted ONLY with the terminal commit, never provisionally |
| response_completed | final (byte-identical legacy result JSON), usage {input, output, cache_read, cache_write}, timings {route_ms, first_token_ms, first_clean_sentence_ms?, stream_ms, pipeline_ms, total_ms} | terminal; sole commit source |
| response_cancelled | reason: user/disconnect, partial_len | terminal; nothing committed |
| response_error | code, message, retryable | terminal |

Exactly one terminal event per response. Client-side execution/receipt timing
continues to come from ui_action_runtime receipts (Phase 4 contract).

## 4. Backend Changes

### 4.1 Refactor by seams (own checkpoint, no user-visible change)

Do NOT extract the 950-line `agent_chat` in one move. Introduce five seams,
one edit each, keeping `agent_chat` as the orchestrator:

1. provider invocation: `_invoke_agent_model(client, model, system, messages, stream_sink=None)`
2. raw-response accumulation: `_accumulate_response_text(response_or_stream)`
3. structured-directive parsing: `_extract_agent_directives(text, agent_type, ctx)`
4. response cleaning: `_clean_agent_answer(text, ctx, request)` (wraps FAI + mojibake order)
5. final result assembly: `_assemble_agent_result(...)`

Golden-equivalence tests use an INJECTED deterministic provider response
(extend the `complete=` injection pattern already used by the router tests
into `_invoke_agent_model`); real model calls cannot establish byte-for-byte
equivalence. Corpus: representative fixtures per mode (plain prose, prose +
tool_calls, prose + UI_ACTIONS, each line marker, FAI defect answer, walkthrough
narration, mojibake bytes). Assert identical result JSON pre/post refactor.

### 4.2 Streaming endpoint

`POST /api/agent/chat/v2/stream`, gated by flags (Section 10). Runs the same
pipeline with an emit callback; provider call switches to
`AsyncAnthropic.messages.stream` (`async for` deltas). Token accounting from
`get_final_message().usage`. Legacy POST /api/agent/chat retained unchanged
indefinitely. Scout endpoint untouched until Phase 6.

### 4.3 StreamDirectiveFilter (marker firewall)

Colocated with the marker parsers; ONE shared sentinel registry so stream and
batch cannot drift. Rules:
- hold back the longest tail that could be a prefix of any sentinel
  (case-insensitive, tolerant of leading whitespace and up to N spaces around
  the marker colon; line-anchored markers held from line start);
- inside an opened block, swallow everything until the terminator;
- after the FIRST directive opens, release no further prose (blocks sit at the
  end of answers by prompt contract; trailing prose commits at finalize);
- ~8-char release margin so mojibake substitution is prefix-stable;
- malformed/unterminated blocks: swallow to end of stream; the batch parser at
  finalize is authoritative for what was actually there.
Tests must cover malformed and partial markers, mixed case, padded whitespace,
and sentinel splits at every byte boundary - not only valid sentinels.

### 4.4 Cancellation / disconnect

Generator awaits `request.is_disconnected()` between events; on disconnect or
client abort: cancel the async provider stream (context-manager exit),
record telemetry status="cancelled" stage="stream_cancelled", emit nothing
further, skip the pipeline entirely. A cancelled or failed stream commits no
message, executes no actions, and MUST NOT advance Phase 5 workflow state:
the WorkflowStateStore update happens only inside the terminal-commit path,
after response_completed's final is assembled.

### 4.5 Telemetry

Additive column firstTokenLatencyMs (+ firstCleanSentenceMs for report-FAI);
workflow="agent_chat_stream_v2"; cancellation accounting; finalize-delta
magnitude metric (how often final.response differs from streamed text).

## 5. Frontend Changes (static/index.html)

1. Generalize `createPlantWalkStreamingMessage` ->
   `createStreamingAssistantMessage(agentKey, messageId)` with `appendText`,
   `setStatus`, `fail`, `commit(final)`. Provisional message is `pending: true`
   and EXCLUDED from `scheduleAgentStateSave()` and `flattenMessagesForApi()`
   until commit (refresh mid-stream leaves clean history).
2. The bubble visibly remains in the "Generating" state (cursor + status chip)
   until response_completed, INCLUDING through the finalize reconciliation, so
   a final correction reads as completion, not as the system silently changing
   its answer.
3. Delta coalescing per requestAnimationFrame; bubble-only rerender via
   `formatMessageText`; typing cursor honors prefers-reduced-motion.
4. Scroll: autoscroll only when within ~48px of bottom; manual scroll pins the
   view; "jump to latest" affordance while pinned.
5. Send button becomes Stop during generation (AbortController);
   `session.waiting` remains the concurrency lock; stale guards retained.
6. Commit path runs the existing 49504-49620 handling against `final`
   verbatim, then swaps provisional text for final.response and persists.
7. Retry policy: automatic fallback to legacy /api/agent/chat ONLY when the
   failure occurs before any visible text was streamed. After partial visible
   output, show a manual Retry control instead of silently paying for a second
   generation.
8. Multi-session isolation: stream handle on the origin session; rendering
   gated by `agentKey === currentAgent`; switch-back rerenders from state.
9. Action turns: stream neutral explanation only. Never stream "I
   highlighted..." / "motion is playing" claims; the receipt-grounded
   confirmation is appended after browser execution succeeds (existing
   deterministic status + honesty rewrite at commit).
10. Harden `formatMessageText` link hrefs to an http(s) allowlist while here.

## 6. Mode Policy and FAI Cleaning

- Low-risk modes (drawing, 3dmodel, assembly/motion explanation, revision
  compare, training, report summaries, Scout): raw delta streaming through the
  firewall; mojibake substitution on release with holdback margin.
- Report/FAI (`_fai_like_turn` or active_mode in {report, report_fai}):
  SENTENCE-BUFFERED streaming + final reconciliation. Raw token streaming is
  unsafe here: the cleaner removes catastrophic claims, changes disposition
  language, scopes repeated instances, and prepends numeric evidence.
  Implementation: refactor the cleaner's sentence loop into a shared
  `_clean_fai_sentence()` used by both stream and batch; hold the first
  sentence until the second boundary when it begins with a disposition verb
  (Accept->Reject flip window); whole-answer transforms (numeric grounding
  prefix) resolve at finalize via the commit replacement, under the visible
  Generating state.
- Latency targets are mode-specific: low-risk first token and high-risk first
  CLEANED SENTENCE are separate metrics with separate targets; the <500 ms
  first-token target does not apply to sentence-buffered FAI.

## 7. Testing Matrix (synthetic fixtures only)

Unit (python, injected deterministic providers):
- StreamDirectiveFilter property tests: all chunkings of every fixture;
  released text equals final display text; no sentinel substring ever
  released; malformed/partial/case-variant/whitespace-variant markers.
- `_clean_fai_sentence` parity vs batch cleaner across the full grounding
  corpus (reuses test_fai_response_grounding cases).
- Golden equivalence for the seam refactor (Section 4.1).
- Fake stream scripts: slow output, error after partial, timeout before first
  token, cancellation, empty response.

Integration (FastAPI TestClient): seq monotonicity, exactly-one-terminal,
disconnect cancels provider (fake), flags-off 404/fallback, workflow state
unchanged after cancelled/failed stream.

Node harness: extracted stream consumer fed synthetic SSE chunk streams
including split-mid-line, duplicate seq, reordered seq, garbage lines; single
atomic commit; no directive fragments.

Playwright (scripted-stream test flag, canned deltas): DOM polled per frame
for banned strings (raw directives, mojibake, banned FAI claims); FAI
sentence streaming; explanation question -> zero viewport change; action turn
executes only post-commit with receipts + honest status; cancel; refresh
mid-generation; two concurrent agent chats; workflow continuity smoke with
streaming on; reduced motion; legacy fallback; accessibility pass.

Frozen bars: all existing suites plus both live smokes green with flags ON
and OFF.

## 8. Rollout Phases

| Phase | Work | Exit gate |
| --- | --- | --- |
| 1 | Telemetry columns, golden fixture capture, sentinel registry | baselines recorded |
| 2 | Seam refactor + AsyncAnthropic move; no UI change | golden equivalence; frozen suites green |
| 3 | v2 endpoint + firewall + frontend consumer; low-risk read-only modes, Sage+Iris | stream Playwright suite green; no-directive invariant |
| 4 | tool_block buffering + action turns (execute-at-commit) | contract smokes green streaming |
| 5 | Report/FAI sentence mode | cleaner parity + live FAI smoke streamed |
| 6 | Scout unification, narration/training, Builder allowlist entry | Scout UX unchanged or better |
| 7 | Default-on; legacy retained | soak; cancel rate + finalize-delta reviewed |
| 8 | Batch surfaces: /api/agent/summarize, /api/fai-verdicts, /api/fai-agent-fill, profile generation, guided narration | "every model answer" objective met |

Rollback at every phase: flags off; legacy endpoint never removed; Phase 2
protected by golden equivalence.

## 9. Flags

- INSPECTORPRO_CHAT_STREAMING (master, default off)
- INSPECTORPRO_STREAMING_AGENTS (csv allowlist: sage,iris,scout,builder)
- INSPECTORPRO_STREAMING_HIGH_RISK_MODES (default off; report/report_fai stay
  non-streaming until Phase 5 even when the master flag is on)

## 10. Risks / Unresolved

1. Seam refactor is the risk center - mitigated by seams + injected-provider
   golden tests, its own checkpoint.
2. Finalize reconciliation visibility in report-FAI - mitigated by the
   persistent Generating state; finalize-delta metric watches magnitude.
3. Voice/TTS stays at commit in v1; sentence-level TTS deferred.
4. Native provider tool-use migration out of scope (would simplify firewall).
5. Scout bespoke browser-panel events: preserved during Phase 6 unification.
6. Cancel discards partial text in v1; retention revisited later.
7. No mid-stream resume in v1 (local single-user); revisit for cloud.

## 11. Definition of Done (production activation)

- Low-risk: first token < 500 ms after route completion (p50). High-risk:
  first cleaned sentence target measured and reviewed separately.
- No test in the frozen + new matrix can surface a directive fragment,
  ungrounded FAI claim, premature action claim, or mojibake at ANY frame.
- Cancel/refresh: no orphaned messages, no executed actions, no workflow-state
  advancement, correct telemetry.
- All gates/receipts/workflow behavior verified live with flags on; golden
  equivalence for the legacy path; token accounting, model identity,
  first-token latency, cancellations, and errors recorded; one-flag rollback.
