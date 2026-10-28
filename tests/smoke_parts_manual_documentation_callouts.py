"""Browser proof for editable parts-manual balloons and leaders."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from parts_manual_smoke_support import IsolatedPartsManualServer


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".runtime" / "parts_manual_documentation_callout_proof"
OUT.mkdir(parents=True, exist_ok=True)
ASSEMBLY = "tricycle"


def _approve_plan(request, app_url: str) -> None:
    initial = request.get(f"{app_url}/api/parts-manual/{ASSEMBLY}").json()
    proposal = request.get(
        f"{app_url}/api/parts-manual/{ASSEMBLY}/proposal"
    ).json()["proposal"]
    ready = [row["candidateId"] for row in proposal["candidates"] if row["status"] == "ready"]
    response = request.post(
        f"{app_url}/api/parts-manual/{ASSEMBLY}/proposals/"
        f"{proposal['proposalRevision']}/approve",
        data={
            "baseRevision": initial["revision"],
            "sourceRevision": initial["sourceRevision"],
            "candidateIds": ready,
        },
    )
    if not response.ok:
        raise RuntimeError(response.text())


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
            request = playwright.request.new_context(base_url=server.app_url, timeout=180_000)
            page.on("pageerror", lambda error: report["browserErrors"].append(str(error)))
            page.on(
                "console",
                lambda message: report["consoleErrors"].append(message.text)
                if message.type == "error"
                else None,
            )
            def capture_failed_response(response) -> None:
                if response.status < 400 or "/api/parts-manual/" not in response.url:
                    return
                try:
                    body = response.text()
                except Exception:
                    body = None
                report["failedResponses"].append(
                    {"status": response.status, "url": response.url, "body": body}
                )

            page.on("response", capture_failed_response)

            _approve_plan(request, server.app_url)
            plan_before = server.plan_path.read_bytes()
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
                """() => {
                    const items = [...document.querySelectorAll(
                        '#documentationPageList .documentation-page-item'
                    )];
                    const pages = window.__compareDbg.state.partsManualDocumentation
                        ?.document?.pages || [];
                    return !document.querySelector('#documentationWorkspace.busy')
                        && pages.length >= 8
                        && items.length === pages.length
                        && items.every(item => item.querySelector(
                            '.documentation-page-thumbnail.has-preview .documentation-thumbnail-page'
                        ));
                }""",
                timeout=120_000,
            )
            cover_item = workspace.locator(
                '.documentation-page-item[title="Tricycle Illustrated Parts Manual"]'
            )
            cover_item.click()
            page.wait_for_function(
                """() => {
                    const active = document.querySelector(
                        '#documentationPageList .documentation-page-item.active'
                    );
                    const image = active?.querySelector(
                        '.documentation-thumbnail-illustration-image'
                    );
                    return !document.querySelector('#documentationWorkspace.busy')
                        && active?.textContent?.includes('Tricycle Illustrated Parts Manual')
                        && image?.complete
                        && image.naturalWidth > 0;
                }""",
                timeout=120_000,
            )
            thumbnail_proof = page.evaluate(
                """() => {
                    const items = [...document.querySelectorAll(
                        '#documentationPageList .documentation-page-item'
                    )];
                    const cover = items.find(item => item.textContent.includes(
                        'Tricycle Illustrated Parts Manual'
                    ));
                    const control = items.find(item => item.textContent.includes(
                        'Document Information and Revision'
                    ));
                    const toc = items.find(item => item.textContent.includes(
                        'Table of Contents'
                    ));
                    return {
                        pageCount: items.length,
                        previewCount: document.querySelectorAll(
                            '#documentationPageList .documentation-thumbnail-page'
                        ).length,
                        coverTitle: cover?.querySelector(
                            '.documentation-page-header-title'
                        )?.textContent,
                        coverHasLiveImage: Boolean(cover?.querySelector(
                            '.documentation-thumbnail-illustration-image'
                        )),
                        documentControlRows: control?.querySelectorAll(
                            '.documentation-control-row'
                        ).length || 0,
                        tocRows: toc?.querySelectorAll('.documentation-toc-row').length || 0,
                        duplicateIds: [...document.querySelectorAll(
                            '#documentationPageList .documentation-thumbnail-page [id]'
                        )].map(element => element.id),
                    };
                }"""
            )
            record(
                "page_rail_previews_reflect_composed_pages_and_live_cover_view",
                thumbnail_proof["pageCount"] == 8
                and thumbnail_proof["previewCount"] == 8
                and thumbnail_proof["coverTitle"] == "ILLUSTRATED PARTS MANUAL"
                and thumbnail_proof["coverHasLiveImage"]
                and thumbnail_proof["documentControlRows"] >= 7
                and thumbnail_proof["tocRows"] >= 4
                and not thumbnail_proof["duplicateIds"],
                thumbnail_proof,
            )
            workspace.screenshot(
                path=str(OUT / "documentation_page_thumbnails.png"),
                timeout=60_000,
            )
            workspace.locator(
                '.documentation-page-item[title="Front Steering and Wheel Assembly"]'
            ).click()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualCallouts?.length >= 9
                    && window.__compareDbg.state.partsManualCallouts.every(value => value.elbowHandle)
                    && document.querySelector(
                        '#documentationPageList .documentation-page-item.active '
                        + '.documentation-thumbnail-illustration-image'
                    )?.complete
                )""",
                timeout=60_000,
            )
            technical_thumbnail = page.evaluate(
                """async () => {
                    const image = document.querySelector(
                        '#documentationPageList .documentation-page-item.active '
                        + '.documentation-thumbnail-illustration-image'
                    );
                    if (!image) return null;
                    if (image.decode) await image.decode();
                    const canvas = document.createElement('canvas');
                    canvas.width = 96;
                    canvas.height = 72;
                    const context = canvas.getContext('2d', { alpha: false });
                    context.drawImage(image, 0, 0, canvas.width, canvas.height);
                    const pixels = context.getImageData(
                        0, 0, canvas.width, canvas.height
                    ).data;
                    let white = 0;
                    let dark = 0;
                    let colored = 0;
                    const count = pixels.length / 4;
                    for (let offset = 0; offset < pixels.length; offset += 4) {
                        const r = pixels[offset];
                        const g = pixels[offset + 1];
                        const b = pixels[offset + 2];
                        if (r >= 245 && g >= 245 && b >= 245) white += 1;
                        if (r <= 90 && g <= 90 && b <= 90) dark += 1;
                        if (Math.max(r, g, b) - Math.min(r, g, b) >= 24) colored += 1;
                    }
                    return {
                        whiteFraction: white / count,
                        darkFraction: dark / count,
                        coloredFraction: colored / count,
                    };
                }"""
            )
            record(
                "active_technical_thumbnail_uses_current_hlr_view",
                technical_thumbnail is not None
                and technical_thumbnail["whiteFraction"] >= 0.70
                and technical_thumbnail["darkFraction"] <= 0.20
                and technical_thumbnail["coloredFraction"] <= 0.08,
                technical_thumbnail,
            )
            workspace.screenshot(
                path=str(OUT / "documentation_technical_page_thumbnails.png"),
                timeout=60_000,
            )
            page.locator("#documentationBalloonMenuRibbon").click()
            page.locator("#documentationClearBalloonsRibbon").click()
            page.wait_for_function(
                """() => {
                    const state = window.__compareDbg.state;
                    const page = state.partsManualDocumentation.document.pages.find(
                        value => value.pageId === state.partsManualDocumentationPageId
                    );
                    return !document.querySelector('#documentationWorkspace.busy')
                        && state.partsManualCallouts?.length === 0
                        && page?.bom?.length === 0
                        && state.partsManualDocumentation.document.status === 'draft_callouts';
                }""",
                timeout=60_000,
            )
            record(
                "clear_page_removes_callouts_and_bom_rows_atomically",
                    page.locator("#documentationPublicationSurface .documentation-page-bom tbody tr").count() == 0
                and page.locator("#documentationPublishRibbon").is_disabled(),
            )

            pedal_target = workspace.locator(
                '.documentation-target-row[data-target-type="occurrence"]'
            ).filter(has_text="Pedal").first
            pedal_target.click()
            floating_toolbar = page.locator("#documentationSelectionToolbar")
            floating_toolbar.wait_for(state="visible", timeout=20_000)
            floating_add = page.locator("#documentationFloatingAddBalloon")
            stage_bounds = workspace.locator(".documentation-canvas-stage").bounding_box()
            toolbar_bounds = floating_toolbar.bounding_box()
            record(
                "selected_cad_item_shows_contextual_toolbar_near_the_canvas_selection",
                floating_add.is_visible()
                and floating_toolbar.get_attribute("data-target-type") == "occurrence"
                and stage_bounds is not None
                and toolbar_bounds is not None
                and toolbar_bounds["x"] >= stage_bounds["x"]
                and toolbar_bounds["x"] + toolbar_bounds["width"]
                <= stage_bounds["x"] + stage_bounds["width"]
                and toolbar_bounds["y"] >= stage_bounds["y"]
                and toolbar_bounds["y"] + toolbar_bounds["height"]
                <= stage_bounds["y"] + stage_bounds["height"],
                {
                    "stage": stage_bounds,
                    "toolbar": toolbar_bounds,
                },
            )
            workspace.screenshot(
                path=str(OUT / "documentation_context_toolbar_part.png"),
                timeout=60_000,
            )
            floating_add.click()
            page.wait_for_function(
                """() => {
                    const state = window.__compareDbg.state;
                    const page = state.partsManualDocumentation.document.pages.find(
                        value => value.pageId === state.partsManualDocumentationPageId
                    );
                    return !document.querySelector('#documentationWorkspace.busy')
                        && state.partsManualCallouts?.length === 1
                        && page?.bom?.length === 1;
                }""",
                timeout=60_000,
            )
            manual_item = page.evaluate(
                """() => {
                    const state = window.__compareDbg.state;
                    const page = state.partsManualDocumentation.document.pages.find(
                        value => value.pageId === state.partsManualDocumentationPageId
                    );
                    const callout = state.partsManualCallouts[0];
                    const route = callout._liveRoute;
                    return {
                        bom: page.bom[0],
                        request: page.renderRequest.calloutItems[0],
                        lineColor: callout.line.material.color.getHex(),
                        hasArrow: Boolean(callout.endMarker),
                        centerSeedMatches: Math.hypot(
                            route.target.x - route.anchorCandidates.center.point.x,
                            route.target.y - route.anchorCandidates.center.point.y
                        ) < 0.000001,
                    };
                }"""
            )
            record(
                "selected_part_creates_next_number_quantity_bom_and_black_arrow_leader",
                manual_item["bom"]["item"] == 1
                and manual_item["bom"]["description"] == "Pedal"
                and manual_item["bom"]["quantity"] == 2
                and manual_item["request"]["anchorPreference"] == "bounding_box_center"
                and manual_item["request"]["endCondition"] == "arrow"
                and manual_item["lineColor"] == 0x111820
                and manual_item["hasArrow"]
                and manual_item["centerSeedMatches"],
                manual_item,
            )

            page.locator("#documentationFloatingSelectLeader").click()
            page.locator("#documentationFloatingEndDot").click()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualCallouts?.[0]?.endCondition === 'dot'
                    && window.__compareDbg.state.partsManualCallouts?.[0]?.endMarkerDot
                )""",
                timeout=60_000,
            )
            record("leader_end_condition_switches_to_dot", True)

            page.locator("#documentationBalloonMenuRibbon").click()
            page.locator("#documentationRestoreBalloonsRibbon").click()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualCallouts?.length >= 9
                    && window.__compareDbg.state.partsManualDocumentation.document.status === 'publication_ready'
                )""",
                timeout=60_000,
            )
            initial_revision = page.evaluate(
                "() => window.__compareDbg.state.partsManualDocumentation.revision"
            )
            item_nine_route_side = page.evaluate(
                """() => window.__compareDbg.state.partsManualCallouts.find(
                    value => value.calloutId === 'callout-item-9'
                )?._liveRoute?.routeSide"""
            )
            record(
                "callout_targets_and_direct_handles_are_available",
                workspace.locator(".documentation-target-row", has_text="Item 9 balloon").count() == 1
                and workspace.locator(".documentation-target-row", has_text="Item 9 leader").count() == 1
                and page.locator(".documentation-callout-handle.elbow").count() >= 9,
            )

            item_nine = page.locator(".manual-item-callout").filter(
                has=page.locator(".manual-item-callout-number", has_text="9")
            ).first
            bounds = item_nine.bounding_box()
            if not bounds:
                raise RuntimeError("item 9 balloon is not visible")
            page.mouse.move(bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2)
            page.mouse.down()
            balloon_dx = 10 if item_nine_route_side in {"top", "bottom"} else 0
            balloon_dy = 10 if item_nine_route_side in {"left", "right"} else 0
            page.mouse.move(
                bounds["x"] + bounds["width"] / 2 + balloon_dx,
                bounds["y"] + bounds["height"] / 2 + balloon_dy,
            )
            page.mouse.up()
            page.wait_for_function(
                """revision => Boolean(
                    window.__compareDbg.state.partsManualDocumentation.revision !== revision
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                arg=initial_revision,
                timeout=60_000,
            )
            scene_after_balloon = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()
            front_page = next(
                row for row in scene_after_balloon["document"]["pages"]
                if row.get("title") == "Front Steering and Wheel Assembly"
            )
            composition = scene_after_balloon["scene"]["pages"][front_page["pageId"]]
            balloon_override = composition["balloonOverrides"].get("callout-item-9")
            record(
                "balloon_drag_persists_normalized_override",
                balloon_override is not None
                and any(abs(float(value)) > 1e-6 for value in balloon_override["translation"][:2]),
                balloon_override,
            )

            workspace.locator(".documentation-target-row", has_text="Item 9 leader").click()
            selected_leader_color = page.evaluate(
                """() => window.__compareDbg.state.partsManualCallouts.find(
                    value => value.calloutId === 'callout-item-9'
                )?.line?.material?.color?.getHex?.()"""
            )
            record(
                "selected_leader_remains_visible_on_white_page",
                selected_leader_color == 0x111820,
                selected_leader_color,
            )
            elbow = page.locator(
                ".documentation-callout-handle.elbow.documentation-selected"
            ).first
            elbow.wait_for(state="visible", timeout=20_000)
            elbow_bounds = elbow.bounding_box()
            if not elbow_bounds:
                raise RuntimeError("item 9 elbow is not visible")
            revision_before_elbow = page.evaluate(
                "() => window.__compareDbg.state.partsManualDocumentation.revision"
            )
            page.mouse.move(
                elbow_bounds["x"] + elbow_bounds["width"] / 2,
                elbow_bounds["y"] + elbow_bounds["height"] / 2,
            )
            page.mouse.down()
            elbow_dx = -6 if item_nine_route_side == "left" else 6 if item_nine_route_side == "right" else 0
            elbow_dy = -6 if item_nine_route_side == "top" else 6 if item_nine_route_side == "bottom" else 0
            page.mouse.move(
                elbow_bounds["x"] + elbow_bounds["width"] / 2 + elbow_dx,
                elbow_bounds["y"] + elbow_bounds["height"] / 2 + elbow_dy,
            )
            page.mouse.up()
            page.wait_for_function(
                """revision => Boolean(
                    window.__compareDbg.state.partsManualDocumentation.revision !== revision
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                arg=revision_before_elbow,
                timeout=60_000,
            )
            scene_after_elbow = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()
            leader_override = scene_after_elbow["scene"]["pages"][front_page["pageId"]][
                "leaderOverrides"
            ].get("callout-item-9")
            record(
                "elbow_drag_persists_orthogonal_corridor_override",
                leader_override is not None
                and any(
                    abs(float(value)) > 1e-6
                    for value in leader_override.get("corridorTranslation", [])[:2]
                ),
                leader_override,
            )

            revision_before_anchor = scene_after_elbow["revision"]
            workspace.get_by_title("Snap anchor to the right visible edge").click()
            page.wait_for_function(
                """revision => Boolean(
                    window.__compareDbg.state.partsManualDocumentation.revision !== revision
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                arg=revision_before_anchor,
                timeout=60_000,
            )
            scene_after_anchor = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()
            anchored = scene_after_anchor["scene"]["pages"][front_page["pageId"]][
                "leaderOverrides"
            ]["callout-item-9"]
            record("anchor_snaps_to_valid_visible_edge", anchored.get("anchorSide") == "right", anchored)

            page.locator("#documentationUndoRibbon").click()
            page.wait_for_function(
                """() => !document.querySelector('#documentationWorkspace.busy')""",
                timeout=60_000,
            )
            page.locator("#documentationCaptureRibbon").click()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && (
                        document.querySelector('.documentation-status-message')?.textContent.includes('captured')
                        || document.querySelector('.documentation-status-message.error')
                    )
                )""",
                timeout=180_000,
            )
            capture_status = workspace.locator(".documentation-status-message").inner_text()
            if "captured" not in capture_status:
                route_diagnostics = page.evaluate(
                    "() => window.__compareDbg.state.partsManualRouteQaDiagnostics"
                )
                raise RuntimeError(
                    f"capture failed: {capture_status}; {report['failedResponses']}; "
                    f"route diagnostics: {route_diagnostics}"
                )
            captured = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/document"
            ).json()["document"]
            captured_page = next(
                row for row in captured["pages"]
                if row.get("title") == "Front Steering and Wheel Assembly"
            )
            image = captured_page["renderRequest"]["image"]
            pedal_bom = next(row for row in captured_page["bom"] if row["description"] == "Pedal")
            record(
                "capture_qa_accepts_manual_balloon_and_leader_overrides",
                image.get("status") == "ready"
                and image.get("quality", {}).get("calloutQuality", {}).get("status") == "PASS"
                and len(image.get("balloons") or []) == len(captured_page["bom"]),
                image.get("quality", {}).get("calloutQuality"),
            )
            record(
                "callout_edits_preserve_bom_and_manual_plan",
                pedal_bom["quantity"] == 2
                and len(pedal_bom["occurrenceIds"]) == 2
                and server.plan_path.read_bytes() == plan_before,
                pedal_bom,
            )
            page.wait_for_function(
                """() => (window.__compareDbg.state.partsManualCallouts || []).every(callout => {
                    const position = callout.line?.geometry?.getAttribute?.('position');
                    const camera = window.__compareDbg.state.assyCamera;
                    if (!position || position.count < 2 || !camera) return false;
                    const points = [];
                    for (let index = 0; index < position.count; index += 1) {
                        points.push(new THREE.Vector3(
                            position.getX(index), position.getY(index), position.getZ(index)
                        ).project(camera));
                    }
                    return points.slice(0, -1).every((point, index) =>
                        Math.abs(points[index + 1].x - point.x) < 0.004
                        || Math.abs(points[index + 1].y - point.y) < 0.004
                    );
                })""",
                timeout=30_000,
            )
            leaders_restored = page.evaluate(
                """() => (window.__compareDbg.state.partsManualCallouts || []).every(callout => {
                    const position = callout.line?.geometry?.getAttribute?.('position');
                    const camera = window.__compareDbg.state.assyCamera;
                    if (!position || position.count < 2 || !camera) return false;
                    const points = [];
                    for (let index = 0; index < position.count; index += 1) {
                        points.push(new THREE.Vector3(
                            position.getX(index), position.getY(index), position.getZ(index)
                        ).project(camera));
                    }
                    return points.slice(0, -1).every((point, index) =>
                        Math.abs(points[index + 1].x - point.x) < 0.004
                        || Math.abs(points[index + 1].y - point.y) < 0.004
                    );
                })"""
            )
            record("capture_restores_orthogonal_live_editor_leaders", leaders_restored)
            workspace.screenshot(
                path=str(OUT / "documentation_callout_editor.png"),
                timeout=60_000,
            )
            record(
                "no_browser_or_request_errors",
                not report["browserErrors"]
                and not report["failedResponses"]
                and not any(
                    token in message
                    for message in report["consoleErrors"]
                    for token in ("ReferenceError", "SyntaxError", "TypeError")
                ),
                {
                    "browserErrors": report["browserErrors"],
                    "consoleErrors": report["consoleErrors"],
                    "failedResponses": report["failedResponses"],
                },
            )
            request.dispose()
            browser.close()
    except Exception as exc:
        report["fatalError"] = str(exc)
        print(f"FAIL fatal :: {exc}")
    finally:
        server.stop()

    report["passed"] = (
        bool(report["checks"])
        and all(value.get("ok") for value in report["checks"].values())
        and "fatalError" not in report
    )
    (OUT / "documentation_callout_proof.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
