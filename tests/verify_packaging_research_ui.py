"""Headless browser check of research evidence review in the Validation panel.

MOCK ONLY. Sage is NOT run and no research provider is contacted: scripted calls to the same gateway tools the
host gives Sage (search, read, record evidence) use the canned researcher from
tests/test_codex_packaging_research.py, which replays fixed raw provider replies about TEST pages on
example.com through the real normalizers. The pilot uses a throwaway store in the system temp directory and
every browser request to another host is aborted and recorded. This says nothing about a live research turn.

    python tests/verify_packaging_research_ui.py [--output .runtime/<new folder>]
"""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
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
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_codex_packaging_research import CARTONS, DATASHEET, TITLES, Researcher  # noqa: E402
from tests.verify_packaging_comparison_ui import HEADERS, designs  # noqa: E402


def start_pilot(storage):
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from ai_inspector.facility_layout.authorization import local_facility_principal
    from ai_inspector.packaging_shipping.admission import PackagingAdmission
    from ai_inspector.packaging_shipping.api import create_router
    from ai_inspector.packaging_shipping.service import PackagingService

    service = PackagingService(storage)
    principal = local_facility_principal(site_id="packaging-pilot")
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda request: principal, static_root=ROOT / "static",
                                     admission=PackagingAdmission(service), sage_enabled=lambda: True))
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
            raise RuntimeError("The mock pilot did not start.")
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server, thread, service, principal


def scripted_sage_research(service, principal, doc, researcher):
    """The calls a Sage research turn would make, run through the same gateway; not a live model or provider."""
    from ai_inspector.codex_runtime import packaging_tools as tools, research_tools
    context = tools.PackagingContext(principal, "session-ui", "conversation-ui", "selection-ui", doc, 0,
                                     "packaging_shipping", False, False)
    gateway = tools.create_packaging_gateway(service, current_context=lambda: context, turn_id="turn-ui",
                                             research=researcher, max_calls=8)

    async def turn():
        found = await gateway.call(research_tools.SEARCH, {"query": "cast acrylic sheet density and carton sizes"})
        sheet = await gateway.call(research_tools.READ, {"researchId": found["data"]["researchId"], "sourceIndex": 0,
                                                         "question": "What density does this datasheet state?"})
        boxes = await gateway.call(research_tools.READ, {"researchId": found["data"]["researchId"], "sourceIndex": 1,
                                                         "question": "Which carton size and SKU does this list?"})
        recorded = await gateway.call("record_packaging_evidence", {"expected_revision": 0, "items": [
            {"kind": "material_density", "research_id": sheet["data"]["researchId"], "subject": "Cast acrylic (PMMA) sheet",
             "claim": "Density (ASTM D792): 1.19 g/cm3", "value": 1.19, "unit": "g/cm3", "confidence": "high"},
            {"kind": "carton_sku", "research_id": boxes["data"]["researchId"], "subject": "RSC carton 12 x 10 x 8 in",
             "claim": "RSC carton 12 x 10 x 8 in, 32 ECT, SKU S-4127", "value": 12, "unit": "in",
             "sku_or_grade": "S-4127", "confidence": "medium"}]})
        return [found, sheet, boxes, recorded], gateway.receipts

    with ThreadPoolExecutor(1) as pool:  # Playwright's sync API owns this thread's event loop.
        return pool.submit(lambda: asyncio.run(turn())).result(timeout=90)


def verify(url, output, service, principal):
    errors, external, checks, reviews = [], [], [], []
    two_boxes, _ = designs()
    researcher = Researcher("anthropic")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda r: reviews.append((r.method, json.loads(r.post_data) if r.post_data else None))
                if "/evidence/" in r.url and r.method in {"PUT", "DELETE"} else None)

        def local_only(route):
            if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
                external.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", local_only)
        created = context.request.post(url + "/api/packaging/documents?contents_confirmed=true", data=two_boxes, headers=HEADERS)
        assert created.ok, created.text()
        doc = created.json()
        checks.append("seeded a two-carton TEST document through the API")

        results, receipts = scripted_sage_research(service, principal, doc["id"], researcher)
        assert all(r["ok"] for r in results), results
        recorded = results[-1]["data"]
        assert len(recorded["recorded"]) == 2 and recorded["refused"] == [], recorded
        assert [r["url"] for r in researcher.requests] == [None, DATASHEET, CARTONS]
        assert [row.get("external", {}).get("kind") for row in receipts] == ["public_research"] * 3 + [None]
        checks.append("scripted gateway search/read/record calls (standing in for Sage, canned researcher) recorded 2 evidence items")

        evidence = page.locator("#research-evidence")
        try:
            page.goto(url + "/packaging", wait_until="networkidle")
            page.get_by_role("button", name="Open", exact=True).click()
            page.locator(".document-row").filter(has_text=two_boxes["name"]).get_by_role("button", name="Open", exact=True).click()
            expect(page.locator("#document-name")).to_have_value(two_boxes["name"])
            command = page.locator("#command-validation")
            if command.get_attribute("aria-expanded") != "true":
                command.click()
            expect(evidence).to_contain_text("Research evidence (2)")
            expect(evidence).to_contain_text("unreviewed until you accept it")
            expect(evidence).to_contain_text("1. Material density: Cast acrylic (PMMA) sheet")
            expect(evidence).to_contain_text("Quoted from the page | Value 1.19 g/cm3 | Sage confidence: high | Unreviewed")
            expect(evidence).to_contain_text("2. Carton SKU: RSC carton 12 x 10 x 8 in")
            expect(evidence).to_contain_text("Value 12 in | SKU/grade S-4127 | Sage confidence: medium | Unreviewed")
            link = evidence.get_by_role("link", name=TITLES[DATASHEET], exact=True)
            assert (link.get_attribute("href"), link.get_attribute("target"), link.get_attribute("rel")) == (
                DATASHEET, "_blank", "noopener noreferrer")
            page.screenshot(path=str(output / "research-evidence.png"), full_page=True)
            checks.append("the Validation panel lists both records with basis, value, unit, SKU, confidence, review state and a new-tab source link")

            evidence.get_by_role("button", name="Accept evidence 1", exact=True).click()
            expect(page.locator("#message")).to_contain_text("Accepted evidence: Cast acrylic (PMMA) sheet. The design was not changed.")
            expect(evidence).to_contain_text("Sage confidence: high | Accepted by you")
            evidence.get_by_role("button", name="Reject evidence 2", exact=True).click()
            expect(page.locator("#message")).to_contain_text("Rejected evidence: RSC carton 12 x 10 x 8 in. The design was not changed.")
            expect(evidence).to_contain_text("Sage confidence: medium | Rejected by you")
            evidence.get_by_role("button", name="Mark evidence 1 unreviewed", exact=True).click()
            expect(page.locator("#message")).to_contain_text("Evidence marked unreviewed: Cast acrylic (PMMA) sheet.")
            expect(evidence).to_contain_text("Sage confidence: high | Unreviewed")
            checks.append("Accept, Reject and Mark unreviewed saved each review state")

            page.once("dialog", lambda dialog: dialog.accept())
            evidence.get_by_role("button", name="Remove evidence 2", exact=True).click()
            expect(page.locator("#message")).to_contain_text("Removed research evidence: RSC carton 12 x 10 x 8 in.")
            expect(evidence).to_contain_text("Research evidence (1)")
            expect(evidence).not_to_contain_text("S-4127")
            page.screenshot(path=str(output / "after-review.png"), full_page=True)
            checks.append("Remove (after the confirmation) deleted the rejected record")
        finally:
            context.close()
            browser.close()
    assert [method for method, _ in reviews] == ["PUT", "PUT", "PUT", "DELETE"], reviews
    assert [body["status"] for method, body in reviews if method == "PUT"] == ["accepted", "rejected", "unreviewed"]
    saved = service.get(tools_scope(principal), doc["id"])
    assert saved["revision"] == 0 and saved["design"] == doc["design"], saved["revision"]
    left = service.evidence(tools_scope(principal), doc["id"])
    assert [(r["subject"], r["review_status"]) for r in left] == [("Cast acrylic (PMMA) sheet", "unreviewed")], left
    checks.append("the document stayed at revision 0 with an unchanged design; one unreviewed record remains")
    return {"passed": not errors and not external, "page_errors": errors, "external_requests": external,
            "research_provider_requests": len(researcher.requests), "research_provider": "canned stand-in (no network)",
            "checks": checks}


def tools_scope(principal):
    from ai_inspector.codex_runtime.packaging_tools import packaging_scope
    return packaging_scope(principal)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-research-ui-" + uuid4().hex[:10]))
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        parser.error("Output must stay in this worktree's .runtime directory")
    output.mkdir(parents=True, exist_ok=False)
    # The research session's policy gates, for this process only; the researcher is a canned local stand-in.
    os.environ.update({"INSPECTORPRO_CODEX_WEB_RESEARCH": "1", "INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE": "1"})
    os.environ.pop("INSPECTORPRO_CODEX_AUTH_MODE", None)
    storage = Path(tempfile.mkdtemp(prefix="pk-research-ui-"))
    url, server, thread, service, principal = start_pilot(storage)
    try:
        result = verify(url, output, service, principal) | {"output": str(output)}
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        shutil.rmtree(storage, ignore_errors=True)
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    sys.exit(0 if result["passed"] else 1)
