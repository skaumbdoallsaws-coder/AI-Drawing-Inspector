# Sage objective-to-layout: tools and isolated candidate preview

Date: 2026-09-17

Subsequent extension: [brief-first research and correction report](sage-research-layout-implementation-report.md).
The inventory below records the earlier reviewed-source slice. The linked report
supersedes its reviewed-source-only entry and no-live-provider evidence boundary;
it does not grant whole-slice or normal-desktop qualification.

Status: Bounded Sage/tool and shared-workspace integration implemented. Off by
default. No live-model, normal-desktop, manufacturing or whole-slice qualification
is claimed. No real reviewed context was published and no manual layout was edited.

## Implemented path

```text
Choose an eligible reviewed context on a clean empty destination
  -> typed Sage chat with a stable client turn ID
  -> bind authenticated scope, exact sources, editor state and empty saved base
  -> inspect context and record every clause of the actual user turn
  -> compile a coordinate-free package through existing admission/geometry engines
  -> retain and inspect one exact current candidate
  -> display that candidate in the shared Plan/3D viewport
```

The model never receives a source-publication, authority-approval, Apply or Save
tool in this mode. A successful receipt, not completion prose, supplies the
candidate identity. Responses without a successful preview receipt have an
explicit incomplete state and cannot fall through to legacy browser edit actions.

### Tool contracts

| Tool | Behavior |
| --- | --- |
| `inspect_generation_planning_context` | Bounded overview and pages of current requirements, process steps, exact equipment mappings and evidence. |
| `record_generation_requirements` | Append requirements tied to the server-received user text and Unicode code-point spans; preserve earlier requirements or explicitly supersede them. |
| `preview_generation_package` | Admit a newly supplied semantic package under the current ledger, compile and validate it, then retain an isolated candidate. |
| `inspect_generation_candidate` | Read bounded entity pages from the exact current candidate, not the saved layout. |

Closed schemas describe nested inputs explicitly. Existing canonicalizers and
predicate validators remain the execution authority. Text-span completeness is
structural coverage, not independent proof of natural-language understanding.
Unseen paraphrase/generalization acceptance remains pending.

Retry keys are scoped by the actual stable turn identity; immutable ledger parents
permit reconstruction of identical retries after restart. Reordered object keys
remain equivalent. New corrections require a new turn, preserve history and make
old candidates ineligible. Caller-supplied trusted bindings are stripped before
the server reconstructs them from authenticated context.

Source/context and candidate inspection are paginated with explicit totals and
continuations. Current tool limits are eight context items or twenty candidate
entities per page, 16 KiB per result, eight provider rounds and the existing
ten-call/cumulative-result budget. Tool schemas cover envelope, departments,
resource patterns/quantities and circulation. Subdivisions, cell recipes,
module families and floor communication are excluded from this tool slice;
legacy generation capabilities are not removed.

### Gates and UI

`INSPECTORPRO_FACILITY_LAYOUT_GENERATION_PLANNING_SAGE` defaults off and depends
on `generation_planning_preview`, which requires `agent_preview`. Source listing,
trusted binding and tool execution check the capability and principal permission.
Tool-spec exposure also requires the explicitly selected planning tool policy.
Preview does not require `agent_write` and does not acquire a writable lease.

The new source-list endpoint is:

`GET /api/facility-layout-planning/{site_id}/{layout_id}/sources`

It lists bounded scoped references after revalidating their source eligibility;
unavailable/omitted contexts are reported. Publication remains curator-only.

The Planning control selects a reviewed context and routes subsequent typed chat
through this mode. The preview loader fetches the exact candidate using the
existing inspection endpoint and checks turn, source, workspace, ledger, base,
candidate revision and editor generation before and after loading. A correction,
source change, disposal or intervening editor change rejects a late response.

The display uses the same controller for Plan and 3D. It does not call
`installGenerationDraft`, change the session document, add history or dirty the
editor. Workspace edit commands and placement gestures are refused while this
isolated candidate is active; Exit planning restores the unchanged editable base.
Camera/view changes remain display-only and are not part of document equality.
No durable editor-adoption or recovery claim follows from this preview behavior.

## Implementation owners

- `ai_inspector/facility_layout/generation_agent.py`: explicit tool schemas,
  authority binding, actual-turn ledger adapter, paging and candidate queries.
- `generation_requirement_repository.py`: bounded scoped source discovery using
  the repository's native-safe filesystem traversal.
- `generation_admission.py`: include the immutable base revision in preview receipts.
- `feature_flags.py`, `host.py`: gated service, source listing and UI capability.
- `server.py`: selected-mode policy, authenticated attachment resolution, existing
  provider-loop execution, legacy-path exclusion and receipt response metadata.
- `static/facility_layout_generation_view.js`: isolated candidate controller.
- `static/facility_layout_transport.js`, `facility_layout_workspace.js`,
  `facility_layout_workspace.css`, `index.html`: scoped transport, source picker,
  shared viewport, responsive panel and typed-chat bridge.

## Verification

JavaScript: **185 checks passed**: workspace 87, transport 28, session 60,
application 6 and inline-script syntax 4.

Isolated Chromium: **one end-to-end test passed**. Evidence:
`.runtime/gen-agent-browser-06.xml` and
`.runtime/generation-preview-evidence/gen-agent-browser-06/browser-report.json`.
Six screenshots cover Plan and 3D at 1440 x 900, 900 x 700 and 430 x 820.
Canvas-pixel checks establish nonblank rendering and camera movement at each
size. A viewport-scoped rule separates the Plan scale and navigation controls
when the panel narrows the canvas; rectangle assertions prove no overlap.
Editor state is equal before preview, after view changes and after exit;
page errors and Save calls are zero. The isolated server shuts down in cleanup.

This harness uses the real shared workspace, transport and backend with a
synthetic source and structured tool calls. Its two assets intentionally use
catalog proxy geometry; these captures are not new GLB or native Electron evidence.
The normal full-page chat-to-viewport bridge still needs live desktop acceptance.

Python verification includes the real `/api/agent/chat` route with a synthetic
provider, actual context normalization/policy, the real tool loop and compiler.
One case first returns a genuinely invalid quantity, receives the registered
predicate refusal, and then compiles a corrected package. It is not evidence of
live-model tool selection or generalization. Adjacent tests cover authority
forgery, current-turn requirements, durable retries, stale corrections, exposure
gates and refusal of unadvertised legacy construction tools.

Final Python regression: **459 passed in 181.16 seconds**, zero failures/skips.
Evidence: `.runtime/gen-agent-regression-03.xml`. This includes generation
requirements, admission, tools, design-loop contracts, planning/program execution,
feature flags, construction service, host and legacy agent integration suites.
`git diff --check` passed for the touched paths. The ambient LangSmith plugin
reports its existing Python 3.14/Pydantic-v1 warning.

Earlier development failures are retained: fixture catalog selection was made
explicit after server environment loading changed it; an older policy assertion
was parameterized for both construction-flag states; the browser harness was
given the normal workspace root/style and resets camera orientation before each
movement check. No geometry tolerance or acceptance predicate was weakened.

## Remaining gates and next slice

1. Freeze an applicable reviewed scenario and independent held-out variants.
   Synthetic review assertions cannot be published as real manufacturing evidence.
2. Qualify actual typed chat with a live provider in the normal desktop app,
   including corrections, source paging, exact receipt display and failure paths.
   Voice-specific submission/display is not qualified by this integration.
3. Implement shared candidate adoption: exact selection, `agent_write` gating,
   correction-versus-Apply serialization, shared lease ownership, captured editor
   frames, O/A/B replacement recovery, lost acknowledgment reconciliation and Undo.
4. Implement the separately agreed explicit Save receipt case on an isolated
   destination, then measure the frozen provider-inclusive latency gates.

Process-binding materialization, FDL transfer optimization, dirty-draft
construction adoption, evidence acquisition and production qualification remain
outside this checkpoint. A populated manual layout is deliberately not a valid
destination for this new-empty-layout slice; nothing here clears it or substitutes
an empty document on the user's behalf.
