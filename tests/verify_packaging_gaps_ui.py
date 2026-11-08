"""Headless browser check of the packaging gap controls: key mode, added product masses, a weighed packed
carton, the contents basis, the movement requirement and results, quote provenance and blocked quoting.

MOCK ONLY. The pilot runs in-process with a throwaway store in the system temp directory, a carrier-account
store under that folder protected by a throwaway Fernet key (not DPAPI and never the desktop's account store),
and an httpx.MockTransport in place of EasyPost; every browser request to another host is aborted and
recorded. The saved TEST key is a made-up string. Synthetic TEST designs and addresses. Passing this says
nothing about live carrier prices, the desktop app or a real EasyPost key.

    python tests/verify_packaging_gaps_ui.py [--output .runtime/<new folder>]
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

import httpx
from playwright.sync_api import expect, sync_playwright
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.verify_packaging_comparison_ui import ADDRESS, HEADERS, priced  # noqa: E402

TEST_KEY = "EZTK_TEST_ONLY_BROWSER_CHECK_NOT_A_CREDENTIAL"
SCENARIO = {"origin": ADDRESS, "destinations": [{**ADDRESS, "city": "Evanston", "zip": "60602", "residential": True}]}


def pad(pid, position, dimensions):
    return {"id": pid, "name": f"TEST {pid}", "position_m": position, "dimensions_m": dimensions,
            "density_kg_m3": 30.0, "material_evidence": "TEST density"}


def design():
    """One 100 x 80 x 40 mm TEST product in a 20 mm lining, except 5 mm of open space on its +X side."""
    lining = [pad("floor", [0, 0, 0], [0.14, 0.02, 0.08]), pad("top", [0, 0.10, 0], [0.14, 0.02, 0.08]),
              pad("x-min", [0, 0.02, 0], [0.02, 0.08, 0.08]), pad("x-max", [0.125, 0.02, 0], [0.015, 0.08, 0.08]),
              pad("z-min", [0.02, 0.02, 0], [0.10, 0.08, 0.02]), pad("z-max", [0.02, 0.02, 0.06], [0.10, 0.08, 0.02])]
    return {"name": "TEST gap controls " + uuid4().hex[:8], "quantity": 1,
            "product": {"name": "TEST product", "dimensions_m": [0.1, 0.08, 0.04], "mass_kg": 0.5,
                        "mass_basis": "user_measured", "mass_evidence": "TEST scale"},
            "constraints": {"contents": "ordinary_nonhazardous", "clearance_m": 0.0, "gap_m": 0.0},
            "packages": [{"id": "box", "carton": {"name": "TEST carton", "inner_m": [0.14, 0.12, 0.08],
                                                   "outer_m": [0.15, 0.13, 0.09], "tare_kg": 0.1,
                                                   "tare_evidence": "TEST scale", "max_payload_kg": 5.0},
                          "placements": [{"id": "item", "position_m": [0.02, 0.02, 0.02]}], "inserts": lining,
                          "allowance_kg": 0.01, "allowance_evidence": "TEST tape"}]}


def start_pilot(storage, calls, replies):
    from cryptography.fernet import Fernet
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from ai_inspector.facility_layout.authorization import local_facility_principal
    from ai_inspector.packaging_shipping import rating as rating_module
    from ai_inspector.packaging_shipping.api import create_router
    from ai_inspector.packaging_shipping.credentials import EasyPostCredentialStore
    from ai_inspector.packaging_shipping.service import PackagingService

    def handle(request):
        calls.append(json.loads(request.content)["shipment"])
        body = priced(request).json()
        body["mode"] = replies["mode"]
        for rate in body["rates"]:
            rate["mode"] = replies["mode"]
        return httpx.Response(200, json=body)

    # The store-backed desk builds a provider per request; every one in this process gets the mock transport.
    real = rating_module.EasyPostRating.__init__

    def mocked(self, *args, **kwargs):
        real(self, *args, **{**kwargs, "transport": httpx.MockTransport(handle)})
    rating_module.EasyPostRating.__init__ = mocked

    cipher = Fernet(Fernet.generate_key())
    store = EasyPostCredentialStore(storage / "carrier-credentials", "tenant-test/profile-test/user-test", enabled=True,
                                    protect=lambda raw, entropy: cipher.encrypt(entropy + b"\x00" + raw),
                                    unprotect=lambda raw, entropy: cipher.decrypt(raw)[len(entropy) + 1:])
    store.replace(TEST_KEY, account_alias="TEST account")  # Saved with no mode recorded.
    service = PackagingService(storage / "packaging")
    principal = local_facility_principal(site_id="packaging-pilot")
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda request: principal, static_root=ROOT / "static",
                                     credential_factory=lambda resolved: store))
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
    return f"http://127.0.0.1:{port}", server, thread, store


def verify(url, output, calls, replies, store):
    errors, external, checks, dialogs, answers = [], [], [], [], []
    seeded = design()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on("pageerror", lambda error: errors.append(str(error)))

        def on_dialog(dialog):  # Accepts unless the next queued answer is False.
            dialogs.append(dialog.message)
            (dialog.dismiss if answers and answers.pop(0) is False else dialog.accept)()
        page.on("dialog", on_dialog)

        def local_only(route):
            if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
                external.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", local_only)
        api = context.request
        # Seeded as the user would declare them, so the classified contents carry the user's confirmation.
        created = api.post(url + "/api/packaging/documents?contents_confirmed=true", data=seeded, headers=HEADERS)
        assert created.ok, created.text()
        base = f"{url}/api/packaging/documents/{created.json()['id']}"
        checks.append("seeded one TEST document through the API; the TEST key is saved with no mode recorded")

        resource = page.locator("#resource-dialog")
        message = page.locator("#message")
        save = page.get_by_role("button", name="Save", exact=True)

        def panel(name):
            command = page.locator(f"#command-{name}")
            if command.get_attribute("aria-expanded") != "true":
                command.click()

        def open_document():
            page.goto(url + "/packaging", wait_until="networkidle")
            if page.locator("#resource-dialog[open]").count():  # A recovery offer, if a checkpoint is still stored.
                resource.get_by_role("button", name="Close dialog", exact=True).click()
            page.get_by_role("button", name="Open", exact=True).click()
            page.locator(".document-row").filter(has_text=seeded["name"]).get_by_role("button", name="Open", exact=True).click()
            expect(page.locator("#document-name")).to_have_value(seeded["name"])

        def saved_as(revision):
            # One press on Save straight after typing: the first click must not be swallowed.
            save.click()
            expect(message).to_contain_text(f"Saved revision {revision}.")
            page.wait_for_load_state("networkidle")

        def quote_api(revision, refresh=False):
            return api.post(base + "/quotes", data={**SCENARIO, "expected_revision": revision, "refresh": refresh}, headers=HEADERS)

        def refused(response, status, code):
            assert response.status == status and response.json()["error"]["code"] == code, (response.status, response.text())

        def record_mode(mode):
            panel("rates")
            page.get_by_role("button", name="Carrier account", exact=True).click()
            choice = resource.locator('[name="carrier_mode"]')
            expect(choice).to_have_value("")  # Never pre-filled from an earlier record.
            choice.select_option(mode)
            with page.expect_request(lambda r: r.method == "PUT" and r.url.endswith("/api/packaging/account/mode")) as sent:
                resource.get_by_role("button", name="Record key mode", exact=True).click()
            assert json.loads(sent.value.post_data) == {"mode": mode}, sent.value.post_data
            expect(message).to_contain_text(f"Key recorded as a {mode} key. Nothing was sent to EasyPost.")

        try:
            # 1. A saved key with no recorded mode: nothing can be quoted, and the alias decides nothing.
            open_document()
            panel("rates")
            expect(page.locator("#account-mode")).to_contain_text("Key mode not recorded")
            expect(page.locator("#account-mode")).to_contain_text("the account alias is only a label")
            expect(page.locator("#quote-block-reason")).to_contain_text("Record whether the saved key is a test or production key")
            expect(page.locator("#quote-button")).to_be_disabled()
            refused(quote_api(0), 409, "account_mode_unconfirmed")
            page.screenshot(path=str(output / "1-no-key-mode.png"))
            assert calls == [], calls
            checks.append("no recorded key mode: the Rates panel says why, Compare rates is disabled and the API refuses with no provider request")

            # 2. Test-assumption contents on a key recorded as production are unavailable.
            panel("product")
            page.locator('[name="contents_basis"]').select_option("test_assumption")
            page.locator('[name="contents_evidence"]').fill("TEST synthetic connection-test parcel; not a real product")
            answers.append(False)  # Cancel the confirmation first: nothing is saved.
            save.click()
            expect(message).to_contain_text("Not saved: the contents change was not confirmed.")
            assert api.get(base, headers=HEADERS).json()["revision"] == 0
            assert "sets the contents to Ordinary, non-hazardous, test assumption" in dialogs[-1], dialogs[-1]
            assert "Confirm this contents classification as your own?" in dialogs[-1], dialogs[-1]
            saved_as(1)
            assert len(dialogs) == 2 and "Only you can classify the contents" in dialogs[-1], dialogs
            record_mode("production")
            expect(page.locator("#account-mode")).to_contain_text("Recorded as a production key, from your check.")
            expect(page.locator("#quote-block-reason")).to_contain_text("contents are a test assumption, so it can be quoted only with a key recorded as a test key")
            expect(page.locator("#quote-button")).to_be_disabled()
            refused(quote_api(1), 409, "test_assumption_needs_test_key")
            assert calls == [], calls
            checks.append("test-assumption contents with the key recorded as production: blocked in the panel and refused by the API before any request")

            # 3. Recorded as a test key, the same synthetic design may be quoted.
            record_mode("test")
            expect(page.locator("#account-mode")).to_contain_text("Recorded as a test key, from your check. EasyPost has not answered with this key yet.")
            expect(page.locator("#quote-block-reason")).to_be_hidden()
            checks.append("contents confirmation: a contents change asked first, naming the change; Cancel saved nothing, OK saved it")
            checks.append("mode selection: the dialog starts unrecorded each time and PUT /account/mode carried exactly the chosen mode")

            # 4. Added masses, a movement requirement and a weighed carton; then save and reopen.
            panel("product")
            add = page.get_by_role("button", name="Add mass item", exact=True)
            rows = page.locator("#added-mass-rows fieldset")
            add.click()
            rows.nth(0).locator('[name$="_name"]').fill("TEST magnets")
            add.click()
            rows.nth(1).locator('[name$="_name"]').fill("TEST adhesive")
            rows.nth(1).locator('select[name$="_basis"]').select_option("estimate")
            rows.nth(1).locator('[name$="_mass"]').fill("0.004")
            rows.nth(1).locator('[name$="_evidence"]').fill("TEST bead length x density")
            page.locator('[name="restraint_max"]').fill("6")
            page.locator('[name="restraint_evidence"]').fill("TEST requirement for the browser check")
            saved_as(2)
            panel("validation")
            validation = page.locator("#validation-panel")
            expect(validation).to_contain_text("Product mass leaves out 1 item(s) of unknown mass: TEST magnets")
            movement = page.locator("#movement-results")
            expect(movement).to_contain_text("Rotation, foam compression and shipping protection remain unverified")
            expect(movement.locator("table")).to_have_count(1)
            expect(movement.locator("caption")).to_have_text("item")
            expect(movement.locator("tbody tr")).to_have_count(6)
            expect(movement.locator("tbody tr").nth(0)).to_have_text("-X0.0 mmpacking material")
            expect(movement.locator("tbody tr").nth(1)).to_have_text("+X5.0 mmpacking material")
            page.screenshot(path=str(output / "4-movement-results.png"))
            panel("carton")
            page.locator('[name="measured_gross"]').fill("0.75")
            page.locator('[name="measured_gross_evidence"]').fill("TEST bench scale reading")
            saved_as(3)
            panel("validation")
            expect(validation).to_contain_text("Weighed packed carton")
            expect(validation).to_contain_text("Component estimate")
            checks.append("two added masses (one unknown, left out and listed), a 6 mm movement requirement and a weighed carton saved; "
                          "the movement table shows 5.0 mm on +X with the bounding-box notice")

            open_document()
            panel("product")
            expect(rows).to_have_count(2)
            expect(rows.nth(0).locator('[name$="_name"]')).to_have_value("TEST magnets")
            expect(rows.nth(0).locator('[name$="_mass"]')).to_be_disabled()
            expect(rows.nth(1).locator('[name$="_mass"]')).to_have_value("0.004")
            expect(page.locator('[name="contents_basis"]')).to_have_value("test_assumption")
            expect(page.locator('[name="restraint_max"]')).to_have_value("6")
            page.get_by_role("button", name="Apply product", exact=True).click()
            expect(save).to_be_disabled()  # An unchanged Apply is not an edit.
            panel("carton")
            expect(page.locator('[name="measured_gross"]')).to_have_value("0.75")
            expect(page.locator('[name="measured_gross_evidence"]')).to_have_value("TEST bench scale reading")
            page.get_by_role("button", name="Apply carton", exact=True).click()
            expect(save).to_be_disabled()
            stored = api.get(base, headers=HEADERS).json()
            assert stored["revision"] == 3, stored["revision"]
            assert [(m["name"], m["mass_kg"], m["basis"]) for m in stored["design"]["product"]["additional_mass"]] == [
                ("TEST magnets", None, "unknown"), ("TEST adhesive", 0.004, "estimate")]
            assert stored["design"]["packages"][0]["measured_gross_kg"] == 0.75
            assert stored["design"]["constraints"]["restraint"] == {"max_travel_m": 0.006, "separate_products": True,
                                                                  "evidence": "TEST requirement for the browser check"}
            checks.append("save and reopen: every new field came back as saved, and unchanged Apply product / Apply carton left nothing to save")

            # 5. A quote records what it rests on.
            panel("rates")
            for prefix, address in (("origin", SCENARIO["origin"]), ("destination0", SCENARIO["destinations"][0])):
                for key in ("street1", "city", "state", "zip"):
                    page.locator(f'[name="{prefix}_{key}"]').fill(address[key])
            page.locator('[name="destination0_residential"]').check()
            with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/quotes")) as answered:
                page.locator("#quote-button").click()
            assert answered.value.ok, answered.value.text()
            provenance = page.locator("#quote-provenance")
            expect(provenance).to_contain_text("Weight basis: Weighed packed carton.")
            expect(provenance).to_contain_text("Contents at quote time: Ordinary, non-hazardous, test assumption")
            expect(provenance).to_contain_text("No contents or hazardous-materials information was sent to the carrier.")
            expect(provenance).to_contain_text("Key mode: recorded test; EasyPost answered test.")
            page.locator("#quote-results details summary").first.click()
            expect(page.locator("#quote-results")).to_contain_text("from the weighed packed carton; component estimate")
            expect(page.locator("#account-mode")).to_contain_text("EasyPost last answered in test mode.")
            assert len(calls) == 1 and set(calls[0]) == {"from_address", "to_address", "parcel"}, calls
            page.screenshot(path=str(output / "5-quote-provenance.png"))
            checks.append("one mock quote: the panel shows its weight basis (weighed), the contents at quote time and the key mode; "
                          "the shipment carried addresses and the parcel only")

            # 6. Magnetized contents: quoting is blocked, and the API refuses before any request.
            panel("product")
            page.locator('[name="contents"]').select_option("magnetized_material")
            page.locator('[name="contents_basis"]').select_option("product_declaration")
            page.locator('[name="contents_evidence"]').fill("TEST declaration for the browser check")
            saved_as(4)
            panel("rates")
            expect(page.locator("#quote-block-reason")).to_contain_text("Quotes are blocked: Magnetized material is not supported for rating")
            expect(page.locator("#quote-button")).to_be_disabled()
            refused(quote_api(4), 422, "package_not_rate_ready")
            assert len(calls) == 1, calls
            page.screenshot(path=str(output / "6-magnetized-blocked.png"))
            confirmations = [d for d in dialogs if "Only you can classify the contents" in d]
            assert len(confirmations) == 3 and "sets the contents to Magnetized material" in confirmations[-1], confirmations
            checks.append("magnetized contents: the Rates panel names the reason, Compare rates is disabled and the API refused with no request")

            # 7. A reply in the other mode: that request was already sent; nothing after it, and no retry.
            panel("product")
            page.locator('[name="contents"]').select_option("ordinary_nonhazardous")
            saved_as(5)
            assert "sets the contents to Ordinary, non-hazardous, declaration about the real product" in dialogs[-1], dialogs[-1]
            replies["mode"] = "production"
            panel("rates")
            with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/quotes")) as answered:
                page.locator("#quote-button").click()
            assert answered.value.status == 409 and answered.value.json()["error"]["code"] == "account_mode_mismatch"
            expect(message).to_contain_text("already sent and created one provider shipment")
            expect(page.locator("#account-mode")).to_contain_text("but EasyPost last answered in production mode")
            expect(page.locator("#quote-block-reason")).to_contain_text("EasyPost last answered in production mode")
            expect(page.locator("#quote-button")).to_be_disabled()
            expect(page.locator("#quote-refresh-button")).to_be_disabled()
            page.wait_for_timeout(1500)  # Any automatic retry would have been sent by now.
            assert len(calls) == 2, calls
            refused(quote_api(5, refresh=True), 409, "account_mode_mismatch")
            record_mode("test")  # Recording the same mode again does not clear what EasyPost reported.
            expect(page.locator("#account-mode")).to_contain_text("but EasyPost last answered in production mode")
            refused(quote_api(5), 409, "account_mode_mismatch")
            assert len(calls) == 2, calls
            assert store.status()["mode_mismatch"] is True
            attempts = api.get(base + "/quote-attempts", headers=HEADERS).json()
            assert attempts["attempt_count"] == 2 and attempts["total_shipments_created"] == 2, attempts
            page.screenshot(path=str(output / "7-mode-mismatch.png"))
            checks.append("a production reply to a key recorded as test: the one request was sent (2 mock shipments in total), "
                          "then the panel, a refresh and a re-recorded mode were all refused with no further request")
        finally:
            context.close()
            browser.close()
    return {"passed": not errors and not external, "page_errors": errors, "external_requests": external,
            "provider_requests": len(calls), "dialogs": dialogs, "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-gaps-ui-" + uuid4().hex[:10]))
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        parser.error("Output must stay in this worktree's .runtime directory")
    output.mkdir(parents=True, exist_ok=False)
    storage = Path(tempfile.mkdtemp(prefix="pk-gaps-ui-"))
    calls, replies = [], {"mode": "test"}
    url, server, thread, store = start_pilot(storage, calls, replies)
    try:
        result = verify(url, output, calls, replies, store) | {"output": str(output)}
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        shutil.rmtree(storage, ignore_errors=True)
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    sys.exit(0 if result["passed"] else 1)
