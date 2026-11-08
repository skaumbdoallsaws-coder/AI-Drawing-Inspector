"""Real local resource persistence; headless browser, generated assets, mocked account only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from uuid import uuid4

from PIL import Image, ImageDraw, ImageStat
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
STEP_GENERATOR = """
import sys
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.Interface import Interface_Static
from OCP.IFSelect import IFSelect_RetDone
writer=STEPControl_Writer()
Interface_Static.SetCVal_s('write.step.unit','MM')
assert writer.Transfer(BRepPrimAPI_MakeBox(40,30,20).Shape(), STEPControl_AsIs)==IFSelect_RetDone
assert writer.Write(sys.argv[1])==IFSelect_RetDone
"""


def verify(url: str, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    asset = Image.new("RGBA", (400, 240))
    draw = ImageDraw.Draw(asset)
    draw.rectangle((80, 60, 319, 179), fill="#e24351")
    draw.rectangle((100, 80, 139, 159), fill="#ffffff")
    draw.rectangle((160, 80, 299, 105), fill="#ffffff")
    artwork = output / "TEST-artwork.png"
    asset.save(artwork)
    errors, calls, checks, account_requests = [], [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.on("request", lambda request: calls.append((request.method, request.url)))
        headers = {"X-InspectorPro-Request": "packaging"}
        status = context.request.get(url + "/api/packaging/status").json()
        assert {"surface_graphics", "saved_alternatives", "material_catalog"}.issubset(status["capabilities"]), "Restart the host with the additive resource backend first."

        def local_only(route):
            if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
                route.abort()
            else:
                route.continue_()

        context.route("**/*", local_only)

        def panel(name):
            command = page.locator(f"#command-{name}")
            if command.get_attribute("aria-expanded") != "true":
                command.click()

        def fill(name, value):
            page.locator(f'[name="{name}"]').fill(str(value))

        def saved():
            response = context.request.get(url + f"/api/packaging/documents/{document_id}")
            assert response.ok
            return response.json()

        def save():
            with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/documents/" + document_id)) as response:
                page.get_by_role("button", name="Save", exact=True).click()
            assert response.value.ok, response.value.text()
            expect(page.locator("#document-status")).to_contain_text("Saved")

        seed = {
            "name": "TEST resources " + uuid4().hex[:8], "quantity": 1,
            "product": {"name": "TEST measured product", "dimensions_m": [.04, .03, .02], "mass_kg": .05,
                        "mass_basis": "user_measured", "mass_evidence": "TEST scale measurement"},
            "constraints": {"clearance_m": .01, "gap_m": .005, "allowed_orientations": [0], "contents": "ordinary_nonhazardous"},
            "packages": [{"id": "test_box", "carton": {"name": "TEST carton", "inner_m": [.4, .3, .25], "outer_m": [.41, .31, .26],
                "tare_kg": .2, "tare_evidence": "TEST scale measurement"}, "placements": [{"id": "test_item", "position_m": [.02, .02, .02], "orientation": 0}],
                "inserts": [], "allowance_kg": 0, "allowance_evidence": "TEST allowance"}],
        }
        created = context.request.post(url + "/api/packaging/documents?contents_confirmed=true", data=seed, headers=headers)
        assert created.ok, created.text()
        document_id = created.json()["id"]
        try:
            page.goto(url + "/packaging", wait_until="networkidle")
            page.get_by_role("button", name="Open", exact=True).click()
            page.locator(".document-row").filter(has_text=seed["name"]).get_by_role("button", name="Open", exact=True).click()
            expect(page.locator("#document-name")).to_have_value(seed["name"])

            panel("carton")
            page.get_by_role("button", name="Carton catalog", exact=True).click()
            expect(page.locator("#resource-dialog")).to_contain_text("Payload Unknown")
            page.locator("#resource-dialog .document-row").filter(has_text="ULINE S-15039").get_by_role("button", name="Use carton", exact=True).click()
            save()
            assert saved()["design"]["packages"][0]["carton"]["sku"] == "S-15039"
            page.locator('[name="tare_method"]').select_option("blank")
            for name, value in {"blank_width": 800, "blank_length": 1200, "blank_quantity": 2,
                                "blank_basis_weight": .4, "blank_evidence": "TEST full blank and sourced area density"}.items():
                fill(name, value)
            page.get_by_role("button", name="Apply carton", exact=True).click()
            save()
            carton = saved()["design"]["packages"][0]["carton"]
            assert abs(carton["tare_kg"] - .768) < 1e-10 and carton["sku"] == "S-15039"
            checks.append("catalog evidence and blank-area tare persisted")

            panel("contents")
            page.get_by_role("button", name="Add pad", exact=True).click()
            fill("pad_name", "TEST pocket insert")
            for axis, value in enumerate([150, 50, 120]):
                fill(f"pad_dim_{axis}", value)
            for axis, value in enumerate([100, 80, 60]):
                fill(f"position_{axis}", value)
            page.get_by_role("button", name="Material catalog", exact=True).click()
            page.locator('[name="material_catalog"]').select_option("ethafoam-150-0924")
            expect(page.locator('[name="density"]')).to_have_value("25")
            page.get_by_role("button", name="Add pocket", exact=True).click()
            pocket_id = page.locator("[data-pocket-id]").get_attribute("data-pocket-id")
            for axis, value in enumerate([50, 40, 40]):
                fill(f"{pocket_id}_dim_{axis}", value)
            for axis, value in enumerate([20, 10, 20]):
                fill(f"{pocket_id}_pos_{axis}", value)
            page.locator("#editor form").get_by_role("button", name="Add pad", exact=True).click()
            save()
            insert = saved()["design"]["packages"][0]["inserts"][0]
            assert insert["pockets"][0]["position_m"] == [.02, .01, .02]
            assert "Sealed Air" in insert["material_evidence"]
            checks.append("catalog material and pocket persisted")

            panel("graphics")
            page.locator('[name="graphic_file"]').set_input_files(str(artwork))
            page.get_by_role("button", name="Add image", exact=True).click()
            expect(page.locator('[name="graphic_rotation"]')).to_be_visible()
            page.locator('[name="graphic_rotation"]').select_option("90")
            page.get_by_role("button", name="Apply graphic", exact=True).click()
            save()
            graphic = saved()["design"]["packages"][0]["graphics"][0]
            metadata = context.request.get(url + "/api/packaging/images/" + graphic["image_id"]).json()
            assert metadata["width"] == 400 and metadata["uv"][0] > 0 and metadata["uv"][2] < 1
            page.get_by_role("button", name="Top", exact=True).click()
            expect(page.locator("#scene-message")).to_have_text("", timeout=30000)
            page.locator("#close-panel").click()
            page.locator("#viewport canvas.packaging-model-canvas").screenshot(path=str(output / "image-top.png"))
            assert max(ImageStat.Stat(Image.open(output / "image-top.png").convert("RGB")).stddev) > 8
            assert sum(r > 130 and r > g * 1.5 and r > b * 1.3 for r, g, b in Image.open(output / "image-top.png").convert("RGB").getdata()) > 100, "Uploaded red artwork must render in the canvas"
            page.get_by_role("button", name="Reload saved document", exact=True).click()
            expect(page.locator("#document-status")).to_contain_text("Saved")
            expect(page.locator("#scene-message")).to_have_text("", timeout=30000)
            assert saved()["design"]["packages"][0]["graphics"][0] == graphic
            checks.append("PNG trim, rotated artwork, persistence and reopen")

            # Browser canvas verifies masking, including through pockets and rotated UVs.
            mask = page.evaluate("""async () => {
                const {maskGraphicPockets}=await import('/static/packaging_scene.js');
                const canvas=document.createElement('canvas'); canvas.width=200; canvas.height=200;
                const c=canvas.getContext('2d'); c.fillStyle='#ff0000'; c.fillRect(0,0,200,200);
                maskGraphicPockets(canvas,[.2,.05,.2],{face:'y+',u:.5,v:.5,width_fraction:1,height_fraction:1,rotation_degrees:90},
                    [{shape:'rectangular',dimensions_m:[.04,.04,.04],position_m:[.08,.01,.08]}]);
                return [c.getImageData(100,100,1,1).data[3],c.getImageData(10,10,1,1).data[3]];
            }""")
            assert mask == [0, 255]

            panel("arrange")
            page.get_by_role("button", name="Saved designs", exact=True).click()
            fill("alternative_name", "TEST baseline snapshot")
            page.get_by_role("button", name="Save snapshot", exact=True).click()
            expect(page.locator("#resource-dialog")).to_contain_text("TEST baseline snapshot")
            page.get_by_role("button", name="Close dialog", exact=True).click()
            baseline = saved()["design"]
            panel("product")
            fill("quantity", 2)
            page.get_by_role("button", name="Apply product", exact=True).click()
            save()
            panel("arrange")
            page.get_by_role("button", name="Saved designs", exact=True).click()
            page.get_by_role("button", name="Apply saved design", exact=True).click()
            expect(page.locator("#document-status")).to_contain_text("Saved")
            expect(page.locator("#resource-dialog")).to_be_hidden()
            assert saved()["design"] == baseline
            with page.expect_response(lambda r: r.url.endswith("/undo")):
                page.get_by_role("button", name="Undo", exact=True).click()
            assert saved()["design"]["quantity"] == 2
            checks.append("immutable snapshot application via PUT and atomic saved Undo")

            if "step_import" in status["capabilities"]:
                runtime = ROOT / ".runtime/step-venv/Scripts/python.exe"
                assert runtime.is_file(), "Configured STEP host needs local runtime for generated browser fixture"
                step = output / "TEST-block.step"
                subprocess.run([str(runtime), "-c", STEP_GENERATOR, str(step)], check=True, capture_output=True,
                               timeout=45, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                panel("product")
                page.locator('[name="source_file"]').set_input_files(str(step))
                expect(page.locator('[name="source_units"]')).to_be_disabled()
                page.get_by_role("button", name="Import STEP", exact=True).click()
                expect(page.locator("#editor")).to_contain_text("dimensions locked", timeout=90000)
                save()
                before_estimate = saved()
                page.get_by_role("button", name="Estimate from volume and density", exact=True).click()
                page.locator('[name="material_catalog"]').select_option("pmma-plexiglas-gs-xt")
                fill("estimate_exclusions", "TEST solid block; grade and manufacturing tolerance unverified")
                page.get_by_role("button", name="Calculate estimate", exact=True).click()
                expect(page.locator("#panel-state")).to_contain_text("Unapplied")
                assert saved() == before_estimate, "Mass calculation must not save or modify the document"
                expect(page.locator('[name="mass_basis"]')).to_have_value("estimate")
                page.get_by_role("button", name="Apply product", exact=True).click()
                save()
                product = saved()["design"]["product"]
                assert abs(product["mass_kg"] - .04 * .03 * .02 * 1190) < 1e-8
                assert product["dimensions_m"] == before_estimate["design"]["product"]["dimensions_m"]
                page.get_by_role("button", name="Imported sources", exact=True).click()
                expect(page.locator("#resource-dialog")).to_contain_text("TEST-block.step")
                page.get_by_role("button", name="Close dialog", exact=True).click()
                checks.append("real generated STEP worker, source list, staged density estimate and Apply")
            else:
                checks.append("STEP unavailable: capability-gated (not tested)")

            # Account-only route mocks: no key is ever sent to the real credential store.
            fake_key = "TEST-UI-ONLY-NOT-A-CARRIER-CREDENTIAL"
            fake_status = {"provider": "EasyPost", "configured": False, "secure_store_enabled": True, "validation": "not_validated", "purchases_enabled": False}
            def account(route):
                method = route.request.method
                account_requests.append(method)
                if method == "PUT":
                    assert route.request.post_data_json == {"api_key": fake_key, "account_alias": "TEST UI account"}
                    assert route.request.headers["x-inspectorpro-request"] == "packaging"
                    if account_requests.count("PUT") == 1:
                        route.fulfill(status=422, json={"error": {"message": "Unsafe echo " + fake_key}})
                    else:
                        fake_status.update(configured=True, account_alias="TEST UI account")
                        route.fulfill(json=fake_status)
                else:
                    if method == "DELETE":
                        fake_status.update(configured=False, account_alias=None)
                    route.fulfill(json=fake_status)

            context.route("**/api/packaging/account", account)
            context.route("**/api/packaging/status", lambda route: route.fulfill(json={**status, "rating": fake_status}))
            panel("rates")
            page.get_by_role("button", name="Refresh provider status", exact=True).click()
            page.get_by_role("button", name="Carrier account", exact=True).click()
            fill("carrier_alias", "TEST UI account")
            fill("carrier_key", fake_key)
            page.get_by_role("button", name="Save account", exact=True).click()
            expect(page.locator("#resource-dialog .error")).to_contain_text("could not be saved")
            expect(page.locator('[name="carrier_key"]')).to_have_value("")
            assert fake_key not in page.locator("body").inner_text()
            storage = page.evaluate("JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)])")
            assert fake_key not in storage and fake_key not in json.dumps(saved())
            fill("carrier_key", fake_key)
            page.get_by_role("button", name="Save account", exact=True).click()
            expect(page.locator("#resource-dialog")).to_be_hidden()
            assert page.locator('[name="carrier_key"]').count() == 0
            page.get_by_role("button", name="Carrier account", exact=True).click()
            page.get_by_role("button", name="Remove account", exact=True).click()
            expect(page.locator("#resource-dialog")).to_be_hidden()
            checks.append("mocked credential failure/save/removal: cleared key, sanitized response, no persisted secret")

            for width, height in [(1440, 1000), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                panel("arrange")
                page.get_by_role("button", name="Saved designs", exact=True).click()
                expect(page.locator("#resource-dialog")).to_be_visible()
                rect = page.locator("#resource-dialog").bounding_box()
                assert rect["x"] >= 0 and rect["x"] + rect["width"] <= width + 1
                assert rect["y"] >= 0 and rect["y"] + rect["height"] <= height + 1
                assert not page.evaluate("document.documentElement.scrollWidth>innerWidth+1")
                page.screenshot(path=str(output / f"{width}-saved-designs.png"))
                page.keyboard.press("Escape")
                expect(page.locator("#resource-dialog")).to_be_hidden()
            assert not errors, errors
            assert not any("/api/agent/chat" in path or path.endswith("/quotes") and method == "POST" for method, path in calls)
            assert account_requests == ["GET", "PUT", "PUT", "GET", "DELETE"]
        except Exception:
            # Never capture a password input even on an unexpected account-test failure.
            page.locator('input[type="password"]').evaluate_all("nodes=>nodes.forEach(n=>n.value='')")
            page.screenshot(path=str(output / "failure.png"), full_page=True)
            (output / "failure.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
            raise
        finally:
            context.close()
            browser.close()
    result = {"passed": True, "page_errors": errors, "checks": checks, "output": str(output)}
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8181")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-resources-" + uuid4().hex[:10]))
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(ROOT / ".runtime"):
        parser.error("Output must stay in this worktree's .runtime directory")
    verify(args.url.rstrip("/"), args.output.resolve())
