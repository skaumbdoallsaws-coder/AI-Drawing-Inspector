"""Exercise the real model-import composer with isolated stores and no inference.

Run with an already installed Playwright/Chromium and server dependencies:
    python tools/verify_model_import_chat_browser.py --glb model.glb --out evidence

The real upload/poll routes and worker run unchanged. Only the chat POST is
fulfilled by Playwright. Optional SpatialInspector/Scout lifespan startup is
explicitly disabled; the host is bootstrapped and closed here instead. No
credentials, existing stores, provider calls, or browser downloads are needed.
A failed assertion still writes screenshots/report.json and returns nonzero.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from typing import Any
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PORTS = frozenset({8181, 8480, 8491, 8493})
SAFE_ENV = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS",
            "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "OS"}
IMPORT_PATH = re.compile(r"/api/facility-layouts/[^/]+/[^/]+/model-imports(?:/mi-[0-9a-f]{24}(?:/retry)?)?$")
IMPORT_ID = re.compile(r"mi-[0-9a-f]{24}$")
CHAT_PATHS = frozenset({"/api/agent/chat", "/api/agent/chat/stream", "/api/agent/chat/v2/stream"})
SUCCESS_TEXT = "Browser verification received the model attachments."
EXPECTED_CHECKS = (
    "isolated_bootstrap", "baseline_navigation", "nonfacility_menu_hidden",
    "facility_menu", "glb_ready", "unsupported_obj_refused", "refused_import_available",
    "send_payload_and_clear", "browser_errors", "no_inference", "cleanup",
)


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="ascii", newline="\n")


class Evidence:
    def __init__(self, out: Path):
        self.out = out
        self.data: dict[str, Any] = {
            "schemaVersion": 1, "checks": [], "lookedFor": [], "screenshots": [],
            "baselineErrors": [], "browserErrors": [], "blockedBrowserRequests": [],
            "blockedServerRequests": [], "guardViolations": [], "chatRequests": [],
            "importResponses": [], "routeErrors": [],
        }

    def looking(self, description: str) -> None:
        print("Looking for: " + description, flush=True)
        self.data["lookedFor"].append(description)

    def result(self, name: str, ok: bool, detail: Any) -> None:
        self.data["checks"].append({"name": name, "status": "passed" if ok else "failed", "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + ": " + json.dumps(detail, ensure_ascii=True), flush=True)
        self.save()

    def check(self, name: str, action, *, critical: bool = False):
        try:
            detail = action()
            self.result(name, True, detail)
            return detail
        except Exception as error:
            self.result(name, False, {"error": str(error), "traceback": traceback.format_exc()})
            if critical:
                raise
            return None

    def shot(self, page, name: str) -> None:
        filename = name + ".png"
        page.screenshot(path=str(self.out / filename), animations="disabled", timeout=10000)
        self.data["screenshots"].append(filename)

    def save(self) -> None:
        write_json(self.out / "report.json", self.data)


def configure_environment(data: Path, browser_cache: str | None) -> None:
    """Match managed_backend's flags, dropping inherited keys and live stores."""
    parent = dict(os.environ)
    env = {key: value for key, value in parent.items() if key.upper() in SAFE_ENV}
    system = Path(parent.get("SYSTEMROOT", parent.get("SystemRoot", "C:/Windows")))
    env.update({
        "PATH": os.pathsep.join([str(Path(sys.executable).parent), str(system / "System32"), str(system)]),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHON_DOTENV_DISABLED": "1", "PYTHONUNBUFFERED": "1",
        "TEMP": str(data / "temp"), "TMP": str(data / "temp"), "TMPDIR": str(data / "temp"),
        "LOCALAPPDATA": str(data / "localappdata"), "APPDATA": str(data / "appdata"),
        "USERPROFILE": str(data / "profile"), "HOME": str(data / "profile"),
        "XDG_CACHE_HOME": str(data / "cache"), "HF_HOME": str(data / "hf"),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
        "INSPECTORPRO_MEMORY_V1_MODE": "off", "INSPECTORPRO_FACILITY_PRIVATE_ASSETS": "1",
        "INSPECTORPRO_CODEX_READONLY_PILOT": "1", "INSPECTORPRO_CODEX_EDIT_PREVIEWS": "1",
        "INSPECTORPRO_CODEX_AUTH_MODE": "api_key", "INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE": "0",
        "INSPECTORPRO_CODEX_ALLOW_SUBSCRIPTION_INFERENCE": "0",
        "INSPECTORPRO_PACKAGING_ENABLED": "0", "INSPECTORPRO_CODEX_PACKAGING": "0",
        "INSPECTORPRO_FACILITY_LAYOUT_CONSTRUCTION_SAGE": "0",
    })
    stores = {
        "INSPECTORPRO_LIBRARY_DIR": "library", "INSPECTORPRO_FACILITY_LAYOUT_ROOT": "facility",
        "INSPECTORPRO_METRICS_DB": "metrics.sqlite", "INSPECTORPRO_MEMORY_DB_PATH": "memory.sqlite",
        "INSPECTORPRO_CHAT_FEEDBACK_DB_PATH": "feedback.sqlite",
        "INSPECTORPRO_CODEX_PILOT_ROOT": "codex", "INSPECTORPRO_CODEX_AUTH_ROOT": "unused-auth",
        "INSPECTORPRO_PACKAGING_ROOT": "packaging",
    }
    for name in ("PARTS_MANUAL", "OPERATIONS_MANUAL", "SPECIFICATION_SHEET", "WORK_INSTRUCTION",
                 "INSPECTION_SHEET", "ASSEMBLY_APPEARANCE", "PART_APPEARANCE"):
        stores["INSPECTORPRO_" + name + "_ROOT"] = name.lower()
    for key, relative in stores.items():
        target = data / relative
        (target.parent if target.suffix == ".sqlite" else target).mkdir(parents=True, exist_ok=True)
        env[key] = str(target)
    for name in ("temp", "localappdata", "appdata", "profile", "cache", "hf", "project/static"):
        (data / name).mkdir(parents=True, exist_ok=True)
    # Use the existing browser installation without inheriting the user's profile.
    if browser_cache:
        env["PLAYWRIGHT_BROWSERS_PATH"] = browser_cache
    os.environ.clear()
    os.environ.update(env)
    tempfile.tempdir = str(data / "temp")
    sys.dont_write_bytecode = True
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    from ai_inspector.facility_layout.feature_flags import (
        FACILITY_LAYOUT_FEATURE_FLAGS, FACILITY_DESIGN_LOOP_FEATURE_FLAGS,
    )
    for name in FACILITY_LAYOUT_FEATURE_FLAGS:
        os.environ[name] = "1"
    for name in FACILITY_DESIGN_LOOP_FEATURE_FLAGS:
        os.environ[name] = "0" if name.endswith(("_LAB", "_SAGE")) else "1"


def installed_browser_cache() -> str | None:
    """Locate only installed browser binaries, never a persistent browser profile."""
    explicit = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if explicit:
        return explicit if explicit == "0" else str(Path(explicit).resolve())
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return str(Path(local) / "ms-playwright") if local else None
    if sys.platform == "darwin":
        return str(Path.home() / "Library/Caches/ms-playwright")
    return str(Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "ms-playwright")


class RuntimeGuard:
    """Fail closed on external Python connections and writes outside fresh roots.

    This is an in-process harness guard, not a sandbox claim for native children.
    Chromium also has browser routing/background networking disabled; the real
    import worker retains its own resource and input isolation.
    """
    def __init__(self, data: Path, out: Path, violations: list):
        self.roots = (data.resolve(), out.resolve())
        self.violations = violations
        self.active = True

    def inside(self, target: Path) -> bool:
        return any(target == root or root in target.parents for root in self.roots)

    def deny(self, message: str) -> None:
        self.violations.append(message)
        raise PermissionError(message)

    def file(self, raw: Any, *, writing: bool = False) -> None:
        if not isinstance(raw, (str, bytes, os.PathLike)) or os.fsdecode(raw) == ":memory:":
            return
        text = os.fsdecode(raw)
        if text.upper().rstrip(":") in ("NUL", "\\\\.\\NUL", "/DEV/NULL"):   # the null device
            return
        if text.startswith("\\\\?\\"):   # Windows extended-length path prefix
            text = text[4:]
        target = Path(text).resolve()
        if self.inside(target):
            return
        if writing:
            self.deny("Write outside isolated roots: " + str(target))
        parts = {part.lower() for part in target.parts}
        if (parts.intersection({"ui-data", ".runtime"}) or target.name.lower().startswith(".env")
                or target.name.lower() in {"auth.json", "accounts.sqlite", "cookies", "cookies.sqlite", ".netrc", "_netrc"}):
            self.deny("Protected data read refused: " + str(target))

    def audit(self, event: str, args: tuple) -> None:
        if not self.active:
            return
        if event == "open":
            mode, flags = args[1], args[2]
            writing = ((isinstance(mode, str) and any(c in mode for c in "wax+"))
                       or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            self.file(args[0], writing=bool(writing))
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime", "sqlite3.connect"}:
            self.file(args[0], writing=True)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            self.file(args[0], writing=True)
            self.file(args[1], writing=True)
        elif event in {"os.listdir", "os.scandir"}:
            self.file(args[0])
        elif event == "socket.connect":
            address = args[1]
            if isinstance(address, tuple):
                if address[0] not in {"127.0.0.1", "::1"} or address[1] in FORBIDDEN_PORTS:
                    self.deny("Non-harness network connection refused: " + str(address))
            else:
                self.deny("Non-IP network connection refused")
        elif event == "socket.getaddrinfo" and args[0] not in {None, "localhost", "127.0.0.1", "::1"}:
            self.deny("External DNS lookup refused: " + str(args[0]))


@contextmanager
def hidden_children():
    original = subprocess.Popen
    class HiddenPopen(original):
        def __init__(self, *args, **kwargs):
            if os.name == "nt":
                kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)
    subprocess.Popen = HiddenPopen
    try:
        yield
    finally:
        subprocess.Popen = original


def reserve_listener() -> socket.socket:
    for _ in range(32):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        if listener.getsockname()[1] not in FORBIDDEN_PORTS:
            return listener
        listener.close()
    raise RuntimeError("Could not reserve a free port outside 8181/8480/8491/8493")


def allowed_server_request(method: str, path: str) -> bool:
    if method == "POST":
        return bool(IMPORT_PATH.fullmatch(path))
    if method not in {"GET", "HEAD"}:
        return False
    if path == "/" or path.startswith(("/static/", "/generated/")):
        return True
    if path in {"/api/facility-layout-bootstrap", "/api/industrial-assets", "/api/profiles",
                "/api/agent/chat/streaming-status", "/api/agent/conversations", "/api/admin/memory/health",
                "/api/documentation/types", "/api/documentation/templates", "/api/library-machines",
                "/api/internal/agent-skills/status"}:
        return True
    return (path.startswith(("/api/facility-layouts/", "/api/facility-shells/", "/api/policy-sets/",
                             "/api/vehicle-profiles/", "/api/training/facility-layout/knowledge/"))
            or (path.startswith("/api/training/process-map-") and path.endswith("-status")))


def import_application(data: Path, evidence: Evidence, hosts: list):
    """Relocate constructor-only paths before the real server creates its host."""
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    from ai_inspector.facility_layout import host as host_module
    project = data / "project"
    catalog = project / host_module.PRIVATE_ASSET_MANIFEST
    catalog.parent.mkdir(parents=True, exist_ok=True)
    write_json(catalog, {"schemaVersion": 1, "assets": [], "summary": {"total": 0}})
    original_host = host_module.LocalFacilityLayoutHost

    class IsolatedHost(original_host):
        def __init__(self, root, **kwargs):
            kwargs.update(private_asset_root=project, private_assets=True,
                          process_map_root=project / "generated/training",
                          facility_planning_root=project / "generated/facility_planning")
            super().__init__(data / "facility", **kwargs)
            hosts.append(self)

    host_module.LocalFacilityLayoutHost = IsolatedHost
    try:
        server = importlib.import_module("server")
    finally:
        host_module.LocalFacilityLayoutHost = original_host
    # Non-environment-backed generated paths must also remain private. Source,
    # schemas and static code continue to come from this worktree.
    for name, value in list(vars(server).items()):
        if isinstance(value, Path) and value.is_absolute():
            for base, replacement in ((ROOT / "generated", project / "generated"),
                                      (ROOT / ".runtime", data / "runtime")):
                if value == base or base in value.parents:
                    setattr(server, name, replacement / value.relative_to(base))
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from ai_inspector.revalidated_static import RevalidatedStaticFiles
    for route in server.app.routes:
        if getattr(route, "path", None) == "/static":
            route.app = StaticFiles(directory=str(ROOT / "static"))
        elif getattr(route, "path", None) == "/generated":
            route.app = RevalidatedStaticFiles(directory=str(project / "generated"))
    def isolated_file_response(path, *args, **kwargs):
        candidate = Path(path)
        if not candidate.is_absolute() and candidate.parts[:1] == ("static",):
            path = ROOT / candidate
        return FileResponse(path, *args, **kwargs)
    server.FileResponse = isolated_file_response
    # /api/profiles lazily initializes the model even with lifespan disabled.
    # Retain its real disk-only fallback against the empty isolated library.
    server._ensure_inspector = lambda: None

    @server.app.middleware("http")
    async def refuse_unneeded_endpoints(request, call_next):
        if not allowed_server_request(request.method, request.url.path):
            evidence.data["blockedServerRequests"].append({"method": request.method, "path": request.url.path})
            return JSONResponse(status_code=503, content={"error": {
                "code": "browser_verifier_endpoint_blocked", "message": "This isolated check does not run this endpoint."}})
        return await call_next(request)

    # Lifespan is off below: never instantiate SpatialInspector or Scout's browser.
    binding = server._FACILITY_LAYOUT_HOST.ensure_bootstrap()
    evidence.data["runtime"] = {
        "dataRoot": str(data), "privateAssetRoot": str(project), "lifespan": "off",
        "siteId": binding["siteId"], "layoutId": binding["layoutId"],
        "flags": {k: v for k, v in os.environ.items() if k.startswith("INSPECTORPRO_")},
    }
    return server, binding


def chat_reply(path: str) -> tuple[str, str]:
    final = {"response": SUCCESS_TEXT, "tool_calls": [], "tool_call_count": 0, "registeredAssets": [],
             "tool_source": "codex_readonly_pilot", "facility_action_mode": "READ_ONLY",
             "facility_runtime_policy": {"mode": "READ_ONLY", "allowedToolNames": []},
             "codex_inspection": {"readOnly": True, "checkedLayout": False, "engineeringChanges": 0,
                                  "verifiedToolCalls": [], "completion": "inspection_response"}}
    if path == "/api/agent/chat":
        return "application/json", json.dumps(final)
    events = [
        {"event": "response_started", "message_id": "browser-check-message"},
        {"event": "text_delta", "text": SUCCESS_TEXT},
        {"event": "response_completed", "final": final},
    ]
    body = "".join("data: " + json.dumps({"v": 1, "response_id": "browser-check-response", "seq": seq, **event})
                   + "\n\n" for seq, event in enumerate(events, 1))
    return "text/event-stream", body


OBSERVER = r"""() => {
    window.__modelImportStates = [];
    const remember = node => {
        if (!(node instanceof Element)) return;
        const rows = node.matches('.agent-model-chip') ? [node] : node.querySelectorAll('.agent-model-chip');
        for (const row of rows) window.__modelImportStates.push({
            name: row.querySelector('strong')?.textContent, state: row.dataset.state,
            text: row.textContent, at: performance.now(),
            sendDisabled: document.querySelector('#agentSendBtn')?.disabled,
            sendText: document.querySelector('#agentSendBtn')?.textContent
        });
    };
    new MutationObserver(changes => {
        for (const change of changes) for (const node of change.addedNodes) remember(node);
    }).observe(document, {childList: true, subtree: true});
}"""


def browser_page(browser, base: str, evidence: Evidence, *, baseline: bool):
    context = browser.new_context(viewport={"width": 1500, "height": 1000}, service_workers="block")
    page = context.new_page()
    page.set_default_timeout(20000)
    phase = "baseline" if baseline else "attachments"
    errors = evidence.data["baselineErrors" if baseline else "browserErrors"]
    page.on("pageerror", lambda error: errors.append({"kind": "pageerror", "text": str(error)}))
    page.on("console", lambda message: errors.append({"kind": "console", "text": message.text,
              "url": message.location.get("url", "")}) if message.type == "error" else None)
    def boundary(route):
        url = urlsplit(route.request.url)
        if (url.scheme, url.netloc) == ("http", urlsplit(base).netloc):
            route.continue_()
        else:
            evidence.data["blockedBrowserRequests"].append({"phase": phase, "url": route.request.url})
            route.abort("blockedbyclient")
    context.route("**/*", boundary)
    if hasattr(context, "route_web_socket"):
        context.route_web_socket("**/*", lambda ws: ws.close())

    def chat(route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method != "POST" or path not in CHAT_PATHS:
            route.fallback()
            return
        payload = request.post_data_json
        evidence.data["chatRequests"].append({"phase": phase, "path": path,
            "message": payload.get("message"), "agent_type": payload.get("agent_type"),
            "attachments": payload.get("attachments"),
            "binding": payload.get("inspection_context", {}).get("attachments", {}).get("facility_layout")})
        content_type, body = chat_reply(path)
        route.fulfill(status=200, content_type=content_type, body=body,
                      headers={"Cache-Control": "no-store"})
    page.route("**/api/agent/chat**", chat)
    if not baseline:
        page.add_init_script("(" + OBSERVER + ")()")
        captured = set()
        def import_route(route):
            request = route.request
            if IMPORT_PATH.fullmatch(urlsplit(request.url).path):
                state = "uploading" if request.method == "POST" else "checking"
                if state not in captured:
                    try:
                        if page.locator('.agent-model-chip[data-state="' + state + '"]').count():
                            evidence.shot(page, "03-" + state)
                            captured.add(state)
                    except Exception as error:
                        evidence.data["routeErrors"].append(str(error))
            route.fallback()
        page.route("**/model-imports**", import_route)
        def imported(response):
            if not IMPORT_PATH.fullmatch(urlsplit(response.url).path):
                return
            try:
                record = response.json()
                evidence.data["importResponses"].append({"path": urlsplit(response.url).path,
                    "method": response.request.method, "httpStatus": response.status, "record": record})
            except Exception as error:
                evidence.data["routeErrors"].append("Import response: " + str(error))
        page.on("response", imported)
    return context, page


def open_chat(page, evidence: Evidence) -> None:
    evidence.looking("window._selectAgent('deviation-analyst'); #rightRailAgent; #agentPanel.open; #agentInput")
    page.wait_for_function("() => typeof window._selectAgent === 'function'")
    page.evaluate("() => window._selectAgent('deviation-analyst')")
    if not page.locator("#agentPanel").evaluate("el => el.classList.contains('open')"):
        page.locator("#rightRailAgent").click()
    page.locator("#agentInput").wait_for(state="visible")


def navigate(page, base: str, binding: dict, evidence: Evidence, *, baseline: bool) -> dict:
    evidence.looking("real /?facilityLayoutId=" + binding["layoutId"] + "; Workflows tab; #trainingTypeRibbonSelect")
    page.goto(base + "/?facilityLayoutId=" + binding["layoutId"], wait_until="domcontentloaded", timeout=60000)
    evidence.looking('role=tab[data-tab="drawing"] before opening nonfacility chat')
    page.locator('[role="tab"][data-tab="drawing"]').click()
    open_chat(page, evidence)
    if baseline:
        hidden = page.locator("#agentCameraBtn").evaluate("el => el.hidden")
        evidence.result("nonfacility_menu_hidden", hidden, {"buttonHiddenBeforeFacility": hidden})
        evidence.shot(page, "00-nonfacility")
    page.get_by_role("tab", name="Workflows", exact=True).click()
    page.locator("#trainingTypeRibbonSelect").wait_for(state="attached")
    # This production select backs the custom ribbon combobox. Existing app
    # verifiers use the same native change event; no workspace state is injected.
    page.locator("#trainingTypeRibbonSelect").evaluate("""el => {
        if (![...el.options].some(option => option.value === 'facility_layout'))
            throw new Error('No facility_layout option in #trainingTypeRibbonSelect');
        el.value = 'facility_layout'; el.dispatchEvent(new Event('change', {bubbles:true}));
    }""")
    evidence.looking("window._trainFacilityLayoutAuthoringApp: loaded session, saved revision, matching site/layout, manualAuthoring")
    page.wait_for_function("""binding => {
        const app = window._trainFacilityLayoutAuthoringApp;
        const state = app?.session?.getState();
        return state?.loaded && state.baseRevision && app?.workspace?.capabilities.manualAuthoring
            && !app.workspace.suspended && !app.workspace.destroyed
            && app.transport.siteId === binding.siteId && app.transport.layoutId === binding.layoutId;
    }""", arg={"siteId": binding["siteId"], "layoutId": binding["layoutId"]}, timeout=120000)
    open_chat(page, evidence)
    page.locator("#agentCameraBtn").wait_for(state="visible")
    # Give baseline boot-time promises and the rendering loop time to settle.
    page.wait_for_timeout(2000)
    evidence.shot(page, "01-baseline-facility" if baseline else "02-facility")
    return {"siteId": binding["siteId"], "layoutId": binding["layoutId"]}


def chip(page, name: str) -> dict | None:
    return page.locator("#agentModelChips .agent-model-chip").evaluate_all("""(rows, name) => {
        const row = rows.find(row => row.querySelector('strong')?.textContent === name);
        return row ? {state: row.dataset.state, text: row.textContent} : null;
    }""", name)


def attach(page, file: Path, evidence: Evidence, screenshot: str) -> dict:
    evidence.looking("#agentModelFileInput -> .agent-model-chip strong = " + file.name + "; terminal data-state within 60 seconds")
    started = time.monotonic()
    try:
        page.locator("#agentModelFileInput").set_input_files(str(file))
        remaining = max(1, int((60 - (time.monotonic() - started)) * 1000))
        page.wait_for_function("""name => [...document.querySelectorAll('#agentModelChips .agent-model-chip')].some(
            row => row.querySelector('strong')?.textContent === name && ['ready','refused','failed','busy'].includes(row.dataset.state))
        """, arg=file.name, timeout=remaining)
    finally:
        elapsed = time.monotonic() - started
        result = chip(page, file.name) or {"state": "missing", "text": "No chip was rendered"}
        result["elapsedSeconds"] = round(elapsed, 3)
        result["states"] = page.evaluate("name => window.__modelImportStates.filter(row => row.name === name)", file.name)
        evidence.data.setdefault("files", {})[file.name] = result
        evidence.shot(page, screenshot)
    require(elapsed <= 60, "Attachment did not finish within 60 seconds")
    return result


def ordered_states(rows: list[dict], expected: list[str]) -> bool:
    index = 0
    for row in rows:
        if index < len(expected) and row["state"] == expected[index]:
            index += 1
    return index == len(expected)


def ready_file(page, file: Path, evidence: Evidence) -> dict:
    result = attach(page, file, evidence, "04-glb-result")
    require(result["state"] == "ready", "GLB did not become ready: " + str(result))
    require(ordered_states(result["states"], ["uploading", "checking", "ready"]),
            "Missing real DOM uploading -> checking -> ready transitions: " + str(result["states"]))
    pending = [row for row in result["states"] if row["state"] in {"uploading", "checking"}]
    require(any(row["sendDisabled"] and "Uploading..." in row["sendText"] for row in pending),
            "Send did not show disabled Uploading... while the import was pending")
    return result


def refused_file(page, file: Path, evidence: Evidence, screenshot: str) -> dict:
    result = attach(page, file, evidence, screenshot)
    require(result["state"] == "refused" and bool(result["text"].split("Refused:")[-1].strip())
            and "Refused:" in result["text"], "Expected refused chip with a reason; observed " + str(result))
    return result


def send(page, evidence: Evidence, binding: dict) -> dict:
    terminal = {item["record"].get("id", item["record"].get("importId")): item["record"]
                for item in evidence.data["importResponses"] if item["httpStatus"] < 300}
    states = {record.get("state") for record in terminal.values()}
    require({"ready", "refused"} <= states, "Need real ready and refused import records before sending")
    expected = [{"kind": "model-import", "importId": import_id} for import_id, record in terminal.items()
                if record.get("state") in {"ready", "refused"}]
    require(all(IMPORT_ID.fullmatch(item["importId"] or "") for item in expected), "Invalid import IDs from real routes")
    evidence.looking("#agentInput, #agentSendBtn; intercepted POST /api/agent/chat/v2/stream (or /api/agent/chat)")
    message = "Check these attached models for the facility library."
    page.locator("#agentInput").fill(message)
    evidence.shot(page, "07-before-send")
    page.locator("#agentSendBtn").click()
    page.wait_for_function("() => document.querySelector('#agentMessages')?.textContent.includes(" + json.dumps(SUCCESS_TEXT) + ")")
    page.wait_for_function("() => document.querySelectorAll('#agentModelChips .agent-model-chip').length === 0")
    evidence.shot(page, "08-sent-chips-cleared")
    requests = evidence.data["chatRequests"]
    require(len(requests) == 1 and requests[0]["phase"] == "attachments", "Unexpected chat POST count: " + str(requests))
    actual = requests[0]
    require(actual["message"] == message and actual["agent_type"] == "deviation-analyst", "Unexpected chat message/agent")
    require(actual["attachments"] == expected, "Attachment payload mismatch: " + str({"expected": expected, "actual": actual}))
    reference = actual["binding"] or {}
    require(all(reference.get(key) == binding[key] for key in ("siteId", "layoutId")), "Chat was not bound to the bootstrapped layout")
    return {"attachments": expected, "path": actual["path"], "chipsCleared": True, "mockResponse": SUCCESS_TEXT}


def compare_errors(evidence: Evidence, base: str) -> dict:
    def key(item):
        return json.dumps(item, sort_keys=True).replace(base, "<loopback>")
    baseline = Counter(key(item) for item in evidence.data["baselineErrors"])
    current = Counter(key(item) for item in evidence.data["browserErrors"])
    new = {error: count for error, count in current.items() if error not in baseline}
    detail = {"baselineNote": "Same real page and navigation in a fresh context, without adding files or sending a turn.",
              "baselineAllowlist": dict(baseline), "attachmentRun": dict(current), "newErrors": new}
    evidence.data["errorComparison"] = detail
    require(not new, "New browser errors: " + json.dumps(new))
    require(not evidence.data["routeErrors"], "Harness route errors: " + str(evidence.data["routeErrors"]))
    return detail


def exercise(browser, base: str, binding: dict, data: Path, glb: Path, evidence: Evidence) -> None:
    context, page = browser_page(browser, base, evidence, baseline=True)
    try:
        evidence.check("baseline_navigation", lambda: navigate(page, base, binding, evidence, baseline=True), critical=True)
    finally:
        context.close()
    context, page = browser_page(browser, base, evidence, baseline=False)
    try:
        navigate(page, base, binding, evidence, baseline=False)
        def menu():
            evidence.looking('#agentCameraBtn -> role=menuitem name="Attach 3D model (.glb, .zip)"')
            page.locator("#agentCameraBtn").click()
            item = page.get_by_role("menuitem", name="Attach 3D model (.glb, .zip)", exact=True)
            item.wait_for(state="visible")
            require(page.locator("#agentModelFileInput").evaluate("el => el.hidden"), "File input should be hidden")
            evidence.shot(page, "02-attachment-menu")
            text = item.text_content()   # read while the menu is open: a closed menu's items are hidden
            page.locator("#agentCameraBtn").click()
            return {"menuItem": text, "fileInputHidden": True}
        evidence.check("facility_menu", menu, critical=True)
        evidence.check("glb_ready", lambda: ready_file(page, glb, evidence))
        obj = data / "unsupported.obj"
        obj.write_text("o unsupported\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="ascii", newline="\n")
        def unsupported():
            # A raw .obj is refused by type at upload (no import record exists, so nothing is sent for it): the chip
            # ends "failed" with the reason, which is the intended behaviour (Claude, 2026-11-09).
            result = attach(page, obj, evidence, "05-unsupported-obj")
            require(result["state"] in ("refused", "failed") and "glTF or GLB" in result["text"],
                    "Expected the unsupported file to be explained; observed " + str(result))
            return result
        evidence.check("unsupported_obj_refused", unsupported)
        def refusal():
            observed = chip(page, obj.name)
            if observed and observed["state"] == "refused":
                return observed
            # MI4 currently rejects raw .obj locally as failed (no import ID).
            # Keep that failed assertion above, then independently cover a real
            # worker refusal via an allowed ZIP containing only unsupported OBJ.
            archive = data / "unsupported-model.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.write(obj, arcname="unsupported.obj")
            return refused_file(page, archive, evidence, "06-server-refused")
        evidence.check("refused_import_available", refusal)
        evidence.check("send_payload_and_clear", lambda: send(page, evidence, binding))
        page.wait_for_timeout(1000)
        evidence.check("browser_errors", lambda: compare_errors(evidence, base))
    except Exception:
        try:
            evidence.shot(page, "99-failure")
            evidence.data["uiDiagnostic"] = page.evaluate("""() => ({
                title: document.title, url: location.href,
                selectors: ['agentPanel','agentCameraBtn','agentModelFileInput','trainingTypeRibbonSelect','agentSendBtn']
                    .map(id => { const el = document.getElementById(id); return {id, exists:!!el, hidden:el?.hidden,
                        classes:el?.className, text:el?.textContent?.slice(0,500)}; }),
                chips: window.__modelImportStates || []
            })""")
        except Exception as error:
            evidence.data["diagnosticError"] = str(error)
        raise
    finally:
        context.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--glb", type=Path, required=True, help="Existing supported GLB; uploaded unchanged to the real worker")
    parser.add_argument("--out", type=Path, required=True, help="Evidence directory (screenshots and report.json)")
    args = parser.parse_args(argv)
    glb, out = args.glb.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    evidence = Evidence(out)
    old_cwd, old_env, old_temp = Path.cwd(), dict(os.environ), tempfile.tempdir
    temporary = None
    hosts: list = []
    guard = listener = application = http_server = thread = None
    browser_cache = installed_browser_cache()
    sys.path.insert(0, str(ROOT))
    try:
        require(glb.is_file() and glb.suffix.lower() == ".glb", "--glb must name an existing .glb file")
        require(glb.stat().st_size <= 128 * 1024 * 1024, "--glb exceeds the 128 MiB upload cap")
        temporary = tempfile.TemporaryDirectory(prefix="model-chat-")
        data = Path(temporary.name).resolve()
        guard = RuntimeGuard(data, out, evidence.data["guardViolations"])
        sys.addaudithook(guard.audit)
        configure_environment(data, browser_cache)
        copied = data / "browser-model.glb"
        shutil.copyfile(glb, copied)
        evidence.data["input"] = {"name": glb.name, "bytes": copied.stat().st_size}
        os.chdir(data / "project")
        with hidden_children():
            application, binding = import_application(data, evidence, hosts)
            import uvicorn
            from playwright.sync_api import sync_playwright
            listener = reserve_listener()
            port = listener.getsockname()[1]
            require(port not in FORBIDDEN_PORTS, "Reserved port is forbidden")
            base = "http://127.0.0.1:" + str(port)
            evidence.data["baseUrl"] = base
            http_server = uvicorn.Server(uvicorn.Config(application.app, host="127.0.0.1", port=port,
                                                       lifespan="off", log_level="error", access_log=False))
            def serve():
                try:
                    http_server.run(sockets=[listener])
                except BaseException as error:
                    evidence.data["serverError"] = repr(error)
            thread = threading.Thread(target=serve, name="model-import-browser-server", daemon=True)
            thread.start()
            deadline = time.monotonic() + 30
            while not http_server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            require(http_server.started, "Real server failed to start: " + str(evidence.data.get("serverError", "timeout")))
            evidence.result("isolated_bootstrap", True, {"baseUrl": base, "siteId": binding["siteId"], "layoutId": binding["layoutId"]})
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader",
                    "--disable-background-networking", "--disable-component-update", "--disable-domain-reliability",
                    "--no-proxy-server"])
                try:
                    exercise(browser, base, binding, data, copied, evidence)
                finally:
                    browser.close()
    except (Exception, KeyboardInterrupt) as error:
        evidence.data["fatalError"] = {"error": str(error), "traceback": traceback.format_exc()}
        print("FAIL: " + str(error), flush=True)
    finally:
        cleanup_errors = []
        if http_server is not None:
            http_server.should_exit = True
        if thread is not None:
            thread.join(timeout=15)
            if thread.is_alive():
                http_server.force_exit = True
                thread.join(timeout=5)
            if thread.is_alive():
                cleanup_errors.append("Server thread did not stop after should_exit/force_exit")
        for host in hosts:
            try:
                host.close()
            except Exception as error:
                cleanup_errors.append("Host/worker close: " + str(error))
        if listener is not None:
            listener.close()
        evidence.result("no_inference", not evidence.data["guardViolations"] and not any(
            item["path"] in CHAT_PATHS for item in evidence.data["blockedServerRequests"]),
            {"pythonGuardViolations": evidence.data["guardViolations"],
             "chatReachedServer": [item for item in evidence.data["blockedServerRequests"] if item["path"] in CHAT_PATHS],
             "paidInferenceEnabled": False, "optionalModelLifespanStarted": False})
        os.chdir(old_cwd)
        if temporary is not None:
            try:
                temporary.cleanup()
            except Exception as error:
                cleanup_errors.append("Temporary store cleanup: " + str(error))
        if guard is not None:
            guard.active = False
        os.environ.clear()
        os.environ.update(old_env)
        tempfile.tempdir = old_temp
        evidence.result("cleanup", not cleanup_errors, {"errors": cleanup_errors, "serverThreadAlive": bool(thread and thread.is_alive())})
        completed = {check["name"] for check in evidence.data["checks"]}
        for name in EXPECTED_CHECKS:
            if name not in completed:
                evidence.data["checks"].append({"name": name, "status": "not_run", "detail": "Earlier step failed; see fatalError/lookedFor."})
        evidence.data["passed"] = not evidence.data.get("fatalError") and all(
            check["status"] == "passed" for check in evidence.data["checks"])
        evidence.save()
    print("Report: " + str(out / "report.json"), flush=True)
    return 0 if evidence.data["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
