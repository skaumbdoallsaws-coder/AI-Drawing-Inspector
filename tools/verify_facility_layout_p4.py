#!/usr/bin/env python3
"""Produce offline browser evidence for the Facility Layout P4 renderer."""

from __future__ import annotations

import argparse
from collections import Counter
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
import threading
from typing import Any

from PIL import Image
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.validate import validate_layout


RENDERING = ROOT / "tests" / "fixtures" / "facility_layout" / "rendering"
PAGE = RENDERING / "p4-renderer.html"
SCRIPT = RENDERING / "p4-renderer.js"
LAYOUT = RENDERING / "p4-facility-layout.json"
CATALOG = RENDERING / "p4-asset-catalog.json"
DEFAULT_OUTPUT = RENDERING / "p4-renderer-result.json"
DEFAULT_DESKTOP = RENDERING / "p4-renderer-desktop.png"
DEFAULT_MOBILE = RENDERING / "p4-renderer-mobile.png"
DEFAULT_EDGE = Path(
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)
EDITOR = ROOT / "static" / "facility_layout_editor.js"
THREE_ADAPTER = ROOT / "static" / "facility_layout_three_adapter.js"
VENDOR = ROOT / "static" / "vendor" / "three" / "0.184.0"
THREE_MODULE = VENDOR / "build" / "three.module.min.js"
GLTF_LOADER = VENDOR / "examples" / "jsm" / "loaders" / "GLTFLoader.js"
ORBIT_CONTROLS = VENDOR / "examples" / "jsm" / "controls" / "OrbitControls.js"
RACK = (
    ROOT
    / "generated"
    / "industrial_assets"
    / "p0_spike"
    / "rack_prototypes"
    / "Pallet Racking_colored.glb"
)
RACK_OVERVIEW = RACK.with_name("Pallet Racking_colored_overview_proxy.glb")
EXPECTED_RACK_SHA256 = (
    "185e9914e28106b14054a8467b941eba1cf31c85593cd566ab40d608cea77c0c"
)
EXPECTED_OVERVIEW_SHA256 = (
    "eb016a7a4bd71ce21e0ffd9a318fda2f2e6d6042ced4ec009e631e8d30cc1f14"
)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_metrics(data: bytes) -> dict[str, Any]:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--desktop", type=Path, default=DEFAULT_DESKTOP)
    parser.add_argument("--mobile", type=Path, default=DEFAULT_MOBILE)
    parser.add_argument("--edge-path", type=Path, default=DEFAULT_EDGE)
    return parser.parse_args()


def _ready(page: Any) -> None:
    try:
        page.wait_for_function(
            """() => {
                const value = window.facilityP4Evidence;
                return value && (
                    value.state === 'ready' || value.state === 'error'
                );
            }""",
            timeout=120_000,
        )
    except PlaywrightTimeoutError as error:
        raise RuntimeError("P4 browser fixture did not become ready.") from error
    state = page.evaluate("() => window.facilityP4Evidence.state")
    if state != "ready":
        errors = page.evaluate(
            "() => window.facilityP4Evidence.errors || []"
        )
        raise RuntimeError(f"P4 browser fixture failed: {errors}")


def _summary(page: Any) -> dict[str, Any]:
    return page.evaluate("() => window.facilityP4Evidence.getSummary()")


def _canvas_evidence(page: Any) -> dict[str, Any]:
    browser_probe = page.evaluate(
        "() => window.facilityP4Evidence.canvasPixelProbe()"
    )
    canvas_png = page.locator("#three-view canvas").screenshot()
    return {
        "webglReadback": browser_probe,
        "elementScreenshot": png_metrics(canvas_png),
        "elementScreenshotSha256": hashlib.sha256(canvas_png).hexdigest(),
    }


def _source_hashes() -> dict[str, str]:
    return {
        "assetCatalogSha256": sha256_file(CATALOG),
        "facilityLayoutEditorSha256": sha256_file(EDITOR),
        "facilityThreeAdapterSha256": sha256_file(THREE_ADAPTER),
        "fixturePageSha256": sha256_file(PAGE),
        "fixtureScriptSha256": sha256_file(SCRIPT),
        "gltfLoaderSha256": sha256_file(GLTF_LOADER),
        "layoutFixtureSha256": sha256_file(LAYOUT),
        "orbitControlsSha256": sha256_file(ORBIT_CONTROLS),
        "rackGlbSha256": sha256_file(RACK),
        "rackOverviewSha256": sha256_file(RACK_OVERVIEW),
        "threeModuleSha256": sha256_file(THREE_MODULE),
        "verifierSha256": sha256_file(Path(__file__).resolve()),
    }


def main() -> int:
    args = parse_args()
    required = (
        PAGE,
        SCRIPT,
        LAYOUT,
        CATALOG,
        EDITOR,
        THREE_ADAPTER,
        THREE_MODULE,
        GLTF_LOADER,
        ORBIT_CONTROLS,
        RACK,
        RACK_OVERVIEW,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing P4 browser-evidence inputs: {missing}")
    if not args.edge_path.is_file():
        raise SystemExit(f"Microsoft Edge not found: {args.edge_path}")
    if sha256_file(RACK) != EXPECTED_RACK_SHA256:
        raise SystemExit("P4 rack GLB does not match the pinned SHA-256.")
    if sha256_file(RACK_OVERVIEW) != EXPECTED_OVERVIEW_SHA256:
        raise SystemExit("P4 rack overview does not match the pinned SHA-256.")

    layout = json.loads(LAYOUT.read_text(encoding="ascii"))
    catalog = json.loads(CATALOG.read_text(encoding="ascii"))
    validate_layout(layout, require_canonical=False)
    expected_ids = sorted(
        placement["placementId"] for placement in layout["placements"]
    )
    if len(expected_ids) != 6 or len(set(expected_ids)) != 6:
        raise SystemExit("P4 layout must contain six stable rack placements.")
    if len(layout["zones"]) != 1 or len(layout["routes"]) != 1:
        raise SystemExit("P4 layout must contain one zone and one route.")
    if len(catalog) != 1:
        raise SystemExit("P4 asset catalog must contain one rack definition.")

    handler = partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    url = (
        f"{origin}/tests/fixtures/facility_layout/rendering/"
        "p4-renderer.html"
    )

    blocked_external: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    failed_requests: list[dict[str, Any]] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    desktop: dict[str, Any] = {}
    mobile: dict[str, Any] = {}

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
                    if route.request.url.startswith(origin):
                        route.continue_()
                    else:
                        blocked_external.append(route.request.url)
                        route.abort()

                context.route("**/*", route_request)

            def configure_page(page: Any) -> None:
                page.on(
                    "response",
                    lambda response: (
                        failed_responses.append(
                            {"status": response.status, "url": response.url}
                        )
                        if response.status >= 400
                        else None
                    ),
                )
                page.on(
                    "requestfailed",
                    lambda request: failed_requests.append(
                        {
                            "failure": request.failure or "",
                            "url": request.url,
                        }
                    ),
                )
                page.on(
                    "pageerror",
                    lambda error: page_errors.append(str(error)),
                )
                page.on(
                    "console",
                    lambda message: (
                        console_errors.append(message.text)
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
            configure_page(desktop_page)
            desktop_page.goto(url, wait_until="load", timeout=30_000)
            _ready(desktop_page)

            initial = _summary(desktop_page)
            desktop_page.locator(
                '#plan-view [data-placement-id="pl-rack-02"]'
            ).click()
            desktop_page.wait_for_function(
                """() => (
                    window.facilityP4Evidence.getSummary()
                        .selectedPlacementId === 'pl-rack-02'
                )"""
            )
            after_plan_pick = _summary(desktop_page)

            pick_point = desktop_page.evaluate(
                """() => window.facilityP4Evidence.find3DPickPoint(
                    'pl-rack-06',
                    'pl-rack-02'
                )"""
            )
            if not pick_point:
                raise RuntimeError("No real 3D rack instance was raycastable.")
            desktop_page.mouse.click(
                float(pick_point["clientX"]),
                float(pick_point["clientY"]),
            )
            desktop_page.wait_for_function(
                """placementId => (
                    window.facilityP4Evidence.getSummary()
                        .selectedPlacementId === placementId
                )""",
                arg=pick_point["placementId"],
            )
            after_three_pick = _summary(desktop_page)
            fit_probe = desktop_page.evaluate(
                "() => window.facilityP4Evidence.runFitProbe()"
            )
            desktop_canvas = _canvas_evidence(desktop_page)
            args.desktop.parent.mkdir(parents=True, exist_ok=True)
            desktop_page.screenshot(path=str(args.desktop), full_page=True)

            context_loss = desktop_page.evaluate(
                "() => window.facilityP4Evidence.simulateContextLoss()"
            )
            desktop_page.wait_for_function(
                """() => (
                    window.facilityP4Evidence.getSummary().contextLost === true
                )"""
            )
            desktop_page.locator(
                '#plan-view [data-placement-id="pl-rack-03"]'
            ).click()
            desktop_page.wait_for_function(
                """() => (
                    window.facilityP4Evidence.getSummary()
                        .selectedPlacementId === 'pl-rack-03'
                )"""
            )
            degraded_selection = _summary(desktop_page)
            remount = desktop_page.evaluate(
                "() => window.facilityP4Evidence.runRemountProbe(20)"
            )
            final_desktop = _summary(desktop_page)

            desktop = {
                "initial": initial,
                "afterPlanPick": after_plan_pick,
                "threePickPoint": pick_point,
                "afterThreePick": after_three_pick,
                "fit": fit_probe,
                "canvas": desktop_canvas,
                "contextLoss": context_loss,
                "degradedPlanSelection": degraded_selection,
                "remount": remount,
                "final": final_desktop,
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
            configure_page(mobile_page)
            mobile_page.goto(url, wait_until="load", timeout=30_000)
            _ready(mobile_page)
            mobile_page.locator(
                '#plan-view [data-placement-id="pl-rack-04"]'
            ).click()
            mobile_page.wait_for_function(
                """() => (
                    window.facilityP4Evidence.getSummary()
                        .selectedPlacementId === 'pl-rack-04'
                )"""
            )
            mobile_page.evaluate(
                "() => window.facilityP4Evidence.runFitProbe()"
            )
            mobile_canvas = _canvas_evidence(mobile_page)
            args.mobile.parent.mkdir(parents=True, exist_ok=True)
            mobile_page.screenshot(path=str(args.mobile), full_page=True)
            mobile = {
                "summary": _summary(mobile_page),
                "canvas": mobile_canvas,
            }
            mobile_page.close()
            mobile_context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    source = _source_hashes()
    representation_groups = desktop.get("initial", {}).get(
        "representationGroups",
        [],
    )
    detail_group = representation_groups[0] if representation_groups else {}
    started_stages = [
        entry["stage"]
        for entry in desktop.get("initial", {}).get("loadTrace", [])
        if entry["status"] == "started"
    ]
    resolved_stages = [
        entry["stage"]
        for entry in desktop.get("initial", {}).get("loadTrace", [])
        if entry["status"] == "resolved"
    ]
    desktop_pixel = desktop.get("canvas", {})
    mobile_pixel = mobile.get("canvas", {})
    remount = desktop.get("remount", {})
    context_loss = desktop.get("contextLoss") or {}
    degraded = desktop.get("degradedPlanSelection", {})
    checks = {
        "authoritative_schema_v1_fixture": layout["schemaVersion"] == 1,
        "exact_six_stable_rack_placements": (
            sorted(desktop.get("initial", {}).get("planPlacementIds", []))
            == expected_ids
        ),
        "official_local_three_r184": (
            desktop.get("initial", {}).get("threeStatus") == "ready"
            and mobile.get("summary", {}).get("threeStatus") == "ready"
        ),
        "progressive_resolution_order": started_stages == [
            "manifest",
            "footprint",
            "proxy",
            "overview",
            "detail",
        ],
        "real_proxy_glb_loaded": "proxy" in resolved_stages,
        "real_detail_glb_loaded": detail_group.get("representation") == "detail",
        "six_repeated_racks_instanced": (
            detail_group.get("instanced") is True
            and detail_group.get("placementIds") == expected_ids
        ),
        "plan_pick_synchronized": (
            desktop.get("afterPlanPick", {}).get("selectedPlacementId")
            == "pl-rack-02"
            and desktop.get("afterPlanPick", {}).get("planSelection")
            == "pl-rack-02"
            and desktop.get("afterPlanPick", {}).get("threeSelection")
            == "pl-rack-02"
            and desktop.get("afterPlanPick", {}).get("propertiesSelection")
            == "pl-rack-02"
        ),
        "real_three_click_synchronized": (
            desktop.get("afterThreePick", {}).get("selectedPlacementId")
            == desktop.get("threePickPoint", {}).get("placementId")
            and desktop.get("afterThreePick", {}).get("planSelection")
            == desktop.get("threePickPoint", {}).get("placementId")
            and desktop.get("afterThreePick", {}).get("propertiesSelection")
            == desktop.get("threePickPoint", {}).get("placementId")
        ),
        "fit_changes_camera_only": all(
            desktop.get("fit", {}).get(field) is True
            for field in (
                "sourceLayoutUnchanged",
                "controllerLayoutUnchanged",
                "modelRootUnchanged",
                "adapterReportedRootUnchanged",
            )
        ),
        "desktop_webgl_canvas_nonblank": (
            desktop_pixel.get("webglReadback", {}).get(
                "changedPixelCount",
                0,
            )
            >= 1000
            and desktop_pixel.get("elementScreenshot", {}).get("nonblank")
            is True
        ),
        "mobile_webgl_canvas_nonblank": (
            mobile_pixel.get("webglReadback", {}).get(
                "changedPixelCount",
                0,
            )
            >= 1000
            and mobile_pixel.get("elementScreenshot", {}).get("nonblank")
            is True
        ),
        "context_loss_enters_degraded_mode": (
            context_loss.get("defaultPrevented") is True
            and context_loss.get("summary", {}).get("contextLost") is True
            and context_loss.get("summary", {}).get("degraded") is True
        ),
        "degraded_mode_preserves_top_plan": (
            degraded.get("selectedPlacementId") == "pl-rack-03"
            and degraded.get("planSelection") == "pl-rack-03"
            and degraded.get("planSvgCount") == 1
        ),
        "twenty_remounts_completed": remount.get("cycles") == 20,
        "remount_leaves_one_canvas": (
            remount.get("maximumCanvasCount") == 1
            and remount.get("finalCanvasCount") == 1
            and remount.get("finalPlanSvgCount") == 1
        ),
        "remount_leaves_no_observer_growth": (
            remount.get("maximumObserverTargets") == 2
            and remount.get("activeObserverTargets") == 2
        ),
        "remount_leaves_no_orphan_render_request": (
            remount.get("activeRenderRequests") == 0
            and remount.get("pendingFrame") is False
            and remount.get("idleRenderRequestsUnchanged") is True
        ),
        "desktop_1440_by_900": (
            Image.open(args.desktop).size == (1440, 900)
        ),
        "mobile_390_by_844": Image.open(args.mobile).size == (390, 844),
        "no_external_requests": not blocked_external,
        "no_failed_http_responses": not failed_responses,
        "no_failed_requests": not failed_requests,
        "no_page_errors": not page_errors,
        "no_console_errors": not console_errors,
    }
    result = {
        "schemaVersion": "facility-layout-p4-browser-evidence-v1",
        "scope": {
            "phase": "P4",
            "authoringIncluded": False,
            "placementCount": 6,
            "releaseScalePerformanceClaimed": False,
            "fiveThousandObjectPerformanceClaimed": False,
        },
        "layout": {
            "layoutId": layout["layoutId"],
            "revision": layout_revision(layout),
            "placementIds": expected_ids,
            "zoneCount": len(layout["zones"]),
            "routeCount": len(layout["routes"]),
        },
        "source": source,
        "browserEvidence": {
            "desktop": desktop,
            "mobile": mobile,
        },
        "screenshots": {
            "desktop": {
                "path": args.desktop.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(args.desktop),
                "bytes": args.desktop.stat().st_size,
                "width": 1440,
                "height": 900,
            },
            "mobile": {
                "path": args.mobile.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(args.mobile),
                "bytes": args.mobile.stat().st_size,
                "width": 390,
                "height": 844,
            },
        },
        "network": {
            "offlineOnly": True,
            "blockedExternalRequests": sorted(set(blocked_external)),
            "failedResponses": failed_responses,
            "failedRequests": failed_requests,
        },
        "pageErrors": page_errors,
        "consoleErrors": console_errors,
        "checks": checks,
        "passed": all(checks.values()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}\t{name}")
    print(f"RESULT\t{args.output}")
    print(f"DESKTOP\t{args.desktop}")
    print(f"MOBILE\t{args.mobile}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
