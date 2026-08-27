"""Verify G1 Facility generation through the visible Sage chat workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "knowledge_foundation"
)
DEFAULT_OUTPUT = EVIDENCE_ROOT / "g1-chat-browser-evidence.json"
DEFAULT_SCREENSHOT = EVIDENCE_ROOT / "g1-chat-browser.png"
PROMPT = (
    "Create a new 100 m by 80 m facility and divide it into four equal "
    "departments named Receiving and Stores, Machining, Assembly, and "
    "Inspection and Shipping."
)
EXPECTED_LABELS = [
    "Receiving and Stores",
    "Machining",
    "Assembly",
    "Inspection and Shipping",
]


def _open_facility(page: Any) -> None:
    page.wait_for_function(
        """() => (
            window.__inspectorProMainScriptReady === true
            && typeof switchTab === 'function'
            && typeof _trainApplyTrainingTypeDefaults === 'function'
        )""",
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
    page.wait_for_selector(
        "#trainFacilityLayoutAuthoring.ip-flw-root",
        state="visible",
        timeout=120_000,
    )
    page.wait_for_function(
        """() => !!(
            typeof _trainFacilityLayoutAuthoringApp !== 'undefined'
            && _trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
        )""",
        timeout=120_000,
    )


def verify(app_url: str, output: Path, screenshot: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    stream_statuses: list[int] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text)
                if message.type == "error"
                else None
            ),
        )

        def observe_response(response: Any) -> None:
            if "/api/agent/chat/v2/stream" in response.url:
                stream_statuses.append(response.status)
            if response.status >= 400 and not response.url.endswith(
                "/static/manifest.json"
            ):
                failed_responses.append({
                    "method": response.request.method,
                    "status": response.status,
                    "url": response.url,
                })

        page.on("response", observe_response)
        page.goto(app_url, wait_until="load", timeout=120_000)
        _open_facility(page)
        page.evaluate("() => window._selectAgent('deviation-analyst')")
        page.wait_for_selector("#agentInput", state="visible", timeout=30_000)
        page.locator("#agentInput").fill(PROMPT)
        page.locator("#agentSendBtn").click()

        page.wait_for_function(
            """labels => {
                const app = _trainFacilityLayoutAuthoringApp;
                const state = app.session.getState();
                const zones = state.layout && Array.isArray(state.layout.zones)
                    ? state.layout.zones : [];
                const actual = zones.map(zone => String(zone.label || ''));
                const pending = document.querySelectorAll(
                    '#agentMessages .agent-stream-pending'
                ).length;
                return pending === 0
                    && zones.length === labels.length
                    && labels.every(label => actual.includes(label));
            }""",
            arg=EXPECTED_LABELS,
            timeout=360_000,
        )
        page.wait_for_timeout(750)

        result = page.evaluate(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return {
                    agent: window._getCurrentAgentKey(),
                    messages: document.getElementById('agentMessages').innerText,
                    state: {
                        baseRevision: state.baseRevision,
                        dirty: state.dirty,
                        canSave: state.canSave,
                        generatedDraft: state.generatedDraft,
                        layout: state.layout,
                        baseLayout: state.baseLayout,
                    },
                };
            }"""
        )
        page.screenshot(path=str(screenshot), full_page=False)
        cleanup = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                await app.workspace.executeCommand('undo');
                const state = app.session.getState();
                return {
                    dirty: state.dirty,
                    zoneCount: (state.layout && state.layout.zones || []).length,
                    placementCount: (
                        state.layout && state.layout.placements || []
                    ).length,
                    routeCount: (state.layout && state.layout.routes || []).length,
                    markingCount: (
                        state.layout && state.layout.floorMarkings || []
                    ).length,
                };
            }"""
        )
        browser.close()

    layout = result["state"]["layout"]
    base = result["state"]["baseLayout"]
    plan = ((layout.get("extensions") or {}).get("facilityPlan") or {})
    labels = [str(zone.get("label") or "") for zone in layout.get("zones", [])]
    messages = str(result.get("messages") or "")
    checks = {
        "sage_selected": result.get("agent") == "deviation-analyst",
        "stream_completed": stream_statuses == [200],
        "no_interruption_message": "Response interrupted" not in messages,
        "exact_dimensions": (
            float(plan.get("widthMeters") or 0) == 100.0
            and float(plan.get("depthMeters") or 0) == 80.0
        ),
        "exact_department_labels": labels == EXPECTED_LABELS,
        "review_draft_is_unsaved": (
            result["state"]["dirty"] is True
            and result["state"]["canSave"] is True
            and not (base.get("zones") or [])
        ),
        "no_unrequested_entities": not any(
            layout.get(field)
            for field in ("routes", "placements", "floorMarkings")
        ),
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
        "cleanup_restores_empty_base": cleanup == {
            "dirty": False,
            "zoneCount": 0,
            "placementCount": 0,
            "routeCount": 0,
            "markingCount": 0,
        },
    }
    evidence = {
        "schemaVersion": "facility-layout-g1-chat-browser-evidence-v1",
        "prompt": PROMPT,
        "passed": all(checks.values()),
        "checks": checks,
        "streamStatuses": stream_statuses,
        "responseText": messages,
        "result": {
            "facility": {
                "widthMeters": plan.get("widthMeters"),
                "depthMeters": plan.get("depthMeters"),
            },
            "departmentLabels": labels,
            "dirty": result["state"]["dirty"],
            "canSave": result["state"]["canSave"],
            "runId": (
                (result["state"].get("generatedDraft") or {}).get("runId")
            ),
            "cleanup": cleanup,
        },
        "errors": {
            "console": console_errors,
            "page": page_errors,
            "failedResponses": failed_responses,
        },
        "screenshot": screenshot.relative_to(ROOT).as_posix(),
    }
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8141/")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--screenshot", type=Path, default=DEFAULT_SCREENSHOT)
    args = parser.parse_args()
    evidence = verify(args.url, args.output, args.screenshot)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
