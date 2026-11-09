# MI0a implementation report

CHANGED

- Added ai_inspector/industrial_assets/model_import/ as a self-contained package.
  containers.py validates GLB chunks and virtual zip resources without extracting
  files. accessors.py and geometry.py validate buffers, indices, quantization and
  node graphs, budget instances before array reads, and flatten transformed parts.
- materials.py decodes allowed images sequentially, downsizes and re-encodes them,
  and projects the supported material extensions. licence.py preserves bounded
  attribution facts/conflicts. summary.py builds bounded, paged inspection JSON
  and unverified flat-top hints.
- worker.py sets resource limits before loading dependencies or source data.
  worker_task.py writes a versioned numeric NPZ/JSON cache and a final hash
  manifest. runner.py provides synchronous and asyncio entry points with a
  cancellation Event, 0.2-second polling, kill/join, exit-code mapping, and
  bounded/schema-checked results. job_io.py and protocol.py keep the host side
  independent of numpy/Pillow.
- README.md documents entry points, fixed job files, cache version 1, budgets,
  texture-transform handling, and the MI0b/MI1 integration boundaries.
- Added tests/model_import_test_support.py, tests/test_model_import_reader.py and
  tests/test_model_import_worker.py. Fixtures are generated in code; tests cover
  valid models, the MI0a hostile cases, cache integrity, startup isolation,
  resource limits, timeout and cancellation. No binary fixtures were added.
- No existing application source, server.py, static/, codex_runtime/ or
  facility_layout/ files were changed. No branches, index changes or commits.

TESTS

- Attempted the requested suite with the installed Python 3.11 executable, through
  pythonw.exe and tools/run_hidden.pyw with redirected output and hidden windows:

      python -B -m pytest tests/test_model_import_reader.py tests/test_model_import_worker.py -q -p no:cacheprovider --basetemp=<temporary MI0a directory>

  Result: exit 1 before collection, "No module named pytest". Probes of the
  available Python 3.14 and 3.11 interpreters also could not import numpy/Pillow.
  No packages were installed.
- Compiled all 21 new Python source/test files using Python 3.11 compile() without
  writing bytecode: passed. AST import-boundary checks passed: package imports
  are standard library, numpy, Pillow or relative; no direct socket/http/urllib
  or other ai_inspector imports.
- Ran dependency-free boundary smoke checks: GLB container, unsafe zip paths,
  licence classes, real worker startup with missing dependencies, timeout and
  pre-cancellation: passed.
- Ran a real Windows worker with a synthetic host-owned dependency probe.
  QueryInformationJobObject confirmed the 60-second CPU limit, 1.5 GiB process
  memory limit, one-process limit and kill-on-close flags: passed.
- Ran real sleeping subprocesses through synchronous Event cancellation and
  asyncio task cancellation; both returned only after the child was joined.
  These checks passed. They validate supervision, not numerical model parsing.
- Checked all new package/test files for CR characters and trailing whitespace:
  none found.

NOT RUN

- The pytest suite collected zero tests because pytest is unavailable in the
  selected environment. Numerical parsing, Pillow decoding, cache round trips
  and the suite's total runtime remain unverified here. Claude should run both
  test files with the configured numpy/Pillow/pytest environment before accepting
  the phase.
- POSIX resource-limit tests were not run on this Windows host.
- No real Sketchfab downloads, browser/app checks, existing application suites,
  or later-phase acceptance tests were run. No prohibited data/configuration
  files or network resources were read.

DEVIATIONS

- The package exposes ModelImportError with code/message/status_code rather than
  importing FacilityLayoutError. MI1 must translate at its host boundary; directly
  importing the facility exception here would violate the self-contained package
  requirement.
- Chose a versioned JSON + uncompressed numeric NPZ cache, with explicit caps of
  16 MiB metadata and 384 MiB arrays/images. MI1 reservations must include these
  actual bounded outputs plus copied input, as section 10 requires.
- No scope deviation: prepared GLB writing, previews, persistent stores/routes,
  catalog registration, gateway wiring and frontend work remain in their phases.

OPEN QUESTIONS

- None for the implementation contract. Full test execution requires Claude's
  configured dependency environment; no installation or dependency substitution
  was attempted.
