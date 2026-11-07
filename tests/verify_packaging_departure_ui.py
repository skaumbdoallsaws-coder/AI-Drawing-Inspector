"""Headless browser check of departure coverage: unapplied fields and unfinished imports survive a closed editor.

Self-contained: it starts its own packaging app from this worktree on a free local port with a throwaway store in
the system temp directory, and aborts every browser request to another host. A "crash" closes the editor page
without saving. The native desktop window is not involved here; this checks the editor half of the contract
(what the native close relies on): the stored recovery draft, the coverage the editor reports, and recovery.

    python tests/verify_packaging_departure_ui.py [--output .runtime/<new folder>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
import trimesh
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.verify_packaging_comparison_ui import HEADERS, designs  # noqa: E402
from tests.verify_packaging_research_ui import tools_scope  # noqa: E402

COVERAGE = "window.InspectorProPackaging.getDepartureCoverage()"


class ImportGate:
    """Holds GLB import requests at this check's own server, then drops them unstored when released."""

    def __init__(self):
        self.active, self.held, self.event = False, 0, threading.Event()

    def hold(self):
        self.event.clear()
        self.held, self.active = 0, True

    def release(self):
        self.active = False
        self.event.set()

    def wait_held(self, page, seconds=20):
        deadline = time.monotonic() + seconds
        while self.held < 1:  # Waits through Playwright, so its route handlers keep running.
            if time.monotonic() > deadline:
                raise AssertionError("The import request never reached the check's server.")
            page.wait_for_timeout(50)


def start(storage, gate):
    import asyncio
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles
    from ai_inspector.facility_layout.authorization import local_facility_principal
    from ai_inspector.packaging_shipping.api import create_router
    from ai_inspector.packaging_shipping.service import PackagingService
    from ai_inspector.packaging_shipping.sources import GlbRuntime

    service = PackagingService(storage)
    principal = local_facility_principal(site_id="packaging-pilot")
    app = FastAPI()

    @app.middleware("http")
    async def import_gate(request, call_next):
        if gate.active and request.method == "POST" and request.url.path == "/api/packaging/sources":
            gate.held += 1
            await asyncio.to_thread(gate.event.wait, 60)
            return JSONResponse({"error": {"code": "check_dropped", "message": "Dropped by the check."}}, status_code=503)
        return await call_next(request)

    app.include_router(create_router(service, principal_resolver=lambda request: principal, static_root=ROOT / "static",
                                     source_runtime=GlbRuntime(Path(trimesh.__file__).resolve().parents[1])))
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("The check's own app did not start.")
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server, thread, service, principal


def verify(url, output, service, principal, gate):
    errors, external, checks, prompts = [], [], [], []
    scope, owner = tools_scope(principal), principal.principal_id
    seed, _ = designs()
    seed["name"] = "TEST departure " + uuid4().hex[:6]
    glb = trimesh.creation.box(extents=[0.08, 0.05, 0.03]).export(file_type="glb")
    model = output / "TEST-departure.glb"
    model.write_bytes(glb)

    def drafts():
        return service.drafts(scope, owner)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})

        def local_only(route):
            if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
                external.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", local_only)
        created = context.request.post(url + "/api/packaging/documents", data=seed, headers=HEADERS)
        assert created.ok, created.text()
        doc = created.json()

        def editor():
            page = context.new_page()
            page.set_default_timeout(20000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: (prompts.append(dialog.message), dialog.accept()))
            page.goto(url + "/packaging", wait_until="networkidle")
            return page

        def open_document(page):
            page.get_by_role("button", name="Open", exact=True).click()
            page.locator(".document-row").filter(has_text=seed["name"]).get_by_role("button", name="Open", exact=True).click()
            expect(page.locator("#document-name")).to_have_value(seed["name"])

        def product_panel(page):
            if page.locator("#command-product").get_attribute("aria-expanded") != "true":
                page.locator("#command-product").click()
            expect(page.locator("[name='product_name']")).to_be_visible()

        def stored_put(page, predicate):
            return page.expect_request(lambda r: r.method == "PUT" and "/api/packaging/drafts/" in r.url
                                       and predicate(json.loads(r.post_data or "{}")))

        def recovery(page, expected):
            dialog = page.locator("#resource-dialog")
            try:
                expect(dialog).to_contain_text("Recover unsaved work")
                expect(dialog).to_contain_text(expected)
            except AssertionError:
                page.screenshot(path=str(output / "failure.png"), full_page=True)
                print("Recovery dialog:", dialog.inner_text() if dialog.count() else None, "| drafts:", drafts(), flush=True)
                raise
            return dialog

        # F. Typed but unapplied values: stored after the debounce, covered, and restored as typed (unapplied).
        page = editor()
        open_document(page)
        product_panel(page)
        coverage = page.evaluate(COVERAGE)
        assert coverage["covered"] is True and coverage["draft"] is None, coverage  # Saved and clean: nothing to keep.
        with stored_put(page, lambda body: (body.get("unapplied") or {}).get("editor") == "product") as sent:
            page.locator("[name='product_name']").fill("TEST typed but not applied")
        fields = dict(json.loads(sent.value.post_data)["unapplied"]["fields"])
        assert fields["product_name"] == "TEST typed but not applied", fields
        page.wait_for_function(f"{COVERAGE}.covered === true")
        coverage = page.evaluate(COVERAGE)
        assert coverage["draft"] and coverage["reasons"] == [], coverage
        assert service.get(scope, doc["id"])["design"]["product"]["name"] == seed["product"]["name"]  # Not applied.
        page.close()
        page = editor()
        dialog = recovery(page, "values typed in the product panel, not applied")
        dialog.screenshot(path=str(output / "recover-unapplied.png"))
        dialog.get_by_role("button", name="Restore 1", exact=True).click()
        expect(page.locator("[name='product_name']")).to_have_value("TEST typed but not applied")
        expect(page.locator("#panel-state")).to_have_text("Unapplied fields")
        expect(page.locator("#message")).to_contain_text("Values typed in the product panel are back, still unapplied")
        page.get_by_role("button", name="Apply product", exact=True).click()
        expect(page.locator("#document-status")).to_contain_text("Unsaved changes")
        checks.append("F: an unapplied product name was checkpointed, reported covered, and restored unapplied after a closed editor")

        # G. Departure preparation stores the newest state at once, without waiting for the debounce.
        with stored_put(page, lambda body: body["design"]["name"] == "TEST prepared G") as sent:
            page.locator("#document-name").fill("TEST prepared G")
            assert page.evaluate("window.InspectorProPackaging.prepareDeparture()") is True
        assert page.evaluate(f"{COVERAGE}.covered") is True
        assert [d["name"] for d in drafts()] == ["TEST prepared G"]
        with page.expect_response(lambda r: r.request.method == "DELETE" and "/api/packaging/drafts/" in r.url):
            page.get_by_role("button", name="Reload saved document", exact=True).click()
        expect(page.locator("#message")).to_contain_text("Document opened.")
        assert drafts() == []
        checks.append("G: prepareDeparture stored the newest state immediately and reported it covered")

        # H. States a recovery draft cannot keep are reported, so the native guard keeps blocking.
        page.get_by_role("button", name="Open", exact=True).click()
        expect(page.locator("dialog[open]")).to_have_count(1)  # The document list.
        assert "dialog" in page.evaluate(COVERAGE)["reasons"]
        page.keyboard.press("Escape")
        expect(page.locator("dialog[open]")).to_have_count(0)
        product_panel(page)
        page.locator("[name='source_file']").set_input_files(str(model))
        assert "selected_file" in page.evaluate(COVERAGE)["reasons"]
        checks.append("H: a selected file and an open dialog are reported as not covered")

        def sources():
            return [m["name"] for m in context.request.get(url + "/api/packaging/sources").json()["sources"]]

        # I. An import closed mid-request: the draft records it; recovery says it did not finish. The server holds the
        # request until the editor has closed, then drops it unstored.
        gate.hold()
        with stored_put(page, lambda body: (body.get("importing") or {}).get("name") == "TEST-departure.glb"):
            page.get_by_role("button", name="Import GLB", exact=True).click()
        gate.wait_held(page)
        page.wait_for_function(f"{COVERAGE}.covered === true")
        coverage = page.evaluate(COVERAGE)
        assert coverage["reasons"] == [], coverage  # Busy importing, yet covered.
        page.close()
        gate.release()
        assert sources() == []
        page = editor()
        dialog = recovery(page, 'an import of "TEST-departure.glb" did not finish')
        dialog.get_by_role("button", name="Restore 1", exact=True).click()
        expect(page.locator("#message")).to_contain_text('The import of "TEST-departure.glb" did not finish. Import it again.')
        checks.append("I: an import closed mid-request was recorded and reported as not finished")

        # J. The same, but the model reached the store after the editor closed: recovery names it.
        product_panel(page)
        page.locator("[name='source_file']").set_input_files(str(model))
        gate.hold()
        with stored_put(page, lambda body: (body.get("importing") or {}).get("name") == "TEST-departure.glb"):
            page.get_by_role("button", name="Import GLB", exact=True).click()
        gate.wait_held(page)
        page.close()
        gate.release()
        assert sources() == []
        finished = context.request.post(url + "/api/packaging/sources?name=TEST-departure.glb&meters_per_unit=1", headers=HEADERS, data=glb)
        assert finished.ok, finished.text()
        page = editor()
        dialog = recovery(page, 'Revision 0, no design changes | an interrupted import of "TEST-departure.glb" finished')
        dialog.screenshot(path=str(output / "recover-import.png"))
        dialog.get_by_role("button", name="Restore 1", exact=True).click()
        expect(page.locator("#message")).to_contain_text('finished: choose it in Imported sources')
        checks.append("J: an import that finished after the editor closed was matched to its stored model")
        browser.close()
    return {"passed": not errors and not external, "page_errors": errors, "external_requests": external, "checks": checks,
            "prompts": prompts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-departure-ui-" + uuid4().hex[:10]))
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        parser.error("Output must stay in this worktree's .runtime directory")
    output.mkdir(parents=True, exist_ok=False)
    storage = Path(tempfile.mkdtemp(prefix="pk-departure-ui-"))
    gate = ImportGate()
    url, server, thread, service, principal = start(storage, gate)
    try:
        result = verify(url, output, service, principal, gate) | {"output": str(output)}
    finally:
        gate.release()
        server.should_exit = True
        thread.join(timeout=20)
        shutil.rmtree(storage, ignore_errors=True)
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    sys.exit(0 if result["passed"] else 1)
