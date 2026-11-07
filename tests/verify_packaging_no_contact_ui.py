"""Headless browser check of the No-contact regions dialog, its validation finding, and a no-op Apply.

Runs the in-process pilot from verify_packaging_comparison_ui (mock carrier transport, throwaway
store in the system temp directory). No rate is requested here; every browser request to another
host is aborted and recorded. Synthetic TEST data only.

    python tests/verify_packaging_no_contact_ui.py [--output .runtime/<new folder>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_packaging_comparison_ui import CARTON, HEADERS, PRODUCT, start_pilot  # noqa: E402


def verify(url, output):
    errors, external, checks = [], [], []
    name = "TEST no-contact UI " + uuid4().hex[:8]
    design = {"name": name, "quantity": 1, "product": PRODUCT, "constraints": {"contents": "ordinary_nonhazardous"},
              "packages": [{"id": "box_0", "carton": CARTON, "allowance_kg": 0.05, "allowance_evidence": "TEST tape",
                            "placements": [{"id": "item_0", "position_m": [0.02, 0.02, 0.02]}]}]}
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
        created = context.request.post(url + "/api/packaging/documents", data=design, headers=HEADERS)
        assert created.ok, created.text()
        doc_url = f"{url}/api/packaging/documents/{created.json()['id']}"

        def panel(command):
            node = page.locator(f"#command-{command}")
            if node.get_attribute("aria-expanded") != "true":
                node.click()

        def save(revision):
            with page.expect_response(lambda r: r.request.method == "PUT" and r.url.split("?")[0] == doc_url) as response:
                page.get_by_role("button", name="Save", exact=True).click()
            assert response.value.ok, response.value.text()
            expect(page.locator("#document-status")).to_have_text(f"Revision {revision} | Saved")

        dialog = page.locator("#resource-dialog")
        status = page.locator("#document-status")
        try:
            page.goto(url + "/packaging", wait_until="networkidle")
            page.get_by_role("button", name="Open", exact=True).click()
            page.locator(".document-row").filter(has_text=name).get_by_role("button", name="Open", exact=True).click()
            expect(status).to_have_text("Revision 0 | Saved")

            panel("product")
            page.get_by_role("button", name="Apply product", exact=True).click()
            expect(page.locator("#message")).to_contain_text("Changes applied to draft.")
            expect(status).to_have_text("Revision 0 | Saved")
            checks.append("an unchanged Apply product leaves the saved document clean")

            page.get_by_role("button", name="Edit no-contact regions", exact=True).click()
            expect(dialog).to_contain_text("No regions set.")
            dialog.locator('[name="region_name"]').fill("TEST lens")
            dialog.locator('[name="region_evidence"]').fill("TEST polished face")
            dialog.get_by_role("button", name="Add region", exact=True).click()
            expect(dialog).to_contain_text("TEST lens: Y max face (top when upright), whole face, air gap 5 mm")
            dialog.locator('[name="region_name"]').fill("TEST sensor")
            dialog.locator('[name="region_face"]').select_option("z_max")
            expect(dialog).to_contain_text("first axis X, second axis Y")
            dialog.locator('[name="region_gap"]').fill("70")
            for key, value in (("u0", "0"), ("u1", "50"), ("v0", "0"), ("v1", "40")):
                dialog.locator(f'[name="region_{key}"]').fill(value)
            dialog.locator('[name="region_evidence"]').fill("TEST sensor window")
            dialog.get_by_role("button", name="Add region", exact=True).click()
            expect(dialog).to_contain_text("TEST sensor: Z max face, X 0-50 mm, Y 0-40 mm, air gap 70 mm")
            expect(page.locator("#message")).to_contain_text("No-contact region added to the draft.")
            page.screenshot(path=str(output / "no-contact-dialog.png"))
            dialog.get_by_role("button", name="Close dialog", exact=True).click()
            expect(page.locator("#editor")).to_contain_text("TEST sensor: Z max face")
            expect(status).to_have_text("Revision 0 | Unsaved changes")
            checks.append("two regions added through the dialog, one partial, shown in the Product panel")

            save(1)
            panel("validation")
            findings = page.locator("#validation-panel")
            expect(findings).to_contain_text("air gap of no-contact region TEST sensor")
            expect(findings).not_to_contain_text("no-contact region TEST lens")
            page.screenshot(path=str(output / "no-contact-finding.png"))
            checks.append("saved revision 1 reports the carton wall inside the sensor's 70 mm gap, not the lens")

            panel("product")
            page.get_by_role("button", name="Edit no-contact regions", exact=True).click()
            dialog.get_by_role("button", name="Remove TEST sensor", exact=True).click()
            expect(dialog).not_to_contain_text("TEST sensor")
            dialog.get_by_role("button", name="Close dialog", exact=True).click()
            save(2)
            panel("validation")
            expect(page.locator("#validation-panel")).not_to_contain_text("no-contact region")
            saved = context.request.get(doc_url, headers=HEADERS).json()["design"]["constraints"]
            assert [r["name"] for r in saved["no_contact"]] == ["TEST lens"], saved
            assert "cushion" not in saved and "package_allowance" not in saved, saved
            checks.append("removing the sensor region cleared the finding; the server keeps only the lens region")
        finally:
            context.close()
            browser.close()
    return {"passed": not errors and not external, "page_errors": errors, "external_requests": external, "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-no-contact-ui-" + uuid4().hex[:10]))
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        parser.error("Output must stay in this worktree's .runtime directory")
    output.mkdir(parents=True, exist_ok=False)
    storage = Path(tempfile.mkdtemp(prefix="pk-no-contact-ui-"))
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
