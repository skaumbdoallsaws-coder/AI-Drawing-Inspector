# Realtime Voice Orchestration Plan

Status: future architecture note. No production implementation yet.

Date captured: 2026-05-21

## Goal

Create a voice mode that feels like a person talking through a design with the user: immediate interruption, low dead air, visible search progress, grounded answers, and coordinated model/drawing highlighting.

The target user experience is not just "voice chat." It is a live design-review conversation where the assistant can:

- stop speaking immediately when interrupted,
- acknowledge the new concern naturally,
- search the active product context in the background,
- keep the user informed with safe progress statements,
- answer only when evidence is available,
- highlight features, drawing views, dimensions, or assembly components as the explanation unfolds.

## Current Agent Structure Must Stay Intact

This architecture does not replace the three product agents.

- Iris remains the inspection, drawing, feature, and part-context agent.
- Sage remains the deviation, FAI, assembly, impact, and engineering-explanation agent.
- Scout remains the sourcing, supplier, and purchased-part intelligence agent.

The new layer is voice-only orchestration above them.

Text mode should remain simple:

```text
User types -> selected agent answers
```

Voice mode gains orchestration:

```text
User speaks
-> Voice Orchestrator
-> selected agent role
-> retrieval worker
-> answer governor
-> speech controller
-> spoken answer + UI actions
```

## Why This Is Needed

The older voice pipeline creates avoidable latency:

```text
audio -> transcription -> LLM -> text -> ElevenLabs -> audio playback
```

Realtime speech models can reduce that path, but they do not eliminate retrieval latency. InspectorPro answers often depend on CAD metadata, drawing maps, inspection profiles, revision manifests, FAI data, supplier context, or quality records.

The design goal is therefore not "no computation time." The goal is:

- immediate interruption,
- immediate task acknowledgement,
- structured background search,
- safe filler tied to actual retrieval progress,
- stale-answer protection,
- grounded final answer.

That creates the perception of near-zero latency without sacrificing traceability.

## Core Components

### 1. Voice Orchestrator

Owns voice-mode state and routing.

Responsibilities:

- detect barge-in,
- cancel current speech,
- create a new `request_id`,
- decide whether retrieval is needed,
- select the active product agent (`inspector`, `deviation-analyst`, `parts-finder`),
- send structured work to retrieval workers,
- ignore stale worker results,
- decide whether to pause, cancel, ask, or finish prior work during task switches.

### 2. Front Speaking Layer

The user-facing voice. It borrows the active agent's voice/persona but does not invent technical conclusions.

It may speak about:

- what source is being checked,
- what source has been found,
- whether enough evidence exists yet,
- whether uncertainty exists,
- whether a previous task is being paused or resumed.

It must not speak:

- final technical conclusions before evidence is ready,
- unsupported material/process/criticality claims,
- exact dimensions unless they came from safe partial evidence,
- stale answers from superseded request IDs.

### 3. Retrieval Worker

Searches product context and emits progress.

Potential sources:

- active part metadata,
- active revision manifest,
- drawing map,
- drawing PDF references,
- inspection profile,
- feature color map,
- comparison data,
- assembly context,
- FAI records,
- supplier/spec context,
- future clean-room supplier capability context.

The worker should not return prose first. It should return structured evidence packets.

### 4. Answer Governor

Turns evidence into a safe answer plan.

Responsibilities:

- enforce source traceability,
- detect missing context,
- detect conflicts,
- apply permission boundaries,
- prevent unsupported claims,
- require uncertainty language when needed,
- route the final answer through Iris, Sage, or Scout.

### 5. Audio Controller

Owns speech playback.

Responsibilities:

- stop current speech on barge-in,
- suppress stale audio,
- play short bridge phrases,
- stream or play final answer,
- keep one audible assistant voice at a time.

### 6. Context Preloader

Keeps the current product context warm before the user asks.

Examples:

- active part number,
- active revision,
- selected feature,
- active drawing view,
- loaded drawing map,
- loaded inspection profile,
- available feature-color map,
- current bridge/SOLIDWORKS document state.

This is where much of the "zero latency" feel comes from: the system should not wait for the user's question before loading obvious current context.

## State Machine

Suggested voice-mode states:

```text
idle
listening
speaking
barge_in_detected
retrieving
bridging
answer_ready
answering
paused
cancelled
fallback
```

Every active task must have a `request_id`. The front speaking layer can only speak progress or evidence associated with the current active `request_id`.

## Event Types

Suggested internal events:

```text
user_turn_detected
barge_in_detected
speech_cancel_requested
retrieval_requested
retrieval_started
retrieval_progress
partial_evidence
retrieval_completed
retrieval_failed
retrieval_cancelled
task_switch_detected
answer_ready
speech_started
speech_finished
stale_result_ignored
```

## Data Contracts

### Retrieval Request

```json
{
  "event": "retrieval_requested",
  "request_id": "rq_1030024_001",
  "active_agent": "inspector",
  "speaker_name": "Iris",
  "user_question": "Can this counterbore be inspected from the drawing?",
  "active_context": {
    "part_number": "1030024",
    "revision": "revD",
    "active_view": "Section View B-B",
    "selected_feature": "Central stepped bore and counterbore"
  },
  "needed_evidence": [
    "drawing_map",
    "inspection_profile",
    "part_metadata",
    "revision_manifest"
  ]
}
```

### Retrieval Progress

Progress events are what make filler feel natural instead of scripted.

```json
{
  "event": "retrieval_progress",
  "request_id": "rq_1030024_001",
  "stage": "checking_drawing_map",
  "agent_visible": true,
  "sayable_hint": "checking the drawing views and dimensions"
}
```

```json
{
  "event": "retrieval_progress",
  "request_id": "rq_1030024_001",
  "stage": "profile_loaded",
  "agent_visible": true,
  "sayable_hint": "I found the revD inspection profile"
}
```

### Partial Evidence

Partial evidence may be spoken only when `safe_to_say` is true.

```json
{
  "event": "partial_evidence",
  "request_id": "rq_1030024_001",
  "safe_to_say": true,
  "claim": "The profile includes a feature named Central stepped bore and counterbore.",
  "source": "parts/1030024/revD/1030024_inspection_profile.json",
  "confidence": "high"
}
```

### Final Evidence Packet

```json
{
  "event": "retrieval_completed",
  "request_id": "rq_1030024_001",
  "active_agent": "inspector",
  "status": "complete",
  "confidence": "medium",
  "facts": [
    {
      "claim": "The profile includes a central stepped bore and counterbore feature.",
      "source_type": "inspection_profile",
      "source_path": "parts/1030024/revD/1030024_inspection_profile.json",
      "confidence": "medium"
    },
    {
      "claim": "Section View B-B includes related diameter and depth-region dimensions.",
      "source_type": "drawing_map",
      "source_path": "parts/1030024/revD/1030024_drawing_map.json",
      "confidence": "medium"
    }
  ],
  "missing_context": [
    "The drawing context does not explicitly label the 10.20 dimension as counterbore depth."
  ],
  "answer_constraints": {
    "may_answer": true,
    "must_mention_uncertainty": true,
    "must_cite_sources": true,
    "must_not_claim": [
      "counterbore depth is confirmed",
      "feature is critical",
      "material is aluminum"
    ]
  }
}
```

### Task Switch Event

```json
{
  "event": "task_switch_detected",
  "old_request_id": "rq_001",
  "new_request_id": "rq_002",
  "old_task": {
    "label": "revC to revD comparison",
    "progress": 0.82,
    "value": "high",
    "has_partial_findings": true,
    "estimated_time_remaining_ms": 1200,
    "safe_to_resume": true
  },
  "policy_recommendation": "ask_user"
}
```

## Filler Policy

Filler should be generated from progress events, not from generic canned lines.

Good examples:

- "Switching to the bolt pattern. I am checking the top view now."
- "I found the revD profile. I am checking whether the drawing explicitly supports it."
- "I found the relevant section view, but I am verifying the dimension before I call it confirmed."
- "I have enough evidence now, but there is one uncertainty to mention."

Bad examples:

- "That counterbore is definitely inspectable." before evidence is complete.
- "That is aluminum." when material is not specified.
- "This is critical." unless the drawing/profile/source explicitly says so.

The front speaking layer can speak about the search process, not unsupported technical conclusions.

Recommended filler frequency:

- immediate acknowledgement after barge-in,
- then at most one short update every 1.5 to 2.5 seconds,
- no filler if the final answer is ready quickly,
- no more than 2 or 3 progress updates for one simple question.

## Interruption And Cancellation Policy

When the user interrupts:

1. Stop current audio immediately.
2. Create a new `request_id`.
3. Mark prior speech as cancelled.
4. Cancel, pause, or deprioritize the active worker job.
5. Ignore any old worker result whose `request_id` is no longer active.

Default behavior:

- If the user clearly changes topic, supersede silently.

Example:

```text
User: Wait, forget that. Show me the bolt pattern.
Assistant: Switching to the bolt pattern. I am checking the top view now.
```

Ask the user only when prior work is valuable or near completion.

Recommended outcomes:

```text
supersede_silently
pause_and_switch
ask_user
finish_then_switch
```

Policy guidance:

- under 50 percent progress: switch silently,
- over 75 percent progress and medium/high value: ask or finish quickly,
- if user says "forget that": cancel,
- if new question is safety/quality critical: switch immediately,
- if old task can be resumed: pause rather than throw it away.

## Agent Routing

The orchestrator may keep the current agent or recommend a switch.

Examples:

- Drawing/feature/inspection question -> Iris.
- Deviation/assembly/FAI/impact question -> Sage.
- Supplier/source/capability question -> Scout.

If the user asks the wrong agent a specialized question, the voice layer may say:

```text
That is more of a Scout question. I can check supplier context for it.
```

But agent switching should not be noisy. If the app already knows the active task belongs to another agent, it can route internally and keep the user experience smooth.

## UI Synchronization

Voice answers should be able to drive existing UI actions:

- highlight part features,
- focus a drawing view,
- select a dimension,
- isolate an assembly component,
- open comparison panels,
- show a profile entry,
- show supplier/spec references,
- show uncertainty or missing-context banners.

The answer packet should eventually include optional UI actions:

```json
{
  "ui_actions": [
    {
      "type": "highlight_feature",
      "part_number": "1030024",
      "feature_name": "Central stepped bore and counterbore"
    },
    {
      "type": "focus_drawing_view",
      "view": "Section View B-B"
    }
  ]
}
```

## Failure Modes To Design For

The implementation must handle:

- silence detection errors,
- user starts speaking while assistant is speaking,
- user starts speaking while retrieval is running,
- multiple interruptions in a row,
- ambiguous references such as "that one",
- stale worker results,
- no evidence found,
- conflicting evidence between drawing/profile/CAD,
- permission-restricted supplier/customer context,
- realtime model unavailable,
- browser microphone permissions denied,
- network drop during live session,
- long-running tasks such as comparison, supplier search, FEA, or profile generation,
- filler fatigue,
- cost spikes from long realtime sessions.

## Telemetry Needed

Track:

- voice session duration,
- audio input tokens/cost,
- audio output tokens/cost,
- barge-in count,
- time to audio stop,
- retrieval latency,
- answer generation latency,
- speech start latency,
- cancelled task count,
- stale result count,
- filler count per turn,
- evidence confidence distribution,
- fallback rate.

This belongs naturally in the existing Usage dashboard once realtime voice is implemented.

## Recommended MVP

Do not implement every edge case first.

MVP should prove:

1. realtime speech path,
2. stop-on-barge-in,
3. one active product agent,
4. one retrieval worker,
5. structured progress events,
6. safe filler tied to progress,
7. stale request protection,
8. grounded final answer,
9. telemetry for each voice turn.

Suggested first scope:

- Iris only,
- active part/revision only,
- drawing map + inspection profile retrieval only,
- no supplier clean-room context,
- no long-running FEA/motion workflows,
- no multi-agent switching except a basic "this belongs to Sage/Scout" message.

After that works, expand to Sage and Scout.

## Acceptance Criteria

The MVP should pass these observable checks:

1. User interrupts spoken answer and audio stops within the target latency budget.
2. New user question creates a new `request_id`.
3. Old worker result cannot speak after a newer request is active.
4. Front voice gives a context-specific progress phrase based on worker progress.
5. Front voice never states unsupported technical conclusions before evidence is ready.
6. Final answer cites or names the evidence source.
7. Missing or weak evidence produces an uncertainty-aware answer.
8. UI can highlight at least one feature or drawing view from the answer packet.
9. Usage dashboard records voice/retrieval latency and cost.
10. If realtime voice fails, the app falls back safely to existing text/current voice path.

## Non-Goals For First Implementation

- Do not replace Iris, Sage, or Scout.
- Do not create two audible agents talking over each other.
- Do not allow filler to invent technical conclusions.
- Do not solve supplier clean-room sharing in the first voice MVP.
- Do not connect to FEA/motion workflows until the basic voice orchestration is proven.

## Strategic Value

If successful, this makes InspectorPro feel less like a chatbot and more like a live product expert walking through a design with the user. The assistant can talk, pause, respond to interruption, search evidence, highlight the model, explain uncertainty, and continue the conversation without dead air.

That would be a meaningful product differentiator because the value is not just speech. The value is realtime, traceable, product-grounded conversation over CAD, drawings, inspections, revisions, assemblies, suppliers, and quality context.
