# Facility Layout Sheets

Implemented September 26, 2026. This change is independent of the paused
provider-backed research-to-layout work; no provider calls were made.

## Behavior

- Bottom layout tabs and a plus button create and open blank layouts.
- Startup opens only the requested layout. The site-wide saved-layout registry
  is not a set of open sheets. The Open layout picker has been removed at the
  user's request; the plus button creates a new blank layout.
- In the Facility Layout workflow, **File > Open Layout...** now opens a modal
  chooser for saved layouts (September 29 follow-up). Only the chosen layout
  becomes another open tab. Cancel changes nothing, archived records are
  excluded, and duplicate names include their layout IDs. The removed bottom
  dropdown is not restored; unrelated saved test layouts are not auto-opened.
- The structure tree shows each open layout as a root; the active root exposes its
  existing zone/equipment hierarchy. Other roots open their layout.
- Each visited sheet retains its session, selection, unsaved draft and Undo
  history while the page remains open. Changing sheets is not Save.
- Creating a sheet persists a new empty document through the existing
  site-scoped creation API, with makeDefault=false. Subsequent edits still
  require explicit Save. Existing saved layout bytes are not changed.
- New sheets retain the source's exact authored shell, coordinate frame,
  association and policy references plus its plan settings. They do not copy
  equipment, zones, process bindings, navigation or generation provenance.
- Missing geometry is not invented. The existing shell's limitations still
  apply to authoring and validation in a new sheet.
- Double-click a sheet tab, or focus it and press F2, to rename. Cancel/Escape
  changes nothing. Blank names are rejected; the maximum is 120 characters.
  Rename uses the existing session gesture: it updates the tree and tab, is
  undoable, and remains unsaved until explicit Save. The tree's rename remains.
- The trash button deletes the active sheet after confirmation. Delete on a
  focused tab targets that tab. This uses the existing revision-checked archive
  endpoint, not filesystem deletion: the saved record is retained, read-only,
  and excluded from the layout inventory. The dialog discloses this and warns
  before discarding any unsaved edits. No implicit Save is issued.
- Keep at least one open sheet. The server continues to reject archiving the
  site's default layout. Busy/recovery states and pending proposals block
  deletion. Other sheets retain their documents, selection and history.
- Deletion locks the target session. A lost reply is checked against the exact
  archived base; an uncertain result retains the lock and Retry Delete layout
  action. A failed fallback mount retains that handle without repeating archive.
  These are in-window recovery semantics, not a new cross-restart journal.
- Busy operations, pending recovery, agent work and visible modal dialogs
  prevent switching. Close observation includes inactive dirty sessions.
- A failed creation retries the same identity, scoped to its source sheet.
  A lost reply is reconciled only against an exact matching document.
- Reload opens the layout identified by the URL. Other saved records are not
  deleted. File > Open Layout reopens them; the strip has no Open picker.
  Tab membership is not new persistent facility data.

### Saved Layout Discovery Follow-up

The normal desktop profile explicitly starts `fl-reference-manual-20260812`.
Factory 02 (`fl-independent-factory-20260928`, 836 placements and 40 movement
programs) was present in that same profile's facility store, but was not an
open tab after restart. The removed picker had left no visible reopen command.
The File menu now reaches the existing sheet activation path rather than
changing the startup profile, copying Factory 02 over the manual reference,
or displaying the whole saved inventory as tabs.

The command refreshes the site-scoped inventory and checks pending work and
workspace identity before and after retrieval and again on selection. It is
disabled outside the active Facility Layout workflow and in restricted shells
without the multi-sheet controller. Opening uses the existing mount rollback,
retained draft/history, renderer lease and revision-bound transport behavior.
No creation, archive or Save is implied.

Follow-up verification: **35 sheet/controller checks passed**, and all four
executable inline application scripts parsed. Native Electron evidence at
`.runtime/layout-open-20260929/native01/report.json` passed against an isolated
saved copy using the normal application entry. The actual File menu opened
the chooser, Cancel left only the manual tab, and explicit Open added Factory
02 with 836 placements and 40 movement programs. Returning to the manual tab
preserved its deliberately unsaved test rename, selection, revision and
history; Undo restored the clean manual draft. Both saved hashes remained
unchanged. The chooser was inspected at 1440 x 900 and 900 x 700 logical pixels;
the File command was also confirmed disabled in Drawing. Owned backend cleanup
and Electron exit were confirmed. No live layout or desktop startup profile
was changed.

### Correction: Inventory Is Not Open Sheets

The first implementation incorrectly displayed every non-archived registry
entry as a tab and tree root. This exposed the site's existing FDL test layouts
as though the user had opened them. The corrected controller returns separate
open layouts and available-layout inventory. Refresh never opens or activates
inventory entries. Failed Open leaves the current set of sheets unchanged.
No test layout or user layout was deleted, renamed or archived for this fix.

## Rendering And Lifecycle

Only one WebGL renderer is leased. Inactive sheets release their GPU scene and
renderer lease; revisiting remounts from the retained document and restores
the camera. Ordinary workflow suspend/resume retains its previous behavior.

Transient movement playback is cleared when leaving a layout. Restart movement
on returning; this does not delete authored routes or motion programs.
In-memory draft retention across tabs is not a new multi-document crash-recovery
or autosave contract. Existing close warnings remain in force.

The shared application page enables this in browser and normal desktop modes.
The restricted single-document desktop acceptance harness intentionally does
not expose sheets. The original rename/delete release did not include native
Electron visual acceptance; the September 29 File Open follow-up above adds a
native check for opening, cancelling, retained drafts, switching and Undo,
not a native rerun of every sheet creation/archive recovery scenario.

## Verification

### Rename/Delete Follow-up

The complete real-backend browser run passed at
.runtime/layout-sheets-20260926-173110/result.json.
It exercises the actual active/inactive tab double-click, F2, Escape, blank-name
rejection, tree synchronization, rename Save/reload, Delete cancellation,
confirmed archive, dirty-sheet discard, and a lost archive reply injected only
after the server committed. The archived record disappears from inventory and
the last open sheet cannot be removed. Existing manual edit/Undo and Plan/3D
remount checks also pass. Both dark/light centered dialogs and narrow/wide
screenshots were inspected. There were no page errors; the backend stopped and
the original manual-layout hash remained unchanged.

The earlier 172715 run also passed functionally. Its captures exposed the
dialog positioning and dark-theme trash-icon contrast defects corrected before
the final run. Focused tests were rerun after the keyboard propagation guard.
This remains browser verification of the shared desktop page, not a fresh
native Electron acceptance run.

The backend repository/API regression run produced 39 passes and one failure:
test_http_operation_preview_is_read_only_and_matches_put expects the preview
and operation-result envelopes to be identical but does not exclude the
preview's extra revision field. Neither that test nor those backend owners
was changed for this task. Archive repository tests passed. The unrelated
expectation mismatch is retained, not concealed as an all-green backend suite.

334 focused JavaScript checks passed:

| Suite | Passed |
| --- | ---: |
| Layout sheets | 28 |
| Structure tree | 51 |
| Three adapter | 71 |
| HTTP transport | 29 |
| Editor session | 61 |
| App lifecycle | 6 |
| Workspace | 88 |

The workspace fake document needed its missing createTextNode method to run
the existing generation-view checks. No production workaround was added.
Four executable inline scripts parse, and git diff --check passes.

Initial real-browser evidence: .runtime/layout-sheets-20260926-161020/result.json.
The actual backend ran against an isolated copy of the manual layout. The test
created two sheets, checked empty geometry and exact shell references, retained
independent drafts/history, switched using both the tree and tabs, exercised
Undo, explicitly saved only a new test sheet, and verified persisted reload.
It also rendered blank and restored-reference 3D using one renderer, and
captured 1440x900 and 900x700 views. No page errors were recorded. The test
backend's shutdown was verified.

Screenshot pixel checks found 997 colors in the blank 3D surface and 45,987
changed geometry-region pixels after restoring the reference. The subsequent
failed-installation rollback hardening is covered by the sheet unit suite;
the full browser run was not repeated after that error-path-only amendment.

The inventory/open-sheets correction and rollback path were subsequently
covered by .runtime/layout-sheets-20260926-164436/result.json (passed).
Startup and reload each expose only the requested layout despite additional
saved registry entries. Explicit Open adds only the selected sheet to the tabs
and visible Structure tree. Both newly created test sheets remain retrievable.
The full edit/Undo, 3D remount, Save and responsive checks passed again, with
no page errors or dialogs, a stopped backend, and the original hash unchanged.

Two preceding follow-up runs remain as failed evidence: 163320 omitted
reopening the lazy Structure pane after reload; 163819 exceeded the test's
30-second reload navigation timeout. The final harness explicitly opens that
pane, checks all drafts are clean before reload, records dialogs, and uses
the same 120-second navigation allowance for startup and reload. No application
timeout or close-protection rule changed. This is functional verification, not
a latency benchmark; the earlier reload delay's cause remains unconfirmed.

Earlier failed-run evidence remains under .runtime/layout-sheets-*; it is not
counted as passing. Findings included the single-renderer lease not being
released, hidden dialogs incorrectly blocking switches, and a reload test
waiting for all page resources rather than application readiness. One earlier
canvas timeout did not reproduce in the completed run and is not assigned an
unverified cause.

Original reference SHA-256, unchanged:

    a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088

## No Flashing Terminals

File inspection now runs in-process. Commands are launched directly with
pythonw.exe and tools/run_hidden.pyw, using CREATE_NO_WINDOW for the child and
windowsHide on the parent spawn. There is no intermediate PowerShell/cmd
window. Standard output, standard error and the exit code are preserved;
these were checked with a deliberate exit code of 7.

AGENTS.md records this user requirement for subsequent work. This changes the
execution path used for this project, not global Codex or Windows settings.
