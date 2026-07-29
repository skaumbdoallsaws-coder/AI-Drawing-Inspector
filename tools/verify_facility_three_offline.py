#!/usr/bin/env python3
"""Verify the pinned local Three.js module and official GLTFLoader offline."""

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
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "rendering"
    / "three-offline-smoke.html"
)
DEFAULT_OUTPUT = FIXTURE.with_name("three-offline-smoke-result.json")
DEFAULT_EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
VENDOR_ROOT = ROOT / "static" / "vendor" / "three" / "0.184.0"
MANIFEST = VENDOR_ROOT / "VERSIONS.md"


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
    parser.add_argument("--edge-path", type=Path, default=DEFAULT_EDGE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    required = (
        FIXTURE,
        FIXTURE.with_name("three-offline-smoke.js"),
        VENDOR_ROOT / "build" / "three.core.min.js",
        VENDOR_ROOT / "build" / "three.module.min.js",
        VENDOR_ROOT / "examples" / "jsm" / "loaders" / "GLTFLoader.js",
        VENDOR_ROOT / "examples" / "jsm" / "utils" / "BufferGeometryUtils.js",
        VENDOR_ROOT / "examples" / "jsm" / "utils" / "SkeletonUtils.js",
        VENDOR_ROOT / "LICENSE",
        MANIFEST,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing offline dependency files: {missing}")
    if not args.edge_path.is_file():
        raise SystemExit(f"Microsoft Edge not found: {args.edge_path}")

    handler = partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    url = (
        f"{origin}/tests/fixtures/facility_layout/rendering/"
        "three-offline-smoke.html"
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
                viewport={"width": 320, "height": 240},
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
                        const value = window.facilityThreeOfflineSmoke;
                        return value && (
                            value.state === 'complete' || value.state === 'error'
                        );
                    }""",
                    timeout=30_000,
                )
            except PlaywrightTimeoutError as error:
                page_errors.append(str(error))
            smoke = page.evaluate(
                "() => window.facilityThreeOfflineSmoke || {state: 'not_started'}"
            )
            page.close()
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    checks = {
        "completed": smoke.get("state") == "complete",
        "three_revision_184": smoke.get("threeRevision") == "184",
        "official_loader_imported": smoke.get("officialLoaderImported") is True,
        "valid_glb_parsed": smoke.get("validGlbParsed") is True,
        "corrupt_glb_rejected": smoke.get("corruptGlbRejected") is True,
        "webgl2_rendered": smoke.get("webgl2Rendered") is True,
        "nonblank_pixel": smoke.get("nonblankPixel") is True,
        "render_call_recorded": int(smoke.get("renderCalls", 0)) >= 1,
        "triangles_recorded": int(smoke.get("triangles", 0)) >= 1,
        "no_external_requests": not blocked_external,
        "no_page_errors": not page_errors,
        "no_console_errors": not console_errors,
    }
    result = {
        "schemaVersion": "facility-three-offline-smoke-v1",
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
            "manifestSha256": sha256_file(MANIFEST),
            "fixtureSha256": sha256_file(FIXTURE),
            "moduleSha256": sha256_file(
                VENDOR_ROOT / "build" / "three.module.min.js"
            ),
            "loaderSha256": sha256_file(
                VENDOR_ROOT / "examples" / "jsm" / "loaders" / "GLTFLoader.js"
            ),
        },
        "smoke": smoke,
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
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
