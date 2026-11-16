CHANGED

MB1b is implemented. The dependency-free schema/protocol checks and real isolated
process refusal/containment checks pass here. Numerical worker success, GLB byte
parity, host geometry verification, and the existing pytest worker suite still
need the user's test environment: the specified interpreter cannot import
pytest, numpy, or PIL in this sandbox.

- ai_inspector/industrial_assets/model_import/worker.py: third task "build".
  Resource limits precede both private package bootstraps. Only build loads
  _model_builder_worker; its shared imports use _model_import_worker. Inspect
  and prepare retain their original task imports and execution paths. Builder
  refusals are written as bounded error.json with exit code 2.
- ai_inspector/industrial_assets/model_import/runner.py: optional build error
  decoder on _launch, used only for task "build". Legacy import decoding is
  unchanged. The same process launcher, restricted environment, -I -S -B,
  containment, CPU 60 s, wall 70 s and 1.5 GiB limits apply.
- ai_inspector/industrial_assets/model_builder/errors.py, budgets.py: strict
  refusal serialization/decoding, fixed known messages, bounded JSON path and
  problem, duplicate-key/non-finite JSON rejection, and an 8 KiB envelope limit
  including escaped Unicode. Triangle refusals report the estimated count and
  limit=60000; the exact 60001 case reports $.entries[2].
- ai_inspector/industrial_assets/model_builder/job_io.py: fixed local input
  contract, normalized recipe, bounded category/appearance allowlists, safe
  regular files/directories and bounded directory enumeration. Inputs are
  recipe.json, allowed.json, fonts/ and an empty includes/; no source.bin.
  Fonts contains fonts.json and the named regular font. Both the manifest and
  copied font are checked against the installed package manifest and its SHA-256.
  Replacing both job copies cannot replace that trust anchor. Includes return
  composition_unavailable until MB3.
- ai_inspector/industrial_assets/model_builder/protocol.py: full bounded result
  with geometry/catalog dimensions, shift, triangles, parts, complete entry/copy
  maps, materials, support surfaces, footprint, lints, warnings, budgets and
  provenance. Input/output hashes bind the result to the job and GLB. The host
  validates scalar limits, counts, maps and GLB node/material metadata. Footprint
  bounds allow float32 rounding at the kernel's coordinate cap; no kernel or
  import geometry bytes change.
- ai_inspector/industrial_assets/model_builder/worker_task.py: validate inputs
  before loading numerical dependencies, refuse includes, build, check that no
  ai_inspector parent was loaded, then exclusively write model.glb and result.json
  with result.json last. No pictures or draft publication.
- ai_inspector/industrial_assets/model_builder_runner.py: host-only
  write_job_inputs, run_build and run_build_async. The host copies the font,
  reuses _launch, checks unchanged inputs and output hashes, and requires
  primitives.verify(glb, dimensions, base_height=hangHeight) before returning.
  Failure/cancellation joins the process and cleans only its admitted job's
  outputs. Existing outputs are refused before ownership and preserved; late
  async cancellation also cleans a completed but undelivered result.
- ai_inspector/industrial_assets/model_builder/README.md and build.py: document
  the kernel/worker/host boundary and the job/refusal/result contracts.
- tests/test_model_builder_protocol.py: stdlib tests of job inputs, pinned fonts,
  refusal limits, result schemas/maps/hashes, material binding and unsafe paths.
- tests/test_model_builder_worker_boundary.py: real isolated worker refusals,
  private-package startup, environment isolation, fail-closed limits,
  cancellation/timeout termination, malformed refusal rejection, and unchanged
  import decoding (including its 250000-triangle diagnostic).
- tests/test_model_builder_worker.py: numerical worker/host integration tests
  for all six reference recipes, exact kernel/worker GLB parity, zero reference
  lints, hangHeight verification, decoded refusals, failed output verification,
  tampering, input preservation and synchronous/asynchronous cancellation cleanup.

TESTS RUN

Python commands were launched with redirected pipes and windowsHide through
C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/pythonw.exe and
tools/run_hidden.pyw. Tests ran serially. No browser, network, install, commit,
or prohibited data-file access was performed.

1. C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -m unittest tests.test_model_builder_schema tests.test_model_builder_protocol tests.test_model_builder_worker_boundary -v

   PASS: unittest ran 36 tests; 35 passed and 1 skipped (symlink creation is not
   permitted here). This includes 12 existing schema tests and 24 new tests.
   Real worker processes returned the schema, 60001-triangle, include and font
   refusals; real child processes were joined after cancellation and timeout.
   The isolation probe records interpreter/module state and then deliberately
   raises ImportError; it is not a substitute for a successful geometry build.

2. C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -m pytest -p no:cacheprovider --basetemp=C:/Users/might/AppData/Local/Temp/inspectorpro-mb1b-pytest tests/test_model_builder_worker.py

   BLOCKED before collection, exit 1: No module named pytest.

3. C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -m pytest -p no:cacheprovider --basetemp=C:/Users/might/AppData/Local/Temp/inspectorpro-mb1b-worker-pytest tests/test_model_import_worker.py

   BLOCKED before collection, exit 1: No module named pytest.

4. C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -B -c <ast.parse and LF-only check> <the 12 changed/new Python files listed above>

   PASS: all 12 parse without writing bytecode and contain no CR line endings.
   git diff --check also passes. The README and this report use LF endings.

NOT RUN

- tests/test_model_builder_worker.py and tests/test_model_import_worker.py under
  pytest: blocked as above. NumPy/Pillow are also unavailable in this interpreter.
  In particular, six-reference byte parity, successful host primitives.verify,
  numerical result acceptance, tampered-output rejection and host async cleanup
  are written tests, not verified runtime outcomes in this sandbox.
- Existing import prepare/reader/inspection, byte-compatibility and shape suites:
  not rerun. The MB1a review records their passing baseline. The shared writer,
  reader, geometry and primitive verifier were not changed in MB1b.
- Native CPU/memory exhaustion stress tests and the full 70-second wall delay:
  not run on this low-memory machine. Limit setup is unchanged; the available
  tests cover failure before bootstrap and real termination at a short deadline.
- Browser tests, full suites, previews, MB2 prints, MB3 composition and MB4
  publication are outside this turn.

DEVIATIONS

- The host runner is deliberately outside model_builder, so importing application
  primitives for verification cannot violate the private worker package boundary.
  The worker package itself still imports only its permitted dependencies.
- result.json is capped at 16 MiB rather than the later 48 KiB MCP response size.
  It retains the complete map for up to 3000 expanded components and four instance
  prefixes per component, including long encoded part keys. The later MCP summary
  must remain separately bounded. model.glb is capped at 30 MiB; error.json at
  8 KiB; allowed.json at 256 KiB; recipe.json retains its 24 KiB kernel limit.
- recipeSha256 in this internal result binds the full normalized input, including
  site-private metadata. It is not the portable-recipe asset identity specified
  for MB4. No asset identity, shared bundle or durable draft is created here.
- Dependency-free tests use stdlib unittest because pytest is unavailable. Their
  real subprocess results are reported separately from pending numerical tests.

OPEN QUESTIONS

- No design decision is needed before the user runs the pending numerical and
  import worker tests. MB1b runtime acceptance remains pending those results.

CLAUDE REVIEW AND VERIFICATION (2026-11-16, outside the sandbox, test venv, one file at a time)

- New: test_model_builder_protocol 13 passed + 1 skipped (31 subtests), _worker_boundary 10 passed (9 subtests),
  _worker 22 passed (six references through the real worker: GLB bytes equal the in-process build, zero lints,
  host primitives.verify with base_height, refusals decoded, tampering refused, cancellation cleanup).
- Existing: test_model_import_worker 27 passed + 2 skipped, _launch 13 passed, _runtime 9 passed; the MB1a builder
  files (schema 12, shapes 43, build 23, import_compat 20) still pass.
- Code review: build-error decoding is reached only for task "build"; import decoding unchanged; the worker loads
  _model_builder_worker only for build; the host runner deletes only the job's own output names. No objection to the
  deviations (runner outside the private package; 16 MiB internal result; internal recipeSha256 is not the MB4
  asset identity).
