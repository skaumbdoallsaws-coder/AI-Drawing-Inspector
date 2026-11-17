CHANGED

MB2 is implemented. Dependency-free checks pass here. Pixel rendering, numerical
geometry, six-reference zero-lint builds and real-worker byte parity are written
tests, not verified runtime outcomes in this sandbox. Per the user's latest
instruction, pytest was not attempted.

- ai_inspector/industrial_assets/model_builder/prints.py: Pillow rendering of
  text, rect, line, circle, decorative barcode, stripes and dots. Text fits its
  explicit one-to-three lines, honors left/center/right alignment, and uses the
  pinned regular font plus round(0.04*size) stroke for bold. Every text draw is
  clipped to its box. PNGs are RGB with no metadata. Dot/stripe work is bounded
  by output pixels, not the number of physical repetitions. Font objects use a
  bounded cache and the BASIC layout engine.
- ai_inspector/industrial_assets/model_builder/print_contract.py: independent
  versioned SHA-256 barcode stream, physical item extents, and stdlib-only PNG
  validation (header, dimensions, allowed chunks, CRCs, exact bounded decoded
  scanline size). No Pillow or NumPy imports in the host result validator.
- ai_inspector/industrial_assets/model_builder/job_io.py: font_bytes reads and
  checks the package or job copy against the installed manifest, length and hash.
  No system-font lookup or fallback. The existing fixed job-directory checks stay.
- ai_inspector/industrial_assets/model_builder/adapt.py: ModelImage records and
  print texture references. Print fronts have facilityArtwork, neutral white RGB
  factors and clamp-to-edge textures; lit fronts share that image as their
  emissiveTexture with [lit, lit, lit]. Backing plates keep their color/back and
  remain non-emissive. Finish on a print material is still refused, with a second
  guard at the material adapter.
- ai_inspector/industrial_assets/model_builder/build.py, worker_task.py: render
  each print entry once, share its texture across copies, pass the worker's job
  fonts/ explicitly, retain per-entry PNG/metrics in BuildResult.prints, and emit
  print_small_text/print_clipped lints. Cap height is measured at each transformed
  copy's real size, including scatter jitter. Findings name the entry, copy and
  item index, capped at 20 per code. Removed the MB1a background-only warning.
- ai_inspector/industrial_assets/model_builder/schema.py, recipe.py: bounded
  print-coordinate overflow can reach print_clipped; invalid ranges still refuse.
  Coverage checks, the 24-item and three-line caps, and finish refusal remain.
- ai_inspector/industrial_assets/model_builder/protocol.py: bounded image records
  in result.json (entryId, dimensions, MIME type, bytes, hash), texture/material
  binding to the GLB, print-specific material rules and the new lint records.
  PNG bytes stay embedded in model.glb; no extra output files or base64 JSON.
- ai_inspector/industrial_assets/model_builder_runner.py: verify image bindings
  and bounded PNG data before application geometry verification. Malformed GLB
  parsing still becomes model_worker_failed with owned-output cleanup.
- ai_inspector/industrial_assets/model_builder/README.md: renderer conventions,
  font source, clipping and sampling rules, result protocol and preview seam.
- tests/test_model_builder_print_contract.py: small stdlib tests for font hashes,
  coverage, exact budget boundaries, barcode determinism, overflow, bounded PNGs,
  textured result/GLB binding and malformed artwork metadata.
- tests/test_model_builder_prints.py: pixel-property tests for every item kind,
  text bounds/alignment/bold, dimensions/aspect/colors, seed stability, clipping,
  transformed cap height, lint caps, artwork/emission, and reference text boxes.
  Asymmetric text and colored marks are sampled through the panel's UVs for all
  five facings under rotation, both mirrors, nested double mirrors and around.
- tests/test_model_builder_print_worker.py: same bytes twice and in a real worker,
  copied-font parity, print lint round trips, corrupt image/material refusal before
  geometry verification, and extended-reader artwork/emissive-texture retention.
- tests/test_model_builder_build.py, test_model_builder_protocol.py: replace MB1a
  placeholder expectations and add the image-list field to the wire fixture.
  The existing six-reference kernel and worker tests still require zero lints and
  worker/kernel byte equality. Reference recipes were not changed.

The existing mesh mirror correction (winding and U reversal) is reused. Proper
rotations carry the artwork with the panel. Shared model_import writer, reader,
preview shaders and import-task launch/decoding were not changed.

TESTS RUN

Each Python command was a separate, small, serial run, launched with redirected
pipes and windowsHide through
C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/pythonw.exe and
tools/run_hidden.pyw. No pytest, browser, worker subprocess test, whole suite,
network, installation, commit or prohibited data-file access was performed.

1. C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -m unittest tests.test_model_builder_print_contract -v

   PASS: 10 tests. The generated PNG and GLB metadata fixtures exercise only the
   wire validator; they are not substitutes for real Pillow rendering or geometry.

2. C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -m unittest tests.test_model_builder_protocol -v

   PASS: 14 tests run, 13 passed and 1 skipped because this host cannot create
   symlinks. Includes the existing bounded error, input, part-map and cleanup-
   completion-marker protocol checks.

3. C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -m unittest tests.test_model_builder_schema -v

   PASS: 12 tests, including all six normalized reference recipes, budgets,
   coverage/cmap, print forms, finish refusal and recipe request-size limits.

4. C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -c <ast.parse and LF-only check> <the 15 changed/new Python files above>

   PASS: syntax and LF checks, without importing numerical/image dependencies or
   writing bytecode. git diff --check also passes. README and this report use LF.

NOT RUN

- tests/test_model_builder_prints.py and test_model_builder_print_worker.py:
  NumPy/Pillow/pytest are unavailable in the sandbox; the user will run them.
- Numerical MB1a/MB1b regressions: test_model_builder_build.py, shapes,
  import_compat and worker. The six-reference zero-lint and worker-byte-parity
  acceptance gates remain pending after these changes, including the pack-station
  24-item screen/scale, baler labels, gaylord label and carrier tag.
- Existing model_import and shape suites, browser tests and resource-limit stress
  tests. Import-byte compatibility was not rerun here; its shared code is unchanged.
- Live 3D finish preservation and canonical-to-layout mirroring remain MB7 visual
  checks. Preview generation/publication remains MB4. prints.preview_model is
  supplied for MB4's full-brightness approximation of lit prints; the production
  GLB retains its physical emissive material.

DEVIATIONS

- Print drawing coordinates now permit -1..2, so modest overflow produces the
  requested print_clipped lint instead of a schema refusal. Larger values still
  refuse before rendering. Circle radius remains in (0,1] of panel width. This
  changes the MB1a schema's 0..1 coordinate bounds deliberately.
- The unspecified smallest text size is 4 pixels; the upper bound is 4096. Text
  that cannot fit at 4 pixels is clipped to its box and linted. Physical cap-height
  linting is independent of that raster-size minimum.
- Pixel dimensions retain MB1a's common-scale rounding and budget estimates.
  An arbitrary physical aspect cannot always be represented exactly by integer
  pixel dimensions under 1024; rounding is at most half a pixel per dimension.
  There is no square intermediate texture or resizing pass.
- result.json gains image manifests and two lint kinds. The full internal result
  cap stays 16 MiB; no image bytes are put in that JSON or a future MCP response.
- No reference recipe, font, geometry or plan text was changed. No disagreement
  with C43-C46 was found.

OPEN QUESTIONS

- No design decision blocks the next review. Runtime acceptance is pending the
  user's pixel, numerical, real-worker and regression tests outside the sandbox.

CLAUDE REVIEW AND VERIFICATION

Run outside the sandbox with the test venv, one file at a time (Pillow 12.0.0):
test_model_builder_prints 46 passed (45 + 1 added below), print_worker 8, print_contract 10, build 23, shapes 43,
schema 12, protocol 13 (+1 skipped, symlinks), worker 22, worker_boundary 10, import_compat 20. The six references
build with no lints, and worker bytes equal the in-process bytes. No model_import file changed.

Two fixes to text placement in prints.py, found by the pixel tests and by looking at the rendered references:
1. Alignment used Pillow's multiline_textbbox, which starts at the pen (x0 = 0) and ends at the advance, so it holds
   the ink but is not the ink. Left-aligned text sat 8 px in from its box edge and centred text was 2.5 px off. The
   ink is now measured once at the chosen size on a scratch mask no larger than that box, and alignment uses it.
   Centred and right lines give fractional boxes, which are widened to whole pixels first.
2. Auto-fit measured each string's own ink height, so on the pack-station screen "Accessory kit (4) x1" (brackets,
   a descender) came out about 20% smaller than the rows beside it. The height now fits a fixed reference line
   (LINE_REFERENCE, the tallest and deepest ASCII glyphs) for that number of lines, so rows of equal height get
   equal type whatever their letters; a line too wide for its box still shrinks. Ink can never leave its box.
   Width-limited signs are unchanged; height-limited text is a little smaller than before (the UPS tag cap height
   285 -> 247 px, the screen title 40 -> 27 px), which reads more like a real screen. New test:
   test_rows_of_equal_height_get_equal_type_size_whatever_their_letters. README updated.

Rendered and inspected: pack-station screen (24 items) and scale display, baler warning and use labels, gaylord
label, UPS tag. No objection to the deviations (overflow -1..2 reaching print_clipped, min size 4 px, pixel
rounding at most half a pixel).
