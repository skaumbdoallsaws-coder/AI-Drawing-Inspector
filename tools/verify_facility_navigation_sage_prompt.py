"""Verify the exact user-facing Sage navigation prompt on a scratch layout."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from time import strftime
from typing import Any

from playwright.sync_api import sync_playwright

from verify_facility_navigation_nav2 import (
    OPERATOR_ID,
    REFERENCE_LAYOUT_ID,
    SITE_ID,
    _http_json,
    _open_facility,
    _prepare_path,
)
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".runtime" / "facility-navigation-sage-prompt"
PROMPT = (
    "Use the selected operator's existing Plan-authored motion path. "
    "Compile its navigation snapshot, plan the journey, and play it in Plan "
    "and 3D. Do not create coordinates and do not save the layout."
)


def verify(base_url: str) -> dict[str, Any]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    reference = _http_json(
        base_url,
        f"/api/facility-layouts/{SITE_ID}/{REFERENCE_LAYOUT_ID}",
    )
    scratch_id = "fl-navigation-sage-" + strftime("%Y%m%d-%H%M%S")
    scratch = deepcopy(reference["layout"])
    scratch["layoutId"] = scratch_id
    scratch["displayName"] = "Navigation Sage Prompt Scratch"
    scratch.setdefault("extensions", {}).pop("facilityNavigation", None)
    _http_json(
        base_url,
        f"/api/facility-layouts/{SITE_ID}",
        method="POST",
        payload={"layout": scratch, "makeDefault": False},
    )

    stream_statuses: list[int] = []
    failed_responses: list[dict[str, Any]] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    result: dict[str, Any] = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
            )
            page = context.new_page()
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )

            def observe_response(response: Any) -> None:
                if "/api/agent/chat/v2/stream" in response.url:
                    stream_statuses.append(response.status)
                if response.status >= 400 and not response.url.endswith(
                    "/static/manifest.json"
                ):
                    failed_responses.append({
                        "status": response.status,
                        "method": response.request.method,
                        "url": response.url,
                    })

            page.on("response", observe_response)
            page.goto(
                base_url.rstrip("/")
                + "/?facilityLayoutId=" + scratch_id
                + "&facilitySelectId=" + OPERATOR_ID
                + "&facilityMotionPath=1",
                wait_until="domcontentloaded",
                timeout=120_000,
            )
            _open_facility(page)
            deep_link_selection = page.evaluate(
                """() => window._trainFacilityLayoutAuthoringApp.session
                    .getState().selection"""
            )
            deep_link_motion_path_open = page.evaluate(
                """() => window._trainFacilityLayoutAuthoringApp.workspace
                    .navigationState.open === true"""
            )
            start = {"x": 196.596, "z": 60.6552}
            authored = _prepare_path(
                page,
                actor_id=OPERATOR_ID,
                points=[
                    start,
                    {"x": 196.596, "z": 56.0},
                    {"x": 190.0, "z": 56.0},
                    {"x": 196.596, "z": 56.0},
                    start,
                ],
                loop_mode="closed_loop",
            )
            if not authored["applied"]:
                raise AssertionError("The Plan-authored operator path was rejected.")
            page.evaluate(
                """actorId => {
                    const app = window._trainFacilityLayoutAuthoringApp;
                    app.workspace.closeNavigationDialog(false);
                    app.session.select(actorId);
                    window._selectAgent('deviation-analyst');
                    if (window._agentPanel
                            && !window._agentPanel.classList.contains('open')
                            && typeof window._toggleAgentPanel === 'function') {
                        window._toggleAgentPanel();
                    }
                }""",
                OPERATOR_ID,
            )
            page.wait_for_selector("#agentInput", state="visible", timeout=30_000)
            page.locator("#agentInput").fill(PROMPT)
            page.locator("#agentSendBtn").click()
            page.wait_for_function(
                """() => (
                    document.querySelectorAll(
                        '#agentMessages .agent-stream-pending'
                    ).length > 0
                    || document.getElementById('agentInput').disabled === true
                )""",
                timeout=30_000,
            )
            page.wait_for_function(
                """() => document.querySelectorAll(
                    '#agentMessages .agent-stream-pending'
                ).length === 0
                    && document.getElementById('agentInput').disabled === false""",
                timeout=360_000,
            )
            page.wait_for_timeout(1_500)
            result = page.evaluate(
                """() => {
                    const app = window._trainFacilityLayoutAuthoringApp;
                    const activity = app.workspace.threeAdapter.activity.getState();
                    const state = app.session.getState();
                    return {
                        messages: document.getElementById('agentMessages').innerText,
                        activity,
                        selectedIds: state.selection,
                        operationCount: (state.operations || []).length,
                        dirty: state.dirty,
                        baseRevision: state.baseRevision,
                    };
                }"""
            )
            screenshot = OUTPUT / "sage-navigation-prompt.png"
            page.screenshot(path=str(screenshot), full_page=False)
            result["screenshot"] = screenshot.relative_to(ROOT).as_posix()
            page.evaluate(
                """() => {
                    const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                    const activity = workspace.threeAdapter.activity;
                    const state = activity.getState();
                    workspace._setViewMode('3d');
                    activity.focusActor(state.actors[0].actorId);
                    workspace.threeAdapter.invalidate();
                }"""
            )
            page.wait_for_function(
                """() => window._trainFacilityLayoutAuthoringApp.workspace
                    .threeAdapter.getDiagnostics().pendingLoads === 0""",
                timeout=240_000,
            )
            page.wait_for_timeout(1_200)
            result["three"] = page.evaluate(
                """() => {
                    const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                    const activity = workspace.threeAdapter.activity.getState();
                    const actor = activity.actors[0];
                    const plan = workspace.topAdapter.activitySnapshot;
                    const planActor = plan && Array.isArray(plan.actors)
                        ? plan.actors.find(item => item.actorId === actor.actorId)
                        : null;
                    return {
                        actorId: actor.actorId,
                        exactCatalogVisual: actor.exactCatalogVisual === true,
                        threePose: actor.pose,
                        planPose: planActor && planActor.pose,
                        viewMode: workspace.getState().viewMode,
                    };
                }"""
            )
            three_screenshot = OUTPUT / "sage-navigation-prompt-3d.png"
            page.screenshot(path=str(three_screenshot), full_page=False)
            result["threeScreenshot"] = three_screenshot.relative_to(
                ROOT
            ).as_posix()
            result["authoredPathApplied"] = authored["applied"]
            result["deepLinkSelection"] = deep_link_selection
            result["deepLinkMotionPathOpen"] = deep_link_motion_path_open
            result["authoredOperationCount"] = len(
                authored["session"].get("operations") or []
            )
            context.close()
            browser.close()
    finally:
        current = _http_json(
            base_url,
            f"/api/facility-layouts/{SITE_ID}/{scratch_id}",
        )
        _http_json(
            base_url,
            f"/api/facility-layouts/{SITE_ID}/{scratch_id}/archive",
            method="POST",
            payload={"baseRevision": current["revision"]},
        )

    activity = result.get("activity") or {}
    checks = {
        "streamCompleted": stream_statuses == [200],
        "promptReturned": bool(result.get("messages")),
        "activityLoaded": activity.get("loaded") is True,
        "oneSelectedActorPlaying": (
            len(activity.get("actors") or []) == 1
            and activity.get("status") in {"playing", "paused"}
        ),
        "threeViewUsesExactCatalogVisual": (
            (result.get("three") or {}).get("viewMode") == "3d"
            and (result.get("three") or {}).get("exactCatalogVisual") is True
        ),
        "planAnd3dPoseAgree": (
            (result.get("three") or {}).get("threePose")
            == (result.get("three") or {}).get("planPose")
        ),
        "selectedOperatorPreserved": result.get("selectedIds") == [OPERATOR_ID],
        "deepLinkOpenedAndSelectedOperator": (
            result.get("deepLinkSelection") == [OPERATOR_ID]
        ),
        "deepLinkOpenedMotionPathTool": (
            result.get("deepLinkMotionPathOpen") is True
        ),
        "playbackDidNotAddOperations": (
            result.get("operationCount") == result.get("authoredOperationCount")
        ),
        "noInterruptedResponse": "Response interrupted" not in str(
            result.get("messages") or ""
        ),
        "noBrowserErrors": not console_errors and not page_errors,
        "noFailedHttp": not failed_responses,
    }
    report = {
        "prompt": PROMPT,
        "scratchLayoutId": scratch_id,
        "checks": checks,
        "result": result,
        "streamStatuses": stream_statuses,
        "consoleErrors": console_errors,
        "pageErrors": page_errors,
        "failedResponses": failed_responses,
    }
    report_path = OUTPUT / "sage-navigation-prompt.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    report["report"] = report_path.relative_to(ROOT).as_posix()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    report = verify(args.url)
    print(json.dumps({
        "checks": report["checks"],
        "messages": report["result"].get("messages"),
        "report": report["report"],
    }, indent=2, sort_keys=True))
    return 0 if all(report["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
