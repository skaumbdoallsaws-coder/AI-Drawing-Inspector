# Additional Codex Engineering Reads

Date: 2026-10-15

## Current Status

Both reads are integrated into the existing `FacilityReadGateway` and inherited
by `FacilityEditGateway`. The live two-turn backend check in
`.runtime/codex-workflows-live-01/live-evidence.json` passed. There is no new UI
route choice, workspace mode, Codex loop or per-workflow budget. The combined
inventory is seven read tools, or nine tools with the two edit-preview tools
enabled. These are additional facility navigation/process-binding workflows,
not CAD/assembly mutation or inspection of external Process Maps.

Native editing acceptance and regular local desktop activation passed; see
the dated current status in [the pilot audit](sage-codex-readonly-pilot.md).

The final live check also used the larger actual Factory 02 document (79 zones,
1,545 placements) on a disposable copy. Evidence:
`.runtime/codex-factory-workflows-final-01/live-evidence.json`. Both turns passed
with source bytes unchanged. Navigation reported 79 actors (40 pedestrian,
39 vehicle), 116 anchors and 40 movement programs, with missing vehicle semantics
and pending review states qualified explicitly. The second turn correctly
reported zero saved Process Map bindings, without claiming external map validation.

## Scope And Audit

Two additional **Facility Layout fact workflows**, not a general CAD migration:

| Adapter key | MCP tool | Actual implementation reused |
| --- | --- | --- |
| `facility_navigation` | `observe_navigation_context` | `FacilityLayoutService.get_layout` -> authorized `FacilityLayoutRepository.get_layout`, then `navigation_intent.navigation_context_summary` |
| `facility_process_routes` | `inspect_saved_process_bindings` | The same authorized saved-layout getter; closed projection, filtering and paging of its persisted `processBindings` |

Navigation returns coordinate-free actors, anchors, movement programs, handoffs,
missing semantics, counts and the domain qualification. These are authored
navigation facts, not certified clearance or safety. It does not compile a
snapshot, solve/validate a journey, simulate motion, or certify safety/compliance.
The process tool returns authored Process Map revision references, node/edge IDs,
placement IDs, route IDs and binding roles. It does not open Process Map documents,
infer process order, validate route geometry, or assert that the referenced map is
the current map revision. Empty bindings are a valid result, not invented facts.

Why not assembly/BOM in this batch:

- `AssemblyKnowledgeRepository.read` verifies document hashes/package revision;
  `source_status` checks server-bound source files. Neither accepts a principal.
  The assembly review GET routes in `server.py` use a feature gate and this
  repository, without an explicit principal/document ownership check there.
- `parts_manual_section_bom` uses the actual catalog, saved plan source-currency
  check and `build_scoped_bom`. Its route likewise has no explicit principal-bound
  ownership input. Feature gates and assembly numbers are not user authorization.
- This is an audit of these candidate entry points, not a claim that all global
  application authentication is absent. They are insufficient to establish the
  requested principal/workspace/document boundary without integration work owned
  by main. No pretend CAD operation or new geometry engine was added.
- The broader facility runtime's `inspect_process_bindings` calls
  `resolve_context`, which can call `host._agent_process_catalog` ->
  `_resolve_process_map` -> `load_named_process_map_revision` -> `_ensure_registry`.
  That last function can initialize/write a registry on a read path. The new
  distinctly named tool deliberately reads saved layout references only and never
  calls that path. It is not equivalent to full Process Map inspection.

## Shared Gateway Integration

The original adapter batch added `engineering_tools.py`, `engineering_schemas.py`
and `test_codex_engineering_tools.py`. Main subsequently integrated their specs
and delegate into the common runtime. The integration is **additive tools on the
existing common gateway**, not a new UI route, workspace mode, harness or
per-workflow loop. Exact helper exports remain:

```python
from ai_inspector.codex_runtime.engineering_tools import (
    ENGINEERING_READ_NAMES, engineering_tool_specs, read_engineering_facts,
)
```

- `engineering_tool_specs()` returns both fresh closed specs with `name`,
  `description`, `input_schema`, `output_schema`.
- `ENGINEERING_READ_NAMES` contains `observe_navigation_context` and
  `inspect_saved_process_bindings`.
- `read_engineering_facts(runtime, principal, reference, name, arguments)` is a
  synchronous `_read_data` delegate. It returns **data only**, not `{ok, data}`.
  It validates inputs, authorizes the saved-layout read, builds bounded facts,
  validates the complete eventual output envelope and rechecks authority/revision.
  Failures raise sanitized `PilotError` for the parent's normal error handling.

`facility_tools.tool_specs()` now appends the two engineering specs, and
`FacilityReadGateway._read_data()` dispatches `ENGINEERING_READ_NAMES` directly to
`read_engineering_facts(...)`. `FacilityEditGateway` inherits those reads and adds
`assisted_tools.edit_tool_specs()`. Do not append the engineering specs a second
time or instantiate a standalone gateway inside `_read_data`.

| Available in | Exact MCP tool names |
| --- | --- |
| Read and edit-preview modes: seven reads | `inspect_facility_context`, `inspect_facility_entities`, `inspect_facility_semantics`, `inspect_facility_findings`, `analyze_facility_spatial`, `observe_navigation_context`, `inspect_saved_process_bindings` |
| Edit-preview mode only: two more, nine total | `preview_facility_operations`, `preview_facility_undo` |

"Nine edit tools" means this nine-tool inventory, not nine mutation capabilities.
Approval, apply/commit and Save are not MCP tools. No helper-owned clock, counter,
lock, receipt store, worker, process or runtime is created. The common gateway
supplies its **single** 8-call / 120-second budget, serialization, cancellation
join and receipt list for inspection, both additional reads and previews together.

## Optional Strict Gateway

The independently testable strict gateway/factory remains available, but is not
required for shared integration and introduces no UI requirement:

```python
from ai_inspector.codex_runtime.engineering_tools import (
    EngineeringContext, create_engineering_gateway, tool_specs,
)

# This callback is supplied by the admitted route/lifecycle owner.
def current_context():
    # Recheck admission and fetch the latest accepted context for this turn.
    # Do not freeze the initial browser dictionary and call it current state.
    admitted = current_admitted_turn()  # Integration-owned callback, NOT a repo API.
    return EngineeringContext(
        principal=host.resolve_principal(http_request),
        session_id=admitted.agent_session_id or admitted.session_id,
        conversation_id=admitted.conversation_id,
        normalized=normalize_agent_context(
            admitted.inspection_context or admitted.context or {}
        )["flat"],
    )

gateway = create_engineering_gateway(
    "facility_navigation",  # Or facility_process_routes; server-selected.
    host.agent_runtime,
    current_context=current_context,
    turn_id=request.client_turn_id,
    max_calls=8,
    timeout=120,
    status_sink=status_sink,
)
```

`tool_specs(workflow)` returns fresh input/output schemas for one standalone
workflow. `tool_specs()` inventories both, as does `engineering_tool_specs()`.
The gateway has `.specs`, `await .call(name, arguments)`, `.check()`, `.closed`,
`.receipts`, `.binding` (defensive copy) and `.binding_key` (SHA-256).
There is no Codex launcher, provider loop, journal or route registration here.

## Integrated Wiring Contract

1. Both read specs are in the common gateway under the existing opt-in gate for Sage
   (`request.agent_type == "deviation-analyst"`) and the actual active workspace
   `facility_layout`. These are additional subworkflows, **not** new workspace
   modes, and must not change the mode to `facility_navigation` or
   `facility_process_routes`. No additional UI route choice is needed: Codex selects
   from the common authorized tool inventory. Adapter keys are output labels, not
   MCP authority arguments. Never silently fall back
   from rejected assembly, documentation or dirty contexts.
2. Keep existing user/session/conversation admission. Resolve the principal with
   `_FACILITY_LAYOUT_HOST.resolve_principal(http_request)`. Existing
   `_memory_principal` maps `principal_id` to memory `user_id`; the gateway uses
   that same source, not a renderer `userId`, role, tenant or ownership assertion.
   Tenant/site scope and `layout.read` permission are enforced by the actual
   service/repository on every check. Session/conversation ownership remains the
   existing backend admission's responsibility; valid-looking IDs alone do not
   prove it. Do not instantiate from unadmitted request fields.
3. Existing `AgentChatRequest` fields are `inspection_context` (or `context`),
   `agent_session_id` (fallback `session_id`), `conversation_id`, and
   `client_turn_id`. Existing normalization takes `attachments.facility_layout`
   identity (`siteId`, `layoutId`, `revision`) and `.state` to
   `facility_layout_ref` / `facility_layout_live_state`; session
   `attachments.session.active_mode` / `mode_contract.mode` supplies active mode.
   Use `normalize_agent_context(...)["flat"]`, preserving these fields before
   trusted-context resolvers pop live state. The shared pilot's admission rejects
   dirty/conflicted state, pending operations, generation/design references and
   proposal IDs; its gateway binds the closed three-field saved reference.
   The optional standalone strict gateway additionally requires exact
   `active_mode == "facility_layout"` and explicit boolean `dirty: false`,
   `conflict: false`. Do not attribute that separate callback contract to the
   shared helper or claim that an absent live-state field proves a clean editor.
4. The common `.check()` reauthorizes the saved layout and rejects a changed
   revision/closed run before and after reads, on replay and at finalization.
   `read_engineering_facts` also rechecks authority/revision, but knows neither
   browser dirty state nor session ownership. Current-editor revocation belongs
   to main's UI/request lifecycle, including Stop, disconnect, dirty/edit changes
   and workspace/document switches, followed by cancellation and joining active
   calls. The two-turn live workflow evidence below does not exercise those
   transitions. The optional strict gateway instead accepts a **thread-safe,
   fresh** `current_context` callback; a lambda over an initial snapshot is not
   evidence of mid-turn revocation. Neither helper owns a current-document registry.
5. `pilot.inspect_facility` now hashes tenant/principal, roles/site scope, admitted
   session/conversation, `workspace: facility_layout`, saved document revision,
   model, `protocol: 2`, the exact `gateway.specs` inventory digest and edit-preview
   mode into the common thread/journal binding. Request hashing binds message and
   document within that inventory-bound journal key. The optional standalone
   gateway has its own `.binding`; shared integration does not use that factory.
   Replay/final checks and the successful-receipt requirement remain in place.
6. The exact combined `gateway.specs` feeds MCP inventory, runtime `enabled_tools`
   and exact discovery verification. `mcp_bridge.make_application` now uses
   `spec.get("output_schema", OUTPUT_SCHEMA)`: the two engineering tools publish
   their closed success/error schemas; older specs without one retain the common
   envelope. The adapter also validates its output. MCP `is_error` is derived
   from `ok`; authentication and capability denial remain shared.
7. The added helpers are read-only even when mounted beside the existing gated
   edit-preview tools. Preserve the parent's preview lifecycle, approval/commit
   checks and response construction. A read-only turn returns
   `facility_action_mode: READ_ONLY`, empty UI calls and zero engineering changes;
   a mixed turn must retain the parent's actual preview/result mode, not be falsely
   labeled read-only by this helper. Do not add apply/approval, navigation
   compilation/planning, generation, file or shell capabilities through these
   helpers. Their `readOnly` result marker describes that read only. Nothing here
   bypasses the existing preview/apply approval path or changes its live acceptance.

## Bounds And Failure Behavior

- Closed schemas at every object boundary; no model-supplied identity, revision,
  user, filesystem path or geometry. Stable IDs only filter within the bound
  layout. Process offsets are bounded integers within that immutable revision;
  they convey no authority. Extensions/private metadata are not returned.
- Navigation: at most 50 records per collection; domain byte/truncation logic is
  retained. Process bindings: at most 20 records per page, 20 unique ID filters,
  offset <= 5000 and source collection <= 5000. Oversized individual records are
  rejected, not truncated into misleading facts.
- Shared helpers enforce 8 KiB serialized arguments and 64 KiB result, and consume
  no separate budget. Configure the parent for the common 8 calls / 120 seconds.
  The optional strict gateway also enforces those maximums itself. Its invalid
  calls consume the budget; at most `max_calls + 1` receipts are retained. Its receipts
  contain tool, success, hashes, elapsed time and fixed error codes, not raw input
  or exception text. Budgets may be lowered but not widened.
- The parent serializes shared reads off the event loop and owns the deadline and
  cancellation policy. `FacilityReadGateway.call` now shields its cleanup join
  with AnyIO `CancelScope(shield=True)` and retains `asyncio.shield` plus repeated
  direct-cancel handling. It closes the gateway and joins the worker before
  releasing the lock, without publishing the cancelled result or a receipt.
  `AppServer.close` likewise shields its owned cleanup task through process and
  child-task completion. In the optional strict gateway, deadline, cancellation, stale revision,
  changed identity/permissions, dirty or unavailable current context discard
  results. Its repeated cancellation joins an executing synchronous worker before
  host teardown. As in the pilot, the deadline bounds result acceptance, **not a
  hard CPU/IO kill**: an already-running repository read can delay teardown.
  A hard execution deadline would require a separately isolated worker.
- No document, registry, geometry, report, cache artifact or preview writes are
  performed by these adapters. Host bootstrap/session admission must already be
  established outside the read; `resolve_principal` itself calls host bootstrap.

## Focused Verification

Tests use `LocalFacilityLayoutHost(private_assets=False)`, the real service and
repository, `tests/fixtures/facility_layout/two_asset_cell.json`, and the existing
NAV8 fixture helper for authored navigation. Geometry is reused unchanged. Test
setup adds actor metadata and authored process references (including deliberately
unresolved map IDs), then real repository APIs save disposable copies. Fault
tests inject concurrent saves/context changes around real reads. No successful
domain result is mocked. No app or paid model is launched.

```powershell
python -m pytest -q tests/test_codex_engineering_tools.py --basetemp .runtime/codex-engineering-tests-NEW -p no:cacheprovider
```

The default Python environment lacks `jsonschema`. The already-existing optional
pilot dependency directory can be appended without installing anything:

```powershell
python -c "import site; site.addsitedir('.runtime/codex-pilot-deps'); import pytest; raise SystemExit(pytest.main(['-q','tests/test_codex_engineering_tools.py','--basetemp','.runtime/codex-engineering-tests-NEW','-p','no:cacheprovider']))"
```

Use a new disposable base directory each run. Coverage includes real function
parity, process paging/filtering and extension removal, unchanged fixture/repository
hashes, closed schemas, principal/site/tenant denial, current document/user/session
changes, stale saves before/during reads, output/call/deadline limits and repeated
cancellation cleanup. Composition tests subclass the actual `FacilityReadGateway`
and `FacilityEditGateway`, combine inventories, execute real inspection plus both
additional reads and prove the next read/preview is denied by the same shared call
budget, with one unchanged deadline and one receipt list.

Original adapter-batch focused run: **72 passed in 6.58 seconds**, using the existing pilot
dependency directory and `.runtime/codex-engineering-tests-06`. The default-env
attempt could not collect without `jsonschema`; it is not counted as a pass.
That implementation run did not launch an app, model or native test. Main later
integrated the common gateway and completed the separate live evidence below.
Main reports **174 combined backend tests passed** at the 2026-10-15 handoff;
this documentation update did not rerun them. The cancellation fix separately
passed nine focused tests in `test_codex_readonly_pilot.py`, including four new
AnyIO/repeated-direct-cancel cases that failed before shielding. These counts
are separate checkpoints, not additive totals or native acceptance.

## Verified Live Evidence

Read and checked `.runtime/codex-workflows-live-01/live-evidence.json` against the
workflow scenario in `tools/check_codex_sage_live.py`. It records GPT-5.5,
`workflowCheck: true`, `readOnly: true`, `status: passed`, with these successful
model-selected receipts through the real common gateway:

| Turn | Elapsed | Successful tools | Result |
| --- | --- | --- | --- |
| 1 | 14.980 s | `inspect_facility_context`, `observe_navigation_context` | HTTP 200, `response_completed`, `READ_ONLY` |
| 2 | 12.226 s | `inspect_facility_context`, `inspect_saved_process_bindings` | HTTP 200, `response_completed`, `READ_ONLY` |

The second runtime timeline contains actual `thread/resume` send/wait/done
events; the evidence also records the same thread ID. Both turns record zero UI
tool calls, zero engineering changes and completed runtime closing/closed phases.
`sourceUnchanged`, `copiedRevisionUnchanged` and `copiedRevisionMatchesExpected`
are all true. No raw prompt, answer, document ID or credential is reproduced here.

The copied gym has no saved process bindings, and the second answer reports zero
instead of inventing examples. This proves live tool selection and truthful empty
binding reporting, not live inspection of a populated external Process Map.
Populated binding filtering/paging is covered by the repository-fixture tests.
The scenario's `countsPresentInAnswer` flag is set by workflow mode, so it is not
an independent numeric-correctness assertion for all navigation counts. Authored
navigation remains metadata, not measured/certified clearance, validated routing
or a safety conclusion. This backend evidence does not establish native editing
acceptance or authorize promotion.

## Read Performance Checkpoint: 2026-10-15

Main reported `.runtime/codex-load-final-01` failed before the repository cache
fix under three allowed CPUs and two qualified load workers (about 22% CPU each).
Runtime initialization/thread start took about 25 seconds, and
`inspect_facility_context` took about 27 seconds. Repeated full saved-layout
validation exhausted the 120-second budget; the native request reached its
150-second deadline without receiving a terminal error. This remains a failed
load run, not a passing acceptance result.

After the fix, a normal-CPU benchmark without artificial load used an unchanged
copy of that saved gym in `.runtime/codex-gym-read-profile-02`, with 29 zones,
282 placements, the actual 518-asset catalog and no unresolved placement asset
IDs. Unprofiled wall-clock measurements were:

| Operation | Measured time |
| --- | --- |
| Cold `get_layout` | 649 ms |
| Five warm `FacilityReadGateway.check()` calls | 88, 99, 100, 36, 87 ms |
| Two complete `inspect_facility_context` calls, including pre/post checks | 2.12 s, 2.46 s |

The repository keeps at most 64 hashes of successfully canonical-validated bytes,
not cached document objects. Every read still authorizes, reads/parses the actual
bytes, hashes them, checks the registry and document identity/scope, and returns
detached data. Only repeated pure canonical validation of identical bytes is
skipped. The server's host/service/repository instance persists across gateway
reads and turns, so the cache remains warm until backend restart.

Profiling identified observation construction, deep copies of layout/catalog
data, one observation-level canonical validation and zone-membership calculations
as the remaining costs. These normal-CPU timings do not prove loaded deadlines.
Budgets and timeouts are unchanged. Main's combined regression run and then the
three-CPU/two-worker repeat are pending at this checkpoint; no load-recovery or
promotion claim is made. This benchmark did not launch paid inference or native UI.
