# Packaging and Shipping: Isolated Pilot

Date: 2026-11-05. Status: usable manual development pilot, **not a desktop release or complete live Sage workflow**.

## Isolation

- Worktree: `C:\Users\might\OneDrive\Desktop\InspectorPro\.runtime\packaging-shipping`.
- Branch: `packaging-shipping-2026-11-05`, starting at `ed68c363b8c14289fd5b304280dc1e321f924b24`.
- The regular desktop checkout, Claude's CopilotTest copy, existing layouts, and source CAD were not edited or promoted.
- All packaging databases, browser screenshots and test documents are under this worktree's `.runtime/`. Test documents are labelled `TEST`.
- The separate pilot runs on `http://127.0.0.1:8179/packaging`. It does not load the main application's environment file, start Codex, or purchase postage.

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
| Host hook | Main app entry is development-only: backend `INSPECTORPRO_PACKAGING_ENABLED=1` plus browser `?packagingPilot=1`. Repeated viewport refresh retains the iframe; navigation checks unsaved work. Packaging chat is explicitly blocked until admission wiring exists. |

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
| P4 Sage/deliverables | Offline gateway and PDF implemented. Live host admission, routing, streaming, safe refresh and a real Sage turn remain open. No new agent loop was added. |
| P5 desktop | Not promoted. Requires live acceptance, full affected regressions, dependency/license packaging, worker resource hardening and explicit release approval. |
| P6 advanced | Deferred. No SolidCraft integration, mixed products, dielines, pallets, crates or freight. |

## Next Work In Order

1. Implement the active-packaging host admission and shared mutation lease described in `packaging-sage-integration.md`. Connect the existing Codex runtime, not another orchestration loop. Add lifecycle/cancellation/receipt tests and then a real Sage turn. Never expose write tools with a fake/null lease.
2. Bind the selected native CAD/assembly configuration to trusted extraction records, including mass overrides, physical material evidence and configuration/revision. Validate against one engineer-approved product and measured mass.
3. Connect an approved carrier account through the existing secure-store pattern. Verify actual quotes for one measured package to three valid US addresses, including two enabled carriers where available. No assertion of all-destination or all-carrier availability until tested.
4. Add sourced carton/material selection, persistent alternatives and cost comparisons. Only then extend primitives to supported pocket cuts with an available solid backend and independently checked net volumes.
5. Add memory/quota enforcement, dedicated packaging permissions, durable create idempotency, cancellation endpoint/admission transport and retention rules. Run full desktop startup/shutdown and workflow regression gates before requesting promotion.

Needed from the user for later acceptance: an approved carrier account/key via secure entry, valid shipping scenarios, and one representative CAD product with a trustworthy mass/dimension reference. Those inputs do not block the completed offline/manual pilot, but they cannot be replaced with fabricated rates or physical properties.

## Dependency References

- Packing solver: https://github.com/enzoruiz/3dbinpacking (MIT).
- Geometry import: https://trimesh.org/trimesh.exchange.gltf.html (trimesh MIT).
- Rate contract and authentication: https://docs.easypost.com/docs/shipments/rates and https://docs.easypost.com/docs/authentication.
- ReportLab is a local PDF dependency (BSD); include its bundled-font notices when packaging a release.

Keep downloaded model licenses separate from software licenses. The existing GLB acceptance fixture remains in the repository; no new customer models or source paths were embedded in tests or release artifacts.

## Final Checkpoint Results

- Combined Python run: **329 passed**, two dependency deprecation warnings, 35.79 seconds. Includes 210 packaging/domain/rating/gateway/MCP tests and 119 existing Codex/Sage routing/MCP regressions.
- JavaScript: **18 passed** (13 workspace contracts, 5 host integration contracts).
- Live local MCP acceptance: **23 passed**, included in the 210. Uses both actual loopback HTTP and ASGI, real solver/service operations, stale-document rejection and listener cleanup. No live model or carrier inference.
- Latest Playwright run: passed at both viewport sizes, zero page errors, real imported mesh and six-instance rendering verified. Every sampled canvas was nonblank and camera changes changed pixels.
- Main tracked checkout remained clean (`git status --short --untracked-files=no`). No desktop promotion or Claude-copy edits.
- `git diff --check` and Python/inline-JavaScript syntax checks passed. The full desktop regression suite and live model/carrier acceptance remain unrun.
