# App Lineage Status

**Effective: 2026-05-18**

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


## What is NOT in the unified branch yet

Acknowledged gaps as of the milestone tag. Each is a separate followup,
not a regression:

1. **Usage / Cost / Latency dashboard UI** -- backend telemetry through
   Phase 3 is fully landed and verified, but the frontend dashboard tab
   that visualises it is intentionally NOT built. Phase 4 (frontend) was
   paused for the reconciliation. The SQLite store at
   `runtime_metrics/inspectorpro_metrics.sqlite` is the data source when
   that work resumes.
2. **Library Intake Wizard implementation** -- only the plan exists on the
   deprecated branch. Implementation was deferred during reconciliation
   to keep this branch focused.
3. **Docs and scripts from the deprecated lineage** -- the following are
   still on `fea-morph-exaggeration-2026-04-26` and have not been moved
   to the unified branch:
   - `docs/bridge-part-assembly-app-integration-plan.md`
   - `docs/customer-overview.md`
   - `docs/installer-phase6-blocked.md`
   - `docs/library-intake-wizard-plan.md`
   - `docs/pilot-demo-script.md`
   - `docs/production-pilot-packaging-checklist.md`
   - `docs/solidworks-bridge.md`
   - `scripts/collect-pilot-bundle.ps1`

   These are documentation/tooling; they do not affect runtime behaviour.
   They can be cherry-picked over to the unified branch at any time
   without coordinating with running services.


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
