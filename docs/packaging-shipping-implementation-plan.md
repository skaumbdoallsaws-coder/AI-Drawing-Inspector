# Packaging and Shipping Implementation Plan

Date: 2026-11-05

Status: implementation in progress in the isolated `packaging-shipping-2026-11-05` worktree.
See [implementation status](packaging-shipping-status.md) for completed checks and open release gates.
This plan describes the intended release, not the capabilities already enabled.

Product surface: a dedicated **Packaging & Shipping** workflow in InspectorPro, usable manually or through Sage.

## 1. Objective and first release

Turn an existing CAD product and requested quantity into an editable packaging assembly, compare practical packaging alternatives, and estimate shipment costs to US destinations. Keep product geometry, physical properties, packaging assumptions and carrier quotations traceable to their sources.

The core user request is:

> Package six of these parts. Compare suitable cartons and inserts, then estimate shipping from Minneapolis to Miami, Chicago and Dallas.

The workflow should return two or three feasible alternatives, not claim a globally optimal or transport-certified design. Each alternative should show the arrangement, carton, inserts, external dimensions, gross weight, material cost when known, and carrier/service quotations. The user can change any supported dimension or placement and recalculate.

### First-release scope

- Existing imported parts or assemblies with confirmed units and geometry references.
- One product type per packing problem, with multiple identical instances; retain a document structure that can accommodate mixed products later.
- Stock rectangular cartons and simple custom rectangular cartons, with internal and external dimensions distinguished.
- Foam pads, end blocks, dividers, spacers, and rectangular or cylindrical insert pockets.
- A 3D workspace with orthographic views, sections, transparency, selection, measurements and exploded inspection; no separate 2D editor required.
- Bounded arrangement search over user-permitted orientations, layers and carton choices, including comparisons between one carton and several cartons.
- US parcel quotations through one approved multi-carrier integration, including customer account rates where supported.
- Saved alternatives, validation findings, quote snapshots, a packaging BOM and packing instructions.
- Sage tools backed by the same operations available to manual controls.

### Explicit exclusions

- Shipment purchase, label purchase, pickup booking and automatic payment.
- Freight quoting, pallet engineering, crates, international customs and hazardous-goods packaging in the first release. Identify these cases and stop or route to a later workflow rather than misquote them as ordinary parcels.
- Automatic certification, drop-test claims, structural/cushioning simulation or guarantees against shipping damage.
- Arbitrary molded inserts, complex undercuts, automatic disassembly of products, or unrestricted CAD modelling.
- A full carton dieline editor, manufacturing-ready tooling or automatic supplier orders.
- Copying a competitor's packaging as proof that it is suitable for the user's product.

## 2. Existing implementations and reuse boundaries

The following code was inspected while planning. Its existence is not evidence that a packaging workflow already runs in the desktop build.

| Existing implementation | Proposed reuse | Boundary or required work |
| --- | --- | --- |
| `ai_inspector/industrial_assets/primitives.py` | Primitive definitions and GLB generation for simple packaging visuals. | Facility conventions are meters, Y-up, floor-centering and yaw-only placement. Some meshes omit faces. Separate packaging transforms and authoritative solids/volume calculations from these rendering shortcuts. |
| `../InspectorPro.SolidWorks/src/InspectorPro.SolidWorksExtractor/Part/PartDocumentPia.cs` | Source mass, volume, density, center of mass and mass-override metadata. | Bind to the selected source revision/configuration and physical material evidence. Some imported library records have no mass data. |
| `geometry_worker.py` | Evaluate existing OpenCascade STEP loading, Boolean cuts, solid volume and tessellation as a geometry backend. | Currently a revision-difference service, not a packaging API. Verify runtime availability, units, tolerances, licensing/deployment and robustness on real product geometry. Do not expose its raw filesystem-path interface to Sage. |
| `static/facility_layout_three_adapter.js` and existing assembly UI | Reuse suitable loading, selection, material and camera utilities. | The facility adapter is coupled to floors, walls, zones and avatars. Reuse small utilities; do not copy the entire editor or perform a broad viewer refactor. |
| `ai_inspector/codex_runtime/`, including `floor_plan_tools.py` | Typed tool definitions, bounded results, source-bound operations and integration with the existing Sage runtime. | Add a packaging document scope; do not masquerade as a facility document or build another reasoning loop. |
| Facility repositories, `operation_proposals.py`, `direct_edit_policy.py`, `transaction_adapter.py` | Reference existing patterns for revisions, receipts, authorization, direct edits and Undo. | Reuse only domain-neutral mechanisms. Packaging must not inherit floor-support or zone-containment rules. |
| `ai_inspector/research/web.py` | Approved provider-side research for carrier rules, materials and packaging references. | Keep the human browser's authenticated cookies separate. Retrieved content is evidence, never executable instructions. |

The assembly import adapter can contain empty mass properties. Treat unavailable mass as missing, not as zero. A black visual finish or a material display name is not sufficient physical-density evidence.

## 3. Architecture

```text
Packaging workspace                         Sage chat
        |                                       |
        +------- typed packaging commands ------+
                            |
              Packaging application service
        revision checks, authorization, Undo, audit
                            |
           Authoritative packaging document
                 /          |          \
        Geometry adapter  Packing search  Rating adapter
                 |          |          |
       Solid/analytic     Feasible     Carrier APIs
       geometry + GLB     candidates   and quote snapshots
                 \          |          /
                 Validation and comparison
                            |
               3D viewport, BOM and report
```

InspectorPro owns document state. Geometry backends return results; they do not independently save changes into the active project. The renderer displays those results and is not the source of authoritative measurements.

### Proposed module boundaries

Names below are implementation targets, not existing files or APIs. Adjust them to local conventions during the first milestone.

| Area | Proposed location and responsibility |
| --- | --- |
| Domain | `ai_inspector/packaging_shipping/`: schemas, persistence, commands, validation, materials, arrangement search and comparison. Add modules only as their responsibilities become necessary. |
| Geometry | A small adapter under the domain package for primitives, source geometry, volume, containment, collision and mesh generation; controlled jobs in the existing geometry-worker environment where appropriate. |
| Rating | Provider-neutral request/result types and one provider adapter; no carrier secrets in tools or document JSON. |
| HTTP | A specialized router following existing application router conventions, mounted with minimal changes to the server entry point. |
| Sage | `ai_inspector/codex_runtime/packaging_tools.py`, registered through the existing gateway and bound to the active packaging document. |
| UI | Focused `static/packaging_*` modules for the workspace, scene and controls, with a dedicated workflow entry. |
| Tests | Domain, adapter, tool-contract and browser tests following the repository's Python and JavaScript test patterns. |

Do not start by building a generic plugin platform or replacing the current viewer. Extract shared code only when both workflows actually need it and regression tests cover the extraction.

## 4. Authoritative document and provenance

Use a versioned, separately persisted packaging document. Large CAD, BREP and GLB artifacts live in scoped artifact storage, not inline in JSON.

| Record | Required information |
| --- | --- |
| Document | Stable ID, schema version, workspace/principal scope, revision, name, units and coordinate convention. |
| Product source | Asset/document ID, revision or content digest, configuration, geometry reference, source units and original-to-package transform. |
| Product instance | Stable ID, source reference, package assignment and rigid translation/quaternion transform. Product scaling is not permitted as a packing shortcut. |
| Physical properties | Mass/volume/density where available; provenance, overrides, warnings and whether CAD-derived, supplier-specified, user-measured or estimated. |
| Material | Grade/SKU, density or board mass per area, thickness, relevant limits, evidence link/version and optional cost basis. Separate from rendering appearance. |
| Carton | Supplier/SKU or custom recipe, inner and outer dimensions, tare weight or calculation basis, capacity/load limits where supplied and cost/availability evidence. |
| Insert/component | Parametric recipe, physical material, component transform, validated geometry reference and derived mass. |
| Constraints | Allowed orientations, keep-clear and no-contact regions, minimum separations, required cushioning, handling limits, fragile surfaces and special-shipping flags. |
| Candidate | Immutable arrangement snapshot, source/design hashes, validation findings, assumptions and comparison metrics. |
| Shipping scenario | Origin/destination, address type, requested shipping date, service constraints, declared value and relevant options. |
| Quote snapshot | Provider, carrier/account alias, service, currency, amount, available breakdown, transit estimate, timestamp, quote ID and exact input fingerprint. |
| Operation receipt | Operation/run IDs, actor, before/after revision, changed entities, validation summary and Undo reference. |

Use meters and kilograms internally to align with existing 3D conventions; display millimeters/inches and kilograms/pounds as selected. Convert explicitly at CAD and provider boundaries. Define packaging-specific geometric tolerances during the geometry spike rather than inheriting facility-scale tolerances or display rounding.

Preserve exact source dimensions and physical properties independently of tessellation and camera transforms. Every derived result records the relevant source and design hashes. A CAD revision, material, quantity, carton or placement change invalidates affected mass, validation and quote results. A changed destination or shipping date invalidates affected quotes, not the geometry.

## 5. Geometry, materials and validation

### Geometry strategy

Start with analytic closed boxes/cylinders and dimensioned assembly recipes. Generate display meshes from those definitions. Use OpenCascade only for operations requiring solid geometry, subject to the feasibility gate.

For an insert pocket, subtract an explicitly dimensioned rectangular/cylindrical cavity, with approved clearance, from a solid foam block. Validate the resulting solid and remaining volume. Do not silently replace a failed Boolean operation with an attractive but inaccurate preview.

An exact negative of arbitrary product geometry is deferred: it may create undercuts, insufficient foam walls or an insert from which the product cannot be removed. Early inserts use simple pockets or separate blocks with straightforward packing directions.

Use bounding boxes as a fast conservative test and exact supported geometry for final checks where required. If only mesh/bounding-box evidence exists, state the validation level. Unsupported narrow-phase geometry must not produce a false precise clearance result.

### Mass calculation

1. Read source mass for the selected configuration, retaining override flags; alternatively use an engineer-entered measured mass.
2. If estimating from volume and density, require valid geometry, confirmed units and a sourced physical density. Missing values remain unresolved.
3. Sum quantity-aware product masses and the net mass of inserts/dividers/spacers.
4. Prefer supplier carton tare weight. For custom board estimates, use a supported blank-area recipe including flaps/overlaps and sourced mass per area; otherwise require a tare input. A hollow box's bounding volume is not cardboard material volume.
5. Include tape, accessories and other packing allowances explicitly. Show measured, calculated and assumed contributions separately; avoid false decimal precision.

### Validation categories

- **Geometry:** containment in usable carton space, collisions, required separations, minimum remaining insert thickness, lid closure and supported packing/removal direction.
- **Inputs:** units, source/configuration identity, missing mass, material evidence, carton inner/outer consistency and unresolved assumptions.
- **Packaging:** supplied carton load limits and product-contact constraints. Unsupported cushioning/stacking performance is a review finding, not an automatic pass.
- **Shipping:** supported destination/service, complete scenario details and package eligibility. Special-handling, batteries or hazardous contents require explicit assessment rather than inferred ordinary-parcel eligibility.

Return structured findings with code, severity, entity IDs, measured value, requirement and a possible next action. Use statuses such as `passed`, `failed`, `needs_review` and `not_evaluated`; never collapse them into one unexplained "valid" flag. Partial work can be saved as a draft, but a blocked candidate cannot be presented as ready to ship.

Fit validation does not establish protective performance. Supplier cushioning data, product fragility and suitable physical tests may be needed. Relevant public guidance: [ISTA design and testing](https://ista.org/getting_started_with_design.php) and [ISTA test procedures](https://www.ista.org/test_procedures.php). Licensed standards must be obtained through permitted access, not assumed freely available through search.

## 6. Shipping estimates and optimization

### Rating integration

Select one multi-carrier provider after comparing US service coverage, account linking, rate completeness, commercial API terms, data handling and integration costs. EasyPost is an initial candidate, not a committed purchase or dependency. Its [shipment API](https://docs.easypost.com/docs/shipments) accepts addresses and parcel data and returns rates separately from the label-purchase operation.

Use provider-returned quotes as the price authority. Published carrier rules support explanations and preliminary comparisons, not a model-invented price. Record effective dates and sources for any local dimensional-weight or surcharge rules; do not hardcode one universal divisor, rounding method or threshold.

Important distinctions from current carrier documentation:

- Applicable FedEx services compare actual and dimensional weight: [FedEx dimensional-weight guidance](https://page.message.fedex.com/weight_calculator).
- UPS identifies additional handling conditions associated with package dimensions and packaging form: [UPS charge-correction guidance](https://www.ups.com/us/en/support/shipping-support/shipping-dimensions-weight/avoid-additional-shipping-fees).
- FedEx supports list/account rates and charges, but quotes are estimates and its referenced parcel Rate API does not quote freight: [FedEx Rates and Transit Times](https://developer.fedex.com/api/en-us/catalog/rate/v1/docs.html).

These references were reviewed on 2026-11-04. Recheck rules, provider terms and API schemas during implementation.

The rating request must include the information required by the selected provider: exact package count, external dimensions and gross mass, origin/destination, shipping date, residential/commercial status and relevant options. Request missing inputs or label scenario assumptions. Do not silently treat every destination as commercial or every quote as the customer's negotiated rate.

For multiple cartons, use the provider's supported shipment semantics. A fallback sum of individual parcel estimates must be labelled as such and must not double-count shipment-level fees. Preserve carrier errors and missing-service outcomes; zero rates does not mean free shipping.

Normalize currency and amount without floating-point currency arithmetic. Keep provider fees, packing-material costs and shipping charges separate. Show unavailable breakdown items as unknown, not zero. All totals remain estimates until actual shipping charges are known.

Cache only by a complete request fingerprint, including provider/account, package data and scenario. Display timestamp, stale state and refresh control. A provider's missing expiry does not justify inventing a guaranteed validity period. API failure must not turn stale or test rates into current live rates.

### Optimization strategy

- Search available carton SKUs, permitted product rotations, regular layouts/layers and supported split-shipment options. Begin conservatively with identical items and bounded candidate counts.
- Evaluate an existing packing solver in the feasibility spike; select on licensing, Windows deployment, determinism and ability to enforce constraints. Do not equate generic bin-packing output with protective packaging.
- Reject physically invalid candidates before quoting. Quote only a small shortlist with bounded concurrency and provider-call budgets.
- Compare shipping, material costs and optional user-supplied packing labor under identical service requirements. Exclude unknown costs from explicit subtotals rather than suggesting a complete total.
- Show alternatives such as lower estimated cost, fewer packages and simpler packing. Label search limits and assumptions; do not promise global optimality or quantify damage risk without evidence.
- Keep a user-selected baseline so any claimed saving names the baseline, date, account and destination. Recalculate after edits.

## 7. User interface and Sage tools

### Workspace

Add a dedicated workflow entry with the existing product navigation and styling. Use a compact command ribbon, left component tree, unframed 3D viewport, properties panel and a comparison/results view. No marketing screen and no mandatory agent interaction.

Initial controls: select product, quantity, carton/material selection, add insert/divider/spacer, move/rotate, align, measure, section, transparency, exploded view, validate, compare shipping, save, Undo/Redo and export. Preserve stable dimensions and correct units when switching views. Manual changes use the same service commands as Sage.

### Proposed Sage tool surface

| Tool | Behavior |
| --- | --- |
| `inspect_packaging` | Read the bound document, source measurements, missing inputs and current validation status. |
| `search_packaging_catalog` | Retrieve dimensioned, sourced stock cartons/materials within constraints. |
| `propose_packaging` | Generate bounded candidate artifacts without modifying the active design. |
| `edit_packaging` | Apply a typed operation batch or selected candidate to the expected document revision, under existing direct-edit permissions. |
| `validate_packaging` | Return deterministic findings and identify checks not evaluated. |
| `quote_packaging` | Request estimates for an identified candidate and authorized destination scenarios; no purchase action. |
| `capture_packaging_view` | Return a bounded scene observation for visual verification, not a substitute for geometric validation. |
| `export_packaging` | Produce a version-bound report/BOM/instructions in authorized project storage. |

Final names should follow the gateway's actual naming conventions. Every tool uses stable IDs, server-bound workspace/document identity, strict schemas, finite numeric inputs and bounded arrays/results. Never accept arbitrary filesystem paths, scripts or external code.

Sage should inspect, identify missing constraints, generate alternatives, validate, correct supported failures and explain tradeoffs. It may research supplier data or comparable packaging through existing research tools, preserving sources and treating web/model text as untrusted data. Do not upload private CAD to research sites or rate providers; send only authorized shipment data needed for the quote.

Respect the user's existing preference for direct editing: ordinary reversible packaging edits should not require a separate preview click when Apply Directly is enabled. Backend validation and revision checks still run. Candidate comparison remains available, not mandatory. Consequential external actions remain excluded, and replacing user work must follow the existing authorization policy.

## 8. Transactions, isolation and observability

- Bind every mutation to the active packaging document and expected revision. Switching documents invalidates pending mutation authority; background results remain attached to their original document and cannot auto-apply elsewhere.
- Compute geometry and validation in staging; commit an operation batch atomically. A failed cut, cancellation or stale revision leaves the saved design unchanged. Return an idempotent receipt to prevent duplicate operations on retries.
- Group a logical Sage action into an understandable Undo step; support crash-safe document persistence and revision-aware Undo. Undo does not reverse an external API call or pretend its cost never occurred.
- Use scoped artifact storage, bounded import sizes, worker time/memory limits and existing safe subprocess conventions. No visible terminal windows in the desktop app.
- Reuse secure credential storage. Redact tokens, addresses and private customer identifiers from diagnostic logs; enforce tenant/workspace isolation for documents, quotes and geometry caches.
- Bound optimizer time, candidates, tool calls and rating requests. Cancellation stops further submissions and prevents late results from committing; report already-completed external requests honestly.
- Emit workflow ID `packaging_shipping`, run ID, document/candidate IDs, elapsed time, validation outcomes, tool counts and provider usage where available. Keep AI usage cost, rating-service fees, packaging cost and shipping cost distinct. A broader Usage-tab redesign is not part of this implementation.

## 9. Milestones and acceptance gates

The milestone gates below remain the acceptance criteria. Partial implementation is recorded in the status document; no release gate is implied by a passing unit test. Work in an isolated development/test copy and use disposable documents. Do not promote or restart the regular desktop build until its release gate and the user's approval.

### P0 - Feasibility and interface contracts

Inspect workflow registration, source/configuration selection, artifact stores, secure credentials, revision/Undo and shared viewer utilities. Test the existing OpenCascade environment on a real selected CAD part and analytic fixtures. Confirm source units and compare extracted mass against the source CAD application's reported value. Evaluate one packing solver and one rating provider with current terms and supported services.

Specify schemas, operation contracts, tolerance policy, resource limits and a small geometry-backend capability interface. The interface should cover geometry creation/loading, transforms, bounds, volume, supported cuts, containment/collision and mesh export without assuming every backend supports every operation.

**Gate:** approved dependency/provider choices; documented unsupported inputs; a real CAD import and dimension/mass comparison; a verified simple insert cut and volume calculation or an explicit pads/dividers-only fallback; no reliance on a future SolidCraft integration.

### P1 - Manual packaging document and 3D workspace

Implement source selection, quantities, persistence, basic carton/pad/divider definitions, transforms, material records, mass accounting, direct edits and Undo behind a development feature flag. Provide dedicated 3D inspection, measurements, source warnings and manual carton dimensions/tare input. Start with one arrangement and one carton; retain multi-carton document structure.

**Gate:** an engineer can package one and six instances of a real product, inspect clearances and save/reopen the exact assembly. Known dimensions/masses match independent references within the P0 tolerances. An overlap is reported; missing mass is not silently zero; source CAD remains unchanged; Undo restores the complete prior design. Manual work needs neither Sage nor a carrier connection.

### P2 - First end-to-end shipping estimate

Integrate one rating provider, destination scenarios, account selection, quote normalization, comparison and quote invalidation. Start with manual package inputs and the P1 measured package. Add explicit offline/test/live states and clear provider errors.

**Gate:** one real package produces live quotes to three valid US addresses with the same dimensions, weights, date, options and account verified in provider evidence. Where possible, compare at least two enabled carriers; never invent coverage if account access is unavailable. Explain differences from a carrier website's retail quote. A material/dimension/date change invalidates the affected quote. No label or shipment is purchased.

**First useful product checkpoint:** CAD to a saved 3D package to destination-specific shipping estimates. Do not delay this checkpoint for automatic custom inserts.

### P3 - Packaging alternatives and simple inserts

Add sourced stock-carton selection, constrained arrangement search, split-carton comparisons and supported pocketed inserts. Evaluate feasibility and cost components before requesting shortlisted live quotes. Show a baseline and side-by-side alternatives; allow manual correction.

**Gate:** fixtures with 1, 6 and 24 identical parts produce valid feasible alternatives or clear infeasibility. Enforce upright/no-contact/minimum-cushion constraints, carton boundaries and load limits where known. Prove a candidate cannot win by shrinking the source model, omitting packing mass or ignoring a failed validation. Report actual measured quote differences without requiring every case to save money.

### P4 - Sage execution and deliverables

Expose the packaging tools through the existing Sage interface. Supply concise workflow guidance for source inspection, assumptions, physical versus visual materials, validation and quote interpretation. Add a packaging BOM and PDF report using existing document/PDF facilities where suitable, with assembly views, source revisions, quantities, materials, packing sequence, findings and timestamped quotes.

**Gate:** in the live Sage chat, complete the six-part Minneapolis example end to end using actual CAD and carrier results. Deliberately introduce a too-small carton, missing mass and a stale revision: Sage must correct the supported problem or ask for the missing information without falsely claiming success. An engineer can manually refine Sage's result and Undo it. Report views identify packed versus exploded presentation; shipping dimensions always come from the saved packed configuration.

### P5 - Desktop release validation

Run targeted tests plus affected facility, assembly, documentation, Sage and desktop regressions. Record existing baseline failures separately. Package dependencies in the existing isolated desktop snapshot; verify startup, shutdown, worker cleanup, missing dependency behavior and offline manual use. Verify the feature flag and document a rollback path.

**Gate:** Windows desktop tests and real-Sage evidence pass; existing saved layouts and source CAD are unchanged; credentials are absent from logs and artifacts, and private customer/CAD data are excluded from distributed test/release evidence; cancellation/restart/Undo are verified; promotion is explicitly approved. Validate at least two live enabled carriers before presenting the release as multi-carrier comparison; otherwise explicitly restrict that capability. Only then enable the workflow in the regular desktop build.

### P6 - Optional advanced geometry and freight

Evaluate SolidCraft behind the same geometry interface with pinned version/licensing and a test corpus: STEP imports, transforms, dimensional fidelity, cuts, volume, topology identity, serialization, tessellation and Windows headless lifecycle. Keep its design state synchronized through InspectorPro-controlled operations, not an independent hidden GUI session. Its official project documents headless CLI/MCP support and an early-stage capability profile: [SolidCraft](https://github.com/tangency-labs/solidcraft).

Separately scope mixed products, more complex fitted inserts, sheet cutting/dielines, reusable packaging, palletization/crates and freight rating. Freight requires its own provider/data/validation work; it is not a larger-parcel toggle. These additions are not prerequisites for releasing P1-P5.

## 10. Verification matrix

| Test area | Required cases and evidence |
| --- | --- |
| Units and source | mm/inch/meter imports, configuration changes, source revision changes, missing materials, mass overrides and assembly quantity/suppression interpretation. |
| Geometry | Analytic box/cylinder volume, valid/invalid cuts, rigid rotation invariance, containment, overlap, minimum wall thickness and source-to-display alignment. Cross-check representative real STEP results against source CAD. |
| Mass | Quantity multiplication, foam subtraction, carton tare, accessory allowance, mixed provenance and unresolved inputs. No physical mass from an open display mesh alone. |
| Packing | Upright-only constraints, impossible cartons, blocked removal, layer separation, supported split shipments, candidate limits and cancellation. |
| Rating | Captured contract fixtures plus live evidence: correct units, per-package totals, residential/optional-service details, account isolation, absent services, timeout, rate limiting, stale quotes, dates, currency and partial provider errors. Test rates cannot appear as live. |
| State and security | Atomic failure, stale mutation, duplicate request, active-document switch, concurrent user edit, crash/restart, Undo/Redo, cross-workspace access denial, path traversal and untrusted research text. |
| UI | Desktop and narrow-window screenshots, visible/nonblank geometry, correct selection and transforms, carton transparency/sections, legible dimensions and no clipped controls. Test actual workspace wiring, not renderer-only fixtures. |
| Agent | Real chat turns that inspect, act, observe validation, correct and conclude. Mock tools test contracts but do not prove live Sage capability or carrier coverage. |
| Regression | Existing facility placement/appearance, assembly viewing, documentation output, chat routing, desktop startup and shutdown. |

Use synthetic fixtures for deterministic coverage and user-approved real parts for acceptance. Store reproducible results, commands, versions and redacted provider evidence. Do not publish private CAD or customer addresses in fixtures.

## 11. Decisions and implementation handoff

Defaults for implementation planning:

- Build a separate packaging domain and a 3D-first UI; no facility document workaround.
- Start with known, non-hazardous products, identical quantities and parcel shipping.
- Use stock packaging and sourced material properties before unrestricted custom design.
- Reuse existing geometry infrastructure where verified; keep SolidCraft optional.
- Use one provider integration and preserve provider-neutral quote records.
- Keep reversible manual/Sage edits direct under the user's selected policy, with deterministic checks and Undo.
- Reuse existing Sage orchestration and document export facilities; no new general-purpose agent loop.

Before live rating, obtain an approved provider account/API credentials through secure storage, valid origin/destination details and an approved real product fixture with a mass reference. Missing credentials should not stop local geometry/UI implementation, but the live-rate release gate remains open until they are supplied.

Before building complex pockets, resolve P0's backend/tolerance findings. Before any desktop promotion, complete P5 and obtain approval. Do not substitute a visual demonstration for an acceptance gate.

**Next action after implementation authorization:** perform P0 in the test copy, record the actual compatibility decisions, then complete P1 and P2 as the first vertical slice. This plan alone does not authorize dependency installation, paid service enrollment, production-data migration or desktop promotion.
