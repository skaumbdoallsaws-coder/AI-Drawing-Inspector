# Packaging and Shipping: P0-P5 Completion Checklist

Started 2026-11-06 from source checkpoint `4c37436` in the isolated worktree
`.runtime/packaging-completion` (branch `packaging-completion-2026-11-06`). This
checklist maps every P0-P5 acceptance requirement in
[the implementation plan](packaging-shipping-implementation-plan.md) to code,
evidence or a concrete missing task. It is updated as work lands; it does not
rewrite earlier results into acceptance claims.

Status words:

- **Live verified**: exercised against the real provider, model or desktop, with evidence.
- **Locally verified**: automated, browser or native checks pass locally with no live
  carrier (mock HTTP transports) and, unless stated, no live model.
- **Implemented**: code exists but has not been verified against the gate.
- **Open**: credential-independent work not done yet.
- **Blocked**: needs a user decision, credentials, addresses or physical evidence.
- **Deferred**: P6 or explicitly excluded from the first release.

"Historical" marks results recorded by earlier checkpoints that were not rerun here.

## Baseline before edits (2026-11-06)

Run in this worktree at `4c37436`, foreground, with no carrier key in the environment.
Interpreter: the `packaging-shipping` worktree's Python 3.14.0 `.venv` (read-only use, `-B`,
no cache provider) with the desktop dependency bundle
`.runtime/packaging-runtime-20261106/dependencies` first on `PYTHONPATH` (trimesh 5.2.0,
numpy 2.5.4, Pillow 13.0.0, py3dbp 1.1.2, reportlab 5.1.0, as the native app ships them).
STEP tests used the separate Python 3.11.9 `step-venv` and the user-approved read-only
straight rack/pusher assembly. Node v24.11.1.

| Batch | Files | Result |
| --- | --- | --- |
| Domain | `tests/test_packaging_{shipping,rating,components,extensions,report_v2,v2_review,credentials}.py` | 483 passed |
| Host | `tests/test_packaging_{admission,memory_host,worker_dependencies}.py` | 107 passed |
| STEP | `tests/test_packaging_step_import.py` (configured runtime + real sample) | 58 passed |
| Sage tools | `tests/test_codex_packaging_*.py` (7 files) | 140 passed |
| Desktop profile | `desktop/tests/test_packaging_{application_profile,promotion}.py` | 20 passed |
| JavaScript | `tests/packaging_{ui,host,ribbon}.test.cjs`, `desktop/tests/packaging-{configuration,lifecycle-observation}.test.cjs` | 176 passed |

Environment finding: with the `.venv` alone (no bundle on `PYTHONPATH`), two GLB-worker tests
fail with `source_invalid`. The isolated worker runs `-I -S` with the directory that holds
trimesh as its only dependency root, and that venv keeps numpy and Pillow in the base
interpreter. The native desktop passes the explicit bundle, so this affects only
non-native hosts built as `--system-site-packages` venvs. Logs: `.runtime/pc-tests/base-*.log`.

## P0 - Feasibility and interface contracts

| Requirement | Status | Evidence or next action |
| --- | --- | --- |
| Dependency choices: py3dbp (MIT), trimesh (MIT), reportlab (BSD), OCP STEP worker, EasyPost | Implemented | In use and promoted locally. Third-party license/notice review and redistribution remain open; inventory in `docs/packaging-shipping-dependencies.md`. |
| Provider choice with current terms and services | Decided: EasyPost first (user, 2026-11-06); live use blocked on credentials | EasyPost remains the only adapter; no other adapter is built. Terms re-read 2026-11-06 by a separate reader from EasyPost's own pages (API Addendum v4.3, effective 2026-10-30; Master Customer Agreement v6.1; Parcel, authentication and carrier docs). Read on the page: rating creates a Shipment (an external write); three rating calls are included per purchased label, then $0.02 per call, charged monthly from the Wallet; label fee $0.08 after 3,000 a month; BYOCA plan $20 a month; address verification $0.02 (US) beyond one per label (this workflow requests none); test rating is free; negotiated rates appear only in production; parcel dimensions are inches to one decimal. From search snippets only (EasyPost's support site refused the reader): production shipments need a positive Wallet balance; card top-ups cost 3.75%; test mode returns retail or near-retail rates. Not stated anywhere official: whether test mode contacts carriers (the old claim that it does not was removed from the code). This workflow buys no labels, so each production rating call is expected to cost $0.02 (the fee notice says so). Parcels are now sent in inches to one decimal and ounces, both rounded up, and each quote records the parcel as sent. Needs the user's account and permission for metered calls. |
| Documented unsupported inputs | Implemented | `/api/packaging/status` lists unsupported capabilities; consolidated list below. |
| Real CAD import with dimension check | Locally verified | Five-solid STEP: bounds and closed-solid volume; original bytes unchanged (STEP batch, real sample). |
| Mass compared with the source CAD application's value | Blocked | Only a PMMA density estimate exists (1.726 kg for four pairs). Needs the CAD-reported mass or a scale measurement from the user. |
| Simple insert cut and volume calculation | Locally verified | Analytic rectangular/cylindrical top-open pockets with net volume and wall/floor/web checks. No OpenCascade Boolean cut is used for inserts. |
| No reliance on SolidCraft | Locally verified | Not referenced by the packaging code. |

## P1 - Manual packaging document and 3D workspace

| Requirement | Status | Evidence or next action |
| --- | --- | --- |
| Package one and six instances of a real product | Implemented | Historical: six GLB instances (CAD-derived fixture, no mass reference) and four STEP pairs. Six instances of the real STEP product not yet recorded. |
| Inspect clearances, save/reopen the exact assembly | Locally verified | Historical browser and native evidence (`evidence-07`, `packaging-ribbon-release-check`). |
| Dimensions/masses match independent references | Blocked | Needs an independent dimension and mass reference for the real product (see P0). |
| Overlap reported; missing mass never zero | Locally verified | Domain tests. |
| Source CAD unchanged; Undo restores the complete design | Locally verified | STEP tests hash the original; service Undo/Redo tests. |
| Works without Sage or a carrier connection | Locally verified | Manual flows and tests run with no key or model. |
| Direct selection of an existing app part/assembly and configuration | Locally verified (editor and API; not yet in the native app) | Browser check: `tests/verify_packaging_library_storage_ui.py` (`.runtime/pc-tests/ui-library-storage-3`; synthetic TEST library). `library.py`: the editor's InspectorPro library dialog lists parts (`<part>.json` + `<part>_colored.glb`) and assemblies (`assemblies/<assembly>_assembly.json` + model) from the host's own library folder, read-only. Requests name an entry, revision, configuration and the record digest shown; the browser never supplies paths, files, sizes or masses. Only the configuration active at extraction has geometry; other recorded configurations are listed as not extracted and refused. The model runs through the isolated GLB worker, part envelopes are cross-checked against the extracted SOLIDWORKS box (2 mm or 2%), library masses are not imported, and the stored copy records kind, ID, revision, configuration and both digests (shown in the report; `library-status` says current, changed or unavailable). Real library, read-only: all 9 parts agree with their boxes (largest difference 1.52 mm, part 100004) and both assemblies import. Tests: `tests/test_packaging_library.py` (12). Sage has no library tool yet. |

## P2 - First end-to-end shipping estimate

| Requirement | Status | Evidence or next action |
| --- | --- | --- |
| Quote-only adapter, no purchase endpoint | Locally verified | `rating.py` creates shipments for rates only; mock-transport tests. |
| Ship date, selected carrier accounts, service constraints, options in the request | Locally verified | `QuoteRequest` adds `carrier_accounts` (up to 10 `ca_` IDs), `services` (carrier + service filters), `options` (delivery confirmation, Saturday delivery) and `refresh`. Accounts and options are sent only when chosen; rates outside the selection are dropped and counted. A `ship_date` is refused (`ship_date_unsupported`) because EasyPost does not document that rates honor a later date. Mock transports only. |
| Price basis: account rate vs list vs retail | Locally verified | Each rate keeps the account rate (`rate`), list rate and retail rate as separate fields, each with its own currency; a basis without an explicit currency is dropped, never assumed. Totals sum a basis only when every parcel has it in the same currency, and the UI shows the three in separate columns. Mock only: which bases EasyPost returns for a given account is unverified. |
| Actionable, sanitized carrier failures | Locally verified | Carrier messages become a category (address, package, account, service, other) with help text, an allowlisted carrier name and account ID; carrier free text is never returned or stored. HTTP rejections show only an allowlisted provider error code (for example `PARCEL.PARAMETERS.INVALID`) with help. Mock only: the categories are keyword-based and real message wording is unverified. |
| Supported US destinations (contiguous, AK/HI, PO boxes, military, territories) | Locally verified | `destinations.py`: the 50 states and DC are rated; Alaska and Hawaii are rated with a note; territories (PR, GU, VI, AS, MP, UM, FM, MH, PW) and military addresses (AA/AE/AP, APO/FPO/DPO) are refused because rating needs customs data this pilot does not collect; PO Box street lines and unknown state codes are refused. Checked for the origin and every destination before any provider request. Carrier coverage of AK/HI is not verified. |
| Complete request fingerprint, duplicate prevention, explicit refresh, account-change staleness | Locally verified | Fingerprint: provider, adapter, design hash, scenario hash (addresses with residential status, accounts, services, options, ship date) and an opaque account reference that changes when the key is replaced or removed. An identical request at the same revision returns the saved quote (`reused: true`) without a provider call; `refresh: true` (UI "Refresh rates", with a confirm naming the shipment count) asks again. History reports `stale_reason` (revision_changed, design_changed, account_changed, account_removed). Every provider attempt is audited at `/quote-attempts`: requests sent, responses, shipments created, unconfirmed requests and outcome, including failed and interrupted attempts. Mock only. |
| Sanitized carrier-account discovery | Locally verified | `POST /api/packaging/account/carrier-accounts` (packaging client header and `packaging.account`) keeps id, type, readable name, description, reference and billing type only; credential fields, logos and malformed entries are discarded and key-like text is blanked. Refusals (403, `MODE.UNAUTHORIZED`) and rejected keys are explained. Mock only: the response shape and the production-key requirement come from EasyPost's docs, not a live call. |
| Change of design invalidates quotes | Locally verified | Revision-bound history marks other revisions stale. |
| Live quotes for one approved package to three valid US addresses, two carriers | Blocked | Needs a privately entered key, approved addresses with residential/commercial status, a confirmed gross weight and permission for metered calls. |
| Explain differences from a carrier website's retail quote | Blocked | Needs live rates; requires the price-basis work above. |

## P3 - Packaging alternatives and simple inserts

| Requirement | Status | Evidence or next action |
| --- | --- | --- |
| Constrained arrangement search, split cartons | Implemented | py3dbp over up to six carton choices and one to six packages of one carton type. Candidates rank by package count then outer volume; cost ranking happens in the saved-design comparison below. |
| Proposals keep approved protection and packing mass | Locally verified | `constraints.cushion` (floor/top/sides thickness, material, evidence) is rebuilt as a foam lining in every candidate; a design with pads and no requirement is refused (`protection_requirement_needed`), never silently stripped. Allowances come from `constraints.package_allowance` or the value every saved package shares, else stay unknown and block rating. Shared carton graphics are carried; insert graphics are reported as dropped. Payload capacity counts lining and allowance. `tests/test_packaging_preservation.py`. |
| Minimum cushioning | Locally verified | `cushion_insufficient` / `cushion_not_verified` errors: least insert material between each product envelope and each carton wall along each axis, pocket voids subtracted, round pockets bounded by their square (undercounts, never overcounts), invalid inserts count as no material. Geometry only, not a cushioning-performance rating. |
| No-contact regions | Locally verified | `constraints.no_contact`: up to 12 regions, each a product face or a rectangle on it (product axes, before packing orientation), an air gap and required evidence. `no_contact_violated` (error) when packing material, a carton wall or another product lies within the gap straight out from the region; pocket voids count as air, invalid inserts as material. Faces follow the viewer's rigid rotation for every dimension order (one table asserted in both the Python and the JS tests). A region facing the carton floor is flagged for review, since support is not modelled beyond insert contact. Proposals reserve the gap on both faces of each affected axis and are revalidated; a carton that only fits without the gap is not proposed. The comparison treats changed regions as changed constraints. Geometric clearance only, not a protective-performance rating. `tests/test_packaging_no_contact.py`, headless `tests/verify_packaging_no_contact_ui.py`. |
| Upright/allowed orientations, carton boundaries, known load limits | Locally verified | Domain tests; unknown payload stays a warning. |
| 1-, 6- and 24-item fixtures: feasible alternatives or clear infeasibility | Locally verified | Synthetic TEST product in the sourced ULINE carton with a cited Ethafoam lining: 1, 6 and 24 items feasible, gross mass matches an independent recomputation; 24 items in an undersized carton return no candidate and an explicit `does_not_fit` rejection. |
| Sourced stock-carton selection | Locally verified | `catalog.py` now holds nine ULINE 200 lb test kraft cartons (S-4080 8x6x4, S-4103 10x8x6, S-4120 12x10x8, S-4187 18x12x6, S-4235 16x12x8, S-4415 24x12x6, S-4196 20x14x10, S-15039 22x18x8, S-4219 24x18x12 in), smallest inner volume first, each with the values its product page states: inside L x W x H, outside dimensions with the +/- 1/8 in tolerance, unit weight, bundle quantity, "200 LB. TEST" and "Meets ASTM D5118"; source URL and check date 2026-11-06 (S-15039 re-read, unchanged). No price, payload limit or board blank is recorded; the notice says 200 lb test is a burst grade, not a load limit. The eight new records were transcribed by Claude from the supplier pages and still need the user's review. Selection: the editor's Carton catalog dialog and Sage's `packaging_resources` (every material, six cartons per page with `next_offset`) feed the existing proposer, which ranks feasible cartons with the rebuilt lining. `tests/test_packaging_catalog.py` (page-value consistency, a unit-weight-versus-board-area transcription guard, proposer choosing S-4187 over three cartons that cannot hold a lined 0.30 m TEST bar), `tests/verify_packaging_catalog_ui.py` (`.runtime/packaging-catalog-ui-02`, own app and throwaway store). One supplier only; cushioning materials unchanged. Independently re-checked on 2026-11-06 by a separate reader against each ULINE product page: all nine SKUs match on inside and outside dimensions, unit weight, bundle quantity, 200 lb test grade, the ASTM D5118 statement (ULINE's own claim, not a certification) and the +/- 1/8 in outside tolerance (now stored as `outer_tolerance_m`). |
| Cost-aware comparison with a baseline; cannot win by shrinking CAD, dropping items or protection, ignoring payload or mixing stale/test rates | Locally verified | `comparison.py` compares the current design and saved designs against a stored baseline on the account rate only, for one scenario, carrier account, mode and service. A design is ranked only when it keeps the baseline's product (dimensions, mass, source), quantity, constraints, protection (insert mass when no cushion requirement exists), packing allowance and payload evidence, passes validation and has a quote with the exact fingerprint; quotes for an edited design, a replaced account, another scenario or the other mode never match. Unknown material cost stays out of totals. Savings are stated only for production-mode quotes and name the baseline, quote dates, account and destinations. Saved designs can be quoted under the session scenario with reuse and the attempt audit. Mock only: `tests/test_packaging_comparison.py` and the headless `tests/verify_packaging_comparison_ui.py`. No live price difference has been measured. |
| Pocketed inserts | Locally verified | Domain tests. |

## P4 - Sage execution and deliverables

| Requirement | Status | Evidence or next action |
| --- | --- | --- |
| Sage tools over the same service | Locally verified | Historical live chat checkpoint (inspect/propose/edit/validate/Undo, density estimate, PDF link). |
| Sage research with stored citations | Locally verified (mock only) | Packaging Sage gets the existing public-research tools (`research_tools.PublicResearchSession`: `search_public_sources`, `read_public_source`; at most 4 provider requests per turn, the same `INSPECTORPRO_CODEX_WEB_RESEARCH` flag and paid-inference policy as Documentation) plus `record_packaging_evidence`, only for principals with `packaging.edit`. The gateway refuses queries containing packaging IDs or the design/product name before any provider request; the existing filter refuses URLs, paths, emails and credentials. Evidence (`evidence.py`, stored per document in `research_evidence`) is accepted only from a page read in the same turn: the claim must appear in a passage the provider quoted from that page (`source_quote`) or in the provider's summary of the read (`provider_summary`, labelled as not a quotation; OpenAI reads always land here because their citations carry no text), the value, unit and SKU/grade must appear in the claim, and an effective date in the read. Each record keeps kind (carton SKU, material density, cushioning guidance, comparable packaging), subject, exact claim, value, unit, SKU/grade, effective date, Sage's confidence, the source URL/title/page age/retrieval time from the research receipt (never model-supplied) and the provider, model and result revision. Duplicates are stored once; 200 per document. Records start unreviewed; the Validation panel lists them with a new-tab source link and **Accept**, **Reject**, **Mark unreviewed** and **Remove** (confirmed). Evidence never edits the design, its revision, validation or approval. Research receipts are recorded as `external` requests with provider request counts. `tests/test_codex_packaging_research.py` (a canned researcher replays raw provider replies through the real Anthropic and OpenAI normalizers), `tests/verify_packaging_research_ui.py`. No live research request has been made. |
| Sage quote using the same service, scenario IDs instead of addresses, explicit transmission authorization | Locally verified (mock only) | `quoting.py` `QuoteDesk` is the one provider path, lock, quote reuse and attempt audit for the Rates panel, saved-design quotes and Sage (the host passes the same desk to the router and the Sage turn). The user authorizes a scenario in the Rates panel (**Allow Sage to quote these addresses**: a dialog lists exactly what Sage sees, city, state and residential status, and sets a provider-shipment budget of 1-12 and a 5-240 minute limit); addresses stay in server memory for that user and document only and are never stored. Sage tools: `packaging_quote_scenarios` (IDs and city-level labels, no provider call), `quote_packaging` (scenario ID, expected revision, design hash, optional saved alternative, refresh; needs `packaging.quote`; shipments are reserved from the budget before any provider request and are not refunded on failure) and `compare_packaging` (saved quotes only, deterministic comparison, claim text without ZIP codes). Results and receipts carry no name, street or ZIP code; the provider still receives the full addresses. Quote receipts are recorded as `external` requests, separate from document edits and Undo. Revoke removes a scenario at once. `tests/test_codex_packaging_quotes.py`, `tests/verify_packaging_sage_quote_ui.py` (a scripted gateway call stands in for Sage). No live Sage turn or live carrier request has been made. |
| Dedicated packaging permissions | Locally verified | `permissions.py`: `packaging.read`, `packaging.edit`, `packaging.quote` (external, possibly billed provider requests) and `packaging.account` (carrier credentials and account discovery). The API, editor admission and Sage gateway ask only for these. The frozen Facility Layout roles are unchanged; each action is derived from the layout action packaging checked before (read from `layout.read`, the others from `layout.edit`, `*` grants all), so no role gains or loses access. Quote and account routes ask for their own action (proved by remapping the derivation in a test). `/api/packaging/status` reports the caller's packaging permissions. Narrowing, for example carrier accounts for administrators only, is a product decision left to the user. `tests/test_packaging_permissions.py`. |
| Live six-part Minneapolis example with too-small carton, missing mass and stale revision | Blocked | Needs carrier access and permission for a bounded live Sage/rating test. Mock tests do not satisfy it. |
| Report: BOM, source revisions, quantities, materials, findings, timestamped quotes | Implemented | Draft PDF. |
| Report: packing sequence, packed vs exploded views, quote identity (design, scenario, account, mode) | Locally verified | `report.py` now prints: a packed-assembly statement (every dimension, position, projection and mass describes the packed carton; exploded or transparent editor views are display aids; rating uses each packed carton's outer dimensions and gross mass; the editor caption already says "exploded view, positions unchanged"); a check-status table (carton fit/lid closure on envelopes, overlaps, minimum cushion, no-contact gaps, payload and allowed orientations as PASSED (geometric) / FAILED / NEEDS REVIEW / NOT REQUIRED from the saved findings; support and packing/removal access always NEEDS REVIEW; drop, vibration, compression and stacking NOT EVALUATED); the protection requirements (contents declaration, allowed orientations, clearance and gap, cushion thicknesses with lining material and sources, least insert material found or "not required", package allowance rule, no-contact regions and their results); a proposed packing order per package derived from saved positions (lowest bottom face first, inserts before products at equal height, then Z, X, ID; close the carton) marked not verified, with insertion/removal access needing review; accepted and unreviewed research evidence with basis, value, source URL and retrieval time (rejected records counted only); and every quote at the current revision, newest per fingerprint, with quote ID, quoted time, provider, mode, design hash, scenario hash, account reference and fingerprint. The report route applies the Rates panel's staleness (revision, design, carrier account changed/removed); stale snapshots print their identity and reason but no amounts. Totals are labelled as sums of per-package account rates, not consolidated or all-in prices, with the fees notice. `tests/test_packaging_report_identity.py` (pdfplumber text of rendered PDFs, offline). Not reviewed by a packaging engineer. |

## P5 - Desktop release validation

| Requirement | Status | Evidence or next action |
| --- | --- | --- |
| Ribbon panels, viewport conventions, display modes, decals | Locally verified | Historical browser and native checks. |
| Promotion into the regular desktop | Implemented | User-approved local promotion at `3ce2b05`; not a gate pass. Next promotion needs approval. |
| Recoverable draft checkpoints, outstanding-operation reconciliation, safe shutdown/restart | Locally verified (store, editor and native guard; not yet in the promoted desktop) | Recovery drafts (`/api/packaging/drafts`, `packaging.edit`, capability `draft_recovery`): the editor checkpoints its unsaved design 1.5 s after each change, records an in-flight save (request ID) in a checkpoint before sending it, and removes the checkpoint after a save or discard. A checkpoint also keeps values typed but not applied (the open panel's fields, at most 300; never file inputs or addresses) and an import in progress (recorded before its request is sent). Drafts belong to one user and scope, one per saved document, at most 10 (refused beyond, never silently dropped), bounded by the 1 MB request limit, and never change a document. On start and from **Open**, **Recover unsaved work** lists each draft against the saved store, including whether its design differs from the saved one: an interrupted save that landed is reported as saved and its draft removed (no second revision); one that never arrived is restored and **Save** replays its original request ID, so it cannot apply twice; a draft behind a newer revision loads only after a confirmation; typed values come back unapplied in their panel; an interrupted import is reported as finished (choose the stored model in Imported sources) or not finished (import it again; never re-run automatically); **Discard** asks first. Native close, reload and **Restart backend** proceed over a mounted editor whose exact state is clean or is its stored recovery draft: the main process first asks the editor to store its newest state (best effort; it authorizes nothing), then the usual two observations decide, with the stored checkpoint version in the fingerprint. Still blocking: Sage turns, admission and reconciliation; save conflicts; open packaging dialogs; running quotes, reports and proposals; selected files; session-only addresses (never stored); typed values whose form cannot be captured; and any state that is not yet in a stored checkpoint or whose last checkpoint failed. The managed runtime bridge keeps the strict rule. After a backend loss, a clean or checkpointed editor no longer blocks **Restart backend** or **Close Packaging**; work not checkpointed before the backend stopped still blocks (it cannot be stored then). Evidence: `tests/test_packaging_recovery.py` (22), UI unit tests, native lifecycle, close and title-bar tests (161), `tests/verify_packaging_recovery_ui.py` (`.runtime/pc-tests/ui-recovery-06`, six cases) and `tests/verify_packaging_departure_ui.py` (`.runtime/pc-tests/ui-departure-14`: typed values, departure preparation, uncovered states, an import that never arrived and one that finished after the editor closed). Not yet run: the real Electron window in an isolated profile (native acceptance). |
| Legacy managed runtime transition path | Done: unsupported for the first release (user decision, 2026-11-06) | Packaging is explicitly off there. The runtime window never adds the workflow, its backend forces `INSPECTORPRO_PACKAGING_ENABLED` and `INSPECTORPRO_CODEX_PACKAGING` to 0, and its boundary refuses `/packaging`, `/api/packaging/*` and `/static/packaging*` with `desktop_packaging_unsupported` before any other check. Tests: `desktop/tests/test_desktop_runtime_boundary.py`, `test_desktop_runtime_lifecycle.py`, `packaging-configuration.test.cjs`. The regular desktop application is the supported host. |
| Missing-dependency behaviour | Locally verified | A missing optional component disables only its feature: GLB import (`source_runtime_unavailable`), arrangement proposals (`arrangement_unavailable`) and the PDF report (`report_unavailable`) answer 503 with a feature message instead of a bad-file or server error, and `/api/packaging/status` lists `glb_import_runtime_missing`, `arrangement_runtime_missing` or `pdf_report_runtime_missing`. `tests/test_packaging_missing_components.py` runs the real GLB worker with an empty dependency folder. STEP, carrier key store and native profile cases were already covered; see `docs/packaging-shipping-dependencies.md`. |
| Dependency/license/security inventory | Declared and texts collected; redistribution clearance open (needs a person) | `docs/packaging-shipping-dependencies.md`. Declared: numpy 2.5.4 and pillow 13.0.0 (imported directly by the GLB worker) in `requirements-packaging.txt`, and both now required by the native profile check; httpx and pywin32 (Windows only, must live in the app's own site-packages) in `requirements.txt`. Exact-version license texts for 27 components (all 70 STEP DLLs, OCP, the wheels and py3dbp) collected locally with a manifest of sources and SHA-256s; re-verified: 40 files, 0 mismatches, 70 of 70 DLLs assigned. Unresolved redistribution obligations are listed there (LGPL source offers for Open CASCADE and LibRaw, license choices for FreeImage, FreeType, LibRaw, zstd and OpenEXR DWA, required notices, Microsoft runtime terms). Local development testing does not depend on them. Not legal clearance. |
| Clean Windows install | Open (blocked) | Needs a clean Windows machine or VM. This computer runs Windows 11 Home without Hyper-V, Windows Sandbox, VirtualBox or VMware, so it cannot host one; not attempted. |
| Artifact retention, quotas and cleanup | Locally verified (decision of 2026-11-06 implemented) | `storage.py`. Nothing is deleted automatically: documents, alternatives, recovery drafts, edit and create receipts, quotes and quote attempts are never removed. Per-workspace limits, configurable in the editor's Storage dialog (defaults 100 imported models or 2 GiB, 500 artwork images or 512 MiB; bounds 1-10,000 / 64 MiB-64 GiB and 1-50,000 / 16 MiB-16 GiB), refuse new imports with `source_storage_full` / `image_storage_full` and delete nothing. A model or image already stored adds nothing. Remove unused lists only models and images that no document (including Undo and Redo history), alternative, recovery draft, edit or create receipt, quote, comparison baseline or research record names, keeps anything imported in the last hour, and deletes exactly the list the user confirmed (by its digest; a changed list is refused with `storage_changed`); each removal is logged. Receipts stay, so duplicate-request protection and interrupted-operation reconciliation are unchanged. Interrupted import job folders are cleaned separately (row below). Tests: `tests/test_packaging_storage.py` (6). |
| No secrets in evidence, no orphaned workers, offline manual use | Locally verified | Historical native evidence; recheck at release. The GLB worker now limits itself like the STEP worker (30 s CPU, one process, 1.5 GiB on Windows) and refuses to parse without limits, so a worker whose host stopped ends by itself; job folders left by a stopped host are removed at startup after an hour (`tests/test_packaging_worker_dependencies.py`). |
| Two live carriers or an explicit single-carrier restriction | Blocked | Depends on P2 live access. |

## Progress log

- 2026-11-06, item 1 (proposal preservation): cushion requirement and allowance rule added to
  `Constraints`; proposals rebuild the lining and keep allowances; the cushion check is part of
  validation; the Product panel edits both and keeps constraint fields it does not show. Contract
  change: proposing a design that has pads but no cushion requirement now fails with
  `protection_requirement_needed` (UI, API and Sage) instead of returning candidates without the
  pads. Design hashes now include the two new (null by default) fields. Mock/offline evidence only.
- 2026-11-06, item 2 (rating hardening): request options, separate price bases, sanitized
  failure categories and provider error codes, US destination rules, fingerprints with reuse and
  explicit refresh, account/design staleness, an attempt audit with fee disclosure and sanitized
  carrier-account discovery; the Rates panel shows all of them. New store table
  `quote_attempts` (additive, schema version unchanged); the `quotes` table is unchanged, so an
  older build can still read and write it. Contract changes: quote history entries may carry
  `stale_reason`; `/api/packaging/status` adds `quote_rules`; a non-null `ship_date` is refused.
  Evidence: `tests/test_packaging_rating_hardening.py` and `tests/test_packaging_destinations.py`
  with mock transports; no request reached EasyPost and no live carrier result exists.
  Test note: the existing `test_separate_instances_replace_atomically` (four threads writing
  one SQLite file) failed 2 of 24 runs on this branch and 0 of 28 runs of the committed
  baseline, all with pytest's temp directory inside OneDrive, and 0 of 10 outside it. The
  difference is not conclusive and the credential change adds no file or database access;
  the test runner's temp directory now lives outside OneDrive.
- 2026-11-06, item 3a (cost comparison): saved designs can be quoted
  (`POST .../alternatives/{id}/quotes`, same reuse, refresh and audit rules as the document);
  a baseline is stored per document (`PUT .../comparison/baseline`); `GET .../comparison`
  reads saved quotes only and returns the integrity reasons, caveats, Decimal totals, signed
  differences, a deterministic ranking and, for production quotes only, savings that name the
  baseline, dates, account and destinations. New additive tables `alternative_quotes` and
  `comparison_baselines`; schema version unchanged and the `quotes` table untouched, so older
  builds neither see nor misread alternative quotes. UI: Quote this design, Set as baseline and
  a Compare costs dialog. Evidence: 9 mock-transport tests (anti-gaming variants included) and
  a headless browser check (`.runtime/packaging-comparison-ui-01`, no page errors, no external
  requests). No live carrier result exists.
- 2026-11-06, item 3b (no-contact regions): regions, the geometric check, proposals that keep
  the gap and a No-contact regions dialog in the Product panel. Sage edits regions through the
  existing full-design edit; its proposal summary now reports whether gaps were reserved.
  Fix found while adding the field: item 1 had added `cushion` and `package_allowance` to
  every serialized design, which changed the hash of every design saved before this branch and
  would have marked their quotes stale (`design_changed`). Unset optional protections are now
  left out of the serialized form, so a design that never used them hashes exactly as at
  `4c37436` (pinned in a test), and the UI writes the same canonical form so an unchanged
  Apply is not an edit. Evidence: 9 domain tests, 3 UI unit tests and a headless browser check
  (`.runtime/packaging-no-contact-ui-01`, no page errors, no external requests).
- 2026-11-06, item 4 (dedicated packaging permissions): packaging code checks only
  `packaging.read/edit/quote/account`, derived from the unchanged Facility Layout roles so every
  role keeps exactly its previous access (matrix over every known role and every packaging
  route). Quote and account routes no longer share the generic edit check. The desktop's local
  principal is `admin`, so nothing changes there.
- 2026-11-06, item 5a (Sage quotes): the Rates panel routes now call a shared `QuoteDesk`
  (`quoting.py`), and the host hands the same desk to Sage turns, so manual and Sage quotes
  share one provider lock, reuse rule and attempt audit (a test holds the lock and both are
  refused). Sage quotes only scenarios the user authorized in the Rates panel, bound to the
  user, document, saved revision and the design hash Sage names, within a shipment budget and
  expiry. Evidence, all MOCK ONLY (httpx.MockTransport, synthetic TEST addresses): 10 domain and
  gateway tests, a host wiring test, 1 UI unit test and a headless browser check
  (`.runtime/packaging-sage-quote-ui-02`, no page errors, no external requests; the browser check
  calls the gateway tool directly instead of running Sage). Research tools (item 5b) remain.
- 2026-11-06, item 5b (Sage research evidence): packaging Sage turns get the existing
  public-research session (search/read, 4 provider requests per turn, same flag and policy as
  Documentation) and a `record_packaging_evidence` tool. Evidence is bound to a page read in the
  same turn, keeps its source from the research receipt, starts unreviewed and never edits the
  design; the user reviews it in the Validation panel. Evidence, all MOCK ONLY (a canned researcher
  through the real normalizers, TEST pages on example.com, no network): 8 domain, API and gateway
  tests, a host wiring test, 1 UI unit test and a headless browser check
  (`.runtime/packaging-research-ui-02`, no page errors, no external requests; scripted gateway calls
  stand in for Sage). The enforced-host acceptance test now expects the three research tools,
  because the web-research flag defaults on.
- 2026-11-06, item 6 (report): the draft PDF gains quote identity for every current quote (newest
  per fingerprint; stale ones show identity and reason without amounts, using the Rates panel's
  account-aware staleness), a check-status table, protection requirements, a proposed packing
  order derived from saved positions (marked not verified), a packed-assembly statement and
  reviewed research evidence. Evidence: `tests/test_packaging_report_identity.py` (5 tests, offline
  synthetic TEST data, PDF text via pdfplumber); existing report tests unchanged and passing; a
  rendered sample was inspected page by page (`.runtime/packaging-report-item6`). No live quote is
  involved; amounts in the tests are synthetic.
- 2026-11-06, item 7a (catalog): nine sourced ULINE 200 lb test cartons, read from the supplier
  pages on 2026-11-06, sorted by inner volume; Sage pages them six at a time. Evidence: 3 catalog
  tests plus updated extension, preservation and Sage resource tests (34 passed together), and a
  self-contained browser check (`.runtime/packaging-catalog-ui-02`). Incident, recorded for the
  owner: `tests/verify_packaging_resources_ui.py` defaults to a running host at
  `127.0.0.1:8181`, and one run of it reached the packaging-shipping worktree's long-running
  `run_packaging_sage_pilot.py --live --port 8181` pilot. It created TEST document
  `pkg_60ffccbf8f76464d82b03144ff5843e3` ("TEST resources f79f0487", seven revisions, one uploaded
  TEST image, one saved snapshot) in that pilot's store, the same kind of record four earlier runs
  of that script left there, and stopped at its STEP step before the carrier-account steps. No
  account, quote, research or Sage request was made, and the run tested that pilot's code, not this
  branch. Nothing was deleted; removal is the owner's call. Separately, the domain batch failed
  once (1 of 7 domain runs this session) in `test_packaging_credentials.py::
  test_separate_instances_replace_atomically` (four threads replacing the sealed credential store:
  `carrier_credentials_unavailable`); the file passed 5 of 5 reruns and the next domain run passed
  483 of 483. The store and the test are unchanged on this branch; recorded as intermittent, not
  fixed.

- 2026-11-06, item 7b (recovery drafts): unsaved editor work is checkpointed in the packaging
  store and offered for recovery; interrupted saves reconcile through their request IDs. Evidence:
  12 store, shape and route tests; 1 UI unit test (188 of 188 UI and lifecycle tests pass); a
  self-contained browser check of six cases (`.runtime/packaging-recovery-ui-04`, no page errors, no
  external requests). Domain 483, host 107, Codex 143, report 77 + 5, catalog 34 tests pass. The desktop lifecycle observation keeps exactly its four
  boolean fields (an extra field broke the host contract tests and was removed). The native guard
  is unchanged; no desktop app was launched or restarted.

- 2026-11-06, item 8a (missing components and dependency inventory): GLB import, arrangement
  proposals and the PDF report now report a missing component as unavailable in this installation
  (503 with a feature message; Sage gets the same code), and the status lists it. Evidence: 4 new
  tests (one runs the real GLB worker with an empty dependency folder), 14 of 14 dependency tests,
  domain 483, report 77, host 107, Codex 144. The inventory tool reported 0 machine blockers for both packaging requirement
  files; it does not see transitive packages or the STEP wheel's native DLLs, which carry no license
  text. No license decision was made.

- 2026-11-06, item 8b (worker limits and job cleanup): the GLB import worker applies CPU, process
  and (Windows) memory limits to itself before parsing, as the STEP worker does, and exits with a
  distinct code if it cannot; leftover job folders older than an hour are removed at startup.
  Evidence: 5 new tests (one reads the job limits from inside the real worker), dependency tests 19
  of 19, domain 483, host 112, report 77, recovery 12, Codex 144.

- 2026-11-06, item 9a (legacy managed runtime): per the user's decision, packaging is unsupported
  there and refused explicitly (environment flags forced off, boundary code
  `desktop_packaging_unsupported`). Evidence: 18 runtime boundary/lifecycle tests, 7 desktop
  configuration tests.

- 2026-11-06, item 9b (carton records): an independent reader re-checked the nine ULINE records
  against the supplier pages (two separate reads per page): no mismatches. The tolerance field is
  renamed `outer_tolerance_m` because ULINE states it for outside dimensions only.

- 2026-11-06, item 9c (EasyPost terms and parcel precision): a separate reader re-read EasyPost's
  pages (verified on the page vs. search snippet recorded in the provider row). EasyPost takes
  parcel dimensions in inches to one decimal; the adapter sent six decimals. Dimensions are now
  rounded up to 0.1 in and weights up at six decimals (never smaller or lighter), each parcel
  records `parcel_sent`, and the fee notice states that each production rating call is expected to
  cost $0.02 when no labels are bought. Evidence: 93 rating, comparison, hardening and report tests
  (mock transport only).

- 2026-11-06, item 1a (existing part/assembly and configuration): editor dialog, list/import/status
  routes and report provenance for the host's inspection library. Evidence: 12 library tests; the real
  library (read-only, throwaway store) imported 9 of 9 parts within 1.52 mm of their extracted boxes and
  both assemblies; regression: domain 484, JS 189, desktop 22, recovery 12, credentials 56 (mock/offline).

- 2026-11-06, item 7 (dependencies): numpy, pillow, httpx and pywin32 declared; the native profile
  check now requires numpy and PIL; exact-version license texts collected and independently
  re-verified (40 files, 0 SHA-256 mismatches, 70 of 70 DLLs assigned); redistribution obligations
  listed separately from local testing. Evidence: desktop 22, JS 189, worker/missing-component 19.

- 2026-11-06, item 6 (retention): storage limits and the confirmed Remove unused, as decided.
  Evidence: 6 storage tests; regression with it: domain 484, host 112, Sage tools 144, recovery 12,
  credentials 56, rating 93, library 12, catalog 34, worker 19, desktop 22, JS 189 (one wording pin
  updated) - all mock/offline. Browser check of the library and Storage dialogs (choose a configuration,
  library status, Remove unused with confirmation, a lower limit refusing the next import):
  `.runtime/pc-tests/ui-library-storage-3`, no page errors, no external requests.

- 2026-11-07, item 1b (native close/restart over recovery drafts): checkpoints also keep typed but
  unapplied values and an import in progress; native close, reload and Restart backend proceed when the
  editor's exact state is clean or stored, and every other state keeps the guard (see the recovery row).
  Two defects found by the browser checks were fixed before commit: restoring a draft whose save had
  already landed raised a script error, and the dialog presented a field count as typed values. Evidence:
  recovery 22, UI 56, native lifecycle/close/title bar 161; browser checks `ui-departure-14` (F-J),
  `ui-recovery-06` (A-F) and `ui-library-storage-3`, no page errors or external requests; regression
  r22 (domain 484, host 112, Sage tools 144, credentials 56, rating 93, library 12, catalog 34,
  storage 6, worker 19, desktop 22, JS 216) and r25/r26 after the fixes (JS 216, recovery 22, domain
  484, host 112, desktop 22). Two desktop JS files outside the packaging batches
  (`application-panel.test.cjs`, `workflow-source-observation.test.cjs`) each fail one test identically
  on the branch base 4c37436; they are not caused by this work. No desktop app was launched or restarted.

- 2026-11-07, item 4 (real straight rack/pusher, read-only): `tests/verify_packaging_real_rack.py`
  (`.runtime/pc-tests/rack-3`; CAD hashes unchanged before and after, nothing copied). The STEP product
  structure confirms one pair per file: the top assembly holds one Rack Assembly (Front Rail, Rack Base
  Rail, Tile Backrest, Tile Support Panel) and one Straight Pusher; 5 solids; no mass, density or
  material entities. Independent checks agree: the five separately exported part files sum to the
  assembly's BRep volume (362.64 cm3; difference below 1e-15), the worker's tessellation matches it
  within 0.0015% with identical extents (508.00 x 29.74 x 79.25 mm), and every part's box matches its
  drawing (Straight Pusher 508 x 34 x 4.75 mm; rack parts 508 x 50 / 23 / 32.5 / 22.5 x 4.75 mm, read
  only from the rack-part sheets of the scallop drawing package). The Straight Pusher drawing's title
  block says inches while its values are millimetres. Mass stays an estimate: 0.4315 kg per pair at
  the cited typical PMMA density, excluding magnets, adhesive and finish (1.726 kg for four pairs,
  2.589 kg for six). Packing, offline, with a labelled test protection assumption (1 in Ethafoam 220
  on every face): one, four and six pairs each fit one ULINE S-4415 24 x 12 x 6 in (S-15039 and
  S-4219 also fit; the 20, 18 and 16 in cartons do not). Foam 0.514 kg (typical density) and carton
  0.522 kg (supplier unit weight); gross mass stays unavailable because the packing allowance is
  unknown. For four and six pairs the assessment flags elevated pairs without detected insert support
  (they would rest on each other). Reports for all three quantities were exported.

- 2026-11-07, item 8 (native acceptance), first attempt, not passed: the native check
  (`desktop/tools/packaging-native-entry.cjs`, extended with artwork, Undo/Redo of artwork, report text,
  Reload and Restart backend over checkpointed work, the recovery-aware departure, a native Close over
  checkpointed work with a second run that must recover it, and a missing-components run) did not
  complete. Two harness problems: the desktop requires the backend to be the process it started, and a
  virtual environment's python.exe on Windows is a launcher with a child interpreter, so the check uses
  the desktop's own `C:\Python314\python.exe`; and the editor's Apply candidate confirmation is a native
  confirm(), which blocks the renderer, so the driver now answers prompts and lists each one in its
  evidence. The second attempt was stopped while memory was critically low; its test window and
  backend then shut down cleanly. Two product defects found while preparing it are fixed: 6b718d5
  (an authorized desktop Reload over packaging work was silently cancelled by the editor's browser
  unload prompt) and 0ace670 (a STEP worker without its geometry component was reported as an unsafe
  file instead of unavailable). The rerun waits for enough free memory.

## Unsupported inputs (first release)

Mixed products in one design; arbitrary contour or fitted inserts; dielines; pallets, crates
and freight; hazardous or special-handling contents as ordinary parcels; international
shipments; verified CAD material mass; GLB as physical volume evidence; label or postage
purchase, pickups and payment; future ship dates (until provider semantics are verified).
PO Box addresses; US territories and military (APO/FPO/DPO) addresses, which need customs data.

## Retention decision (2026-11-06, implemented)

Conservative defaults: no automatic deletion of saved documents, referenced assets, recovery drafts or
quote and fee history. Storage limits refuse new imports instead of deleting, start at the proposed
source and image limits, and are configurable per workspace. Remove unused runs only when the user
confirms the exact list. Receipts needed to reconcile interrupted operations are never pruned, so
duplicate-request protection is preserved. The store file does not shrink after removals; freed pages
are reused.

## Credential-independent work order

1. Proposal preservation of protection and packing mass, with a deterministic test that a
   candidate cannot become lighter or cheaper by losing them.
2. Rating request/result hardening with mock transports: ship-date handling, carrier
   accounts, price bases, sanitized failures, US destination rules, fingerprints,
   duplicate prevention, refresh and account-change staleness, sanitized discovery.
3. Deterministic cost comparison with an explicit baseline and the anti-gaming tests;
   1-, 6- and 24-item fixtures.
4. Dedicated packaging permissions with backward-compatible derivation.
5. Sage quote and research tools bound to scenario IDs and the same services.
6. Report: quote identity, packed/exploded labelling, packing sequence.
7. Catalog expansion with sourced records; recovery and release items.

## Needed from the user for the blocked gates

- A carrier API account (EasyPost unless another is chosen), its key entered privately in the
  Rates account form, and permission for any enrollment, funding or metered calls.
- Origin and three destination addresses with residential/commercial status.
- The product, configuration and quantity to quote (the four-pair straight rack/pusher set is
  prepared offline; see the item 4 log entry), and an approved gross weight or a measured mass.
- Physical facts CAD cannot give for the rack/pusher: a scale weight of one finished pair (magnets
  and adhesive included) or the magnet count, size and grade per pair; the packing materials actually
  used (sleeves, bags or dividers between pairs, tape, labels) with their weights, or one weighed
  packed carton; the protection to design for (the offline runs used 1 in Ethafoam 220 as a labelled
  test assumption); and the carton actually used.
- A ChatGPT sign-in for the isolated live Sage test profile (the desktop's sign-in is not reused),
  and later permission for desktop promotion.
- Permission for a bounded live Sage research turn, with the questions to research. With a
  ChatGPT-plan sign-in, research runs on that plan's usage: no API key and no API fallback. An
  API-key or Anthropic research configuration would be billed by that provider separately.
- Redistribution decisions for the STEP runtime's bundled libraries before any installer or bundle
  is given to anyone (list in `docs/packaging-shipping-dependencies.md`); not needed for local testing.
- A clean Windows machine or VM for the install test.
