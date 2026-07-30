"""Capture the P11 Facility Layout viewport and theme evidence matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "release"
    / "visual"
)
VIEWPORTS = (
    (1920, 1080),
    (1440, 960),
    (1366, 768),
    (390, 844),
)
THEMES = ("light", "dark")
VISUAL_SOURCE_PATHS = (
    "static/index.html",
    "static/facility_layout_app.js",
    "static/facility_layout_editor.js",
    "static/facility_layout_session.js",
    "static/facility_layout_spatial_advisor.js",
    "static/facility_layout_spatial_worker.js",
    "static/facility_layout_three_adapter.js",
    "static/facility_layout_transport.js",
    "static/facility_layout_workspace.css",
    "static/facility_layout_workspace.js",
    "static/vendor/three/0.128.0/build/three.min.js",
    "tools/capture_facility_layout_p11_visuals.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _visual_source_binding(
    root: Path = ROOT,
    relative_paths: tuple[str, ...] = VISUAL_SOURCE_PATHS,
) -> dict[str, Any]:
    files = []
    for relative in sorted(relative_paths):
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"Visual source escapes the repository: {relative}"
            ) from exc
        if not path.is_file():
            raise FileNotFoundError(
                f"Visual source is missing: {relative}"
            )
        files.append(
            {
                "path": relative,
                "byteLength": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "algorithm": "sha256",
        "aggregateAlgorithm": "sha256-canonical-json-v1",
        "files": files,
        "aggregateSha256": hashlib.sha256(
            _canonical_json_bytes(files)
        ).hexdigest(),
    }


def _read_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _ensure_visual_fixture(app_url: str) -> dict[str, Any]:
    base = app_url.rstrip("/")
    bootstrap = _read_json(f"{base}/api/facility-layout-bootstrap")
    if not bootstrap.get("capabilities", {}).get("viewerV2"):
        raise RuntimeError("Facility Layout viewerV2 must be enabled.")
    existing_placements = (
        bootstrap["layout"]["layout"].get("placements") or []
    )
    if len(existing_placements) >= 4:
        return bootstrap

    catalog = bootstrap.get("assetCatalog", [])
    if len(catalog) < 4:
        raise RuntimeError("The visual fixture requires four catalog assets.")
    positions = (
        {"x": 6.0, "y": 0.0, "z": 6.0},
        {"x": 16.0, "y": 0.0, "z": 6.0},
        {"x": 6.0, "y": 0.0, "z": 16.0},
        {"x": 16.0, "y": 0.0, "z": 16.0},
    )
    operations = []
    start = len(existing_placements)
    for asset, position in zip(
        catalog[start:4],
        positions[start:4],
        strict=True,
    ):
        operations.append(
            {
                "op": "place_asset",
                "placement": {
                    "assetId": asset["assetId"],
                    "assetDefinitionRevision": asset[
                        "assetDefinitionRevision"
                    ],
                    "transform": {
                        "position": position,
                        "quaternion": {
                            "x": 0.0,
                            "y": 0.0,
                            "z": 0.0,
                            "w": 1.0,
                        },
                        "scale": 1.0,
                    },
                    "positionMode": "manual",
                    "snapRelationship": None,
                    "metadata": {"instanceLabel": asset["displayName"]},
                },
            }
        )
    _write_json(
        f"{base}/api/facility-layouts/site-local/fl-main",
        {
            "baseRevision": bootstrap["layout"]["revision"],
            "operations": operations,
        },
    )
    return _read_json(f"{base}/api/facility-layout-bootstrap")


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


def _image_evidence(path: Path) -> dict[str, Any]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        extrema = image.getextrema()
        histogram = image.resize((96, 96)).getcolors(96 * 96) or []
        return {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(path),
            "byteLength": path.stat().st_size,
            "width": image.width,
            "height": image.height,
            "nonblank": any(low != high for low, high in extrema),
            "sampledColorCount": len(histogram),
        }


def _capture_webgl_context_recovery(
    browser: Any,
    app_url: str,
    output_dir: Path,
) -> dict[str, Any]:
    page_errors: list[str] = []
    console_errors: list[str] = []
    context = browser.new_context(
        viewport={"width": 1440, "height": 960},
        device_scale_factor=1,
    )
    context.add_init_script(
        "localStorage.setItem('inspectorpro.theme', 'dark');"
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
    page.goto(app_url, wait_until="load", timeout=120_000)
    _open_facility(page)
    root = page.locator("#trainFacilityLayoutAuthoring")
    root.locator('[data-view="3d"]').click()
    page.wait_for_function(
        """() => (
            _trainFacilityLayoutAuthoringApp.workspace.viewMode === '3d'
            && document.querySelector(
                '#trainFacilityLayoutAuthoring #ip-flw-three-view canvas'
            )
        )""",
        timeout=120_000,
    )
    result = page.evaluate(
        """async () => {
            const app = _trainFacilityLayoutAuthoringApp;
            const adapter = app.workspace.threeAdapter;
            const canvas = document.querySelector(
                '#trainFacilityLayoutAuthoring #ip-flw-three-view canvas'
            );
            const gl = canvas && (
                canvas.getContext('webgl2')
                || canvas.getContext('webgl')
            );
            const extension = gl && gl.getExtension('WEBGL_lose_context');
            if (!adapter || !canvas || !gl || !extension) {
                return {
                    available: false,
                    reason: 'webgl_lose_context_unavailable',
                };
            }
            const waitFor = async (predicate, timeoutMs) => {
                const started = performance.now();
                while (performance.now() - started < timeoutMs) {
                    if (predicate()) return true;
                    await new Promise(resolve => setTimeout(resolve, 25));
                }
                return false;
            };
            const before = adapter.getDiagnostics();
            extension.loseContext();
            const lostObserved = await waitFor(() => {
                const value = adapter.getDiagnostics();
                return value.contextLost && value.status === 'degraded';
            }, 5000);
            await new Promise(resolve => setTimeout(resolve, 100));
            extension.restoreContext();
            const restoredObserved = await waitFor(() => {
                const value = adapter.getDiagnostics();
                return (
                    !value.contextLost
                    && value.status === 'ready'
                    && value.placementCount === before.placementCount
                );
            }, 15000);
            await app.workspace.whenIdle();
            const after = adapter.getDiagnostics();
            return {
                available: true,
                before: {
                    status: before.status,
                    contextLost: before.contextLost,
                    placementCount: before.placementCount,
                },
                lostObserved,
                restoredObserved,
                after: {
                    status: after.status,
                    contextLost: after.contextLost,
                    placementCount: after.placementCount,
                    renderedFrames:
                        after.demandRendering
                        && after.demandRendering.renderedFrames,
                },
            };
        }"""
    )
    page.wait_for_timeout(250)
    screenshot_path = output_dir / "facility-layout-webgl-restored.png"
    page.screenshot(path=str(screenshot_path), full_page=False)
    image = _image_evidence(screenshot_path)
    checks = {
        "extensionAvailable": bool(result.get("available")),
        "contextLossObserved": bool(result.get("lostObserved")),
        "contextRestored": bool(result.get("restoredObserved")),
        "sceneIdentityRestored": (
            result.get("before", {}).get("placementCount")
            == result.get("after", {}).get("placementCount")
            and int(result.get("after", {}).get("placementCount") or 0) >= 4
        ),
        "rendererReady": (
            result.get("after", {}).get("status") == "ready"
            and result.get("after", {}).get("contextLost") is False
        ),
        "nonblankScreenshot": (
            image["nonblank"] and image["sampledColorCount"] >= 8
        ),
        "noPageErrors": not page_errors,
        "noConsoleErrors": not console_errors,
    }
    context.close()
    return {
        **result,
        "screenshot": image,
        "checks": checks,
        "errors": {
            "page": page_errors,
            "console": console_errors,
        },
        "passed": all(checks.values()),
    }


def capture(
    app_url: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_binding_before = _visual_source_binding()
    bootstrap = _ensure_visual_fixture(app_url)
    records: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in VIEWPORTS:
            for theme in THEMES:
                page_errors: list[str] = []
                console_errors: list[str] = []
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                )
                context.add_init_script(
                    "localStorage.setItem('inspectorpro.theme', "
                    + json.dumps(theme)
                    + ");"
                )
                page = context.new_page()
                page.on(
                    "pageerror",
                    lambda error, target=page_errors: target.append(
                        str(error)
                    ),
                )
                page.on(
                    "console",
                    lambda message, target=console_errors: (
                        target.append(message.text)
                        if message.type == "error"
                        else None
                    ),
                )
                page.goto(app_url, wait_until="load", timeout=120_000)
                _open_facility(page)
                root = page.locator("#trainFacilityLayoutAuthoring")
                plan_tab = root.locator('[data-view="plan"]')
                if plan_tab.get_attribute("aria-selected") != "true":
                    plan_tab.click()
                page.evaluate(
                    """async () => {
                        const workspace =
                            _trainFacilityLayoutAuthoringApp.workspace;
                        await workspace.executeCommand('fit');
                        await workspace.whenIdle();
                    }"""
                )
                page.wait_for_timeout(250)

                state = page.evaluate(
                    """() => {
                        const app = _trainFacilityLayoutAuthoringApp;
                        const root = document.querySelector(
                            '#trainFacilityLayoutAuthoring'
                        );
                        const viewport = root.querySelector(
                            '.ip-flw-viewport-pane'
                        );
                        const rootRect = root.getBoundingClientRect();
                        const viewportRect = viewport.getBoundingClientRect();
                        return {
                            theme: document.documentElement.dataset.theme,
                            placementCount:
                                app.session.getState().layout.placements.length,
                            assetRows: root.querySelectorAll(
                                '.ip-flw-asset-row[data-asset-id]'
                            ).length,
                            planSvgs: root.querySelectorAll(
                                'svg[data-facility-layout-view="top-plan"]'
                            ).length,
                            rootRect: {
                                x: rootRect.x,
                                y: rootRect.y,
                                width: rootRect.width,
                                height: rootRect.height,
                            },
                            viewportRect: {
                                x: viewportRect.x,
                                y: viewportRect.y,
                                width: viewportRect.width,
                                height: viewportRect.height,
                            },
                            documentScrollWidth:
                                document.documentElement.scrollWidth,
                            documentClientWidth:
                                document.documentElement.clientWidth,
                        };
                    }"""
                )
                filename = (
                    f"facility-layout-{width}x{height}-{theme}.png"
                )
                path = output_dir / filename
                page.screenshot(path=str(path), full_page=False)
                image = _image_evidence(path)
                checks = {
                    "requestedThemeApplied": state["theme"] == theme,
                    "fixturePlacementsRendered": (
                        state["placementCount"] >= 4
                    ),
                    "assetCatalogRendered": state["assetRows"] >= 4,
                    "onePlanSurface": state["planSvgs"] == 1,
                    "workspaceVisible": (
                        state["rootRect"]["width"] > 0
                        and state["rootRect"]["height"] > 0
                        and state["viewportRect"]["width"] > 0
                        and state["viewportRect"]["height"] > 0
                    ),
                    "exactImageDimensions": (
                        image["width"] == width
                        and image["height"] == height
                    ),
                    "nonblankImage": (
                        image["nonblank"]
                        and image["sampledColorCount"] >= 8
                    ),
                    "noPageErrors": not page_errors,
                    "noConsoleErrors": not console_errors,
                }
                records.append(
                    {
                        **image,
                        "theme": theme,
                        "viewport": {"width": width, "height": height},
                        "state": state,
                        "checks": checks,
                        "passed": all(checks.values()),
                        "errors": {
                            "page": page_errors,
                            "console": console_errors,
                        },
                    }
                )
                context.close()
        webgl_context_recovery = _capture_webgl_context_recovery(
            browser,
            app_url,
            output_dir,
        )
        browser.close()

    source_binding_after = _visual_source_binding()
    source_stable = source_binding_before == source_binding_after
    result = {
        "schemaVersion": "facility-layout-p11-visual-capture-v2",
        "appUrl": app_url,
        "bootstrapRevision": bootstrap["layout"]["revision"],
        "sourceBinding": source_binding_before,
        "sourceStableDuringCapture": source_stable,
        "webglContextRecovery": webgl_context_recovery,
        "records": records,
        "passed": len(records) == len(VIEWPORTS) * len(THEMES)
        and all(record["passed"] for record in records)
        and webgl_context_recovery["passed"]
        and source_stable,
    }
    result_path = output_dir / "p11-visual-capture.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--app-url",
        default=os.getenv(
            "P11_FACILITY_LAYOUT_APP_URL",
            "http://127.0.0.1:8044/",
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    args = parser.parse_args()
    result = capture(args.app_url, args.output_dir.resolve())
    for record in result["records"]:
        viewport = record["viewport"]
        print(
            ("PASS" if record["passed"] else "FAIL")
            + "\t"
            + f"{viewport['width']}x{viewport['height']}"
            + "\t"
            + record["theme"]
        )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
