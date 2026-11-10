# Documentation editor implementation plan

Date: 2026-11-09. Builder: Codex. Reviewer, independent tester and committer:
Claude. Approval covers Phases 0-5; P0 is committed and P1a is the current review gate. Read with
[the audit](documentation-editor-audit-and-strategy.md), especially sections
6.4-6.6 and 7, and [the capability matrix](documentation-editor-capability-matrix.md).
The user retains the PyMuPDF licensing decision. No release approval is inferred.

## 1. Delivery and scope

Keep the CAD publisher, existing ribbon, page canvas, managed assets, typed
engineering fields and existing Sage tools. Deliver inline typography, headings,
lists, find/replace, authored non-BOM tables, safe regeneration, a declared
PDF/DOCX subset and basic image/object controls. No Office replacement.

The original phases are too large for a single build session. The slices below
are separate review/commit gates, in order. Finish the named slice and its report,
then stop for Claude. Do not start the next slice until Claude reviews the diff,
runs its tests and isolated real-browser gate, and commits. Do not combine failed
slices into a larger checkpoint. Re-estimate after the P2 proof.

| Slice | Bounded deliverable | Report |
| --- | --- | --- |
| P1a | Read-bound service, atomic batches within each store, receipts | `P1a.md` |
| P1b | Citation integrity, UI, named-change undo and text-safe figure captures | `P1b.md` |
| P1c | Stable generated identities, three-way refresh and conflict UI | `P1c.md` |
| P2a | One authored-region Tiptap adapter under a development flag | `P2a.md` |
| P2b | Same region through PDF/DOCX; integration decision | `P2b.md` |
| P3a | Narrative typography, lists/styles, find/replace | `P3a.md` |
| P3b | Authored tables, stable cell identities and exports | `P3b.md` |
| P4a | Image/object controls and shared export object pass | `P4a.md` |
| P4b | Page presets, overflow, complete supported-export matrix | `P4b.md` |
| P5a | Scale, recovery, migration/rollback and accessibility | `P5a.md` |
| P5b | Independent browser regression and live desktop acceptance | `P5b.md` |

Each report uses CHANGED, TESTS, NOT RUN, DEVIATIONS and OPEN QUESTIONS, with
actual commands/results and the exact baseline changes approved by Claude.
Failed/skipped/unavailable checks are never reported as passed. A mock tool call
is not a live Sage run; a synthetic capture is not a live CAD capture.

Work stays inside this worktree. No network, installs, real stores, `.env*`,
credentials or saved sessions. No git index/history writes by Codex. Write LF;
keep `server.py`'s BOM and ASCII additions in it and `static/index.html`. Every
changed static JS URL gets a new `?v=`. New store names stay short. No bulk generated
trees or binaries in phase reports. Claude supplies dependencies and an isolated
code copy for testing, and vendors Tiptap before P2.

## 2. P0 baseline and limits

Run both `tools/documentation_baseline.py --inventory` and `--local --inventory`
before the gate. Tracked-only coverage and authorized local coverage are distinct.
Claude has copied the ignored engineering inputs into this worktree: the
documentation assembly registry, operations evidence JSON, MMLE specification
profile, process-map synthetic JSON, semantic-knowledge JSON, the MMLE and TR1631
local-library assets, `generated/training/mmle-50d-497533f6`, and the part-number
registry. These are locally excluded and must never be committed. Reading these
engineering inputs is authorized; credentials, environment files and real stores
remain out of bounds. The tracked MMLE golden is still an output oracle, not input.

The tool uses the tracked `_assembly_profile`, `_png` and `_valid_balloon`
fixtures in `tests/test_parts_manual.py` and the inspection fixture in
`tests/test_inspection_sheet.py`. It builds the synthetic parts manual, a generic
specification sheet and an inspection sheet; a separate synthetic cited table
exercises the scene and operations text adapter. It calls existing production
Python repository/build/export APIs without importing the server. The separate
`--local` section imports `server.app` through TestClient with dotenv disabled,
all five document roots and appearance roots patched to temporary stores. It
builds the MMLE operations manual, work instructions and reviewed specification
sheet through the production paths used by the existing tests. Its operations
probe edits page-specifications-1 / spec-table-1.r0.c1 from "1,100 lb" to "1,000 lb".
The real compiled row has only two cells, no claimIds/sourceIds or status column.
The probe records the block's retained evidenceClaimIds (including CLM-SPEC-001),
the top-level evidenceCitations authorities, and the changed row's presence in
PDF/DOCX text. It separately records the linked source-register wording and its
presence in both exports: OEM_CURRENT is rendered there as "Current manufacturer
source", not as an inline cell badge. Captures are synthetic, not live CAD proof.
The collector pins library discovery to this worktree's `400S_Sorted_Library` to
prevent fallback to the user's checkout; MMLE is loaded from the local registry.
For the full documentation suites Claude also sets `INSPECTORPRO_LIBRARY_DIR` to
the supplied assembly-library snapshot (100001 and the other library assemblies).
The local work-instruction probe pins its text edit to the figure-bearing cover's
`wi-cover-status`. Claude measured that this currently invalidates only the cover
capture: the next export returns 422 `work_instruction_capture_required`. Record
`textEditInvalidatesPageCapture`, `pagesNeedingCaptureAfterTextEdit`,
`textEditExportHttpStatus` and `recapturedPageIds` under `workInstructions` before
recapturing only the pending pages at the current revision through the production
artifact API. Then fingerprint the edited PDF/DOCX. P1b deliberately changes this
fact to false, with empty page lists and HTTP 200; it must list that expectation
change in P1b.md. Operations and specification capture probes are unchanged.

Claude also supplied locally excluded `generated/parts_manual/mmle-50d/`
`manual-plan.json` and `documentation-scene.json` for the isolated publication
smoke. These full files stay local; the scene is available as a real old-shape
migration source for P1a. The publication smoke produced 18 pages, 12 technical;
its old 15-page expectation was stale. The two old tricycle editor smokes are
unavailable because that assembly no longer exists in the user's library.
P1a's new editor smoke uses MMLE-50D and replaces those editor checks.

The baseline records semantic JSON SHA-256 values before/after/reopen, PDF text
SHA-256 and dimensions **per page**, DOCX `word/document.xml` text in paragraph
order including nested cells, no-write-on-read checks, and undo behavior. Clocks
and fixture ID generation are fixed; semantic normalization removes clocks only.
It retains evidence, source revisions, IDs, order, geometry and whitespace.
No PDF binary hashes are used. Temporary binaries are removed with the store.

Baseline files live in `docs/documentation-editor-reports/baseline/`. `expected.json`
and `expected-local.json` are separate, pending Claude's measured captures.
The corresponding `--check` must fail while pending; `--record` cannot overwrite
either file. When local inputs are absent, that section reports exactly
"skipped: local inputs absent" (CLI exit 3 / pytest skip), never passed. Inputs
present but broken, missing dependencies or export failures are errors, not skips.
Claude captures each section twice, compares
candidates, investigates differences, reviews output and replaces expectations
deliberately. Later reports name every changed fingerprint and the intended
behavior change. The P0 gate is not complete until that capture and browser check.
There is no longer a "supply sanitized MMLE inputs before P1" precondition.
Claude's reported current suite baseline is 326 passed, the pending baseline,
and one pre-existing failure:
`test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed`.
It fails identically in the user's real checkout; leave it unchanged and report
it separately. Every slice runs the documentation suites including MMLE.

See [P0 report](documentation-editor-reports/P0.md) for the current coverage,
export and undo matrices, licence inventory and runnable handoff.

## 3. Shared model and compatibility contract

### 3.1 Storage and versions

Existing versions: scene 2, parts document 4, operations document 1,
specification document 1, slots 1, work-instruction document 1 / plan 2,
inspection values 1. Preserve the existing parts plan version and narrow
`rebind_manual_plan` behavior. Inspection remains a typed form, not rich prose.

Supervisor decision for P1: add guarantees **in place**. DocumentationSceneRepository
in parts_manual/documentation.py remains the only owner of documentation-scene.json;
SlotStore in specification_sheet/slots.py remains the only owner of slots.json.
There is no authoritative envelope, reader cutover, cross-file transaction, or
cross-process lock. The desktop's single backend process is assumed. Each owner
uses its process RLock around read/check/stage/fsync/replace. The host holds those
same locks while compiling effective target hashes; repositories do not compile.

P1a scene schema 2 -> 3 adds editRevision (monotonic integer), editEpoch,
fieldVersions, receipts and receiptOrder. Rendering identity excludes these
transaction fields and uses the historical schema-2 projection. Old command
entries replay exactly as before. New batch history entries contain operation
"batch", commands, requestId and actor; they replay and undo/redo as ONE step
through the existing historyCursor. A legacy apply_command remains compatible
and advances mutation counters. No second undo stack is introduced.

Slot schema 1 -> 2 adds the same transaction fields inside slots.json. Value,
row, settings and compound operations stage all their changes before one write.
Slot undo remains P1b work. The two stores have independent monotonic revisions.
A documentId is UUID5(namespace, documentType + normalized assemblyNumber), never
a long directory name. Reads also return source/plan bindings and opaque scene
revision when applicable. There is no single undo group spanning slots and page text.

Read migration is pure: old files upgrade in memory with unchanged rendering and
no write on open, export or read. The first explicit write preserves original
bytes atomically beside the file as documentation-scene.v2.json (also accepts the
older v1 scene input) or slots.v1.json. Subsequent writes retain that rollback
input. A differing pre-existing backup rejects the upgrade. Unknown future
schemas are refused with a schema error and their bytes are never overwritten;
this slice does not attempt to render a future format it cannot validate.

Under the scene/slot lock, validate document/source bindings, look up the receipt
before stale checks, compare every observed target hash, stage and validate the
entire candidate, then replace once. Retained identical retries return the
original receipt; same requestId with a different payload is request_id_reused.
The host passes current effective hashes and the scene revision they describe;
a stale unlocked snapshot cannot authorize a write. Every affected target must
have a matching pre-image and no open conflict, including with an older observed
revision. Future revisions fail. Manual legacy scene routes keep their stricter
baseRevision check; Sage batches and bound slot writes allow matching older reads.

Retain the newest 1,000 receipts in commit order, keyed by request IDs of 1-128
characters. Eviction happens in the same atomic write. Include monotonic per-field
and structural mutation counters in hashes, advancing them on every mutation,
undo and redo. Thus evicted retries cannot apply a change twice even after an
undo or change-then-revert. Unrelated writes do not invalidate target hashes.
Bounded requests are at most 256 KiB; scene history retains its existing 2,000
entry cap and scene files are limited to 16 MiB. A no-op changes no content,
revision or cursor; its receipt may be persisted as transaction metadata.

Future slices version additive keys in these same stores: P1b adds fieldMeta and
named-change metadata (including a slot undo journal); P1c adds identities,
generatedBaseline, conflicts, orphans and refresh receipts where relevant.
P2a adds versioned richText, P3 advances its typography/table schema, and P4 adds
object and page-setup metadata to the scene. Assign each store's next version at
that slice, with pure read migration and old-shape fixtures. Generated parts
documents advance 4 -> 5 in P1b and 5 -> 6 in P1c; operations/specification/work
advance 1 -> 2 -> 3 for provenance and identity. Rich payloads carry their own
version and advance generated-document versions when first introduced.

Keep a reduced, sanitized old MMLE scene under tests/fixtures/documentation_editor/.
Test exact bytes before/after read, preserved history/projection, original-byte
backup on first write, restart, retry and refused unsupported versions. Rollback
restores the pre-upgrade file into a separate temporary store; it does not promise
that an old executable understands new edited content. Keep new files for recovery.

### 3.2 Target identity, hashes and bindings

All reads include `documentId`, `revision`, `sourceRevision`, `manualPlanRevision`.
A hash covers the complete field value **and** its provenance, rich text,
relevant type attributes and fieldVersion, using UTF-8 canonical JSON (sorted keys, no NaN,
no Unicode/whitespace normalization). Return `hashVersion: 1`. Keep source and
document revision separate. Hash absence never means "use whatever is current".

Stale document revision alone is not a rejection. Under the store lock, accept
`expectedRevision < currentRevision` when **every target and structural dependency
pre-image hash still matches and none has an open conflict**. Thus a human change
to another field does not bounce Sage's write. If a hash differs, a dependency
was deleted/rebound or a target has an open conflict, reject the entire batch
with `content_hash_mismatch`, `stale_revision` or `manual_edit_conflict` as applicable.
Future revisions and changed document/source bindings are rejected. This rule
applies to Sage batches and bound slot writes. Existing manual scene commands
keep the stricter exact baseRevision requirement. Conflict-resolution operations instead
validate the explicitly named conflict's hash and all affected field hashes;
they are the only operations allowed to resolve an open conflict. The receipt
records `expectedRevision` (requested), `beforeRevision` (actual commit base) and
`revision` (result). Reading or retrying never rewinds the document revision.

Existing part description IDs remain definition-keyed. Rows, columns, cells,
blocks, list items and authored objects get persistent IDs; page placement is
not identity. Generated IDs derive from compiler-owned source keys, not visible
text or the current array offset. Authored IDs are allocated once. A cell is
addressed by table/row/column identity; merge retains the anchor cell and records
covered cells. Deleted identities remain tombstoned for conflict/orphan recovery.

Legacy `.rN.cN` / `.iN` aliases are supported only in a **read revision's** alias
map. A write from that read resolves the alias to its stable ID. Migration records
the original row/item fingerprint and source binding. If the original generated
baseline is unavailable, repeated rows make the mapping ambiguous, or the source
has changed, hold the override as an orphan. Never guess using nearest index.

### 3.3 Sage API: compatible additions

Keep all names, current inputs, authorization and output keys in
`ai_inspector/codex_runtime/documentation_tools.py`. This includes specialized
specification/inspection tools and publication queues; do not replace them with
the illustrative tool names in audit section 6.3. Updates to any schemas/catalog
must also update `test_codex_readonly_pilot.py`, `test_codex_assisted_tools.py`,
`test_codex_documentation_tools.py`, `test_codex_specification_sheet_tools.py` and
any other list pin found by searching the exact tool name.

`read_document_pages` retains `{documentType, fromPage?, pageCount?}` (six-page
limit). Add optional `documentId`, and `targets: [{pageId?, targetId}]` (1-12).
Without targets retain paged summaries, labeling each truncated string with
`isExcerpt`, `fullLength`, `contentHash` and `targetId`. Targeted reads return
`text` in full, `isExcerpt: false`, `richText?`, `provenance`, capabilities and
binding. Do not normalize whitespace. Retain the 64-KiB result guard: reject an
oversized multi-target read with `read_result_too_large` and target sizes; the
caller retries one target. Cap stored rich fields at 32 KiB of canonical JSON
so a single eligible target always fits. Old strings are still readable in
full, with an explicit size error if a legacy oversized field cannot fit.

`edit_document_text` retains `{documentType, edits:[{pageId,targetId,text}]}` and
the 12-edit/2,000-character compatibility limit. Add optional `documentId`,
`expectedRevision`, `requestId`, and per-edit `expectedContentHash`. Output retains
`changed` and `note`, adding `receipt: {requestId, changeId, documentId,
expectedRevision, beforeRevision, revision, changedIds, undoable, validation, payloadHash}`.

For old callers, the gateway binds edits to its most recent read snapshot for
each target in the current turn; use that read's revision/hash even if the fields
are omitted. An edit without a read is accepted by the schema but safely returns
`document_read_required`, with instructions to read; it never fills preconditions
from a last-minute host read. An excerpt is not replacement material: require a
full targeted read before replacement (`full_read_required`). Legacy reads keep
working; unsafe legacy behavior deliberately changes. No silent stale overwrite.

Legacy retries receive a gateway-assigned request ID based on turn, document,
read snapshot and canonical arguments, retained across transport retry. Explicit
client IDs are preferred. Same ID/same payload returns exactly the original
receipt; same ID/different payload yields `request_id_reused` without mutation.
Receipt lookup follows authorization/document binding and precedes stale revision
checks, so a genuine retry succeeds after intervening edits. A new intended edit
requires a fresh read/request ID. The host receives the captured preconditions.

P1a adds `apply_document_edits`:

```text
input: documentId, expectedRevision, requestId, operations[1..12]
operation (tagged union):
  replace_text {targetId, expectedContentHash, text}
  set_slot_value {targetId, expectedContentHash, value}
output: {receipt: <above>, changed: [stable target IDs]}
```

A request cannot span stores. Mixed text/value operations return
`invalid_document_operation`: "send text and value edits as separate requests".

The service infers actor from the authenticated host context. Slot numeric/source
restrictions still apply; raw `source`, `accepted` or `actor` supplied by Sage
cannot grant authority. Mixed slot/scene batches belong to one document only.
New rich-text/table/object operation unions are added in their owning slices.

P1b adds `inspect_document_change {documentId,changeId}` and
`undo_document_change {documentId,changeId,expectedRevision,requestId}`. Return a
structured before/after summary and receipt, not arbitrary filesystem paths.
P1c adds `read_document_conflicts {documentId,from?,limit?}` and
`resolve_document_conflicts {documentId,expectedRevision,requestId,
resolutions:[{conflictId,expectedConflictHash,choice,mergedText?}]}`.

Specialized-tool compatibility in P1a/P1b:

| Existing name(s) | Additions; original inputs and guards retained |
| --- | --- |
| `inspect_documentation_context`, `inspect_documentation_type`, `inspect_parts_manual_bom` | Add binding/revision, capability and full-value hash metadata; preserve existing context/BOM keys and read-only classification. Context's slot descriptors carry full values/provenance and hashes. |
| `provide_document_values`, `record_researched_values`, `draft_specification_text`, `edit_specification_sheet` | Add optional documentId/expectedRevision/requestId; optional expectedContentHash on value/target items. Gateway supplies omitted preconditions from the captured sheet read. Keep user-stated value, quotation, researched/unreviewed and number-validation rules. Return existing result plus receipt. |
| `accept_specification_values`, `approve_specification_template` | Same additive request preconditions/receipt, existing explicit-user-approval checks unchanged. Approval cannot be inferred from a text-edit request. Template registry mutation remains its own guarded operation, never an implicit side effect of a document batch. |
| `propose_specification_template` | Keep proposal schema and behavior; add proposal revision to output. Shared template lifecycle stays separate from per-document undo. |
| `export_specification_sheet`, `run_documentation_workflow` and workflow names in `WORKFLOWS` | Preserve current options/queue contracts. Bind queued work to documentId/revision; attach job status and final artifact revision without presenting a queue receipt as completion. |
| `move_parts_manual_parts` | Preserve current move schema and narrow rebind behavior; add optional expectedRevision/requestId and receipt; do not replace its membership validation with table edits. |
| `build_inspection_sheet`, `provide_inspection_sheet_values` | Keep specialized inputs/output and permission checks; add document binding to output. No generic prose/undo capability or signature-writing authority added. |

Machine/library/appearance/dimension tools keep their schemas unchanged. Full
targeted page reads may add specification to the accepted documentType enum, but
must retain the three existing values and typed-slot capabilities. The older
`edit_document_text` tools must never expose editable CAD ITEM/QTY merely because
the new read has a stable target ID for them.

Errors retain existing outer `{ok:false,error:{code,message,details?}}`. New codes:
`document_read_required`, `full_read_required`, `document_binding_changed`,
`stale_revision`, `content_hash_mismatch`, `target_not_found`,
`ambiguous_legacy_target`, `read_only_derived_field`, `invalid_document_operation`,
`request_id_reused`, `document_busy`, `legacy_store_changed`,
`manual_edit_conflict`, `undo_conflict`, `unconfirmed_cited_values`,
`unsupported_document_schema`, `read_result_too_large`, `layout_overflow`, and
`unsupported_export_feature`. Include operation index and target ID for validation
failures; **zero** operations commit on any batch failure. Existing error codes
outside these paths remain unchanged. Preserve HTTP compatibility error fields
and add the canonical service code in details when an old route pins its code.

Playbook text added to `SERVER_INSTRUCTIONS` and relevant documentation skill
prompts in the repo (these are app prompts, not authorization for this builder):

> Read the loaded document and the complete targets before editing. Keep the
> document ID, revision and content hashes from that read. Summary excerpts are
> not complete replacement text. Submit related changes together with one request
> ID; retry the identical request after a transport failure. On stale/conflict
> errors, read again and preserve newer user work. Edited evidence-bound values
> are manual text, not facts established by their former sources. Never restore
> an OEM/approved label by editing prose. Read conflicts and resolve only the
> requested targets. You may propose that the user confirm an edited cited value,
> but only the user can confirm it in the UI. Report a queued export as queued
> until its final receipt.

### 3.4 Citation integrity

The P0 local run establishes a compilation gap: `document.py::_specification_rows`
has per-row claimIds/sourceIds in plan rows, but the generated MMLE prototype
table has only `rows:[{cells:[...]}]`, block-level `evidenceClaimIds`, and top-level
`evidenceCitations`. In particular, spec-table-1 row 0 has two cells, "Rated
capacity" and "1,100 lb". `content.py::prototype_sections` supplies unannotated
rows to `_table`; `flow.py::_place_table` preserves row keys it receives but
cannot recover missing bindings. Do not infer a third authority column or use
the synthetic baseline's annotated rows as the compiled-document contract.

P1b's generated operations document schema 1 -> 2 adds
`evidenceBindingVersion:1` on annotated blocks and additive `claimIds`/`sourceIds`
on their rows (and list items where a precise binding exists). Carry the explicit
plan/registered-claim relation through content construction and pagination into
compiled blocks; preserve each binding on split row fragments. Keep the existing
block and document citation keys for compatibility. Test old schema-1 two-cell
blocks and their positional overrides: migrate in memory without rewriting stores
or guessing row bindings from current text/positions. Use explicit source-plan
bindings when provable; otherwise retain the conservative block-level fallback.

P1b `fieldMeta[targetId]` contains `origin: generated|manual`,
`evidenceStatus: source_backed|edited_unverified|entered_by_user|unbound`, original `claimIds`,
`sourceIds`, source revision, generated value/hash, edit change ID and actor.
Keep original links under `originalEvidence` for audit. Active claim-support lists
exclude an edited value; they must not assert the source gave the new text.
Formatting-only changes that leave the exact semantic value unchanged do not
invalidate a citation. Changing numbers, words or units does. Undo restores the
previous provenance with the value; replacing text back to an old string is not
an implicit evidence acceptance or a new approval.

An edit to a bound row invalidates only that row's supporting claim links; other
rows retain their claims, even when they share a source. Where a row binding
exists but the claim-to-cell relation is unknown, mark the affected row. Only
where no row binding exists, mark the entire cited block conservatively.
Paragraphs are marked at block level; lists use item bindings when available,
otherwise block level. Display "Edited - source does not verify
this value" beside that field/row and in its properties; the reference panel may
still show "Original source". No "OEM current" badge on the new value. Compile
the same effective metadata into document JSON, Sage reads and export adapters.
Review/draft PDF and DOCX show the edited marker and legend near the table/block
(not metadata alone). Workspace and Sage reads retain the distinction. Preserve
the customer copy's existing absence of generation commentary, covered by
`test_customer_copy_has_no_orphan_or_generation_commentary`.
The source's own authority is unchanged; the link supporting this value is not.

For customer/controlled export, every edited cited value must be reverted to its
generated source-backed value or **confirmed by the user through a UI action**.
Unconfirmed values block that export with `unconfirmed_cited_values` and the exact
target list. A visible "Confirm as entered by me" action shows the value and
former source; the backend records `confirmation:{by,at,changeId,valueHash}` from
the authenticated user context, sets provenance to `entered_by_user`, and removes
that value's active OEM/source citations. Historical links stay in originalEvidence.
The customer copy then prints the confirmed value without a warning and without
an OEM citation for it. Other unedited values may still cite the same source.
Use the same binding scope for confirmation and export gating: the affected row
when row bindings exist, otherwise the whole block (or bound list item). Do not
leave an ambiguous source citation beside the confirmed scope. A whole-block
confirmation must show every affected value and require the user's explicit action.

Follow the explicit-approval checks of `accept_specification_values`, with a
stricter authority boundary for this new confirmation: no Sage tool or supplied
actor field may execute it, even if Sage says the user agreed. A UI-only endpoint
`POST /api/documentation/{documentId}/confirm-values` takes expectedRevision,
requestId and `{targetId,expectedContentHash}` items; the server requires trusted
human interaction/authority, logs the confirmation and returns one transaction
receipt. Sage may expose `propose_document_value_confirmation` with the same
target/hash list to offer a UI action, never to mutate confirmation. Proposal
output is `{proposalId,documentId,targets,status:'awaiting_user'}`. Do not conflate
that proposal with a confirmation receipt. Hash/revision validation still applies
to the later click. Confirmation is undoable; editing the confirmed value again
clears confirmation and returns it to edited_unverified. It is not source approval
or a bypass of other controlled-release prerequisites.

Legacy positional overrides on cited fields are detected on read and displayed
as edited conservatively, without modifying disk. Specification slots retain
their existing `overrides_evidence`/`overrides_cad` findings, acceptance gates and
source distinctions. No new tool may accept engineering facts on behalf of a user.

### 3.5 Refresh and conflict resolution

Retain `rebind_manual_plan` for the existing narrow parts-section move. General
regeneration must call the shared refresh service, not destructive `rebaseline`.
Compare old generated baseline B, current authored value C and new generated N:

| Condition | Stored/displayed result |
| --- | --- |
| C == B; N changed | Adopt N and its provenance |
| C changed; N == B | Preserve C exactly, including marks and manual provenance |
| C == N | Keep value; retain manual status unless explicit supported evidence acceptance occurs |
| Both changed differently | Keep C; persist a conflict with B/C/N and old/new evidence |
| Source row reordered | Move by stable identity; keep manual fields |
| Source deleted/changed identity | Keep manual content in `orphans`; mark link stale |
| User-only object/table/paragraph | Preserve content, frame, ordering and identity |
| Complete reset explicitly requested | Show affected IDs/count, retain recoverable version, then execute authorized reset |

Conflicts live in `edit.json`, not ephemeral browser state: short `conflictId`,
target, kind, B/C/N payloads and hashes, old/new source refs, created revision,
status and resolution receipt. Store source-less identities as orphans rather
than attaching them to a new row. Resolve uses `keep_manual`, `use_generated`,
`merge_text`, or `detach` for an orphan. Reattach requires an explicit new target
and hash, never fuzzy text matching. Recompute citation status after resolution;
`merge_text` remains edited. `use_generated` takes exactly the generated payload
and its current evidence status; it does not invent an approval.

Workspace: persistent conflict count in the documentation status bar; a review
pane lists field/page, current text, prior baseline, proposed generated text and
evidence changes. Selecting a conflict focuses/highlights the target. Deleted
targets are shown under "Unplaced manual content" with restore/detach controls.
Buttons offer the same choices as Sage. Unresolved conflicts survive reopen,
appear in Sage reads, and mark review exports; controlled exports are blocked.
Resolution is one undoable transaction, with expected conflict hash and revision.
Later refreshes update proposed N without replacing C or losing the original B;
resolved conflicts stay in the audit history. New generation failure commits
nothing. Missing legacy baseline is a conflict, never permission to clear edits.

## 4. Phase 1 implementation slices

### P1a - read-bound atomic edits

Change/add commands.py and targets.py under ai_inspector/documentation/;
parts_manual/documentation.py (pure candidate command function and in-place
apply_batch), specification_sheet/slots.py (staged transactions), server.py host
and additive request bindings, codex_runtime/documentation_tools.py and playbook,
and the pinned tool tests. Remove the superseded edit_store.py foundation.
Frontend documentation_commands.js captures the displayed document/revision at
edit start. Keep existing save routes; stale saves report a clear error, reload
only the bound model, and preserve the visible draft. Delayed responses cannot
retarget the active document after switching. Version its script URL.

Implement section 3's in-place guarantees. edit_document_text submits one scene
batch rather than committing each edit independently. apply_document_edits permits
one store per request: mixed replace_text/set_slot_value operations return
invalid_document_operation with "send text and value edits as separate requests".
Existing specialized slot tools retain their authority rules and inputs, adding
optional preconditions and receipts. Internal validation reads never authorize
an unseen mutation. No provenance, named undo, refresh or rich text in this slice.

The ownership test scans production server.py and ai_inspector/ Python with
AST/literal checks, including assigned names and indirect path helpers. Only
parts_manual/documentation.py may own documentation-scene.json and only
specification_sheet/slots.py may own slots.json. Keep an explicit reviewed
(file, function) allowlist, initially empty. Test fixtures/tools are outside the
production scan. There is no reader/writer cutover: all existing callers continue
to use their existing repository, with guarantees implemented there.

Tests cover v2 scene/v1 slot reads without writes, one-time byte backups,
atomic invalid-second-operation failure, single cursor batch undo/redo, stale
hash rejection, matching older-revision acceptance, open-conflict rejection,
future revision/source-binding refusal, retained receipt retry after restart,
request-ID reuse, bounded eviction including undo/structural ABA, two threads
racing one read, denied replace, and crash after commit/before response. Gateway
tests cover full whitespace-preserving reads, excerpt refusal, old inputs,
explicit tool schema, separate-store refusal and specialized value authority.

Gate: section 9 commands plus
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_store_chokepoint.py
and python tests/smoke_documentation_editor.py --phase P1a.
The real MMLE browser smoke double-clicks text, commits, rejects a stale Sage-host
HTTP request, reopens, checks original bytes and disk receipts, retries a two-target
Sage batch, undoes it in one UI step, and switches documents during a delayed save.
It redirects all five document roots and both appearance roots to a temporary
snapshot, blocks outbound traffic and emits JSON/nonzero failure status. Claude
runs it; a deterministic host bridge is not a live provider inference test.

### P1b - provenance, undo and text-safe figure captures

The next additive scene/slot versions add fieldMeta and named-change metadata
without rewriting old stores on read. Change
`documentation/commands.py`, add `provenance.py`, update operations/specification/
work document compilers and their `exports.py`, `codex_runtime/documentation_tools.py`,
`server.py`, `static/documentation_commands.js`, `index.html` and pinned tests.
Also change `operations_manual/content.py` and `flow.py` to carry explicit
row/item claimIds/sourceIds through content construction and pagination, with
generated document schema 2 / block evidenceBindingVersion 1 as in section 3.4.
Current compiled rows have only cells; block evidenceClaimIds alone cannot prove
which row a claim supports. Preserve old shapes on read with block fallback.
Implement section 3.4, including export markings and source-support summaries.
Add inspector/undo/conflict messages through agent display-name lookup.

Work instructions must keep figure captures across text-only edits, including
`page-work-instructions-cover / wi-cover-status`. Today `_apply_scene` copies the
entire page composition into renderRequest, so its text overrides change the
figure request and defeat capture carry-forward. In the work-document schema
1 -> 2 transition, add `figureRevision` derived from source/plan/render-pipeline
identity and effective CAD figure requests, excluding paragraph/cell text,
typography and nonfigure page composition. Include camera, pose, occurrence
visibility/transforms, callouts and other inputs that actually change the capture.
Do not merely delete all composition from the hash: genuine figure edits must
invalidate the affected capture. Preserve other pages with unchanged requests.

Bind work-instruction capture storage, attachment, readiness and export lookup
to that figure revision, following specification's figureRevision binding and
operations' preservation of unchanged figure requests. Keep documentRevision
for text/export identity, and project ready images onto the current document
revision. Change `work_instructions/document.py`, `exports.py`, the work routes
and builders in `server.py`, and the shared `operations_manual/artifacts.py` only
where necessary without changing operations/specification behavior. Additive
figureRevision capture inputs remain optional for existing callers. Old generated
documents/artifacts without figureRevision load through a validated legacy lookup
by documentRevision and unchanged figure request; compute the new identity in
memory, never rewrite old stores/artifacts merely on read or accept a stale figure.
Cover that old shape and first-mutation adoption in tests.

Named undo is an inverse transaction, not a shared cursor jump. Compare each
affected field's current content/provenance with the chosen change's after-state;
revert all or report `undo_conflict`. Unrelated later edits remain. Deletions,
table structure and compound slot row operations compare their dependency set.
Redo is an equally guarded inverse of the undo. Frontend Ctrl+Z outside an active
editor and scene undo endpoints use one scene group. Slot undo uses its own slots.json
journal; there is no cross-store undo group. Existing
inspection measurements/signatures stay on their current guarded form path and
are explicitly not advertised as generic document undo.

Add `tests/test_documentation_provenance.py`:
`test_cited_cell_edit_invalidates_support`, `test_legacy_override_marked_edited`,
`test_plan_row_bindings_survive_compilation_and_pagination`,
`test_capacity_edit_preserves_other_rows_claims`, `test_old_compiled_block_uses_conservative_fallback`,
`test_paragraph_and_list_item_binding_scope`,
`test_format_only_preserves_citation`, `test_pdf_docx_and_sage_show_edited`,
`test_slot_overrides_keep_existing_findings`, `test_unconfirmed_customer_export_blocked`,
`test_user_confirmation_removes_active_citation`, `test_sage_cannot_confirm_value`,
`test_confirmation_stale_click_rejected`, `test_confirmed_customer_copy_has_no_warning_or_oem_citation`,
`test_edit_clears_confirmation`. Keep the existing customer-copy test passing. Add
`tests/test_documentation_change_undo.py`: `test_slot_batch_one_undo`,
`test_named_undo_preserves_later_human_edit`, `test_overlapping_undo_conflicts`,
`test_undo_restores_provenance`, `test_old_command_history_migrates`.

Add `test_a_text_edit_keeps_the_figures_captured_and_a_figure_edit_does_not` to
`tests/test_work_instruction_workflow.py`, mirroring the operations test: capture
all pages, edit the cover text, assert documentRevision changes but figureRevision
and ready captures remain, export PDF/DOCX with no recapture, then change a figure
and require only its recapture. Add `test_legacy_work_instruction_capture_opens_unchanged`
for the pre-figureRevision document/artifact shape and no-write-on-read behavior.
The local baseline must flip `textEditInvalidatesPageCapture` from true to false,
both page lists to [], and `textEditExportHttpStatus` from 422 to 200; list those
deliberate expectation changes in P1b.md.

Gate: shared section 9 checks, plus:

```text
python -m pytest -q tests/test_documentation_provenance.py tests/test_documentation_change_undo.py
python -m pytest -q tests/test_work_instruction_workflow.py::test_a_text_edit_keeps_the_figures_captured_and_a_figure_edit_does_not tests/test_work_instruction_workflow.py::test_legacy_work_instruction_capture_opens_unchanged
python -m pytest -q tests/test_operations_manual_workspace.py::test_a_text_edit_keeps_the_figures_captured_and_a_figure_edit_does_not
python tests/smoke_documentation_editor.py --phase P1b
```

Expected: edit a sourced capacity, reopen, read through Sage and export a review
copy; all show edited/unverified, with no source-current claim for the changed
row, while the other specification rows retain their source bindings. Repeat with
an old block lacking row bindings: the whole block is marked; paragraph/list scope
follows section 3.4. Customer export blocks until the user reverts or confirms in the UI;
confirmation produces clean customer text with entered-by-user provenance and
no OEM citation for that value. Sage's proposal cannot confirm it. Undo restores
original text/provenance in one action. In the browser, capture the MMLE work
instructions, edit cover text and export without recapture; a real figure change
must still require capture. Inspect PDF and DOCX visually,
not just text hashes. Risk: bindings may be absent or row-wide; use the explicit
row/block fallback and explain its scope. Leave source reapproval workflows and inspection undo
out; user confirmation as entered-by-user content is included in this slice.

### P1c - stable identity and safe refresh

The next additive scene/slot versions add identities, generatedBaseline, conflicts
and refresh receipts, with generated-document versions from section 3.1. Add
`documentation/identity.py`, `refresh.py`; change parts `document.py` and
`documentation.py`, operations/work/specification `document.py`, server builders,
tools, `static/documentation_conflicts.js`, `index.html`, and prompts. Source data
is never rewritten to store publication identities. Existing part definitions
and approved plan IDs remain authoritative. Keep old positional aliases scoped
to reads and test their refusal after reorder.

Add `tests/test_documentation_refresh.py`: `test_three_way_policy`,
`test_reorder_follows_ids`, `test_duplicate_rows_are_not_guessed`,
`test_deleted_part_keeps_commentary`, `test_missing_baseline_preserves_orphan`,
`test_conflict_persists_on_reopen`, `test_resolution_requires_current_hash`,
`test_resolution_undo`, `test_rebind_manual_plan_still_preserves_captures`,
`test_failed_generation_commits_nothing`, `test_old_shape_no_save_on_read`.
Use old JSON with positional table/list overrides and real compiler fixtures.

Gate: pytest file and `smoke_documentation_editor.py --phase P1c`. Browser edits a
description and unrelated note, then a fixture source revision reorders a BOM and
changes the same field; notes survive, changed field shows a persistent conflict,
and user/Sage resolution agrees. Repeat after restart. Risk: actual old baseline
may be missing; expose an orphan, do not claim automatic migration. No automatic
fuzzy matching, multi-user CRDT or unrequested full rebuild.

## 5. Tiptap delivery contract before P2

No frontend build step is introduced. Claude delivers one prebuilt ESM bundle
`static/vendor/tiptap/tiptap.bundle.js`, `LICENSE`, `THIRD_PARTY_NOTICES.txt`,
`VERSIONS.md`, exact dependency lockfile and the reproducible bundle entry/build
recipe. Record bundle/package/license SHA-256 values and include every transitive
ProseMirror licence. No imports from CDN URLs, npm bare specifiers or Node APIs
may remain inside the bundle. Review the compiled artifact, not only package names.

**Exact pin: 3.33.0 for every @tiptap package below.** Claude verified these
versions and MIT licences on npm in the P0 review, including extension-unique-id.
This builder did not use the network. Claude will verify the actual named exports
while building the bundle and report any difference before P2a. Gate P2 on the
manifest, licence records, offline import and export-shape tests; no mixed versions.

| Exact package, all pinned 3.33.0 | Purpose / bundle exports |
| --- | --- |
| `@tiptap/core` | `Editor`, `Extension`, `Node`, `Mark`, `mergeAttributes` |
| `@tiptap/pm` | ProseMirror peer substrate, bundled; no public app export required |
| `@tiptap/starter-kit` | `StarterKit`: document, paragraph, text, hardBreak, heading, bold, italic, strike, blockquote, code/codeBlock, bulletList, orderedList, listItem, link, underline, undoRedo, gap/drop cursor and trailing-node support as supplied by pinned v3 |
| `@tiptap/extension-text-style` | `TextStyle`, `Color` (P2); `FontFamily`, `FontSize`, `LineHeight` (P3a) |
| `@tiptap/extension-unique-id` | `UniqueID` (P2a authored-node IDs, extended to table nodes in P3b) |
| `@tiptap/extension-highlight` | `Highlight` |
| `@tiptap/extension-subscript` | `Subscript` |
| `@tiptap/extension-superscript` | `Superscript` |
| `@tiptap/extension-text-align` | `TextAlign` |
| `@tiptap/extension-table` | `Table`, `TableRow`, `TableCell`, `TableHeader` (named v3 exports) |

Those are the **complete runtime export list**, with the core five and StarterKit
plus the named extension exports above. BackgroundColor is available from
extension-text-style in v3 but is not exported by this bundle: the planned range
highlighting uses Highlight, so no slice needs a second background-color mark.
Do not also register standalone duplicate
paragraph/list/link/underline/history extensions. Disable starter-kit code,
codeBlock, blockquote and horizontalRule initially; configure allowed headings,
links and list depths. P2 needs core/StarterKit/TextStyle/Color/UniqueID; P3 enables the
remaining typography/table extensions; P4 uses the same bundle. Prefer the bundled
FontSize, LineHeight and UniqueID extensions over local replacements. Configure
UniqueID to preserve persisted authored IDs, with server validation for duplicates,
paste collisions and document ownership; it must not regenerate compiler-owned
CAD/source identities. Only unsupported paragraph spacing/indent and bounded
table style attrs need small local extensions, with server validators/export maps.
No Tiptap image, collaboration, AI, Pages, conversion, React/Vue, floating-menu,
bubble-menu or proprietary package is required. Managed images stay page objects.

`index.html` loads one versioned adapter module:

```html
<script type="module" src="/static/documentation_rich_text.js?v=1"></script>
```

The adapter imports named exports from
`/static/vendor/tiptap/tiptap.bundle.js?v=<reviewed-bundle-sha-prefix>` and exposes
a narrow `window.DocumentationRichText` interface for the existing classic-script
workspace. It supplies readiness and mount/dispose methods; the workspace awaits
readiness. Do not add Tiptap entries to or alter the existing Three importmap.
The bundle is self-contained. Disable the feature gracefully if the import fails;
keep old fields readable and never save lossy plain text over unsupported rich data.

## 6. Phases 2 and 3 - rich text and tables

### P2a - one-region editor

Change/add `documentation/rich_text.py` (schema/plain-text projection/validation),
`documentation/commands.py`, `static/documentation_rich_text.js`,
`static/documentation_rich_text.css`, `index.html`, and the tool schema pins.
Envelope 4 stores `{format:'tiptap',schemaVersion:1,doc:<allowlisted JSON>}` per
eligible authored field. Plain `text` in responses is a **derived** projection;
it is never a second canonical editable value. Unedited old strings remain
strings. Conversion on first rich edit preserves all newlines/whitespace with
tests; typed specification quantities, BOM numbers/quantities and inspection
fields never mount Tiptap.

Flag `documentationRichText` defaults off during proof. Mount one editor only
inside an existing manually authored text object on a specification page (which
already has both PDF and DOCX paths). Parts-page support is exercised by the same
adapter. Paragraphs, hard breaks, B/I/U, color, safe links, H1-H3 and lists only.
Reject arbitrary HTML, script/event attributes, external media and unapproved
URL schemes. Plain/HTML paste is normalized through the same allowlist. Untrusted
content cannot become a model instruction or a local file link.

Ribbon pointer handling preserves editor selection; editor focus suspends page
drag and CAD keyboard shortcuts. Escape cancels the draft; compositionend precedes
commit; blur/save commits one transaction. In-focus undo is local; after commit,
clear/rebase local history and document undo owns the group. An incoming agent
write cannot destroy a dirty draft; show a conflict and keep the draft available.

Add operation `replace_rich_text {targetId,expectedContentHash,richText}` to
`apply_document_edits`, capability-gated. Old `edit_document_text` on a rich field
replaces the entire field with a plain paragraph only when the user requested a
whole-field replacement; reads expose that consequence. For a range change use
the P3 semantic operation, never raw editor steps. Existing tools keep working.

Add `test_documentation_rich_text.py`: `test_plain_text_lossless_migration`,
`test_unsupported_nodes_rejected`, `test_link_scheme_allowlist`,
`test_old_scene_no_rewrite`, `test_rich_hash_and_plain_projection`.
Gate: pytest file, vendor checksum/export-list check in the smoke script and
`smoke_documentation_editor.py --phase P2a`. Test selection/ribbon, multiline
paste, emoji/combining marks, dirty-edit concurrency, Escape, local/document undo,
reload and disposal. Claude performs real IME composition manually in addition
to automated composition-event checks. Risk: mount/focus integration; leave flag
off and exports reject rich fields until P2b passes. No broad narrative rollout.

### P2b - proof exports

Add `documentation/rich_layout.py` for a bounded run/paragraph layout contract;
extend parts `pdf.py`, operations/specification `exports.py` and work instruction
delegation. Use existing PyMuPDF and python-docx only. Add a narrow shared text
object export path for the proof region; no general graphics expansion yet.
Render marks, line breaks, links, heading/list levels and list numbering in PDF
and native DOCX runs. Fixed frames report overflow; no silent clipping or
flattening to a whole-page bitmap. Preserve old plain rendering exactly.

No schema or new Sage names. Add `test_documentation_rich_exports.py` with mixed
runs/lists, whitespace/Unicode, link annotations, unedited legacy export equality,
object presence, and explicit overflow tests. Gate: that file plus P2a tests and
`smoke_documentation_editor.py --phase P2b`. Export the exact browser-authored
region, reopen, edit it through Sage's service, export again, compare text/marks
and visually inspect PDF/DOCX. No document can silently drop rich content.
If proof fails, stop expansion and report the specific failure; any alternative
editor proof requires a separately reviewed change to this plan, not an install.

### P3a - narrative editing

Extend adapter/schema/exporters and add `documentation/search.py`. Rich schema
2 adds font token/size, highlight, strike, sub/sup, paragraph alignment/indent,
spacing and named style ID; schema-1 defaults reproduce its prior rendering.
Fonts use the approved token set, sizes 6-48 pt, indentation 0-72 pt, spacing
0-36 pt, line spacing 1-2; lists nest to six levels. Server validates exactly the
same ranges. Prove each mark in PDF/DOCX before exposing its ribbon control.
Enable approved narrative blocks/captions, including operations/work text; keep
technical slots/formulas typed. Show capabilities per selected target.

Add `find_document_text {documentId,query,caseSensitive?,scopeIds?,cursor?,limit?}`:
literal text only, response with revision, stable target ID, contentHash, exact
match and Unicode **code-point** start/end. No regex in first release. Add
`replace_range` and `format_range` operations with target hash, exact expected
substring and code-point range; reject ambiguous/stale boundaries and grapheme
splits. JS explicitly converts UTF-16 positions; test emoji and combining marks.
Replace-all previews count, sends an explicit validated batch (bounded request;
larger sets require multiple user-visible groups, not silent partial success).
Named styles: title/heading/body/caption/note, no arbitrary CSS. Engineering-symbol
picker includes only glyphs proven by the approved fonts; no equation editor.

Files: prior adapter/schema/export files, new search module, tools/server, pinned
tests, `index.html`. Add `test_documentation_typography.py` and
`test_documentation_search.py` (range boundaries, untouched marks, locked/typed
fields, deterministic literal matches, full read and replace group).
Gate: both files plus rich export tests, `smoke_documentation_editor.py --phase P3a`.
Expected: supported typography survives reopen and both exports; Sage range edits
preserve neighboring marks; find/replace undo is coherent. No full word processor
pagination, custom dictionaries or arbitrary font upload.

### P3b - authored non-BOM tables

Rich schema 3 adds table/row/header/cell nodes with durable IDs, spans, widths,
style token, cell alignment/fill and bounded rich content. Each table also has
`ownership:'authored'`; server rejects structural operations on `ownership:'bom'`
or generated engineering tables. Existing generated text overrides keep their
identity/provenance semantics. No automatic conversion of a CAD table.

Use Tiptap table commands behind a semantic operation adapter. Add
`create_table {parentId,afterId?,rows,columns}` and
`modify_table {tableId,action,rowId?,columnId?,cellIds?,widths?,style?}` to batches.
Actions: insert/delete row or column, merge/split rectangular cells, set widths,
set cell style, delete table. Caps: 50 rows, 12 columns, 600 cells, no nested
tables; spans must form a complete non-overlapping grid. Merge stores covered
cell contents in row-major order with paragraph separators; split does not
invent lost values; undo restores original cells/IDs. Widths sum to the bounded
table frame and have a physical minimum. Use auto row height; overflow is explicit.

Files: `documentation/tables.py` (new), rich validator/layout/exporters, adapter,
commands/tools/server/pinned inventories, `index.html`. Add
`test_documentation_tables.py`: old rich-schema load, IDs through insert/delete/
reorder/merge/split, span validation, native DOCX grid spans, PDF repeated text
coverage, BOM refusal and transaction undo.
Gate: pytest file plus rich exports and `smoke_documentation_editor.py --phase P3b`.
Expected: create/edit/merge/split/resize table in real workspace; reload and Sage
edits preserve identities and content; both exports include every cell. Risk:
table overflow and inaccessible selection. No spreadsheets, calculations,
arbitrary row heights, nested tables or unrestricted BOM surgery.

## 7. Phase 4 - composition and publication

### P4a - basic object controls

A versioned additive scene transition adds ordered object IDs per page, aspect-lock flag, normalized image
crop `{x,y,width,height}` in source-image coordinates and rotation limited to
0/90/180/270 for images in this release. Old `contain`/`cover` objects retain their
old rendering until explicitly edited; do not silently convert `cover` to a new
crop. Existing text/shape angle semantics are preserved and validated by format.
Add a shared object renderer/export mapping under `documentation/objects.py` and
extend every supported exporter, adapter/selection code, tools and `index.html`.

Add batch operations `set_object_frame`, `set_image_crop`, `set_object_order`,
`arrange_objects`, each with object IDs and expected hashes; managed asset ID only.
Frontend gives aspect-lock resize, crop reset, align/distribute, bring/send and
keyboard nudges in page units. Group/ungroup is deliberately deferred (it is not
needed for basic controls); no changes to CAD transforms, captures or callouts.
A DOCX adapter can use native runs/tables/images and bounded OOXML drawing support;
if an existing shape cannot be represented, return `unsupported_export_feature`
with its ID instead of silently dropping it. Basic supported shapes must have a
documented mapping (vector or explicit per-object raster fallback, never page
rasterization); text stays editable. No claim of arbitrary Office shape editability.

Add `test_documentation_objects.py` and `test_documentation_export_matrix.py`:
old-shape unchanged, crop/rotation/aspect, z-order/hit testing, coordinates,
managed-asset refusal, image/object presence in each supported format and undo.
Gate: both pytest files and `smoke_documentation_editor.py --phase P4a`. Inspect
objects placed over/under text in every buildable document type, both exports,
reload and keyboard selection. Risk: browser/DOCX anchoring differences; publish
the supported subset and fail unsupported cases explicitly. No wrapping, groups,
freeform diagram engine, new fonts or PPTX.

### P4b - page setup and complete fidelity gate

A versioned additive scene transition adds optional `pageSetup` with paper A4/Letter, orientation, margins in
pt, and `layoutMode:'fixed'`. Absence uses the existing generated geometry (including
960x540 manuals); migration must not turn those into Letter. Presets apply to an
explicitly selected publication, not globally. Each document type advertises
supported presets: parts/operations/work allow portrait/landscape only after their
layout planner passes fit checks; specification is portrait A4/Letter; inspection
keeps its existing form geometry and advertises no page setup in this release.
Reject unsupported preset/type combinations. Do not accept a setting then ignore it.

Add `set_page_setup` operation, shared layout/style tokens in
`documentation/layout.py`, update type compilers, shared rich layout/exporters,
UI and tool capabilities. Existing generated BOM continuation is preserved.
Rich text cannot silently flow across fixed pages: report affected IDs with
`layout_overflow` and offer shorter text/resize/move. No unlimited font shrinking.
Missing or stale required captures block their relevant export. Header/footer,
page number, contents and caption references resolve after layout by stable ID.

Add `test_documentation_page_setup.py`, extend export matrix with every combination
of text/rich text/table/image/shape/CAD figure by document type and supported
PDF/DOCX format, plus glyph/overflow/missing capture cases. Parts DOCX and
inspection DOCX remain unsupported, explicitly reported by capabilities; "consistent
PDF/DOCX" covers formats the document type actually supports. A new parts DOCX
publisher is outside the first release, consistent with the audit's existing subset.

Gate: those tests plus `smoke_documentation_editor.py --phase P4b`. Real browser
and PDF/DOCX comparison at normal/high DPI; no dropped objects/cells, clipped text
or wrong page references. Open DOCX in Word and LibreOffice when available and
record which was used; no assertion of exact Word pagination from python-docx.
Risk: legacy layouts are fixed; unsupported presets must stay disabled. Leave
flow pagination, columns, arbitrary sections and master designer for later.

## 8. Phase 5 - recovery and release

### P5a - measured scale and recovery

No schema change planned. Add `tools/benchmark_documentation_editor.py` and
`tests/test_documentation_recovery.py`; extend the browser smoke script with
1/50/100-page synthetic manuals, realistic BOM sizes and repeated managed CAD
fixtures. Measure cold open, edit-to-visible latency, commit, undo, reload,
export, peak RSS and listener/editor counts. One active editor; dispose on switch.
Benchmark on Claude's stated Windows hardware; record median/p95 from five runs
and exact fixture sizes. Provisional acceptance budgets: typing p95 <=100 ms,
selection <=150 ms, local save <=1 s, 100-page open <=5 s, 100-page PDF <=30 s,
100-page DOCX <=30 s, and <=100 MiB retained growth after 20 open/close cycles.
Record absolute memory and compare with P0 on the same machine; changes to these
budgets require a written finding, not an undocumented relaxation.

Crash tests kill a child before replace, after replace/before receipt delivery,
during refresh and during export. Test disk full/read-only directory/denied file
replace, concurrent writers, interrupted first migration, unknown newer schema,
restart and restoring the versioned original-byte backup into another temporary store. Failures preserve
the old committed state or the complete new state, never a hybrid. Retained
receipts remain valid and evicted retries cannot mutate again. No overwrite of
real files during recovery testing.

Gate: `python -m pytest -q tests/test_documentation_recovery.py`,
`python tools/benchmark_documentation_editor.py --pages 1 50 100 --runs 5`,
`python tests/smoke_documentation_editor.py --phase P5a`. Keyboard-only editing,
screen-reader labels/status announcements, normal/high DPI, 125/150/200% scaling,
focus return and contrast checked in real browser. Risk: budgets are provisional
until measured; report failures. No collaborative editing or schema rollback that
pretends new content can be represented by the old app.

### P5b - independent release and live desktop gate

No new features. Claude runs the complete gate set below, including the supplied
MMLE inputs and both promoted baselines, then the automated Electron smoke using
`desktop/README.md`'s isolated-snapshot launch. Never launch that renderer against
the live checkout. Add `tests/smoke_documentation_editor_desktop.cjs` using the
desktop's existing harness; preserve Node >=22.12 and Electron 44.3.0.

After all slices pass, **Claude**, not this builder, creates a backup branch in
the user's real repo, ports the completed branch there, gracefully restarts the
user's actual desktop app and runs the witnessed acceptance sequence there.
Claude records backup/port identifiers and restart outcome. This explicit final
supervisor action does not authorize the builder to touch the real repo, perform
git mutations or restart the app during a build slice.

Gate: `npm test` in `desktop`, the desktop smoke script against the isolated app,
and a witnessed sequence in the user's actual desktop app, on a **scratch document
or a copy**, never the user's own documents: old document copy open -> edit cited
text -> rich text/list/table -> change scratch source -> resolve conflict ->
save/restart -> undo/redo -> review export -> user-confirm or revert cited edit ->
customer PDF/DOCX -> open output. Verify disk state, provenance and source links.
A live Sage read/edit/retry run through that desktop is part of P5b and is reported
separately from deterministic host tests and the isolated Electron smoke.
If provider or desktop is unavailable,
leave P5b open; no mock substitution. Claude records screenshots/logs locally and
small JSON results in the report. User's PyMuPDF decision remains a release gate.
This phase ends with the live desktop check, not unit tests alone.

## 9. Executable gates and reviewer protocol

Commands below use `python` as the reviewer environment's installed interpreter.
On Windows launch it hidden through the documented wrapper, e.g. from a parent
with `windowsHide:true`, directly invoke `pythonw.exe tools/run_hidden.pyw
<python.exe> <arguments>`. Redirect stdout/stderr. No intermediate visible shell.
No dependency installation by the builder.

Common gate for every slice (Claude uses its own hidden runner and the isolated
code copy with the authorized ignored local inputs; preserve its configured
assembly-library snapshot for the full suites):

```text
python tools/documentation_baseline.py --inventory
python tools/documentation_baseline.py --local --inventory
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python -m pytest -q tests/test_documentation_baseline.py
python -m pytest -q tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py
```

Every slice also runs the complete documentation suites, including MMLE; this is
not conditional on which document files changed:

```text
python -m pytest -q tests/test_parts_manual.py tests/test_inspection_sheet.py
python -m pytest -q tests/test_specification_sheet_slots.py tests/test_specification_sheet_workflow.py
python -m pytest -q tests/test_operations_manual_workspace.py tests/test_work_instruction_workflow.py
python -m pytest -q tests/test_documentation_form_fields.py tests/test_documentation_library_assembly.py tests/test_parts_manual_ui_contract.py tests/test_parts_manual_callout_quality.py
python -m pytest -q tests/test_operations_manual_precoding_contracts.py
```

Claude's P0 review reports **326 passed**, plus the pending baseline test and the
one pre-existing failure
`tests/test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed`.
That failure also occurs in the user's real repo: leave it, run/report it
separately and require no additional failures. Report actual counts, including
new baseline/local checks, rather than assuming 326 remains the count. Keep all
documentation suites green against this known exception; enumerate deliberate
expectation changes in each slice report. Do not skip/weaken tests to obtain a
green total. MMLE suites are runnable with the already supplied inputs; there is
no additional-input precondition before P1. On a genuinely tracked-only checkout
the optional local baseline is skipped explicitly, which is not completion of
Claude's required local gate in this environment.

`tests/smoke_documentation_editor.py` is a **planned P1a deliverable**, not a P0
passing test. It uses MMLE-50D as its fixture and replaces the unavailable tricycle
editor smokes. It extends `IsolatedPartsManualServer`'s temporary server/loopback/
cleanup pattern: sanitize the code snapshot (no private files), disable dotenv
before server import, redirect **all five** document roots plus other mutable
roots to its own short temporary directory, seed only approved fixtures, use a
fresh browser context, and forbid outbound requests. The existing helper redirects
only the parts store; that alone is insufficient for this project. No copied
cookies, sessions or auth profiles. GET-before/after JSON and actual persisted
state accompany screenshot evidence; screenshots alone cannot prove preservation.

The script takes `--phase P1a` through `--phase P5a` and `--phase all`; each runs
the cumulative scenarios up to that slice. It reports JSON with individual checks,
document/revision IDs, console/network failures and result, exits nonzero on any
failure, and cleans up on exceptions. Do not mock the renderer or replace the
real page with an HTML test fixture. DOM controls drive at least one mutation,
undo and reopen in every slice. Direct HTTP calls are allowed to induce races
and source changes, not as a substitute for the UI path.

Before P0 acceptance Claude reruns the existing isolated MMLE publication smoke
with the corrected page count, using the supplied locally excluded manual plan
and scene after auditing isolation:

```text
python tests/smoke_parts_manual_isolated_pilot_publication.py --assembly MMLE-50D --minimum-occurrences 200 --expected-pages 18 --expected-technical-pages 12
```

Expected: 18 published pages, 12 technical pages, all captures pass callout QA,
no browser errors and unchanged source CAD. Claude observed those results in P0;
the run failed only the stale 15-page assertion. The old commands
`python tests/smoke_parts_manual_documentation_workspace.py` and
`python tests/smoke_parts_manual_documentation_workflow.py` are unavailable:
`parts_manual.get failed: unknown assembly` because tricycle no longer exists.
Do not repair them in this project; P1a's MMLE editor smoke replaces their role.
Later each slice has its exact pytest file and smoke scenario above.
If a requested check cannot run, report the exact
command, error, missing dependency/fixture and the remaining gate. Commit only
after that slice's agreed gate; the builder never commits.

## 10. Deliberately later

Word-style wrapping/columns and arbitrary long-document flow, general page/section
authoring, full template/master designer, equations, custom font installation,
group/ungroup and nested transforms, presentation document mode/PPTX, arbitrary
DOCX/PPTX import/round trip, tracked changes/comments, collaboration, e-signatures,
and external Office automation. Also exclude research/browser cookie bridging,
agent-key renames, source-evidence approval by prose edits and changes to CAD-derived
quantity/geometry rules. None is implied by installing an editor extension.
