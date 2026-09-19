"""Launch the real InspectorPro application in an isolated, inert rendering spike.

This is a developer fixture launcher, not production authentication or a managed
desktop backend. It deliberately rejects every non-allowlisted application API.
"""
from __future__ import annotations

import sys

# This literal precedes the remaining imports so a silent child can be
# distinguished from a child stalled while importing its launcher dependencies.
_STARTUP_CHECKPOINTS_ENABLED = __name__ == "__main__" and "--serve" in sys.argv
if _STARTUP_CHECKPOINTS_ENABLED:
    try:
        sys.stderr.write("INSPECTORPRO_DESKTOP_BACKEND_BOOTSTRAP_ENTERED\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass

import os
import time
import json

_STARTUP_STARTED = time.monotonic()
_STARTUP_SEQUENCE = 0
STARTUP_CHECKPOINT_PREFIX = "INSPECTORPRO_DESKTOP_BACKEND_CHECKPOINT "


def enable_startup_checkpoints(*, started_at: float | None = None) -> None:
    """Explicit wrapper opt-in; importing this module never enables diagnostics.

    A wrapper may supply its own monotonic entry time so elapsed values include
    its imports. This changes diagnostics only, not startup or ownership gates.
    """
    global _STARTUP_CHECKPOINTS_ENABLED, _STARTUP_STARTED
    if started_at is not None:
        if (isinstance(started_at, bool) or not isinstance(started_at, (int, float))
                or not 0 <= started_at <= time.monotonic()):
            raise ValueError("Checkpoint start must be an earlier monotonic time")
        _STARTUP_STARTED = started_at
    _STARTUP_CHECKPOINTS_ENABLED = True


def startup_checkpoint(phase: str) -> None:
    """Flush fixed phase metadata only; never serialize paths, args or secrets."""
    if not _STARTUP_CHECKPOINTS_ENABLED:
        return
    global _STARTUP_SEQUENCE
    _STARTUP_SEQUENCE += 1
    record = {"schemaVersion": 1, "pid": os.getpid(), "timeUnixMs": int(time.time() * 1000),
              "phase": phase, "sequence": _STARTUP_SEQUENCE,
              "elapsedMs": max(0, int((time.monotonic() - _STARTUP_STARTED) * 1000))}
    instance = os.environ.get("INSPECTORPRO_DESKTOP_INSTANCE_ID", "")
    # UUID shape validation is deliberately independent of the later uuid import.
    if (len(instance) == 36 and all(instance[index] == "-" for index in (8, 13, 18, 23))
        and all(character in "0123456789abcdefABCDEF" for index, character in enumerate(instance)
                if index not in (8, 13, 18, 23))):
        record["instanceId"] = instance.lower()
    try:
        sys.stderr.write(STARTUP_CHECKPOINT_PREFIX + json.dumps(record, separators=(",", ":")) + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        # Diagnostic IO must not prevent the existing resource cleanup path.
        pass


startup_checkpoint("child-file-entered")
startup_checkpoint("stdlib-imports-starting")
import argparse
from contextlib import asynccontextmanager
from pathlib import Path
import re
import signal
import site
import subprocess
import urllib.error
import urllib.request
import uuid
startup_checkpoint("stdlib-imports-completed")

ROOT = Path(__file__).resolve().parents[2]
MARKER_NAME = "desktop-rendering-identity.json"
READ_APIS = frozenset({
    "/api/profiles", "/api/facility-layout-bootstrap", "/api/industrial-assets",
    "/api/agent/chat/streaming-status",
})
IDENTITY_PATH = "/api/desktop-shell/identity"
SAFE_ENV_KEYS = frozenset({
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "OS",
})


def within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def no_links(path: Path) -> Path:
    """Reject junctions/symlinks, including parents, before resolving paths."""
    raw = str(path)
    if raw.startswith("\\\\?\\") and not raw.startswith("\\\\?\\UNC\\"):
        path = Path(raw[4:])
    elif raw.startswith("\\\\"):
        raise ValueError("Rendering fixture roots must be on the local filesystem")
    absolute = path.absolute()
    for item in (absolute, *absolute.parents):
        if item.exists() and (item.is_symlink() or getattr(item, "is_junction", lambda: False)()):
            raise ValueError("Fixture paths must not contain symbolic links or junctions")
    return absolute.resolve()


def verify_snapshot(root: Path) -> Path:
    root = no_links(root)
    checkpoint = root / "desktop-checkpoint.json"
    if not checkpoint.is_file():
        raise ValueError("A copied desktop snapshot with desktop-checkpoint.json is required")
    value = json.loads(checkpoint.read_text(encoding="utf-8-sig"))
    source = no_links(Path(value["source"]))
    if within(root, source) or within(source, root):
        raise ValueError("Rendering spike must run outside the source workspace")
    for folder in ("static", "generated", "ai_inspector"):
        target = no_links(root / folder)
        if not target.is_dir():
            raise ValueError(f"Snapshot is missing required {folder} directory")
    return source


def validate_identity(value: dict, *, origin: str, profile_id: str, root: Path) -> dict:
    expected = {
        "schemaVersion": 1, "product": "InspectorPro", "mode": "rendering-spike",
        "profileId": profile_id, "researchBrowsing": False, "interactive": False,
        "origin": origin, "snapshotRoot": str(root),
    }
    if not isinstance(value, dict) or any(value.get(key) != item for key, item in expected.items()):
        raise ValueError("Existing fixture identity does not match this profile, origin, or snapshot")
    for key in ("backendId", "storeId"):
        uuid.UUID(value.get(key, ""))
    return value


def prepare_fixture(root: Path, data_root: Path, profile_id: str, port: int,
                    library_root: Path | None = None) -> tuple[Path, dict]:
    source = verify_snapshot(root)
    root = root.resolve()
    data_root = no_links(data_root)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", profile_id):
        raise ValueError("profile-id must contain 1-64 simple identifier characters")
    if not 1024 <= port <= 65535:
        raise ValueError("port must be explicitly chosen between 1024 and 65535")
    if within(data_root, source) or within(source, data_root) or within(root, data_root):
        raise ValueError("Data root overlaps a source workspace")
    if within(data_root, root) and not within(data_root, root / ".runtime" / "desktop-spike"):
        raise ValueError("Snapshot data roots must be under .runtime/desktop-spike")
    marker = data_root / MARKER_NAME
    origin = f"http://127.0.0.1:{port}"
    if marker.exists():
        identity = validate_identity(json.loads(marker.read_text(encoding="utf-8")),
                                     origin=origin, profile_id=profile_id, root=root)
    else:
        if data_root.exists() and any(data_root.iterdir()):
            raise ValueError("Unmarked data root must be empty; refusing to use existing data")
        data_root.mkdir(parents=True, exist_ok=True)
        identity = {
            "schemaVersion": 1, "product": "InspectorPro", "mode": "rendering-spike",
            "backendId": str(uuid.uuid4()), "storeId": str(uuid.uuid4()),
            "profileId": profile_id, "researchBrowsing": False, "interactive": False,
            "origin": origin, "snapshotRoot": str(root),
        }
        # Exclusive create prevents concurrent first launches from replacing IDs.
        with marker.open("x", encoding="utf-8") as handle:
            json.dump(identity, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
    library = no_links(library_root or data_root / "library")
    if not within(library, data_root) or library == data_root:
        raise ValueError("Fixture library must be inside the isolated data root")
    if library_root is not None and not library.is_dir():
        raise ValueError("Explicit fixture library must exist; fallback is forbidden")
    library.mkdir(parents=True, exist_ok=True)
    for name in ("temp", "localappdata", "appdata", "facility", "logs"):
        no_links(data_root / name).mkdir(parents=True, exist_ok=True)
    return library, identity


def child_environment(parent: dict[str, str], data_root: Path, library: Path) -> dict[str, str]:
    # Start with an allowlist, not a credentials blocklist. Never mutate os.environ
    # in the launching process or pass the parent's .env/provider configuration.
    env = {key: value for key, value in parent.items() if key.upper() in SAFE_ENV_KEYS}
    system = Path(parent.get("SYSTEMROOT", parent.get("SystemRoot", r"C:\Windows")))
    env.update({
        "PATH": os.pathsep.join([str(Path(sys.executable).parent), str(system / "System32"), str(system)]),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1", "TEMP": str(data_root / "temp"), "TMP": str(data_root / "temp"),
        "LOCALAPPDATA": str(data_root / "localappdata"), "APPDATA": str(data_root / "appdata"),
        "INSPECTORPRO_LIBRARY_DIR": str(library),
        "INSPECTORPRO_FACILITY_LAYOUT_ROOT": str(data_root / "facility"),
        "INSPECTORPRO_METRICS_DB": str(data_root / "metrics.sqlite"),
        "INSPECTORPRO_MEMORY_DB_PATH": str(data_root / "memory.sqlite"),
        "INSPECTORPRO_MEMORY_V1_MODE": "off",
        "INSPECTORPRO_CHAT_FEEDBACK_DB_PATH": str(data_root / "feedback.sqlite"),
        "INSPECTORPRO_PARTS_MANUAL_ROOT": str(data_root / "parts-manual"),
        "INSPECTORPRO_OPERATIONS_MANUAL_ROOT": str(data_root / "operations-manual"),
        "INSPECTORPRO_SPECIFICATION_SHEET_ROOT": str(data_root / "specification-sheets"),
        "INSPECTORPRO_WORK_INSTRUCTION_ROOT": str(data_root / "work-instructions"),
        "INSPECTORPRO_FACILITY_LAYOUT_VIEWER_V2": "1",
        "INSPECTORPRO_INDUSTRIAL_ASSET_LIBRARY": "1",
        "INSPECTORPRO_FACILITY_LAYOUT_CONSTRUCTION_SAGE": "0",
        "INSPECTORPRO_FACILITY_PRIVATE_ASSETS": "0",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        # This machine installs web dependencies in the interpreter's user site.
        # Preserve explicit package lookup while isolating APPDATA runtime writes.
        "INSPECTORPRO_DESKTOP_PYTHON_SITES": json.dumps([
            str(Path(path).resolve()) for path in [*site.getsitepackages(), site.getusersitepackages()]
            if Path(path).is_dir() and Path(path).name == "site-packages"
        ]),
    })
    return env


def install_fixture_write_guard(root: Path, data_root: Path) -> None:
    """Defense for Python-level startup writes; this is not an OS sandbox."""
    permitted = (data_root.resolve(), (root / "generated").resolve(), (root / ".runtime").resolve())

    def check(raw):
        if isinstance(raw, (str, bytes, os.PathLike)):
            path = no_links(Path(os.fsdecode(raw)))
            if not any(within(path, parent) for parent in permitted):
                raise PermissionError("Rendering fixture rejected a write outside isolated output roots")

    def audit(event, args):
        if event == "open":
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            ):
                check(args[0])
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime", "sqlite3.connect"}:
            if args[0] != ":memory:":
                check(args[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            check(args[0]); check(args[1])
        elif event in {"subprocess.Popen", "os.system", "os.posix_spawn"}:
            raise PermissionError("Native helpers and subprocesses are disabled in the rendering spike")

    sys.addaudithook(audit)


def public_identity(identity: dict) -> dict:
    return {key: identity[key] for key in (
        "schemaVersion", "product", "mode", "backendId", "storeId", "profileId",
        "researchBrowsing", "interactive",
    )}


def shutdown_receipt_path(data_root: Path, instance_id: str) -> Path:
    return data_root / "shutdown" / (str(uuid.UUID(instance_id)) + ".json")


def allowed_request(method: str, path: str) -> bool:
    if method not in {"GET", "HEAD"} or "\\" in path or any(piece in {".", ".."} for piece in path.split("/")):
        return False
    return path in {"/", IDENTITY_PATH, *READ_APIS} or path.startswith(("/static/", "/generated/"))


class RenderingBoundary:
    def __init__(self, app, identity: dict, instance_id: str = ""):
        self.app = app
        self.identity = identity
        self.instance_id = instance_id

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        expected_host = self.identity["origin"].removeprefix("http://").encode("ascii")
        origin = headers.get(b"origin")
        valid_host = headers.get(b"host") == expected_host
        valid_origin = origin is None or origin == self.identity["origin"].encode("ascii")
        if not valid_host or not valid_origin or not allowed_request(scope["method"], scope["path"]):
            from starlette.responses import JSONResponse
            return await JSONResponse({"error": {"code": "desktop_rendering_only",
                "message": "This isolated rendering spike does not allow this operation."}}, status_code=403)(scope, receive, send)
        if scope["path"] == IDENTITY_PATH:
            from starlette.responses import JSONResponse
            return await JSONResponse(public_identity(self.identity), headers={"Cache-Control": "no-store",
                "X-InspectorPro-Rendering-Instance": self.instance_id})(scope, receive, send)
        return await self.app(scope, receive, send)


def serve(args, library: Path, identity: dict) -> None:
    startup_checkpoint("serve-entered")
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    startup_checkpoint("snapshot-path-configured")
    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1" or os.environ.get("INSPECTORPRO_LIBRARY_DIR") != str(library):
        raise ValueError("The internal backend must be launched through its scrubbed supervisor")
    startup_checkpoint("scrubbed-environment-verified")
    startup_checkpoint("dependency-paths-starting")
    for package_root in json.loads(os.environ.get("INSPECTORPRO_DESKTOP_PYTHON_SITES", "[]")):
        path = Path(package_root)
        if not path.is_absolute() or not path.is_dir() or path.name != "site-packages":
            raise ValueError("Invalid configured Python dependency directory")
        if str(path) not in sys.path:
            sys.path.append(str(path))
    startup_checkpoint("dependency-paths-completed")
    startup_checkpoint("write-guard-installing")
    install_fixture_write_guard(ROOT, args.data_root)
    startup_checkpoint("write-guard-installed")
    startup_checkpoint("uvicorn-import-starting")
    import uvicorn
    startup_checkpoint("uvicorn-import-completed")
    startup_checkpoint("server-import-starting")
    import server
    startup_checkpoint("server-import-completed")
    startup_checkpoint("server-library-validation-starting")
    if server.LIBRARY_DIR.resolve() != library.resolve():
        raise RuntimeError("Server resolved a different library; refusing to start")
    startup_checkpoint("server-library-validation-completed")
    original_lifespan = server.app.router.lifespan_context

    @asynccontextmanager
    async def lifecycle(app):
        lifespan_completed = False
        startup_checkpoint("application-lifespan-entering")
        try:
            async with original_lifespan(app):
                # The original application startup has completed. This alone
                # does not prove the socket is serving; the parent checks identity.
                startup_checkpoint("application-lifespan-startup-completed")
                try:
                    yield
                finally:
                    startup_checkpoint("application-lifespan-shutdown-starting")
            lifespan_completed = True
            startup_checkpoint("application-lifespan-stopped")
        finally:
            startup_checkpoint("facility-host-close-starting")
            server._FACILITY_LAYOUT_HOST.close()
            startup_checkpoint("facility-host-close-completed")
            startup_checkpoint("agent-memory-close-starting")
            server._reset_agent_memory_runtime_for_tests()
            startup_checkpoint("agent-memory-close-completed")
            startup_checkpoint("skill-route-executor-close-starting")
            server._SKILL_ROUTE_SHADOW_EXECUTOR.shutdown(wait=True, cancel_futures=True)
            startup_checkpoint("skill-route-executor-close-completed")
            startup_checkpoint("viewport-intent-executor-close-starting")
            server._VIEWPORT_INTENT_EXECUTOR.shutdown(wait=True, cancel_futures=True)
            startup_checkpoint("viewport-intent-executor-close-completed")
            if lifespan_completed:
                startup_checkpoint("shutdown-receipt-writing")
                instance_id = os.environ.get("INSPECTORPRO_DESKTOP_INSTANCE_ID", "")
                path = shutdown_receipt_path(args.data_root, instance_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("x", encoding="utf-8") as handle:
                    json.dump({"schemaVersion": 1, "instanceId": instance_id,
                               "status": "lifespan-stopped", "resourcesClosed": True}, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                startup_checkpoint("shutdown-receipt-written")

    server.app.router.lifespan_context = lifecycle
    startup_checkpoint("application-lifespan-hook-installed")
    boundary = RenderingBoundary(server.app, identity, os.environ.get("INSPECTORPRO_DESKTOP_INSTANCE_ID", ""))
    run_options = {"host": "127.0.0.1", "port": args.port, "lifespan": "on", "log_level": "warning",
                   "access_log": False, "timeout_graceful_shutdown": 10}
    startup_checkpoint("uvicorn-configuration-prepared")
    startup_checkpoint("uvicorn-run-starting")
    uvicorn.run(boundary, **run_options)
    startup_checkpoint("uvicorn-run-returned")


def wait_ready(process, identity: dict, seconds: float, instance_id: str) -> None:
    expected = public_identity(identity)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Rendering backend exited before readiness; inspect its isolated log")
        try:
            with opener.open(identity["origin"] + IDENTITY_PATH, timeout=1) as response:
                actual = json.load(response)
                actual_instance = response.headers.get("X-InspectorPro-Rendering-Instance")
            if actual != expected or actual_instance != instance_id:
                raise RuntimeError("Occupied port or backend identity mismatch; refusing to attach")
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
            time.sleep(0.15)
    raise RuntimeError("Rendering backend startup timed out; inspect its isolated log")


def check_http_boundary(origin: str) -> dict[str, int]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks = [("GET", "/", 200), ("GET", "/api/profiles", 200),
              ("GET", "/api/facility-layout-bootstrap", 200),
              ("GET", "/api/bridge/status", 403), ("GET", "/api/admin/memory/health", 403),
              ("POST", "/api/agent/chat", 403), ("POST", "/api/facility-layout-bootstrap", 403)]
    result = {}
    for method, path, expected in checks:
        request = urllib.request.Request(origin + path, method=method)
        try:
            with opener.open(request, timeout=10) as response:
                status = response.status
                response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
        if status != expected:
            raise RuntimeError(f"Rendering HTTP check failed: {method} {path} returned {status}")
        result[f"{method} {path}"] = status
    return result


def stop_child(process, seconds: float = 15) -> None:
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
        process.wait(timeout=seconds)
    except (OSError, subprocess.TimeoutExpired):
        # Only the child we created, never another process found through a port.
        process.terminate()
        process.wait(timeout=5)


def main(argv=None) -> int:
    startup_checkpoint("main-entered")
    startup_checkpoint("arguments-parsing")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--profile-id", default="desktop-spike")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--library-root", type=Path)
    parser.add_argument("--startup-timeout", type=float, default=45)
    parser.add_argument("--check", action="store_true", help="Verify real startup/readiness, then stop the owned backend")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    startup_checkpoint("arguments-parsed")
    if not 1 <= args.startup_timeout <= 120:
        parser.error("startup-timeout must be between 1 and 120 seconds")
    startup_checkpoint("data-root-validation-starting")
    args.data_root = no_links(args.data_root)
    startup_checkpoint("data-root-validation-completed")
    try:
        startup_checkpoint("fixture-preparation-starting")
        library, identity = prepare_fixture(ROOT, args.data_root, args.profile_id, args.port, args.library_root)
        startup_checkpoint("fixture-preparation-completed")
        if args.serve:
            serve(args, library, identity)
            return 0
        def request_stop(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, request_stop)
        if os.name == "nt":
            signal.signal(signal.SIGBREAK, request_stop)
        log_path = args.data_root / "logs" / "backend.log"
        command = [sys.executable, "-u", str(Path(__file__).resolve()), "--serve", "--port", str(args.port),
                   "--profile-id", args.profile_id, "--data-root", str(args.data_root), "--library-root", str(library)]
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        with log_path.open("a", encoding="utf-8") as log:
            child_env = child_environment(dict(os.environ), args.data_root, library)
            instance_id = str(uuid.uuid4())
            child_env["INSPECTORPRO_DESKTOP_INSTANCE_ID"] = instance_id
            process = subprocess.Popen(command, cwd=ROOT, env=child_env,
                                       stdout=log, stderr=log, creationflags=creationflags, startupinfo=startupinfo)
            try:
                wait_ready(process, identity, args.startup_timeout, instance_id)
                checks = check_http_boundary(identity["origin"]) if args.check else None
                print(json.dumps({"status": "ready", "origin": identity["origin"],
                                  "identity": public_identity(identity), "log": str(log_path), "checks": checks}), flush=True)
                if args.check:
                    return 0
                return process.wait()
            finally:
                stop_child(process)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Rendering backend refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
