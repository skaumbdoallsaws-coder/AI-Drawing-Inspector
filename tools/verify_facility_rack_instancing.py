#!/usr/bin/env python3
"""Exercise a real rack GLB through the pinned local Three.js instance path."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
RENDERING = ROOT / "tests" / "fixtures" / "facility_layout" / "rendering"
FIXTURE = RENDERING / "repeated-rack-instance-spike.json"
PAGE = RENDERING / "rack-instancing-smoke.html"
SCRIPT = RENDERING / "rack-instancing-smoke.js"
DEFAULT_OUTPUT = RENDERING / "rack-instancing-smoke-result.json"
DEFAULT_SCREENSHOT = RENDERING / "rack-instancing-smoke.png"
DEFAULT_EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--screenshot", type=Path, default=DEFAULT_SCREENSHOT)
    parser.add_argument("--edge-path", type=Path, default=DEFAULT_EDGE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fixture = json.loads(FIXTURE.read_text(encoding="ascii"))
    prototype_path = ROOT / fixture["prototype"]["geometryPath"]
    extraction_path = ROOT / fixture["prototype"]["extractionPath"]
    required = (FIXTURE, PAGE, SCRIPT, prototype_path, extraction_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing rack instancing inputs: {missing}")
    if not args.edge_path.is_file():
        raise SystemExit(f"Microsoft Edge not found: {args.edge_path}")
    if sha256_file(prototype_path) != fixture["prototype"]["geometrySha256"]:
        raise SystemExit("Rack prototype GLB does not match the pinned SHA-256")
    if sha256_file(extraction_path) != fixture["prototype"]["extractionSha256"]:
        raise SystemExit("Rack extraction JSON does not match the pinned SHA-256")

    handler = partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    url = (
        f"{origin}/tests/fixtures/facility_layout/rendering/"
        "rack-instancing-smoke.html"
    )
    blocked_external: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    failed_requests: list[dict[str, Any]] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    smoke: dict[str, Any] = {}
    browser_version = ""

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(args.edge_path),
                headless=True,
            )
            browser_version = browser.version
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                device_scale_factor=1,
            )

            def route_request(route: Any) -> None:
                if route.request.url.startswith(origin):
                    route.continue_()
                else:
                    blocked_external.append(route.request.url)
                    route.abort()

            context.route("**/*", route_request)
            page = context.new_page()
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
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text)
                    if message.type == "error"
                    else None
                ),
            )
            page.goto(url, wait_until="load", timeout=30_000)
            try:
                page.wait_for_function(
                    """() => {
                        const value = window.facilityRackInstancingSmoke;
                        return value && (
                            value.state === 'complete' || value.state === 'error'
                        );
                    }""",
                    timeout=120_000,
                )
            except PlaywrightTimeoutError as error:
                page_errors.append(str(error))
            smoke = page.evaluate(
                "() => window.facilityRackInstancingSmoke || "
                "{state: 'not_started'}"
            )
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.screenshot), full_page=True)
            page.close()
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    expected_meshes = fixture["prototype"]["meshCount"]
    expected_placements = len(fixture["placements"])
    checks = {
        "completed": smoke.get("state") == "complete",
        "three_revision_184": smoke.get("threeRevision") == "184",
        "official_loader_imported": smoke.get("officialLoaderImported") is True,
        "prototype_mesh_count": smoke.get("prototypeMeshCount") == expected_meshes,
        "placement_count": smoke.get("placementCount") == expected_placements,
        "one_instance_group_per_mesh": (
            smoke.get("instancedMeshCount") == expected_meshes
        ),
        "all_geometry_instances_present": (
            smoke.get("totalGeometryInstances")
            == expected_meshes * expected_placements
        ),
        "draw_calls_reduced": (
            int(smoke.get("instancedDrawCalls", 0))
            < int(smoke.get("naiveDrawCalls", 0))
        ),
        "draw_call_reduction_at_least_5x": (
            float(smoke.get("drawCallReductionRatio", 0)) >= 5
        ),
        "stable_placement_ids_unique": (
            smoke.get("uniquePlacementIds") == expected_placements
        ),
        "instance_raycast_resolves_placement": (
            smoke.get("raycastResolvedStablePlacement") is True
        ),
        "webgl2_rendered": smoke.get("webgl2Rendered") is True,
        "nonblank_scene": int(smoke.get("changedPixelCount", 0)) >= 1000,
        "no_external_requests": not blocked_external,
        "no_page_errors": not page_errors,
        "no_console_errors": not console_errors,
    }
    result = {
        "schemaVersion": "facility-rack-instancing-smoke-v1",
        "environment": {
            "os": platform.platform(),
            "python": sys.version,
            "browser": browser_version,
        },
        "network": {
            "servedOrigin": origin,
            "externalRequestsBlocked": True,
            "blockedExternalRequests": blocked_external,
            "failedResponses": failed_responses,
            "failedRequests": failed_requests,
        },
        "source": {
            "fixtureSha256": sha256_file(FIXTURE),
            "pageSha256": sha256_file(PAGE),
            "scriptSha256": sha256_file(SCRIPT),
            "prototypeSha256": sha256_file(prototype_path),
            "extractionSha256": sha256_file(extraction_path),
        },
        "smoke": smoke,
        "screenshot": {
            "path": args.screenshot.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(args.screenshot),
            "bytes": args.screenshot.stat().st_size,
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
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}\t{name}")
    print(f"RESULT\t{args.output}")
    print(f"SCREENSHOT\t{args.screenshot}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
