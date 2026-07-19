"""Live Playwright smoke for source-tree process-map authoring."""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "runtime_logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
APP_URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8023/")


def _synthetic_structure() -> dict:
    return {
        "schemaVersion": 1,
        "productId": "racing-bike",
        "productName": "Synthetic Product Structure",
        "occurrences": [
            {
                "occurrenceId": "root",
                "parentOccurrenceId": None,
                "itemId": None,
                "name": "Synthetic Assembly",
                "kind": "assembly",
                "level": 0,
                "partIds": ["SYN-A", "SYN-B"],
            },
            {
                "occurrenceId": "module-a",
                "parentOccurrenceId": "root",
                "itemId": None,
                "name": "Module A",
                "kind": "subassembly",
                "level": 1,
                "partIds": ["SYN-A"],
            },
            {
                "occurrenceId": "module-b",
                "parentOccurrenceId": "root",
                "itemId": None,
                "name": "Module B",
                "kind": "subassembly",
                "level": 1,
                "partIds": ["SYN-B"],
            },
            {
                "occurrenceId": "part-a-1",
                "parentOccurrenceId": "module-a",
                "itemId": "RB-003",
                "name": "Repeated Part A",
                "kind": "part",
                "level": 2,
                "partIds": ["RB-003"],
            },
            {
                "occurrenceId": "part-a-2",
                "parentOccurrenceId": "module-a",
                "itemId": "RB-003",
                "name": "Repeated Part A",
                "kind": "part",
                "level": 2,
                "partIds": ["RB-003"],
            },
            {
                "occurrenceId": "part-b",
                "parentOccurrenceId": "module-b",
                "itemId": "SYN-B",
                "name": "Part B",
                "kind": "part",
                "level": 2,
                "partIds": ["SYN-B"],
            },
        ],
    }


def _synthetic_process_map() -> dict:
    return {
        "schemaVersion": 3,
        "mapId": "default",
        "productId": "racing-bike",
        "productName": "Synthetic Process Map",
        "sourceStructureRevision": "structure-rev-1",
        "layoutVersion": 1,
        "canvasNodes": [],
        "canvasEdges": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }


def _install_synthetic_process_map_route(page, store: dict) -> None:
    def fulfill(route, status: int, payload: dict) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def handler(route) -> None:
        request = route.request
        if request.method == "GET":
            fulfill(
                route,
                200,
                {
                    "success": True,
                    "map": copy.deepcopy(store["map"]),
                    "revision": store["revision"],
                    "findings": copy.deepcopy(store.get("findings", [])),
                    "productStructure": copy.deepcopy(store["structure"]),
                    "structureRevision": "structure-rev-1",
                    "assetName": "synthetic_process_map.json",
                },
            )
            return

        payload = request.post_data_json or {}
        submitted = copy.deepcopy(payload.get("map") or {})
        store["putCount"] += 1
        if store.pop("conflictNext", False):
            store["revision"] = "rev-external"
            fulfill(route, 409, {"error": "revision_conflict", "currentRevision": store["revision"]})
            return
        pairs = {
            (edge.get("from", {}).get("nodeId"), edge.get("to", {}).get("nodeId")): edge
            for edge in submitted.get("canvasEdges", [])
            if edge.get("kind") == "precedence"
        }
        reverse_pair = next(
            (
                edge for (source, target), edge in pairs.items()
                if (target, source) in pairs
            ),
            None,
        )
        if reverse_pair:
            fulfill(
                route,
                422,
                {
                    "error": "validation_failed",
                    "findings": [
                        {
                            "severity": "error",
                            "code": "precedence_cycle",
                            "edgeId": reverse_pair.get("edgeId"),
                            "message": "Precedence edges must not form a cycle.",
                        }
                    ],
                },
            )
            return
        store["map"] = submitted
        store["revision"] = f"rev-{store['putCount'] + 1}"
        store["findings"] = []
        fulfill(
            route,
            200,
            {
                "success": True,
                "map": copy.deepcopy(store["map"]),
                "revision": store["revision"],
                "findings": [],
                "productStructure": copy.deepcopy(store["structure"]),
                "structureRevision": "structure-rev-1",
                "assetName": "synthetic_process_map.json",
            },
        )

    page.route("**/api/training/process-map/racing-bike", handler)


def _wait_for_process_flow_entry(page) -> None:
    page.wait_for_timeout(1_500)
    page.locator("#profileCount").inner_text(timeout=120_000)
    page.locator(".tab[data-tab='training']").click()
    page.wait_for_selector(".tab.active[data-tab='training']", timeout=10_000)
    page.wait_for_selector("[data-training-open-process-flow='true']", timeout=30_000)


def _open_process_flow(page) -> None:
    _wait_for_process_flow_entry(page)
    page.click("[data-training-open-process-flow='true']")
    page.wait_for_selector("[data-process-flow-editor='true']", timeout=15_000)


def _ensure_process_flow_editor(page) -> None:
    page.wait_for_function(
        "document.querySelector('[data-process-flow-editor=true]')"
        " || document.querySelector('[data-training-open-process-flow=true]')",
        timeout=15_000,
    )
    if page.locator("[data-process-flow-editor='true']").count() == 0:
        page.click("[data-training-open-process-flow='true']")
    page.wait_for_selector("[data-process-flow-editor='true']", timeout=15_000)


def _expand(page, occurrence_id: str) -> None:
    row = page.locator(f".pm-tree-row[data-occurrence-id='{occurrence_id}']")
    row.scroll_into_view_if_needed()
    if row.get_attribute("aria-expanded") == "false":
        row.locator(".pm-tree-caret").click()


def _drag_tree_item(page, occurrence_id: str, target_x: float, target_y: float) -> None:
    source = page.locator(f".pm-tree-row[data-occurrence-id='{occurrence_id}']")
    source.scroll_into_view_if_needed()
    source.drag_to(
        page.locator(".pm-viewport"),
        target_position={"x": target_x, "y": target_y},
        force=True,
    )


def _drag_connection(page, from_id: str, to_id: str) -> None:
    output_box = page.locator(f".pm-node[data-node-id='{from_id}'] .pm-port-out").bounding_box()
    input_box = page.locator(f".pm-node[data-node-id='{to_id}'] .pm-port-in").bounding_box()
    assert output_box is not None and input_box is not None
    page.mouse.move(output_box["x"] + output_box["width"] / 2, output_box["y"] + output_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(input_box["x"] + input_box["width"] / 2, input_box["y"] + input_box["height"] / 2, steps=8)
    page.mouse.up()


def _edge_screen_point(page, edge_id: str, fraction: float = 0.5) -> dict:
    return page.locator(f".pm-edge-hit[data-edge-id='{edge_id}']").evaluate(
        """(path, fraction) => {
            const point = path.getPointAtLength(path.getTotalLength() * fraction);
            const matrix = path.getScreenCTM();
            return {
                x: matrix.a * point.x + matrix.c * point.y + matrix.e,
                y: matrix.b * point.x + matrix.d * point.y + matrix.f,
            };
        }""",
        fraction,
    )


def _drag_connection_to_edge(page, from_id: str, edge_id: str, fraction: float = 0.5) -> dict:
    output_box = page.locator(f".pm-node[data-node-id='{from_id}'] .pm-port-out").bounding_box()
    target = _edge_screen_point(page, edge_id, fraction)
    assert output_box is not None
    page.mouse.move(output_box["x"] + output_box["width"] / 2, output_box["y"] + output_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(target["x"], target["y"], steps=10)
    preview = {
        "dot": page.locator(".pm-junction-preview").count(),
        "highlight": page.locator(f".pm-edge.branch-target[data-edge-id='{edge_id}']").count(),
    }
    page.mouse.up()
    return preview


def _drag_connection_to_junction(page, from_id: str, junction_id: str) -> None:
    output_box = page.locator(f".pm-node[data-node-id='{from_id}'] .pm-port-out").bounding_box()
    junction_box = page.locator(f".pm-junction[data-node-id='{junction_id}']").bounding_box()
    assert output_box is not None and junction_box is not None
    page.mouse.move(output_box["x"] + output_box["width"] / 2, output_box["y"] + output_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(junction_box["x"] + junction_box["width"] / 2, junction_box["y"] + junction_box["height"] / 2, steps=8)
    page.mouse.up()


def _drag_connection_from_junction(page, junction_id: str, to_id: str) -> None:
    junction = page.locator(f".pm-junction[data-node-id='{junction_id}']")
    junction.hover()
    output_box = junction.locator(".pm-junction-handle").bounding_box()
    input_box = page.locator(f".pm-node[data-node-id='{to_id}'] .pm-port-in").bounding_box()
    assert output_box is not None and input_box is not None
    page.mouse.move(output_box["x"] + output_box["width"] / 2, output_box["y"] + output_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(input_box["x"] + input_box["width"] / 2, input_box["y"] + input_box["height"] / 2, steps=8)
    page.mouse.up()


def _position_card_in_viewport(
    page,
    node_id: str,
    x_ratio: float,
    y_ratio: float,
    scale: float,
) -> None:
    page.evaluate(
        """({ nodeId, xRatio, yRatio, scale }) => {
            const editor = window.__processMapFlow.editor;
            const viewport = editor.viewport.getBoundingClientRect();
            const position = editor.positions[nodeId];
            const centerX = position.x + position.width / 2;
            const centerY = position.y + position.height / 2;
            editor.transform.scale = scale;
            editor.transform.x = viewport.width * xRatio - centerX * scale;
            editor.transform.y = viewport.height * yRatio - centerY * scale;
            editor.applyTransform();
        }""",
        {
            "nodeId": node_id,
            "xRatio": x_ratio,
            "yRatio": y_ratio,
            "scale": scale,
        },
    )
    page.wait_for_timeout(120)


def _toolbar_geometry(page, node_id: str) -> dict:
    return page.evaluate(
        """nodeId => {
            const compact = element => {
                const value = element.getBoundingClientRect();
                return {
                    x: value.x,
                    y: value.y,
                    width: value.width,
                    height: value.height,
                    right: value.right,
                    bottom: value.bottom,
                };
            };
            const overlaps = (left, right) => !(
                left.right <= right.x || right.right <= left.x
                || left.bottom <= right.y || right.bottom <= left.y
            );
            const toolbarElement = document.querySelector('.pm-card-toolbar');
            const node = document.querySelector(`.pm-node[data-node-id="${nodeId}"]`);
            const inputElement = node.querySelector(':scope > .pm-port-in');
            const outputElement = node.querySelector(':scope > .pm-port-out');
            const toolbar = compact(toolbarElement);
            const card = compact(node);
            const input = compact(inputElement);
            const output = compact(outputElement);
            const viewport = compact(window.__processMapFlow.editor.viewport);
            const placement = toolbarElement.dataset.placement || '';
            const style = getComputedStyle(toolbarElement);
            return {
                toolbar,
                card,
                input,
                output,
                viewport,
                placement,
                onScreen: toolbar.x >= 11 && toolbar.y >= 11
                    && toolbar.right <= window.innerWidth - 11
                    && toolbar.bottom <= window.innerHeight - 11,
                withinViewport: toolbar.x >= viewport.x + 11
                    && toolbar.y >= viewport.y + 11
                    && toolbar.right <= viewport.right - 11
                    && toolbar.bottom <= viewport.bottom - 11,
                overlapsInput: overlaps(toolbar, input),
                overlapsOutput: overlaps(toolbar, output),
                horizontalCenterError: Math.abs(
                    toolbar.x + toolbar.width / 2 - (card.x + card.width / 2)
                ),
                verticalCenterError: Math.abs(
                    toolbar.y + toolbar.height / 2 - (card.y + card.height / 2)
                ),
                backgroundColor: style.backgroundColor,
                color: style.color,
                borderColor: style.borderColor,
                animationName: style.animationName,
            };
        }""",
        node_id,
    )


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report: dict[str, object] = {"url": APP_URL, "checks": {}, "page_errors": []}

    def record(name: str, ok: bool, detail=None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        live_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        live_page = live_context.new_page()
        live_page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        live_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(live_page)
        live_payload = live_page.evaluate(
            """async () => (await (await fetch('/api/training/process-map/racing-bike')).json())"""
        )
        record(
            "live_catalog_and_saved_placements_remain_separate",
            live_payload["map"]["schemaVersion"] == 3
            and len(live_payload["productStructure"]["occurrences"]) > 0
            and live_page.locator(".pm-node").count() == len(live_payload["map"]["canvasNodes"])
            and (
                live_page.locator(".pm-empty-state:visible").count() == 1
            ) == (len(live_payload["map"]["canvasNodes"]) == 0),
            {
                "canvasNodes": len(live_payload["map"]["canvasNodes"]),
                "sourceOccurrences": len(live_payload["productStructure"]["occurrences"]),
            },
        )
        record(
            "solidworks_style_source_tree_is_separate_from_canvas",
            live_page.locator(".pm-structure-sidebar").count() == 1
            and live_page.locator(".pm-tree-row").count() > 0,
        )
        palettes = {}
        viewport_surfaces = {}
        for theme in ("light", "dark"):
            live_page.evaluate("theme => document.documentElement.setAttribute('data-theme', theme)", theme)
            palettes[theme] = live_page.locator(".pm-structure-sidebar").evaluate(
                "el => { const s = getComputedStyle(el); return { body: s.getPropertyValue('--cad-folder-body').trim(), tab: s.getPropertyValue('--cad-folder-tab').trim(), stroke: s.getPropertyValue('--cad-folder-stroke').trim() }; }"
            )
            viewport_surfaces[theme] = live_page.locator(".pm-viewport").evaluate(
                "el => { const base = getComputedStyle(el); const dots = getComputedStyle(el, '::before'); return { base: base.backgroundImage, dots: dots.backgroundImage, dotSize: dots.backgroundSize }; }"
            )
            live_page.screenshot(
                path=str(OUT_DIR / f"process_flow_source_tree_{theme}.png"),
                full_page=False,
            )
        record(
            "folder_palette_is_shared_and_visible_in_both_themes",
            palettes["light"] == palettes["dark"]
            and palettes["dark"] == {"body": "#e2a52e", "tab": "#ffd166", "stroke": "#6b4a12"},
            palettes,
        )
        record(
            "flow_viewport_uses_cad_surface_with_dot_field",
            all(
                "gradient" in viewport_surfaces[theme]["base"]
                and "radial-gradient" in viewport_surfaces[theme]["dots"]
                and viewport_surfaces[theme]["dotSize"] == "22px 22px"
                for theme in ("light", "dark")
            ),
            viewport_surfaces,
        )
        live_context.close()

        fallback_context = browser.new_context(viewport={"width": 1400, "height": 900})
        fallback_page = fallback_context.new_page()
        fallback_page.route(
            "**/api/training/process-map/racing-bike",
            lambda route: route.fulfill(status=404, content_type="application/json", body='{"detail":"disabled"}'),
        )
        fallback_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        fallback_page.locator(".tab[data-tab='training']").click()
        fallback_page.wait_for_selector("[data-training-product-structure-diagram='racing-bike']")
        record(
            "flag_off_preserves_legacy_training_structure",
            fallback_page.locator("[data-training-open-process-flow='true']").count() == 0,
        )
        fallback_context.close()

        store = {
            "map": _synthetic_process_map(),
            "structure": _synthetic_structure(),
            "revision": "rev-1",
            "findings": [],
            "putCount": 0,
        }
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        _install_synthetic_process_map_route(page, store)
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(page)

        record(
            "loading_and_expanding_tree_creates_no_canvas_nodes",
            page.locator(".pm-node").count() == 0,
        )
        _expand(page, "module-a")
        record(
            "assemblies_and_subassemblies_expand_independently",
            page.locator(".pm-tree-row[data-occurrence-id='part-a-1']").count() == 1
            and page.locator(".pm-node").count() == 0,
        )

        viewport_box = page.locator(".pm-viewport").bounding_box()
        assert viewport_box is not None
        first_target = {"x": 330.0, "y": 260.0}
        _drag_tree_item(page, "part-a-1", first_target["x"], first_target["y"])
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 1")
        first_id = page.evaluate("window.__processMapFlow.editor.processMap.canvasNodes[0].nodeId")
        first_box = page.locator(f".pm-node[data-node-id='{first_id}']").bounding_box()
        assert first_box is not None
        record(
            "tree_drop_creates_card_at_release_position",
            abs((first_box["x"] + first_box["width"] / 2) - (viewport_box["x"] + first_target["x"])) < 12
            and abs((first_box["y"] + first_box["height"] / 2) - (viewport_box["y"] + first_target["y"])) < 12,
            {"card": first_box, "viewport": viewport_box, "target": first_target},
        )
        record(
            "placed_tree_occurrence_is_marked",
            page.locator(".pm-tree-row[data-occurrence-id='part-a-1'] .pm-tree-placed").count() == 1,
        )

        page.evaluate("window.__processMapEditorBeforePreview = window.__processMapFlow.editor")
        first_card = page.locator(f".pm-node[data-node-id='{first_id}'] .pm-node-card")
        first_card.click()
        page.wait_for_selector(".pm-card-toolbar")
        record(
            "selecting_card_opens_actions_without_opening_preview",
            page.locator(".pm-card-toolbar").count() == 1
            and page.locator("#trainUniquePreviewShell.open").count() == 0,
        )
        record(
            "context_toolbar_prioritizes_frequent_card_actions",
            page.locator(".pm-card-toolbar [data-card-command='add-step']").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='edit-label']").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='edit-note']").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='preview']").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='delete']").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='orientation']").count() == 0
            and page.locator(".pm-card-toolbar [data-card-command='port-order']").count() == 0,
        )

        page.locator(".pm-card-toolbar [data-card-command='edit-label']").click()
        label_field = page.locator(".pm-card-toolbar [data-card-editor-field='label']")
        label_field.fill("Primary seat shell")
        label_field.press("Enter")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).labelOverride === 'Primary seat shell'",
            arg=first_id,
        )
        record(
            "edit_label_updates_only_the_placed_card",
            "Primary seat shell" in first_card.inner_text()
            and page.locator(".pm-tree-row[data-occurrence-id='part-a-1'] .pm-tree-name").inner_text()
            == "Repeated Part A",
        )

        page.locator(".pm-card-toolbar [data-card-command='edit-note']").click()
        note_field = page.locator(".pm-card-toolbar [data-card-editor-field='note']")
        note_field.fill("Verify the seating surface before the inspection step.")
        note_field.press("Control+Enter")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).note === "
            "'Verify the seating surface before the inspection step.'",
            arg=first_id,
        )
        record(
            "card_note_is_visible_and_persisted_in_map_state",
            page.locator(f".pm-node[data-node-id='{first_id}'] .pm-node-note-indicator").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='edit-note']").get_attribute("aria-pressed") == "true",
        )

        page.locator(".pm-card-toolbar [data-context-command='references']").click()
        page.wait_for_selector(".pm-card-toolbar-editor[data-editor-mode='references']")
        page.locator("[data-reference-kind]").select_option("machine")
        page.locator("[data-reference-field='name']").fill("Five-axis machining center")
        page.locator("[data-reference-field='identifier']").fill("MC-01")
        page.get_by_role("button", name="Attach reference").click()
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).referenceIds.length === 1",
            arg=first_id,
        )
        record(
            "card_context_can_attach_machine_reference",
            page.locator(
                f".pm-node[data-node-id='{first_id}'] .pm-reference-badge-machine"
            ).inner_text() == "M 1"
            and page.evaluate(
                "window.__processMapFlow.editor.processMap.referenceCatalog[0].identifier"
            ) == "MC-01",
        )
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        page.wait_for_timeout(500)
        page.screenshot(
            path=str(OUT_DIR / "process_flow_card_references_light.png"),
            full_page=False,
        )
        page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
        page.get_by_role("button", name="Close reference editor").click()

        page.locator(".pm-card-toolbar [data-card-command='add-step']").select_option("inspection")
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 2"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 1"
        )
        connected_step_id = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeKind === 'process_step').nodeId"
        )
        record(
            "add_connected_step_creates_card_and_precedence_edge_together",
            page.evaluate(
                """({ sourceId, stepId }) => {
                    const map = window.__processMapFlow.editor.processMap;
                    return map.canvasEdges.some(edge => edge.from.nodeId === sourceId
                        && edge.to.nodeId === stepId && edge.kind === 'precedence');
                }""",
                {"sourceId": first_id, "stepId": connected_step_id},
            ),
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 1"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 0"
        )
        record(
            "one_undo_removes_connected_step_and_its_edge",
            page.locator(f".pm-node[data-node-id='{first_id}']").count() == 1,
        )
        first_card.click()
        page.wait_for_selector(".pm-card-toolbar")
        page.screenshot(
            path=str(OUT_DIR / "process_flow_card_toolbar.png"),
            full_page=False,
        )

        toolbar_themes = {}
        for theme in ("light", "dark"):
            page.evaluate(
                "theme => document.documentElement.setAttribute('data-theme', theme)",
                theme,
            )
            page.wait_for_timeout(80)
            geometry = _toolbar_geometry(page, first_id)
            toolbar_themes[theme] = {
                "backgroundColor": geometry["backgroundColor"],
                "color": geometry["color"],
                "borderColor": geometry["borderColor"],
            }
            page.screenshot(
                path=str(OUT_DIR / f"process_flow_card_toolbar_{theme}.png"),
                full_page=False,
            )
        record(
            "card_toolbar_uses_readable_theme_tokens_in_both_modes",
            toolbar_themes["light"] != toolbar_themes["dark"]
            and all(
                values["backgroundColor"] not in ("rgba(0, 0, 0, 0)", "transparent")
                and values["color"] not in ("rgba(0, 0, 0, 0)", "transparent")
                for values in toolbar_themes.values()
            ),
            toolbar_themes,
        )
        page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")

        page.emulate_media(reduced_motion="reduce")
        reduced_animation = _toolbar_geometry(page, first_id)["animationName"]
        page.emulate_media(reduced_motion="no-preference")
        record(
            "card_toolbar_honors_reduced_motion",
            reduced_animation == "none",
            reduced_animation,
        )

        scale_geometry = {}
        for scale in (0.28, 1.6):
            _position_card_in_viewport(page, first_id, 0.5, 0.5, scale)
            geometry = _toolbar_geometry(page, first_id)
            scale_geometry[str(scale)] = geometry
        record(
            "card_toolbar_tracks_at_minimum_and_maximum_zoom",
            all(
                geometry["placement"].startswith(("top", "bottom"))
                and geometry["horizontalCenterError"] < 5
                and geometry["withinViewport"]
                and not geometry["overlapsInput"]
                and not geometry["overlapsOutput"]
                for geometry in scale_geometry.values()
            ),
            scale_geometry,
        )

        inset_x = (310 / 2 + 6) / viewport_box["width"]
        inset_y = (170 / 2 + 6) / viewport_box["height"]
        edge_targets = {
            "top": (0.5, inset_y),
            "right": (1 - inset_x, 0.5),
            "bottom": (0.5, 1 - inset_y),
            "left": (inset_x, 0.5),
        }
        edge_geometry = {}
        for edge_name, (x_ratio, y_ratio) in edge_targets.items():
            _position_card_in_viewport(page, first_id, x_ratio, y_ratio, 1.0)
            edge_geometry[edge_name] = _toolbar_geometry(page, first_id)
        record(
            "flip_and_shift_keep_toolbar_inside_every_viewport_edge",
            all(
                geometry["withinViewport"]
                and geometry["onScreen"]
                and not geometry["overlapsInput"]
                and not geometry["overlapsOutput"]
                for geometry in edge_geometry.values()
            )
            and edge_geometry["top"]["placement"].startswith("bottom")
            and edge_geometry["bottom"]["placement"].startswith("top"),
            edge_geometry,
        )

        page.get_by_role("button", name="Fit flow to viewport").click()
        page.wait_for_timeout(160)
        page.locator(".pm-viewport").click(position={"x": 16, "y": 16})
        page.wait_for_function("!document.querySelector('.pm-card-toolbar')")
        record(
            "outside_canvas_click_dismisses_card_toolbar",
            page.locator(".ip-floating-surface").count() == 0,
        )
        first_card.click()
        page.wait_for_selector(".pm-card-toolbar")

        drag_state_before = page.evaluate(
            """nodeId => ({
                position: structuredClone(window.__processMapFlow.editor.processMap.canvasNodes
                    .find(node => node.nodeId === nodeId).position),
                undoDepth: window.__processMapFlow.editor.history.undoStack.length,
            })""",
            first_id,
        )
        card_before_drag = first_card.bounding_box()
        toolbar_before_drag = page.locator(".pm-card-toolbar").bounding_box()
        assert card_before_drag is not None and toolbar_before_drag is not None
        page.mouse.move(
            card_before_drag["x"] + card_before_drag["width"] / 2,
            card_before_drag["y"] + card_before_drag["height"] / 2,
        )
        page.mouse.down()
        page.mouse.move(
            card_before_drag["x"] + card_before_drag["width"] / 2 + 64,
            card_before_drag["y"] + card_before_drag["height"] / 2 + 38,
            steps=7,
        )
        page.mouse.up()
        page.wait_for_timeout(100)
        card_after_drag = first_card.bounding_box()
        toolbar_after_drag = page.locator(".pm-card-toolbar").bounding_box()
        drag_state_after = page.evaluate(
            """nodeId => ({
                position: structuredClone(window.__processMapFlow.editor.processMap.canvasNodes
                    .find(node => node.nodeId === nodeId).position),
                undoDepth: window.__processMapFlow.editor.history.undoStack.length,
            })""",
            first_id,
        )
        assert card_after_drag is not None and toolbar_after_drag is not None
        record(
            "card_toolbar_tracks_selected_card_during_drag",
            abs((card_after_drag["x"] - card_before_drag["x"])
                - (toolbar_after_drag["x"] - toolbar_before_drag["x"])) < 8
            and abs((card_after_drag["y"] - card_before_drag["y"])
                    - (toolbar_after_drag["y"] - toolbar_before_drag["y"])) < 8
            and drag_state_after["position"] != drag_state_before["position"]
            and drag_state_after["undoDepth"] == drag_state_before["undoDepth"] + 1,
            {
                "cardBefore": card_before_drag,
                "cardAfter": card_after_drag,
                "toolbarBefore": toolbar_before_drag,
                "toolbarAfter": toolbar_after_drag,
                "stateBefore": drag_state_before,
                "stateAfter": drag_state_after,
            },
        )
        if drag_state_after["undoDepth"] > drag_state_before["undoDepth"]:
            page.get_by_role("button", name="Undo process-map edit").click()
            page.wait_for_timeout(160)
        else:
            page.evaluate("window.__processMapFlow.editor.renderGraph({ fit: false })")
        first_card.click()
        page.wait_for_selector(".pm-card-toolbar")

        page.evaluate(
            """() => {
                window.__pmToolbarPreviewOverlap = false;
                if (window.__pmToolbarPreviewObserver) {
                    window.__pmToolbarPreviewObserver.disconnect();
                }
                const observer = new MutationObserver(() => {
                    const shell = document.getElementById('trainUniquePreviewShell');
                    if (shell && shell.classList.contains('open')
                        && document.querySelector('.pm-card-toolbar')) {
                        window.__pmToolbarPreviewOverlap = true;
                    }
                });
                observer.observe(document.body, {
                    childList: true,
                    subtree: true,
                    attributes: true,
                    attributeFilter: ['class'],
                });
                window.__pmToolbarPreviewObserver = observer;
            }"""
        )
        page.locator(".pm-card-toolbar [data-card-command='preview']").click()
        page.wait_for_selector("#trainUniquePreviewShell.open .train-unique-preview-viewer canvas")
        page.wait_for_function(
            "() => { const el = document.querySelector('#trainUniquePreviewShell.open .train-unique-preview-viewer-status'); return el && !el.textContent.toLowerCase().includes('loading'); }",
            timeout=20_000,
        )
        preview_status = page.locator(
            "#trainUniquePreviewShell.open .train-unique-preview-viewer-status"
        ).inner_text()
        page.screenshot(path=str(OUT_DIR / "process_flow_part_3d_preview.png"), full_page=False)
        record(
            "flow_part_card_opens_existing_interactive_3d_viewer",
            page.locator("#trainUniquePreviewBackdrop.open").count() == 1
            and page.locator("#trainUniquePreviewShell.open canvas").count() == 1
            and "interactive 3d" in preview_status.lower(),
            preview_status,
        )
        record(
            "preview_command_closes_toolbar_before_modal_opens",
            page.locator(".pm-card-toolbar").count() == 0
            and page.evaluate("window.__pmToolbarPreviewOverlap === false"),
        )
        page.evaluate(
            """() => {
                if (window.__pmToolbarPreviewObserver) {
                    window.__pmToolbarPreviewObserver.disconnect();
                    window.__pmToolbarPreviewObserver = null;
                }
            }"""
        )
        page.keyboard.press("Escape")
        page.wait_for_function(
            "!document.getElementById('trainUniquePreviewShell').classList.contains('open')"
        )
        page.wait_for_timeout(350)
        record(
            "closing_3d_preview_returns_to_unchanged_flow_canvas",
            page.evaluate(
                "window.__processMapFlow.editor === window.__processMapEditorBeforePreview"
                " && window.__processMapFlow.editor.processMap.canvasNodes.length === 1"
            ),
        )
        first_card.click()
        page.wait_for_selector(".pm-card-toolbar")
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('.pm-card-toolbar')")
        record(
            "escape_dismisses_card_toolbar_and_restores_card_focus",
            first_card.evaluate("card => document.activeElement === card"),
        )

        _drag_tree_item(page, "part-a-1", 520, 320)
        record(
            "duplicate_occurrence_drop_selects_without_copying",
            page.evaluate("window.__processMapFlow.editor.processMap.canvasNodes.length") == 1
            and "already on the map" in page.locator(".pm-editor-status").inner_text().lower(),
        )
        _drag_tree_item(page, "part-a-2", 430, 380)
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 2")
        record(
            "same_part_number_with_distinct_occurrences_can_be_placed",
            page.evaluate(
                "new Set(window.__processMapFlow.editor.processMap.canvasNodes.map(n => n.sourceOccurrenceId)).size"
            ) == 2,
        )

        page.mouse.move(viewport_box["x"] + 80, viewport_box["y"] + viewport_box["height"] - 60)
        page.mouse.down()
        page.mouse.move(viewport_box["x"] + 150, viewport_box["y"] + viewport_box["height"] - 105, steps=6)
        page.mouse.up()
        page.mouse.move(viewport_box["x"] + viewport_box["width"] / 2, viewport_box["y"] + viewport_box["height"] / 2)
        page.mouse.wheel(0, -360)
        _expand(page, "module-b")
        transformed_target = {"x": viewport_box["width"] - 240, "y": viewport_box["height"] - 220}
        _drag_tree_item(page, "part-b", transformed_target["x"], transformed_target["y"])
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 3")
        part_b_id = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.find(n => n.sourceOccurrenceId === 'part-b').nodeId"
        )
        part_b_box = page.locator(f".pm-node[data-node-id='{part_b_id}']").bounding_box()
        assert part_b_box is not None
        record(
            "drop_coordinates_remain_correct_after_pan_and_zoom",
            abs((part_b_box["x"] + part_b_box["width"] / 2) - (viewport_box["x"] + transformed_target["x"])) < 14
            and abs((part_b_box["y"] + part_b_box["height"] / 2) - (viewport_box["y"] + transformed_target["y"])) < 14,
        )

        page.locator(f".pm-node[data-node-id='{part_b_id}'] .pm-node-card").click()
        page.wait_for_selector(".pm-card-toolbar")
        page.locator(".pm-card-toolbar [data-card-command='delete']").click()
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 2")
        record(
            "deleting_card_keeps_tree_source_available",
            page.locator(".pm-tree-row[data-occurrence-id='part-b']").count() == 1
            and page.locator(".pm-tree-row[data-occurrence-id='part-b'] .pm-tree-placed").count() == 0,
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 3")

        page.get_by_role("button", name="Add an operation to the center of the process map").click()
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 4")
        page.locator(".pm-type-select").select_option("inspection")
        process_step_id = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.find(n => n.nodeKind === 'process_step').nodeId"
        )
        record(
            "authored_process_steps_remain_separate_from_product_tree",
            page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'process_step' && n.processType === 'inspection').length"
            ) == 1,
        )

        canvas_ids = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'product_occurrence').slice(0, 2).map(n => n.nodeId)"
        )
        _drag_connection(page, canvas_ids[0], canvas_ids[1])
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasEdges.length === 1")
        trunk_edge_id = page.evaluate("window.__processMapFlow.editor.processMap.canvasEdges[0].edgeId")
        path_before_orientation = page.locator(
            f".pm-edge[data-edge-id='{trunk_edge_id}']"
        ).get_attribute("d")
        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", canvas_ids[1])
        page.locator(".pm-port-orientation-select").select_option("vertical")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrientation === 'vertical'",
            arg=canvas_ids[1],
        )
        vertical_node = page.locator(f".pm-node[data-node-id='{canvas_ids[1]}']")
        vertical_box = vertical_node.bounding_box()
        input_box = vertical_node.locator(":scope > .pm-port-in").bounding_box()
        output_box = vertical_node.locator(":scope > .pm-port-out").bounding_box()
        path_after_orientation = page.locator(
            f".pm-edge[data-edge-id='{trunk_edge_id}']"
        ).get_attribute("d")
        page.wait_for_timeout(120)
        vertical_toolbar_geometry = _toolbar_geometry(page, canvas_ids[1])
        record(
            "selected_card_ports_switch_from_left_right_to_top_bottom",
            vertical_node.evaluate("node => node.classList.contains('pm-node-ports-vertical')")
            and vertical_box is not None
            and input_box is not None
            and output_box is not None
            and abs((input_box["x"] + input_box["width"] / 2)
                    - (vertical_box["x"] + vertical_box["width"] / 2)) < 2
            and abs((output_box["x"] + output_box["width"] / 2)
                    - (vertical_box["x"] + vertical_box["width"] / 2)) < 2
            and abs((input_box["y"] + input_box["height"] / 2) - vertical_box["y"]) < 2
            and abs((output_box["y"] + output_box["height"] / 2)
                    - (vertical_box["y"] + vertical_box["height"])) < 2
            and path_after_orientation != path_before_orientation,
            {
                "node": vertical_box,
                "input": input_box,
                "output": output_box,
                "pathBefore": path_before_orientation,
                "pathAfter": path_after_orientation,
            },
        )
        record(
            "orientation_aware_toolbar_avoids_vertical_ports",
            vertical_toolbar_geometry["placement"].startswith(("right", "left"))
            and vertical_toolbar_geometry["verticalCenterError"] < 5
            and vertical_toolbar_geometry["withinViewport"]
            and not vertical_toolbar_geometry["overlapsInput"]
            and not vertical_toolbar_geometry["overlapsOutput"],
            vertical_toolbar_geometry,
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "nodeId => !window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrientation",
            arg=canvas_ids[1],
        )
        page.get_by_role("button", name="Redo process-map edit").click()
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrientation === 'vertical'",
            arg=canvas_ids[1],
        )
        record(
            "card_port_orientation_is_one_undoable_edit",
            page.locator(f".pm-node[data-node-id='{canvas_ids[1]}']")
            .evaluate("node => node.classList.contains('pm-node-ports-vertical')"),
        )
        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", canvas_ids[1])
        path_before_order = page.locator(
            f".pm-edge[data-edge-id='{trunk_edge_id}']"
        ).get_attribute("d")
        order_select = page.locator(".pm-port-order-select")
        order_labels = order_select.locator("option").all_text_contents()
        order_select.select_option("output_first")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrder === 'output_first'",
            arg=canvas_ids[1],
        )
        reversed_node = page.locator(f".pm-node[data-node-id='{canvas_ids[1]}']")
        reversed_box = reversed_node.bounding_box()
        reversed_input_box = reversed_node.locator(":scope > .pm-port-in").bounding_box()
        reversed_output_box = reversed_node.locator(":scope > .pm-port-out").bounding_box()
        path_after_order = page.locator(
            f".pm-edge[data-edge-id='{trunk_edge_id}']"
        ).get_attribute("d")
        record(
            "vertical_card_can_swap_input_bottom_and_output_top",
            order_labels == ["Input: top", "Input: bottom"]
            and reversed_node.evaluate(
                "node => node.classList.contains('pm-node-port-order-output_first')"
            )
            and reversed_box is not None
            and reversed_input_box is not None
            and reversed_output_box is not None
            and abs((reversed_input_box["y"] + reversed_input_box["height"] / 2)
                    - (reversed_box["y"] + reversed_box["height"])) < 2
            and abs((reversed_output_box["y"] + reversed_output_box["height"] / 2)
                    - reversed_box["y"]) < 2
            and path_after_order != path_before_order,
            {
                "labels": order_labels,
                "node": reversed_box,
                "input": reversed_input_box,
                "output": reversed_output_box,
                "pathBefore": path_before_order,
                "pathAfter": path_after_order,
            },
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "nodeId => !window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrder",
            arg=canvas_ids[1],
        )
        page.get_by_role("button", name="Redo process-map edit").click()
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrder === 'output_first'",
            arg=canvas_ids[1],
        )
        record(
            "card_port_order_is_one_undoable_edit",
            page.locator(f".pm-node[data-node-id='{canvas_ids[1]}']")
            .evaluate("node => node.classList.contains('pm-node-port-order-output_first')"),
        )
        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", canvas_ids[1])
        page.locator(".pm-port-order-select").select_option("input_first")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrder === 'input_first'",
            arg=canvas_ids[1],
        )
        _drag_connection_to_edge(page, process_step_id, trunk_edge_id, 0.995)
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasEdges.length === 2")
        record(
            "drop_near_wire_endpoint_reuses_existing_node",
            page.evaluate(
                """({ sourceId, targetId }) => {
                    const map = window.__processMapFlow.editor.processMap;
                    return !map.canvasNodes.some(node => node.nodeKind === 'junction')
                        && map.canvasEdges.some(edge => edge.from.nodeId === sourceId && edge.to.nodeId === targetId);
                }""",
                {"sourceId": process_step_id, "targetId": canvas_ids[1]},
            ),
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasEdges.length === 1")
        preview = _drag_connection_to_edge(page, part_b_id, trunk_edge_id)
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'junction').length === 1"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 3"
        )
        record(
            "wire_target_highlights_and_shows_preview_before_drop",
            preview == {"dot": 1, "highlight": 1},
            preview,
        )
        junction_id = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.find(n => n.nodeKind === 'junction').nodeId"
        )
        record(
            "junction_selection_never_opens_card_toolbar",
            page.locator(".pm-card-toolbar").count() == 0,
        )
        topology = page.evaluate(
            """({ sourceId, junctionId, trunkId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    originalRemoved: !map.canvasEdges.some(edge => edge.edgeId === trunkId),
                    branch: map.canvasEdges.some(edge => edge.from.nodeId === sourceId && edge.to.nodeId === junctionId),
                    incoming: map.canvasEdges.filter(edge => edge.to.nodeId === junctionId).length,
                    outgoing: map.canvasEdges.filter(edge => edge.from.nodeId === junctionId).length,
                    logicalTrunkSegments: map.canvasEdges.filter(edge => edge.logicalConnectionId === trunkId).length,
                };
            }""",
            {"sourceId": part_b_id, "junctionId": junction_id, "trunkId": trunk_edge_id},
        )
        record(
            "drop_on_wire_creates_persistent_directed_junction_topology",
            topology == {
                "originalRemoved": True,
                "branch": True,
                "incoming": 2,
                "outgoing": 1,
                "logicalTrunkSegments": 2,
            }
            and page.locator(f".pm-junction[data-node-id='{junction_id}']").count() == 1,
            topology,
        )

        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 4"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 1"
        )
        undo_topology = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasEdges[0].edgeId"
        )
        page.get_by_role("button", name="Redo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'junction').length === 1"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 3"
        )
        record(
            "junction_split_is_one_atomic_undo_and_redo_action",
            undo_topology == trunk_edge_id,
        )

        branch_edge_id = page.evaluate(
            """({ sourceId, junctionId }) => window.__processMapFlow.editor.processMap.canvasEdges
                .find(edge => edge.from.nodeId === sourceId && edge.to.nodeId === junctionId).edgeId""",
            {"sourceId": part_b_id, "junctionId": junction_id},
        )
        page.locator(f".pm-edge-hit[data-edge-id='{branch_edge_id}']").focus()
        page.keyboard.press("Enter")
        page.get_by_role("button", name="Delete selected node or connection").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 4"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 1"
        )
        collapsed = page.evaluate(
            """({ fromId, toId }) => {
                const map = window.__processMapFlow.editor.processMap;
                const edge = map.canvasEdges[0];
                return !map.canvasNodes.some(node => node.nodeKind === 'junction')
                    && edge.from.nodeId === fromId && edge.to.nodeId === toId;
            }""",
            {"fromId": canvas_ids[0], "toId": canvas_ids[1]},
        )
        record("deleting_branch_preserves_and_collapses_original_trunk", collapsed)
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'junction').length === 1"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 3"
        )

        _drag_connection_to_junction(page, process_step_id, junction_id)
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasEdges.length === 4")
        record(
            "dropping_near_existing_junction_reuses_it",
            page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'junction').length"
            ) == 1,
        )

        page.get_by_role("button", name="Add an operation to the center of the process map").click()
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 6")
        second_step_id = page.evaluate(
            """existingId => window.__processMapFlow.editor.processMap.canvasNodes
                .find(node => node.nodeKind === 'process_step' && node.nodeId !== existingId).nodeId""",
            process_step_id,
        )
        page.get_by_role("button", name="Fit flow to viewport").click()
        page.wait_for_timeout(160)
        _drag_connection_from_junction(page, junction_id, second_step_id)
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasEdges.length === 5")
        record(
            "junction_can_start_an_additional_wire",
            page.evaluate(
                """({ junctionId, targetId }) => window.__processMapFlow.editor.processMap.canvasEdges
                    .some(edge => edge.from.nodeId === junctionId && edge.to.nodeId === targetId)""",
                {"junctionId": junction_id, "targetId": second_step_id},
            ),
        )

        junction_before = page.evaluate(
            """junctionId => ({
                position: window.__processMapFlow.editor.processMap.canvasNodes.find(node => node.nodeId === junctionId).position,
                paths: Array.from(document.querySelectorAll('.pm-edge[data-edge-id]'))
                    .filter(path => {
                        const edge = window.__processMapFlow.editor.processMap.canvasEdges.find(item => item.edgeId === path.dataset.edgeId);
                        return edge && (edge.from.nodeId === junctionId || edge.to.nodeId === junctionId);
                    }).map(path => path.getAttribute('d')),
            })""",
            junction_id,
        )
        junction_box = page.locator(f".pm-junction[data-node-id='{junction_id}']").bounding_box()
        assert junction_box is not None
        page.mouse.move(junction_box["x"] + junction_box["width"] / 2, junction_box["y"] + junction_box["height"] / 2)
        page.mouse.down()
        page.mouse.move(junction_box["x"] + junction_box["width"] / 2 + 60, junction_box["y"] + junction_box["height"] / 2 + 45, steps=8)
        page.mouse.up()
        junction_after = page.evaluate(
            """junctionId => ({
                position: window.__processMapFlow.editor.processMap.canvasNodes.find(node => node.nodeId === junctionId).position,
                paths: Array.from(document.querySelectorAll('.pm-edge[data-edge-id]'))
                    .filter(path => {
                        const edge = window.__processMapFlow.editor.processMap.canvasEdges.find(item => item.edgeId === path.dataset.edgeId);
                        return edge && (edge.from.nodeId === junctionId || edge.to.nodeId === junctionId);
                    }).map(path => path.getAttribute('d')),
            })""",
            junction_id,
        )
        record(
            "moving_junction_updates_all_attached_wires",
            junction_after["position"] != junction_before["position"]
            and junction_after["paths"] != junction_before["paths"],
            {"before": junction_before, "after": junction_after},
        )

        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", canvas_ids[1])
        page.locator(".pm-port-order-select").select_option("output_first")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrder === 'output_first'",
            arg=canvas_ids[1],
        )

        trunk_segment_id = page.evaluate(
            "logicalId => window.__processMapFlow.editor.processMap.canvasEdges"
            ".find(edge => edge.logicalConnectionId === logicalId).edgeId",
            trunk_edge_id,
        )
        page.locator(f".pm-edge-hit[data-edge-id='{trunk_segment_id}']").focus()
        page.keyboard.press("Enter")
        page.wait_for_selector(f".pm-edge-toolbar[data-edge-id='{trunk_segment_id}']")
        page.locator(".pm-edge-toolbar [data-card-command='edge-label']").click()
        edge_label_field = page.locator("[data-card-editor-field='edge-label']")
        edge_label_field.fill("Inspection release")
        edge_label_field.press("Enter")
        page.wait_for_function(
            "edgeId => window.InspectorProProcessMap.logicalEdgeLabel("
            "window.__processMapFlow.editor.processMap, edgeId) === 'Inspection release'",
            arg=trunk_segment_id,
        )
        page.locator(".pm-edge-toolbar [data-context-command='references']").click()
        page.wait_for_selector(".pm-card-toolbar-editor[data-editor-mode='references']")
        page.locator("[data-reference-kind]").select_option("standard")
        page.locator("[data-reference-field='name']").fill("Dimensioning and tolerancing")
        page.locator("[data-reference-field='identifier']").fill("ASME Y14.5")
        page.locator("[data-reference-field='revision']").fill("2018")
        page.locator("[data-reference-field='clause']").fill("7.5")
        page.get_by_role("button", name="Attach reference").click()
        page.wait_for_function(
            "logicalId => window.__processMapFlow.editor.processMap.canvasEdges"
            ".filter(edge => edge.logicalConnectionId === logicalId)"
            ".every(edge => Array.isArray(edge.referenceIds) && edge.referenceIds.length === 1)",
            arg=trunk_edge_id,
        )
        record(
            "wire_context_propagates_standard_across_logical_segments",
            page.evaluate(
                "logicalId => { const edges = window.__processMapFlow.editor.processMap.canvasEdges"
                ".filter(edge => edge.logicalConnectionId === logicalId);"
                " return edges.length === 2 && edges.every(edge => edge.referenceIds.length === 1); }",
                trunk_edge_id,
            )
            and page.locator(".pm-edge-context-label").filter(
                has_text="Inspection release | Std 1"
            ).count() == 1,
        )

        group_setup = page.evaluate(
            """nodeId => {
                const editor = window.__processMapFlow.editor;
                editor.addCanvasGroup();
                const runtime = window.InspectorProProcessMap;
                const group = editor.processMap.canvasGroups.at(-1);
                const node = editor.processMap.canvasNodes.find(item => item.nodeId === nodeId);
                let next = runtime.resizeGroup(editor.processMap, group.groupId, {
                    position: { x: node.position.x - 90, y: node.position.y - 75 },
                    size: { width: 560, height: 340 },
                });
                next = runtime.setGroupMembers(next, group.groupId, [nodeId]);
                editor.commitMutation(next);
                editor.selectGroup(group.groupId);
                return { groupId: group.groupId, nodeId };
            }""",
            first_id,
        )
        group_id = group_setup["groupId"]
        page.wait_for_selector(f".pm-group-frame[data-group-id='{group_id}']")
        page.wait_for_selector(f".pm-group-toolbar[data-group-id='{group_id}']")
        record(
            "group_layer_is_below_edges_and_nodes_with_click_through_body",
            page.evaluate(
                """groupId => {
                    const editor = window.__processMapFlow.editor;
                    const order = Array.from(editor.world.children).map(item => item.className.baseVal || item.className);
                    const frame = editor.groupLayer.querySelector(`[data-group-id="${groupId}"]`);
                    const header = frame.querySelector('.pm-group-header');
                    return order[0] === 'pm-group-layer'
                        && order[1] === 'pm-edge-layer'
                        && order[2] === 'pm-node-layer'
                        && getComputedStyle(frame).pointerEvents === 'none'
                        && getComputedStyle(header).pointerEvents === 'auto';
                }""",
                group_id,
            ),
        )
        record(
            "group_selection_uses_one_context_toolbar_with_frequent_actions",
            page.locator(".ip-floating-surface").count() == 1
            and page.locator(".pm-group-toolbar [data-group-command='rename']").count() == 1
            and page.locator(".pm-group-toolbar .pm-group-color-select").count() == 1
            and page.locator(".pm-group-toolbar .pm-group-toolbar-move-only").count() == 1
            and page.locator(".pm-group-toolbar [data-group-command='delete']").count() == 1,
        )
        page.locator(".pm-group-toolbar [data-group-command='rename']").click()
        page.locator(".pm-group-toolbar .pm-card-toolbar-field").fill("Final inspection cell")
        page.get_by_role("button", name="Save group label").click()
        page.locator(".pm-group-toolbar .pm-group-color-select").select_option("teal")
        record(
            "group_toolbar_renames_and_recolors_through_undoable_mutations",
            page.evaluate(
                """groupId => {
                    const group = window.__processMapFlow.editor.processMap.canvasGroups
                        .find(item => item.groupId === groupId);
                    return group.label === 'Final inspection cell' && group.colorKey === 'teal';
                }""",
                group_id,
            )
            and page.locator(
                f".pm-group-frame[data-group-id='{group_id}'].pm-group-color-teal"
            ).count() == 1,
        )

        before_group_move = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                    undoDepth: window.__processMapFlow.editor.history.undoStack.length,
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        group_header = page.locator(f".pm-group-frame[data-group-id='{group_id}'] .pm-group-header")
        header_box = group_header.bounding_box()
        assert header_box is not None
        page.mouse.move(header_box["x"] + header_box["width"] / 2, header_box["y"] + 12)
        page.mouse.down()
        page.mouse.move(header_box["x"] + header_box["width"] / 2 + 80, header_box["y"] + 62, steps=8)
        page.mouse.up()
        after_group_move = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                    undoDepth: window.__processMapFlow.editor.history.undoStack.length,
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        group_dx = after_group_move["group"]["x"] - before_group_move["group"]["x"]
        group_dy = after_group_move["group"]["y"] - before_group_move["group"]["y"]
        record(
            "group_header_drag_moves_frame_and_members_as_one_history_entry",
            abs((after_group_move["node"]["x"] - before_group_move["node"]["x"]) - group_dx) < 1
            and abs((after_group_move["node"]["y"] - before_group_move["node"]["y"]) - group_dy) < 1
            and after_group_move["undoDepth"] == before_group_move["undoDepth"] + 1,
            {"before": before_group_move, "after": after_group_move},
        )

        page.evaluate("groupId => window.__processMapFlow.editor.selectGroup(groupId)", group_id)
        page.wait_for_selector(".pm-group-toolbar .pm-group-toolbar-move-only")
        page.locator(".pm-group-toolbar .pm-group-toolbar-move-only").click()
        frame_only_before = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        header_box = group_header.bounding_box()
        assert header_box is not None
        page.mouse.move(header_box["x"] + header_box["width"] / 2, header_box["y"] + 12)
        page.mouse.down()
        page.mouse.move(header_box["x"] + header_box["width"] / 2 + 55, header_box["y"] + 42, steps=6)
        page.mouse.up()
        frame_only_after = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        record(
            "group_toolbar_frame_only_mode_leaves_member_coordinates_unchanged",
            frame_only_after["group"] != frame_only_before["group"]
            and frame_only_after["node"] == frame_only_before["node"],
            {"before": frame_only_before, "after": frame_only_after},
        )

        page.evaluate("window.__processMapFlow.editor.fit()")
        page.wait_for_timeout(150)
        size_before = page.evaluate(
            "groupId => structuredClone(window.__processMapFlow.editor.processMap.canvasGroups.find(item => item.groupId === groupId).size)",
            group_id,
        )
        resize_handle = page.locator(
            f".pm-group-frame[data-group-id='{group_id}'] .pm-group-resize-se"
        )
        resize_box = resize_handle.bounding_box()
        assert resize_box is not None
        resize_hit = page.evaluate(
            """point => {
                const target = document.elementFromPoint(point.x, point.y);
                const viewport = window.__processMapFlow.editor.viewport.getBoundingClientRect();
                return {
                    tag: target ? target.tagName : null,
                    className: target ? target.className : null,
                    x: point.x,
                    y: point.y,
                    viewport: {
                        x: viewport.x,
                        y: viewport.y,
                        right: viewport.right,
                        bottom: viewport.bottom,
                    },
                };
            }""",
            {"x": resize_box["x"] + 6, "y": resize_box["y"] + 6},
        )
        page.mouse.move(resize_box["x"] + 6, resize_box["y"] + 6)
        page.mouse.down()
        resize_interaction = page.evaluate(
            "window.__processMapFlow.editor.interaction && window.__processMapFlow.editor.interaction.mode"
        )
        page.mouse.move(resize_box["x"] + 86, resize_box["y"] + 56, steps=6)
        page.mouse.up()
        size_after = page.evaluate(
            "groupId => structuredClone(window.__processMapFlow.editor.processMap.canvasGroups.find(item => item.groupId === groupId).size)",
            group_id,
        )
        record(
            "selected_group_resizes_from_canvas_handle",
            size_after["width"] > size_before["width"]
            and size_after["height"] > size_before["height"],
            {
                "before": size_before,
                "after": size_after,
                "hit": resize_hit,
                "interaction": resize_interaction,
            },
        )

        page.evaluate("groupId => window.__processMapFlow.editor.selectGroup(groupId)", group_id)
        page.wait_for_selector(".pm-group-toolbar .pm-group-toolbar-move-only")
        move_only_button = page.locator(".pm-group-toolbar .pm-group-toolbar-move-only")
        if move_only_button.get_attribute("aria-pressed") == "true":
            move_only_button.click()
        alt_move_before = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        group_header = page.locator(f".pm-group-frame[data-group-id='{group_id}'] .pm-group-header")
        header_box = group_header.bounding_box()
        assert header_box is not None
        page.keyboard.down("Alt")
        page.mouse.move(header_box["x"] + header_box["width"] / 2, header_box["y"] + 12)
        page.mouse.down()
        page.mouse.move(header_box["x"] + header_box["width"] / 2 + 28, header_box["y"] + 30, steps=5)
        page.mouse.up()
        page.keyboard.up("Alt")
        alt_move_after = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        record(
            "alt_drag_moves_group_frame_without_members",
            alt_move_after["group"] != alt_move_before["group"]
            and alt_move_after["node"] == alt_move_before["node"],
            {"before": alt_move_before, "after": alt_move_after},
        )

        overlap_group_id = page.evaluate(
            """({ groupId, nodeId }) => {
                const editor = window.__processMapFlow.editor;
                const runtime = window.InspectorProProcessMap;
                const outer = editor.processMap.canvasGroups.find(item => item.groupId === groupId);
                editor.addCanvasGroup();
                const inner = editor.processMap.canvasGroups.at(-1);
                let next = runtime.resizeGroup(editor.processMap, inner.groupId, {
                    position: { x: outer.position.x + 90, y: outer.position.y + 70 },
                    size: { width: 420, height: 250 },
                });
                next = runtime.moveNode(next, nodeId, {
                    x: outer.position.x - 500,
                    y: outer.position.y + 25,
                });
                editor.commitMutation(next);
                return inner.groupId;
            }""",
            {"groupId": group_id, "nodeId": process_step_id},
        )
        page.evaluate("window.__processMapFlow.editor.fit()")
        page.wait_for_timeout(150)
        overlap_frame = page.locator(f".pm-group-frame[data-group-id='{overlap_group_id}']")
        overlap_box = overlap_frame.bounding_box()
        step_card = page.locator(f".pm-node[data-node-id='{process_step_id}'] .pm-node-card")
        step_box = step_card.bounding_box()
        assert overlap_box is not None and step_box is not None
        overlap_target = page.evaluate(
            """groupId => {
                const frame = document.querySelector(`.pm-group-frame[data-group-id="${groupId}"]`);
                const rect = frame.getBoundingClientRect();
                const fractions = [0.2, 0.5, 0.8];
                for (const y of fractions) {
                    for (const x of fractions) {
                        const point = { left: rect.left + rect.width * x, top: rect.top + rect.height * y };
                        const hit = document.elementFromPoint(point.left, point.top);
                        if (!hit || !hit.closest('.pm-node, .pm-junction')) {
                            return { x: point.left, y: point.top };
                        }
                    }
                }
                return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
            }""",
            overlap_group_id,
        )
        join_facts = page.evaluate(
            """({ nodeId, outerId, innerId, start, target }) => {
                const editor = window.__processMapFlow.editor;
                const runtime = window.InspectorProProcessMap;
                const groups = editor.processMap.canvasGroups;
                const targetWorld = editor.clientToWorld(target.x, target.y);
                const startHit = document.elementFromPoint(start.x, start.y);
                return {
                    startNodeId: startHit && startHit.closest('.pm-node')
                        ? startHit.closest('.pm-node').dataset.nodeId
                        : null,
                    outerContains: runtime.groupContainsPoint(
                        groups.find(item => item.groupId === outerId), targetWorld
                    ),
                    innerContains: runtime.groupContainsPoint(
                        groups.find(item => item.groupId === innerId), targetWorld
                    ),
                };
            }""",
            {
                "nodeId": process_step_id,
                "outerId": group_id,
                "innerId": overlap_group_id,
                "start": {
                    "x": step_box["x"] + step_box["width"] / 2,
                    "y": step_box["y"] + step_box["height"] / 2,
                },
                "target": overlap_target,
            },
        )
        page.mouse.move(step_box["x"] + step_box["width"] / 2, step_box["y"] + step_box["height"] / 2)
        page.mouse.down()
        join_action = page.evaluate(
            """() => {
                const action = window.__processMapFlow.editor.interaction;
                return action && {
                    mode: action.mode,
                    nodeId: action.nodeId,
                };
            }"""
        )
        page.mouse.move(
            step_box["x"] + step_box["width"] / 2 + 12,
            step_box["y"] + step_box["height"] / 2 + 8,
            steps=2,
        )
        page.mouse.move(overlap_target["x"], overlap_target["y"], steps=8)
        page.mouse.up()
        overlap_membership = page.evaluate(
            """({ outerId, innerId, nodeId }) => {
                const groups = window.__processMapFlow.editor.processMap.canvasGroups;
                const outer = groups.find(item => item.groupId === outerId);
                const inner = groups.find(item => item.groupId === innerId);
                return {
                    outer: outer.memberNodeIds.includes(nodeId),
                    inner: inner.memberNodeIds.includes(nodeId),
                    nodeAfter: structuredClone(
                        window.__processMapFlow.editor.processMap.canvasNodes
                            .find(item => item.nodeId === nodeId).position
                    ),
                };
            }""",
            {"outerId": group_id, "innerId": overlap_group_id, "nodeId": process_step_id},
        )
        record(
            "pointer_up_in_overlap_joins_only_smallest_group",
            join_facts["startNodeId"] == process_step_id
            and join_facts["outerContains"] is True
            and join_facts["innerContains"] is True
            and join_action == {"mode": "node", "nodeId": process_step_id}
            and overlap_membership["outer"] is False
            and overlap_membership["inner"] is True,
            {"membership": overlap_membership, "facts": join_facts, "action": join_action},
        )

        outside_point = page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                const runtime = window.InspectorProProcessMap;
                const rect = editor.viewport.getBoundingClientRect();
                const candidates = [
                    { x: rect.left + 70, y: rect.top + 70 },
                    { x: rect.right - 70, y: rect.top + 70 },
                    { x: rect.left + 70, y: rect.bottom - 70 },
                    { x: rect.right - 70, y: rect.bottom - 70 },
                ];
                return candidates.find(point => {
                    const world = editor.clientToWorld(point.x, point.y);
                    const hit = document.elementFromPoint(point.x, point.y);
                    return !editor.processMap.canvasGroups.some(group => runtime.groupContainsPoint(group, world))
                        && (!hit || !hit.closest('.pm-node, .pm-junction'));
                });
            }"""
        )
        assert outside_point is not None
        step_box = page.locator(f".pm-node[data-node-id='{process_step_id}'] .pm-node-card").bounding_box()
        assert step_box is not None
        page.mouse.move(step_box["x"] + step_box["width"] / 2, step_box["y"] + step_box["height"] / 2)
        page.mouse.down()
        leave_action = page.evaluate(
            """() => {
                const action = window.__processMapFlow.editor.interaction;
                return action && { mode: action.mode, nodeId: action.nodeId };
            }"""
        )
        page.mouse.move(
            step_box["x"] + step_box["width"] / 2 + 12,
            step_box["y"] + step_box["height"] / 2 + 8,
            steps=2,
        )
        page.mouse.move(outside_point["x"], outside_point["y"], steps=8)
        page.mouse.up()
        record(
            "pointer_up_outside_groups_removes_membership",
            leave_action == {"mode": "node", "nodeId": process_step_id}
            and page.evaluate(
                """nodeId => !window.__processMapFlow.editor.processMap.canvasGroups
                    .some(group => group.memberNodeIds.includes(nodeId))""",
                process_step_id,
            ),
        )
        page.evaluate(
            """groupId => {
                const editor = window.__processMapFlow.editor;
                editor.commitMutation(window.InspectorProProcessMap.deleteGroup(editor.processMap, groupId));
                editor.selectGroup(null);
            }""",
            overlap_group_id,
        )

        theme_group_styles = {}
        for theme in ("light", "dark"):
            page.evaluate("theme => document.documentElement.setAttribute('data-theme', theme)", theme)
            theme_group_styles[theme] = page.locator(
                f".pm-group-frame[data-group-id='{group_id}']"
            ).evaluate(
                "el => ({ background: getComputedStyle(el).backgroundColor, border: getComputedStyle(el).borderColor })"
            )
        record(
            "group_palette_is_visible_in_light_and_dark_themes",
            all(
                style["background"] not in ("rgba(0, 0, 0, 0)", "transparent")
                and style["border"] not in ("rgba(0, 0, 0, 0)", "transparent")
                for style in theme_group_styles.values()
            ),
            theme_group_styles,
        )

        page.evaluate("groupId => window.__processMapFlow.editor.selectGroup(groupId)", group_id)
        page.locator(".pm-group-toolbar [data-group-command='delete']").click()
        record(
            "deleting_group_keeps_member_cards_and_undo_restores_frame",
            page.locator(f".pm-node[data-node-id='{first_id}']").count() == 1
            and page.locator(f".pm-group-frame[data-group-id='{group_id}']").count() == 0,
        )
        page.evaluate("window.__processMapFlow.editor.undo()")
        page.wait_for_selector(f".pm-group-frame[data-group-id='{group_id}']")

        page.screenshot(
            path=str(OUT_DIR / "process_flow_wire_references_dark.png"),
            full_page=False,
        )
        page.get_by_role("button", name="Save process map").click()
        page.wait_for_function("window.__processMapFlow.editor.dirty === false")
        record(
            "save_persists_only_placed_nodes_and_canvas_edges",
            store["putCount"] == 1
            and len(store["map"]["canvasNodes"]) == 6
            and len(store["map"]["canvasEdges"]) == 5
            and len([node for node in store["map"]["canvasNodes"] if node.get("nodeKind") == "junction"]) == 1
            and len([node for node in store["map"]["canvasNodes"] if node.get("portOrientation") == "vertical"]) == 1
            and len([node for node in store["map"]["canvasNodes"] if node.get("portOrder") == "output_first"]) == 1
            and any(
                node.get("nodeId") == first_id
                and node.get("labelOverride") == "Primary seat shell"
                and node.get("note") == "Verify the seating surface before the inspection step."
                and len(node.get("referenceIds", [])) == 1
                for node in store["map"]["canvasNodes"]
            )
            and len(store["map"].get("referenceCatalog", [])) == 2
            and store["map"].get("layoutVersion") == 2
            and len(store["map"].get("canvasGroups", [])) == 1
            and store["map"]["canvasGroups"][0].get("label") == "Final inspection cell"
            and first_id in store["map"]["canvasGroups"][0].get("memberNodeIds", [])
            and len([
                edge for edge in store["map"]["canvasEdges"]
                if edge.get("logicalConnectionId") == trunk_edge_id
                and len(edge.get("referenceIds", [])) == 1
            ]) == 2
            and "occurrences" not in store["map"],
        )

        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", first_id)
        page.wait_for_selector(".pm-card-toolbar")
        page.evaluate(
            "() => window.__processMapFlow.editor.applyNodeNote('Temporary conflicting edit')"
        )
        page.wait_for_function("window.__processMapFlow.editor.dirty === true")
        store["conflictNext"] = True
        page.get_by_role("button", name="Save process map").click()
        page.wait_for_function("window.__processMapFlow.editor.conflict === true")
        record(
            "revision_conflict_closes_and_locks_context_toolbar",
            page.locator(".ip-floating-surface").count() == 0
            and "newer saved revision" in page.locator(".pm-editor-status").inner_text().lower(),
        )
        page.get_by_role("button", name="Reload the latest saved process map").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.conflict === false"
            " && window.__processMapFlow.editor.dirty === false"
        )
        record(
            "conflict_reload_restores_saved_state_without_toolbar_residue",
            page.locator(".ip-floating-surface").count() == 0
            and page.evaluate(
                "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
                ".find(node => node.nodeId === nodeId).note === "
                "'Verify the seating surface before the inspection step.'",
                first_id,
            ),
        )

        page.reload(wait_until="networkidle", timeout=60_000)
        _open_process_flow(page)
        record(
            "saved_placements_and_connections_survive_reload",
            page.locator(".pm-node").count() == 5
            and page.locator(".pm-junction").count() == 1
            and page.evaluate("window.__processMapFlow.editor.processMap.canvasEdges.length") == 5
            and page.locator(".pm-node-ports-vertical").count() == 1
            and page.locator(".pm-node-port-order-output_first").count() == 1
            and page.locator(f".pm-group-frame[data-group-id='{group_id}']").count() == 1
            and page.locator(f".pm-node[data-node-id='{first_id}'] .pm-node-note-indicator").count() == 1
            and page.locator(
                f".pm-node[data-node-id='{first_id}'] .pm-reference-badge-machine"
            ).count() == 1
            and page.locator(".pm-edge-context-label").filter(
                has_text="Inspection release | Std 1"
            ).count() == 1
            and "Primary seat shell" in page.locator(
                f".pm-node[data-node-id='{first_id}'] .pm-node-card"
            ).inner_text(),
        )

        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", first_id)
        page.wait_for_selector(".pm-card-toolbar")
        page.evaluate(
            "window.__pmToolbarManagers = [window.__processMapFlow.editor.cardToolbarManager]"
        )
        churn_ok = True
        for _index in range(3):
            page.locator(".tab[data-tab='drawing']").click()
            page.wait_for_selector(".tab.active[data-tab='drawing']")
            page.wait_for_timeout(80)
            churn_ok = churn_ok and page.locator(".ip-floating-surface").count() == 0
            churn_ok = churn_ok and page.evaluate(
                "window.__pmToolbarManagers.every(manager => !manager.isOpen())"
            )

            page.locator(".tab[data-tab='training']").click()
            page.wait_for_selector(".tab.active[data-tab='training']")
            _ensure_process_flow_editor(page)
            page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", first_id)
            page.wait_for_selector(".pm-card-toolbar")
            page.evaluate(
                "window.__pmToolbarManagers.push(window.__processMapFlow.editor.cardToolbarManager)"
            )
            churn_ok = churn_ok and page.locator(".ip-floating-surface").count() == 1
            churn_ok = churn_ok and page.evaluate(
                "window.__pmToolbarManagers.slice(0, -1).every(manager => !manager.isOpen())"
                " && window.__pmToolbarManagers.at(-1).isOpen()"
            )
        record(
            "rapid_tab_remount_churn_leaves_only_current_surface_active",
            churn_ok,
        )

        page.locator(".tab[data-tab='drawing']").click()
        page.wait_for_selector(".tab.active[data-tab='drawing']")
        page.wait_for_timeout(80)
        record(
            "tab_change_destroys_toolbar_without_dom_or_manager_residue",
            page.locator(".ip-floating-surface").count() == 0
            and page.evaluate(
                "window.__pmToolbarManagers.every(manager => !manager.isOpen())"
            ),
        )

        page.locator(".tab[data-tab='training']").click()
        page.wait_for_selector(".tab.active[data-tab='training']")
        _ensure_process_flow_editor(page)
        page.screenshot(path=str(OUT_DIR / "process_flow_source_tree_authored.png"), full_page=False)
        context.close()

        record("no_browser_page_errors", not report["page_errors"], report["page_errors"])
        browser.close()

    output_path = OUT_DIR / "process_flow_editor_smoke.json"
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = [name for name, value in report["checks"].items() if not value["ok"]]
    print(f"Wrote {output_path}")
    if failed:
        print("Failed checks: " + ", ".join(failed), file=sys.stderr)
        return 1
    print(f"Process-flow smoke: {len(report['checks'])}/{len(report['checks'])} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
