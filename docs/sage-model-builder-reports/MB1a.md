CHANGED

MB1a implementation and tests are written. Geometry acceptance and import-byte
compatibility are NOT yet verified: the specified Python runtime cannot import
pytest, numpy, or PIL in this sandbox.

- ai_inspector/industrial_assets/model_builder/
  - __init__.py, errors.py: private-package entry point and bounded builder
    refusals with codes and JSON paths.
  - schema.py, recipe.py, budgets.py: closed dependency-free schema, canonical
    defaults, globally unique IDs, category/finish allowlists, print validation,
    include pins/selectors, provenance separation, and pre-expansion budgets.
  - shapes.py, scene.py: all eight shapes, closed caps and miters, panel backing
    and UV quad, nested transforms, repeat/grid/around/mirror/scatter, and
    deterministic SHA-256-based scatter with size jitter.
  - adapt.py, imports.py: adjacent private model_import bootstrap, Model/Part
    adapter, per-name/per-material merging, and entry/copy-to-component-key maps.
    Group instance prefixes are mapped too. Long encoded names use the app's
    512-character node-index fallback.
  - build.py, lints.py: in-memory build result, normalization and reported shift,
    hangHeight, geometry versus catalog dimensions, transformed support
    rectangles, footprint, authored/default finishes, and the requested
    picture-independent lints.
  - README.md: kernel API, frame/material contracts, limitations, and MB1b seam.
- ai_inspector/industrial_assets/model_import/
  - writer.py: generator, grouped, extended_materials options; legacy defaults
    retained. Grouped output emits one node per name and primitives per material.
  - reader.py, materials.py, geometry.py, extended_materials.py: opt-in default
    finish adjustments, artwork, finish groups, emission textures, and node-name
    retention. Matching texture transforms are baked into UV0.
  - errors.py: gltf_texture_unsupported refusal for unsupported extended UV
    combinations; default import reading keeps its previous projection.
- ai_inspector/industrial_assets/primitives.py: verify(..., base_height=0).
  Its dimensions argument continues to mean geometry size, excluding base height.
- tests/model_builder_test_support.py and tests/test_model_builder_schema.py,
  test_model_builder_shapes.py, test_model_builder_build.py,
  test_model_builder_import_compat.py: validation/budgets, all shapes, closure and
  signed volume, winding, exact counts, transforms, patterns, deterministic GLB
  bytes including a second isolated process, component maps, finishes, hangHeight,
  lints/caps/performance, six reference builds, and opt-in/legacy import behavior.
- tests/fixtures/model_builder/import_writer_567f22a.py: exact original writer
  snapshot, SHA-256 cc7fc6d3fc8815609c020ef688077ad0018ae577d7867f6caeb156b6a47cc57d.
  Compatibility tests pass the six existing generated import fixtures and a
  textured duplicate-name fixture through inspect/prepare twice, comparing all
  published bytes with this original writer.
- docs/sage-model-builder-reference/recipes/carrier-tag-ups.json: added the
  missing named carrier tag plate; details below.

TESTS RUN

All Python commands were launched with redirected pipes and windowsHide through
C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/pythonw.exe and
tools/run_hidden.pyw. Only one Python test process ran at a time. No browser,
network, install, commit, or prohibited data-file access was performed.

1. C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -m unittest tests.test_model_builder_schema -v

   PASS: 12 tests. Covers all six supplied recipes, normalized JSON-RPC tools/call
   envelope limits, the composition template after synthetic pins, defaults,
   malformed inputs, schema and aggregate budgets, finish allowlists, print
   discriminators/glyphs, provenance separation, and the actual bundled font
   SHA-256/cmap. This is stdlib unittest execution, not a pytest result.

2. Requested pytest invocation:

       C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -m pytest -p no:cacheprovider --basetemp=C:/Users/might/AppData/Local/Temp/inspectorpro-mb1a-pytest tests/test_model_builder_schema.py tests/test_model_builder_shapes.py tests/test_model_builder_build.py tests/test_model_builder_import_compat.py tests/test_model_import_reader.py tests/test_model_import_prepare.py tests/test_model_import_inspection.py tests/test_shape_primitives.py tests/test_shape_families.py

   BLOCKED before collection, exit 1: No module named pytest. An earlier attempt
   with only tests/test_shape_primitives.py failed for the same reason.
   Import discovery also returned no numpy or PIL in this interpreter. A direct
   private-package build smoke attempt failed at import numpy, before any model
   was built. No geometry-test or existing-suite pass is claimed.

3. python.exe -B -c (in-memory ast.parse over the 24 changed/new Python source,
   support, test, and frozen-writer files): PASS. All 24 parsed. A separate byte
   check of those files plus the package README and edited recipe found LF only.
   No bytecode compilation or generated model files were written.

4. git --no-optional-locks -c core.excludesFile= diff --check: PASS.

5. Dependency-free reference normalization/preflight: PASS for all six recipes.
   Estimated triangle counts (not generated-GLB measurements):
   baler 1144; gaylord including pallet 650; pack station 1064; corrected tag 50;
   plain pallet 240; plain roll cage 988. All are within kernel budgets.
   An independent scalar check of the gaylord's 16 seeded box scatters found no
   oversized rotated/jittered copy for its supplied container.

NOT RUN

- The three numpy/Pillow-dependent new pytest files and all five requested
  existing files: no pytest/numpy/Pillow available in the specified interpreter.
  The schema file ran through unittest only.
- Consequently, actual reference GLBs, primitives.verify on them, per-shape mesh
  assertions, same-process/cross-process GLB determinism, performance ceilings,
  previews, and import-byte comparisons have not been executed here. These tests
  must pass before treating MB1a runtime acceptance as complete.
- No full model_import suite, browser harness, application/Electron suite, or
  live Sage evaluation. The supplied MB0 baseline was read, not rerun.
- Worker task/error transport (MB1b), raster artwork (MB2), include execution
  (MB3), catalog/store/registration and frontend finish precedence (later phases).

DEVIATIONS

- The carrier-tag recipe was schema-valid but had only two functional names;
  baseline-stats.json requires carrier tag plate, carrier tag print, and carrier
  tag clips. Added a 2 mm box behind the panel's automatic backing. The two
  backings touch, with no coincident same-facing face; outer dimensions and
  hangHeight remain the supplied values. Its estimated triangle count is now 50
  versus the original 38. The baseline statistics and historical envelope
  measurements were not rewritten.
- Extended material reading refuses nonzero/missing UV0 or differing base and
  emission texture transforms with gltf_texture_unsupported. Part has one UV
  array; accepting these cases would silently lose their intended appearance.
  These restrictions apply only to the opt-in mode.
- Contact diagnostics cap work at 100,000 candidate pairs and 20 findings per
  code. On truncation they return an explicit incomplete-analysis warning and
  suppress floating-part claims. This bounds dense 3,000-component cases without
  manufacturing false floating results.
- Surface heights may be negative in the recipe frame, then must lie within the
  final model after normalization. This follows C45's recipe-frame contract.
  fitsWithin.height is checked against floor-to-top height for hung builds;
  size.height remains the geometry's own height.
- No disagreement with C43-C46. The private TR1631 artifact was not read or
  recounted; the supplied C43 measurements exceed the implemented limits.
  C44's later host must verify using own geometry dimensions plus base_height,
  then register catalog_dimensions, whose height includes hangHeight.

OPEN QUESTIONS

- No kernel design decision is needed before running the pending tests.
- Later E1/C42 triangle scoring needs attention: the gaylord body's estimate is
  410 triangles after excluding its 240-triangle plain pallet, versus 318 in the
  original body, or +28.9%. Closed thin-box straps/lips and the backing plate
  account for the increase. The supplied geometry was retained, as this turn's
  reference acceptance requests bounds and functional names. Before E1 is
  scored, decide whether to simplify that body or amend its 25% triangle
  allowance. This estimate still needs confirmation from the generated GLB.

CLAUDE REVIEW AND VERIFICATION (2026-11-16, outside the sandbox, test venv)

- New tests: test_model_builder_schema 12 passed (54 subtests), _shapes 43 passed, _build 23 passed,
  _import_compat 20 passed (the frozen 567f22a writer gives byte-identical import output).
- Existing suites, one file at a time (browser harness skipped, machine low on memory): every
  tests/test_model_import_*.py file, test_shape_primitives.py and test_shape_families.py pass. One timing test
  (test_model_import_preview.py::test_full_contact_sheet_timing[50-50-2]) failed once under memory pressure and
  passed on two reruns; preview.py is unchanged.
- Code review: the shared reader/writer/materials/geometry changes are opt-in only (defaults unchanged, pinned by
  the compatibility tests); primitives.verify base_height defaults to 0. Transform order, pattern copies, around
  spacing and the SHA-256 scatter stream follow C10 and C45. No objection to the deviations (tag plate box, opt-in UV
  refusals, bounded contact lint, surface heights).
- Pictures: the six references built and rendered with the model-import contact sheet; all look as intended.
- The lints found real flaws in Claude's recipes (several were in the hand-built originals too): the baler power
  pack shared its +x face with the body (visible flicker), corner posts and body bottoms coplanar, the door handle
  floating 8 mm in front of the bars; gaylord wall tops coplanar with the lips; pack-station shelves flush with legs
  and uprights; tag clips flush with the plate; four pallet deck boards with nothing under them (a real pallet has
  stringer boards). All fixed in the recipes; the pallet gained three stringer boards (23 pallet components, test
  updated). The reference test now also requires the six references to build with no lints at all.
- Plan C42: pallet spec gains the stringers; the gaylord body triangle allowance is +-35% (closed boxes).
