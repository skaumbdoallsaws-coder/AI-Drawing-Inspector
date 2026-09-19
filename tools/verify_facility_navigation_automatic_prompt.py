"""Verify GPS-like automatic operator routing through the live Sage surface."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from time import strftime
from typing import Any

from playwright.sync_api import sync_playwright

from verify_facility_navigation_nav2 import (
    ARCHIVE,
    REFERENCE_LAYOUT_ID,
    SITE_ID,
    _http_json,
    _open_facility,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".runtime" / "facility-navigation-automatic-prompt"
ACTOR_ID = "pl-bcacfe9d20c7e2cb5b3adc85"
TARGET_IDS = [
    "pl-0ebca12155b950e01123b122",
    "pl-06f42576ee65a4b3d7887b8c",
]
PROMPT = (
    "Route this operator through the selected stops in order, return to the "
    "start, and play it. Do not save."
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(base_url: str) -> dict[str, Any]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    archive_before = _sha(ARCHIVE)
    reference = _http_json(
        base_url,
        f"/api/facility-layouts/{SITE_ID}/{REFERENCE_LAYOUT_ID}",
    )
    scratch_id = "fl-navigation-auto-" + strftime("%Y%m%d-%H%M%S")
    scratch = deepcopy(reference["layout"])
    scratch["layoutId"] = scratch_id
    scratch["displayName"] = "Automatic Operator Route Scratch"
    scratch.setdefault("extensions", {}).pop("facilityNavigation", None)
    created = _http_json(
        base_url,
        f"/api/facility-layouts/{SITE_ID}",
        method="POST",
        payload={"layout": scratch, "makeDefault": False},
    )
    scratch_revision = str(created.get("revision") or "")

    stream_statuses: list[int] = []
    stream_responses: list[Any] = []
    stream_bodies: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    result: dict[str, Any] = {}
    selected: list[str] = []
    saved_revision_unchanged = False
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
                    stream_responses.append(response)
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
                base_url.rstrip("/") + "/?facilityLayoutId=" + scratch_id,
                wait_until="domcontentloaded",
                timeout=120_000,
            )
            _open_facility(page)
            selected = page.evaluate(
                """ids => {
                    const app = window._trainFacilityLayoutAuthoringApp;
                    app.session.select(ids[0]);
                    ids.slice(1).forEach(id => app.session.select(id, {
                        additive: true,
                    }));
                    window._selectAgent('deviation-analyst');
                    if (window._agentPanel
                            && !window._agentPanel.classList.contains('open')
                            && typeof window._toggleAgentPanel === 'function') {
                        window._toggleAgentPanel();
                    }
                    return app.session.getState().selection;
                }""",
                [ACTOR_ID, *TARGET_IDS],
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
            stream_bodies = [
                response.body().decode("utf-8", errors="replace")
                for response in stream_responses
            ]
            result = page.evaluate(
                """ids => {
                    const app = window._trainFacilityLayoutAuthoringApp;
                    const state = app.session.getState();
                    const navigation = state.layout.extensions
                        && state.layout.extensions.facilityNavigation;
                    const program = navigation
                        && navigation.movementPrograms.find(item => (
                            item.actorPlacementId === ids.actor
                        ));
                    const required = new Set(
                        program && program.requiredAnchorIds || []
                    );
                    const anchors = navigation
                        ? navigation.anchors.filter(item => (
                            required.has(item.navigationAnchorId)
                        )) : [];
                    const anchorById = new Map(anchors.map(item => (
                        [item.navigationAnchorId, item]
                    )));
                    const orderedAnchors = (program && program.orderedStops || [])
                        .map(stop => anchorById.get(stop.navigationAnchorId))
                        .filter(Boolean);
                    const activity = app.workspace.threeAdapter.activity.getState();
                    const destinationSourceIds = orderedAnchors
                        .filter(item => item.derivedPositionRef
                            && item.derivedPositionRef.sourceKind
                                === 'placement_access')
                        .map(item => item.derivedPositionRef.sourceId);
                    return {
                        messages: document.getElementById('agentMessages').innerText,
                        activity,
                        selection: state.selection,
                        dirty: state.dirty,
                        operationCount: (state.operations || []).length,
                        baseRevision: state.baseRevision,
                        program,
                        anchors,
                        destinationSourceIds,
                        allDerivedCoordinatesAbsent: anchors.every(item => (
                            item.positionAuthority !== 'derived'
                            || item.localPosition === null
                        )),
                        manualPathConstraintCount: navigation
                            ? navigation.manualPathConstraints.length : -1,
                    };
                }""",
                {"actor": ACTOR_ID, "targets": TARGET_IDS},
            )
            page.evaluate(
                """() => {
                    const app = window._trainFacilityLayoutAuthoringApp;
                    app.session.clearSelection();
                    const workspace = app.workspace;
                    if (workspace.motionPanel) {
                        workspace.motionPanel.style.left = '14px';
                        workspace.motionPanel.style.top = '14px';
                        workspace.motionPanel.style.bottom = 'auto';
                        workspace.motionPanel.style.width = '500px';
                    }
                    workspace._setViewMode('plan');
                    workspace.topAdapter.fitLayout();
                    const center = {x: 102.108, z: 67.05};
                    for (let index = 0; index < 2; index += 1) {
                        const client = workspace.topAdapter.worldToClient(center);
                        workspace.topAdapter.zoomAt({
                            clientX: client.x,
                            clientY: client.y,
                        }, 4);
                    }
                    workspace.topAdapter._render();
                }"""
            )
            page.wait_for_timeout(700)
            plan_path = OUTPUT / "automatic-operator-route-plan.png"
            page.screenshot(path=str(plan_path), full_page=False)
            result["planScreenshot"] = plan_path.relative_to(ROOT).as_posix()

            page.evaluate(
                """placementId => {
                    const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                    workspace._setViewMode('3d');
                    workspace.threeAdapter.activity.pause();
                    const actor = workspace.threeAdapter.activity.getState().actors
                        .find(item => item.placementId === placementId);
                    if (actor) workspace.threeAdapter.activity.focusActor(actor.actorId);
                    workspace.threeAdapter.invalidate();
                }""",
                ACTOR_ID,
            )
            page.wait_for_timeout(3_000)
            page.evaluate(
                """placementId => {
                    const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                    const actor = workspace.threeAdapter.activity.getState().actors
                        .find(item => item.placementId === placementId);
                    if (actor) workspace.threeAdapter.activity.focusActor(actor.actorId);
                    workspace.threeAdapter.invalidate();
                }""",
                ACTOR_ID,
            )
            page.wait_for_timeout(1_200)
            result["three"] = page.evaluate(
                """placementId => {
                    const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                    const activity = workspace.threeAdapter.activity.getState();
                    const actor = activity.actors.find(
                        item => item.placementId === placementId
                    );
                    const plan = workspace.topAdapter.activitySnapshot;
                    const planActor = plan && Array.isArray(plan.actors)
                        ? plan.actors.find(item => (
                            actor && item.actorId === actor.actorId
                        )) : null;
                    return {
                        actorId: actor && actor.actorId,
                        placementId: actor && actor.placementId,
                        exactCatalogVisual: actor
                            && actor.exactCatalogVisual === true,
                        threePose: actor && actor.pose,
                        planPose: planActor && planActor.pose,
                        viewMode: workspace.getState().viewMode,
                        unrelatedPendingLoads: workspace.threeAdapter
                            .getDiagnostics().pendingLoads,
                    };
                }""",
                ACTOR_ID,
            )
            three_path = OUTPUT / "automatic-operator-route-3d.png"
            page.screenshot(path=str(three_path), full_page=False)
            result["threeScreenshot"] = three_path.relative_to(ROOT).as_posix()

            result["afterUndo"] = page.evaluate(
                """async () => {
                    const app = window._trainFacilityLayoutAuthoringApp;
                    await app.session.undo();
                    const state = app.session.getState();
                    return {
                        dirty: state.dirty,
                        operationCount: (state.operations || []).length,
                        navigationPresent: Boolean(
                            state.layout.extensions
                            && state.layout.extensions.facilityNavigation
                        ),
                    };
                }"""
            )
            context.close()
            browser.close()
    finally:
        current = _http_json(
            base_url,
            f"/api/facility-layouts/{SITE_ID}/{scratch_id}",
        )
        saved_revision_unchanged = str(current.get("revision") or "") == (
            scratch_revision
        )
        _http_json(
            base_url,
            f"/api/facility-layouts/{SITE_ID}/{scratch_id}/archive",
            method="POST",
            payload={"baseRevision": current["revision"]},
        )

    activity = result.get("activity") or {}
    actors = activity.get("actors") or []
    three = result.get("three") or {}
    checks = {
        "selectionOrderPreserved": selected == [ACTOR_ID, *TARGET_IDS],
        "streamCompleted": stream_statuses == [200],
        "oneUnsavedSemanticOperation": (
            result.get("dirty") is True
            and result.get("operationCount") == 1
        ),
        "programUsesExistingActor": (
            (result.get("program") or {}).get("actorPlacementId") == ACTOR_ID
        ),
        "destinationsPreserveSelectionOrder": (
            result.get("destinationSourceIds") == TARGET_IDS
        ),
        "noGeneratedCoordinatesPersisted": (
            result.get("allDerivedCoordinatesAbsent") is True
        ),
        "noManualPathWasRequired": (
            result.get("manualPathConstraintCount") == 0
        ),
        "activityLoadedAndPlaying": (
            activity.get("loaded") is True
            and len(actors) == 1
            and actors[0].get("placementId") == ACTOR_ID
            and activity.get("status") in {"playing", "paused"}
        ),
        "threeUsesExistingCatalogActor": (
            three.get("viewMode") == "3d"
            and three.get("placementId") == ACTOR_ID
            and three.get("exactCatalogVisual") is True
        ),
        "planAnd3dPoseAgree": three.get("threePose") == three.get("planPose"),
        "undoRestoredScratchBase": result.get("afterUndo") == {
            "dirty": False,
            "operationCount": 0,
            "navigationPresent": False,
        },
        "savedScratchRevisionUnchanged": saved_revision_unchanged,
        "manualReferenceUnchanged": _sha(ARCHIVE) == archive_before,
        "noInterruptedResponse": "Response interrupted" not in str(
            result.get("messages") or ""
        ),
        "noBrowserErrors": not console_errors and not page_errors,
        "noFailedHttp": not failed_responses,
    }
    report = {
        "prompt": PROMPT,
        "scratchLayoutId": scratch_id,
        "actorPlacementId": ACTOR_ID,
        "orderedTargetPlacementIds": TARGET_IDS,
        "checks": checks,
        "result": result,
        "streamStatuses": stream_statuses,
        "streamBodies": stream_bodies,
        "consoleErrors": console_errors,
        "pageErrors": page_errors,
        "failedResponses": failed_responses,
    }
    report_path = OUTPUT / "automatic-operator-route-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    report["report"] = report_path.relative_to(ROOT).as_posix()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8125")
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
