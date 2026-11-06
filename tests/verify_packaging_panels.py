"""Bounded, headless packaging UI acceptance; never attaches to an existing browser."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import expect, sync_playwright
import trimesh


ROOT = Path(__file__).resolve().parents[1]


def verify(url: str, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    errors, calls, screenshots = [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(15000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.on("request", lambda request: calls.append((request.method, request.url)))

        def panel(name):
            button = page.locator(f"#command-{name}")
            if button.get_attribute("aria-expanded") != "true":
                button.click()
            expect(page.locator("#tool-panel")).to_be_visible()

        def close():
            if page.locator("#tool-panel").is_visible():
                page.locator("#close-panel").click()
            expect(page.locator("#tool-panel")).to_be_hidden()

        def fill(name, value):
            page.locator(f'[name="{name}"]').fill(str(value))

        def canvas(name):
            page.wait_for_timeout(150)
            path = output / f"canvas-{name}.png"
            page.locator("#viewport canvas").screenshot(path=str(path))
            screenshots.append(path)

        def layout():
            return page.evaluate("""() => {
                const rect = id => {
                    const r = document.getElementById(id).getBoundingClientRect();
                    return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};
                };
                return { viewport:rect('viewport'), panel:rect('tool-panel'),
                    width:innerWidth, height:innerHeight, overflow:document.documentElement.scrollWidth > innerWidth + 1 };
            }""")

        try:
            page.goto(url + "/packaging", wait_until="networkidle")
            expect(page.locator("#viewport canvas")).to_be_visible()
            expect(page.locator("#document-status")).not_to_contain_text("Working")
            expect(page.locator("#tool-panel")).to_be_hidden()
            initial = layout()
            assert initial["viewport"]["width"] >= 1438, initial
            assert initial["viewport"]["height"] > 500, initial

            # Modeless keyboard admission and field retention across close/reopen.
            page.locator("#command-product").focus()
            page.keyboard.press("Enter")
            expect(page.locator("#tool-panel")).to_be_focused()
            fill("quantity", 6)
            page.keyboard.press("Escape")
            expect(page.locator("#command-product")).to_be_focused()
            expect(page.locator("#tool-panel")).to_be_hidden()
            panel("product")
            expect(page.locator('[name="quantity"]')).to_have_value("6")
            expect(page.locator("#panel-state")).to_contain_text("Unapplied")
            page.locator("#document-name").fill("TEST panel acceptance " + uuid4().hex[:8])
            fill("product_name", "TEST envelope")
            for axis, value in enumerate([100, 60, 40]):
                fill(f"product_dim_{axis}", value)
            page.get_by_role("button", name="Add manual product", exact=True).click()
            committed = []

            def lose_first_save_response(route):
                if route.request.method != "POST":
                    route.continue_()
                    return
                response = route.fetch()
                assert response.ok, response.text()
                committed.append(response.json())
                route.abort("failed")

            page.route("**/api/packaging/documents", lose_first_save_response)
            page.get_by_role("button", name="Save", exact=True).click()
            expect(page.locator("#message")).to_contain_text("fetch", ignore_case=True)
            assert len(committed) == 1
            page.unroute("**/api/packaging/documents", lose_first_save_response)
            page.get_by_role("button", name="Save", exact=True).click()
            expect(page.locator("#document-status")).to_contain_text("Saved")
            documents = page.request.get(url + "/api/packaging/documents").json()["documents"]
            matches = [doc for doc in documents if doc["name"] == committed[0]["design"]["name"]]
            assert [doc["id"] for doc in matches] == [committed[0]["id"]], matches
            panel("arrange")
            page.get_by_role("button", name="Generate candidates", exact=True).click()
            page.get_by_role("button", name="Apply candidate", exact=True).first.click()
            expect(page.locator("#panel-title")).to_have_text("Carton")
            page.get_by_role("button", name="Save", exact=True).click()
            panel("validation")
            expect(page.locator("#validation-panel")).to_contain_text("6 / 6 products placed")
            expect(page.locator("#validation-panel")).to_contain_text("Unknown")
            page.screenshot(path=str(output / "desktop-validation.png"))
            close()
            assert layout()["viewport"]["width"] >= 1438

            # Display-only operations must not mark or mutate the saved design.
            page.get_by_role("button", name="Fit view", exact=True).click()
            for label, name in [("Gray shaded", "shaded"), ("Shaded with edges", "edges"), ("Wireframe", "wireframe")]:
                page.get_by_role("button", name=label, exact=True).click()
                expect(page.get_by_role("button", name=label, exact=True)).to_have_attribute("aria-pressed", "true")
                canvas(name)
                expect(page.locator("#document-status")).to_contain_text("Saved")
            page.get_by_role("button", name="Gray shaded", exact=True).click()
            page.get_by_label("Display transparency", exact=True).fill("65")
            canvas("transparent")
            page.get_by_label("Display transparency", exact=True).fill("0")
            page.get_by_role("button", name="Top", exact=True).click()
            canvas("top")
            page.get_by_label("Section", exact=True).check()
            canvas("section")
            page.get_by_label("Section", exact=True).uncheck()
            page.get_by_label("Exploded", exact=True).check()
            canvas("exploded")
            page.get_by_label("Exploded", exact=True).uncheck()
            page.get_by_role("button", name="Orbit", exact=True).click()
            expect(page.locator("#document-status")).to_contain_text("Saved")
            panel("product")
            expect(page.locator('[name="product_dim_0"]')).to_have_value("100")
            expect(page.locator('[name="quantity"]')).to_have_value("6")
            expect(page.locator('[name="mass_basis"]')).to_have_value("unknown")
            panel("rates")
            expect(page.get_by_role("button", name="Compare rates", exact=True)).to_be_disabled()
            close()

            dimensions = []
            for width, height in [(1600, 1000), (1280, 720), (768, 1024), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                page.get_by_role("button", name="Fit view", exact=True).click()
                canvas(f"{width}-closed")
                page.screenshot(path=str(output / f"{width}-closed.png"))
                for name in ["product", "carton", "contents", "arrange", "appearance", "graphics", "validation", "rates"]:
                    panel(name)
                    data = layout()
                    assert not data["overflow"], data
                    assert data["viewport"]["height"] >= 70, data
                    assert data["panel"]["bottom"] <= height + 1, data
                    if width > 680:
                        assert data["viewport"]["right"] <= data["panel"]["x"] + 1, data
                    else:
                        assert data["viewport"]["bottom"] <= data["panel"]["y"] + 1, data
                    assert page.locator("#close-panel").is_visible()
                page.screenshot(path=str(output / f"{width}-rates.png"))
                dimensions.append(data)
                close()
                assert layout()["viewport"]["width"] >= width - 2

            # Additive design controls are exercised as local drafts; backend rollout is independent.
            page.set_viewport_size({"width": 1440, "height": 1000})
            panel("contents")
            page.get_by_role("button", name="Add pad", exact=True).click()
            fill("pad_name", "TEST pocketed insert")
            for axis, value in enumerate([200, 50, 150]):
                fill(f"pad_dim_{axis}", value)
            for axis, value in enumerate([20, 140, 20]):
                fill(f"position_{axis}", value)
            fill("material_evidence", "TEST physical density 30 kg/m3")
            page.get_by_role("button", name="Add pocket", exact=True).click()
            first = page.locator("[data-pocket-id]").first.get_attribute("data-pocket-id")
            for axis, value in enumerate([50, 40, 50]):
                fill(f"{first}_dim_{axis}", value)
            for axis, value in enumerate([20, 10, 20]):
                fill(f"{first}_pos_{axis}", value)
            page.get_by_role("button", name="Add pocket", exact=True).click()
            second = page.locator("[data-pocket-id]").last.get_attribute("data-pocket-id")
            page.locator(f'[name="{second}_shape"]').select_option("cylindrical")
            fill(f"{second}_dim_0", 40)
            # AABBs intersect at the corner, but the actual voids retain >5 mm web.
            # The opening is 0.9 microns above the top, within backend tolerance.
            fill(f"{second}_dim_1", 30.0009)
            expect(page.locator(f'[name="{second}_dim_2"]')).to_have_value("40")
            for axis, value in enumerate([68, 20, 68]):
                fill(f"{second}_pos_{axis}", value)
            page.locator("#editor form").get_by_role("button", name="Add pad", exact=True).click()
            panel("appearance")
            page.locator('[name="appearance_target"]').select_option(label="TEST pocketed insert")
            fill("appearance_color", "#4c9c76")
            page.get_by_role("button", name="Apply appearance", exact=True).click()
            expect(page.get_by_role("button", name="Appearance colors", exact=True)).to_have_attribute("aria-pressed", "true")
            panel("graphics")
            page.get_by_role("button", name="Add lettering", exact=True).click()
            fill("graphic_text", "TEST PACK / 6")
            page.locator('[name="graphic_face"]').select_option("z+")
            page.locator("#editor form").get_by_role("button", name="Add lettering", exact=True).click()
            close()
            page.get_by_role("button", name="Orbit", exact=True).click()
            expect(page.locator("#scene-message")).to_have_text("")
            canvas("pockets-and-lettering")
            page.screenshot(path=str(output / "pockets-and-lettering.png"))
            page.get_by_role("button", name="Top", exact=True).click()
            canvas("pocket-openings")
            page.get_by_role("button", name="Undo", exact=True).click()
            panel("graphics")
            expect(page.locator("#editor")).to_contain_text("No surface graphics")
            page.get_by_role("button", name="Redo", exact=True).click()
            expect(page.locator("#editor")).to_contain_text("TEST PACK / 6")

            # Exercise the actual GLB worker and rendered source, not just a box fixture.
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.get_by_role("button", name="New", exact=True).click()
            part = trimesh.creation.annulus(r_min=.014, r_max=.035, height=.025)
            part.apply_transform(trimesh.transformations.rotation_matrix(.35, [1, 1, 0]))
            source = output / "synthetic-source.glb"
            part.export(source)
            page.locator('[name="source_file"]').set_input_files(str(source))
            page.get_by_role("button", name="Import GLB", exact=True).click()
            expect(page.locator("#editor")).to_contain_text("dimensions locked", timeout=35000)
            expect(page.locator("#scene-message")).to_have_text("", timeout=20000)
            imported_dimensions = [page.locator(f'[name="product_dim_{axis}"]').input_value() for axis in range(3)]
            close()
            page.get_by_role("button", name="Shaded with edges", exact=True).click()
            canvas("source-edges")
            page.get_by_role("button", name="Wireframe", exact=True).click()
            canvas("source-wireframe")
            page.get_by_role("button", name="Gray shaded", exact=True).click()
            page.screenshot(path=str(output / "source-full-viewport.png"))
            panel("product")
            assert imported_dimensions == [page.locator(f'[name="product_dim_{axis}"]').input_value() for axis in range(3)]
            assert all(page.locator(f'[name="product_dim_{axis}"]').get_attribute("readonly") is not None for axis in range(3))
            expect(page.locator('[name="mass_basis"]')).to_have_value("unknown")
            assert not errors, errors
            assert not any(method == "POST" and path.endswith("/quotes") for method, path in calls)
            assert not any("/api/agent/chat" in path for _, path in calls)
        except Exception:
            page.screenshot(path=str(output / "failure.png"), full_page=True)
            (output / "failure.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
            raise
        finally:
            context.close()
            browser.close()

    statistics = {}
    for path in screenshots:
        image = Image.open(path).convert("RGB")
        values = ImageStat.Stat(image).stddev
        assert max(values) > 8, (path.name, values)
        statistics[path.name] = [round(value, 2) for value in values]
    for first, second in [("shaded", "edges"), ("shaded", "wireframe"), ("shaded", "transparent"), ("shaded", "top"), ("source-edges", "source-wireframe")]:
        a, b = (Image.open(output / f"canvas-{name}.png").convert("RGB") for name in (first, second))
        assert ImageChops.difference(a, b).getbbox(), f"Unchanged pixels: {first}, {second}"
    result = {"page_errors": errors, "viewports": dimensions, "canvas_stddev": statistics,
              "checks": ["eight modeless panels", "full closed viewport", "keyboard and focus", "dirty field retention",
                         "saved six-item arrangement", "display modes", "transparency", "section and exploded",
                         "unchanged physical inputs", "lost first-save response retries without duplication", "diagonal mixed pockets and one-micron opening tolerance", "local pocket/appearance/lettering drafts and Undo", "generated GLB import and precise bounds", "no chat or carrier calls"]}
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "output": str(output), "checks": result["checks"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8181")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-panels-" + uuid4().hex[:10]))
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(ROOT / ".runtime"):
        parser.error("Output must remain inside this worktree's .runtime directory")
    verify(args.url.rstrip("/"), args.output.resolve())
