# MB4a - drafts, identity, bundles and registration

CHANGED

- `ai_inspector/facility_layout/model_import_store.py` and new `model_build_store.py`: build reservations use `kind: build` and an `mbj-<24 hex>` object ID; registration leases use the `md-<24 hex>` draft ID. They share import admission (8 app / 2 user), coordinator, process ownership, site quota and cleanup. A build reserves 160 MiB before inputs are copied. Complete drafts are atomically published, deduplicated by complete identity, and retained after cancellation crosses publication. There is no source file or parent import record. Published folders are the recovery index. Unregistered builds have a seven-day expiry and a limit of 20 per site; held drafts count toward that limit and are protected. Registered drafts retain recipe, result, manifest and preview while their heavy files are compacted.
- New `ai_inspector/industrial_assets/model_builder/drafts.py`: bounded, immutable draft contents and validation; normalized private recipe, full result, GLB, preview, thumbnail, optional credit, hashes, scope, creation/expiry, and a bounded parts summary. The store exposes `build` and `list_build_drafts`; existing draft inspection, preview, receipt and registration boundaries dispatch by kind. Missing kind remains a legacy import. `model_import/prepare_protocol.py` also accepts an explicit import kind without changing the legacy output or identity.
- New `ai_inspector/industrial_assets/model_builder/identity.py` and `adapt_keys.py`: portable recipe hash, engine, artifact pins, output hash and catalog semantics determine `asset-built-<slug40>-<hash24>` and the content-derived draft ID. Provenance validates the existing recipe size-basis choices, up to three HTTPS citations, triangle count, recipe hash and optional `derivedFrom`. Private reference IDs remain in the draft; they do not enter the published recipe, identity or GLB.
- `model_builder/build.py` and `protocol.py`: included builds bind their include frames, anchorability, part maps and carried credit into GLB asset extras. This lets installation check the persisted anchor metadata against the output hash already in the identity. Builds without includes keep their prior GLB serialization path.
- `model_builder/job_io.py`, `worker_task.py`, and `ai_inspector/industrial_assets/model_builder_runner.py`: an opt-in, fixed `draft-request.json` asks the contained build worker for the existing import preview and thumbnail. Inputs remain fingerprinted and output pictures are validated before staging a draft. The ordinary MB3 worker request still produces only model/result. Rendering shares the existing CPU/wall/memory limits and cancellation path; no extra worker or renderer process is launched.
- New `ai_inspector/industrial_assets/model_builder_bundle.py` and dispatch in `authored_library.py`: independent build validation, canonical portable recipe, provenance and include validation, `primitives.verify` with hangHeight, immutable built folder, exact file set, and CREDITS.txt only for carried attribution. Missing-kind imports still use the existing import validator, unchanged; explicit import kind also delegates to it. Existing folders are never repaired on identity conflict.
- `ai_inspector/facility_layout/private_catalog.py` and `host.py`: optional provenance is validated by a new projection wrapper and carried into the bound record and definition/revision. `private_asset_spec` itself and its category rules are unchanged. Host functions `build_model_draft` and `list_model_build_drafts` check saved-document scope, permissions and revision. The build host supplies current catalog categories and bundled appearance IDs, and rechecks authorization/revision before publication.
- `ai_inspector/facility_layout/model_import_registration.py`: existing inspect/register hooks dispatch build drafts, install and bind without restart, persist receipts immediately after binding, and validate repeat registration from installed bytes after compaction. `derivedFrom` is accepted as host metadata only for a present catalog asset. No Sage tool, gateway, server route or UI wiring was added.
- New tests: `tests/test_model_builder_identity.py`, `test_model_builder_draft_store.py`, `test_model_builder_bundle.py`, `test_model_builder_registration.py`, `test_model_builder_draft_worker.py`, with `tests/model_builder_draft_support.py`. They cover private/portable metadata, strict identity and bundle checks, both cancellation sides, concurrent identical jobs, crash recovery, kind-aware leases, capacity/admission/expiry, scope and permissions, legacy preservation, live/restart registration, hung models, provenance projection, second-generation composition, credit presence, include frames/maps, and worker preview parity/refusals. All generated geometry and catalogs use test temporary roots; no binary fixtures were added.

The existing renderer samples base-colour textures through UVs, so printed faces are textured in these previews. It produces the same 768 x 768 four-view sheet and 256 x 256 thumbnail as imports. It does not sample `emissiveTexture`: its shader adds a constant emissive colour, which can wash out a lit print. It also does not resolve library default finishes. No close-ups, top view, dimension arrows, enhanced lighting or other MB4b picture work is included. These observations are from the renderer code, not a visual run in this sandbox.

TESTS RUN

All commands ran serially through `pythonw.exe tools/run_hidden.pyw`, with redirected output and hidden Windows processes. No pytest invocation was attempted.

- `C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -m unittest tests.test_model_builder_identity -q`: 10 passed.
- `C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -m unittest tests.test_model_builder_identity tests.test_model_builder_schema tests.test_model_builder_composition_contract -q`: 34 passed. This includes the ten identity tests above; it is not 44 distinct tests.
- The same Python interpreter with `-B -c` and `ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))` for each changed/new Python file: all 22 files parsed. No modules were imported and no bytecode was written by this check.
- `git --no-optional-locks -c core.excludesFile= diff --check`: passed. A byte check of all changed/new Python files found LF endings and no CR bytes.

NOT RUN

- Per instruction, no pytest, numerical/image execution, browser test or full suite. The sandbox's lack of pytest/numpy/Pillow was not probed again.
- Please run the five new test files individually, using the test venv, `-p no:cacheprovider`, and a separate `--basetemp` under `%TEMP%`. The four files other than identity need the normal application/test dependencies. The draft-worker file launches isolated workers serially; it does not launch a browser.
- Existing builder numerical/print/composition/worker files, import registration/catalog/store/recovery/worker files, import-byte compatibility fixtures, and shape suites were not run here. In particular, real worker byte/picture parity, the six no-lint reference builds, live registration/restart, and import-byte compatibility remain outside-sandbox validation gates. The new tests are written; their passing status is not claimed.
- MB4b pictures, finish consumers, asset-card text, lint/performance fixture set; MB5 tools/gateways/anchor replacement; MB5b reference intake remain outside this phase.

DEVIATIONS

- The worker input gains the optional fixed `draft-request.json` rather than changing the default MB3 output contract or introducing another worker task. Draft rendering stays under the same single contained launch and limits.
- Include-bearing builder GLBs now contain `asset.extras.facilityBuildIncludes` and `facilityBuildAttribution`. C3 hashes the GLB, recipe and catalog semantics but does not separately hash persisted include frames/maps. Binding them to GLB bytes prevents an edited bundle manifest from substituting an anchor frame or part map while retaining the old identity. This changes include-bearing builder bytes from MB3; in-process and worker code use the same binding. Import writer output is not changed. The new bundle tests reject independently altered frames, keys, pins and credits.
- Identical portable builds preserve the first complete draft, including its creation/expiry and private reference list, instead of rewriting it with the second job's timestamps or references. This makes publication idempotent and preserves the immutable manifest. Reference-file intake and pin management are still MB5b.
- The build reservation is a conservative 160 MiB peak allowance covering copied includes/font and worker plus staged draft outputs. It shrinks after publication; it uses the existing shared quota and admission machinery rather than a separate builder quota.

OPEN QUESTIONS

- None for MB4a. The unrun application, numerical and real-worker tests above are the remaining validation work for your environment. No commits, installs, network calls or reads of the prohibited data/credential locations were made.

CLAUDE REVIEW AND VERIFICATION

This turn was cut off by the host for low memory just after this report was written (before the final reply); the
work on disk was complete. Run outside the sandbox with the test venv, one file at a time: identity 10, bundle 19,
draft_store 30, draft_worker 4, registration 19, build 35 (+12 added below), and every earlier builder file (prints
46, print_worker 8, print_contract 10, schema 12, shapes 43, protocol 13 + 1 skipped, worker 22, worker_boundary 10,
import_compat 20, composition 17, composition_contract 12, composition_host 29, composition_worker 12). Because the
store, registration, catalog and installer changed, every model_import file except the browser harness was run:
catalog 43, registration 24, store 40 (+1 skipped), lifecycle_fixes 24, prepare 21, inspection 14, preview 25,
worker 27 (+2 skipped), launch 13, runtime 9, reader 112, recipe 137, regressions 14, diagnostics 9, long_paths 4,
routes 10, sage_tools 41, chat_transport 62 (+1 skipped), sage_integration 7; shape_primitives 15, shape_families 15.
All pass. test_real_many_parts_prepare_is_bounded_and_can_be_paged hit model_timeout once; back to back it then
failed at c6f8128 (120 s) and passed here (39 s), so it is the memory-starved machine, not this change.

Two fixes:
1. test_hung_model_registers_catalog_height_and_keeps_spatial_geometry compared host._asset_versions[...] with a
   definition; that map holds bound records, so the test now compares its ["definition"] (as
   test_model_import_catalog does).
2. A real bug the registration tests exposed (include rotated 25 degrees refused at install): build.py took the
   footprint from the float32 Part arrays, while the dimensions come from the float64 components, and
   private_catalog refuses a footprint point beyond width/2 or depth/2 by more than 1e-8. Any extreme coordinate
   float32 cannot hold rounds outward by up to ~3e-8: measured on the references, the baler (+2.6e-8), pack station
   (+2.2e-8) and roll cage (+1.2e-8) would all have been refused at install. The footprint now comes from the
   float64 components (excess 0 on all six). New test
   test_footprint_stays_inside_catalog_bounds_at_the_catalog_tolerance (six references x hull/box).

Reviewed authored_library's dispatch: a manifest without `kind` goes to the unchanged import validator and folder;
an explicit "import" kind is validated by the same validator with the kind removed; "build" goes to the separate
validator and folder; anything else is refused. No objection to the deviations (draft-request.json in the same
worker launch, include frames and credit bound into the GLB extras, first identical draft kept, 160 MiB build
reservation).
