"""Browser smoke for Scout's provider-token stream using a scripted SSE reply."""

from __future__ import annotations

import json
import os
import sys


APP_URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8021/")


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    events = [
        {"type": "status", "phase": "generating"},
        {"type": "text_delta", "text": "Scout found "},
        {"type": "text_delta", "text": "a compatible spacer."},
        {
            "type": "response",
            "text": "Scout found a compatible spacer.",
            "memory": {
                "turnSequence": 1,
                "revisionAdvancedDuringTurn": False,
                "warnings": [],
            },
        },
        {"type": "done"},
    ]
    body = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
    checks = []

    def check(name: str, condition: bool):
        checks.append((name, bool(condition)))
        print(("PASS " if condition else "FAIL ") + name)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1450, "height": 900})
        page.route(
            "**/api/agent/chat/stream",
            lambda route: route.fulfill(
                status=200,
                content_type="text/event-stream",
                headers={"Cache-Control": "no-cache"},
                body=body,
            ),
        )
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_function("window._selectAgent && window._handleAgentSend", timeout=30_000)
        page.evaluate("window._selectAgent('parts-finder')")
        page.wait_for_selector("#agentInput", state="visible", timeout=15_000)
        page.fill("#agentInput", "find a spacer")
        page.evaluate("async () => { await window._handleAgentSend(); }")
        text = page.locator("#agentMessages .agent-msg-row.assistant").last.inner_text()
        check("Scout commits the terminal SSE response", "Scout found a compatible spacer." in text)
        check(
            "Scout leaves no provisional bubble after done",
            page.locator("#agentMessages .agent-stream-pending").count() == 0,
        )
        check(
            "Scout releases its stream controller after done",
            page.locator("#agentSendBtn").get_attribute("title") == "Send message",
        )
        browser.close()

    failures = [name for name, passed in checks if not passed]
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
