# InspectorPro desktop runtime inventory and rendering fixture

Date: 2026-09-12. Scope: Phase 0 inventory and the initial, inert Phase 1 rendering spike from implementation-plan revision 2. This is not interactive-shell acceptance or a production backend access boundary.

## Checkpoint and isolation

The implementation snapshot is outside the live project, under the Codex workspace. Its `desktop-checkpoint.json` records source `C:\Users\might\OneDrive\Desktop\InspectorPro\AI-Drawing-Inspector`, source HEAD `1632770aa18c1e6862614171f751977b051de6d2`, 1,942 copied files, and source-manifest SHA-256 `c319206a9940fb08871af69649a2f4c241d9075bf0925e38a6928ad2c7f91bf4`. It includes current copied source; it is not represented as a clean checkout of that commit. Runtime stores, `.env`, and ignored large/private assets were excluded. Do not overwrite source changes by copying the snapshot back wholesale.

The rendering launcher requires this checkpoint marker and rejects execution inside the recorded source workspace. It does not modify `server.py` or replace the application with a test web page. It imports the real application and runs its actual FastAPI lifespan.

## Reproducible commands

From the isolated snapshot root, verify backend startup and HTTP restrictions, then stop its owned child:

```powershell
python desktop/tools/run-rendering-backend.py --port 8191 --profile-id backend-smoke --data-root .runtime/desktop-spike/backend-smoke --check
```

To keep the backend running for a shell rendering inspection, omit `--check`. Ctrl+C stops the owned backend. The launcher uses a hidden Windows child console, a separate process group, a bounded readiness deadline (45 seconds by default), and a bounded graceful stop. Termination fallback targets only the process it created. This fallback is acceptable for this inert fixture; it is not the planned transaction-aware managed-backend shutdown contract.

Use a separate profile and data directory for another explicitly selected port. A stored profile refuses a changed port or profile name. It never silently chooses a new port or adopts a process already listening on the requested port. A per-launch response header distinguishes a new process from an older process serving the same persisted profile IDs.

Run launcher tests without importing the application:

```powershell
python -B -m unittest discover -s desktop/tests -p test_rendering_backend.py -v
```

The launcher prints a narrow ready receipt with canonical origin, public identity, and the isolated log path. No provider credentials are printed or inherited by the child.

## Runtime observed on this machine

| Dependency | Observed installation |
| --- | --- |
| Python | `C:\Python314\python.exe`, 3.14.0 |
| Node | `C:\Program Files\nodejs\node.exe`, v24.11.1 |
| Uvicorn / FastAPI | 0.38.0 / 0.124.0 |
| Pydantic / python-dotenv | 2.12.4 / 1.2.1 |
| python-multipart | 0.0.20 |
| Anthropic / OpenAI SDK | 0.75.0 / 2.8.1 |
| Shapely / Pillow | 2.1.2 / 12.0.0 |
| PyMuPDF / python-docx | 1.27.2.3 / 1.2.0 |
| Playwright / torch | 1.56.0 / 2.9.1 |
| faster-whisper | Not installed |

This inventory describes the developer machine; it is not a dependency lock or installer. `requirements.txt` contains many unpinned packages and `setup.py` declares Python >=3.9, which is not proof that current code works on every such version. Keep the existing PyMuPDF licensing/distribution disposition as a separate release issue.

Many Python dependencies reside in this interpreter's user site. Changing APPDATA for isolation initially made `uvicorn` unavailable. The launcher therefore preserves an explicit list of the installed interpreter's `site-packages` directories for read-only import lookup while isolating APPDATA runtime writes. It does not inherit arbitrary PYTHONPATH or execute another browser/application profile migration.

Construction uses `shutil.which("node")` and a fixed script subprocess in `ai_inspector/facility_layout/construction_compiler.py`. The spike disables construction, removes Node from the child search path, and denies subprocesses. A later interactive/backend milestone must explicitly supply and test its supported Node runtime. Electron's embedded runtime does not fulfill this lookup automatically.

## Current server launch and environment behavior

`server.py` defines the FastAPI application. The normal direct launch mechanism is `python -m uvicorn server:app`, run from the repository root. Relative static mounts, motion data, and other paths make cwd significant. No root `run_app.py` exists. `init.sh` installs packages and starts a network-exposed autoreloading development server; it is not used by the desktop launcher.

`server.py:51-52` loads repository and parent `.env` files. `SpatialInspector.__init__` also invokes dotenv loading. Installed python-dotenv 1.2.1 honors `PYTHON_DOTENV_DISABLED=1`, verified from its implementation.

The fixture child environment is built from a short operating-system-variable allowlist. It contains no inherited provider keys, proxy settings, workflow rollout flags, arbitrary package paths, or native-helper overrides. It supplies isolated TEMP, TMP, APPDATA, and LOCALAPPDATA directories. The launching process's environment is unchanged. This avoids discovering the live SolidWorks bridge through the user's normal LOCALAPPDATA directory.

Full lifespan startup remains active (`server.py:1351`):

1. Attempt initialization of the inspection engine. Without provider keys it logs its existing unavailable status and serves available local/static routes.
2. Run `_ensure_assembly_files`, which can create the chosen library's `assemblies` directory and copy cwd assembly JSON, PNG, and GLB files (`server.py:1126`).
3. Load assembly profiles/prepared packages, which may assign library part numbers.
4. Attempt optional Scout browser startup. Its module is absent in this snapshot, and the existing application catches that failure.

The launcher wraps shutdown to close the facility spatial executor, memory runtime, route-shadow executor, and viewport-intent executor after the application's original lifespan completes. These were not all closed by the original lifespan. No business transaction recovery is inferred from these cleanup calls.

## Persistence inventory

| Workflow/state | Current source behavior | Rendering-fixture treatment |
| --- | --- | --- |
| Inspection library, intake, profiles, revision sidecars | `INSPECTORPRO_LIBRARY_DIR`; otherwise scored candidates, including possible primary-workspace libraries for some worktree paths (`server.py:560`) | Explicit existing `data-root/library`; supplied library must exist inside data root; validate `server.LIBRARY_DIR` after import. No fallback. |
| Facility layouts, authority documents, transactions, generation/design artifacts | `INSPECTORPRO_FACILITY_LAYOUT_ROOT`; default repo `.runtime/facility-layout` (`server.py:1592`; facility host/repositories) | Explicit `data-root/facility`. Fixture bootstrap writes here are expected. |
| Process maps and assembly knowledge | Repo `generated/training`, also passed to facility host | Isolated snapshot only; no current unified root override. |
| Facility planning | Repo `generated/facility_planning` | Isolated snapshot only; no current unified root override. |
| Parts manuals | `INSPECTORPRO_PARTS_MANUAL_ROOT` or repo generated directory | Explicit isolated root; routes denied in spike. |
| Operations manuals | `INSPECTORPRO_OPERATIONS_MANUAL_ROOT` | Explicit isolated root; routes denied in spike. |
| Specification sheets | `INSPECTORPRO_SPECIFICATION_SHEET_ROOT` | Explicit isolated root; routes denied in spike. |
| Work instructions | `INSPECTORPRO_WORK_INSTRUCTION_ROOT` | Explicit isolated root; routes denied in spike. |
| Metrics | `INSPECTORPRO_METRICS_DB`; default cwd `runtime_metrics/inspectorpro_metrics.sqlite` | `data-root/metrics.sqlite`. Even allowlisted API reads may write telemetry. |
| Agent memory | `INSPECTORPRO_MEMORY_DB_PATH`; default LOCALAPPDATA InspectorPro memory DB | Explicit isolated DB; memory mode off. |
| Chat feedback | `INSPECTORPRO_CHAT_FEEDBACK_DB_PATH`; default repo runtime_logs DB | Explicit isolated DB; feedback routes denied. |
| Preview/validation caches and generated assets | Several repo `.runtime` and cwd `generated` locations | Isolated snapshot only. |
| Chat registry/preferences | Existing frontend origin-bound localStorage | Desktop partition/profile work; no external-browser-profile import. |
| Design Undo recovery | Existing sessionStorage and host hooks | No interactive recovery claim; engineering inputs remain inert in the shell spike. |

The launcher accepts an explicit data root under snapshot `.runtime/desktop-spike`, or another local root verified empty before first use and outside the source workspace. It refuses symlink/junction paths, source/ancestor overlap, and unmarked nonempty roots. After first use, a durable identity marker binds that root to the snapshot, profile, and origin. Copying a store requires a new reviewed identity procedure; do not copy its marker to share authority.

A Python audit hook additionally rejects Python-level file writes outside the isolated data root and the snapshot's `generated`/`.runtime` directories, including SQLite opens. It normalizes the Windows extended-length paths used by the facility repositories. Native subprocess execution is denied. This is a fixture guard, not an operating-system sandbox or a replacement for application authorization. Imported native extensions are not comprehensively confined by Python audit events. The rendering fixture is intended for known copied local content, not untrusted documents or websites.

## Narrow identity and rendering boundary

The existing application has no narrow whole-backend readiness/store-identity endpoint. `/` proves only HTML availability, and `/api/admin/memory/health` is an administrative route. The fixture wrapper provides:

```json
{
  "schemaVersion": 1,
  "product": "InspectorPro",
  "mode": "rendering-spike",
  "backendId": "<persisted UUID>",
  "storeId": "<persisted UUID>",
  "profileId": "<explicit profile>",
  "researchBrowsing": false,
  "interactive": false
}
```

`GET /api/desktop-shell/identity` becomes reachable through Uvicorn only after full lifespan startup. It returns no paths, provider configuration, project data, or credentials. The supervisor verifies exact identity and a per-launch instance header. This identifies a restricted fixture; it does not authenticate or pair a production backend.

The outer ASGI fixture wrapper passes only GET/HEAD requests for:

- `/`, `/static/*`, and `/generated/*`.
- `/api/desktop-shell/identity`.
- `/api/profiles`, `/api/facility-layout-bootstrap`, `/api/industrial-assets`, and `/api/agent/chat/streaming-status`.

All other API routes, all HTTP mutation methods, WebSockets, mismatched Host values, and present origins other than the exact canonical application origin are denied before the real application is called. No native-action GET is allowlisted. Static assets are the isolated snapshot's copied assets. This boundary intentionally disables existing workflows; it is not the complete authenticated boundary required for an interactive shell or research browsing.

## Native helpers, optional components, and restart gaps

- Existing helper variables: `INSPECTORPKG_CLI`, `SOLIDWORKS_EXTRACTOR_EXE`, `EXPORT_FORMATS_EXE` (`server.py:2139-2174`). None are invoked by the spike.
- The SolidWorks bridge normally reads LOCALAPPDATA `InspectorPro/Bridge/bridge.json` and `bridge_token` (`bridge/client.py:252`). Spike LOCALAPPDATA is isolated, and bridge routes are denied.
- `ai_inspector.search.browser_engine` and `ai_inspector.services.training_scene_service` are absent in this snapshot. Scout browsing and Blender cannot be claimed as tested.
- Speech capture/transcription needs separate frontend permission acceptance. Local faster-whisper is absent; CUDA/model caches are optional dependencies. Voice provider routes are denied.
- Motion uses cwd `generated/engine_motion/motion/motion_registry.json`; some entries/private assets are excluded from the snapshot. Real model/motion acceptance remains outstanding.
- Facility pending follow-ups and skill workflow stores include in-memory TTL state (`orchestration.py:464`, `server.py:35354`). A backend restart cannot simply assume their continuity.

## Verification recorded

On 2026-09-12, the actual launcher `--check` completed with exit 0 in approximately 9.8 seconds including startup, HTTP checks, and shutdown. Its log shows original inspection/assembly/Scout lifespan steps and the original shutdown message. Provider keys were unavailable as intended. The missing private MMLE-50D documentation-registry path was reported by existing startup code; no real-assembly coverage is claimed.

| Check through actual backend process | Result |
| --- | --- |
| Exact profile identity after full lifespan | Passed |
| GET `/` | 200 |
| GET `/api/profiles` | 200; empty fixture library |
| GET `/api/facility-layout-bootstrap` | 200; isolated starter fixture |
| GET `/api/bridge/status` | 403 |
| GET `/api/admin/memory/health` | 403 |
| POST `/api/agent/chat` | 403 |
| POST `/api/facility-layout-bootstrap` | 403 |
| Owned-child graceful stop | Exit 0 |

Fourteen focused launcher tests pass: stable identity and separate stores, profile/origin mismatch, nonempty/source-root rejection, missing/outside library rejection, child environment isolation, Windows extended paths, write/helper denial, route/method/socket restrictions, Host/Origin denial, per-launch identity confusion, early exit, and owned shutdown behavior. These are unit/boundary tests; the HTTP table above is the separately executed actual-backend test.

## Remaining gates and ownership

| Gap | Next implementation owner/slice | Required evidence |
| --- | --- | --- |
| Interactive lifecycle and durable recovery for each workflow | Lifecycle/renderer integration | Dirty close cancel, pending Apply/Undo, durable failure/restart reconciliation; no automatic Save or replay. |
| Whole-application authenticated session boundary | Backend boundary + desktop pairing | Both attach/managed modes, every privileged route class/assets/streams/sockets; no credential-free access to live data. |
| Stable authoritative store identity across every root | Backend settings/profile contract | Mismatch and store-copy detection; two stores/principals cannot share recovery. |
| Full backend ownership and native jobs | Managed supervisor | Active-job settlement, restart/reconnect protocol, unrelated-process survival. |
| Real fixture assets and workflow acceptance | Workflow fixture/acceptance work | Real GLBs, motion, maps, reports, voice, all workflow entry points; browser comparison. |
| Live Sage construction in Electron | Bounded pilot acceptance | Existing unchanged prompt and assertions, supported Node compiler; provider scope reported separately. |
| Research browser | Research/permission/navigation implementation | Disabled until protected backend and lifecycle gates pass; actual native-view isolation. |

Direct inspection found 217 HTTP routes declared in `server.py`, in addition to the imported facility router. The existing facility origin middleware covers only selected facility paths and accepts missing/loopback Origins. Library/intake, native edit sessions, training/builder, inspection, manuals, agent/memory, voice, and geometry also need coverage. The read allowlist above cannot be loosened into an interactive release without that work.

Phase 0 now has a source-grounded inventory and an executed restricted full-application launch. The inert rendering spike may be reviewed independently. The implementation-plan gates for an interactive Milestone A, research Milestone B, and clean-machine distribution remain open.
