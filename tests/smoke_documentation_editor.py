"""Real MMLE browser/editor gate. Run by Claude, never against a live checkout.

Uses the isolated server/loopback/cleanup pattern of IsolatedPartsManualServer,
with a sanitized code snapshot, every document root redirected, a new browser
context, no dotenv or credentials, and blocked outbound traffic. JSON evidence
and screenshots are retained under .runtime/de; the temporary stores are removed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import site
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.documentation_baseline import local_inventory, safe_source, tracked_paths

ASSEMBLY = "MMLE-50D"
DOC_TYPE = "illustrated_parts_manual"
PHASES = ("P1a", "P1b", "P1c", "P2a", "P2b", "P3a", "P3b", "P4a", "P4b", "P5a", "all")
ROOT_NAMES = {"PARTS_MANUAL_ROOT": "p", "OPERATIONS_MANUAL_ROOT": "o", "SPECIFICATION_SHEET_ROOT": "s",
              "WORK_INSTRUCTION_ROOT": "w", "INSPECTION_SHEET_ROOT": "i",
              "ASSEMBLY_APPEARANCE_ROOT": "a", "PART_APPEARANCE_ROOT": "b"}


# Supervisor-observed gaps in this sanitized MMLE fixture, never documentation
# failures. Keep status, method and complete path shapes narrow.
KNOWN_OPTIONAL_HTTP = (
    (404, re.compile(r"/api/(?:drawing-map|drawing-pdf|part-features)/[^/]+"), "MMLE drawing/feature inputs absent"),
    (404, re.compile(r"/api/training/(?:process-map|process-map-for-assembly)/[^/]+"), "MMLE process-map preview absent"),
    (500, re.compile(r"/api/reference-views/[^/]+"), "MMLE reference drawings absent"),
)
KNOWN_FIXTURE_LIMITATIONS = [
    "Drawing-map, drawing-pdf, part-features and process-map preview GETs may return 404 in the sanitized MMLE copy.",
    "Reference-views GET may return 500 because this copy has no MMLE drawings.",
    "The ignored static/contracts/semantic-knowledge-prototype-v1.json is not copied; its server startup FileNotFoundError is known.",
    "A bridge status poll still in flight when the smoke reloads the page is aborted (net::ERR_ABORTED).",
]
# The page polls this status route; the smoke's own reload between workspace opens can cut one off.
KNOWN_ABORTED_POLLS = re.compile(r"/api/bridge/status")


def known_network_failure(failure):
    return (failure.get("error") == "net::ERR_ABORTED"
            and bool(KNOWN_ABORTED_POLLS.fullmatch(urlsplit(failure.get("url", "")).path)))


def known_http_failure(failure):
    if failure.get("method") != "GET":
        return None
    route = urlsplit(failure.get("url", "")).path
    return next((reason for status, pattern, reason in KNOWN_OPTIONAL_HTTP
                 if failure.get("status") == status and pattern.fullmatch(route)), None)


def classify_failures(report):
    """Keep all raw evidence, separating only the supervisor's known fixture gaps."""
    known_http = [item for item in report["httpFailures"] if known_http_failure(item)]
    unexpected_http = [item for item in report["httpFailures"] if not known_http_failure(item)]
    known = [{"kind": "http", **item, "reason": known_http_failure(item)} for item in known_http]
    unexpected_console = []
    for item in report["consoleErrors"]:
        message, url = item["message"], item["location"].get("url", "")
        resource = re.fullmatch(r"Failed to load resource: the server responded with a status of (\d{3})(?: \([^\n]*\))?", message)
        matched = next((failure for failure in known_http
                        if resource and failure["url"] == url and failure["status"] == int(resource[1])), None)
        reference_json = (message.startswith("Failed to load reference views:")
                          and ("SyntaxError" in message or "JSON" in message)
                          and any(urlsplit(failure["url"]).path.startswith("/api/reference-views/")
                                  for failure in known_http))
        if matched or reference_json:
            known.append({"kind": "console", **item, "reason": "Console consequence of a known optional GET failure"})
        else:
            unexpected_console.append(item)
    unexpected_network = []
    for item in report["networkFailures"]:
        if known_network_failure(item):
            known.append({"kind": "network", **item, "reason": "Status poll aborted by the smoke's own page reload"})
        else:
            unexpected_network.append(item)
    report["knownFixtureFailures"] = known
    report["unexpectedHttpFailures"] = unexpected_http
    report["unexpectedConsoleErrors"] = unexpected_console
    report["unexpectedNetworkFailures"] = unexpected_network
    return not (unexpected_http or unexpected_console or report["browserErrors"]
                or unexpected_network or report["outboundRequests"])


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii"))


class IsolatedDocumentationServer:
    def __init__(self, output):
        self.output = output
        self.temporary = self.process = self.log = None
        self.original = {}

    def start(self):
        runtime = ROOT / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="de-", dir=runtime)
        self.scratch = Path(self.temporary.name).resolve()
        self.code, self.stores = self.scratch / "c", self.scratch / "d"
        self.code.mkdir()
        inputs = local_inventory()
        if not inputs["available"]:
            raise RuntimeError("Required MMLE inputs absent: " + repr(inputs["missingInputs"]))

        # Copy only reviewed source/static trees and the explicit engineering
        # manifest. Never copy the working tree wholesale, .git, user stores,
        # environment files, auth profiles or browser state.
        extensions = {".py", ".js", ".mjs", ".cjs", ".html", ".css", ".svg", ".png", ".jpg",
                      ".jpeg", ".webp", ".woff", ".woff2", ".ttf", ".json", ".md", ".yaml", ".yml", ".txt"}
        names = {"server.py", "geometry_worker.py"}
        for name in tracked_paths():
            parts = Path(name).parts
            if parts[0] in {"ai_inspector", "static"} and Path(name).suffix.lower() in extensions:
                if Path(name).suffix.lower() == ".json" and any(
                        word in name.lower() for word in ("credential", "secret", "token", "cookie", "session", "auth")):
                    continue
                names.add(name)
        # Include new, still-uncommitted implementation files without admitting
        # ignored data or generated trees.
        names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "ai_inspector/documentation").glob("*.py"))
        names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "static").glob("documentation_*.js"))
        names.update(inputs["inputFiles"])
        for name in sorted(names):
            source = safe_source(name)
            if not source.is_file():
                continue  # tracked file removed by the uncommitted implementation
            if source.is_symlink():
                raise RuntimeError("Snapshot rejects symlink: " + name)
            target = self.code / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if name in inputs["inputFiles"]:
                self.original[name] = sha(source)
        (self.code / "400S_Sorted_Library").mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "tests/documentation_editor_smoke_server.py", self.code / "smoke_server.py")
        for name, short in ROOT_NAMES.items():
            (self.stores / short).mkdir(parents=True, exist_ok=True)
        self.manual = self.stores / "p" / "mmle-50d"
        self.manual.mkdir()
        for name in ("manual-plan.json", "documentation-scene.json"):
            relative = "generated/parts_manual/mmle-50d/" + name
            source = safe_source(relative)
            self.original[relative] = sha(source)
            shutil.copyfile(source, self.manual / name)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        # An allowlisted environment avoids inherited API credentials/proxies.
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "COMSPEC", "PATHEXT"}}
        environment.update({"INSPECTORPRO_" + name: str(self.stores / short)
                            for name, short in ROOT_NAMES.items()})
        environment.update(INSPECTORPRO_LIBRARY_DIR=str(self.code / "400S_Sorted_Library"),
                           INSPECTORPRO_CODEX_WEB_RESEARCH="0", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1",
                           TEMP=str(self.scratch), TMP=str(self.scratch), HOME=str(self.scratch),
                           USERPROFILE=str(self.scratch), APPDATA=str(self.scratch), LOCALAPPDATA=str(self.scratch),
                           # Packages may live in the user site; keep it importable with APPDATA redirected.
                           PYTHONUSERBASE=site.getuserbase(),
                           INSPECTORPRO_FACILITY_LAYOUT_ROOT=str(self.scratch / "f"))
        self.log = (self.output / "server.log").open("wb")
        self.process = subprocess.Popen([sys.executable, str(self.code / "smoke_server.py"), str(self.scratch), str(port)],
            cwd=self.code, env=environment, stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Isolated server exited; see server.log")
            try:
                with opener.open(self.url + "/__p1a/isolation", timeout=2) as response:
                    self.isolation = json.load(response)
                    return self
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("Isolated server readiness timed out")

    def stop(self):
        try:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
        finally:
            if self.log:
                self.log.close()
            if self.temporary:
                self.temporary.cleanup()

    def inputs_unchanged(self):
        return all(sha(safe_source(name)) == checksum for name, checksum in self.original.items())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=PHASES)
    args = parser.parse_args()
    output = ROOT / ".runtime" / "de"
    output.mkdir(parents=True, exist_ok=True)
    report = {"phase": args.phase, "assembly": ASSEMBLY, "checks": {}, "browserErrors": [],
              "consoleErrors": [], "networkFailures": [], "httpFailures": [], "outboundRequests": [], "passed": False,
              "knownFixtureLimitations": KNOWN_FIXTURE_LIMITATIONS, "failureScreenshots": [], "workspaceOpens": []}
    server = IsolatedDocumentationServer(output)
    playwright = browser = context = page = None
    page_handlers = {}

    def failure_screenshot(check):
        evidence = {"check": check}
        report["failureScreenshots"].append(evidence)
        filename = f"fail-{len(report['failureScreenshots']):02d}.png"
        try:
            if page is None or page.is_closed():
                evidence["unavailable"] = "Browser page was not available at failure time"
                return
            page.screenshot(path=str(output / filename), full_page=True, timeout=15000)
            evidence["file"] = filename
        except Exception as error:
            evidence["error"] = f"{type(error).__name__}: {error}"

    def record(name, ok, detail=None):
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            failure_screenshot(name)

    def begin_edit(cell):
        # A manual page redraws on every press, so the browser never sees a double-click there; the workspace starts an
        # edit on two separate presses on the same text within half a second (_documentationTextPressed).
        cell.wait_for(state="visible", timeout=30000)
        box = cell.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.click(x, y)
        page.wait_for_timeout(150)
        page.mouse.click(x, y)
        page.wait_for_function("() => !!document.querySelector('[contenteditable=\"true\"]')", timeout=15000)

    try:
        if args.phase != "P1a":
            raise RuntimeError("Later cumulative phases are not implemented; this is the P1a gate only.")
        from playwright.sync_api import sync_playwright
        server.start()
        report["isolation"] = server.isolation
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1720, "height": 1080}, service_workers="block")
        if not hasattr(context, "route_web_socket"):
            raise RuntimeError("Installed Playwright lacks route_web_socket; outbound isolation cannot be proved")

        def websocket_route(route):
            if urlsplit(route.url).netloc == urlsplit(server.url).netloc:
                route.connect_to_server()
            else:
                report["outboundRequests"].append(route.url)
                route.close()

        context.route_web_socket("**/*", websocket_route)

        def route(request_route):
            url = request_route.request.url
            parsed = urlsplit(url)
            if parsed.scheme in {"data", "blob"} or parsed.netloc == urlsplit(server.url).netloc:
                request_route.continue_()
            else:
                report["outboundRequests"].append(url)
                request_route.abort()

        context.route("**/*", route)
        page = context.new_page()
        page_handlers = {
            "pageerror": lambda error: report["browserErrors"].append(str(error)),
            "console": lambda event: report["consoleErrors"].append(
                {"message": event.text, "location": event.location}) if event.type == "error" else None,
            "requestfailed": lambda request: report["networkFailures"].append(
                {"url": request.url, "error": request.failure}),
            "response": lambda response: report["httpFailures"].append(
                {"url": response.url, "status": response.status, "method": response.request.method})
                if response.status >= 400 else None,
        }
        for event, handler in page_handlers.items():
            page.on(event, handler)
        request = context.request
        scene_url = server.url + "/api/parts-manual/MMLE-50D/documentation-scene"

        def get_scene():
            response = request.get(scene_url, timeout=120000)
            if not response.ok:
                raise RuntimeError(f"Scene HTTP {response.status}: {response.text()[:800]}")
            return response.json()

        def tool(name, arguments):
            response = request.post(server.url + "/__p1a/tool", data={"name": name, "arguments": arguments},
                                    timeout=120000)
            if not response.ok:
                raise RuntimeError(f"Tool HTTP {response.status}: {response.text()[:800]}")
            return response.json()

        copied_scene_hash = sha(server.manual / "documentation-scene.json")
        before = get_scene()
        write_json(output / "before.json", before)
        legacy_before = {name: sha(server.manual / name) for name in ("documentation-scene.json", "manual-plan.json")}
        record("opening_does_not_rewrite", sha(server.manual / "documentation-scene.json") == copied_scene_hash)
        chosen = next(p for p in before["document"]["pages"] if p.get("bom"))
        # Derive the real definition-keyed alias with the production reader,
        # never an invented HTML fixture or a test-only renderer.
        initial_read = tool("read_document_pages", {"documentType": DOC_TYPE,
                            "fromPage": chosen["pageNumber"], "pageCount": 1})
        if not initial_read.get("ok"):
            raise RuntimeError("Sage page read failed: " + repr(initial_read))
        read_page = initial_read["data"]["pages"][0]
        row = next(block for block in read_page["blocks"] if block["type"] == "parts_list")["rows"][0]
        alias = row[2].get("legacyTargetId") or row[2].get("id") or row[2]["targetId"]
        full = tool("read_document_pages", {"documentType": DOC_TYPE,
                    "targets": [{"pageId": chosen["pageId"], "targetId": alias}]})
        record("full_target_read_bound", full.get("ok") and full.get("data", {}).get("documentId")
               and isinstance(full.get("data", {}).get("revision"), int), full)
        # Even an incomplete gateway must proceed through the real DOM race;
        # missing metadata stays a failed check, never a skip/pass fallback.
        stale_arguments = {"documentType": DOC_TYPE, "edits": [{"pageId": chosen["pageId"],
                           "targetId": alias, "text": "Stale Sage replacement must be refused"}]}

        def open_workspace():
            stored_before = {name: sha(server.manual / name) for name in legacy_before}
            page.goto(server.url + "/?assemblyProfile=MMLE-50D", wait_until="domcontentloaded", timeout=90000)
            page.wait_for_function("""() => window.__compareDbg?.state.partNumber === 'MMLE-50D'
                && window.__compareDbg.state.assyLiveScene""", timeout=90000)
            page.evaluate("() => window.__compareDbg.openDocumentationWorkflow()")
            page.locator("#documentationWorkspace").wait_for(state="visible", timeout=120000)
            page.wait_for_function("""() => window.__compareDbg.state.partsManualDocumentation
                && !document.querySelector('#documentationWorkspace.busy')""", timeout=120000)
            snapshot = page.evaluate("() => window.__compareDbg.documentationGenerationSnapshot()")
            used_refresh = snapshot["visiblePageCount"] == 0
            if used_refresh:
                # The real Refresh control calls _documentationReloadWorkflow ->
                # _documentationRefreshScene({revealAll:true}). No generation,
                # publication, test-only state changes or localStorage seeding.
                with page.expect_response(lambda response: response.request.method == "GET"
                                          and response.url == scene_url, timeout=120000) as refreshed:
                    page.locator("#documentationRefreshRibbon").click()
                if not refreshed.value.ok:
                    raise RuntimeError(f"Refresh scene HTTP {refreshed.value.status}")
            page.wait_for_function("""() => {
                const snapshot = window.__compareDbg.documentationGenerationSnapshot();
                return snapshot.workspaceOpen && !snapshot.blank && snapshot.visiblePageCount > 0
                    && !document.querySelector('#documentationWorkspace.busy');
            }""", timeout=120000)
            revealed = page.evaluate("() => window.__compareDbg.documentationGenerationSnapshot()")
            report["workspaceOpens"].append({"before": snapshot, "after": revealed, "usedRefresh": used_refresh})
            number = len(report["workspaceOpens"])
            record(f"workspace_open_{number}_reveals_saved_pages",
                   revealed["visiblePageCount"] == len(before["document"]["pages"]), revealed)
            record(f"workspace_open_{number}_does_not_rewrite_stores", stored_before ==
                   {name: sha(server.manual / name) for name in legacy_before})
            page.locator(f'.documentation-page-item[data-page-id="{chosen["pageId"]}"]').click()

        open_workspace()
        cell = page.locator(f'#documentationPublicationSurface [data-documentation-edit-target="{alias}"]:visible').first
        cell.wait_for(state="visible", timeout=30000)
        original_text = cell.inner_text()
        human_text = original_text + " P1a browser edit"
        begin_edit(cell)
        cell.fill(human_text)
        with page.expect_response(lambda response: response.request.method == "POST"
                                  and ("documentation-scene/commands" in response.url or "/edits" in response.url),
                                  timeout=120000) as response_info:
            cell.press("Enter")
        response = response_info.value
        saved = response.json()
        record("ui_commit_succeeded", response.ok, saved.get("receipt"))
        after = get_scene()
        write_json(output / "after.json", after)
        disk_before_stale = {p.name: sha(p) for p in server.manual.iterdir() if p.is_file()}
        stale = tool("edit_document_text", stale_arguments)
        record("stale_sage_host_write_rejected", stale.get("ok") is False and
               stale.get("error", {}).get("code") in {"content_hash_mismatch", "stale_revision"}, stale)
        record("stale_request_keeps_stores_byte_identical", disk_before_stale ==
               {p.name: sha(p) for p in server.manual.iterdir() if p.is_file()})
        open_workspace()
        reopened_text = page.locator(f'#documentationPublicationSurface [data-documentation-edit-target="{alias}"]:visible').first.inner_text()
        record("reopen_preserves_human_text", reopened_text == human_text, reopened_text)
        reopened = get_scene()
        write_json(output / "reopened.json", reopened)
        page.screenshot(path=str(output / "reopened.png"), full_page=True)
        record("scene_upgraded_in_place", reopened["scene"]["schemaVersion"] == 3
               and not (server.manual / "edit.json").exists())
        record("original_v2_bytes_retained", sha(server.manual / "documentation-scene.v2.json") == copied_scene_hash)
        record("manual_plan_unchanged", sha(server.manual / "manual-plan.json") == legacy_before["manual-plan.json"])

        # A fresh complete read now authorizes one two-target Sage batch.
        other_alias = row[1].get("legacyTargetId") or row[1]["id"]
        fresh = tool("read_document_pages", {"documentType": DOC_TYPE, "targets": [
            {"pageId": chosen["pageId"], "targetId": alias},
            {"pageId": chosen["pageId"], "targetId": other_alias}]})
        if not fresh.get("ok"):
            raise RuntimeError("Fresh full read failed: " + repr(fresh))
        targets = fresh["data"]["targets"]
        batch = {"documentId": fresh["data"]["documentId"], "expectedRevision": fresh["data"]["revision"],
                 "requestId": "p1a-browser-sage-batch", "operations": [
                     {"operation": "replace_text", "targetId": item["targetId"],
                      "expectedContentHash": item["contentHash"], "text": item["text"] + " P1a Sage batch"}
                     for item in targets]}
        applied = tool("apply_document_edits", batch)
        record("sage_batch_succeeded", applied.get("ok"), applied)
        if not applied.get("ok"):
            raise RuntimeError("Fresh Sage batch failed: " + repr(applied))
        receipt = applied["data"]["receipt"]
        persisted = json.loads((server.manual / "documentation-scene.json").read_bytes())
        record("receipt_and_scene_committed_together",
               persisted["receipts"][receipt["requestId"]]["receipt"] == receipt
               and persisted["commands"][-1]["operation"] == "batch"
               and len(persisted["commands"][-1]["commands"]) == 2)
        report.update(documentId=receipt["documentId"], revision=receipt["revision"])
        write_json(output / "committed-scene.json", persisted)
        committed_files = {p.name: sha(p) for p in server.manual.iterdir() if p.is_file()}
        retry = tool("apply_document_edits", batch)
        record("retry_returns_stored_receipt_without_write", retry.get("data", {}).get("receipt") == receipt
               and committed_files == {p.name: sha(p) for p in server.manual.iterdir() if p.is_file()})
        open_workspace()
        with page.expect_response(lambda response: response.request.method == "POST" and "/undo" in response.url,
                                  timeout=120000):
            page.locator("#documentationUndoRibbon").click()
        open_workspace()
        record("batch_undo_is_one_step", page.locator(
            f'#documentationPublicationSurface [data-documentation-edit-target="{alias}"]:visible').first.inner_text() == human_text
            and page.locator(f'#documentationPublicationSurface [data-documentation-edit-target="{other_alias}"]:visible').first.inner_text() == targets[1]["text"])
        with page.expect_response(lambda response: response.request.method == "POST" and "/undo" in response.url,
                                  timeout=120000):
            page.locator("#documentationUndoRibbon").click()
        undone = get_scene()
        write_json(output / "undone.json", undone)
        open_workspace()
        undo_text = page.locator(f'#documentationPublicationSurface [data-documentation-edit-target="{alias}"]:visible').first.inner_text()
        record("ui_undo_and_reopen_restore_prior_text", undo_text == original_text, undo_text)
        # Hold the real DOM save request, switch through the visible type
        # selector, then release it. Its response must not replace the sheet.
        held = []
        route_pattern = "**/api/parts-manual/MMLE-50D/documentation-scene/commands"
        page.route(route_pattern, lambda pending: held.append(pending))
        cell = page.locator(f'#documentationPublicationSurface [data-documentation-edit-target="{alias}"]:visible').first
        begin_edit(cell)
        cell.fill(original_text + " delayed save")
        cell.press("Enter")
        page.wait_for_timeout(100)
        if len(held) != 1:
            raise RuntimeError("Delayed save request was not captured")
        page.locator("#documentationTypeRibbonTrigger").click()
        page.locator("#documentationTypeRibbonOption-product_specification_sheet").click()
        page.wait_for_function("() => window.__compareDbg.state.documentationDocumentType === 'product_specification_sheet'")
        with page.expect_response(lambda response: response.request.method == "POST"
                                  and "documentation-scene/commands" in response.url, timeout=120000):
            held[0].continue_()
        page.unroute(route_pattern)
        page.wait_for_timeout(300)
        record("delayed_save_does_not_retarget_document", page.evaluate("""() => {
            const s = window.__compareDbg.state;
            return s.documentationDocumentType === 'product_specification_sheet'
                && (!s.partsManualDocumentation || s.partsManualDocumentation.document.documentType === 'product_specification_sheet');
        }"""))
        page.screenshot(path=str(output / "switched.png"), full_page=True)
    except Exception as error:
        report["fatalError"] = f"{type(error).__name__}: {error}"
        failure_screenshot("fatalError")
    finally:
        try:
            if server.original:
                record("source_inputs_unchanged", server.inputs_unchanged())
            record("no_unexpected_browser_or_network_failures", classify_failures(report))
        except Exception as error:
            report["cleanupError"] = str(error)
            failure_screenshot("cleanupError")
        finally:
            # Stop observing before close deliberately cancels background requests.
            # Capture failure screenshots while Playwright is still connected.
            try:
                if page is not None and not page.is_closed():
                    for event, handler in page_handlers.items():
                        page.remove_listener(event, handler)
            except Exception as error:
                report.setdefault("browserCleanupErrors", []).append(str(error))
                failure_screenshot("browserCleanupError")
            for resource, close in ((context, "close"), (browser, "close"), (playwright, "stop")):
                if resource is not None:
                    try:
                        getattr(resource, close)()
                    except Exception as error:
                        report.setdefault("browserCleanupErrors", []).append(str(error))
                        failure_screenshot("browserCleanupError")
            try:
                server.stop()
            except Exception as error:
                report["cleanupError"] = str(error)
                failure_screenshot("cleanupError")
        clean_events = classify_failures(report)
        report["passed"] = clean_events and bool(report["checks"]) and all(item["ok"] for item in report["checks"].values()) \
            and "fatalError" not in report and "cleanupError" not in report and not report.get("browserCleanupErrors")
        write_json(output / "report.json", report)
        print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
