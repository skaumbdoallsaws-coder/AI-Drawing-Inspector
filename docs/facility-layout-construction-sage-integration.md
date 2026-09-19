# Bounded Sage Construction Integration

Date: 2026-09-12
Status: implemented pilot; live two-turn recovery acceptance passed against the
restored Anthropic API in `live-16-completion-check`. Independent review and broad
promotion remain pending; the feature stays off by default outside the pilot.

## Scope

Sage can invoke four hardened construction commands through its authorized
server tool loop. It does not click ribbon dialogs and does not execute
model-authored JavaScript. Existing deterministic builders produce an operation
plan; the authoritative operation kernel validates that plan.

| Command | Native Sage tool |
| --- | --- |
| Cell Layout | `preview_facility_cell_layout` |
| On Surface | `preview_facility_surface_stack` |
| Create Cell | `preview_facility_create_cell_group` |
| Linear Pattern | `preview_facility_linear_pattern` |

This is a cell-construction pilot, not whole-factory autonomy or a manufacturing
feasibility approval. It does not add equipment capabilities, motion, or Save authority.
The host needs Node on PATH, the published asset catalog, and a working model API.

## Execution Contract

1. A clean saved layout, catalog, shell, policy, and trusted editor context are resolved.
2. Sage supplies explicit entity IDs, `expectedDraftRevision`, `requestId`, and
   `parentProposalId`. The first parent is empty.
3. A fixed Node CLI calls the existing command adapter, session, and builders.
4. The Python service replays cumulative operations against the saved base through
   `preview_operations`. Invalid commands leave both the editor and saved layout unchanged.
5. A durable receipt returns the proposal ID, candidate revision, created/changed
   IDs, cell membership, attachment identities, and bounded findings. Sage uses
   those returned identities and revisions for its next command.
6. The complete candidate is shown in the existing right-hand review pane and in
   Plan/3D. Failed later steps mark a partial preview; its Apply button is disabled.
7. The user clicks **Apply to unsaved draft**. Server approval binds the exact
   candidate, principal, session, base revision, and editor generation.
8. The editor revalidates and installs the cumulative operations as one ordinary
   undoable gesture. No layout Save endpoint is called.
9. Undo restores the original layout document and draft revision. Old approvals
   cannot be applied after Undo. The normal explicit Save action remains separate.

One bounded continuation prompt handles a model response that acknowledges a
failed command but issues no recovery command. It permits only user-authorized
recovery, or a specific blocker/question. It cannot relax constraints or apply.
One separate bounded completion check compares the original request with the
executed command list and actual candidate counts when the provider stops. This
addresses stopping after grouping without executing a requested pattern. It does
not increase the existing tool-call or operation limits. It remains a model
completion review, not a deterministic proof that arbitrary prose requirements
have all been satisfied; explicit user review remains necessary.
The scoped provider tool list excludes whole-factory generation and semantic-plan
fallbacks. Explicit construction bypasses legacy department-based cell creation;
active generation drafts, full-factory requests, and resource amendments retain
their existing paths.

## Authorization and Retries

- Rollout flag: `INSPECTORPRO_FACILITY_LAYOUT_CONSTRUCTION_SAGE=1`, off by default.
- Preview requires `construction_sage`, its `agent_preview` dependencies, and the
  existing principal permissions. Apply additionally requires `agent_write`,
  `proposal.approve`, and `proposal.apply`, enforced independently on the server.
- Immutable preview/approval artifacts use the existing design repository.
  They are not saved layout documents and do not acquire a separate layout lease.
- Preview retry identity includes tenant, site, layout, principal, trusted client
  turn ID, and request ID. Canonical signatures sort object keys, retaining array order.
- Equivalent retries return the original receipt. Changed input under the same
  retry identity conflicts. Independent chat turns do not share request-key identity.
- Approval has a separate durable retry identity. Reinstalling the same approval
  in its current editor frame is a no-op; changed or stale frames are rejected.
- Source binding includes layout, shell, policy, catalog, evidence, and compiler
  source hashes. Changed sources require a new preview.

## Deliberate Limits

- Freshly loaded saved bases only: no existing unsaved edits, generation draft,
  design proposal, or undo/redo history. Reload after Undo before starting another
  pilot preview. Adopting dirty editor frames and generation leases is deferred.
- Undo restores layout/revision through normal history, not every presentation
  detail such as the prior selection or camera. Browser reload does not restore
  the applied unsaved draft automatically.
- Four commands; at most eight successful chained commands, 500 cumulative
  operations, and 120 affected entities per command. The existing provider tool
  budget remains bounded. This is not an 827-placement acceptance result.
- Preview TTL: 30 minutes. Artifact ceiling: 8 MiB. Tool summaries: 16 KiB.
  Compiler input/output: 8 MiB, timeout: 20 seconds, V8 old-space ceiling: 128 MiB.
  The V8 setting is not a proof of a whole-process memory ceiling.
- Normal inspection tools inspect the saved/editor context, not the uninstalled
  candidate. Candidate receipts supply the chaining evidence in this pilot.
- Cell Layout's `gap` is a **preferred input**, not guaranteed measured edge
  clearance. The tested prompt intentionally says preferred spacing. Exact
  clearance is not claimed. Linear Pattern pitch includes the original instance.
- North is `direction: "north"` (+Z); `vertical` is not its synonym.
- Repeating a completed cell requires its returned `cells[].cellId` as the
  pattern seed. Passing all members immediately after Create Cell now returns a
  targeted error with that ID; it does not silently omit or invent the cell envelope.
- Input/schema errors do not prove geometric infeasibility. Their feedback now
  explicitly says geometry was not evaluated and asks for corrected input.
- Desktop is the authoring target. Narrow-screen canvas smoke checks are not
  acceptance of the entire existing application as a mobile editor.

## Test Layout and Prompt

Run from the project directory:

```powershell
python tools/run_facility_construction_pilot.py --port 8187
```

Open <http://127.0.0.1:8187/?facilityLayoutId=fl-main&facilityAssets=1>.
Choose **Workflows > Facility Layout**, select the three existing objects in Plan,
open Sage, and start a new conversation. This is an isolated pilot, not the manual factory.

The pilot uses two real `asset-assembled-laboratory-workstation` assets named
Table A and Table B, plus `asset-carr-lane-cl-400-ptpb` named Device. It seeds only
`.runtime/construction-sage-pilot/store`; it refuses to overwrite changed pilot
content. No requests are directed at the manual reference store.

> Arrange existing Table A and Table B in a line with a preferred 0.5 m spacing input, preserving orientation, within a 14 m by 6 m envelope. Attach the existing Device (the Carr Lane tooling plate) to Table A's published worktop with a 0.05 m inset. Group both tables and that device as Pilot Cell with 0.2 m envelope padding. Make three total cells with a linear pattern north at 8 m pitch. Use the existing equipment, preserve the surface attachments in the copies, and show the complete construction preview for my approval. Do not apply or save yet.

Review, click **Apply to unsaved draft**, switch to **3D**, then use **Undo**.
Expected: 9 placements, 3 cells, 3 surface attachments; Undo returns to 3 placements
and no cells. Do not click Save during acceptance.

## Evidence

- `live-7/report.json`: actual Sage chat, four native tools, full candidate,
  explicit UI Apply, Plan/3D screenshots, exact layout/revision Undo, unchanged
  saved revision, zero page errors and failed requests. Chat-to-preview: 94.65 s.
- `live-8-recovery/report.json`: actual malformed-input recovery, complete
  unsaved Apply/Undo, duplicate approval no-op, stale approval rejected, correct
  copied supports, zero Save calls. 3D diagnostics: 9 placements, no degradation,
  no pending loads, real workstation and tooling-plate representation groups.
  Desktop and 390 px canvas-pixel checks were nonblank.
- `live-9-recovery`: genuine 1 m envelope refusal, but continuation stopped.
  This exposed the missing bounded continuation case; a regression test now covers it.
- `live-10-recovery`: failed acceptance because Sage skipped the requested
  negative test. A successful larger candidate alone was not counted as recovery evidence.
- `live-11-two-turn-recovery`: failed because the standalone command entered the
  older department-based cell workflow. A direct regression test covers the bypass.
- `live-12-two-turn-recovery`: provider failure followed by an unrelated semantic
  fallback. Construction-only tool exposure and fallback exclusion now prevent
  that substitution; their policy tests pass.
- `live-13-bounded`: correct geometric refusal and corrected three-step seed,
  followed by failed repetition using member IDs instead of the cell ID. The
  partial preview could not be applied. The schema and executable feedback now
  make the complete-cell seed requirement explicit.
- `live-14-cell-seed`: blocked by insufficient Anthropic credit balance. No
  post-fix live recovery success was claimed then. Provider requests stopped
  until the user restored credits.
- `live-15-confirmation`: the restored API worked, but the model stopped after
  Create Cell and incorrectly described three cells. The unchanged acceptance
  assertion rejected the three-command result before Apply. This led to explicit
  executed-command/count receipts and the bounded completion check.
- `live-16-completion-check/report.json`: the unchanged two-turn acceptance
  passed. The first turn produced a genuine 1 m envelope geometry refusal. The
  corrected turn executed all four commands, producing 9 placements and 3 cells.
  Chat submission to corrected preview took 60.29 s, including provider time but
  excluding the earlier refusal turn. UI Apply produced one unsaved history
  entry; repeated approval was a no-op, all three support relationships were
  correctly remapped, Undo restored the original document/revision, and the old
  approval then failed with `facility_command_stale`. Zero Save calls, page errors,
  and failed browser requests. The saved revision stayed
  `33d14bf718db07a7747623e7f405884b644d9a33e3f0c43cea5de603598ba21e`.
  The isolated pilot did not read or write the manual reference layout store.
- Screenshots from that passing run were visually inspected:
  `02-chat-preview.png`, `05-wide-3d.png`, and `06-narrow-3d.png`. The 3D scene
  contains real workstation/tooling-plate representations, 9 audited placements,
  zero transform mismatches, zero pending loads, and no degraded rendering.
  Both desktop and narrow-screen canvas-pixel checks passed. The narrow screenshot
  is only a canvas smoke check; the existing ribbon is not a fully mobile editor.

All paths above are under `.runtime/construction-sage-pilot/`. Failed attempts
are retained, not overwritten. These runs are not a latency benchmark or p95 claim.

Focused automated evidence: 201 JavaScript checks (patterns 23, adapter 8,
session 60, transport 27, workspace 83); schema/real-kernel parity is also covered
by Python tests. The final targeted construction/contract/service run passed 34
tests. Earlier broad execution passed 302 with one test import error; that import
was corrected and the affected service suite passed in the targeted rerun.
Across those earlier broad and targeted runs, all 304 unique focused Python cases
have passed. This is not a full-repository test-suite claim.
The construction/schema/knowledge rerun passed 39 tests, including the cell-seed
feedback. After the final completion change, 15 targeted tests passed, covering
both an interrupted recovery and premature stopping after grouping, plus shared
schema/real-kernel parity. The browser harness stops at the first provider error
rather than sending the subsequent correction. The two-turn live gate is closed.

The final post-live regression run passed **278 Python tests** in 242.33 s:
construction service/contract, agent integration, host, ordinary layout service,
knowledge foundation, and tool knowledge. Machine-readable evidence:
`.runtime/construction-sage-pilot/live16-final-tests.xml`. Together with the
passing actual chat/browser run, this is the evidence for this bounded pilot,
not a full-repository or sustained provider-reliability claim.

The passing run is reproducible with the unchanged acceptance assertions (use a
new output directory to preserve earlier evidence):

```powershell
python tools/capture_facility_construction_sage.py --exercise-recovery --output .runtime/construction-sage-pilot/live-review
```

It must record a real 1 m envelope geometry refusal, then the corrected four-command
chain in the same conversation, explicit unsaved Apply, duplicate-free approval,
correct support remapping, exact Undo, stale-approval refusal, and zero Save calls.

## Code Map

- `ai_inspector/facility_layout/construction_compiler.py`: native schemas and fixed Node bridge.
- `tools/compile_facility_construction_command.js`: existing builder invocation, operation capture only.
- `ai_inspector/facility_layout/construction_service.py`: source binding, artifacts, retries, approval.
- `server.py`: authorized provider loop, construction receipts, bounded recovery.
- `ai_inspector/facility_layout/host.py`: feature capabilities and preview/approval endpoints.
- `ai_inspector/facility_layout/service.py`: normal preview now publishes its resulting revision.
- `static/facility_layout_session.js`: deterministic compiler IDs and one-gesture installation.
- `static/facility_layout_transport.js`: scoped fetch and explicit unsaved approval.
- `static/facility_layout_workspace.js`: review pane, shared candidate view, stale/partial gates.
- `static/index.html`: server-owned preview delivery to the active workspace.
- `tools/capture_facility_construction_sage.py`: actual chat/browser acceptance, not fixture-provider substitution.

Broad rollout, dirty-draft adoption, sustained chat reliability, and performance
optimization remain separate milestones. Keep the flag off outside the pilot
until the integration and evidence receive independent review.
