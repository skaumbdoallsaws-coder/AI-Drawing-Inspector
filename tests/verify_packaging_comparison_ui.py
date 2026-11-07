"""Headless browser check of saved-design quoting and the Compare costs dialog.

MOCK ONLY. The pilot runs in-process with an httpx.MockTransport priced by a fixed weight formula
and a throwaway store in the system temp directory; every browser request to another host is
aborted and recorded. Synthetic TEST designs and addresses. Passing this says nothing about live
carrier prices.

    python tests/verify_packaging_comparison_ui.py [--output .runtime/<new folder>]
"""
from __future__ import annotations

import argparse
from decimal import Decimal
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

HEADERS = {"X-InspectorPro-Request": "packaging"}
PRODUCT = {"name": "TEST product", "dimensions_m": [0.1, 0.08, 0.04], "mass_kg": 0.5,
           "mass_basis": "user_measured", "mass_evidence": "TEST scale"}
CARTON = {"name": "TEST carton", "inner_m": [0.17, 0.23, 0.12], "outer_m": [0.2032, 0.254, 0.1524], "tare_kg": 0.1,
          "tare_evidence": "TEST scale", "max_payload_kg": 5, "cost_usd": 1.5}
ADDRESS = {"name": "TEST ONLY", "street1": "1 Test Street", "city": "Chicago", "state": "IL", "zip": "60601", "residential": False}
SCENARIO = {"origin": ADDRESS, "destinations": [{**ADDRESS, "zip": "60602", "residential": True},
                                                {**ADDRESS, "zip": "60603", "residential": True}]}


def priced(request):
    body = json.loads(request.content)["shipment"]
    weight = Decimal(str(body["parcel"]["weight"]))
    amount = (Decimal("4.00") + Decimal("2.00") * weight / 16).quantize(Decimal("0.01"))
    base = {"currency": "USD", "carrier": "TEST Carrier", "carrier_account_id": "ca_TEST_A", "mode": "test"}
    rates = [{**base, "id": "rate_TEST_ground", "rate": str(amount), "service": "TEST Ground", "delivery_days": 3},
             {**base, "id": "rate_TEST_express", "rate": str(amount + 5), "service": "TEST Express", "delivery_days": 1}]
    return httpx.Response(200, json={"id": "shp_TEST", "mode": "test", "rates": rates})


def package(index, positions):
    return {"id": f"box_{index}", "carton": CARTON, "allowance_kg": 0.05, "allowance_evidence": "TEST tape",
            "placements": [{"id": f"item_{index}_{i}", "position_m": p} for i, p in enumerate(positions)]}


def designs():
    two = {"name": "TEST compare UI " + uuid4().hex[:8], "quantity": 2, "product": PRODUCT,
           "constraints": {"contents": "ordinary_nonhazardous"},
           "packages": [package(0, [[0.02, 0.02, 0.02]]), package(1, [[0.02, 0.02, 0.02]])]}
    return two, {**two, "packages": [package(0, [[0.02, 0.02, 0.02], [0.02, 0.12, 0.02]])]}


def start_pilot(storage):
    from ai_inspector.packaging_shipping.rating import EasyPostRating
    from tools.run_packaging_pilot import create_app
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    rating = EasyPostRating(key="EZTK_TEST_ONLY_BROWSER_CHECK", transport=httpx.MockTransport(priced))
    server = uvicorn.Server(uvicorn.Config(create_app(storage, rating=rating), host="127.0.0.1", port=port,
                                           access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("The mock pilot did not start.")
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server, thread


def verify(url, output):
    errors, external, checks = [], [], []
    two_boxes, one_box = designs()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())

        def local_only(route):
            if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
                external.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", local_only)
        api = context.request
        created = api.post(url + "/api/packaging/documents", data=two_boxes, headers=HEADERS)
        assert created.ok, created.text()
        doc = created.json()
        base = f"{url}/api/packaging/documents/{doc['id']}"
        alt = api.post(base + "/alternatives", data={"expected_revision": doc["revision"], "request_id": "req_ui_one_box",
                                                     "name": "TEST one box", "design": one_box}, headers=HEADERS)
        assert alt.ok, alt.text()
        alt = alt.json()
        for path in (base, f"{base}/alternatives/{alt['id']}"):
            quoted = api.post(path + "/quotes", data={**SCENARIO, "expected_revision": doc["revision"]}, headers=HEADERS)
            assert quoted.ok, quoted.text()
        checks.append("seeded a document, a saved design and two mock quotes through the API")

        def panel(name):
            command = page.locator(f"#command-{name}")
            if command.get_attribute("aria-expanded") != "true":
                command.click()

        dialog = page.locator("#resource-dialog")
        try:
            page.goto(url + "/packaging", wait_until="networkidle")
            page.get_by_role("button", name="Open", exact=True).click()
            page.locator(".document-row").filter(has_text=two_boxes["name"]).get_by_role("button", name="Open", exact=True).click()
            expect(page.locator("#document-name")).to_have_value(two_boxes["name"])

            panel("arrange")
            page.get_by_role("button", name="Saved designs", exact=True).click()
            expect(dialog).to_contain_text("Comparison baseline: current design")
            dialog.get_by_role("button", name="Set as baseline", exact=True).click()
            expect(dialog).to_contain_text("Comparison baseline: TEST one box")
            expect(dialog.get_by_role("button", name="Set as baseline", exact=True)).to_be_disabled()
            dialog.get_by_role("button", name="Use current design as baseline", exact=True).click()
            expect(dialog).to_contain_text("Comparison baseline: current design")
            checks.append("baseline switched to the saved design and back through PUT")

            dialog.get_by_role("button", name="Compare costs", exact=True).click()
            expect(dialog).to_contain_text("Reads saved quotes only. No provider request is made.")
            table = dialog.get_by_role("table", name="Design cost comparison")
            first = table.locator("tbody tr").nth(0).locator("td")
            expect(first.nth(0)).to_have_text("TEST one box")
            expect(first.nth(1)).to_have_text("Compared")
            expect(first.nth(7)).to_contain_text("(lower)")
            expect(table.locator("tbody tr").nth(1).locator("td").nth(1)).to_have_text("Baseline")
            expect(dialog).to_contain_text("No saving is claimed")
            expect(page.locator("#message")).to_contain_text("No provider request was made")
            ground = first.nth(4).inner_text()
            page.screenshot(path=str(output / "compare-costs.png"))
            service = dialog.locator('[name="comparison_service"]')
            service.select_option(index=1)
            expect(service).to_have_value('["TEST Carrier","TEST Express","ca_TEST_A","USD"]')
            expect(table.locator("tbody tr").nth(0).locator("td").nth(4)).not_to_have_text(ground)
            checks.append(f"table ranked the saved design first (ground {ground}) and re-read for the express service")
            dialog.get_by_role("button", name="Close dialog", exact=True).click()

            panel("rates")
            expect(page.locator("#rates-panel").get_by_role("button", name="Compare costs", exact=True)).to_be_visible()
            for prefix, address in (("origin", ADDRESS), ("destination0", {**ADDRESS, "zip": "60604"})):
                for key in ("street1", "city", "state", "zip"):
                    page.locator(f'[name="{prefix}_{key}"]').fill(address[key])
            panel("arrange")
            page.get_by_role("button", name="Saved designs", exact=True).click()
            target = f"/alternatives/{alt['id']}/quotes"
            with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith(target)) as response:
                dialog.get_by_role("button", name="Quote this design", exact=True).click()
            assert response.value.ok, response.value.text()
            expect(page.locator("#message")).to_contain_text("Carrier quote received for the saved design (1 provider shipment(s) created)")
            with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith(target)) as again:
                dialog.get_by_role("button", name="Quote this design", exact=True).click()
            assert again.value.json()["reused"] is True
            expect(page.locator("#message")).to_contain_text("No provider request was made")
            dialog.get_by_role("button", name="Compare costs", exact=True).click()
            expect(dialog.locator('[name="comparison_scenario"] option')).to_have_count(2)
            page.screenshot(path=str(output / "compare-costs-two-scenarios.png"))
            checks.append("Quote this design used the session scenario, then reused the identical quote; two scenarios listed")
        finally:
            context.close()
            browser.close()
    return {"passed": not errors and not external, "page_errors": errors, "external_requests": external, "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-comparison-ui-" + uuid4().hex[:10]))
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        parser.error("Output must stay in this worktree's .runtime directory")
    output.mkdir(parents=True, exist_ok=False)
    storage = Path(tempfile.mkdtemp(prefix="pk-compare-ui-"))
    url, server, thread = start_pilot(storage)
    try:
        result = verify(url, output) | {"output": str(output)}
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        shutil.rmtree(storage, ignore_errors=True)
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    sys.exit(0 if result["passed"] else 1)
