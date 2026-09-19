"""User-run, bounded inert-shell then full-application rendering verification.

Electron is launched directly: there is no Node or backend supervisor process
to terminate while leaving its actual application child behind. This tool does
not elevate, change policy, disable Chromium sandboxing, or download runtimes.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
spec = importlib.util.spec_from_file_location("rendering_fixture_launcher", Path(__file__).with_name("run-rendering-backend.py"))
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
CHECKS = frozenset({"backendIdentity", "inputLock", "markup", "isolation", "firstPaint",
                    "wideCapture", "narrowCapture", "lifecycleClose"})
FIXTURE_HTML = b'''<!doctype html><html><head><title>InspectorPro fixture</title></head><body>
<main data-inspectorpro-rendering-fixture="true"><h1>InspectorPro desktop acceptance fixture</h1>
<button id="edit">Edit</button><p>Input must be locked. This is a test page, not the product.</p></main><svg xmlns="http://www.w3.org/2000/svg" id="desktop-fixture-svg" width="24" height="24" viewBox="0 0 24 24" tabindex="0" role="img" aria-label="Non-HTML input-lock fixture"><circle cx="12" cy="12" r="9" fill="#286fba"/></svg><script>(() => { const svg = document.getElementById("desktop-fixture-svg"); svg.focus(); const baseline = { svgFocusable: document.activeElement === svg }; svg.blur(); svg.setAttribute("inert", ""); svg.focus(); baseline.svgAttributeStillFocusable = document.activeElement === svg; svg.blur(); svg.removeAttribute("inert"); window.__desktopFixtureFocusBaseline = Object.freeze(baseline); })();</script></body></html>'''


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_electron(desktop: Path = DESKTOP) -> dict:
    requested = json.loads((desktop / "package.json").read_text(encoding="utf-8"))["devDependencies"]["electron"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", requested):
        raise ValueError("Desktop Electron dependency must be pinned to an exact release")
    package = desktop / "node_modules" / "electron"
    installed = json.loads((package / "package.json").read_text(encoding="utf-8"))["version"]
    version = (package / "dist" / "version").read_text(encoding="utf-8").strip()
    executable_name = (package / "path.txt").read_text(encoding="utf-8").strip()
    if installed != requested or version != requested:
        raise ValueError("Installed Electron package/binary release does not match the exact pin")
    if executable_name != "electron.exe":
        raise ValueError("This Windows rendering check requires the installed electron.exe path")
    executable = backend.no_links(package / "dist" / executable_name)
    if not executable.is_file():
        raise ValueError("Pinned Electron executable is missing; runtime installation is a separate step")
    return {"executable": str(executable), "version": requested, "sha256": file_hash(executable)}


def spawn_options():
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0}
    if os.name == "nt":
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
        options["startupinfo"] = info
    return options


def electron_environment(parent, output: Path):
    env = dict(parent)
    for name in ("ELECTRON_RUN_AS_NODE", "ELECTRON_OVERRIDE_DIST_PATH", "NODE_OPTIONS"):
        env.pop(name, None)
    env["ELECTRON_ENABLE_LOGGING"] = "1"
    env["INSPECTORPRO_DESKTOP_SMOKE_OUTPUT"] = str(output)
    return env


@contextmanager
def inert_fixture(output: Path):
    identity = {"schemaVersion": 1, "product": "InspectorPro", "mode": "rendering-spike",
                "backendId": str(uuid.uuid4()), "storeId": str(uuid.uuid4()), "profileId": "inert-rendering-check",
                "researchBrowsing": False, "interactive": False}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == backend.IDENTITY_PATH:
                content, mime, status = json.dumps(identity).encode(), "application/json", 200
            elif self.path == "/":
                content, mime, status = FIXTURE_HTML, "text/html; charset=utf-8", 200
            else:
                content, mime, status = b"Rendering fixture operation denied", "text/plain", 403
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="inert-rendering-fixture")
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    marker = output / "identity.json"
    write_json(marker, {**identity, "origin": origin})
    try:
        yield {"identity": identity, "origin": origin, "marker": marker}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if thread.is_alive():
            raise RuntimeError("Inert fixture server shutdown could not be confirmed")


def validate_window_size_policy(report: dict) -> None:
    """Recompute integer DIP geometry independently of Electron's policy helper."""
    policy = report.get("windowSizePolicy")
    fields = {"revision", "display", "nominalWide", "nominalNarrow", "minimum", "availableWorkArea",
              "wide", "narrow", "wideBounds", "exactWide"}
    if not isinstance(policy, dict) or set(policy) != fields or policy.get("revision") != "work-area-v1":
        raise ValueError("Electron window-size policy is missing or unsupported")
    display = policy.get("display")
    if not isinstance(display, dict) or set(display) != {"id", "bounds", "workArea", "scaleFactor"}:
        raise ValueError("Electron window-size policy has invalid display metadata")
    safe_integer_limit = 2 ** 53 - 1
    def js_length(value):
        return len(value.encode("utf-16-le", errors="surrogatepass")) // 2
    display_id = display["id"]
    if not ((type(display_id) is int and abs(display_id) <= safe_integer_limit)
            or (isinstance(display_id, str) and 0 < js_length(display_id) <= 128)):
        raise ValueError("Electron display identity must be a safe integer or bounded nonempty string")
    def number(value):
        try:
            return type(value) in {int, float} and math.isfinite(value)
        except OverflowError:
            return False
    if not number(display["scaleFactor"]) or display["scaleFactor"] <= 0:
        raise ValueError("Electron display scale factor must be positive and finite")
    def rectangle(value, *, integer=False):
        if (not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}
            or not all(type(item) is int if integer else number(item) for item in value.values())
            or value["width"] <= 0 or value["height"] <= 0):
            return False
        right, bottom = value["x"] + value["width"], value["y"] + value["height"]
        if not number(right) or not number(bottom):
            return False
        limits = (math.floor(value["x"]), math.floor(value["y"]), math.ceil(right), math.ceil(bottom))
        return all(abs(item) <= safe_integer_limit for item in limits)
    if not rectangle(display["bounds"]) or not rectangle(display["workArea"]):
        raise ValueError("Electron display bounds/work area are invalid")
    work, display_bounds = display["workArea"], display["bounds"]
    if (work["x"] < display_bounds["x"] or work["y"] < display_bounds["y"]
        or work["x"] + work["width"] > display_bounds["x"] + display_bounds["width"]
        or work["y"] + work["height"] > display_bounds["y"] + display_bounds["height"]):
        raise ValueError("Electron display work area must be contained in its display bounds")
    right = work["x"] + work["width"]
    bottom = work["y"] + work["height"]
    if not math.isfinite(right) or not math.isfinite(bottom):
        raise ValueError("Electron display work area exceeds finite coordinate bounds")
    left, top = math.ceil(work["x"]), math.ceil(work["y"])
    available = {"x": left, "y": top, "width": math.floor(right) - left, "height": math.floor(bottom) - top}
    def vector(value):
        return isinstance(value, list) and len(value) == 2 and all(type(item) is int for item in value)
    for key, expected in (("nominalWide", [1440, 960]), ("nominalNarrow", [900, 700]), ("minimum", [800, 600])):
        if not vector(policy[key]) or policy[key] != expected:
            raise ValueError("Electron nominal/minimum DIP window policy was changed")
    if available["width"] < 800 or available["height"] < 600:
        raise ValueError("Electron display work area is smaller than the minimum 800x600 DIP window")
    if not rectangle(policy["availableWorkArea"], integer=True) or policy["availableWorkArea"] != available:
        raise ValueError("Electron available work area is not the canonical integer DIP rectangle")
    # Electron workArea is already expressed in DIPs. scaleFactor is metadata;
    # applying it here would double-scale the permitted window dimensions.
    wide = [min(1440, available["width"]), min(960, available["height"])]
    narrow = [min(900, available["width"]), min(700, available["height"])]
    if wide == narrow:
        raise ValueError("Electron wide and narrow rendering stages must use distinct sizes")
    if any(not vector(policy[key]) or policy[key] != expected for key, expected in (("wide", wide), ("narrow", narrow))):
        raise ValueError("Electron fitted window sizes do not match the canonical work-area plan")
    bounds = {"x": left + (available["width"] - wide[0]) // 2,
              "y": top + (available["height"] - wide[1]) // 2, "width": wide[0], "height": wide[1]}
    if not rectangle(policy["wideBounds"], integer=True) or policy["wideBounds"] != bounds:
        raise ValueError("Electron wide window bounds are not centered in the canonical work area")
    exact = wide == [1440, 960]
    if type(policy["exactWide"]) is not bool or policy["exactWide"] != exact:
        raise ValueError("Electron exact-wide claim disagrees with its calculated work-area plan")
    captures = report.get("captures")
    if not isinstance(captures, dict):
        raise ValueError("Electron window policy has no actual capture sizes")
    for key, expected in (("wide", wide), ("narrow", narrow)):
        capture = captures.get(key)
        actual = capture.get("outerSize") if isinstance(capture, dict) else None
        if (not isinstance(actual, dict) or set(actual) != {"width", "height"}
            or type(actual["width"]) is not int or type(actual["height"]) is not int
            or actual != {"width": expected[0], "height": expected[1]}):
            raise ValueError("Electron actual capture size does not exactly match its calculated DIP plan")
    reference = report.get("referenceWideCapture")
    if (not isinstance(reference, dict) or set(reference) - {"requestedOuterSize", "status", "reason"}
        or not vector(reference.get("requestedOuterSize")) or reference["requestedOuterSize"] != [1440, 960]):
        raise ValueError("Electron nominal-wide reference capture evidence is missing or invalid")
    if reference.get("status") != ("passed" if exact else "not-exercised"):
        raise ValueError("Electron nominal-wide reference capture claim does not match the actual window")
    if exact and report.get("checks", {}).get("wideCapture") != "passed":
        raise ValueError("Electron nominal-wide reference capture has not passed its actual capture check")
    if not exact:
        reason = reference.get("reason")
        if (not isinstance(reason, str) or not reason.strip() or js_length(reason) > 1024
            or not re.search(r"work[\s-]*area", reason, re.IGNORECASE)):
            raise ValueError("An unexercised nominal-wide capture must identify the work area limitation")


def validate_input_lock_snapshot(evidence: dict) -> None:
    """An acknowledgement alone cannot replace current native root evidence."""
    if not isinstance(evidence, dict):
        raise ValueError("Electron current input-lock evidence is missing")
    count = evidence.get("bodyChildren")
    lock = evidence.get("lockEvidence")
    diagnostics = evidence.get("preloadLockDiagnostics")
    if (type(count) is not int or not 1 <= count <= 2 ** 53 - 1 or evidence.get("frozen") is not True
        or not isinstance(lock, dict) or lock.get("uniqueBanner") is not True
        or type(lock.get("totalRoots")) is not int or lock["totalRoots"] != count
        or type(lock.get("unlockedRootCount")) is not int or lock["unlockedRootCount"] != 0
        or not isinstance(diagnostics, dict) or type(diagnostics.get("schemaVersion")) is not int
        or diagnostics["schemaVersion"] != 1 or diagnostics.get("acknowledged") is not True):
        raise ValueError("Electron current input-lock evidence is incomplete or disagrees with its root count")
    current = diagnostics.get("current")
    if (not isinstance(current, dict) or current.get("allProtectedRootsLocked") is not True
        or type(current.get("protectedRootCount")) is not int or current["protectedRootCount"] != count):
        raise ValueError("Electron preload acknowledgement has no matching current native input lock")


def validate_fixture_focus_proof(proof: dict) -> None:
    required = ("expectedSvg", "nativeHtmlParent", "nativeParentInert", "parentInertAttribute",
                "closeIsButton", "svgFocusAttempted", "svgFocusBlocked", "closeFocusAttempted", "closeFocusAllowed")
    baseline = proof.get("baseline") if isinstance(proof, dict) else None
    if (not isinstance(proof, dict) or type(proof.get("schemaVersion")) is not int or proof["schemaVersion"] != 1
        or not isinstance(baseline, dict) or baseline.get("svgFocusable") is not True
        or baseline.get("svgAttributeStillFocusable") is not True
        or any(type(proof.get(key)) is not int or proof[key] != 1 for key in ("svgCount", "bannerCount", "closeButtonCount"))
        or any(proof.get(key) is not True for key in required)
        or not isinstance(proof.get("errors"), list) or proof["errors"]):
        raise ValueError("Electron inert fixture native focus proof is incomplete or failed")
    html_namespace, svg_namespace = "http://www.w3.org/1999/xhtml", "http://www.w3.org/2000/svg"
    descriptors = {
        "svg": {"id": "desktop-fixture-svg", "tagName": "svg", "namespaceURI": svg_namespace},
        "parent": {"namespaceURI": html_namespace},
        "banner": {"id": "inspectorpro-desktop-spike-banner"},
        "close": {"tagName": "BUTTON", "namespaceURI": html_namespace},
    }
    for key, expected in descriptors.items():
        node = proof.get(key)
        if (not isinstance(node, dict) or node.get("connected") is not True
            or any(node.get(field) != value for field, value in expected.items())):
            raise ValueError("Electron inert fixture native focus proof has invalid node evidence")


def validate_chrome_layout(layout: dict) -> None:
    """Independently recompute the bounded toolbar/tab geometry assertions."""
    def number(value):
        try:
            return type(value) in {int, float} and math.isfinite(value)
        except OverflowError:
            return False
    def rectangle(value):
        return (isinstance(value, dict) and all(number(value.get(key)) for key in ("x", "y", "width", "height"))
                and value["width"] > 0 and value["height"] > 0)
    def contains(outer, inner):
        return (inner["x"] >= outer["x"] - 1 and inner["y"] >= outer["y"] - 1
                and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + 1
                and inner["y"] + inner["height"] <= outer["y"] + outer["height"] + 1)
    viewport = layout.get("viewport") if isinstance(layout, dict) else None
    if (not isinstance(layout, dict) or layout.get("revision") != "chrome-layout-v1"
        or not isinstance(viewport, dict) or not number(viewport.get("width")) or not number(viewport.get("height"))
        or viewport["width"] <= 0 or viewport["height"] <= 0 or layout.get("violations") != []):
        raise ValueError("Electron current chrome layout evidence is missing or failed")
    viewport_bounds = {"x": 0, "y": 0, "width": viewport["width"], "height": viewport["height"]}
    expected_tabs = ("drawing", "3dmodel", "assembly", "training", "dfm", "report", "usage", "sessions")
    for name, key in (("toolbar", "controls"), ("tabbar", "tabs")):
        section = layout.get(name)
        nodes = section.get(key) if isinstance(section, dict) else None
        if (not isinstance(section, dict) or not rectangle(section.get("bounds"))
            or not isinstance(nodes, list) or not 1 <= len(nodes) <= 128
            or not contains(viewport_bounds, section["bounds"])):
            raise ValueError("Electron chrome layout container is missing or outside the viewport")
        ids = [node.get("id") if isinstance(node, dict) else None for node in nodes]
        if name == "tabbar" and (len(nodes) != len(expected_tabs) or any(ids.count(tab) != 1 for tab in expected_tabs)):
            raise ValueError("Electron chrome layout must contain all eight unique workflow tabs")
        for node in nodes:
            if (not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]
                or ids.count(node["id"]) != 1 or node.get("visible") is not True
                or not rectangle(node.get("bounds")) or not rectangle(node.get("clipBounds"))
                or not isinstance(node.get("labelBounds"), list) or len(node["labelBounds"]) > 64
                or not all(rectangle(label) for label in node["labelBounds"])
                or not isinstance(node.get("ancestorIds"), list)
                or any(ancestor not in ids or ancestor == node["id"] for ancestor in node["ancestorIds"])
                or (name == "tabbar" and (not node["labelBounds"] or node["ancestorIds"]))):
                raise ValueError("Electron chrome layout has invalid control or tab evidence")
            if (not contains(viewport_bounds, node["bounds"]) or not contains(section["bounds"], node["bounds"])
                or not contains(node["clipBounds"], node["bounds"])):
                raise ValueError("Electron chrome layout contains a clipped control or workflow tab")
            if any(not contains(node["bounds"], label) or not contains(node["clipBounds"], label) for label in node["labelBounds"]):
                raise ValueError("Electron chrome layout contains a clipped label")
        for index, first in enumerate(nodes):
            for second in nodes[index + 1:]:
                first_contains = first["id"] in second["ancestorIds"]
                second_contains = second["id"] in first["ancestorIds"]
                if first_contains or second_contains:
                    outer, inner = (first, second) if first_contains else (second, first)
                    if (first_contains and second_contains) or not contains(outer["bounds"], inner["bounds"]):
                        raise ValueError("Electron chrome layout control ancestry is inconsistent")
                    continue
                a, b = first["bounds"], second["bounds"]
                overlap_width = min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])
                overlap_height = min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"])
                if overlap_width > 1 and overlap_height > 1:
                    raise ValueError("Electron chrome layout contains overlapping controls or workflow tabs")


def validate_chrome_layout_capture(layout: dict, capture: dict) -> None:
    frame = capture.get("frameCheckpoint") if isinstance(capture, dict) else None
    viewport = frame.get("viewport") if isinstance(frame, dict) else None
    if (not isinstance(viewport, dict) or any(type(viewport.get(key)) not in {int, float}
        or not math.isfinite(viewport[key]) or viewport[key] <= 0 for key in ("width", "height"))
        or any(abs(layout["viewport"][key] - viewport[key]) > 1 for key in ("width", "height"))):
        raise ValueError("Electron chrome layout is stale relative to the captured renderer viewport")


def validate_input_lock_report(report: dict, kind: str) -> None:
    if report.get("inputLockRevision") != "html-root-lock-v1":
        raise ValueError("Electron input-lock report revision is missing or unsupported")
    validate_input_lock_snapshot(report)
    events = report.get("events")
    if not isinstance(events, list):
        raise ValueError("Electron input-lock capture rechecks are missing")
    rechecks = [event for event in events if isinstance(event, dict) and event.get("name") == "input-lock-rechecked"]
    phases = ["before-wide-capture", "after-wide-capture", "before-narrow-capture", "after-narrow-capture"]
    if [event.get("phase") for event in rechecks] != phases:
        raise ValueError("Electron input lock must be rechecked once before and after each capture, in order")
    for event in rechecks:
        validate_input_lock_snapshot(event)
    if kind == "inert-fixture":
        validate_fixture_focus_proof(report.get("fixtureFocusProof"))
    else:
        validate_chrome_layout(report.get("chromeLayout"))
        for event in rechecks:
            validate_chrome_layout(event.get("chromeLayout"))
        for name in ("wide", "narrow"):
            after = next(event for event in rechecks if event["phase"] == "after-" + name + "-capture")
            validate_chrome_layout_capture(after["chromeLayout"], report.get("captures", {}).get(name))


def validate_report(report: dict, *, kind: str, identity: dict, electron_version: str) -> None:
    if (report.get("schemaVersion") != 2 or report.get("diagnosticRevision") != "rendering-readiness-v1"
        or report.get("status") != "passed" or any(report.get("checks", {}).get(name) != "passed" for name in CHECKS)):
        raise ValueError("Electron staged readiness report did not pass every required check")
    if (report.get("electron") != electron_version or report.get("backendIdentity") != identity
        or report.get("markup", {}).get("kind") != kind or report.get("frozen") is not True
        or report.get("nodeExposed") is not False or report.get("researchViews") != 0
        or report.get("webContentsCount") != 1 or report.get("capabilities", {}).get("researchBrowsing") is not False
        or report.get("capabilities", {}).get("interactive") is not False):
        raise ValueError("Electron report identity, page type, or isolation evidence did not match this stage")
    captures = report.get("captures", {})
    if not captures.get("wide") or not captures.get("narrow"):
        raise ValueError("Electron report has no verified wide/narrow captures")
    validate_window_size_policy(report)
    validate_input_lock_report(report, kind)


def start_pipe_capture(stream, log_path: Path):
    state = {"eof": False, "closed": False, "error": None}
    def consume():
        try:
            with log_path.open("ab", buffering=0) as log:
                while True:
                    data = stream.read1(65536)
                    if not data:
                        state["eof"] = True
                        break
                    remaining = memoryview(data)
                    while remaining:
                        count = log.write(remaining)
                        if not count:
                            raise OSError("Diagnostic write made no progress")
                        remaining = remaining[count:]
                os.fsync(log.fileno())
        except BaseException as exc:
            state["error"] = str(exc) or type(exc).__name__
        finally:
            # Only this reader closes its pipe. Main-thread close could block
            # behind a read lock while a surviving descendant retains the pipe.
            if state["eof"]:
                try:
                    stream.close()
                    state["closed"] = True
                except OSError as exc:
                    state["error"] = str(exc)
    thread = threading.Thread(target=consume, daemon=True, name="electron-diagnostic-pipe")
    thread.start()
    return thread, state


def run_electron_stage(binary: dict, stage: Path, origin: str, marker: Path, identity: dict,
                       kind: str, timeout: float, *, process_factory=subprocess.Popen, drain_timeout: float = 5) -> dict:
    stage.mkdir(parents=True, exist_ok=True)
    if file_hash(Path(binary["executable"])) != binary["sha256"]:
        raise ValueError("Pinned Electron executable changed between rendering stages")
    state = Path(tempfile.mkdtemp(prefix="ip-rendering-check-"))
    command = [binary["executable"], str(DESKTOP), "--", "--backend", origin,
               "--identity-file", str(marker), "--state-root", str(state),
               "--smoke-output", str(stage), "--expected-page", kind]
    write_json(stage / "launch.json", {"startedAt": now(), "binary": binary, "stateRoot": str(state),
        "expectedPage": kind, "origin": origin, "sandboxRequested": True,
        "ownership": "direct Electron main process; Chromium descendant termination is not independently verified"})
    process = None
    reader = None
    pipe_state = None
    cleanup_attempted = False
    log_path = stage / "electron.log"
    receipt = {"startedAt": now(), "status": "starting", "ownedPid": None, "code": None,
               "terminationConfirmed": False, "stdioMode": "combined-pipe", "stdioClosed": False,
               "stdioEOFVerified": False, "descendantTerminationVerified": False}
    def settle_owned():
        nonlocal cleanup_attempted
        if process is None or cleanup_attempted:
            return
        cleanup_attempted = True
        try:
            backend.stop_child(process)
        finally:
            receipt["terminationConfirmed"] = process.poll() is not None
            receipt["code"] = process.poll()
            if reader is not None:
                reader.join(timeout=drain_timeout)
                receipt["stdioEOFVerified"] = not reader.is_alive() and pipe_state["eof"]
                receipt["stdioClosed"] = receipt["stdioEOFVerified"] and pipe_state["closed"]
                if pipe_state["error"]:
                    receipt["logError"] = pipe_state["error"]
            elif process.stdout is not None:
                # Reader setup never completed; closing our untouched read end
                # releases its handle but is not evidence of stream EOF.
                process.stdout.close()
    try:
        with log_path.open("ab") as log:
            log.write(f"[rendering-check {now()}] Starting directly owned Electron process\n".encode())
            log.flush()
            os.fsync(log.fileno())
        process = process_factory(command, cwd=DESKTOP, env=electron_environment(os.environ, stage),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **spawn_options())
        receipt["ownedPid"] = process.pid
        reader, pipe_state = start_pipe_capture(process.stdout, log_path)
        try:
            receipt["code"] = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            receipt["status"] = "timed-out"
            raise RuntimeError("Direct Electron process exceeded its rendering deadline") from exc
        finally:
            settle_owned()
        if not receipt["stdioClosed"] or receipt.get("logError"):
            receipt["status"] = "stdio-unconfirmed"
            raise RuntimeError("Electron exited without confirmed diagnostic EOF and successful log persistence")
        if receipt["code"] != 0:
            raise RuntimeError(f"Direct Electron process failed with exit code {receipt['code']}")
        report_path = stage / "report.json"
        if not report_path.is_file() or report_path.stat().st_size > 1024 * 1024:
            raise ValueError("Electron staged report is missing or oversized")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        validate_report(report, kind=kind, identity=identity, electron_version=binary["version"])
        for filename in ("desktop-wide.png", "desktop-narrow.png"):
            capture = stage / filename
            if not capture.is_file() or capture.stat().st_size <= 8:
                raise ValueError("Verified Electron capture artifact is missing")
            with capture.open("rb") as stream:
                if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise ValueError("Electron capture artifact is not a PNG")
        receipt["status"] = "passed"
        return {"status": "passed", "output": str(stage), "report": str(report_path), "process": receipt}
    except BaseException as exc:
        if receipt["status"] not in {"timed-out", "stdio-unconfirmed"}:
            receipt["status"] = "failed"
        receipt["error"] = str(exc) or type(exc).__name__
        if process is None:
            receipt["status"] = "spawn-error"
        try:
            with log_path.open("ab") as log:
                log.write(f"\n[rendering-check] {receipt['status']}: {receipt['error']}\n".encode())
                log.flush()
                os.fsync(log.fileno())
        except OSError as log_error:
            receipt["logError"] = str(log_error)
        raise
    finally:
        previous_error = sys.exc_info()[1]
        try:
            settle_owned()
        except BaseException as cleanup_error:
            receipt["cleanupError"] = str(cleanup_error) or type(cleanup_error).__name__
            receipt["status"] = "failed"
            if previous_error is None:
                raise
        finally:
            receipt["finishedAt"] = now()
            if process is not None:
                receipt["terminationConfirmed"] = process.poll() is not None
            write_json(stage / "process-result.json", receipt)


def fixture_profile_count(origin: str) -> int:
    opener = backend.urllib.request.build_opener(backend.urllib.request.ProxyHandler({}))
    with opener.open(origin + "/api/profiles", timeout=10) as response:
        payload = response.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024:
        raise ValueError("Fixture profile response exceeded its bound")
    profiles = json.loads(payload)
    if not isinstance(profiles, list):
        raise ValueError("Fixture profile response is not a list")
    return len(profiles)


BACKEND_CHECKPOINT_PREFIX = b"INSPECTORPRO_DESKTOP_BACKEND_CHECKPOINT "
BACKEND_BOOTSTRAP_MARKER = b"INSPECTORPRO_DESKTOP_BACKEND_BOOTSTRAP_ENTERED"


def backend_startup_evidence(log_path: Path, instance_id: str, owned_pid: int | None) -> dict:
    """Bounded diagnostic projection, never readiness or shutdown authority."""
    result = {"revision": "backend-startup-v1", "logBytes": None, "tailBytes": 0,
              "truncated": False, "incompleteTrailingLine": False, "bootstrapMarkerObserved": False,
              "checkpointCountInTail": 0, "malformedCheckpointLines": 0, "foreignCheckpointLines": 0,
              "lastCheckpoint": None, "checkpoints": []}
    try:
        with log_path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            offset = max(0, size - 262144)
            handle.seek(offset)
            data = handle.read(262144)
        result.update(logBytes=size, tailBytes=len(data), truncated=offset > 0)
        if offset:
            # The beginning may be part of an arbitrary application log line.
            data = data.partition(b"\n")[2]
        result["incompleteTrailingLine"] = bool(data and not data.endswith(b"\n"))
        lines = data.split(b"\n")[:-1]
        checkpoints = []
        for line in lines:
            line = line.rstrip(b"\r")
            if line == BACKEND_BOOTSTRAP_MARKER:
                result["bootstrapMarkerObserved"] = True
            if not line.startswith(BACKEND_CHECKPOINT_PREFIX):
                continue
            try:
                raw = line[len(BACKEND_CHECKPOINT_PREFIX):]
                if len(raw) > 2048:
                    raise ValueError("oversized checkpoint")
                value = json.loads(raw)
                if (not isinstance(value, dict) or type(value.get("schemaVersion")) is not int
                    or value["schemaVersion"] != 1 or type(value.get("pid")) is not int or value["pid"] < 1
                    or type(value.get("timeUnixMs")) is not int or value["timeUnixMs"] < 0
                    or not isinstance(value.get("phase"), str)
                    or not re.fullmatch(r"[a-z][a-z0-9-]{0,95}", value["phase"])):
                    raise ValueError("invalid checkpoint")
                if value.get("instanceId") != instance_id or value["pid"] != owned_pid:
                    result["foreignCheckpointLines"] += 1
                    continue
                item = {key: value[key] for key in ("schemaVersion", "pid", "timeUnixMs", "phase", "instanceId")}
                for key in ("sequence", "elapsedMs"):
                    candidate = value.get(key)
                    if type(candidate) in (int, float) and math.isfinite(candidate) and candidate >= 0:
                        item[key] = candidate
                checkpoints.append(item)
            except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
                result["malformedCheckpointLines"] += 1
        result["checkpointCountInTail"] = len(checkpoints)
        result["checkpoints"] = checkpoints[-64:]
        result["lastCheckpoint"] = checkpoints[-1] if checkpoints else None
    except (OSError, ValueError) as exc:
        result["readError"] = str(exc) or type(exc).__name__
    return result


def append_backend_parent_event(log_path: Path, event: dict) -> None:
    # Parent-only file: never share append positions with inherited child stdio handles.
    data = (json.dumps(event) + "\n").encode("utf-8")
    with log_path.open("ab", buffering=0) as log:
        remaining = memoryview(data)
        while remaining:
            count = log.write(remaining)
            if not count:
                raise OSError("Backend parent log write made no progress")
            remaining = remaining[count:]
        os.fsync(log.fileno())


def run_backend_stage(args, output: Path, binary: dict | None, *, process_factory=subprocess.Popen) -> dict:
    instance_id = str(uuid.uuid4())
    log_path = output / "backend.log"
    parent_log_path = output / "backend-parent.jsonl"
    result = {"status": "starting", "diagnosticRevision": "backend-startup-v1", "startedAt": now(),
              "instanceId": instance_id, "startupTimeoutSeconds": args.startup_timeout,
              "ownedPid": None, "terminationConfirmed": False, "stdioClosed": None,
              "stdioEOFVerified": False, "descendantTerminationVerified": False,
              "gracefulResourceCleanupVerified": False, "events": []}
    process = None
    def record(phase, *, strict=True, **fields):
        event = {"at": now(), "phase": phase, "instanceId": instance_id, **fields}
        result["events"].append(event)
        result["phase"] = phase
        try:
            append_backend_parent_event(parent_log_path, event)
            write_json(output / "backend-result.json", result)
        except OSError as exc:
            result.setdefault("diagnosticErrors", []).append({"phase": phase, "error": str(exc)})
            if strict:
                raise
    def startup_snapshot():
        return backend_startup_evidence(log_path, instance_id, result["ownedPid"])
    try:
        record("fixture-preparation-starting")
        library, identity = backend.prepare_fixture(ROOT, args.data_root, args.profile_id, args.port)
        if any(library.iterdir()):
            raise ValueError("Full rendering check requires a fresh empty fixture library; choose a new data root")
        result.update(identity=backend.public_identity(identity), origin=identity["origin"])
        record("fixture-preparation-complete")
        env = backend.child_environment(dict(os.environ), args.data_root, library)
        env["INSPECTORPRO_DESKTOP_INSTANCE_ID"] = instance_id
        env["PYTHONUNBUFFERED"] = "1"
        command = [sys.executable, "-u", str(Path(__file__).with_name("run-rendering-backend.py")), "--serve",
                   "--port", str(args.port), "--profile-id", args.profile_id, "--data-root", str(args.data_root),
                   "--library-root", str(library)]
        marker = args.data_root / backend.MARKER_NAME
        write_json(output / "backend-launch.json", {"diagnosticRevision": "backend-startup-v1", "at": now(),
            "instanceId": instance_id, "command": command, "cwd": str(ROOT), "log": str(log_path),
            "parentLog": str(parent_log_path),
            "startupTimeoutSeconds": args.startup_timeout, "unbuffered": True,
            "ownership": "direct Python child; stdout/stderr file; no descendant or pipe EOF proof"})
        record("spawn-starting")
        with log_path.open("ab", buffering=0) as log:
            process = process_factory(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                      stdout=log, stderr=log, **spawn_options())
            result["ownedPid"] = process.pid
            record("spawn-returned", ownedPid=process.pid)
            record("readiness-wait-starting")
            backend.wait_ready(process, identity, args.startup_timeout, instance_id)
            result["startupDiagnosticsAtReadiness"] = startup_snapshot()
            record("readiness-verified")
            record("http-boundary-checks-starting")
            result["httpChecks"] = backend.check_http_boundary(identity["origin"])
            result["profileCount"] = fixture_profile_count(identity["origin"])
            result["status"] = "ready"
            record("http-boundary-checks-complete")
            if binary is not None:
                record("full-application-rendering-starting")
                result["rendering"] = run_electron_stage(binary, output / "full-application", identity["origin"],
                    marker, backend.public_identity(identity), "full-application", args.electron_timeout)
                record("full-application-rendering-complete")
            result["status"] = "passed"
        return result
    except BaseException as exc:
        result["status"] = "failed"
        result["error"] = str(exc) or type(exc).__name__
        result["failurePhase"] = result.get("phase")
        # Freeze this before stop_child can produce shutdown checkpoints or an exit code.
        result["startupDiagnosticsAtFailure"] = startup_snapshot()
        record("operation-failed", strict=False, errorType=type(exc).__name__)
        raise
    finally:
        operation_error = sys.exc_info()[1]
        cleanup_error = None
        if process is not None:
            try:
                record("shutdown-requested", strict=False)
                backend.stop_child(process)
                result["terminationConfirmed"] = process.poll() is not None
                result["code"] = process.poll()
                if not result["terminationConfirmed"]:
                    raise RuntimeError("Owned backend shutdown could not be confirmed")
                record("owned-process-terminated", strict=False, exitCode=result["code"])
                path = backend.shutdown_receipt_path(args.data_root, instance_id)
                if not path.is_file() or path.stat().st_size > 16384:
                    raise RuntimeError("Owned backend exited without a confirmed lifespan shutdown receipt")
                receipt = json.loads(path.read_text(encoding="utf-8"))
                if receipt != {"schemaVersion": 1, "instanceId": instance_id,
                               "status": "lifespan-stopped", "resourcesClosed": True}:
                    raise RuntimeError("Owned backend shutdown receipt does not match this launched instance")
                result["shutdown"] = receipt
                result["gracefulResourceCleanupVerified"] = True
                record("resource-cleanup-receipt-verified", strict=False)
            except BaseException as exc:
                cleanup_error = exc
                result["shutdownError"] = str(exc) or type(exc).__name__
                result["status"] = "failed"
            finally:
                result["terminationConfirmed"] = process.poll() is not None
                result["code"] = process.poll()
        result["startupDiagnostics"] = startup_snapshot()
        result["finishedAt"] = now()
        if result.get("diagnosticErrors"):
            result["status"] = "failed"
        try:
            write_json(output / "backend-result.json", result)
        except OSError:
            if operation_error is None and cleanup_error is None:
                raise
        if operation_error is None:
            if cleanup_error is not None:
                raise cleanup_error
            if result.get("diagnosticErrors"):
                raise RuntimeError("Backend diagnostics could not be persisted completely")


def execute(args) -> dict:
    source = backend.verify_snapshot(ROOT)
    output = backend.no_links(args.output)
    args.data_root = backend.no_links(args.data_root)
    if backend.within(output, source) or backend.within(source, output):
        raise ValueError("Rendering reports must not overlap the live source workspace")
    if backend.within(output, args.data_root) or backend.within(args.data_root, output):
        raise ValueError("Use separate, non-overlapping output and backend data directories")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()  # Fresh run only: stale passing screenshots/reports cannot be reused.
    report = {"schemaVersion": 1, "diagnosticRevision": "two-stage-rendering-v1", "startedAt": now(),
              "status": "running", "mode": "backend-check-only" if args.backend_check_only else "two-stage-rendering",
              "fullRenderingPassed": False, "stages": {}, "output": str(output)}
    write_json(output / "rendering-check.json", report)
    try:
        binary = None if args.backend_check_only else resolve_electron()
        report["binary"] = binary
        if binary is not None:
            inert = output / "inert-fixture"
            inert.mkdir()
            with inert_fixture(inert) as fixture:
                report["stages"]["inert"] = run_electron_stage(binary, inert, fixture["origin"], fixture["marker"],
                    fixture["identity"], "inert-fixture", args.electron_timeout)
            write_json(output / "rendering-check.json", report)
        else:
            report["stages"]["inert"] = {"status": "not-run", "reason": "explicit backend-check-only diagnostic"}
        # The normal rendering path reaches backend preparation only after the
        # process exit and every staged inert-page assertion have passed.
        try:
            report["stages"]["backend"] = run_backend_stage(args, output, binary)
        except BaseException:
            report["stages"]["backend"] = {"status": "failed", "report": str(output / "backend-result.json"),
                "log": str(output / "backend.log"), "parentLog": str(output / "backend-parent.jsonl")}
            raise
        report["status"] = "passed"
        report["fullRenderingPassed"] = binary is not None
        return report
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = str(exc) or type(exc).__name__
        raise
    finally:
        previous_error = sys.exc_info()[1]
        report["finishedAt"] = now()
        try:
            write_json(output / "rendering-check.json", report)
        except OSError as persistence_error:
            if previous_error is None:
                raise
            # Preserve the original startup/cleanup failure if final reporting fails.
            try:
                print(json.dumps({"aggregatePersistenceError": str(persistence_error)}), file=sys.stderr, flush=True)
            except (OSError, ValueError):
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--profile-id", default="rendering-check")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--startup-timeout", type=float, default=45)
    parser.add_argument("--electron-timeout", type=float, default=90)
    parser.add_argument("--backend-check-only", action="store_true", help="Verify only backend startup/boundary/shutdown; never launches Electron")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535 or not 1 <= args.startup_timeout <= 120 or not 1 <= args.electron_timeout <= 180:
        parser.error("Invalid explicit port or bounded timeout")
    def request_stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, request_stop)
    if os.name == "nt":
        signal.signal(signal.SIGBREAK, request_stop)
    try:
        report = execute(args)
        print(json.dumps({"passed": True, "fullRenderingPassed": report["fullRenderingPassed"], "output": report["output"]}))
        return 0
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print(json.dumps({"passed": False, "output": str(args.output.absolute()),
                          "error": str(exc) or type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
