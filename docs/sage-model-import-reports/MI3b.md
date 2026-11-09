# MI3b - Sage model-import tools

## CHANGED

- ai_inspector/codex_runtime/model_import_tools.py (new): closed inspect/register inputs and the
  exact MI0b RECIPE_SCHEMA (deep-copied) for prepare. inspect_model_import lists recent site
  imports with no ID, or reads an import/draft with bounded paging. prepare_model_asset and
  register_model_asset delegate directly to the agreed agent_runtime hooks. The gateway principal
  and the gateway's bound reference are passed unchanged; no store, file, registration or placement
  work is performed by the tool adapter. Missing hooks fail closed.
- ai_inspector/codex_runtime/facility_tools.py: exposes inspection in the read inventory and read
  dispatch, supplies a fresh threading.Event per serialized model-import call, signals it before
  joining cancelled work, and clears late pictures. Model-import failures retain the host's
  bounded diagnostics (including recipe problems/closest and field paths). Existing error handling
  for other tools keeps its prior filtering.
- ai_inspector/codex_runtime/assisted_tools.py: exposes prepare/register in the edit inventory,
  dispatches them through the host, and explicitly shares the inspection path with the read gateway.
  Library registration does not create, replace or consume a layout proposal.
- ai_inspector/codex_runtime/progress.py: plain progress labels for the three tools.
- ai_inspector/codex_runtime/pilot.py: read-only inspection mention and the D7/section-3 playbook:
  inspect pictures, explain licence, state a real size, prepare, inspect/fix at most twice more,
  preserve credit, offer plain materials for visible slogans/marks/people, register to the shared
  library, and place only when asked. The initial edit restriction now explicitly says layout
  changes, consistent with direct library registration.
- tests/test_model_import_sage_tools.py (new): fake-hook unit contracts for both inventories,
  exact recipe schema, paging, scope/permission delegation, missing hooks, invalid inputs,
  PNG transport, clearing after failures/staleness, request/result limits, error paths, progress,
  instructions, fresh cancellation events and repeated asyncio/AnyIO cancellation with joined threads.
- tests/test_model_import_sage_integration.py (new): separate real-host gate suite on temporary roots:
  real HTTP upload -> worker -> inspect -> prepare -> register -> inspect_facility_asset ->
  existing placement proposal -> fresh host on the same roots; viewer denial, stale binding,
  cross-tenant/site IDs versus missing IDs, 3000 primitives x 12 copies with paging, and real
  gateway cancellation through the worker launcher with killed/joined process, released admission
  and import lock, and no published draft.
- Updated inventory assertions in tests/test_sage_shape_tools.py, tests/test_codex_mcp_pictures.py,
  tests/test_codex_assisted_tools.py, tests/test_codex_readonly_pilot.py and
  tests/test_codex_floor_plan_tools.py. Picture inventory checks include both new picture tools.
- docs/sage-model-import-reports/MI3b.md: this report.

No edits to server.py, static/, host.py, private_catalog.py, authored_library.py, the import store/routes/files,
the model_import package, or the concurrently built host registration adapter. Changes visible in those files
belong to the other builder. No commits, branches, index changes, network access or package installs.

## TESTS

- Attempted, using the hidden runner:
  C:/Python314/python.exe -B -m pytest tests/test_model_import_sage_tools.py
  tests/test_model_import_sage_integration.py -q -p no:cacheprovider --basetemp=C:/tmp/mi3b
- Result: exit 1, "No module named pytest". No tests collected or executed.
- Python syntax compilation of all 12 changed/new Python files: passed.
- Scoped git diff --check: passed.
- Byte checks: all MI3b files use LF, end with LF and contain no trailing whitespace.
  New source, tests and report are ASCII; server.py and its BOM were not edited.

## NOT RUN

- Both new pytest suites, the five updated inventory suites, and related cancellation/progress/transport
  regression suites need Claude's environment.
- Suggested combined check: the two new suites plus test_codex_readonly_pilot.py,
  test_codex_assisted_tools.py, test_codex_mcp_pictures.py, test_codex_floor_plan_tools.py,
  test_sage_shape_tools.py, test_codex_progress_steps.py and test_model_import_chat_transport.py.
- Browser/Electron, live provider inference and real downloaded models were not run.
- MI3a transport tests were not duplicated. Their existing suite covers attachment validation,
  non-facility refusal, request and memory hashes, all prompt branches, and registeredAssets.

## DEVIATIONS

- No functional deviations. Kept the tool adapter in a small new module.
- The prepare schema is imported unchanged from MI0b; no second recipe definition or host-side
  source parser was introduced. The inspect offset cap is 100000, above the maximum possible
  primitive-instance count under the import/copy limits.
- The 48 KiB summary limit uses the same compact JSON accounting as the host/worker.
  The existing gateway separately checks the complete JSON result against 64 KiB, and the MCP
  manager still caps the complete request envelope at 32768 bytes. Tool arguments also have
  a defensive 32 KiB check for direct gateway callers. PNGs are separate MCP image content
  with a 1.5 MiB byte cap; no image decoding occurs in the tool adapter.
- The cancellation integration test replaces only the worker entry point with a temporary sleeping
  script after a real upload. It uses the real host, store, subprocess launcher and process-tree cleanup,
  allowing cancellation to be observed deterministically. Other integration cases use the actual
  reader, prepare worker, preview renderer and catalog publication.

## OPEN QUESTIONS / HANDOFF

No blocking contract questions. Runtime calls match Claude's shared contract exactly:

- model_import_inspect(principal, reference, import_id=..., draft_id=..., offset=..., limit=...)
- model_import_prepare(principal, reference, recipe, cancel)
- model_import_register(principal, reference, draft_id)

Host hooks remain responsible for checking permissions/scope/revision, ending the worker, releasing the
admission reservation and import lock, and publishing no draft after cancellation. The gateway sets the event
and waits for the hook thread to finish before releasing its lock; it neither abandons the thread nor publishes
late JSON/pictures. Registration has no cancellation parameter in the shared contract and is joined if already
running, with catalog reconciliation/MI4 refresh handling a publication that completed during interruption.

The integration suite deliberately does not skip missing hooks or unavailable workers. Claude should run it
after both builders finish; dependency/resource-limit failures should remain visible. Its temporary-store
dependency root is taken from the installed numpy package, following the existing worker tests.
