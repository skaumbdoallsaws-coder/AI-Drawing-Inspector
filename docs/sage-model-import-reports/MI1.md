# MI1 implementation report

## CHANGED

Implemented the tenant/site import store, background inspection and HTTP routes.
No commits or index/history changes. No network or package installs. No files
under static/ or server.py were edited by this phase. Concurrent changes to
host.py, server.py and a new private_catalog.py appeared during the final audit;
those changes were left untouched and are not part of this report.

- model_import_store.py: ModelImportScope, authorization on each public lookup,
  upload/inspection lifecycle, deterministic frozen draft publication, metadata
  paging, receipt hooks, reference-based source cleanup, admission, reservations,
  restart reconciliation and retention.
- model_import_files.py: checked local paths, no symlink/junction traversal,
  atomic/fsynced JSON replacement, a cross-process coordinator using Windows
  byte-range locks or POSIX flock, and PID/start-time identity checks.
- model_imports.py: raw streamed uploads, polling/list/retry routes and bounded
  PNG responses. Uploads return before inspection completes. The router starts
  an hourly sweep and cancels/joins owned work on shutdown.
- facility_layout/api.py: four lines mount the router beside floor-plan imports.
  No server.py wiring was necessary.
- model_import/inspection.py and the worker protocol: optional worker-produced
  full scalar part metadata and original licence evidence. The host can page
  parts without importing numpy or decoding a model. Inspection manifests use
  version 3 only when storeMetadata=true; existing version-1/2 cache contracts
  and the default MI0 inspect/prepare behavior remain supported. Scalar part
  and licence validators were factored out of protocol.py.
- Tests: new test_model_import_store.py, test_model_import_routes.py and generated
  protocol fixtures in model_import_store_support.py. The fake workers exercise
  store boundaries; a separate test uses the actual inspect/prepare workers.

Storage is under <layout root>/model-imports/<sha256(tenant + NUL + site)>:

    sources/<sha256>.glb|zip
    imports/mi-<24 hex>.json
    inspections/<importId>/{summary.json,inspection.json,preview.png}
    drafts/md-<24 hex>/{frozen MI0 output files}
    registrations/<draftId>.json
    uploads/<importId>.part
    jobs/<operation id>/
    locks/<importId>.json

The model-import root also holds the coordinator and active-operation reservation
ledger. Durable leases contain pid, processStart, created, scope, user hash,
import ID, operation token and reserved bytes. The coordinator serializes
admission, quota checks, publication and cleanup across processes.

Admission is two operations per tenant/user and eight per app root. The 4 GiB
site budget includes retained sources, metadata, drafts, previews and jobs.
Uploads reserve Content-Length (or 128 MiB if absent) plus bounded metadata
overhead before the first receive; a lying length acquires more capacity before
writing. Worker reservations include the copied source and all bounded outputs,
including the 384 MiB geometry cache, metadata, pictures and preparation files.
Live trees are charged at their reservation, not by subtracting two racy size
scans while workers write. Housekeeping checks capacity for atomic replacements.
Reservations settle to retained bytes when a lease ends; leftover cleanup files
still count as physical storage.

The store discards numerical caches after inspection and keeps scalar metadata
and previews. Prepare rebuilds the numerical cache inside its isolated worker.
This trades another source read/render for substantially less retained storage.
Sources with identical bytes share one file and have separate import records;
GC derives references from the records and never deletes a referenced source.

Reconciliation runs on open, reads/admission and before sweeps. Dead or reused
PID identities release abandoned reservations and jobs; queued/checking records
without a live lock become failed/interrupted. Retry requires a failed record
whose source remains. Complete draft folders published just before a crash are
re-associated with their import. Old local work is cancelled and joined before
reclamation. Matching live foreign PID/start identities, and uncertain/corrupt
locks, are preserved regardless of age.

Only 20 unregistered drafts are retained per import; the oldest are evicted.
Unregistered drafts expire after seven days, failed/refused imports after one
day. Registered drafts retain draft.json, parts.jsonl, preview.png and the hash
manifest; model.glb, thumbnail.webp and CREDITS.txt can be removed because MI2's
bundle owns them. Imports with receipts remain to preserve registered draft
lookup/provenance. Sweeps skip held imports.

### HTTP contract for the concurrent MI4 builder

All paths start with /api/facility-layouts/{site_id}/{layout_id}:

- POST /model-imports: raw body, percent-encoded X-Model-Name; returns HTTP 202
  with the record directly. Both id and importId contain the mi- ID. Normal
  initial state is queued; name, bytes, format, created, createdBy and refusal
  are present. created/updated are Unix seconds.
- GET /model-imports: {"imports": [newest twenty compact records]}.
- GET /model-imports/{importId}: the current record directly, including summary,
  licence, warnings, drafts and registrations derived from receipts.
- POST /model-imports/{importId}/retry: HTTP 202 with the same ID, queued.
- GET /model-imports/{importId}/preview and
  GET /model-drafts/{draftId}/preview: image/png.
- Failures use {"error": {"code", "message", "details"?}}. Cross-scope IDs return
  the same 404 as missing IDs. Viewer writes are 403, admission 429, storage
  quota 507, body cap 413, worker refusals normally 422; unavailable runtime/
  storage is 503. All responses/pictures are private/no-store, with nosniff.

No frontend changes are needed beyond consuming this contract.

### MI2 / MI3 integration seams

get_model_import_store(service) shares the router's store. Call it with a
ModelImportScope(principal, site_id, layout_id); the store rechecks action and
layout existence. Methods: inspect(scope, import_id=None, offset=0, limit=64),
prepare(scope, recipe, cancel), draft(scope, draft_id),
draft_parts(scope, draft_id, offset=0, limit=64), preview(...),
receipt(scope, draft_id), record_receipt(...).

MI2 should use hold_draft(scope, draft_id), which yields the frozen metadata,
directory and lease, throughout bundle publication/live binding/receipt creation.
Pass that lease as _lease to record_receipt. A receipt is written atomically
before compaction and is idempotent; conflicting asset/revision values refuse.
After compaction, repeat registration must verify/reuse the library bundle,
not require deleted draft files. MI2 still owns bundle validation, publication,
live catalog binding and catalog-version reconciliation.

The runtime uses packaging_shipping.sources.glb_runtime(), including its trusted
native-release binding. Tests may inject a trusted runtime/worker explicitly.
ModelImportError details are retained when translated to FacilityLayoutError.

## TESTS

The available Python 3.14 lacks pytest, FastAPI, numpy, Pillow and jsonschema.
Attempted the required command through the hidden launcher:

    python -B -m pytest tests/test_model_import_store.py tests/test_model_import_routes.py -q -p no:cacheprovider --basetemp=<temporary-directory>/mi1/pt

Result: exit 1, No module named pytest; zero tests collected.

Executed standard-library probes against the actual store modules, bypassing
application package facades and using protocol-shaped fake worker outputs:

- upload -> inspect -> prepare -> identical-recipe reuse -> receipt -> compaction,
  including retained preview and part paging;
- tenant/site isolation, viewer denial and duplicate-source reference cleanup;
- 22 prepares retain 20 unregistered drafts; seven-day draft expiration;
- concurrent reservations through two store instances, absent/false lengths and
  denial before excess bytes are written;
- two real hidden Windows Python processes competing for the same site quota:
  exactly one acquired the reservation, the other received model_import_quota;
- old local worker cancellation and joining before reclamation, interrupted
  upload cleanup, PID/start identity mismatch and conservative unknown locks;
  an exited Windows process is also correctly stale while its parent retains
  a process handle;
- actual-byte quota settlement across prepares, cancellation during final
  cleanup, recovery after draft rename but before record publication, retry,
  and receipt recovery after an injected cleanup failure.

These probes passed. A late quota-helper editing error was caught by a probe,
fixed, and the affected upload/prepare/quota/recovery paths were rerun successfully.
Syntax and LF checks passed for 43 Python files, with self-contained imports in
the worker package. The report/README use LF, and the MI1-scoped git diff --check
passed. Bounded Unicode draft paging and compact tool listings also passed
standard-library probes.

## NOT RUN

- Pytest collection/execution, the minimal FastAPI TestClient/ASGI route tests,
  and the new real numerical-worker store smoke test.
- The existing model-import, facility-layout and packaging suites.
- POSIX flock/process identity and real symlink/junction rejection on all
  supported platforms.
- Concurrent host.py/server.py/private_catalog.py changes from other work.
- Browser/frontend integration, real downloads, and real-venv peak storage/
  worker timing. No server was started and no private app data was read.

## DEVIATIONS

- The full worker/cache bounds replace nominal 64 MiB reservations, as required
  by section 10 item 1. Capacity is conservative and acquired before writes.
- Inspection retains scalar metadata rather than the large geometry cache.
  The optional version-3 worker result is the required paging/provenance bridge.
- A live operation owned by another process is never forcibly reclaimed based
  on age. Local operations are cancelled/joined; foreign operations remain
  protected until their PID/start identity is gone.
- Registered import provenance records are retained with their receipts.
- Numerical, HTTP and platform verification remain unrun because dependencies
  are unavailable here; no dependency substitutes or installs were introduced.

## OPEN QUESTIONS

No design decisions are pending. Claude should run both new test files and the
existing model-import/facility suites in the real venv before committing MI1.
MI2 must use the registration lease and verify the library bundle when answering
an existing receipt. MI4 should consume the HTTP contract above; static/ was
left entirely to its builder.
