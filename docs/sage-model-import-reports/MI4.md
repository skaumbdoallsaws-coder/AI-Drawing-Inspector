# MI4 frontend builder report

Date: 2026-11-09. Built against revision 3 of docs/sage-model-import-plan.md,
including sections 8-10. No commits, branches, index changes, network requests,
package installs, or Python edits were made by this builder. The concurrent
server builder's files were left alone.

## CHANGED

- static/facility_layout_chat_attachments.js (new): pure chip transitions and
  payload builder, asynchronous queue, and small DOM view. Three chips per
  composer, at most two upload/retry requests per conversation, real upload
  progress, polling, remove, and 429 retries after 2/4/8 seconds before Busy -
  retry. Queued/checking/uploading chips block send. Ready/refused IDs are sent;
  failed/busy chips are excluded. Removing or switching never lets a late
  response revive a chip, and an already uploading request finishes normally.
- static/facility_layout_transport.js: raw-body importModel with percent-encoded
  X-Model-Name, getModelImport, and retryModelImport. Browser uploads use XHR for
  byte progress; injected/non-browser transports retain a fetch fallback.
  Existing structured HTTP errors preserve status 429 for the queue.
- static/index.html: eligible Facility Layout Sage composer gets the + menu,
  hidden multiple-file input, chips, and chat-pane drop target. Send accepts
  attachments without text; top-level attachments are included before the
  request is frozen. Failed sends retain chips; successful sends clear the
  captured composer batch. Frozen retries retain the original IDs, require the
  original layout, and leave subsequently added attachments alone. Session
  restore, conversation/site/layout switches, and leaving the eligible context
  clear local chips. Pending chips display Uploading...; an active stream still
  exposes Stop. Changed scripts and the new script have versioned URLs.
- static/facility_layout_workspace.js: public refreshAssetCatalog() and
  checkAssetCatalogVersion(), preserving array-only loaders while accepting the
  assets/catalogVersion envelope. Checks run after every Facility Sage request
  finishes, including errors/cancellation, on online/recovered-memory events,
  and on workspace mount/resume/sheet changes. registeredAssets triggers an
  immediate refresh. Concurrent checks coalesce with a follow-up check, and old
  responses cannot overwrite a newer catalog request. normalizeCatalog keeps
  attribution; the current card renderer displays Credit: title | author |
  license through textContent.
- tests/test_model_import_chat_attachments.js (new): plain-node state machine,
  queue, payload, transport, catalog/version/credit, eligibility, and wiring
  tests. Also parses the page's classic inline scripts without executing them.
- docs/sage-model-import-reports/MI4.md: this handoff.

## TESTS

Commands ran hidden, using C:/Python314/pythonw.exe tools/run_hidden.pyw node
<test-file>, with windowsHide on the parent spawn. No server was started.

| Test | Result |
| --- | --- |
| tests/test_model_import_chat_attachments.js | 22/22 passed |
| tests/test_facility_layout_transport.js | 31/31 passed |
| tests/test_facility_layout_workspace.js | 138/138 passed |
| tests/test_chat_memory_frontend_contract.js | 12/12 passed |
| tests/test_chat_stream_frontend_contract.js | 21 passed, 2 pre-existing failures |

The stream contract runner misleadingly prints "21 passed, 1 failed": its
failure count is a boolean exit-code check. Both failed assertions also fail
against HEAD's index.html, verified by running the same contract source in a
Node VM with that baseline HTML substituted for the read:

- "runtime failures explain recovery without exposing raw provider messages":
  expects "No engineering changes were made" in the extracted function.
- "non-replayable terminal failures do not offer the old request ID as Retry":
  expects "err.streamCancelled || err.streamRetryable === false".

The workspace suite emits its existing intentional "Sage's glide stopped.
Error: lost context" diagnostic and exits 0.

Final git diff --check for the touched frontend files passed. All six written
files have LF line endings. All added lines in index.html are ASCII; its 1,896
pre-existing non-ASCII characters are unchanged. The other changed/new JS
files and this report are ASCII.

## NOT RUN

- Browser/Electron/Playwright checks: assigned to Claude on the isolated D12
  server, per the phase instructions. In particular, exercise file selection
  and three-file drop, real progress, permission gating, terminal failures,
  attachment-only send, frozen retry, and library Credit visibility.
- Live MI1/MI2/MI3 integration/provider runs or Python suites: server work is
  concurrent and this builder has frontend scope and no network access.

## DEVIATIONS

- The plan's _assetCard name is stale in this worktree. The Credit line is in
  Workspace._renderAssetBrowserCard, the existing library card renderer.
- A failed network poll retries GET, because the worker may still be running.
  A record explicitly reporting failed retries POST .../{importId}/retry.
- Unchanged catalog versions do not rerender the library. Changed versions use
  the assets already returned by GET /api/industrial-assets, avoiding another
  download of the same response.
- Existing non-ASCII index.html text was preserved rather than rewriting
  unrelated content; all new strings/markup are ASCII.

## OPEN QUESTIONS / ASSUMPTIONS

No blocking questions. Backend/browser review should verify these integration
assumptions against the concurrently built routes:

- Existing workspace.capabilities.manualAuthoring is the frontend edit gate,
  following the floor-plan controls. The server enforces layout.edit. A loaded
  session with baseRevision plus transport.siteId/layoutId supplies the bound
  layout; the chat must be the internal deviation-analyst key in Facility Layout.
- Upload, record GET and retry POST return the direct D4 import record (id,
  state queued/checking/ready/refused/failed, refusal.message). importId is also
  accepted as an ID alias; failure/error.message and record.message are accepted
  for failures. Polling uses a one-second interval.
- X-Model-Name uses encodeURIComponent, following the floor-plan upload header.
- GET /api/industrial-assets?siteId=... retains its existing siteId/assets
  envelope and adds catalogVersion as an opaque scalar. Missing versions
  remain backward compatible by refreshing on each check.
- registeredAssets is a top-level array on the terminal turn result as D10
  specifies. Correctness also uses the unconditional version check in finally.
