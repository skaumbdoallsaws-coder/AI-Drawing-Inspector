# GitHub Repo State

Last updated: 2026-06-18

## Source Of Truth

The working app state is in this Git worktree:

```powershell
C:\Users\skaumb\OneDrive - continentalmachines.com\Desktop\Projects\AI-tool\tmp\ui-bridge-telemetry-unified-2026-05-18
```

Use this folder to launch and continue InspectorPro work. Do not launch from the repo root unless the root has first been synchronized with this worktree.

Launch command:

```powershell
cd "C:\Users\skaumb\OneDrive - continentalmachines.com\Desktop\Projects\AI-tool\tmp\ui-bridge-telemetry-unified-2026-05-18"
& "C:\Users\skaumb\OneDrive - continentalmachines.com\Desktop\Projects\AI-tool\.venv313\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8020
```

## GitHub Remote

Remote:

```text
origin  https://github.com/skaumbdoallsaws-coder/AI-Drawing-Inspector.git
```

## Working App Branch

Working branch:

```text
ui-bridge-telemetry-unified-2026-05-18
```

Latest local commit:

```text
842eddb5aaa4f0dc63584269cec06c34aea8d003
842eddb fix(sage): route wrapped caster batch prompt deterministically
```

Local Git caveat:

Git reports this worktree as a different-owner repository under the sandbox user. Use a per-command safe-directory override when inspecting it from automation:

```powershell
$u = "C:/Users/skaumb/OneDrive - continentalmachines.com/Desktop/Projects/AI-tool/tmp/ui-bridge-telemetry-unified-2026-05-18"
git -c safe.directory=$u -C $u status --short --branch
```

GitHub sync status:

- The working branch does not currently show an upstream tracking branch in `git status`.
- Local remote refs show `origin/main` and `origin/fea-morph-exaggeration-2026-04-26`; no local tracking ref for `origin/ui-bridge-telemetry-unified-2026-05-18` was observed.
- This means the working branch should be treated as local-only until explicitly pushed or connected to an upstream.

If intentionally publishing this exact working branch later, use a reviewed/cleaned tree first, then:

```powershell
$u = "C:/Users/skaumb/OneDrive - continentalmachines.com/Desktop/Projects/AI-tool/tmp/ui-bridge-telemetry-unified-2026-05-18"
git -c safe.directory=$u -C $u push -u origin ui-bridge-telemetry-unified-2026-05-18
```

Do not run that until the dirty/untracked state is reviewed.

## Repo Root Branch

Repo root:

```text
C:\Users\skaumb\OneDrive - continentalmachines.com\Desktop\Projects\AI-tool
```

Current root branch:

```text
fea-morph-exaggeration-2026-04-26
```

Latest root commit:

```text
4ce632c7692e5e5ddea5a1bb539f9fc3443bdad6
4ce632c feat(telemetry): record endpoint and workflow timing
```

Root upstream:

```text
origin/fea-morph-exaggeration-2026-04-26
```

Root sync status:

```text
ahead 18
```

The root branch is not the current working app branch. The Training/Plant Process work is in the `ui-bridge-telemetry-unified-2026-05-18` worktree.

## Dirty State Warning

The working app worktree is dirty. Observed modified tracked files include:

```text
SolidWorksExtractor/Models/ExtractionOptions.cs
SolidWorksExtractor/Program.cs
SolidWorksExtractor/Services/GlbExporter.cs
ai_inspector/feature_intent/rules.py
schemas/drawing_evidence_v1.1.0.schema.json
schemas/drawing_evidence_v1.1.1.schema.json
server.py
static/index.html
tests/test_edit_sessions.py
tests/test_feature_intent.py
tests/test_intake_stub_gate.py
tests/test_refresh_from_solidworks.py
tests/test_semantic_regions.py
tests/test_semantic_regions_curator.py
```

Observed untracked files include test temp folders, diagnostic scripts, generated assets, demo assets, and Training/Plant files. Recent relevant untracked/working assets include:

```text
generated/
demo_library/
_verify_plant_walkthrough.py
_verify_bargein_browser.py
static/audio/
static/inspectorpro_intro_dark_3s.mp4
static/inspectorpro_intro_dark_3s_v2.mp4
static/inspectorpro_intro_dark_preview.png
static/inspectorpro_intro_dark_preview_v2.png
static/inspectorpro_intro_light_3s.mp4
static/inspectorpro_intro_light_preview.png
tests/test_training_process_map.py
```

There are also many `.pytest-basetemp-*` folders and local diagnostic artifacts. These should be cleaned or ignored before any serious GitHub sync.

## Current Software State

Working areas currently expected in the unified worktree:

- Training tab with Racing Bike guided assembly work.
- Training tab Plant / Process Explanation mode.
- Cooling tower 3D plant/process model loading from generated Training process assets.
- Cooling tower process flow overlays:
  - airflow and plume
  - hot water loop
  - cold water loop
  - drain/overflow loop
- Sage-triggered cooling tower process walkthrough from the chat pane.
- Sage walkthrough text now behaves as one timed caption block during narration, then displays the full transcript at the end.
- Design for Manufacturing tab exists as an empty UI tab.
- Branded intro video assets generated under `static/`.

Recent known validation:

```text
JS syntax check: passed
_verify_plant_walkthrough.py: 12/12 passed
```

## Recommended Next Git Action

Before syncing to GitHub:

1. Decide whether `ui-bridge-telemetry-unified-2026-05-18` should become the official working branch.
2. Clean temporary folders and diagnostics that should not be committed.
3. Review generated assets and decide which ones belong in the repo.
4. Commit only the intended app/source/data changes.
5. Push the reviewed branch to GitHub with an upstream.

Do not blindly commit all dirty/untracked files.
