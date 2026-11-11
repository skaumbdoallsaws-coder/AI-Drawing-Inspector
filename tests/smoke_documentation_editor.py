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
RICH_PROOF_TEXT = "Alpha beta gamma"
RICH_PROOF_PASTE = "\nline two\n\n  \U0001f642 e\u0301\tend  "
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
    "The isolated parts manual has no CAD captures, so it is not publication-ready and its Publish button stays "
    "disabled; P2b proves the parts region on the canvas and through Sage, and its PDF path in "
    "tests/test_documentation_rich_exports.py.",
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
    known_http, unexpected_http, known = [], [], []
    expected = list(report.get("expectedHttpFailures", [])) if report.get("phase") in {"P2b", "P3b"} else []
    for item in report["httpFailures"]:
        reason = known_http_failure(item)
        proof = next((row for row in expected if report.get("phase") == "P2b" and row.get("error") == "unsupported_export_glyph"
                      and row.get("checked") is True and row.get("status") == item.get("status") == 422
                      and row.get("method") == item.get("method") == "POST" and row.get("url") == item.get("url")
                      and urlsplit(item["url"]).path == "/api/specification-sheet/MMLE-50D/pdf"), None)
        if proof is None and report.get("phase") == "P3b":
            proof = next((row for row in expected if row.get("error") == "table_column_too_narrow"
                          and row.get("checked") is True and row.get("status") == item.get("status") == 422
                          and row.get("method") == item.get("method") == "POST" and row.get("url") == item.get("url")
                          and urlsplit(item["url"]).path == "/api/documentation/operations_and_maintenance_manual/MMLE-50D/tables"), None)
        if proof is not None:
            expected.remove(proof)  # Exactly one observed, checked proof refusal.
            reason = "Expected " + proof["error"] + " proof refusal"
        if reason:
            known_http.append(item)
            known.append({"kind": "http", **item, "reason": reason})
        else:
            unexpected_http.append(item)
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
            known.append({"kind": "console", **item, "reason": "Console consequence of a classified HTTP failure"})
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
        self.rich_text = phase in {"P2a", "P2b", "P3a", "P3b"}
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
        names.update(p.relative_to(ROOT).as_posix()
                     for p in (ROOT / "static/assets/documentation-ribbon-icons").glob("*.svg"))
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


def rich_select_word(page, editor, word):
    editor.evaluate("""(node, word) => {
        const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
        const nodes = []; let text = '', current;
        while ((current = walker.nextNode())) {
            if (current.parentElement.closest('[contenteditable="false"]')) continue;
            nodes.push({node:current, start:text.length}); text += current.textContent;
        }
        const start = text.indexOf(word), end = start + word.length;
        if (start < 0) throw new Error('Proof word is missing: ' + word);
        const first = nodes.find(item => start >= item.start && start < item.start + item.node.length);
        const last = nodes.find(item => end > item.start && end <= item.start + item.node.length);
        const range = document.createRange(); range.setStart(first.node, start - first.start); range.setEnd(last.node, end - last.start);
        const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
        window.__p2aMountedElement = DocumentationRichText.active.element;
        window.__p2aEditor = DocumentationRichText.active.editor;
    }""", word)


def rich_paste(editor, value, mime="text/plain"):
    editor.evaluate("""(node, {value, mime}) => {
        const data = new DataTransfer(); data.setData(mime, value);
        node.dispatchEvent(new ClipboardEvent('paste', {clipboardData:data, bubbles:true, cancelable:true}));
    }""", {"value": value, "mime": mime})


def rich_compose(page, check_pending):
    cdp = page.context.new_cdp_session(page)
    try:
        cdp.send("Input.imeSetComposition", {"text": "\u6f22", "selectionStart": 1, "selectionEnd": 1})
        page.wait_for_function("() => DocumentationRichText.active?.composing", timeout=5000)
        # Request save without moving native IME focus (a focus change may itself
        # legitimately finish composition before the click event reaches Done).
        page.evaluate('() => DocumentationRichText.active.commit()')
        page.wait_for_timeout(250)
        check_pending()
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/commands"), timeout=120000) as composed:
            cdp.send("Input.insertText", {"text": "\u6f22\u5b57"})
        composed.value.finished()
        if not composed.value.ok:
            raise RuntimeError(composed.value.text()[:1000])
        page.wait_for_function("() => DocumentationRichText.mountedCount === 0", timeout=120000)
    finally:
        cdp.detach()


def rich_browser_helpers(page, request, server, output, report, begin_edit, fresh_page, phase):
    """Shared real scene/browser controls for P2a and P2b; no editor mocks."""
    from types import SimpleNamespace
    spec = "product_specification_sheet"
    routes = {spec: "specification-sheet", DOC_TYPE: "parts-manual",
              "operations_and_maintenance_manual": "operations-manual", "work_instructions": "work-instructions"}
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

    def create(kind, key, value, *, frame=None, style=None):
        before = scene(kind)
        page_id = before["document"]["pages"][0]["pageId"]
        response = request.post(base(kind) + "/documentation-scene/commands", data={
            "baseRevision": before["revision"], "sourceRevision": before["scene"]["sourceRevision"],
            "manualPlanRevision": before["scene"]["manualPlanRevision"],
            "operation": "add_object", "pageId": page_id, "targetType": "document_object", "targetId": key,
            "documentObject": {"objectId": key, "type": "text", "name": "Rich text proof", "source": "user",
                "content": value, "frame": frame or {"x": 0.12, "y": 0.28, "width": 0.66, "height": 0.24},
                "styleOverrides": {"fontSize": 16, "fill": "#FFFFFF", "color": "#18212A", **(style or {})}}}, timeout=120000)
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

    def refresh(pointer=False):
        # Use the real ribbon callback without moving focus; this is the same reload
        # the Sage completion/poll paths perform while a user is still typing.
        with page.expect_response(lambda r: r.request.method == "GET" and r.url.endswith("/documentation-scene"), timeout=120000) as response:
            if pointer:
                page.locator("#documentationRefreshRibbon").click()
            else:
                page.locator("#documentationRefreshRibbon").evaluate("button => button.click()")
        response.value.finished()
        idle()
        page.wait_for_function("() => window.__compareDbg.documentationGenerationSnapshot().visiblePageCount > 0", timeout=120000)

    def open_document(kind, page_id, *, pointer_refresh=False):
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
        refresh(pointer_refresh)
        navigate(page_id)
        report["workspaceOpens"].append({"phase": phase, "documentType": kind, "pageId": page_id})
        return page

    def box(key=object_id, *, generated=False):
        attribute = "data-documentation-edit-target" if generated else "data-documentation-object-id"
        return page.locator(f'#documentationPublicationSurface [{attribute}="{key}"]').first

    def mount(key=object_id, *, generated=False):
        begin_edit(box(key, generated=generated))
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

    def press_export(kind, format="pdf"):
        with page.expect_response(lambda r: r.request.method == "POST" and r.url == base(kind) + "/pdf", timeout=600000) as response:
            page.locator("#documentationExportDocxRibbon" if format == "docx" else "#documentationPublishRibbon").click()
        response.value.finished()  # Never reload with a large POST body in flight.
        idle()
        return response.value, response.value.json()

    def download(artifact, filename):
        assert artifact.get("url", "").startswith("/api/"), artifact
        response = request.get(server.url + artifact["url"], timeout=120000)
        assert response.ok, response.text()[:500]
        payload = response.body()
        (output / filename).write_bytes(payload)
        report.setdefault("exportArtifacts", []).append({"file": filename, "sha256": hashlib.sha256(payload).hexdigest(),
                                                         "bytes": len(payload)})
        return payload

    def canvas_lines(key=object_id):
        return box(key).evaluate(CANVAS_LINES_JS)

    def screenshot(name):
        filename = phase.lower() + "-" + name + ".png"
        page.screenshot(path=str(output / filename), full_page=True)
        report.setdefault("visualArtifacts", {})[name] = {"path": (output / filename).relative_to(ROOT).as_posix()}

    return SimpleNamespace(**locals())


def run_p2a(page, request, server, output, report, record, begin_edit, tool, fresh_page):
    """One real Chromium, shared scene writes, CDP IME, persisted rich rendering."""
    from ai_inspector.documentation.rich_text import from_plain, plain_text, validate

    h = rich_browser_helpers(page, request, server, output, report, begin_edit, fresh_page, "P2a")
    spec, routes, object_id, posts = h.spec, h.routes, h.object_id, h.posts
    base = h.base
    scene = h.scene
    field = h.field
    create = h.create
    idle = h.idle
    commands = h.commands
    saved_command = h.saved_command
    switch = h.switch
    navigate = h.navigate
    refresh = h.refresh
    box = h.box
    mount = h.mount
    finish = h.finish
    screenshot = h.screenshot

    def open_document(kind, page_id):
        nonlocal page
        page = h.open_document(kind, page_id)

    original = RICH_PROOF_TEXT
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

    rich_select_word(page, editor, "beta")
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
    pasted = RICH_PROOF_PASTE
    rich_paste(editor, pasted)
    finish(blur=True)
    current = field(scene())
    record("p2a_04_multiline_unicode_blur_commit", current["isRichText"]
           and validate(current["richText"]) == current["richText"]
           and plain_text(current["richText"]) == current["text"] == original + pasted)

    editor = mount()
    editor.press("Control+End")
    before_ime = len(posts)
    rich_compose(page, lambda: record("p2a_05_ime_no_mid_composition_commit", len(posts) == before_ime
                 and page.evaluate("() => DocumentationRichText.mountedCount") == 1))
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


CANVAS_LINES_JS = """
box => {
  const rect = box.getBoundingClientRect();
  const scale = rect.width / parseFloat(getComputedStyle(box).width);
  const style = getComputedStyle(box);
  const insetLeft = parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft);
  const insetTop = parseFloat(style.borderTopWidth) + parseFloat(style.paddingTop);
  const local = r => ({left: (r.left - rect.left) / scale - insetLeft,
    top: (r.top - rect.top) / scale - insetTop,
    right: (r.right - rect.left) / scale - insetLeft, bottom: (r.bottom - rect.top) / scale - insetTop});
  const lines = [];
  let current = null, currentBlock = null;
  const tolerance = box.querySelector('.documentation-rich-content')?.dataset.schemaVersion === '2' ? 1.25 : 2.5;
  const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const text = walker.currentNode, parent = text.parentElement;
    if (parent.closest('.documentation-resize-handle')) continue;
    const css = getComputedStyle(parent), size = parseFloat(css.fontSize);
    const metrics = DocumentationRichTextCore.font(css.fontFamily.replaceAll('"', ''));
    const script = parent.closest('sub, sup');
    const shift = script ? parseFloat(getComputedStyle(script).top) : 0;
    const block = parent.closest('p,h1,h2,h3');
    // Range rectangles use the font content box, not the line box. Infer the
    // common baseline, undoing only position:relative's paint shift. Large,
    // small, mixed-family and scripted glyphs then stay on the same line.
    for (let i = 0; i < text.data.length;) {
      const length = text.data.codePointAt(i) > 0xffff ? 2 : 1;
      const range = document.createRange();
      range.setStart(text, i); range.setEnd(text, i + length);
      const r = [...range.getClientRects()].pop();
      if (!r || (!r.width && !r.height)) { i += length; continue; }
      const glyph = local(r), baseline = glyph.top + metrics.ascent * size - shift;
      if (!current || block !== currentBlock || Math.abs(baseline - current.baseline) > tolerance) {
        current = {top: glyph.top, bottom: glyph.bottom, left: glyph.left, baseline, text: '', glyphs: []};
        lines.push(current); currentBlock = block;
      }
      current.left = Math.min(current.left, glyph.left);
      current.text += text.data.slice(i, i + length);
      current.glyphs.push({text: text.data.slice(i, i + length), ...glyph, size, family: metrics.canvas});
      i += length;
    }
  }
  const editing = box.querySelector('.documentation-rich-editor .tiptap');
  const blocks = [...(editing || box).children].filter(child => !child.classList.contains('documentation-resize-handle'));
  const bottom = Math.max(...blocks.map(child => child.getBoundingClientRect().bottom));
  const highlights = [...box.querySelectorAll('mark')].flatMap(mark => [...mark.getClientRects()].map(r =>
    ({...local(r), color: DocumentationRichTextCore.color(getComputedStyle(mark).backgroundColor)})));
  return { scale, width: box.offsetWidth, height: box.offsetHeight, lines, highlights,
           contentHeight: (bottom - rect.top) / scale - insetTop };
}
"""


def same_canvas(first, second, tolerance=0.01):
    """Two measurements of one canvas box from separate page loads: the same text and structure, numbers within a
    hundredth of a pixel. The fit-page scale of two loads differs at float32 precision (6e-8 relative, measured), so
    exact equality fails on differences of 0.00006 px."""
    if isinstance(first, dict) and isinstance(second, dict):
        return first.keys() == second.keys() and all(same_canvas(first[key], second[key], tolerance) for key in first)
    if isinstance(first, list) and isinstance(second, list):
        return len(first) == len(second) and all(same_canvas(a, b, tolerance) for a, b in zip(first, second))
    if isinstance(first, bool) or isinstance(second, bool):
        return first is second
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        return abs(first - second) <= tolerance
    return first == second


def canvas_matches_layout(snapshot, page_id, key, label, measured, record, page_size=None, *, typography=False):
    """Shared real-canvas check. P3a adds glyph content boxes and every mark fragment."""
    import fitz
    import unicodedata
    from ai_inspector.documentation.rich_layout import TAB_SPACES, prepare_pdf_objects, authored_objects
    descriptor = next(p for p in snapshot["pages"] if p["pageId"] == page_id)
    authored = next((row for row in authored_objects(descriptor) if row[0] == key), None)
    if authored:
        frame = authored[1]["frame"]
        if page_size is None:
            page_size = (measured["width"] / frame["width"], measured["height"] / frame["height"])
        def prepare(rounding=False):
            return prepare_pdf_objects(fitz, snapshot, page_size, canvas_rounding=rounding)[page_id][key]
        expected_size = [frame["width"] * page_size[0], frame["height"] * page_size[1]]
    else:
        from ai_inspector.documentation.rich_blocks import prepare_pdf_blocks, content_frame, block_frame
        block = next(b for b in descriptor["layoutBlocks"] if key in {b["blockId"], b.get("stableId")})
        def prepare(rounding=False):
            return prepare_pdf_blocks(fitz, snapshot, canvas_rounding=rounding)[page_id][block["blockId"]]
        frame = content_frame(block, block_frame(snapshot, descriptor, block))
        expected_size = [frame[2] - frame[0], prepare().layout.measured_height if block["blockType"] in {"note", "status_panel"} else frame[3] - frame[1]]
    plan = prepare()
    inner = plan.layout.frame
    pdf = [{"text": "".join(r.text for r in runs), "left": runs[0].x - inner[0],
            "top": runs[0].rect[1] - inner[1], "bottom": runs[0].rect[3] - inner[1]}
           for runs in ([r for r in line.runs if not r.marker] for line in plan.layout.lines) if runs]
    canvas = [{"text": unicodedata.normalize("NFC", row["text"]).replace("\t", " " * TAB_SPACES).replace("\r", " "),
               "left": row["left"], "top": row["top"], "bottom": row["bottom"]} for row in measured["lines"]]
    pdf = [row for row in pdf if row["text"].strip()]
    canvas = [row for row in canvas if row["text"].strip()]
    box_size = [abs(measured["width"] - expected_size[0]), abs(measured["height"] - expected_size[1])]
    detail = {"canvas": canvas, "pdf": pdf, "boxSizeError": box_size,
              "contentHeight": {"canvas": measured["contentHeight"], "pdf": plan.layout.measured_height}}
    ok = (len(canvas) == len(pdf)
          and all(a["text"].rstrip() == b["text"].rstrip() and abs(a["left"] - b["left"]) <= 1 for a, b in zip(canvas, pdf))
          and abs(measured["contentHeight"] - plan.layout.measured_height) <= 1 and max(box_size) <= .6)
    if typography:
        # Vertical geometry is compared with the same layout rounded as Blink rounds at device scale 1 (whole-pixel
        # ascent/descent, LayoutUnit line heights, floored top half-leading; rich_fonts.line_box). The export itself is
        # unrounded, within about a pixel of every display scale; the checks above already bound it.
        rounded = prepare(True)
        assert [len(line.runs) for line in rounded.layout.lines] == [len(line.runs) for line in plan.layout.lines]
        plan = rounded
        inner = plan.layout.frame
        pdf = [{"text": "".join(r.text for r in runs), "top": runs[0].rect[1] - inner[1], "bottom": runs[0].rect[3] - inner[1]}
               for runs in ([r for r in line.runs if not r.marker] for line in plan.layout.lines) if runs]
        pdf = [row for row in pdf if row["text"].strip()]
        detail["rounded"] = {"lines": pdf, "contentHeight": plan.layout.measured_height}
        ok = ok and abs(measured["contentHeight"] - plan.layout.measured_height) <= .25
        ok = ok and all(abs(a[k] - b[k]) <= .25 for a, b in zip(canvas, pdf) for k in ("top", "bottom"))
        # P3a's ASCII typography vectors also compare every glyph, so a script
        # or small run in the middle of a mixed line cannot hide behind its first glyph.
        glyphs = [{"text": g["text"], "top": g["top"], "bottom": g["bottom"]}
                  for row in measured["lines"] for g in row["glyphs"]]
        expected_glyphs = [{"text": char, "top": run.rect[1] - inner[1], "bottom": run.rect[3] - inner[1]}
                           for line in plan.layout.lines for run in line.runs if not run.marker for char in run.text]
        detail["glyphs"] = {"canvas": glyphs, "pdf": expected_glyphs}
        ok = ok and len(glyphs) == len(expected_glyphs) and all(a["text"] == b["text"] and
            all(abs(a[k] - b[k]) <= .25 for k in ("top", "bottom")) for a, b in zip(glyphs, expected_glyphs))
        # A mark is one inline box per line, even if marks/font fallback split its
        # PDF drawing into adjacent runs. Join only contiguous equal rectangles.
        expected = []
        for line in plan.layout.lines:
            for run in line.runs:
                if not run.highlight:
                    continue
                x0, y0, x1, y1 = run.highlight_rect
                item = {"left": x0 - inner[0], "top": y0 - inner[1], "right": x1 - inner[0],
                        "bottom": y1 - inner[1], "color": run.highlight,
                        "hangingTail": run.width if run.hanging else 0.0}
                if expected and all(expected[-1][k] == item[k] for k in ("top", "bottom", "color")) and abs(expected[-1]["right"] - item["left"]) < .01:
                    expected[-1]["right"] = item["right"]
                    expected[-1]["hangingTail"] = item["hangingTail"]
                else:
                    expected.append(item)
        actual = measured["highlights"]
        detail["highlights"] = {"canvas": actual, "pdf": expected}
        # A fragment ending in hanging white space (pre-wrap, at a line end) may end anywhere inside it: Chromium's
        # inline box covers only part of a hanging space, while the PDF highlights the whole advance.
        ok = ok and len(actual) == len(expected) and all(
            a["color"] == b["color"] and abs(a["left"] - b["left"]) <= .5
            and all(abs(a[k] - b[k]) <= .25 for k in ("top", "bottom"))
            and b["right"] - b["hangingTail"] - .5 <= a["right"] <= b["right"] + .5
            for a, b in zip(actual, expected))
    record(label, ok, None if ok else detail)
    return detail


def docx_run_text(payload, target):
    """The authored table's run text in document order: w:t, and w:tab as a tab (w:br and numbering excluded)."""
    import zipfile
    from io import BytesIO
    from lxml import etree
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(BytesIO(payload)) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    table = next(t for t in root.xpath("//w:tbl", namespaces=ns)
                 if t.xpath("string(./w:tblPr/w:tblCaption/@w:val)", namespaces=ns) == "Authored text: " + target)
    return "".join("\t" if leaf.tag.endswith("}tab") else (leaf.text or "")
                   for leaf in table.xpath(".//w:r/w:t | .//w:r/w:tab", namespaces=ns))


def fitz_open(payload):
    import fitz
    return fitz.open(stream=payload, filetype="pdf")


def run_p2b(page, request, server, output, report, record, begin_edit, tool, fresh_page):
    """One Chromium: browser authors -> refusal -> Sage edits -> real UI exports."""
    from copy import deepcopy
    from ai_inspector.documentation.rich_text import validate, plain_text
    from ai_inspector.documentation.rich_layout import authored_objects, content_model
    from ai_inspector.parts_manual.pdf import _document_object_style, _document_theme
    from tests.documentation_rich_export_support import compare_docx, compare_pdf, export_characters

    h = rich_browser_helpers(page, request, server, output, report, begin_edit, fresh_page, "P2b")
    spec, key = h.spec, h.object_id
    pages, stored = {}, {}
    comparison = {"authoring": {}, "export1": {}, "export2": {}, "export3": {}, "changes": {}}
    comparison_path = output / "p2b-comparison.json"

    def checkpoint():
        write_json(comparison_path, comparison)
        report["p2bComparison"] = comparison_path.relative_to(ROOT).as_posix()

    def open_document(kind):
        nonlocal page
        page = h.open_document(kind, pages[kind])
        # A real export may open a PDF viewer; close the extra tab to keep the
        # proof in one low-memory Chromium. The artifact is downloaded below.
        page.on("popup", lambda popup: popup.close())

    def author(kind):
        pages[kind] = h.create(kind, key, RICH_PROOF_TEXT)
        open_document(kind)
        ready = page.evaluate("async () => await DocumentationRichText.ready")
        record("p2b_01_" + kind + "_ready", ready["ok"], ready)
        editor = h.mount()
        rich_select_word(page, editor, "beta")
        page.locator('.documentation-rich-controls [data-rich-action="bold"]').click()
        editor.press("Control+End")
        pasted = RICH_PROOF_PASTE
        rich_paste(editor, pasted)
        h.finish(blur=True)
        record("p2b_01_" + kind + "_p2a_paste", h.field(h.scene(kind))["text"] == RICH_PROOF_TEXT + pasted)
        editor = h.mount()
        editor.press("Control+End")
        before_ime = len(h.posts)
        rich_compose(page, lambda: record("p2b_01_" + kind + "_ime_pending", len(h.posts) == before_ime
                     and page.evaluate("() => DocumentationRichText.mountedCount") == 1))
        h.idle()
        record("p2b_01_" + kind + "_p2a_ime", h.field(h.scene(kind))["text"] == RICH_PROOF_TEXT + pasted + "\u6f22\u5b57")
        # Add a link and native lists through the same editor's actual controls
        # and HTML paste path, so the export proof also exercises relationships
        # and numbering without replacing the browser-authored whitespace.
        editor = h.mount()
        rich_select_word(page, editor, "gamma")
        page.get_by_role("textbox", name="HTTP or HTTPS link").fill("https://example.test/proof?a=1&b=two%20words#part")
        page.locator('.documentation-rich-controls [data-rich-action="link"]').click()
        editor.press("Control+End")
        editor.press("Enter")
        # ProseMirror joins a pasted slice's open first block with the current paragraph, which dissolved a leading
        # <ul> into plain text (supervisor finding). A leading paragraph takes that join; the list stays a list.
        rich_paste(editor, '<p>Lists</p><ul><li><p>Bullet</p><ol start="3"><li><p>Third</p></li></ol></li></ul>',
                   "text/html")
        h.finish()
        field = h.field(h.scene(kind))
        stored[kind] = deepcopy(field["richText"])
        encoded = json.dumps(stored[kind])
        record("p2b_01_" + kind + "_browser_authored", validate(stored[kind]) == stored[kind]
               and "bulletList" in encoded and "orderedList" in encoded and '"link"' in encoded
               and "\U0001f642" in field["text"] and "e\u0301" in field["text"] and "\t" in field["text"])
        comparison["authoring"][kind] = {"pageId": pages[kind], "targetId": key, "richText": stored[kind]}
        h.screenshot("authored-" + ("spec" if kind == spec else "parts"))
        checkpoint()

    def artifacts_on_disk():
        return {p.relative_to(server.stores).as_posix(): sha(p) for extension in ("*.pdf", "*.docx")
                for p in server.stores.rglob(extension)}

    press_export = h.press_export

    def walk(value, mutate):
        if isinstance(value, dict):
            mutate(value)
            for child in value.values():
                walk(child, mutate)
        elif isinstance(value, list):
            for child in value:
                walk(child, mutate)

    def sage_edit(kind, round_number):
        current = h.field(h.scene(kind))["richText"]
        candidate = deepcopy(current)
        changed = []
        if round_number == 2:
            def mutate(node):
                if node.get("type") == "text" and "\U0001f642" in node["text"]:
                    node["text"] = node["text"].replace("\U0001f642", "smile")
                    changed.append("emoji")
        else:
            def mutate(node):
                if node.get("type") != "text":
                    return
                if node["text"] == "beta":
                    node.setdefault("marks", []).append({"type": "italic"})
                    changed.append("beta")
                elif node["text"] == "gamma":
                    node["marks"] = [m for m in node.get("marks", []) if m["type"] != "textStyle"] + [
                        {"type": "textStyle", "attrs": {"color": "#cc3300"}}]
                    changed.append("gamma")
        walk(candidate, mutate)
        candidate = validate(candidate)
        assert changed == (["emoji"] if round_number == 2 else ["beta", "gamma"]), changed
        # Verify the proposed edit has no unrelated node/ID/whitespace changes.
        restored = deepcopy(candidate)
        if round_number == 2:
            walk(restored, lambda node: node.update(text=node["text"].replace("smile", "\U0001f642"))
                 if node.get("type") == "text" else None)
        else:
            old_marks = {}
            walk(current, lambda node: old_marks.update({node["text"]: node.get("marks", [])})
                 if node.get("type") == "text" and node["text"] in {"beta", "gamma"} else None)
            walk(restored, lambda node: node.update(marks=old_marks[node["text"]])
                 if node.get("type") == "text" and node["text"] in old_marks else None)
        assert validate(restored) == current
        bound = tool("read_document_pages", {"documentType": kind, "targets": [{"pageId": pages[kind], "targetId": key}]})
        assert bound.get("ok"), bound
        observed = bound["data"]["targets"][0]
        applied = tool("apply_document_edits", {"documentId": bound["data"]["documentId"],
            "expectedRevision": observed["revision"], "requestId": f"p2b-{round_number}-{kind}", "operations": [{
                "operation": "replace_rich_text", "targetId": observed["targetId"],
                "expectedContentHash": observed["contentHash"], "richText": candidate}]})
        assert applied.get("ok"), applied
        fresh = h.field(h.scene(kind))["richText"]
        record(f"p2b_0{round_number + 2}_sage_{kind}", fresh == candidate, {"changed": changed})
        stored[kind] = fresh
        return fresh

    download, canvas_lines = h.download, h.canvas_lines

    def compare_canvas(kind, label, measured, page_size=None):
        return canvas_matches_layout(h.scene(kind)["document"], pages[kind], key, label, measured, record, page_size)

    def parts_not_publishable(round_number):
        open_document(DOC_TYPE)
        assert h.field(h.scene(DOC_TYPE))["richText"] == stored[DOC_TYPE]
        canvas = compare_canvas(DOC_TYPE, f"p2b-{round_number}-parts_canvas_matches_pdf_layout", canvas_lines())
        state = page.evaluate("""() => {
            const doc = window.__compareDbg.state.partsManualDocumentation?.document || {};
            const pending = (doc.pages || []).filter(p => p.renderRequest && p.renderRequest.image?.status !== 'ready');
            return {disabled: document.querySelector('#documentationPublishRibbon').disabled,
                    status: doc.status || null, pendingCaptures: pending.length};
        }""")
        record(f"p2b-{round_number}-parts_publish_needs_captures", state["disabled"]
               and (state["status"] != "publication_ready" or state["pendingCaptures"] > 0), state)
        comparison["export" + str(round_number)][DOC_TYPE] = {"richText": stored[DOC_TYPE], "canvas": canvas,
            "skipped": "isolated parts manual is not publication-ready", **state}
        checkpoint()

    def export_and_compare(kind, round_number):
        if kind != spec:
            return parts_not_publishable(round_number)
        open_document(kind)
        current = h.scene(kind)
        assert h.field(current)["richText"] == stored[kind]
        measured = canvas_lines()
        response, result = press_export(kind)
        assert response.ok, result
        prefix = f"p2b-{round_number}-spec"
        pdf_bytes = download(result["pdf"], prefix + ".pdf")
        snapshot = h.scene(kind)["document"]
        descriptor = next(p for p in snapshot["pages"] if p["pageId"] == pages[kind])
        _, obj, canonical = next(row for row in authored_objects(descriptor) if row[0] == key)
        assert canonical == stored[kind]
        model = content_model(canonical, _document_object_style(_document_theme(snapshot), obj))
        try:
            pdf_result = compare_pdf(pdf_bytes, snapshot, pages[kind], key, output / (prefix + ".png"))
        except Exception as error:
            record(prefix + "_pdf_matches", False, str(error))
            raise
        record(prefix + "_pdf_matches", True)
        with fitz_open(pdf_bytes) as exported:
            pdf_page = exported[next(i for i, p in enumerate(snapshot["pages"]) if p["pageId"] == pages[kind])]
            pdf_size = (pdf_page.rect.width, pdf_page.rect.height)
        row = {"richText": canonical, "pdf": pdf_result,
               "canvas": compare_canvas(kind, prefix + "_canvas_matches_pdf_layout", measured, pdf_size)}
        response, result = press_export(kind, "docx")
        assert response.ok, result
        docx_bytes = download(result["docx"], prefix + ".docx")
        try:
            row["docx"] = compare_docx(docx_bytes, key, model)
        except Exception as error:
            record(prefix + "_docx_matches", False, str(error))
            raise
        record(prefix + "_docx_matches", True)
        # Independent of content_model: the stored envelope's own plain text, every character but LF, in order.
        expected = plain_text(canonical).replace("\r", " ").replace("\n", "")
        actual = docx_run_text(docx_bytes, key)
        record(prefix + "_docx_text_is_the_stored_text", actual == expected,
               None if actual == expected else {"expected": expected, "actual": actual})
        comparison["export" + str(round_number)][kind] = row
        checkpoint()

    semantic_characters = export_characters

    for kind in (spec, DOC_TYPE):
        author(kind)
    open_document(spec)
    before = artifacts_on_disk()
    response, failure = press_export(spec)
    correct = response.status == 422 and failure.get("error") == "unsupported_export_glyph"
    details = failure.get("details") or {}
    correct = correct and "U+1F642" in details.get("codePoints", []) and any(t["targetId"] == key for t in details.get("targets", []))
    record("p2b_02_glyph_refusal", correct, failure)
    if correct:
        report.setdefault("expectedHttpFailures", []).append({"url": response.url, "status": 422, "method": "POST",
                                                               "error": "unsupported_export_glyph", "checked": True})
    status = page.locator("#documentationWorkspace .documentation-status-message")
    page.wait_for_function("() => document.querySelector('#documentationWorkspace .documentation-status-message')?.textContent.includes('unsupported_export_glyph')")
    record("p2b_02_refusal_in_page", all(text in status.inner_text() for text in ("unsupported_export_glyph", key, "U+1F642")))
    record("p2b_02_no_artifact_written", artifacts_on_disk() == before)
    h.screenshot("glyph-refusal")
    comparison["export1"] = failure
    checkpoint()
    open_document(spec)
    record("p2b_03_reopen_unchanged", h.field(h.scene())["richText"] == stored[spec]
           and h.box().locator("strong").all_text_contents() == ["beta"]
           and h.box().locator("a").get_attribute("href") == "https://example.test/proof?a=1&b=two%20words#part")
    for kind in (spec, DOC_TYPE):
        sage_edit(kind, 2)
        export_and_compare(kind, 2)
    for kind in (spec, DOC_TYPE):
        open_document(kind)
        record("p2b_06_reopen_" + kind, h.field(h.scene(kind))["richText"] == stored[kind])
        sage_edit(kind, 3)
        export_and_compare(kind, 3)
        for format in ("pdf", "docx") if kind == spec else ():
            old = semantic_characters(comparison["export2"][kind][format], format)
            new = semantic_characters(comparison["export3"][kind][format], format)
            text = "".join(c["text"] for c in old)
            assert text == "".join(c["text"] for c in new)
            allowed = {i for word in ("beta", "gamma") for i in range(text.index(word), text.index(word) + len(word))}
            changed = {i for i, (a, b) in enumerate(zip(old, new)) if a != b}
            record("p2b_06_only_requested_marks_" + kind + "_" + format, changed == allowed,
                   {"changedCharacterOffsets": sorted(changed)})
            comparison["changes"][kind + "_" + format] = {"changedCharacterOffsets": sorted(changed), "textUnchanged": True}
        checkpoint()
    report["p2bScenePosts"] = h.posts



def typography_export_check(snapshot, page_id, key, pdf, docx, measured, size, output, stem, record):
    """One canvas/PDF/DOCX proof, reused for Sage and ribbon-authored typography."""
    from ai_inspector.documentation.rich_text import plain_text
    from ai_inspector.documentation.rich_layout import authored_objects, content_model
    from ai_inspector.parts_manual.pdf import _document_object_style, _document_theme
    from tests.documentation_rich_export_support import compare_pdf, compare_docx
    descriptor = next(p for p in snapshot["pages"] if p["pageId"] == page_id)
    _, obj, value = next(row for row in authored_objects(descriptor) if row[0] == key)
    model = content_model(value, _document_object_style(_document_theme(snapshot), obj))
    result = {"pdf": compare_pdf(pdf, snapshot, page_id, key, output / (stem + "-pdf.png")),
              "docx": compare_docx(docx, key, model),
              "canvas": canvas_matches_layout(snapshot, page_id, key, stem + "-canvas", measured, record, size, typography=True)}
    record(stem + "-exports", True)
    record(stem + "-raw-text", docx_run_text(docx, key) == plain_text(value).replace("\r", " ").replace("\n", ""))
    return result


def run_p3a(page, request, server, output, report, record, begin_edit, tool, fresh_page):
    """P3a parts 1 and 2: authored typography and the real ribbon editor."""
    from copy import deepcopy
    import math
    from PIL import Image
    import fitz
    from ai_inspector.documentation.rich_text import validate, plain_text
    from ai_inspector.documentation.rich_layout import authored_objects, content_model, prepare_pdf_objects
    from ai_inspector.parts_manual.pdf import _document_object_style, _document_theme
    # Share the declarative vector builders with the focused typography tests.
    from tests.test_documentation_typography import envelope, paragraph, text, mark, nested
    from tests.documentation_rich_export_support import compare_pdf, compare_docx, export_characters

    h = rich_browser_helpers(page, request, server, output, report, begin_edit, fresh_page, "P3a")
    spec = h.spec
    keys = ["document-object-p3a-a", "document-object-p3a-b", "document-object-p3a-c"]
    families, sizes = ["Arial", "Helvetica", "Times New Roman", "Courier New"], [6, 9.5, 12, 24, 48]
    # Twenty short runs fit on one line at their authored sizes. The second line
    # holds the 48 pt decoration specimen, and the third carries script/link combinations.
    runs = [text(chr(65 + i), mark("textStyle", fontFamily=family, fontSize=size))
            for i, (family, size) in enumerate((family, size) for family in families for size in sizes)]
    specimen = text("Measured", mark("strike"), mark("highlight", color="#ffe680"),
                    mark("textStyle", fontFamily="Arial", fontSize=48, color="#183a60"))
    typography = envelope(paragraph(*runs), paragraph(specimen),
        paragraph(text("strike ", mark("strike")), text("both ", mark("underline"), mark("strike")),
                  text("sub", mark("subscript"), mark("textStyle", fontSize=24)), text(" "),
                  text("sup", mark("superscript"), mark("textStyle", fontFamily="Times New Roman", fontSize=24)),
                  text(" linked", mark("link", href="https://example.test/typography"), mark("textStyle", fontSize=9.5)),
                  text(" tint", mark("highlight", color="#98e5cc"), mark("textStyle", color="#cc3300"))),
        {"type": "heading", "attrs": {"level": 3, "textAlign": "right", "spaceBefore": 1, "lineHeight": 1},
         "content": [text("Heading", mark("textStyle", fontSize=12))]},
        paragraph(text("break"), {"type": "hardBreak", "marks": [mark("textStyle", fontSize=9.5), mark("strike")]}, text("after")))
    paragraphs = envelope(paragraph(text("Centered"), textAlign="center", spaceBefore=3, spaceAfter=5, lineHeight=1),
        paragraph(text("Right aligned"), textAlign="right", indent=12.5, spaceBefore=7, spaceAfter=2, lineHeight=2),
        nested(6, mixed=True, indent=18),
        # An unbroken three-level bullet branch measures disc, circle and square as well.
        nested(3),
        paragraph(text("Wrapped highlighted fragments repeat across a line boundary. " * 2,
                       mark("highlight", color="#abddef"), mark("textStyle", fontSize=12))))
    georgia = envelope(paragraph(text("Georgia box renders Times New Roman", mark("strike"))))
    values = [typography, paragraphs, georgia]
    frames = [{"x": .06, "y": .07, "width": .88, "height": .32},
              {"x": .06, "y": .40, "width": .88, "height": .48},
              {"x": .06, "y": .90, "width": .88, "height": .06}]
    comparison = {"rounds": {}, "scope": "P3a-1/P3a-2"}
    # Each field's authored IDs are unique across the document.
    def rekey(value, group):
        counter = 0
        def walk(node):
            nonlocal counter
            if "id" in node.get("attrs", {}):
                counter += 1
                node["attrs"]["id"] = f"rt-00000000-0000-4000-8000-{group * 1000 + counter:012x}"
            for child in node.get("content", []):
                walk(child)
        walk(value["doc"])
        return validate(value)
    stored = {key: rekey(value, index + 1) for index, (key, value) in enumerate(zip(keys, values))}
    page_id = None

    def sage_write(key, value, suffix):
        bound = tool("read_document_pages", {"documentType": spec, "targets": [{"pageId": page_id, "targetId": key}]})
        assert bound.get("ok"), bound
        observed = bound["data"]["targets"][0]
        applied = tool("apply_document_edits", {"documentId": bound["data"]["documentId"], "expectedRevision": observed["revision"],
            "requestId": "p3a-" + suffix, "operations": [{"operation": "replace_rich_text", "targetId": observed["targetId"],
                "expectedContentHash": observed["contentHash"], "richText": value}]})
        assert applied.get("ok"), applied
        actual = h.field(h.scene(spec), key)["richText"]
        record("p3a_sage_" + suffix, actual == value)

    for index, key in enumerate(keys):
        page_id = h.create(spec, key, "", frame=frames[index], style={"fontSize": 12,
            "fontFamily": "Georgia" if index == 2 else "Arial"})
        sage_write(key, stored[key], "create-" + str(index))

    def reopen():
        nonlocal page
        page = h.open_document(spec, page_id)
        page.on("popup", lambda popup: popup.close())
        assert page.evaluate("async () => (await DocumentationRichText.ready).ok")
        snapshot = h.scene(spec)
        for key in keys:
            record("p3a_reopen_" + key, h.field(snapshot, key)["richText"] == stored[key])
        return snapshot

    snapshot = reopen()
    family = h.box(keys[2]).locator('.documentation-rich-content').evaluate("node => getComputedStyle(node).fontFamily")
    record("p3a_georgia_uses_times", family.replace('"', '') == "Times New Roman", family)
    revision = snapshot["revision"]
    before_posts = len(h.posts)
    editor = h.mount(keys[0])
    record("p3a_schema2_editor_mounts", page.evaluate("() => DocumentationRichText.mountedCount") == 1)
    h.screenshot("schema2-editor")
    editor.press("Escape")
    record("p3a_unchanged_editor_does_not_save", h.scene(spec)["revision"] == revision and len(h.posts) == before_posts)
    reopen()

    def press_export(format):
        response, result = h.press_export(spec, format)
        assert response.ok, result
        return result

    download = h.download

    def export_round(round_number):
        snapshot = reopen()["document"]
        measured = {key: h.canvas_lines(key) for key in keys}
        h.screenshot(str(round_number) + "-full")
        for key in keys:
            h.box(key).screenshot(path=str(output / f"p3a-{round_number}-{key[-1]}-canvas.png"))
        pdf = download(press_export("pdf")["pdf"], f"p3a-{round_number}.pdf")
        docx = download(press_export("docx")["docx"], f"p3a-{round_number}.docx")
        descriptor = next(p for p in snapshot["pages"] if p["pageId"] == page_id)
        with fitz.open(stream=pdf, filetype="pdf") as exported:
            pdf_page = exported[next(i for i, p in enumerate(snapshot["pages"]) if p["pageId"] == page_id)]
            size = (pdf_page.rect.width, pdf_page.rect.height)
            plans = prepare_pdf_objects(fitz, snapshot, size)[page_id]
            plan = plans[keys[0]]
            run = next(run for line in plan.layout.lines for run in line.runs if run.text == "Measured")
            # Side-by-side raw visual evidence: the real app's mark and the same
            # content rectangle rasterized from the exported PDF at its screen scale.
            specimen = h.box(keys[0]).locator('mark').filter(has_text="Measured")
            canvas_path = output / f"p3a-{round_number}-word-canvas.png"
            pdf_path = output / f"p3a-{round_number}-word-pdf.png"
            scale = measured[keys[0]]["scale"]
            # Both crops start on a whole output pixel with a known origin, so each baseline is exact in its crop. The
            # canvas mark's content box starts Chromium's whole-pixel ascent above the baseline (device scale 1).
            assert page.evaluate("devicePixelRatio === 1 && scrollX === 0 && scrollY === 0")
            mark_box = specimen.bounding_box()
            clip = {"x": math.floor(mark_box["x"]), "y": math.floor(mark_box["y"])}
            clip["width"] = math.ceil(mark_box["x"] + mark_box["width"]) - clip["x"]
            clip["height"] = math.ceil(mark_box["y"] + mark_box["height"]) - clip["y"]
            page.screenshot(path=str(canvas_path), clip=clip)
            canvas_baseline = mark_box["y"] + math.floor(.9053 * 48 + .5) * scale - clip["y"]
            pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=fitz.Rect(run.highlight_rect))
            pixmap.save(str(pdf_path))
            pdf_baseline = run.baseline * scale - pixmap.y
            with Image.open(canvas_path) as left, Image.open(pdf_path) as right:
                pair = Image.new("RGB", (left.width + right.width + 12, max(left.height, right.height)), "white")
                pair.paste(left, (0, 0)); pair.paste(right, (left.width + 12, 0))
                pair.save(output / f"p3a-{round_number}-word-side-by-side.png")
            # The minimum text-color coverage across a row isolates a continuous
            # strike from the glyphs (there is blank ink space on every glyph row).
            # Report the measured center/thickness in layout px, including the
            # pixel quantization bound. This is evidence from the real canvas.
            def stroke_measurement(filename, baseline):
                with Image.open(filename).convert("RGB") as image:
                    background, foreground = 255, 24  # red channel: #ffe680 -> #183a60
                    coverage = [min(max(0, min(1, (background - image.getpixel((x, y))[0]) / (background - foreground)))
                                    for x in range(2, image.width - 2)) for y in range(image.height)]
                    weights = [value if value > .03 else 0 for value in coverage]
                    total = sum(weights)
                    assert total > 0, "No continuous line-through found in the 48 pt specimen"
                    center = sum((y + .5) * value for y, value in enumerate(weights)) / total
                    return {"offsetFromBaseline": (center - baseline) / scale, "thickness": total / scale,
                            "pixelBound": 1 / scale, "rowCoverage": coverage}
            canvas_stroke = stroke_measurement(canvas_path, canvas_baseline)
            pdf_stroke = stroke_measurement(pdf_path, pdf_baseline)
            # Chromium (P3a-1 gate, rich_fonts.decoration): line-through centred a third of the whole-pixel ascent
            # above the baseline, its top edge and thickness on whole pixels; the PDF keeps the exact third.
            ascent, thickness = math.floor(.9053 * 48 + .5), max(1, round(48 / 10))
            chromium = math.floor(2 * ascent / 3 - thickness / 2 + .5) + thickness / 2 - ascent
            expected = {"canvas": {"offsetFromBaseline": chromium, "thickness": thickness},
                        "pdf": {"offsetFromBaseline": -.9053 / 3 * 48, "thickness": 48 / 10}}
            comparison.setdefault("decorationMeasurements", {})[str(round_number)] = {
                "canvas": canvas_stroke, "pdf": pdf_stroke, "expected": expected}
            # Each raster against its own model: the canvas within one output pixel (the scaled raster can move a
            # snapped line), the PDF within .15 px. The strikes then line up within about a pixel.
            bound = canvas_stroke["pixelBound"]
            record(f"p3a_{round_number}_strike_raster",
                   all(abs(canvas_stroke[k] - expected["canvas"][k]) <= bound for k in ("offsetFromBaseline", "thickness"))
                   and all(abs(pdf_stroke[k] - expected["pdf"][k]) <= .15 for k in ("offsetFromBaseline", "thickness")),
                   comparison["decorationMeasurements"][str(round_number)])
        results = {}
        for key, obj, value in authored_objects(descriptor):
            if key not in keys:
                continue
            results[key] = typography_export_check(snapshot, page_id, key, pdf, docx, measured[key], size,
                output, f"p3a-{round_number}-{key[-1]}", record)
        comparison["rounds"][str(round_number)] = results
        write_json(output / "p3a-comparison.json", comparison)
        return results

    first_round = export_round(1)
    candidate = deepcopy(stored[keys[0]])
    # The first 6 pt run becomes 6.5 pt; the line's 48 pt maximum is unchanged.
    candidate["doc"]["content"][0]["content"][0]["marks"][0]["attrs"]["fontSize"] = 6.5
    candidate = validate(candidate)
    restored = deepcopy(candidate)
    restored["doc"]["content"][0]["content"][0]["marks"][0]["attrs"]["fontSize"] = 6
    record("p3a_only_requested_stored_attribute", restored == stored[keys[0]])
    sage_write(keys[0], candidate, "resize-one-run")
    stored[keys[0]] = candidate
    second_round = export_round(2)
    for key in keys:
        for format in ("pdf", "docx"):
            fields = ("font", "family", "size", "bold", "italic", "underline", "strike", "highlight", "script", "color", "href")
            before = export_characters(first_round[key][format], format, fields)
            after = export_characters(second_round[key][format], format, fields)
            changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
            record("p3a_only_one_run_" + key + "_" + format, len(before) == len(after) and changed == ([0] if key == keys[0] else []), changed)
    report["p3aComparison"] = (output / "p3a-comparison.json").relative_to(ROOT).as_posix()
    run_p3a_editor(page, h, page_id, keys, output, report, record, tool)
    run_p3a_narrative(h, output, report, record, tool)
    run_p3a_search(h, output, report, record, tool)
    report["p3aScenePosts"] = h.posts

def run_p3a_editor(page, h, page_id, prior_keys, output, report, record, tool):
    """Part 2 uses pointer/keyboard toolbar input, never editor formatting commands."""
    from copy import deepcopy
    from ai_inspector.documentation.rich_text import validate, plain_text, FEATURES
    from ai_inspector.documentation.commands import canonical_bytes
    from tests.test_documentation_typography import envelope, paragraph, text, mark

    # Part 1's proofs are saved. Remove its overlapping specimens in this isolated
    # store so part 2 can measure a fresh, unobscured authored box on the same page.
    for key in prior_keys:
        before = h.scene()
        response = h.request.post(h.base() + "/documentation-scene/commands", data={
            "baseRevision": before["revision"], "sourceRevision": before["scene"]["sourceRevision"],
            "manualPlanRevision": before["scene"]["manualPlanRevision"], "operation": "remove_object",
            "pageId": page_id, "targetType": "document_object", "targetId": key}, timeout=120000)
        assert response.ok, response.text()[:1000]
        response.body()
    key = "document-object-p3a-edit"
    h.create(h.spec, key, "", frame={"x": .08, "y": .07, "width": .84, "height": .86}, style={"fontSize": 12, "fontFamily": "Arial"})
    words = ["Title", "Caption", "Note", "Styled sub sup link", "Centered", "Right", "Spacing"] + [f"List {i}" for i in range(1, 7)]
    initial = validate(envelope(*(paragraph(text(word)) for word in words), version=1))
    bound = tool("read_document_pages", {"documentType": h.spec, "targets": [{"pageId": page_id, "targetId": key}]})
    assert bound.get("ok"), bound
    observed = bound["data"]["targets"][0]
    applied = tool("apply_document_edits", {"documentId": bound["data"]["documentId"], "expectedRevision": observed["revision"],
        "requestId": "p3a-editor-initial", "operations": [{"operation": "replace_rich_text", "targetId": observed["targetId"],
            "expectedContentHash": observed["contentHash"], "richText": initial}]})
    assert applied.get("ok"), applied
    page = h.open_document(h.spec, page_id)
    editor = h.mount(key)
    controls = page.locator('.documentation-rich-controls')
    checks = 0

    def state(label, expected, *, toggle=False):
        nonlocal checks
        control = controls.get_by_role("button", name=label, exact=True) if toggle else controls.get_by_label(label, exact=True)
        actual = control.get_attribute("aria-pressed") if toggle else control.input_value()
        checks += 1
        record(f"p3a2_control_{checks:02d}_" + label.replace(" ", "_"), actual == str(expected), {"expected": expected, "actual": actual})

    def choose(word):
        rich_select_word(page, editor, word)

    def click(label, expected=None):
        controls.get_by_role("button", name=label, exact=True).click()
        if expected is not None:
            state(label, expected, toggle=True)

    def select(label, value):
        control = controls.get_by_label(label, exact=True)
        control.click()
        control.select_option(value)
        state(label, value)

    def fill(label, value):
        control = controls.get_by_label(label, exact=True)
        control.click()
        control.press("Control+a")
        if value:
            page.keyboard.insert_text(str(value))
        else:
            control.press("Backspace")
        control.press("Tab")
        state(label, value)

    # Style controls convert the block, and resets remove rather than store defaults.
    for word, style in (("Title", "title"), ("Caption", "caption"), ("Note", "note")):
        choose(word); select("Style", style)
    choose("Centered")
    for style in ("h1", "h2", "h3", "body"):
        select("Style", style)
    choose("Styled")
    select("Font", "Courier New")
    editor.press("Control+z"); state("Font", "box")
    record("p3a2_control_undo_is_local", h.field(h.scene(), key)["richText"] == initial)
    editor.press("Control+y"); state("Font", "Courier New")
    select("Font", "box"); select("Font", "Helvetica")
    fill("Size", "12"); fill("Size", ""); fill("Size", "24")
    for label in ("Bold", "Italic", "Underline", "Strikethrough"):
        click(label, "true")
    fill("Text color", "#2468ac")
    # The native picker beside each colour field mirrors the shared colour (black when there is none), and a pick is
    # one undoable change (supervisor P3a-2).
    picker = controls.get_by_label("Text color picker", exact=True)
    record("p3a2_color_picker_mirrors_field", picker.input_value() == "#2468ac", picker.input_value())
    picker.fill("#13579b"); state("Text color", "#13579b")
    editor.press("Control+z"); state("Text color", "#2468ac")
    fill("Highlight color", "#ffee80")
    click("Remove highlight"); state("Highlight color", "")
    highlight_picker = controls.get_by_label("Highlight color picker", exact=True)
    record("p3a2_color_picker_none_is_black", highlight_picker.input_value() == "#000000", highlight_picker.input_value())
    fill("Highlight color", "#ffee80")
    choose("sub"); click("Subscript", "true")
    choose("sup"); click("Subscript", "true"); click("Superscript", "true"); state("Subscript", "false", toggle=True)
    choose("link")
    fill("HTTP or HTTPS link", "https://example.test/editor")
    click("Link"); state("HTTP or HTTPS link", "https://example.test/editor")
    click("Unlink"); state("HTTP or HTTPS link", "")
    fill("HTTP or HTTPS link", "https://example.test/editor"); click("Link")
    state("HTTP or HTTPS link", "https://example.test/editor")
    choose("Centered"); click("Align left", "true"); click("Box alignment", "true"); click("Align center", "true")
    choose("Right"); click("Align right", "true")
    choose("Spacing")
    click("Increase indent"); click("Decrease indent"); click("Increase indent")
    record("p3a2_indent_state", controls.get_by_role("button", name="Increase indent", exact=True).get_attribute("data-indent") == "18")
    fill("Space before", "3.5"); fill("Space after", "4")
    select("Line spacing", "2"); select("Line spacing", "1.2"); select("Line spacing", "1.5")

    # Select whole paragraphs by their native DOM range, then click the ribbon.
    editor.evaluate("""node => {
        const ps = [...node.querySelectorAll('p')];
        const start = ps.find(p => p.textContent === 'List 1'), end = ps.find(p => p.textContent === 'List 6');
        const range = document.createRange(); range.setStart(start, 0); range.setEnd(end, end.childNodes.length);
        const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); node.focus();
    }""")
    page.wait_for_timeout(50)
    click("Numbering", "true"); click("Bullets", "true")
    for depth in range(2, 7):
        choose(f"List {depth}")
        for _ in range(depth - 1):
            click("Increase indent")
        record(f"p3a2_list_depth_{depth}", page.evaluate("""() => {
            let p = getSelection().anchorNode.parentElement, depth = 0;
            while (p && !p.classList.contains('tiptap')) { if (p.matches('ul,ol')) depth++; p = p.parentElement; }
            return depth;
        }""") == depth)
        state("Bullets", "true", toggle=True)
        record(f"p3a2_style_disabled_in_list_{depth}", controls.get_by_label("Style", exact=True).is_disabled())
    click("Increase indent")
    record("p3a2_depth_limit_notice", "6 levels" in page.locator('.documentation-rich-message').inner_text())
    h.screenshot("part2-ribbon")
    h.finish()
    actual = h.field(h.scene(), key)["richText"]

    # Expected formatting is authored here, independent of the editor's output.
    # Retained paragraphs have known IDs; only newly allocated list/container IDs
    # are copied from the API, after checking their node kinds and tree structure.
    expected = deepcopy(initial); expected["schemaVersion"] = 2
    blocks = expected["doc"]["content"]
    for index, style in enumerate(("title", "caption", "note")):
        blocks[index]["attrs"]["namedStyle"] = style
    blocks[3]["content"] = [text("Styled", mark("bold"), mark("italic"), mark("underline"), mark("strike"),
        mark("highlight", color="#ffee80"), mark("textStyle", fontFamily="Helvetica", fontSize=24, color="#2468ac")),
        text(" "), text("sub", mark("subscript")), text(" "), text("sup", mark("superscript")), text(" "),
        text("link", mark("link", href="https://example.test/editor"))]
    blocks[4]["attrs"]["textAlign"] = "center"
    blocks[5]["attrs"]["textAlign"] = "right"
    blocks[6]["attrs"].update(indent=18, spaceBefore=3.5, spaceAfter=4, lineHeight=1.5)
    tail = None
    for p in reversed(blocks[7:]):
        tail = {"type": "bulletList", "content": [{"type": "listItem", "content": [p] + ([tail] if tail else [])}]}
    expected["doc"]["content"] = blocks[:7] + [tail]

    def allocated_ids(wanted, observed):
        assert wanted["type"] == observed["type"], (wanted, observed)
        if wanted["type"] not in {"doc", "text"} and "id" not in wanted.get("attrs", {}):
            wanted.setdefault("attrs", {})["id"] = observed["attrs"]["id"]
        assert len(wanted.get("content", [])) == len(observed.get("content", [])), (wanted, observed)
        for a, b in zip(wanted.get("content", []), observed.get("content", [])):
            allocated_ids(a, b)
    allocated_ids(expected["doc"], actual["doc"])
    expected = validate(expected)
    record("p3a2_exact_saved_envelope", canonical_bytes(actual) == canonical_bytes(expected), {"expected": expected, "actual": actual})
    write_json(output / "p3a2-expected.json", expected)

    def export_edited(stem):
        snapshot = h.scene()["document"]
        measured = h.canvas_lines(key)
        h.screenshot(stem)
        h.box(key).screenshot(path=str(output / (stem + "-canvas.png")))
        artifacts = {}
        for format in ("pdf", "docx"):
            response, result = h.press_export(h.spec, format)
            assert response.ok, result
            artifacts[format] = h.download(result[format], stem + "." + format)
        with fitz_open(artifacts["pdf"]) as pdf:
            size = (pdf[0].rect.width, pdf[0].rect.height)
        result = typography_export_check(snapshot, page_id, key, artifacts["pdf"], artifacts["docx"], measured, size, output, stem, record)
        report.setdefault("p3a2Exports", {})[stem] = result
        return measured

    static = export_edited("p3a2-edited")
    editor = h.mount(key)
    editing = h.canvas_lines(key)
    record("p3a2_editor_static_lines", len(static["lines"]) == len(editing["lines"]) and all(
        a["text"] == b["text"] and all(abs(a[k] - b[k]) <= 1 for k in ("left", "top", "bottom"))
        for a, b in zip(static["lines"], editing["lines"])), {"static": static, "editing": editing})
    h.screenshot("part2-editor-measured")
    editor.press("Escape")
    for direction, wanted in (("undo", initial), ("redo", expected)):
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/documentation-scene/" + direction), timeout=120000) as moved:
            page.locator("#documentation" + direction.title() + "Ribbon").click()
        moved.value.finished(); assert moved.value.ok, moved.value.text()[:1000]
        h.idle()
        record("p3a2_document_" + direction, canonical_bytes(h.field(h.scene(), key)["richText"]) == canonical_bytes(wanted))

    editor = h.mount(key)
    # A partial clear lifts only the selected item out of all its lists; the items around it stay valid lists
    # (supervisor P3a-2: Tiptap's clearNodes lifted a nested list one level per node).
    choose("List 3")
    click("Clear formatting")
    partial = page.evaluate("""() => {
        const shape = n => n.type === 'paragraph' ? (n.content || []).map(t => t.text || '').join('')
            : n.type === 'listItem' ? (n.content || []).map(shape).join('>')
            : n.type + '[' + (n.content || []).map(shape).join('|') + ']';
        const doc = DocumentationRichText.active.editor.getJSON();
        return {shape: doc.content.map(shape), id: doc.content.find(n => shape(n) === 'List 3')?.attrs?.id};
    }""")

    def paragraph_ids(node):
        if node["type"] == "paragraph":
            yield "".join(child.get("text", "") for child in node.get("content", [])), node["attrs"]["id"]
        for child in node.get("content", []):
            yield from paragraph_ids(child)
    record("p3a2_partial_clear_lifts_one_item", partial["shape"] == [
        "Title", "Caption", "Note", "Styled sub sup link", "Centered", "Right", "Spacing",
        "bulletList[List 1>bulletList[List 2]]", "List 3", "bulletList[List 4>bulletList[List 5>bulletList[List 6]]]"]
        and partial["id"] == dict(paragraph_ids(expected["doc"]))["List 3"], partial)
    editor.press("Control+a")
    click("Clear formatting")
    state("Bold", "false", toggle=True); state("Size", ""); state("Font", "box"); state("Style", "body")
    state("Space before", ""); state("Space after", ""); state("Line spacing", "1.2")
    h.finish()
    cleared = h.field(h.scene(), key)["richText"]
    record("p3a2_clear_returns_schema1", cleared["schemaVersion"] == 1 and plain_text(cleared) == plain_text(initial)
           and all(p["type"] == "paragraph" and set(p["attrs"]) == {"id"}
                   and all(not run.get("marks") for run in p.get("content", [])) for p in cleared["doc"]["content"]))
    record("p3a2_clear_keeps_paragraph_ids", [p["attrs"]["id"] for p in cleared["doc"]["content"]]
           == [p["attrs"]["id"] for p in initial["doc"]["content"]])
    editor = h.mount(key)
    editor.press("Control+a")
    rich_paste(editor, '<p style="text-align:justify"><span style="font-family:Georgia; font-size:12pt">Dropped</span></p>'
        '<p><span style="font-family:Helvetica,serif; font-size:13.26px">Mapped</span> '
        '<span style="font-family:Courier New; font-size:48px">Token</span></p>', mime="text/html")
    h.finish()
    pasted = h.field(h.scene(), key)["richText"]
    wanted = {"format": "tiptap", "schemaVersion": 2, "doc": {"type": "doc", "content": [
        {"type": "paragraph", "content": [text("Dropped")]},
        {"type": "paragraph", "content": [text("Mapped", mark("textStyle", fontFamily="Helvetica", fontSize=13.5)),
            text(" "), text("Token", mark("textStyle", fontFamily="Courier New", fontSize=48))]}]}}
    allocated_ids(wanted["doc"], pasted["doc"])
    record("p3a2_paste_exact_mappings", canonical_bytes(validate(wanted)) == canonical_bytes(pasted), pasted)
    before_canvas = export_edited("p3a2-paste")
    page = h.open_document(h.spec, page_id)
    record("p3a2_reopen_keeps_envelope", h.field(h.scene(), key)["richText"] == pasted)
    after_canvas = h.canvas_lines(key)
    record("p3a2_reopen_keeps_canvas", same_canvas(before_canvas, after_canvas),
           None if same_canvas(before_canvas, after_canvas) else {"before": before_canvas, "after": after_canvas})
    read = tool("read_document_pages", {"documentType": h.spec, "targets": [{"pageId": page_id, "targetId": key}]})
    assert read.get("ok"), read
    # P3b: a text box also takes schema 3 and the table feature (FEATURES now ends with it).
    record("p3a2_read_capabilities", read["data"]["targets"][0]["richTextCapabilities"] == {
        "schemaVersions": [1, 2, 3], "features": list(FEATURES), "listDepth": 6},
        read["data"]["targets"][0]["richTextCapabilities"])
    write_json(output / "p3a2-comparison.json", report["p3a2Exports"])


def run_p3a_narrative(h, output, report, record, tool):
    """Part 3: real generated blocks, native editor controls, captures and exports."""
    from copy import deepcopy
    from ai_inspector.documentation.commands import canonical_bytes
    from ai_inspector.documentation.rich_text import from_plain, plain_text, validate
    from ai_inspector.documentation.rich_layout import content_model
    from ai_inspector.documentation.rich_blocks import base_style, effective_override
    from tests.documentation_rich_export_support import compare_pdf, compare_docx

    ops, wi = "operations_and_maintenance_manual", "work_instructions"
    proofs = {}

    def choose(kind, block_type):
        document = h.scene(kind)["document"]
        candidates = [(p, b) for p in document["pages"] for b in p.get("layoutBlocks", [])
                      if (b.get("blockType") == block_type or block_type == "note" and b.get("blockType") == "status_panel")
                      and b.get("text", b.get("caption", ""))]
        # A list needs an extra 40 pt start indent; use a roomy generated frame, never resize the proof to conceal overflow.
        return max(candidates, key=lambda pair: pair[1]["frame"]["width"] * pair[1]["frame"]["height"] /
                   max(1, len(pair[1].get("text", pair[1].get("caption", "")))))

    def capture():
        page.locator("#documentationCaptureAllRibbon").click(no_wait_after=True)
        page.wait_for_function("""() => {
            const figures = (window.__compareDbg.state.partsManualDocumentation?.document?.pages || []).filter(p => p.renderRequest);
            return figures.length && figures.every(p => p.renderRequest.image?.status === 'ready')
                && !document.querySelector('#documentationWorkspace.busy');
        }""", timeout=240000)

    def field(kind, alias):
        return h.field(h.scene(kind), alias)

    def override(kind, alias):
        snapshot = h.scene(kind)
        row = h.field(snapshot, alias)
        return next((p.get("pageElementOverrides", {}).get(row["targetId"]) for p in snapshot["scene"]["pages"].values()
                     if row["targetId"] in p.get("pageElementOverrides", {})), None)

    def color(label, value):
        control = page.locator('.documentation-rich-controls').get_by_label(label, exact=True)
        control.click(); control.press("Control+a"); page.keyboard.insert_text(value); control.press("Tab")
        record("p3a3_" + label.replace(" ", "_"), control.input_value() == value)

    chosen = {kind: choose(ops, kind) for kind in ("paragraph", "note", "cad_figure")}
    before, after = {}, {}
    for kind, (descriptor, block) in chosen.items():
        alias = block["blockId"]
        page = h.open_document(ops, descriptor["pageId"], pointer_refresh=True)
        before[alias] = deepcopy(override(ops, alias))
        current = field(ops, alias)
        editor = h.mount(alias, generated=True)
        # Opening a block for editing must leave the caret in it: a person types straight away. Observed before any
        # key or click is sent (Playwright's own key helpers focus the element, which would hide a missing focus).
        focus = None
        for _ in range(20):
            focus = page.evaluate("""() => {
                const editor = DocumentationRichText.active.editor, active = document.activeElement;
                return {focused: editor.isFocused, active: active === editor.view.dom, documentFocus: document.hasFocus(),
                        activeTag: active?.tagName || null, activeId: active?.id || null,
                        activeClass: String(active?.className || '').slice(0, 80)};
            }""")
            if focus["focused"] and focus["active"]:
                break
            page.wait_for_timeout(250)
        record("p3a3_" + kind + "_editor_takes_focus", focus["focused"] and focus["active"], focus)
        controls = page.locator('.documentation-rich-controls')
        record("p3a3_" + kind + "_no_style", controls.get_by_label("Style", exact=True).count() == 0)
        if kind != "paragraph":
            record("p3a3_" + kind + "_marks_only", all(controls.get_by_label(label, exact=True).count() == 0
                for label in ("Font", "Size", "Space before", "Space after", "Line spacing")) and all(
                controls.get_by_role("button", name=label, exact=True).count() == 0
                for label in ("Bullets", "Numbering", "Align center", "Increase indent")))
        word = re.search(r"[A-Za-z]+", current["text"]).group()
        if kind == "note":
            # The mount focuses the editor in an animation frame, and ProseMirror re-applies its own selection 20 ms
            # after a focus event. A key sent inside that window can be undone by the re-applied selection, so the
            # caret stays at the end and Backspace removes the last character (run p3a4c lost the final period).
            # Send Control+Home until the editor's own selection is the start of the text, then press Backspace.
            caret, attempts = None, []
            for _ in range(10):
                editor.press("Control+Home")
                page.wait_for_timeout(150)
                caret = page.evaluate("""() => {
                    const editor = DocumentationRichText.active.editor, selection = editor.state.selection;
                    return {from: selection.from, to: selection.to,
                            start: selection.constructor.atStart(editor.state.doc).from,
                            focused: editor.isFocused, active: document.activeElement === editor.view.dom};
                }""")
                attempts.append(caret)
                if caret["from"] == caret["to"] == caret["start"]:
                    break
            at_start = caret["from"] == caret["to"] == caret["start"]
            if at_start:
                editor.press("Backspace")
            stored_text = page.evaluate("() => DocumentationRichTextCore.plainText(DocumentationRichText.active.editor.getJSON())")
            record("p3a3_signal_immutable", at_start and stored_text == current["text"]
                   and editor.locator('.documentation-rich-signal:visible').inner_text() == current["richTextStyle"]["signalWord"],
                   attempts)
        rich_select_word(page, editor, word)
        mark = "Italic" if kind == "note" else "Bold"
        controls.get_by_role("button", name=mark, exact=True).click()
        record("p3a3_" + kind + "_toggle", controls.get_by_role("button", name=mark, exact=True).get_attribute("aria-pressed") == "true")
        if kind == "paragraph":
            color("Text color", "#2468ac")
            controls.get_by_role("button", name="Bullets", exact=True).click()
            record("p3a3_paragraph_bullets", controls.get_by_role("button", name="Bullets", exact=True).get_attribute("aria-pressed") == "true")
        if kind == "note":
            color("Highlight color", "#ffee80")
        h.screenshot("part3-" + kind + "-editor")
        h.finish()
        after[alias] = deepcopy(override(ops, alias))
        record("p3a3_" + kind + "_projection", after[alias]["text"] == plain_text(after[alias]["richText"]))
        read = tool("read_document_pages", {"documentType": ops, "targets": [{"pageId": descriptor["pageId"], "targetId": alias}]})
        assert read.get("ok"), read
        row = read["data"]["targets"][0]
        record("p3a3_" + kind + "_read", row["richTextEligible"] and row["richText"] == after[alias]["richText"]
               and row["richTextCapabilities"]["listDepth"] == (6 if kind == "paragraph" else 0)
               and "heading" not in row["richTextCapabilities"]["features"])

    def export_proofs(kind, selected, stem, *, capture_first=True):
        artifacts = {}
        if capture_first:
            capture()
        for format in ("pdf", "docx"):
            response, result = h.press_export(kind, format)
            assert response.ok, result
            artifacts[format] = h.download(result[format], stem + "." + format)
        snapshot = h.scene(kind)["document"]
        for type_name, (descriptor, block) in selected.items():
            h.navigate(descriptor["pageId"])
            alias = block["blockId"]
            current = field(kind, alias)
            box = h.box(alias, generated=True)
            measured = box.evaluate(CANVAS_LINES_JS)
            name = stem + "-" + type_name
            h.screenshot(name)
            box.screenshot(path=str(output / (name + "-canvas.png")))
            details = canvas_matches_layout(snapshot, descriptor["pageId"], alias, name + "-canvas", measured, record, typography=True)
            pdf = compare_pdf(artifacts["pdf"], snapshot, descriptor["pageId"], alias, output / (name + "-pdf.png"))
            docx = compare_docx(artifacts["docx"], current["targetId"], content_model(current["richText"], current["richTextStyle"]))
            record(name + "-exports", True)
            if type_name == "note":
                record(name + "-signal-first", pdf["text"].startswith(current["richTextStyle"]["signalWord"]))
            proofs[name] = {"canvas": details, "pdf": pdf, "docx": docx}
            # Mounting the same stored envelope must not alter line wrapping or baselines.
            editor = h.mount(alias, generated=True)
            editing = h.box(alias, generated=True).evaluate(CANVAS_LINES_JS)
            record(name + "-editor-static", len(measured["lines"]) == len(editing["lines"]) and all(
                a["text"] == b["text"] and all(abs(a[k] - b[k]) <= 1 for k in ("left", "top", "bottom"))
                for a, b in zip(measured["lines"], editing["lines"])), {"static": measured, "editor": editing})
            editor.press("Escape")
        return artifacts

    export_proofs(ops, chosen, "p3a3-operations")
    # Three independent document steps, in edit order and reverse edit order.
    for direction, aliases, expected in (("undo", list(reversed(after)), before), ("redo", list(after), after)):
        for alias in aliases:
            with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/" + direction), timeout=120000) as response:
                page.locator("#documentation" + direction.title() + "Ribbon").click()
            response.value.finished(); assert response.value.ok, response.value.text()[:1000]
            h.idle()
            record("p3a3_" + direction + "_" + alias, canonical_bytes(override(ops, alias)) == canonical_bytes(expected[alias]))
    for kind, (descriptor, block) in chosen.items():
        page = h.open_document(ops, descriptor["pageId"], pointer_refresh=True)
        record("p3a3_reopen_" + kind, override(ops, block["blockId"]) == after[block["blockId"]])
        canvas_matches_layout(h.scene(ops)["document"], descriptor["pageId"], block["blockId"], "p3a3_reopen_canvas_" + kind,
                              h.box(block["blockId"], generated=True).evaluate(CANVAS_LINES_JS), record, typography=True)

    heading_page, heading = choose(ops, "heading")
    page = h.open_document(ops, heading_page["pageId"], pointer_refresh=True)
    read = tool("read_document_pages", {"documentType": ops, "targets": [{"pageId": heading_page["pageId"], "targetId": heading["blockId"]}]})
    assert read.get("ok"), read
    record("p3a3_heading_ineligible", not read["data"]["targets"][0].get("richTextEligible"))
    heading_element = h.box(heading["blockId"], generated=True)
    h.begin_edit(heading_element)
    record("p3a3_heading_plain_editor", heading_element.get_attribute("contenteditable") == "true"
           and page.locator('.documentation-rich-editor').count() == 0)
    heading_element.fill("P3a plain heading proof")
    record("p3a3_heading_plain_typing", heading_element.inner_text() == "P3a plain heading proof")
    heading_element.press("Escape")

    wi_page, wi_block = choose(wi, "paragraph")
    page = h.open_document(wi, wi_page["pageId"], pointer_refresh=True)
    capture()  # The following rich edit must reuse these real captures.
    figures = {p["pageId"]: p.get("figureRevision") for p in h.scene(wi)["document"]["pages"] if p.get("renderRequest")}
    read = tool("read_document_pages", {"documentType": wi, "targets": [{"pageId": wi_page["pageId"], "targetId": wi_block["blockId"]}]})
    assert read.get("ok"), read
    data, row = read["data"], read["data"]["targets"][0]
    value = from_plain(row["text"])
    leaf = next(c for c in value["doc"]["content"][0].get("content", []) if c["type"] == "text")
    leaf["marks"] = [{"type": "bold"}, {"type": "textStyle", "attrs": {"color": "#2468ac"}}]
    result = tool("apply_document_edits", {"documentId": data["documentId"], "expectedRevision": row["binding"]["revision"],
        "requestId": "p3a3-wi-sage", "operations": [{"operation": "replace_rich_text", "targetId": row["targetId"],
            "expectedContentHash": row["contentHash"], "richText": value}]})
    assert result.get("ok"), result
    page = h.open_document(wi, wi_page["pageId"], pointer_refresh=True)
    current = h.scene(wi)
    record("p3a3_wi_capture_reused", figures == {p["pageId"]: p.get("figureRevision") for p in current["document"]["pages"] if p.get("renderRequest")}
           and all(p["renderRequest"]["image"].get("status") == "ready" for p in current["document"]["pages"] if p.get("renderRequest")))
    record("p3a3_wi_sage_value", field(wi, wi_block["blockId"])["richText"] == validate(value))
    export_proofs(wi, {"paragraph": (wi_page, wi_block)}, "p3a3-work-instructions", capture_first=False)
    report["p3a3Exports"] = proofs
    write_json(output / "p3a3-comparison.json", proofs)


def run_p3a_search(h, output, report, record, tool):
    """Part 4: real find UI, bounded group undo, symbols and Sage range tools."""
    from copy import deepcopy
    from ai_inspector.documentation.rich_text import from_plain, plain_text, node_ids
    from ai_inspector.documentation.rich_layout import content_model
    from tests.documentation_rich_export_support import compare_pdf, compare_docx
    import fitz

    kind = "operations_and_maintenance_manual"
    snapshot = h.scene(kind)
    row = next(f for f in snapshot["richTextFields"] if f["isRichText"]
               and f.get("richTextCapabilities", {}).get("listDepth") == 6 and f["targetId"].startswith("gen-"))
    alias, page_id, stable = row["legacyTargetId"], row["pageId"], row["targetId"]
    key = "document-object-p3a4"
    h.create(kind, key, "Rangepin rangepin", frame={"x": .12, "y": .78, "width": .6, "height": .08}, style={"fontSize": 10})
    read = tool("read_document_pages", {"documentType": kind, "targets": [{"targetId": stable}]})
    assert read.get("ok"), read
    full = read["data"]["targets"][0]
    value = from_plain("Rangepin rangepin")
    value["doc"]["content"][0]["content"] = [
        {"type": "text", "text": "Rangepin ", "marks": [{"type": "bold"}]},
        {"type": "text", "text": "rangepin", "marks": [{"type": "italic"}]}]
    seeded = tool("apply_document_edits", {"documentId": read["data"]["documentId"],
        "expectedRevision": full["binding"]["revision"], "requestId": "p3a4-seed", "operations": [{
            "operation": "replace_rich_text", "targetId": stable, "expectedContentHash": full["contentHash"], "richText": value}]})
    assert seeded.get("ok"), seeded
    page = h.open_document(kind, page_id, pointer_refresh=True)
    page.locator("#documentationFindRibbon").click()
    panel = page.get_by_role("region", name="Find and Replace")
    # section with an accessible name is a region; use only visible pointer/input controls.
    # Supervisor: the list is bounded, and Replace all refuses an incomplete list.
    panel.get_by_label("Find text", exact=True).fill("e")
    panel.get_by_role("button", name="Find", exact=True).click()
    page.wait_for_function("""() => /^Showing the first 1000 of [0-9]+ matches[.]/.test(
        document.querySelector('.documentation-find-panel [role=status]')?.textContent || '')""", timeout=180000)
    panel.get_by_role("button", name="Replace all", exact=True).click()
    bounded = panel.get_by_role("status").inner_text()
    record("p3a4_bounded_list", panel.locator('.documentation-find-results li').count() == 1000
           and bounded.startswith("Replace all needs every match")
           and panel.get_by_role("button", name="Apply replacement groups", exact=True).is_hidden(), bounded)
    h.screenshot("part4-bounded-list")
    panel.get_by_label("Find text", exact=True).fill("rangepin")
    panel.get_by_role("button", name="Find", exact=True).click()
    page.wait_for_function("() => document.querySelector('.documentation-find-panel [role=status]')?.textContent === '4 matches.'")
    record("p3a4_find_plain_and_rich", panel.locator('.documentation-find-results li').count() == 4)
    selected = set()
    for _ in range(4):
        page.wait_for_function("() => !document.querySelector('.documentation-find-panel [aria-label=Next]').disabled")
        selected.add(page.evaluate("() => { const s = window.__compareDbg.state; return JSON.stringify(s.partsManualDocumentationSelection); }"))
        panel.get_by_role("button", name="Next", exact=True).click()
    record("p3a4_next_selects_targets", len(selected) == 2, sorted(selected))
    panel.get_by_label("Replace with", exact=True).fill("Pin")
    panel.get_by_role("button", name="Replace", exact=True).click()
    page.wait_for_function("() => document.querySelector('.documentation-find-panel [role=status]')?.textContent === 'Applied 1 of 1 group.'", timeout=120000)
    before = h.scene(kind)
    before_rich, before_plain = deepcopy(h.field(before, alias)), deepcopy(h.field(before, key))
    record("p3a4_replace_one", sum(f["text"].lower().count("rangepin") for f in [before_rich, before_plain]) == 3)
    panel.get_by_role("button", name="Replace all", exact=True).click()
    record("p3a4_preview", '3 matches; 3 replaceable; 0 read-only. 1 group, one undo step' in panel.get_by_role("status").inner_text())
    h.screenshot("part4-preview")
    panel.get_by_role("button", name="Apply replacement groups", exact=True).click()
    page.wait_for_function("() => document.querySelector('.documentation-find-panel [role=status]')?.textContent === 'Applied 1 of 1 group.'", timeout=120000)
    after = h.scene(kind)
    rich_after = h.field(after, alias)
    record("p3a4_replace_group", rich_after["text"] == "Pin Pin" and h.field(after, key)["text"] == "Pin Pin")
    leaves = rich_after["richText"]["doc"]["content"][0]["content"]
    record("p3a4_neighbor_marks", node_ids(rich_after["richText"]) == node_ids(value)
           and leaves[0]["marks"] == [{"type": "bold"}] and leaves[-1]["marks"] == [{"type": "italic"}])
    panel.get_by_role("button", name="Close find", exact=True).click()
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith('/documentation-scene/undo'), timeout=120000) as response:
        page.locator("#documentationUndoRibbon").click()
    response.value.finished(); h.idle()
    restored = h.scene(kind)
    record("p3a4_group_one_undo", h.field(restored, alias)["richText"] == before_rich["richText"]
           and h.field(restored, key)["text"] == before_plain["text"])
    # Supervisor: Ctrl+F opens the panel inside the workspace, and it leaves with the document.
    page.locator("#documentationPublicationSurface").click(position={"x": 4, "y": 4})
    page.keyboard.press("Control+f")
    panel.wait_for(state="visible", timeout=30000)
    record("p3a4_ctrl_f_opens_in_workspace", page.locator("#documentationWorkspace .documentation-find-panel").count() == 1)
    h.switch("work_instructions")
    h.idle()
    record("p3a4_panel_follows_document", page.locator(".documentation-find-panel").count() == 0)

    page = h.open_document(kind, page_id, pointer_refresh=True)
    editor = h.mount(alias, generated=True)
    editor.press("Control+End")
    page.locator('.documentation-rich-controls').get_by_role("button", name="Symbol", exact=True).click()
    h.screenshot("part4-symbol-picker")
    picker = page.locator('.documentation-symbol-picker')
    viewport = page.viewport_size
    inside = picker.bounding_box()
    record("p3a4_symbol_picker_on_screen", picker.locator('button').count() == 69 and inside is not None
           and inside["x"] >= 0 and inside["y"] >= 0 and inside["x"] + inside["width"] <= viewport["width"]
           and inside["y"] + inside["height"] <= viewport["height"], inside)
    page.get_by_role("button", name="PLUS-MINUS SIGN", exact=True).click()
    h.screenshot("part4-symbol-editor")
    h.finish()
    symbol_field = h.field(h.scene(kind), alias)
    record("p3a4_symbol_stored_with_marks", symbol_field["text"].endswith("\u00b1") and
           symbol_field["richText"]["doc"]["content"][0]["content"][-1]["marks"] == [{"type": "italic"}])
    # Captures from part 3 are reusable after text-only edits; capture any newly materialized figure.
    page.locator("#documentationCaptureAllRibbon").click(no_wait_after=True)
    page.wait_for_function("""() => {
        const pages = window.__compareDbg.state.partsManualDocumentation?.document?.pages || [];
        return pages.filter(p => p.renderRequest).every(p => p.renderRequest.image?.status === 'ready')
            && !document.querySelector('#documentationWorkspace.busy');
    }""", timeout=240000)
    artifacts = {}
    for format in ("pdf", "docx"):
        response, result = h.press_export(kind, format)
        assert response.ok, result
        artifacts[format] = h.download(result[format], "p3a4-operations." + format)
    current = h.scene(kind)
    h.navigate(page_id)
    box = h.box(alias, generated=True)
    measured = box.evaluate(CANVAS_LINES_JS)
    h.screenshot("part4-symbol-canvas")
    box.screenshot(path=str(output / "p3a4-symbol-canvas.png"))
    canvas = canvas_matches_layout(current["document"], page_id, alias, "p3a4-symbol", measured, record, typography=True)
    pdf = compare_pdf(artifacts["pdf"], current["document"], page_id, alias, output / "p3a4-symbol-pdf.png")
    docx = compare_docx(artifacts["docx"], stable, content_model(symbol_field["richText"], symbol_field["richTextStyle"]))
    with fitz.open(stream=artifacts["pdf"], filetype="pdf") as exported:
        spans = [span for p in exported for block in p.get_text('dict')["blocks"] for line in block.get('lines', []) for span in line['spans'] if "\u00b1" in span['text']]
        # PyMuPDF names the built-in Helvetica faces "Nimbus Sans ..."; the symbol shares its span with the text.
        record("p3a4_symbol_no_fallback", bool(spans) and all(
            span['font'].lower().replace(' ', '').startswith(('helvetica', 'nimbussans')) and span['text'].strip() != "\u00b1"
            for span in spans), [(span['font'], span['text']) for span in spans])
    found = tool("find_document_text", {"documentType": kind, "query": "rangepin", "scopeIds": [stable]})
    assert found.get("ok"), found
    data = found["data"]
    edits = [{"operation": "replace_range", "targetId": item["targetId"], "expectedContentHash": item["contentHash"],
              "start": item["start"], "end": item["end"], "expectedText": item["match"], "text": "Sagepin"} for item in data["matches"]]
    assert edits
    result = tool("apply_document_edits", {"documentId": data["documentId"], "expectedRevision": data["rangeRevision"],
        "requestId": "p3a4-sage-range", "operations": edits})
    assert result.get("ok"), result
    record("p3a4_sage_find_batch", "Sagepin" in h.field(h.scene(kind), alias)["text"] and result["data"]["receipt"]["undoable"])
    report["p3a4Exports"] = {"canvas": canvas, "pdf": pdf, "docx": docx}
    write_json(output / "p3a4-comparison.json", report["p3a4Exports"])


def measure_table_canvas(h, kind, key, page_id, output, record, stem):
    """Shared static table geometry and per-cell typography proof (composition points)."""
    import fitz
    from ai_inspector.documentation.rich_layout import prepare_pdf_objects
    snapshot = h.scene(kind)["document"]
    box = h.box(key)
    whole = box.evaluate(CANVAS_LINES_JS)
    item = next(p for p in snapshot["pages"] if p["pageId"] == page_id)["documentationObjects"][key]
    # Supervisor: offsetWidth is a whole number. A frame of .84 x 960 is 806.4 px, and a layout made for 806 px
    # put every column 1/8 px off the real canvas. The element's own style holds the exact size.
    exact = box.evaluate("box => [parseFloat(box.style.width), parseFloat(box.style.height)]")
    size = (exact[0] / item["frame"]["width"], exact[1] / item["frame"]["height"])
    plan = prepare_pdf_objects(fitz, snapshot, size, canvas_rounding=True)[page_id][key]
    geometry = box.evaluate("""box => {
        const bounds = box.getBoundingClientRect(), css = getComputedStyle(box);
        const scale = bounds.width / parseFloat(css.width);
        const left = bounds.left + (parseFloat(css.borderLeftWidth) + parseFloat(css.paddingLeft)) * scale;
        const top = bounds.top + (parseFloat(css.borderTopWidth) + parseFloat(css.paddingTop)) * scale;
        const rect = node => { const r = node.getBoundingClientRect(); return [
            (r.left - left) / scale, (r.top - top) / scale, (r.right - left) / scale, (r.bottom - top) / scale]; };
        const table = box.querySelector('table');
        return {table: rect(table), columns: [...table.querySelectorAll('col')].map(rect),
            rows: [...table.querySelectorAll('tr')].map(rect),
            cells: [...table.querySelectorAll('td,th')].map(c => ({id:c.dataset.richId, box:rect(c)}))};
    }""")
    expected = plan.layout.tables[0]
    x, y = plan.layout.frame[:2]
    local = lambda rect: [rect[0] - x, rect[1] - y, rect[2] - x, rect[3] - y]
    # Supervisor: 0.05 px. The table rules are measured Chromium facts to 1/64 px; one px would hide an error.
    near = lambda a, b, tol=.05: len(a) == len(b) and all(abs(v - w) <= tol for v, w in zip(a, b))
    record(stem + "_canvas_table_box", near(geometry["table"], local(expected.box))
           and abs(whole["contentHeight"] - plan.layout.measured_height) <= .05,
           {"canvas": geometry["table"], "layout": local(expected.box), "canvasHeight": whole["contentHeight"],
            "layoutHeight": plan.layout.measured_height})
    record(stem + "_canvas_column_edges", all(near([c[0], c[2]], [expected.column_edges[n] - x, expected.column_edges[n + 1] - x])
        for n, c in enumerate(geometry["columns"])),
        {"canvas": geometry["columns"], "layout": [edge - x for edge in expected.column_edges]})
    record(stem + "_canvas_row_edges", all(near([r[1], r[3]], [expected.row_edges[n] - y, expected.row_edges[n + 1] - y])
        for n, r in enumerate(geometry["rows"])),
        {"canvas": geometry["rows"], "layout": [edge - y for edge in expected.row_edges]})
    lines = {}
    for number, cell in enumerate(geometry["cells"], 1):
        cid = cell["id"]
        actual = box.locator('[data-rich-id="' + cid + '"]').evaluate(CANVAS_LINES_JS)
        element = box.locator('[data-rich-id="' + cid + '"]')
        inset = element.evaluate("""node => {const s=getComputedStyle(node);return [
            parseFloat(s.borderLeftWidth)+parseFloat(s.paddingLeft), parseFloat(s.borderTopWidth)+parseFloat(s.paddingTop)];}""")
        expected_cell = expected.cells[cid]
        want = [{"text": "".join(r.text for r in line.runs), "left": line.runs[0].x - x,
                 "top": line.runs[0].rect[1] - y, "bottom": line.runs[0].rect[3] - y}
                for line in expected_cell.layout.lines if line.runs]
        got = [{"text": line["text"], "left": line["left"] + cell["box"][0] + inset[0],
                "top": line["top"] + cell["box"][1] + inset[1], "bottom": line["bottom"] + cell["box"][1] + inset[1]}
               for line in actual["lines"] if line["text"].strip()]
        record(stem + "_canvas_cell_%02d" % number, near(cell["box"], local(expected_cell.box)) and len(got) == len(want)
               and all(a["text"] == b["text"] and near([a[k] for k in ("left", "top", "bottom")],
                   [b[k] for k in ("left", "top", "bottom")]) for a, b in zip(got, want)),
               {"id": cid, "canvasBox": cell["box"], "layoutBox": local(expected_cell.box), "canvas": got, "layout": want})
        lines[cid] = got
    h.screenshot(stem + "-table")
    box.screenshot(path=str(output / (stem + "-canvas-table.png")))
    return {"geometry": geometry, "lines": lines}, snapshot, plan



def run_p3b(page, request, server, output, report, record, begin_edit, tool, fresh_page):
    """P3b part 1: Sage-authored table, real canvas, workspace exports and undo."""
    from copy import deepcopy
    import fitz
    from ai_inspector.documentation import tables
    from ai_inspector.documentation.commands import canonical_bytes
    from ai_inspector.documentation.rich_text import plain_text, node_ids
    from ai_inspector.documentation.rich_layout import prepare_pdf_objects
    from tests.documentation_rich_export_support import compare_pdf, compare_docx

    kind, key = "operations_and_maintenance_manual", "document-object-p3b"
    h = rich_browser_helpers(page, request, server, output, report, begin_edit, fresh_page, "P3b")
    page_id = h.create(kind, key, "Authored table", frame={"x": .12, "y": .24, "width": .7, "height": .55},
                       style={"fontFamily": "Arial", "fontSize": 10})
    page = h.open_document(kind, page_id, pointer_refresh=True)
    evidence = {"steps": []}
    sequence = 0

    def read_field():
        result = tool("read_document_pages", {"documentType": kind, "targets": [{"pageId": page_id, "targetId": key}]})
        assert result.get("ok"), result
        return result["data"], result["data"]["targets"][0]

    def stored():
        return h.field(h.scene(kind), key)["richText"]

    def table(value):
        return next(n for n in value["doc"]["content"] if n["type"] == "table")

    def apply(operations, name):
        nonlocal sequence
        sequence += 1
        full, field = read_field()
        previous = deepcopy(field.get("richText"))
        result = tool("apply_document_edits", {"documentId": full["documentId"],
            "expectedRevision": field["binding"]["revision"], "requestId": "p3b-" + str(sequence),
            "operations": [{**op, "targetId": field["targetId"], "expectedContentHash": field["contentHash"]} for op in operations]})
        assert result.get("ok"), result
        receipt = result["data"]["receipt"]
        value = stored()
        record("p3b_" + name + "_canonical", value["schemaVersion"] == 3 and plain_text(value) == h.field(h.scene(kind), key)["text"])
        if previous:
            # Pure style/range writes retain the complete ID inventory; structural changes are checked below.
            if all(op["operation"] in {"replace_range", "format_range"} or op.get("action", "").startswith("set_") for op in operations):
                record("p3b_" + name + "_ids", node_ids(previous) == node_ids(value))
        results = receipt.get("operationResults")
        if results:
            record("p3b_" + name + "_result_ids", results[-1]["table"] == tables.describe(table(value)))
        evidence["steps"].append({"name": name, "value": value, "receipt": receipt})
        write_json(output / "p3b-table.json", evidence)
        return value, receipt

    value, created = apply([{"operation": "create_table", "rows": 3, "columns": 4, "headerRow": True}], "create")
    identity = created["operationResults"][0]["table"]
    record("p3b_created_grid", len(identity["rows"]) == 3 and len(identity["columnIds"]) == 4
           and all(len(r["cellIds"]) == 4 for r in identity["rows"]))
    initial_ids = node_ids(value)
    # Empty cells are separated in the projection, so every insertion refers to a distinct pre-image boundary.
    start = len("Authored table") + 1
    text = plain_text(value)
    fills = [{"operation": "replace_range", "start": start + n, "end": start + n, "expectedText": "", "text": "Cell " + str(n + 1)}
             for n in range(12)]
    value, _ = apply(fills, "fill")
    record("p3b_fill_keeps_all_ids", node_ids(value) == initial_ids)
    text = plain_text(value)
    start = text.index("Cell 6")
    value, _ = apply([{"operation": "format_range", "start": start, "end": start + 6, "expectedText": "Cell 6",
                       "add": [{"feature": "bold"}]}], "format")

    def modify(action, **extra):
        return {"operation": "modify_table", "tableId": identity["tableId"], "action": action, **extra}

    before_merge = deepcopy(value)
    value, _ = apply([modify("merge_cells", cellIds=identity["rows"][0]["cellIds"][:2]),
                      modify("merge_cells", cellIds=[identity["rows"][1]["cellIds"][2], identity["rows"][2]["cellIds"][2]])], "merge")
    anchors = tables.grid(table(value))[0]
    record("p3b_merge_survivors", any(e["cell"]["attrs"]["id"] == identity["rows"][0]["cellIds"][0] and e["colspan"] == 2 for e in anchors)
           and any(e["cell"]["attrs"]["id"] == identity["rows"][1]["cellIds"][2] and e["rowspan"] == 2 for e in anchors))
    record("p3b_merge_paragraph_ids", {p["attrs"]["id"] for row in table(before_merge)["content"] for cell in row["content"] for p in cell["content"]}
           == {p["attrs"]["id"] for row in table(value)["content"] for cell in row["content"] for p in cell["content"]})
    value, _ = apply([modify("set_widths", widths=[{"columnId": cid, "width": width}
                        for cid, width in zip(identity["columnIds"], [200, 300, 250, 250])]),
                      modify("set_cell_style", cellIds=[identity["rows"][1]["cellIds"][2]], style={"fill": "#fff0aa", "verticalAlign": "middle"}),
                      modify("set_cell_style", cellIds=[identity["rows"][2]["cellIds"][3]], style={"verticalAlign": "bottom"})], "style")
    before_insert = deepcopy(value)
    value, inserted = apply([modify("insert_row", rowId=identity["rows"][1]["rowId"], position="before"),
                            modify("insert_column", columnId=identity["columnIds"][1], position="after")], "insert")
    record("p3b_insert_preserves_ids", node_ids(before_insert) < node_ids(value))
    inserted_identity = inserted["operationResults"][-1]["table"]
    new_row = next(r["rowId"] for r in inserted_identity["rows"] if r["rowId"] not in {r["rowId"] for r in identity["rows"]})
    new_column = next(c for c in inserted_identity["columnIds"] if c not in identity["columnIds"])
    value, _ = apply([modify("delete_row", rowId=new_row), modify("delete_column", columnId=new_column)], "delete")
    record("p3b_delete_restores_ids", node_ids(value) == node_ids(before_insert))
    # Supervisor: one-line cells cannot show a wrong row rule. Wrap one cell, and make the merged cell taller than
    # its two rows so the canvas shares the difference between them (fractions of 1/64 px).
    text = plain_text(value)
    wrap = "Torque every fastener to the value on the drawing, then mark it with paint."
    tall = ("Check the hydraulic oil level at the sight glass before every shift. Top up with ISO VG 46 oil only. "
            "Do not mix oil grades. Record the level, the date and your initials on the lubrication chart beside "
            "the machine.")
    ids_before_wrap = node_ids(value)
    value, _ = apply([{"operation": "replace_range", "start": text.index("Cell 8"), "end": text.index("Cell 8") + 6,
                       "expectedText": "Cell 8", "text": wrap},
                      {"operation": "replace_range", "start": text.index("Cell 7"), "end": text.index("Cell 7") + 6,
                       "expectedText": "Cell 7", "text": tall}], "wrap")
    record("p3b_wrap_keeps_all_ids", node_ids(value) == ids_before_wrap)
    value, _ = apply([modify("set_cell_style", cellIds=[identity["rows"][1]["cellIds"][1]],
                             style={"verticalAlign": "middle"})], "align")
    before_last = deepcopy(value)
    value, _ = apply([modify("set_cell_style", cellIds=[identity["rows"][1]["cellIds"][0]], style={"fill": "#dceeff"})], "last_batch")

    page = h.open_document(kind, page_id, pointer_refresh=True)
    record("p3b_reload_ids_and_bytes", canonical_bytes(stored()) == canonical_bytes(value))
    _, field = read_field()
    record("p3b_capabilities", field["richTextCapabilities"]["schemaVersions"] == [1, 2, 3]
           and "table" in field["richTextCapabilities"]["features"])

    def measure(stem="p3b"):
        return measure_table_canvas(h, kind, key, page_id, output, record, stem)

    measured, snapshot, plan = measure()
    shape = plan.layout.tables[0]
    heights = [b - a for a, b in zip(shape.row_edges, shape.row_edges[1:])]
    spare = {cid: (cell.content_box[3] - cell.content_box[1]) - cell.layout.measured_height
             for cid, cell in shape.cells.items()}
    # The proof must really contain what it claims: wrapped cells, a merged cell that stretches its rows to a
    # fractional height, and aligned cells with room to move.
    record("p3b_proof_has_wrapped_and_stretched_rows",
           sum(len(lines) > 1 for lines in measured["lines"].values()) >= 2
           and any(abs(h - round(h)) > .01 for h in heights)
           and spare[identity["rows"][1]["cellIds"][1]] > 4 and spare[identity["rows"][2]["cellIds"][3]] > 4,
           {"rowHeights": heights, "lines": {cid: len(lines) for cid, lines in measured["lines"].items()},
            "spare": spare})
    page.locator("#documentationCaptureAllRibbon").click(no_wait_after=True)
    page.wait_for_function("""() => {
        const figures = (window.__compareDbg.state.partsManualDocumentation?.document?.pages || []).filter(p => p.renderRequest);
        return figures.length && figures.every(p => p.renderRequest.image?.status === 'ready')
            && !document.querySelector('#documentationWorkspace.busy');
    }""", timeout=240000)
    artifacts = {}
    for format in ("pdf", "docx"):
        response, result = h.press_export(kind, format)
        assert response.ok, result
        artifacts[format] = h.download(result[format], "p3b-table." + format)
    snapshot = h.scene(kind)["document"]
    evidence["pdf"] = compare_pdf(artifacts["pdf"], snapshot, page_id, key, output / "p3b-pdf.png")
    evidence["docx"] = compare_docx(artifacts["docx"], key, plan.layout.content)
    record("p3b_exports", docx_run_text(artifacts["docx"], key) == plain_text(value).replace("\n", ""))
    revision = h.scene(kind)["revision"]
    # P3b-2 lifts the editor guard; entering and escaping unchanged still never writes.
    editor = h.mount(key)
    record("p3b_table_editor_enabled", page.evaluate("() => DocumentationRichText.mountedCount") == 1
           and h.scene(kind)["revision"] == revision and stored() == value)
    editor.press("Escape")
    page.wait_for_function("() => DocumentationRichText.mountedCount === 0")
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/undo"), timeout=120000) as response:
        page.locator("#documentationUndoRibbon").click()
    response.value.finished()
    assert response.value.ok, response.value.text()[:1000]
    h.idle()
    record("p3b_one_undo_exact_preimage", canonical_bytes(stored()) == canonical_bytes(before_last))
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/redo"), timeout=120000) as response:
        page.locator("#documentationRedoRibbon").click()
    response.value.finished()
    assert response.value.ok, response.value.text()[:1000]
    h.idle()
    page = h.open_document(kind, page_id, pointer_refresh=True)
    record("p3b_reopen_after_redo", canonical_bytes(stored()) == canonical_bytes(value))
    reopened, _, _ = measure("p3b-reopened")
    record("p3b_reopened_canvas", same_canvas(measured, reopened))
    evidence["canvas"] = measured
    # Transparent rules are a distinct authored table style: measure and export it in the real app too.
    plain, _ = apply([modify("set_table_style", style="plain")], "plain_style")
    h.refresh(pointer=True)
    plain_canvas, plain_snapshot, plain_plan = measure("p3b-plain")
    plain_artifacts = {}
    for format in ("pdf", "docx"):
        response, result = h.press_export(kind, format)
        assert response.ok, result
        plain_artifacts[format] = h.download(result[format], "p3b-plain-table." + format)
    evidence["plain"] = {"canvas": plain_canvas,
        "pdf": compare_pdf(plain_artifacts["pdf"], plain_snapshot, page_id, key, output / "p3b-plain-pdf.png"),
        "docx": compare_docx(plain_artifacts["docx"], key, plain_plan.layout.content)}
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/undo"), timeout=120000) as response:
        page.locator("#documentationUndoRibbon").click()
    response.value.finished(); assert response.value.ok, response.value.text()[:1000]
    h.idle()
    record("p3b_plain_style_undo", canonical_bytes(stored()) == canonical_bytes(value))
    write_json(output / "p3b-table.json", evidence)
    run_p3b_editor(page, request, server, output, report, record, begin_edit, tool, fresh_page, key)



def run_p3b_editor(page, request, server, output, report, record, begin_edit, tool, fresh_page, prior_key):
    """Part 2: real pointer/keyboard input; editor API access below only reads state."""
    from copy import deepcopy
    from ai_inspector.documentation import tables
    from ai_inspector.documentation.commands import canonical_bytes
    from ai_inspector.documentation.rich_text import node_ids, plain_text
    from tests.documentation_rich_export_support import compare_pdf, compare_docx

    kind, key = "operations_and_maintenance_manual", "document-object-p3b-edit"
    h = rich_browser_helpers(page, request, server, output, report, begin_edit, fresh_page, "P3b2")
    before = h.scene(kind)
    page_id = before["document"]["pages"][0]["pageId"]
    # The prior proof is saved; keep this specimen unobscured in the isolated scene.
    removed = request.post(h.base(kind) + "/documentation-scene/commands", data={
        "baseRevision": before["revision"], "sourceRevision": before["scene"]["sourceRevision"],
        "manualPlanRevision": before["scene"]["manualPlanRevision"], "operation": "remove_object",
        "pageId": page_id, "targetType": "document_object", "targetId": prior_key}, timeout=120000)
    assert removed.ok, removed.text()
    removed.body()
    h.create(kind, key, "Workspace table", frame={"x": .08, "y": .15, "width": .84, "height": .72},
             style={"fontFamily": "Arial", "fontSize": 10})
    page = h.open_document(kind, page_id, pointer_refresh=True)
    h.mount(key)
    proof = {"steps": []}
    controls = page.locator(".documentation-rich-controls")
    panel = page.get_by_role("dialog", name="Table menu", exact=True)

    def stored():
        return h.field(h.scene(kind), key).get("richText")

    def table(value=None):
        return next(n for n in (value or stored())["doc"]["content"] if n["type"] == "table")

    def editor():
        return page.locator('.documentation-rich-editor [contenteditable="true"]')

    def caret():
        return page.evaluate("""() => {
            const s = DocumentationRichText.active.editor.state.selection;
            for (let d = s.$from.depth; d > 0; d--) {
                const n = s.$from.node(d);
                if (['tableCell','tableHeader'].includes(n.type.name)) return n.attrs.id;
            }
            return null;
        }""")

    def cell(cid):
        return editor().locator('[data-rich-id="' + cid + '"]')

    def open_menu():
        controls.get_by_role("button", name="Table", exact=True).click()
        panel.wait_for(state="visible")

    def close_menu():
        panel.get_by_label("Rows", exact=True).press("Escape")
        panel.wait_for(state="hidden")

    def input_number(label, value):
        control = panel.get_by_label(label, exact=True)
        control.click(); control.press("Control+a"); page.keyboard.insert_text(str(value))
        # Button pointer handling preserves the value; blur must not save a draft.
        control.press("Tab")

    def cell_text(node):
        # Supervisor: plain_text takes a whole envelope; a cell is walked here.
        return node.get("text", "") + "".join(cell_text(child) for child in node.get("content", []))

    def action(label, name, configure=None):
        preimage = deepcopy(stored())
        open_menu()
        if configure:
            configure()
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/tables"), timeout=120000) as response:
            panel.get_by_role("button", name=label, exact=True).click()
        response.value.finished()
        result = response.value.json()
        assert response.value.ok, result
        page.wait_for_function("""() => DocumentationRichText.active && !DocumentationRichText.active.saving
            && document.querySelector('.documentation-rich-editor [contenteditable="true"]')
            && !document.querySelector('.documentation-table-menu:not([hidden])')""", timeout=120000)
        # Focus is asynchronous in Tiptap; wait for the actual caret before sending the next physical key.
        page.wait_for_function("() => document.activeElement?.classList.contains('tiptap')")
        value = stored()
        identity = result["receipt"]["operationResults"][0]["table"]
        record("p3b2_" + name + "_receipt", identity == (tables.describe(table(value)) if identity else None),
               {"receipt": result["receipt"], "caret": caret()})
        proof["steps"].append({"name": name, "before": preimage, "after": value, "receipt": result["receipt"], "caret": caret()})
        write_json(output / "p3b2-editor.json", proof)
        return preimage, value, identity

    open_menu()
    record("p3b2_insert_defaults", panel.get_by_label("Rows", exact=True).input_value() == "3"
           and panel.get_by_label("Columns", exact=True).input_value() == "3"
           and panel.get_by_label("Header row", exact=True).is_checked())
    h.screenshot("menu")
    close_menu()
    _, value, identity = action("Insert", "insert")
    first = identity["rows"][0]["cellIds"][0]
    record("p3b2_insert_focus_first_cell", caret() == first, caret())
    for i in range(9):
        page.keyboard.insert_text("Typed" + str(i + 1))
        page.keyboard.press("Tab")
    draft = page.evaluate("() => DocumentationRichText.active.editor.getJSON()")
    draft_table = next(n for n in draft["content"] if n["type"] == "table")
    record("p3b2_tab_last_no_row", len(draft_table["content"]) == 3
           and caret() == identity["rows"][-1]["cellIds"][-1], draft_table)
    page.keyboard.press("Shift+Tab")
    record("p3b2_shift_tab_previous", caret() == identity["rows"][-1]["cellIds"][-2], caret())
    page.keyboard.press("Tab")
    # Supervisor: Tab selects the text of the cell it enters (as Word does), so typing would replace it.
    record("p3b2_tab_selects_cell_text", page.evaluate("""() => {
        const s = DocumentationRichText.active.editor.state;
        return s.doc.textBetween(s.selection.from, s.selection.to);
    }""") == "Typed9")
    page.keyboard.press("End")
    # The editor learns of a native caret move from the browser's selectionchange event, which arrives after the
    # key. A key sent before it (only automation is that fast) would still act on the old selection.
    page.wait_for_function("() => DocumentationRichText.active.editor.state.selection.empty")
    page.keyboard.press("Enter"); page.keyboard.insert_text("Second paragraph")
    record("p3b2_enter_in_cell", page.evaluate("""() => {
        const doc = DocumentationRichText.active.editor.getJSON();
        return doc.content.find(n=>n.type==='table').content.at(-1).content.at(-1).content.length;
    }""") == 2)
    h.finish()
    value = stored()
    record("p3b2_typed_text_and_ids", all("Typed" + str(i) in plain_text(value) for i in range(1, 10))
           and tables.describe(table(value)) == identity, value)
    measured, _, _ = measure_table_canvas(h, kind, key, page_id, output, record, "p3b2-typed")
    # Compare cell boxes with the unchanged static view in composition points.
    def cell_boxes():
        return h.box(key).evaluate("""box => {
            const bounds = box.getBoundingClientRect(), scale = bounds.width / parseFloat(getComputedStyle(box).width);
            return [...box.querySelectorAll('td,th')].map(c => {const r=c.getBoundingClientRect();
                return {id:c.dataset.richId, rect:[r.left-bounds.left,r.top-bounds.top,r.width,r.height].map(v=>v/scale)};});
        }""")
    static = cell_boxes()
    h.mount(key)
    mounted = cell_boxes()
    record("p3b2_mount_geometry", len(static) == len(mounted) and all(a["id"] == b["id"]
           and all(abs(x-y) <= .05 for x, y in zip(a["rect"], b["rect"])) for a, b in zip(static, mounted)),
           {"static": static, "mounted": mounted})
    cell(first).click()
    for label in ("Style",):
        record("p3b2_cell_disabled_" + label, controls.get_by_label(label, exact=True).get_attribute("aria-disabled") == "true")
    for label in ("Bullets", "Numbering"):
        record("p3b2_cell_disabled_" + label, controls.get_by_role("button", name=label, exact=True).get_attribute("aria-disabled") == "true")
    # Drag across the first two cells: ProseMirror creates a real cell selection.
    a = cell(first).bounding_box(); b = cell(identity["rows"][0]["cellIds"][1]).bounding_box()
    page.mouse.move(a["x"] + 8, a["y"] + 8); page.mouse.down()
    page.mouse.move(b["x"] + b["width"] - 8, b["y"] + b["height"] / 2, steps=12); page.mouse.up()
    selected = page.evaluate("""() => {
        const s=DocumentationRichText.active.editor.state.selection, ids=[];
        if(s.$anchorCell && typeof s.forEachCell==='function') s.forEachCell(c=>ids.push(c.attrs.id));
        return ids;
    }""")
    record("p3b2_cell_selection", selected == identity["rows"][0]["cellIds"][:2], selected)
    h.screenshot("cell-selection")
    _, value, _ = action("Merge cells", "merge")
    record("p3b2_merge_focus", table(value)["content"][0]["content"][0]["attrs"].get("colspan") == 2
           and caret() == first, {"cell": table(value)["content"][0]["content"][0], "caret": caret()})
    page.keyboard.insert_text("Immediate")
    record("p3b2_merge_typing_immediate", "Immediate" in editor().inner_text())
    pre = deepcopy(stored())
    _, value, _ = action("Insert row below", "insert_row")
    # The saved draft and server operation have distinct history entries.
    step = proof["steps"][-1]["receipt"]
    record("p3b2_dirty_text_and_structure_two_steps", "Immediate" in plain_text(value)
           and step["beforeRevision"] == proof["steps"][-2]["receipt"]["revision"] + 1
           and node_ids(pre) < node_ids(value), step)
    _, value, _ = action("Insert column right", "insert_column")
    record("p3b2_insert_dimensions", len(table(value)["content"]) == 4 and len(table(value)["attrs"]["columns"]) == 4)
    _, value, _ = action("Split cell", "split")
    record("p3b2_split_content_anchor", caret() == first
           and "Immediate" in cell_text(table(value)["content"][0]["content"][0])
           and all(not c["attrs"].get("colspan") for c in table(value)["content"][0]["content"]))
    _, value, _ = action("Header cell", "header")
    record("p3b2_header_toggle", table(value)["content"][0]["content"][0]["type"] == "tableCell")
    open_menu()
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/tables"), timeout=120000) as response:
        fill = panel.get_by_label("Fill hex", exact=True)
        fill.click(); fill.press("Control+a"); page.keyboard.insert_text("#cceeff"); fill.press("Tab")
    response.value.finished(); assert response.value.ok, response.value.text()
    page.wait_for_function("() => DocumentationRichText.active && !DocumentationRichText.active.saving && document.activeElement?.classList.contains('tiptap')")
    record("p3b2_fill", table()["content"][0]["content"][0]["attrs"].get("fill") == "#cceeff")
    _, value, _ = action("Align middle", "middle")
    record("p3b2_middle", table(value)["content"][0]["content"][0]["attrs"].get("verticalAlign") == "middle")
    _, value, _ = action("Borders", "plain")
    record("p3b2_plain", table(value)["attrs"]["style"] == "plain")
    _, value, _ = action("Borders", "grid")
    record("p3b2_grid", table(value)["attrs"]["style"] == "grid")
    columns_before = deepcopy(table()["attrs"]["columns"])
    expected = [400, *tables._shares([c["width"] for c in columns_before[1:]], 600)]
    _, value, _ = action("Apply", "width_40", lambda: input_number("Column width", 40))
    record("p3b2_width_40", [c["width"] for c in table(value)["attrs"]["columns"]] == expected,
           {"expected": expected, "columns": table(value)["attrs"]["columns"]})
    _, value, _ = action("Equal widths", "equal")
    record("p3b2_equal_widths", [c["width"] for c in table(value)["attrs"]["columns"]] == [250] * 4)
    # A 1% column is below 12 pt in this frame. The checked refusal is the only expected HTTP failure.
    saved = deepcopy(stored()); revision = h.scene(kind)["revision"]
    open_menu(); input_number("Column width", 1)
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/tables"), timeout=120000) as response:
        panel.get_by_role("button", name="Apply", exact=True).click()
    response.value.finished(); error = response.value.json()
    page.wait_for_function("() => DocumentationRichText.active && !DocumentationRichText.active.saving")
    message = page.locator(".documentation-rich-message").inner_text()
    checked = response.value.status == 422 and error.get("error") == "table_column_too_narrow"
    report.setdefault("expectedHttpFailures", []).append({"url": response.value.url, "status": response.value.status,
        "method": "POST", "error": error.get("error"), "checked": checked})
    record("p3b2_server_refusal_keeps_editor", checked and bool(message) and stored() == saved
           and h.scene(kind)["revision"] == revision and page.evaluate("() => DocumentationRichText.mountedCount") == 1,
           {"response": error, "notice": message})
    close_menu()
    # Write an HTML clipboard payload, then use a real paste key; no editor commands.
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=server.url)
    page.evaluate("""async () => navigator.clipboard.write([new ClipboardItem({
        'text/html':new Blob(['<table><tr><td>Foreign</td></tr></table>'],{type:'text/html'}),
        'text/plain':new Blob(['Foreign'],{type:'text/plain'})})])""")
    draft_before = page.evaluate("() => DocumentationRichText.active.editor.getJSON()")
    page.keyboard.press("Control+v")
    page.wait_for_function("() => document.querySelector('.documentation-rich-message')?.textContent === 'Tables cannot be pasted here. Use Table, Insert table.'")
    record("p3b2_paste_refused", page.evaluate("() => DocumentationRichText.active.editor.getJSON()") == draft_before
           and stored() == saved, page.locator(".documentation-rich-message").inner_text())
    _, value, _ = action("Delete row", "delete_row")
    record("p3b2_delete_row_count", len(table(value)["content"]) == 3)
    _, value, _ = action("Delete column", "delete_column")
    record("p3b2_delete_column_count", len(table(value)["attrs"]["columns"]) == 3)
    # The final table has no trailing paragraph. Arrow out into the gap, then type there.
    last_cell = table(value)["content"][-1]["content"][-1]["attrs"]["id"]
    cell(last_cell).click()
    page.keyboard.press("Control+End"); page.keyboard.press("ArrowDown")
    gap = page.evaluate("() => DocumentationRichText.active.editor.state.selection.constructor.name")
    page.keyboard.insert_text("After the table")
    h.finish()
    value = stored()
    record("p3b2_type_after_final_table", value["doc"]["content"][-1]["type"] == "paragraph"
           and cell_text(value["doc"]["content"][-1]) == "After the table", {"selection": gap, "value": value})
    h.mount(key)
    cell(table(value)["content"][0]["content"][0]["attrs"]["id"]).click()
    pre_delete, deleted, _ = action("Delete table", "delete_table")
    record("p3b2_delete_table", all(n["type"] != "table" for n in deleted["doc"]["content"]))
    editor().press("Escape")
    def history(which):
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/documentation-scene/" + which), timeout=120000) as response:
            page.locator("#documentation" + which.title() + "Ribbon").click()
        response.value.finished(); assert response.value.ok, response.value.text()
        h.idle()
    history("undo")
    record("p3b2_undo_delete_exact", canonical_bytes(stored()) == canonical_bytes(pre_delete))
    history("redo")
    record("p3b2_redo_delete_exact", canonical_bytes(stored()) == canonical_bytes(deleted))
    history("undo")  # Restore the authored table for export and the final Sage interoperability proof.
    measured, snapshot, plan = measure_table_canvas(h, kind, key, page_id, output, record, "p3b2-final")
    h.screenshot("final-table")
    page.locator("#documentationCaptureAllRibbon").click(no_wait_after=True)
    page.wait_for_function("""() => {
        const figures=(window.__compareDbg.state.partsManualDocumentation?.document?.pages||[]).filter(p=>p.renderRequest);
        return figures.length && figures.every(p=>p.renderRequest.image?.status==='ready')
            && !document.querySelector('#documentationWorkspace.busy');
    }""", timeout=240000)
    artifacts = {}
    for format in ("pdf", "docx"):
        response, result = h.press_export(kind, format)
        assert response.ok, result
        artifacts[format] = h.download(result[format], "p3b2-table." + format)
    proof["pdf"] = compare_pdf(artifacts["pdf"], h.scene(kind)["document"], page_id, key, output / "p3b2-pdf.png")
    proof["docx"] = compare_docx(artifacts["docx"], key, plan.layout.content)
    record("p3b2_exports", docx_run_text(artifacts["docx"], key) == plain_text(stored()).replace("\n", ""))
    bound = tool("read_document_pages", {"documentType": kind, "targets": [{"pageId": page_id, "targetId": key}]})
    assert bound.get("ok"), bound
    field = bound["data"]["targets"][0]; before_sage = deepcopy(stored())
    result = tool("apply_document_edits", {"documentId": bound["data"]["documentId"], "expectedRevision": field["revision"],
        "requestId": "p3b2-sage", "operations": [{"operation": "modify_table", "targetId": field["targetId"],
            "expectedContentHash": field["contentHash"], "tableId": table()["attrs"]["id"],
            "action": "set_table_style", "style": "plain"}]})
    assert result.get("ok"), result
    value = stored()
    record("p3b2_sage_keeps_ids_text", node_ids(value) == node_ids(before_sage) and plain_text(value) == plain_text(before_sage))
    page = h.open_document(kind, page_id, pointer_refresh=True)
    record("p3b2_reload_ids_content", canonical_bytes(stored()) == canonical_bytes(value), value)
    reopened, _, _ = measure_table_canvas(h, kind, key, page_id, output, record, "p3b2-reopened")
    record("p3b2_reloaded_geometry", same_canvas(measured, reopened))
    proof["final"] = value
    write_json(output / "p3b2-editor.json", proof)


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

    def begin_edit(cell, *, read_only=False):
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
                page.wait_for_function("readonly => readonly ? !!document.querySelector('.documentation-rich-readonly') : !!document.querySelector('[contenteditable=\"true\"]')",
                                       arg=read_only, timeout=5000)
                report["editAttempts"].append(attempt)
                return
            except Exception:
                page.wait_for_timeout(1000)
        raise RuntimeError("Inline edit did not start after three double presses")

    try:
        if args.phase not in {"P1a", "P1b", "P1c", "P2a", "P2b", "P3a", "P3b"}:
            raise RuntimeError("Only the P1a-P3a and P3b part 1 gates are implemented.")
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

        if args.phase == "P3b":
            run_p3b(page, request, server, output, report, record, begin_edit, tool, fresh_page)
        elif args.phase == "P3a":
            run_p3a(page, request, server, output, report, record, begin_edit, tool, fresh_page)
        elif args.phase == "P2b":
            run_p2b(page, request, server, output, report, record, begin_edit, tool, fresh_page)
        elif args.phase == "P2a":
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
            record("scene_upgraded_in_place", reopened["scene"]["schemaVersion"] == 6
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
