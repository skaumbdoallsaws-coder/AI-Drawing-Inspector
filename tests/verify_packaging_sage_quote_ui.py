"""Headless browser check of the Rates panel's Sage quoting control.

MOCK ONLY. The pilot runs in-process with an httpx.MockTransport priced by a fixed weight formula and
a throwaway store in the system temp directory; every browser request to another host is aborted and
recorded. Synthetic TEST designs and addresses. Sage itself is NOT run: a scripted call to the same
gateway tool the host gives Sage stands in for it, so this says nothing about a live Sage turn or live
carrier prices.

    python tests/verify_packaging_sage_quote_ui.py [--output .runtime/<new folder>]
"""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
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

import httpx
from playwright.sync_api import expect, sync_playwright
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.verify_packaging_comparison_ui import ADDRESS, HEADERS, designs, priced  # noqa: E402

PRIVATE = ("1 Test Street", "TEST ONLY", "60601", "60605")


def start_pilot(storage, calls):
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from ai_inspector.facility_layout.authorization import local_facility_principal
    from ai_inspector.packaging_shipping.admission import PackagingAdmission
    from ai_inspector.packaging_shipping.api import create_router
    from ai_inspector.packaging_shipping.quoting import QuoteDesk
    from ai_inspector.packaging_shipping.rating import EasyPostRating
    from ai_inspector.packaging_shipping.service import PackagingService

    def handle(request):
        calls.append(json.loads(request.content)["shipment"])
        return priced(request)

    service = PackagingService(storage)
    desk = QuoteDesk(service, rating=EasyPostRating(key="EZTK_TEST_ONLY_BROWSER_CHECK", transport=httpx.MockTransport(handle),
                                                declared_mode="test"))
    principal = local_facility_principal(site_id="packaging-pilot")
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda request: principal, static_root=ROOT / "static",
                                     admission=PackagingAdmission(service), sage_enabled=lambda: True, quotes=desk))
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
    return f"http://127.0.0.1:{port}", server, thread, service, desk, principal


def scripted_sage_quote(service, desk, principal, doc, design_hash, scenario_id):
    """The quote_packaging call a Sage turn would make, run through the same gateway; not a live model."""
    from ai_inspector.codex_runtime import packaging_tools as tools
    context = tools.PackagingContext(principal, "session-ui", "conversation-ui", "selection-ui", doc, 0,
                                     "packaging_shipping", False, False)
    gateway = tools.create_packaging_gateway(service, current_context=lambda: context, turn_id="turn-ui", quotes=desk)
    arguments = {"expected_revision": 0, "scenario_id": scenario_id, "expected_design_hash": design_hash}
    with ThreadPoolExecutor(1) as pool:  # Playwright's sync API owns this thread's event loop.
        return pool.submit(lambda: asyncio.run(gateway.call("quote_packaging", arguments))).result(timeout=90)


def verify(url, output, service, desk, principal, calls):
    errors, external, checks = [], [], []
    two_boxes, _ = designs()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on("pageerror", lambda error: errors.append(str(error)))

        def local_only(route):
            if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
                external.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", local_only)
        created = context.request.post(url + "/api/packaging/documents", data=two_boxes, headers=HEADERS)
        assert created.ok, created.text()
        doc = created.json()
        checks.append("seeded a two-carton TEST document through the API")

        dialog = page.locator("#resource-dialog")
        sage = page.locator("#sage-scenarios")
        try:
            page.goto(url + "/packaging", wait_until="networkidle")
            page.get_by_role("button", name="Open", exact=True).click()
            page.locator(".document-row").filter(has_text=two_boxes["name"]).get_by_role("button", name="Open", exact=True).click()
            expect(page.locator("#document-name")).to_have_value(two_boxes["name"])
            command = page.locator("#command-rates")
            if command.get_attribute("aria-expanded") != "true":
                command.click()
            expect(sage).to_contain_text("never names, streets or ZIP codes")
            for prefix, address in (("origin", ADDRESS), ("destination0", {**ADDRESS, "city": "Evanston", "zip": "60605"})):
                for key in ("street1", "city", "state", "zip"):
                    page.locator(f'[name="{prefix}_{key}"]').fill(address[key])
            page.locator('[name="destination0_residential"]').check()

            sage.get_by_role("button", name="Allow Sage to quote these addresses", exact=True).click()
            expect(dialog).to_contain_text("Origin: Chicago, IL")
            expect(dialog).to_contain_text("Destination 1: Evanston, IL (residential)")
            expect(dialog).to_contain_text("creates 2 provider shipment(s) for rating")
            body_text = dialog.inner_text()
            assert not any(value in body_text.split("Each new quote")[0] for value in PRIVATE), body_text
            dialog.locator('[name="sage_shipments"]').fill("3")
            dialog.locator('[name="sage_minutes"]').fill("30")
            page.screenshot(path=str(output / "allow-sage-dialog.png"))
            with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/scenarios")) as sent:
                with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/scenarios")) as answered:
                    dialog.get_by_role("button", name="Allow Sage", exact=True).click()
            posted, scenario = json.loads(sent.value.post_data), answered.value.json()
            assert posted["sage_shipments"] == 3 and posted["minutes"] == 30, posted
            assert posted["destinations"][0]["street1"] == "1 Test Street" and posted["destinations"][0]["residential"] is True
            assert "expected_revision" not in posted and "refresh" not in posted, posted
            assert not any(value in json.dumps(scenario) for value in PRIVATE), scenario
            expect(page.locator("#message")).to_contain_text(f"Sage may quote scenario {scenario['id']}: up to 3 provider shipment(s) for 30 min. Nothing was sent yet.")
            expect(sage).to_contain_text(f"{scenario['id']}: Chicago, IL to Evanston, IL (residential) | 3 of 3 provider shipment(s) left")
            assert calls == [], calls
            checks.append("Allow Sage posted the visible addresses with a 3-shipment, 30-minute budget; nothing reached the provider")

            result = scripted_sage_quote(service, desk, principal, doc["id"], doc["assessment"]["design_hash"], scenario["id"])
            assert result["ok"] and result["data"]["provider_shipments_created"] == 2 == len(calls), result
            assert not any(value in json.dumps(result) for value in PRIVATE), result
            assert {c["to_address"]["street1"] for c in calls} == {"1 Test Street"}
            sage.get_by_role("button", name="Refresh quotes and Sage scenarios", exact=True).click()
            expect(page.locator("#message")).to_contain_text("Saved quotes and Sage scenarios refreshed. No provider request was made.")
            expect(sage).to_contain_text("1 of 3 provider shipment(s) left")
            expect(page.locator("#quote-results")).to_contain_text("Evanston")
            page.screenshot(path=str(output / "after-scripted-sage-quote.png"))
            checks.append("a scripted gateway quote_packaging call (standing in for Sage) used 2 of the 3 shipments; the panel shows the saved quote")

            sage.get_by_role("button", name=f"Revoke {scenario['id']}", exact=True).click()
            expect(page.locator("#message")).to_contain_text(f"Sage can no longer quote scenario {scenario['id']}.")
            expect(sage).not_to_contain_text(scenario["id"])
            again = scripted_sage_quote(service, desk, principal, doc["id"], doc["assessment"]["design_hash"], scenario["id"])
            assert again["ok"] is False and again["error"]["code"] == "scenario_not_found" and len(calls) == 2, again
            checks.append("Revoke removed the scenario; a later scripted quote was refused with no provider request")
        finally:
            context.close()
            browser.close()
    return {"passed": not errors and not external, "page_errors": errors, "external_requests": external,
            "provider_requests": len(calls), "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-sage-quote-ui-" + uuid4().hex[:10]))
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        parser.error("Output must stay in this worktree's .runtime directory")
    output.mkdir(parents=True, exist_ok=False)
    storage = Path(tempfile.mkdtemp(prefix="pk-sage-quote-ui-"))
    calls = []
    url, server, thread, service, desk, principal = start_pilot(storage, calls)
    try:
        result = verify(url, output, service, desk, principal, calls) | {"output": str(output)}
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        shutil.rmtree(storage, ignore_errors=True)
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    sys.exit(0 if result["passed"] else 1)
