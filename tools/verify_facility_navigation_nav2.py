"""Verify NAV2 end to end against a scratch clone of the manual factory."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from time import strftime
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
OUTPUT = ROOT / "tests" / "fixtures" / "facility_layout" / "navigation" / "browser"
REPORT = OUTPUT / "nav2-browser-evidence-v1.json"
SITE_ID = "site-local"
REFERENCE_LAYOUT_ID = "fl-reference-manual-20260812"
OPERATOR_ID = "pl-0ede7a2f4cd16826e9a68785"
FORKLIFT_ID = "pl-043ba93c06287a1189f76121"
FORKLIFT_PROFILE_ID = "prototype-red-telescopic-forklift-v1"
FORKLIFT_PROFILE_REVISION = (
    "65e868ee2d4d122bf1d9db32d0d8a7279dbbcf386b1f973b587db0952a81d042"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _http_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: Any | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {error.code} {detail}") from error


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
            && (_trainFacilityLayoutAuthoringApp.session.getState().layout
                .placements || []).length === 827
        )""",
        timeout=240_000,
    )


def _prepare_path(
    page: Any,
    *,
    actor_id: str,
    points: list[dict[str, float]],
    loop_mode: str,
    constraint_mode: str = "complete_override",
    profile_id: str = "",
    profile_revision: str = "",
) -> dict[str, Any]:
    return page.evaluate(
        """async request => {
            const app = window._trainFacilityLayoutAuthoringApp;
            const workspace = app.workspace;
            workspace.closeNavigationDialog(false);
            app.session.select(request.actorId);
            if (!workspace.openNavigationDialog()) {
                throw new Error('Motion Path did not open for ' + request.actorId);
            }
            workspace.navigationState.points = request.points;
            workspace.navigationState.loopMode = request.loopMode;
            workspace.navigationState.direction = 'forward';
            workspace.navigationState.constraintMode = request.constraintMode;
            workspace.navigationState.actorProfileId = request.profileId;
            workspace.navigationState.actorProfileRevision = request.profileRevision;
            workspace.navigationState.validation = null;
            workspace.navigationState.validationStatus = 'pending';
            workspace.navigationState.drawing = false;
            workspace.navigationState.previewNormalizedTime = 0.375;
            workspace._syncNavigationAuthoringPreview();
            workspace._renderNavigationDialog();
            const applied = await workspace._applyNavigationPath();
            return {
                applied,
                navigation: JSON.parse(JSON.stringify(workspace.navigationState)),
                session: JSON.parse(JSON.stringify(app.session.getState())),
            };
        }""",
        {
            "actorId": actor_id,
            "points": points,
            "loopMode": loop_mode,
            "constraintMode": constraint_mode,
            "profileId": profile_id,
            "profileRevision": profile_revision,
        },
    )


def _focus_plan(page: Any, point: dict[str, float], zooms: int = 2) -> None:
    page.evaluate(
        """request => {
            const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
            workspace._setViewMode('plan');
            workspace.topAdapter.fitLayout();
            for (let index = 0; index < request.zooms; index += 1) {
                const client = workspace.topAdapter.worldToClient(request.point);
                workspace.topAdapter.zoomAt({
                    clientX: client.x,
                    clientY: client.y,
                }, 4);
            }
        }""",
        {"point": point, "zooms": zooms},
    )
    page.wait_for_timeout(500)


def _preview_3d(page: Any, point: dict[str, float]) -> dict[str, Any]:
    result = page.evaluate(
        """async point => {
            const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
            workspace._setViewMode('3d');
            await workspace._loadNavigationPreview();
            workspace.threeAdapter.navigationPreview.seek(0.375);
            const preview = workspace.threeAdapter.navigationPreview.getState();
            const target = preview.pose || point;
            const camera = new THREE.PerspectiveCamera();
            camera.position.set(target.x + 10, 7, target.z + 10);
            camera.lookAt(target.x, 1.1, target.z);
            const view = workspace.threeAdapter.getCameraView();
            view.position = {
                x: camera.position.x,
                y: camera.position.y,
                z: camera.position.z,
            };
            view.quaternion = {
                x: camera.quaternion.x,
                y: camera.quaternion.y,
                z: camera.quaternion.z,
                w: camera.quaternion.w,
            };
            view.target = {x: target.x, y: 1.1, z: target.z};
            workspace.threeAdapter.applyCameraView(view);
            await new Promise(resolve => setTimeout(resolve, 900));
            const diagnostics = workspace.threeAdapter.getDiagnostics();
            return {
                three: workspace.threeAdapter.navigationPreview.getState(),
                plan: workspace._navigationPreviewDescriptor(),
                diagnostics: {
                    status: diagnostics.status,
                    placementCount: diagnostics.placementCount,
                    warningCount: Array.isArray(diagnostics.warnings)
                        ? diagnostics.warnings.length
                        : 0,
                },
            };
        }""",
        point,
    )
    page.wait_for_timeout(900)
    return result


def _snapshot(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const app = window._trainFacilityLayoutAuthoringApp;
            const state = app.session.getState();
            const navigation = state.layout.extensions
                && state.layout.extensions.facilityNavigation;
            return {
                baseRevision: state.baseRevision,
                dirty: state.dirty,
                canSave: state.canSave,
                operationCount: (state.operations || []).length,
                navigation: navigation ? JSON.parse(JSON.stringify(navigation)) : null,
            };
        }"""
    )


def _compact_validation(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    fields = (
        "schemaVersion",
        "valid",
        "actorClass",
        "actorPlacementId",
        "actorProfileRef",
        "constraintMode",
        "pointCount",
        "segmentCount",
        "invalidSegmentIndexes",
        "validationMethod",
        "validationFingerprint",
        "evidenceStatus",
        "reviewStatus",
        "mutated",
        "prototypeMode",
        "prototypeLabel",
        "productionEligible",
        "qualification",
        "findings",
    )
    return {field: value[field] for field in fields if field in value}


def _compact_interaction(value: dict[str, Any]) -> dict[str, Any]:
    navigation = value["navigation"]
    session = value["session"]
    return {
        "applied": value["applied"],
        "navigation": {
            field: navigation[field]
            for field in (
                "actorClass",
                "actorPlacementId",
                "actorProfileId",
                "actorProfileRevision",
                "constraintMode",
                "direction",
                "loopMode",
                "lockedSegmentIndexes",
                "points",
                "message",
                "validationStatus",
            )
            if field in navigation
        },
        "validation": _compact_validation(navigation.get("validation")),
        "session": {
            "baseRevision": session.get("baseRevision"),
            "dirty": session.get("dirty"),
            "canSave": session.get("canSave"),
            "canUndo": session.get("canUndo"),
            "operationCount": len(session.get("operations") or []),
        },
    }


def _compact_preview(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "diagnostics": value["diagnostics"],
        "plan": {
            field: value["plan"][field]
            for field in (
                "actorClass",
                "actorPlacementId",
                "pathsVisible",
                "points",
                "pose",
                "validationStatus",
            )
            if field in value["plan"]
        },
        "three": {
            field: value["three"][field]
            for field in (
                "actorClass",
                "actorPlacementId",
                "duplicateVisiblePlacementCount",
                "exactCatalogVisual",
                "loaded",
                "pathsVisible",
                "pose",
                "previewId",
                "qualification",
                "sourcePlacementSuppressed",
                "status",
                "validationStatus",
            )
            if field in value["three"]
        },
    }


def _compact_evidence(value: dict[str, Any]) -> dict[str, Any]:
    compact = {
        field: value[field]
        for field in (
            "schemaVersion",
            "referenceLayoutId",
            "scratchLayoutId",
            "referenceSha256Before",
            "referenceSha256After",
            "initial",
            "operatorDraft",
            "pathsHidden",
            "beforeUndo",
            "afterUndo",
            "afterSave",
            "reopened",
            "screenshots",
            "consoleErrors",
            "pageErrors",
            "failedResponses",
            "checks",
        )
    }
    for field in ("invalidAttempt", "operator", "vehicle"):
        compact[field] = _compact_interaction(value[field])
    compact["operatorPreview"] = _compact_preview(value["operatorPreview"])
    compact["vehiclePreview"] = _compact_preview(value["vehiclePreview"])
    compact["validationResponses"] = []
    for item in value["validationResponses"]:
        request_body = item.get("requestBody", {})
        response_body = item.get("responseBody", {})
        if isinstance(request_body, str):
            request_body = json.loads(request_body)
        if isinstance(response_body, str):
            response_body = json.loads(response_body)
        compact["validationResponses"].append({
            "status": item.get("status"),
            "requestActorClass": request_body.get("request", {}).get(
                "actorClass"
            ),
            "valid": response_body.get("valid"),
            "validationFingerprint": response_body.get(
                "validationFingerprint"
            ),
        })
    return compact


def _set_navigation_dialog_visible(page: Any, visible: bool) -> None:
    page.evaluate(
        """visible => {
            const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
            workspace.navigationDialog.hidden = !visible;
        }""",
        visible,
    )
    page.wait_for_timeout(250)


def verify(base_url: str) -> dict[str, Any]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    reference_sha_before = _sha(ARCHIVE)
    reference_receipt = _http_json(
        base_url,
        f"/api/facility-layouts/{SITE_ID}/{REFERENCE_LAYOUT_ID}",
    )
    scratch_id = "fl-nav2-browser-" + strftime("%Y%m%d-%H%M%S")
    scratch_layout = deepcopy(reference_receipt["layout"])
    scratch_layout["layoutId"] = scratch_id
    scratch_layout["displayName"] = "NAV2 Browser Evidence Scratch"
    scratch_layout.setdefault("extensions", {}).pop("facilityNavigation", None)
    scratch_receipt = _http_json(
        base_url,
        f"/api/facility-layouts/{SITE_ID}",
        method="POST",
        payload={"layout": scratch_layout, "makeDefault": False},
    )
    screenshots = {
        "invalid": OUTPUT / "05-nav2-invalid-operator-segment.png",
        "operator_plan": OUTPUT / "06-nav2-operator-loop-plan.png",
        "operator_3d": OUTPUT / "07-nav2-operator-loop-3d.png",
        "vehicle_plan": OUTPUT / "08-nav2-paired-lane-vehicle-plan.png",
        "vehicle_3d": OUTPUT / "09-nav2-paired-lane-vehicle-3d.png",
    }
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    validation_responses: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}

    def current_bootstrap() -> dict[str, Any]:
        bootstrap = _http_json(base_url, "/api/facility-layout-bootstrap")
        bootstrap["layoutId"] = scratch_id
        bootstrap["layout"] = _http_json(
            base_url,
            f"/api/facility-layouts/{SITE_ID}/{scratch_id}",
        )
        return bootstrap

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
                if message.type == "error" else None,
            )

            def observe_response(response: Any) -> None:
                if "/navigation/manual-path/validate" in response.url:
                    validation_responses.append({
                        "status": response.status,
                        "requestBody": response.request.post_data or "",
                        "responseBody": response.text(),
                    })
                if response.status >= 400 and not response.url.endswith(
                    "/static/manifest.json"
                ):
                    try:
                        response_body = response.text()
                    except Exception:  # Playwright can race a closing page.
                        response_body = ""
                    failed_responses.append({
                        "status": response.status,
                        "method": response.request.method,
                        "url": response.url,
                        "body": response_body,
                    })

            page.on("response", observe_response)
            page.route(
                "**/api/facility-layout-bootstrap",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(current_bootstrap()),
                ),
            )
            page.goto(base_url, wait_until="domcontentloaded", timeout=120_000)
            _open_facility(page)
            initial = _snapshot(page)

            operator_start = {"x": 196.596, "z": 60.6552}
            invalid = _prepare_path(
                page,
                actor_id=OPERATOR_ID,
                points=[
                    operator_start,
                    {"x": -2.0, "z": 60.6552},
                    {"x": -2.0, "z": 62.0},
                    operator_start,
                ],
                loop_mode="closed_loop",
            )
            _focus_plan(page, operator_start, 2)
            page.screenshot(path=str(screenshots["invalid"]), full_page=False)

            operator_candidates = [
                [
                    operator_start,
                    {"x": 196.596, "z": 56.0},
                    {"x": 190.0, "z": 56.0},
                    {"x": 196.596, "z": 56.0},
                    operator_start,
                ],
            ]
            operator = None
            for candidate in operator_candidates:
                result = _prepare_path(
                    page,
                    actor_id=OPERATOR_ID,
                    points=candidate,
                    loop_mode="closed_loop",
                )
                if result["applied"]:
                    operator = result
                    break
            if operator is None:
                raise AssertionError("No reviewed operator-loop candidate validated.")
            _focus_plan(page, operator_start, 2)
            page.screenshot(
                path=str(screenshots["operator_plan"]),
                full_page=False,
            )
            operator_preview = _preview_3d(page, operator_start)
            _set_navigation_dialog_visible(page, False)
            page.screenshot(
                path=str(screenshots["operator_3d"]),
                full_page=False,
            )
            _set_navigation_dialog_visible(page, True)
            operator_saved_draft = _snapshot(page)

            forklift_start = {"x": 15.24, "z": 67.056}
            vehicle_points = [
                forklift_start,
                {"x": 15.24, "z": 82.0},
                {"x": 16.5, "z": 87.0},
                {"x": 21.0, "z": 90.5},
                {"x": 30.0, "z": 91.44},
                {"x": 250.0, "z": 91.44},
                {"x": 258.0, "z": 92.0},
                {"x": 264.0, "z": 94.488},
                {"x": 258.0, "z": 97.0},
                {"x": 250.0, "z": 97.536},
                {"x": 30.0, "z": 97.536},
                {"x": 21.0, "z": 96.5},
                {"x": 16.5, "z": 93.0},
                {"x": 15.24, "z": 86.0},
                forklift_start,
            ]
            vehicle = _prepare_path(
                page,
                actor_id=FORKLIFT_ID,
                points=vehicle_points,
                loop_mode="paired_lane_return",
                profile_id=FORKLIFT_PROFILE_ID,
                profile_revision=FORKLIFT_PROFILE_REVISION,
            )
            if not vehicle["applied"]:
                vehicle = _prepare_path(
                    page,
                    actor_id=FORKLIFT_ID,
                    points=vehicle_points,
                    loop_mode="paired_lane_return",
                    constraint_mode="guide",
                    profile_id=FORKLIFT_PROFILE_ID,
                    profile_revision=FORKLIFT_PROFILE_REVISION,
                )
            if not vehicle["applied"]:
                raise AssertionError("The paired-lane vehicle path was not authored.")
            _focus_plan(page, {"x": 140.0, "z": 94.488}, 1)
            page.screenshot(
                path=str(screenshots["vehicle_plan"]),
                full_page=False,
            )
            vehicle_preview = _preview_3d(page, {"x": 140.0, "z": 94.488})
            _set_navigation_dialog_visible(page, False)
            page.screenshot(
                path=str(screenshots["vehicle_3d"]),
                full_page=False,
            )
            _set_navigation_dialog_visible(page, True)

            hidden = page.evaluate(
                """() => {
                    const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                    workspace.navigationState.pathsVisible = false;
                    workspace._syncNavigationAuthoringPreview();
                    return {
                        three: workspace.threeAdapter.navigationPreview.getState(),
                        planVisible: workspace.navigationState.pathsVisible,
                    };
                }"""
            )
            before_undo = _snapshot(page)
            page.evaluate(
                """async () => {
                    await window._trainFacilityLayoutAuthoringApp.workspace
                        .executeCommand('undo');
                }"""
            )
            after_undo = _snapshot(page)
            page.evaluate(
                """async () => {
                    const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                    await workspace.executeCommand('redo');
                    await workspace.executeCommand('save');
                }"""
            )
            after_save = _snapshot(page)
            page.reload(wait_until="domcontentloaded", timeout=120_000)
            _open_facility(page)
            # Let any restored editor validation acquire the still-live scratch
            # revision before the finally block archives that layout.
            page.wait_for_timeout(2_000)
            reopened = _snapshot(page)
            browser.close()

            evidence = {
                "schemaVersion": "facility-navigation-nav2-browser-evidence-v1",
                "referenceLayoutId": REFERENCE_LAYOUT_ID,
                "scratchLayoutId": scratch_id,
                "referenceSha256Before": reference_sha_before,
                "initial": initial,
                "invalidAttempt": invalid,
                "operator": operator,
                "operatorPreview": operator_preview,
                "operatorDraft": operator_saved_draft,
                "vehicle": vehicle,
                "vehiclePreview": vehicle_preview,
                "pathsHidden": hidden,
                "beforeUndo": before_undo,
                "afterUndo": after_undo,
                "afterSave": after_save,
                "reopened": reopened,
                "screenshots": {
                    key: path.relative_to(ROOT).as_posix()
                    for key, path in screenshots.items()
                },
                "consoleErrors": console_errors,
                "pageErrors": page_errors,
                "failedResponses": failed_responses,
                "validationResponses": validation_responses,
            }
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

    reference_sha_after = _sha(ARCHIVE)
    evidence["referenceSha256After"] = reference_sha_after
    operator_three = evidence["operatorPreview"]["three"]
    operator_plan = evidence["operatorPreview"]["plan"]
    vehicle_three = evidence["vehiclePreview"]["three"]
    vehicle_plan = evidence["vehiclePreview"]["plan"]
    evidence["checks"] = {
        "reference_unchanged": reference_sha_before == reference_sha_after,
        "invalid_visible_and_not_authored": (
            evidence["invalidAttempt"]["applied"] is False
            and evidence["invalidAttempt"]["navigation"]["validationStatus"]
            == "invalid"
            and evidence["invalidAttempt"]["session"]["operations"] == []
        ),
        "operator_complete_override_validated": (
            evidence["operator"]["navigation"]["validationStatus"] == "validated"
            and evidence["operator"]["navigation"]["constraintMode"]
            == "complete_override"
        ),
        "operator_exact_visual": (
            operator_three["exactCatalogVisual"] is True
            and operator_three["sourcePlacementSuppressed"] is True
            and operator_three["duplicateVisiblePlacementCount"] == 0
        ),
        "vehicle_exact_visual": (
            vehicle_three["exactCatalogVisual"] is True
            and vehicle_three["sourcePlacementSuppressed"] is True
            and vehicle_three["duplicateVisiblePlacementCount"] == 0
        ),
        "operator_plan_3d_pose_agree": operator_plan["pose"] == operator_three["pose"],
        "vehicle_plan_3d_pose_agree": vehicle_plan["pose"] == vehicle_three["pose"],
        "paired_lane_mode_preserved": (
            evidence["vehicle"]["navigation"]["loopMode"]
            == "paired_lane_return"
        ),
        "vehicle_complete_override_validated": (
            evidence["vehicle"]["navigation"]["validationStatus"]
            == "validated"
            and evidence["vehicle"]["navigation"]["constraintMode"]
            == "complete_override"
            and evidence["vehicle"]["navigation"]["validation"][
                "prototypeMode"
            ] is True
            and evidence["vehicle"]["navigation"]["validation"][
                "productionEligible"
            ] is False
        ),
        "path_visibility_independent": (
            evidence["pathsHidden"]["planVisible"] is False
            and evidence["pathsHidden"]["three"]["pathsVisible"] is False
            and evidence["pathsHidden"]["three"]["exactCatalogVisual"] is True
        ),
        "undo_removed_only_vehicle_gesture": (
            len(evidence["beforeUndo"]["navigation"]["movementPrograms"]) == 2
            and len(evidence["afterUndo"]["navigation"]["movementPrograms"]) == 1
        ),
        "save_and_reopen_exact": (
            evidence["afterSave"]["dirty"] is False
            and evidence["reopened"]["navigation"]
            == evidence["afterSave"]["navigation"]
        ),
        "no_browser_errors": not console_errors and not page_errors,
        "no_failed_http": not failed_responses,
    }
    REPORT.write_text(
        json.dumps(_compact_evidence(evidence), indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    if not all(evidence["checks"].values()):
        failed = [key for key, value in evidence["checks"].items() if not value]
        raise AssertionError("NAV2 browser checks failed: " + ", ".join(failed))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    evidence = verify(args.url)
    print(json.dumps(evidence["checks"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
