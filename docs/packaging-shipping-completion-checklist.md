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
| Dependency choices: py3dbp (MIT), trimesh (MIT), reportlab (BSD), OCP STEP worker, EasyPost | Implemented | In use and promoted locally. Third-party license/notice review and redistribution remain P5 work. |
| Provider choice with current terms and services | Blocked | EasyPost remains the only adapter. Terms re-read 2026-11-06 from EasyPost's docs and API Addendum v4.3 (effective 2026-10-30): rating creates a Shipment (an external write); three rating calls are included per purchased label, then $0.02 per additional call; address verification $0.02 beyond one per label; SmartRate $0.03; test mode contacts no carrier. This workflow buys no labels, so production rating calls are expected to be billed (inference, shown as the fee notice). Needs the user's account choice and permission for metered calls. |
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
| Direct selection of an existing app part/assembly and configuration | Open | Sources are uploads (GLB/STEP). A small source adapter for selected assemblies is section E work. |

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
| Sourced stock-carton selection | Open | One ULINE carton and cited PMMA/Ethafoam densities. |
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
| Report: packing sequence, packed vs exploded views, quote identity (design, scenario, account, mode) | Open | The report states that the sequence is unverified; only the first current quote is printed without its fingerprint. |

## P5 - Desktop release validation

| Requirement | Status | Evidence or next action |
| --- | --- | --- |
| Ribbon panels, viewport conventions, display modes, decals | Locally verified | Historical browser and native checks. |
| Promotion into the regular desktop | Implemented | User-approved local promotion at `3ce2b05`; not a gate pass. Next promotion needs approval. |
| Recoverable draft checkpoints, outstanding-operation reconciliation, safe shutdown/restart | Open | A fail-closed guard prevents data loss; it is not recovery. |
| Legacy managed runtime transition path | Open | Needs an explicit supported/unsupported decision with tests before enabling packaging there. |
| Dependency/license/security review, clean Windows install, missing-dependency behaviour | Open | Local development deployment only. |
| Artifact retention, quotas and cleanup | Open | No retention policy for sources, images, quotes or alternatives. |
| No secrets in evidence, no orphaned workers, offline manual use | Locally verified | Historical native evidence; recheck at release. |
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

## Unsupported inputs (first release)

Mixed products in one design; arbitrary contour or fitted inserts; dielines; pallets, crates
and freight; hazardous or special-handling contents as ordinary parcels; international
shipments; verified CAD material mass; GLB as physical volume evidence; label or postage
purchase, pickups and payment; future ship dates (until provider semantics are verified).
PO Box addresses; US territories and military (APO/FPO/DPO) addresses, which need customs data.

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
- The product, configuration and quantity to quote, and an approved gross weight or a
  measured/CAD mass reference.
- Permission for a bounded live Sage and rating test, and later for desktop promotion.
- Permission for a bounded live Sage research turn (it uses the configured research provider and
  is billed by that provider), with the questions to research.
