"""Browser proof for the first-class Documentation workflow."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from PIL import Image

from parts_manual_smoke_support import IsolatedPartsManualServer


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".runtime" / "parts_manual_documentation_workflow_proof"
ASSEMBLY = "tricycle"


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report: dict[str, object] = {
        "checks": {},
        "failureClassifications": {
            "direct_entry_generates_a_complete_semantic_baseline": {
                "classification": "obsolete_test_expectation",
                "rootCause": (
                    "Documentation entry intentionally opens a blank authoring workspace; "
                    "AI Arrange is the explicit baseline-generation action."
                ),
            },
            "documentation_technical_preview_uses_retina_resolution": {
                "classification": "test_assertion_defect",
                "rootCause": (
                    "The old assertion divided the backing buffer by a CSS-transformed "
                    "canvas rectangle. The renderer pixel ratio and backing-buffer density "
                    "are the applicable preview contract; print capture is independently "
                    "rendered at publication resolution."
                ),
            },
            "editor_has_page_rail_landscape_canvas_and_properties": {
                "classification": "cascade_from_missing_generation_step",
                "rootCause": "The stale test inspected thumbnails before invoking AI Arrange.",
            },
            "publication_canvas_uses_pdf_page_geometry": {
                "classification": "cascade_from_missing_generation_step",
                "rootCause": "The stale test inspected the intentionally blank page surface.",
            },
        },
        "browserErrors": [],
        "consoleErrors": [],
        "failedResponses": [],
        "allHttpFailures": [],
        "expectedUnavailableResponses": [],
        "unexpectedHttpFailures": [],
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
            request = playwright.request.new_context(base_url=server.app_url, timeout=180_000)

            def open_documentation_inspector() -> None:
                if page.locator("#documentationInspectorRibbon").is_visible():
                    page.locator("#documentationInspectorRibbon").click()
                    return
                page.locator("#documentationOverflowMenuRibbon").click()
                page.locator(
                    '.documentation-overflow-section[data-overflow-group="workspace"] '
                    '.documentation-menu-item',
                    has_text="Inspector",
                ).click()

            page.on("pageerror", lambda error: report["browserErrors"].append(str(error)))
            page.on(
                "console",
                lambda message: report["consoleErrors"].append(message.text)
                if message.type == "error"
                else None,
            )
            def observe_response(response) -> None:
                if response.status < 400:
                    return
                failure = {"status": response.status, "url": response.url}
                report["allHttpFailures"].append(failure)
                if "/api/parts-manual/" in response.url:
                    report["failedResponses"].append(failure)
                path = urlsplit(response.url).path
                expected_unavailable = (
                    response.status == 503
                    and path == "/api/agent/conversations"
                ) or (
                    response.status == 404
                    and path in {
                        f"/api/drawing-map/{ASSEMBLY}",
                        f"/api/drawing-pdf/{ASSEMBLY}",
                        f"/api/part-features/{ASSEMBLY}",
                    }
                )
                target = (
                    report["expectedUnavailableResponses"]
                    if expected_unavailable
                    else report["unexpectedHttpFailures"]
                )
                target.append(failure)

            page.on("response", observe_response)

            initial = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}"
            ).json()
            record(
                "fixture_starts_without_a_manual_baseline",
                initial["publicationReadiness"]["status"] != "PASS",
                initial["publicationReadiness"],
            )

            page.goto(
                f"{server.app_url}/?assemblyProfile={ASSEMBLY}",
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            page.wait_for_function(
                """assembly => Boolean(
                    window.__compareDbg?.state.partNumber === assembly
                    && window.__compareDbg.state.assyLiveScene
                    && window.__compareDbg.state.assyOccurrenceMeshMap
                )""",
                arg=ASSEMBLY,
                timeout=90_000,
            )

            page.evaluate("() => window.__compareDbg.openDocumentationWorkflow()")
            workspace = page.locator("#documentationWorkspace")
            workspace.wait_for(state="visible", timeout=120_000)
            page.wait_for_function(
                """() => Boolean(
                    document.querySelector('#documentationWorkspace.workflow-mode')
                    && window.__compareDbg.state.partsManualDocumentation
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=120_000,
            )

            entry_snapshot = page.evaluate(
                "window.__compareDbg.documentationGenerationSnapshot()"
            )
            current = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}"
            ).json()
            record(
                "direct_entry_opens_a_blank_authoring_workspace",
                entry_snapshot["blank"]
                and entry_snapshot["visiblePageCount"] == 0
                and current["publicationReadiness"]["status"] != "PASS",
                {
                    "generation": entry_snapshot,
                    "readiness": current["publicationReadiness"],
                    "sections": [row["name"] for row in current["plan"]["sections"]],
                },
            )

            page.evaluate(
                """() => {
                    window.__documentationBaselineResult = { status: 'running' };
                    window.__documentationBaselinePromise = window.__compareDbg
                        .startDocumentationBaseline()
                        .then(value => {
                            window.__documentationBaselineResult = {
                                status: 'fulfilled',
                                value,
                            };
                            return value;
                        })
                        .catch(error => {
                            window.__documentationBaselineResult = {
                                status: 'rejected',
                                message: String(error?.message || error),
                                stack: String(error?.stack || ''),
                            };
                            return null;
                        });
                }"""
            )
            page.wait_for_function(
                """() => window.__compareDbg.documentationGenerationSnapshot()
                    .generationState === 'running'""",
                timeout=30_000,
            )
            page.wait_for_function(
                """() => {
                    const value = window.__compareDbg.documentationGenerationSnapshot();
                    const result = window.__documentationBaselineResult;
                    return result?.status === 'rejected'
                        || (value.generationState === 'complete'
                            && !value.working
                            && value.visiblePageCount === value.totalPageCount);
                }""",
                timeout=180_000,
            )
            page.evaluate("() => window.__documentationBaselinePromise")
            generation_snapshot = page.evaluate(
                "window.__compareDbg.documentationGenerationSnapshot()"
            )
            generation_result = page.evaluate(
                "window.__documentationBaselineResult"
            )
            if generation_result.get("status") == "rejected":
                raise AssertionError(
                    "Documentation baseline generation failed: "
                    f"{generation_result}; snapshot={generation_snapshot}"
                )
            current = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}"
            ).json()
            record(
                "ai_arrange_generates_a_complete_semantic_baseline",
                current["publicationReadiness"]["status"] == "PASS"
                and float(current["publicationReadiness"]["coveragePercent"]) == 100.0
                and len(current["plan"]["sections"]) == 3
                and generation_snapshot["visiblePageCount"] == 8,
                {
                    "readiness": current["publicationReadiness"],
                    "sections": [row["name"] for row in current["plan"]["sections"]],
                    "generation": generation_snapshot,
                },
            )
            front_page_id = page.evaluate(
                """() => window.__compareDbg.state.partsManualDocumentation.document.pages
                    .find(value => value.title === 'Front Steering and Wheel Assembly')?.pageId"""
            )
            front_phases = [
                row["phase"]
                for row in generation_snapshot["events"]
                if row.get("type") == "page_phase"
                and row.get("pageId") == front_page_id
            ]
            compressed_front_phases = []
            for phase in front_phases:
                if not compressed_front_phases or compressed_front_phases[-1] != phase:
                    compressed_front_phases.append(phase)
            record(
                "progressive_reveal_uses_the_complete_ordered_phase_sequence",
                compressed_front_phases
                == [
                    "shell", "title", "illustration", "tableHeader",
                    "rows", "annotations", "settled",
                ]
                and not generation_snapshot.get("pagePhase"),
                {
                    "pageId": front_page_id,
                    "phases": compressed_front_phases,
                },
            )
            record(
                "parts_manual_opens_the_editor_without_planner_windows",
                page.locator("#partsManualOverlay").count() == 0
                and page.locator("#manualDocumentPreviewOverlay").count() == 0
                and workspace.locator(".documentation-toolbar:visible").count() == 0,
            )
            page.locator(
                '.documentation-page-item[title="Complete Tricycle Assembly"]'
            ).click(timeout=120_000)
            page.wait_for_function(
                """() => document.querySelector(
                    '#documentationPublicationSurface .documentation-page-header-title'
                )?.textContent.includes('FIGURE 1-1')""",
                timeout=120_000,
            )
            preview_resolution = page.evaluate(
                """() => {
                    const canvas = document.querySelector(
                        '#documentationIllustrationFrame #assy-3d-container canvas:not(.orientation-gizmo)'
                    );
                    const rect = canvas?.getBoundingClientRect();
                    return {
                        cssWidth: rect?.width || 0,
                        cssHeight: rect?.height || 0,
                        bufferWidth: canvas?.width || 0,
                        bufferHeight: canvas?.height || 0,
                        ratioX: rect?.width ? canvas.width / rect.width : 0,
                        ratioY: rect?.height ? canvas.height / rect.height : 0,
                        rendererPixelRatio:
                            window.__compareDbg.state.assyRenderer?.getPixelRatio?.() || 0,
                        devicePixelRatio: window.devicePixelRatio || 1,
                    };
                }"""
            )
            record(
                "documentation_technical_preview_uses_a_high_density_backing_buffer",
                preview_resolution["rendererPixelRatio"] >= 2
                and preview_resolution["bufferWidth"] > 0
                and preview_resolution["bufferHeight"] > 0
                and preview_resolution["ratioX"] >= 1.5
                and preview_resolution["ratioY"] >= 1.5,
                preview_resolution,
            )
            record(
                "documentation_is_selected_in_the_workflow_dropdown",
                page.locator("#trainingTypeRibbonSelect").input_value() == "documentation",
            )
            required_ribbon_ids = [
                "documentationBaselineRibbon",
                "documentationUndoRibbon",
                "documentationRedoRibbon",
                "documentationFitRibbon",
                "documentationCaptureRibbon",
                "documentationCaptureAllRibbon",
                "documentationPublishRibbon",
            ]
            record(
                "documentation_has_a_dedicated_main_ribbon",
                all(page.locator(f"#{value}").count() == 1 for value in required_ribbon_ids),
                required_ribbon_ids,
            )
            ribbon_hierarchy = page.evaluate(
                """() => {
                    const measure = id => {
                        const button = document.getElementById(id);
                        const icon = button?.querySelector(
                            '.documentation-command-icon, .documentation-system-icon'
                        );
                        const rect = button?.getBoundingClientRect();
                        const iconRect = icon?.getBoundingClientRect();
                        return {
                            size: button?.dataset.documentationRibbonSize || null,
                            width: rect?.width || 0,
                            height: rect?.height || 0,
                            iconWidth: iconRect?.width || 0,
                        };
                    };
                    const ribbon = document.querySelector('.documentation-workflow-ribbon');
                    return {
                        ribbonHeight: ribbon?.getBoundingClientRect().height || 0,
                        horizontalOverflow: ribbon
                            ? Math.max(0, ribbon.scrollWidth - ribbon.clientWidth) : 0,
                        generate: measure('documentationBaselineRibbon'),
                        refresh: measure('documentationRefreshRibbon'),
                        undo: measure('documentationUndoRibbon'),
                        capture: measure('documentationCaptureRibbon'),
                        view: measure('documentationViewMenuRibbon'),
                        publish: measure('documentationPublishRibbon'),
                    };
                }"""
            )
            record(
                "documentation_ribbon_uses_mixed_command_hierarchy_without_overflow",
                ribbon_hierarchy["ribbonHeight"] == 107
                and ribbon_hierarchy["horizontalOverflow"] == 0
                and ribbon_hierarchy["generate"]["size"] == "large"
                and ribbon_hierarchy["generate"]["iconWidth"] >= 40
                and ribbon_hierarchy["refresh"]["size"] == "medium"
                and ribbon_hierarchy["refresh"]["iconWidth"] >= 29
                and ribbon_hierarchy["undo"]["size"] == "compact"
                and ribbon_hierarchy["undo"]["iconWidth"] >= 20
                and ribbon_hierarchy["capture"]["size"] == "large"
                and ribbon_hierarchy["view"]["size"] == "compact"
                and ribbon_hierarchy["publish"]["size"] == "large",
                ribbon_hierarchy,
            )
            authoring_chrome = page.evaluate(
                """() => ({
                    tabs: [...document.querySelectorAll('.documentation-ribbon-tab')]
                        .map(node => node.textContent.trim()),
                    menuTriggers: document.querySelectorAll(
                        '.documentation-ribbon-menu-trigger'
                    ).length,
                    splitters: document.querySelectorAll(
                        '.documentation-panel-splitter'
                    ).length,
                    hasZoom: Boolean(document.querySelector('#documentationZoomRange')),
                    hasInspector: Boolean(document.querySelector('#documentationProperties')),
                    inspectorOpen: document.querySelector('#documentationWorkspace')
                        ?.classList.contains('inspector-open') || false,
                    inspectorHidden: document.querySelector('#documentationProperties')
                        ?.getAttribute('aria-hidden'),
                    hasInspectorToggle: Boolean(
                        document.querySelector('#documentationInspectorRibbon')
                    ),
                })"""
            )
            record(
                "documentation_uses_one_grouped_ribbon_and_on_demand_inspector",
                authoring_chrome["tabs"] == []
                and authoring_chrome["menuTriggers"] >= 5
                and authoring_chrome["splitters"] == 1
                and authoring_chrome["hasZoom"]
                and authoring_chrome["hasInspector"]
                and not authoring_chrome["inspectorOpen"]
                and authoring_chrome["inspectorHidden"] == "true"
                and authoring_chrome["hasInspectorToggle"],
                authoring_chrome,
            )
            open_documentation_inspector()
            inspector_open = page.evaluate(
                """() => ({
                    open: document.querySelector('#documentationWorkspace')
                        ?.classList.contains('inspector-open') || false,
                    hidden: document.querySelector('#documentationProperties')
                        ?.getAttribute('aria-hidden'),
                    visible: Boolean(document.querySelector(
                        '#documentationProperties .documentation-inspector-close'
                    )),
                })"""
            )
            page.locator(".documentation-inspector-close").click()
            inspector_closed = page.locator("#documentationProperties").get_attribute(
                "aria-hidden"
            )
            record(
                "documentation_inspector_opens_and_closes_only_on_command",
                inspector_open == {"open": True, "hidden": "false", "visible": True}
                and inspector_closed == "true",
                {"opened": inspector_open, "closedAriaHidden": inspector_closed},
            )
            original_page_id = page.evaluate(
                "() => window.__compareDbg.state.partsManualDocumentationPageId"
            )
            first_page = page.locator(
                "#documentationPageList .documentation-page-item"
            ).first
            first_page.click()
            page.wait_for_function(
                "() => !document.querySelector('#documentationWorkspace.busy')",
                timeout=120_000,
            )
            wheel_before = page.evaluate(
                """() => ({
                    pageId: window.__compareDbg.state.partsManualDocumentationPageId,
                    pageNumber: Number(document.querySelector(
                        '#documentationPageList .documentation-page-item.active .documentation-page-number'
                    )?.textContent || 0),
                    enabled: document.querySelector('.documentation-canvas-stage')
                        ?.dataset.pageWheelNavigation,
                })"""
            )
            page.locator(".documentation-canvas-stage").hover()
            page.mouse.wheel(0, 120)
            page.wait_for_function(
                """before => !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentationPageId !== before""",
                arg=wheel_before["pageId"],
                timeout=120_000,
            )
            wheel_after = page.evaluate(
                """() => ({
                    pageId: window.__compareDbg.state.partsManualDocumentationPageId,
                    pageNumber: Number(document.querySelector(
                        '#documentationPageList .documentation-page-item.active .documentation-page-number'
                    )?.textContent || 0),
                })"""
            )
            record(
                "documentation_canvas_wheel_advances_exactly_one_page",
                wheel_before["enabled"] == "true"
                and wheel_after["pageNumber"] == wheel_before["pageNumber"] + 1,
                {"before": wheel_before, "after": wheel_after},
            )
            if original_page_id:
                page.locator(
                    f'#documentationPageList .documentation-page-item[data-page-id="{original_page_id}"]'
                ).click()
                page.wait_for_function(
                    "() => !document.querySelector('#documentationWorkspace.busy')",
                    timeout=120_000,
                )
            align_trigger = page.locator("#documentationAlignMenuRibbon")
            if align_trigger.is_visible():
                align_trigger.click()
                align_menu = page.locator(
                    "#documentationAlignMenuRibbon + .documentation-ribbon-menu"
                )
                align_visible = align_menu.is_visible()
                align_items = align_menu.locator(".documentation-menu-item").count()
            else:
                page.locator("#documentationOverflowMenuRibbon").click()
                align_menu = page.locator(
                    '.documentation-overflow-section[data-overflow-group="arrange"]'
                )
                align_visible = align_menu.is_visible()
                align_items = align_menu.locator(
                    ".documentation-menu-item"
                ).evaluate_all(
                    "rows => rows.filter(row => row.textContent.trim().startsWith('Align:')).length"
                )
            page.screenshot(path=OUT / "documentation_align_gallery.png")
            if align_trigger.is_visible():
                align_trigger.click()
            else:
                page.locator("#documentationOverflowMenuRibbon").click()

            page.locator("#documentationViewMenuRibbon").click()
            view_menu = page.locator(
                "#documentationViewMenuRibbon + .documentation-ribbon-menu"
            )
            view_visible = view_menu.is_visible()
            view_items = view_menu.locator(".documentation-menu-item").count()
            page.screenshot(path=OUT / "documentation_view_gallery.png")
            page.locator("#documentationViewMenuRibbon").click()

            page.locator("#documentationShapesMenuRibbon").click()
            shapes_menu = page.locator(
                "#documentationShapesMenuRibbon + .documentation-ribbon-menu"
            )
            shapes_visible = shapes_menu.is_visible()
            shape_items = shapes_menu.locator(".documentation-menu-item").count()
            page.screenshot(path=OUT / "documentation_shapes_gallery.png")
            page.locator("#documentationShapesMenuRibbon").click()
            record(
                "documentation_dropdown_galleries_are_visible_and_structured",
                align_visible
                and align_items == 8
                and view_visible
                and view_items >= 7
                and shapes_visible
                and shape_items == 6,
                {
                    "alignItems": align_items,
                    "viewItems": view_items,
                    "shapeItems": shape_items,
                },
            )
            geometry = page.evaluate(
                """() => {
                    const stage = document.querySelector('.documentation-canvas-stage');
                    const pageCanvas = document.querySelector('.documentation-viewport-guide');
                    const rail = document.querySelector('.documentation-page-rail');
                    const properties = document.querySelector('.documentation-properties');
                    const thumbnail = document.querySelector('.documentation-page-thumbnail');
                    const statusbar = document.querySelector('.documentation-statusbar');
                    const rect = value => value?.getBoundingClientRect();
                    return {
                        stage: rect(stage),
                        page: rect(pageCanvas),
                        rail: rect(rail),
                        properties: rect(properties),
                        thumbnail: rect(thumbnail),
                        statusbar: rect(statusbar),
                        pageCount: document.querySelectorAll('.documentation-page-item').length,
                    };
                }"""
            )
            page_rect = geometry["page"]
            ratio = page_rect["width"] / page_rect["height"] if page_rect else 0
            record(
                "editor_has_page_rail_landscape_canvas_and_properties",
                geometry["pageCount"] == 8
                and geometry["rail"]["width"] >= 175
                and geometry["thumbnail"]["width"] >= 135
                and geometry["properties"]["width"] >= 260
                and geometry["statusbar"]["height"] >= 30
                and abs(ratio - (792 / 612)) < 0.02,
                {**geometry, "pageRatio": ratio},
            )
            rail_splitter = page.locator(".documentation-rail-splitter")
            splitter_box = rail_splitter.bounding_box()
            page.mouse.move(
                splitter_box["x"] + splitter_box["width"] / 2,
                splitter_box["y"] + 80,
            )
            page.mouse.down()
            page.mouse.move(
                splitter_box["x"] + splitter_box["width"] / 2 + 32,
                splitter_box["y"] + 80,
            )
            page.mouse.up()
            resized_rail_width = page.locator(
                ".documentation-page-rail"
            ).bounding_box()["width"]
            rail_splitter.dblclick()
            reset_rail_width = page.locator(
                ".documentation-page-rail"
            ).bounding_box()["width"]
            record(
                "page_rail_splitter_resizes_and_resets",
                resized_rail_width >= geometry["rail"]["width"] + 25
                and abs(reset_rail_width - 184) <= 1,
                {
                    "initial": geometry["rail"]["width"],
                    "resized": resized_rail_width,
                    "reset": reset_rail_width,
                },
            )

            base_page_width = page.locator(
                ".documentation-viewport-guide"
            ).bounding_box()["width"]
            logical_page_width = page.evaluate(
                """() => Number(
                    window.__compareDbg.state.partsManualDocumentation
                        ?.document?.publicationLayout?.page?.width
                )"""
            )
            page.locator("#documentationZoomRange").evaluate(
                """node => {
                    node.value = '120';
                    node.dispatchEvent(new Event('input', { bubbles: true }));
                }"""
            )
            page.wait_for_timeout(150)
            zoomed_page_width = page.locator(
                ".documentation-viewport-guide"
            ).bounding_box()["width"]
            page.locator("#documentationFitPageStatus").click()
            fitted_page_width = page.locator(
                ".documentation-viewport-guide"
            ).bounding_box()["width"]
            record(
                "status_bar_zoom_changes_and_refits_the_page",
                abs(zoomed_page_width - logical_page_width * 1.20) <= 2
                and abs(fitted_page_width - base_page_width) <= 2,
                {
                    "base": base_page_width,
                    "zoomed": zoomed_page_width,
                    "fitted": fitted_page_width,
                    "logicalPageWidth": logical_page_width,
                },
            )
            publication = page.evaluate(
                """() => {
                    const box = selector => {
                        const node = document.querySelector(selector);
                        const rect = node?.getBoundingClientRect();
                        return rect ? {
                            left: rect.left,
                            top: rect.top,
                            right: rect.right,
                            bottom: rect.bottom,
                            width: rect.width,
                            height: rect.height,
                        } : null;
                    };
                    const surface = document.querySelector('#documentationPublicationSurface');
                    return {
                        logicalWidth: surface?.offsetWidth,
                        logicalHeight: surface?.offsetHeight,
                        header: box('#documentationPageHeader'),
                        illustration: box('#documentationIllustrationFrame'),
                        sidecar: box('#documentationPageSidecar'),
                        footer: box('#documentationPageFooter'),
                        headerTitle: document.querySelector(
                            '#documentationPublicationSurface .documentation-page-header-title'
                        )?.textContent,
                        footerText: document.querySelector('#documentationPageFooter')?.textContent,
                        canvasBackground: getComputedStyle(
                            document.querySelector('#documentationIllustrationFrame canvas')
                        ).backgroundColor,
                    };
                }"""
            )
            screenshot = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
            illustration = publication["illustration"]
            illustration_crop = screenshot.crop(
                (
                    max(0, round(illustration["left"])),
                    max(0, round(illustration["top"])),
                    min(screenshot.width, round(illustration["right"])),
                    min(screenshot.height, round(illustration["bottom"])),
                )
            )
            illustration_pixels = list(illustration_crop.getdata())
            publication["screenshotPixelWhiteFraction"] = round(
                sum(
                    1
                    for red, green, blue in illustration_pixels
                    if red >= 240 and green >= 240 and blue >= 240
                ) / max(1, len(illustration_pixels)),
                6,
            )
            publication["screenshotPixelInkFraction"] = round(
                sum(
                    1
                    for red, green, blue in illustration_pixels
                    if min(red, green, blue) <= 220
                ) / max(1, len(illustration_pixels)),
                6,
            )
            record(
                "publication_canvas_uses_pdf_page_geometry",
                publication["logicalWidth"] == 792
                and publication["logicalHeight"] == 612
                and publication["header"]["bottom"] <= publication["illustration"]["top"]
                and publication["illustration"]["right"] < publication["sidecar"]["left"]
                and publication["illustration"]["bottom"] <= publication["footer"]["top"]
                and "FIGURE 1-1" in publication["headerTitle"]
                and "Page 4 of 8" in publication["footerText"]
                and publication["canvasBackground"] == "rgb(255, 255, 255)"
                and publication["screenshotPixelWhiteFraction"] >= 0.75
                and publication["screenshotPixelInkFraction"] >= 0.001,
                publication,
            )

            page.locator(
                '.documentation-page-item[title="Table of Contents"]'
            ).click()
            page.wait_for_function(
                """() => Boolean(
                    document.querySelectorAll(
                        '#documentationPublicationSurface .documentation-toc-row'
                    ).length
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=30_000,
            )
            static_page = page.evaluate(
                """() => ({
                    tocRows: document.querySelectorAll(
                        '#documentationPublicationSurface .documentation-toc-row'
                    ).length,
                    illustrationDisplay: getComputedStyle(
                        document.querySelector('#documentationIllustrationFrame')
                    ).display,
                    footer: document.querySelector('#documentationPageFooter')?.textContent,
                })"""
            )
            record(
                "all_manual_pages_are_present_and_static_pages_render_in_canvas",
                static_page["tocRows"] == 5
                and static_page["illustrationDisplay"] == "none"
                and "Page 3 of 8" in static_page["footer"],
                static_page,
            )

            page.locator(
                '.documentation-page-item[title="Front Steering and Wheel Assembly"]'
            ).click()
            page.wait_for_function(
                """() => Boolean(
                    document.querySelector(
                        '#documentationPublicationSurface .documentation-page-header-title'
                    )?.textContent.includes('FIGURE 2-1')
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=60_000,
            )
            dense_page = page.evaluate(
                """() => ({
                    title: document.querySelector(
                        '#documentationPublicationSurface .documentation-page-header-title'
                    )?.textContent,
                    bomRows: document.querySelectorAll(
                        '#documentationPublicationSurface .documentation-page-bom tbody tr'
                    ).length,
                    bomHeaders: [...document.querySelectorAll(
                        '#documentationPublicationSurface .documentation-page-bom th'
                    )]
                        .map(node => node.textContent),
                    illustrationRect: document.querySelector('#documentationIllustrationFrame')
                        ?.getBoundingClientRect().toJSON(),
                    bomRect: document.querySelector('#documentationPageSidecar')
                        ?.getBoundingClientRect().toJSON(),
                })"""
            )
            record(
                "dense_figure_has_wysiwyg_hlr_and_engineering_bom",
                "FIGURE 2-1" in dense_page["title"]
                and dense_page["bomRows"] == 9
                and dense_page["bomHeaders"] == ["ITEM", "PART NUMBER", "DESCRIPTION", "QTY"]
                and dense_page["illustrationRect"]["right"] < dense_page["bomRect"]["left"],
                dense_page,
            )
            phase_event_count_before_revisit = len([
                row for row in generation_snapshot["events"]
                if row.get("type") == "page_phase"
            ])
            phase_event_count_after_revisit = page.evaluate(
                """() => window.__compareDbg.documentationGenerationSnapshot().events
                    .filter(value => value.type === 'page_phase').length"""
            )
            record(
                "revisiting_a_settled_page_does_not_replay_generation",
                phase_event_count_after_revisit == phase_event_count_before_revisit,
                {
                    "before": phase_event_count_before_revisit,
                    "after": phase_event_count_after_revisit,
                },
            )

            edit_isolation = page.evaluate(
                """async () => {
                    const activePage = _documentationActivePage();
                    _documentationRefreshLiveCallouts(activePage);
                    const originalViewDocumentPage = _partsManualViewDocumentPage;
                    let recompositionCount = 0;
                    _partsManualViewDocumentPage = (...args) => {
                        recompositionCount += 1;
                        return originalViewDocumentPage(...args);
                    };
                    const close = (left, right, tolerance = 1e-7) =>
                        Math.abs(Number(left) - Number(right)) <= tolerance;
                    const pointClose = (left, right, tolerance = 1e-7) =>
                        close(left?.x, right?.x, tolerance)
                        && close(left?.y, right?.y, tolerance);
                    const routeRows = () => (state.partsManualCallouts || [])
                        .map(callout => callout?._liveRoute)
                        .filter(Boolean);
                    const snapshotRows = () => routeRows().map(row => ({
                        calloutId: _partsManualCalloutId(row),
                        target: { ...row.target },
                        balloon: { ...row.balloon },
                        occurrenceIds: [...(row.occurrenceIds || [])],
                        anchorOccurrenceId: row.anchorOccurrenceId || null,
                    }));
                    try {
                        const beforeBalloon = snapshotRows();
                        const selectedRow = beforeBalloon.find(row =>
                            row.occurrenceIds.length === 1
                        ) || beforeBalloon[0];
                        const balloonTarget = _documentationCalloutTarget(
                            activePage, selectedRow.calloutId, 'balloon'
                        );
                        _documentationSelectTarget(balloonTarget, { silent: true });
                        const balloonSaved = await _documentationDispatchCommand(
                            'translate', [0.012, 0.006, 0]
                        );
                        const afterBalloon = snapshotRows();
                        const balloonBeforeRow = beforeBalloon.find(
                            row => row.calloutId === selectedRow.calloutId
                        );
                        const balloonAfterRow = afterBalloon.find(
                            row => row.calloutId === selectedRow.calloutId
                        );
                        const balloonRecompositions = recompositionCount;
                        const balloonOnly = balloonSaved
                            && pointClose(balloonBeforeRow.target, balloonAfterRow.target)
                            && !pointClose(balloonBeforeRow.balloon, balloonAfterRow.balloon)
                            && beforeBalloon.every(before => {
                                if (before.calloutId === selectedRow.calloutId) return true;
                                const after = afterBalloon.find(
                                    row => row.calloutId === before.calloutId
                                );
                                return pointClose(before.target, after.target)
                                    && pointClose(before.balloon, after.balloon);
                            });
                        await _documentationDispatchCommand('reset');

                        const beforeCad = snapshotRows();
                        const cadRow = beforeCad.find(row =>
                            row.occurrenceIds.length === 1
                            && row.anchorOccurrenceId
                        ) || beforeCad.find(row => row.occurrenceIds.length === 1);
                        const occurrenceId = String(
                            cadRow.anchorOccurrenceId || cadRow.occurrenceIds[0]
                        );
                        const occurrenceTarget = _documentationTargetsForPage(activePage)
                            .find(target => target.targetType === 'occurrence'
                                && target.targetId === occurrenceId);
                        _documentationSelectTarget(occurrenceTarget, { silent: true });
                        const targetMeshes = _documentationTargetMeshes(
                            activePage, occurrenceTarget
                        );
                        const targetMesh = targetMeshes[0];
                        const unrelatedMesh = _partsManualPageMeshes(activePage).find(
                            mesh => !targetMeshes.includes(mesh)
                        );
                        const targetPositionBefore = targetMesh.position.clone();
                        const unrelatedPositionBefore = unrelatedMesh?.position.clone() || null;
                        const cadRecompositionsBefore = recompositionCount;
                        const componentSaved = await _documentationDispatchCommand(
                            'translate', [0.001, 0, 0]
                        );
                        const afterCad = snapshotRows();
                        const cadBeforeRow = beforeCad.find(
                            row => row.calloutId === cadRow.calloutId
                        );
                        const cadAfterRow = afterCad.find(
                            row => row.calloutId === cadRow.calloutId
                        );
                        const componentMovedLocally = componentSaved
                            && targetMesh.position.distanceTo(targetPositionBefore) > 1e-7
                            && (!unrelatedMesh || unrelatedMesh.position.distanceTo(
                                unrelatedPositionBefore
                            ) <= 1e-10)
                            && !pointClose(cadBeforeRow.target, cadAfterRow.target)
                            && pointClose(cadBeforeRow.balloon, cadAfterRow.balloon)
                            && beforeCad.every(before => {
                                if (before.calloutId === cadRow.calloutId) return true;
                                const after = afterCad.find(
                                    row => row.calloutId === before.calloutId
                                );
                                return pointClose(before.target, after.target)
                                    && pointClose(before.balloon, after.balloon);
                            });
                        const componentRecompositions = recompositionCount
                            - cadRecompositionsBefore;
                        await _documentationMoveHistory('undo');
                        const undoLocal = recompositionCount === cadRecompositionsBefore
                            && targetMesh.position.distanceTo(targetPositionBefore) <= 1e-7;
                        return {
                            balloonOnly,
                            componentMovedLocally,
                            undoLocal,
                            balloonRecompositions,
                            componentRecompositions,
                            totalRecompositions: recompositionCount,
                        };
                    } finally {
                        _partsManualViewDocumentPage = originalViewDocumentPage;
                    }
                }"""
            )
            record(
                "balloon_and_component_moves_do_not_recompose_the_exploded_view",
                edit_isolation["balloonOnly"]
                and edit_isolation["componentMovedLocally"]
                and edit_isolation["undoLocal"]
                and edit_isolation["totalRecompositions"] == 0,
                edit_isolation,
            )

            capture_settle = page.evaluate(
                """async () => {
                    const payload = window.__compareDbg.state.partsManualDocumentation;
                    const targetPage = payload.document.pages.find(
                        value => value.title === 'Front Steering and Wheel Assembly'
                    );
                    const generation = window.__compareDbg.state
                        .partsManualDocumentationGeneration;
                    const digest = async blob => {
                        const bytes = await blob.arrayBuffer();
                        const hash = await crypto.subtle.digest('SHA-256', bytes);
                        return [...new Uint8Array(hash)]
                            .map(value => value.toString(16).padStart(2, '0')).join('');
                    };
                    generation.status = 'running';
                    generation.lastRevealedPageId = String(targetPage.pageId);
                    _documentationSetPagePhase(targetPage.pageId, 'annotations', {
                        rowsRevealed: targetPage.bom?.rows?.length || 0,
                        annotationsRevealed: 1,
                    });
                    _documentationRenderPublicationPage(targetPage);
                    const before = document.querySelector(
                        '#documentationPublicationSurface'
                    )?.getAttribute('data-reveal-phase');
                    const first = await _partsManualCaptureCurrentView(targetPage);
                    const afterFirst = document.querySelector(
                        '#documentationPublicationSurface'
                    )?.getAttribute('data-reveal-phase');
                    generation.status = 'complete';
                    generation.lastRevealedPageId = null;
                    _documentationRenderPublicationPage(targetPage);
                    const second = await _partsManualCaptureCurrentView(targetPage);
                    return {
                        before,
                        afterFirst,
                        firstSha256: await digest(first.blob),
                        secondSha256: await digest(second.blob),
                        firstBalloons: JSON.stringify(first.balloons || []),
                        secondBalloons: JSON.stringify(second.balloons || []),
                    };
                }"""
            )
            record(
                "capture_forces_a_settled_page_during_progressive_generation",
                capture_settle["before"] == "annotations"
                and capture_settle["afterFirst"] is None
                and capture_settle["firstSha256"] == capture_settle["secondSha256"]
                and capture_settle["firstBalloons"] == capture_settle["secondBalloons"],
                capture_settle,
            )
            bom = page.locator('#documentationPageSidecar')
            before_drag = bom.bounding_box()
            page.mouse.move(
                before_drag['x'] + before_drag['width'] * 0.5,
                before_drag['y'] + before_drag['height'] * 0.5,
            )
            page.mouse.down()
            page.mouse.move(
                before_drag['x'] + before_drag['width'] * 0.5 + 14,
                before_drag['y'] + before_drag['height'] * 0.5 + 8,
                steps=4,
            )
            page.mouse.up()
            page.wait_for_function(
                """() => Boolean(
                    window.__compareDbg.state.partsManualDocumentation?.scene?.pages?.[
                        window.__compareDbg.state.partsManualDocumentationPageId
                    ]?.pageElementOverrides?.bom
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=30_000,
            )
            after_drag = bom.bounding_box()
            persisted_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()['scene']
            active_page_id = page.evaluate(
                "window.__compareDbg.state.partsManualDocumentationPageId"
            )
            bom_override = persisted_scene['pages'][active_page_id][
                'pageElementOverrides'
            ]['bom']['translation']
            record(
                "bom_drag_is_persistent_and_uses_the_publication_coordinate_system",
                after_drag['x'] > before_drag['x'] + 8
                and after_drag['y'] > before_drag['y'] + 4
                and bom_override[0] > 0
                and bom_override[1] > 0,
                {
                    'before': before_drag,
                    'after': after_drag,
                    'override': bom_override,
                },
            )
            if page.locator("#documentationProperties").get_attribute("aria-hidden") == "true":
                open_documentation_inspector()
            page.get_by_title('Reset object').click()
            page.wait_for_function(
                """() => Boolean(
                    !window.__compareDbg.state.partsManualDocumentation?.scene?.pages?.[
                        window.__compareDbg.state.partsManualDocumentationPageId
                    ]?.pageElementOverrides?.bom
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=30_000,
            )

            page.emulate_media(reduced_motion="reduce")
            reduced_snapshot = page.evaluate(
                """async () => {
                    const payload = window.__compareDbg.state.partsManualDocumentation;
                    window.__compareDbg.state.partsManualDocumentationGenerationEvents = [];
                    const work = _documentationBeginSageWork('Reduced-motion reveal proof');
                    _documentationPreparePageGeneration(payload, { revealAll: false });
                    try {
                        await _documentationRevealPagesSequentially(payload, {
                            work,
                            prepared: true,
                        });
                        _documentationEndSageWork(work, 'complete', 'Reduced-motion proof complete.');
                    } catch (error) {
                        _documentationEndSageWork(work, 'failed', error.message);
                        throw error;
                    }
                    return window.__compareDbg.documentationGenerationSnapshot();
                }"""
            )
            page.emulate_media(reduced_motion="no-preference")
            record(
                "reduced_motion_skips_visual_phases_and_lands_settled",
                reduced_snapshot["generationState"] == "complete"
                and reduced_snapshot["visiblePageCount"] == 8
                and not [
                    row for row in reduced_snapshot["events"]
                    if row.get("type") == "page_phase"
                ],
                {
                    "generationState": reduced_snapshot["generationState"],
                    "visiblePageCount": reduced_snapshot["visiblePageCount"],
                    "phaseEventCount": len([
                        row for row in reduced_snapshot["events"]
                        if row.get("type") == "page_phase"
                    ]),
                },
            )
            record(
                "documentation_pipeline_has_no_unexpected_runtime_or_http_failures",
                not report["browserErrors"]
                and not report["failedResponses"]
                and not report["unexpectedHttpFailures"]
                and not any(
                    token in message
                    for message in report["consoleErrors"]
                    for token in ("ReferenceError", "SyntaxError", "TypeError")
                ),
                {
                    "browserErrors": report["browserErrors"],
                    "consoleErrors": report["consoleErrors"],
                    "failedResponses": report["failedResponses"],
                    "expectedUnavailableResponses": report[
                        "expectedUnavailableResponses"
                    ],
                    "unexpectedHttpFailures": report["unexpectedHttpFailures"],
                },
            )

            page.screenshot(
                path=str(OUT / "documentation_workflow.png"),
                full_page=True,
            )
            report["screenshot"] = str(OUT / "documentation_workflow.png")
            request.dispose()
            context.close()
            browser.close()
    finally:
        server.stop()

    passed = all(row["ok"] for row in report["checks"].values())
    report["status"] = "PASS" if passed else "FAIL"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "documentation_workflow_proof.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(run())
