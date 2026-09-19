"""Browser proof for the CAD-grounded Documentation Workspace."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from parts_manual_smoke_support import IsolatedPartsManualServer


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".runtime" / "parts_manual_documentation_workspace_proof"
OUT.mkdir(parents=True, exist_ok=True)
ASSEMBLY = "tricycle"


def _approve_semantic_plan(request, app_url: str) -> dict:
    initial = request.get(f"{app_url}/api/parts-manual/{ASSEMBLY}").json()
    proposal = request.get(
        f"{app_url}/api/parts-manual/{ASSEMBLY}/proposal"
    ).json()["proposal"]
    ready = [row for row in proposal["candidates"] if row.get("status") == "ready"]
    response = request.post(
        f"{app_url}/api/parts-manual/{ASSEMBLY}/proposals/"
        f"{proposal['proposalRevision']}/approve",
        data={
            "baseRevision": initial["revision"],
            "sourceRevision": initial["sourceRevision"],
            "candidateIds": [row["candidateId"] for row in ready],
        },
    )
    if not response.ok:
        raise RuntimeError(f"could not approve semantic manual plan: {response.text()}")
    return response.json()


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report: dict[str, object] = {
        "checks": {},
        "browserErrors": [],
        "consoleErrors": [],
        "failedResponses": [],
    }

    def record(name: str, ok: bool, detail=None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if not ok else ""))

    server = IsolatedPartsManualServer(ROOT, OUT, ASSEMBLY)
    try:
        server.start()
        report["appUrl"] = server.app_url
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1720, "height": 1080})
            page = context.new_page()
            request = playwright.request.new_context(base_url=server.app_url, timeout=120_000)
            page.on("pageerror", lambda error: report["browserErrors"].append(str(error)))
            page.on(
                "console",
                lambda message: report["consoleErrors"].append(message.text)
                if message.type == "error"
                else None,
            )
            page.on(
                "response",
                lambda response: report["failedResponses"].append(
                    {"status": response.status, "url": response.url}
                )
                if response.status >= 400 and "/api/parts-manual/" in response.url
                else None,
            )

            approval = _approve_semantic_plan(request, server.app_url)
            plan_before = server.plan_path.read_bytes()
            baseline_document = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/document"
            ).json()["document"]

            page.goto(
                f"{server.app_url}/?assemblyProfile={ASSEMBLY}",
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            page.wait_for_function(
                """assembly => Boolean(
                    window.__compareDbg
                    && window.__compareDbg.state.partNumber === assembly
                    && window.__compareDbg.state.assyLiveScene
                    && window.__compareDbg.state.assyOccurrenceMeshMap
                )""",
                arg=ASSEMBLY,
                timeout=90_000,
            )
            page.get_by_role("button", name="Parts Manual", exact=True).click()
            workspace = page.locator("#documentationWorkspace")
            workspace.wait_for(state="visible", timeout=120_000)
            page.wait_for_function(
                """() => Boolean(
                    window.__compareDbg.state.partsManualDocumentation
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=30_000,
            )
            record(
                "workspace_opens_without_browser_errors",
                not report["browserErrors"]
                and not any(
                    token in message
                    for message in report["consoleErrors"]
                    for token in ("ReferenceError", "SyntaxError", "TypeError")
                ),
                {
                    "pageErrors": report["browserErrors"],
                    "consoleErrors": report["consoleErrors"],
                },
            )
            record(
                "workspace_has_expected_figure_and_tool_surfaces",
                workspace.locator(".documentation-page-item").count() == 8
                and page.locator("#documentationUndoRibbon").count() == 1
                and page.locator("#documentationRedoRibbon").count() == 1
                and workspace.locator("#documentationProperties").count() == 1,
                {
                    "figureCount": workspace.locator(".documentation-page-item").count(),
                },
            )
            record(
                "live_cad_viewport_is_mounted_in_documentation_stage",
                workspace.locator(
                    ".documentation-canvas-host > #assy-3d-container"
                ).count() == 1
                and workspace.locator("#assy-3d-container .three-toolbar:visible").count() == 0
                and page.locator("body.documentation-workspace-active").count() == 1,
            )
            page.screenshot(path=str(OUT / "documentation_workspace_overview.png"), full_page=True)

            frame_group = workspace.locator(".documentation-target-row").filter(
                has_text="Frame and Seat Assembly"
            ).first
            frame_group.click()
            workspace.locator(".documentation-move-pad .south").click()
            page.wait_for_function(
                """() => Boolean(
                    window.__compareDbg.state.partsManualDocumentation?.canUndo
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=30_000,
            )
            moved_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()
            overview = next(
                row
                for row in moved_scene["document"]["pages"]
                if row["pageType"] == "assembly_overview"
            )
            frame_item = next(
                row
                for row in overview["manualGroupItems"]
                if row["name"] == "Frame and Seat Assembly"
            )
            group_override = moved_scene["scene"]["pages"][overview["pageId"]][
                "manualGroupOverrides"
            ][frame_item["sectionId"]]
            record(
                "group_move_persists_as_documentation_only_override",
                any(abs(float(value)) > 1e-8 for value in group_override["translation"])
                and server.plan_path.read_bytes() == plan_before,
                group_override,
            )

            page.locator("#documentationUndoRibbon").click()
            page.wait_for_function(
                """() => Boolean(
                    window.__compareDbg.state.partsManualDocumentation?.canRedo
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=30_000,
            )
            undone_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            record(
                "undo_restores_generated_group_pose",
                overview["pageId"] not in undone_scene["pages"],
                undone_scene["pages"],
            )
            page.locator("#documentationRedoRibbon").click()
            page.wait_for_function(
                """() => Boolean(
                    window.__compareDbg.state.partsManualDocumentation?.canUndo
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=30_000,
            )

            front_page_button = workspace.locator(".documentation-page-item").filter(
                has_text="Front Steering and Wheel Assembly"
            )
            front_page_button.click()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && document.querySelectorAll('#documentationProperties .documentation-target-row').length > 2
                )""",
                timeout=30_000,
            )
            pedal_targets = workspace.locator(".documentation-target-row").filter(has_text="Pedal")
            record(
                "repeated_pedals_remain_individually_selectable",
                pedal_targets.count() == 2,
                {"pedalTargetCount": pedal_targets.count()},
            )
            pedal_targets.first.click()
            workspace.locator(".documentation-move-pad .west").click()
            page.wait_for_function(
                """() => !document.querySelector('#documentationWorkspace.busy')""",
                timeout=30_000,
            )
            composed_document = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/document"
            ).json()["document"]
            front_page = next(
                row
                for row in composed_document["pages"]
                if row.get("title") == "Front Steering and Wheel Assembly"
            )
            pedal_bom = next(
                row for row in front_page["bom"] if row.get("description") == "Pedal"
            )
            record(
                "moving_one_repeated_occurrence_preserves_one_bom_item_qty_two",
                pedal_bom["quantity"] == 2
                and len(pedal_bom["occurrenceIds"]) == 2
                and composed_document["documentRevision"]
                != baseline_document["documentRevision"],
                pedal_bom,
            )
            record(
                "composition_edits_leave_manual_plan_unchanged",
                server.plan_path.read_bytes() == plan_before,
            )
            page.screenshot(path=str(OUT / "documentation_workspace_component.png"), full_page=True)
            page.set_viewport_size({"width": 680, "height": 900})
            page.wait_for_timeout(2_000)
            responsive = page.evaluate(
                """() => {
                    const workspace = document.querySelector('#documentationWorkspace');
                    const toolbar = workspace?.querySelector('.documentation-toolbar');
                    const rail = workspace?.querySelector('.documentation-page-rail');
                    const properties = workspace?.querySelector('.documentation-properties');
                    const guide = workspace?.querySelector('.documentation-viewport-guide');
                    const assemblyContainer = document.querySelector('#assy-3d-container');
                    const rendererCanvas = assemblyContainer?.querySelector('canvas:not(.orientation-gizmo)');
                    const guideRect = guide?.getBoundingClientRect();
                    const probeX = (guideRect?.left || 0) + 20;
                    const probeY = (guideRect?.top || 0) + 20;
                    const rect = value => value?.getBoundingClientRect();
                    return {
                        viewportWidth: window.innerWidth,
                        bodyScrollWidth: document.documentElement.scrollWidth,
                        workspace: rect(workspace),
                        toolbar: rect(toolbar),
                        rail: rect(rail),
                        properties: rect(properties),
                        guide: rect(guide),
                        assemblyContainer: rect(assemblyContainer),
                        rendererCanvas: rect(rendererCanvas),
                        rendererBuffer: rendererCanvas ? {
                            width: rendererCanvas.width,
                            height: rendererCanvas.height,
                            clientWidth: rendererCanvas.clientWidth,
                            clientHeight: rendererCanvas.clientHeight,
                        } : null,
                        rendererViewport: window.__compareDbg.state.assyRenderer
                            ? window.__compareDbg.state.assyRenderer.getViewport(new THREE.Vector4()).toArray()
                            : null,
                        rendererSize: window.__compareDbg.state.assyRenderer
                            ? window.__compareDbg.state.assyRenderer.getSize(new THREE.Vector2()).toArray()
                            : null,
                        rendererScissor: window.__compareDbg.state.assyRenderer
                            ? window.__compareDbg.state.assyRenderer.getScissor(new THREE.Vector4()).toArray()
                            : null,
                        rendererScissorTest: window.__compareDbg.state.assyRenderer
                            ? window.__compareDbg.state.assyRenderer.getScissorTest()
                            : null,
                        glViewport: window.__compareDbg.state.assyRenderer
                            ? Array.from(window.__compareDbg.state.assyRenderer.getContext().getParameter(
                                window.__compareDbg.state.assyRenderer.getContext().VIEWPORT
                            ))
                            : null,
                        glScissor: window.__compareDbg.state.assyRenderer
                            ? Array.from(window.__compareDbg.state.assyRenderer.getContext().getParameter(
                                window.__compareDbg.state.assyRenderer.getContext().SCISSOR_BOX
                            ))
                            : null,
                        glScissorTest: window.__compareDbg.state.assyRenderer
                            ? window.__compareDbg.state.assyRenderer.getContext().isEnabled(
                                window.__compareDbg.state.assyRenderer.getContext().SCISSOR_TEST
                            )
                            : null,
                        rendererAutoClear: window.__compareDbg.state.assyRenderer?.autoClear,
                        guideStyle: guide ? {
                            background: getComputedStyle(guide).background,
                            backgroundColor: getComputedStyle(guide).backgroundColor,
                        } : null,
                        elementsAtGuideProbe: document.elementsFromPoint(probeX, probeY).map(
                            element => `${element.tagName.toLowerCase()}#${element.id || ''}.${element.className || ''}`
                        ),
                        coveringElements: Array.from(document.querySelectorAll('body *'))
                            .filter(element => {
                                const bounds = element.getBoundingClientRect();
                                return bounds.width > 0 && bounds.height > 0
                                    && probeX >= bounds.left && probeX <= bounds.right
                                    && probeY >= bounds.top && probeY <= bounds.bottom;
                            })
                            .map(element => {
                                const style = getComputedStyle(element);
                                const bounds = element.getBoundingClientRect();
                                return {
                                    element: `${element.tagName.toLowerCase()}#${element.id || ''}.${element.className || ''}`,
                                    background: style.background,
                                    opacity: style.opacity,
                                    pointerEvents: style.pointerEvents,
                                    position: style.position,
                                    zIndex: style.zIndex,
                                    rect: { left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height },
                                };
                            }),
                    };
                }"""
            )
            record(
                "workspace_reflows_without_panel_overlap_at_narrow_width",
                responsive["bodyScrollWidth"] <= responsive["viewportWidth"]
                and responsive["guide"]["width"] > 300
                and responsive["rail"]["bottom"] <= responsive["guide"]["top"]
                and responsive["guide"]["bottom"] <= responsive["properties"]["top"],
                responsive,
            )
            page.screenshot(path=str(OUT / "documentation_workspace_narrow.png"), full_page=True)
            record(
                "no_failed_parts_manual_requests",
                not report["failedResponses"],
                report["failedResponses"],
            )
            record(
                "semantic_plan_remains_complete",
                len(approval.get("sections", [])) == 3,
                {"sectionCount": len(approval.get("sections", []))},
            )
            request.dispose()
            browser.close()
    except Exception as exc:
        report["fatalError"] = str(exc)
        print(f"FAIL fatal :: {exc}")
    finally:
        server.stop()

    passed = all(row.get("ok") for row in report["checks"].values())
    report["passed"] = bool(passed) and "fatalError" not in report
    (OUT / "documentation_workspace_proof.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
