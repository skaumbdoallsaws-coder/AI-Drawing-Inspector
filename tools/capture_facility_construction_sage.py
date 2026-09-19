"""Actual chat, preview, explicit unsaved Apply and Undo on the isolated pilot."""
from __future__ import annotations

import argparse
import json
from io import BytesIO
from pathlib import Path
import time
from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROMPT = (
    "Arrange existing Table A and Table B in a line with a preferred 0.5 m spacing input, "
    "preserving orientation, within a 14 m by 6 m envelope. Attach the existing Device "
    "(the Carr Lane tooling plate) to Table A's published worktop with a 0.05 m inset. "
    "Group both tables and that device as Pilot Cell with 0.2 m envelope padding. "
    "Make three total cells with a linear pattern north at 8 m pitch. Use the existing "
    "equipment, preserve the surface attachments in the copies, and show the complete "
    "construction preview for my approval. Do not apply or save yet."
)


def state(page):
    return page.evaluate("""() => {
        const app = _trainFacilityLayoutAuthoringApp, s = app.session.getState();
        return {baseRevision:s.baseRevision, draftRevision:s.draftRevision, layout:s.layout,
            dirty:s.dirty, history:s.history, historyCursor:s.historyCursor,
            editorGenerationId:s.editorGenerationId, canUndo:s.canUndo,
            construction: app.workspace.constructionPreview && app.workspace.constructionPreview.proposal};
    }""")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:8187")
    parser.add_argument("--output", default=".runtime/construction-sage-pilot/live-1")
    parser.add_argument("--exercise-recovery", action="store_true")
    args = parser.parse_args()
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    prompt = PROMPT
    report = {"prompt": prompt, "pageErrors": [], "failedRequests": [], "chatResponses": [], "saveCalls": [], "approvals": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=1, service_workers="block")
        context.add_init_script("localStorage.setItem('inspectorpro.theme','light')")
        page = context.new_page()
        page.on("pageerror", lambda error: report["pageErrors"].append(str(error)))
        page.on("requestfailed", lambda request: report["failedRequests"].append(request.url))
        def response_received(response):
            if "/api/agent/chat" in response.url:
                try:
                    report["chatResponses"].append(response.json())
                except Exception:
                    report["chatResponses"].append({"status": response.status, "body": response.text()})
            if "/construction/" in response.url and response.url.endswith("/approve-unsaved") and response.ok:
                report["approvals"].append(response.json())
            if (response.request.method == "PUT" and "/api/facility-layouts/" in response.url
                    or response.request.method == "POST" and response.url.endswith("/save")):
                report["saveCalls"].append(response.url)
        page.on("response", response_received)
        try:
            page.goto(args.origin + "/?facilityLayoutId=fl-main&facilityAssets=1&build=construction-sage-pilot", wait_until="load", timeout=120000)
            page.wait_for_function("window.__inspectorProMainScriptReady === true", timeout=120000)
            page.evaluate("""() => { const previous = trainingState.type; trainingState.type='facility_layout';
                trainingState.viewportMode='facility_layout'; _trainApplyTrainingTypeDefaults(previous); switchTab('training'); }""")
            page.wait_for_function("window._trainFacilityLayoutAuthoringApp && _trainFacilityLayoutAuthoringApp.workspace && _trainFacilityLayoutAuthoringApp.session.getState().loaded", timeout=120000)
            report["before"] = state(page)
            page.evaluate("_trainFacilityLayoutAuthoringApp.workspace.closeAssetBrowser(false)")
            page.evaluate("""() => { _trainFacilityLayoutAuthoringApp.session.selectMany(['pl-construction-0','pl-construction-1','pl-construction-2']);
                if(window._setRightDockMode) _setRightDockMode('agent'); else _toggleAgentPanel(); }""")
            page.wait_for_selector("#agentInput", state="visible")
            page.click("#agentChatNewBtn")
            page.evaluate("window._selectAgent('deviation-analyst')")
            page.wait_for_timeout(1000)
            page.screenshot(path=str(output / "01-before.png"))
            def send(message):
                response_start = len(report["chatResponses"])
                count = page.locator('#agentMessages .agent-msg-row.assistant').count()
                page.fill("#agentInput", message)
                page.click("#agentSendBtn")
                page.wait_for_function("count => document.querySelectorAll('#agentMessages .agent-msg-row.assistant').length > count", arg=count, timeout=300000)
                page.wait_for_function("!document.querySelector('#agentMessages .agent-working-row') && !document.querySelector('#agentMessages .agent-stream-pending')", timeout=300000)
                page.wait_for_timeout(500)
                for response in report["chatResponses"][response_start:]:
                    for line in response.get("body", "").splitlines():
                        if line.startswith("data: "):
                            event = json.loads(line[6:])
                            if event.get("event") == "response_error":
                                report["providerError"] = event
                                raise RuntimeError("Provider request failed: " + str(event.get("code")))
            if args.exercise_recovery:
                report["invalidPrompt"] = ("Create a ghost preview using Cell Layout for existing Table A and Table B "
                    "in a line within a 1 m by 1 m envelope, preferred gap 0.5 m, one row, orientation preserved. "
                    "Invoke the preview tool to check the fit. If it fails, report the exact failure. "
                    "Do not substitute a larger envelope, apply, or save.")
                send(report["invalidPrompt"])
                report["invalidAnswer"] = page.locator('#agentMessages .agent-msg-row.assistant').last.inner_text()
                assert state(page)["layout"] == report["before"]["layout"]
                page.screenshot(path=str(output / "01-invalid-refused.png"))
            started = time.monotonic()
            send(prompt)
            report["chatSeconds"] = time.monotonic() - started
            report["answer"] = page.locator("#agentMessages .agent-msg-row.assistant").last.inner_text()
            finals = []
            for response in report["chatResponses"]:
                if response.get("body"):
                    for line in response["body"].splitlines():
                        if line.startswith("data: "):
                            event = json.loads(line[6:])
                            if event.get("event") == "response_completed":
                                finals.append(event["final"])
                else:
                    finals.append(response)
            report["toolTrace"] = [call for final in finals for call in final.get("facility_read_trace", {}).get("calls", [])]
            if args.exercise_recovery:
                assert any(call["tool"] == "preview_facility_cell_layout" and call["status"] == "failed"
                           and call.get("error", {}).get("code") == "facility_construction_compile_failed"
                           and isinstance(call.get("arguments", {}).get("arguments"), dict)
                           and call["arguments"]["arguments"].get("targetBounds") == {"width": 1, "depth": 1}
                           for call in report["toolTrace"]), "No genuine geometric refusal was recorded"
            report["preview"] = state(page)
            page.screenshot(path=str(output / "02-chat-preview.png"))
            assert report["preview"]["construction"], report["answer"]
            assert report["preview"]["layout"] == report["before"]["layout"]
            assert report["preview"]["construction"]["commandCount"] == 4
            candidate = report["preview"]["construction"]["candidateLayout"]
            assert len(candidate["placements"]) == 9 and len(candidate["zones"]) == 3
            page.locator('[data-construction-action="apply"]').click()
            page.wait_for_function("_trainFacilityLayoutAuthoringApp.session.getState().dirty && !_trainFacilityLayoutAuthoringApp.session.getState().busy")
            report["applied"] = state(page)
            assert report["applied"]["layout"] == candidate
            assert len(report["applied"]["history"]) == 1
            approval = report["approvals"][-1]
            page.evaluate("approval => _trainFacilityLayoutAuthoringApp.session.installConstructionApproval(approval)", approval)
            assert state(page) == report["applied"]
            report["duplicateApprovalWasNoop"] = True
            for cell in candidate["zones"]:
                inside = [p for p in candidate["placements"] if p.get("snapRelationship")
                          and p["transform"]["position"]["z"] >= min(v["z"] for v in cell["boundary"])
                          and p["transform"]["position"]["z"] <= max(v["z"] for v in cell["boundary"])]
                assert len(inside) == 1
                support = next(p for p in candidate["placements"] if p["placementId"] == inside[0]["snapRelationship"]["supportPlacementId"])
                assert abs(support["transform"]["position"]["z"] - inside[0]["transform"]["position"]["z"]) < 1
            report["attachmentsRemapped"] = True
            page.screenshot(path=str(output / "03-unsaved-plan.png"))
            page.locator('#trainFacilityLayoutAuthoring [data-view="3d"]').click()
            page.wait_for_timeout(8000)
            page.screenshot(path=str(output / "04-unsaved-3d.png"))
            report["threeDiagnostics"] = page.evaluate("_trainFacilityLayoutAuthoringApp.workspace.threeAdapter.getDiagnostics()")
            canvas = page.locator('#trainFacilityLayoutAuthoring canvas').filter(visible=True).first
            pixels = Image.open(BytesIO(canvas.screenshot())).convert("RGB")
            report["canvasPixelStddev"] = ImageStat.Stat(pixels).stddev
            assert max(report["canvasPixelStddev"]) > 8
            page.evaluate("() => { _setRightDockMode(null); _toggleLeftPanel(); _trainFacilityLayoutAuthoringApp.session.clearSelection(); }")
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.wait_for_timeout(500)
            page.screenshot(path=str(output / "05-wide-3d.png"))
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(500)
            page.evaluate("_trainFacilityLayoutAuthoringApp.workspace.controller.fit()")
            page.wait_for_timeout(500)
            page.screenshot(path=str(output / "06-narrow-3d.png"))
            report["narrowCanvasBounds"] = canvas.bounding_box()
            assert report["narrowCanvasBounds"]["width"] > 150
            pixels = Image.open(BytesIO(canvas.screenshot())).convert("RGB")
            report["narrowCanvasPixelStddev"] = ImageStat.Stat(pixels).stddev
            assert max(report["narrowCanvasPixelStddev"]) > 8
            awaitable = "_trainFacilityLayoutAuthoringApp.session.undo()"
            page.evaluate(awaitable)
            report["undone"] = state(page)
            assert report["undone"]["layout"] == report["before"]["layout"]
            assert report["undone"]["draftRevision"] == report["before"]["draftRevision"]
            report["oldApprovalAfterUndo"] = page.evaluate("""async approval => {
                try { await _trainFacilityLayoutAuthoringApp.session.installConstructionApproval(approval); return 'unexpected_success'; }
                catch (error) { return error.code; }
            }""", approval)
            assert report["oldApprovalAfterUndo"] == "facility_command_stale"
            saved = page.request.get(args.origin + "/api/facility-layouts/site-local/fl-main").json()
            assert saved["revision"] == report["before"]["baseRevision"]
            report["savedRevisionAfter"] = saved["revision"]
            assert not report["saveCalls"] and not report["pageErrors"] and not report["failedRequests"]
            report["passed"] = True
        except Exception as error:
            report["passed"] = False
            report["error"] = str(error)
            page.screenshot(path=str(output / "failure.png"))
            raise
        finally:
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            browser.close()
    print(json.dumps({"passed": report["passed"], "seconds": report.get("chatSeconds"), "output": str(output)}))


if __name__ == "__main__":
    main()
