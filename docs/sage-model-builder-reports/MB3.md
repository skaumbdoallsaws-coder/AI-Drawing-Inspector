CHANGED

- Added `ai_inspector/industrial_assets/model_builder_host.py`. `IncludeCatalog(project_root)` uses the existing private catalog binder for revisions and the catalog record for the artifact, authorship, frame and attribution. It reads the artifact, never the overview, checks revision/hash pins, applies the licence and byte gates, and supports injected catalog providers for temporary fixtures. `inspect_model_include(request, catalog=...)` returns artifact selectors and pinned, byte-bounded pages.
- Added `model_builder/include_contract.py`: dependency-free scene inventory, component-key encoding (including sibling ordinals and long-path fallback), image-header allocation estimates, recolor planning, copied manifest/hash checks and aggregate preflight. No source arrays or images are decoded before the budgets pass. Includes now count as entries; triangle and primitive estimates count every expanded copy.
- Added `model_builder/composition.py`: private-package extended reader integration, canonical source transforms, preserved normals/materials/textures, ordered recolor rules, finish-group namespaces and include frames. Recolor selectors resolve before renaming. Artwork and textured parts cannot be recolored. Host catalog attribution travels through a nested composition as one credit.
- Updated `model_builder/adapt.py`, `build.py`, `scene.py`, `shapes.py`, `budgets.py`, `lints.py` and `errors.py` for included components, prefixed nodes, entry/copy maps, original-key-to-output-key maps, bounded refusals and `include_surfaces_dropped`. The old MB3-unavailable refusal is removed.
- Updated `model_builder/job_io.py`, `worker_task.py` and `model_builder_runner.py`. `write_job_inputs(..., include_catalog=...)` copies pinned artifacts into `includes/0.glb` through `includes/2.glb`, with `includes/manifest.json`. The worker checks hashes and preflights before loading numerical dependencies. The host fingerprints include inputs across the worker run, binds result metadata to those inputs, and still verifies the returned GLB. The existing launch, resource limits, cancellation and import-task handling are unchanged.
- Updated `model_builder/protocol.py` and `print_contract.py` for includes, attribution, copied-part maps, validated frames, included PNGs and multiple texture samplers/emissive maps. Primitive/material budget values are upper bounds where composition merges copies; actual emitted counts remain checked. The full result stays under the existing 16 MiB bound; inspection pages stay under 48 KiB.
- Updated `model_import/reader.py`, `materials.py` and `geometry.py` only in extended mode: images are normalized losslessly to metadata-free PNG, and node-derived names retain up to 512 characters. Legacy reader defaults retain the existing image conversion and name projection. The writer itself is unchanged in this phase.
- Added `tests/model_builder_composition_support.py`, `test_model_builder_composition_contract.py`, `test_model_builder_composition_host.py`, `test_model_builder_composition.py` and `test_model_builder_composition_worker.py`. Fixtures generate the pallet, cage, synthetic credited geometry and printed assets in temporary catalogs. The cage/tag template is filled from artifact inspection at test time, including the actual top-rail key. Tests cover pinning, licence authority and credit carry, paging, pre-decode budgets, recolor precedence, duplicate names, textures, finish groups, transforms, non-anchorable groups, real-worker parity and tampered inputs/results.
- Updated the obsolete include-refusal assertions in `test_model_builder_build.py`, `test_model_builder_schema.py`, `test_model_builder_protocol.py`, `test_model_builder_worker.py` and `test_model_builder_worker_boundary.py`. Undeclared/missing copied inputs still refuse.
- Added this report. No reference recipes, bulk binary fixtures, registration code, bundle format, Sage gateways or replacement tools were changed. No network, installs or commits.

TESTS RUN

Commands below used `C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe`, launched serially through the matching `pythonw.exe tools/run_hidden.pyw` with a hidden parent process. They are stdlib unittest runs, not pytest or numerical builds.

- `python.exe -B -m unittest tests.test_model_builder_composition_contract`: final run 12 passed. The first run had one test-fixture failure: a repeat count of 201 hit the schema limit before the intended primitive-budget check. The fixture now uses permitted nested repeat counts.
- `python.exe -B -m unittest tests.test_model_builder_schema`: 12 passed.
- `python.exe -B -m unittest tests.test_model_builder_protocol`: 13 passed, 1 skipped (host does not allow creating the test symlink). Rechecked after the final protocol changes.
- `python.exe -B -m unittest tests.test_model_builder_print_contract`: 10 passed. Rechecked after the final texture metadata changes.
- `python.exe -B -c 'import ast,sys; from pathlib import Path; [ast.parse(Path(p).read_text(encoding="utf-8-sig"), filename=p) for p in sys.argv[1:]]; print("AST parsed", len(sys.argv)-1, "files")'` with the 28 changed/new Python paths: parsed successfully without importing numpy/Pillow or writing bytecode.
- `git --no-optional-locks -c core.excludesFile= diff --check`: clean. Changed/new text files checked for LF endings.

NOT RUN

- No pytest attempted, as requested. No numerical renderer, real build worker, browser or whole-suite run was attempted in this sandbox. Passing stdlib checks do not establish geometry, image or worker parity.
- Outside-sandbox runs still needed, one file at a time: `tests/test_model_builder_composition.py`, `tests/test_model_builder_composition_host.py`, `tests/test_model_builder_composition_worker.py`, then the existing builder test files, especially `test_model_builder_build.py` (the six references must remain lint-free), `test_model_builder_import_compat.py` (legacy import byte comparison), and the worker/print-worker files.
- Existing import reader/prepare/inspection/worker/launch/runtime tests and shape primitives/families remain for the user's outside-sandbox regression run. No claim of unchanged import bytes or successful real-worker parity is based on this sandbox run.
- The actual private asset library and catalog were not read. All new fixture paths belong to temporary roots. Registration, bundle identity/credits and anchor replacement remain MB4/MB5 work.

DEVIATIONS

- Non-anchorable include records carry `frame: null`. A repeated assembly has multiple frames; a tilted assembly cannot be represented by yaw plus translation. Keeping a projected or first-copy frame would be misleading. Single, unscaled, unmirrored yaw-only includes carry `{yaw, translation}` in the final normalized model frame. MB4's validator must preserve this nullable contract and MB5 must require `anchorable: true`.
- The copied manifest adds a bounded `hasSurfaces` boolean so the worker can issue the required dropped-surfaces lint without receiving support-surface geometry or accessing the catalog. The manifest lives inside `includes/`, preserving the four top-level job-input names and empty includes directory for recipes without composition.
- Extended reader image normalization uses PNG to avoid JPEG artifacts in included printed faces. It retains the reader's supported 2048-pixel texture ceiling; authored print limits remain unchanged. Ordinary import mode retains its existing encoding path. Extended node names are bounded at 512 characters; a longer prefixed output name refuses instead of silently truncating identity. A namespaced finish group exceeding the existing 120-character viewer limit also refuses instead of merging or truncating groups.
- Enclosing scatter with nonzero sizeJitter refuses for an include, enforcing real size. Repeated, mirrored, around and tilted groups otherwise compose, with anchoring disabled as required. Input-byte quotas count copied include entries; geometry, material and pixel preflight estimates conservatively count pattern copies before merging.
- No disagreement with C43: heavy artifacts refuse at the byte or pre-decode geometry budget. No library model was substituted or silently simplified.

OPEN QUESTIONS

None blocking MB3. MB4 must persist and validate the carried catalog credit and include metadata when it adds installation; this phase intentionally does not open bundles or write catalog entries. The numerical and isolated-process acceptance checks above remain pending the outside-sandbox run.

CLAUDE REVIEW AND VERIFICATION

Run outside the sandbox with the test venv, one file at a time: composition_contract 12, composition_host 29,
composition 17, composition_worker 12, build 23, prints 46, print_worker 8, print_contract 10, schema 12, shapes 43,
protocol 13 (+1 skipped), worker 22, worker_boundary 10, import_compat 20 (import bytes unchanged). Because
reader.py, materials.py and geometry.py changed (extended mode only), every model_import test file except the
browser harness was run too: reader 112, inspection 14, prepare 21, preview 25, worker 27 (+2 skipped), launch 13,
runtime 9, catalog 43, diagnostics 9, lifecycle_fixes 24, long_paths 4, recipe 137, registration 24, regressions 14,
store 40 (+1 skipped), routes 10, sage_tools 41, sage_integration 7, chat_transport 62 (+1 skipped); shape_primitives
15 and shape_families 15. All pass. The legacy paths are unchanged by construction: the 512-character node names
and lossless PNG apply only with preserve_node_names / extended_materials, and Image.frombytes(mode) equals the old
"RGBA" whenever the old branch ran (alpha_used implies mode RGBA).

One recipe fix (mine, not the code's): the roll-cage tag template failed its zero-lint check with two
coplanar_overlap findings. The clips' back faces sat exactly on the tag plate's back face (both at the cage front,
facing the cage), which would flicker seen through the mesh. The clips now start 1 mm inside the plate: centre z
0.331 -> 0.3315, depth 0.012 -> 0.011 (front face unchanged at 0.337, size unchanged). Same change in the plan's
section 4 example (both plan copies).

Reviewed model_builder_host.py: the licence gate follows C9 (own only from host catalog data: source.kind
authored-primitive / basic shape / authored-recipe or buildProvenance, with no attribution; CC0 and one CC BY or CC
BY-SA credit allowed; NC, ND, unknown and conflicting evidence refused, naming the include). The catalog is read
twice and compared, so a change during a read refuses. Tests use temporary catalogs only. No objection to the
deviations (frame null when not anchorable, hasSurfaces in the copied manifest, lossless PNG for included textures,
size-jittered scatter refused around an include).

Open point for the user (not a code defect): under C9, a model the user imported from their own CAD library carries
no authorship evidence and is therefore "unknown", so it cannot be included. Composition works today with models
the builder made, basic shapes and correctly licensed imports.
