"""Live Playwright smoke for the read-only Training process-flow canvas."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "runtime_logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
APP_URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8023/")


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
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        page.click(".tab[data-tab='training']")
        page.wait_for_function(
            "window.__processMapFlow && window.__processMapFlow.available === true",
            timeout=30_000,
        )

        expected = page.evaluate(
            """async () => {
                const response = await fetch('/api/training/process-map/racing-bike');
                const payload = await response.json();
                const nodes = payload.map.nodes || [];
                return {
                    defaultCount: nodes.filter(node => node.level === 1 || node.level === 2).length,
                    focus: nodes.find(node => node.level === 2
                        && nodes.some(child => child.parentNodeId === node.nodeId)),
                    childCounts: Object.fromEntries(nodes.map(node => [
                        node.nodeId,
                        nodes.filter(child => child.parentNodeId === node.nodeId).length
                    ])),
                };
            }"""
        )
        flow_button = page.locator("[data-training-open-process-flow='true']")
        record("flow_button_available_when_api_enabled", flow_button.count() == 1)
        flow_button.click()
        page.wait_for_selector("[data-process-flow-editor='true']", timeout=15_000)

        nodes = page.locator(".pm-node")
        record(
            "default_scope_renders_levels_one_and_two",
            nodes.count() == expected["defaultCount"],
            {"expected": expected["defaultCount"], "actual": nodes.count()},
        )
        record(
            "rich_training_cards_are_reused",
            page.locator(".pm-node-card.train-diagram-card").count() == nodes.count(),
        )
        record(
            "every_node_has_type_badge_and_two_ports",
            page.locator(".pm-node-type").count() == nodes.count()
            and page.locator(".pm-port").count() == nodes.count() * 2,
        )

        page.evaluate("window.setInspectorProTheme && window.setInspectorProTheme('light')")
        page.wait_for_timeout(200)
        light_computed = page.evaluate(
            """() => ({
                viewport: getComputedStyle(document.querySelector('.pm-viewport')).backgroundColor,
                card: getComputedStyle(document.querySelector('.pm-node-card')).backgroundColor,
                text: getComputedStyle(document.querySelector('.pm-node-card')).color,
            })"""
        )
        page.screenshot(path=str(OUT_DIR / "process_flow_editor_light.png"), full_page=False)
        page.evaluate("window.setInspectorProTheme && window.setInspectorProTheme('dark')")
        page.wait_for_timeout(200)
        page.screenshot(path=str(OUT_DIR / "process_flow_editor_dark.png"), full_page=False)
        computed = page.evaluate(
            """() => {
                const viewport = document.querySelector('.pm-viewport');
                const card = document.querySelector('.pm-node-card');
                return {
                    viewport: getComputedStyle(viewport).backgroundColor,
                    card: getComputedStyle(card).backgroundColor,
                    text: getComputedStyle(card).color,
                };
            }"""
        )
        record(
            "light_and_dark_themes_have_distinct_readable_surface_tokens",
            len({computed["viewport"], computed["card"], computed["text"]}) == 3
            and len({light_computed["viewport"], light_computed["card"], light_computed["text"]}) == 3
            and light_computed["viewport"] != computed["viewport"],
            {"light": light_computed, "dark": computed},
        )

        before_pan = page.evaluate("({ ...window.__processMapFlow.editor.transform })")
        viewport = page.locator(".pm-viewport")
        box = viewport.bounding_box()
        assert box is not None
        page.mouse.move(box["x"] + 24, box["y"] + box["height"] - 24)
        page.mouse.down()
        page.mouse.move(box["x"] + 104, box["y"] + box["height"] - 74, steps=5)
        page.mouse.up()
        after_pan = page.evaluate("({ ...window.__processMapFlow.editor.transform })")
        record(
            "empty_space_drag_pans_canvas",
            abs(after_pan["x"] - before_pan["x"]) > 20
            and abs(after_pan["y"] - before_pan["y"]) > 20,
            {"before": before_pan, "after": after_pan},
        )

        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        before_zoom = page.evaluate("window.__processMapFlow.editor.transform.scale")
        page.mouse.wheel(0, -500)
        page.wait_for_timeout(100)
        after_zoom = page.evaluate("window.__processMapFlow.editor.transform.scale")
        record("wheel_zooms_toward_cursor", after_zoom > before_zoom)
        page.get_by_role("button", name="Fit flow to viewport").click()
        fitted = page.evaluate("window.__processMapFlow.editor.transform.scale")
        record("fit_control_restores_bounded_scale", 0.28 <= fitted <= 1.15, fitted)

        focus = expected.get("focus")
        if focus:
            page.locator(f".pm-node[data-node-id='{focus['nodeId']}']").dblclick()
            page.wait_for_function(
                "nodeId => window.__processMapFlow.editor.focusNodeId === nodeId",
                arg=focus["nodeId"],
                timeout=10_000,
            )
            focused_count = page.locator(".pm-node").count()
            record(
                "subassembly_focus_shows_direct_children",
                focused_count == expected["childCounts"][focus["nodeId"]],
                {"node": focus["nodeId"], "actual": focused_count},
            )
            page.get_by_role("button", name="Back one process scope").click()
            record(
                "focus_back_navigation_is_available",
                page.locator(".pm-node").count() > 0,
            )

        page.click(".tab[data-tab='drawing']")
        page.click(".tab[data-tab='training']")
        page.wait_for_selector("[data-process-flow-editor='true']", timeout=15_000)
        record(
            "flow_view_survives_training_tab_round_trip",
            page.evaluate("window.__processMapFlow.editor !== null"),
        )

        page.get_by_role("button", name="Return to product structure").click()
        page.wait_for_selector("[data-training-product-structure-diagram='racing-bike']")
        record(
            "structure_view_remains_available",
            page.locator("[data-process-flow-editor='true']").count() == 0,
        )

        fallback_context = browser.new_context(viewport={"width": 1400, "height": 900})
        fallback_page = fallback_context.new_page()
        fallback_page.route(
            "**/api/training/process-map/racing-bike",
            lambda route: route.fulfill(
                status=404,
                content_type="application/json",
                body='{"detail":"disabled"}',
            ),
        )
        fallback_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        fallback_page.click(".tab[data-tab='training']")
        fallback_page.wait_for_selector("[data-training-product-structure-diagram='racing-bike']")
        record(
            "flag_off_falls_back_to_unchanged_structure_board",
            fallback_page.locator("[data-training-open-process-flow='true']").count() == 0
            and fallback_page.locator("[data-process-flow-editor='true']").count() == 0,
        )
        fallback_context.close()

        record("no_browser_page_errors", not report["page_errors"], report["page_errors"])
        browser.close()

    report_path = OUT_DIR / "process_flow_editor_smoke.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = [name for name, result in report["checks"].items() if not result["ok"]]
    print(f"Artifact: {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
