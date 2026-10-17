"""Capture end-to-end browser evidence for multi-actor Facility playback."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAYOUT = (
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
REFERENCE_LAYOUT = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
DEFAULT_OUTPUT = ROOT / ".runtime" / "facility-motion" / "activity-evidence"
DEFAULT_EDGE = Path(
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)
PROMPT = (
    "Play a prototype factory activity view with vehicles on authored material "
    "lanes and operators on authored pedestrian routes. Keep machines without "
    "revision-bound kinematic evidence stationary. Use up to 20 actors."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _image_evidence(path: Path) -> dict[str, Any]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        sampled = image.resize((128, 72))
        extrema = image.getextrema()
        colors = sampled.getcolors(128 * 72) or []
        return {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(path),
            "byteLength": path.stat().st_size,
            "width": image.width,
            "height": image.height,
            "nonblank": any(low != high for low, high in extrema),
            "sampledColorCount": len(colors),
        }


def _changed_pixel_ratio(left: Path, right: Path) -> float:
    with Image.open(left) as left_source, Image.open(right) as right_source:
        left_image = left_source.convert("RGB")
        right_image = right_source.convert("RGB")
        if left_image.size != right_image.size:
            return 1.0
        difference = ImageChops.difference(left_image, right_image)
        changed = sum(
            1
            for pixel in difference.getdata()
            if pixel != (0, 0, 0)
        )
        return changed / max(1, left_image.width * left_image.height)


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
            const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
            if (workspace.controller
                    && typeof workspace.controller.ready === 'function') {
                await workspace.controller.ready();
            }
        }"""
    )


def _snapshot(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const app = window._trainFacilityLayoutAuthoringApp;
            const workspace = app.workspace;
            const session = app.session.getState();
            const activity = workspace.threeAdapter.activity.getState();
            const plan = workspace.topAdapter.getDiagnostics();
            const three = workspace.threeAdapter.getDiagnostics();
            const scenario = workspace.activityPresentation
                && workspace.activityPresentation.scenario;
            const actorPayloads = workspace.activityPresentation
                && workspace.activityPresentation.actorPayloads || {};
            const actors = scenario && Array.isArray(scenario.actors)
                ? scenario.actors : [];
            const markers = Array.from(document.querySelectorAll(
                '[data-activity-actor-id]'
            )).map((marker) => ({
                actorId: marker.getAttribute('data-activity-actor-id'),
                actorType: marker.getAttribute('data-activity-actor-type'),
                display: marker.getAttribute('display'),
                distanceMeters: Number(
                    marker.getAttribute('data-activity-distance-meters') || 0
                ),
                headingRadians: Number(
                    marker.getAttribute('data-activity-heading-radians') || 0
                ),
                points: marker.getAttribute('points') || '',
            }));
            const actorBindings = actors.map((actor) => {
                const payload = actorPayloads[actor.motionPackageId] || {};
                const movement = payload.package && payload.package.movement || {};
                const returnPayload = actor.returnMotionPackageId
                    ? actorPayloads[actor.returnMotionPackageId] || {} : {};
                const returnMovement = returnPayload.package
                    && returnPayload.package.movement || {};
                const endTransferPayload = actor.endTransferMotionPackageId
                    ? actorPayloads[actor.endTransferMotionPackageId] || {} : {};
                const endTransferMovement = endTransferPayload.package
                    && endTransferPayload.package.movement || {};
                const startTransferPayload = actor.startTransferMotionPackageId
                    ? actorPayloads[actor.startTransferMotionPackageId] || {} : {};
                const startTransferMovement = startTransferPayload.package
                    && startTransferPayload.package.movement || {};
                const group = (three.representationGroups || []).find(
                    (candidate) => candidate.assetId
                        === actor.assetDefinitionRef.assetId
                        && candidate.assetDefinitionRevision === actor.assetDefinitionRef.assetDefinitionRevision
                );
                const visual = activity.actors.find(item => item.actorId === actor.actorId);
                return {
                    actorId: actor.actorId,
                    actorType: actor.actorType,
                    label: actor.label,
                    placementId: actor.placementId,
                    routeId: actor.routeId,
                    assetDefinitionRef: actor.assetDefinitionRef,
                    loopMode: actor.loopMode,
                    endpointTurnSeconds: actor.endpointTurnSeconds,
                    motionPackageId: actor.motionPackageId,
                    returnMotionPackageId: actor.returnMotionPackageId,
                    endTransferMotionPackageId: actor.endTransferMotionPackageId,
                    startTransferMotionPackageId: actor.startTransferMotionPackageId,
                    visualAlignment: actor.visualAlignment,
                    visualSource: visual && visual.visualSource,
                    exactCatalogVisual: visual && visual.exactCatalogVisual,
                    outcome: movement.outcome || null,
                    laneBinding: movement.laneBinding || null,
                    returnOutcome: returnMovement.outcome || null,
                    returnLaneBinding: returnMovement.laneBinding || null,
                    endTransferOutcome: endTransferMovement.outcome || null,
                    startTransferOutcome: startTransferMovement.outcome || null,
                    prototypeMeshCount: group
                        ? Number(group.prototypeMeshCount || 0) : 0,
                    representation: group ? group.representation : null,
                };
            });
            return {
                layoutId: session.layout.layoutId,
                baseRevision: session.baseRevision,
                dirty: session.dirty,
                operationCount: session.operations.length,
                zoneCount: session.layout.zones.length,
                routeCount: session.layout.routes.length,
                placementCount: session.layout.placements.length,
                markingCount: session.layout.floorMarkings.length,
                viewMode: workspace.viewMode,
                activity,
                planActivity: plan.activity,
                markers,
                actorBindings,
                placementTransformAudit: three.placementTransformAudit,
                walkthrough: three.navigation.walkthrough,
                drone: three.navigation.drone,
                pendingLoads: three.pendingLoads,
                panel: {
                    visible: workspace.motionPanel
                        ? !workspace.motionPanel.hidden : false,
                    mode: workspace.motionPanel
                        ? workspace.motionPanel.getAttribute('data-mode') : null,
                    text: workspace.motionPanel
                        ? workspace.motionPanel.innerText : '',
                },
                layoutBytes: JSON.stringify(session.layout),
            };
        }"""
    )


def _seek(page: Any, seconds: float, view: str) -> dict[str, Any]:
    page.evaluate(
        """([seconds, view]) => {
            const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
            workspace._setViewMode(view);
            const activity = workspace.threeAdapter.activity;
            activity.pause();
            activity.seek(seconds);
        }""",
        [seconds, view],
    )
    page.wait_for_timeout(850)
    return _snapshot(page)


def _capture(page: Any, path: Path, screenshots: list[Path]) -> None:
    page.screenshot(path=str(path), full_page=False)
    screenshots.append(path)


def _focus_wide(page: Any, actor_id: str, zoom_factor: float = 0.3) -> None:
    page.evaluate(
        """([actorId, zoomFactor]) => {
            const adapter = window._trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter;
            adapter.activity.selectActor(actorId);
            adapter.activity.focusActor(actorId);
            adapter.zoomBy(zoomFactor);
        }""",
        [actor_id, zoom_factor],
    )
    page.wait_for_timeout(500)


def capture(args: argparse.Namespace) -> dict[str, Any]:
    layout_path = Path(args.layout).resolve()
    reference_path = Path(args.reference).resolve()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    layout_hash_before = _sha256(layout_path)
    reference_hash_before = _sha256(reference_path)
    archived_layout = json.loads(reference_path.read_text(encoding="utf-8"))
    screenshots: list[Path] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    server_errors: list[str] = []
    stream_statuses: list[int] = []

    with sync_playwright() as playwright:
        launch_options: dict[str, Any] = {
            "headless": True,
            "args": [
                "--enable-precise-memory-info",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
            ],
        }
        if DEFAULT_EDGE.is_file():
            launch_options["executable_path"] = str(DEFAULT_EDGE)
        browser = playwright.chromium.launch(**launch_options)
        browser_version = browser.version
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            reduced_motion="no-preference",
        )
        context.add_init_script(
            "localStorage.setItem('inspectorpro.theme', 'light');"
        )
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text)
                if message.type == "error"
                else None
            ),
        )
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
            """() => window._trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.getDiagnostics().pendingLoads === 0""",
            timeout=240_000,
        )
        initial = _snapshot(page)
        browser_layout = json.loads(initial["layoutBytes"])
        browser_layout["layoutId"] = archived_layout["layoutId"]
        matches_archive = browser_layout == archived_layout
        if not matches_archive:
            raise RuntimeError(
                "The browser layout differs from the archived manual layout."
            )

        page.evaluate("() => window._selectAgent('deviation-analyst')")
        page.wait_for_selector("#agentInput", state="visible", timeout=30_000)
        page.locator("#agentInput").fill(PROMPT)
        page.locator("#agentSendBtn").click()
        page.wait_for_function(
            """() => {
                const app = window._trainFacilityLayoutAuthoringApp;
                const state = app.workspace.threeAdapter.activity.getState();
                const pending = document.querySelectorAll(
                    '#agentMessages .agent-stream-pending'
                ).length;
                return pending === 0 && state.loaded && state.actors.length >= 4;
            }""",
            timeout=360_000,
        )
        page.wait_for_function(
            """() => window._trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.getDiagnostics().pendingLoads === 0""",
            timeout=240_000,
        )
        page.wait_for_timeout(1200)
        response_text = page.locator("#agentMessages").inner_text()

        plan_35 = _seek(page, 35, "plan")
        path = output_dir / "01-sage-prompt-and-plan-activity.png"
        _capture(page, path, screenshots)

        page.evaluate(
            """() => {
                const panel = document.getElementById('agentPanel');
                if (panel && panel.classList.contains('open')
                        && typeof window._toggleAgentPanel === 'function') {
                    window._toggleAgentPanel();
                }
            }"""
        )
        page.wait_for_timeout(500)
        plan_35_clean = _seek(page, 35, "plan")
        path = output_dir / "02-plan-all-actors-35-seconds.png"
        _capture(page, path, screenshots)

        plan_115 = _seek(page, 115, "plan")
        path = output_dir / "03-plan-all-actors-115-seconds.png"
        _capture(page, path, screenshots)

        control_probe = page.evaluate(
            """async () => {
                const activity = window._trainFacilityLayoutAuthoringApp
                    .workspace.threeAdapter.activity;
                const before = activity.getState();
                activity.setActorTypeVisible('operator', false);
                await new Promise((resolve) => setTimeout(resolve, 300));
                const hidden = activity.getState();
                activity.setActorTypeVisible('operator', true);
                const memberships = new Map();
                before.actors.forEach((actor) => {
                    actor.departmentZoneIds.forEach((zoneId) => {
                        memberships.set(
                            zoneId,
                            (memberships.get(zoneId) || 0) + 1
                        );
                    });
                });
                const selectedZone = Array.from(memberships.entries())
                    .sort((left, right) => left[1] - right[1]
                        || left[0].localeCompare(right[0]))[0][0];
                activity.setDepartmentFilter(selectedZone);
                await new Promise((resolve) => setTimeout(resolve, 300));
                const filtered = activity.getState();
                activity.setDepartmentFilter(null);
                await new Promise((resolve) => setTimeout(resolve, 300));
                const restored = activity.getState();
                return { before, hidden, selectedZone, filtered, restored };
            }"""
        )

        three_overview = _seek(page, 75, "3d")
        page.evaluate(
            """async () => {
                const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                if (workspace.controller && workspace.controller.ready) {
                    await workspace.controller.ready();
                }
                workspace.threeAdapter.fitLayout();
            }"""
        )
        page.wait_for_timeout(1800)
        three_overview = _snapshot(page)
        path = output_dir / "04-3d-factory-activity-overview.png"
        _capture(page, path, screenshots)

        focus_result = page.evaluate(
            """() => {
                const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                const scenario = workspace.activityPresentation.scenario;
                const actor = scenario.actors.find((candidate) =>
                    candidate.actorType === 'vehicle'
                    && candidate.loopMode === 'paired_lanes'
                );
                const activity = workspace.threeAdapter.activity;
                activity.selectActor(actor.actorId);
                return {
                    actorId: actor.actorId,
                    placementId: actor.placementId,
                    assetId: actor.assetDefinitionRef.assetId,
                    focused: activity.focusActor(actor.actorId),
                };
            }"""
        )
        page.wait_for_timeout(1800)
        primary_focus = _snapshot(page)
        path = output_dir / "05-3d-primary-forklift-on-marked-lane.png"
        _capture(page, path, screenshots)

        secondary_focus = page.evaluate(
            """(primaryActorId) => {
                const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                const scenario = workspace.activityPresentation.scenario;
                const actor = scenario.actors.find((candidate) =>
                    candidate.actorType === 'vehicle'
                    && candidate.loopMode === 'paired_lanes'
                    && candidate.actorId !== primaryActorId
                );
                const activity = workspace.threeAdapter.activity;
                activity.selectActor(actor.actorId);
                return {
                    actorId: actor.actorId,
                    assetId: actor.assetDefinitionRef.assetId,
                    focused: activity.focusActor(actor.actorId),
                };
            }""",
            focus_result["actorId"],
        )
        page.wait_for_timeout(1600)
        path = output_dir / "06-3d-secondary-forklift-exact-glb.png"
        _capture(page, path, screenshots)

        operator_focus = page.evaluate(
            """() => {
                const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                const actor = workspace.activityPresentation.scenario.actors
                    .find((candidate) => candidate.actorType === 'operator');
                const activity = workspace.threeAdapter.activity;
                activity.selectActor(actor.actorId);
                return {
                    actorId: actor.actorId,
                    assetId: actor.assetDefinitionRef.assetId,
                    focused: activity.focusActor(actor.actorId),
                };
            }"""
        )
        page.wait_for_timeout(1600)
        path = output_dir / "07-3d-operator-exact-glb.png"
        _capture(page, path, screenshots)

        loop_definition = page.evaluate(
            """() => {
                const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                const scenario = workspace.activityPresentation.scenario;
                const actor = scenario.actors.find((candidate) =>
                    candidate.actorType === 'vehicle'
                    && candidate.loopMode === 'paired_lanes'
                );
                const payloads = workspace.activityPresentation.actorPayloads;
                const outbound = payloads[
                    actor.motionPackageId
                ];
                const endTransfer = payloads[
                    actor.endTransferMotionPackageId
                ];
                const returnLane = payloads[
                    actor.returnMotionPackageId
                ];
                const startTransfer = payloads[
                    actor.startTransferMotionPackageId
                ];
                const duration = (payload) => Number(
                    payload.package.movement.plannerDurationEstimateSeconds
                );
                return {
                    actorId: actor.actorId,
                    assetId: actor.assetDefinitionRef.assetId,
                    outboundPackageId: actor.motionPackageId,
                    endTransferPackageId: actor.endTransferMotionPackageId,
                    returnPackageId: actor.returnMotionPackageId,
                    startTransferPackageId: actor.startTransferMotionPackageId,
                    outboundDuration: duration(outbound),
                    endTransferDuration: duration(endTransfer),
                    returnDuration: duration(returnLane),
                    startTransferDuration: duration(startTransfer),
                };
            }"""
        )
        loop_outbound = _seek(
            page,
            max(0.0, loop_definition["outboundDuration"] - 0.25),
            "3d",
        )
        _focus_wide(page, loop_definition["actorId"])
        page.wait_for_timeout(900)
        loop_outbound = _snapshot(page)
        path = output_dir / "08-3d-forklift-outbound-end.png"
        _capture(page, path, screenshots)

        loop_turn = _seek(
            page,
            loop_definition["outboundDuration"]
            + loop_definition["endTransferDuration"] / 2,
            "3d",
        )
        _focus_wide(page, loop_definition["actorId"])
        page.wait_for_timeout(650)
        path = output_dir / "09-3d-forklift-transfer-to-opposite-lane.png"
        _capture(page, path, screenshots)

        loop_return = _seek(
            page,
            loop_definition["outboundDuration"]
            + loop_definition["endTransferDuration"]
            + min(1.0, loop_definition["returnDuration"] / 2),
            "3d",
        )
        _focus_wide(page, loop_definition["actorId"])
        page.wait_for_timeout(650)
        path = output_dir / "10-3d-forklift-opposite-lane-return.png"
        _capture(page, path, screenshots)

        loop_start_transfer = _seek(
            page,
            loop_definition["outboundDuration"]
            + loop_definition["endTransferDuration"]
            + loop_definition["returnDuration"]
            + loop_definition["startTransferDuration"] / 2,
            "3d",
        )
        _focus_wide(page, loop_definition["actorId"])
        page.wait_for_timeout(650)
        path = output_dir / "11-3d-forklift-transfer-back-to-outbound-lane.png"
        _capture(page, path, screenshots)

        loop_next_outbound = _seek(page, 0.5, "3d")

        page.locator('[data-three-command="drone"]').click()
        page.wait_for_timeout(1200)
        drone = _snapshot(page)
        path = output_dir / "12-3d-drone-with-activity.png"
        _capture(page, path, screenshots)
        page.evaluate(
            """() => window._trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.exitDrone('activity_acceptance')"""
        )
        page.wait_for_function(
            """() => !window._trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.getDroneState().active"""
        )
        page.locator('[data-three-command="walkthrough"]').click()
        page.wait_for_timeout(1200)
        walkthrough = _snapshot(page)
        path = output_dir / "13-3d-walkthrough-with-activity.png"
        _capture(page, path, screenshots)

        final = _snapshot(page)
        browser.close()

    layout_hash_after = _sha256(layout_path)
    reference_hash_after = _sha256(reference_path)
    actors_35 = {
        actor["actorId"]: actor for actor in plan_35_clean["activity"]["actors"]
    }
    actors_115 = {
        actor["actorId"]: actor for actor in plan_115["activity"]["actors"]
    }
    advanced_actor_ids = sorted(
        actor_id
        for actor_id, actor in actors_35.items()
        if actor.get("pose")
        and actors_115.get(actor_id, {}).get("pose")
        and (
            actor["pose"].get("x") != actors_115[actor_id]["pose"].get("x")
            or actor["pose"].get("z")
            != actors_115[actor_id]["pose"].get("z")
        )
    )
    marker_by_id = {
        marker["actorId"]: marker for marker in plan_115["markers"]
    }
    plan_pose_agreement = all(
        marker_by_id.get(actor["actorId"], {}).get("display") == "inline"
        and abs(
            marker_by_id[actor["actorId"]]["distanceMeters"]
            - actor["pose"]["distanceMeters"]
        ) < 1e-6
        and abs(
            marker_by_id[actor["actorId"]]["headingRadians"]
            - actor["pose"]["heading"]
        ) < 1e-6
        for actor in plan_115["activity"]["actors"]
        if actor.get("visible") and actor.get("pose")
    )
    bindings = plan_115["actorBindings"]
    actor_placement_ids = {
        binding["placementId"] for binding in bindings
    }
    baseline_audit = initial["placementTransformAudit"]
    audit = three_overview["placementTransformAudit"]
    baseline_mismatches = set(
        baseline_audit.get("transformMismatchIdsAll")
        or baseline_audit.get("transformMismatchIds")
        or []
    )
    mismatches = set(
        audit.get("transformMismatchIdsAll")
        or audit.get("transformMismatchIds")
        or []
    )
    new_mismatches = mismatches - baseline_mismatches
    stationary_transforms_unchanged = new_mismatches.issubset(
        actor_placement_ids
    )
    type_counts = {
        actor_type: sum(
            actor["actorType"] == actor_type
            for actor in plan_115["activity"]["actors"]
        )
        for actor_type in ("vehicle", "operator", "mobile_equipment")
    }
    paired_binding = next(
        (
            binding
            for binding in bindings
            if binding["actorId"] == loop_definition["actorId"]
        ),
        None,
    )
    route_binding_counts: dict[str, int] = {}
    for binding in bindings:
        route_id = str(binding["routeId"])
        route_binding_counts[route_id] = (
            route_binding_counts.get(route_id, 0) + 1
        )
    primary_route_id = sorted(
        route_binding_counts,
        key=lambda route_id: (-route_binding_counts[route_id], route_id),
    )[0]
    primary_route_bindings = [
        binding for binding in bindings
        if binding["routeId"] == primary_route_id
    ]
    primary_lane_directions = {
        binding.get("laneBinding", {}).get("travelDirection")
        for binding in primary_route_bindings
    }
    primary_lane_mean_z = []
    for binding in primary_route_bindings:
        centerline = binding.get("laneBinding", {}).get("laneCenterline", [])
        if centerline:
            primary_lane_mean_z.append(
                sum(float(point["z"]) for point in centerline)
                / len(centerline)
            )
    primary_loop_checks = []
    for binding in primary_route_bindings:
        outbound_lane = binding.get("laneBinding") or {}
        return_lane = binding.get("returnLaneBinding") or {}
        outbound_centerline = outbound_lane.get("laneCenterline") or []
        return_centerline = return_lane.get("laneCenterline") or []
        outbound_mean_z = (
            sum(float(point["z"]) for point in outbound_centerline)
            / len(outbound_centerline)
            if outbound_centerline else None
        )
        return_mean_z = (
            sum(float(point["z"]) for point in return_centerline)
            / len(return_centerline)
            if return_centerline else None
        )
        outbound_markings = set(outbound_lane.get("sourceMarkingIds") or [])
        return_markings = set(return_lane.get("sourceMarkingIds") or [])
        primary_loop_checks.append({
            "actorId": binding["actorId"],
            "loopMode": binding["loopMode"],
            "outboundDirection": outbound_lane.get("travelDirection"),
            "returnDirection": return_lane.get("travelDirection"),
            "outboundMarkingIds": sorted(outbound_markings),
            "returnMarkingIds": sorted(return_markings),
            "markingSetsDisjoint": bool(outbound_markings)
            and bool(return_markings)
            and outbound_markings.isdisjoint(return_markings),
            "laneCenterlineSeparationMeters": (
                abs(outbound_mean_z - return_mean_z)
                if outbound_mean_z is not None and return_mean_z is not None
                else 0.0
            ),
            "outcomes": {
                "outbound": binding.get("outcome"),
                "return": binding.get("returnOutcome"),
                "endTransfer": binding.get("endTransferOutcome"),
                "startTransfer": binding.get("startTransferOutcome"),
            },
        })
    axis_offsets = {
        "+X": 0.0,
        "-X": math.pi,
        "+Z": math.pi / 2,
        "-Z": -math.pi / 2,
    }

    def angle_difference(left: float, right: float) -> float:
        return abs(math.atan2(math.sin(left - right), math.cos(left - right)))

    aligned_actor_ids = []
    for actor in plan_115["activity"]["actors"]:
        if not actor.get("pose") or actor.get("visualYawRadians") is None:
            continue
        expected_yaw = (
            axis_offsets[actor["visualForwardAxis"]]
            - float(actor["pose"]["heading"])
        )
        if angle_difference(
            float(actor["visualYawRadians"]),
            expected_yaw,
        ) < 1e-6:
            aligned_actor_ids.append(actor["actorId"])

    def actor_state(snapshot: dict[str, Any], actor_id: str) -> dict[str, Any]:
        return next(
            actor
            for actor in snapshot["activity"]["actors"]
            if actor["actorId"] == actor_id
        )

    loop_outbound_actor = actor_state(
        loop_outbound,
        loop_definition["actorId"],
    )
    loop_turn_actor = actor_state(loop_turn, loop_definition["actorId"])
    loop_return_actor = actor_state(
        loop_return,
        loop_definition["actorId"],
    )
    loop_start_transfer_actor = actor_state(
        loop_start_transfer,
        loop_definition["actorId"],
    )
    loop_next_outbound_actor = actor_state(
        loop_next_outbound,
        loop_definition["actorId"],
    )
    outbound_return_heading_delta = angle_difference(
        float(loop_outbound_actor["pose"]["heading"]),
        float(loop_return_actor["pose"]["heading"]),
    )
    hidden_operators = [
        actor
        for actor in control_probe["hidden"]["actors"]
        if actor["actorType"] == "operator"
    ]
    filtered_visible = sum(
        bool(actor.get("visible"))
        for actor in control_probe["filtered"]["actors"]
    )
    report = {
        "schemaVersion": 1,
        "acceptanceId": "facility-multi-actor-manual-reference-browser-v1",
        "prompt": PROMPT,
        "url": args.url,
        "browserVersion": browser_version,
        "layout": {
            "layoutId": initial["layoutId"],
            "revision": initial["baseRevision"],
            "zoneCount": initial["zoneCount"],
            "routeCount": initial["routeCount"],
            "placementCount": initial["placementCount"],
            "markingCount": initial["markingCount"],
            "acceptanceHashBefore": layout_hash_before,
            "acceptanceHashAfter": layout_hash_after,
            "referenceHashBefore": reference_hash_before,
            "referenceHashAfter": reference_hash_after,
            "savedFilesByteIdentical": (
                layout_hash_before == layout_hash_after
                and reference_hash_before == reference_hash_after
            ),
            "browserLayoutByteIdentical": (
                initial["layoutBytes"] == final["layoutBytes"]
            ),
            "matchesArchivedManualExceptLayoutId": matches_archive,
            "dirtyAfter": final["dirty"],
            "operationCountAfter": final["operationCount"],
        },
        "sage": {
            "streamStatuses": stream_statuses,
            "responseText": response_text,
            "activityLoadedFromPrompt": plan_35["activity"]["loaded"],
        },
        "activity": {
            "scenarioId": plan_115["activity"]["scenarioId"],
            "actorCount": len(plan_115["activity"]["actors"]),
            "actorTypeCounts": type_counts,
            "advancedActorIds": advanced_actor_ids,
            "planAndThreeSharedPose": plan_pose_agreement,
            "planVisibleMarkerCount": plan_115["planActivity"][
                "visibleMarkerCount"
            ],
            "stationaryEvidence": plan_115["activity"][
                "stationaryEvidence"
            ],
            "stationaryTransformsUnchanged": stationary_transforms_unchanged,
            "baselineTransformMismatchIds": sorted(baseline_mismatches),
            "transformMismatchIds": sorted(mismatches),
            "newTransformMismatchIds": sorted(new_mismatches),
            "unavailableActivity": plan_115["activity"][
                "unavailableActivity"
            ],
            "bindings": bindings,
            "allActorsUseDeclaredVisuals": all(
                (binding["representation"] in {"overview", "detail"}
                 and binding["exactCatalogVisual"] is True)
                or (binding["actorType"] == "operator"
                    and binding["assetDefinitionRef"] == {
                        "assetId": "asset-operator",
                        "assetDefinitionRevision": "773d3761fb0796587de7a21ccb8b368f4334c71f73c06682b84472d69d4b5757",
                    }
                    and binding["representation"] == "operator-avatar"
                    and binding["visualSource"] == "animated-operator-avatar"
                    and binding["exactCatalogVisual"] is False)
                for binding in bindings
            ),
            "visualHeadingAlignment": {
                "alignedActorIds": sorted(aligned_actor_ids),
                "allActorsFaceTravel": len(aligned_actor_ids)
                == len(plan_115["activity"]["actors"]),
            },
            "primaryBoulevard": {
                "routeId": primary_route_id,
                "actorIds": [
                    binding["actorId"]
                    for binding in primary_route_bindings
                ],
                "allActorsAreVehicles": bool(primary_route_bindings)
                and all(
                    binding["actorType"] == "vehicle"
                    for binding in primary_route_bindings
                ),
                "hasMobileEquipment": any(
                    binding["actorType"] == "mobile_equipment"
                    for binding in primary_route_bindings
                ),
                "laneDirections": sorted(primary_lane_directions),
                "allLanesBoundToDirectionMarkings": all(
                    binding.get("laneBinding", {}).get("status")
                    == "direction_markings"
                    and bool(
                        binding.get("laneBinding", {}).get(
                            "sourceMarkingIds"
                        )
                    )
                    for binding in primary_route_bindings
                ),
                "laneCenterlineSeparationMeters": (
                    abs(primary_lane_mean_z[0] - primary_lane_mean_z[1])
                    if len(primary_lane_mean_z) == 2 else 0
                ),
                "pairedLaneLoops": primary_loop_checks,
            },
            "pairedLaneLoop": {
                "actorId": loop_definition["actorId"],
                "assetId": loop_definition["assetId"],
                "outboundPhase": loop_outbound_actor["playbackPhase"],
                "endTransferPhase": loop_turn_actor["playbackPhase"],
                "returnPhase": loop_return_actor["playbackPhase"],
                "startTransferPhase": loop_start_transfer_actor[
                    "playbackPhase"
                ],
                "nextCyclePhase": loop_next_outbound_actor["playbackPhase"],
                "outboundPackageId": loop_outbound_actor[
                    "currentMotionPackageId"
                ],
                "endTransferPackageId": loop_turn_actor[
                    "currentMotionPackageId"
                ],
                "returnPackageId": loop_return_actor[
                    "currentMotionPackageId"
                ],
                "startTransferPackageId": loop_start_transfer_actor[
                    "currentMotionPackageId"
                ],
                "nextCyclePackageId": loop_next_outbound_actor[
                    "currentMotionPackageId"
                ],
                "outboundReturnHeadingDeltaRadians": (
                    outbound_return_heading_delta
                ),
                "binding": paired_binding,
            },
            "primaryForklift": {
                "focus": focus_result,
                "binding": paired_binding,
                "selectedActorId": primary_focus["activity"][
                    "selectedActorId"
                ],
            },
            "secondaryForkliftFocus": secondary_focus,
            "operatorFocus": operator_focus,
            "controls": {
                "operatorHidden": bool(hidden_operators)
                and all(not actor["visible"] for actor in hidden_operators),
                "departmentFilterZoneId": control_probe["selectedZone"],
                "departmentFilterVisibleCount": filtered_visible,
                "departmentFilterReducedActors": (
                    0 < filtered_visible
                    < len(control_probe["filtered"]["actors"])
                ),
                "restoredActorCount": sum(
                    bool(actor.get("visible"))
                    for actor in control_probe["restored"]["actors"]
                ),
            },
            "immersiveModes": {
                "droneActive": drone["drone"]["active"],
                "droneActivityLoaded": drone["activity"]["loaded"],
                "walkthroughActive": walkthrough["walkthrough"]["active"],
                "walkthroughActivityLoaded": walkthrough["activity"]["loaded"],
            },
        },
        "visual": {
            "planChangedPixelRatio": _changed_pixel_ratio(
                output_dir / "02-plan-all-actors-35-seconds.png",
                output_dir / "03-plan-all-actors-115-seconds.png",
            ),
            "screenshots": [_image_evidence(path) for path in screenshots],
        },
        "errors": {
            "page": page_errors,
            "console": console_errors,
            "failedRequests": failed_requests,
            "server5xx": server_errors,
        },
    }
    paired_loops = report["activity"]["primaryBoulevard"][
        "pairedLaneLoops"
    ]
    paired_lane_valid = len(paired_loops) >= 2 and all(
        item["loopMode"] == "paired_lanes"
        and {
            item["outboundDirection"],
            item["returnDirection"],
        } == {"forward", "reverse"}
        and item["markingSetsDisjoint"]
        and item["laneCenterlineSeparationMeters"] > 0.5
        and set(item["outcomes"].values()) == {"accepted"}
        for item in paired_loops
    )
    required = [
        report["layout"]["savedFilesByteIdentical"],
        report["layout"]["browserLayoutByteIdentical"],
        report["layout"]["matchesArchivedManualExceptLayoutId"],
        report["layout"]["dirtyAfter"] is False,
        report["layout"]["operationCountAfter"] == 0,
        report["sage"]["streamStatuses"] == [200],
        report["sage"]["activityLoadedFromPrompt"],
        report["activity"]["actorCount"] >= 6,
        report["activity"]["actorTypeCounts"]["vehicle"] >= 2,
        report["activity"]["actorTypeCounts"]["operator"] >= 2,
        len(report["activity"]["advancedActorIds"]) >= 4,
        report["activity"]["planAndThreeSharedPose"],
        report["activity"]["planVisibleMarkerCount"] >= 4,
        report["activity"]["stationaryEvidence"]["placementCount"] > 0,
        report["activity"]["stationaryTransformsUnchanged"],
        report["activity"]["allActorsUseDeclaredVisuals"],
        report["activity"]["visualHeadingAlignment"][
            "allActorsFaceTravel"
        ],
        report["activity"]["primaryBoulevard"]["allActorsAreVehicles"],
        not report["activity"]["primaryBoulevard"]["hasMobileEquipment"],
        report["activity"]["primaryBoulevard"][
            "laneDirections"
        ] == ["forward", "reverse"],
        report["activity"]["primaryBoulevard"][
            "allLanesBoundToDirectionMarkings"
        ],
        report["activity"]["primaryBoulevard"][
            "laneCenterlineSeparationMeters"
        ] > 0.5,
        paired_lane_valid,
        report["activity"]["pairedLaneLoop"]["outboundPhase"]
        == "outbound",
        report["activity"]["pairedLaneLoop"]["endTransferPhase"]
        == "lane_change_at_end",
        report["activity"]["pairedLaneLoop"]["returnPhase"]
        == "return",
        report["activity"]["pairedLaneLoop"]["startTransferPhase"]
        == "lane_change_at_start",
        report["activity"]["pairedLaneLoop"]["nextCyclePhase"]
        == "outbound",
        report["activity"]["pairedLaneLoop"]["outboundPackageId"]
        == loop_definition["outboundPackageId"],
        report["activity"]["pairedLaneLoop"]["endTransferPackageId"]
        == loop_definition["endTransferPackageId"],
        report["activity"]["pairedLaneLoop"]["returnPackageId"]
        == loop_definition["returnPackageId"],
        report["activity"]["pairedLaneLoop"]["startTransferPackageId"]
        == loop_definition["startTransferPackageId"],
        report["activity"]["pairedLaneLoop"]["nextCyclePackageId"]
        == loop_definition["outboundPackageId"],
        abs(
            report["activity"]["pairedLaneLoop"][
                "outboundReturnHeadingDeltaRadians"
            ] - math.pi
        ) < 1e-6,
        paired_binding is not None,
        paired_binding and paired_binding["prototypeMeshCount"] > 1,
        paired_binding and paired_binding["representation"] in {
            "overview", "detail"
        },
        focus_result["focused"],
        secondary_focus["focused"],
        operator_focus["focused"],
        report["activity"]["controls"]["operatorHidden"],
        report["activity"]["controls"]["departmentFilterReducedActors"],
        report["activity"]["immersiveModes"]["droneActive"],
        report["activity"]["immersiveModes"]["droneActivityLoaded"],
        report["activity"]["immersiveModes"]["walkthroughActive"],
        report["activity"]["immersiveModes"]["walkthroughActivityLoaded"],
        report["visual"]["planChangedPixelRatio"] > 0.00001,
        all(item["nonblank"] for item in report["visual"]["screenshots"]),
        not any(report["errors"].values()),
    ]
    report["passed"] = all(required)
    report_path = output_dir / "facility-activity-browser-evidence.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8153/")
    parser.add_argument("--layout", default=str(DEFAULT_LAYOUT))
    parser.add_argument("--reference", default=str(REFERENCE_LAYOUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    report = capture(args)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
