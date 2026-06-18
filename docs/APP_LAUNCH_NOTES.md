# InspectorPro App Launch Notes

These notes describe the currently working unified app state.

## Working Directory

Launch the app from the unified worktree root, not from an older checkout or a directory missing the generated demo assets.

The launch directory must contain:

- `server.py`
- `static/index.html`
- `generated/training/racing-bike/`
- `generated/training/process/cooling-tower/`

## Start The Server

From the unified worktree root:

```powershell
python -m uvicorn server:app --host 127.0.0.1 --port 8020
```

If you are using the repo-local Python environment from the parent project layout:

```powershell
& "..\..\.venv313\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8020
```

Open:

```text
http://127.0.0.1:8020/
```

## Smoke Checks

Run these from the same worktree root after the server starts:

```powershell
curl -s http://127.0.0.1:8020/generated/training/racing-bike/racing_bike_process_map_working_draft.json | python -c "import sys,json; d=json.load(sys.stdin); print('racing-bike nodes=', len(d['nodes']))"

curl -s -o NUL -w "guided plan %{http_code}\n" http://127.0.0.1:8020/generated/training/racing-bike/racing_bike_guided_build_plan.json

curl -s -o NUL -w "racing bike GLB %{http_code}\n" http://127.0.0.1:8020/generated/training/racing-bike/assembly_glb/racing_bike_assembly.glb

curl -s -o NUL -w "cooling tower GLB %{http_code}\n" http://127.0.0.1:8020/generated/training/process/cooling-tower/cooling_tower_body.glb

curl -s -o NUL -w "cooling tower flows %{http_code}\n" http://127.0.0.1:8020/generated/training/process/cooling-tower/cooling_tower_flow_paths.json
```

Expected result: all HTTP checks return `200`; the process map should report roughly 56 nodes.

## Demo Areas

- Training tab: racing-bike guided assembly, narration, barge-in, subassembly GLB viewer.
- Plant / Process Explanation: cooling tower 3D walkthrough with air, hot water, cold water, and drain/overflow overlays.
- Design for Manufacturing tab: present as an empty placeholder tab.

## Environment Notes

- `.env` is intentionally not committed.
- API keys must stay outside Git.
- The committed runtime demo uses files under `generated/training/`.
- Local logs, smoke captures, pytest temp folders, and diagnostic scripts are ignored by `.gitignore`.
