# Sage workspace install performance (Job 4)

Measured 2026-11-03 in the throwaway clone. Baseline is c476a2f; the three changed JavaScript modules are byte-identical at the starting HEAD fb59e2c. No browser, Electron, network, real plant, or private asset data was used.

## Result and measurement

The benchmark uses the real session, workspace, editor controller and SVG renderer with the workspace suite's in-memory DOM. A recording 3D sink receives the real controller handoff; it does not render models. The synthetic document contains 2,250 placements, 230 assets, 40 zones and 300 floor markings (6,785,380 JSON bytes). Each reported number is the median of three rounds after one warmup. Receipt transport is an immediate in-memory result; JSON parsing, network, browser layout/paint and real 3D work are excluded. Source wrappers time nested stages without adding production telemetry.

The initial untouched baseline run measured 2,246.6 ms for commit and 2,319.2 ms for Undo, both with five plan renders. Host timing varied substantially during the session. The table below uses the final paired before/after runs, not that early baseline divided by a later after value. Render and normalization counts remained stable.

| Flow | Baseline ms | Changed ms | Full SVG renders |
| --- | ---: | ---: | ---: |
| Direct commit | 642.6 | 365.2 | 5 -> 1 |
| Direct undo | 639.9 | 361.5 | 5 -> 1 |
| Review preview | 747.0 | 344.6 | 7 -> 1 |
| Review apply | 619.2 | 299.9 | 6 -> 1 |
| Review undoPreview | 739.5 | 372.1 | 7 -> 1 |
| Review undoApply | 595.2 | 294.2 | 6 -> 1 |

Direct commit/Undo improve about 43%; reviewed operations improve about 50-54% in this harness. These are not Factory 02 browser timings. The main session must measure that separately.

Exclusive stage times for direct operations (ms; nested work is excluded):

| Stage | Commit before | Commit after | Undo before | Undo after |
| --- | ---: | ---: | ---: | ---: |
| session.clone | 117.8 | 116.1 | 110.9 | 125.5 |
| session.getState | 0.5 | 0.5 | 0.3 | 0.3 |
| session.normalizeLayoutAlternative | 0.1 | 0.1 | 0.0 | 0.1 |
| session.installReceipt | 1.7 | 1.7 | 1.5 | 1.6 |
| workspace.clone | 47.4 | 76.4 | 58.8 | 68.8 |
| workspace._syncController | 25.0 | 26.8 | 27.5 | 27.3 |
| workspace._handleSessionState | 7.1 | 6.5 | 6.7 | 5.4 |
| editor.clone | 85.9 | 44.5 | 92.9 | 53.0 |
| editor.collectTopPlanGeometry | 46.7 | 8.1 | 41.9 | 7.8 |
| controller._notifyLayout | 11.7 | 29.7 | 12.8 | 29.4 |
| controller.setLayout | 2.6 | 0.3 | 3.1 | 0.3 |
| plan._render | 271.9 | 52.2 | 294.4 | 52.5 |

Inclusive stage times (ms; overlap with the preceding table, so do not add them):

| Stage | Commit before | Commit after | Undo before | Undo after |
| --- | ---: | ---: | ---: | ---: |
| session.busy.true | 195.3 | 70.8 | 193.6 | 67.1 |
| session.busy.false | 340.3 | 235.2 | 336.9 | 235.1 |
| session.normalizeLayoutAlternative | 23.7 | 17.8 | 11.0 | 25.4 |
| controller._notifyLayout | 125.4 | 57.4 | 128.3 | 57.5 |

The busy-false stage includes installing/rendering the result. Busy-on still performs the existing snapshot, status/control and event work, but zero plan renders. A busy-only failure recovery also performs zero plan renders. A direct install now collects plan geometry once instead of five times; reviewed preview/Apply collect it once instead of nine/eight times. Initial operation preview normalization is once instead of twice; independently fetched approval previews still validate anew. Workspace catalog normalization occurs at mount, not during these measured installs.

## Exact path

- static/index.html: the operation-proposal tool handoff calls session.fetchAndInstallOperationProposal with the server reference and Apply Directly mode.
- static/facility_layout_session.js: fetchOperationProposal sets busy synchronously, fetches/normalizes the authoritative preview, and either exposes a review or calls applyDirectOperationProposal. The direct path approves, applies, then installReceipt resets the saved base/draft and preserves valid selection. The finally block clears busy and broadcasts the new snapshot. Reviewed Apply uses approveAndApplyLayoutProposal. Saved-operation Undo goes through requestOperationUndoPreview and the same direct/review path; local draft Undo/Redo use the existing history cursor and preview flow.
- Workspace._handleSessionState updates state and controls, then _syncController batches the plan environment, document, proposal, selection and ghost updates. Controller._notifyLayout hands a separate document copy to the 3D adapter exactly as before. The final SVG is ready synchronously before structure and workspace state observers run.

## Changes and safety boundaries

- static/facility_layout_editor.js: nestable synchronous plan transactions; unchanged selection/ghost setters skip rendering; fit and render reuse geometry within that transaction only. Each new layout copy invalidates the geometry identity, and the cache is discarded at transaction end. The built-in plan adapter makes its own defensive copy, removing the preceding redundant copy; custom adapters and overrides keep their input-copy boundary. The controller can omit an unused return-state snapshot when requested by the workspace. Default public return behavior stays intact.
- static/facility_layout_workspace.js: one transaction around environment/document/proposal/selection/ghost installation, with try/finally flushing. Requests no return-state clone from controller.setLayout. Session busy values, guards, history and broadcasts are untouched.
- static/facility_layout_session.js: reuses the alternative already normalized from the same receipt, only within the initial fetch/install. Top-level binding validation still runs. No revision-only or long-lived cache can suppress a later changed receipt.
- static/index.html: bumps all three changed static script version tags; added text is ASCII.
- tests/facility_workspace_install_harness.js: synthetic plant, real runtime loader, pinned baseline loader, stage profiler, DOM and recording sink. Windows subprocesses use pythonw.exe and tools/run_hidden.pyw with windowsHide; no shell windows.
- tests/benchmark_facility_workspace_install.js: direct and reviewed workflows with before/after stage measurements.
- tests/test_facility_workspace_install.js: exact baseline comparison for direct/reviewed commit+Undo, local history Undo/Redo, changed environment, selection removal, and ghost clearing. Compares full document/state/revisions, selection, history/cursor/dirty/save flags, SVG tree, 3D inputs and selection calls, command states, workspace state events and structure events. Full-scale direct commit+Undo compares SHA-256 of every snapshot field/event to keep memory bounded. Only the deliberately reduced renderCount diagnostics are excluded. Also checks synchronous busy guards/status, zero-render busy/error transitions (including visible ghosts), nested transactions, selection ordering, and independent document ownership.

No 3D adapter source or tests were edited. Defensive session and observer snapshots remain; removing those would change ownership guarantees. No revision-only shortcuts, persistent placement caches, session event coalescing or async frame scheduling were introduced.

## Reproduce and verification

Run from the repo root, using the existing hidden command launcher on Windows:

- node tests/benchmark_facility_workspace_install.js
- node tests/benchmark_facility_workspace_install.js --review
- node tests/test_facility_workspace_install.js

Passing suites:

| Command | Result |
| --- | --- |
| node tests/test_facility_workspace_install.js | 9 scenario checks |
| node tests/test_facility_layout_workspace.js | 110/110 |
| node tests/test_facility_layout_editor.js | 47/47 |
| node tests/test_facility_layout_three_adapter.js | 162/162 (existing material-map warnings) |
| node tests/test_facility_light_pools.js | 14/14 |
| node tests/test_facility_layout_session.js | 65/65 |
| node tests/test_codex_facility_operation_preview.js | 48/48 node:test cases |
| node tests/test_facility_targeted_operation_session.js | 20/20 node:test cases |
| node tests/test_facility_layout_p11_contracts.js | 8/8 |
| node tests/test_facility_layout_app.js | 6/6 |
| node tests/test_facility_layout_command_adapter.js | 8/8 |

Additional attempted checks:

- node tests/test_chat_stream_frontend_contract.js: 20 passes and TWO printed failures, reproduced with unchanged HEAD index.html/workspace sources. Its summary says "1 failed" because it prints process.exitCode rather than a failure count. Existing failures are the provider-error recovery wording and non-replayable retry guard.
- node tests/test_facility_layout_construction_kernel.js: blocked before exercising the kernel because fastapi is missing. Retried via .night-tmp/run-install-check.cjs construction with CONSTRUCTION_TEST_PYTHON set to the prescribed InspectorPro-CopilotTest venv, PYTHONPATH/PYTHONHOME removed, and hidden Python subprocesses; same missing dependency. No installs attempted.
- git diff --check: clean.

Not verified: live Factory 02 browser timing/paint, real 3D timing within this harness, Electron, and the Python-backed construction integration. The required standalone 3D suite passed. Changes remain uncommitted.
