# InspectorPro Desktop Shell Implementation Plan

Date: 2026-09-12
Revision: 2 — review feedback incorporated on 2026-09-12.
Status (2026-09-14): the isolated native rendering, facility/asset recovery, ten-case managed recovery and Apply/Undo status follow-up are accepted at their tested scopes. The next [combined managed desktop integration](desktop-runtime-integration.md) batch implements the normal launcher, protected backend, full-app facility lifecycle bridge and plain draft recovery. Its real-backend engine checks passed; normal-entry native acceptance remains pending. General editing and research browsing remain gated. Use milestone reviews after three to five connected steps, with internal tests and agent review during implementation; do not repeat unchanged accepted matrices. The full design and exit gates below remain in force.
Target: Windows first, using Electron provisionally, while retaining the existing web application and Python backend.

Execution update (2026-09-15): the normal-entry facility lifecycle now has native
verification, and wide/narrow native research capture is now verified. The
project-owned launcher passed the combined facility/research checks and a real
Process Map preservation/refusal check. Other workflows have conservative state
guards, not completed recovery or editing support. All-workflow acceptance,
permissions and broader research compatibility remain pending.
See [current implementation report](desktop-research-runtime-implementation.md).

Further September 15 execution: native page/frame/dedicated/shared/service-worker
request denial, popup ownership and download cancellation passed with the
production research policy. Stale navigation results and suspension ownership
were hardened; 599 Node tests and another combined facility/research native run
passed. This does not waive all-workflow, permission, compatibility or release
gates. See [security evidence](desktop-research-security-acceptance.md).
This supersedes the September 14 execution status, not the scope or exit gates.

## 1. Objective and agreed scope

Deliver a desktop application that hosts the complete InspectorPro application and provides an internal, tabbed research browser. Users should be able to follow Scout/Sage citations, read manufacturer references, and open additional tabs without losing their engineering workspace or leaving InspectorPro.

The contract-hardening work and bounded live Sage construction pilot now provide a suitable starting checkpoint. Record the exact reviewed code state before shell work; broad construction rollout remains outside this plan. Coordinate a clean checkpoint without changing unrelated work.

The shell must include all current workflows from its first prototype. “Minimal shell” means minimal desktop infrastructure, not a facility-layout-only product. Keep the ordinary browser development path functional.

Reuse the existing interface, APIs, geometry, persistence, agent runtime, and validation. Do not rewrite the frontend in a new framework or move manufacturing algorithms into Electron.

## 2. Evidence and assumptions

Confirmed from the repository and conversation:

- InspectorPro currently runs as a web application; there is no desktop host supplied for this work.
- The project contains `server.py`, a FastAPI application, and a vanilla HTML/CSS/JavaScript frontend under `static/`.
- The repository README describes localhost port 8000, but it is not a complete current runtime inventory. Its older storage and feature descriptions should not be treated as authoritative for today's system.
- The current Python server has application lifespan behavior and substantial workflow state. Do not bypass lifespan simply to make startup faster without determining the consequences.
- The four hardened facility construction contracts now have bounded live Sage integration. The recorded pilot rejects an undersized cell, chains all four commands, produces three cells/nine placements with attachments, applies unsaved, and restores the exact original with Undo. It remains off by default outside the pilot. See [integration report](facility-layout-construction-sage-integration.md). Desktop packaging does not expand its authorization or rollout scope.
- `construction_compiler.py` currently resolves `node` using `shutil.which("node")` and launches a fixed compiler script. Electron's embedded Node runtime does not automatically provide that executable on the backend's PATH. Inventory and test this dependency explicitly.
- `server.py` currently applies its origin middleware to selected facility authority paths. This is not evidence of complete application protection, and it accepts some loopback origins and requests without an Origin header. Research isolation must not rely on that middleware alone.
- `static/facility_layout_app.js` currently defaults design Undo recovery to `sessionStorage`, keyed by site/layout. The session can restore the local frame while server Undo acknowledgment is still pending. Desktop restart recovery needs durable storage and backend/store identity.
- `static/index.html` stores chat registry and preferences in `localStorage`; it also uses microphone and pointer-lock APIs. Origin, permission, and focus choices must preserve these working features.
- No `run_app.py` was found at the project root or its immediate parent during this inspection. Discover the actual current launch command rather than assuming that filename exists.

Before implementation, record the working Python interpreter, launch command, environment loading, storage roots, background workers, GPU/browser requirements, and external binaries. Inspect applicable repository instructions at that time.

Electron is the recommended first prototype, not an irreversible commitment. Prove that the actual viewport, file workflows, and embedded browser work before investing in an installer. Select a maintained Electron version at implementation time and commit its exact dependency lockfile.

## 3. Completion boundaries

### Milestone A: internal desktop shell

- Entire current interface loads in one desktop window.
- Existing browser launch still works.
- Attach mode connects to an explicitly selected development server without owning it.
- Managed mode starts and supervises an owned backend.
- Startup, failure, close, and unsaved-work behavior are understandable and tested.
- Representative existing workflows pass in the desktop environment.

### Milestone B: internal research browser

- Chat citations open a resizable pane with browser tabs.
- Users can create, close, switch, navigate, and reload tabs.
- Engineering and conversation state survive pane changes.
- External content is isolated from privileged application capabilities and backend credentials.

### Later milestones, excluded from A/B

- Signed installer, bundled Python runtime, automatic updates, and clean-machine distribution.
- Agent reading or controlling browser pages.
- “Ask Sage about this page” and “Add as project source.”
- Research-to-planning knowledge architecture.
- General-purpose local code execution, filesystem automation, or new SolidWorks integrations.
- macOS/Linux release support.

Do not label an internal launchable prototype a distributable product.

## 4. Proposed architecture

```text
Electron main process
  |-- application window and lifecycle
  |-- backend supervisor (attach or managed)
  |-- bounded desktop IPC handlers
  |-- research tab manager and isolated browser session
  |-- app-owned settings and diagnostic logs
  |
  |-- trusted InspectorPro view
  |      existing web UI -> existing Python APIs
  |      narrow preload bridge -> desktop commands
  |
  |-- research WebContentsView(s)
         external pages; no InspectorPro preload or application authority

Python backend
  existing services, persistence, agents, validators, and native helpers
```

Prototype a BrowserWindow hosting the existing application, with WebContentsView instances for research content. Reserve a DOM region for the browser and position the active native view within it. If composition proves problematic, compare a BaseWindow with separate application and research views before fixing the implementation.

One tab owns one webContents and its navigation history. Only the active research view needs to be attached visibly. Closing a tab must dispose of its webContents and listeners. Merely hiding it is not cleanup.

## 5. Proposed repository structure

These paths are proposed, not existing implementation names:

```text
desktop/
  package.json
  package-lock.json
  src/
    main.js
    backend-supervisor.js
    backend-identity.js
    lifecycle-coordinator.js
    recovery-store.js
    research-tabs.js
    navigation-policy.js
    permission-policy.js
    desktop-settings.js
    preload.js
  tests/
  README.md
static/
  desktop_bridge.js
  desktop_lifecycle.js
  research_panel.js
  research_panel.css
docs/
  inspectorpro-desktop-shell-implementation-plan.md
  inspectorpro-desktop-shell-acceptance.md
```

Use a separate checkout/worktree for the implementation after the hardening checkpoint. Keep runtime output outside tracked source. Avoid simultaneous broad edits to `static/index.html` or `server.py`; coordinate the few integration points.

The shared browser frontend should detect the desktop bridge. Browser mode should keep normal external-link behavior. Desktop-only dependencies must not become prerequisites for running the web application.

## 6. Backend lifecycle

### Attach mode: first development target

- Accept an explicit loopback URL and verify that it is the expected InspectorPro application.
- Bind it to a named backend profile and the stable identity contract below. A server's product name or HTTP 200 is not sufficient identity verification.
- Never attach silently to whichever process occupies port 8000.
- Do not terminate an attached backend when closing Electron.
- Expose attach status in diagnostics, without placing development details in ordinary workflow UI.
- Keep embedded research browsing disabled until that attached server satisfies the complete application access boundary in section 7. An ordinary unprotected development server may be used for the application-only prototype.

### Managed mode: internal application target

- Discover and explicitly configure the Python interpreter and working directory.
- Launch with an argument array and no shell-string concatenation; hide the Windows child console.
- Bind to the profile's canonical loopback address and persistent port under section 6.1. On contention, fail safely; never silently change the application origin or attach to the process occupying that port.
- Keep a record of the exact owned process and any managed descendants. Never kill processes by executable name or port alone.
- Wait for an application readiness handshake with bounded timeout and useful error details. Process existence and HTTP 200 alone do not prove workflow readiness.
- Add a narrow readiness endpoint only if no suitable current endpoint exists. Do not reuse an administrative health endpoint that exposes internal data.
- Keep startup states explicit: stopped, starting, ready, failed, stopping.
- Avoid development autoreload in managed mode; it complicates process ownership. Attach mode can support the developer's existing reload setup.
- On failure, offer retry and logs. Do not repeatedly restart a crashing backend without a bound.
- Follow the close/restart protocol in section 6.2 before graceful backend shutdown. A timeout must not silently authorize data loss or termination of active transactions. Only terminate verified owned processes after the lifecycle decision and the shutdown deadline.

Audit writable roots before introducing managed mode. A worktree must not accidentally bootstrap, migrate, or overwrite the user's live layout database or asset library. Use isolated test roots and fixture documents for acceptance testing.

### 6.1. Stable origin and storage identity

For Milestones A/B, use a direct, stable HTTP loopback application origin per backend profile. This avoids adding an application proxy or custom URL scheme before the existing APIs, streaming, assets, and storage are proven in Electron.

- Canonicalize the scheme, address, and port once; do not alternate between `localhost`, `127.0.0.1`, IPv6 loopback, or different ports on later launches.
- For a new managed profile, the backend may bind an OS-assigned port once and report the actual bound address through an authenticated startup channel. Persist that address only after identity/readiness verification and before loading the application. Subsequent launches must bind that same port; avoid the check-free-port-then-release race.
- Attach profiles use their explicitly configured, verified origin. Changing it requires a deliberate profile change/migration, not an automatic retry on a different port.
- Persist opaque backend and authoritative-store identifiers independently of the port, process ID, checkout path, and layout name. Phase 0 inventories each workflow's persistence root; the readiness contract must identify the store configuration it actually serves. Two stores containing `fl-main` must have different store identities. Store copies used for isolated tests receive a new identity.
- Bind the application storage partition to the desktop profile, backend/store identity, and authenticated principal scope. Bind document recovery records additionally to tenant/site/layout and document revisions. Research storage remains separate. On an unexpected identity change, block reuse of the old partition/recovery records and require explicit profile selection.
- Keep the origin stable across restarts so current browser storage remains available. A persistent Electron partition alone does not migrate data between web origins.
- If a port/origin change is necessary, export only enumerated chat/preferences keys through the trusted application, validate a versioned migration envelope, and import into the verified destination for the same backend/store/principal. Retain the old copy until the import is verified; do not transfer cookies, credentials, or unresolved transaction authority. If the old origin is unavailable, offer an existing verified export or a clearly labeled new profile; never silently present empty history as successful migration.
- Existing external Chrome/Edge history is not automatically available in Electron. Any web-to-desktop import is an explicit, scoped product action; never copy a browser profile directory.

Record these decisions in the runtime inventory before the interactive shell is frozen. Tests must cover an occupied port, backend restart, deliberate migration, and switching between two isolated stores with the same site/layout IDs.

### 6.2. Close, reload, restart, and crash contract

Implement one bounded lifecycle coordinator with workflow adapters. A generic dirty boolean cannot represent the existing transaction state. The main process requests an authoritative snapshot from the trusted application containing:

```text
intentId, reason (close | reload | backendRestart), rendererGeneration, stateSequence
backend/store/principal identity
documents: IDs, base/draft revisions, dirty state, journal/history cursor
pending operations: request/transaction IDs, phase, revision bindings, unknown outcomes
active jobs: IDs, owner, cancellation/detachment support
recovery checkpoint: schema version, identity, checkpoint ID, durable acknowledgment
```

These are proposed fields, not existing APIs. Each workflow adapter must declare its coverage. Unknown state, an unavailable adapter, or a stale reply cannot be treated as clean.

1. Intercept window close, application Quit, app reload shortcuts/menu actions, and managed backend restart before destroying any view. Give the intent a unique ID and prevent repeated requests from starting competing shutdowns.
2. Ask the application to prepare: stop accepting new mutations, release pointer lock, collect state, and let in-flight work settle or retain its recovery record. This preparation must not save, apply, Undo, clear history, or discard a proposal.
3. Require an initial reply within five seconds. Bound each automatic settlement attempt to fifteen seconds, then present the actual blocker with Wait/Cancel options. These are initial configurable deadlines, not permission to destroy the renderer when time expires.
4. Return `ready`, `needsDecision`, or `blocked` with the same intent ID, generation, and state sequence. Immediately before committing the action, revalidate that state; new edits, jobs, or transaction transitions invalidate the earlier decision.
5. For clean, settled work, proceed. For dirty work, default to Cancel; explicit discard may abandon only the identified local drafts after pending transactions are reconciled. If an existing workflow supports Save, the user invokes its normal Save path and the lifecycle coordinator checks again. Closing or restarting never synthesizes a Save or approval.
6. Cancel releases the temporary input freeze and preserves the exact draft, selection, history, and pending recovery handle. Do not reload as a way of canceling the close.

The behavior differs by event:

| Event | Required behavior |
| --- | --- |
| Normal close/Quit | Coordinate all open workflow adapters. Managed jobs must reach a confirmed safe cancellation/completion point before their backend is stopped. Attached jobs may remain on the independently owned server only when their status and reconnection behavior are known and explained. |
| Application reload | Run the same handshake. Dirty state needs a verified local checkpoint/restore path or explicit discard; otherwise cancel reload. Never accept an old response into a new renderer generation. Reloading a research tab does not reload the application. |
| Managed backend restart | Keep the application renderer and local draft where possible; quiesce operations, preserve recovery, restart only the owned process, then verify origin and store identity. Reconcile outstanding IDs before re-enabling mutation. Never automatically save or reapply a proposal. Attach mode offers reconnect, not ownership of the server's restart. |
| Renderer failure/unresponsive window | A handshake may be impossible. Use already durable records and backend transaction status; do not assume clean state or automatically restart the backend. Show a recovery entry point and retain unknown outcomes for reconciliation. |
| OS shutdown/process kill/power loss | No final callback is guaranteed. Recovery must have been persisted at transaction boundaries, not only during window close. Report any workflow whose ordinary unsaved edits do not yet have crash-recovery coverage. |

Electron provides a cancelable BrowserWindow `close` event [6] and renderer failure/unload events [3]. Use them to implement this protocol; do not treat `beforeunload` alone as durable recovery. In particular, overriding `will-prevent-unload` can permit an unload that the page tried to stop [3].

### 6.3. Durable transaction recovery

Use a narrow main-process recovery store under the user's application-data directory, with schema validation, identity checks, atomic replacement, and an acknowledgment only after the chosen durability operation completes. The renderer supplies structured records, never arbitrary filesystem paths. Research tabs have no access.

- Adapt the existing recovery hooks (`loadDesignUndoRecovery`, `persistDesignUndoRecovery`, `clearDesignUndoRecovery`) instead of building a second transaction implementation. Audit Apply, Undo, generation, and other workflow transitions independently: the current `sessionStorage` record only covers a particular design Undo path.
- Persist the known operation/transaction identity and required recovery frame before a transition that could leave the client uncertain after a crash. If an ID is returned by the backend, persist it before installing the next local state and retain the preceding request identity until the outcome is known. Close protection cannot repair a crash window between server preparation and client persistence.
- Cover `undo_acknowledgment_pending`: the restored local frame is not proof that the backend has acknowledged Undo. Keep the handle until authoritative reconciliation succeeds. A user discarding a local draft must not silently delete unresolved server transaction records.
- On restart, query authoritative transaction status and validate identity, revisions, and journal bindings. Only finish an already-authorized protocol step when its receipt permits it. Never replay a proposal Apply, infer new approval, or call Save as a recovery shortcut. Stale or conflicting records remain available for reviewed recovery rather than being installed over newer work.
- Distinguish transaction reconciliation from ordinary unsaved-draft restoration. If a workflow promises restoration, checkpoint the necessary local frame/history and validate its restoration path. Unsupported dirty workflows block controlled reload/close unless explicitly discarded; do not advertise universal crash recovery.
- A recovery-write failure blocks the dependent state transition or leaves it explicitly unresolved using the last durable request identity. Never claim the recovery handle is safe when only the renderer has it.

Acceptance must inject interruption before/after server preparation, local installation, and acknowledgment, including Undo whose acknowledgment response is lost. Restart must preserve the recovery handle, and canceling a normal close must preserve the exact editor frame and history.

## 7. Local backend access boundary

An isolated research renderer can still attempt network requests to localhost. Separate browser partitions alone do not secure local APIs.

This contract applies equally to attach and managed modes, across every workflow. Inventory all HTTP routes, WebSockets, authenticated static/private assets, helper endpoints, and any state-changing GETs. Exempt only enumerated public bootstrap/liveness resources with no sensitive content or effects. Do not assume `/api/facility-*` coverage protects chat, drawings, reports, libraries, workers, or native helpers.

Use a per-launch credential or an equivalent authenticated session mechanism. Managed startup exchanges it through a private local startup channel. Attach mode must authenticate/pair with the selected server through a verified channel and check a versioned backend security capability contract; a self-reported product name is insufficient. Exact pairing/bootstrap details and endpoint coverage must be recorded in Phase 0 before implementing this boundary.

Keep secrets out of URLs, logs, external tabs, and page-visible browser state. Limit credential injection to the trusted application webContents, approved frame context, and the exact verified backend origin. Cover streaming, downloads, and WebSockets deliberately; strip credentials across redirects and never provide them to research sessions or their workers.

Verify that malicious external pages cannot read private API responses, mutate layout state, connect to privileged WebSockets, or acquire native privileges. Do not rely on CORS alone as mutation authorization. Preserve the supported browser-access path with explicit authentication behavior rather than weakening the backend for compatibility.

Require backend authentication on sensitive reads as well as mutations, with deliberate browser-session/CSRF handling. Do not treat absent Origin, `Origin: null`, or an arbitrary loopback-origin alias as desktop authorization. Validate Host/authority and WebSocket handshakes. A narrow origin allowlist complements authentication; it does not replace it. Test the ordinary authenticated web application as well as the desktop path.

Enforce research request restrictions at session/network-request level in addition to navigation handlers. Cover frames, fetch/XHR, form submissions, images/scripts, workers, WebSockets, redirects, downloads, and new windows. Normalize address forms and exercise IPv4/IPv6 loopback, mapped/numeric aliases, hostname aliases, and DNS resolution/rebinding cases. An initial hostname check is not proof about the eventual network destination; authentication must still reject credential-free requests even if a network filter misses an alias. Keep any test-only loopback exception out of production configuration.

Maintain a single coordinated request policy per session so adding a download or telemetry hook cannot replace the security handler. If the chosen Electron mechanism cannot cover a request class, document and close that gap before enabling research, rather than assuming a navigation event covers it.

If an attached or managed server has not passed these requirements, expose `researchBrowsing: false` and use the ordinary external-browser fallback. Do not create external WebContentsViews in that mode. Application-only Phase 1 can proceed; arbitrary embedded research cannot. Report backend remediation as real implementation scope.

## 8. Research pane user experience

Use the supplied screenshots as interaction references, while matching InspectorPro's visual style.

- Clicking an external citation opens the pane and focuses a tab.
- Keep Scout/Sage visible where screen width permits; allocate the pane within or adjacent to the central workspace instead of making chat unusably narrow.
- Include tab title, loading indicator, close button, new-tab button, address/search input, back, forward, reload/stop, and expand/collapse controls.
- Preserve the main application instance. Pane transitions must not reload or remount the engineering workspace.
- Hide the pane without discarding its tabs; closing an individual tab disposes of it.
- Define duplicate-link behavior: initially focus an already-open exact URL, with an explicit action to open another copy.
- Define new-tab behavior: a local empty address/search page, with a configurable search provider. Treat text as a query and valid URLs as navigation; encode queries correctly.
- On narrow windows, provide an expanded research mode with an obvious return to the engineering workspace.
- Support keyboard operation, visible focus, accessible names, and sensible focus return when the pane closes. Avoid hijacking shortcuts while typing in chat or the viewport's precision controls.

Native view geometry is an implementation risk: test display scaling, zoom, scrolling, resize, maximize, multiple monitors, and modal overlays. A native browser view must not cover application menus, dialogs, or the divider. Clamp view bounds in the main process; temporarily hide or reposition it when overlays require it.

Test that viewport resize updates the canvas and pointer coordinates. Reopening research must preserve camera, selection, active workflow, chat position, and unsaved facility journal.

## 9. Tab and navigation implementation

Keep tab state in the main process; expose a serialized UI projection containing tab ID, URL, title, loading state, and navigation availability. Treat website-provided titles and URLs as untrusted text.

Proposed bridge operations:

```text
research.open({url, disposition}) -> {tabId}
research.navigate({tabId, url})
research.activate({tabId})
research.close({tabId})
research.back({tabId}) / forward({tabId}) / reload({tabId})
research.setPaneState({visible, bounds})
research.subscribe(listener) -> unsubscribe
desktop.getCapabilities()
```

These are design sketches, not a finalized API. Validate each payload, target tab, sender webContents, and frame. No generic IPC dispatch, arbitrary command strings, filesystem access, or script evaluation belongs in this bridge.

Route application links centrally with a small integration point. Preserve same-page anchors, application routes, report exports, and asset links. Handle `target=_blank` and script-created windows as well as ordinary anchor clicks. Website popup/authentication flows need deliberate testing: blindly converting every window request to a fresh unrelated view can break opener/session behavior.

Default research navigation to HTTPS. Reject executable schemes and block access to InspectorPro's privileged local origins and aliases under section 7, including subresource requests rather than just navigation. Apply policy again on redirects and new windows. Provide a deliberate external-browser fallback for unsupported websites, authentication, or protocols. Do not promise every site will behave exactly as it does in a full consumer browser.

## 10. External-content isolation

Use sandboxed external renderers with Node integration disabled, context isolation enabled, and web security retained. External pages receive no InspectorPro preload. Keep application and research browser sessions separate. Validate IPC senders, navigation, window creation, permissions, and external protocol requests. Retain certificate validation. These boundaries follow Electron's official security guidance [2].

### Permission matrix for Milestones A/B

Install both `setPermissionRequestHandler` and `setPermissionCheckHandler` on each relevant session; Electron documents that both are needed for complete handling [5]. Implement one policy function shared by the two handlers and validate the requesting origin/frame, not only the top-level URL. Reject unknown permissions, missing/ambiguous requesting identities, research subframes, and background permission requests unless a specifically supported policy covers them. Add device/display-capture handlers where the pinned release requires separate APIs; a permission callback is not a universal interception mechanism.

The following is the InspectorPro product policy, not Electron's default behavior:

| Capability | Trusted application | External research content |
| --- | --- | --- |
| Microphone/audio capture | Permit only the verified application frame following the user's voice/recording action and consent. Deny camera/video additions to an audio request. Honor OS denial and stop capture through the existing control. | Deny; use external-browser fallback if a site requires it. |
| Camera, screen/desktop capture | Deny in A/B unless the workflow inventory proves an existing required feature and adds a specific picker/consent contract before acceptance. Canvas recording does not automatically require desktop capture. | Deny. |
| Clipboard read | No ambient read. Permit explicit Paste in the focused app through standard user interaction or a narrow validated action; preserve platform paste without granting background polling. | Deny programmatic reads. Test explicit native paste separately; do not claim permission handlers disable every operating-system paste action. |
| Clipboard write | Permit explicit Copy/export actions in the app. No arbitrary background writes or generic clipboard IPC. | Deny programmatic grants by default; allow normal user-selected text Copy through tested native commands without an InspectorPro bridge. |
| Pointer lock | Permit the active application viewport following explicit walkthrough/drone entry. Release on Escape, app blur, or research-pane focus; require deliberate re-entry. | Deny. |
| Fullscreen | Permit explicit application fullscreen through shell-owned controls. | Deny page-requested fullscreen; expanding the research pane is shell UI. |
| Notifications, geolocation, MIDI, USB, HID, serial, Bluetooth, persistent filesystem access | Deny until a concrete existing workflow has a reviewed, narrowly scoped requirement. Native file upload/download pickers remain explicit actions under their own policies. | Deny. |
| Unknown/future permission types | Deny and record a non-sensitive diagnostic. | Deny. |

Do not implement the permission-check handler as unconditional approval just to make the request handler run. Map actual permission names and media details against the pinned Electron version. Test microphone grant/denial, explicit Copy/Paste, pointer lock and Escape, subframes, revoked consent, and focus transfer to a research view. No broad local filesystem or command execution permission is added by this matrix.

Default to session-only research storage for the prototype. Decide explicitly whether later versions retain logins and browsing history; provide clear-data behavior if persistence is enabled. Do not copy the user's Chrome/Edge profile into the shell.

Downloads should require a selected destination or a configured download location and produce visible status. Do not auto-execute downloaded content. Distinguish normal InspectorPro report downloads from external research downloads. Test PDF viewing, download cancellation, and native file dialogs.

## 11. Workflow acceptance matrix

Use representative fixtures and isolated persistence. Record desktop/web comparisons and outstanding limitations.

| Workflow | Representative acceptance |
| --- | --- |
| Drawing inspection | Open/upload a supported drawing; navigate features; complete an available inspection path; display results. Separate mocked-provider tests from live-provider runs. |
| Assembly and 3D | Load a representative assembly and real GLBs; orbit/pan/zoom/select; resize and reopen research; check hit testing, camera, asset-library access, textures, and rendering. |
| Process maps | Open a map; edit and undo using a fixture; verify menus, drag interactions, and persistence against the test root. |
| Facility layout/manual tools | Load representative published assets from an isolated fixture with real GLBs; select, move, pattern, Undo; verify draft revision, journal, attachments, and asset-library access. Keep the live manual layout unchanged. |
| Motion, walkthrough, and drone | Play a configured motion fixture while switching research focus, walkthrough, and drone. Follow existing mode semantics; preserve playback position/state where supported, verify intentional pauses, pointer lock/release/re-entry, camera and controls, and no unintended remount. |
| Sage construction pilot | Run the existing four-command acceptance in Electron: undersized-envelope refusal, corrected three-cell/nine-placement preview, attachments in all copies, explicit unsaved Apply, duplicate-retry no-op, stale retry rejection, and exact Undo. Record zero Save calls. Distinguish deterministic/provider-mocked checks from a live-provider run. |
| Proposal and transaction continuity | Open/resize/close research while preview, Apply, or Undo is pending; advance the editor or switch documents before a delayed result returns. The old result must not replace the newer state or gain approval. Verify lost Undo acknowledgment recovery across renderer restart. |
| Scout/Sage chat and voice | Send/stream a message through an available test path; follow citations; preserve conversation context and input focus. Verify microphone grant/denial, stopping capture, and standard Copy/Paste in the actual Electron window. |
| Reports | Preview and export available formats; verify paths and file contents. |
| Sessions/library/settings | Reopen saved fixture state; verify asset URLs and preferences in desktop and browser mode. Restart on the stable origin and verify chat history. Verify explicit origin migration and no state/recovery crossover between two stores named `fl-main`. |
| Native helpers | Confirm existing integrations still work where configured; explicitly mark unavailable dependencies rather than claiming coverage. |

Inventory additional current workflows before freezing the matrix. This table does not claim the older README is the complete feature list.

Reuse `tools/capture_facility_construction_sage.py` and its assertions as the provider/browser baseline, adapting browser connection and window interaction for Electron. Do not assume the current browser harness already supports Electron. Start with isolated stores and the pilot-only construction flag. Preserve the unchanged tested prompt from the integration report; do not weaken the geometry or counts to obtain a pass. One live pilot demonstrates that scenario, not a general model success rate.

## 12. Testing strategy

Add meaningful focused tests for the new boundaries:

- Supervisor: timeout, crash, stable-port collision, failed identity/credential handshake, attach-versus-owned shutdown, and no termination of unrelated processes.
- Access boundary: in both modes, attack representative facility and non-facility read/mutation/helper routes and WebSockets without credentials. Cover absent/null/untrusted Origin, allowed-origin confusion, local-address aliases, redirects, subresources, workers, and Host/DNS cases. Verify both backend rejection and research-session blocking where applicable. Unprotected attach must advertise research as unavailable.
- IPC/navigation/permissions: reject wrong senders, subframes, unsafe schemes, privileged local origins, malformed tab requests, and unsolicited permission requests. Verify both permission handlers and the permitted application voice/clipboard/pointer-lock paths.
- Browser lifecycle: tabs retain independent history, popup policy is applied, closing disposes resources, and pane toggling preserves the app.
- Frontend fallback: without a desktop bridge, existing web workflows and links still work.
- Draft preservation: closing/reopening research does not change layout revision, selection, journal, or Save count.
- Lifecycle: cancel close with an unchanged draft/history; close/reload during Apply and Undo; lost acknowledgment; renderer failure before/after each transaction checkpoint; recovery-store write failure; bounded unresponsive handling; managed restart without automatic Save or proposal reapplication. Assert the retained request/transaction identity as well as UI text.
- Storage identity: stable-origin relaunch retains chat/preferences; an occupied port cannot redirect into a fresh storage origin; origin migration is verified; two backends/stores/principals cannot share document recovery accidentally.
- Async state: delay preview/approval/asset-load responses while research opens and the app advances generation or changes document; verify that stale responses are rejected using existing identity/revision checks.

Run an actual Electron-window acceptance pass; Node unit tests alone cannot establish native view placement or browser isolation. Test at common Windows scaling levels, including 100%, 125%, and 150%.

Use controlled local test pages for popup, redirect, permission, and navigation failures in an isolated test environment. Use a small representative set of real documentation sites and PDFs for compatibility; do not make CI depend on arbitrary live websites.

Record startup time, representative viewport responsiveness, memory with several research tabs, and memory after closing them. Capture the browser baseline first; agree numeric regression thresholds from measurements rather than inventing a performance guarantee.

## 13. Implementation sequence and exit gates

### Phase 0 — checkpoint and runtime inventory

Record the reviewed hardening/Sage pilot revision, current dirty changes, launch recipe, data locations, instructions, and dependencies. Create an isolated implementation checkout with isolated test storage. No live data writes.

Inventory all workflow endpoints and persistence roots, existing lifecycle/recovery hooks, permission-dependent features, and native helpers. Record the stable origin/profile/store identity contract from section 6.1, the concrete authenticated startup/attach handshake from section 7, and each workflow's close/recovery coverage. List gaps as implementation tasks with owners and acceptance evidence; do not count the existing facility-only origin middleware as the completed backend boundary.

Verify a supported compiler runtime for the existing `node` subprocess path. For developer-installed A/B, a pinned, explicitly configured Node installation is acceptable. For later distribution, prefer a bundled Node executable resolved by a reviewed explicit path; changing to an Electron utility process is a separately tested compiler-host change, not an automatic consequence of using Electron.

Exit: repeatable web launch, written runtime/data/endpoint inventory, chosen origin and identity contract, specified close/recovery protocol and permission policy, and a concrete backend-protection design. Phase 0 can begin now. Unresolved implementation details are listed as blockers for the affected later gate, not silently deferred until research is enabled.

### Phase 1 — attach-mode shell

Create `desktop/`, pin dependencies, launch the full UI against an explicitly supplied local backend, and implement stable profile storage, safe app navigation, the lifecycle bridge, and the permission matrix. Add durable transaction recovery through the existing workflow hooks. Verify main rendering and input workflows. An initial read-only rendering spike may precede recovery implementation; it is not the accepted interactive shell.

Exit: an actual Electron window runs all representative workflow entry points, while browser mode still launches unchanged. Canceling close preserves the draft/history, transaction recovery survives restart, and voice/viewport input permissions pass. Research remains disabled on an unprotected attached server. Do not freeze the interactive shell before these lifecycle and identity requirements pass.

### Phase 2 — managed backend and access boundary

Implement supervisor, readiness, logging, ownership, controlled shutdown/restart, and complete backend session protection. Apply the same security contract to attach mode and verify all workflow route classes, assets, streams, and sockets. Implement and test the chosen pairing mechanism. A generic “close app” confirmation must not falsely imply that unsaved work is recoverable.

Exit: startup/failure tests pass; credential-free external traffic cannot read sensitive or mutate privileged local endpoints in either mode; the supported web client remains functional; unrelated servers survive application closure. Both modes need explicit evidence before their research capability can be enabled.

### Phase 3 — tabbed research pane

Add native views, pane UI, link routing, navigation, popup handling, download behavior, request restrictions, isolation, and browser fallbacks. Gate creation of research views on verified backend protection. Test layout preservation, pending transactions, permission/focus changes, real assets/motion, and real-site compatibility.

Exit: the screenshot-inspired browsing interaction works end to end, with no application reload, stale-result replacement, or unintended Save. Navigation, subresource, redirect, and permission tests pass in both protected attach and managed modes.

### Phase 4 — internal release acceptance

Complete the strengthened workflow matrix, accessibility checks, lifecycle/recovery fault injection, performance comparison, and operational instructions. Run the unchanged bounded Sage construction acceptance in the actual Electron environment and document provider availability. Produce a limitations list and evidence report; unavailable live-provider coverage remains explicitly incomplete.

Exit: internal users can launch from a documented command/shortcut and use the complete application plus research pane reliably. This remains a developer-installed release.

### Phase 5 — separately scoped distribution

Choose a packaging tool after validating runtime needs. Bundle Python and its dependencies, the supported construction compiler runtime, fixed compiler scripts/contracts, and licensed redistributable assets; define writable user-data locations, configuration migration, signing, updates, crash diagnostics, and rollback. Test on a clean Windows machine without the developer's Python, Node, environment files, or repository paths, including a real compiler invocation. Do not bundle private keys or proprietary assets without an explicit distribution decision.

Exit: installer and upgrade paths are tested independently of the development machine.

## 14. Connection to Sage and the knowledge architecture

The browser pane displays sources; it does not automatically make those pages readable or controllable by agents. Future page extraction must be an explicit, bounded capability with provenance and content treated as untrusted evidence.

The research workflow should remain in shared backend services: retrieve evidence, maintain a research record, compile a planning package, then use existing authorized planning/construction paths. The shell can display evidence and collect user actions without becoming a second planner.

Do not use desktop privileges to bypass facility capabilities, revision checks, durable idempotency, review, Undo, or explicit persistence. Opening a browser tab neither approves a proposal nor grants a website local command access.

## 15. Agent handoff and reporting requirements

- Implement one phase at a time and report its exit gate with evidence.
- Preserve unrelated in-progress changes and the user's manual reference layout.
- Prefer small shared integration patches; keep desktop implementation primarily under `desktop/`.
- Record exact commands and versions needed to reproduce the shell.
- Report tests by actual scope: unit, kernel, Electron UI, provider integration, or clean-machine packaging.
- Keep app startup logs free of credentials and sensitive document content.
- Document deviations and their reasons. If packaging or authentication exposes substantial hidden work, revise the estimate before calling the shell complete.

Earlier conversational estimates of roughly 1–2 weeks for an internal version and additional weeks for distribution are preliminary effort ranges, not deadlines. Runtime inventory and the native-view prototype should drive the revised estimate.

The complete backend access boundary, durable lifecycle recovery, and storage migration are real integration work beyond displaying the web UI in a window. Revise the estimate after Phase 0 identifies coverage gaps; do not retain an earlier thin-wrapper estimate by dropping these requirements.

## 16. Review disposition and implementation evidence

All five supplied review findings are accepted as plan corrections. They identify contracts that must be implemented, not evidence that the new behaviors already exist.

| Review finding | Revision and acceptance location |
| --- | --- |
| P1: protect attach mode and every workflow | Section 7; access-boundary tests in section 12; Phase 2 gates both modes, and unprotected attach cannot create research views. |
| P1: executable close/restart contract | Sections 6.2–6.3; lifecycle fault injection in section 12; Phase 1 requires durable transaction recovery before interactive acceptance. |
| P2: origin/storage identity | Section 6.1 chooses a stable per-profile loopback origin and isolated identity; Phase 0 records it and section 12 tests restart, migration, and store separation. |
| P2: permission matrix | Section 10 names default denials and narrowly permitted voice/clipboard/viewport behavior, with both Electron permission handlers. |
| P2: acceptance of actual working features | Section 11 adds real GLBs/library access, motion and camera modes, the four-command Sage pilot, and stale/pending-proposal scenarios. |
| Outdated Sage integration statement | Section 2 now records bounded live integration; Phases 0/5 explicitly cover its Node compiler dependency. |

Repository evidence reviewed for this revision: `server.py` (`_facility_layout_same_origin_boundary`, `_request_origin_is_trusted`); `static/facility_layout_app.js` (`designUndoRecoveryStore`); `static/facility_layout_session.js` (`installPreparedDesignUndo`, `acknowledgePendingDesignUndo`, `resumeDesignUndoRecovery`); `static/index.html` (chat registry, microphone and pointer-lock paths); and `ai_inspector/facility_layout/construction_compiler.py` (fixed Node subprocess). These are implementation observations at this checkpoint, not promises about future code.

## 17. Official implementation references

These references establish Electron mechanisms; the architecture and phased scope above are InspectorPro-specific proposals.

1. [Electron WebContentsView](https://www.electronjs.org/docs/latest/api/web-contents-view) — native views for independently hosted web content.
2. [Electron security guidance](https://www.electronjs.org/docs/latest/tutorial/security) — renderer isolation and privileged boundaries.
3. [Electron webContents API](https://www.electronjs.org/docs/latest/api/web-contents) — navigation, window requests, lifecycle, and events.
4. [Electron web embedding options](https://www.electronjs.org/docs/latest/tutorial/web-embeds) — embedding approaches and iframe limitations.
5. [Electron session API](https://www.electronjs.org/docs/latest/api/session) — request/check permission handlers and session configuration.
6. [Electron BrowserWindow API](https://www.electronjs.org/docs/latest/api/browser-window) — cancelable window-close event and window lifecycle.

Verify APIs against the pinned Electron release before implementation; do not copy deprecated BrowserView examples into new code.
