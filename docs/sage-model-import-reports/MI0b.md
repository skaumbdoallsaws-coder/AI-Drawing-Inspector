# MI0b builder report

CHANGED

- Fixed all three MI0a review findings first:
  - licence.py keeps repeated assertions, classifies labels and URLs independently
    before display truncation, and retains bounded contradictory evidence with
    class unknown. Distinct asserted versions and unknown licence labels are
    also detected; equivalent CC spellings do not create false conflicts.
  - validation.py and summary.py normalize after character/byte truncation,
    including excerpts and conflict values.
  - runner.py records output ownership. Async cancellation joins its worker
    thread and removes completed outputs when cancellation wins delivery,
    without deleting pre-existing files.
- Added recipe.py: closed Draft 2020-12 RECIPE_SCHEMA, semantic validation,
  canonical defaults, cleaned names, six-decimal numbers and bounded inputs.
- Added transforms.py and simple_parts.py: selectors with bounded closest-name
  diagnostics; exact D11 ordering; source-identity selectors across renames;
  material patches; copies; boxes, cylinders and hollow/solid frustums.
- Added footprint.py: conservative whole-model hulls, outward simplification,
  bounding rectangles, and explicit support surfaces in the catalog's exact
  origin/bounds shape.
- Added writer.py: deterministic textured GLB, one node per output part,
  reusable accessor/mesh data, authored finish/material-role extras, embedded
  PNG/JPEG, alpha/unlit/emission support and output byte/triangle limits.
- Added prepare.py, prepare_protocol.py and prepare_runner.py; extended
  worker.py, runner.py, job_io.py and errors.py. The limited worker supports
  prepare from source plus a verified MI0a cache, re-decodes original images
  after material changes, writes complete frozen outputs, and the host checks
  hashes/schema/caps before publication. Both sync and async APIs accept
  cancellation. Existing destinations are never replaced.
- Added identity.py and credit.py: complete D6 identity inputs, stable IDs,
  deterministic changes text and CREDITS.txt.
- Added tests/model_import_recipe_support.py,
  tests/test_model_import_regressions.py,
  tests/test_model_import_recipe.py and tests/test_model_import_prepare.py.
  Fixtures cover the six recipes, every recipe field, selector/order behavior,
  materials/textures, shapes, footprint overhangs, 36,000 output parts,
  catalog/verify/inspect_glb compatibility, identity, deterministic bytes,
  protocol corruption and publication/cancellation failures.
- Updated the package README with public interfaces, numerical caps, cache
  reuse, output formats, result paging and MI0c/MI1/MI2 integration notes.
- No changes to server.py, static/, codex_runtime/, facility_layout/, or other
  application behavior. No commits, branch operations or index changes.

TESTS

Attempted the complete model-import suite using the hidden Python launcher:

    python -B -m pytest tests/test_model_import_reader.py tests/test_model_import_worker.py tests/test_model_import_regressions.py tests/test_model_import_recipe.py tests/test_model_import_prepare.py -q -p no:cacheprovider --basetemp=<temporary MI0b directory>/pt

Result: exit 1 before collection: No module named pytest. The available
Python 3.14 and Python 3.11 interpreters both lack numpy, Pillow, pytest and
jsonschema in this sandbox. No installation was attempted.

Checks actually executed successfully using the standard library:

- Compiled all 35 package/test Python modules; checked LF line endings.
- Audited package AST imports: standard library, numpy, Pillow or relative
  imports only; no socket/http/urllib imports.
- Seven licence regression probes, all text truncation boundary probes,
  canonical recipe/default checks and invalid recipe contract probes.
- Full draft scalar schema validation and identity changes for every recipe
  field, every D6 semantic field, engine, source and output hash; artifact
  path/assetId exclusion.
- Two real subprocess timeout/kill/join probes (inspect and prepare).
- Late async cancellation probes for successful inspect output, pre-existing
  inspect output, and a completed published draft. Rechecked inspect probes
  after replacing shielded-result delivery with cancellation-safe asyncio.wait;
  no unhandled worker exceptions remained.
- Real prepare worker startup with an empty dependency directory: expected
  model_runtime_unavailable, with no published draft or retained job.
- git diff --check passed.

NOT RUN

- Pytest collected zero tests here. No numerical transform, image decode,
  generated GLB, six-recipe, many-part, real successful prepare worker,
  jsonschema parity or host catalog/verify/inspect_glb test was executed here.
  Claude must run the command above in the real environment before accepting.
- The approximately 60-second full-suite target is unmeasured here.
- No private downloads, network, browser, preview or live app checks.
- No POSIX resource-limit run on this Windows host.

DEVIATIONS / IMPLEMENTATION CHOICES

- No scope expansion beyond the requested MI0a fixes and MI0b.
- The package remains stdlib/numpy/Pillow only. Its bounded schema validator
  implements the keywords used by RECIPE_SCHEMA; jsonschema is used only in
  tests for parity, not as a worker dependency.
- Category is a bounded open string because the real catalog binder has no
  category enum. Unspecified numerical ceilings are documented in the README.
- The public prepare result is <=48 KiB; full draft.json is separately capped
  at 128 KiB to retain the normalized recipe. A <=32 MiB parts.jsonl ledger
  retains all part records for future paging; manifest.json hashes fixed
  output files. Very long escaped names may reduce the public prefix below
  64 while keeping nextPartsOffset and the complete ledger.
- More than 64 authored material roles may be needed for output parts with
  distinct names. The source reader retains its 64-material input limit;
  the public material list is capped at 64 with materialsTotal.
- Unused vertex rows are discarded before transforms/copies. They do not
  contribute to an authored solid's dimensions or footprint.
- The synchronous convenience runner accepts optional trusted dependency_root
  and cache_dir parameters. A sibling exclusive prepare lock coordinates
  publication; crash/stale-lock recovery, quotas and scope remain MI1.
- ModelImportError remains the independent package boundary; MI1 will translate
  it to FacilityLayoutError, avoiding an application import in the worker.

OPEN QUESTIONS

None requiring a design decision. Acceptance remains pending Claude's full
test run and review in the real dependency environment.
