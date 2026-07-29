#!/usr/bin/env python3
"""Produce hermetic browser evidence for Facility Layout P5 authoring."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
import hashlib
from io import BytesIO
import json
from pathlib import Path
import socket
import sys
import threading
import time
from tempfile import TemporaryDirectory
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from PIL import Image
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.api import create_facility_layout_router
from ai_inspector.facility_layout.authority_repository import (
    FacilityShellRepository,
    PolicySetRepository,
    VehicleProfileRepository,
)
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.canonical import (
    canonicalize_layout,
    layout_revision,
)
from ai_inspector.facility_layout.operations import create_layout_document
from ai_inspector.facility_layout.repository import FacilityLayoutRepository
from ai_inspector.facility_layout.service import (
    FacilityLayoutService,
    coordinate_frame_fingerprint,
)
from ai_inspector.facility_layout.validate import validate_layout


FIXTURES = ROOT / "tests" / "fixtures" / "facility_layout"
AUTHORING = FIXTURES / "authoring"
RENDERING = FIXTURES / "rendering"
PAGE = AUTHORING / "p5-authoring.html"
SCRIPT = AUTHORING / "p5-authoring.js"
CATALOG = RENDERING / "p4-asset-catalog.json"
P4_LAYOUT = RENDERING / "p4-facility-layout.json"
AUTHORITY_FIXTURE = FIXTURES / "p0_authority_documents.json"
DEFAULT_RESULT = AUTHORING / "p5-authoring-result.json"
DEFAULT_DESKTOP = AUTHORING / "p5-authoring-desktop.png"
DEFAULT_MOBILE = AUTHORING / "p5-authoring-mobile.png"
DEFAULT_THREE = AUTHORING / "p5-authoring-three.png"
DEFAULT_EDGE = Path(
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)
SESSION = ROOT / "static" / "facility_layout_session.js"
WORKSPACE = ROOT / "static" / "facility_layout_workspace.js"
WORKSPACE_CSS = ROOT / "static" / "facility_layout_workspace.css"
EDITOR = ROOT / "static" / "facility_layout_editor.js"
THREE_ADAPTER = ROOT / "static" / "facility_layout_three_adapter.js"
VENDOR = ROOT / "static" / "vendor" / "three" / "0.184.0"
THREE_MODULE = VENDOR / "build" / "three.module.min.js"
GLTF_LOADER = VENDOR / "examples" / "jsm" / "loaders" / "GLTFLoader.js"
ORBIT_CONTROLS = VENDOR / "examples" / "jsm" / "controls" / "OrbitControls.js"
OVERVIEW = (
    ROOT
    / "generated"
    / "industrial_assets"
    / "p0_spike"
    / "rack_prototypes"
    / "Pallet Racking_colored_overview_proxy.glb"
)
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _png_metrics(data: bytes) -> dict[str, Any]:
    with Image.open(BytesIO(data)) as source:
        image = source.convert("RGB")
        width, height = image.size
        pixels = list(image.getdata())
    corners = (
        pixels[0],
        pixels[width - 1],
        pixels[(height - 1) * width],
        pixels[-1],
    )
    background = Counter(corners).most_common(1)[0][0]
    changed = 0
    maximum_delta = 0
    for red, green, blue in pixels:
        delta = (
            abs(red - background[0])
            + abs(green - background[1])
            + abs(blue - background[2])
        )
        maximum_delta = max(maximum_delta, delta)
        if delta > 24:
            changed += 1
    return {
        "width": width,
        "height": height,
        "backgroundRgb": list(background),
        "changedPixelCount": changed,
        "changedPixelFraction": round(changed / max(1, width * height), 8),
        "maximumDelta": maximum_delta,
        "nonblank": changed >= 1000 and maximum_delta >= 40,
    }


def _principal(role: str = "admin") -> FacilityPrincipal:
    return FacilityPrincipal(
        principal_id=f"p5-{role}",
        tenant_id="tenant-a",
        allowed_site_ids=("site-a",),
        roles=(role,),
    )


def _authority_documents() -> dict[str, dict[str, Any]]:
    values = json.loads(AUTHORITY_FIXTURE.read_text(encoding="ascii"))
    return {
        value["documentKind"]: deepcopy(value)
        for value in values
        if value["documentKind"]
        in {"facility_shell", "policy_set", "vehicle_profile"}
    }


def _publish(repository, document, id_field):
    principal = _principal()
    candidate = deepcopy(document)
    candidate["status"] = "draft"
    created = repository.create(
        principal,
        site_id="site-a",
        document=candidate,
    )
    reviewed = repository.review(
        principal,
        site_id="site-a",
        authority_id=candidate[id_field],
        expected_revision=created.envelope.revision,
    )
    return repository.publish(
        principal,
        site_id="site-a",
        authority_id=candidate[id_field],
        expected_revision=reviewed.envelope.revision,
    ).envelope


class _P5PermissiveSpatialExecutor:
    """Keep the historical P5 proof isolated from P6 constraints."""

    @staticmethod
    def run_diagnostics(document, *_args, **_kwargs):
        placements = document.get("placements", [])
        return {
            "spatialEngineVersion": 0,
            "safetyStatus": "unverified",
            "safe": False,
            "valid": True,
            "findings": [],
            "zoneMembership": {},
            "metrics": {
                "placementCount": len(placements),
                "indexedPolygonCount": 0,
                "placementCollisions": 0,
                "shellObstacleCollisions": 0,
                "clearanceConflicts": 0,
                "errorCount": 0,
                "unverifiedCount": 0,
                "warningCount": 0,
            },
        }


def _bootstrap_app(
    data_root: Path,
) -> tuple[FastAPI, FacilityLayoutService, dict[str, Any]]:
    documents = _authority_documents()
    clock = lambda: NOW
    shell_repository = FacilityShellRepository(
        data_root / "authority" / "shells",
        clock=clock,
    )
    policy_repository = PolicySetRepository(
        data_root / "authority" / "policies",
        clock=clock,
    )
    vehicle_repository = VehicleProfileRepository(
        data_root / "authority" / "vehicles",
        clock=clock,
    )
    shell = _publish(shell_repository, documents["facility_shell"], "shellId")
    policy = _publish(policy_repository, documents["policy_set"], "policySetId")
    _publish(
        vehicle_repository,
        documents["vehicle_profile"],
        "vehicleProfileId",
    )
    catalog = json.loads(CATALOG.read_text(encoding="ascii"))
    available_assets = {
        (entry["assetId"], entry["assetDefinitionRevision"]): {
            "revision": entry["assetDefinitionRevision"],
            "definition": deepcopy(entry["definition"]),
        }
        for entry in catalog
    }
    service = FacilityLayoutService(
        layout_repository=FacilityLayoutRepository(
            data_root / "layouts",
            clock=clock,
        ),
        shell_repository=shell_repository,
        policy_repository=policy_repository,
        vehicle_repository=vehicle_repository,
        asset_definition_resolver=lambda _principal, _site, asset_id, revision: (
            deepcopy(available_assets.get((asset_id, revision)))
        ),
        spatial_executor=_P5PermissiveSpatialExecutor(),
    )

    frame = deepcopy(shell.document["coordinateFrame"])
    layout = create_layout_document(
        layout_id="fl-p5-authoring",
        display_name="P5 Manual Authoring Cell",
        association={"siteId": "site-a", "areaId": "p5-cell"},
        coordinate_frame=frame,
        source_shell_ref={
            "shellId": shell.document["shellId"],
            "shellRevision": shell.revision,
            "coordinateFrameFingerprint": coordinate_frame_fingerprint(frame),
        },
        policy_set_ref={
            "policySetId": policy.document["policySetId"],
            "policySetRevision": policy.revision,
        },
        catalog_snapshot_revision="3" * 64,
        created_at=NOW.isoformat().replace("+00:00", "Z"),
    )
    p4 = json.loads(P4_LAYOUT.read_text(encoding="ascii"))
    auto = deepcopy(p4["placements"][0])
    auto["placementId"] = "pl-p5-auto"
    auto["positionMode"] = "auto"
    auto["metadata"]["instanceLabel"] = "Auto Rack"
    manual = deepcopy(p4["placements"][3])
    manual["placementId"] = "pl-p5-manual"
    manual["positionMode"] = "manual"
    manual["transform"]["position"] = {"x": 7, "y": 0, "z": 8}
    manual["metadata"]["instanceLabel"] = "Manual Rack"
    locked = deepcopy(p4["placements"][1])
    locked["placementId"] = "pl-p5-locked"
    locked["positionMode"] = "locked"
    locked["transform"]["position"] = {"x": 14, "y": 0, "z": 3}
    locked["metadata"]["instanceLabel"] = "Locked Rack"
    layout["placements"] = [auto, manual, locked]
    layout = canonicalize_layout(layout)
    validate_layout(layout, require_canonical=True)
    created = service.create_layout(_principal(), "site-a", layout)

    def resolve_principal(request: Request) -> FacilityPrincipal:
        return _principal(request.headers.get("X-Test-Role", "admin"))

    app = FastAPI()
    app.include_router(
        create_facility_layout_router(
            service=service,
            principal_resolver=resolve_principal,
        )
    )
    app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="workspace")
    return app, service, created


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.bind(("127.0.0.1", 0))
        return int(connection.getsockname()[1])


def _wait_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    deadline = time.time() + 15
    while not server.started and thread.is_alive() and time.time() < deadline:
        time.sleep(0.03)
    if not server.started:
        raise RuntimeError("P5 verification server did not start.")


def _ready(page: Any) -> None:
    try:
        page.wait_for_function(
            """() => {
                const value = window.facilityP5Evidence;
                return value && (
                    value.state === 'ready' || value.state === 'error'
                );
            }""",
            timeout=120_000,
        )
    except PlaywrightTimeoutError as error:
        raise RuntimeError("P5 browser fixture did not become ready.") from error
    state = page.evaluate("() => window.facilityP5Evidence.state")
    if state != "ready":
        errors = page.evaluate("() => window.facilityP5Evidence.errors || []")
        raise RuntimeError(f"P5 browser fixture failed: {errors}")


def _screenshot_record(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        size = image.size
        rgb = image.convert("RGB")
        extrema = rgb.getextrema()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "width": size[0],
        "height": size[1],
        "channelSpans": [high - low for low, high in extrema],
    }


def _source_hashes() -> dict[str, str]:
    return {
        "assetCatalogSha256": _sha256(CATALOG),
        "authorityFixtureSha256": _sha256(AUTHORITY_FIXTURE),
        "facilityLayoutEditorSha256": _sha256(EDITOR),
        "facilityLayoutSessionSha256": _sha256(SESSION),
        "facilityLayoutWorkspaceSha256": _sha256(WORKSPACE),
        "facilityLayoutWorkspaceCssSha256": _sha256(WORKSPACE_CSS),
        "facilityThreeAdapterSha256": _sha256(THREE_ADAPTER),
        "fixturePageSha256": _sha256(PAGE),
        "fixtureScriptSha256": _sha256(SCRIPT),
        "gltfLoaderSha256": _sha256(GLTF_LOADER),
        "orbitControlsSha256": _sha256(ORBIT_CONTROLS),
        "overviewGlbSha256": _sha256(OVERVIEW),
        "p4LayoutSeedSha256": _sha256(P4_LAYOUT),
        "threeModuleSha256": _sha256(THREE_MODULE),
        "verifierSha256": _sha256(Path(__file__).resolve()),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--desktop", type=Path, default=DEFAULT_DESKTOP)
    parser.add_argument("--mobile", type=Path, default=DEFAULT_MOBILE)
    parser.add_argument("--three", type=Path, default=DEFAULT_THREE)
    parser.add_argument("--edge-path", type=Path, default=DEFAULT_EDGE)
    return parser.parse_args()


def _position_delta(
    before: dict[str, float],
    after: dict[str, float],
) -> dict[str, float]:
    return {
        axis: round(float(after[axis]) - float(before[axis]), 9)
        for axis in ("x", "y", "z")
    }


def main() -> int:
    args = _parse_args()
    required = (
        PAGE,
        SCRIPT,
        CATALOG,
        P4_LAYOUT,
        AUTHORITY_FIXTURE,
        SESSION,
        WORKSPACE,
        WORKSPACE_CSS,
        EDITOR,
        THREE_ADAPTER,
        THREE_MODULE,
        GLTF_LOADER,
        ORBIT_CONTROLS,
        OVERVIEW,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing P5 browser-evidence inputs: {missing}")
    if not args.edge_path.is_file():
        raise SystemExit(f"Microsoft Edge not found: {args.edge_path}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.desktop.parent.mkdir(parents=True, exist_ok=True)
    args.mobile.parent.mkdir(parents=True, exist_ok=True)
    args.three.parent.mkdir(parents=True, exist_ok=True)
    runtime_root = ROOT / ".runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)

    blocked_external: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    failed_requests: list[dict[str, Any]] = []
    request_urls: list[str] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    desktop: dict[str, Any] = {}
    mobile: dict[str, Any] = {}

    with TemporaryDirectory(
        prefix="facility-p5-",
        dir=runtime_root,
    ) as directory:
        app, service, created = _bootstrap_app(Path(directory))
        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="error",
                access_log=False,
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        _wait_server(server, thread)
        origin = f"http://127.0.0.1:{port}"
        page_url = (
            f"{origin}/tests/fixtures/facility_layout/authoring/"
            "p5-authoring.html"
        )

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=str(args.edge_path),
                    headless=True,
                    args=(
                        "--disable-background-timer-throttling",
                        "--disable-renderer-backgrounding",
                        "--disable-backgrounding-occluded-windows",
                    ),
                )

                def configure_context(context: Any) -> None:
                    def route_request(route: Any) -> None:
                        request_urls.append(route.request.url)
                        if route.request.url.startswith(origin):
                            route.continue_()
                        else:
                            blocked_external.append(route.request.url)
                            route.abort()

                    context.route("**/*", route_request)

                def configure_page(page: Any, label: str) -> None:
                    page.on(
                        "response",
                        lambda response: (
                            failed_responses.append(
                                {
                                    "page": label,
                                    "status": response.status,
                                    "url": response.url,
                                }
                            )
                            if response.status >= 400
                            else None
                        ),
                    )
                    page.on(
                        "requestfailed",
                        lambda request: failed_requests.append(
                            {
                                "page": label,
                                "failure": request.failure or "",
                                "url": request.url,
                            }
                        ),
                    )
                    page.on(
                        "pageerror",
                        lambda error: page_errors.append(
                            f"{label}: {error}"
                        ),
                    )
                    page.on(
                        "console",
                        lambda message: (
                            console_errors.append(
                                f"{label}: {message.text}"
                            )
                            if message.type == "error"
                            else None
                        ),
                    )

                desktop_context = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    device_scale_factor=1,
                    reduced_motion="reduce",
                )
                configure_context(desktop_context)
                desktop_page = desktop_context.new_page()
                configure_page(desktop_page, "desktop")
                desktop_page.goto(
                    page_url + "?theme=light",
                    wait_until="load",
                    timeout=30_000,
                )
                _ready(desktop_page)

                initial = desktop_page.evaluate(
                    "() => window.facilityP5.summary()"
                )
                authoring = desktop_page.evaluate(
                    "() => window.facilityP5.runAuthoringScenario()"
                )
                plan_prepared = desktop_page.evaluate(
                    "() => window.facilityP5.preparePlanProjection()"
                )
                desktop_page.set_viewport_size(
                    {"width": 1180, "height": 760}
                )
                desktop_page.evaluate(
                    "() => window.dispatchEvent(new Event('resize'))"
                )
                desktop_page.wait_for_timeout(100)
                plan = desktop_page.evaluate(
                    """prepared => (
                        window.facilityP5.finishPlanProjection(prepared)
                    )""",
                    plan_prepared,
                )
                desktop_page.set_viewport_size(
                    {"width": 1440, "height": 900}
                )
                desktop_page.evaluate(
                    "() => window.dispatchEvent(new Event('resize'))"
                )
                desktop_page.wait_for_timeout(100)

                three_prepared = desktop_page.evaluate(
                    "() => window.facilityP5.prepareThreeProjection()"
                )
                canvas = desktop_page.locator(
                    ".ip-flw-three-view canvas"
                )
                canvas_box = canvas.bounding_box()
                if not canvas_box:
                    raise RuntimeError("P5 3D canvas has no browser bounds.")
                start_x = canvas_box["x"] + canvas_box["width"] * 0.62
                start_y = canvas_box["y"] + canvas_box["height"] * 0.46
                desktop_page.mouse.move(start_x, start_y)
                desktop_page.mouse.down(button="left")
                desktop_page.mouse.move(
                    start_x + 82,
                    start_y - 44,
                    steps=10,
                )
                desktop_page.mouse.up(button="left")
                desktop_page.wait_for_timeout(120)
                desktop_page.set_viewport_size(
                    {"width": 1260, "height": 780}
                )
                desktop_page.evaluate(
                    "() => window.dispatchEvent(new Event('resize'))"
                )
                desktop_page.wait_for_timeout(120)
                three = desktop_page.evaluate(
                    """prepared => (
                        window.facilityP5.finishThreeProjection(prepared)
                    )""",
                    three_prepared,
                )
                invalid = desktop_page.evaluate(
                    "() => window.facilityP5.runInvalidDrop()"
                )
                persistence = desktop_page.evaluate(
                    "() => window.facilityP5.saveAndReopen()"
                )

                desktop_page.set_viewport_size(
                    {"width": 1440, "height": 900}
                )
                desktop_page.evaluate(
                    "() => window.dispatchEvent(new Event('resize'))"
                )
                desktop_page.evaluate(
                    """async () => {
                        window.facilityP5.workspace._setViewMode('3d');
                        window.facilityP5.workspace.controller.fit();
                        await window.facilityP5.settle(7);
                    }"""
                )
                desktop_canvas_probe = desktop_page.evaluate(
                    "() => window.facilityP5.canvasPixelProbe()"
                )
                desktop_canvas_png = canvas.screenshot(path=str(args.three))
                desktop_canvas = {
                    "webglReadback": desktop_canvas_probe,
                    "elementScreenshot": _png_metrics(desktop_canvas_png),
                    "elementScreenshotSha256": hashlib.sha256(
                        desktop_canvas_png
                    ).hexdigest(),
                }
                desktop_page.evaluate(
                    """async () => {
                        window.facilityP5.workspace._setViewMode('plan');
                        window.facilityP5.workspace.controller.fit();
                        await window.facilityP5.settle(5);
                    }"""
                )
                final_desktop = desktop_page.evaluate(
                    "() => window.facilityP5.summary()"
                )
                desktop_page.screenshot(
                    path=str(args.desktop),
                    full_page=True,
                )
                desktop_dispose = desktop_page.evaluate(
                    "() => window.facilityP5.disposeProbe()"
                )
                desktop = {
                    "initial": initial,
                    "authoring": authoring,
                    "planPrepared": plan_prepared,
                    "plan": plan,
                    "threePrepared": three_prepared,
                    "three": three,
                    "invalidDrop": invalid,
                    "persistence": persistence,
                    "canvas": desktop_canvas,
                    "final": final_desktop,
                    "dispose": desktop_dispose,
                }
                desktop_page.close()
                desktop_context.close()

                mobile_context = browser.new_context(
                    viewport={"width": 390, "height": 844},
                    device_scale_factor=1,
                    reduced_motion="reduce",
                )
                configure_context(mobile_context)
                mobile_page = mobile_context.new_page()
                configure_page(mobile_page, "mobile")
                mobile_page.goto(
                    page_url + "?theme=dark",
                    wait_until="load",
                    timeout=30_000,
                )
                _ready(mobile_page)
                mobile_probe = mobile_page.evaluate(
                    "() => window.facilityP5.runMobileProbe()"
                )
                mobile_summary = mobile_page.evaluate(
                    "() => window.facilityP5.summary()"
                )
                mobile_page.screenshot(
                    path=str(args.mobile),
                    full_page=True,
                )
                mobile_dispose = mobile_page.evaluate(
                    "() => window.facilityP5.disposeProbe()"
                )
                mobile = {
                    "probe": mobile_probe,
                    "summary": mobile_summary,
                    "dispose": mobile_dispose,
                }
                mobile_page.close()
                mobile_context.close()
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=15)

        saved = service.get_layout(
            _principal(),
            "site-a",
            "fl-p5-authoring",
        )

    final_layout = persistence["reopened"]
    validate_layout(final_layout, require_canonical=False)
    authoring = desktop["authoring"]
    move = authoring["move"]
    undo_redo = authoring["undoRedo"]
    duplicate = authoring["duplicateDelete"]
    rotation = authoring["rotation"]
    locking = authoring["locking"]
    zones = authoring["zones"]
    plan = desktop["plan"]
    three = desktop["three"]
    plan_drop = plan["drop"]
    three_drop = three["drop"]
    desktop_dispose = desktop["dispose"]["after"]
    mobile_dispose = mobile["dispose"]["after"]
    desktop_screenshot = _screenshot_record(args.desktop)
    mobile_screenshot = _screenshot_record(args.mobile)
    three_screenshot = _screenshot_record(args.three)
    successful_request_urls = [
        url for url in request_urls if url.startswith(origin)
    ]
    sage_requests = [
        url for url in successful_request_urls
        if "sage" in url.lower()
        or "/chat" in url.lower()
        or "/agent" in url.lower()
    ]
    lock_rejections = [
        item
        for item in desktop["final"]["transport"]["previewRejections"]
        if item["code"] == "locked_placement_movement"
        and item["status"] == 422
    ]
    expected_failed_responses = [
        item
        for item in failed_responses
        if item["status"] == 422
        and item["url"] == f"{origin}/api/facility-layouts/"
        "site-a/fl-p5-authoring/preview"
    ][:len(lock_rejections)]
    unexpected_failed_responses = [
        item
        for item in failed_responses
        if item not in expected_failed_responses
    ]
    expected_console_errors: list[str] = []
    unexpected_console_errors = list(console_errors)
    for expected in expected_failed_responses:
        del expected
        match = next(
            (
                message
                for message in unexpected_console_errors
                if "server responded with a status of 422" in message
            ),
            None,
        )
        if match:
            expected_console_errors.append(match)
            unexpected_console_errors.remove(match)

    checks = {
        "actual_production_backend_preview_apply": (
            desktop["final"]["transport"]["previewCount"] >= 10
            and desktop["final"]["transport"]["applyCount"] == 1
        ),
        "workspace_loaded_without_sage": (
            desktop["initial"]["session"]["loaded"] is True
            and desktop["initial"]["dom"]["sageElements"] == 0
            and not sage_requests
        ),
        "asset_tree_uses_stable_id_payload": (
            plan_drop["payload"]["assetId"]
            == json.loads(CATALOG.read_text(encoding="ascii"))[0]["assetId"]
            and plan_drop["payload"]["assetDefinitionRevision"]
            == json.loads(CATALOG.read_text(encoding="ascii"))[0][
                "assetDefinitionRevision"
            ]
            and plan_drop["payload"]["dragSessionId"].startswith(
                "p5-browser-drag-"
            )
        ),
        "server_allocates_stable_placement_ids": (
            plan_drop["placementId"].startswith("pl-")
            and plan_drop["placementId"] in plan_drop["previewCreatedIds"]
            and plan_drop["placementIdWasClientSupplied"] is False
            and three_drop["placementId"].startswith("pl-")
            and three_drop["placementId"] in three_drop["previewCreatedIds"]
        ),
        "plan_drop_after_fit_resize_pan_zoom_exact": (
            plan_drop["actualWorld"] == plan_drop["expectedWorld"]
            and plan["projectionDelta"] > 1
            and plan["viewport"]["width"]
            != desktop["planPrepared"]["viewport"]["width"]
            and plan["fitChangedLayout"] is False
        ),
        "three_drop_after_fit_orbit_resize_exact": (
            three_drop["actualWorld"] == three_drop["expectedWorld"]
            and three["projectionDelta"] > 1
            and three["renderedFrameDelta"] > 0
            and three["canvasRect"]["width"]
            != desktop["threePrepared"]["canvasRect"]["width"]
            and three["floorRoundTripError"] < 1e-7
        ),
        "plan_ghost_is_transient_in_both_views": (
            plan_drop["ghost"]["layoutUnchanged"] is True
            and plan_drop["ghost"]["sessionGhost"] is not None
            and plan_drop["ghost"]["topGhostActive"] is True
            and plan_drop["ghost"]["threeGhostActive"] is True
            and plan_drop["ghost"]["planGhostCount"] == 1
            and plan_drop["ghost"]["overlayVisible"] is True
        ),
        "three_ghost_is_transient_in_both_views": (
            three_drop["ghost"]["layoutUnchanged"] is True
            and three_drop["ghost"]["sessionGhost"] is not None
            and three_drop["ghost"]["topGhostActive"] is True
            and three_drop["ghost"]["threeGhostActive"] is True
            and three_drop["ghost"]["planGhostCount"] == 1
            and three_drop["ghost"]["overlayVisible"] is True
        ),
        "grid_snap_applied_to_plan_and_three": (
            all(
                float(plan_drop["actualWorld"][axis]) * 2
                == round(float(plan_drop["actualWorld"][axis]) * 2)
                for axis in ("x", "z")
            )
            and all(
                float(three_drop["actualWorld"][axis]) * 2
                == round(float(three_drop["actualWorld"][axis]) * 2)
                for axis in ("x", "z")
            )
        ),
        "each_drop_is_one_undo_gesture": (
            plan_drop["historyAfter"] == plan_drop["historyBefore"] + 1
            and plan_drop["operationCount"] == 1
            and three_drop["historyAfter"] == three_drop["historyBefore"] + 1
            and three_drop["operationCount"] == 1
        ),
        "marquee_selects_two_placements": (
            authoring["marqueeSelection"]
            == ["pl-p5-auto", "pl-p5-manual"]
        ),
        "multi_move_is_one_undo_gesture": (
            move["historyAfter"] == move["historyBefore"] + 1
            and move["operationCount"] == 2
            and _position_delta(
                move["autoBefore"],
                move["autoAfter"],
            ) == {"x": 1.0, "y": 0.0, "z": 1.0}
            and _position_delta(
                move["manualBefore"],
                move["manualAfter"],
            ) == {"x": 1.0, "y": 0.0, "z": 1.0}
        ),
        "user_drag_converts_auto_to_manual": (
            move["autoPositionMode"] == "manual"
        ),
        "undo_redo_restore_exact_multi_move": (
            undo_redo["undoAuto"] == move["autoBefore"]
            and undo_redo["undoManual"] == move["manualBefore"]
            and undo_redo["redoAuto"] == move["autoAfter"]
            and undo_redo["redoManual"] == move["manualAfter"]
        ),
        "duplicate_and_delete_cover_multi_selection": (
            len(duplicate["duplicateIds"]) == 2
            and duplicate["selectionAfterDuplicate"]
            == duplicate["duplicateIds"]
            and duplicate["historyAfterDuplicate"]
            == duplicate["historyBefore"] + 1
            and duplicate["duplicateOperationCount"] == 2
            and duplicate["deleteOperationCount"] == 2
            and duplicate["duplicatesRemain"] is False
        ),
        "rotation_is_exact_quarter_turn": (
            abs(float(rotation["quaternion"]["y"]) - 2**-0.5) < 1e-9
            and abs(float(rotation["quaternion"]["w"]) - 2**-0.5) < 1e-9
        ),
        "locked_placement_never_moves": (
            locking["error"]["code"] == "locked_placement_movement"
            and len(lock_rejections) == 1
            and len(expected_failed_responses) == 1
            and locking["historyUnchanged"] is True
            and locking["placementUnchanged"] is True
            and locking["modeAfterLock"] == "locked"
            and locking["modeAfterUnlock"] == "manual"
        ),
        "invalid_floor_drop_changes_nothing": (
            desktop["invalidDrop"]["invalidProjection"] is True
            and desktop["invalidDrop"]["layoutUnchanged"] is True
            and desktop["invalidDrop"]["historyUnchanged"] is True
            and desktop["invalidDrop"]["ghostCleared"] is True
        ),
        "rectangle_zone_has_exact_dimensions": (
            zones["rectangleId"].startswith("zn-")
            and zones["rectangleOperationCount"] == 1
            and zones["rectangleDimensions"]["width"] == 8
            and zones["rectangleDimensions"]["depth"] == 5
        ),
        "polygon_zone_has_measured_dimensions": (
            zones["polygonId"].startswith("zn-")
            and len(zones["polygonBoundary"]) == 4
            and zones["polygonDimensions"]["width"] > 0
            and zones["polygonDimensions"]["depth"] > 0
        ),
        "save_is_one_atomic_apply": (
            persistence["applyCalls"] == 1
            and persistence["appliedOperationCount"]
            == persistence["operationCount"]
            and len(persistence["receiptRevision"]) == 64
        ),
        "save_reopen_preserves_exact_layout": (
            persistence["exact"] is True
            and persistence["before"]["placements"]
            == persistence["reopened"]["placements"]
            and persistence["before"]["zones"]
            == persistence["reopened"]["zones"]
            and persistence["reopened"] == saved["layout"]
        ),
        "save_reopen_clears_history": (
            persistence["savedState"] == {
                "dirty": False,
                "historyLength": 0,
            }
            and persistence["reopenedState"]["dirty"] is False
            and persistence["reopenedState"]["historyLength"] == 0
        ),
        "real_local_three_proxy_rendered": (
            any(
                group["representation"] == "proxy"
                for group in desktop["final"]["three"][
                    "representationGroups"
                ]
            )
            and desktop["canvas"]["webglReadback"][
                "changedPixelCount"
            ] >= 1000
            and desktop["canvas"]["elementScreenshot"]["nonblank"] is True
        ),
        "p6_constraint_warning_visible": (
            isinstance(desktop["final"]["dom"]["p6Warning"], str)
            and (
                desktop["final"]["dom"]["p6Warning"].startswith(
                    "Collision, containment, and clearance validation "
                    "arrives in P6."
                )
                or desktop["final"]["dom"]["p6Warning"].startswith(
                    "Browser overlap feedback is advisory. The server "
                    "validates every accepted placement."
                )
            )
            and desktop["final"]["dom"]["p6WarningVisible"] is True
            and mobile["probe"]["warningVisible"] is True
        ),
        "light_and_dark_themes_render": (
            desktop["final"]["theme"]["name"] == "light"
            and mobile["probe"]["theme"]["name"] == "dark"
            and desktop["final"]["theme"]["background"]
            != mobile["probe"]["theme"]["background"]
        ),
        "mobile_workspace_remains_visible": (
            mobile["probe"]["rootWidth"] == 390
            and mobile["probe"]["rootScrollWidth"]
            <= mobile["probe"]["rootWidth"] + 10
            and mobile["probe"]["planWidth"] >= 250
            and mobile["probe"]["assetPaneWidth"] >= 120
        ),
        "mobile_ghost_and_three_canvas_work": (
            mobile["probe"]["ghost"]["topGhostActive"] is True
            and mobile["probe"]["ghost"]["threeGhostActive"] is True
            and mobile["probe"]["pixels"]["changedPixelCount"] >= 1000
        ),
        "desktop_teardown_leaves_no_leaks": (
            desktop_dispose["firstDestroy"] is True
            and desktop_dispose["secondDestroy"] is False
            and desktop_dispose["rootChildren"] == 0
            and desktop_dispose["canvasCount"] == 0
            and desktop_dispose["activeObserverTargets"] == 0
            and desktop_dispose["activeFrames"] == 0
            and desktop_dispose["three"]["disposed"] is True
        ),
        "mobile_teardown_leaves_no_leaks": (
            mobile_dispose["firstDestroy"] is True
            and mobile_dispose["secondDestroy"] is False
            and mobile_dispose["rootChildren"] == 0
            and mobile_dispose["canvasCount"] == 0
            and mobile_dispose["activeObserverTargets"] == 0
            and mobile_dispose["activeFrames"] == 0
        ),
        "desktop_1440_by_900": (
            desktop_screenshot["width"] == 1440
            and desktop_screenshot["height"] == 900
        ),
        "mobile_390_by_844": (
            mobile_screenshot["width"] == 390
            and mobile_screenshot["height"] == 844
        ),
        "three_canvas_screenshot_nonblank": (
            three_screenshot["width"] > 500
            and three_screenshot["height"] > 400
            and all(
                span >= 40
                for span in three_screenshot["channelSpans"]
            )
        ),
        "no_external_requests": not blocked_external,
        "no_unexpected_failed_http_responses": (
            not unexpected_failed_responses
        ),
        "no_failed_requests": not failed_requests,
        "no_page_errors": (
            not page_errors
            and not desktop["final"]["workspace"]["lastError"]
            and not mobile["summary"]["workspace"]["lastError"]
            and not desktop["initial"]["workspace"]["lastError"]
        ),
        "no_unexpected_console_errors": not unexpected_console_errors,
    }
    result = {
        "schemaVersion": "facility-layout-p5-browser-evidence-v1",
        "scope": {
            "phase": "P5",
            "actualFacilityService": True,
            "actualSessionModule": True,
            "actualWorkspaceModule": True,
            "actualPlanAdapter": True,
            "actualThreeAdapter": True,
            "sageLoaded": False,
            "p6ConstraintValidationIncluded": False,
        },
        "initial": {
            "revision": created["revision"],
            "layoutRevision": layout_revision(created["layout"]),
            "placementIds": sorted(
                item["placementId"] for item in created["layout"]["placements"]
            ),
        },
        "evidence": desktop,
        "mobile": mobile,
        "finalLayout": final_layout,
        "final": {
            "revision": persistence["baseRevision"],
            "layoutRevision": layout_revision(final_layout),
            "placementCount": len(final_layout["placements"]),
            "zoneCount": len(final_layout["zones"]),
        },
        "source": _source_hashes(),
        "screenshots": {
            "desktop": desktop_screenshot,
            "mobile": mobile_screenshot,
            "three": three_screenshot,
        },
        "network": {
            "offlineOnly": True,
            "requestCount": len(successful_request_urls),
            "sageRequests": sage_requests,
            "blockedExternalRequests": sorted(set(blocked_external)),
            "failedResponses": failed_responses,
            "expectedFailedResponses": expected_failed_responses,
            "unexpectedFailedResponses": unexpected_failed_responses,
            "failedRequests": failed_requests,
        },
        "pageErrors": page_errors,
        "consoleErrors": console_errors,
        "expectedConsoleErrors": expected_console_errors,
        "unexpectedConsoleErrors": unexpected_console_errors,
        "checks": checks,
        "passed": all(checks.values()),
    }
    args.output.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}\t{name}")
    print(f"RESULT\t{args.output}")
    print(f"DESKTOP\t{args.desktop}")
    print(f"MOBILE\t{args.mobile}")
    print(f"THREE\t{args.three}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
