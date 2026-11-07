"""Headless browser check of the sourced carton catalog in the editor.

Self-contained: it starts its own packaging app from this worktree on a free local port with a throwaway store in
the system temp directory, and aborts every browser request to another host. No running pilot or desktop host is
used, and no carrier, research or Sage request is made. The catalog values were read from the supplier pages on the
date in catalog.py; this check only shows that the editor lists and applies them.

    python tests/verify_packaging_catalog_ui.py [--output .runtime/<new folder>]
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
sys.path.insert(0, str(ROOT))

from tests.verify_packaging_comparison_ui import HEADERS, designs  # noqa: E402
from tests.verify_packaging_research_ui import start_pilot, tools_scope  # noqa: E402

ORDER = ["S-4080", "S-4103", "S-4120", "S-4187", "S-4235", "S-4415", "S-4196", "S-15039", "S-4219"]


def verify(url, output, service, principal):
    from ai_inspector.packaging_shipping.catalog import catalog
    errors, external, checks = [], [], []
    seed, _ = designs()
    record = next(c["carton"] for c in catalog()["cartons"] if c["carton"]["sku"] == "S-4187")
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
        created = context.request.post(url + "/api/packaging/documents", data=seed, headers=HEADERS)
        assert created.ok, created.text()
        doc = created.json()
        checks.append("seeded a TEST document through this check's own app")
        try:
            page.goto(url + "/packaging", wait_until="networkidle")
            page.get_by_role("button", name="Open", exact=True).click()
            page.locator(".document-row").filter(has_text=seed["name"]).get_by_role("button", name="Open", exact=True).click()
            expect(page.locator("#document-name")).to_have_value(seed["name"])
            command = page.locator("#command-carton")
            if command.get_attribute("aria-expanded") != "true":
                command.click()
            page.get_by_role("button", name="Carton catalog", exact=True).click()
            dialog = page.locator("#resource-dialog")
            expect(dialog).to_contain_text("200 lb test is a burst-strength grade, not a carton load limit")
            rows = dialog.locator(".document-row")
            expect(rows).to_have_count(len(ORDER))
            names = [rows.nth(i).locator("strong").inner_text() for i in range(len(ORDER))]
            assert [name.split()[1] for name in names] == ORDER, names
            for i in range(len(ORDER)):
                text = rows.nth(i).inner_text()
                assert "Payload Unknown" in text and "Checked 2026-11-06" in text and "https://www.uline.com/Product/Detail/" in text, text
            dialog.screenshot(path=str(output / "carton-catalog.png"))
            checks.append("the dialog lists nine ULINE cartons, smallest first, each with its unit weight source, check date and unknown payload")

            rows.filter(has_text="ULINE S-4187").get_by_role("button", name="Use carton", exact=True).click()
            expect(dialog).to_be_hidden()
            with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/documents/" + doc["id"])) as response:
                page.get_by_role("button", name="Save", exact=True).click()
            assert response.value.ok, response.value.text()
            expect(page.locator("#document-status")).to_contain_text("Saved")
            checks.append("Use carton applied S-4187 to the selected package and Save stored it")

            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="Carton catalog", exact=True).click()
            expect(dialog).to_be_visible()
            box = dialog.bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= 391 and box["y"] + box["height"] <= 845, box
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            rows.last.scroll_into_view_if_needed()
            expect(rows.last).to_be_in_viewport()
            page.screenshot(path=str(output / "carton-catalog-390.png"))
            page.keyboard.press("Escape")
            checks.append("at 390 px the dialog fits the viewport and scrolls to the last carton")
        finally:
            context.close()
            browser.close()
    saved = service.get(tools_scope(principal), doc["id"])
    first = saved["design"]["packages"][0]["carton"]
    assert first == record, first
    assert [p["carton"]["name"] for p in saved["design"]["packages"][1:]] == ["TEST carton"]
    checks.append("the saved first package's carton equals the catalog record exactly; the second package is unchanged")
    return {"passed": not errors and not external, "page_errors": errors, "external_requests": external, "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-catalog-ui-" + uuid4().hex[:10]))
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        parser.error("Output must stay in this worktree's .runtime directory")
    output.mkdir(parents=True, exist_ok=False)
    storage = Path(tempfile.mkdtemp(prefix="pk-catalog-ui-"))
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
