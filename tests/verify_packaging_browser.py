"""Opt-in live pilot verification; writes only disposable packaging documents."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import time

from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import sync_playwright, expect


def verify(url, output, *, headed=False, slow_mo=0, hold_seconds=0):
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, slow_mo=slow_mo,
                                    args=["--enable-unsafe-swiftshader"])
        desktop = {"width": 1440, "height": 900 if headed else 1000}
        context = browser.new_context(viewport=desktop, accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(15000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())

        def phase(message):
            print(message, flush=True)
            if headed:
                page.wait_for_timeout(2500)

        page.goto(url + "/packaging", wait_until="networkidle")
        expect(page.locator("#provider-status")).to_contain_text("not configured")
        expect(page.locator("#viewport canvas")).to_be_visible()
        phase("1/7: Creating a six-item test package with documented input assumptions.")
        name = f"TEST browser package {int(time())}"
        page.locator("#document-name").fill(name)

        def fill(field, value):
            page.locator(f'[name="{field}"]').fill(str(value))

        fill("product_name", "TEST machined component envelope")
        for axis, value in enumerate([100, 60, 40]):
            fill(f"product_dim_{axis}", value)
        fill("quantity", 6)
        page.locator('[name="mass_basis"]').select_option("estimate")
        fill("product_mass", .5)
        fill("mass_evidence", "DEMO assumption: 0.5 kg per item, not a measured or CAD-derived value")
        page.locator('[name="contents"]').select_option("ordinary_nonhazardous")
        page.get_by_role("button", name="Add manual product", exact=True).click()
        page.get_by_role("button", name="Save", exact=True).click()
        expect(page.locator("#document-status")).to_contain_text("Saved")
        phase("2/7: Comparing carton arrangements and applying a feasible candidate.")
        page.get_by_role("tab", name="Arrange", exact=True).click()
        fill("tare", .2)
        fill("tare_evidence", "TEST carton scale")
        fill("payload", 10)
        page.get_by_role("button", name="Apply alternative", exact=True).click()
        page.get_by_role("button", name="Generate candidates", exact=True).click()
        page.get_by_role("button", name="Apply candidate", exact=True).first.click()
        fill("allowance", .05)
        fill("allowance_evidence", "TEST tape allowance")
        page.get_by_role("button", name="Apply carton", exact=True).click()
        page.get_by_role("button", name="Save", exact=True).click()
        expect(page.locator("#validation-panel")).to_contain_text("Eligible for a rate request")
        expect(page.locator("#validation-panel")).to_contain_text("3.25 kg")
        phase("3/7: Adding a foam pad and checking the updated gross mass.")

        # Add a real solid pad below the product envelopes without colliding.
        page.get_by_role("tab", name="Contents", exact=True).click()
        page.get_by_role("button", name="Add pad", exact=True).click()
        fill("material_evidence", "TEST supplier density 30 kg/m3")
        page.locator("#editor form").get_by_role("button", name="Add pad", exact=True).click()
        page.get_by_role("button", name="Save", exact=True).click()
        expect(page.locator("#validation-panel")).to_contain_text("Eligible for a rate request")
        page.get_by_role("button", name="Fit view", exact=True).click()
        page.locator("#viewport canvas").screenshot(path=str(output / "canvas-orbit.png"))
        page.screenshot(path=str(output / "desktop.png"))
        phase("4/7: Inspecting top, section and exploded views; testing Undo and Redo.")
        page.get_by_role("button", name="Top", exact=True).click()
        page.locator("#viewport canvas").screenshot(path=str(output / "canvas-top.png"))
        page.get_by_label("Section", exact=True).check()
        page.get_by_label("Section", exact=True).uncheck()
        page.get_by_label("Exploded", exact=True).check()
        page.screenshot(path=str(output / "exploded.png"))
        page.get_by_label("Exploded", exact=True).uncheck()
        page.get_by_role("button", name="Orbit", exact=True).click()

        page.get_by_role("button", name="Undo", exact=True).click()
        expect(page.locator("#validation-panel")).to_contain_text("3.25 kg")
        page.get_by_role("button", name="Redo", exact=True).click()
        expect(page.locator("#document-status")).to_contain_text("Saved")
        phase("5/7: Exporting the review PDF. Carrier quotes are unavailable without credentials.")
        with page.expect_download() as downloaded:
            page.get_by_role("button", name="Download PDF", exact=True).click()
        downloaded.value.save_as(str(output / "packaging-review.pdf"))
        page.get_by_role("tab", name="Rates", exact=True).click()
        expect(page.get_by_role("button", name="Compare rates", exact=True)).to_be_disabled()
        expect(page.locator("#rates-panel")).to_contain_text("Not configured")
        page.get_by_role("button", name="Open", exact=True).click()
        page.locator(".document-row", has_text=name).get_by_role("button", name="Open", exact=True).click()
        expect(page.locator("#document-name")).to_have_value(name)
        expect(page.locator("#validation-panel")).to_contain_text("Eligible for a rate request")

        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="Fit view", exact=True).click()
        page.screenshot(path=str(output / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), "Horizontal overflow"
        page.locator("#viewport canvas").screenshot(path=str(output / "canvas-mobile.png"))

        # Import an existing CAD-derived repository asset through the actual UI.
        page.set_viewport_size(desktop)
        phase("6/7: Importing the existing CAD-derived model without changing its dimensions.")
        page.get_by_role("button", name="New", exact=True).click()
        asset = Path(__file__).resolve().parents[1] / "generated/training/racing-bike/part_glb/RB-001_viewer.glb"
        page.locator('[name="source_file"]').set_input_files(str(asset))
        page.get_by_role("button", name="Import GLB", exact=True).click()
        expect(page.locator("#editor")).to_contain_text("dimensions locked", timeout=35000)
        expect(page.locator("#scene-message")).to_have_text("", timeout=20000)
        assert page.locator('[name="product_dim_0"]').get_attribute("readonly") is not None
        page.get_by_role("button", name="Fit view", exact=True).click()
        page.screenshot(path=str(output / "imported-model.png"))
        page.locator("#viewport canvas").screenshot(path=str(output / "canvas-imported.png"))
        assert "Only the source envelope" not in page.locator("#scene-message").inner_text()
        assert "unknown" in page.locator("#message").inner_text().lower()
        page.locator("#document-name").fill(name + " CAD source")
        fill("quantity", 6)
        fill("clearance", 2)
        fill("gap", 1)
        page.get_by_role("button", name="Apply product", exact=True).click()
        page.get_by_role("button", name="Save", exact=True).click()
        expect(page.locator("#document-status")).to_contain_text("Saved")
        page.get_by_role("tab", name="Arrange", exact=True).click()
        for axis, value in enumerate([30, 40, 30]):
            fill(f"inner_{axis}", value)
            fill(f"outer_{axis}", value + 4)
        page.get_by_role("button", name="Apply alternative", exact=True).click()
        page.get_by_role("button", name="Generate candidates", exact=True).click()
        page.get_by_role("button", name="Apply candidate", exact=True).first.click()
        page.get_by_role("button", name="Save", exact=True).click()
        page.get_by_role("tab", name="Validation", exact=True).click()
        expect(page.locator("#validation-panel")).to_contain_text("6 / 6 products placed")
        expect(page.locator("#validation-panel")).to_contain_text("Unknown")
        expect(page.locator("#scene-message")).to_have_text("")
        page.get_by_role("button", name="Fit view", exact=True).click()
        page.screenshot(path=str(output / "six-imported-products.png"))
        page.locator("#viewport canvas").screenshot(path=str(output / "canvas-six-imported.png"))
        phase("7/7: Six imported models packed. Missing mass remains unknown and blocks rate requests.")
        assert not errors, errors
        if headed and hold_seconds:
            print(f"Holding the final view for {hold_seconds} seconds.", flush=True)
            page.wait_for_timeout(hold_seconds * 1000)
        context.close()
        browser.close()

    pixel_stats = {}
    for file in output.glob("canvas-*.png"):
        image = Image.open(file).convert("RGB")
        deviations = ImageStat.Stat(image).stddev
        assert max(deviations) > 8, (file.name, deviations)
        pixel_stats[file.name] = [round(x, 2) for x in deviations]
    first, second = [Image.open(output / x).convert("RGB") for x in ("canvas-orbit.png", "canvas-top.png")]
    assert ImageChops.difference(first, second).getbbox(), "View controls did not change rendered pixels"
    result = {"url": url, "headed": headed, "document_name": name, "page_errors": errors, "canvas_stddev": pixel_stats,
              "checks": ["manual editing", "packing solver", "pad mass", "validation", "undo redo", "PDF",
                         "save reopen", "unconfigured rates", "responsive", "camera pixels", "real GLB render",
                         "six real GLB instances with unknown mass preserved"]}
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8179")
    parser.add_argument("--output", type=Path, default=Path(".runtime/packaging-browser"))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--slow-mo", type=int, choices=range(0, 2001), metavar="MS", default=0)
    parser.add_argument("--hold-seconds", type=int, choices=range(0, 301), metavar="SECONDS", default=0)
    args = parser.parse_args()
    verify(args.url, args.output, headed=args.headed, slow_mo=args.slow_mo, hold_seconds=args.hold_seconds)
