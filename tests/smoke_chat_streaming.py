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

    report = {"url": APP_URL, "checks": {}, "partial_samples": []}

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

        page.fill("#agentInput", "In two short sentences, explain what a datum is.")
        page.click("#agentSendBtn")
        page.wait_for_selector(".agent-stream-pending", timeout=15_000)
        deadline = time.time() + 25
        last = None
        while time.time() < deadline:
            pending = page.locator(".agent-stream-pending")
            if pending.count() == 0:
                break
            text = pending.last.inner_text()
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

        # Cancellation must discard the partial assistant message and leave no
        # committed half-answer in history.
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
