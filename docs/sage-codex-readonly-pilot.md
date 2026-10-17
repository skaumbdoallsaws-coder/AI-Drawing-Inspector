# Sage Codex Migration: Audit and Read-Only Pilot

## Current Status: 2026-10-15

The Facility Layout path supports revision-bound engineering reads and
approved authoring previews. Codex owns one
tool-selection loop through the existing Sage route and common gateway; no
per-workflow loop or new UI route was added. This is bounded facility inspection
and assisted editing, **not a general CAD/assembly migration**. It was promoted
to the regular local desktop profile after the acceptance below; this is not a
claim of general product-release certification. The 2026-10-14 audit below is
retained as historical evidence; its
five-tool inventory and "no write adapter yet" statements describe that batch,
not the current implementation.

### Public Research Through Sage

The current inventory includes 18 read tools, plus lettering preparation and the
two approval-only preview tools. `search_public_sources` discovers public sources;
`read_public_source` accepts a research ID and source index from the same turn,
not an arbitrary URL. Both use the existing revision-bound MCP gateway. No second
facility-planning loop, browser extraction bridge or geometry implementation was
introduced. The existing generation research workflow remains unchanged.

The default provider is OpenAI hosted web search, using the existing dedicated
Codex credential and configured verified model. The adapter implements the same
bounded provenance contract as `ai_inspector/research/web.py` and reuses its URL
and domain validation and the existing research source-card renderer. The
provider request uses live access, returned web-call sources, required tool use,
three hosted calls maximum, a 3,000-token output limit, `store: false`, a fixed
API endpoint, no proxy/cookie inheritance, no redirects and no automatic retries.
See [OpenAI web-search documentation](https://developers.openai.com/api/docs/guides/tools-web-search)
and [Responses API limits](https://developers.openai.com/api/reference/resources/responses/methods/create).

Controls:

- `INSPECTORPRO_CODEX_WEB_RESEARCH=0` disables new public research and cached
  research-tool reads. The default is enabled, subject to the existing paid-
  inference gate. No standalone credentials are needed for the OpenAI default.
- `INSPECTORPRO_CODEX_RESEARCH_PROVIDER=anthropic` explicitly selects the existing
  research reader and its gateway configuration/credential. There is no silent
  provider fallback or credential migration.
- Four research requests maximum per turn share the overall tool/time budget.
  Identical successful requests reuse a turn-local receipt. Quota/authentication
  failure stops further provider requests in that turn. HTTP operations time out;
  cancellation joins an already-running bounded request and discards late results.
- Authorization and saved revision are checked before and after research. Provider
  configuration changes and application-policy revocation invalidate in-flight
  results. No research call writes the layout or grants editing approval.

Only explicit public query terms and a selected public URL go to the researcher;
the adapter does not forward conversations, geometry, files or browser sessions.
Obvious local paths, credentials, email addresses, URLs and document IDs are
rejected in query text. This is not a general DLP guarantee: public-only wording
and natural-language user restrictions also depend on the agent instructions.
Disable the application flag where public egress is prohibited.

Source provenance must come from provider tool-call metadata. Model-only URLs do
not qualify. A selected-page read requires a completed open-page action for the
exact URL and a complete response citing it. This is provider-reported retrieval,
not an independently archived or byte-verified original. Sources and summaries
remain supporting, unreviewed and ineligible for production approval. Missing,
conflicting, paywalled and incomplete evidence must remain explicit. Current
edition, jurisdiction, model variant and applicability still need review.

Source cards are generated from these receipts, not model-authored cards, and
travel through the existing chat/SSE path. They retain retrieval status and source
links without inventing publishers. The normal result journal retains the research
receipts; telemetry records provider usage/timing, not queries or source contents.
Provider-reported token usage does not by itself account for hosted web-tool fees.

These changes load on desktop restart. After the user restored credits, the
bounded live research check passed using the existing vault credential and
`gpt-5.5`. One real Sage chat/SSE turn completed in 34.107 seconds: Codex inspected
a disposable copy of the saved gym, searched the U.S. Access Board site, read a
returned parking-guidance page, and provided a cited answer. All three MCP calls
succeeded; two research receipts supplied eight source cards in the final chat
payload. The answer distinguished accessible pedestrian access aisles from
vehicle maneuvering aisles without claiming layout compliance.

Evidence: `.runtime/codex-public-research-live-01/live-evidence.json`, generated
by `tools/check_codex_sage_live.py --live --research-check` with the existing
credential profile. The original gym hash and copied revision were unchanged,
with zero engineering changes. Runtime shutdown completed without owned orphan
processes. This verifies the live backend/provider/chat-stream path, not native
source-card clicks or the separate authoring workflow. No running user app was
restarted. Local provider tests below use synthetic HTTP responses; the live
receipt remains provider-reported retrieval, not an independently archived page.

Local verification: 130 Python tests passed across public research, read-only
pilot, assisted tools, Sage HTTP/SSE routing, generation exploration and research
presentation (`.runtime/pytest-codex-public-research-02`). JavaScript checks also
passed: rich content (12), stream runtime (14) and Codex stream transport (34).
Coverage includes provider request bounds, source provenance, complete cited
reads, query rejection, quota/authentication errors, per-turn budgets/caching,
policy revocation, stale revisions, cancellation, journal replay and source cards.

### Functional Design Guidance and Parking Review

Sage's editing instructions now treat a requested area as a functional design
goal: reserve circulation, entrances, working sides, service access and usable
capacity before arranging objects. This guidance also covers rooms and workcells;
it is not a general-purpose engineering certification engine.

That step brought the read inventory to 16 tools, including `review_facility_parking`. This
revision-bound, authorized read checks explicit parking-box footprints, bay count,
zone containment, authored aisle geometry, bay adjacency and boundary connection
evidence. Loose lines, labels, arrows and vehicle counts do not prove usable bays
or aisles. Requested capacity is per selected zone. Missing geometry dependencies
and bounded-scope limits return `not_checked`, never a passing result.

Changed parking zones are also reviewed automatically during operation previews,
with findings under `alternative.validation.functionalDesign`. Findings are
advisory so users can approve incremental drafts; they do not silently approve
or block edits. Sage must resolve findings or describe the result as an unfinished
draft. Existing authorization, revision checks, approval and Undo remain intact.
Cosmetic-only changes do not trigger a parking review. No user layout is modified
by the review itself.

This checks represented topology, not swept vehicle paths, obstacle-free widths,
external road access, accessibility or local-code compliance. Those limitations
remain explicit even when all represented bays touch an aisle. General design
guidance cannot guarantee that an agent will infer every supporting requirement.

Model training supplies general design knowledge; current standards and
project-specific facts require evidence. The public-research integration above
supersedes this step's earlier research limitation. The regular desktop loads
source changes on restart. Public-research live acceptance has now passed as
recorded above. A live parking-design/editing acceptance remains outstanding;
the read-only research check does not validate that workflow.

Local verification: 87 tests passed across `test_facility_parking_review.py`,
`test_codex_readonly_pilot.py`, `test_codex_assisted_tools.py` and
`test_facility_operation_proposals.py`. Coverage includes missing/isolated aisles,
bay/aisle overlap, rotated footprints, elevation separation, cosmetic changes,
stale reads, closed tool schemas, real operation preview, explicit approval,
commit and receipt-Undo. These tests do not claim live-model acceptance.

### Authoring Expansion (Local Checks Passed; Live Acceptance Quota-Blocked)

The initial seven-operation MCP schema was narrower than the existing editing
engine. It also reused persisted-document schemas for adds, incorrectly requiring
server-generated IDs. The expanded contracts distinguish add inputs from saved
records and expose existing deterministic authoring operations, with explicit
schemas rather than arbitrary document patches or Python execution.

New inspection includes authorized library search and fit analysis, exact saved
zone/floor/wall/artwork records, exact asset geometry and real GLB material slots.
The context reports its current operation inventory. Schema failures return
bounded field diagnostics so the agent can correct a rejected request.

Targeted floor, interior-wall and decal updates preserve unrelated records.
Perimeter paint and legacy artwork updates preserve the existing wall composition.
Transparent lettering is rendered into the site's controlled image store before
a separate layout preview; no arbitrary filesystem or network image import is
available. Newly referenced artwork must be imported through that controlled store
or already belong to the current layout. Outdoor finishes follow the actual
flat ground support, including extensions outside the original plan rectangle.

Editing sessions are bounded to 24 calls/240 seconds; read-only mode remains
8 calls/120 seconds. Each preview remains at most 50 operations/24,000 bytes.
Approval and commit remain UI actions, never MCP tools. Saved identity, revision,
validation, dependency, receipt and Undo protections are retained.

This does not grant unrestricted OS access, CAD import/conversion, cross-document
editing, safety certification, or autonomous approval. New blank sheets and new
local source-file intake still use their existing app controls. Navigation writer
authority must not be impersonated as a manual Plan-pointer action.

That expansion's inventory was 15 read tools, transparent-lettering preparation, and
two preview tools exposing 49 closed operation variants. Component finishes
require real discovered material keys and a SHA256 proof of the catalog GLB;
the exact bytes are rechecked before preview and commit. New/replaced equipment
must be saved and inspected before applying component finishes.

Verification of this expansion:

- Integrated Python suite: 178 passed; focused component inventory/proposal
  checks: 17 and 15 passed; frontend authoring/context/stream/preview suite: 112 passed.
- Real saved-gym gateway, explicit test approval, commit and receipt-Undo passed
  for outdoor floors, component finishes and cell groups. Evidence:
  `.runtime/codex-authoring-outdoor-01/authoring-evidence.json`,
  `.runtime/codex-authoring-material-proof-01/authoring-evidence.json`, and
  `.runtime/codex-authoring-cell-group-01/authoring-evidence.json`.
- Live native attempt `.runtime/codex-authoring-native-01` reached a successful
  `preview_facility_operations` after correcting two schema rejections. The
  provider then returned `Quota exceeded. Check your plan and billing details.`
  before a final agent response. This run is **failed, not accepted evidence**
  for native approval, 3D rendering or Undo. No layout writes occurred; shutdown
  was unforced with no runtime orphans. A fresh native authoring acceptance is
  still required; the later successful research check does not validate editing.
- That attempt verified unchanged application-code SHA256
  `23b4660022940716ef492531d254ce3a5c1f07cf5aa74ea320ca23c08c53fdae`
  and dependency bundle before/after. These source changes load through the
  regular desktop checkout; the existing profile and vault remain unchanged.
- Current user-gym source SHA256 was preserved:
  `f402f0a6ed28901397b833851d080e0025ad27ee3e5729d1f2dd017c59aeab82`.
  It includes the user's edits since the original integration acceptance below.

### Original Integration Acceptance

The evidence in this section describes the earlier, narrower integration build,
not a new acceptance claim for the authoring expansion above.

All five final native checks used the same verified application-code SHA256
`d4e4aea6a29c6c2a71867b0ef887f3985669805cabc0016085f914b5d23de932`.
Their `application-code-evidence.json` files confirm unchanged code and bundle
before/after each run. Reports are under `.runtime/<run>/codex-desktop-acceptance.json`.

| Run | Result | Elapsed seconds |
| --- | --- | ---: |
| `codex-load-final-03` | Passed; 3 logical CPUs, 2 qualified load workers | 113.242 |
| `codex-desktop-edit-final-03` | Passed; real UI Approve and approved Undo restore the copy | 165.121 |
| `codex-editor-change-final-03` | Passed; draft mutation cancels the active request | 69.667 |
| `codex-recovery-final-03` | Passed; cancellation, runtime failure, restart and thread resumption | 174.129 |
| `codex-memory-final-03` | Passed; memory reload and document switching | 111.991 |

Every accepted shutdown was unforced, with resource closure and no owned runtime
orphans. Loaded startup reached ready in 26.735 seconds without changing the
120-second startup deadline. Dependency verification now avoids redundant parent
checks, while retaining full-byte hashes and link/junction rejection. Repository
reads cache only successful validation by exact raw-byte hash; authorization,
disk reads, registry/revision checks and detached results remain per-read.

Regression runs passed: 242 backend checks, 65 launcher/reliability checks,
49 package checks, 52 activation checks, 45 startup-failure JS checks, and the
focused frontend/inline-script checks. These are suite results, not a sum of
distinct tests. Failed earlier runs remain retained and are not accepted evidence.

The regular application profile was activated with edit previews enabled and a
profile-specific Windows vault credential. Activation record:
`../.runtime/codex-desktop-activation-20261015-01/codex-profile-activation.json`,
SHA256 `5b65d9ac7596dfb5e5b2481aaadcd05061f89a2eb6e811f8442da956422c70ff`.
Only `codexRuntime` was added; startup remains Private Gym, with the existing
shortcut, application checkout, gateway configuration and user stores preserved.
The saved gym SHA256 remains
`492b44b61f576ea0ba87589f02b3f7db2e8c07b67feede36793666c376dd9ac6`.

Post-activation normal-shortcut verification also passed, recorded separately in
`.runtime/codex-desktop-normal-smoke-20261015.json`. Private Gym loaded, the first
real UI request returned 29 zones/282 placements and cardio dimensions, and a
follow-up after F5 resumed the same Codex thread (`thread/resume:done`). Both
journaled requests completed with zero engineering changes. The existing separate
server-conversation-memory setting remains off; browser chat restoration and
Codex thread resumption were verified in that actual configuration. The native
memory/recovery gates above additionally exercised enforced server memory.

### Integrated Inventory And Authority

- `FacilityReadGateway`: `inspect_facility_context`, `inspect_facility_entities`,
  `inspect_facility_semantics`, `inspect_facility_findings`,
  `analyze_facility_spatial`, `observe_navigation_context`,
  `inspect_saved_process_bindings`, `search_industrial_assets`,
  `inspect_facility_region`, `analyze_facility_fit`, `inspect_pattern_provenance`,
  `inspect_cell_layout_provenance`, `inspect_facility_authoring`,
  `inspect_facility_asset`, and `inspect_facility_components`.
- `FacilityEditGateway` inherits those reads and adds
  `preview_facility_operations`, `preview_facility_undo`, and
  `prepare_facility_lettering`. The last prepares an image artifact only;
  approval, apply/commit and Save are not MCP tools.
- All tools share a bounded session budget, lock and receipts: 24 calls / 240
  seconds with editing enabled, 8 calls / 120 seconds in read-only mode.
  Saved-layout authorization/revision checks remain backend-owned. Admission
  uses the existing principal/session/conversation and active Facility Layout
  context; dirty, conflicted and pending-preview input is rejected. Fresh editor
  revocation belongs to the UI/request lifecycle, not to model-supplied fields.
- The thread/journal binding includes tenant/principal, roles/site scope,
  session/conversation, workspace, saved revision, model, `protocol: 2`, exact
  combined inventory hash and edit-preview mode. MCP publishes each supplied
  spec's output schema, including the additional reads' closed success/error
  envelopes; older specs retain the shared envelope. Runtime tool discovery must
  match the enabled inventory exactly.

Navigation returns **authored** actors, anchors, movement programs and handoffs,
not certified clearance, solved routes or safety/compliance evidence. Saved
process bindings are references recorded in the layout; the adapter does not
open or inspect the external Process Maps or establish their current revisions.
See [additional workflows](codex-additional-workflows.md) for exact helper APIs,
bounds, ownership and verified live evidence.

### Exact Preview, Apply And Undo

1. With `INSPECTORPRO_CODEX_EDIT_PREVIEWS=1`, Codex can submit a closed batch to
   `preview_facility_operations`. The current exact operation inventory is
   generated by `codex_runtime.edit_schemas.operation_batch_schema` and exposed
   through `inspect_facility_context`; do not infer it from older chat history.
   It includes placement/appearance, zones, markings, aisles/routes, utilities,
   process bindings, plan/ground, wall/surface/decal authoring and targeted
   collection edits, with at most 50 operations. It is not arbitrary document
   mutation or shell access.
2. `assisted_tools.FacilityEditGateway` calls
   `facility_layout.operation_proposals.create` over the existing service,
   operations, dependency/spatial/routing checks and transaction kernel. It
   prepares an exact diff/ghost preview, binds tenant/site/layout/base revision,
   diff hash and dependency fingerprint, and persists a proposal record without
   saving the layout. A rejected batch must be corrected and revalidated; no new
   geometry engine or mock result is substituted. Results identify `saved: false`
   and `approvalRequired: true`.
3. A successful proposal returns only the server reference
   `{siteId, layoutId, revision, proposalId}` through
   `present_codex_facility_preview`, in `facility_action_mode: PREVIEW`.
   The editor fetches `/api/facility-layouts/{site}/{layout}/proposals/{proposal}/preview`
   and checks the current document/revision, editor generation and clean state
   before and after the fetch. Model-supplied geometry is not installed directly.
4. Explicit user approval uses the existing `/approvals` endpoint with the exact
   transaction binding, editor session, idempotency key and
   `explicitApproval: true`. `/apply` consumes the approval token and binding via
   `FacilityLayoutService.apply_layout_proposal`. Backend regeneration/revalidation,
   authority checks and transaction idempotency remain authoritative; a successful
   commit returns its persisted revision and receipt. Chat text is not approval.
5. Undo is a second approved transaction, not an in-memory inverse or silent
   rollback. `preview_facility_undo(receiptId)` and the editor's
   `/operation-undo-preview` path both use the authorized commit receipt while
   its resulting revision is still current. `operation_proposals.prepare_undo`
   reconstructs the receipt's prior saved revision, retains current document
   timestamps, and rechecks restored asset authority, dependencies, spatial and
   routing constraints. The resulting `exact-undo-v1` preview requires another
   explicit approval/apply and yields another receipt. Intervening saves reject
   undo; the editor additionally binds its Undo control to the last approved
   operation commit and current editor generation.

### Optional Package And Secure Vault

The deployment implementation uses an optional, closed `codexRuntime` object in
the existing desktop application profile. Its fields are `schemaVersion`, `model`,
`editPreviews`, `allowPaidInference`, `dependencyRoot`, `binary`, `packageSha256`,
`pilotRoot` and `credentialTarget`. Absence disables this route;
`editPreviews: false` retains read-only mode. Paid inference requires
explicit opt-in.

Normal deployment keeps the existing checkout, shortcut, user stores and generated
resources. The separate optional dependency bundle pins Codex CLI 0.162.1, MCP
2.3.0 and jsonschema 4.26.0, with a complete dependency manifest. Startup verifies
the profile-approved package hash, exact file inventory/hashes, versions, platform
and interpreter before loading dependencies or reading a credential; nothing is
downloaded at launch. Dependencies are appended with `site.addsitedir`, not
installed over the base environment.

Only the Python backend reads the current Windows user's profile-scoped
`InspectorPro/Codex/<profileId>` credential through the Windows Credential Manager
vault. Keys are not stored in profile JSON, sent to the renderer or supplied in
command-line arguments. Inherited Codex settings are stripped; missing/invalid
vault data fails closed without a legacy-key or personal-login fallback.
Provisioning and installed-profile changes remain approval-gated. See
[desktop deployment](codex-desktop-deployment.md) for package verification,
test-credential isolation and profile-only rollback. Prepared packaging and vault
support are not evidence of native acceptance or authorization to promote.

### Earlier Verification Handoff (Superseded)

The pending/running statements below record earlier handoffs, not current status.
The accepted native release above supersedes them.

- Verified `.runtime/codex-workflows-live-01/live-evidence.json`: two successful
  GPT-5.5 backend turns, navigation in 14.980 seconds and saved process bindings
  in 12.226 seconds. Both used context plus the requested additional tool, returned
  `READ_ONLY` with zero UI calls/engineering changes, and preserved the source
  hash and copied saved revision. The second timeline records actual
  `thread/resume`. The gym's saved process bindings were truthfully reported as
  zero; this is not a live populated-map inspection.
- Main reports the live backend collision -> correction -> validated preview ->
  explicit approval/apply -> commit receipt -> approved receipt-bound undo chain
  passed, and **174 combined backend tests passed** at this handoff. This docs-only
  update did not rerun those tests or infer native success from them.
- Unit cancellation fixes in `FacilityReadGateway.call` and `AppServer.close`
  wrap cleanup joins in AnyIO `CancelScope(shield=True)` while retaining
  `asyncio.shield` and repeated direct `Task.cancel()` handling. Cancelled reads
  join their worker before releasing the lock and publish no result/receipt;
  App Server cleanup joins its process wait and child tasks. Four new regressions
  reproduced busy-spin before the fix; all nine focused cancellation/read-boundary
  tests passed afterward. Settings, budgets and timeouts were not increased.
  Joining a synchronous read is still not a hard CPU/IO execution kill.
- **Native editing acceptance remains pending.** At main's handoff,
  `.runtime/codex-desktop-edit-02` moved the intended object correctly but the
  driver used the wrong Undo selector; that run is not accepted as a full pass.
  `.runtime/codex-desktop-edit-03` was running. Main will append its final native
  evidence and any separately approved promotion record. Neither is claimed here.
- Historical native read-only memory/recovery passes and controlled-load failures
  remain evidence for their own scenarios only. Current editor-revocation/native
  acceptance is owned by main's lifecycle work, not established by the two-turn
  backend workflow run. No implementation/test files, installed profile or vault
  entries were changed in this documentation task.

### Earlier SSE Lifecycle Investigation

This update supersedes the earlier in-progress handoff above for lifecycle
verification only; it does not establish a controlled-load pass or promotion.

- `.runtime/codex-load-final-01` failed the unchanged three-CPU/two-worker load
  scenario. Its UI received no terminal event within 150 seconds, and backend
  shutdown required forced cleanup. The turn began at `1792046090.101`; the pilot
  journal recorded `codex_time_budget_exhausted` at `1792046253.865`, about 164
  seconds later, after shutdown had begun. This timing does not prove a timeout
  error was ready for delivery before the UI deadline. The runtime's recorded
  context read took 27.262 seconds; repeated layout checks and repository work
  were optimized separately by main and the domain owner.
- A separate, reproduced SSE defect left `_events` polling an empty queue forever
  when its producer had already been cancelled. The narrow `server.py` fix checks
  producer completion after the existing queue poll, drains queued events first,
  and emits a terminal cancellation only when no known failure exists.
- The stream now retains a failure before awaiting error publication. If that
  queue write is cancelled, the known error takes precedence over cancellation.
  A classified Codex HTTP error in the exception chain also survives teardown
  cancellation. Known `codex_time_budget_exhausted` failures remain a single
  `response_error` with `retryable: false`, not a user-cancellation result. The
  stream does not read the pilot journal or infer a timeout from cancellation
  alone. Disconnected requests still join worker teardown; inference budgets,
  shutdown limits and forced-cleanup reporting were not relaxed.
- `tests/test_agent_chat_stream_terminal_lifecycle.py` covers cancellation before
  and after progress, ordinary timeout delivery after cleanup, cancellation while
  publishing a timeout into the full queue, and cleanup cancellation with a known
  timeout for both connected and disconnected clients. The first three cases plus
  existing streaming regressions passed independently: **21/21**. Main subsequently
  reports **242 combined Python tests passed**, including repository, SSE, HTTP,
  tool and route coverage, and **44 JS checks passed**, including four inline-script
  syntax checks. These focused checks are not native stress acceptance.
- Main added shared `clean_desktop_shutdown(receipt)` validation to both native
  harnesses. Acceptance now requires `forced === false`, exit code zero and the
  resource-closure checks; resource closure alone cannot turn a forced stop into
  a pass. Main's 65-test focused validation of this change was still running at
  this documentation update.
- Implementation is frozen for main's rerun of all five native scenarios against
  the same application-code hash, starting with the unchanged three-CPU/two-worker
  load. **No repeat stress pass, clean-shutdown pass or promotion is claimed yet.**
  This follow-up changes documentation only and does not rerun paid inference,
  native drivers, installed-profile activation or vault operations.

## Historical Read-Only Batch: 2026-10-14

The following audit and chronological evidence are preserved unchanged. Read the
current-status section above for the expanded inventory and accepted native gates.

Date: 2026-10-14

## Status and Scope

Implemented a development-only path from the existing Sage chat endpoint to a
pinned Codex App Server and a short-lived, read-only InspectorPro MCP adapter.
The default agent route is unchanged. Manual tools do not depend on Codex.
No desktop promotion, layout edits, or write-tool migration is part of this batch.
The subsequently authorized live test passed two read-only turns through the
existing Sage streaming endpoint on copied Private Gym data, using GPT-5.5.

This is **not yet a production autonomous engineering agent**. Live evidence now
proves model-selected inspection, follow-up reads, streaming, and thread resumption
through Sage's backend. It does not prove the desktop UI, live cancellation,
memory-enforced sessions, or transactional placement/correction workflows.

## Current Architecture Map

| Area | Actual implementation | Migration decision |
| --- | --- | --- |
| Sage UI and streaming | `static/index.html`, `static/chat_stream_runtime.js`, `/api/agent/chat/v2/stream` in `server.py` | Preserve chat identity, cancellation, streaming events, and manual commands. Add two bounded progress labels. |
| Provider/model gateway | `ai_inspector/model_gateway.py`, `_sage_answer_provider_config`, `_invoke_agent_model` in `server.py` | Preserve for existing routes. It selects/transports model requests; it is not an agent runtime. Do not put it around Codex's execution loop. |
| General chat dispatch | `agent_chat` and `_agent_chat_impl` in `server.py` | New pilot dispatch happens before creating legacy provider clients. Disabled flag and other workflows use the old path. Errors never silently fall back to another paid model. |
| Facility observe/replan loop | `_resolve_facility_layout_provider_reads` in `server.py` | Replace incrementally with Codex's model/tool loop. Retain until migration regressions pass. |
| Context normalization | `normalize_agent_context`, `_resolve_trusted_facility_layout_context` | Preserve identity conventions. Pilot uses normalized saved-layout identity but deliberately bypasses generation/preview preparation. |
| Facility engineering inspection | `facility_layout/agent_runtime.py`, `observation.py`, `semantic_model.py`, `service.py` | Reuse principal-bound, revision-bound read functions and their existing schemas. No geometry implementation in MCP handlers. |
| Engineering authorization/persistence | `authorization.py`, `repository.py`, authority repositories, `transaction_adapter.py` | Remain authoritative. These are not replaced by conversation history or model confidence. No write adapter exposed yet. |
| Skills and routing | `agent_skills/runtime.py`, `routing.py`, `tool_policy.py`, workflow contracts and `SKILL.md` files | Preserve domain instructions, contracts, and receipt validation. Retire redundant model routing only when equivalent workflow behavior is proven. |
| Persistent chat/workflow state | `_execute_agent_chat_with_memory`, `ai_inspector/memory/`, `agent_skills/workflow_state.py` | Existing user/session admission stays outside the runtime adapter. Codex threads are separate from this memory and from engineering documents. |
| Desktop lifecycle | `desktop/src/application-main.cjs`, `runtime-main.cjs`, `main.cjs` | No packaging or launch changes in this batch. Pinned runtime packaging and secure credential provisioning are future work. |

The audit is deepest for Facility Layout, the chosen pilot. Assembly, CAD,
inspection, revision analysis, documentation, ERP, and sourcing have **not** been
declared migrated or proven MCP-compatible. Their existing skills and UI contracts
are candidates, not evidence that every illustrative operation is implemented.

### Reusable Domain Guidance

`agent_skills/analyze-facility-layout/SKILL.md` already distinguishes authored
facts, deterministic geometry, engineering inference, and missing safety evidence.
It also explains the existing semantics/spatial tools. Preserve this guidance.
Its front matter already resembles Codex skills, but it mentions tools outside the
five-tool pilot; do not expose the entire skill catalog or automatically install
skill dependencies. Curate instructions per authorized tool set first.

## Integration Decision

Use **App Server over local stdio**, behind a small Python transport adapter.
InspectorPro already has a Python backend and an Electron renderer, so no new
hosted service, second agent planner, or WebSocket gateway is needed.

The current [App Server documentation](https://learn.chatgpt.com/docs/app-server)
provides thread lifecycle, streaming, interruption, approvals, authentication, and
MCP integration. It also marks the app-server command and WebSocket transport as
experimental and unsupported for production. Production adoption needs a fresh
support/compatibility review; this pilot is not a production-support guarantee.

The [Python SDK](https://developers.openai.com/codex/sdk) was evaluated locally at
0.162.1. Its launcher merges the parent environment and does not expose the Windows
hidden-process controls needed here. Rather than monkey-patch SDK internals, this
pilot implements only bounded JSON-RPC transport and lifecycle handling against
the same pinned executable. Codex still owns planning, tool selection, and model
iteration. InspectorPro does not add another reasoning loop.

```text
Existing Sage endpoint / stream
  -> existing session admission, then development feature gate
  -> pilot adapter: principal + saved document revision + run budget
  -> hidden Codex App Server process, isolated CODEX_HOME, stdio
  -> ephemeral authenticated loopback MCP endpoint
  -> existing FacilityLayoutAgentRuntime / service / geometry
```

## Contracts and Safety Boundary

Five tools are exposed:

- `inspect_facility_context`: bounded saved-layout identity/digest.
- `inspect_facility_entities`: existing stable-ID inspection contract.
- `inspect_facility_semantics`: existing semantic/derived-metric contract.
- `inspect_facility_findings`: existing deterministic findings contract.
- `analyze_facility_spatial`: existing bounded geometry analysis contract.

Inputs use the existing explicit JSON schemas; unknown fields are rejected. Output
uses `{ok, data}` or `{ok:false, error:{code,message}}`, plus MCP error status.
Inspection results are bounded to 64 KiB by the adapter, on top of existing domain
limits. A successful response requires at least one successful inspection receipt;
this proves inspection occurred, **not** that all statements are correct or that a
facility is safe/compliant.

The binding includes tenant, principal, Sage session, conversation, site, layout,
saved revision, model, and adapter protocol version. Every tool rechecks authority
and revision. The pilot rejects unsaved edits, conflicts, and generation/design
preview references. It never accepts model-provided replacement document IDs.
Changing documents/revisions yields a different Codex thread binding.

The MCP listener uses a fresh random loopback port and per-run bearer capability.
It rejects a wrong Host, any browser Origin, non-loopback clients, missing/wrong
tokens, and requests after revocation. Request bodies are capped at 32 KiB. The
capability stays in backend/child environment, never in renderer responses.
This is a local process boundary, not protection against a compromised Windows
account capable of inspecting other processes.

Child environment is allowlisted, not inherited. It excludes normal Codex config,
personal credentials, model-gateway keys, and proxy settings. Shell execution,
computer/browser control, app/plugins, multi-agent delegation, native web search, image
tools, automatic skill dependency installation, and permission requests are
disabled for the verified GPT-5.5 configuration. The named `inspectorpro-readonly`
permission profile denies root access and grants read access only to the empty
per-binding workspace, with command network access disabled. The adapter checks
effective configuration, the active thread profile, and the exact MCP inventory
before inference. All unexpected server-side approval/tool/permission requests
are denied. No host-defined dynamic tools or shell fallback are provided.

The runtime still advertises `apply_patch`; an offline scripted-provider test
proves an attempted write is rejected by its read-only sandbox and never creates
the canary. MCP resource/discovery helpers remain present, scoped to the single
authorized server; user-input requests are denied. This is not a claim that every
built-in tool has been removed. These controls require security review before
shipping a multi-user product.

Eight tool calls and 120 seconds bound a pilot turn. Cancel/error attempts
`turn/interrupt`, revokes MCP access, and terminates the child process. A synchronous
geometry function already executing may finish before cancellation completes.
Reads run off the event loop, serially per gateway; cancellation joins the active
worker before releasing the host and discards its result. MCP calls have a
90-second timeout within the 120-second turn budget so queued reads do not trigger
premature retries. A hard per-operation CPU deadline would require a separately
isolated domain worker.

SQLite stores thread IDs, request hashes, status, response, and hashed-argument
tool receipts under the dedicated pilot root. Completed identical requests replay
the saved response without another model turn. Changed-content duplicates conflict.
Failed/interrupted turns are never automatically rerun. A crashed run's binding
lease expires after ten minutes, allowing a **new** request, never silently replaying
the abandoned one. Runtime stderr is not forwarded because it may contain sensitive
material. Bounded provider failure messages are credential-redacted and stored in
the backend journal, not returned to the renderer. Private prompts/responses in Codex state and the pilot journal require
the same retention/access policy as engineering documents before production.

Responses declare the existing `facility_action_mode: READ_ONLY` contract and
contain no UI tool calls. This also suppresses the renderer's legacy inferred
viewport actions. Conversation history is not an engineering commit or undo log.

## Authentication and Billing

Initial route is API-only, using an explicitly supplied dedicated backend
`INSPECTORPRO_CODEX_API_KEY`. It does not read or reuse a personal ChatGPT/Codex
login, and does not persist the credential in application files or logs. Do not
put this variable in renderer configuration, source control, or committed `.env`.
OS credential storage/provisioning is still required before product release;
environment injection is for a controlled development process, not an end-user
credential-management UI.

Paid inference has its own opt-in, separate from the feature flag. Model name must
be configured explicitly and be available to that API account. No availability or
pricing is inferred from a ChatGPT subscription. Application-level spending caps,
token accounting, and billing UX remain future work; the pilot has time/call
budgets, not a guaranteed dollar ceiling.

[Sign in with ChatGPT guidance](https://developers.openai.com/siwc/token-sharing-open-source)
distinguishes eligible local/open-source integrations from commercial/hosted use.
InspectorPro must verify its commercial eligibility and required approval before
offering plan-backed usage. Bundled Codex login must not be treated as permission
to resell or embed subscription inference. Keep authentication replaceable.

## Development Setup

Optional dependencies are in `requirements-codex-pilot.txt`. Do not install them
into the promoted desktop environment. The verified local evaluation installed
them in `.runtime/codex-pilot-deps`; append that directory with `site.addsitedir`
after the application's normal dependencies. This preserves the existing FastAPI
and Starlette versions and processes pywin32's `.pth` files on Windows. A dedicated
tested lockfile/environment is a packaging prerequisite.

Pinned executable: `openai-codex-cli-bin==0.162.1`. The adapter verifies the runtime
version before initialization. Named permission profiles require the experimental
App Server API in this version. Do not silently auto-upgrade it. MCP is pinned to
2.3.0; its constructor-based handlers and snake_case Python model fields differ
from older MCP examples.

Before any development server launch, point `INSPECTORPRO_FACILITY_LAYOUT_ROOT`,
`INSPECTORPRO_MEMORY_DB_PATH`, `INSPECTORPRO_METRICS_DB`, and the documentation output
roots at disposable test storage. Never enable the pilot against a production or
desktop data directory just to run a smoke test.

Required pilot settings, all backend-only:

| Setting | Meaning |
| --- | --- |
| `INSPECTORPRO_CODEX_READONLY_PILOT=1` | Route only Sage Facility Layout turns to the pilot. Default off. |
| `INSPECTORPRO_CODEX_BINARY` | Absolute path to the pinned executable. |
| `INSPECTORPRO_CODEX_PILOT_ROOT` | Dedicated absolute pilot state directory; not a user profile or personal Codex directory. |
| `INSPECTORPRO_CODEX_MODEL` | Currently only `gpt-5.5`, whose native tool surface has been checked. |
| `INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE=1` | Separate intentional billing opt-in; set only in the authorized isolated test process. |
| `INSPECTORPRO_CODEX_API_KEY` | Dedicated backend credential, provisioned outside the renderer. |

Disable the first flag to restore the existing route. No migration rollback of
engineering documents is needed because this pilot has no write tools.

## Verification

`tests/test_codex_readonly_pilot.py` covers isolation, typed arguments, read-only
authorization, actual domain reads, stale revisions, tool budgets, revocation,
MCP authentication, duplicate requests, abandoned runs, failure, interruption,
missing evidence, and restricted filesystem policy.

`tests/test_codex_sage_route.py` covers feature/workflow gating, bypass of legacy
providers, terminal errors, and existing Sage SSE progress/response transport.
Transport fakes in these tests are explicitly not proof of autonomous reasoning.
Existing chat-stream and facility-runtime regression suites remain enabled.

`tools/verify_codex_readonly_pilot.py` provides the no-inference integration check:

```powershell
python tools/verify_codex_readonly_pilot.py `
  --binary "<absolute path to pinned codex.exe>" `
  --dependency-dir .runtime/codex-pilot-deps `
  --source-root .runtime/facility-layout `
  --layout-file .runtime/facility-layout/layouts/local/site-local/layouts/fl-private-gym-20261007.json `
  --output-root .runtime/codex-pilot-check/new-offline-run
```

The output directory must be new. It copies the layout and authority records into
disposable storage, starts the real App Server, opens a thread, and invokes three
real MCP inspection tools through `mcpServer/tool/call`. It never calls `turn/start`
and points its provider at a closed loopback port. Source SHA-256 and copied
revision must remain unchanged. It records only evidence metadata, not raw tool
data or credentials. This verifies integration plumbing and real domain reads,
not model selection of tools or a live UI walkthrough.

Initial successful real-layout check: the repository's saved Private Gym snapshot,
29 zones and 282 placements. This snapshot is not asserted to be the latest desktop
gym. Evidence is stored under `.runtime/codex-pilot-check/` and is not for source
control. No rendering or CAD tessellation was needed for this backend inspection.

### Initial Offline Results

- Focused pilot, Sage route, existing streaming, and facility-runtime tests:
  **62 passed**.
- Existing `test_facility_layout_agent_integration.py`: **202 passed** with its
  Facility Layout and design-loop test feature flags enabled. The initial isolated
  run had 200 passes and two failures because those proposal-application flags
  were intentionally absent; no production defaults were changed to address this.
- `node tests/test_chat_stream_runtime.js`: **11 passed**, including both new
  progress labels.
- Real Codex 0.162.1 initialization, effective shell/MCP configuration checks,
  thread creation, and three successful real MCP reads: **passed**. Evidence:
  `.runtime/codex-pilot-check/offline-real-final/evidence.json`.
- Model turns: **0**. API credentials passed to the real runtime: **none**.
  Copied layout revision and source file SHA-256: **unchanged**.
- Scoped tracked-file `git diff --check`: clean. No desktop promotion or restart.

These are targeted tests, not a full-repository pass or live-model acceptance.

### Live Follow-Up: 2026-10-14

Preflight found two controls described in current documentation that were not
honored by the pinned runtime: `sandboxPolicy.readOnly.access` was absent from its
generated protocol, and `tools.view_image=false` was ignored. They were replaced
with the supported named permission profile and `features.view_image=false`.
Earlier mocked assertions were not evidence that those old controls worked.

Astra's bundled model metadata forces additional code-mode/delegation tools even
when the corresponding feature flags are false. It is therefore excluded from
the pilot allowlist, not silently assumed safe. This does not change InspectorPro's
legacy model-gateway configuration. The pilot uses GPT-5.5 pending separate model
compatibility checks.

Two restricted-network attempts failed with a connection error before any model
output or engineering tool use was observed.
After approved network access, the first live inspection exposed event-loop
blocking and premature MCP timeouts during concurrent reads. The gateway now
offloads serialized reads, joins workers on cancellation, and gives the model
curated guidance for zone metrics and geometric membership. No agent reasoning
loop or replacement geometry implementation was added.

Successful live evidence: `.runtime/codex-live-04/live-evidence.json`.

- Same Codex thread resumed across two Sage SSE requests.
- First turn: four successful model-selected engineering reads, 161 text deltas,
  56.68 seconds. Correctly reported 29 zones, 282 placements, a 240 m2 cardio zone
  with 24 x 10 m bounds, and real Cybex treadmill/stationary-bike placement IDs.
- Second turn: two successful reads, 87 text deltas, 26.667 seconds. Reidentified
  the cardio zone, rechecked its area, and distinguished the label's station count
  from the separate geometry-derived placement count.
- Both turns returned `READ_ONLY`, zero UI tool calls, and zero engineering changes.
- Source SHA-256 and copied saved revision remained unchanged.
- Final regression run: 67 Python tests passed across the pilot, Sage route,
  existing stream backend, and facility agent runtime. These include worker
  cancellation, redaction, unsupported models, permission mismatch, and incomplete
  tool discovery. All 11 chat-stream JavaScript tests also passed.
- Real native-tool guard probe passed without API credentials or model inference:
  `.runtime/codex-pilot-check/guard-final/evidence.json`.

Reproduce the native guard test with `tools/verify_codex_runtime_guards.py`, using
`--binary`, `--dependency-dir`, and a new `--output-root`. Its provider is entirely
local and scripted; it is a permission test, not evidence of model reasoning.

`tools/check_codex_sage_live.py --live` runs at most two paid read-only turns per
invocation against a newly copied layout. It accepts the same binary/dependency/
source/layout/output arguments as the offline check, plus `--model gpt-5.5` and
an optional `--api-key-file` pointing to an existing backend dotenv file. Only the
OpenAI key is selected and passed in the child environment; the file is never
modified. Never retry it automatically on failure. Network permission and paid
inference authorization are separate requirements.

The live harness uses FastAPI TestClient with memory mode off, real Codex, the
real provider API, and real InspectorPro MCP/domain reads. It does not mock model
outputs or engineering functions. It is not a visual desktop/UI acceptance test,
and the copied repository snapshot is not asserted to be the latest desktop gym.

### Native Desktop Follow-Up: 2026-10-14

The normal Electron application now has an explicit, test-only
`--codex-acceptance-output` entry. `tools/check_codex_sage_desktop.py --live`
prepares a disposable Private Gym copy and separate desktop profile, then uses
native renderer input events through the existing Sage input and Send/Stop
controls. It does not enable editing, substitute model output, or save layouts.
The normal installed desktop profile and legacy gateway remain unchanged.

The native test found a real integration gap: memory-off facility chat omitted
the client turn ID. Facility request construction now supplies stable conversation
and per-turn IDs independently of memory mode, preserving server-memory and retry
IDs when already present. Three JavaScript regressions cover this behavior.

Evidence is deliberately retained with its original pass/fail status:

- `.runtime/codex-desktop-01`: input-driver hit testing failed before a message
  was sent. No paid inference or engineering operation ran.
- `.runtime/codex-desktop-02`: the real UI request reached the pilot but failed
  closed with `codex_identity_required`, before inference.
- `.runtime/codex-desktop-03`: after the identity fix, two native chat turns
  completed and resumed one Codex thread. The first reported 29 zones, 282 assets,
  and the cardio area's 24 x 10 m bounds / 240 m2 area using two actual reads
  (48.575 seconds). The follow-up reidentified the zone and a real Cybex treadmill
  placement using three reads (58.965 seconds). Streamed replies were visible in
  the actual desktop and screenshots inspected. A third read-only spatial request
  also completed, but the test had watched the wrong DOM node for pre-response
  progress and never clicked Stop. Its overall report correctly remains failed.
- `.runtime/codex-desktop-04`: a focused `--cancel-only` rerun, with the corrected
  progress selector, passed. Visible phases included connecting and inspecting.
  Native Stop aborted the HTTP stream, restored chat controls, and recorded
  `interrupted` / `codex_interrupted` in the backend journal. This one-turn run
  does not claim conversation resumption.
- All four runs confirmed original and copied layout hashes unchanged, zero Save
  requests, and owned backend termination, stdio closure, and resource cleanup.
  The cancellation run also compared layout, revisions, dirty state, and history
  before/after and found them unchanged.

Reproduce with `tools/check_codex_sage_desktop.py --live --binary PATH
--dependency-dir PATH --api-key-file PATH --output-root NEW_DIRECTORY --port PORT`.
Add `--cancel-only` to test only cancellation, avoiding repeated paid conversation
checks. The runner uses GPT-5.5, the existing pinned runtime, and memory mode off.
It loads optional packages through a test-only Python bootstrap, not the promoted
desktop's dependency environment. Helpers run without console windows. Runtime
permission and paid-inference approval are still required.

This establishes native read-only chat, multi-turn continuity, visible progress,
and real Stop cancellation across the recorded runs, not a complete production
acceptance or a claim that the latest full test passed as one uninterrupted run.
The existing plan labels overlap at the fitted overview scale; this test does not
accept overall viewport styling or 3D asset rendering. Read latency remains too
high to call this a polished demo.

Regression follow-up: 67 focused Python tests and all 14 chat-stream JavaScript
tests passed. The first Python attempt was blocked at fixture setup by sandbox
permissions on the shared Windows pytest temporary directory; the successful run
used a fresh repository-local test directory with approved execution permissions.
The broad desktop suite exposed missing layout-sheet callbacks in its startup
fixture. That fixture now records setup/render calls and verifies the expected
workspace, layout, and retained-session behavior; its 37 startup tests pass.
At unrestricted test concurrency, the separate owned-child startup test sometimes
times out before its 500 ms stdout marker, while still confirming process/stdio
cleanup. No production timeout or cleanup assertion was weakened.
The complete desktop suite subsequently passed **667/667** with
`node --test --test-concurrency=2 desktop/tests/*.test.cjs` (43.347 seconds).

### Memory and Document Binding Follow-Up: 2026-10-14

The Codex route now invokes the existing memory-envelope preparer before
inference and passes its result as untrusted conversational context. Previously,
the fallback prepared the envelope after the response, so its applied-to-prompt
metadata did not reflect actual Codex input. Model attribution now records the
actual Codex model/runtime instead of the legacy gateway configuration.

Memory uses a compact, server-authorized saved-document binding for this pilot.
Detailed geometry remains available through MCP, not a duplicate prompt snapshot.
Identity/reconciliation checks read the authorized repository and preserve the
layout, shell, and policy revision vector without rebuilding full facility
analysis. They still reject stale, dirty, conflicting, or preview documents.
Other agents and the legacy execution route retain their existing behavior.

Final regression evidence: 90 tests passed across the pilot, Sage route, memory
server lifecycle, streaming backend, and facility runtime (312.23 seconds). This
includes a real repository test confirming identical scope/revision values
between the old domain context and the bounded pilot binding. Coverage includes memory
preparation failure before inference, committed history/replay without duplicate
inference, server-owned history over forged browser history, provider attribution,
and discarding a read whose saved revision advanced during execution.

`tools/check_codex_sage_desktop.py --live --memory-check` is a three-turn native
scenario: inspect the copied gym, reload its conversation, attempt a blocked
mid-turn tab change, then inspect a second copied layout in the same conversation.
It checks separate document-bound Codex sessions, visible responses, no Save
requests, unchanged source/copy hashes, and process cleanup. It does not enable
the pilot in the normal installed desktop profile.

Retained diagnostic runs:

- `.runtime/codex-memory-desktop-01`: failed before inference because the second
  layout's test registry was not canonical. The fixture now uses the repository
  serializer.
- `.runtime/codex-memory-desktop-02`: memory rejected an oversized context before
  inference. Source/copy hashes and Save counts were unchanged. The owned backend
  was terminated, but resource cleanup was not confirmed, so cleanup is not
  claimed for this run.
- `.runtime/codex-memory-desktop-03`: timed out before a completed answer; the
  pilot recorded interruption with no tool receipts. Both layouts were unchanged
  and backend termination/resource cleanup were confirmed. This exposed the cost
  of rebuilding geometry in memory identity checks.
- `.runtime/codex-memory-desktop-04`: reached runtime connection but timed out
  before an engineering tool ran. Original/copy hashes and Save counts remained
  unchanged. Backend termination was confirmed but graceful resource cleanup was
  not. Protocol timeouts now record only method/timeout diagnostics, never request
  bodies or credentials, to distinguish startup failures from model turn limits.
- `.runtime/codex-memory-desktop-05`: the final bounded retry also timed out at
  startup, with no established Codex session and no engineering receipts. The
  outer time budget expired without a per-method diagnostic. The actual window
  and its connecting state were captured and inspected. Both source/copy hashes
  remained unchanged, zero Save requests ran, and backend/resource cleanup was
  confirmed. Conversation reload and busy/idle tab switching were not reached;
  those native scenarios remain unverified. Do not promote this as a passing
  memory-enabled desktop pilot or widen timeouts to hide the failure.

`tools/check_codex_sage_live.py --live --stale-check` adds a one-turn fault-injection
scenario. A test-only writer advances only the disposable copy through the actual
repository save API at the first real read boundary. The model and engineering
read are not mocked. Passing requires a failed stale-document tool receipt, a
terminal error rather than a completed answer, and an unchanged source layout.
The agent itself still receives only read-only tools.

Live stale-revision evidence: `.runtime/codex-stale-live-01/live-evidence.json`
passed in 38.29 seconds. Codex selected `inspect_facility_context`; the controlled
writer saved a new display name in the disposable copy. The gateway discarded
the old read and recorded a failed `codex_document_unavailable` receipt. SSE ended
with that error, no final answer or UI actions, and a failed pilot journal turn.
The source hash remained unchanged; the copy's revision matched exactly the
test writer's save receipt. This is a synchronized real read/save fault injection,
not a claim that a second user performed the concurrent edit through the UI.

JavaScript verification also passed: 14 stream-runtime checks, 20 frontend
contract checks, and the native Codex acceptance-option isolation test.

### Native Memory Gate Completed: 2026-10-14

The unresolved native gate was reopened immediately after user feedback. Bounded
runtime timing now records process launch, initialization, configuration, thread
start/resume, tool discovery and shutdown, without arguments, credentials or raw
stderr. No timeout was increased, memory was not disabled, and no fallback model
or broader tool permissions were introduced.

- `.runtime/codex-memory-desktop-06` stopped before sending a chat request because
  the test clicked a temporarily disabled New Conversation control. The driver
  now waits for usable controls and identifies the selector on failure.
- `.runtime/codex-memory-desktop-07` completed its real memory-enabled reply in
  39.023 seconds and restored the persisted conversation after reload. Tool
  discovery completed 3.556 seconds after runtime construction. The test then
  tried to type into the collapsed chat panel; it now reopens that panel before
  continuing, without creating a new conversation.
- `.runtime/codex-memory-desktop-08` passed the complete native scenario in
  178.013 seconds. All three requests completed (29.643, 44.870 and 28.602 seconds).
  The second request actually executed `thread/resume`, not merely the same
  application binding. The busy tab change was refused. After idle switching,
  Sage correctly inspected Reference Factory - Manual Build: 45 zones and 827
  placements, explicitly distinguishing it from the gym (29 zones / 282 assets).
  There were two document-bound Codex sessions within one conversation, three
  committed memory turns attributed to GPT-5.5 / Codex App Server, and a context
  manifest for each. Both original/copied layouts, editor state and history were
  unchanged, with zero Save calls and confirmed backend/resource cleanup. The
  actual desktop reply screenshot and persisted audit records were inspected.
- `.runtime/codex-memory-desktop-09` exposed an evidence-recorder failure:
  Chromium evicted the response body from its inspector cache. The visible second
  answer, pilot journal and memory commit all completed, but the driver mislabeled
  its missing evidence as a turn timeout. The recorder now collects only the chat
  response through `Network.streamResourceContent`, with a 4 MiB bound. It keeps
  the initial buffered bytes ahead of live chunks, decodes UTF-8 after joining,
  requires a terminal event and reports evidence/network failures immediately.
- `.runtime/codex-memory-desktop-10` exposed a real conversation transition race:
  a message was sent against the previous conversation while New Conversation
  was loading. Activating the new conversation then interrupted that request.
  Memory initialization/loading now blocks Send, voice submission and overlapping
  conversation changes; UI synchronization cannot falsely mark loading complete.
  Stop remains available for an active stream. The saved composer also retained
  already-sent text, which contaminated earlier follow-up prompts after reload.
  Sage/Iris and Scout now consume that persisted draft when accepting a new send.
  The native check requires an empty restored composer and exact prompt equality.
- `.runtime/codex-memory-desktop-11` passed the strengthened three-turn check in
  151.016 seconds. It verified actual `thread/resume`, exact prompts, busy switch
  rejection, idle document rebinding, two Codex sessions, three committed memory
  records with manifests and GPT-5.5 attribution, zero Save requests, unchanged
  source/copy hashes and successful cleanup. The final screenshot was taken while
  the UI's text queue was still draining, so the next run additionally waits for
  the Stop control to return to Send before capturing a finished response.
- `.runtime/codex-memory-desktop-12` completed its first reply in 47.515 seconds
  and rendered it correctly with the Send control restored. Its assertion failed
  because it sliced a bold Markdown delimiter in half before removing formatting.
  The comparison now removes bold delimiters before taking the prefix; the actual
  captured response passes that corrected comparison. The app was not changed to
  accommodate test wording. Original/copy hashes, zero Save calls and cleanup
  were again verified. This run is retained as failed, not retroactively passed.
- `.runtime/codex-memory-desktop-13` passed the final repeat in 193.914 seconds.
  All three exact prompts completed (45.313, 49.053 and 22.858 seconds), and each
  screenshot waits for the finished reply with Send restored. The last screenshot
  was visually inspected. Actual thread resumption, restored empty composer,
  busy-switch refusal, correct idle document rebinding, three committed memory
  turns with manifests/attribution, zero Save calls, unchanged originals/copies
  and process cleanup all passed again.

Post-fix backend regression: 91 tests passed in 55.94 seconds across the pilot,
Sage route, memory lifecycle, streaming backend and facility agent runtime.
Focused JavaScript coverage exercises the actual conversation transition handlers
with a delayed server response, composer/Send disabling, preserved Stop behavior,
draft consumption, and bounded streamed evidence including fragmented UTF-8,
setup failures, oversized responses and interrupted/truncated streams.

These native runs were performed without concurrent heavy regression suites.
The earlier startup timeouts were not reproduced in the successful serial runs;
resource contention is a plausible contributor, not a proven sole cause. Do not
claim this proves behavior under arbitrary system load. The added timing makes
a recurrence diagnosable. This completes the tested native memory/reload/switch
gate; it does not constitute production promotion or write-tool approval.

### Native Recovery And Controlled Load: 2026-10-14

`tools/check_codex_sage_desktop.py --reliability-check startup|recovery` now
supports isolated, enforced-memory native tests. The test-only supervisor tracks
only descendants of its own Electron process, retains process creation times,
requires an active journal turn before terminating that turn's Codex process,
and checks both runtime exit and closure of the capability-protected MCP listener.
It never targets an ordinary desktop instance. Load workers are credential-free,
bounded to 600 seconds, and stopped in `finally`; CPU affinity is restored.

The recovery sequence is: complete inspection, Stop during a real engineering
read, resume with a follow-up, terminate the owned runtime during another real
read, close the whole desktop, restart with the same isolated profile, and ask a
context-dependent follow-up. Assertions cover persisted memory, exact prompts,
restored committed history, exclusion of failed/cancelled history, real
`thread/resume`, model attribution, unchanged source/copy hashes and zero Save.

Findings and fixes:

- `.runtime/codex-recovery-desktop-01` failed its strict cleanup gate. Stop had
  journaled `interrupted` and memory `cancelled`, but resources had not settled
  within 30 seconds. The stream handler cancelled its pipeline in several paths
  and again in `finally`, allowing cancellation to interrupt runtime teardown.
- The stream handler now cancels once and joins the worker under an ASGI
  cancellation shield. Tests exercise direct task cancellation, AnyIO scope
  cancellation and polled disconnects, requiring completed cleanup and exactly
  one worker cancellation. The protocol deadline now includes blocked stdin
  writes. Interrupt requests are awaited directly rather than left running in a
  detached shielded task. No timeout, model permission or inference retry limit
  was increased.
- `.runtime/codex-recovery-desktop-02` passed the five-turn native sequence in
  226.449 seconds. Stop cleanup settled in 7.446 seconds; injected runtime-failure
  cleanup settled in 2.791 seconds. Both desktop processes exited cleanly, with
  no observed orphaned children or open tool listeners. There was one document
  binding, one conversation and one agent session. Journal statuses were
  `completed, interrupted, completed, failed, completed`; memory statuses were
  `committed, cancelled, committed, failed, committed`. The failed turn carried
  `codex_runtime_stopped`; the completed follow-ups actually resumed the thread.
- The UI previously replaced the specific runtime error with a generic provider
  failure. Timeout and disconnect codes now map to fixed, actionable messages,
  without exposing raw provider text. The disconnect screenshot was inspected.
  The native driver was also corrected to use flat SSE `code`/`message` fields.
- `.runtime/codex-recovery-desktop-03` repeated the full sequence successfully
  with the final transport deadlines and directly awaited interrupt request, in
  251.972 seconds. Stop settled in 1.837 seconds and injected disconnect cleanup
  in 4.025 seconds. Both desktop processes, listeners, memory statuses, restored
  conversation and actual resumed reads passed again.
- UI failure handling also offered a frozen-ID Retry even when the server said
  `retryable: false`. Such terminal turns intentionally cannot be replayed. The
  UI now suppresses that invalid Retry for both partial and non-partial terminal
  failures, preserves normal network retries, and tells the user to send a new
  request. It does not silently allocate a new ID or automatically repeat work.
- `.runtime/codex-recovery-desktop-04` passed the final five-turn repeat in
  192.325 seconds, including a native assertion that the disconnect message
  offers no invalid Retry. Stop cleanup settled in 0.762 seconds and disconnect
  cleanup in 2.797 seconds. Both desktop lifecycles closed all observed children
  and tool listeners without forced cleanup. The original/copy hashes, editor
  state, zero Save calls, expected memory statuses, single conversation/binding,
  full restart restoration and actual thread-resumed inspection all passed.
  The corrected failure screenshot was visually inspected. No promotion or
  write-tool enablement was performed.

Controlled startup observations, without concurrent regression suites:

| Run | Allowed CPUs | Load workers | Result |
| --- | --- | --- | --- |
| `codex-startup-baseline-01` | 2 | 0 | Passed; tool discovery 18.261 s, response 67.716 s |
| `codex-startup-load-01` | 2 | 2 | Failed at `thread/start` with `codex_protocol_timeout`; no engineering receipts |
| `codex-startup-load-02` | 4 | 2 | Passed; tool discovery 4.020 s, response 41.103 s |
| `codex-startup-load-03` | 2 | 2 | Failed again before tool discovery; capture also stalled and the owned test window was terminated |

The failed run consumed 121.189 seconds in the native request and 225.409 seconds
overall. Its phase timeline recorded slow process launch and initialization,
then a `thread/start` timeout (configured deadline still 20 seconds). Worker CPU
times were 41.375 and 38.984 seconds over about 225 seconds. The four-CPU run's
workers each consumed about 27.9 CPU seconds over 68 seconds. All workers stopped;
original and copied layouts remained unchanged. These are measurements on this
machine, not a minimum hardware specification or proof that all startup stalls
have been eliminated. Do not treat the four-CPU pass as a fix for the two-CPU
failure or promote solely on this evidence.

The stricter repeat (`load-03`) reached `thread/start:wait` at 30.546 seconds and
`closing` at 58.135 seconds, but persisted the generic `codex_runtime_failed`
code, not a successful inspection. Its unfinished capture prevented normal test
completion. Artificial load was stopped after the persisted failure, at about
297 seconds, and only the exactly identified test Electron process was then
terminated. The supervisor stopped its remaining owned child. Runtime and MCP
listener closure were observed, but normal cleanup was **not** accepted as
passing. Source/copy SHA-256 checks were repeated afterwards and matched. The
native driver now bounds renderer and screenshot waits at 15 seconds, focuses
its own test window before capture, and reports these failures distinctly from
model completion. Three additional deadline tests passed. This run is retained
as failed; it is not evidence that startup saturation has been fixed.

Regression coverage: 102 backend tests passed together; the optional MCP test
passed separately after initializing dependencies with `site.addsitedir`, as the
native launcher does. Earlier invocations hit an inaccessible system pytest
directory and omitted optional dependencies. A new disposable workspace test
directory was used; the existing directory and its permissions were not changed.
JavaScript verification passed 66 checks across streaming, memory transitions,
frontend contracts, streamed evidence, acceptance isolation and native capture
deadlines.

## Next Gates

1. Reduce read latency and investigate startup behavior under controlled system
   load before calling this a polished demo. Preserve the passing serial native
   memory/reload/switch acceptance and the real stale-revision fault injection.
2. Preserve the now-passing enforced-memory Stop, unexpected disconnect, full
   desktop restart and thread-resumption gate alongside memory reload and
   document-switch coverage. Repeat it after transport/lifecycle changes.
3. Add a proposal-only placement adapter over existing transactions. Require
   backend preview validation, exact revision/operation approval, idempotency,
   commit receipts, and undo/rollback before exposing any write tool.
4. Prove constrained placement -> actual interference result -> correction ->
   deterministic final validation on real copied CAD/layout data. Do not substitute
   fake geometry or a fluent model response for this acceptance test.
5. Review commercial authentication, runtime support status, model budgets,
   secure storage, telemetry/redaction, binary provenance, dependency locks,
   Windows signed packaging, and update/rollback strategy before promotion.
6. Migrate one additional workflow at a time. Remove old orchestration only after
   equivalent regression coverage; never remove the engineering/manual command
   implementations merely because Codex can call them.

Additional official references:
[MCP configuration](https://developers.openai.com/codex/mcp),
[Codex configuration reference](https://developers.openai.com/codex/config-reference).
