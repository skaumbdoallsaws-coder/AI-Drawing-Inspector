# Packaging Tools: Sage Integration Contract

Status: host admission, the shared Codex runtime route, and the editor/chat bridge
are implemented in the isolated worktree. Live chat acceptance passed on
2026-11-05. This is not a desktop release. Existing offline transport evidence
must not be interpreted as proof of a real model turn or live carrier rates.

## Host Implementation

- `packaging_shipping/admission.py` owns a bounded, expiring editor admission
  and a shared mutation lock. It pins the authenticated principal, conversation,
  selection, document and saved revision. Heartbeats cannot acknowledge an
  unrelated writer's revision. A successful terminal binding is read-only and
  remains available for memory finalization, not further tool calls.
- `packaging_shipping/api.py` exposes same-origin editor publish, heartbeat and
  revoke endpoints. Renderer input never grants edit authority. The isolated
  host explicitly enables direct edits through its existing Codex edit flag.
- `codex_runtime/packaging_pilot.py` uses the existing service, journal and MCP
  gateway. `gateway_turn.py` shares AppServer lifecycle with documentation;
  neither adds a new reasoning loop. Cancellation closes tool admission before
  transport shutdown and drains active work, preserving mutation receipts.
- `server.py` routes only admitted Sage `packaging_shipping` turns. It requires
  streaming, never falls back to another provider, and supplies packaging-only
  memory scope and revision metadata. Conversation history is not model state.
- `static/packaging.js` and `static/index.html` coordinate a same-origin,
  frame-validated bridge, lock manual edits during a turn, heartbeat admission,
  drain cancellation before transitions, and reconcile the saved document before
  unlocking. Unknown or committed outcomes never claim that nothing changed.

The development host is `tools/run_packaging_sage_pilot.py`. It uses isolated
engineering data and an explicitly selected existing ChatGPT account. It does
not load the desktop environment file or enable API billing fallback. Native
CAD material-mass extraction, live carrier verification, dedicated packaging permission names
and release hardening remain separate gates.

Authenticated malformed editor transitions also revoke prior admission, including
invalid JSON and oversized bodies. HTTP schema rejection must not leave an old
selection authorized. Desktop observation is conservative: a mounted packaging
workspace, active turn or reconciliation blocks destructive native transitions
until the user leaves that workspace. No packaging crash-recovery format is claimed.

## Adapter Surface

`create_packaging_gateway(service, current_context=..., turn_id=...,
mutation_guard=None, max_calls=8, timeout=120, status_sink=None)` returns a
`PackagingGateway` with the existing gateway interface: `specs`, `call`,
`check`, `closed`, `receipts`, and `server_instructions`. `binding` returns an
independent copy; `binding_key` identifies the admitted turn. No runtime,
reasoning loop, shell, credentials, HTTP client, or model selection is added.
The existing host `credential_check` callback hook is also rechecked on admission;
it carries no keys and does not replace the refreshed context callback.

| Tool | Input and behavior |
| --- | --- |
| `packaging_resources` | Saved revision and resource `sources`, `catalog`, `alternatives` or `report`. Bounded source/alternative pages; cited density/carton presets; revision-specific PDF link. Read-only, no credential or filesystem access. |
| `estimate_packaging_mass` | Saved revision, authorized source ID/revision, documented density and exclusions. Returns an unsaved Product estimate based on closed-solid STEP volume; edit/validate are separate. |
| `inspect_packaging` | Required `expected_revision`; `package_offset` 0-10 and `package_limit` 1-2. Returns product, constraints, package page, saved history availability, source references, and assessment summary. |
| `validate_packaging` | Required `expected_revision`; optional complete `design`, findings offset and limit (1-50). Checks source provenance and assesses envelopes without saving. `saved` distinguishes the assessed saved design from a proposed design. |
| `propose_packaging` | `PackingRequest` plus `limit` 1-3: saved revision, 1-6 cartons, 1-6 maximum packages. Calls existing `packing.propose`, then assesses returned designs. No persistence or rates. |
| `edit_packaging` | `Edit`: expected revision, unique request ID, and complete replacement design. Read all saved package pages before replacement. Saves through `PackagingService.change`. |
| `undo_packaging` / `redo_packaging` | `RevisionCommand`: expected revision and unique request ID. Uses service history, including human edits, not just this turn's edits. |

The last three tools are advertised and callable only when the admitted
principal permits `layout.edit`, the host grants `direct_edit_authorized=True`,
and a host mutation lease is provided. All tools require `layout.read`, matching
the current packaging API's role vocabulary. There is no tool to grant itself
permission. Read-only turns can validate proposed designs and calculate
arrangements, but cannot save them. Undo is a write and uses the same gate.

Inputs and outputs are closed Pydantic models with generated JSON schemas.
Input parsing is strict JSON (no string/boolean numeric coercion, tuple coercion,
non-finite values, extra properties, paths, scope overrides, or document selectors).
The domain `models.py` remains the source of design constraints: SI dimensions,
six orthogonal orientations (0-5), 48 requested items, cartons, pads, top-open pockets, surface graphics,
and mass/material evidence. The adapter additionally bounds total placed items
to 48, revisions to JavaScript-safe nonnegative integers, argument depth to 20,
argument nodes to 10,000, arguments to 24 KiB, and results to 64 KiB. Full designs
that exceed the argument cap must be edited in the application, not split into
partial replacements. Existing documents/history outside the adapter's bounds
can fail admission or require application recovery after Undo; do not promise
that every service-valid historical document is editable by Sage.

Up to 24 calls and 240 seconds can be configured; defaults are 8 and 120.
Denied and malformed calls consume budget. Calls are serialized. Proposal search
uses the existing solver's cooperative deadline, at most 10 seconds or the turn's
remaining time. A single synchronous solver step or database operation can outlast
the deadline; it is joined rather than abandoned. This is not process preemption.

Manual dimensions have no source reference. Imported GLB/STEP sources are selected using
`product.source_id` and the exact imported hash in `product.source_revision`.
`PackagingService.source` is resolved only within the admitted scope, and its
dimensions/revision must match. Returned `source_refs` contain only
`{kind: "imported_glb" | "imported_step", source_id, source_revision}`. Source bytes, metadata
extensions, storage roots, database paths, and private source paths are not
returned. Admission/source validation reads metadata without loading model bytes.
No imported source claims verified material mass. STEP density calculations remain estimates;
GLB/manual envelopes cannot be used as trusted solid volume.

Proposals replace existing packages, including pads and allowance evidence. The
result explicitly warns about this; it is not a protective-packaging design or
transport certification. Selecting a candidate is not an approval or a save.
Saving it requires a separate authorized `edit_packaging` call and current
revision. There are no create/import/purchase tools. Resource discovery is scope-bound,
and report links are generated for the admitted document revision only.

Quote tools exist only when the host passes its `QuoteDesk` (the same object the Rates panel
routes use) to the turn. `packaging_quote_scenarios` and `compare_packaging` read scenario
labels and saved quotes; `quote_packaging` also needs `packaging.quote` and a scenario the user
authorized in the Rates panel for this document. Sage passes a scenario ID, never an address;
results show city, state and residential status only. Each provider request is reserved from
the scenario's shipment budget first, recorded in the attempt audit and in the turn receipt as
an `external` request, and is not reversible by Undo.

Research tools exist when the host enables public research (`INSPECTORPRO_CODEX_WEB_RESEARCH`,
default on, as for Documentation) and the principal has `packaging.edit`. They reuse
`research_tools.PublicResearchSession`: generic public queries only (the gateway also refuses
packaging IDs and the design or product name), a source must be read before it is relied on,
and at most four provider requests are made per turn. `record_packaging_evidence` stores facts
from a page read in the same turn as unreviewed evidence for the document; the app attaches the
source link, title and retrieval time from the research receipt. Evidence is reviewed by the
user in the Validation panel and never edits the design, passes validation or approves
anything. Research requests are recorded as `external` requests in the turn receipts.

## Required Host Admission

`PackagingContext` is a frozen dataclass populated by the authenticated host:

- `principal`: the current server-resolved `FacilityPrincipal` (shared identity
  type only, **not** a facility document binding).
- `session_id`, `conversation_id`, `selection_id`, `document_id`, `revision`:
  stable admitted identities plus the editor's saved revision.
- `active_mode`: must be exactly `packaging_shipping`.
- `dirty=False`, `conflict=False`, `pending_operations=0`: affirmative saved
  editor state, including unflushed forms, drag operations, pending saves, and
  pending proposal application.
- `direct_edit_authorized=False` by default: an explicit server decision tied
  to this turn and the user's requested action, never an LLM argument or a raw
  renderer capability flag.

`current_context()` must obtain a fresh, thread-safe host snapshot every time,
including role/admission revocation and disconnect. Returning the original HTTP
request's normalized dictionary forever does not meet this contract. Missing or
ambiguous admission must raise. Principal, scope, session, conversation, active
mode, document, selection generation, and edit grant are pinned for the turn.
`selection_id` must change on every document/workspace transition, even an
away-and-back transition to the same document. Any mismatch closes the gateway.

Scope is exactly:

```python
digest({"tenant": principal.tenant_id,
        "sites": sorted(principal.allowed_site_ids),
        "workflow": "packaging_shipping"})
```

Every read checks the current saved service revision before and after work. Every
mutation also uses the service's transactional expected-revision check. Only the
gateway's own committed revisions advance its saved-revision cursor. The editor
may temporarily report an earlier gateway-owned revision while it reloads; once
it acknowledges a newer revision, reverting to an older one fails. An external
service revision advance invalidates the turn, even if the editor reports it.

For direct edits, `mutation_guard()` must return a **bounded synchronous context
manager** that holds a host-owned selection/admission lease. Use the same lease
when publishing selection, workspace, role/grant, session, dirty/conflict/pending,
and admission changes. The adapter holds it across the last refreshed context
check and the service transaction. A fresh callback alone cannot eliminate the
check-to-commit race. The service revision CAS separately arbitrates concurrent
database writers. Do not supply `nullcontext` as a production write lease.

The renderer must coordinate transitions with this host state: cancel and drain
the active turn before switching/editing, or wait for the host lease/admission
transition acknowledgement before exposing the transition. An unacknowledged,
delayed browser event cannot provide active-document-switch protection. The
implemented bridge and admission manager provide this coordination. Invalidate admission on frame unload,
disconnect, expired session, and turn cancellation.

## Receipts And Cancellation

Successful saves return service request/action/before/after revision receipts,
with `outcome="committed"`. Same-turn exact request retries at the same resulting
revision return `replayed=True` without another mutation. A reused ID with changed
content is refused. Retries after intervening edits are stale, not new writes.
The service also retains its durable request receipts; the host must not generate
a new request ID merely because the response was lost.

Each admitted call records a bounded host receipt with argument/binding hashes,
duration, success/error code, and any mutation outcome. No arguments or raw
exception details are logged there. Failures use `{ok: false, error: {code,
message}, mutation?: ...}`; messages are allowlisted, not exception strings.

Cancellation before the transaction prevents the write. Once synchronous
`service.change` has been entered, cancellation cannot guarantee rollback.
The gateway closes and joins the worker under repeated asyncio/AnyIO cancellation,
retaining `committed` evidence when available. A lost service response is
`outcome="unknown"`, not "nothing changed". Timeout errors carry the same evidence.
Cancellation still propagates `CancelledError`; the host must persist/read
`gateway.receipts` on interruption and failure as well as success, refresh the
authorized document, and reconcile unknown outcomes against service receipts.
Await all active gateway calls before releasing the host. Do not apply a blind
compensating Undo: it could undo a different editor's subsequent work.

## Original Integration Checklist

Locations below were inspected in this isolated worktree on 2026-11-05. Other
owners are actively editing these files; use the named symbols as anchors.
This checklist describes the original adapter handoff. Its admission, runtime,
streaming and refresh changes are now implemented as summarized above. The
historical line numbers and descriptions below identify the inspected baseline;
use symbols rather than those line numbers when reviewing the current code.

1. **Use the existing service instance and add live admission.**
   `server.py:1673`, the `INSPECTORPRO_PACKAGING_ENABLED` block, now conditionally
   mounts `_PACKAGING_SERVICE` with `_FACILITY_PRINCIPAL_RESOLVER`. Reuse that
   instance and resolver; do not open a second database or bind through
   `_FACILITY_LAYOUT_HOST`'s selected layout. Add the host snapshot and shared
   lease described above. `packaging_shipping/api.py:create_router` is the
   authoritative existing scope calculation, not a model-selected scope.

2. **Publish an explicit packaging attachment and lifecycle.**
   `static/packaging.js:DraftDocument`, `hasDraft`, `working`, `loadDocument`,
   `newDocument`, `saveDocument`, `historyAction`, and `reloadDocument` own the
   saved document, pending work, draft/form state, and refresh path. The pilot is
   embedded by `static/index.html`'s `trainingState.type === 'packaging_shipping'`
   branch (around line 49797). Add a same-origin, source-frame-validated bounded
   parent/frame exchange or equivalent host bridge for document ID, saved
   revision, selection generation, and cleanliness. Treat it as context evidence,
   not principal or edit authority. Attach it in `buildAgentAttachments` /
   `buildInspectionContext` (around line 83672); `buildModeContract` already
   derives the training workflow mode. Extend `server.py:normalize_agent_context`
   (around line 27662) with packaging fields and an admitted resolver. Reject
   legacy flat overrides rather than accepting renderer-supplied designs or
   substituting `facility_layout_ref`.

3. **Route only admitted Sage packaging turns through the existing runtime.**
   Add an explicit packaging branch in `server.py:agent_chat` (around line
   41440), before `_agent_chat_impl`. Recognize internal agent key
   `deviation-analyst` and exact mode `packaging_shipping`. Extend
   `_require_subscription_chat_route` and the Codex predicates in
   `agent_chat_v2_stream`, `agent_chat_endpoint` (stream required),
   `_memory_model_metadata`, and `agent_chat_streaming_status`. Do not fall through
   to the legacy provider on a rejected packaging turn. An authenticated but
   missing/stale packaging attachment must fail before inference.

4. **Supply this gateway to the existing AppServer turn, not another model loop.**
   `ai_inspector/codex_runtime/documentation_pilot.py:inspect_documentation`
   (line 203) contains the reusable host lifecycle: settings/paid-access gates,
   credential checks, `Journal`, `serve_gateway`, child environment, runtime
   configuration, `AppServer.inspect`, cancellation, and terminal receipts.
   It currently hardcodes `DocumentationGateway`/`PartGateway` and assembly/part
   bindings; it cannot accept this adapter unchanged. Extract or inject gateway,
   binding, instructions, and terminal-result handling in that existing lifecycle.
   Do not reuse `documentation_binding`, `part_binding`, or
   `pilot.py:saved_layout_reference` as packaging admission. Include the
   admitted packaging binding, tool inventory, model/account, and protocol in
   the existing journal/thread binding. Supply the safe initial document reference
   and revision to the turn so its first required `expected_revision` is known.
   Recheck admission on journal replay and finalization. Interrupted/unknown-write
   turns require reconciliation, not an automatic fresh edit retry.

5. **Reuse the current bridge and restrictive runtime policy.**
   `mcp_bridge.py:make_application` / `serve_gateway` already consume `specs`,
   `call`, `closed`, and `server_instructions`; no alternate MCP server is needed.
   `policy.py:runtime_config` defaults to facility tools: override
   `config['mcp_servers']['inspectorpro']['enabled_tools']` with precisely
   `gateway.specs`, as `inspect_documentation` already does. Keep all existing
   native-tool/network/shell/credential restrictions and paid-inference gates.
   Do not install packaging tools into the facility or documentation inventories.

6. **Wire the existing streaming UI and document refresh.**
   `static/index.html:handleAgentSend` (around line 94242) currently returns early
   with "Packaging chat execution is not enabled". Keep that guard until the
   admission path exists. `_requestAgentChatStream` (around line 93908) currently
   recognizes only facility/documentation/assembly/part Codex turns; add packaging
   using the new streaming-status capability, without paid API fallback.
   Send successful mutation document/revision/receipts in the authoritative final
   response and reload only the still-selected, clean matching packaging document.
   Keep source refs as IDs resolved by authorized application endpoints. Render
   proposals without applying them. `codex_packaging` is the adapter's status
   phase; provide a corresponding status label. Update failure/cancellation UI
   handling so existing "No engineering changes were made" messages are never
   used for committed or unknown packaging mutations.

No new `AGENT_TOOL_SPECS` entries, skill-router workflow, mode-reasoning loop,
provider configuration, or dependency installation is needed for this explicit
Codex/MCP route. The missing work is host admission/lifecycle wiring and UI
refresh/error handling. Existing `TurnProgress` can be reused, but this adapter
currently emits status and receipts only, not progress-step events.

## Verification

From the isolated worktree:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_codex_packaging_tools.py -q -p no:cacheprovider
```

78 tests passed at the last recorded run. Tests use actual `PackagingService`,
disposable SQLite storage, real `py3dbp`, and a generated GLB passed through the
real importer. Network connection creation and quote persistence are forbidden
in the adapter fixture. Coverage includes closed/strict schemas, 48 placements,
all orientations and pads, scoped sources, immutable admission, draft/selection
switches, revision CAS, exact replay, Undo/Redo, budgets, pagination, host leases,
and cancellation/timeout before and after transaction entry.

### Offline MCP Transport Acceptance

Measured on 2026-11-05 in the isolated `packaging-shipping` worktree:

| Run | Result |
| --- | --- |
| `tests/test_codex_packaging_mcp.py` | **23 passed in 9.84s**, no skips |
| MCP acceptance plus `tests/test_codex_packaging_tools.py` | **101 passed in 19.38s**, no skips |

The new transport suite runs 15 in-process ASGI cases through the existing
`mcp_bridge.make_application` and 8 real loopback HTTP cases through the existing
`mcp_bridge.serve_gateway`. Both use real `PackagingGateway`, `PackagingService`,
disposable SQLite databases, and `py3dbp`; neither substitutes tool dispatch,
domain results, or a model response. The test client performs the MCP
`initialize` / `notifications/initialized` handshake with protocol `2025-11-25`,
then sends actual JSON-RPC HTTP requests, not direct `gateway.call` invocations.

Verified over both transports:

- Discover exactly the admitted packaging tools and their read/write annotations;
  validate advertised input/output schemas and every structured tool result with
  `Draft202012Validator`. Text content must decode to the same structured result,
  and MCP `isError` must match the gateway envelope.
- Inspect, propose without persistence, edit a real solver candidate, replay the
  exact request without another write, validate the saved revision, Undo, and
  Redo. Verify the resulting database designs, monotonic revisions, and durable
  edit/Undo/Redo receipts. Quotes remain empty.
- Reject stale selection generations, active-document switches, principal-role
  changes, dirty state, and external service revisions before writing. The first
  failure carries a structured error and `not_started` mutation outcome; further
  requests receive HTTP 403 after the gateway closes.
- Read-only discovery excludes writes, and an attempted unadvertised edit fails.
  Unknown fields, a raw source path, a float revision, and a stale expected
  revision produce structured errors without mutation.

The ASGI cases additionally verify missing/wrong capability tokens, Origin,
Host, non-loopback client scope, wrong path, and a closed gateway are rejected
before gateway calls or database changes. Every loopback case checks that the
listener has released its port after teardown by rebinding without
`SO_REUSEADDR`.

The safety fixture refuses process launches and non-loopback HTTP/DNS/socket
attempts, disables paid-inference flags, and makes quote persistence fail.
HTTP clients use `trust_env=False`; the only live network destination is a
temporary `127.0.0.1` listener inside the test process. On Windows, the fixture
returns the actual Windows OS family for `platform.system()` to avoid Python's
optional `cmd /c ver` probe during Uvicorn startup. The bridge is unchanged.

An initial run reused the existing local dependency installation read-only.
The final run used the isolated `.venv` after installing InspectorPro's pinned
MCP 2.3.0 and jsonschema 4.26.0 there. No main-checkout dependencies were changed.
Measured final versions: Python 3.14.0, MCP 2.3.0, jsonschema 4.26.0, Pydantic 2.12.4,
Uvicorn 0.38.0, HTTPX 0.28.1, AnyIO 4.12.0, py3dbp 1.1.2.
Missing dependencies deliberately fail this suite instead of silently skipping.

Reproduce from this worktree, without a PYTHONPATH override:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_codex_packaging_mcp.py tests/test_codex_packaging_tools.py -q -p no:cacheprovider --basetemp=.runtime/packaging-mcp-NEW
```

**This transport run did not use live Sage.** It proves the local MCP transport
contract, not end-to-end chat or carrier prices. The subsequent host integration
uses explicit development flags; no regular desktop build has been promoted.

## Live Chat Acceptance

`tests/verify_packaging_sage_chat.py --live --headed` passed against the isolated
full host on port 8180 with memory enforcement and ChatGPT-plan authentication.
It used the actual Sage pane, AppServer, MCP gateway, solver and saved-document
service. No model response or geometry operation was substituted.

The model inspected an imported CAD-derived GLB, proposed six placements,
validated the proposal, saved it, then validated saved revision 1. Three invalid
argument calls were rejected before it corrected them; five calls succeeded.
`checkedPackaging` requires saved validation at the final revision, not merely a
proposal or older validation. Unknown masses and handling status stayed unknown.
The geometric fit passed, but the package remained unready for quotes until the
missing inputs are supplied. No protection certification was claimed.

The renderer refreshed to six meshes, unlocked editing, and manual Undo/Redo
worked. Canvas checks and screenshots were inspected; there were no page errors.
Source/product, constraints, quantity, name and carton were independently compared
against the original stored design. Native CAD mass/dimension verification is
still outstanding. Evidence stays local in `.runtime/packaging-sage-browser-02/`.

Related automated checks: 509 Python tests and 39 JavaScript tests passed. The
eight memory-host tests use real admission, SQLite and MCP with only inference
scripted; the separate browser run above used the real model. See
`packaging-shipping-status.md` for release gaps and unrelated baseline fixture drift.
