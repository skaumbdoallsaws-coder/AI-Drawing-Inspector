"""Presentation acceptance on a disposable store; no carrier or Sage requests."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from PIL import Image, ImageChops
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from verify_packaging_comparison_ui import HEADERS, designs, start_pilot


def verify(url, output):
    errors, external, checks = [], [], []
    # Test-only access to the actual scene. No debug hooks ship in the application.
    source = (ROOT / "static/packaging_scene.js").read_text(encoding="utf-8")
    source = source.replace("this.host = host;", "globalThis.testScene = this; this.host = host;", 1)
    original = subprocess.check_output(["git", "show", "414e5fd:static/index.html"], cwd=ROOT).decode("utf-8")
    old_background = original[original.index("function _themeCssColorToken("):original.index("function _applyCadViewportBackground(")]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        def local_only(route):
            if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
                external.append(route.request.url)
                route.abort()
            else:
                route.continue_()
        context.route("**/*", local_only)
        context.route("**/static/packaging_scene.js", lambda route: route.fulfill(body=source, content_type="text/javascript"))
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.set_default_timeout(20000)
        design = designs()[1]
        created = context.request.post(url + "/api/packaging/documents?contents_confirmed=true", data=design, headers=HEADERS)
        assert created.ok, created.text()
        doc = created.json()
        endpoint = url + "/api/packaging/documents/" + doc["id"]
        before = context.request.get(endpoint, headers=HEADERS).json()
        page.goto(url + "/packaging", wait_until="networkidle")
        page.get_by_role("button", name="Open", exact=True).click()
        page.locator(".document-row").filter(has_text=design["name"]).get_by_role("button", name="Open", exact=True).click()
        expect(page.locator("#document-name")).to_have_value(design["name"])
        canvas = page.locator("canvas.packaging-model-canvas")
        triad = page.locator("canvas.orientation-gizmo")
        expect(canvas).to_be_visible()
        expect(triad).to_have_count(1)
        page.wait_for_timeout(300)
        original_design = page.evaluate("JSON.stringify(testScene.design)")
        assert page.evaluate("() => { const types=[]; testScene.content.traverse(n=>types.push(n.type)); return !types.some(t=>['GridHelper','AxesHelper'].includes(t)); }")
        checks.append("no grid or world-origin axes in the scene")

        # Compare every pixel of the shared texture with the pre-change Assembly recipe.
        page.add_script_tag(content=old_background)
        for theme in ("dark", "light"):
            page.evaluate("t => document.documentElement.dataset.theme=t", theme)
            page.wait_for_timeout(150)
            assert page.evaluate("""async () => {
                const THREE = await import('/static/vendor/three/0.184.0/build/three.module.min.js');
                const old = _makeCadViewportBackgroundTexture(THREE);
                const fresh = InspectorProCadViewport.createBackgroundTexture(THREE, document);
                const pixels = t => t.image.getContext('2d').getImageData(0,0,1024,768).data;
                const a=pixels(old), b=pixels(fresh), same=a.every((v,i)=>v===b[i]);
                old.dispose(); fresh.dispose(); return same;
            }""")
            page.screenshot(path=str(output / f"desktop-{theme}.png"))
        checks.append("dark and light background textures match original Assembly pixel-for-pixel")

        def settle():
            page.wait_for_timeout(200)
        def image(locator):
            return Image.open(io.BytesIO(locator.screenshot())).convert("RGB")
        def changed(a, b):
            return ImageChops.difference(a, b).getbbox() is not None
        def drag(button, dx, dy):
            r = canvas.bounding_box()
            x, y = r["x"] + r["width"] * .55, r["y"] + r["height"] * .55
            page.mouse.move(x, y)
            page.mouse.down(button=button)
            page.mouse.move(x + dx, y + dy, steps=12)
            page.mouse.up(button=button)
            settle()

        a, model = image(triad), image(canvas)
        assert len(model.getcolors(model.width * model.height)) > 200, "blank render"
        drag("right", 65, 30)
        assert not changed(a, image(triad)), "triad moved on pan"
        assert changed(model, image(canvas)), "pan did not move the model"
        model = image(canvas)
        page.mouse.wheel(0, -200)
        settle()
        assert not changed(a, image(triad)), "triad moved on zoom"
        assert changed(model, image(canvas)), "zoom did not change the model"
        drag("left", 90, 50)
        assert changed(a, image(triad)), "triad did not rotate on orbit"
        checks.append("real mouse pan and zoom keep the triad fixed; orbit rotates it")

        page.evaluate("testScene.view('iso')")
        settle()
        for theme in ("dark", "light"):
            page.evaluate("t => document.documentElement.dataset.theme=t", theme)
            for width, height in ((1440, 1000), (1000, 760), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                settle()
                r, t = page.locator("#viewport").bounding_box(), triad.bounding_box()
                assert t["width"] == t["height"] == 80, t
                assert abs(t["x"] - r["x"] - 12) < 2, (r, t)
                assert abs(r["y"] + r["height"] - t["y"] - 80 - 12) < 2, (r, t)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                icons = page.evaluate("""async () => {
                    const result=[];
                    for(const node of document.querySelectorAll('.ribbon-command .packaging-ribbon-icon')) {
                        const style=getComputedStyle(node),r=node.getBoundingClientRect();
                        const image=new Image();
                        image.src=getComputedStyle(node,'::before').backgroundImage.match(/url\\(["']?([^"')]+)/)[1];
                        await image.decode();
                        result.push({name:node.dataset.packagingIcon,mask:style.maskImage,width:r.width,height:r.height,loaded:image.naturalWidth>0});
                    }
                    return result;
                }""")
                assert len(icons) == 8, icons
                for icon in icons:
                    assert icon["loaded"] and icon["mask"] == "none", icon
                    assert icon["width"] == icon["height"] == (20 if width <= 680 else 23), icon
                page.screenshot(path=str(output / f"{theme}-{width}.png"))
                assert len(image(canvas).getcolors(width * height * 4)) > 200
        checks.append("nonblank desktop, compact and mobile renders; anchored triad and no horizontal overflow")
        checks.append("all ribbon PNGs decode in both themes, retain square desktop/mobile slots and bypass the monochrome mask")
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.evaluate("testScene.setSection(true); testScene.setExploded(true)")
        settle()
        assert page.evaluate("testScene.renderer.clippingPlanes.length === 1 && testScene.exploded")
        page.evaluate("testScene.setSection(false); testScene.setExploded(false)")
        assert page.evaluate("JSON.stringify(testScene.design)") == original_design
        assert context.request.get(endpoint, headers=HEADERS).json() == before
        checks.append("display operations preserved design, persisted revision and coordinates")
        page.evaluate("testScene.dispose()")
        expect(triad).to_have_count(0)
        assert not errors, errors
        assert not external, external
        browser.close()
    result = {"status": "passed", "checks": checks, "errors": errors, "external_requests": external}
    (output / "viewport.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--panels", action="store_true")
    parser.add_argument("--dependencies", type=Path, help="Approved desktop dependency folder for isolated import workers")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.dependencies:
        from ai_inspector.packaging_shipping.sources import configure_glb_runtime
        configure_glb_runtime(args.dependencies)
        sys.path.insert(0, str(args.dependencies))
    with tempfile.TemporaryDirectory(prefix="packaging-viewport-") as folder:
        url, server, thread = start_pilot(Path(folder))
        try:
            verify(url, args.output)
            if args.panels:
                from verify_packaging_panels import verify as verify_panels
                verify_panels(url, args.output / "panels")
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "test server did not shut down"


if __name__ == "__main__":
    main()
