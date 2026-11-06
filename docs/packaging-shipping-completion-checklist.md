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
| Provider choice with current terms and services | Open | EasyPost is the only adapter. Current account prerequisites, fees, test/production behaviour and carrier coverage are being rechecked (P2 notes below). |
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
| Ship date, selected carrier accounts, service constraints, options in the request | Open | `QuoteRequest` has revision, origin and up to three destinations only. Add, or block clearly where semantics are unverified. |
| Price basis: account rate vs list vs retail | Open | Only `rate` is kept. Keep the price types separate and never mix them in a comparison. |
| Actionable, sanitized carrier failures | Open | Provider messages are only counted. |
| Supported US destinations (contiguous, AK/HI, PO boxes, military, territories) | Open | Any two-letter state and ZIP is accepted. Define and test the supported set; reject or explain the rest. |
| Complete request fingerprint, duplicate prevention, explicit refresh, account-change staleness | Open | Quotes go stale by revision only. Repeated identical requests create new provider shipments. |
| Sanitized carrier-account discovery | Open | No discovery endpoint. Allowlisted IDs/aliases/capabilities only, never raw provider objects. |
| Change of design invalidates quotes | Locally verified | Revision-bound history marks other revisions stale. |
| Live quotes for one approved package to three valid US addresses, two carriers | Blocked | Needs a privately entered key, approved addresses with residential/commercial status, a confirmed gross weight and permission for metered calls. |
| Explain differences from a carrier website's retail quote | Blocked | Needs live rates; requires the price-basis work above. |

## P3 - Packaging alternatives and simple inserts

| Requirement | Status | Evidence or next action |
| --- | --- | --- |
| Constrained arrangement search, split cartons | Implemented | py3dbp over up to six carton choices and one to six packages of one carton type. Ranks by package count then outer volume, not cost. |
| Proposals keep approved protection and packing mass | Open | `packing.propose` rebuilds packages and drops inserts, allowances and graphics. Fix before any cost comparison. |
| Minimum cushioning and no-contact constraints | Open | Not modelled. |
| Upright/allowed orientations, carton boundaries, known load limits | Locally verified | Domain tests; unknown payload stays a warning. |
| 1-, 6- and 24-item fixtures: feasible alternatives or clear infeasibility | Open | No 24-item fixture exists. |
| Sourced stock-carton selection | Open | One ULINE carton and cited PMMA/Ethafoam densities. |
| Cost-aware comparison with a baseline; cannot win by shrinking CAD, dropping items or protection, ignoring payload or mixing stale/test rates | Open | Saved alternatives compare volume, mass and known material cost; no shipping-cost comparison or baseline. |
| Pocketed inserts | Locally verified | Domain tests. |

## P4 - Sage execution and deliverables

| Requirement | Status | Evidence or next action |
| --- | --- | --- |
| Sage tools over the same service | Locally verified | Historical live chat checkpoint (inspect/propose/edit/validate/Undo, density estimate, PDF link). |
| Sage research with stored citations | Open | Packaging Sage has no research tool. Reuse `ai_inspector/research/web.py` and the existing workflow pattern. |
| Sage quote using the same service, scenario IDs instead of addresses, explicit transmission authorization | Open | No quote tool. |
| Dedicated packaging permissions | Open | API and gateway reuse `layout.read` / `layout.edit`. |
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

## Unsupported inputs (first release)

Mixed products in one design; arbitrary contour or fitted inserts; dielines; pallets, crates
and freight; hazardous or special-handling contents as ordinary parcels; international
shipments; verified CAD material mass; GLB as physical volume evidence; label or postage
purchase, pickups and payment; future ship dates (until provider semantics are verified).

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
