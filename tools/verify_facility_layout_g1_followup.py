"""Verify successive whole-facility requests through the visible Sage chat."""

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
DEFAULT_OUTPUT = EVIDENCE_ROOT / "g1-followup-browser-evidence.json"
DEFAULT_SCREENSHOT = EVIDENCE_ROOT / "g1-followup-browser.png"

PROMPTS = (
    (
        "Create a new 100 m by 80 m facility and divide it into four equal "
        "departments named Receiving and Stores, Machining, Assembly, and "
        "Inspection and Shipping."
    ),
    (
        "Create a new 100 m by 100 m facility and divide it into four equal "
        "departments named Receiving and Stores, Machining, Assembly, and "
        "Inspection and Shipping."
    ),
    (
        "Create a new 120 m by 90 m facility and divide it into five equal "
        "departments named Inbound, Fabrication, Assembly, Quality, and Dispatch."
    ),
)
LABELS = (
    [
        "Receiving and Stores",
        "Machining",
        "Assembly",
        "Inspection and Shipping",
    ],
    [
        "Receiving and Stores",
        "Machining",
        "Assembly",
        "Inspection and Shipping",
    ],
    ["Inbound", "Fabrication", "Assembly", "Quality", "Dispatch"],
)
DIMENSIONS = ((100.0, 80.0), (100.0, 100.0), (120.0, 90.0))


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
            _trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
        )""",
        timeout=120_000,
    )


def _send_and_wait(
    page: Any,
    prompt: str,
    labels: list[str],
    dimensions: tuple[float, float],
) -> dict[str, Any]:
    page.locator("#agentInput").fill(prompt)
    page.locator("#agentSendBtn").click()
    page.wait_for_function(
        """expected => {
            const state = _trainFacilityLayoutAuthoringApp.session.getState();
            const agentSession = typeof getCurrentAgentSession === 'function'
                ? getCurrentAgentSession() : null;
            const layout = state.layout || {};
            const plan = layout.extensions && layout.extensions.facilityPlan || {};
            const labels = Array.isArray(layout.zones)
                ? layout.zones.map(zone => String(zone.label || '')) : [];
            return state.canSave === true
                && state.generatedDraft
                && state.generatedDraft.status === 'complete'
                && !state.generatedDraft.currentStageId
                && (!agentSession || (
                    agentSession.waiting !== true
                    && !agentSession.activeStream
                ))
                && state.dirty === true
                && Number(plan.widthMeters) === expected.width
                && Number(plan.depthMeters) === expected.depth
                && JSON.stringify(labels) === JSON.stringify(expected.labels);
        }""",
        arg={"labels": labels, "width": dimensions[0], "depth": dimensions[1]},
        timeout=360_000,
    )
    page.wait_for_timeout(500)
    return page.evaluate(
        """() => {
            const state = _trainFacilityLayoutAuthoringApp.session.getState();
            const plan = state.layout.extensions.facilityPlan;
            return {
                runId: state.generatedDraft.runId,
                widthMeters: plan.widthMeters,
                depthMeters: plan.depthMeters,
                labels: state.layout.zones.map(zone => zone.label),
                dirty: state.dirty,
                canSave: state.canSave,
                baseRevision: state.baseRevision,
                baseLabels: (state.baseLayout.zones || []).map(zone => zone.label),
            };
        }"""
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

        first = _send_and_wait(page, PROMPTS[0], LABELS[0], DIMENSIONS[0])
        second = _send_and_wait(page, PROMPTS[1], LABELS[1], DIMENSIONS[1])
        saved = page.evaluate(
            """async () => {
                await _trainFacilityLayoutAuthoringApp.workspace.executeCommand('save');
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return {
                    dirty: state.dirty,
                    widthMeters: state.baseLayout.extensions.facilityPlan.widthMeters,
                    depthMeters: state.baseLayout.extensions.facilityPlan.depthMeters,
                    labels: state.baseLayout.zones.map(zone => zone.label),
                    baseRevision: state.baseRevision,
                };
            }"""
        )
        third = _send_and_wait(page, PROMPTS[2], LABELS[2], DIMENSIONS[2])
        page.screenshot(path=str(screenshot), full_page=False)
        restored = page.evaluate(
            """async () => {
                await _trainFacilityLayoutAuthoringApp.workspace.executeCommand('undo');
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const plan = state.layout.extensions.facilityPlan;
                return {
                    dirty: state.dirty,
                    widthMeters: plan.widthMeters,
                    depthMeters: plan.depthMeters,
                    labels: state.layout.zones.map(zone => zone.label),
                };
            }"""
        )
        messages = page.locator("#agentMessages").inner_text()
        browser.close()

    checks = {
        "three_streams_completed": stream_statuses == [200, 200, 200],
        "followup_superseded_first_run": first["runId"] != second["runId"],
        "followup_recompiled_dimensions": (
            second["widthMeters"] == 100.0
            and second["depthMeters"] == 100.0
        ),
        "followup_kept_exact_labels": second["labels"] == LABELS[1],
        "followup_was_unsaved_review_draft": (
            second["dirty"] is True and second["canSave"] is True
        ),
        "save_persisted_second_request": saved == {
            "dirty": False,
            "widthMeters": 100.0,
            "depthMeters": 100.0,
            "labels": LABELS[1],
            "baseRevision": saved["baseRevision"],
        },
        "brownfield_request_is_dynamic": (
            third["runId"] != second["runId"]
            and third["widthMeters"] == 120.0
            and third["depthMeters"] == 90.0
            and third["labels"] == LABELS[2]
        ),
        "undo_restored_saved_brownfield_base": restored == {
            "dirty": False,
            "widthMeters": 100.0,
            "depthMeters": 100.0,
            "labels": LABELS[1],
        },
        "no_interruption_or_lifecycle_blocker": not any(
            phrase in messages
            for phrase in (
                "Response interrupted",
                "Save or discard editor changes",
                "g1_greenfield_base_not_empty",
                "facility_layout_request_failed",
                "I could not complete the Facility draft",
            )
        ),
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
    }
    evidence = {
        "schemaVersion": "facility-layout-g1-followup-browser-evidence-v1",
        "prompts": list(PROMPTS),
        "passed": all(checks.values()),
        "checks": checks,
        "streamStatuses": stream_statuses,
        "runs": {"first": first, "second": second, "third": third},
        "saved": saved,
        "restored": restored,
        "responseText": messages,
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
