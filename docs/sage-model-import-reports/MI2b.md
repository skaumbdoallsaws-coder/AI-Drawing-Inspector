# MI2b - registration and host hooks

## CHANGED

- ai_inspector/facility_layout/model_import_runtime.py: model-import-only trusted dependency discovery. A configured packaging/native runtime wins. Otherwise host find_spec locations for numpy and PIL must name ordinary package initializers in the same validated local directory; linked/junction paths and split/missing installs fall back to packaging's purelib default. Packaging behavior is unchanged.
- ai_inspector/industrial_assets/authored_library.py: move the destination path resolution/check inside LOCK + CatalogLock, alongside immutable bundle reuse/publication. A competing rename cannot produce an outside-folder refusal before serialization.
- tests/test_model_import_chat_transport.py: clearly skip the frozen request-hash case if its untracked fixture is absent.
- ai_inspector/facility_layout/model_import_store.py: construction is now filesystem-free. The first authorized use creates the store; reconciliation and sweep leave a nonexistent store alone. Add bounded read-only attachment descriptions and receipt-derived registration notifications. Receipt publication uses the peak reservation held by hold_draft instead of charging another 4 KiB on top of it.
- ai_inspector/facility_layout/model_import_registration.py: publish the frozen draft without rebuilding. Recheck edit authority and scope, hold its durable lease through installation, bind and live swap, then immediately persist the receipt. Concurrent callers reuse the same identity. A competing host can finish its lease while another waits briefly. After compaction, repeat registration verifies installed bytes against the retained draft manifest and the complete D6 identity through install_bundle. Missing/changed installed files are conflicts, never repaired.
- ai_inspector/facility_layout/host.py: expose register_imported_asset and all five shared-contract agent_runtime hooks; close import jobs during host shutdown. No server.py change was needed.
- tests/test_model_import_runtime.py, tests/test_model_import_registration.py: runtime discovery, frozen publication, live binding, placement/revision stability, same-draft concurrency across two hosts, publication/binding/receipt failure recovery, compaction/sweep/restart, bundle corruption, scope/permission checks, hook shapes and pagination, retained recipe diagnostics, attachment descriptions, receipt notifications and near-quota receipt publication.
- tests/test_model_import_catalog.py, tests/test_model_import_store.py, tests/test_model_import_routes.py: deterministic destination-resolution race regression and lazy store/router/startup/shutdown regression coverage.

The new adapter returns the exact shared signatures:
- model_import_inspect(principal, reference, *, import_id=None, draft_id=None, offset=0, limit=64)
- model_import_prepare(principal, reference, recipe, cancel)
- model_import_register(principal, reference, draft_id)
- describe_model_attachment(principal, binding, import_id)
- registrations_since(binding, started_at)

Inspect/prepare return bounded JSON and PNG bytes separately; registration returns assetId, assetDefinitionRevision, displayName, category, dimensions, attribution and added. Draft inspection keeps pagination usable after heavy draft files are deleted. Bounded summaries preserve at least one part on a nonempty page, trimming materials/warnings if needed.

registrations_since has no principal argument in the agreed contract. The adapter therefore retains actual server-resolved principal objects in a bounded 512-entry memory cache, refreshed by resolve_principal and authorized hooks. It never constructs authority from binding IDs. Local mode also accepts only the host's fixed local identity. The hook rechecks layout.read and layout existence; it deliberately does not reject an old pre-turn revision, since a successful placement in that turn can advance it. Unknown custom identities fail closed. Notifications contain at most 256 distinct recent asset IDs; catalogVersion remains the authoritative refresh mechanism.

This session did not edit the concurrent MI3b tool/playbook/pinned-test files, static/, server.py, or packaging's runtime implementation. No commit or index/history operation was performed.

## TESTS

Actual checks in this sandbox:
- AST parsing and LF checks passed for the 11 changed/new Python source/test files owned by this phase.
- git diff --check passed for the phase-owned tracked changes.
- A standard-library probe on temporary roots passed: filesystem-free construction/idle maintenance; upload/prepare with protocol worker stand-ins; six concurrent registrations yielding one added result; receipt-derived notifications; inspection after compaction; sweep/repeat; corrupted bundle refusal; retry after live-bind and receipt-write failures; bounded timestamp refusal; receipt publication at its admission budget.
- The same probe passed user-site discovery, configured-runtime precedence and purelib fallback. It used the actual GlbRuntime/binding definitions extracted from packaging's source so unavailable packaging application dependencies were not imported.

Probe limits: GLB verification and live catalog binding were substitutes. Its worker data used the existing protocol stand-ins. Those checks establish orchestration/storage behavior, not actual geometry, renderer, FastAPI or full-host correctness. The new pytest registration fixture uses the real reader/transforms/writer and real host binding, with inexpensive protocol picture fixtures; it has not run here.

Attempted through hidden pythonw.exe + tools/run_hidden.pyw:

    python -B -m pytest tests/test_model_import_registration.py tests/test_model_import_runtime.py tests/test_model_import_store.py tests/test_model_import_routes.py tests/test_model_import_catalog.py tests/test_model_import_chat_transport.py -q -p no:cacheprovider --basetemp=<temporary directory>/mi2b-pytest

Result: exit 1 before collection, "No module named pytest". The earlier four-fix regression command failed for the same reason. No pytest pass count is claimed.

## NOT RUN

- Pytest suites, real worker store smoke, actual GLB verification/live host binding, and FastAPI TestClient tests. The sandbox C:/Python314 interpreter reports numpy, PIL, pytest, fastapi and jsonschema unavailable. No packages were installed.
- The concurrent MI3b integration tests, native desktop/user-site execution, private downloads, network or provider calls.
- server.py import and default-store inspection were intentionally not used; lazy initialization is tested through a minimal app and temporary roots.

Claude should run the command above in the real environment, including test_model_import_store.py::test_real_worker_store_smoke, then the concurrent MI3b Sage integration suite. The existing concurrent installer test remains in the catalog suite alongside the deterministic guard regression.

## DEVIATIONS

No feature-scope deviation. Registration orchestration lives in a small host adapter module rather than expanding host.py. The trusted runtime is model-import-specific and consults packaging's existing configured binding without changing packaging behavior. The principal cache and notification cap implement the supplied two-argument receipt-hook contract without granting roles from IDs. The receipt reservation adjustment is needed to avoid refusing publication after admission already reserved its metadata.

## OPEN QUESTIONS

None. Real-environment verification remains for Claude.


## MI2b result-projection correction

Claude's real-environment run reported 713 passing tests and 18 failures at the same registration result projection. The four prerequisite fixes passed, including the real-worker smoke and concurrent installer test.

CHANGED: model_import_registration.py now takes dimensions from the frozen draft, while assetId, assetDefinitionRevision, displayName, category and attribution come from the bound catalog record; added still comes from install_bundle. Bound records expose size through definition.geometry.aabb, not a top-level dimensions field. The existing real-host registration test now explicitly pins that distinction, checks the five bound metadata fields, and compares returned dimensions with the bound AABB. No host/catalog shape or persisted identity was changed.

Reviewed every listed failing test, including the entire Sage upload/inspect/prepare/register/asset-inspection/placement-preview/restart chain. Checked the generated placement-ID path and staged validation shape as well as receipt/reuse/restart assertions. No additional mismatch was found by inspection.

TESTS: A standard-library probe using the actual unmodified _revision, _asset, _private_manifest_specs and build_private_local_asset_catalog functions, plus the real semantics/mirroring helpers, passed exact result-shape checks, frozen dimensions, bound metadata, six concurrent registrations, repeat after compaction/sweep, fresh binding and retained preview. It also confirmed the old projection raises KeyError("dimensions") on those bound records. The earlier orchestration probe's substitute bound record wrongly included entry dimensions; this probe corrects that verification gap. Syntax/LF and targeted diff checks passed.

NOT RUN: pytest and full-host/Sage integration reruns remain for Claude; the sandbox lacks the dependencies. The probe still substitutes worker outputs and GLB verification and is not a full-host test.

DEVIATIONS: None. OPEN QUESTIONS: None.
