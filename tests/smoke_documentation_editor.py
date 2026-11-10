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
import threading
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
    "A page reload aborts GETs still in flight (bridge status poll, static assets, figure images): net::ERR_ABORTED.",
]
# The smoke reloads the app between workspace opens, which aborts GETs still in flight: the bridge status poll,
# static assets and saved figure images. Only those reads; an aborted write or any other route still fails.
KNOWN_ABORTED_GETS = re.compile(
    r"/api/bridge/status"
    r"|/static/[A-Za-z0-9_./-]+"
    r"|/api/(?:parts-manual|operations-manual|work-instructions|specification-sheet)/[^/]+/renders/[0-9a-f]{64}/[A-Za-z0-9_.-]+")


def known_network_failure(failure):
    return (failure.get("error") == "net::ERR_ABORTED" and failure.get("method", "GET") == "GET"
            and bool(KNOWN_ABORTED_GETS.fullmatch(urlsplit(failure.get("url", "")).path)))


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
            known.append({"kind": "network", **item, "reason": "GET aborted by the smoke's own page reload"})
        else:
            unexpected_network.append(item)
    report["knownFixtureFailures"] = known
    report["unexpectedHttpFailures"] = unexpected_http
    report["unexpectedConsoleErrors"] = unexpected_console
    report["unexpectedNetworkFailures"] = unexpected_network
    return not (unexpected_http or unexpected_console or report["browserErrors"]
                or unexpected_network or report["outboundRequests"])


def attach_stall_probe(page):
    """A DevTools session kept open on each tab, so a later stall can still be examined: Debugger.pause and
    Performance.getMetrics interrupt a running script, but enabling those domains does not."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("Performance.enable")
    cdp.send("Debugger.enable")
    return cdp


def stall_probe(page, cdp, report, on_blocked):
    """After a timeout: is the page running a script (and where), busy in layout, or idle but not drawing?
    A watchdog calls on_blocked if the renderer stops answering DevTools altogether."""
    probe = report["stallProbe"] = {}
    watchdog = threading.Timer(90, on_blocked)
    watchdog.daemon = True
    watchdog.start()
    try:
        def metrics():
            return {item["name"]: item["value"] for item in cdp.send("Performance.getMetrics")["metrics"]}
        first = metrics()
        page.wait_for_timeout(3000)
        second = metrics()
        probe["busySecondsOver3s"] = {name: round(second.get(name, 0) - first.get(name, 0), 3) for name in
            ("TaskDuration", "ScriptDuration", "LayoutDuration", "RecalcStyleDuration")}
        probe["jsHeapUsedMB"] = round(second.get("JSHeapUsedSize", 0) / 1e6, 1)
        probe["domNodes"] = second.get("Nodes")
        paused = []
        cdp.on("Debugger.paused", lambda event: paused.append(event))  # Playwright cannot wrap a builtin method
        cdp.send("Debugger.pause")
        for _ in range(20):
            if paused:
                break
            page.wait_for_timeout(250)
        if paused:
            probe["pauseReason"] = paused[0].get("reason")
            probe["stack"] = [
                "{} {}:{}:{}".format(frame.get("functionName") or "<anonymous>",
                                     (frame.get("url") or "").rsplit("/", 1)[-1],
                                     frame["location"]["lineNumber"] + 1, frame["location"].get("columnNumber", 0) + 1)
                for frame in paused[0].get("callFrames", [])[:16]]
            cdp.send("Debugger.resume")
        else:
            probe["stack"] = None
        if probe["busySecondsOver3s"]["ScriptDuration"] < 1:
            probe["frames"] = page.evaluate("""() => new Promise(resolve => {
                const started = performance.now();
                const timer = setTimeout(() => resolve({animationFrame: false, waitedMs: Math.round(performance.now() - started)}), 3000);
                requestAnimationFrame(() => { clearTimeout(timer); resolve({animationFrame: true, waitedMs: Math.round(performance.now() - started)}); });
            }).then(result => ({...result, visibility: document.visibilityState, focused: document.hasFocus()}))""")
            probe["pageState"] = page.evaluate("""() => {
                const debug = window.__compareDbg, state = debug && debug.state;
                let generation = null;
                try { generation = debug && debug.documentationGenerationSnapshot(); } catch (error) { generation = String(error); }
                return {url: location.pathname + location.search, documentType: state && state.documentationDocumentType,
                    workspaceVisible: !!document.querySelector('#documentationWorkspace:not([hidden])'),
                    workspaceBusy: !!document.querySelector('#documentationWorkspace.busy'),
                    pageId: state && state.partsManualDocumentationPageId, generation,
                    pageItems: document.querySelectorAll('.documentation-page-item').length};
            }""")
    except Exception as error:
        probe["error"] = f"{type(error).__name__}: {error}"[:600]
    finally:
        watchdog.cancel()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii"))


class IsolatedDocumentationServer:
    def __init__(self, output, phase=None):
        self.output = output
        self.rich_text = phase == "P2a"
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
        names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "static").glob("documentation_*.css"))
        names.update(inputs["inputFiles"])
        # Work instructions accept the function-ready MMLE package only in semantic-knowledge prototype mode, which
        # this ignored engineering contract defines (no credentials; its review receipt is in docs/semantic-knowledge).
        prototype_contract = "static/contracts/semantic-knowledge-prototype-v1.json"
        if safe_source(prototype_contract).is_file():
            names.add(prototype_contract)
            inputs["inputFiles"].append(prototype_contract)
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
        return self._launch()

    def _launch(self):
        previous_url = getattr(self, "url", None)
        while True:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            candidate_url = f"http://127.0.0.1:{port}"
            if candidate_url != previous_url:
                break
        self.url = candidate_url
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
        if self.rich_text:
            environment["INSPECTORPRO_DOCUMENTATION_RICH_TEXT"] = "1"
        self.log = (self.output / "server.log").open("ab")
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
                    assert Path(self.isolation["snapshot"]).resolve() == self.code
                    assert self.isolation["dotenvDisabled"] and self.isolation["outboundBlocked"]
                    assert all(Path(self.isolation["roots"][name]).resolve() == self.stores / short
                               for name, short in ROOT_NAMES.items())
                    return self
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("Isolated server readiness timed out")

    def restart(self):
        self._stop_process()
        return self._launch()

    def _stop_process(self):
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

    def stop(self):
        try:
            self._stop_process()
        finally:
            if self.temporary:
                self.temporary.cleanup()

    def inputs_unchanged(self):
        return all(sha(safe_source(name)) == checksum for name, checksum in self.original.items())


def run_p1b(page, request, server, output, report, record, begin_edit, tool, fresh_page):
    """Real UI edits, captures and trusted confirmation; production HTTP export gates."""
    import fitz
    from tools.documentation_baseline import docx_paragraphs

    marker = "Edited - source does not verify this value"
    ops = "operations_and_maintenance_manual"
    wi = "work_instructions"
    routes = {ops: "operations-manual", wi: "work-instructions"}
    report["visualArtifacts"] = {}
    report["p1bInputs"] = [name for name in server.original if any(part in name for part in
        ("docs/operations-manual/", "docs/process-map/", "generated/training/", "docs/semantic-knowledge/"))]
    renders = []

    def observe(response):
        if response.request.method == "POST" and re.search(r"/document/[^/]+/render$", urlsplit(response.url).path):
            renders.append({"url": response.url, "status": response.status})

    page.on("response", observe)

    def base(kind):
        return server.url + "/api/" + routes[kind] + "/" + ASSEMBLY

    def state(kind):
        response = request.get(base(kind) + "/documentation-scene", timeout=120000)
        if not response.ok:
            raise RuntimeError(response.text()[:1000])
        return response.json()

    def open_document(kind, page_id):
        # Reopening loads the app in a new tab (the old one is closed), then uses its visible type picker and
        # Refresh: a full reload with a fresh renderer. No document state injection or fake renderer.
        # (One tab reloaded eight or nine times froze headless Chromium in three runs; see stallProbe if it recurs.)
        nonlocal page
        page = fresh_page()
        page.on("response", observe)
        page.goto(server.url + "/?assemblyProfile=MMLE-50D", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_function("""() => window.__compareDbg?.state.partNumber === 'MMLE-50D'
            && window.__compareDbg.state.assyLiveScene""", timeout=90000)
        page.evaluate("() => window.__compareDbg.openDocumentationWorkflow()")
        page.locator("#documentationWorkspace").wait_for(state="visible", timeout=120000)
        page.wait_for_function("() => !document.querySelector('#documentationWorkspace.busy')", timeout=120000)
        page.locator("#documentationTypeRibbonTrigger").click()
        page.locator("#documentationTypeRibbonOption-" + kind).click()
        page.wait_for_function("kind => window.__compareDbg.state.documentationDocumentType === kind && !document.querySelector('#documentationWorkspace.busy')", arg=kind, timeout=120000)
        with page.expect_response(lambda r: r.request.method == "GET" and r.url == base(kind) + "/documentation-scene", timeout=120000):
            page.locator("#documentationRefreshRibbon").click()
        page.wait_for_function("() => !document.querySelector('#documentationWorkspace.busy') && window.__compareDbg.documentationGenerationSnapshot().visiblePageCount > 0", timeout=120000)
        # Refresh reveals the pages before its own activation of page 1 finishes rendering, so a click right after it
        # can be overtaken by that late render (the app's pre-existing refresh race). Click until the chosen page is
        # really active, and keep the attempt count as evidence.
        attempts = 0
        for attempts in range(1, 4):
            page.locator(f'.documentation-page-item[data-page-id="{page_id}"]').click()
            try:
                page.wait_for_function("""pageId => window.__compareDbg.state.partsManualDocumentationPageId === pageId
                    && !document.querySelector('#documentationWorkspace.busy')""", arg=page_id, timeout=5000)
                page.wait_for_timeout(1000)
                if page.evaluate("() => window.__compareDbg.state.partsManualDocumentationPageId") == page_id:
                    break
            except Exception:
                pass
        else:
            raise RuntimeError(f"Page {page_id} did not stay active after three clicks")
        report["workspaceOpens"].append({"phase": "P1b", "documentType": kind, "usedRefresh": True,
            "pageClickAttempts": attempts,
            "after": page.evaluate("() => window.__compareDbg.documentationGenerationSnapshot()")})

    def cell(alias):
        return page.locator(f'#documentationPublicationSurface [data-documentation-edit-target="{alias}"]:visible').first

    def edit(alias, value):
        target = cell(alias)
        begin_edit(target)
        target.fill(value)
        with page.expect_response(lambda r: r.request.method == "POST" and "documentation-scene/commands" in r.url, timeout=120000) as saved:
            target.press("Enter")
        if not saved.value.ok:
            raise RuntimeError(saved.value.text()[:1000])
        page.wait_for_function("() => !document.querySelector('#documentationWorkspace.busy')", timeout=120000)
        return saved.value.json()

    def capture_all(kind):
        start = len(renders)
        # Capture/export are not navigations; their completion is awaited below, so never block on the click.
        page.locator("#documentationCaptureAllRibbon").click(no_wait_after=True)
        page.wait_for_function("""() => {
            const payload = window.__compareDbg.state.partsManualDocumentation;
            const figures = (payload?.document?.pages || []).filter(p => p.renderRequest);
            return figures.length && figures.every(p => p.renderRequest.image?.status === 'ready')
                && !document.querySelector('#documentationWorkspace.busy');
        }""", timeout=240000)
        document = state(kind)["document"]
        figures = [p for p in document["pages"] if p.get("renderRequest")]
        record(kind + "_real_captures", len(renders) - start == len(figures)
               and all(row["status"] == 200 for row in renders[start:]), renders[start:])
        return document

    def export_ui(kind):
        with page.expect_response(lambda r: r.request.method == "POST" and urlsplit(r.url).path == urlsplit(base(kind)).path + "/pdf", timeout=180000) as exported:
            page.locator("#documentationPublishRibbon").click(no_wait_after=True)
        if not exported.value.ok:
            raise RuntimeError(exported.value.text()[:1000])
        page.wait_for_function("() => !document.querySelector('#documentationWorkspace.busy')", timeout=120000)
        return exported.value.json()

    def save_page(receipt, name, match):
        pdf_bytes = request.get(server.url + receipt["pdf"]["url"], timeout=120000).body()
        word = "\n".join(docx_paragraphs(request.get(server.url + receipt["docx"]["url"], timeout=120000).body()))
        (output / (name + ".pdf")).write_bytes(pdf_bytes)
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            index = next(i for i, p in enumerate(pdf) if match(p.get_text()))
            text = pdf[index].get_text()
            png = output / (name + ".png")
            pdf[index].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(str(png))
            report["visualArtifacts"][name] = {"path": png.relative_to(ROOT).as_posix(), "pageNumber": index + 1}
        return text, word

    def capacity(document):
        return next(b for p in document["pages"] for b in p.get("layoutBlocks", []) if b.get("blockId") == "spec-table-1")

    op_page, alias = "page-specifications-1", "spec-table-1.r0.c1"
    open_document(ops, op_page)
    original = capture_all(ops)
    original_row = capacity(original)["rows"][0]
    initial_claims = [row.get("claimIds", []) for row in capacity(original)["rows"]]
    edited = edit(alias, "1,000 lb")
    change_id = edited["command"]["commandId"]
    open_document(ops, op_page)
    record("p1b_operations_reopen_marked", cell(alias).inner_text() == "1,000 lb" and
        page.locator('#documentationPublicationSurface [data-evidence-marker]').count() > 0)
    read = tool("read_document_pages", {"documentType": ops, "targets": [{"pageId": op_page, "targetId": alias}]})
    if not read.get("ok"):
        raise RuntimeError(repr(read))
    data = read["data"]
    record("p1b_proof_read_marked", data["targets"][0]["provenance"]["evidenceStatus"] == "edited_unverified", read)
    document = state(ops)["document"]
    rows = capacity(document)["rows"]
    record("p1b_other_rows_keep_sources", rows[0]["claimIds"] == [] and
        [row.get("claimIds", []) for row in rows[1:]] == initial_claims[1:])
    text, word = save_page(export_ui(ops), "p1b-review-capacity", lambda text: "Rated capacity" in text)
    record("p1b_review_pdf_docx_marked", marker in text and marker in word and "1,000 lb" in text)
    expected = [{"targetId": target["targetId"], "pageId": target["pageId"], "alias": target["alias"]}
                for target in data["confirmationTargets"]]
    blocked = request.post(base(ops) + "/pdf?mode=customer", timeout=120000)
    record("p1b_customer_export_blocked_exact_targets", blocked.status == 422 and
        blocked.json().get("error") == "unconfirmed_cited_values" and blocked.json().get("details", {}).get("targets") == expected,
        blocked.json())
    proposal = tool("propose_document_value_confirmation", {"documentId": data["documentId"], "targets": [
        {"targetId": target["targetId"], "expectedContentHash": target["contentHash"]} for target in data["confirmationTargets"]]})
    record("p1b_proposal_does_not_confirm", proposal.get("data", {}).get("status") == "awaiting_user" and
        capacity(state(ops)["document"])["rows"][0]["provenance"]["evidenceStatus"] == "edited_unverified", proposal)
    # Both clicks are Playwright mouse events, hence trusted. Never dispatch an
    # event or invoke the confirmation handler through evaluate/the tool bridge.
    if not page.get_by_role("button", name="Confirm as entered by me", exact=True).first.is_visible():
        # At narrower widths the ribbon folds Inspector into More; use whichever control the user can see.
        direct = page.locator("#documentationInspectorRibbon")
        if direct.is_visible():
            direct.click()
        else:
            page.locator("#documentationOverflowMenuRibbon").click()
            page.locator(".documentation-ribbon-overflow-menu").get_by_role(
                "button", name="Open or close the object Inspector", exact=True).click()
    record("p1b_properties_show_edited", marker in page.locator("#documentationProperties").inner_text())
    page.get_by_role("button", name="Confirm as entered by me", exact=True).first.click()
    dialog = page.locator("dialog[open]")
    record("p1b_confirmation_shows_value_and_source", "1,000 lb" in dialog.inner_text() and "Original source:" in dialog.inner_text())
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/confirm-values"), timeout=120000) as confirmed:
        dialog.get_by_role("button", name="Confirm as entered by me", exact=True).click()
    if not confirmed.value.ok:
        raise RuntimeError(confirmed.value.text())
    confirmation_receipt = confirmed.value.json()["receipt"]
    customer = request.post(base(ops) + "/pdf?mode=customer", timeout=120000)
    record("p1b_customer_export_succeeds", customer.ok, customer.json())
    text, word = save_page(customer.json(), "p1b-customer-capacity", lambda text: "Rated capacity" in text)
    confirmed_row = capacity(state(ops)["document"])["rows"][0]
    record("p1b_confirmed_copy_clean", marker not in text + word and "1,000 lb" in text and
        not confirmed_row["claimIds"] and not confirmed_row["sourceIds"] and
        confirmed_row["provenance"]["evidenceStatus"] == "entered_by_user")
    inspected = tool("inspect_document_change", {"documentId": data["documentId"], "changeId": change_id})
    record("p1b_inspect_before_after", inspected.get("ok") and bool(inspected.get("data", {}).get("fields")), inspected)
    refused = tool("undo_document_change", {"documentId": data["documentId"], "changeId": change_id,
        "expectedRevision": confirmation_receipt["revision"], "requestId": "p1b-overlap"})
    record("p1b_undo_checks_confirmation_provenance", refused.get("error", {}).get("code") == "undo_conflict", refused)
    undone_confirmation = tool("undo_document_change", {"documentId": data["documentId"], "changeId": confirmation_receipt["changeId"],
        "expectedRevision": confirmation_receipt["revision"], "requestId": "p1b-undo-confirmation"})
    if not undone_confirmation.get("ok"):
        raise RuntimeError(repr(undone_confirmation))
    undone = tool("undo_document_change", {"documentId": data["documentId"], "changeId": change_id,
        "expectedRevision": undone_confirmation["data"]["receipt"]["revision"], "requestId": "p1b-undo-edit"})
    open_document(ops, op_page)
    restored = capacity(state(ops)["document"])["rows"][0]
    record("p1b_named_undo_restores_text_and_provenance", undone.get("ok") and cell(alias).inner_text() == "1,100 lb"
        and restored["claimIds"] == original_row["claimIds"] and restored["provenance"]["evidenceStatus"] == "source_backed", undone)

    cover = "page-work-instructions-cover"
    open_document(wi, cover)
    captured = capture_all(wi)
    figures = {p["pageId"]: p["figureRevision"] for p in captured["pages"] if p.get("renderRequest")}
    capture_count = len(renders)
    changed = edit("wi-cover-status", "P1b browser instruction note.")["document"]
    record("p1b_work_text_keeps_ready_figures", changed["documentRevision"] != captured["documentRevision"] and
        all(p["figureRevision"] == figures[p["pageId"]] and p["renderRequest"]["image"]["status"] == "ready"
            for p in changed["pages"] if p.get("renderRequest")))
    exported = export_ui(wi)
    text, word = save_page(exported, "p1b-work-instructions", lambda text: "P1b browser instruction note." in text)
    record("p1b_work_exports_without_recapture", len(renders) == capture_count and
        exported["pdf"]["documentRevision"] == exported["docx"]["documentRevision"] == changed["documentRevision"]
        and bool(word))  # Cover status is a known P4 DOCX gap.
    page.locator(f'.documentation-page-item[data-page-id="{cover}"]').click()
    page.locator("#documentationViewMenuRibbon").click()
    with page.expect_response(lambda r: r.request.method == "POST" and "documentation-scene/commands" in r.url, timeout=120000) as view:
        page.locator("#documentationViewRightRibbon").click()
    record("p1b_real_figure_change_saved", view.value.ok)
    figure_changed = state(wi)["document"]
    pending = [p["pageId"] for p in figure_changed["pages"] if p.get("renderRequest") and
               p["renderRequest"].get("image", {}).get("status") != "ready"]
    refused = request.post(base(wi) + "/pdf", timeout=120000)
    record("p1b_figure_change_requires_only_cover", pending == [cover] and refused.status == 422 and
        refused.json().get("error") == "work_instruction_capture_required" and
        [p["pageId"] for p in refused.json().get("pendingPages", [])] == [cover], refused.json())
    report["p1bCaptureRequests"] = renders
    page.remove_listener("response", observe)


def run_p1c(page, request, server, output, report, record, begin_edit, tool, fresh_page):
    """One Chromium, persistent real stores, UI/Sage twins and source-keyed row movement."""
    import fitz

    started = time.monotonic()
    plan_path = server.manual / "manual-plan.json"
    scene_path = server.manual / "documentation-scene.json"
    # The disposable legacy-shaped plan has no pinned item numbers. This makes
    # source sorting observable; approved explicit item assignments intentionally
    # remain fixed in production. The grouping and occurrence membership stay intact.
    plan = json.loads(plan_path.read_bytes())
    for section in plan["sections"]:
        section["itemAssignments"] = []
    write_json(plan_path, plan)
    scene_path.unlink(missing_ok=True)
    report["p1cFixture"] = {"unpinnedItemAssignments": True, "groupingUnchanged": True}

    def base():
        return server.url + "/api/parts-manual/" + ASSEMBLY

    def get_scene():
        response = request.get(base() + "/documentation-scene", timeout=120000)
        if not response.ok:
            raise RuntimeError(response.text()[:1000])
        return response.json()

    def review():
        response = request.get(server.url + "/api/documentation/" + DOC_TYPE + "/" + ASSEMBLY + "/conflicts?limit=100")
        if not response.ok:
            raise RuntimeError(response.text()[:1000])
        return response.json()

    def screenshot(name):
        filename = "p1c-" + name + ".png"
        page.screenshot(path=str(output / filename), full_page=True)
        report.setdefault("visualArtifacts", {})[name] = {"path": (output / filename).relative_to(ROOT).as_posix()}

    def idle():
        page.wait_for_function("() => !document.querySelector('#documentationWorkspace.busy')", timeout=120000)

    def open_workspace(stale=False):
        nonlocal page
        page = fresh_page()
        page.goto(server.url + "/?assemblyProfile=MMLE-50D", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_function("""() => window.__compareDbg?.state.partNumber === 'MMLE-50D'
            && window.__compareDbg.state.assyLiveScene""", timeout=90000)
        page.evaluate("() => window.__compareDbg.openDocumentationWorkflow()")
        page.locator("#documentationWorkspace").wait_for(state="visible", timeout=120000)
        idle()
        if stale:
            page.locator("#documentationSourceChanged").wait_for(state="visible")
            return
        snapshot = page.evaluate("() => window.__compareDbg.documentationGenerationSnapshot()")
        if not snapshot["visiblePageCount"]:
            page.locator("#documentationRefreshRibbon").click()
            page.wait_for_function("""() => window.__compareDbg.documentationGenerationSnapshot().visiblePageCount > 0
                && !document.querySelector('#documentationWorkspace.busy')""", timeout=120000)
        report["workspaceOpens"].append({"phase": "P1c",
            "after": page.evaluate("() => window.__compareDbg.documentationGenerationSnapshot()")})

    def navigate(page_id):
        if page.locator("#documentationConflictPane").is_visible():
            page.get_by_role("button", name="Close review", exact=True).click()
        for attempt in range(3):
            page.locator(f'.documentation-page-item[data-page-id="{page_id}"]').click()
            idle()
            page.wait_for_timeout(250)
            if page.evaluate("() => window.__compareDbg.state.partsManualDocumentationPageId") == page_id:
                return
        raise RuntimeError("Page activation did not settle")

    def cell(alias):
        return page.locator(f'#documentationPublicationSurface [data-documentation-edit-target="{alias}"]:visible').first

    def edit(alias, value):
        target = cell(alias)
        begin_edit(target)
        target.fill(value)
        with page.expect_response(lambda r: r.request.method == "POST" and "/documentation-scene/commands" in r.url,
                                  timeout=120000) as saved:
            target.press("Enter")
        record("p1c_edit_" + alias, saved.value.ok, saved.value.json().get("command"))
        idle()

    before = get_scene()
    chosen = next(p for p in before["document"]["pages"] if p.get("pageType") == "manual_section"
                  and 2 <= len(p.get("bom", [])) <= 12 and not p.get("bomContinuationCount"))
    row = chosen["bom"][0]
    target_id = row["cellIds"]["description"]
    # BOM cells are definition-keyed (part.<definitionId>.<field>) and carry that stable ID in the DOM; only
    # positional page text has an aliasMap entry.
    alias = next((a for a, entry in before["document"].get("aliasMap", {}).get(chosen["pageId"], {}).items()
                  if entry["targetId"] == target_id), target_id)
    baseline = row["description"]
    human = "P1c manual service description"
    generated = "P1c changed generated description"
    note = "P1c unrelated service note"
    merged = "P1c reviewed merged description"
    order_before = [r["definitionId"] for r in chosen["bom"]]
    open_workspace()
    navigate(chosen["pageId"])
    edit(alias, human)
    cover = next(p for p in before["document"]["pages"] if p["pageType"] == "cover")
    navigate(cover["pageId"])
    edit("cover_subtitle", note)
    record("p1c_two_browser_edits_saved", cell("cover_subtitle").inner_text() == note)

    changed = request.post(server.url + "/__p1c/source-fixture", data={
        "assemblyNumber": ASSEMBLY, "definitionId": row["definitionId"],
        "description": generated, "partNumber": "ZZZ-P1c-reordered"})
    record("p1c_source_fixture_persisted", changed.ok and (server.scratch / "source-fixture.json").is_file(),
           changed.json())
    open_workspace(stale=True)
    record("p1c_source_changed_shown", "Source revision changed" in page.locator("#documentationSourceChanged").inner_text())
    page.locator("#documentationSourceChanged").get_by_role("button", name="Refresh from source", exact=True).click()
    dialog = page.locator("#documentationRefreshDialog")
    dialog.get_by_role("button", name="Refresh now", exact=True).wait_for()
    record("p1c_refresh_preview", all(value in dialog.inner_text()
           for value in ("From binding:", "To binding:", "carries to the new source.")), dialog.inner_text())
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/refresh"),
                              timeout=120000) as refreshed:
        dialog.get_by_role("button", name="Refresh now", exact=True).click()
    record("p1c_refresh_executed", refreshed.value.ok, refreshed.value.json().get("refreshReceipt"))
    page.locator("#documentationRefreshReceipt").wait_for(state="visible", timeout=120000)
    screenshot("refresh-receipt")
    current = get_scene()
    conflict = next(c for c in review()["conflicts"] if c["targetId"] == target_id)
    cid, conflict_hash = conflict["conflictId"], conflict["conflictHash"]
    record("p1c_single_persistent_conflict", current["openConflictCount"] == 1)
    moved = next(p for p in current["document"]["pages"] if p["pageId"] == chosen["pageId"])
    order_after = [r["definitionId"] for r in moved["bom"]]
    record("p1c_rows_move_by_identity", order_before != order_after and set(order_before) == set(order_after)
           and order_after[-1] == row["definitionId"]
           and next(r for r in moved["bom"] if r["definitionId"] == row["definitionId"])["cellIds"]["description"] == target_id,
           {"before": order_before, "after": order_after})
    navigate(cover["pageId"])
    record("p1c_note_survives_refresh", cell("cover_subtitle").inner_text() == note)
    navigate(chosen["pageId"])
    marker = cell(alias)
    record("p1c_current_value_and_page_marker", marker.inner_text() == human
           and marker.get_attribute("data-documentation-conflict") == cid)
    screenshot("page-marker")
    # A double press must review this conflict instead of entering an editor.
    marker.dblclick()
    page.locator("#documentationConflictPane").wait_for(state="visible")
    record("p1c_conflict_blocks_inline_editor", not page.locator('[contenteditable="true"]').count())
    page.locator(f'[data-conflict-id="{cid}"]').wait_for()
    card = page.locator(f'[data-conflict-id="{cid}"]')
    record("p1c_pane_shows_B_C_N", all(card.locator(f'[data-conflict-side="{side}"]').inner_text() == value
           for side, value in (("B", baseline), ("C", human), ("N", generated))))
    record("p1c_status_count", page.locator("#documentationConflictCount").inner_text() == "1 conflict")
    screenshot("conflict-pane")

    page.get_by_role("button", name="Close review", exact=True).click()
    # Real capture path, as P1b: no fixture raster or forged publication status.
    page.locator("#documentationCaptureAllRibbon").click(no_wait_after=True)
    page.wait_for_function("""() => {
        const figures = (window.__compareDbg.state.partsManualDocumentation?.document?.pages || []).filter(p => p.renderRequest);
        return figures.length && figures.every(p => p.renderRequest.image?.status === 'ready')
            && !document.querySelector('#documentationWorkspace.busy');
    }""", timeout=240000)
    record("p1c_real_figures_captured", True)

    def export(mode):
        document = get_scene()["document"]
        return request.post(base() + "/pdf?mode=" + mode, data={k: document[k]
            for k in ("sourceRevision", "manualPlanRevision", "documentRevision")}, timeout=120000)

    exported = export("review")
    record("p1c_review_export_created", exported.ok, exported.json())
    if not exported.ok:
        raise RuntimeError("Review export failed: " + exported.text()[:1000])
    artifact = exported.json()["artifact"]
    pdf_response = request.get(server.url + artifact["url"], timeout=120000)
    pdf_bytes = pdf_response.body()
    (output / "p1c-review.pdf").write_bytes(pdf_bytes)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        text = "\n".join(p.get_text() for p in pdf)
    record("p1c_review_marks_conflict_and_count", "Open manual edit conflict" in text and cid in text
           and "Open manual edit conflicts: 1; unplaced manual content: 0" in text)
    blocked = export("customer")
    record("p1c_customer_export_blocked", not blocked.ok and blocked.json().get("error") == "manual_edit_conflict"
           and cid in blocked.json().get("details", {}).get("conflictIds", []), blocked.json())

    # Close the tab before stopping so intentional connection shutdowns are not
    # mislabeled as application failures. fresh_page removes observers first.
    page = fresh_page()
    retained = {name: sha(server.manual / name) for name in ("manual-plan.json", "documentation-scene.json")}
    server.restart()
    record("p1c_restart_keeps_stores", retained == {name: sha(server.manual / name) for name in retained})
    open_workspace()
    navigate(chosen["pageId"])
    record("p1c_restart_marker_and_count", cell(alias).get_attribute("data-documentation-conflict") == cid
           and page.locator("#documentationConflictCount").inner_text() == "1 conflict")
    page.locator("#documentationConflictCount").click()
    page.locator(f'[data-conflict-id="{cid}"]').wait_for()
    reopened = review()
    record("p1c_restart_same_conflict", reopened["conflicts"][0]["conflictHash"] == conflict_hash
           and reopened["conflicts"][0]["conflictId"] == cid)
    bound = tool("read_document_pages", {"documentType": DOC_TYPE, "targets": [{"targetId": target_id}]})
    if not bound.get("ok"):
        raise RuntimeError(repr(bound))
    sage = tool("read_document_conflicts", {"documentId": bound["data"]["documentId"]})
    record("p1c_sage_sees_same_conflict", sage.get("ok") and sage["data"]["conflicts"][0]["conflictId"] == cid
           and sage["data"]["conflicts"][0]["conflictHash"] == conflict_hash, sage)
    copies = {name: (server.manual / name).read_bytes() for name in retained}

    def stored_result():
        state = json.loads(scene_path.read_bytes())
        history = next(c for c in state["resolutionHistory"] if c["conflictId"] == cid)
        values = [p["pageElementOverrides"][target_id] for p in state["pages"].values()
                  if target_id in p.get("pageElementOverrides", {})]
        return {"values": values, "status": history["status"], "choice": history["resolution"]["choice"],
                "B": state["generatedBaseline"][target_id], "conflictB": history["B"]}

    card = page.locator(f'[data-conflict-id="{cid}"]')
    card.get_by_role("textbox", name="Merged text", exact=True).fill(merged)
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/conflicts/resolve"),
                              timeout=120000) as resolved:
        card.get_by_role("button", name="Merge", exact=True).click()
    record("p1c_browser_merge_saved", resolved.value.ok, resolved.value.json())
    page.wait_for_function("() => document.querySelector('#documentationConflictCount')?.textContent === '0 conflicts'")
    browser_result = stored_result()
    record("p1c_merge_stays_manual", browser_result["values"] and browser_result["values"][0]["text"] == merged)
    screenshot("resolved")
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/undo"),
                              timeout=120000) as undone:
        page.locator("#documentationUndoRibbon").click()
    record("p1c_browser_undo_succeeded", undone.value.ok)
    page.locator(f'[data-conflict-id="{cid}"]').wait_for()
    reopened_conflict = review()["conflicts"][0]
    record("p1c_undo_reopens_same_conflict", reopened_conflict["conflictHash"] == conflict_hash
           and all(reopened_conflict[side] == conflict[side] for side in ("B", "C", "N")))
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/redo"),
                              timeout=120000) as redone:
        page.locator("#documentationRedoRibbon").click()
    record("p1c_browser_redo_succeeded", redone.value.ok)
    page.wait_for_function("() => document.querySelector('#documentationConflictCount')?.textContent === '0 conflicts'")
    record("p1c_redo_same_stored_result", stored_result() == browser_result)

    page = fresh_page()
    server._stop_process()
    for name, raw in copies.items():
        (server.manual / name).write_bytes(raw)
    server.restart()
    bound = tool("read_document_pages", {"documentType": DOC_TYPE, "targets": [{"targetId": target_id}]})
    if not bound.get("ok"):
        raise RuntimeError(repr(bound))
    sage_read = tool("read_document_conflicts", {"documentId": bound["data"]["documentId"]})
    if not sage_read.get("ok"):
        raise RuntimeError(repr(sage_read))
    twin = sage_read["data"]["conflicts"][0]
    sage_result = tool("resolve_document_conflicts", {
        "documentId": sage_read["data"]["documentId"], "expectedRevision": twin["revision"], "requestId": "p1c-sage-twin",
        "resolutions": [{"conflictId": cid, "expectedConflictHash": twin["conflictHash"],
                         "choice": "merge_text", "mergedText": merged}]})
    record("p1c_sage_merge_saved", sage_result.get("ok"), sage_result)
    record("p1c_ui_and_sage_agree", stored_result() == browser_result, stored_result())
    allowed = export("customer")
    record("p1c_resolved_customer_not_conflict_blocked", allowed.ok or allowed.json().get("error") != "manual_edit_conflict",
           allowed.json())
    open_workspace()
    navigate(chosen["pageId"])
    record("p1c_resolved_reopen", cell(alias).inner_text() == merged
           and not cell(alias).get_attribute("data-documentation-conflict")
           and page.locator("#documentationConflictCount").inner_text() == "0 conflicts")
    screenshot("resolved-reopen")
    record("p1c_under_ten_minutes", time.monotonic() - started < 600, time.monotonic() - started)


def run_p2a(page, request, server, output, report, record, begin_edit, tool, fresh_page):
    """One real Chromium, shared scene writes, CDP IME, persisted rich rendering."""
    from ai_inspector.documentation.rich_text import from_plain, plain_text, validate

    spec = "product_specification_sheet"
    routes = {spec: "specification-sheet", DOC_TYPE: "parts-manual"}
    object_id = "document-object-p2a"
    posts = []

    def base(kind=spec):
        return server.url + "/api/" + routes[kind] + "/" + ASSEMBLY

    def scene(kind=spec):
        response = request.get(base(kind) + "/documentation-scene", timeout=120000)
        if not response.ok:
            raise RuntimeError(response.text()[:1000])
        return response.json()

    def field(payload, key=object_id):
        return next(row for row in payload["richTextFields"] if row["legacyTargetId"] == key)

    def create(kind, key, value):
        before = scene(kind)
        page_id = before["document"]["pages"][0]["pageId"]
        response = request.post(base(kind) + "/documentation-scene/commands", data={
            "baseRevision": before["revision"], "sourceRevision": before["scene"]["sourceRevision"],
            "manualPlanRevision": before["scene"]["manualPlanRevision"],
            "operation": "add_object", "pageId": page_id, "targetType": "document_object", "targetId": key,
            "documentObject": {"objectId": key, "type": "text", "name": "Rich text proof", "source": "user",
                "content": value, "frame": {"x": 0.12, "y": 0.28, "width": 0.66, "height": 0.24},
                "styleOverrides": {"fontSize": 16, "fill": "#FFFFFF", "color": "#18212A"}}}, timeout=120000)
        if not response.ok:
            raise RuntimeError(response.text()[:1000])
        response.body()  # Consume writes before any reload or navigation.
        return page_id

    def observe(req):
        if req.method == "POST" and "/documentation-scene/" in req.url:
            posts.append({"url": req.url, "body": req.post_data_json})

    def idle():
        page.wait_for_function("() => !document.querySelector('#documentationWorkspace.busy')", timeout=120000)

    def commands():
        return sum(1 for row in posts if row["url"].endswith("/documentation-scene/commands"))

    def saved_command():
        return page.expect_response(lambda r: r.request.method == "POST"
                                    and r.url.endswith("/documentation-scene/commands"), timeout=120000)

    def switch(kind):
        page.locator("#documentationTypeRibbonTrigger").click()
        page.locator("#documentationTypeRibbonOption-" + kind).click()
        page.wait_for_function("kind => window.__compareDbg.state.documentationDocumentType === kind && !document.querySelector('#documentationWorkspace.busy')",
                               arg=kind, timeout=120000)

    def navigate(page_id):
        for _ in range(3):
            page.locator(f'.documentation-page-item[data-page-id="{page_id}"]').click()
            idle()
            page.wait_for_timeout(250)
            if page.evaluate("() => window.__compareDbg.state.partsManualDocumentationPageId") == page_id:
                return
        raise RuntimeError("Rich editor page activation did not settle")

    def refresh():
        # Use the real ribbon callback without moving focus; this is the same reload
        # the Sage completion/poll paths perform while a user is still typing.
        with page.expect_response(lambda r: r.request.method == "GET" and r.url.endswith("/documentation-scene"), timeout=120000) as response:
            page.locator("#documentationRefreshRibbon").evaluate("button => button.click()")
        response.value.finished()
        idle()
        page.wait_for_function("() => window.__compareDbg.documentationGenerationSnapshot().visiblePageCount > 0", timeout=120000)

    def open_document(kind, page_id):
        nonlocal page
        page = fresh_page()
        page.on("request", observe)
        page.goto(server.url + "/?assemblyProfile=MMLE-50D", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_function("() => window.__compareDbg?.state.partNumber === 'MMLE-50D' && window.__compareDbg.state.assyLiveScene", timeout=90000)
        page.evaluate("() => window.__compareDbg.openDocumentationWorkflow()")
        page.locator("#documentationWorkspace").wait_for(state="visible", timeout=120000)
        idle()
        if page.evaluate("() => window.__compareDbg.state.documentationDocumentType") != kind:
            switch(kind)
        refresh()
        navigate(page_id)
        report["workspaceOpens"].append({"phase": "P2a", "documentType": kind, "pageId": page_id})

    def box(key=object_id):
        return page.locator(f'#documentationPublicationSurface [data-documentation-object-id="{key}"]')

    def mount(key=object_id):
        begin_edit(box(key))
        page.wait_for_function("() => window.DocumentationRichText?.mountedCount === 1", timeout=30000)
        return page.locator('.documentation-rich-editor [contenteditable="true"]')

    def finish(blur=False):
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/commands"), timeout=120000) as saved:
            if blur:
                page.locator('.documentation-rich-editor [contenteditable="true"]').evaluate("node => node.blur()")
            else:
                page.locator('[data-rich-action="done"]').click()
        saved.value.finished()
        if not saved.value.ok:
            raise RuntimeError(saved.value.text()[:1000])
        page.wait_for_function("() => window.DocumentationRichText.mountedCount === 0", timeout=120000)
        idle()
        return saved.value.json()

    def screenshot(name):
        filename = "p2a-" + name + ".png"
        page.screenshot(path=str(output / filename), full_page=True)
        report.setdefault("visualArtifacts", {})[name] = {"path": (output / filename).relative_to(ROOT).as_posix()}

    original = "Alpha beta gamma"
    page_id = create(spec, object_id, original)
    open_document(spec, page_id)
    version = (ROOT / "static/vendor/tiptap/VERSIONS.md").read_text("utf-8")
    expected_sha = re.search(r"SHA-256 `([0-9a-f]{64})`", version).group(1)
    exports = sorted(re.findall(r"`(\w+)`", version.split("## Exports", 1)[1].split("## Rebuild", 1)[0]))
    bundle = ROOT / "static/vendor/tiptap/tiptap.bundle.js"
    export_block = re.search(r"export\s*\{([^}]+)\}", bundle.read_text("ascii")).group(1)
    file_exports = sorted(item.strip().split(" as ")[-1] for item in export_block.split(",") if item.strip())
    browser_vendor = page.evaluate("""async () => {
        const url = '/static/vendor/tiptap/tiptap.bundle.js?v=c36fd989775f';
        const bytes = await (await fetch(url)).arrayBuffer();
        const digest = await crypto.subtle.digest('SHA-256', bytes);
        return {sha: [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2,'0')).join(''),
            exports: Object.keys(await import(url)).sort(), ready: await DocumentationRichText.ready};
    }""")
    record("p2a_01_vendor_and_ready", sha(bundle) == expected_sha == browser_vendor["sha"]
           and file_exports == exports == browser_vendor["exports"] and browser_vendor["ready"]["ok"], browser_vendor)
    editor = mount()
    record("p2a_02_spec_text_box_mount", page.evaluate("() => DocumentationRichText.mountedCount") == 1
           and field(scene())["owner"] == "scene")
    screenshot("mounted-ribbon")

    # Set a real DOM range, then use a real pointer click on the ribbon.
    editor.evaluate("""node => {
        const text = node.querySelector('p').firstChild;
        const range = document.createRange(); range.setStart(text, 6); range.setEnd(text, 10);
        const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
        window.__p2aMountedElement = DocumentationRichText.active.element;
        window.__p2aEditor = DocumentationRichText.active.editor;
    }""")
    page.locator('.documentation-rich-controls [data-rich-action="bold"]').click()
    record("p2a_03_selection_ribbon", page.evaluate("""() => {
        const c = DocumentationRichText.active;
        const runs = c.editor.getJSON().content[0].content;
        return c.element === window.__p2aMountedElement && c.editor === window.__p2aEditor
            && getSelection().toString() === 'beta'
            && runs.filter(n => n.marks?.some(m => m.type === 'bold')).map(n => n.text).join('') === 'beta';
    }"""))
    # A workspace reload re-renders the page and its object layer while the editor is mounted.
    refresh()
    record("p2a_03_reload_preserves_editor_and_selection", page.evaluate("""() =>
        DocumentationRichText.active?.element === window.__p2aMountedElement
        && DocumentationRichText.active?.editor === window.__p2aEditor
        && DocumentationRichText.active.editor.state.selection.from === 7
        && DocumentationRichText.active.editor.state.selection.to === 11"""))
    editor = page.locator('.documentation-rich-editor [contenteditable="true"]')
    editor.press("Control+End")
    pasted = "\nline two\n\n  \U0001f642 e\u0301\tend  "
    # Dispatch a clipboard event at the actual editor; the production paste handler
    # supplies inline JSON to ProseMirror (no direct editor-content mutation).
    editor.evaluate("""(node, text) => {
        const data = new DataTransfer(); data.setData('text/plain', text);
        node.dispatchEvent(new ClipboardEvent('paste', {clipboardData:data, bubbles:true, cancelable:true}));
    }""", pasted)
    finish(blur=True)
    current = field(scene())
    record("p2a_04_multiline_unicode_blur_commit", current["isRichText"]
           and validate(current["richText"]) == current["richText"]
           and plain_text(current["richText"]) == current["text"] == original + pasted)

    editor = mount()
    editor.press("Control+End")
    before_ime = len(posts)
    cdp = page.context.new_cdp_session(page)
    try:
        cdp.send("Input.imeSetComposition", {"text": "\u6f22", "selectionStart": 1, "selectionEnd": 1})
        page.wait_for_function("() => DocumentationRichText.active?.composing", timeout=5000)
        # Request save without moving native IME focus (a focus change may itself
        # legitimately finish composition before the click event reaches Done).
        page.evaluate('() => DocumentationRichText.active.commit()')
        page.wait_for_timeout(250)
        record("p2a_05_ime_no_mid_composition_commit", len(posts) == before_ime
               and page.evaluate("() => DocumentationRichText.mountedCount") == 1)
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/commands"), timeout=120000) as composed:
            cdp.send("Input.insertText", {"text": "\u6f22\u5b57"})
        composed.value.finished()
        if not composed.value.ok:
            raise RuntimeError(composed.value.text()[:1000])
        page.wait_for_function("() => DocumentationRichText.mountedCount === 0", timeout=120000)
    finally:
        cdp.detach()
    record("p2a_05_ime_saved", field(scene())["text"] == original + pasted + "\u6f22\u5b57")

    unchanged = field(scene())["richText"]
    editor = mount()
    count = len(posts)
    editor.press("Control+End")
    page.keyboard.insert_text(" canceled")
    editor.press("Escape")
    page.wait_for_timeout(300)
    record("p2a_06_escape_no_command", len(posts) == count and field(scene())["richText"] == unchanged
           and page.evaluate("() => DocumentationRichText.mountedCount") == 0)

    editor = mount()
    count = len(posts)
    editor.press("Control+End")
    page.keyboard.insert_text(" local undo")
    editor.press("Control+z")
    record("p2a_07_local_undo_only", len(posts) == count
           and page.evaluate("() => DocumentationRichTextCore.plainText(DocumentationRichText.active.editor.getJSON())")
           == plain_text(unchanged))
    editor.press("Control+y")
    record("p2a_07_local_redo_only", len(posts) == count
           and page.evaluate("() => DocumentationRichTextCore.plainText(DocumentationRichText.active.editor.getJSON())")
           == plain_text(unchanged) + " local undo")
    editor.press("Control+z")
    page.keyboard.insert_text(" committed")
    finish()
    committed = field(scene())["richText"]
    for direction, expected in (("undo", unchanged), ("redo", committed)):
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/" + direction), timeout=120000) as moved:
            page.locator("#documentation" + direction.title() + "Ribbon").click()
        moved.value.finished()
        if not moved.value.ok:
            raise RuntimeError(moved.value.text()[:1000])
        idle()
        record("p2a_07_document_" + direction, field(scene())["richText"] == expected)

    editor = mount()
    editor.press("Control+End")
    page.keyboard.insert_text(" retained draft")
    draft = page.evaluate("() => DocumentationRichTextCore.plainText(DocumentationRichText.active.editor.getJSON())")
    page.evaluate("() => { window.__p2aMountedElement = DocumentationRichText.active.element; }")
    bound = tool("read_document_pages", {"documentType": spec, "targets": [{"pageId": page_id, "targetId": object_id}]})
    if not bound.get("ok"):
        raise RuntimeError(repr(bound))
    observed = bound["data"]["targets"][0]
    newer = from_plain("Sage newer value")
    applied = tool("apply_document_edits", {"documentId": bound["data"]["documentId"],
        "expectedRevision": observed["revision"], "requestId": "p2a-dirty-draft", "operations": [{
            "operation": "replace_rich_text", "targetId": observed["targetId"],
            "expectedContentHash": observed["contentHash"], "richText": newer}]})
    if not applied.get("ok"):
        raise RuntimeError(repr(applied))
    count = len(posts)
    refresh()
    page.locator('.documentation-rich-panel[data-conflict="true"]').wait_for(state="visible")
    record("p2a_08_concurrent_sage_draft_kept", len(posts) == count and field(scene())["richText"] == newer
           and page.evaluate("() => DocumentationRichText.active.element === window.__p2aMountedElement")
           and page.evaluate("() => DocumentationRichTextCore.plainText(DocumentationRichText.active.editor.getJSON())") == draft)
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/commands"), timeout=120000) as overwritten:
        page.locator('[data-rich-action="overwrite"]').click()
    overwritten.value.finished()
    if not overwritten.value.ok:
        raise RuntimeError(overwritten.value.text()[:1000])
    page.wait_for_function("() => DocumentationRichText.mountedCount === 0", timeout=120000)
    record("p2a_08_explicit_overwrite", field(scene())["text"] == draft)

    before_keys = scene()
    frame = before_keys["scene"]["pages"][page_id]["documentObjects"][object_id]["frame"]
    editor = mount()
    count = len(posts)
    editor.press("Control+Home")
    for key in ("ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Backspace", "Delete"):
        editor.press(key)
    rect = editor.bounding_box()
    page.mouse.move(rect["x"] + 12, rect["y"] + 10)
    page.mouse.down()
    page.mouse.move(rect["x"] + min(110, rect["width"] - 10), rect["y"] + 10, steps=8)
    page.mouse.up()
    selection = page.evaluate("() => getSelection().toString()")
    after_keys = scene()
    record("p2a_09_keys_and_pointer_select_text", len(posts) == count and bool(selection)
           and after_keys["scene"]["pages"][page_id]["documentObjects"][object_id]["frame"] == frame
           and field(after_keys)["richText"] == field(before_keys)["richText"])
    editor.press("Escape")

    # A press elsewhere on the page ends editing like Done: one save, and no other object is selected
    # (keys must never go to this editor while another object looks selected).
    editor = mount()
    editor.press("Control+End")
    page.keyboard.insert_text(" pressed away")
    pressed_draft = page.evaluate("() => DocumentationRichTextCore.plainText(DocumentationRichText.active.editor.getJSON())")
    rect = box().bounding_box()
    surface_rect = page.locator("#documentationPublicationSurface").bounding_box()
    away = [rect["x"] + rect["width"] / 2,
            min(rect["y"] + rect["height"] + 24, surface_rect["y"] + surface_rect["height"] - 4)]
    on_page = page.evaluate("([x, y]) => Boolean(document.elementFromPoint(x, y)?.closest('#documentationPublicationSurface'))", away)
    count = commands()
    with saved_command() as pressed:
        page.mouse.click(*away)
    pressed.value.finished()
    page.wait_for_function("() => DocumentationRichText.mountedCount === 0", timeout=120000)
    idle()
    selected = page.evaluate("() => window.__compareDbg.state.partsManualDocumentationSelection?.targetId || null")
    pressed_field = field(scene())
    record("p2a_09_press_elsewhere_commits", on_page and pressed.value.ok and commands() == count + 1
           and pressed_field["text"] == pressed_draft and selected in (None, object_id, pressed_field["targetId"]),
           {"selected": selected, "point": away, "onPage": on_page})

    open_document(spec, page_id)
    record("p2a_10_formatted_canvas_after_reload", page.evaluate("() => DocumentationRichText.mountedCount") == 0
           and box().locator("strong").all_text_contents() == ["beta"])
    screenshot("saved-reloaded")
    # Switch to a second real parts page for the page-disposal check if the sheet
    # has one page; no synthetic page is injected into the renderer.
    parts_key = "document-object-p2a-parts"
    parts_page = create(DOC_TYPE, parts_key, "Parts proof")
    mount().press("Control+End")
    page.keyboard.insert_text(" saved on switch")
    switched_draft = page.evaluate("() => DocumentationRichTextCore.plainText(DocumentationRichText.active.editor.getJSON())")
    count = commands()
    switch(DOC_TYPE)
    record("p2a_11_document_switch_saves_and_disposes", page.evaluate("() => DocumentationRichText.mountedCount") == 0
           and commands() == count + 1 and field(scene())["text"] == switched_draft)
    refresh()
    navigate(parts_page)
    editor = mount(parts_key)
    editor.press("Control+End")
    page.keyboard.insert_text(" kept")
    next_page = next(p["pageId"] for p in scene(DOC_TYPE)["document"]["pages"] if p["pageId"] != parts_page)
    count = commands()
    with saved_command() as kept:
        page.locator(f'.documentation-page-item[data-page-id="{next_page}"]').click()
    kept.value.finished()
    page.wait_for_function("id => window.__compareDbg.state.partsManualDocumentationPageId === id",
                           arg=next_page, timeout=120000)
    idle()
    record("p2a_11_page_switch_saves_and_disposes", kept.value.ok
           and page.evaluate("() => DocumentationRichText.mountedCount") == 0 and commands() == count + 1
           and field(scene(DOC_TYPE), parts_key)["text"] == "Parts proof kept")
    navigate(parts_page)
    editor = mount(parts_key)
    editor.press("Control+End")
    page.keyboard.insert_text(" edited")
    finish()
    record("p2a_12_parts_shared_adapter", field(scene(DOC_TYPE), parts_key)["text"] == "Parts proof kept edited"
           and field(scene(DOC_TYPE), parts_key)["isRichText"])

    # Retain the exact disposable stores; restart without the flag, in the same Chromium.
    page = fresh_page()  # Detach old-tab observers before stopping its server.
    server.rich_text = False
    server.restart()
    open_document(spec, page_id)
    count = len(posts)
    box().dblclick()
    page.wait_for_timeout(300)
    record("p2a_13_flag_off_readonly", not scene()["documentationRichText"]
           and page.evaluate("() => DocumentationRichText.mountedCount") == 0
           and page.locator('.documentation-rich-controls').count() == 0
           and not box().evaluate('node => node.isContentEditable')
           and box().locator('[contenteditable="true"]').count() == 0
           and box().locator('strong').all_text_contents() == ["beta"] and len(posts) == count)
    screenshot("flag-off-readonly")
    report["p2aScenePosts"] = posts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=PHASES)
    args = parser.parse_args()
    output = ROOT / ".runtime" / "de"
    output.mkdir(parents=True, exist_ok=True)
    report = {"phase": args.phase, "assembly": ASSEMBLY, "checks": {}, "editAttempts": [], "browserErrors": [],
              "consoleErrors": [], "networkFailures": [], "httpFailures": [], "outboundRequests": [], "passed": False,
              "knownFixtureLimitations": KNOWN_FIXTURE_LIMITATIONS, "failureScreenshots": [], "workspaceOpens": []}
    server = IsolatedDocumentationServer(output, phase=args.phase)
    playwright = browser = context = page = None
    page_handlers = {}
    probe_session = {}

    def on_blocked():
        # Runs on the watchdog thread while the main thread waits on a renderer that no longer answers DevTools.
        report.setdefault("stallProbe", {})["blocked"] = "Renderer stopped answering DevTools; the run was ended."
        report["passed"] = False
        try:
            write_json(output / "report.json", report)
            print(json.dumps(report, sort_keys=True), flush=True)
        finally:
            try:
                server.stop()
            finally:
                os._exit(3)

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
        # Playwright's mouse waits for each press to be handled (including the redraw) before sending the next, which
        # a person's queued presses never do. Send two real presses 150 ms apart with explicit event timestamps, the
        # way the system delivers a quick double press; the workspace times presses by event.timeStamp.
        # A double press that lands while a just-activated page is still redrawing selects nothing; like a person,
        # wait for the workspace to be idle and press again (at most three times). Attempts are kept as evidence.
        for attempt in range(1, 4):
            page.wait_for_function("() => !document.querySelector('#documentationWorkspace.busy')", timeout=120000)
            cell.wait_for(state="visible", timeout=30000)
            box = cell.bounding_box()
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            cdp = page.context.new_cdp_session(page)
            try:
                start = time.time()
                cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "timestamp": start})
                for offset in (0.0, 0.15):
                    for kind, lag, buttons in (("mousePressed", 0.0, 1), ("mouseReleased", 0.03, 0)):
                        cdp.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left",
                                  "buttons": buttons, "clickCount": 1, "timestamp": start + offset + lag})
            finally:
                cdp.detach()
            try:
                page.wait_for_function("() => !!document.querySelector('[contenteditable=\"true\"]')", timeout=5000)
                report["editAttempts"].append(attempt)
                return
            except Exception:
                page.wait_for_timeout(1000)
        raise RuntimeError("Inline edit did not start after three double presses")

    try:
        if args.phase not in {"P1a", "P1b", "P1c", "P2a"}:
            raise RuntimeError("Only the P1a, P1b, P1c and P2a gates are implemented.")
        from playwright.sync_api import sync_playwright
        server.start()
        report["isolation"] = server.isolation
        playwright = sync_playwright().start()
        # The headless shell renders WebGL in software (SwiftShader), which hangs on this 3D-heavy app under memory
        # pressure. Full Chromium's headless mode can use the real GPU (Direct3D 11) without a visible window; fall
        # back to the shell when it is unavailable, and record the renderer either way.
        try:
            browser = playwright.chromium.launch(headless=True, channel="chromium",
                                                 args=["--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist"])
            report["browserMode"] = "chromium-headless-gpu"
        except Exception as error:
            browser = playwright.chromium.launch(headless=True)
            report["browserMode"] = "headless-shell (" + type(error).__name__ + ")"
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
        probe_session["cdp"] = attach_stall_probe(page)
        report["webglRenderer"] = page.evaluate("""() => {
            const gl = document.createElement('canvas').getContext('webgl2');
            const info = gl && gl.getExtension('WEBGL_debug_renderer_info');
            return gl ? (info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)) : null;
        }""")
        page_handlers = {
            "pageerror": lambda error: report["browserErrors"].append(str(error)),
            "console": lambda event: report["consoleErrors"].append(
                {"message": event.text, "location": event.location}) if event.type == "error" else None,
            "requestfailed": lambda request: report["networkFailures"].append(
                {"url": request.url, "method": request.method, "error": request.failure}),
            "response": lambda response: report["httpFailures"].append(
                {"url": response.url, "status": response.status, "method": response.request.method})
                if response.status >= 400 else None,
            "crash": lambda crashed: report["browserErrors"].append("Renderer process crashed"),
            "dialog": lambda dialog: (report["browserErrors"].append(
                f"Unexpected {dialog.type} dialog: {dialog.message[:200]}"), dialog.dismiss()),
        }
        for event, handler in page_handlers.items():
            page.on(event, handler)

        def fresh_page():
            # Stop observing the old tab before closing it: closing cancels its background reads on purpose.
            nonlocal page
            for name, listener in page_handlers.items():
                page.remove_listener(name, listener)
            page.close()
            page = context.new_page()
            for name, listener in page_handlers.items():
                page.on(name, listener)
            probe_session["cdp"] = attach_stall_probe(page)
            return page

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

        if args.phase == "P2a":
            run_p2a(page, request, server, output, report, record, begin_edit, tool, fresh_page)
        elif args.phase == "P1c":
            run_p1c(page, request, server, output, report, record, begin_edit, tool, fresh_page)
        else:
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
            record("scene_upgraded_in_place", reopened["scene"]["schemaVersion"] == 5
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
                                      timeout=120000) as first_undo:
                page.locator("#documentationUndoRibbon").click()
            # The reopen reloads the page: let the (large) response body finish first, or Chromium aborts it.
            first_undo.value.finished()
            open_workspace()
            record("batch_undo_is_one_step", page.locator(
                f'#documentationPublicationSurface [data-documentation-edit-target="{alias}"]:visible').first.inner_text() == human_text
                and page.locator(f'#documentationPublicationSurface [data-documentation-edit-target="{other_alias}"]:visible').first.inner_text() == targets[1]["text"])
            with page.expect_response(lambda response: response.request.method == "POST" and "/undo" in response.url,
                                      timeout=120000) as second_undo:
                page.locator("#documentationUndoRibbon").click()
            second_undo.value.finished()
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
            if args.phase == "P1b":
                run_p1b(page, request, server, output, report, record, begin_edit, tool, fresh_page)
    except Exception as error:
        report["fatalError"] = f"{type(error).__name__}: {error}"
        if type(error).__name__ == "TimeoutError" and page is not None and not page.is_closed() and probe_session:
            stall_probe(page, probe_session["cdp"], report, on_blocked)
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
