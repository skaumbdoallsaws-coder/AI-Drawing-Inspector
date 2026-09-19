# Sage objective-to-layout: admission and isolated preview backend

Date: 2026-09-17

Status: Backend checkpoint implemented. Not a live Sage conversation, editor
integration, manufacturing qualification or promotion of the whole first slice.

## What is now implemented

`generation_admission.py` connects the generation ledger to the existing
FacilityPlanningPackage/FacilityProgram compilers and authoritative layout
preview service. A request supplies a new coordinate-free package proposal, not
an allowlisted fixture package or candidate coordinates.

1. Require the preview capability and principal action before source/lease access.
2. Bind the request to the exact current ledger, workspace and saved empty base.
   Check the observed editor state and existing shared draft ownership.
3. Resolve an immutable curator-recorded prototype source context. Re-resolve its
   exact Process Map revision/identity and current preview-eligible catalog assets.
4. Reject model-authored authority/review fields. Populate server-owned prototype
   authority without elevating pending evidence or claiming production eligibility.
5. Validate package schema, approved process/equipment mapping and every active
   registered requirement. Unsupported clauses, missing references and extra
   unresolved source bindings block admission.
6. Retain the admitted package and compiled program with source/compiler/base
   fingerprints and a logical content revision.
7. Execute the exact admission ID/revision through existing deterministic
   compilers. Reject forbidden operations and enforce the cumulative kernel limit.
8. Replay through `FacilityLayoutService.preview_operations`, including dependency,
   spatial and routing checks. Compare its resulting revision with the staged
   execution result. Both diagnostic verdicts must be present and passing;
   missing validation is not a pass.
9. Retain the candidate, operation plan, cumulative diff, receipts, generated IDs
   and findings. Return a bounded summary; explicit inspection returns the exact
   candidate and validation evidence, including warnings and unverified findings.

Candidates remain prototype geometry. They do not establish production flow,
safety, capacity, staffing or manufacturing feasibility. Executable process
bindings are not created and `optimizationAvailable` is explicitly false.

## Persistence and correction

The existing design repository owns immutable artifacts and retention pins.
The generation repository adds a publication marker after all pins succeed.
An interrupted publication cannot be consumed as a finished admission/preview;
retrying the same request repairs publication. Logical IDs are hashed before
use as Windows storage components. Content revisions are verified on read.

Retry addresses include principal, tenant, site, layout, workspace, action and
request key. Canonical object-key ordering preserves equivalent retries;
different content under the same key conflicts. Preview retries return the
retained candidate without recompiling geometry.

Publication uses the same site lock as ledger corrections. A correction committed
first rejects a late publication. Previously published artifacts remain immutable
and pinned, but their old ledger revision is ineligible for current inspection
or execution. A failed corrected preview does not restore old eligibility.

Current eligibility conservatively fingerprints the complete selected catalog,
effective shell/policy, resolved Process Map, reviewed context, base and compiler
sources. It is not minimal dependency invalidation. An exact retained Process Map
edition remains usable when the repository can resolve that edition; the service
does not silently substitute the latest edition.

These checks are preview eligibility, not a reservation for Apply. No write lease
is acquired. Authoritative editor capture and correction-versus-Apply preparation
are still required in the adoption integration.

## Interfaces and ownership

New gated endpoint:

`POST /api/facility-layout-planning/{site_id}/{layout_id}/{action}`

The closed outer body contains `workspaceId`, `request`, and `editorContext`.

| Action | Request fields | Result |
| --- | --- | --- |
| `admit` | requestKey, ledgerId, ledgerRevision, sourceContextRef, proposal | Admission ID/revision and exact package identity/hash. |
| `preview` | requestKey, admissionId, admissionRevision | Candidate ID/revision, counts and qualification. |
| `inspect` | previewId, previewRevision | Exact current candidate, manifest, receipts and diagnostics. |

`INSPECTORPRO_FACILITY_LAYOUT_GENERATION_PLANNING_PREVIEW` defaults off through
the environment policy. Tests explicitly enable it. `agent_preview` is required;
preview remains available when `agent_write` is disabled. There is no new Apply,
Save or source-review HTTP action. The existing MMLE allowlist is unchanged.

`publish_source_context` is an explicit server-side curator operation requiring
`authority.review`; it is not an agent tool. It records the curator's prototype
mapping assertion with identity and retention. Product/document/package references
inside that reviewed snapshot are not independently read or engineering-qualified
by this adapter. Document fact extraction, review revocation and an installed
configuration registry remain outside this checkpoint. Missing real reviews must
not be replaced with the synthetic test contexts.

Added ledger predicates: `resource_mapping`, `department_allocation`,
`resource_pattern`, and `resource_spacing`. Existing envelope, quantity and
unsaved-preview predicates remain. Text-span accounting is still structural;
no general natural-language understanding claim is made.

Bounds: 256 KiB admission/source requests, 8 MiB retained artifacts, 16 KiB tool
summaries, 32 process steps/mappings, eight departments, 24 resource batches,
120 placements and 500 cumulative operations. Full candidate inspection is a
separate artifact response, not a promise to put the entire layout into model
context. There is no automatic retirement of pinned artifacts in this slice.

Cell recipes/module families are explicitly unsupported by this new adapter
pending coverage; supported resource placement patterns are enabled. Existing
generation engines and their broader legacy paths are unchanged.

## Verification

Final result: **243 passed in 138.10 seconds**, with zero failures/skips.
Machine-readable evidence: `.runtime/generation-admission-verified.xml`.

| Suite | Passed |
| --- | ---: |
| New admission/preview tests | 55 |
| Generation requirements and storage | 76 |
| Existing design-loop contracts | 44 |
| Existing facility planning and planning generation | 10 |
| Feature flags | 16 |
| Program execution and FacilityProgram | 15 |
| Construction service | 12 |
| Host integration | 15 |

Command executed from the project directory:

```powershell
python -m pytest tests/test_facility_generation_admission.py tests/test_facility_generation_requirements.py tests/test_facility_layout_design_loop_contracts.py tests/test_facility_layout_facility_planning.py tests/test_facility_layout_planning_generation.py tests/test_facility_layout_feature_flags.py tests/test_facility_layout_program_execution.py tests/test_facility_layout_facility_program.py tests/test_facility_layout_construction_service.py tests/test_facility_layout_host.py -q -p no:cacheprovider --basetemp=.runtime/gen-admission-verified --junitxml=.runtime/generation-admission-verified.xml
```

`git diff --check` passed for the touched paths. The ambient LangSmith plugin
emitted its existing Python 3.14/Pydantic-v1 warning. Earlier development runs
exposed test-fixture/import/assertion issues that were corrected without changing
legacy geometry or validation tolerances. This is a focused regression run, not
a full repository or native desktop qualification.

Tests use isolated temporary hosts and synthetic review assertions, not the live
manual layout or reviewed manufacturing acceptance fixtures. New coverage proves:

- A newly supplied package compiles through real geometry and authoritative
  validation into two placements, then a quantity correction produces three.
  Both candidates derive from the same empty base; saved canonical bytes match.
- Two additional feasible configurations use 32 x 24 m/three benches and
  38 x 28 m/four benches without supplied candidate coordinates. These are
  deterministic variation tests, not held-out provider generalization evidence.
- The negative packing control has 120 bench footprints exceeding the entire
  10 x 10 m site even before aisles/spacing. The actual compiler reports
  `facility_program_resource_set_unplaceable`; no fixture failure is injected.
- A corrected envelope larger than the bound floor fails. Old candidate A stays
  retained but cannot be used under corrected requirements B.
- Forged authority, unresolved clauses, mismatched quantities/patterns/spacing/
  allocations, unknown sources, wrong scope and changed source/compiler inputs
  fail closed. Catalog eligibility cannot be overridden by the review assertion.
- Equivalent retries, changed-key conflicts, exact admission revision and artifact
  corruption checks; retained Process Map resolution through the real host loader.
- Repository/service reconstruction retains the exact preview and retry receipt.
  This is restart persistence evidence, not native process-kill recovery testing.
- Fault injection at retention/publication boundaries verifies ineligibility and
  idempotent repair. A competing shared owner is neither displaced nor modified.
- Preview works with agent write disabled. HTTP rejects malformed input and has
  no Apply/Save/source-review actions. Windows reserved/colon IDs round-trip as data.

New preview tests install a failing Save spy and check saved bytes. Adjacent legacy
tests intentionally exercise Save only in their own isolated fixtures. No live
manual layout, catalog, Process Map, application feature configuration or editor
state was modified. No provider request or Electron acceptance run was made.

## Remaining gates

1. Freeze the reviewed real scenario, source applicability and product thresholds.
2. Register bounded Sage tools and trusted turn/editor context; bind live semantic
   interpretation to the ledger and prove complete clause coverage.
3. Show the exact isolated candidate in Plan/3D and handle superseded previews.
4. Implement shared Apply preparation, exact selection, editor-frame capture,
   pending acknowledgment recovery, Undo and the amended explicit Save receipt.
5. Complete actual provider/normal-desktop acceptance and promotion review.

The current API returns an exact immutable preview; it does not install a draft.
The whole batch 2/3 integration remains open until these contracts compose.
