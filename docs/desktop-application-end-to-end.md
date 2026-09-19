# Native Application End-to-End Verification

Date: 2026-09-16. Scope: the normal Electron `--application` entry, not the
restricted managed acceptance shell. The native facility workflow passes the
checks below. This is not acceptance of every business workflow or AI task.

## Environment And Isolation

- Windows, existing Electron 44.3.0, Node 24.11.1, Python 3.14.
- Final profile: `.runtime/da5/profile.json`, private backend on port 8486.
- The runner copies the manual layout and its authority data. Catalog assets
  are read from the real library. Save checks target the copy only.
- Original manual layout: 827 placements, 45 zones, 8 routes, 50 markings.
- Original SHA-256 before and after:
  `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.
- The runner refuses a non-isolated root or a starting revision different from
  that recorded source. It does not reset saved bytes to hide revision changes.

## Native Results

Final machine-readable evidence:
`.runtime/da5/evidence/application-check.json` (`status: passed`).
An earlier complete pass is preserved at
`.runtime/da4/evidence-run2/application-check.json`.

| Check | Observed result |
| --- | --- |
| Manual layout | Correct layout ID, 827 placements, 45 zones, exact source revision |
| Native application authority | No renderer Node access, old diagnostic bridge, or persistent inert lock; unauthenticated API request returns 401 |
| Ribbon and library | Native Pan/Select clicks succeed; asset-library button opens the actual 148-asset catalog |
| Workflow navigation | All eight visible tabs activate; returning to Facility restores the same workspace/session |
| Real GLBs | 37 asset groups, no pending loads, no degraded renderer; close-up ABB robot has 13 prototype meshes, not a fallback box |
| Native downloads | Layout Blob export matches the current document; authenticated profile download completes through the normal download handler |
| Close / Cancel | Actual Windows unsaved-work dialog was cancelled using Computer Use; exact layout, draft revision, history, cursor, and selection retained |
| Actual Sage chat | Prompt submitted through chat; real streaming endpoint and activity-scenario POST/GET return success |
| Playback | 23 distinct existing placement IDs: 17 operators and 6 vehicles; all 23 move across samples at 0, 2.5, 7.5, and 17.5 seconds |
| Actor rendering | All 23 report exact catalog visuals and suppressed stationary source placements; duplicate placement list remains empty |
| Playback controls | Native Play, Pause, and Paths clicks change actual playback state |
| Drone | Active drone mode, advancing playback clock, no visible duplicate source placements |
| Remount | Switching away/back restores the connected docked playback panel and all 23 actors without dirtying the layout |
| Edit / Undo | Real session/backend edit creates an unsaved draft; Undo restores the exact original document |
| Save | Two real Save calls on the isolated copy; authoritative revision advances |
| Owned backend restart | New backend identity; exact unsaved layout, revision, history, cursor, and selection preserved; Undo still works |
| Cleanup | Child termination, closed stdio/resources, stopped lifespan, exit code 0, no forced termination |

The 24 requests refused in the final run were made while private network access
was deliberately disabled during restart. None were refused while access was
enabled. The final renderer error capture is empty. The separate unauthenticated
401 probe is intentional and is not counted as an application failure.

Playback remains a qualified prototype presentation. Five partial candidate
programs and inferred/pending handoff evidence remain disclosed in the pane.
Movement evidence does not prove traffic avoidance, throughput, safety,
manufacturing timing, robot articulation, or production eligibility. Not every
actor uses a closed journey cycle; existing return/hold policies remain intact.

## Screenshots

All are real native Electron `capturePage` results under `.runtime/da5/evidence/`:

- `01-plan-and-library.png`: real asset cards and library controls.
- `02-three-dimensional-assets.png`: loaded facility scene.
- `02b-robot-real-glb.png`: inspectable robot geometry and surrounding guarding.
- `04-sage-motion-plan.png`: actual Sage response and Plan playback.
- `05-drone-moving-existing-operator.png`: drone scene and docked controls.
- `06-restored-docked-playback.png`: playback after workspace remount.
- `03-restored-plan.png`: draft restoration after backend restart.
- `07-cancel-preserved-draft-and-undo.png`: cancelled-close restoration.

The robot screenshot is 1783 x 974 physical pixels. Its robot-only region
`[800, 470, 1000, 680]` contains 1,162 distinct colors; RGB standard deviations
are 21.387, 25.210, and 26.657. Pixel checks and visual inspection confirm a
nonblank mesh, not merely a successful download or nonempty canvas element.
The drone screenshot alone is not evidence that every actor is visible at once;
the per-actor assertions supply that separate identity/pose evidence.

## Fixes Made During Verification

1. Suspend a connected Facility workspace before replacing viewport DOM.
   Reattach its existing root and docked motion panel on return, preserving the
   session rather than constructing a second editor. Regression tests exercise
   both suspended and retained-but-not-suspended instances.
2. Do not register the web PWA service worker in native application mode. Native
   requests use per-launch authentication; no worker authorization was relaxed.
3. Use the existing `--bg-input` theme token for docked playback controls instead
   of an undefined `--bg-secondary` token. The latter produced pale text on a
   light fallback background. Native computed colors are now foreground
   `rgb(227, 230, 235)` and background `rgb(22, 26, 34)`, with controls enabled.
4. Enable the existing local motion-prototype and construction-Sage feature
   flags. Existing authorization, validation, and prototype qualifications remain.
5. Correct the test harness: select Sage after New Chat, wait for renderer frames
   after seeking, accept actual GLB overview representations, and use Electron
   44's console event shape. Preserve failed reports rather than overwriting them.
6. Normalize CRLF in the ribbon source-contract test; its 33-command assertion
   remains unchanged.

Earlier startup work replaced a blocking stdin reader with the bounded,
nonblocking control pipe. Controlled reproduction distinguished that deadlock
from application import work. Final native startup took 12.186 seconds and the
owned replacement backend took 6.886 seconds. These are observations, not p95s.

## Test Runs

- `node --test desktop/tests/*.test.cjs`: 620 passed.
- `C:\Python314\python.exe -m unittest discover -s desktop/tests -p test_*.py`:
  229 tests, 228 passed and 1 skipped.
- Shared app, session, workspace, and ribbon Node test files: all four passed;
  workspace reports 85/85 and ribbon verifies 33 reachable commands.
- The last changes after the full desktop suite were scoped playback CSS,
  its workspace assertion, and native-runner control clicks. The shared suites
  and final native run cover those changes.

## Remaining Findings And Coverage Limits

1. Cold complete-movement preparation is slow. In the final run the activity
   POST took 151.419 seconds. The full Sage stage, including checks, took
   171.848 seconds. A warm rerun completed that stage in 16.875 seconds. An
   earlier run exceeded the harness's 240-second wait; its cause was not fully
   isolated. There is no latency acceptance or stability/p95 claim here.
2. An actual Iris request in an earlier run exceeded the provider limit:
   567,980 prompt tokens against a 200,000-token maximum. It returned HTTP 400.
   This context-budget failure remains unresolved. The successful Sage motion
   prompt takes the existing deterministic intent path; it does not prove that
   arbitrary provider-backed planning is working.
3. Startup reports an unavailable optional Scout browser-search module. Scout
   research has not been accepted by this run.
4. Workflow tab activation is not a full Drawing, Assembly, DFM, Report, or
   Sessions business-workflow test. Microphone consent/recording, real CAD
   extraction, arbitrary uploads, the full construction approval conversation,
   production scheduling, and a tabbed embedded research pane were not verified.
5. Normal-mode tests above verify a clean and dirty-draft owned restart. They do
   not re-certify all pending-transaction crash cases; earlier isolated recovery
   evidence remains separate. No universal desktop release acceptance is claimed.

## User Launcher

`InspectorPro Desktop.lnk` has been upgraded, with a backup, from the restricted
managed profile to the normal `--application` profile. It starts Electron, not a
browser, and opens the original manual layout on the protected owned backend at
port 8480. This profile intentionally permits ordinary editing and explicit Save.
The isolated acceptance runner is never used by this shortcut.

See [launch instructions](launch-inspectorpro-native-desktop.md). Do not delete
the Electron runtime or profile directories while using the development shortcut.

The upgraded `.lnk` was then launched directly. Windows Computer Use confirmed
the real native manual-layout window, working dark-to-light theme switch, and
asset-library opening/closing without adding equipment. The normal backend
verified the original facility/library roots and reported ready after 10.758
seconds. The original SHA was checked again and is unchanged. This normal app
was left open for the user; isolated acceptance backends were shut down.
