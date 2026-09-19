# Desktop Workflow Connections

Date: 2026-09-16

## Scope

The ordinary `InspectorPro Desktop` shortcut runs `--application`, loading the
same `server.py` and frontend as the browser. It uses normal provider settings
and the original asset library. It does not use the restricted diagnostic
shell's endpoint allowlist or blanket input locks.

This change addresses native navigation and panel behavior and adds a native,
real-backend workflow check. It is not a claim that every business operation,
AI response, hardware integration, or unfinished web feature is complete.

## Changes

- `desktop/src/application-links.cjs` handles same-window and popup artifact
  navigation through authenticated native downloads. Previously, a manual's
  `location.assign(artifact.url)` could be prevented without downloading it.
  The editor and unsaved draft now remain mounted during that handoff.
- Root application links retain the existing guarded reload protocol and their
  target URL. External links retain confirmation. Executable schemes,
  credentialed URLs and foreign blob URLs are refused. Backend credentials
  are not exposed to the renderer or external sites.
- `static/index.html` restores the part/upload panel when leaving the
  desktop's initial Facility Layout view. This only reverses the shell's own
  startup collapse; subsequent user panel choices and browser behavior are
  preserved.
- `--workflow-acceptance-output` explicitly selects the native workflow test
  driver. It is unavailable in restricted managed mode and mutually exclusive
  with other acceptance modes. Normal launch does not run the driver.
- `prepare-application-check.py --include-documents` prepares isolated copies
  of the manual layout and four existing MMLE-50D document sets, with source
  hashes. Test failures retain their reports and screenshots.

## Coverage

The native check exercises these entry points using real Electron input and
the protected application backend:

| Area | Check |
| --- | --- |
| Facility Layout | Original reference identity, 827 placements, 45 zones, library toggle |
| Drawing | Upload/part panel visible; file-input/FileReader/image-render path |
| 3D Model and Assembly | MMLE-50D GLB mounted, loader gone, actual asset meshes present |
| Report, Usage, Sessions | Shared views mounted; session list loaded |
| DFM | Navigation only; shared web viewport is currently empty |
| Plant Process | Workflow selected and its viewport mounted |
| Process Map | Editor mounted with nodes queried through its schema-aware API |
| Service, Maintenance, Troubleshooting, Operator | Workflow and shared assembly viewport mounted |
| Documentation | Existing illustrated parts, operations/maintenance, specification and work-instruction documents loaded |
| Native download | Same-window file navigation downloads exact bytes without replacing the editor |
| Draft preservation | Unsaved facility revision, layout, history, cursor and selection survive workflow switches; Undo restores the original |

Documentation starts with a blank authoring view in the shared web application.
The test uses its existing **Refresh** command to reveal the saved baseline.
The native download check uses the existing logo PNG as a controlled artifact;
it verifies the native handoff, not a newly generated PDF or DOCX publication.
The upload check supplies a File through the real input handler; it does not
claim verification of Windows' file-picker dialog.

## Evidence

Final native run: **24/24 checks passed**, saved in
`.runtime/dw2/evidence4/workflows-check.json`, with 21 native screenshots.
The run used an isolated application profile on port 8494.

- Both 3D views mounted 206 meshes with 1,534,740 vertices from the existing GLB.
- The Process Map contained 19 nodes queried through `InspectorProProcessMap.mapNodes`.
- Documentation loaded 15 illustrated-parts pages, 33 operations/maintenance
  pages, one specification page and 20 work-instruction pages.
- No captured JavaScript console errors and no desktop-network refusals.
  This does not mean every HTTP response was successful: absent optional
  drawing artifacts returned 404, and Process Map card-preview validation
  returned 422. Those are application responses, not shell access blocks.
- No facility Save calls. The original manual-layout SHA remained
  `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`;
  all 1,092 original document files also matched their source hashes.
- Exact unsaved draft/history/selection preservation and Undo restoration passed.
- `native-cleanup.json` preserves the owned-backend shutdown receipt: clean
  exit, termination confirmed, resources closed and no cleanup errors.
  The test's Electron and Python process IDs were absent after shutdown.

Representative captures: `02-assembly.png`,
`04-operations_and_maintenance_manual.png`, `06-facility-restored.png` and
`07-process-map.png`, under the final evidence directory.

Regression results:

- 636 desktop Node tests passed, run serially after native testing stopped.
- 9 focused application-boundary/control Python tests passed.
- Shared frontend checks passed: facility app 6/6, workflow state 8/8,
  Process Map 83/83.
- `git diff --check` found no whitespace errors in the changed tracked files.

An earlier concurrent full-suite run had timing-sensitive child-startup and
Windows checkpoint-replacement failures under native-test load. The serial
rerun passed without changing production timeouts or retry limits.

Earlier native reports remain in `.runtime/dw1/` and `.runtime/dw2/`. They are
not final acceptance evidence: the harness initially captured a loading screen,
read legacy Process Map fields, and omitted Documentation's Refresh action.
The model gate now inspects mounted asset geometry because a post-processing
screen quad can report two rendered triangles before any GLB has loaded.

## Remaining Limits

- No provider-generated inspection, new manual, or training procedure was
  requested in this run. Provider connectivity, credits, context limits and
  workflow-specific validation still apply.
- Microphone recording and SolidWorks extraction were not exercised. The CAD
  bridge must be available for extraction; microphone permission remains explicit.
- The shared DFM view is unfinished, and Inspection Sheet is marked unavailable
  in the shared Documentation type registry. Desktop parity does not implement
  those features.
- No business Save was requested by this test. The receipt's `saveCalls`
  counter specifically tracks facility-layout PUTs; independent source hashes
  also cover the original layout and seeded document files.
- Process Map loading may materialize an unsaved migrated draft. Its existing
  discard prompt remains in place. The isolated test inspects it last and
  does not Save or accept a discard prompt in the user's app.
- Earlier Sage context-budget and optional Scout startup issues are not fixed
  or certified by these workflow-connection checks.

## Use the Update

Save any work you want to keep, close InspectorPro normally, then double-click
**InspectorPro Desktop**. A running Electron main process must restart to pick
up the download changes. The user's existing application was not forcibly
closed or restarted during this work.

The separate **InspectorPro - Manual Layout** shortcut opens the browser; it is
not the native desktop launcher. See [launch instructions](launch-inspectorpro-native-desktop.md).
