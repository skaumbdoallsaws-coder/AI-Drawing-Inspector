"""Headless browser check of the InspectorPro library dialog and the Storage dialog.

Self-contained: it starts its own packaging app from this worktree on a free local port, with a throwaway store and a
synthetic TEST library in the system temp directory, and aborts every browser request to another host. No running
pilot, desktop host, carrier, research or Sage request is involved.

    python tests/verify_packaging_library_storage_ui.py [--output .runtime/<new folder>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import socket
import sqlite3
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

HEADERS = {"X-InspectorPro-Request": "packaging"}


def model(extents):
    return trimesh.creation.box(extents=extents).export(file_type="glb")


def make_library(root):
    (root / "assemblies").mkdir(parents=True)
    record = {"fileName": "TEST-100.SLDPRT", "units": {"internalSystem": "SI (meters)"},
              "identity": {"partNumber": "TEST-100", "description": "TEST bracket", "revision": "A"},
              "physical": {"mass": 1.234, "boundingBox": {"length": 0.1, "width": 0.06, "height": 0.04}},
              "configurations": [{"name": "Default", "isActive": False}, {"name": "Long", "isActive": True}]}
    (root / "TEST-100.json").write_text(json.dumps(record))
    (root / "TEST-100_colored.glb").write_bytes(model([0.1, 0.06, 0.04]))
    (root / "assemblies" / "TEST-ASM_assembly.json").write_text(json.dumps(
        {"identity": {"assemblyNumber": "TEST-ASM", "description": "TEST pair", "revision": "B"}, "components": []}))
    (root / "assemblies" / "TEST-ASM_colored.glb").write_bytes(model([0.3, 0.1, 0.05]))


def start(storage, library):
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from ai_inspector.facility_layout.authorization import local_facility_principal
    from ai_inspector.packaging_shipping.api import create_router
    from ai_inspector.packaging_shipping.service import PackagingService
    from ai_inspector.packaging_shipping.sources import GlbRuntime

    service = PackagingService(storage)
    principal = local_facility_principal(site_id="packaging-pilot")
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda request: principal, static_root=ROOT / "static",
                                     source_runtime=GlbRuntime(Path(trimesh.__file__).resolve().parents[1]), library_root=library))
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
    return f"http://127.0.0.1:{port}", server, thread, service


def verify(url, output, service, library):
    errors, external, checks, prompts = [], [], [], []
    name = "TEST library UI " + uuid4().hex[:6]
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
        created = context.request.post(url + "/api/packaging/documents", headers=HEADERS, data={
            "name": name, "quantity": 1, "product": None, "packages": [],
            "constraints": {"clearance_m": 0.02, "gap_m": 0.01, "allowed_orientations": [0], "contents": "unconfirmed"}})
        assert created.ok, created.text()
        doc = created.json()
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: (prompts.append(dialog.message), dialog.accept()))
        page.goto(url + "/packaging", wait_until="networkidle")
        page.get_by_role("button", name="Open", exact=True).click()
        page.locator(".document-row").filter(has_text=name).get_by_role("button", name="Open", exact=True).click()
        expect(page.locator("#document-name")).to_have_value(name)
        if page.locator("#command-product").get_attribute("aria-expanded") != "true":
            page.locator("#command-product").click()  # The product panel holds the source buttons.
        expect(page.locator("#editor")).to_be_visible()
        dialog = page.locator("#resource-dialog")

        # A. Library: the part with its configurations; the inactive one cannot be chosen.
        page.get_by_role("button", name="InspectorPro library").click()
        part = dialog.locator(".document-row").filter(has_text="Part TEST-100 rev A - TEST bracket")
        expect(part).to_have_count(1)
        select = part.locator("select[name='library_configuration']")
        expect(select).to_have_value("Long")
        options = select.locator("option").evaluate_all("list => list.map(o => [o.value, o.textContent, o.disabled])")
        assert options == [["Default", "Default (not extracted)", True], ["Long", "Long (active at extraction)", False]], options
        dialog.locator("input[name='library_search']").fill("ASM")
        expect(dialog.locator(".document-row")).to_have_count(1)
        expect(dialog.locator(".document-row")).to_contain_text("Assembly TEST-ASM rev B - TEST pair")
        dialog.locator("input[name='library_search']").fill("")
        dialog.screenshot(path=str(output / "library-dialog.png"))
        checks.append("library lists the part, its configurations and the assembly; search filters")
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/api/packaging/sources/library")) as chosen:
            part.get_by_role("button", name="Use as product").click()
        meta = chosen.value.json()
        assert chosen.value.ok and meta["library"]["configuration"] == "Long", meta
        expect(page.locator("#message")).to_contain_text("Library model imported. Product mass is unknown.")
        expect(page.locator("[name='product_name']")).to_have_value("Part TEST-100 rev A - TEST bracket (Long)")
        expect(page.get_by_text("Imported source | dimensions locked")).to_be_visible()
        with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/packaging/documents/" + doc["id"])) as saved:
            page.get_by_role("button", name="Save", exact=True).click()
        assert saved.value.ok, saved.value.text()
        assert saved.value.json()["design"]["product"]["source_id"] == meta["id"]
        checks.append("choosing the active configuration imports a locked product and saves it")

        # B. Imported sources: the library provenance and its status check.
        page.get_by_role("button", name="Imported sources").click()
        row = dialog.locator(".document-row").filter(has_text=meta["id"])
        expect(row).to_contain_text("InspectorPro library part TEST-100 rev A, configuration Long")
        row.get_by_role("button", name="Check library").click()
        expect(page.locator("#message")).to_contain_text("The imported copy matches the library entry.")
        (library / "TEST-100_colored.glb").write_bytes(model([0.1, 0.06, 0.05]))
        row.get_by_role("button", name="Check library").click()
        expect(page.locator("#message")).to_contain_text("The library entry changed after import.")
        page.keyboard.press("Escape")
        checks.append("Imported sources shows library provenance and reports current, then changed")

        # C. Storage: usage, an unused upload removed after confirmation, the saved product kept.
        unused = context.request.post(url + "/api/packaging/sources?meters_per_unit=1&name=TEST%20spare", headers=HEADERS,
                                      data=model([0.05, 0.05, 0.05]))
        assert unused.ok, unused.text()
        spare = unused.json()["id"]
        with sqlite3.connect(service.path) as db:  # As if it had been imported yesterday (the one-hour guard).
            db.execute("UPDATE asset_imports SET imported = imported - 86400 WHERE id=?", (spare,))
        page.get_by_role("button", name="Storage", exact=True).click()
        expect(dialog).to_contain_text("Imported models: 2 of 100")
        expect(dialog).to_contain_text("Model: TEST spare")
        dialog.screenshot(path=str(output / "storage-dialog.png"))
        with page.expect_response(lambda r: r.url.endswith("/api/packaging/storage/remove-unused")) as removed:
            dialog.get_by_role("button", name="Remove 1 unused").click()
        assert removed.value.ok and [i["id"] for i in removed.value.json()["removed"]] == [spare], removed.value.text()
        expect(page.locator("#message")).to_contain_text("Removed 1 unused item(s)")
        expect(dialog).to_contain_text("Nothing unused to remove.")
        listed = {m["id"] for m in context.request.get(url + "/api/packaging/sources").json()["sources"]}
        assert listed == {meta["id"]}, listed
        assert any("Permanently remove 1 unused item(s)" in p for p in prompts), prompts
        checks.append("Remove unused asks first, removes only the unused upload and keeps the saved product")

        # D. Limits: a lower model limit refuses the next import and deletes nothing.
        dialog.locator("input[name='limit_sources']").fill("1")
        with page.expect_response(lambda r: r.url.endswith("/api/packaging/storage/limits")) as limited:
            dialog.get_by_role("button", name="Save limits").click()
        assert limited.value.ok and limited.value.json()["limits"]["sources"] == 1
        expect(page.locator("#message")).to_contain_text("Storage limits saved. Nothing was deleted.")
        refused = context.request.post(url + "/api/packaging/sources?meters_per_unit=1", headers=HEADERS, data=model([0.07, 0.05, 0.05]))
        assert refused.status == 409 and refused.json()["error"]["code"] == "source_storage_full", refused.text()
        assert {m["id"] for m in context.request.get(url + "/api/packaging/sources").json()["sources"]} == {meta["id"]}
        checks.append("a lower limit refuses the next import without deleting anything")
        browser.close()
    return {"passed": not errors and not external, "page_errors": errors, "external_requests": external, "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-library-storage-ui-" + uuid4().hex[:10]))
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        parser.error("Output must stay in this worktree's .runtime directory")
    output.mkdir(parents=True, exist_ok=False)
    temporary = Path(tempfile.mkdtemp(prefix="pk-library-ui-"))
    make_library(temporary / "library")
    url, server, thread, service = start(temporary / "store", temporary / "library")
    try:
        result = verify(url, output, service, temporary / "library") | {"output": str(output)}
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        shutil.rmtree(temporary, ignore_errors=True)
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    sys.exit(0 if result["passed"] else 1)
