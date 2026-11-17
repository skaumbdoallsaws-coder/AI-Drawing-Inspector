"""Verify MB7 in an isolated real app. Run outside the sandbox; never invoke Sage.

    python tools/verify_model_builder_browser.py --out <evidence-directory>

The chat POST is fulfilled by Playwright. Reference and model upload routes,
catalog registration, placement operations and the 3D renderer are real.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time
import traceback
from urllib.parse import urlsplit

from tools import verify_model_import_chat_browser as base

RECIPE_IDS = ("floor-sign-receiving", "flammable-cabinet-45gal", "eyewash-station")
RECIPE_ROOT = base.ROOT / "ai_inspector/industrial_assets/model_builder/cookbook"
REFERENCE_PATH = base.REFERENCE_PATH
SERVER_REFUSALS = {  # ai_inspector/facility_layout/reference_files.py
    "reference_invalid": "Choose a PNG, JPEG or WebP image, or an enabled PDF.",
    "reference_pdf_disabled": "PDF reading is not enabled; attach a screenshot of the page.",
}
EXPECTED_CHECKS = ("isolated_bootstrap", "baseline_navigation", "reference_menu",
                   "model_ready", "reference_ready", "gif_refused", "pdf_refused",
                   "mixed_send", "three_models_3d", "part_finish_3d", "browser_errors",
                   "no_inference", "cleanup")


def recipe(identifier: str) -> dict:
    base.require(identifier in RECIPE_IDS, "Unknown verifier recipe")
    return json.loads((RECIPE_ROOT / (identifier + ".json")).read_text(encoding="utf-8"))


def placement(asset: dict, placement_id: str, x: float, z: float) -> dict:
    return {"placementId": placement_id, "assetId": asset["assetId"],
            "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "transform": {"position": {"x": x, "y": 0, "z": z},
                          "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1},
            "positionMode": "locked", "snapRelationship": None, "metadata": {}}


def non_print_part(parts: list[dict]) -> str:
    for part in parts:
        if part.get("name") == "cabinet body" and str(part.get("key", "")).startswith("p:"):
            return part["key"]
    raise AssertionError("The cabinet body is absent from the built artifact parts")


def build_and_place(host, binding: dict, data: Path) -> list[dict]:
    """Use real host build, registration and layout operations, all under temp roots."""
    principal = host.principal()
    site, layout = binding["siteId"], binding["layoutId"]
    prepared = []
    for index, identifier in enumerate(RECIPE_IDS):
        saved = host.service.get_layout(principal, site, layout)
        reference = {"siteId": site, "layoutId": layout, "revision": saved["revision"]}
        draft, _ = host.build_model_draft(principal, reference, recipe(identifier))
        base.require(not draft["lints"], identifier + " has build lints: " + str(draft["lints"]))
        asset = host.register_imported_asset(principal, site, layout, draft["draftId"])
        placed = None
        # The saved shell and any zones are authoritative. Let the normal
        # placement preview choose a valid location instead of reproducing it.
        for z in (4, 8, 12, 16, 20):
            for x in (4, 8, 12, 16, 20, 24, 28, 32):
                if any((x-row["x"])**2 + (z-row["z"])**2 < 9 for row in prepared):
                    continue
                candidate = placement(asset, "pl-mb7-" + str(index + 1), x, z)
                operation = {"op": "place_asset", "placementId": candidate["placementId"],
                             "placement": candidate}
                saved = host.service.get_layout(principal, site, layout)
                try:
                    host.service.preview_operations(principal, site, layout, saved["revision"], [operation])
                    host.service.apply_operations(principal, site, layout, saved["revision"], [operation])
                    placed = {"recipeId": identifier, "draftId": draft["draftId"], "assetId": asset["assetId"],
                              "placementId": candidate["placementId"], "x": x, "z": z,
                              "height": draft["dimensions"]["height"]}
                    break
                except Exception as error:
                    if getattr(error, "code", "") not in {"placement_outside_floor", "zone_containment_violation",
                                                             "spatial_conflict", "invalid_placement"}:
                        raise
            if placed:
                break
        base.require(placed is not None, "No valid isolated placement for " + identifier)
        prepared.append(placed)
        if identifier == "flammable-cabinet-45gal":
            saved = host.service.get_layout(principal, site, layout)
            finish = {"representation": "detail", "overrides": [{"key": non_print_part(draft["parts"]),
                       "color": "#2457a8", "roughness": 0.35, "metalness": 0.12}]}
            host.service.apply_operations(principal, site, layout, saved["revision"],
                [{"op": "set_component_materials", "placementId": placed["placementId"], "materials": finish}])
            placed["finishKey"] = finish["overrides"][0]["key"]
        if index == 0:
            source = host._component_visual_root / "generated/industrial_assets/authored/built" / asset["assetId"] / "model.glb"
            base.require(source.is_file(), "Built GLB is absent from the isolated library")
            shutil.copyfile(source, data / "chat-model.glb")
    return prepared


def reference_fixtures(data: Path) -> dict[str, Path]:
    from PIL import Image, ImageDraw
    photo = data / "equipment-photo.png"
    image = Image.new("RGB", (900, 600), "#e7e4de")
    draw = ImageDraw.Draw(image)
    draw.rectangle((180, 100, 710, 520), fill="#bd933f", outline="#354657", width=8)
    draw.rectangle((260, 180, 630, 280), fill="#425b77")
    image.save(photo, format="PNG")
    gif = data / "unsupported.gif"
    gif.write_bytes(bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"))
    pdf = data / "spec-sheet.pdf"
    pdf.write_bytes(b"%PDF-1.7\n% Reference reading is disabled in this verifier.\n")
    return {"photo": photo, "gif": gif, "pdf": pdf}


def capture_chip(page, file: Path, selector: str, evidence: base.Evidence, terminal: set[str]) -> dict:
    page.locator(selector).set_input_files(str(file))
    page.wait_for_function("""value => [...document.querySelectorAll('#agentModelChips .agent-model-chip')].some(
        row => row.querySelector('strong')?.textContent === value.name && value.terminal.includes(row.dataset.state))""",
        arg={"name": file.name, "terminal": sorted(terminal)}, timeout=70000)
    value = base.chip(page, file.name)
    value["states"] = page.evaluate("name => window.__modelImportStates.filter(row => row.name === name)", file.name)
    evidence.data.setdefault("files", {})[file.name] = value
    return value


def remove_chip(page, name: str) -> None:
    row = page.locator("#agentModelChips .agent-model-chip").filter(has=page.locator("strong", has_text=name))
    row.get_by_role("button", name="Remove " + name).click()


def view_model(page, model: dict, evidence: base.Evidence, filename: str, *, quarter: bool = False) -> dict:
    root = page.locator("#trainFacilityLayoutAuthoring")
    root.locator('[data-view="3d"]').click()
    canvas = root.locator(".ip-flw-three-view canvas")
    canvas.wait_for(state="visible", timeout=30000)
    pose = {"x": model["x"], "z": model["z"], "height": model["height"], "quarter": quarter}
    page.evaluate("""pose => {
        const app = window._trainFacilityLayoutAuthoringApp;
        const adapter = app.workspace.threeAdapter;
        const view = adapter.getCameraView();
        const distance = pose.height < 1.2 ? 1.8 : 2.7;
        view.position = {x: pose.x + (pose.quarter ? distance * 0.55 : 0),
            y: pose.height * 0.60 + 0.65, z: pose.z + distance};
        view.target = {x: pose.x, y: pose.height * 0.52, z: pose.z};
        adapter.applyCameraView(view);
    }""", pose)
    page.wait_for_timeout(700)
    target = evidence.out / filename
    canvas.screenshot(path=str(target), animations="disabled", timeout=10000)
    evidence.data["screenshots"].append(filename)
    return {"assetId": model["assetId"], "placementId": model["placementId"],
            "screenshot": str(target), "camera": pose}


def compare_errors_with_refusals(evidence: base.Evidence, base_url: str, binding: dict, refusals: int) -> dict:
    """Chromium logs every 4xx reply to the console. Allow exactly the deliberate GIF and PDF refusals: one
    422 console line per refused upload, no more and no fewer; every other new error still fails."""
    expected = {"kind": "console", "url": base_url + "/api/facility-layouts/" + binding["siteId"] + "/"
                + binding["layoutId"] + "/reference-files",
                "text": "Failed to load resource: the server responded with a status of 422 (Unprocessable Content)"}
    errors = evidence.data["browserErrors"]
    matched = [row for row in errors if row == expected]
    base.require(refusals == 2 and len(matched) == refusals,
                 "Expected one 422 console line per deliberate refusal: " + str({"refusals": refusals,
                                                                                    "lines": len(matched)}))
    evidence.data["browserErrors"] = [row for row in errors if row != expected]
    try:
        return {**base.compare_errors(evidence, base_url), "deliberateRefusalLines": len(matched)}
    finally:
        evidence.data["browserErrors"] = errors


def exercise(browser, base_url: str, binding: dict, files: dict[str, Path], models: list[dict], evidence: base.Evidence):
    context, page = base.browser_page(browser, base_url, evidence, baseline=True)
    try:
        evidence.check("baseline_navigation", lambda: base.navigate(page, base_url, binding, evidence, baseline=True), critical=True)
    finally:
        context.close()
    context, page = base.browser_page(browser, base_url, evidence, baseline=False)
    try:
        base.navigate(page, base_url, binding, evidence, baseline=False)
        responses = []
        def watch(response):
            if REFERENCE_PATH.fullmatch(urlsplit(response.url).path) and response.request.method == "POST":
                # The status is always known; Chromium may already have evicted a small body from its inspector
                # cache by the time this handler runs, so the body is optional evidence.
                row = {"status": response.status, "body": None}
                try:
                    row["body"] = response.json()
                except Exception as error:
                    evidence.data.setdefault("responseBodiesUnavailable", []).append(str(error)[:200])
                responses.append(row)
        page.on("response", watch)
        def menu():
            page.locator("#agentCameraBtn").click()
            item = page.get_by_role("menuitem", name="Attach photo or spec sheet (.png, .jpg, .webp, .pdf)", exact=True)
            item.wait_for(state="visible")
            result = {"name": item.text_content(), "hiddenInput": page.locator("#agentReferenceFileInput").evaluate("el => el.hidden")}
            base.require(result["hiddenInput"], "Reference input is not hidden")
            evidence.shot(page, "02-reference-menu")
            page.locator("#agentCameraBtn").click()
            return result
        evidence.check("reference_menu", menu, critical=True)
        def model_ready():
            result = capture_chip(page, files["model"], "#agentModelFileInput", evidence, {"ready", "refused", "failed"})
            base.require(result["state"] == "ready", "Built GLB did not become ready: " + str(result))
            base.require(base.ordered_states(result["states"], ["uploading", "checking", "ready"]), "Model chip transitions were incomplete")
            evidence.shot(page, "03-model-ready")
            return result
        evidence.check("model_ready", model_ready, critical=True)
        def reference_ready():
            result = capture_chip(page, files["photo"], "#agentReferenceFileInput", evidence, {"ready", "refused", "failed"})
            base.require(result["state"] == "ready", "Reference did not become ready: " + str(result))
            base.require(base.ordered_states(result["states"], ["uploading", "checking", "ready"]), "Reference chip transitions were incomplete")
            base.require(page.locator("#agentModelChips .agent-model-chip-note").count() == 1, "First-use provider note is missing")
            evidence.shot(page, "04-reference-ready")
            return result
        evidence.check("reference_ready", reference_ready, critical=True)
        def refused(file: Path, code: str):
            result = capture_chip(page, file, "#agentReferenceFileInput", evidence, {"ready", "refused", "failed"})
            base.require(result["state"] == "refused" and "Refused:" in result["text"], "Expected a refused chip: " + str(result))
            # Each refusal is one POST. Its code comes from the body, or else from the chip showing the server's
            # own refusal text for that code (the browser never writes these texts itself).
            base.require(responses, "No reference upload response was seen")
            last = responses[-1]
            body_code = ((last["body"] or {}).get("error") or {}).get("code")
            base.require(last["status"] == 422 and (body_code == code or (last["body"] is None and
                         SERVER_REFUSALS[code] in result["text"])), "The server did not return " + code + ": " + str(last))
            evidence.shot(page, "05-" + file.stem + "-refused")
            remove_chip(page, file.name)
            return result
        evidence.check("gif_refused", lambda: refused(files["gif"], "reference_invalid"), critical=True)
        evidence.check("pdf_refused", lambda: refused(files["pdf"], "reference_pdf_disabled"), critical=True)
        def mixed_send():
            page.locator("#agentInput").fill("Review these two attached files.")
            page.locator("#agentSendBtn").click()
            page.wait_for_function("() => document.querySelector('#agentMessages')?.textContent.includes(" + json.dumps(base.SUCCESS_TEXT) + ")")
            page.wait_for_function("() => document.querySelectorAll('#agentModelChips .agent-model-chip').length === 0")
            requests = [row for row in evidence.data["chatRequests"] if row["phase"] == "attachments"]
            base.require(len(requests) == 1, "Expected one intercepted chat POST")
            attachments = requests[0]["attachments"]
            base.require(isinstance(attachments, list) and len(attachments) == 2
                         and [row["kind"] for row in attachments] == ["model-import", "reference-file"]
                         and base.IMPORT_ID.fullmatch(attachments[0]["importId"])
                         and base.re.fullmatch(r"rf-[0-9a-f]{24}", attachments[1]["referenceId"]),
                         "Mixed chat attachment payload is invalid: " + str(attachments))
            return {"attachments": attachments, "path": requests[0]["path"], "chipsCleared": True}
        evidence.check("mixed_send", mixed_send, critical=True)
        def models_3d():
            page.locator("#trainFacilityLayoutAuthoring [data-view='3d']").click()
            page.wait_for_function("""() => window._trainFacilityLayoutAuthoringApp?.workspace?.threeAdapter
                ?.getDiagnostics()?.placementCount >= 3""", timeout=30000)
            shots = [view_model(page, model, evidence, model["recipeId"] + "-3d.png") for model in models]
            return shots
        evidence.check("three_models_3d", models_3d, critical=True)
        def part_finish():
            present = page.evaluate("""model => window._trainFacilityLayoutAuthoringApp.session.getState()
                .layout.placements.some(row => row.placementId === model.placementId &&
                    row.componentMaterials?.overrides?.some(finish => finish.key === model.finishKey))""", models[1])
            base.require(present, "The cabinet's non-print part finish was not saved in the layout")
            return view_model(page, models[1], evidence, "flammable-cabinet-part-finish-3d.png", quarter=True)
        evidence.check("part_finish_3d", part_finish, critical=True)
        evidence.check("browser_errors", lambda: compare_errors_with_refusals(
            evidence, base_url, binding, sum(1 for row in responses if row["status"] == 422)))
    except Exception:
        try:
            evidence.shot(page, "99-mb7-failure")
        except Exception:
            pass
        raise
    finally:
        context.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    evidence = base.Evidence(out)
    old_cwd, old_env, old_temp = Path.cwd(), dict(os.environ), tempfile.tempdir
    temporary = None
    hosts = []
    guard = listener = application = http_server = thread = None
    cache = base.installed_browser_cache()
    try:
        temporary = tempfile.TemporaryDirectory(prefix="model-builder-browser-")
        data = Path(temporary.name).resolve()
        guard = base.RuntimeGuard(data, out, evidence.data["guardViolations"])
        import sys
        sys.addaudithook(guard.audit)
        base.configure_environment(data, cache)
        os.chdir(data / "project")
        with base.hidden_children():
            application, binding = base.import_application(data, evidence, hosts)
            models = build_and_place(application._FACILITY_LAYOUT_HOST, binding, data)
            files = {**reference_fixtures(data), "model": data / "chat-model.glb"}
            import uvicorn
            from playwright.sync_api import sync_playwright
            listener = base.reserve_listener()
            port = listener.getsockname()[1]
            base.require(port not in base.FORBIDDEN_PORTS, "Reserved port is forbidden")
            base_url = "http://127.0.0.1:" + str(port)
            evidence.data["baseUrl"] = base_url
            http_server = uvicorn.Server(uvicorn.Config(application.app, host="127.0.0.1", port=port,
                                                       lifespan="off", log_level="error", access_log=False))
            def serve():
                try:
                    http_server.run(sockets=[listener])
                except BaseException as error:
                    evidence.data["serverError"] = repr(error)
            thread = threading.Thread(target=serve, name="model-builder-browser-server", daemon=True)
            thread.start()
            deadline = time.monotonic() + 30
            while not http_server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.05)
            base.require(http_server.started, "Isolated server failed to start: " + str(evidence.data.get("serverError", "timeout")))
            evidence.result("isolated_bootstrap", True, {"baseUrl": base_url, "models": models})
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader",
                    "--disable-background-networking", "--disable-component-update", "--disable-domain-reliability",
                    "--no-proxy-server"])
                try:
                    exercise(browser, base_url, binding, files, models, evidence)
                finally:
                    browser.close()
    except (Exception, KeyboardInterrupt) as error:
        evidence.data["fatalError"] = {"error": str(error), "traceback": traceback.format_exc()}
        print("FAIL: " + str(error), flush=True)
    finally:
        cleanup_errors = []
        if http_server is not None:
            http_server.should_exit = True
        if thread is not None:
            thread.join(timeout=15)
            if thread.is_alive():
                http_server.force_exit = True
                thread.join(timeout=5)
            if thread.is_alive():
                cleanup_errors.append("Server thread did not stop")
        for host in hosts:
            try:
                host.close()
            except Exception as error:
                cleanup_errors.append("Host close: " + str(error))
        if listener is not None:
            listener.close()
        evidence.result("no_inference", not evidence.data["guardViolations"] and not any(
            row["path"] in base.CHAT_PATHS for row in evidence.data["blockedServerRequests"]),
            {"guardViolations": evidence.data["guardViolations"], "paidInferenceEnabled": False})
        os.chdir(old_cwd)
        if temporary is not None:
            for attempt in range(5):
                gc.collect()
                try:
                    temporary.cleanup()
                    break
                except Exception as error:
                    if attempt == 4:
                        cleanup_errors.append("Temp cleanup: " + str(error))
                    else:
                        time.sleep(.5)
        if guard is not None:
            guard.active = False
        os.environ.clear()
        os.environ.update(old_env)
        tempfile.tempdir = old_temp
        evidence.result("cleanup", not cleanup_errors, {"errors": cleanup_errors})
        completed = {row["name"] for row in evidence.data["checks"]}
        for name in EXPECTED_CHECKS:
            if name not in completed:
                evidence.data["checks"].append({"name": name, "status": "not_run", "detail": "Earlier step failed."})
        evidence.data["passed"] = not evidence.data.get("fatalError") and all(
            row["status"] == "passed" for row in evidence.data["checks"])
        evidence.save()
    print("Report: " + str(out / "report.json"), flush=True)
    return 0 if evidence.data["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
