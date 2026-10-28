"""Browser proof for CAD-aware Documentation arrangement commands."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from parts_manual_smoke_support import IsolatedPartsManualServer


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".runtime" / "parts_manual_documentation_arrange_proof"
ASSEMBLY = "tricycle"


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
            page.on(
                "response",
                lambda response: report["failedResponses"].append(
                    {"status": response.status, "url": response.url}
                )
                if response.status >= 400 and "/api/parts-manual/" in response.url
                else None,
            )

            page.goto(
                f"{server.app_url}/?assemblyProfile={ASSEMBLY}",
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            page.wait_for_function(
                """assembly => Boolean(
                    window.__compareDbg?.state.partNumber === assembly
                    && window.__compareDbg.state.assyOccurrenceMeshMap
                )""",
                arg=ASSEMBLY,
                timeout=90_000,
            )
            page.evaluate("() => window.__compareDbg.openDocumentationWorkflow()")
            page.locator("#documentationWorkspace").wait_for(state="visible", timeout=120_000)
            page.wait_for_function(
                """() => Boolean(
                    window.__compareDbg.state.partsManualDocumentation
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=120_000,
            )
            page.locator(
                '.documentation-page-item[title="Front Steering and Wheel Assembly"]'
            ).click()
            page.wait_for_function(
                """() => Boolean(
                    document.querySelector(
                        '#documentationPublicationSurface .documentation-page-header-title'
                    )
                        ?.textContent.includes('FIGURE 2-1')
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=60_000,
            )

            part_rows = page.locator(
                '.documentation-target-row[data-target-type="occurrence"]'
            )
            record(
                "dense_page_exposes_component_targets",
                part_rows.count() >= 3,
                {"componentTargets": part_rows.count()},
            )
            part_rows.nth(0).click()
            part_rows.nth(1).click(modifiers=["Control"])
            part_rows.nth(2).click(modifiers=["Control"])
            page.wait_for_function(
                "window.__compareDbg.state.partsManualDocumentationSelections.length === 3"
            )
            selection_state = page.evaluate(
                """() => ({
                    count: window.__compareDbg.state.partsManualDocumentationSelections.length,
                    alignEnabled: !document.querySelector('#documentationAlignTopRibbon')?.disabled,
                    distributeEnabled: !document.querySelector(
                        '#documentationDistributeHorizontalRibbon'
                    )?.disabled,
                    helperCount: window.__compareDbg.state
                        .partsManualDocumentationSelectionHelper?.children?.length || 0,
                })"""
            )
            record(
                "ctrl_click_creates_a_real_multi_selection",
                selection_state["count"] == 3
                and selection_state["alignEnabled"]
                and selection_state["distributeEnabled"]
                and selection_state["helperCount"] == 3,
                selection_state,
            )

            page.locator("#documentationAlignMenuRibbon").click()
            page.locator("#documentationAlignTopRibbon").click()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene?.commands?.at(-1)
                        ?.operation === 'arrange'
                )""",
                timeout=60_000,
            )
            arranged_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            arrange_command = arranged_scene["commands"][-1]
            arranged_cursor = arranged_scene["historyCursor"]
            record(
                "alignment_is_one_atomic_persistent_command",
                arrange_command["operation"] == "arrange"
                and arrange_command["arrangement"] == "align_top"
                and arrange_command["actor"] == "user"
                and len(arrange_command["transforms"]) >= 1,
                arrange_command,
            )
            page.locator("#documentationUndoRibbon").click()
            page.wait_for_function(
                """cursor => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene
                        ?.historyCursor === cursor - 1
                )""",
                arg=arranged_cursor,
                timeout=30_000,
            )
            record(
                "one_undo_reverts_the_complete_alignment",
                page.evaluate(
                    "window.__compareDbg.state.partsManualDocumentation.scene.historyCursor"
                ) == arranged_cursor - 1,
            )

            page.locator("#documentationRedoRibbon").click()
            page.wait_for_function(
                """cursor => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene
                        ?.historyCursor === cursor
                )""",
                arg=arranged_cursor,
                timeout=30_000,
            )
            redone_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            record(
                "redo_reapplies_the_exact_alignment_transaction",
                redone_scene["historyCursor"] == arranged_cursor
                and redone_scene["commands"][arranged_cursor - 1] == arrange_command,
                {
                    "historyCursor": redone_scene["historyCursor"],
                    "command": redone_scene["commands"][arranged_cursor - 1],
                },
            )
            page.locator("#documentationUndoRibbon").click()
            page.wait_for_function(
                """cursor => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene
                        ?.historyCursor === cursor - 1
                )""",
                arg=arranged_cursor,
                timeout=30_000,
            )

            part_rows = page.locator(
                '.documentation-target-row[data-target-type="occurrence"]'
            )
            part_rows.nth(0).click()
            moved_target_id = page.evaluate(
                "window.__compareDbg.state.partsManualDocumentationSelection.targetId"
            )
            page.keyboard.press("ArrowRight")
            page.wait_for_function(
                """targetId => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene?.commands?.[
                        window.__compareDbg.state.partsManualDocumentation.scene.historyCursor - 1
                    ]?.operation === 'translate'
                    && window.__compareDbg.state.partsManualDocumentation.scene.commands[
                        window.__compareDbg.state.partsManualDocumentation.scene.historyCursor - 1
                    ]?.targetId === targetId
                )""",
                arg=moved_target_id,
                timeout=30_000,
            )
            moved_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            moved_command = moved_scene["commands"][moved_scene["historyCursor"] - 1]
            page_id = page.evaluate("window.__compareDbg.state.partsManualDocumentationPageId")
            moved_override = moved_scene["pages"][page_id]["occurrenceOverrides"][
                moved_target_id
            ]["translation"]
            record(
                "keyboard_nudge_persists_a_real_component_movement",
                moved_command["operation"] == "translate"
                and moved_command["targetId"] == moved_target_id
                and any(abs(float(value)) > 0.000001 for value in moved_override),
                {"command": moved_command, "translation": moved_override},
            )

            part_rows = page.locator(
                '.documentation-target-row[data-target-type="occurrence"]'
            )
            part_rows.nth(1).click()
            page.keyboard.press("Shift+ArrowRight")
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene?.commands?.[
                        window.__compareDbg.state.partsManualDocumentation.scene.historyCursor - 1
                    ]?.operation === 'translate'
                )""",
                timeout=30_000,
            )
            part_rows = page.locator(
                '.documentation-target-row[data-target-type="occurrence"]'
            )
            part_rows.nth(0).click()
            part_rows.nth(1).click(modifiers=["Control"])
            part_rows.nth(2).click(modifiers=["Control"])
            distributed_ids = page.evaluate(
                "window.__compareDbg.state.partsManualDocumentationSelections.map(row => row.targetId)"
            )
            page.locator("#documentationAlignMenuRibbon").click()
            page.locator("#documentationDistributeHorizontalRibbon").click()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene?.commands?.[
                        window.__compareDbg.state.partsManualDocumentation.scene.historyCursor - 1
                    ]?.arrangement === 'distribute_horizontal'
                )""",
                timeout=60_000,
            )
            distributed_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            distribute_command = distributed_scene["commands"][
                distributed_scene["historyCursor"] - 1
            ]
            transformed_ids = {
                row["targetId"] for row in distribute_command.get("transforms", [])
            }
            record(
                "horizontal_distribution_is_executed_and_persisted",
                distribute_command["operation"] == "arrange"
                and distribute_command["arrangement"] == "distribute_horizontal"
                and bool(transformed_ids)
                and transformed_ids.issubset(set(distributed_ids)),
                distribute_command,
            )

            part_rows = page.locator(
                '.documentation-target-row[data-target-type="occurrence"]'
            )
            part_rows.nth(0).click()
            snap_drag = page.evaluate(
                """() => {
                    const target = window.__compareDbg.state.partsManualDocumentationSelection;
                    const pageModel = _documentationActivePage();
                    const canvas = window.__compareDbg.state.assyRenderer?.domElement;
                    const row = _documentationProjectedBounds(pageModel, target);
                    if (!target || !canvas || !row) return null;
                    const rect = canvas.getBoundingClientRect();
                    const meshes = _partsManualPageMeshes(pageModel);
                    const raycaster = new THREE.Raycaster();
                    let point = null;
                    for (let yi = 1; yi < 12 && !point; yi += 1) {
                        for (let xi = 1; xi < 12; xi += 1) {
                            const x = row.left + (row.right - row.left) * xi / 12;
                            const y = row.top + (row.bottom - row.top) * yi / 12;
                            raycaster.setFromCamera(new THREE.Vector2(x * 2 - 1, 1 - y * 2), window.__compareDbg.state.assyCamera);
                            const hit = raycaster.intersectObjects(meshes, false)[0];
                            const hitTarget = hit ? _documentationTargetFromHit(pageModel, hit.object) : null;
                            if (hitTarget?.targetType === target.targetType
                                && hitTarget?.targetId === target.targetId) {
                                point = {
                                    x: rect.left + x * rect.width,
                                    y: rect.top + y * rect.height,
                                };
                                break;
                            }
                        }
                    }
                    if (!point) return null;
                    const xDistance = Math.abs(row.centerX - 0.5);
                    const yDistance = Math.abs(row.centerY - 0.5);
                    const axis = xDistance >= yDistance ? 'x' : 'y';
                    return {
                        startX: point.x,
                        startY: point.y,
                        endX: point.x + (axis === 'x' ? (0.5 - row.centerX) * rect.width : 0),
                        endY: point.y + (axis === 'y' ? (0.5 - row.centerY) * rect.height : 0),
                        axis,
                        targetId: target.targetId,
                    };
                }"""
            )
            if snap_drag is None:
                raise RuntimeError("could not resolve a visible component point for snap proof")
            page.mouse.move(snap_drag["startX"], snap_drag["startY"])
            page.mouse.down()
            page.mouse.move(
                snap_drag["endX"], snap_drag["endY"], steps=12
            )
            guide_state = page.evaluate(
                """() => ({
                    vertical: getComputedStyle(document.querySelector(
                        '#documentationSnapGuideVertical'
                    )).display,
                    horizontal: getComputedStyle(document.querySelector(
                        '#documentationSnapGuideHorizontal'
                    )).display,
                })"""
            )
            page.mouse.up()
            page.wait_for_function(
                """targetId => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene?.commands?.[
                        window.__compareDbg.state.partsManualDocumentation.scene.historyCursor - 1
                    ]?.operation === 'translate'
                    && window.__compareDbg.state.partsManualDocumentation.scene.commands[
                        window.__compareDbg.state.partsManualDocumentation.scene.historyCursor - 1
                    ]?.targetId === targetId
                )""",
                arg=snap_drag["targetId"],
                timeout=60_000,
            )
            snapped_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            snapped_command = snapped_scene["commands"][snapped_scene["historyCursor"] - 1]
            expected_guide = "vertical" if snap_drag["axis"] == "x" else "horizontal"
            record(
                "pointer_drag_uses_a_visible_page_center_snap_guide_and_persists",
                guide_state[expected_guide] == "block"
                and snapped_command["operation"] == "translate"
                and snapped_command["targetId"] == snap_drag["targetId"],
                {
                    "axis": snap_drag["axis"],
                    "guides": guide_state,
                    "command": snapped_command,
                },
            )

            page.locator("#documentationResetMenuRibbon").click()
            page.locator("#documentationResetRibbon").click()
            page.wait_for_function(
                """targetId => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene?.commands?.[
                        window.__compareDbg.state.partsManualDocumentation.scene.historyCursor - 1
                    ]?.operation === 'reset'
                    && window.__compareDbg.state.partsManualDocumentation.scene.commands[
                        window.__compareDbg.state.partsManualDocumentation.scene.historyCursor - 1
                    ]?.targetId === targetId
                )""",
                arg=snap_drag["targetId"],
                timeout=60_000,
            )
            object_reset_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            remaining_occurrence_overrides = object_reset_scene.get("pages", {}).get(
                page_id, {}
            ).get("occurrenceOverrides", {})
            record(
                "reset_object_restores_the_selected_component_to_its_ai_baseline",
                snap_drag["targetId"] not in remaining_occurrence_overrides,
                {
                    "targetId": snap_drag["targetId"],
                    "remainingOccurrenceOverrides": remaining_occurrence_overrides,
                },
            )

            part_rows = page.locator(
                '.documentation-target-row[data-target-type="occurrence"]'
            )
            part_rows.nth(0).click()
            page.locator("#documentationArrangeMenuRibbon").click()
            page.locator("#documentationRotateRightRibbon").click()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene?.commands?.at(-1)
                        ?.operation === 'rotate'
                )""",
                timeout=60_000,
            )
            rotated_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            rotate_command = rotated_scene["commands"][rotated_scene["historyCursor"] - 1]
            rotation = rotated_scene["pages"][page_id]["occurrenceOverrides"][
                rotate_command["targetId"]
            ]["rotation"]
            record(
                "presentation_rotation_persists_without_changing_product_semantics",
                rotate_command["rotation"] == [0.0, 15.0, 0.0]
                and rotation == [0.0, 15.0, 0.0],
                {"command": rotate_command, "override": rotation},
            )

            page.locator("#documentationViewMenuRibbon").click()
            page.locator("#documentationViewFrontRibbon").click()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene?.commands?.at(-1)
                        ?.operation === 'set_view'
                )""",
                timeout=60_000,
            )
            viewed_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            record(
                "publication_camera_preset_is_persistent_and_visibly_active",
                viewed_scene["pages"][page_id]["figureOverride"]["cameraPreset"] == "front"
                and page.locator("#documentationViewFrontRibbon").get_attribute(
                    "aria-pressed"
                ) == "true",
                viewed_scene["pages"][page_id]["figureOverride"],
            )

            page.locator("#documentationViewMenuRibbon").click()
            page.locator("#documentationExplodeMoreRibbon").click()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene?.commands?.at(-1)
                        ?.operation === 'adjust_explode'
                )""",
                timeout=60_000,
            )
            spaced_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            record(
                "exploded_view_spacing_is_a_persistent_figure_override",
                spaced_scene["pages"][page_id]["figureOverride"]["explodeScale"] == 1.15,
                spaced_scene["pages"][page_id]["figureOverride"],
            )

            page.locator(
                ".documentation-target-row",
                has_text="Bill of materials",
            ).click()
            resize_handle = page.locator(
                "#documentationPageSidecar .documentation-resize-handle"
            )
            resize_handle.wait_for(state="visible")
            before_resize = page.locator("#documentationPageSidecar").bounding_box()
            handle_box = resize_handle.bounding_box()
            page.mouse.move(
                handle_box["x"] + handle_box["width"] / 2,
                handle_box["y"] + handle_box["height"] / 2,
            )
            page.mouse.down()
            page.mouse.move(
                handle_box["x"] + handle_box["width"] / 2 + 24,
                handle_box["y"] + handle_box["height"] / 2 + 12,
                steps=5,
            )
            page.mouse.up()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene?.commands?.at(-1)
                        ?.operation === 'resize'
                )""",
                timeout=30_000,
            )
            after_resize = page.locator("#documentationPageSidecar").bounding_box()
            resized_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            size_delta = resized_scene["pages"][page_id]["pageElementOverrides"]["bom"][
                "sizeDelta"
            ]
            record(
                "bom_resize_handle_updates_the_shared_publication_override",
                after_resize["width"] > before_resize["width"] + 15
                and after_resize["height"] > before_resize["height"] + 7
                and size_delta[0] > 0
                and size_delta[1] > 0,
                {
                    "before": before_resize,
                    "after": after_resize,
                    "sizeDelta": size_delta,
                },
            )

            thumbnails = page.evaluate(
                """() => ({
                    count: document.querySelectorAll('.documentation-page-thumbnail').length,
                    rendered: document.querySelectorAll('.documentation-page-thumbnail img').length,
                    resizeHandleVisible: getComputedStyle(document.querySelector(
                        '#documentationPageSidecar .documentation-resize-handle'
                    )).display !== 'none',
                })"""
            )
            record(
                "page_rail_and_selection_handles_are_visual_editor_objects",
                thumbnails["count"] == 8 and thumbnails["resizeHandleVisible"],
                thumbnails,
            )

            reset_cursor = resized_scene["historyCursor"]
            page.locator("#documentationResetMenuRibbon").click()
            page.locator("#documentationResetPageRibbon").click()
            page.wait_for_function(
                """() => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene?.commands?.at(-1)
                        ?.operation === 'reset_page'
                )""",
                timeout=60_000,
            )
            reset_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            reset_command_cursor = reset_scene["historyCursor"]
            reset_clean = page_id not in reset_scene["pages"]
            page.locator("#documentationUndoRibbon").click()
            page.wait_for_function(
                """cursor => Boolean(
                    !document.querySelector('#documentationWorkspace.busy')
                    && window.__compareDbg.state.partsManualDocumentation?.scene
                        ?.historyCursor === cursor - 1
                )""",
                arg=reset_command_cursor,
                timeout=60_000,
            )
            restored_scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()["scene"]
            record(
                "reset_page_is_atomic_and_one_undo_restores_all_overrides",
                reset_clean
                and reset_cursor == reset_command_cursor - 1
                and restored_scene["pages"][page_id]["figureOverride"]["cameraPreset"] == "front"
                and restored_scene["pages"][page_id]["figureOverride"]["explodeScale"] == 1.15
                and restored_scene["pages"][page_id]["pageElementOverrides"]["bom"][
                    "sizeDelta"
                ] == size_delta,
                {
                    "resetClean": reset_clean,
                    "resetCursor": reset_command_cursor,
                    "restoredPage": restored_scene["pages"].get(page_id),
                },
            )

            ribbon_geometry = page.evaluate(
                """() => {
                    const ribbon = document.querySelector('.documentation-workflow-ribbon');
                    const publish = document.querySelector('#documentationPublishRibbon');
                    const bounds = publish?.getBoundingClientRect();
                    return {
                        ribbonScrollWidth: ribbon?.scrollWidth || 0,
                        ribbonClientWidth: ribbon?.clientWidth || 0,
                        publishRight: bounds?.right || 0,
                        viewportWidth: window.innerWidth,
                    };
                }"""
            )
            record(
                "complete_documentation_ribbon_remains_reachable",
                ribbon_geometry["publishRight"] <= ribbon_geometry["viewportWidth"] + 1,
                ribbon_geometry,
            )
            record(
                "arrangement_workflow_has_no_runtime_or_api_failures",
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

            OUT.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(OUT / "documentation_arrange.png"), full_page=True)
            report["screenshot"] = str(OUT / "documentation_arrange.png")
            request.dispose()
            context.close()
            browser.close()
    finally:
        server.stop()

    passed = all(row["ok"] for row in report["checks"].values())
    report["status"] = "PASS" if passed else "FAIL"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "documentation_arrange_proof.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(run())
