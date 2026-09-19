"""Browser proof for InspectorPro structured chat content and feedback."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "runtime_logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
APP_URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8114/")


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report: dict[str, object] = {
        "url": APP_URL,
        "checks": {},
        "pageErrors": [],
        "consoleErrors": [],
        "feedbackRequests": [],
    }

    def record(name: str, ok: bool, detail=None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.on("pageerror", lambda error: report["pageErrors"].append(str(error)))
        page.on(
            "console",
            lambda message: report["consoleErrors"].append(message.text)
            if message.type == "error" else None,
        )
        page.on(
            "request",
            lambda request: report["feedbackRequests"].append(
                json.loads(request.post_data or "{}")
            ) if request.method == "POST"
            and request.url.endswith("/api/agent/chat/feedback") else None,
        )

        page.goto(APP_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_function(
            "window.__agentChatStreamV1 && window.InspectorProChatRichContent",
            timeout=30_000,
        )
        page.evaluate("window._selectAgent && window._selectAgent('deviation-analyst')")
        page.evaluate(
            """() => {
                const panel = document.getElementById('agentPanel');
                if (panel && !panel.classList.contains('open') && window._toggleAgentPanel) {
                    window._toggleAgentPanel();
                }
                window.__chatActionSmoke = null;
                document.addEventListener('inspectorpro:chat-action', event => {
                    window.__chatActionSmoke = event.detail;
                }, { once: true });
            }"""
        )
        page.wait_for_selector("#agentMessages", state="visible", timeout=15_000)

        working_available = page.evaluate(
            "typeof window.__agentChatStreamV1.createWorkingState === 'function'"
        )
        record("working_state_runtime_available", working_available)
        if working_available:
            page.evaluate(
                "window.__richContentWorkingSmoke = "
                "window.__agentChatStreamV1.createWorkingState("
                "'deviation-analyst', 'searching')"
            )
            working = page.locator("#agentMessages .agent-working-row").last
            working.wait_for(state="visible", timeout=5_000)
            animation_names = working.evaluate(
                """node => ({
                    halo: getComputedStyle(
                        node.querySelector('.agent-working-compass-shell'), '::before'
                    ).animationName,
                    haloDuration: getComputedStyle(
                        node.querySelector('.agent-working-compass-shell'), '::before'
                    ).animationDuration,
                    haloShadow: getComputedStyle(
                        node.querySelector('.agent-working-compass-shell'), '::before'
                    ).boxShadow,
                    logo: getComputedStyle(
                        node.querySelector('.agent-working-compass')
                    ).animationName,
                    logoDuration: getComputedStyle(
                        node.querySelector('.agent-working-compass')
                    ).animationDuration,
                    operation: node.querySelector('.agent-working-operation').textContent,
                })"""
            )
            record(
                "thinking_logo_uses_restrained_halo_and_rotation",
                animation_names.get("halo") == "agentWorkingHalo"
                and animation_names.get("haloDuration") == "1.8s"
                and "0, 145, 255" in animation_names.get("haloShadow", "")
                and animation_names.get("logo") == "agentWorkingCompassRotate"
                and animation_names.get("logoDuration") == "3.5s"
                and animation_names.get("operation") == "Searching sources",
                animation_names,
            )
            page.screenshot(path=str(OUT_DIR / "chat_rich_content_thinking.png"))
            stopped = page.evaluate(
                """() => {
                    const node = document.querySelector('#agentMessages .agent-working-row:last-child');
                    window.__richContentWorkingSmoke.beginStreaming();
                    return {
                        stopped: node.classList.contains('is-stopped'),
                        halo: getComputedStyle(
                            node.querySelector('.agent-working-compass-shell'), '::before'
                        ).animationName,
                        logo: getComputedStyle(
                            node.querySelector('.agent-working-compass')
                        ).animationName,
                    };
                }"""
            )
            record(
                "thinking_animation_stops_before_streaming_content",
                stopped.get("stopped")
                and stopped.get("halo") == "none"
                and stopped.get("logo") == "none",
                stopped,
            )
            page.wait_for_function(
                "document.querySelectorAll('.agent-working-row').length === 0",
                timeout=5_000,
            )

        page.evaluate(
            """() => {
                const markdown = [
                    '### Machining cell review',
                    '',
                    'The proposed row maintains **operator clearance** and preserves the main material route.',
                    '',
                    '| Check | Result | Evidence |',
                    '| --- | --- | --- |',
                    '| Operator clearance | 1.2 m | Facility validator |',
                    '| Aisle overlap | None | Layout geometry |',
                    '',
                    '`CNC-04` remains the highest-area machine in the selected cell.',
                    '',
                    '<script>window.__unsafeChatExecuted = true</script>'
                ].join('\\n');
                const stream = window.__agentChatStreamV1.createMessage('deviation-analyst', {
                    source: 'rich_content_smoke',
                    showStatus: false,
                });
                stream.commit(markdown, {
                    contentBlocks: [
                        {
                            type: 'sources',
                            title: 'Engineering sources',
                            sources: [
                                {
                                    id: 'source_skf_6205',
                                    title: '6205-2RS1 deep groove ball bearing',
                                    url: 'https://www.skf.com/',
                                    publisher: 'SKF',
                                    sourceType: 'manufacturer',
                                    partNumber: '6205-2RS1',
                                    description: 'Manufacturer product reference used for dimensional evidence.',
                                    specifications: { Bore: '25 mm', 'Outside diameter': '52 mm' },
                                    links: [{ label: 'View product', url: 'https://www.skf.com/', kind: 'product' }],
                                },
                                {
                                    id: 'source_mcmaster',
                                    title: 'Industrial machine guarding reference',
                                    url: 'https://www.mcmaster.com/',
                                    publisher: 'McMaster-Carr',
                                    sourceType: 'supplier',
                                    availability: 'Catalog reference',
                                },
                            ],
                        },
                        {
                            type: 'facts',
                            title: 'Evidence',
                            facts: [
                                { label: 'Bore diameter', value: '25', unit: 'mm', sourceId: 'source_skf_6205', provenance: 'source' },
                                { label: 'Minimum clearance', value: '1.2', unit: 'm', provenance: 'derived' },
                                { label: 'Layout interpretation', value: 'Acceptable with review', provenance: 'agent' },
                            ],
                        },
                        {
                            type: 'visualization',
                            spec: {
                                type: 'bar',
                                title: 'Department physical equipment footprint coverage',
                                subtitle: 'Net floor-contact area in m^2',
                                unit: 'm^2',
                                data: [
                                    { machine: 'Machining Hall', area: 6.417, entityId: 'zone_machining' },
                                    { machine: 'Receiving + Raw Material', area: 5.235, entityId: 'zone_receiving' },
                                    { machine: 'Inspection + Packing + Finished goods', area: 2.79, entityId: 'zone_inspection' },
                                    { machine: 'Assembly + Kitting', area: 1.766, entityId: 'zone_assembly' },
                                    { machine: 'Automation + Robot cells', area: 1.337, entityId: 'zone_automation' },
                                    { machine: 'Material handling + Maintenance', area: 1.149, entityId: 'zone_maintenance' },
                                ],
                                encoding: { x: 'machine', y: 'area', entityId: 'entityId' },
                            },
                        },
                        {
                            type: 'entity_reference',
                            entity: {
                                id: 'asset_cnc_04',
                                entityType: 'facility_asset',
                                label: 'CNC-04',
                                subtitle: 'Horizontal machining center | Machining Hall',
                            },
                            actions: [
                                { actionId: 'locate_in_plan', label: 'Locate in Plan', entityId: 'asset_cnc_04', entityType: 'facility_asset' },
                                { actionId: 'show_in_3d', label: 'Show in 3D', entityId: 'asset_cnc_04', entityType: 'facility_asset' },
                            ],
                        },
                    ],
                    meta: {
                        feedbackEligible: true,
                        conversationId: 'conversation-smoke',
                        agentSessionId: 'session-smoke',
                        clientTurnId: 'client-turn-smoke',
                        turnId: 'turn-smoke-rich-content',
                        runId: 'run-smoke-rich-content',
                        responseId: 'response-smoke-rich-content',
                        serverMessageId: 'message-smoke-rich-content',
                        agentType: 'deviation-analyst',
                        model: 'deterministic-smoke',
                        promptVersion: 'chat-rich-content-v1',
                        contextManifestId: 'manifest-smoke',
                        memoryEnvelopeSha256: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                        toolIds: ['facility.layout.validate'],
                        workspaceMode: 'facility_layout',
                    },
                });
                window.__richContentSmokeMessage = stream.message;
            }"""
        )

        answer = page.locator("#agentMessages .agent-msg-row.assistant").last
        answer.wait_for(state="visible", timeout=10_000)
        record("markdown_table_rendered", answer.locator("table").count() == 1)
        record("markdown_code_rendered", answer.locator("code").count() == 1)
        record(
            "model_html_is_escaped",
            not page.evaluate("Boolean(window.__unsafeChatExecuted)")
            and answer.locator("script").count() == 0
            and "<script>" in answer.inner_text(),
        )
        record("source_cards_rendered", answer.locator(".agent-source-card").count() == 2)
        record("fact_provenance_rendered", answer.locator(".agent-fact-row").count() == 3)
        record("validated_chart_rendered", answer.locator(".agent-chart-svg").count() == 1)
        chart = answer.locator(".agent-chart-svg").first
        chart_labels = chart.locator(".agent-chart-label")
        label_boxes = chart_labels.evaluate_all(
            """nodes => nodes.map(node => ({
                label: node.getAttribute('aria-label'),
                lines: node.querySelectorAll('tspan').length,
                box: node.getBoundingClientRect().toJSON(),
            }))"""
        )
        record(
            "engineering_exponents_are_typeset",
            "m\u00b2" in answer.inner_text() and "m^2" not in answer.inner_text(),
            answer.inner_text(),
        )
        record(
            "long_bar_labels_wrap_without_overlap",
            len(label_boxes) == 6
            and all(1 <= item["lines"] <= 3 for item in label_boxes)
            and all(
                label_boxes[index]["box"]["right"]
                <= label_boxes[index + 1]["box"]["left"] + 0.5
                for index in range(len(label_boxes) - 1)
            ),
            label_boxes,
        )
        record("entity_actions_rendered", answer.locator(".agent-rich-action").count() == 2)
        record("feedback_controls_rendered", answer.locator(".agent-feedback-button").count() == 2)

        answer.locator('[data-chat-action="show_in_3d"]').click()
        action_detail = page.evaluate("window.__chatActionSmoke")
        record(
            "allowlisted_action_dispatches_structured_intent",
            action_detail == {
                "actionId": "show_in_3d",
                "label": "Show in 3D",
                "entityId": "asset_cnc_04",
                "entityType": "facility_asset",
            },
            action_detail,
        )

        page.evaluate("window.setInspectorProTheme('dark')")
        dark_background = answer.locator(".agent-source-card").first.evaluate(
            "node => getComputedStyle(node).backgroundImage + getComputedStyle(node).backgroundColor"
        )
        answer.screenshot(path=str(OUT_DIR / "chat_rich_content_dark.png"))
        page.screenshot(path=str(OUT_DIR / "chat_rich_content_app_dark.png"))

        answer.get_by_label("Unhelpful answer").click()
        answer.locator(".agent-feedback-status").wait_for(state="visible")
        page.wait_for_function(
            "document.querySelectorAll('.agent-feedback-status').length > 0 && "
            "Array.from(document.querySelectorAll('.agent-feedback-status')).some(n => n.textContent === 'Saved')",
            timeout=10_000,
        )
        answer.get_by_role("button", name="Invalid clearance").click()
        answer.locator(".agent-feedback-correction").fill(
            "The plan should preserve 1.5 m clearance at CNC-04."
        )
        answer.get_by_role("button", name="Save feedback").click()
        page.wait_for_function(
            "Array.from(document.querySelectorAll('.agent-feedback-status')).some(n => n.textContent === 'Saved')",
            timeout=10_000,
        )
        feedback_requests = report["feedbackRequests"]
        final_feedback = feedback_requests[-1] if feedback_requests else {}
        record("feedback_endpoint_received_updates", len(feedback_requests) >= 2, len(feedback_requests))
        record(
            "feedback_is_linked_to_exact_run",
            final_feedback.get("turnId") == "turn-smoke-rich-content"
            and final_feedback.get("runId") == "run-smoke-rich-content"
            and final_feedback.get("reasons") == ["invalid_clearance"]
            and final_feedback.get("trace", {}).get("sourceIds")
            == ["source_skf_6205", "source_mcmaster"],
            final_feedback,
        )

        page.evaluate("window.setInspectorProTheme('light')")
        light_background = answer.locator(".agent-source-card").first.evaluate(
            "node => getComputedStyle(node).backgroundImage + getComputedStyle(node).backgroundColor"
        )
        record("rich_blocks_follow_application_theme", dark_background != light_background, {
            "dark": dark_background,
            "light": light_background,
        })
        answer.screenshot(path=str(OUT_DIR / "chat_rich_content_light.png"))
        page.screenshot(path=str(OUT_DIR / "chat_rich_content_app_light.png"))

        record("no_page_errors", not report["pageErrors"], report["pageErrors"])
        relevant_console_errors = [
            value for value in report["consoleErrors"]
            if "favicon.ico" not in value and "ERR_CONNECTION" not in value
        ]
        record("no_relevant_console_errors", not relevant_console_errors, relevant_console_errors)
        browser.close()

    output = OUT_DIR / "chat_rich_content_smoke.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = [
        name for name, item in report["checks"].items()
        if not item["ok"]
    ]
    print(f"{len(report['checks']) - len(failed)}/{len(report['checks'])} checks passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
