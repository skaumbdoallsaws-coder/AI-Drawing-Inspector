"""Capture browser proof for local operator and material-handoff activity."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
LAYOUT = (
    ROOT
    / ".runtime"
    / "facility-motion"
    / "acceptance-root"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-main.json"
)
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
PROMPT = (
    "Play a prototype factory activity view using only operators, forklifts, "
    "and vehicles that are already placed in this layout. Move the selected "
    "existing operators around their assigned assembly and kitting cells, "
    "including each complete outbound walk to its FIFO point, the material "
    "handoff between the paired FIFO points, and the return walk to the "
    "operator's original station. Move the existing forklifts only on their "
    "authored direction-marked material lanes, changing to the opposite lane "
    "before each return trip. Do not add or duplicate any operator, vehicle, "
    "asset, route, or placement. Keep machines without revision-bound "
    "kinematic evidence stationary. Show the operator paths, FIFO access "
    "paths, handoff lines, and FIFO points, loop every moving actor "
    "continuously, use up to 20 actors, and keep the layout unsaved."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _image_record(path: Path) -> dict[str, Any]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        extrema = image.getextrema()
        return {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(path),
            "width": image.width,
            "height": image.height,
            "nonblank": any(low != high for low, high in extrema),
        }


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
            window._trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && _trainFacilityLayoutAuthoringApp.session.getState().loaded
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
        )""",
        timeout=180_000,
    )
    page.evaluate(
        """async () => {
            const workspace = _trainFacilityLayoutAuthoringApp.workspace;
            if (workspace.controller
                    && typeof workspace.controller.ready === 'function') {
                await workspace.controller.ready();
            }
        }"""
    )


def capture(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    before_hash = _sha256(LAYOUT)
    screenshots: list[Path] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    server_errors: list[str] = []
    stream_statuses: list[int] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(EDGE) if EDGE.exists() else None,
            headless=True,
            args=["--disable-features=TranslateUI"],
        )
        page = browser.new_page(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error" else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                f"{request.method} {request.url}: {request.failure}"
            ),
        )
        def observe_response(response: Any) -> None:
            if "/api/agent/chat/v2/stream" in response.url:
                stream_statuses.append(response.status)
            if response.status >= 500:
                server_errors.append(f"{response.status} {response.url}")

        page.on("response", observe_response)
        page.goto(args.url, wait_until="domcontentloaded", timeout=120_000)
        _open_facility(page)
        page.wait_for_function(
            """() => _trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.getDiagnostics().pendingLoads === 0""",
            timeout=240_000,
        )
        response_text = ""
        agent_context_probe = None
        if args.through_chat:
            page.evaluate("() => window._selectAgent('deviation-analyst')")
            page.wait_for_selector("#agentInput", state="visible", timeout=30_000)
            page.locator("#agentInput").fill(PROMPT)
            with page.expect_request(
                lambda request: "/api/agent/chat/v2/stream" in request.url,
                timeout=30_000,
            ) as request_info:
                page.locator("#agentSendBtn").click()
            request_payload = request_info.value.post_data_json
            facility_attachment = (
                request_payload.get("inspection_context", {})
                .get("attachments", {})
                .get("facility_layout")
            )
            agent_context_probe = {
                "siteId": facility_attachment.get("siteId"),
                "layoutId": facility_attachment.get("layoutId"),
                "revision": facility_attachment.get("revision"),
                "dirty": facility_attachment.get("state", {}).get("dirty"),
            } if isinstance(facility_attachment, dict) else None
            print(json.dumps({"facilityContextProbe": agent_context_probe}), flush=True)
        else:
            page.evaluate(
                """async () => {
                    const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                    await workspace.startActivityPlayback({
                        preset: 'mobile_actors_on_authored_routes',
                        prototypeMode: true,
                        maximumActors: 20,
                        scenarioLabel: 'Existing operators with complete handoffs',
                    });
                }"""
            )
        page.wait_for_function(
            """() => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                const state = workspace.threeAdapter.activity.getState();
                const pending = document.querySelectorAll(
                    '#agentMessages .agent-stream-pending'
                ).length;
                return pending === 0 && state.loaded
                    && state.actors.length >= 16
                    && state.leanMotionCounts
                    && state.leanMotionCounts.operatorPaths === 12
                    && state.leanMotionCounts.pedestrianConnections === 12
                    && state.leanMotionCounts.assistanceGates === 3
                    && state.leanMotionCounts.materialHandoffs === 7
                    && state.leanMotionCounts.fifoPoints === 12
                    && workspace.threeAdapter.getDiagnostics().pendingLoads === 0;
            }""",
            timeout=300_000,
        )
        if args.through_chat:
            response_text = page.locator("#agentMessages").inner_text()
            prompt_path = output / "00-sage-existing-actors-and-handoffs.png"
            page.screenshot(path=str(prompt_path))
            screenshots.append(prompt_path)
        summary = page.evaluate(
            """() => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                const scenario = workspace.activityPresentation.scenario;
                const actors = scenario.actors || [];
                const counts = {vehicle: 0, operator: 0, mobile_equipment: 0};
                actors.forEach(actor => {
                    counts[actor.actorType] = (counts[actor.actorType] || 0) + 1;
                });
                const lean = scenario.leanMotion || {};
                return {
                    scenarioId: scenario.scenarioId,
                    layoutRevision: scenario.layoutRevision,
                    label: scenario.label,
                    prototypeMode: scenario.prototypeMode,
                    actorCount: actors.length,
                    actorTypeCounts: counts,
                    leanMotionCounts: {
                        operatorPaths: (lean.operatorPaths || []).length,
                        pedestrianConnections:
                            (lean.pedestrianConnections || []).length,
                        assistanceGates: (lean.assistanceGates || []).length,
                        materialHandoffs: (lean.materialHandoffs || []).length,
                        fifoPoints: (lean.fifoPoints || []).length,
                    },
                    cycleDurationSeconds: scenario.cycleDurationSeconds,
                    qualification: scenario.qualification,
                };
            }"""
        )
        topology_audit = page.evaluate(
            """() => {
                const app = _trainFacilityLayoutAuthoringApp;
                const workspace = app.workspace;
                const layout = app.session.getState().layout;
                const presentation = workspace.activityPresentation;
                const scenario = presentation.scenario;
                const payloads = presentation.actorPayloads;
                const lean = scenario.leanMotion;
                const actors = new Map(scenario.actors.map(actor => [
                    actor.actorId,
                    actor,
                ]));
                const fifo = new Map(lean.fifoPoints.map(point => [
                    point.pointId,
                    point,
                ]));
                const connections = new Map(
                    lean.pedestrianConnections.map(connection => [
                        connection.connectionId,
                        connection,
                    ])
                );
                const equalPoint = (left, right) => !!left && !!right
                    && Number(left.x) === Number(right.x)
                    && Number(left.z) === Number(right.z);
                const connectionFailures = [];
                lean.pedestrianConnections.forEach(connection => {
                    const actor = actors.get(connection.actorId);
                    const point = fifo.get(connection.fifoPointId);
                    const outbound = payloads[connection.motionPackageIds[0]];
                    const returning = payloads[connection.motionPackageIds[1]];
                    const outboundPoses = outbound
                        && outbound.package.movement.poses || [];
                    const returnPoses = returning
                        && returning.package.movement.poses || [];
                    if (!actor || actor.actorType !== 'operator'
                            || !point
                            || connection.motionPackageIds.length !== 2
                            || !outboundPoses.length || !returnPoses.length
                            || !equalPoint(outboundPoses.at(-1), point.position)
                            || !equalPoint(returnPoses[0], point.position)
                            || !equalPoint(outboundPoses[0], returnPoses.at(-1))
                            || !equalPoint(
                                connection.centerline[0],
                                connection.centerline.at(-1)
                            )) {
                        connectionFailures.push(connection.connectionId);
                    }
                });
                const handoffFailures = [];
                lean.materialHandoffs.forEach(handoff => {
                    const fromConnection = connections.get(
                        handoff.fromConnectionId
                    );
                    const toConnection = connections.get(handoff.toConnectionId);
                    const fromPoint = fifo.get(handoff.fromPointId);
                    const toPoint = fifo.get(handoff.toPointId);
                    if (!fromConnection || !toConnection
                            || handoff.fromActorId === handoff.toActorId
                            || fromConnection.actorId !== handoff.fromActorId
                            || toConnection.actorId !== handoff.toActorId
                            || !fromPoint || !toPoint
                            || !equalPoint(
                                handoff.centerline[0],
                                fromPoint.position
                            )
                            || !equalPoint(
                                handoff.centerline.at(-1),
                                toPoint.position
                            )) {
                        handoffFailures.push(handoff.handoffId);
                    }
                });
                const operatorActors = scenario.actors.filter(
                    actor => actor.actorType === 'operator'
                );
                const layoutOperatorIds = new Set(
                    layout.placements
                        .filter(placement => placement.assetId === 'asset-operator')
                        .map(placement => placement.placementId)
                );
                const actorPlacementIds = scenario.actors.map(
                    actor => actor.placementId
                );
                const sourceCards = new Set(
                    Array.from(document.querySelectorAll('[data-placement-id]'))
                        .map(element => element.getAttribute('data-placement-id'))
                );
                const movingMarkers = Array.from(document.querySelectorAll(
                    '[data-activity-borrowed-placement="true"]'
                ));
                const activityState = workspace.threeAdapter.activity.getState();
                return {
                    placementCount: layout.placements.length,
                    availableExistingOperatorCount: layoutOperatorIds.size,
                    usedExistingOperatorCount: operatorActors.length,
                    operatorActorsAreExisting: operatorActors.every(
                        actor => layoutOperatorIds.has(actor.placementId)
                    ),
                    uniqueActorPlacementIds:
                        new Set(actorPlacementIds).size === actorPlacementIds.length,
                    duplicatePlanSourceCount: actorPlacementIds.filter(
                        placementId => sourceCards.has(placementId)
                    ).length,
                    movingMarkerCount: movingMarkers.length,
                    borrowedPlacementCount: activityState.borrowedPlacementCount,
                    duplicateVisiblePlacementIds:
                        activityState.duplicateVisiblePlacementIds,
                    connectionCount: lean.pedestrianConnections.length,
                    handoffCount: lean.materialHandoffs.length,
                    connectionFailures,
                    handoffFailures,
                };
            }"""
        )
        proximity_audit = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                const workspace = app.workspace;
                const activity = workspace.threeAdapter.activity;
                const layout = app.session.getState().layout;
                const presentation = workspace.activityPresentation;
                const movingIds = new Set(
                    presentation.scenario.actors.map(actor => actor.placementId)
                );
                const stationaryOperators = layout.placements
                    .filter(placement => placement.assetId === 'asset-operator'
                        && !movingIds.has(placement.placementId))
                    .map(placement => ({
                        placementId: placement.placementId,
                        x: Number(placement.transform.position.x),
                        z: Number(placement.transform.position.z),
                    }));
                let activePair = null;
                let activeToStationary = null;
                let maximumOrientationErrorRadians = 0;
                let orientationFailure = null;
                const normalized = value => Math.atan2(
                    Math.sin(value),
                    Math.cos(value)
                );
                const visualOffset = axis => ({
                    '+X': 0,
                    '-X': Math.PI,
                    '+Z': Math.PI / 2,
                    '-Z': -Math.PI / 2,
                })[axis];
                const duration = activity.getState().durationSeconds;
                activity.pause();
                for (let seconds = 0; seconds <= duration; seconds += 0.5) {
                    activity.seek(seconds);
                    await new Promise(resolve => requestAnimationFrame(resolve));
                    const operators = activity.getState().actors.filter(
                        actor => actor.actorType === 'operator'
                            && actor.visible && actor.pose
                    );
                    operators.forEach(operator => {
                        const expected = normalized(
                            visualOffset(operator.visualForwardAxis)
                                - operator.pose.heading
                        );
                        const error = Math.abs(normalized(
                            operator.visualYawRadians - expected
                        ));
                        if (error > maximumOrientationErrorRadians) {
                            maximumOrientationErrorRadians = error;
                            orientationFailure = {
                                seconds,
                                actor: operator.label,
                                expectedYawRadians: expected,
                                actualYawRadians: operator.visualYawRadians,
                                errorRadians: error,
                            };
                        }
                    });
                    for (let left = 0; left < operators.length; left += 1) {
                        for (let right = left + 1;
                                right < operators.length; right += 1) {
                            const distance = Math.hypot(
                                operators[left].pose.x - operators[right].pose.x,
                                operators[left].pose.z - operators[right].pose.z
                            );
                            if (!activePair || distance < activePair.distanceMeters) {
                                activePair = {
                                    seconds,
                                    distanceMeters: distance,
                                    left: operators[left].label,
                                    right: operators[right].label,
                                };
                            }
                        }
                        stationaryOperators.forEach(stationary => {
                            const distance = Math.hypot(
                                operators[left].pose.x - stationary.x,
                                operators[left].pose.z - stationary.z
                            );
                            if (!activeToStationary
                                    || distance
                                        < activeToStationary.distanceMeters) {
                                activeToStationary = {
                                    seconds,
                                    distanceMeters: distance,
                                    moving: operators[left].label,
                                    stationaryPlacementId: stationary.placementId,
                                };
                            }
                        });
                    }
                }
                activity.seek(0);
                await new Promise(resolve => requestAnimationFrame(resolve));
                return {
                    sampleStepSeconds: 0.5,
                    durationSeconds: duration,
                    stationaryOperatorCount: stationaryOperators.length,
                    closestMovingPair: activePair,
                    closestMovingToStationary: activeToStationary,
                    maximumOrientationErrorRadians,
                    orientationFailure,
                };
            }"""
        )
        page.evaluate(
            """() => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                workspace._setViewMode('plan');
                workspace.layerVisibility.cells = false;
                workspace.layerVisibility.zones = false;
                workspace._applyLayerVisibility();
                workspace.threeAdapter.activity.pause();
                workspace.threeAdapter.activity.seek(74);
                const client = workspace.topAdapter.worldToClient({
                    x: 132,
                    z: 41,
                });
                workspace.topAdapter.zoomAt(client, 2.45);
            }"""
        )
        page.wait_for_timeout(900)
        plan_path = output / "01-plan-lean-motion-paths.png"
        page.screenshot(path=str(plan_path))
        screenshots.append(plan_path)
        plan_visible = page.evaluate(
            """() => ({
                operators: document.querySelectorAll(
                    '[data-lean-motion-kind="operator_path"]'
                ).length,
                handoffs: document.querySelectorAll(
                    '[data-lean-motion-kind="material_handoff"]'
                ).length,
                connections: document.querySelectorAll(
                    '[data-lean-motion-kind="pedestrian_connection"]'
                ).length,
                gates: document.querySelectorAll(
                    '[data-lean-motion-kind="assistance_gate"]'
                ).length,
                fifo: document.querySelectorAll(
                    '[data-lean-motion-kind="fifo_point"]'
                ).length,
                checkbox: document.querySelector(
                    '[data-activity-paths]'
                ).checked,
            })"""
        )
        page.locator("[data-activity-paths]").uncheck()
        page.wait_for_timeout(500)
        plan_hidden = page.evaluate(
            """() => ({
                operators: document.querySelectorAll(
                    '[data-lean-motion-kind="operator_path"]'
                ).length,
                handoffs: document.querySelectorAll(
                    '[data-lean-motion-kind="material_handoff"]'
                ).length,
                connections: document.querySelectorAll(
                    '[data-lean-motion-kind="pedestrian_connection"]'
                ).length,
                gates: document.querySelectorAll(
                    '[data-lean-motion-kind="assistance_gate"]'
                ).length,
                fifo: document.querySelectorAll(
                    '[data-lean-motion-kind="fifo_point"]'
                ).length,
                activity: _trainFacilityLayoutAuthoringApp.workspace
                    .threeAdapter.activity.getState(),
            })"""
        )
        hidden_path = output / "02-plan-paths-hidden.png"
        page.screenshot(path=str(hidden_path))
        screenshots.append(hidden_path)
        page.locator("[data-activity-paths]").check()
        page.evaluate(
            """() => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                workspace.layerVisibility.cells = true;
                workspace.layerVisibility.zones = true;
                workspace._applyLayerVisibility();
                workspace._setViewMode('3d');
            }"""
        )
        page.wait_for_selector(
            "#ip-flw-three-view:not([hidden]) canvas",
            state="visible",
            timeout=120_000,
        )
        page.wait_for_function(
            """() => _trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.getDiagnostics().pendingLoads === 0""",
            timeout=240_000,
        )
        page.wait_for_timeout(700)
        page.evaluate(
            """() => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                const presentation = workspace.activityPresentation;
                const actor = presentation.scenario.actors.find(item =>
                    item.label === 'Operator - Assembly Cell A02'
                );
                const connection = presentation.scenario.leanMotion
                    .pedestrianConnections.find(item =>
                        item.actorId === actor.actorId
                );
                const targetPackageId = connection.motionPackageIds[0];
                let evidenceSeconds = Number(actor.startOffsetSeconds || 0);
                for (const packageId of actor.cycleMotionPackageIds) {
                    const movement = presentation.actorPayloads[packageId]
                        .package.movement;
                    const duration = Number(
                        movement.plannerDurationEstimateSeconds || 0
                    );
                    if (packageId === targetPackageId) {
                        evidenceSeconds += duration / 2;
                        break;
                    }
                    evidenceSeconds += duration + Number(
                        actor.endpointTurnSeconds || 0
                    );
                }
                window.__leanMotionEvidenceTarget = {
                    actorId: actor.actorId,
                    label: actor.label,
                    seconds: evidenceSeconds,
                };
                workspace.threeAdapter.activity.seek(evidenceSeconds);
                workspace.threeAdapter.activity.selectActor(actor.actorId);
                workspace.threeAdapter.activity.focusActor(actor.actorId);
                workspace.threeAdapter.zoomBy(0.42);
            }"""
        )
        page.wait_for_timeout(1100)
        three_path = output / "03-3d-existing-operator-fifo-access.png"
        page.screenshot(path=str(three_path))
        screenshots.append(three_path)
        state_before = page.evaluate(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.workspace
                    .threeAdapter.activity.getState();
                return {
                    pathsVisible: state.pathsVisible,
                    leanMotionCounts: state.leanMotionCounts,
                    actor: state.actors.find(item =>
                        item.actorId === window.__leanMotionEvidenceTarget.actorId
                    ),
                };
            }"""
        )
        page.locator("[data-activity-paths]").uncheck()
        page.wait_for_timeout(450)
        state_hidden = page.evaluate(
            """() => _trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.activity.getState()"""
        )
        three_hidden_path = output / "04-3d-paths-hidden.png"
        page.screenshot(path=str(three_hidden_path))
        screenshots.append(three_hidden_path)
        page.locator("[data-activity-paths]").check()
        page.evaluate(
            """() => {
                const activity = _trainFacilityLayoutAuthoringApp.workspace
                    .threeAdapter.activity;
                activity.seek(window.__leanMotionEvidenceTarget.seconds + 4);
            }"""
        )
        page.wait_for_timeout(400)
        state_after = page.evaluate(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.workspace
                    .threeAdapter.activity.getState();
                return state.actors.find(item =>
                    item.actorId === window.__leanMotionEvidenceTarget.actorId
                );
            }"""
        )
        session = page.evaluate(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return {
                    dirty: state.dirty,
                    operationCount: state.operations.length,
                    baseRevision: state.baseRevision,
                };
            }"""
        )
        browser.close()

    after_hash = _sha256(LAYOUT)
    moved = (
        state_before["actor"]["pose"] != state_after["pose"]
        and state_before["actor"]["visualYawRadians"] is not None
        and state_after["visualYawRadians"] is not None
    )
    report = {
        "summary": summary,
        "sage": {
            "throughChat": bool(args.through_chat),
            "prompt": PROMPT if args.through_chat else None,
            "responseText": response_text,
            "streamStatuses": stream_statuses,
            "facilityContextProbe": agent_context_probe,
        },
        "topologyAudit": topology_audit,
        "proximityAudit": proximity_audit,
        "planVisible": plan_visible,
        "planHidden": {
            "operators": plan_hidden["operators"],
            "handoffs": plan_hidden["handoffs"],
            "connections": plan_hidden["connections"],
            "gates": plan_hidden["gates"],
            "fifo": plan_hidden["fifo"],
            "pathsVisible": plan_hidden["activity"]["pathsVisible"],
        },
        "three": {
            "before": state_before,
            "hiddenPathsVisible": state_hidden["pathsVisible"],
            "afterActor": state_after,
            "operatorMoved": moved,
        },
        "layout": {
            "beforeSha256": before_hash,
            "afterSha256": after_hash,
            "unchanged": before_hash == after_hash,
            **session,
        },
        "screenshots": [_image_record(path) for path in screenshots],
        "browserErrors": {
            "console": console_errors,
            "page": page_errors,
            "failedRequests": failed_requests,
            "server5xx": server_errors,
        },
    }
    report["passed"] = all([
        plan_visible == {
            "operators": 12,
            "handoffs": 7,
            "connections": 12,
            "gates": 3,
            "fifo": 12,
            "checkbox": True,
        },
        report["planHidden"] == {
            "operators": 0,
            "handoffs": 0,
            "connections": 0,
            "gates": 0,
            "fifo": 0,
            "pathsVisible": False,
        },
        state_before["pathsVisible"] is True,
        state_before["leanMotionCounts"]["renderedObjects"] == 46,
        topology_audit["placementCount"] == 827,
        topology_audit["availableExistingOperatorCount"] == 20,
        topology_audit["usedExistingOperatorCount"] == 12,
        topology_audit["operatorActorsAreExisting"],
        topology_audit["uniqueActorPlacementIds"],
        topology_audit["duplicatePlanSourceCount"] == 0,
        topology_audit["movingMarkerCount"] == 16,
        topology_audit["borrowedPlacementCount"] == 16,
        not topology_audit["duplicateVisiblePlacementIds"],
        topology_audit["connectionCount"] == 12,
        topology_audit["handoffCount"] == 7,
        not topology_audit["connectionFailures"],
        not topology_audit["handoffFailures"],
        proximity_audit["closestMovingPair"]["distanceMeters"] > 0.81,
        proximity_audit["closestMovingToStationary"]["distanceMeters"] > 0.81,
        proximity_audit["maximumOrientationErrorRadians"] < 1e-6,
        state_hidden["pathsVisible"] is False,
        moved,
        report["layout"]["unchanged"],
        not report["layout"]["dirty"],
        report["layout"]["operationCount"] == 0,
        not args.through_chat or stream_statuses == [200],
        not args.through_chat
        or "prototype factory activity" in response_text.casefold(),
        not any(report["browserErrors"].values()),
        all(item["nonblank"] for item in report["screenshots"]),
    ])
    report_path = output / "facility-lean-activity-browser-evidence.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8153/")
    parser.add_argument(
        "--output",
        default=str(ROOT / ".runtime" / "facility-motion" / "lean-activity-evidence"),
    )
    parser.add_argument(
        "--through-chat",
        action="store_true",
        help="Send the acceptance prompt through Sage's visible chat surface.",
    )
    args = parser.parse_args()
    report = capture(args)
    print(json.dumps({
        "passed": report["passed"],
        "actors": report["summary"].get("actorCount"),
        "planVisible": report["planVisible"],
        "topologyAudit": report["topologyAudit"],
        "proximityAudit": report["proximityAudit"],
        "operatorMoved": report["three"]["operatorMoved"],
        "layoutUnchanged": report["layout"]["unchanged"],
        "screenshots": [item["path"] for item in report["screenshots"]],
    }, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
