# Research security and asynchronous lifecycle checkpoint

Updated: 2026-09-15, America/Chicago.

## Scope

The isolated native research security check passed on Electron 44.3.0 / Chromium
152.0.7977.78. This is not acceptance of the complete desktop application,
arbitrary website compatibility, interactive attach, or normal research release.
General desktop editing and browsing remain gated outside the acceptance harness.

## Implementation

- Explicit navigation requests have per-tab generations. A late failed request
  cannot overwrite a newer result; Stop, history navigation, renderer failure,
  tab close and disposal invalidate the old request.
- Website popup requests can create an isolated tab only from the active,
  visible, focused research view in the focused application window. Hidden,
  background, suspended, closed and disposed sources cannot reopen the pane.
  Native popup windows remain denied. This is not support for opener-dependent
  authentication flows; those still require compatibility testing/fallback.
- Toolbar commands cannot bypass hidden/suspended state. A native external-browser
  confirmation is bound to its original tab, URL and navigation generation. A
  delayed answer after navigation, hiding, suspension or closure does nothing.
- Disposal marks the pane closed before cancelling downloads or closing views,
  preventing cleanup callbacks from opening new tabs.
- Close-dialog and backend-restart suspensions have separate owners. Dialog Cancel
  and preflight restart refusal release their own suspension, not another owner's.
  A failed backend or unreconciled recovery retains the research lock.
- The existing coordinated request policy records bounded per-resource-type
  counters, without storing request URLs, page contents or credentials.

These changes use the existing main-process tab manager and permission/network
policy; no second browsing engine or renderer execution bridge was introduced.
Electron's navigation events and load promises remain distinct from application
request ownership. See the [official webContents contract](https://www.electronjs.org/docs/latest/api/web-contents).

## Native evidence

[Native result](../../.runtime/research-security-20260915-b/result.json)
binds the five relevant source files by SHA-256 and records the pinned runtime.
The actual research WebContentsView uses the production sandbox, session,
permission, request and proxy configuration. A test-only in-memory HTTPS handler
serves controlled pages for one fixture origin *after* the production policy.
There is no loopback exception, credential injection, TLS override or DIRECT
proxy fallback. This controlled transport does not prove remote-site compatibility
or exercise a successful remote CONNECT tunnel; the earlier real-public-page
check and proxy tests are separate evidence.

Passed checks:

| Check | Evidence |
| --- | --- |
| Renderer isolation | No Node `process`, `require`, InspectorPro bridge or trusted research-control bridge; sandbox/context isolation/web security enabled |
| Page, iframe, dedicated worker, shared worker, service worker | All five execution contexts actually ran; each attempted five local-address targets and received rejection |
| Independent request observations | 25 blocked fetches, one blocked WebSocket, one blocked image at the session request policy |
| Navigation | Private top-level navigation, frame/form targets and public-to-private redirect failed closed; no local connection arrived |
| Popup ownership | Hidden, suspended and background attempts did not reveal/open views; the active focused public popup created a separate isolated tab, not a native window |
| Download | Real inert fixture download cancelled; no destination was chosen and no content was executed |
| Local canary | Zero TCP connections and zero HTTP requests; zero rejected targets reached the test HTTPS handler |
| Cleanup | No native windows, listening canary or proxy sockets remained; no cleanup errors |

The service worker registered, ran its probe, and was unregistered. The shared
worker ran before its message port closed. A blocked worker script alone is not
counted as proof of worker request interception.

The local canary is not the real authenticated InspectorPro backend. Exact-origin
backend authentication and mutation rejection remain independently covered by the
backend suites; this record does not replace those tests.

## Tests

- **599 Node tests passed**, zero failures/skips, in
  [full JUnit](../../.runtime/desktop-completion-evidence/node-research-final.xml).
- This adds 22 tab/request lifecycle cases and seven tests executing the actual
  runtime Close/Restart functions. Earlier tests were adjusted to model real
  focus transfer instead of a no-op fake `focus()`.
- No Python source changed in this follow-up. The preceding 229 Python tests,
  306 subtests and one skip are retained as earlier evidence, not claimed rerun.
- The previous native security run is preserved at
  [run A](../../.runtime/research-security-20260915-a/result.json); run B adds
  actual shared/service workers and source hash binding.

## Remaining gates

Native file selection/upload, PDF compatibility, standard clipboard, supported
authentication/citation sites, zoom/monitor transitions, memory regression
thresholds and application camera/motion/voice interactions are not established
by this test. It does not authorize general application edits, all-workflow
recovery, live Sage execution or an end-user release.

No facility layout is loaded or written by the security driver. The separate
combined facility/research acceptance uses an isolated manual-layout copy and
forbids Save. It was rerun against the hardened pane/main wiring and passed as
`inspectorpro-runtime-20260915-173342-aa0dafb0`: actual facility attachment,
Process Map refusal/preservation, pending Apply/Undo restarts, five inspected
screenshots, zero Save and verified owned cleanup. The 13-file current-source
comparison and remaining visual limitations are recorded in its
[visual review](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-173342-aa0dafb0/visual-review.json).
See the [consolidated implementation report](desktop-research-runtime-implementation.md).
