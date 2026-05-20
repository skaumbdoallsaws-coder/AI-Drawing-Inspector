# App Lineage Status

**Effective: 2026-05-20**  *(originally written 2026-05-18 alongside the
`milestone/ui-bridge-telemetry-unified` tag; refreshed to reflect the
Usage dashboard UI and Library Intake Wizard MVP that landed in the
days immediately after the tag.)*

## Source of truth

The unified app branch is the **only** lineage that should be built against
for new app, bridge, or telemetry work going forward:

- **Branch:** `ui-bridge-telemetry-unified-2026-05-18`
- **Milestone tag:** `milestone/ui-bridge-telemetry-unified`
- **Base:** `main` @ `489adc4` (`fix(fai): theme report surfaces and load revisioned maps`)
- **Worktree (local):** `tmp/ui-bridge-telemetry-unified-2026-05-18/`

This branch carries the light/dark/training UI from `main`, the full SOLIDWORKS
bridge stack (drawing/part/assembly), and the telemetry foundation through
Phase 3 (endpoint timing + workflow stage events + provider-call
instrumentation in engine, qc_report, and server).

End-to-end verified on 2026-05-18:

- Light/dark theme toggle: PASS (visual smoke)
- Training tab UI: PASS (visual smoke)
- Sales-demo light-mode polish: PASS (visual smoke)
- Part bridge extraction on Part 1030024: PASS
  - sidecar at `400S_Sorted_Library/_bridge_imports/part/1030024/<packageId>/`
  - `_latest.txt` -> `4c9d1ceb8991f127131e15c00aa944f5727ce763c8d20570baaec4ef66b25cb9`
  - full bridge audit sequence captured
  - telemetry stage breakdown captured with the approval_wait/extract_wait
    split working as intended (60.8s operator wait vs 6.0s extractor wait,
    cleanly separated)
  - no telemetry warnings during full session


## Deprecated lineage -- do NOT build against

The following lineage was the source of bridge + telemetry work
**before** reconciliation. It is preserved for git archaeology only and
must not be the base for new app work:

- **Branch:** `fea-morph-exaggeration-2026-04-26`
- **Last useful HEAD:** `4ce632c` (`feat(telemetry): record endpoint and workflow timing`)

Why deprecated:

- Built on top of the **old dark-only** `static/index.html` (no light theme,
  no Training tab, no sales-demo polish).
- Carries unrelated FEA exaggeration work (~25 commits) that is not part
  of the bridge / telemetry roadmap.
- Both lineages drifted independently; the reconciliation that produced
  `ui-bridge-telemetry-unified-2026-05-18` is the merge of the two and
  is the only branch that has BOTH the modern UI AND the bridge/telemetry
  stack.

Related dark-only-era branches (do not build against):

- `theme-analysis-light-dark-2026-05-06`
- `worktree-training-solidworks-layout-2026-05-10`
- `sales-coaching-tone-2026-05-06`

Their work is already absorbed into `main` (and therefore into the unified
branch). Treat them as archived.


## What landed in the unified branch (commit chain)

```
af7d272 fix(server): resolve library from tmp worktrees
69a3f8a feat(telemetry): port server provider-call instrumentation        (Step 5b)
8d59ce4 fix(telemetry): avoid duplicate errorType tag collision            (Step 5a)
d1f0559 feat(bridge): port SOLIDWORKS controls to unified frontend         (Step 6)
03c2f63 feat(telemetry): port endpoint and workflow timing to unified app  (Step 5)
4ccf396 fix(packaging): make spatial package importable
5b0fb20 feat(bridge): port extraction endpoints to unified app             (Step 4)
85971b6 feat(telemetry): port engine and report provider instrumentation   (Step 3)
fd225f7 chore(repo): ignore generated runtime artifacts                    (Step 2)
4afee50 port(bridge,telemetry): copy modules from old dark-only lineage    (Step 1)
489adc4 fix(fai): theme report surfaces and load revisioned maps           (main HEAD)
```


## What has landed AFTER the original milestone tag

`milestone/ui-bridge-telemetry-unified` (commit `a2d1d27`) was placed
on 2026-05-18 to anchor the reconciliation state. Two MVP features
shipped immediately after that tag and are now in the unified branch
HEAD:

1. **Usage / Cost / Latency dashboard UI** -- frontend tab that
   visualises the Phase-3 telemetry store. Lives in
   `static/index.html` (Usage tab) and adds reporting endpoints in
   `server.py`. Landed in commit `61a0dcb feat(telemetry): add usage
   tracking dashboard`. SQLite source remains
   `runtime_metrics/inspectorpro_metrics.sqlite`.

2. **Library Intake Wizard MVP** -- right-side wizard panel that
   commits a bridge-extracted part + drawing into the canonical
   per-revision library shape, with the matching stub-aware
   consumer surface. Landed in four commits:
   - `9ad125f feat(library-intake): stub-profile awareness gate (Step 1)`
     -- /api/profile-details + /api/inspect stub-aware gates +
     frontend [INTAKE] badge / Profile-incomplete banner / disabled
     Inspect button.
   - `61a05be feat(library-intake): preview + promote backend (Step 2)`
     -- /api/library/intake/preview + /promote endpoints with .partial
     safety, .bak rollback, single-flight lock, sec 5.7 real-profile
     protection.
   - `d9644a7 feat(library-intake): wizard frontend (Step 3)` --
     /api/library/revisions/{pn} endpoint + 6-step wizard JS IIFE.
   - `c4c08f6 fix(library-intake): stabilize wizard after end-to-end
     smoke` -- DOMContentLoaded init + bridge LIBRARY_DIR pin +
     extraction-metadata pass-through into intake_manifest.

   Verified end-to-end on real SOLIDWORKS extraction of part
   **1030024**: `revC` promoted during initial smoke; `revD`
   promoted after the stabilization fix with full provenance
   confirmed in `intake_manifest.json` (sourceDrawing.packageId +
   sourceDocPath + sheetCount=1 + viewCount=5; sourcePart.packageId
   + sourceDocPath + featureCount=46 + activeConfiguration=Default).
   Both promotes landed under
   `400S_Sorted_Library/parts/1030024/rev{C,D}/`; the existing real
   inspection profile at root was correctly left untouched (sec 5.7
   row 3 protection -- no [INTAKE] badge for this part, as expected).

   The canonical plan document (`docs/library-intake-wizard-plan.md`)
   was also cherry-picked over from the deprecated branch in
   commit `eea0c78`; the unified branch now carries it.

## What is STILL NOT in the unified branch

These are the followups that remain. None affect runtime behaviour.

1. **Docs and scripts from the deprecated lineage that are still on
   `fea-morph-exaggeration-2026-04-26` only**:
   - `docs/bridge-part-assembly-app-integration-plan.md`
   - `docs/customer-overview.md`
   - `docs/installer-phase6-blocked.md`
   - `docs/pilot-demo-script.md`
   - `docs/production-pilot-packaging-checklist.md`
   - `docs/solidworks-bridge.md`
   - `scripts/collect-pilot-bundle.ps1`

   These can be cherry-picked over at any time without coordinating
   with running services.

2. **Assembly intake** through the wizard -- out of MVP scope per
   plan sec 3.2 / sec 10.3. The wizard accepts only part + drawing.
   Assembly extraction still works via the existing
   `/api/request-assembly-extraction` (sidecar-only) flow.

3. **Profile Builder** -- a future tool that would let an operator
   author a real (non-stub) `{pn}_inspection_profile.json` through
   a guided flow. Out of MVP scope per plan sec 12.2 future.
   Until it exists, real profiles continue to be hand-authored.


## Migration guidance

If you are starting new app, bridge, or telemetry work, branch from
`ui-bridge-telemetry-unified-2026-05-18` (or whatever `main` points at
after this branch is merged forward).

If you find a commit in `fea-morph-exaggeration-2026-04-26` that looks
like it has a feature you want, first check whether it has already been
ported:

```
git log --grep="<keyword>" main..ui-bridge-telemetry-unified-2026-05-18
```

If the equivalent work already exists in the unified branch, use that.
If it doesn't, cherry-pick the specific commit -- do NOT branch off the
deprecated lineage.

If you need to compare runtime behaviour against an older release, you
can still check out and run any deprecated branch in a separate worktree
for diagnostic purposes; just do not commit new app work there.


## Notes for the next person who picks this up

- The errorType-collision fix in `record_endpoint_event` (commit
  `8d59ce4`) closed a latent bug that existed in the original
  `4ce632c` Phase 3 work. If you ever revisit that commit on the
  deprecated branch, the same fix needs to be applied or the dashboard
  telemetry foundation is silently broken.
- `ai_inspector/spatial/__init__.py` is now tracked in git (commit
  `4ccf396`). Prior to this milestone it was untracked on `main`,
  causing `import server` to fail on fresh clones -- the fix was to
  commit the 3-line re-export that existed only on disk in some
  worktrees.
- The `_bridge_imports/` sidecar directory is gitignored
  (`400S_Sorted_Library/_bridge_imports/`) and so is
  `runtime_metrics/`. Real extractions land there at runtime.
