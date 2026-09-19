"""Verify the selected-path prompt fails clearly on the blank default."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".runtime" / "facility-navigation-sage-prompt"
PROMPT = (
    "Use the selected operator's existing Plan-authored motion path. "
    "Compile its navigation snapshot, plan the journey, and play it in Plan "
    "and 3D. Do not create coordinates and do not save the layout."
)


def verify(base_url: str) -> dict[str, Any]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    stream_statuses: list[int] = []
    failed_http: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )

        def observe(response: Any) -> None:
            if "/api/agent/chat/v2/stream" in response.url:
                stream_statuses.append(response.status)
            if response.status >= 400 and not response.url.endswith(
                "/static/manifest.json"
            ):
                failed_http.append({
                    "status": response.status,
                    "url": response.url,
                })

        page.on("response", observe)
        page.goto(base_url, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_function(
            """() => window.__inspectorProMainScriptReady === true
                && typeof switchTab === 'function'
                && typeof _trainApplyTrainingTypeDefaults === 'function'""",
            timeout=120_000,
        )
        page.evaluate(
            """() => {
                const previous = trainingState.type;
                trainingState.type = 'facility_layout';
                trainingState.viewportMode = 'facility_layout';
                _trainApplyTrainingTypeDefaults(previous);
                switchTab('training');
            }"""
        )
        page.wait_for_function(
            """() => window._trainFacilityLayoutAuthoringApp
                && _trainFacilityLayoutAuthoringApp.session.getState().loaded
                && !_trainFacilityLayoutAuthoringApp.session.getState().busy
                && (_trainFacilityLayoutAuthoringApp.session.getState()
                    .layout.placements || []).length === 0""",
            timeout=240_000,
        )
        page.evaluate(
            """() => {
                window._selectAgent('deviation-analyst');
                if (window._agentPanel
                        && !window._agentPanel.classList.contains('open')
                        && typeof window._toggleAgentPanel === 'function') {
                    window._toggleAgentPanel();
                }
            }"""
        )
        page.wait_for_selector("#agentInput", state="visible", timeout=30_000)
        page.locator("#agentInput").fill(PROMPT)
        page.locator("#agentSendBtn").click()
        page.wait_for_function(
            """() => document.getElementById('agentInput').disabled === true""",
            timeout=30_000,
        )
        page.wait_for_function(
            """() => document.getElementById('agentInput').disabled === false
                && document.querySelectorAll(
                    '#agentMessages .agent-stream-pending'
                ).length === 0""",
            timeout=120_000,
        )
        page.wait_for_timeout(500)
        result = page.evaluate(
            """() => ({
                messages: document.getElementById('agentMessages').innerText,
                selection: _trainFacilityLayoutAuthoringApp.session
                    .getState().selection,
                placementCount: (_trainFacilityLayoutAuthoringApp.session
                    .getState().layout.placements || []).length,
                activity: _trainFacilityLayoutAuthoringApp.workspace
                    .threeAdapter.activity.getState(),
            })"""
        )
        screenshot = OUTPUT / "blank-layout-prerequisite.png"
        page.screenshot(path=str(screenshot), full_page=False)
        browser.close()

    messages = str(result["messages"])
    checks = {
        "blankDefaultConfirmed": result["placementCount"] == 0,
        "nothingSelected": result["selection"] == [],
        "specificPrerequisiteReturned": (
            "No operator or vehicle is selected" in messages
        ),
        "genericFailureAbsent": (
            "could not generate a response" not in messages.casefold()
        ),
        "noActivityStarted": result["activity"]["loaded"] is False,
        "streamCompleted": stream_statuses == [200],
        "noFailedHttp": not failed_http,
    }
    report = {
        "prompt": PROMPT,
        "checks": checks,
        "messages": messages,
        "streamStatuses": stream_statuses,
        "failedHttp": failed_http,
        "screenshot": screenshot.relative_to(ROOT).as_posix(),
    }
    path = OUTPUT / "blank-layout-prerequisite.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    report = verify(args.url)
    return 0 if all(report["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
