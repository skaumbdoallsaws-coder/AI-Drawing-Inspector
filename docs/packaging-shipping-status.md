# Packaging and Shipping: Isolated Pilot

Date: 2026-11-06. Status: promoted to the local regular desktop build. Earlier sections retain their historical pilot results; the desktop checkpoint below supersedes their deployment status.

## Desktop Promotion Checkpoint

Packaging was merged into the current desktop source after the columns review changes, not copied over them. Normal application mode opts in through `packagingRuntime` in its explicit profile. The optional configuration supplies a dependency directory and a separate STEP interpreter; its persistent documents live under `dataRoot/packaging`. Existing Codex authentication, model-gateway configuration, facility roots and startup layout stay unchanged. Neither Claude's checkout nor saved facility documents are part of the promotion.

The development desktop uses `requirements-packaging.txt` and `requirements-packaging-step.txt` in a separate local runtime directory. GLB and STEP workers run isolated with explicit dependency paths; they do not execute `.pth` startup files or inherit carrier credentials. This is local development deployment, not a signed redistributable installer or a completed third-party license review.

Native acceptance in `.runtime/native-packaging-01/evidence-07` passed: authenticated iframe, main ribbon, manual packing and mass validation, Undo/Redo, nonblank camera pixels, native PDF download, real five-solid STEP import with four-pair quantity, compact window layout, guarded departure, backend restart and saved-document reopen. A controlled backend stop also passed clean departure through the native menu while the renderer was inert, followed by restart. This is not hard-crash recovery. Original CAD bytes remained unchanged. No inference or live carrier request was made.

The mounted editor still prevents native close/reload/restart. Save, then choose the ribbon's **Document > Close Packaging** before leaving the app. Press **Alt**, then **Document > Close Packaging** for the native menu while the renderer is inert; it permits only clean, idle departure. Unsaved work, conflicts, file selections, dialogs and Sage admission/reconciliation remain guarded. This is not crash recovery or an autosave promise.

Verification: 783 packaging/Codex/profile Python tests passed with 12 optional geometry skips; the configured STEP suite then passed all 58 tests including the real assembly. The current columns/floor-plan subset has 179 passes and the same 29 `parse_unavailable` failures on both the unmodified desktop source and the integration worktree. Those baseline failures are not reported as fixed.

Final isolated-worker regression: 266 passed, one optional proprietary-sample skip, plus 29 focused checks. Runtime acceptance at `.runtime/packaging-release-imports-03` imported a GLB ring and STEP bored block using the deployed dependency locations, with correct mesh dimensions/STEP volume, desktop/mobile render pixels, view changes and PDF outputs; zero browser errors or external requests. The affected desktop/packaging JavaScript subset passed 194 tests. Profile-promotion backup/idempotency checks passed two tests. This is not a claim that the full legacy application suite is green.

Enable only after native checks pass using `tools/enable_desktop_packaging.py`. It validates the profile and dependencies, writes an exact backup beside the profile, detects concurrent profile changes, and changes only `packagingRuntime`. The regular desktop shortcut stays in place. Live shipping quotes still require a privately entered carrier account and verified shipping inputs; no rates, purchase or destination-coverage claims are inferred from mock tests.

Local promotion completed at `3ce2b05`, with the prior source retained as `before-packaging-desktop-20261106`. The regular profile was backed up beside itself and its non-packaging values compared equal after activation. The regular shortcut launched the updated source, the protected backend reported ready, and the native window was present and responsive. The permanent packaging database was initialized separately from the pilot/test stores. Pilot documents were not bulk-copied, and no live carrier credentials were entered. The pre-existing untracked implementation plan was preserved under the workspace's `.runtime/packaging-promotion-backup-20261106` before the updated tracked plan was installed.

## Current V2 Checkpoint

The active updated test host is `http://127.0.0.1:8181/?packagingPilot=1`; standalone workspace: `http://127.0.0.1:8181/packaging`.
Its data is isolated under `.runtime/packaging-v2-acceptance`. The previous visible demonstration on port 8180 is not the current backend.

### Ribbon And Viewport Consistency

The embedded packaging workspace now uses the main application's shared workflow ribbon, icon assets, command sizing, dropdowns and density. Product, Carton, Contents, Arrange, Appearance, Graphics, Validation and Rates open the existing modeless panels. Document actions, Save and Undo/Redo live in the outer ribbon; narrower windows retain commands in More/Document menus. The duplicated embedded title and ribbon are hidden only when hosted; the standalone editor retains its commands.

The viewport uses a centered heads-up toolbar with the existing view/display icons and hover titles, section/exploded toggles and transparency. Document/package selection stays in one compact context row. Status sits in the footer, and the host theme propagates to the editor and 3D background without remounting the document.

Both ribbons dispatch through the same controls and draft handlers. Busy requests, modal dialogs and Sage admission disable the outer controls; Resume editing still cancels and reconciles through the existing host bridge. No new engineering edit path or model request was introduced.

Verification for this UI increment: 61 packaging JavaScript tests plus 83 desktop lifecycle tests passed. The full-host browser checks passed at 1600/1280/1000 widths, with and without Sage, including modal/lock rejection, focus return, theme sync, canvas pixel changes, no iframe remount and numeric editing when WebGL is unavailable. The existing saved four-pair STEP package was opened for section/top screenshots and its complete saved response remained unchanged. Evidence: `.runtime/packaging-ribbon-release-check/`. Standalone desktop/mobile acceptance also passed, including all eight panels, 390px width, source import, section/exploded views, graphics and Undo: `.runtime/packaging-ribbon-panels-final/`. No live inference or carrier request was made for these UI checks. The regular desktop build remains unchanged.

Implemented since the baseline below:

- Icon ribbon with modeless Product, Carton, Contents, Arrange, Appearance, Graphics, Validation and Rates panels. Closing a panel restores the full viewport; unapplied inputs remain protected.
- Gray shaded, shaded-with-edges, wireframe and saved-appearance modes; transparency, section and exploded inspection. Display controls do not change physical properties or Undo history.
- Optional owned STEP worker with explicit units, BRep bounds and summed closed-solid volume; bounded CPU/memory/time, hidden processes, cancellation cleanup and no carrier credentials. Its OCP dependencies are separate from the main Python environment. GLB remains an envelope source, not solid-volume evidence.
- Density-based product estimates bound to immutable STEP revision/volume, retaining material evidence and exclusions. They remain estimates, not verified CAD material mass.
- Rectangular/cylindrical top-open insert pockets, side-wall/floor/web checks, material-intersection checks and net-volume insert mass. Invalid pockets leave mass unknown. These checks do not certify protection or a complete removal sequence.
- Full-blank area/basis-weight carton tare estimates, with evidence and explicit unknown inputs preserved.
- Cited PMMA and Ethafoam density presets and an initial ULINE carton preset. No invented material prices, payload ratings, shipping prices or cushioning approvals.
- Scoped alpha-preserving PNG/JPEG artwork and face-bound lettering on cartons/inserts. Normalized fit regions resize with the target face; artwork does not change mass.
- Up to 20 immutable named alternatives per document, revision checks, idempotent save, volume/mass/known-material-cost comparisons. Apply uses ordinary edits and Undo. Unknown cost is not zero.
- Schema 2 migration with a pre-upgrade SQLite backup for schema 1 stores. Existing documents, source IDs, receipts and Undo/Redo are retained.
- Durable, scoped first-save idempotency. Exact retries return the original creation result across server restarts; conflicting content is rejected. The UI retains its request key after a lost response. Existing unkeyed clients remain compatible.
- Current-user Windows DPAPI carrier account storage and manual account endpoints. Saved credentials, replacement and removal are distinct from environment fallback; no secrets enter Sage tools or document JSON. Live carrier credentials are still absent.
- Malformed, oversized and excessively nested editor transitions invalidate the old admission rather than leaving Sage authorized to edit a previous selection. Non-binary mutation body limits apply regardless of JSON content type.
- Desktop observation includes the actual packaging iframe, unapplied fields, selected files, requests, dialogs and Sage admission/reconciliation. This is a fail-closed guard, not native draft recovery: an open packaging workspace must be exited before native close/reload/restart is allowed.
- Sage can discover scoped sources/catalog/alternatives, calculate a documented STEP density estimate, edit all supported document fields and provide a revision-specific PDF download link. File upload and carrier requests remain manual UI operations; no shell, account-secret or shipment-purchase tool is exposed.
- Expanded draft PDF with density/exclusions, carton provenance, net insert/pocket details, graphics schedule, findings and revision-bound quote snapshots.

### Real Acceptance

- User-approved straight rack/pusher STEP imported through the actual API: five solids, unchanged original hash. Four copies represent four racks and four pushers. PMMA-only product mass estimate: **1.726154403 kg total**, excluding magnets, adhesive and packaging.
- A four-pocket concept passed supported geometric checks and rendered at desktop/mobile sizes without page errors. Carton tare, allowance and handling remain unknown, correctly blocking rates. Original CAD was not modified. Evidence: `.runtime/packaging-v2-real-step-01/`.
- A real ChatGPT-plan Sage turn through the main chat pane read the catalog and source evidence, estimated mass, validated, saved and revalidated, then returned a draft PDF link. Ten successful tool calls, no API billing fallback. Placements, inserts, graphics and unknown inputs remained unchanged; manual Undo/Redo passed. Evidence: `.runtime/packaging-v2-sage-resources-01/`.
- Combined Python regression: **894 passed, 1 optional proprietary-file test skipped**, with two upstream WebSocket deprecation warnings. That optional test was then run against the user-approved straight STEP and **passed**, checking five solids, exact bounds/volume, rendered extents and unchanged original bytes. After the final credential-owner encoding change, the affected account/API suite passed **69 tests**.
- Workspace/host JavaScript: **57 passed**. Three final Playwright suites passed with no page errors: `.runtime/packaging-panels-final-01`, `.runtime/packaging-resources-final-01`, `.runtime/packaging-host-final-01`. They cover desktop/mobile canvas pixels, the lost-first-save response, ribbon dialogs, source imports, density evidence, alpha artwork, alternatives/Undo, synthetic account UI and live-editor admission/reconciliation. Synthetic carrier tests are not evidence of real quotes.
- Dedicated desktop packaging lifecycle contracts: **83 passed**, using actual renderer/preload/main source with mocked native effects. Full desktop suite: **791 passed, 11 failed**. The same 11 failure locations reproduced with the pre-guard source/fixture: seven startup fixtures, two facility-mount fixtures, one panel regex and one documentation-generation fixture. No new lifecycle regression was found; this is not a clean full-desktop release result.
- The three-page expanded report was rendered and visually inspected; additional real-product PDF output is in the STEP evidence directory. Reports remain draft reviews, not a manufacturing or protective-performance certification.
- Earlier counts below describe previous checkpoints, not a current desktop release.

### Remaining Release Gates

- Carrier credentials entered privately, actual package/weight confirmation and valid origin/destination scenarios, then real account/service comparisons. No claim of universal US carrier or destination coverage before that acceptance.
- Full native Electron acceptance, recoverable packaging workspace integration and dependency/license deployment checks. Lifecycle contract tests do not substitute for launching an isolated release snapshot. No change to the production desktop profile, Claude's copy, or saved facility layouts.
- The new observation guard covers normal application mode and the facility-attached managed runtime. The legacy managed runtime's unattached transition path does not invoke that observer. Do not enable packaging in that mode until its transition contract is extended and tested.
- Direct selected-assembly/configuration integration, manufacturing-ready packing/removal instructions, no-contact constraints, additional stock-carton records and storage retention/quota policy are still broader release work.
- Sage does not yet initiate carrier requests or upload files. It uses already authorized uploaded sources and the same validated editing service.
- Complex contour inserts, mixed products, cushioning simulation, dielines, SolidCraft, pallets/crates/freight and shipment purchase remain outside this increment.

### Optional STEP Runtime

`requirements-packaging-step.txt` pins the optional OCP worker dependencies. Run `tools/setup_packaging_geometry.py` with Python 3.11 to provision the worktree-local `.runtime/step-venv`; `--check` verifies an existing installation. The Sage pilot detects this local environment. Other hosts must explicitly set `INSPECTORPRO_PACKAGING_GEOMETRY_PYTHON` to its absolute executable path. No dependency is installed into the normal desktop environment.

The worker has resource limits, rejects supported external-reference forms and receives a restricted environment. It is **not an OS security sandbox** and still runs as the current Windows user. Binary redistribution, native dependency notices and security hardening remain release gates. Account credentials are never sent to the geometry worker.

The full test host intentionally does not contain the normal desktop's private assembly registry/library. Its existing missing-registry/legacy-provider startup warnings do not prevent packaging, but this host is not proof that unrelated workflows are release-ready.

## Historical Baseline

The sections below retain the earlier pilot's implementation and verification history. Where they describe a feature as missing, the Current V2 Checkpoint above takes precedence.

## Isolation

- Worktree: `C:\Users\might\OneDrive\Desktop\InspectorPro\.runtime\packaging-shipping`.
- Branch: `packaging-shipping-2026-11-05`, starting at `ed68c363b8c14289fd5b304280dc1e321f924b24`.
- The regular desktop checkout, Claude's CopilotTest copy, existing layouts, and source CAD were not edited or promoted.
- All packaging databases, browser screenshots and test documents are under this worktree's `.runtime/`. Test documents are labelled `TEST`.
- The separate pilot runs on `http://127.0.0.1:8179/packaging`. It does not load the main application's environment file, start Codex, or purchase postage.
- The full Sage test host runs separately at `http://127.0.0.1:8180/?packagingPilot=1`, with isolated engineering data, enforced conversation memory and the explicitly selected existing ChatGPT account. API billing fallback is disabled.

## Working Now

| Area | Implemented behavior |
| --- | --- |
| Document | Separate scoped SQLite store, schema version 1, optimistic revisions, atomic edit receipts, 30-step Undo/Redo, save/reopen. SI meters/kilograms, Y-up. |
| Product | Manual bounding dimensions or self-contained static GLB import, explicit source units, immutable imported dimensions/revision, documented measured or estimated mass. Missing mass remains unknown. |
| Import worker | 24 MiB input, bounded geometry, no external GLB resources, no animation, hidden subprocess, 25-second timeout and cancellation cleanup. Credentials excluded from worker environment. |
| Manual assembly | Up to 48 identical products, 10 cartons, numeric positions, six proper orthogonal rotations, solid rectangular pads/dividers/spacers with density evidence. No source-model scaling to make it fit. |
| Inspection | Local bundled Three.js viewport, actual imported mesh instances, fit/orbit/top/front/side views, carton transparency, section/exploded inspection, selection and source warnings. |
| Mass and validation | Quantity-aware product mass plus solid-pad volume times density, carton tare and explicit packing allowance. Conservative envelope overlap/containment, orientation/gap/clearance and supplied payload limits. |
| Arrangement search | Existing MIT-licensed py3dbp solver, up to six carton alternatives and six boxes per search, independent validation, bounded cooperative search. Replacing an arrangement is explicit and undoable. |
| Rating adapter | Quote-only EasyPost requests, up to three US destinations and 12 package/destination combinations, kg/m conversion to oz/in, account/currency/mode-aware totals, Decimal arithmetic, revision-bound snapshots, sanitized failures and a 65-second overall deadline. |
| Reports | Revision-bound draft PDF with product/source data, mass evidence, material BOM, top envelope diagram, placement schedule, findings and any current quotes. |
| Sage adapter | Inspect, validate, propose, edit, Undo and Redo contracts over the same service. Editing requires refreshed host context, direct-edit authorization, a mutation lease, revisions and bounded calls. See `packaging-sage-integration.md`. |
| Host hook | Main app entry is development-only: backend `INSPECTORPRO_PACKAGING_ENABLED=1` plus browser `?packagingPilot=1`. Sage additionally requires `INSPECTORPRO_CODEX_PACKAGING=1`. Saved-editor admission, heartbeat, mutation lease, revision checks, cancellation/reconciliation and streaming reuse the existing runtime. |

The geometry status remains `needs_review` even with no detected errors. A fit check is not a cushioning, stacking, support, removal, or transport certification. Carton tare is entered with evidence; it is not computed from the carton bounding volume. Product appearance is not physical material evidence.

Only an applied candidate is saved with the document. Unapplied alternatives and destination street-address inputs are session-only. Quote snapshots retain a scenario fingerprint and city/state/ZIP, not the full street address. Every quote shows its timestamp and account/mode; the interface does not claim a price guarantee.

## Verification

The reproducible checks are:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_packaging_shipping.py tests/test_packaging_rating.py tests/test_codex_packaging_tools.py tests/test_codex_packaging_mcp.py -q --tb=short --basetemp=.runtime/packaging-check-NEW
node --test tests/packaging_ui.test.cjs tests/packaging_host.test.cjs
.\.venv\Scripts\python.exe tests/verify_packaging_browser.py
.\.venv\Scripts\python.exe -m pytest tests/test_codex_sage_route.py tests/test_codex_chat_http_boundary.py tests/test_codex_mcp_schema_types.py tests/test_codex_readonly_pilot.py -q --tb=short --basetemp=.runtime/packaging-regression-NEW
```

Choose a fresh basetemp suffix; pytest clears its selected temporary test directory. Run only in this worktree. Never point a test storage root at the regular desktop data.

- Browser acceptance has passed on 1440x1000 and 390x844: manual six-item arrangement, pad mass, save/reopen, Undo/Redo, PDF, disabled unconfigured quotes, camera changes and nonblank canvas pixel checks. No page errors or horizontal overflow.
- A repository CAD-derived GLB (`RB-001_viewer.glb`) was imported, rendered and packed as six independent instances. The test does **not** establish its physical dimensions against native CAD or prove a mass reference; its mass correctly remains unknown.
- The PDF was rendered using PDFium and both pages visually inspected. This is test evidence, not a release-ready packaging specification.
- Existing Codex/Sage routing and MCP regression subset: 119 passed after installing the existing pinned MCP dependency in the isolated venv. This is not the full application's regression suite.
- Final packaging-specific counts are recorded at the bottom after the last run. Carrier fixtures use `httpx.MockTransport`; no live carrier price or coverage has been verified.
- Main app inline scripts parse and iframe guard contracts pass, but the full Electron workspace has not been launched or tested in this isolated branch.

Browser evidence: `.runtime/packaging-browser/` (local only, not for distribution). Its `result.json` records viewport checks and pixel statistics.

## Running The Pilot

The pilot uses the existing app's base dependencies plus `requirements-packaging.txt`: py3dbp 1.1.2, trimesh 5.2.0 and reportlab 5.1.0. The isolated `.venv` uses system site packages; this is a development environment, not a verified redistributable dependency bundle. Tests also use pytest, Playwright/Chromium, Pillow, pdfplumber, MCP 2.3.0 and jsonschema 4.26.0 (the latter two already pinned by `requirements-codex-pilot.txt`).

From this worktree, start a hidden helper without a console popup:

```powershell
Start-Process -FilePath '.\.venv\Scripts\pythonw.exe' -ArgumentList 'tools/run_packaging_pilot.py','--port','8179' -WorkingDirectory (Get-Location).Path -WindowStyle Hidden
```

Use another free port if occupied. Only stop processes whose command line identifies this pilot and this worktree. Do not stop the regular desktop app or Claude's processes.

The rate adapter accepts `INSPECTORPRO_PACKAGING_EASYPOST_KEY` from the pilot's process environment. Do not paste keys into source, tests, logs or chat. Secure-store integration and a credential/account UI are still release work. A key is not required for manual packaging. There is deliberately no label-buy, pickup or payment operation.

## Milestone Position

| Gate | Current status |
| --- | --- |
| P0 feasibility | Partial: GLB units/bounds and analytic pads verified; solver/adapter selected for the pilot. OpenCascade is unavailable in this Python environment. Native CAD dimension/mass comparison and provider deployment approval remain open. |
| P1 manual workspace | Implemented and browser-tested for envelopes/GLB and rectangular pads. Full real-product acceptance needs a verified dimension and mass reference; direct CAD/assembly selection is not wired. |
| P2 live estimates | Adapter and test-mode/failure contracts implemented. Not passed: no credentialed live rate comparison at valid destinations. |
| P3 alternatives/inserts | Rectangular envelope arrangement implemented. Sourced carton catalog, custom board blank/tare calculation, pockets, no-contact regions, support/removal checks and cost-driven candidate comparison remain open. |
| P4 Sage/deliverables | Gateway, PDF and live chat-driven arrangement passed. Host admission, streaming, safe refresh, memory enforcement and manual Undo/Redo are verified. Broader real-product tasks remain; the agent cannot yet import CAD, request quotes or export reports through tools. No new agent loop was added. |
| P5 desktop | Not promoted. Requires live acceptance, full affected regressions, dependency/license packaging, worker resource hardening and explicit release approval. |
| P6 advanced | Deferred. No SolidCraft integration, mixed products, dielines, pallets, crates or freight. |

## Next Work In Order

1. Completed this increment: active-packaging admission/shared mutation lease, existing Codex runtime route, lifecycle/cancellation/receipt tests and a real Sage arrangement through the chat pane. Expand live acceptance to more products and interrupted turns before release.
2. Bind the selected native CAD/assembly configuration to trusted extraction records, including mass overrides, physical material evidence and configuration/revision. Validate against one engineer-approved product and measured mass.
3. Connect an approved carrier account through the existing secure-store pattern. Verify actual quotes for one measured package to three valid US addresses, including two enabled carriers where available. No assertion of all-destination or all-carrier availability until tested.
4. Add sourced carton/material selection, persistent alternatives and cost comparisons. Only then extend primitives to supported pocket cuts with an available solid backend and independently checked net volumes.
5. Conversation-memory enforcement and cancellation/admission transport now work. Dedicated packaging permissions, quota policy, durable create idempotency and retention rules remain. Run full desktop startup/shutdown and workflow regression gates before requesting promotion.

Needed from the user for later acceptance: an approved carrier account/key via secure entry, valid shipping scenarios, and one representative CAD product with a trustworthy mass/dimension reference. Those inputs do not block the completed offline/manual pilot, but they cannot be replaced with fabricated rates or physical properties.

## Dependency References

- Packing solver: https://github.com/enzoruiz/3dbinpacking (MIT).
- Geometry import: https://trimesh.org/trimesh.exchange.gltf.html (trimesh MIT).
- Rate contract and authentication: https://docs.easypost.com/docs/shipments/rates and https://docs.easypost.com/docs/authentication.
- ReportLab is a local PDF dependency (BSD); include its bundled-font notices when packaging a release.

Keep downloaded model licenses separate from software licenses. The existing GLB acceptance fixture remains in the repository; no new customer models or source paths were embedded in tests or release artifacts.

## Previous Manual Checkpoint Results

- Combined Python run: **329 passed**, two dependency deprecation warnings, 35.79 seconds. Includes 210 packaging/domain/rating/gateway/MCP tests and 119 existing Codex/Sage routing/MCP regressions.
- JavaScript: **18 passed** (13 workspace contracts, 5 host integration contracts).
- Live local MCP acceptance: **23 passed**, included in the 210. Uses both actual loopback HTTP and ASGI, real solver/service operations, stale-document rejection and listener cleanup. No live model or carrier inference.
- Latest Playwright run: passed at both viewport sizes, zero page errors, real imported mesh and six-instance rendering verified. Every sampled canvas was nonblank and camera changes changed pixels.
- Main tracked checkout remained clean (`git status --short --untracked-files=no`). No desktop promotion or Claude-copy edits.
- `git diff --check` and Python/inline-JavaScript syntax checks passed. The full desktop regression suite and live model/carrier acceptance remain unrun.

## Live Sage Checkpoint

- **509 Python tests passed**, two dependency deprecation warnings, 110.10 seconds. Covers packaging/domain/rating, admission, MCP, shared runtime, routing, saved-validation receipts, memory-enforced real SQLite/MCP writes and affected documentation/part/read-only gateway tests.
- **39 JavaScript tests passed**, including frame/source checks, editor locks, heartbeat, drain-before-switch, conversation changes, revision scope, failed reconciliation and browser timer receiver binding.
- A real ChatGPT-plan turn through the existing Sage pane completed in about 67 seconds with memory `enforce`. It inspected, proposed, validated a proposal, saved six imported parts and validated the saved revision. Five successful tools and three rejected argument attempts; Sage corrected those attempts without relaxing validation.
- The rejected arguments were `package_limit: 50` (maximum 2) and two proposals with string dimensions instead of JSON numbers. Tool descriptions now explicitly explain these constraints. The descriptions were regression-tested after that live run; reduced retry frequency has not yet been measured.
- The viewport reconciled revision 1, displayed all six imported meshes, and remained nonblank. Manual Undo returned to zero placements; Redo restored six at revision 3. No browser page errors. Source/product properties, constraints, quantity, name and carton were compared with the original stored design and remained unchanged.
- Unknown mass, carton weight, packing allowance and handling confirmation remained unknown. Overall validation correctly remained `failed` for missing inputs; geometric fit alone did not imply shipping readiness or protection certification. No live rates were requested.
- Evidence: `.runtime/packaging-sage-browser-02/` contains the final SSE result, screenshots and browser summary. The CAD-derived GLB fixture still has no engineer-verified physical dimension/mass reference.
- Existing memory fixture regression has one unrelated baseline mismatch: its workflow-stage fixture lacks the already-existing `documentation-publication` policy. The new packaging memory-host suite passes all eight cases. Missing baseline fixture files were copied only into this worktree as untracked test inputs, not committed or changed in the source checkout.
- The initial browser run found an unbound browser timer invocation before inference; the timer receiver fix and regression are included. A later successful run used the real model, not a scripted replacement.
- Manual browser regression also passed against the full host at desktop and mobile sizes: editing, solver, pad mass, save/reopen, PDF, camera/section/exploded views, Undo/Redo and imported meshes. Evidence: `.runtime/packaging-manual-regression-02/`; no page errors.
- Not performed: full Electron release/startup/shutdown acceptance, live carrier comparison, verified native CAD mass, fitted protective inserts, or desktop promotion. Ribbon/dialog and decal/display-mode finishing remains on the implementation plan.
