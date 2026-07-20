"""Live Playwright smoke for provisional provider-token chat streaming."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "runtime_logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
APP_URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8022/")
THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
THREE_CACHE = OUT_DIR / "three.r128.min.js"


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report = {
        "url": APP_URL,
        "checks": {},
        "partial_samples": [],
        "presentation_samples": [],
    }

    def record(name: str, ok: bool, detail=None):
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}")

    three_js = None
    try:
        if THREE_CACHE.exists() and THREE_CACHE.stat().st_size > 100_000:
            three_js = THREE_CACHE.read_text(encoding="utf-8")
        else:
            with urllib.request.urlopen(THREE_URL, timeout=15) as response:
                three_js = response.read().decode("utf-8")
            THREE_CACHE.write_text(three_js, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke:warn] Three.js route unavailable: {exc}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1500, "height": 950})
        page = context.new_page()
        report["console"] = []
        report["page_errors"] = []
        page.on("console", lambda message: report["console"].append(
            {"type": message.type, "text": message.text}
        ))
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        if three_js:
            page.route(
                THREE_URL,
                lambda route: route.fulfill(
                    status=200, content_type="application/javascript", body=three_js
                ),
            )
        stream_requests = []
        page.on(
            "request",
            lambda request: stream_requests.append(request.url)
            if request.method == "POST" and request.url.endswith("/api/agent/chat/v2/stream")
            else None,
        )
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_function("window.__agentChatStreamV1 && window._handleAgentSend", timeout=30_000)
        page.evaluate("window._selectAgent && window._selectAgent('inspector')")
        page.evaluate(
            "() => { const panel = window._agentPanel;"
            " if (panel && !panel.classList.contains('open') && window._toggleAgentPanel)"
            " window._toggleAgentPanel(); }"
        )
        page.wait_for_selector("#agentInput", state="visible", timeout=15_000)

        # Exercise the visual queue with a deterministic local append. This
        # isolates presentation pacing from provider chunk sizes and confirms
        # Markdown is deferred until the authoritative terminal commit.
        display_text = "The visual queue reveals this response progressively without rendering raw transport chunks. " * 4
        page.evaluate(
            """text => {
                const stream = window.__agentChatStreamV1.createMessage('inspector', {
                    source: 'presentation_smoke', status: 'Generating'
                });
                window.__chatStreamPresentationSmoke = stream;
                stream.appendText(text);
            }""",
            display_text,
        )
        deadline = time.time() + 4
        last_length = -1
        while time.time() < deadline:
            pending_text = page.locator(".agent-stream-pending .agent-msg").last.inner_text()
            if len(pending_text) != last_length:
                report["presentation_samples"].append(len(pending_text))
                last_length = len(pending_text)
            if len(pending_text) >= len(display_text):
                break
            page.wait_for_timeout(35)
        page.evaluate(
            "() => window.__chatStreamPresentationSmoke.commit('**Final rendered Markdown**')"
        )
        page.wait_for_function(
            "document.querySelectorAll('.agent-stream-pending').length === 0",
            timeout=10_000,
        )
        presentation_deltas = [
            current - previous
            for previous, current in zip(
                report["presentation_samples"], report["presentation_samples"][1:]
            )
        ]
        final_presentation = page.locator("#agentMessages .agent-msg-row.assistant").last
        record(
            "visual_queue_drains_in_small_progressive_steps",
            len(report["presentation_samples"]) >= 5
            and report["presentation_samples"][-1] == len(display_text)
            and max(presentation_deltas or [0]) <= 48,
            report["presentation_samples"],
        )
        record(
            "markdown_is_applied_at_terminal_commit",
            final_presentation.locator("strong").inner_text() == "Final rendered Markdown",
        )
        page.evaluate("() => window.__chatStreamPresentationSmoke.discard()")

        assistants_before_request = page.locator("#agentMessages .agent-msg-row.assistant").count()
        page.fill("#agentInput", "In two short sentences, explain what a datum is.")
        page.click("#agentSendBtn")
        page.wait_for_selector(".agent-working-row", timeout=15_000)
        working = page.locator(".agent-working-row").last
        record(
            "working_state_shows_compass_without_answer_bubble",
            working.locator(".agent-working-compass").count() == 1
            and page.locator("#agentMessages .agent-msg-row.assistant").count() == assistants_before_request,
            working.inner_text(),
        )
        page.screenshot(path=str(OUT_DIR / "chat_streaming_working_state.png"))
        page.wait_for_selector(".agent-stream-pending", timeout=15_000)
        page.wait_for_function(
            "document.querySelectorAll('.agent-working-row').length === 0",
            timeout=5_000,
        )
        record(
            "working_state_exits_on_first_visible_text",
            page.locator(".agent-stream-pending .agent-msg").last.inner_text().strip() != "",
        )
        deadline = time.time() + 25
        last = None
        while time.time() < deadline:
            text = page.evaluate(
                """() => {
                    const rows = document.querySelectorAll('.agent-stream-pending');
                    return rows.length ? rows[rows.length - 1].innerText : null;
                }"""
            )
            if text is None:
                break
            if text != last:
                report["partial_samples"].append(text)
                last = text
            page.wait_for_timeout(100)
        page.wait_for_function(
            "document.querySelectorAll('.agent-stream-pending').length === 0",
            timeout=30_000,
        )
        assistants = page.locator("#agentMessages .agent-msg-row.assistant")
        final_text = assistants.last.inner_text() if assistants.count() else ""
        report["final_text"] = final_text
        record("v2_endpoint_used", len(stream_requests) == 1, stream_requests)
        record("provisional_text_was_visible", any(len(item) > 20 for item in report["partial_samples"]))
        record("multiple_incremental_states", len(report["partial_samples"]) >= 2, report["partial_samples"])
        record("final_answer_committed", "datum" in final_text.lower(), final_text)
        record("no_machine_directive_visible", not any(
            token in "\n".join(report["partial_samples"]) for token in
            ("<tool_calls", "[UI_ACTIONS", "HIGHLIGHT_PARTS:")
        ))
        page.wait_for_timeout(700)
        storage = page.evaluate("localStorage.getItem('inspectorpro.chat_registry.v1') || ''")
        record("pending_message_not_persisted", '"pending":true' not in storage)

        # A post-start error keeps the already rendered answer text visible
        # and surfaces an error state without committing it to chat history.
        page.evaluate(
            """() => {
                const stream = window.__agentChatStreamV1.createMessage('inspector', {
                    source: 'error_presentation_smoke', showStatus: false
                });
                window.__chatStreamErrorSmoke = stream;
                stream.appendInitialText('Partial answer remains visible.');
                stream.fail('Response interrupted. Retry the request to continue.');
            }"""
        )
        failed_stream = page.locator(".agent-stream-failed").last
        record(
            "stream_error_preserves_partial_text",
            "Partial answer remains visible." in failed_stream.inner_text()
            and "Response interrupted" in failed_stream.inner_text(),
        )
        page.evaluate("() => window.__chatStreamErrorSmoke.discard()")

        # Cancellation during a visible stream preserves the existing product
        # behavior: discard the provisional response and leave no history item.
        before_rows = assistants.count()
        page.fill("#agentInput", "Give a detailed explanation of datum reference frames in ten paragraphs.")
        page.click("#agentSendBtn")
        page.wait_for_selector(".agent-stream-pending", timeout=15_000)
        page.click("#agentSendBtn")
        page.wait_for_function(
            "document.querySelectorAll('.agent-stream-pending').length === 0",
            timeout=15_000,
        )
        after_rows = page.locator("#agentMessages .agent-msg-row.assistant").count()
        record("cancel_discards_partial_message", after_rows == before_rows, {
            "before": before_rows, "after": after_rows,
        })
        record("stop_restores_send_control", page.get_attribute("#agentSendBtn", "aria-label") == "Send message")

        page.screenshot(path=str(OUT_DIR / "chat_streaming_smoke.png"))
        browser.close()

    output = OUT_DIR / "chat_streaming_smoke.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = [name for name, item in report["checks"].items() if not item["ok"]]
    print(f"{len(report['checks']) - len(failed)}/{len(report['checks'])} checks passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
