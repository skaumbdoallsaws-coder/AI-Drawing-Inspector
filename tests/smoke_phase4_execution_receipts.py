"""Live Playwright smoke for Phase 4 browser execution receipts.

Requires a running InspectorPro server and a configured agent API key.
The test executes one viewport command, verifies browser postcondition
receipts and receipt-grounded status, then confirms the receipts return in
the next request's viewport context and are acknowledged after success.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "runtime_logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

APP_URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8021/")
PART_NUMBER = os.environ.get("SMOKE_PART_NUMBER", "100006")
THREE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
THREE_CACHE = OUT_DIR / "three.r128.min.js"


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report = {"url": APP_URL, "part": PART_NUMBER, "checks": {}, "requests": []}

    def record(name: str, ok: bool, detail=None):
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        suffix = f" :: {detail}" if detail is not None and not ok else ""
        print(f"{'PASS' if ok else 'FAIL'} {name}{suffix}")

    three_js = None
    try:
        if THREE_CACHE.exists() and THREE_CACHE.stat().st_size > 100_000:
            three_js = THREE_CACHE.read_text(encoding="utf-8")
        else:
            with urllib.request.urlopen(THREE_CDN_URL, timeout=15) as response:
                three_js = response.read().decode("utf-8")
            THREE_CACHE.write_text(three_js, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke:warn] Three.js route unavailable: {exc}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        if three_js:
            page.route(
                THREE_CDN_URL,
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/javascript",
                    body=three_js,
                ),
            )

        captured_payloads = []

        def capture_request(request):
            if request.method != "POST" or not request.url.endswith("/api/agent/chat"):
                return
            try:
                captured_payloads.append(request.post_data_json)
            except Exception:  # noqa: BLE001
                pass

        page.on("request", capture_request)
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_function(
            "window.__compareDbg && window._handleAgentSend && window.__phase4Receipts",
            timeout=30_000,
        )
        page.evaluate("window.__phase4Receipts.clear()")

        page.fill("#partSearch", PART_NUMBER)
        page.dispatch_event("#partSearch", "input")
        page.wait_for_timeout(600)
        page.locator(f".search-dropdown-item:has-text('{PART_NUMBER}')").first.click()
        page.wait_for_function(
            f"window.__compareDbg.state.partNumber === '{PART_NUMBER}'", timeout=30_000
        )
        try:
            page.wait_for_function(
                "window.__compareDbg.state.motionPkgInfo"
                " && window.__compareDbg.state.motionPkgInfo.summary",
                timeout=10_000,
            )
        except Exception:
            page.click(".tab[data-tab='assembly']")
            page.wait_for_function(
                "window.__compareDbg.state.motionPkgInfo"
                " && window.__compareDbg.state.motionPkgInfo.summary",
                timeout=45_000,
            )

        page.click(".tab[data-tab='report']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'report'", timeout=15_000)
        page.evaluate("window._selectAgent && window._selectAgent('deviation-analyst')")
        page.wait_for_timeout(500)

        def ask(message: str) -> str:
            sent = page.evaluate(
                "async (q) => { window._agentInput.value = q;"
                " await window._handleAgentSend(); return true; }",
                message,
            )
            if not sent:
                raise RuntimeError("message was not sent")
            return page.evaluate(
                "() => { const rows = document.querySelectorAll('#agentMessages .agent-msg-row.assistant');"
                " return rows.length ? rows[rows.length - 1].innerText : ''; }"
            )

        first_answer = ask("show the affected motion")
        try:
            page.wait_for_function("window.__compareDbg.state.motionPlaying === true", timeout=20_000)
        except Exception:
            pass
        history = page.evaluate("window.__phase4Receipts.history()")
        pending = page.evaluate("window.__phase4Receipts.pending()")
        succeeded = [item for item in history if item.get("status") == "succeeded"]
        tool_ids = {item.get("tool_id") for item in succeeded}
        record("command_started_motion", page.evaluate("window.__compareDbg.state.motionPlaying === true"))
        record("highlight_receipt_succeeded", "set_part_highlight" in tool_ids, history)
        record("motion_receipt_succeeded", "play_motion" in tool_ids, history)
        record("receipt_status_is_visible", "Showing " in first_answer and "RPM" in first_answer, first_answer)
        record("receipts_pending_for_next_turn", len(pending) >= 2, pending)

        second_answer = ask("what did the browser verify on the previous turn?")
        record("second_answer_received", bool(second_answer.strip()), second_answer)
        record("two_chat_requests_captured", len(captured_payloads) >= 2, len(captured_payloads))
        second_payload = captured_payloads[-1] if captured_payloads else {}
        attached = (
            second_payload.get("inspection_context", {})
            .get("attachments", {})
            .get("viewport", {})
            .get("execution_receipts", [])
        )
        attached_ids = {item.get("receipt_id") for item in attached}
        expected_ids = {item.get("receipt_id") for item in pending}
        record("next_turn_carries_receipts", expected_ids <= attached_ids, {
            "expected": sorted(expected_ids), "attached": sorted(attached_ids)
        })
        pending_after = page.evaluate("window.__phase4Receipts.pending()")
        pending_after_ids = {item.get("receipt_id") for item in pending_after}
        record(
            "successful_response_acknowledges_receipts",
            not (expected_ids & pending_after_ids),
            {"sent": sorted(expected_ids), "still_pending": sorted(pending_after_ids)},
        )

        report["first_answer"] = first_answer
        report["second_answer"] = second_answer
        report["receipt_history"] = history
        report["requests"] = [
            {
                "message": payload.get("message"),
                "receipt_count": len(
                    payload.get("inspection_context", {})
                    .get("attachments", {})
                    .get("viewport", {})
                    .get("execution_receipts", [])
                ),
            }
            for payload in captured_payloads
        ]
        page.screenshot(path=str(OUT_DIR / "phase4_execution_receipts_smoke.png"))
        browser.close()

    output = OUT_DIR / "phase4_execution_receipts_smoke.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = [name for name, result in report["checks"].items() if not result["ok"]]
    print(f"findings -> {output.relative_to(REPO_ROOT)}")
    print(f"{len(report['checks']) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
