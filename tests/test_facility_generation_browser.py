"""Opt-in Chromium verification of the real shared workspace and isolated backend.

This uses a synthetic reviewed source and structured tool calls, not a live model
or the complete normal desktop/chat application. No production files are saved.
"""
import json
import os
from pathlib import Path
import socket
import threading
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import pytest
import uvicorn

from tests.test_facility_generation_admission import case
from tests.test_facility_generation_agent import chat, generate
from tests.test_facility_generation_exploration import prepare
from ai_inspector.facility_layout.generation_exploration import PREPARE_TOOL
from tests.test_facility_generation_agent import execute


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.environ.get("INSPECTORPRO_GENERATION_BROWSER_CHECK") != "1", reason="Opt-in native Chromium check")
@pytest.mark.parametrize("source_mode", ["reviewed", "brief"])
def test_shared_workspace_generation_preview(chat, tmp_path, source_mode):
    from playwright.sync_api import sync_playwright
    from PIL import Image
    from io import BytesIO

    host = chat["host"]
    artifacts = ROOT / ".runtime" / "generation-preview-evidence" / tmp_path.parent.name / source_mode
    artifacts.mkdir(parents=True, exist_ok=False)
    app = FastAPI()
    app.include_router(host.create_router())
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    scripts = ["facility_layout_navigation_authoring", "facility_layout_editor", "facility_layout_three_adapter",
        "facility_layout_recorder", "facility_layout_patterns", "facility_layout_command_adapter", "facility_layout_session",
        "facility_layout_transport", "facility_layout_generation_view", "facility_layout_workspace", "facility_layout_app"]
    html = """<!doctype html><meta charset="utf-8"><title>Isolated generation preview check</title>
<link rel="stylesheet" href="/static/facility_layout_workspace.css">
<style>*{box-sizing:border-box}html,body,#trainFacilityLayoutAuthoring{margin:0;width:100%;height:100%;overflow:hidden;font:13px Arial}</style>
<script src="/static/vendor/three/0.128.0/build/three.min.js"></script><div id="trainFacilityLayoutAuthoring"></div>"""
    html += "".join(f'<script src="/static/{name}.js"></script>' for name in scripts)
    html += """<script>window.ready = (async () => {
        const bootstrap = await (await fetch('/api/facility-layout-bootstrap')).json();
        window.app = InspectorProFacilityApp.createFacilityLayoutApp({root: document.getElementById('trainFacilityLayoutAuthoring'),
            siteId: bootstrap.siteId, layoutId: bootstrap.layoutId, initialReceipt: bootstrap.layout,
            assetCatalog: bootstrap.assetCatalog, capabilities: bootstrap.capabilities,
            enableSpatialAdvisory: false, threeRuntime: InspectorProFacilityThree});
        await app.ready;
    })();</script>"""

    @app.get("/")
    def index():
        return HTMLResponse(html)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                page.evaluate("() => window.ready")
                await_state = page.evaluate("() => ({loaded: app.getState().loaded, state: app.session.getState()})")
                assert await_state["loaded"]
                before = await_state["state"]
                page.get_by_title("Generation planning", exact=True).click()
                picker = page.get_by_label("Reviewed generation source", exact=True)
                page.wait_for_function("() => document.querySelector('[aria-label=\"Reviewed generation source\"]').options.length === 2")
                if source_mode == "reviewed":
                    picker.select_option("0")
                reference = page.evaluate("() => app.workspace.generationPlanningView.reference()")
                chat["binding"] = chat["agent"].bind(chat["principal"], site_id=chat["options"]["site_id"],
                    layout_id=chat["options"]["layout_id"], base_revision=chat["ledger"]["baseRevision"], reference=reference)
                if source_mode == "brief":
                    assert reference["sourceContextRef"] is None
                    chat["request"]["proposal"] = json.loads(json.dumps(chat["request"]["proposal"]).replace("synthetic-scenario-v1", "brief-interpretation"))
                    chat["record"] = json.loads(json.dumps(chat["record"]).replace("synthetic-scenario-v1", "brief-interpretation"))
                    proposed = execute(chat, PREPARE_TOOL, prepare(chat))
                    source_ref = proposed["sourceContextRef"]
                else:
                    source_ref = reference["sourceContextRef"]
                receipt, _ = generate(chat)
                summary = {**receipt, "clientTurnId": chat["turn"], "workspaceId": reference["workspaceId"],
                           "sourceContextRef": source_ref}
                page.evaluate("id => app.workspace.generationPlanningView.begin(id)", chat["turn"])
                page.evaluate("summary => app.workspace.generationPlanningView.show(summary)", summary)
                assert page.evaluate("() => app.session.getState()") == before
                assert page.evaluate("() => app.workspace.generationPlanningView.activeLayout().placements.length") == 2
                assert page.evaluate("() => app.workspace.generationPlanningView.reference().sourceContextRef") == source_ref
                if source_mode == "brief":
                    assert page.get_by_text(prepare(chat)["assumptions"][0], exact=True).is_visible()
                    assert page.get_by_text(prepare(chat)["unknowns"][0], exact=True).is_visible()
                captures = []
                for width, height in [(1440, 900), (900, 700), (430, 820)]:
                    page.set_viewport_size({"width": width, "height": height})
                    for mode in ("plan", "3d"):
                        page.evaluate("mode => app.workspace._setViewMode(mode)", mode)
                        if mode == "3d":
                            assert page.evaluate("() => app.workspace._applyThreeOrientation('iso')")
                        page.evaluate("() => app.workspace.executeCommand('fit')")
                        page.wait_for_timeout(350)
                        if mode == "plan":
                            assert page.evaluate("""() => {
                                const scale = document.querySelector('.ip-flw-plan-scale').getBoundingClientRect();
                                const nav = document.querySelector('.ip-flw-plan-navigation').getBoundingClientRect();
                                return scale.bottom <= nav.top || scale.top >= nav.bottom
                                    || scale.right <= nav.left || scale.left >= nav.right;
                            }"""), "Plan scale and navigation controls overlap"
                        filename = f"generation-{width}-{mode}.png"
                        pixels = page.screenshot(path=str(artifacts / filename))
                        image = Image.open(BytesIO(pixels)).convert("RGB")
                        assert len(image.resize((144, 90)).getcolors(144 * 90) or []) > 40
                        if mode == "3d":
                            canvas = page.locator('.ip-flw-three-view canvas').first
                            assert canvas.is_visible()
                            rendered = Image.open(BytesIO(canvas.screenshot())).convert("RGB")
                            assert len(rendered.resize((96, 64)).getcolors(96 * 64) or []) > 20
                            page.evaluate("() => app.workspace.executeCommand('top-view')")
                            page.wait_for_timeout(150)
                            changed = Image.open(BytesIO(canvas.screenshot())).convert("RGB")
                            assert changed.tobytes() != rendered.tobytes(), "3D camera control did not change the rendered scene"
                        captures.append(filename)
                assert page.evaluate("() => app.session.getState()") == before
                page.get_by_role("button", name="Exit planning", exact=True).click()
                assert page.evaluate("() => app.workspace.generationPlanningView.activeLayout()") is None
                assert page.evaluate("() => app.session.getState()") == before
                assert not errors, errors
                (artifacts / "browser-report.json").write_text(json.dumps({"scope": "isolated shared workspace; synthetic source; no live provider",
                    "sourceMode": source_mode, "preview": receipt, "screenshots": captures, "pageErrors": errors, "editorUnchanged": True,
                    "saveCalls": 0}, indent=2), encoding="utf-8")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        assert not thread.is_alive(), "Isolated browser server did not shut down"
