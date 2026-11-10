# P2a - documentation editor

## P2a-1

Server implementation is ready for supervisor review, not runtime-approved.
P2a-2 has not started. No commit, branch/index mutation, network access, package
installation, application launch, pytest run, baseline run or smoke run was made.

### CHANGED

- `ai_inspector/documentation/rich_text.py`: schema-1 validation, canonical JSON,
  exact plain projection/conversion, fail-closed environment flag, node ownership
  checks, display projection and export refusal. The canonical field value is
  `scene.pages[pageId].documentObjects[id].content`: either its old string or
  `{format:'tiptap', schemaVersion:1, doc:...}`. There is no second stored text value.
- `ai_inspector/parts_manual/documentation.py`: scene schema 5; versions 1-4 migrate
  in memory without writing. First explicit write of v4 preserves its original
  bytes in `documentation-scene.v4.json`. One `replace_rich_text` scene operation
  serves both workspace and Sage. Plain `update_text` refuses rich content unless
  `wholeFieldReplacement:true`. Journal snapshots retain exact strings/envelopes;
  undo and orphan restoration also check node collisions. Replay/undo work with
  the flag off. Malformed stored rich content is retained and its field is read-only.
- `documentation/commands.py`, `targets.py`, `provenance.py`, and
  `specification_sheet/document.py`: rich hashes cover the canonical envelope,
  including marks and IDs; existing plain hash inputs are unchanged. Reads expose
  envelopes, derived text, capabilities and owner bindings. Authored objects stay
  unbound, as with plain edits; rich edits never acquire source authority. Explicit
  plain replacement records `rich_text_replaced_with_plain` in Sage's receipt.
- `server.py` and `codex_runtime/documentation_tools.py`: additive Sage operation
  and per-edit `wholeFieldReplacement` input; specification authored objects are
  scene-owned targets alongside the existing slot inventory. Slot and scene
  operations cannot mix. UI writes check the field hash under the owner locks and
  keep the existing exact `baseRevision` rule. GETs expose the flag and field
  contracts. Scene responses can JSON-escape corrupt Unicode without changing
  stored bytes. The request-local scene-free baseline remains authoritative.
- Export refusal is in the shared provenance/export boundary, before rendering,
  capture checks and controlled-release checks. It covers parts PDF, operations
  PDF/DOCX, work-instruction PDF/DOCX, specification PDF/DOCX and fillable PDF,
  including review/draft/customer/controlled modes, with
  `unsupported_export_feature` and `{pageId,targetId}` targets. The fillable HTTP
  route now checks this before capture readiness. Plain export rendering is unchanged.
- Reader audit: the canvas and thumbnails receive derived strings in compiled
  `documentationObjects.content`; canonical envelopes remain in the scene and
  composition. `parts_manual/pdf.py` uses the projection rather than `str()`.
  Sage reads use `targets.py`; DOCX publishers refuse before layout. Refresh,
  reset recovery files, orphan payloads and undo snapshots retain whole values.
- Added `tests/test_documentation_rich_text.py`; updated the three Codex inventory
  pins and scene-version assertions in transactions, provenance, refresh, parts
  tests and the existing smoke. No UI/static code or vendored file changed.

The flag is `INSPECTORPRO_DOCUMENTATION_RICH_TEXT`, default off. Only
`1/true/yes/on` (case-insensitive, trimmed) enable it. Invalid values fail closed.
Off removes the rich capability and rejects rich writes with
`documentation_rich_text_disabled`; saved rich fields still read and undo safely.

Specification inventory now adds only authored text objects; generated page
prose remains excluded and typed slots stay typed. Each object uses the scene's
edit revision/counters, while `slotBinding` retains only slot/structure hashes.
Unedited plain specification documents acquire no extra provenance projection.
The flag itself changes neither baseline hash input. The required scene version
bump is expected to move only synthetic `/table/scene`; Claude must measure,
review and promote that metadata change. The local fixture authors no text
objects, so its baseline is expected unchanged. Neither expectation was edited.

P2a-2 client contract:

- GET the existing `/api/<document>/{n}/documentation-scene`. Top-level
  `documentationRichText` is the server flag; `revision` is the opaque scene
  revision. `scene.sourceRevision` and `scene.manualPlanRevision` bind the source.
  `richTextFields` contains each authored text field. Sage targeted reads return
  the same field contract under `targets`.
- Each field returns `targetId`, `legacyTargetId`, `pageId`, `text`, `fullLength`
  (code points), `isExcerpt:false`, `contentHash`, `hashVersion:1`,
  `aliasRevision`, `provenance`, `hasOpenConflict`, `conflictIds`, `capabilities`,
  `owner:'scene'`, numeric `revision`, and
  `binding:{documentId,revision,sourceRevision,manualPlanRevision}`. It also returns
  `richTextEligible:true`, `isRichText`, `richText` (envelope or null),
  `richTextError` (code or null), `plainEditConsequence`, and
  `wholeFieldReplacementRequired`. A malformed field has empty text, no envelope
  exposed to Sage, an error code and no capabilities. Locked/conflicted fields
  have no write capabilities. Mount only when `replace_rich_text` is advertised.
- At edit start, keep `DocumentationCommands.capture(payload,page,apiBase)` and
  that field's hash. Commit once to the existing `/commands` route with captured
  `baseRevision`, `sourceRevision`, `manualPlanRevision`, plus
  `operation:'replace_rich_text'`, `targetType:'document_object'`, `pageId`,
  `targetId`, `expectedContentHash`, and the complete `richText` envelope. Reload
  the GET after success for fresh hashes. The manual route returns its existing
  `command.commandId`, `changes`, `canUndo` and `canRedo`; Sage returns a receipt.
- Use existing `/documentation-scene/undo` and `/redo` with the latest opaque
  `baseRevision` and source/plan bindings. Named undo uses `command.commandId`
  (or Sage's `receipt.changeId`) and the field owner's numeric revision. Rebase
  local editor history after commit; in-focus undo stays local in P2a-2.
- Compare incoming `contentHash` with the captured hash, including for mark-only
  changes. Keep dirty drafts on a mismatch or server conflict. UI scene revisions
  are exact: even an unrelated scene write requires a fresh context before retry.
  Never substitute a fresh hash into a dirty draft automatically. Use field
  `binding.revision`, not the specification read's top-level slot revision, for Sage.
- IDs are `rt-<lowercase UUID>` on paragraphs, headings, lists, list items and
  hard breaks; doc/text nodes have none. Allocate explicitly and re-key paste;
  never change generated identities. Allowed attributes are only `id`, heading
  `level:1..3`, ordered-list `start:1..9999`; marks are B/I/U, textStyle with
  six-digit hex color, and absolute HTTP/HTTPS links. Link target/rel/class are
  server-owned. Mailto is excluded from this proof. Strip unsupported/default
  editor attributes before submission; do not use BackgroundColor. Bounds are
  512 nodes, three list levels, depth 12 and 24 KiB canonical envelope. For old
  strings mirror `from_plain`: one paragraph, LF hard breaks, literal CR, tabs,
  spaces and Unicode unchanged; use full whitespace preservation. Explicit plain
  replacement stores a string and removes formatting/IDs; the next mount treats
  that string as one plain paragraph with hard breaks.
- Import named exports from
  `/static/vendor/tiptap/tiptap.bundle.js?v=c36fd989775f`. Bundle remains 3.32.0.
  Adapter/CSS/wiring, Node tests, disposal/focus/draft behavior and the CDP IME
  check belong to P2a-2.

### TESTS

Static checks only:

- Python `ast.parse` accepted all 18 changed/new Python files through
  `pythonw.exe tools/run_hidden.pyw`, with a hidden parent; no application imports.
- `git diff --check` passed. Written files use LF; server BOM remains `efbbbf`;
  added server strings are ASCII.
- Pure file reads verified the 450,957-byte vendor bundle SHA-256
  `c36fd989775f6ed6f6884333bd05d8e4f097b25e256e1e14a42c226f7b83b301`
  and its recorded 24 exports. Vendor and baseline expectation files are untouched.

Authored tests cover the five named tests, schema/link/ID/size/depth refusals,
flag states, field read headroom, corrupt stored fields, specification ownership,
real route/Sage storage equivalence, stale hashes, atomic batches, plain replacement,
named/document undo/redo, refresh/reset/orphans, conflicts, exporters, schemas and
vendor pins. None of these pytest tests has been run by the builder.

### NOT RUN

Claude runs these outside the sandbox with its established isolation and supplied
engineering inputs, using the hidden Windows launcher:

```text
python -m pytest -q tests/test_documentation_rich_text.py
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_refresh.py tests/test_documentation_store_chokepoint.py tests/test_documentation_editor_smoke.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py
python tools/documentation_baseline.py --inventory
python tools/documentation_baseline.py --local --inventory
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tests/smoke_documentation_editor.py --phase P1a
python tests/smoke_documentation_editor.py --phase P1b
python tests/smoke_documentation_editor.py --phase P1c
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
```

Retain the recorded pre-existing source-closure failure and wide-suite base
failures as comparison points; no runtime pass counts are claimed. P2a smoke and
new Node tests wait for P2a-2. Pytest, numpy, Pillow, PyMuPDF and browser dependencies
were not installed or worked around.

### DEVIATIONS

- Supervisor split honored: server only, with 3.32.0 vendor pin and explicit client
  IDs. No P2b exports or P3a narrative typography.
- The canonical cap is 24 KiB rather than the plan's 32 KiB ceiling, leaving room
  for the full derived text and binding/provenance within a 64 KiB Sage read.
- Scene is version 5, not the plan's old envelope numbering. Generated document
  version constants remain unchanged: the versioned rich storage belongs to the
  scene, display objects stay derived, and rich publication is refused until P2b.
- Synthetic baseline metadata needs supervisor promotion for scene 5; expected
  files were left intact. Local baseline and plain export fingerprints are
  expected unchanged, pending measurement.

### OPEN QUESTIONS

No user decision is required. Supervisor runtime review, both baseline gates and
the P1 smokes remain open. P2a-2 starts only after this round's supervisor review.

## P2a-1 supervisor gate (Claude, 2026-11-10)

Result: PASSED after supervisor fixes; committed together with this section.

Codex ran this round (fresh session 01a1c5c9) in 40 minutes, with static checks only. I reviewed every diff:
- rich_text.py;
- the scene engine (schema 5, the replace_rich_text operation, plain-over-rich refusal, restored-field guard);
- targets (spec text objects as scene-owned targets, capabilities, owner revisions, hash inputs);
- commands and provenance;
- server (one write path, the field-hash precondition on the UI route, the store lock on the four command routes,
  export refusal);
- the parts PDF;
- Sage schemas.
Both locks the new route decorator takes are RLocks, and the decorator already guarded the four builders. The batch
receipt's zip(changed, persisted) stays aligned, because both lists skip _noChange together.

### Security review of the allowlist (scratch script, not committed)

37 hostile or edge inputs went through validate().
- Refused:
  - links with javascript:, mixed case, a tab split, data:, file:, UNC, scheme-relative, relative paths,
    credentials, no host, or a bad port;
  - link onclick and style attributes;
  - named colors, CSS-injection colors, extra textStyle attributes;
  - image nodes and paragraph event attributes;
  - missing or uppercase IDs, duplicate IDs, and IDs reserved by another field;
  - heading level 4;
  - bool or float schemaVersion, and extra envelope keys;
  - lone surrogates, empty text leaves, a nested doc;
  - list depth 4, 513 nodes, and more than 24 KiB.
- Accepted: HTML inside a text leaf, which stays plain data, and Tiptap's default link attributes, which the server
  replaces with its own.
- from_plain round trips are lossless.

### Supervisor fixes (Claude)

- Test: the parts PDF route binds an export to the read's revisions (PartsManualPdfBody). The shared-contract test
  posted no body and got FastAPI's 422 without an "error" key. It now sends the revisions from a fresh read. 93/93
  pass.
- Synthetic baseline: only /table/scene moved. Recomputing that scene inside the tool's own collect() with
  schemaVersion set back to 4 reproduces the old expected hash exactly, so the schema number is the whole change.
  Promoted (one line). The local baseline is unchanged, as Codex predicted.
- P1c-3 review module (static/documentation_conflicts.js, ?v= bumped to 20261110-p2a-1): the P1c smoke failed twice
  after the ribbon undo, with the pane stuck on "Loading review...". A temporary request-timeline and module-state
  probe (removed) showed the cause.
  - _documentationRenderPublicationPage queues a review sync for every page render, thumbnails included: about 40
    per workspace reload.
  - While a load was in flight, data was empty, so each sync started another full review load.
  - The server serializes them at about 0.9 s each, so about 40 loads took about 36 s and exceeded the smoke's 30 s
    wait. P1c-3 had only passed because the burst finished just inside the wait.
  Fixes:
  - review loads are single-flight per document stamp;
  - a sync that arrives during the 5 s change check defers its load to the end of the check, instead of being
    dropped.
  After the fix: 6 full review loads in the whole P1c run (at most 1 per second), against about 40 in one burst
  before.
  Two Node tests were added. Each fails against the committed P1c-3 module and passes now (18/18).
- Smoke harness (tests/smoke_documentation_editor.py): in the P1a/P1b flow, each of the two ribbon undos is followed
  by a full reload. In one re-gate run the reload started while Chromium was still receiving the undo response body,
  so the request was aborted (net::ERR_ABORTED on POST .../documentation-scene/undo). The server had already
  committed the undo; only no_unexpected_browser_or_network_failures failed (P1b 45/46). The smoke now waits for each
  undo response to finish (response.finished()) before reloading. P1a and P1b reran green. P1c does not run this
  flow.

### Numbers

- tests/test_documentation_rich_text.py: 93 passed. Focused documentation files: 669 passed, plus the baseline test,
  fixed by the promotion.
- Baselines: synthetic promoted (/table/scene, schema 5 only); local unchanged.
- Smokes on the final code: P1a 27/27, P1b 46/46, P1c 35/35. P1c ran on the final module without the probe. P1a and
  P1b reran after the harness fix. The smoke's own pytest files (test_documentation_editor_smoke.py,
  test_documentation_conflicts_ui.py): 36 passed on the final files.
- Documentation suites: 735 passed, 1 failed. The failure is the pre-existing
  test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed. P1c-3 had
  642 passed; the 93 new tests are this round's.
- Wide suites: 170 failed, 9 errors, 3851 passed, the same totals as P1c-3. Every failure is in the base set.

### Notes for P2a-2 (also in its brief)

- Tiptap's getJSON() emits default attributes that the server refuses, such as orderedList "type": null (and later
  paragraph textAlign). Pasted colors may be rgb() or names. The adapter normalizes before every commit.
- Splits and pastes duplicate node IDs, so the adapter re-keys at commit time against the read's other fields.
- When no editor is mounted, the canvas shows the plain projection. A safe static renderer must show the
  formatting.
- Known P2a limitations, accepted for the flag-off proof:
  - add_object refuses rich content, so duplicating a rich text box is not possible yet;
  - a malformed stored envelope freezes its object, including move and delete;
  - undo refuses to restore node IDs that another field has since reused (fail closed).
